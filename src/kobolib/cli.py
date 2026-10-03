from __future__ import annotations

import argparse
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from kobolib import alfred, oracle
from kobolib.alfred import counted
from kobolib.apply import Applied, apply, undo
from kobolib.asking import (
    Question,
    ask_all,
    ask_authors,
    author_folder_names,
    collect_evidence,
    embed_all,
    embed_summary,
    genre_question,
    name_question,
    summary,
)
from kobolib.commands import (
    chooser_items,
    genre_picker_items,
    index_problem,
    roles,
    search_items,
    served_models,
    without_index_items,
)
from kobolib.config import (
    covers_dir,
    db_path,
    embed_model,
    genre_store,
    journal_path,
    library_index,
    library_root,
    model_on_update,
    selected_books,
    sources,
    suggestion_store,
    vector_store,
)
from kobolib.index import IndexBusy, add_book, fill_thumbnails, index_busy
from kobolib.library import (
    apply_fixes,
    apply_summary,
    dismiss_book,
    fix_operations,
    genre_text,
    import_blocked,
    inbox_folder,
    inbox_note,
    known_genres,
    operation_line,
    refresh_index,
    row_by_reference,
    run_index,
    run_index_sources,
    set_genres,
    transfer,
    trash_operations,
)
from kobolib.model import Book, Row

NOTIFY_SCRIPT = ("on run argv", 'display notification (item 1 of argv) with title "Kobo Library"', "end run")
CONFIGURE_SCRIPT = (
    "on run argv",
    'tell application id "com.runningwithcrayons.Alfred" to set configuration (item 1 of argv) '
    "to value (item 2 of argv) in workflow (item 3 of argv) exportable false",
    "end run",
)
BUNDLE_ID = "com.anokhin.kobolib"
ROLE_VARIABLES = {"oracle": ("KOBO_ORACLE_MODEL", "Oracle"), "embed": ("KOBO_EMBED_MODEL", "Embeddings")}


def osascript(script: tuple[str, ...], *args: str) -> None:
    lines = [arg for line in script for arg in ("-e", line)]
    subprocess.run(["osascript", *lines, "--", *args], capture_output=True, check=False)


def notify(message: str) -> None:
    osascript(NOTIFY_SCRIPT, message)


def configure(variable: str, value: str) -> None:
    osascript(CONFIGURE_SCRIPT, variable, value, os.environ.get("alfred_workflow_bundleid") or BUNDLE_ID)


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
    if model_on_update():
        consult_models(args.notify)
    return 0


BUSY = "The model is already being asked, try again later"


def consult_models(should_notify: bool) -> None:
    try:
        lock = oracle.lock()
    except IndexBusy:
        report(BUSY, should_notify)
        return
    try:
        if oracle.configured():
            ask_questions("", [], force=False, should_notify=should_notify, quiet=True)
        if embed_model():
            embed_books([], force=False, should_notify=should_notify, quiet=True)
    finally:
        lock.unlink(missing_ok=True)


def locked(run: Callable[[], None], should_notify: bool) -> int:
    try:
        lock = oracle.lock()
    except IndexBusy:
        return refuse(BUSY, should_notify)
    try:
        run()
    finally:
        lock.unlink(missing_ok=True)
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
    result = apply_fixes(ops)
    if not targets:
        return finish_with_reindex(apply_summary(result), args.notify)
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


def genres_label(genres: list[str]) -> str:
    distinct = sorted(set(genres))
    return distinct[0] if len(distinct) == 1 else counted(len(distinct), "genre")


def genre_summary(assignments: list[tuple[Row, str]], outcomes: list[tuple[bool, str]], missing: list[str]) -> str:
    label = genres_label([genre for _, genre in assignments])
    if len(assignments) == 1:
        return f"{assignments[0][0].title} → {label} · {outcomes[0][1]}{skipped_summary(missing)}"
    moved = sum(1 for was_moved, _ in outcomes if was_moved)
    return f"{counted(len(assignments), 'book')} → {label} · {moved} moved, {len(assignments) - moved} stayed put{skipped_summary(missing)}"


def references(values: list[str]) -> list[str]:
    return [line for value in values for line in value.splitlines() if line]


def assignment(line: str, genre: str) -> tuple[str, str]:
    reference, _, own = line.partition("\t")
    return reference, genre_text(own) or genre


def cmd_genre(args) -> int:
    if reason := not_writable():
        return refuse(reason, args.notify)
    index, store = library_index(), genre_store()
    wanted = dict(assignment(line, genre_text(args.genre)) for line in references(args.books))
    if not all(wanted.values()):
        return refuse("No genre given", args.notify)
    found = {ref: row_by_reference(ref, index) for ref in wanted}
    assignments = [(row, wanted[ref]) for ref, row in found.items() if row is not None]
    unknown = [ref for ref, row in found.items() if row is None]
    missing = [f"not indexed: {ref}" for ref in unknown]
    if not assignments:
        return refuse(f"Not indexed: {'; '.join(unknown)}", args.notify)
    outcomes = set_genres(assignments, index, store)
    report(genre_summary(assignments, outcomes, missing), args.notify)
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


