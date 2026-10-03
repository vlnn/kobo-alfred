from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from kobolib import alfred
from kobolib.alfred import counted
from kobolib.apply import Applied, apply, undo
from kobolib.commands import (
    genre_picker_items,
    index_problem,
    search_items,
    without_index_items,
)
from kobolib.config import covers_dir, db_path, genre_store, journal_path, library_index, library_root, selected_books, sources
from kobolib.index import add_book, fill_thumbnails, index_busy
from kobolib.library import (
    apply_summary,
    fix_operations,
    genre_text,
    import_blocked,
    inbox_folder,
    inbox_note,
    operation_line,
    refresh_index,
    row_by_reference,
    run_index,
    run_index_sources,
    set_genre,
    transfer,
    trash_operations,
)
from kobolib.model import Book, Row

NOTIFY_SCRIPT = ("on run argv", 'display notification (item 1 of argv) with title "Kobo Library"', "end run")


def notify(message: str) -> None:
    lines = [arg for line in NOTIFY_SCRIPT for arg in ("-e", line)]
    subprocess.run(["osascript", *lines, "--", message], capture_output=True, check=False)


def report(message: str, should_notify: bool) -> None:
    print(message, flush=True)
    if should_notify:
        notify(message)


def cmd_update(args) -> int:
    code, message = run_index()
    report(message + (inbox_note() if code == 0 else ""), args.notify)
    if code != 0:
        return code
    if sources():
        report(run_index_sources()[1], args.notify)
    if not args.no_thumbnails:
        report(f"Generated {fill_thumbnails(library_index(), covers_dir())} PDF covers", args.notify)
    return 0


def cmd_search(args) -> int:
    print(alfred.render(search_items(args.query)))
    return 0


def refuse(message: str, should_notify: bool) -> int:
    report(message, should_notify)
    return 1


def not_writable() -> str:
    if problem := index_problem():
        return f"{problem}: run kb update"
    if index_busy(db_path()):
        return "Indexing is running, try again later"
    return ""


def finish_with_reindex(message: str, should_notify: bool) -> int:
    code, index_message = run_index()
    report(f"{message} · {index_message}", should_notify)
    return code


def cmd_undo(args) -> int:
    if index_busy(db_path()):
        return refuse("Indexing is running, try again later", args.notify)
    undone = undo(library_root(), journal_path())
    return finish_with_reindex(f"Undid {undone}", args.notify)


def cmd_fix(args) -> int:
    if reason := not_writable():
        return refuse(reason, args.notify)
    targets = references(args.targets)
    ops = fix_operations(targets)
    if args.dry_run:
        print("".join(f"{operation_line(o)}\n" for o in ops), end="")
        return 0
    result = apply(ops, library_root(), journal_path())
    if not targets:
        return finish_with_reindex(apply_summary(result), args.notify)
    refresh_index(result)
    report(apply_summary(result), args.notify)
    return 0


def trashed_summary(result: Applied, missing: list[str]) -> str:
    return f"Moved {counted(result.done, 'book')} to _trash/{skipped_summary([*result.skipped, *missing])}"


def cmd_trash(args) -> int:
    if reason := not_writable():
        return refuse(reason, args.notify)
    index = library_index()
    found = {ref: row_by_reference(ref, index) for ref in references(args.paths)}
    rows = [row for row in found.values() if row is not None]
    unknown = [ref for ref, row in found.items() if row is None]
    missing = [f"not indexed: {ref}" for ref in unknown]
    if not rows:
        return refuse(f"Not indexed: {'; '.join(unknown)}", args.notify)
    result = apply(trash_operations(rows), library_root(), journal_path())
    refresh_index(result)
    report(trashed_summary(result, missing), args.notify)
    return 0


def genre_summary(rows: list[Row], genre: str, outcomes: list[tuple[bool, str]], missing: list[str]) -> str:
    if len(rows) == 1:
        return f"{rows[0].title} → {genre} · {outcomes[0][1]}{skipped_summary(missing)}"
    moved = sum(1 for was_moved, _ in outcomes if was_moved)
    return f"{counted(len(rows), 'book')} → {genre} · {moved} moved, {len(rows) - moved} stayed put{skipped_summary(missing)}"


def references(values: list[str]) -> list[str]:
    return [line for value in values for line in value.splitlines() if line]


def cmd_genre(args) -> int:
    if reason := not_writable():
        return refuse(reason, args.notify)
    genre, index, store = genre_text(args.genre), library_index(), genre_store()
    if not genre:
        return refuse("No genre given", args.notify)
    found = {ref: row_by_reference(ref, index) for ref in references(args.books)}
    rows = [row for row in found.values() if row is not None]
    unknown = [ref for ref, row in found.items() if row is None]
    missing = [f"not indexed: {ref}" for ref in unknown]
    if not rows:
        return refuse(f"Not indexed: {'; '.join(unknown)}", args.notify)
    outcomes = [set_genre(row, genre, index, store) for row in rows]
    report(genre_summary(rows, genre, outcomes, missing), args.notify)
    return 0


def cmd_genres(args) -> int:
    items = without_index_items() if index_problem() else genre_picker_items(args.query.strip(), selected_books())
    print(alfred.render(items))
    return 0


def import_one(path: str) -> tuple[Book | None, str]:
    src, dst = Path(path), inbox_folder() / Path(path).name
    if reason := import_blocked(src, dst):
        return None, reason
    transfer(src, dst)
    return add_book(db_path(), dst, library_root(), covers_dir()), ""


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
    report(imported_summary(books, reasons) + inbox_note(), args.notify)
    return 0 if books else 1


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
    notify, query = flag("--notify"), query_argument()
    sub.add_parser("update", parents=[notify, flag("--no-thumbnails")]).set_defaults(func=cmd_update)
    sub.add_parser("search", parents=[query]).set_defaults(func=cmd_search)
    sub.add_parser("genres", parents=[query]).set_defaults(func=cmd_genres)
    sub.add_parser("undo", parents=[notify]).set_defaults(func=cmd_undo)
    fix_cmd = sub.add_parser("fix", parents=[notify, flag("--dry-run")])
    fix_cmd.add_argument("targets", nargs="*")
    fix_cmd.set_defaults(func=cmd_fix)
    trash_cmd = sub.add_parser("trash", parents=[notify])
    trash_cmd.add_argument("paths", nargs="+")
    trash_cmd.set_defaults(func=cmd_trash)
    genre_cmd = sub.add_parser("genre", parents=[notify])
    genre_cmd.add_argument("books", nargs="+")
    genre_cmd.add_argument("genre")
    genre_cmd.set_defaults(func=cmd_genre)
    import_cmd = sub.add_parser("import", parents=[notify])
    import_cmd.add_argument("book")
    import_cmd.set_defaults(func=cmd_import)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
