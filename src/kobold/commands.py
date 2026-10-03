from __future__ import annotations

import random
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from kobold import alfred, embedder, oracle
from kobold.alfred import counted
from kobold.apply import EXECUTABLE, last_batch, read_journal
from kobold.asking import genre_rows, name_rows
from kobold.config import (
    db_path,
    embed_model,
    embed_url,
    genre_store,
    journal_path,
    library_index,
    library_root,
    oracle_model,
    oracle_url,
    sources_db_path,
    sources_index,
    suggestion_store,
    vector_store,
)
from kobold.genres import GenreStore
from kobold.history import last_opened
from kobold.index import EVERYTHING, Index, index_busy, is_current
from kobold.library import (
    SourceCount,
    concerning,
    diagnosis,
    is_merge,
    known_genres,
    merge_target,
    not_in_library,
    pending_operations,
    source_counts,
    suggested_operations,
    unclassified_rows,
)
from kobold.model import Finding, Operation, Row
from kobold.query import query_words
from kobold.suggestions import SuggestionStore
from kobold.vectors import VectorStore


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
    index = library_index()
    if index.count() == 0:
        return [alfred.action_item(EMPTY_INDEX, "↩ rebuilds it", "update")]
    if not words:
        return inbox_reminder(index) + book_rows(index.search([]))
    return book_rows(index.search(words)) or [alfred.empty_item(" ".join(words))]


def matching_books(words: list[str]) -> list[dict]:
    return [] if index_problem() else book_rows(library_index().search(words))


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


def duplicate_groups(index: Index, words: list[str]) -> list[list[Row]]:
    groups = index.duplicates()
    if not words:
        return groups
    wanted = index.rel_paths(words)
    return [g for g in groups if any(b.rel_path in wanted for b in g)]


def dups_items(words: list[str]) -> list[dict]:
    groups = duplicate_groups(library_index(), words)
    rows = [alfred.copy_item(book, len(g)) for g in groups for book in g]
    return rows or [alfred.message_item("No duplicate titles")]


def random_items(words: list[str]) -> list[dict]:
    rows = library_index().search(words, limit=5000)
    picks = random.sample(rows, min(5, len(rows)))
    return book_rows(picks) or [alfred.empty_item(" ".join(words))]


def inbox_items(words: list[str]) -> list[dict]:
    rows = [alfred.inbox_item(r) for r in unclassified_rows(words)]
    return rows or nothing(words, "Inbox is empty", "Every book has a genre")


def headed(heads: list[dict], items: list[dict], batch_size: int) -> list[dict]:
    return [*heads, *items] if batch_size > 1 else items


def suggested_genres(store: SuggestionStore) -> dict[str, str]:
    return {fp: a["genre"] for fp, a in store.answers("genre").items() if a.get("genre") not in ("", oracle.NONE)}


def unasked(rows: list[Row], question: str, store: SuggestionStore) -> list[Row]:
    return [r for r in rows if store.get(r.fingerprint, question) is None]


def ask_title(inbox: int, unnamed: int, words: list[str]) -> str:
    parts = [counted(inbox, "inbox book")] * bool(inbox) + [counted(unnamed, "unnamed file")] * bool(unnamed)
    matching = f" matching ‘{' '.join(words)}’" if words else ""
    return f"Ask the model about {' and '.join(parts)}{matching}"


def oracle_rows(index: Index, store: SuggestionStore, words: list[str]) -> list[dict]:
    if not oracle.configured():
        return []
    if oracle.busy():
        return [alfred.busy_item("Asking the model… a notification follows")]
    down = [alfred.unreachable_item(url)] if (url := oracle.unreachable()) else []
    inbox, unnamed = len(unasked(genre_rows(index, words), "genre", store)), len(unasked(name_rows(index, words), "name", store))
    return down + ([alfred.ask_item(ask_title(inbox, unnamed, words), " ".join(words))] if inbox or unnamed else [])


def classify_rows(words: list[str]) -> list[Row]:
    index = library_index()
    return index.search(words, limit=CLASSIFY_LIMIT) if words else index.unclassified([])


def accept_items(rows: list[Row], suggested: dict[str, str]) -> list[dict]:
    pairs = [(r.fingerprint, suggested[r.fingerprint]) for r in rows if r.fingerprint in suggested]
    return [alfred.accept_genres_item(pairs)] if pairs else []


