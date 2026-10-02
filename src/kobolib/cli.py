from __future__ import annotations

import argparse
import os
import random
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from kobolib import alfred
from kobolib.apply import Applied, apply, undo
from kobolib.index import Index, IndexBusy, Row, add_book, build_index, build_sources_index, fill_thumbnails, index_busy
from kobolib.lint import lint
from kobolib.plan import Operation, plan, read_plan, relocation, write_plan
from kobolib.query import parse_query
from kobolib.scan import fingerprint, probe_root, relative_path
from kobolib.tags import Tag, TagStore, folder_slug, genre_from_folder


def library_root() -> Path:
    return Path(os.environ.get("KOBO_ROOT", "/Volumes/Transcend/kobo")).expanduser()


def sources() -> list[Path]:
    raw = os.environ.get("KOBO_SOURCES", "")
    return [Path(p).expanduser() for p in raw.replace("\n", os.pathsep).split(os.pathsep) if p.strip()]


def data_dir() -> Path:
    default = Path.home() / "Library" / "Application Support" / "kobolib"
    chosen = os.environ.get("KOBO_DATA") or os.environ.get("alfred_workflow_data") or str(default)
    return Path(chosen).expanduser()


def db_path() -> Path:
    return data_dir() / "library.db"


def sources_db_path() -> Path:
    return data_dir() / "sources.db"


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
    store, index = tag_store(), Index(db_path())
    added = store.bootstrap(all_rows(index))
    store.save()
    index.write_tags(store)
    return added


def row_by_reference(reference: str, index: Index) -> Row | None:
    if reference.startswith("/"):
        return index.by_rel_path(relative_path(Path(reference), library_root()))
    return index.by_fingerprint(reference)


def apply_edits(tag: Tag, edits: list[str]) -> Tag:
    for edit in edits:
        if edit.startswith("genre="):
            tag.genre = edit.removeprefix("genre=").strip().lower()
        elif edit.startswith("+"):
            tag.tags = [*tag.tags, edit[1:]]
        elif edit.startswith("-"):
            tag.tags = [t for t in tag.tags if t != edit[1:].lower()]
    return tag


def known_genres(index: Index, store: TagStore) -> list[str]:
    from_tags = {t.genre for t in store.entries.values() if t.genre}
    from_folders = {g for f in index.folders() if (g := genre_from_folder(f))}
    return sorted(from_tags | from_folders | set(index.genres()))


NOTIFY_SCRIPT = ("on run argv", 'display notification (item 1 of argv) with title "Kobo Library"', "end run")


def notify(message: str) -> None:
    lines = [arg for line in NOTIFY_SCRIPT for arg in ("-e", line)]
    subprocess.run(["osascript", *lines, "--", message], capture_output=True, check=False)


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
    if code != 0:
        return code
    if sources():
        report(run_index_sources()[1], args.notify)
    if not args.no_thumbnails:
        report(f"Generated {fill_thumbnails(db_path(), covers_dir())} PDF covers", args.notify)
    return 0


def book_items(raw: str) -> list[dict]:
    if not db_path().exists():
        return without_index_items()
    index = Index(db_path())
    rows = index.search(parse_query(raw))
    if not rows and index.count() == 0:
        return [alfred.message_item("Index is empty", "Run kb:index with the library mounted; check Alfred's Removable Volumes permission")]
    return [alfred.book_item(r) for r in rows] or [alfred.empty_item(raw)]


def split_command(raw: str) -> tuple[str, str]:
    word, _, rest = raw.strip().partition(" ")
    return (word.lower(), rest.strip()) if word.lower() in COMMANDS else ("", raw)


def search_items(raw: str) -> list[dict]:
    command, rest = split_command(raw)
    if not command:
        return suggestions(raw) + book_items(raw)
    books = [b for b in book_items(raw) if b.get("valid") is not False]
    return command_items(command, rest) + books


def with_action(item: dict, action: str) -> dict:
    return {**item, "variables": {**item.get("variables", {}), "action": action}}


def command_items(command: str, rest: str) -> list[dict]:
    chosen = COMMANDS[command]
    if chosen.needs_index and not db_path().exists():
        return without_index_items()
    return [with_action(i, chosen.action) for i in chosen.items(rest)]


def completes(word: str, command: Command) -> str:
    return next((name for name in command.names if name.startswith(word)), "")


def suggestions(raw: str) -> list[dict]:
    word = raw.strip().lower()
    if len(word) < MIN_SUGGESTION_PREFIX or " " in word or word in COMMANDS:
        return []
    completions = sorted((name, command) for command in COMMAND_LIST if (name := completes(word, command)))
    return [alfred.suggestion_item(name, command.help) for name, command in completions]


