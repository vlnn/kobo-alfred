from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
from pathlib import Path

from kobolib import alfred
from kobolib.apply import apply, undo
from kobolib.index import Index, IndexBusy, build_index, fill_thumbnails, index_busy
from kobolib.lint import lint
from kobolib.plan import plan, read_plan, write_plan
from kobolib.scan import relative_path
from kobolib.query import parse_query
from kobolib.scan import probe_root
from kobolib.tags import TagStore


def library_root() -> Path:
    return Path(os.environ.get("KOBO_ROOT", "/Volumes/Transcend/kobo")).expanduser()


def data_dir() -> Path:
    default = Path.home() / "Library" / "Application Support" / "kobolib"
    chosen = os.environ.get("KOBO_DATA") or os.environ.get("alfred_workflow_data") or str(default)
    return Path(chosen).expanduser()


def db_path() -> Path:
    return data_dir() / "library.db"


def covers_dir() -> Path:
    return data_dir() / "covers"


def plan_path() -> Path:
    return data_dir() / "plan.tsv"


def journal_path() -> Path:
    return data_dir() / "journal.jsonl"


def tag_store() -> TagStore:
    return TagStore(data_dir() / "tags.tsv").load()


def all_rows(index: Index) -> list:
    return index.search(parse_query(""), limit=100_000)


def bootstrap_tags() -> int:
    store = tag_store()
    added = store.bootstrap(all_rows(Index(db_path())))
    store.save()
    return added


def notify(message: str) -> None:
    script = f'display notification "{message}" with title "Kobo Library"'
    subprocess.run(["osascript", "-e", script], capture_output=True, check=False)


def run_index() -> tuple[int, str]:
    root = library_root()
    if not root.exists():
        return 1, f"Library root not mounted: {root}"
    try:
        count = build_index(root, db_path(), covers_dir(), thumbnails=False, exclude=(data_dir(),))
    except IndexBusy:
        return 1, "Indexing is already running"
    if count == 0:
        return 1, f"No books found: {probe_root(root) or f'no ebook files under {root}'}"
    bootstrap_tags()
    return 0, f"Indexed {count} books from {root}"


def report(message: str, should_notify: bool) -> None:
    print(message, flush=True)
    if should_notify:
        notify(message)


def cmd_index(args) -> int:
    code, message = run_index()
    report(message, args.notify)
    if code != 0 or args.no_thumbnails:
        return code
    made = fill_thumbnails(db_path(), covers_dir())
    report(f"Generated {made} PDF covers", args.notify)
    return 0


def search_items(raw: str) -> list[dict]:
    index = Index(db_path())
    rows = index.search(parse_query(raw))
    if not rows and index.count() == 0:
        return [alfred.message_item("Index is empty", "Run kb:index with the library mounted; check Alfred's Removable Volumes permission")]
    return [alfred.book_item(r) for r in rows] or [alfred.empty_item(raw)]


def cmd_search(args) -> int:
    print(f"kobolib search query={args.query!r} db={db_path()} root={library_root()}", file=sys.stderr)
    if not db_path().exists():
        return without_index()
    print(alfred.render(search_items(args.query)))
    return 0


def cmd_dups(args) -> int:
    groups = Index(db_path()).duplicates()
    items = [alfred.duplicate_item(g) for g in groups] or [alfred.message_item("No duplicate titles")]
    print(alfred.render(items))
    return 0


def cmd_random(args) -> int:
    rows = Index(db_path()).search(parse_query(args.query + " is:complete"), limit=5000)
    picks = random.sample(rows, min(5, len(rows)))
    print(alfred.render([alfred.book_item(r) for r in picks] or [alfred.empty_item(args.query)]))
    return 0


def without_index() -> int:
    print(alfred.render([alfred.message_item("No index yet", "Run kb:index to build it")]))
    return 0


def cmd_inbox(args) -> int:
    if not db_path().exists():
        return without_index()
    store = tag_store()
    rows = sorted((r for r in all_rows(Index(db_path())) if not store.genre_of(r)), key=lambda r: r.mtime)
    items = [alfred.inbox_item(r, "") for r in rows] or [alfred.message_item("Inbox is empty", "Every book has a genre")]
    print(alfred.render(items))
    return 0


def text_report(findings) -> str:
    return "\n".join(f"{f.rule}\t{f.detail}\t{' | '.join(f.rel_paths)}" for f in findings)