def classify_items(words: list[str]) -> list[dict]:
    index, store = library_index(), suggestion_store()
    rows, suggested = classify_rows(words), suggested_genres(store)
    items = [alfred.classify_item(r, suggested.get(r.fingerprint, "")) for r in rows]
    heads = [alfred.classify_all_item(rows), *accept_items(rows, suggested)]
    listed = headed(heads, [*oracle_rows(index, store, words), *items], len(rows))
    return listed or nothing(words, "Nothing to classify", "Every book has a genre")


def contains(fragment: str, text: str) -> bool:
    return fragment.casefold() in text.casefold()


def genre_choices(current: str, known: list[str]) -> list[str]:
    return [current, *(g for g in known if g != current)] if current else known


def words_of(text: str) -> set[str]:
    return set(WORD.findall(text.casefold()))


def subject_likely_first(known: list[str], subjects: str) -> list[str]:
    wanted = words_of(subjects)
    likely = [g for g in known if words_of(g) & wanted]
    return likely + [g for g in known if g not in likely]


def genre_row(genre: str, book: str, typed: str, current: str) -> dict:
    item = alfred.genre_item(genre, book, typed)
    return alfred.keep_genre_item(item) if genre == current else item


def picker_header(rows: list[Row], store: GenreStore) -> dict:
    if len(rows) > 1:
        return alfred.message_item(f"{len(rows)} books", "↩ on a genre sets it for all of them")
    return alfred.genre_header(rows[0], store.genre_of(rows[0]))


def suggestion_for(rows: list[Row]) -> str:
    return suggested_genres(suggestion_store()).get(rows[0].fingerprint, "") if len(rows) == 1 else ""


def genre_picker_items(typed: str, books: list[str]) -> list[dict]:
    index, store = library_index(), genre_store()
    rows = [row for fingerprint in books if (row := index.by_fingerprint(fingerprint))]
    if not rows:
        return [alfred.message_item("No book selected", "Press ⇧↩ on a book in kb, or ↩ in kb classify")]
    book = alfred.LINE.join(books)
    current, suggested = (store.genre_of(rows[0]) if len(rows) == 1 else ""), suggestion_for(rows)
    likely = subject_likely_first(known_genres(index, store), "; ".join(r.subjects for r in rows))
    genres = [g for g in genre_choices(current, likely) if contains(typed, g) and g != suggested]
    first = [alfred.suggested_genre_item(suggested, book, typed)] if suggested and contains(typed, suggested) else []
    choices = [*first, *(genre_row(g, book, typed, current) for g in genres)]
    fallback = [alfred.new_genre_item(typed, book)] if typed else []
    return [picker_header(rows, store), *(choices or fallback)]


def nothing_new_item(words: list[str], held: int) -> dict:
    if not held:
        return alfred.empty_item(" ".join(words))
    what = counted(held, "book matches", "books match") if words else counted(held, "book")
    where = f" ‘{' '.join(words)}’" if words else " in the sources"
    return alfred.message_item(f"{what}{where}, already in the library", "kb src shows only what the library does not hold")


def source_items(words: list[str]) -> list[dict]:
    found = sources_index().search(words, limit=EVERYTHING)
    fresh = not_in_library(found)
    items = [alfred.source_item(r) for r in fresh]
    return headed([alfred.import_all_item(fresh)], items, len(fresh)) or [nothing_new_item(words, len(found))]


def sources_items(words: list[str]) -> list[dict]:
    if stale_index():
        return without_index_items()
    if problem := index_problem(sources_db_path(), "Sources index"):
        return [alfred.message_item(problem, "Set KOBOLD_SOURCES, then kb update")]
    return source_items(words)


def stats_items() -> list[dict]:
    index = library_index()
    return [
        alfred.navigation_item(counted(index.complete_count(), "book"), str(library_root()), ""),
        alfred.navigation_item(f"{counted(len(index.unclassified([])), 'book')} without a genre", "↩ shows the inbox", "inbox "),
        alfred.navigation_item(counted(len(index.duplicates()), "duplicate title"), "↩ lists every copy", "dups "),
        alfred.navigation_item(counted(len(pending_operations()), "pending fix", "pending fixes"), "↩ lists them", "fix "),
        alfred.navigation_item(counted(len(index.partials([])), "unfinished download"), "↩ lists them", "trash "),
        alfred.navigation_item(f"{counted(embedded_count(), 'book')} embedded", "↩ kb model", "model "),
    ]


