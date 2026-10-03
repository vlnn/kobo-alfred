from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from kobolib import alfred
from kobolib.alfred import counted
from kobolib.apply import EXECUTABLE, last_batch, read_journal
from kobolib.config import db_path, genre_store, journal_path, library_root, sources, sources_db_path
from kobolib.genres import GenreStore
from kobolib.index import Index, index_busy, is_current
from kobolib.library import concerning, diagnosis, known_genres, not_in_library, pending_operations, unclassified_rows
from kobolib.model import DuplicateGroup, Finding, Operation, Row
from kobolib.query import query_words


def index_problem(path: Path | None = None, what: str = "Index") -> str:
    path = path or db_path()
    if not path.exists():
        return f"No {what.lower()} yet"
    if not is_current(path):
        return f"{what} is from an older version"
    return ""


def stale_index() -> bool:
    return db_path().exists() and not is_current(db_path())


EMPTY_INDEX = "Index is empty — is the library folder there? On a removable volume Alfred needs Removable Volumes access"


def without_index_items() -> list[dict]:
    return [alfred.action_item(index_problem(), "↩ builds it", "update")]


def inbox_reminder(index: Index) -> list[dict]:
    waiting = len(index.unclassified([]))
    if not waiting:
        return []
    return [alfred.navigation_item(f"{counted(waiting, 'book')} without a genre", "↩ shows the inbox", "inbox ")]


def book_rows(rows: list[Row]) -> list[dict]:
    return [alfred.book_item(r) for r in rows]


def plain_items(words: list[str]) -> list[dict]:
    if index_problem():
        return without_index_items()
    index = Index(db_path())
    if index.count() == 0:
        return [alfred.action_item(EMPTY_INDEX, "↩ rebuilds it", "update")]
    if not words:
        return inbox_reminder(index) + book_rows(index.search([]))
    return book_rows(index.search(words)) or [alfred.empty_item(" ".join(words))]


def matching_books(words: list[str]) -> list[dict]:
    return [] if index_problem() else book_rows(Index(db_path()).search(words))


def unlisted(books: list[dict], rows: list[dict]) -> list[dict]:
    listed = {row.get("uid") for row in rows}
    return [book for book in books if book["uid"] not in listed]


def search_items(raw: str) -> list[dict]:
    words = query_words(raw)
    command = COMMANDS.get(words[0].lower()) if words else None
    if command is None:
        return suggestions(raw) + plain_items(words)
    return command_items(command, words)


def with_action(item: dict, action: str) -> dict:
    variables = item.get("variables", {})
    return item if "action" in variables else {**item, "variables": {**variables, "action": action}}


def command_items(command: Command, words: list[str]) -> list[dict]:
    if command.needs_index and index_problem():
        return without_index_items()
    rows = [with_action(i, command.action) for i in command.items(words[1:])]
    return rows + unlisted(matching_books(words), rows)


def completes(word: str, command: Command) -> str:
    return next((name for name in command.names if name.startswith(word)), "")


def suggestions(raw: str) -> list[dict]:
    word = raw.strip().lower()
    if len(word) < MIN_SUGGESTION_PREFIX or " " in word or word in COMMANDS:
        return []
    completions = sorted((name, command) for command in COMMAND_LIST if (name := completes(word, command)))
    return [alfred.suggestion_item(name, command.help) for name, command in completions]


def nothing(words: list[str], title: str, subtitle: str = "") -> list[dict]:
    return [alfred.empty_item(" ".join(words))] if words else [alfred.message_item(title, subtitle)]


def duplicate_groups(index: Index, words: list[str]) -> list[DuplicateGroup]:
    groups = index.duplicates()
    if not words:
        return groups
    wanted = index.rel_paths(words)
    return [g for g in groups if any(b.rel_path in wanted for b in g.books)]


def dups_items(words: list[str] = ()) -> list[dict]:
    groups = duplicate_groups(Index(db_path()), list(words))
    rows = [alfred.copy_item(book, len(g.books)) for g in groups for book in g.books]
    return rows or [alfred.message_item("No duplicate titles")]


def random_items(words: list[str]) -> list[dict]:
    rows = Index(db_path()).search(words, limit=5000)
    picks = random.sample(rows, min(5, len(rows)))
    return book_rows(picks) or [alfred.empty_item(" ".join(words))]


def inbox_items(words: list[str]) -> list[dict]:
    rows = [alfred.inbox_item(r) for r in unclassified_rows(words)]
    return rows or nothing(words, "Inbox is empty", "Every book has a genre")


