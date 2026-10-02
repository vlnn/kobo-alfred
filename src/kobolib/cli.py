from __future__ import annotations

import argparse
import subprocess
from argparse import Namespace
from collections.abc import Callable
from functools import wraps
from pathlib import Path

from kobolib import alfred
from kobolib.apply import apply, undo
from kobolib.commands import (
    all_stats_items,
    classify_items,
    dups_items,
    genre_edits,
    inbox_items,
    lint_items,
    plan_items,
    random_items,
    search_items,
    sources_items,
    tag_edits,
    without_index_items,
)
from kobolib.config import covers_dir, db_path, journal_path, library_root, plan_path, selected_book, sources, tag_store
from kobolib.index import Index, add_book, fill_thumbnails, index_busy
from kobolib.library import (
    apply_edits,
    apply_summary,
    current_plan,
    findings,
    import_blocked,
    inbox_folder,
    ops_for_one,
    plan_is_stale,
    refresh_index,
    rehome,
    row_by_reference,
    run_index,
    run_index_sources,
    sets_genre,
    tag_summary,
    text_report,
    transfer,
)
from kobolib.model import Tag
from kobolib.plan import read_plan, write_plan

NOTIFY_SCRIPT = ("on run argv", 'display notification (item 1 of argv) with title "Kobo Library"', "end run")


def notify(message: str) -> None:
    lines = [arg for line in NOTIFY_SCRIPT for arg in ("-e", line)]
    subprocess.run(["osascript", *lines, "--", message], capture_output=True, check=False)


def report(message: str, should_notify: bool) -> None:
    print(message, flush=True)
    if should_notify:
        notify(message)


def cmd_index(args) -> int:
    code, message = run_index()
    report(message, args.notify)
    if code != 0:
        return code
    if sources():
        report(run_index_sources()[1], args.notify)
    if not args.no_thumbnails:
        report(f"Generated {fill_thumbnails(db_path(), covers_dir())} PDF covers", args.notify)
    return 0


def cmd_search(args) -> int:
    print(alfred.render(search_items(args.query)))
    return 0


def cmd_dups(args) -> int:
    print(alfred.render(dups_items()))
    return 0


def cmd_random(args) -> int:
    print(alfred.render(random_items(args.query)))
    return 0


def without_index() -> int:
    print(alfred.render(without_index_items()))
    return 0


def requires_index(command: Callable[[Namespace], int]) -> Callable[[Namespace], int]:
    @wraps(command)
    def guarded(args: Namespace) -> int:
        return command(args) if db_path().exists() else without_index()

    return guarded


@requires_index
def cmd_inbox(args) -> int:
    print(alfred.render(inbox_items(args.query)))
    return 0


@requires_index
def cmd_classify(args) -> int:
    print(alfred.render(classify_items(args.query)))
    return 0


@requires_index
def cmd_lint(args) -> int:
    if args.text:
        print(text_report(findings()))
        return 0
    print(alfred.render(lint_items()))
    return 0


@requires_index
def cmd_plan(args) -> int:
    ops = current_plan()
    write_plan(ops, plan_path())
    if args.text:
        print(plan_path().read_text(encoding="utf-8"), end="")
        return 0
    print(alfred.render(plan_items(ops)))
    return 0


def refuse(message: str, should_notify: bool) -> int:
    report(message, should_notify)
    return 1


def not_writable() -> str:
    if not db_path().exists():
        return "No index yet: run kb:index"
    if index_busy(db_path()):
        return "Indexing is running, try again later"
    return ""


def finish_with_reindex(message: str, should_notify: bool) -> int:
    code, index_message = run_index()
    report(f"{message} · {index_message}", should_notify)
    return code


def cmd_apply(args) -> int:
    if reason := not_writable():
        return refuse(reason, args.notify)
    if not args.only and not plan_path().exists():
        return refuse("No plan: run kb:plan first", args.notify)
    if not args.only and plan_is_stale():
        return refuse("Plan is stale (index changed since): run kb:plan again", args.notify)
    if args.only:
        return apply_one(args.only, args.notify)
    result = apply(read_plan(plan_path()), library_root(), journal_path())
    plan_path().unlink(missing_ok=True)
    return finish_with_reindex(apply_summary(result), args.notify)


def apply_one(path: str, should_notify: bool) -> int:
    result = apply(ops_for_one(path), library_root(), journal_path())
    plan_path().unlink(missing_ok=True)
    refresh_index(result)
    report(apply_summary(result), should_notify)
    return 0