def cmd_lint(args) -> int:
    if not db_path().exists():
        return without_index()
    findings = lint(all_rows(Index(db_path())), tag_store(), library_root(), exclude=(data_dir(),))
    if args.text:
        print(text_report(findings))
        return 0
    items = [alfred.finding_item(f, str(library_root())) for f in findings] or [alfred.message_item("Nothing to fix", "The library is clean")]
    print(alfred.render(items))
    return 0


def cmd_plan(args) -> int:
    if not db_path().exists():
        return without_index()
    rows, store = all_rows(Index(db_path())), tag_store()
    ops = plan(rows, lint(rows, store, library_root(), exclude=(data_dir(),)), store)
    write_plan(ops, plan_path())
    if args.text:
        print(plan_path().read_text(encoding="utf-8"), end="")
        return 0
    items = [alfred.plan_item(o, str(library_root())) for o in ops] or [alfred.message_item("Nothing to do", "Every classified book is where it belongs")]
    print(alfred.render(items))
    return 0


def current_plan():
    rows, store = all_rows(Index(db_path())), tag_store()
    return plan(rows, lint(rows, store, library_root(), exclude=(data_dir(),)), store)


def plan_is_stale() -> bool:
    return plan_path().stat().st_mtime < db_path().stat().st_mtime


def ops_for(only: str | None):
    if only:
        rel = relative_path(Path(only), library_root())
        return [o for o in current_plan() if o.src == rel]
    if not plan_path().exists():
        return None
    return None if plan_is_stale() else read_plan(plan_path())


def refuse(message: str, should_notify: bool) -> int:
    report(message, should_notify)
    return 1


def finish_with_reindex(message: str, should_notify: bool) -> int:
    code, index_message = run_index()
    report(f"{message} · {index_message}", should_notify)
    return code


def cmd_apply(args) -> int:
    if not db_path().exists():
        return refuse("No index yet: run kb:index", args.notify)
    if index_busy(db_path()):
        return refuse("Indexing is running, try again later", args.notify)
    if not args.only and not plan_path().exists():
        return refuse("No plan: run kb:plan first", args.notify)
    if not args.only and plan_is_stale():
        return refuse("Plan is stale (index changed since): run kb:plan again", args.notify)
    result = apply(ops_for(args.only), library_root(), journal_path())
    plan_path().unlink(missing_ok=True)
    summary = f"Applied {result.done}" + (f", skipped {len(result.skipped)}" if result.skipped else "")
    return finish_with_reindex(summary, args.notify)


def cmd_undo(args) -> int:
    if index_busy(db_path()):
        return refuse("Indexing is running, try again later", args.notify)
    undone = undo(library_root(), journal_path())
    plan_path().unlink(missing_ok=True)
    return finish_with_reindex(f"Undid {undone}", args.notify)


def cmd_stats(args) -> int:
    index = Index(db_path())
    partial = len(index.search(parse_query("is:partial"), limit=5000))
    print(alfred.render([
        alfred.message_item(f"{index.count()} books indexed", str(library_root())),
        alfred.message_item(f"{partial} incomplete downloads", "kb is:partial"),
        alfred.message_item(f"{len(index.duplicates())} duplicate titles", "kb:dups"),
    ]))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kobolib")
    sub = parser.add_subparsers(dest="command", required=True)
    index = sub.add_parser("index")
    index.add_argument("--notify", action="store_true")
    index.add_argument("--no-thumbnails", action="store_true")
    index.set_defaults(func=cmd_index)
    search = sub.add_parser("search")
    search.add_argument("query", nargs="?", default="")
    search.set_defaults(func=cmd_search)
    sub.add_parser("dups").set_defaults(func=cmd_dups)
    rnd = sub.add_parser("random")
    rnd.add_argument("query", nargs="?", default="")
    rnd.set_defaults(func=cmd_random)
    sub.add_parser("stats").set_defaults(func=cmd_stats)
    sub.add_parser("inbox").set_defaults(func=cmd_inbox)
    lint_cmd = sub.add_parser("lint")
    lint_cmd.add_argument("--text", action="store_true")
    lint_cmd.set_defaults(func=cmd_lint)
    plan_cmd = sub.add_parser("plan")
    plan_cmd.add_argument("--text", action="store_true")
    plan_cmd.set_defaults(func=cmd_plan)
    apply_cmd = sub.add_parser("apply")
    apply_cmd.add_argument("--only")
    apply_cmd.add_argument("--notify", action="store_true")
    apply_cmd.set_defaults(func=cmd_apply)
    undo_cmd = sub.add_parser("undo")
    undo_cmd.add_argument("--notify", action="store_true")
    undo_cmd.set_defaults(func=cmd_undo)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