def action_item(title: str, subtitle: str) -> dict:
    return {"title": title, "subtitle": subtitle, "arg": "", "valid": True}


def cmd_search(args) -> int:
    print(alfred.render(search_items(args.query)))
    return 0


def dups_items(query: str = "") -> list[dict]:
    groups = Index(db_path()).duplicates()
    return [alfred.duplicate_item(g) for g in groups] or [alfred.message_item("No duplicate titles")]


def cmd_dups(args) -> int:
    print(alfred.render(dups_items()))
    return 0


def random_items(query: str) -> list[dict]:
    rows = Index(db_path()).search(parse_query(query + " is:complete"), limit=5000)
    picks = random.sample(rows, min(5, len(rows)))
    return [alfred.book_item(r) for r in picks] or [alfred.empty_item(query)]


def cmd_random(args) -> int:
    print(alfred.render(random_items(args.query)))
    return 0


def without_index_items() -> list[dict]:
    return [alfred.message_item("No index yet", "Run kb:index to build it")]


def without_index() -> int:
    print(alfred.render(without_index_items()))
    return 0


def unclassified_rows(query: str = "") -> list[Row]:
    return Index(db_path()).unclassified(query)


def inbox_items(query: str) -> list[dict]:
    return [alfred.inbox_item(r, "") for r in unclassified_rows(query)] or [alfred.message_item("Inbox is empty", "Every book has a genre")]


def cmd_inbox(args) -> int:
    if not db_path().exists():
        return without_index()
    print(alfred.render(inbox_items(args.query)))
    return 0


def classify_items(query: str) -> list[dict]:
    return [alfred.classify_item(r, "") for r in unclassified_rows(query)] or [
        alfred.message_item("Nothing to classify", "Every book has a genre")
    ]


def cmd_classify(args) -> int:
    if not db_path().exists():
        return without_index()
    print(alfred.render(classify_items(args.query)))
    return 0


def text_report(findings) -> str:
    return "\n".join(f"{f.rule}\t{f.detail}\t{' | '.join(f.rel_paths)}" for f in findings)


def cmd_lint(args) -> int:
    if not db_path().exists():
        return without_index()
    if args.text:
        print(text_report(findings()))
        return 0
    print(alfred.render(lint_items()))
    return 0


def findings() -> list:
    return lint(all_rows(Index(db_path())), tag_store(), library_root(), exclude=(data_dir(),))


def lint_items(query: str = "") -> list[dict]:
    return [alfred.finding_item(f, str(library_root())) for f in findings()] or [
        alfred.message_item("Nothing to fix", "The library is clean")
    ]


def cmd_plan(args) -> int:
    if not db_path().exists():
        return without_index()
    ops = current_plan()
    write_plan(ops, plan_path())
    if args.text:
        print(plan_path().read_text(encoding="utf-8"), end="")
        return 0
    print(alfred.render(plan_items(ops)))
    return 0


def written_plan_items(query: str = "") -> list[dict]:
    ops = current_plan()
    write_plan(ops, plan_path())
    return plan_items(ops)


def plan_items(ops) -> list[dict]:
    if not ops:
        return [alfred.message_item("Nothing to do", "Every classified book is where it belongs")]
    return [alfred.apply_all_item(len(ops)), *(alfred.plan_item(o, str(library_root())) for o in ops)]


def current_plan():
    rows, store = all_rows(Index(db_path())), tag_store()
    return plan(rows, lint(rows, store, library_root(), exclude=(data_dir(),)), store)


def plan_is_stale() -> bool:
    return plan_path().stat().st_mtime < db_path().stat().st_mtime


def fresh_plan() -> list[Operation]:
    if not plan_path().exists() or plan_is_stale():
        return []
    return read_plan(plan_path())


def ops_for_one(path: str) -> list[Operation]:
    rel = relative_path(Path(path), library_root())
    if planned := [o for o in fresh_plan() if o.src == rel]:
        return planned
    index = Index(db_path())
    row = index.by_rel_path(rel)
    op = relocation(row, all_rows(index), tag_store()) if row else None
    return [op] if op else []


def refuse(message: str, should_notify: bool) -> int:
    report(message, should_notify)
    return 1


def finish_with_reindex(message: str, should_notify: bool) -> int:
    code, index_message = run_index()
    report(f"{message} · {index_message}", should_notify)
    return code


def refresh_index(result: Applied) -> None:
    index = Index(db_path())
    for src, dst in result.moved.items():
        index.relocate(src, dst, library_root())
    for src in result.removed:
        index.remove(src)


def cmd_apply(args) -> int:
    if not db_path().exists():
        return refuse("No index yet: run kb:index", args.notify)
    if index_busy(db_path()):
        return refuse("Indexing is running, try again later", args.notify)
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


