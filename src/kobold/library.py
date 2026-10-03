from __future__ import annotations

import shutil
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import astuple, dataclass, replace
from pathlib import Path

from kobold.alfred import counted
from kobold.apply import EXECUTABLE, Applied, Entry, apply, last_batch, read_journal, undo
from kobold.authors import obvious_groups
from kobold.config import (
    author_store,
    covers_dir,
    data_dir,
    db_path,
    genre_store,
    journal_path,
    library_index,
    library_root,
    mounted_sources,
    sources,
    sources_db_path,
    suggestion_store,
    vector_store,
)
from kobold.genres import GenreStore, folder_slug, genre_from_folder, without_author
from kobold.index import Index, IndexBusy, build_index, build_sources_index
from kobold.lint import all_folders, author_folders, lint
from kobold.metadata import is_sound, read_book
from kobold.model import Finding, GenreEntry, Operation, Row
from kobold.naming import canonical_name, fat_safe, known_authors
from kobold.paths import relative_path
from kobold.plan import TRASH, aside, plan, relocations
from kobold.scan import probe_root
from kobold.suggestions import LIBRARY, SuggestionStore

SUGGESTED = "suggested"
MERGE = f"{SUGGESTED} merge into "


def all_rows(index: Index) -> list[Row]:
    return index.everything()


def bootstrap_genres() -> int:
    store, index = genre_store(), library_index()
    added = store.bootstrap(all_rows(index))
    store.save()
    index.write_genres({fingerprint: entry.genre for fingerprint, entry in store.entries.items()})
    return added


def prune_suggestions(index: Index) -> None:
    present = {row.fingerprint for row in all_rows(index)}
    store = suggestion_store()
    if store.prune(present):
        store.save()
    if vector_store().path.exists():
        vector_store().prune(present)


def is_path(reference: str) -> bool:
    return reference.startswith("/")


def row_by_reference(reference: str, index: Index) -> Row | None:
    if is_path(reference):
        return index.by_rel_path(relative_path(Path(reference), library_root()))
    return index.by_fingerprint(reference)


def genre_text(raw: str) -> str:
    return without_author(raw.strip().lower())


Outcome = tuple[bool, str]


def set_genres(assignments: list[tuple[Row, str]], index: Index, store: GenreStore) -> list[Outcome]:
    for row, genre in assignments:
        store.set(row.fingerprint, GenreEntry(genre=genre, rel_path=row.rel_path))
    store.save()
    index.write_genres({row.fingerprint: genre for row, genre in assignments})
    forget_suggestions([row.fingerprint for row, _ in assignments], "genre")
    return rehome([row for row, _ in assignments], index, store)


def forget_suggestions(fingerprints: list[str], question: str) -> None:
    store = suggestion_store()
    for fingerprint in fingerprints:
        store.drop(fingerprint, question)
    if store.entries or store.path.exists():
        store.save()


def known_genres(index: Index, store: GenreStore) -> list[str]:
    from_store = {e.genre for e in store.entries.values() if e.genre}
    from_folders = {g for f in index.folders() if (g := genre_from_folder(f))}
    return sorted(from_store | from_folders | set(index.genres()))


def inbox_note() -> str:
    waiting = len(library_index().unclassified([]))
    return f" · {counted(waiting, 'book')} without a genre" if waiting else ""


def run_index() -> tuple[int, str]:
    root = library_root()
    if not root.exists():
        return 1, f"Library root not mounted: {root}"
    try:
        count = build_index(root, db_path(), covers_dir(), exclude=(data_dir(),))
    except IndexBusy:
        return 1, "Indexing is already running"
    if count == 0:
        return 1, f"No books found: {probe_root(root) or f'no ebook files under {root}'}"
    bootstrap_genres()
    prune_suggestions(library_index())
    return 0, f"Indexed {count} books from {root}"


def run_index_sources() -> tuple[int, str]:
    if not sources():
        return 1, "No sources configured: set KOBOLD_SOURCES (paths separated by ':')"
    found, missing = mounted_sources()
    if not found:
        return 1, f"No source is mounted: {', '.join(map(str, missing))}"
    try:
        count = build_sources_index(found, sources_db_path(), covers_dir(), exclude=(data_dir(),))
    except IndexBusy:
        return 1, "Indexing is already running"
    skipped = f", skipped {len(missing)} unmounted: {', '.join(map(str, missing))}" if missing else ""
    return 0, f"Indexed {count} books from {len(found)} sources{skipped}"


def unclassified_rows(words: list[str]) -> list[Row]:
    return library_index().unclassified(words)