def source_stats_item(count: SourceCount) -> dict:
    title = f"{count.new} new of {counted(count.total, 'book')} in {count.source.name}"
    return alfred.navigation_item(title, f"{count.source} · ↩ searches it", f"src {count.source.name} ")


def sources_stats_items() -> list[dict]:
    if index_problem(sources_db_path()):
        return []
    return [source_stats_item(c) for c in source_counts(sources_index().everything())]


def all_stats_items(words: list[str]) -> list[dict]:
    return stats_items() + sources_stats_items()


def like_seed(index: Index, words: list[str]) -> Row | None:
    if words:
        return next(iter(index.search(words, limit=1)), None)
    opened = last_opened(library_root())
    return (index.by_rel_path(opened) if opened else None) or next(iter(index.search([], limit=1)), None)


def neighbour_rows(seed: Row, index: Index, store: VectorStore) -> list[dict]:
    scored = ((index.by_fingerprint(other), score) for other, score in store.neighbours(embed_model(), seed.fingerprint))
    return [alfred.like_item(row, score) for row, score in scored if row is not None and row.norm_title != seed.norm_title]


def embed_rows(store: VectorStore) -> list[dict]:
    if oracle.busy():
        return [alfred.busy_item("Embedding… a notification follows")]
    missing = missing_embeddings()
    return (
        [alfred.action_item(f"Embed {counted(missing, 'new book')}", "↩ runs in the background, then notifies", "embed")] if missing else []
    )


def like_items(words: list[str]) -> list[dict]:
    if not embed_model():
        return [alfred.navigation_item("No embedding model", "↩ opens kb model", "model ")]
    index, store = library_index(), vector_store()
    seed = like_seed(index, words)
    if seed is None:
        return nothing(words, "No books yet", "kb update indexes the library")
    if not store.count(embed_model()):
        return [alfred.action_item("No embeddings yet", "↩ embeds in the background, then notifies", "embed")]
    rows = neighbour_rows(seed, index, store)
    unembedded = [alfred.message_item(f"{seed.title} is not embedded yet")] if store.get(embed_model(), seed.fingerprint) is None else []
    return [alfred.like_header(seed), *rows, *unembedded, *embed_rows(store)]


def served_models() -> dict[str, list[str] | None]:
    return {url: embedder.models(url) for url in dict.fromkeys([oracle_url(), embed_url()])}


def reachability(listed: list[str] | None) -> str:
    return "reachable" if listed is not None else "not reachable"


def roles(model: str) -> list[str]:
    return [role for role, chosen in (("oracle", oracle_model()), ("embeddings", embed_model())) if model == chosen]


def model_row(model: str) -> dict:
    marks = [f"✓ {role}" for role in roles(model)]
    subtitle = alfred.SEPARATOR.join([*marks, "↩ choose what it is for"])
    return {
        "uid": f"model:{model}",
        **alfred.action_item(model, subtitle, "model", model),
        "variables": {"model": model, "action": "model"},
    }


def model_rows(served: dict[str, list[str] | None]) -> list[dict]:
    rows = []
    for url, listed in served.items():
        rows += [model_row(m) for m in listed] if listed is not None else [alfred.unreachable_item(url)]
    return rows


def embedded_count() -> int:
    return vector_store().count(embed_model()) if embed_model() else 0


def missing_embeddings() -> int:
    return len(vector_store().missing(embed_model(), library_index().search([], limit=EVERYTHING))) if not index_problem() else 0


def embeddings_item() -> dict:
    title = f"Embeddings: {embed_model() or 'none'}"
    if not embed_model():
        return alfred.message_item(title, "↩ on a model below chooses it")
    done, missing = embedded_count(), missing_embeddings()
    if not missing:
        return alfred.message_item(title, f"{counted(done, 'book')} embedded")
    return alfred.action_item(title, f"{done} of {done + missing} books embedded · ↩ embeds the rest", "embed")


def model_headers(served: dict[str, list[str] | None]) -> list[dict]:
    oracle_state = alfred.SEPARATOR.join([oracle_url(), reachability(served[oracle_url()])])
    return [alfred.message_item(f"Oracle: {oracle_model() or 'server default'}", oracle_state), embeddings_item()]