def skip_reasons(skipped: list[str]) -> str:
    reasons = sorted({s.rpartition(": ")[2] for s in skipped})
    return ", ".join(reasons)


def apply_summary(result) -> str:
    if not result.skipped:
        return f"Applied {result.done}"
    return f"Applied {result.done}, skipped {len(result.skipped)} ({skip_reasons(result.skipped)})"


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


def sets_genre(edits: list[str]) -> bool:
    return any(e.startswith("genre=") for e in edits)


def tag_summary(title: str, tag: Tag) -> str:
    return f"{title} → {tag.genre or 'no genre'}" + (f" · {', '.join(tag.tags)}" if tag.tags else "")


def rehome(row: Row, index: Index, store: TagStore) -> str:
    op = relocation(row, all_rows(index), store)
    if op is None or op.kind != "move":
        return "stays put (no author or already home)"
    result = apply([op], library_root(), journal_path())
    plan_path().unlink(missing_ok=True)
    refresh_index(result)
    if result.skipped:
        return f"not moved: {skip_reasons(result.skipped)}"
    return f"moved → {Path(op.dst).parent}/"


def selected_book() -> str:
    return os.environ.get("book", "")


def genre_edits(query: str, index: Index, store: TagStore, book: str) -> list[dict]:
    genres = [g for g in known_genres(index, store) if g.startswith(query)]
    items = [alfred.edit_item(f"genre={g}", g, book, uid=f"genre:{g}") for g in genres]
    if query and not genres:
        items.append(alfred.edit_item(f"genre={query}", f"New genre: {query}", book))
    return items


def tag_edits(query: str, current: list[str], book: str) -> list[dict]:
    if query.startswith("+") and len(query) > 1:
        return [alfred.edit_item(query, f"Add tag: {query[1:]}", book)]
    if query.startswith("-") and len(query) > 1:
        return [alfred.edit_item(query, f"Remove tag: {query[1:]}", book)]
    return [alfred.edit_item(f"-{t}", f"Remove tag: {t}", book) for t in current if not query]


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


def mounted_sources() -> tuple[list[Path], list[Path]]:
    found, missing = [], []
    for source in sources():
        (found if source.is_dir() else missing).append(source)
    return found, missing


def run_index_sources() -> tuple[int, str]:
    if not sources():
        return 1, "No sources configured: set KOBO_SOURCES (paths separated by ':')"
    found, missing = mounted_sources()
    if not found:
        return 1, f"No source is mounted: {', '.join(map(str, missing))}"
    try:
        count = build_sources_index(found, sources_db_path(), covers_dir(), thumbnails=False, exclude=(data_dir(),))
    except IndexBusy:
        return 1, "Indexing is already running"
    skipped = f", skipped {len(missing)} unmounted" if missing else ""
    return 0, f"Indexed {count} books from {len(found)} sources{skipped}"


def cmd_index_sources(args) -> int:
    code, message = run_index_sources()
    report(message, args.notify)
    return code


def not_in_library(rows: list[Row]) -> list[Row]:
    copies = Index(db_path()).fingerprints_among([r.fingerprint for r in rows]) if db_path().exists() else set()
    return [r for r in rows if r.fingerprint not in copies]


def source_items(raw: str) -> list[dict]:
    rows = not_in_library(Index(sources_db_path()).search(parse_query(raw)))
    return [alfred.source_item(r, None) for r in rows] or [alfred.empty_item(raw)]


def sources_items(query: str) -> list[dict]:
    if not sources_db_path().exists():
        return [alfred.message_item("No sources index yet", "Set KOBO_SOURCES, then run kb:index")]
    return source_items(query)


def cmd_sources(args) -> int:
    print(alfred.render(sources_items(args.query)))
    return 0


def inbox_folder() -> Path:
    root = library_root()
    existing = next((p for p in sorted(root.iterdir()) if p.is_dir() and folder_slug(p.name) == "inbox"), None)
    return existing or root / "_inbox"


def import_blocked(src: Path, dst: Path) -> str:
    if not src.is_file():
        return f"source missing: {src}"
    if dst.exists():
        return f"destination exists: {relative_path(dst, library_root())}"
    if (copy := Index(db_path()).by_fingerprint(fingerprint(src))) is not None:
        return f"already in library: {copy.rel_path}"
    return ""


def transfer(src: Path, dst: Path, move: bool) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if move:
        shutil.move(src, dst)
    else:
        shutil.copy2(src, dst)