def diagnosis() -> tuple[list[Finding], list[Operation]]:
    rows, store = all_rows(library_index()), genre_store()
    found = lint(rows, library_root(), exclude=(data_dir(),))
    return found, plan(rows, found, store, author_store().aliases)


def current_plan() -> list[Operation]:
    return diagnosis()[1]


def confident_names(store: SuggestionStore) -> dict[str, dict]:
    return {fp: a for fp, a in store.answers("name").items() if a.get("confident") and a.get("title")}


def renamed(row: Row, answer: dict, known: frozenset[str]) -> Operation | None:
    proposed = replace(row, title=answer["title"], authors="; ".join(answer["authors"]))
    name = canonical_name(proposed, known, author_store().aliases)
    if name == Path(row.rel_path).name:
        return None
    return Operation("move", row.rel_path, str(Path(row.rel_path).with_name(name)), f"{SUGGESTED} title and author")


def suggested_renames(rows: list[Row], store: SuggestionStore) -> list[Operation]:
    names, known = confident_names(store), frozenset(known_authors(all_folders(rows)))
    proposals = (renamed(r, names[r.fingerprint], known) for r in rows if r.fingerprint in names and not r.partial)
    return [op for op in proposals if op is not None]


def model_groups(store: SuggestionStore) -> list[dict]:
    return store.answers("authors").get(LIBRARY, {}).get("groups", [])


def folder_counts(rows: list[Row]) -> Counter:
    counts: Counter = Counter()
    for folder, books in author_folders(rows).items():
        counts[Path(folder).name] += books
    return counts


def claimed_by(groups: list[dict]) -> set[str]:
    return {name for g in groups for name in (g["canonical"], *g["aliases"])}


def unclaimed(group: dict, claimed: set[str]) -> dict:
    return {"canonical": group["canonical"], "aliases": [a for a in group["aliases"] if a not in claimed]}


def author_groups(rows: list[Row], store: SuggestionStore) -> list[dict]:
    groups = model_groups(store)
    claimed = claimed_by(groups)
    obvious = (unclaimed(g, claimed) for g in obvious_groups(folder_counts(rows)) if g["canonical"] not in claimed)
    return groups + [g for g in obvious if g["aliases"]]


def merged(row: Row, canonical: str, known: frozenset[str]) -> Operation:
    name = canonical_name(row, known, {Path(row.folder).name: canonical})
    dst = Path(row.folder).parent / fat_safe(canonical) / name
    return Operation("move", row.rel_path, dst.as_posix(), f"{MERGE}{canonical}")


def group_merges(rows: list[Row], group: dict, known: frozenset[str]) -> list[Operation]:
    aliases = set(group["aliases"]) - {group["canonical"]}
    return [merged(r, group["canonical"], known) for r in rows if Path(r.folder).name in aliases and not r.partial]


def suggested_merges(rows: list[Row], store: SuggestionStore) -> list[Operation]:
    known = frozenset(known_authors(all_folders(rows)))
    return [op for group in author_groups(rows, store) for op in group_merges(rows, group, known)]


def suggested_operations(rows: list[Row], settled: set[str]) -> list[Operation]:
    store = suggestion_store()
    return [op for op in suggested_renames(rows, store) + suggested_merges(rows, store) if op.src not in settled]


def merge_target(op: Operation) -> str:
    return op.reason.removeprefix(MERGE)


def is_merge(op: Operation) -> bool:
    return op.reason.startswith(MERGE)


def is_suggested(op: Operation) -> bool:
    return op.reason.startswith(SUGGESTED)


def concerning(words: list[str]) -> Callable[[str], bool]:
    if not words:
        return lambda rel_path: True
    return library_index().rel_paths(words).__contains__


def targeted(targets: list[str]) -> Callable[[str], bool]:
    paths = {relative_path(Path(t), library_root()) for t in targets if is_path(t)}
    by_words = concerning([t for t in targets if not is_path(t)])
    return lambda rel_path: (not paths or rel_path in paths) and by_words(rel_path)


def fix_operations(targets: list[str]) -> list[Operation]:
    wanted = targeted(targets)
    certain = [o for o in current_plan() if o.kind in EXECUTABLE and wanted(o.src)]
    if not targets:
        return certain
    suggested = suggested_operations(all_rows(library_index()), {o.src for o in certain})
    return certain + [o for o in suggested if wanted(o.src)]


def learn_aliases(ops: list[Operation], moved: dict[str, str]) -> None:
    learned = {Path(o.src).parent.name: merge_target(o) for o in ops if is_merge(o) and o.src in moved}
    if not learned:
        return
    store = author_store()
    store.learn(learned)
    store.save()