def cmd_undo(args) -> int:
    if index_busy(db_path()):
        return refuse("Indexing is running, try again later", args.notify)
    undone = undo(library_root(), journal_path())
    plan_path().unlink(missing_ok=True)
    return finish_with_reindex(f"Undid {undone}", args.notify)


def cmd_tag(args) -> int:
    index, store = Index(db_path()), tag_store()
    row = row_by_reference(args.book, index)
    if row is None:
        print(f"Not indexed: {args.book}")
        return 1
    tag = apply_edits(store.get(row.fingerprint) or Tag(rel_path=row.rel_path), args.edits)
    store.set(row.fingerprint, tag)
    store.save()
    index.write_tag(row.fingerprint, store.get(row.fingerprint))
    summary = tag_summary(row.title, tag)
    if not sets_genre(args.edits):
        print(summary)
        return 0
    report(f"{summary} · {rehome(row, index, store)}", args.notify)
    return 0


def cmd_fix(args) -> int:
    book = selected_book()
    index, store = Index(db_path()), tag_store()
    row = index.by_fingerprint(book) if book else None
    if row is None:
        print(alfred.render([alfred.message_item("No book selected", "Start from kb and press ⇧↩ on a book")]))
        return 0
    tag = store.get(book) or Tag()
    query = args.query.strip().lower()
    items = [alfred.fix_header(row, tag.genre, tag.tags), *tag_edits(query, tag.tags, book)]
    if not query.startswith(("+", "-")):
        items += genre_edits(query, index, store, book)
    print(alfred.render(items))
    return 0


def cmd_genres(args) -> int:
    book = selected_book()
    if not book:
        print(alfred.render([alfred.message_item("No book selected", "Start from kb:classify")]))
        return 0
    print(alfred.render(genre_edits(args.query.strip().lower(), Index(db_path()), tag_store(), book)))
    return 0


def cmd_index_sources(args) -> int:
    code, message = run_index_sources()
    report(message, args.notify)
    return code


def cmd_sources(args) -> int:
    print(alfred.render(sources_items(args.query)))
    return 0


def cmd_import(args) -> int:
    if reason := not_writable():
        return refuse(reason, args.notify)
    src, dst = Path(args.book), inbox_folder() / Path(args.book).name
    if reason := import_blocked(src, dst):
        return refuse(f"Not imported: {reason}", args.notify)
    transfer(src, dst, args.move)
    book = add_book(db_path(), dst, library_root(), covers_dir())
    report(f"Imported {book.title} → {Path(book.rel_path).parent}/", args.notify)
    return 0


def cmd_stats(args) -> int:
    print(alfred.render(all_stats_items()))
    return 0


def flag(name: str) -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(name, action="store_true")
    return parent


def query_argument() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("query", nargs="?", default="")
    return parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kobolib")
    sub = parser.add_subparsers(dest="command", required=True)
    notify, text, query = flag("--notify"), flag("--text"), query_argument()
    sub.add_parser("index", parents=[notify, flag("--no-thumbnails")]).set_defaults(func=cmd_index)
    sub.add_parser("index-sources", parents=[notify]).set_defaults(func=cmd_index_sources)
    sub.add_parser("search", parents=[query]).set_defaults(func=cmd_search)
    sub.add_parser("random", parents=[query]).set_defaults(func=cmd_random)
    sub.add_parser("inbox", parents=[query]).set_defaults(func=cmd_inbox)
    sub.add_parser("classify", parents=[query]).set_defaults(func=cmd_classify)
    sub.add_parser("sources", parents=[query]).set_defaults(func=cmd_sources)
    sub.add_parser("fix", parents=[query]).set_defaults(func=cmd_fix)
    sub.add_parser("genres", parents=[query]).set_defaults(func=cmd_genres)
    sub.add_parser("dups").set_defaults(func=cmd_dups)
    sub.add_parser("stats").set_defaults(func=cmd_stats)
    sub.add_parser("lint", parents=[text]).set_defaults(func=cmd_lint)
    sub.add_parser("plan", parents=[text]).set_defaults(func=cmd_plan)
    sub.add_parser("undo", parents=[notify]).set_defaults(func=cmd_undo)
    apply_cmd = sub.add_parser("apply", parents=[notify])
    apply_cmd.add_argument("--only")
    apply_cmd.set_defaults(func=cmd_apply)
    tag_cmd = sub.add_parser("tag", parents=[notify])
    tag_cmd.add_argument("book")
    tag_cmd.add_argument("edits", nargs=argparse.REMAINDER)
    tag_cmd.set_defaults(func=cmd_tag)
    import_cmd = sub.add_parser("import", parents=[notify, flag("--move")])
    import_cmd.add_argument("book")
    import_cmd.set_defaults(func=cmd_import)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
