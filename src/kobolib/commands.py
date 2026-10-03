from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from kobolib import alfred
from kobolib.config import db_path, library_root, plan_path, sources, sources_db_path
from kobolib.index import Index, is_current
from kobolib.library import current_plan, findings, known_genres, not_in_library, pending_operations, unclassified_rows
from kobolib.model import DuplicateGroup, Row
from kobolib.plan import write_plan
from kobolib.query import query_words
from kobolib.tags import GenreStore


def index_problem(path: Path | None = None, what: str = "Index") -> str:
    path = path or db_path()
    if not path.exists():
        return f"No {what.lower()} yet"
    if not is_current(path):
        return f"{what} is from an older version"
    return ""


def stale_index() -> bool:
    return db_path().exists() and not is_current(db_path())


EMPTY_INDEX = "Index is empty — is the card mounted? Alfred needs Removable Volumes access"


def without_index_items() -> list[dict]:
    return [alfred.action_item(index_problem(), "↩ builds it", "update")]


def counted(n: int, noun: str, plural: str = "") -> str:
    return f"{n} {noun if n == 1 else plural or noun + 's'}"


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
    if "action" in item.get("variables", {}):
        return item
    mods = {key: {**mod, "variables": {"action": action, **mod.get("variables", {})}} for key, mod in item.get("mods", {}).items()}
    return {**item, "variables": {**item.get("variables", {}), "action": action}, "mods": mods}


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


def lint_items(words: list[str] = ()) -> list[dict]:
    return [alfred.finding_item(f, str(library_root())) for f in findings()] or [
        alfred.message_item("Nothing to fix", "The library is clean")
    ]


def written_plan_items(words: list[str] = ()) -> list[dict]:
    ops = current_plan()
    write_plan(ops, plan_path())
    return plan_items(ops)


def plan_items(ops) -> list[dict]:
    if not ops:
        return [alfred.message_item("Nothing to do", "Every classified book is where it belongs")]
    rows = alfred.with_batch([alfred.plan_item(o, str(library_root())) for o in ops], alfred.batch_mod(f"Apply all {len(ops)} operations"))
    return [alfred.apply_all_item(len(ops)), *rows]


def contains(fragment: str, text: str) -> bool:
    return fragment.casefold() in text.casefold()


def genre_edits(query: str, index: Index, store: GenreStore, book: str) -> list[dict]:
    genres = [g for g in known_genres(index, store) if contains(query, g)]
    items = [alfred.genre_item(g, book) for g in genres]
    if query and query not in genres:
        items.append(alfred.edit_item(f"genre={query}", f"New genre: {query}", book))
    return items


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
    return [
        alfred.action_item("Rebuild the index", "Library, sources and PDF thumbnails · runs in the background, then notifies", "update")
    ]


def apply_items(words: list[str]) -> list[dict]:
    return [alfred.action_item("Apply the plan", "Runs what kb plan showed, then rebuilds the index", "apply")]


def undo_items(words: list[str]) -> list[dict]:
    return [alfred.action_item("Undo the last apply", "Reverses the last batch of moves", "undo")]


COMMAND_LIST = [
    Command("stats", all_stats_items, "stats", "counts: books, inbox, duplicates, pending fixes, unfinished downloads, sources"),
    Command("dups", dups_items, "open", "every copy of a title that exists in several files"),
    Command("rnd", random_items, "open", "five random books, drawn from those matching the words", aliases=("random",)),
    Command("lint", lint_items, "open", "problems: junk, partial downloads, noisy names, duplicates, misfiled series"),
    Command("inbox", inbox_items, "open", "books without a genre yet, oldest first"),
    Command("classify", classify_items, "classify", "set the genre of inbox books, or of any books matching the words"),
    Command("plan", written_plan_items, "apply-one", "proposed moves, renames and trash · ↩ on a row applies it"),
    Command("src", sources_items, "import", "search the other sources · ↩ imports into the inbox", needs_index=False),
    Command("update", update_items, "update", "rebuild the library and sources index", needs_index=False),
    Command("apply", apply_items, "apply", "apply plan.tsv, then rebuild the index", needs_index=False),
    Command("undo", undo_items, "undo", "move the last batch back", needs_index=False),
]

COMMANDS = {name: command for command in COMMAND_LIST for name in command.names}

MIN_SUGGESTION_PREFIX = 2
CLASSIFY_LIMIT = 200