def model_items(words: list[str]) -> list[dict]:
    if not oracle.configured():
        return [alfred.message_item("No model server", "set KOBOLD_ORACLE_URL in the workflow configuration to a running llama-server")]
    served = served_models()
    return [*model_headers(served), *model_rows(served)]


def chooser_items(typed: str, model: str) -> list[dict]:
    if not model:
        return [alfred.message_item("No model selected", "Press ↩ on a model in kb model")]
    rows = [
        alfred.choose_item(model, "oracle", f"Use {model} for the oracle", "answers the genre, name and author questions"),
        alfred.choose_item(
            model, "embed", f"Use {model} for embeddings", "re-embeds everything; the old vectors are kept until the new ones exist"
        ),
    ]
    return [r for r in rows if contains(typed, r["title"])]


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
    index = library_index()
    return index.partials(words) + (index.search(words, limit=LIST_LIMIT) if words else [])


def trash_all_item(rows: list[Row]) -> dict:
    paths = alfred.LINE.join(r.path for r in rows)
    return alfred.head_row("trash:all", f"Trash all {counted(len(rows), 'book')}", "↩ moves every book listed below to _trash/", paths)


def trash_items(words: list[str]) -> list[dict]:
    rows = trash_rows(words)
    items = [alfred.trash_item(r) for r in rows]
    return headed([trash_all_item(rows)], items, len(rows)) or nothing(words, "Nothing to trash", "No unfinished downloads")


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
    index = library_index()
    waiting, partial = len(index.unclassified(words)), len(index.partials(words))
    inbox = reminder_item("inbox", f"{counted(waiting, 'book')} without a genre", "↩ lists them", completion("classify", words))
    downloads = reminder_item("partials", counted(partial, "unfinished download"), "↩ lists them", completion("trash", words))
    return [item for item, count in ((inbox, waiting), (downloads, partial)) if count]


def dismiss_items(words: list[str], store: SuggestionStore) -> list[dict]:
    if not words:
        return []
    rows = library_index().search(words, limit=2)
    if len(rows) != 1 or not any(store.answers(q).get(rows[0].fingerprint) for q in ("genre", "name")):
        return []
    return [alfred.dismiss_item(rows[0].fingerprint)]


def nothing_to_fix(words: list[str]) -> dict:
    title = f"Nothing to fix for ‘{' '.join(words)}’" if words else "Nothing to fix"
    return alfred.message_item(title, "The library is clean")


def merge_groups(ops: list[Operation], concerns: Callable[[str], bool]) -> dict[str, list[Operation]]:
    groups: dict[str, list[Operation]] = {}
    for op in ops:
        groups.setdefault(merge_target(op), []).append(op)
    return {canonical: group for canonical, group in groups.items() if any(concerns(o.src) for o in group)}


def fix_items(words: list[str]) -> list[dict]:
    found, ops = diagnosis()
    index, store, concerns, root = library_index(), suggestion_store(), concerning(words), str(library_root())
    todo = [o for o in ops if o.kind in EXECUTABLE and concerns(o.src)]
    suggested = suggested_operations(index.everything(), {o.src for o in ops})
    renames = [o for o in suggested if not is_merge(o) and concerns(o.src)]
    merges = merge_groups([o for o in suggested if is_merge(o)], concerns)
    conflicts = [o for o in ops if o.kind == "skip" and concerns(o.src)]
    manual = [f for f in by_hand(found, ops + suggested) if concerns(f.rel_paths[0])]
    rows = [
        *fix_all_items(todo, words),
        *undo_items(),
        *dismiss_items(words, store),
        *oracle_rows(index, store, words),
        *fix_reminders(words),
        *(alfred.plan_item(o, root) for o in todo),
        *(alfred.plan_item(o, root) for o in renames),
        *(alfred.merge_item(canonical, group, root) for canonical, group in merges.items()),
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
    Command("like", like_items, "open", "books like one: the top match for the words, or the one KOReader opened last"),
    Command(
        "model",
        model_items,
        "model",
        "the local model server: which models it serves, which one answers, which one embeds",
        needs_index=False,
    ),
]

COMMANDS = {name: command for command in COMMAND_LIST for name in command.names}

MIN_SUGGESTION_PREFIX = 2
WORD = re.compile(r"\w+")
CLASSIFY_LIMIT = 200
LIST_LIMIT = 200
FIX_KINDS = ("move", "trash", "dups")
MANUAL_RULES = {"author_inversion", "noisy_name", "opaque", "double_extension"}