def questions(name: str) -> list[Question]:
    index, store = library_index(), genre_store()
    all_questions = {"name": name_question, "genre": lambda: genre_question(known_genres(index, store))}
    return [make() for key, make in all_questions.items() if name in ("", key)]


def cmd_dismiss(args) -> int:
    if problem := index_problem():
        return refuse(f"{problem}: run kb update", args.notify)
    title = dismiss_book(args.book)
    if not title:
        return refuse(f"Not indexed: {args.book}", args.notify)
    report(f"Suggestions for {title} dismissed", args.notify)
    return 0


def dry_run_report(asked_blocks: list[str]) -> str:
    return "\n\n".join(asked_blocks) + "\n" if asked_blocks else ""


def asks_authors(name: str) -> bool:
    return name in ("", "authors")


def evidence_report(name: str, words: list[str]) -> str:
    index = library_index()
    blocks = [block for question in questions(name) for block in collect_evidence(question, question.candidates(index, words)).evidence]
    if asks_authors(name):
        blocks.append(oracle.authors_evidence(author_folder_names(index.everything())))
    return dry_run_report(blocks)


def ask_questions(name: str, words: list[str], force: bool, should_notify: bool, quiet: bool = False) -> None:
    index, store = library_index(), suggestion_store()
    passes = [(q.noun, ask_all(q, q.candidates(index, words), store, force)) for q in questions(name)]
    if asks_authors(name):
        passes.append(("merge", ask_authors(index.everything(), store, force)))
    store.save()
    for noun, asked in passes:
        if asked.books or not quiet:
            report(summary(noun, asked), should_notify)


def cmd_ask(args) -> int:
    if not oracle.configured():
        return refuse("No model server: set KOBO_ORACLE_URL in the workflow configuration", args.notify)
    if problem := index_problem():
        return refuse(f"{problem}: run kb update", args.notify)
    words = [word for value in args.words for word in value.split()]
    if args.dry_run:
        print(evidence_report(args.question, words), end="")
        return 0
    return locked(lambda: ask_questions(args.question, words, args.force, args.notify), args.notify)


def embed_books(words: list[str], force: bool, should_notify: bool, quiet: bool = False) -> None:
    rows, store = library_index().search(words, limit=100_000), vector_store()
    wanted = rows if force else store.missing(embed_model(), rows)
    if wanted or not quiet:
        report(embed_summary(embed_all(wanted, embed_model(), store), not wanted), should_notify)


def cmd_embed(args) -> int:
    if not embed_model():
        return refuse("No embedding model: set KOBO_EMBED_MODEL, or ↩ on a model in kb model", args.notify)
    if problem := index_problem():
        return refuse(f"{problem}: run kb update", args.notify)
    return locked(lambda: embed_books(args.words, args.force, args.notify), args.notify)


def cmd_choose(args) -> int:
    variable, label = ROLE_VARIABLES[args.role]
    configure(variable, args.model)
    report(f"{label}: {args.model}", args.notify)
    return 0


def cmd_models(args) -> int:
    if not oracle.configured():
        return refuse("No model server: set KOBO_ORACLE_URL in the workflow configuration", False)
    served = served_models()
    for url, listed in served.items():
        if listed is None:
            print(f"Model not reachable at {url}")
        else:
            print("".join(f"{model}\t{', '.join(roles(model))}\n" for model in listed), end="")
    return int(any(listed is None for listed in served.values()))


def cmd_chooser(args) -> int:
    print(alfred.render(chooser_items(args.query.strip(), os.environ.get("model", ""))))
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
    ask_cmd = sub.add_parser("ask", parents=[notify, flag("--force"), flag("--dry-run")])
    ask_cmd.add_argument("question", nargs="?", default="", choices=["", "genre", "name", "authors"])
    ask_cmd.add_argument("words", nargs="*")
    ask_cmd.set_defaults(func=cmd_ask)
    dismiss_cmd = sub.add_parser("dismiss", parents=[notify])
    dismiss_cmd.add_argument("book")
    dismiss_cmd.set_defaults(func=cmd_dismiss)
    choose_cmd = sub.add_parser("choose", parents=[notify])
    choose_cmd.add_argument("role", choices=list(ROLE_VARIABLES))
    choose_cmd.add_argument("model")
    choose_cmd.set_defaults(func=cmd_choose)
    sub.add_parser("models").set_defaults(func=cmd_models)
    embed_cmd = sub.add_parser("embed", parents=[notify, flag("--force")])
    embed_cmd.add_argument("words", nargs="*")
    embed_cmd.set_defaults(func=cmd_embed)
    sub.add_parser("chooser", parents=[query]).set_defaults(func=cmd_chooser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
