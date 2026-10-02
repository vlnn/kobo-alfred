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
    index_problem,
    lint_items,
    plan_items,
    random_items,
    search_items,
    sources_items,
    tag_edits,
    without_index_items,
)
from kobolib.config import covers_dir, db_path, journal_path, library_root, plan_path, selected_book, selected_books, sources, tag_store
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
from kobolib.model import Book, Row, Tag
from kobolib.plan import read_plan, write_plan
from kobolib.tags import TagStore

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


def without_index() -> int:
    print(alfred.render(without_index_items()))
    return 0


def requires_index(command: Callable[[Namespace], int]) -> Callable[[Namespace], int]:
    @wraps(command)
    def guarded(args: Namespace) -> int:
        return without_index() if index_problem() else command(args)

    return guarded


@requires_index
def cmd_dups(args) -> int:
    print(alfred.render(dups_items()))
    return 0


@requires_index
def cmd_random(args) -> int:
    print(alfred.render(random_items(args.query)))
    return 0


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
    if problem := index_problem():
        return f"{problem}: run kb:index"
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


def tag_one(row: Row, edits: list[str], index: Index, store: TagStore) -> str:
    tag = apply_edits(store.get(row.fingerprint) or Tag(rel_path=row.rel_path), edits)
    store.set(row.fingerprint, tag)
    store.save()
    index.write_tag(row.fingerprint, store.get(row.fingerprint))
    summary = tag_summary(row.title, tag)
    return summary if not sets_genre(edits) else f"{summary} · {rehome(row, index, store)}"


def tagged_summary(rows: list[Row], results: list[str], edits: list[str], missing: list[str]) -> str:
    if len(rows) == 1:
        return results[0] + skipped_summary(missing)
    what = " ".join(e for e in edits if e.startswith("genre=")).removeprefix("genre=") or ", ".join(edits)
    return f"{counted(len(rows), 'book')} → {what}{skipped_summary(missing)}"


def cmd_tag(args) -> int:
    if reason := not_writable():
        return refuse(reason, args.notify)
    index, store = Index(db_path()), tag_store()
    found = {ref: row_by_reference(ref, index) for ref in args.book.splitlines() if ref}
    rows = [row for row in found.values() if row is not None]
    missing = [f"not indexed: {ref}" for ref, row in found.items() if row is None]
    if not rows:
        print("; ".join(missing).capitalize())
        return 1
    results = [tag_one(row, args.edits, index, store) for row in rows]
    report(tagged_summary(rows, results, args.edits, missing), args.notify)
    return 0


@requires_index
def cmd_fix(args) -> int:
    book = selected_book()
    index, store = Index(db_path()), tag_store()
    row = index.by_fingerprint(book) if book else None
    if row is None:
        print(alfred.render([alfred.message_item("No book selected", "Start from kb and press ⇧↩ on a book")]))
        return 0
    tag = store.get(book) or Tag()
    query = args.query.strip().lower()
    items = [alfred.fix_header(row, tag.genre, tag.tags), *tag_edits(query, tag.tags, index, book)]
    if not query.startswith(("+", "-")):
        items += genre_edits(query, index, store, book)
    print(alfred.render(items))
    return 0


@requires_index
def batch_header(books: list[str]) -> list[dict]:
    if len(books) < 2:
        return []
    return [alfred.message_item(f"Genre for {len(books)} books", "↩ on a genre applies it to all of them")]


def cmd_genres(args) -> int:
    books = selected_books()
    if not books:
        print(alfred.render([alfred.message_item("No book selected", "Start from kb:classify")]))
        return 0
    edits = genre_edits(args.query.strip().lower(), Index(db_path()), tag_store(), selected_book())
    print(alfred.render(batch_header(books) + edits))
    return 0


def cmd_index_sources(args) -> int:
    code, message = run_index_sources()
    report(message, args.notify)
    return code


def cmd_sources(args) -> int:
    print(alfred.render(sources_items(args.query)))
    return 0


def import_one(path: str) -> tuple[Book | None, str]:
    src, dst = Path(path), inbox_folder() / Path(path).name
    if reason := import_blocked(src, dst):
        return None, reason
    transfer(src, dst)
    return add_book(db_path(), dst, library_root(), covers_dir()), ""


def counted(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def skipped_summary(reasons: list[str]) -> str:
    return f" · skipped {len(reasons)}: {'; '.join(reasons)}" if reasons else ""


def imported_summary(books: list[Book], reasons: list[str]) -> str:
    if not books:
        return f"Not imported: {'; '.join(reasons)}"
    folder = f"{Path(books[0].rel_path).parent}/"
    what = books[0].title if len(books) == 1 else counted(len(books), "book")
    return f"Imported {what} → {folder}{skipped_summary(reasons)}"


def cmd_import(args) -> int:
    if reason := not_writable():
        return refuse(reason, args.notify)
    outcomes = [import_one(path) for path in args.book.splitlines() if path]
    books = [book for book, _ in outcomes if book]
    reasons = [reason for _, reason in outcomes if reason]
    report(imported_summary(books, reasons), args.notify)
    return 0 if books else 1


@requires_index
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
    import_cmd = sub.add_parser("import", parents=[notify])
    import_cmd.add_argument("book")
    import_cmd.set_defaults(func=cmd_import)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
