from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from kobolib import alfred
from kobolib.config import db_path, library_root, plan_path, sources, sources_db_path
from kobolib.index import Index, is_current
from kobolib.library import current_plan, findings, known_genres, not_in_library, unclassified_rows
from kobolib.model import Row
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


def without_index_items() -> list[dict]:
    return [alfred.message_item(index_problem(), "Run kb:index to build it")]


def book_items(raw: str) -> list[dict]:
    if index_problem():
        return without_index_items()
    index = Index(db_path())
    rows = index.search(query_words(raw))
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
    mods = {key: {**mod, "variables": {"action": action, **mod.get("variables", {})}} for key, mod in item.get("mods", {}).items()}
    return {**item, "variables": {**item.get("variables", {}), "action": action}, "mods": mods}


def complete(rows: list[Row]) -> list[Row]:
    return [r for r in rows if not r.partial]


def classify_batch(rows: list[Row]) -> dict:
    books = alfred.LINE.join(r.fingerprint for r in complete(rows))
    return alfred.batch_mod(f"Classify all {len(complete(rows))} shown", variables={"book": books, "action": "classify"})


def command_items(command: str, rest: str) -> list[dict]:
    chosen = COMMANDS[command]
    if chosen.needs_index and index_problem():
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


def dups_items(query: str = "") -> list[dict]:
    groups = Index(db_path()).duplicates()
    return [alfred.duplicate_item(g) for g in groups] or [alfred.message_item("No duplicate titles")]


def random_items(query: str) -> list[dict]:
    rows = Index(db_path()).search(query_words(query), limit=5000)
    picks = random.sample(rows, min(5, len(rows)))
    return [alfred.book_item(r) for r in picks] or [alfred.empty_item(query)]


def inbox_items(query: str) -> list[dict]:
    rows = unclassified_rows(query)
    items = alfred.with_batch([alfred.inbox_item(r) for r in rows], classify_batch(rows))
    return items or [alfred.message_item("Inbox is empty", "Every book has a genre")]


def headed(head: dict, items: list[dict], batch_size: int) -> list[dict]:
    return [head, *items] if batch_size > 1 else items


def classify_items(query: str) -> list[dict]:
    rows = unclassified_rows(query)
    items = alfred.with_batch([alfred.classify_item(r) for r in rows], classify_batch(rows))
    return headed(alfred.classify_all_item(complete(rows)), items, len(complete(rows))) or [
        alfred.message_item("Nothing to classify", "Every book has a genre")
    ]


def lint_items(query: str = "") -> list[dict]:
    return [alfred.finding_item(f, str(library_root())) for f in findings()] or [
        alfred.message_item("Nothing to fix", "The library is clean")
    ]


def written_plan_items(query: str = "") -> list[dict]:
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


def source_items(raw: str) -> list[dict]:
    rows = not_in_library(Index(sources_db_path()).search(query_words(raw)))
    batch = alfred.batch_mod(f"Import all {len(rows)} shown", alfred.LINE.join(r.path for r in rows))
    items = alfred.with_batch([alfred.source_item(r) for r in rows], batch)
    return headed(alfred.import_all_item(rows), items, len(rows)) or [alfred.empty_item(raw)]


def sources_items(query: str) -> list[dict]:
    if stale_index():
        return without_index_items()
    if problem := index_problem(sources_db_path(), "Sources index"):
        return [alfred.message_item(problem, "Set KOBO_SOURCES, then run kb:index")]
    return source_items(query)


def stats_items() -> list[dict]:
    index = Index(db_path())
    partial = len(index.partials(query_words("")))
    return [
        alfred.message_item(f"{index.count()} books indexed", str(library_root())),
        alfred.message_item(f"{partial} incomplete downloads", "kb lint"),
        alfred.message_item(f"{len(index.duplicates())} duplicate titles", "kb:dups"),
    ]


def sources_stats_items() -> list[dict]:
    if index_problem(sources_db_path()):
        return []
    return [alfred.message_item(f"{Index(sources_db_path()).count()} books in {len(sources())} sources", "kb:src")]


def all_stats_items(query: str = "") -> list[dict]:
    return stats_items() + sources_stats_items()


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
    Command("rnd", random_items, "open", "five random books, drawn from those matching the words", aliases=("random",)),
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