def headed(head: dict, items: list[dict], batch_size: int) -> list[dict]:
    return [head, *items] if batch_size > 1 else items


def classify_rows(words: list[str]) -> list[Row]:
    index = Index(db_path())
    return index.search(words, limit=CLASSIFY_LIMIT) if words else index.unclassified([])


def classify_items(words: list[str]) -> list[dict]:
    rows = classify_rows(words)
    items = [alfred.classify_item(r) for r in rows]
    return headed(alfred.classify_all_item(rows), items, len(rows)) or nothing(words, "Nothing to classify", "Every book has a genre")


def contains(fragment: str, text: str) -> bool:
    return fragment.casefold() in text.casefold()


def genre_choices(current: str, known: list[str]) -> list[str]:
    return [current, *(g for g in known if g != current)] if current else known


def genre_row(genre: str, book: str, typed: str, current: str) -> dict:
    item = alfred.genre_item(genre, book, typed)
    return alfred.keep_genre_item(item) if genre == current else item


def picker_header(rows: list[Row], store: GenreStore) -> dict:
    if len(rows) > 1:
        return alfred.message_item(f"{len(rows)} books", "↩ on a genre sets it for all of them")
    return alfred.genre_header(rows[0], store.genre_of(rows[0]))


def genre_picker_items(typed: str, books: list[str]) -> list[dict]:
    index, store = Index(db_path()), genre_store()
    rows = [row for fingerprint in books if (row := index.by_fingerprint(fingerprint))]
    if not rows:
        return [alfred.message_item("No book selected", "Press ⇧↩ on a book in kb, or ↩ in kb classify")]
    book = alfred.LINE.join(books)
    current = store.genre_of(rows[0]) if len(rows) == 1 else ""
    genres = [g for g in genre_choices(current, known_genres(index, store)) if contains(typed, g)]
    choices = [genre_row(g, book, typed, current) for g in genres]
    fallback = [alfred.new_genre_item(typed, book)] if typed else []
    return [picker_header(rows, store), *(choices or fallback)]


def source_items(words: list[str]) -> list[dict]:
    rows = not_in_library(Index(sources_db_path()).search(words))
    items = [alfred.source_item(r) for r in rows]
    return headed(alfred.import_all_item(rows), items, len(rows)) or [alfred.empty_item(" ".join(words))]


def sources_items(words: list[str]) -> list[dict]:
    if stale_index():
        return without_index_items()
    if problem := index_problem(sources_db_path(), "Sources index"):
        return [alfred.message_item(problem, "Set KOBO_SOURCES, then kb update")]
    return source_items(words)


def stats_items() -> list[dict]:
    index = Index(db_path())
    return [
        alfred.navigation_item(counted(index.complete_count(), "book"), str(library_root()), ""),
        alfred.navigation_item(f"{counted(len(index.unclassified([])), 'book')} without a genre", "↩ shows the inbox", "inbox "),
        alfred.navigation_item(counted(len(index.duplicates()), "duplicate title"), "↩ lists every copy", "dups "),
        alfred.navigation_item(counted(len(pending_operations()), "pending fix", "pending fixes"), "↩ lists them", "fix "),
        alfred.navigation_item(counted(len(index.partials([])), "unfinished download"), "↩ lists them", "trash "),
    ]


def sources_stats_items() -> list[dict]:
    if index_problem(sources_db_path()):
        return []
    count = Index(sources_db_path()).count()
    return [alfred.navigation_item(f"{counted(count, 'book')} in {counted(len(sources()), 'source')}", "↩ searches them", "src ")]


def all_stats_items(words: list[str] = ()) -> list[dict]:
    return stats_items() + sources_stats_items()


@dataclass(frozen=True)
class Command:
    name: str
    items: Callable[[list[str]], list[dict]]
    action: str
    help: str
    aliases: tuple[str, ...] = ()
    needs_index: bool = True

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


def update_items(words: list[str]) -> list[dict]:
    if index_busy(db_path()):
        return [alfred.message_item("Update is running", "A notification follows when it finishes")]
    return [alfred.action_item("Rebuild the index", "Library, sources and PDF thumbnails · in the background, then notifies", "update")]


def trash_rows(words: list[str]) -> list[Row]:
    index = Index(db_path())
    return index.partials(words) + (index.search(words, limit=LIST_LIMIT) if words else [])


def trash_all_item(rows: list[Row]) -> dict:
    paths = alfred.LINE.join(r.path for r in rows)
    return alfred.head_row("trash:all", f"Trash all {counted(len(rows), 'book')}", "↩ moves every book listed below to _trash/", paths)