def undone_alias(entry: Entry, aliases: Mapping[str, str]) -> str:
    alias, canonical = Path(entry.src).parent.name, Path(entry.dst).parent.name
    return alias if aliases.get(alias) == canonical else ""


def unlearn_aliases(batch: list[Entry]) -> None:
    store = author_store()
    forgotten = [alias for e in batch if (alias := undone_alias(e, store.aliases))]
    if forgotten:
        store.forget(forgotten)
        store.save()


def undo_fixes() -> int:
    unlearn_aliases(last_batch(read_journal(journal_path())))
    return undo(library_root(), journal_path())


def apply_fixes(ops: list[Operation]) -> Applied:
    index = library_index()
    acted = [index.by_rel_path(o.src) for o in ops if is_suggested(o)]
    result = apply(ops, library_root(), journal_path())
    forget_suggestions([r.fingerprint for r in acted if r and r.rel_path in result.moved], "name")
    learn_aliases(ops, result.moved)
    refresh_index(result)
    return result


def dismiss_book(reference: str) -> str:
    row = row_by_reference(reference, library_index())
    if row is None:
        return ""
    store = suggestion_store()
    store.dismiss(row.fingerprint)
    store.save()
    return row.title


def pending_operations() -> list[Operation]:
    return fix_operations([])


def trash_operations(rows: list[Row]) -> list[Operation]:
    return [aside("trash", TRASH, row, "set aside by hand") for row in rows]


def operation_line(op: Operation) -> str:
    return "\t".join(astuple(op))


def refresh_index(result: Applied) -> None:
    index, store = library_index(), genre_store()
    for src, dst in result.moved.items():
        if (row := index.by_rel_path(src)) and (entry := store.get(row.fingerprint)):
            store.set(row.fingerprint, replace(entry, rel_path=dst))
        index.relocate(src, dst)
    for src in result.removed:
        index.remove(src)
    store.save()
    prune_suggestions(index)


def skip_reasons(skipped: list[str]) -> str:
    reasons = sorted({s.rpartition(": ")[2] for s in skipped})
    return ", ".join(reasons)


def apply_summary(result) -> str:
    if not result.skipped:
        return f"Applied {result.done}"
    return f"Applied {result.done}, skipped {len(result.skipped)} ({skip_reasons(result.skipped)})"


def outcome(row: Row, ops: dict[str, Operation], result: Applied) -> Outcome:
    op = ops.get(row.rel_path)
    if op is None:
        return False, "stays put (no author or already home)"
    if row.rel_path in result.moved:
        return True, f"moved → {Path(op.dst).parent}/"
    reason = op.reason if op.kind == "skip" else skip_reasons([s for s in result.skipped if s.startswith(f"{row.rel_path}: ")])
    return False, f"not moved: {reason}"


def rehome(rows: list[Row], index: Index, store: GenreStore) -> list[Outcome]:
    everything = all_rows(index)
    settled = {r.rel_path for r in everything} - {r.rel_path for r in rows}
    ops = {op.src: op for op in relocations(everything, store, settled, author_store().aliases)}
    result = apply(list(ops.values()), library_root(), journal_path())
    refresh_index(result)
    return [outcome(row, ops, result) for row in rows]


def inbox_folder() -> Path:
    root = library_root()
    existing = next((p for p in sorted(root.iterdir()) if p.is_dir() and folder_slug(p.name) == "inbox"), None)
    return existing or root / "_inbox"


def import_blocked(src: Path, dst: Path) -> str:
    if not src.is_file():
        return f"source missing: {src}"
    if dst.exists():
        return f"destination exists: {relative_path(dst, library_root())}"
    book = read_book(src, src.parent)
    if not is_sound(book):
        return f"unreadable or unfinished file: {src.name}"
    if (copy := library_index().by_fingerprint(book.fingerprint)) is not None:
        return f"already in library: {copy.rel_path}"
    return ""


def transfer(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def not_in_library(rows: list[Row]) -> list[Row]:
    copies = library_index().fingerprints_among([r.fingerprint for r in rows]) if db_path().exists() else set()
    return [r for r in rows if r.fingerprint not in copies]


@dataclass(frozen=True)
class SourceCount:
    source: Path
    total: int
    new: int


def source_of(row: Row) -> Path:
    return Path(row.root) / Path(row.rel_path).parts[0]


def source_counts(rows: list[Row]) -> list[SourceCount]:
    fresh = {r.rel_path for r in not_in_library(rows)}
    totals, news = Counter(source_of(r) for r in rows), Counter(source_of(r) for r in rows if r.rel_path in fresh)
    return [SourceCount(source, totals[source], news[source]) for source in sorted(totals)]