def cmd_import(args) -> int:
    if not db_path().exists():
        return refuse("No index yet: run kb:index", args.notify)
    if index_busy(db_path()):
        return refuse("Indexing is running, try again later", args.notify)
    src, dst = Path(args.book), inbox_folder() / Path(args.book).name
    if reason := import_blocked(src, dst):
        return refuse(f"Not imported: {reason}", args.notify)
    transfer(src, dst, args.move)
    book = add_book(db_path(), dst, library_root(), covers_dir())
    report(f"Imported {book.title} → {Path(book.rel_path).parent}/", args.notify)
    return 0


def stats_items() -> list[dict]:
    index = Index(db_path())
    partial = len(index.search(parse_query("is:partial"), limit=5000))
    return [
        alfred.message_item(f"{index.count()} books indexed", str(library_root())),
        alfred.message_item(f"{partial} incomplete downloads", "kb is:partial"),
        alfred.message_item(f"{len(index.duplicates())} duplicate titles", "kb:dups"),
    ]


def sources_stats_items() -> list[dict]:
    if not sources_db_path().exists():
        return []
    return [alfred.message_item(f"{Index(sources_db_path()).count()} books in {len(sources())} sources", "kb:src")]


def all_stats_items(query: str = "") -> list[dict]:
    return stats_items() + sources_stats_items()


def cmd_stats(args) -> int:
    print(alfred.render(all_stats_items()))
    return 0


@dataclass(frozen=True)
class Command:
    name: str
    items: Callable[[str], list[dict]]
    action: str
    help: str
    aliases: tuple[str, ...] = ()
    needs_index: bool = True

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


def index_items(query: str) -> list[dict]:
    return [action_item("Rebuild the index", "Library and sources: reads every book, extracts covers · same as kb:index")]


def apply_items(query: str) -> list[dict]:
    return [action_item("Apply the plan", "Runs what kb:plan showed, then rebuilds the index · same as kb:apply")]


def undo_items(query: str) -> list[dict]:
    return [action_item("Undo the last apply", "Reverses the last batch of moves · same as kb:undo")]


COMMAND_LIST = [
    Command("stats", all_stats_items, "stats", "counts: books, incomplete downloads, duplicate titles"),
    Command("dups", dups_items, "dups", "same title in several files or formats"),
    Command("rnd", random_items, "open", "five random complete books, filters allowed", aliases=("random",)),
    Command("lint", lint_items, "open", "problems: junk, partial downloads, noisy names, duplicates, misfiled series"),
    Command("inbox", inbox_items, "open", "books without a genre yet, oldest first"),
    Command("classify", classify_items, "classify", "pick an inbox book, then a genre"),
    Command("plan", written_plan_items, "apply-one", "proposed moves, renames and trash · ↩ on a row applies it"),
    Command("src", sources_items, "import", "search the other sources · ↩ imports into the inbox", aliases=("sources",), needs_index=False),
    Command("index", index_items, "index", "rebuild the library and sources index", aliases=("update",), needs_index=False),
    Command("apply", apply_items, "apply", "apply plan.tsv, then rebuild the index", needs_index=False),
    Command("undo", undo_items, "undo", "move the last batch back", needs_index=False),
]
COMMANDS = {name: command for command in COMMAND_LIST for name in command.names}
MIN_SUGGESTION_PREFIX = 2


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
    inbox_cmd = sub.add_parser("inbox")
    inbox_cmd.add_argument("query", nargs="?", default="")
    inbox_cmd.set_defaults(func=cmd_inbox)
    classify_cmd = sub.add_parser("classify")
    classify_cmd.add_argument("query", nargs="?", default="")
    classify_cmd.set_defaults(func=cmd_classify)
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
    tag_cmd = sub.add_parser("tag")
    tag_cmd.add_argument("book")
    tag_cmd.add_argument("--notify", action="store_true")
    tag_cmd.add_argument("edits", nargs=argparse.REMAINDER)
    tag_cmd.set_defaults(func=cmd_tag)
    fix_cmd = sub.add_parser("fix")
    fix_cmd.add_argument("query", nargs="?", default="")
    fix_cmd.set_defaults(func=cmd_fix)
    index_sources = sub.add_parser("index-sources")
    index_sources.add_argument("--notify", action="store_true")
    index_sources.set_defaults(func=cmd_index_sources)
    sources_cmd = sub.add_parser("sources")
    sources_cmd.add_argument("query", nargs="?", default="")
    sources_cmd.set_defaults(func=cmd_sources)
    import_cmd = sub.add_parser("import")
    import_cmd.add_argument("book")
    import_cmd.add_argument("--move", action="store_true")
    import_cmd.add_argument("--notify", action="store_true")
    import_cmd.set_defaults(func=cmd_import)
    genres_cmd = sub.add_parser("genres")
    genres_cmd.add_argument("query", nargs="?", default="")
    genres_cmd.set_defaults(func=cmd_genres)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