def trash_items(words: list[str]) -> list[dict]:
    rows = trash_rows(words)
    items = [alfred.trash_item(r) for r in rows]
    return headed(trash_all_item(rows), items, len(rows)) or nothing(words, "Nothing to trash", "No unfinished downloads")


def by_hand(found: list[Finding], ops: list[Operation]) -> list[Finding]:
    moving = {o.src for o in ops}
    return [f for f in found if f.rule in MANUAL_RULES and f.rel_paths[0] not in moving]


def kind_label(kind: str, n: int) -> str:
    return counted(n, "move") if kind == "move" else f"{n} to _{kind}"


def kinds_summary(ops: list[Operation]) -> str:
    counts = Counter(o.kind for o in ops)
    return alfred.SEPARATOR.join(kind_label(kind, counts[kind]) for kind in FIX_KINDS if counts[kind])


def fix_all_items(ops: list[Operation], words: list[str]) -> list[dict]:
    if not ops:
        return []
    paths = alfred.LINE.join(str(library_root() / o.src) for o in ops) if words else ""
    return [alfred.head_row("fix:all", f"Fix all {len(ops)}", kinds_summary(ops), paths)]


def undo_items() -> list[dict]:
    batch = last_batch(read_journal(journal_path()))
    if not batch:
        return []
    title = f"Undo last batch ({counted(len(batch), 'move')})"
    return [{"uid": "undo:last", **alfred.action_item(title, "An undo is itself a batch: undoing twice re-applies", "undo")}]


def completion(command: str, words: list[str]) -> str:
    return " ".join([command, *words]) + " "


def reminder_item(key: str, title: str, subtitle: str, completes: str) -> dict:
    return {"uid": f"reminder:{key}", **alfred.navigation_item(title, subtitle, completes)}


def fix_reminders(words: list[str]) -> list[dict]:
    index = Index(db_path())
    waiting, partial = len(index.unclassified(words)), len(index.partials(words))
    inbox = reminder_item("inbox", f"{counted(waiting, 'book')} without a genre", "↩ lists them", completion("classify", words))
    downloads = reminder_item("partials", counted(partial, "unfinished download"), "↩ lists them", completion("trash", words))
    return [item for item, count in ((inbox, waiting), (downloads, partial)) if count]


def nothing_to_fix(words: list[str]) -> dict:
    title = f"Nothing to fix for ‘{' '.join(words)}’" if words else "Nothing to fix"
    return alfred.message_item(title, "The library is clean")


def fix_items(words: list[str]) -> list[dict]:
    found, ops = diagnosis()
    concerns, root = concerning(words), str(library_root())
    todo = [o for o in ops if o.kind in EXECUTABLE and concerns(o.src)]
    conflicts = [o for o in ops if o.kind == "skip" and concerns(o.src)]
    manual = [f for f in by_hand(found, ops) if concerns(f.rel_paths[0])]
    rows = [
        *fix_all_items(todo, words),
        *undo_items(),
        *fix_reminders(words),
        *(alfred.plan_item(o, root) for o in todo),
        *(alfred.conflict_item(o, root) for o in conflicts),
        *(alfred.problem_item(f, root) for f in manual),
    ]
    return rows or [nothing_to_fix(words)]


COMMAND_LIST = [
    Command("stats", all_stats_items, "stats", "counts: books, inbox, duplicates, pending fixes, unfinished downloads, sources"),
    Command("dups", dups_items, "open", "every copy of a title that exists in several files"),
    Command("rnd", random_items, "open", "five random books, drawn from those matching the words", aliases=("random",)),
    Command("inbox", inbox_items, "open", "books without a genre yet, oldest first"),
    Command("classify", classify_items, "classify", "set the genre of inbox books, or of any books matching the words"),
    Command("fix", fix_items, "fix", "what is wrong and how to fix it · ↩ applies, ⌥↩ reveals"),
    Command("trash", trash_items, "trash", "unfinished downloads; with words, any book · ↩ moves it to _trash/"),
    Command("src", sources_items, "import", "search the other sources · ↩ imports into the inbox", needs_index=False),
    Command("update", update_items, "update", "rebuild the library and sources index", needs_index=False),
]

COMMANDS = {name: command for command in COMMAND_LIST for name in command.names}

MIN_SUGGESTION_PREFIX = 2
CLASSIFY_LIMIT = 200
LIST_LIMIT = 200
FIX_KINDS = ("move", "trash", "dups")
MANUAL_RULES = {"author_inversion", "noisy_name", "opaque", "double_extension"}
