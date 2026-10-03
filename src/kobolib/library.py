from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import astuple, replace
from pathlib import Path

from kobolib.alfred import counted
from kobolib.apply import EXECUTABLE, Applied, apply
from kobolib.config import (
    covers_dir,
    data_dir,
    db_path,
    genre_store,
    journal_path,
    library_root,
    mounted_sources,
    sources,
    sources_db_path,
)
from kobolib.genres import GenreStore, folder_slug, genre_from_folder
from kobolib.index import Index, IndexBusy, build_index, build_sources_index
from kobolib.lint import lint
from kobolib.metadata import is_sound, read_book
from kobolib.model import Finding, GenreEntry, Operation, Row
from kobolib.paths import relative_path
from kobolib.plan import TRASH, aside, plan, relocation
from kobolib.scan import probe_root


def all_rows(index: Index) -> list[Row]:
    return index.everything()


def bootstrap_genres() -> int:
    store, index = genre_store(), Index(db_path())
    added = store.bootstrap(all_rows(index))
    store.save()
    index.write_genres({fingerprint: entry.genre for fingerprint, entry in store.entries.items()})
    return added


def is_path(reference: str) -> bool:
    return reference.startswith("/")


def row_by_reference(reference: str, index: Index) -> Row | None:
    if is_path(reference):
        return index.by_rel_path(relative_path(Path(reference), library_root()))
    return index.by_fingerprint(reference)


def genre_text(raw: str) -> str:
    return raw.strip().lower()


def set_genre(row: Row, genre: str, index: Index, store: GenreStore) -> tuple[bool, str]:
    store.set(row.fingerprint, GenreEntry(genre=genre, rel_path=row.rel_path))
    store.save()
    index.write_genres({row.fingerprint: genre})
    return rehome(row, index, store)


def known_genres(index: Index, store: GenreStore) -> list[str]:
    from_store = {e.genre for e in store.entries.values() if e.genre}
    from_folders = {g for f in index.folders() if (g := genre_from_folder(f))}
    return sorted(from_store | from_folders | set(index.genres()))


def inbox_note() -> str:
    waiting = len(Index(db_path()).unclassified([]))
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
    return 0, f"Indexed {count} books from {root}"


def run_index_sources() -> tuple[int, str]:
    if not sources():
        return 1, "No sources configured: set KOBO_SOURCES (paths separated by ':')"
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
    return Index(db_path()).unclassified(words)


def diagnosis() -> tuple[list[Finding], list[Operation]]:
    rows, store = all_rows(Index(db_path())), genre_store()
    found = lint(rows, library_root(), exclude=(data_dir(),))
    return found, plan(rows, found, store)


def current_plan() -> list[Operation]:
    return diagnosis()[1]


def concerning(words: list[str]) -> Callable[[str], bool]:
    if not words:
        return lambda rel_path: True
    return Index(db_path()).rel_paths(words).__contains__


def targeted(targets: list[str]) -> Callable[[str], bool]:
    paths = {relative_path(Path(t), library_root()) for t in targets if is_path(t)}
    by_words = concerning([t for t in targets if not is_path(t)])
    return lambda rel_path: (not paths or rel_path in paths) and by_words(rel_path)


def fix_operations(targets: list[str]) -> list[Operation]:
    wanted = targeted(targets)
    return [o for o in current_plan() if o.kind in EXECUTABLE and wanted(o.src)]


def pending_operations() -> list[Operation]:
    return fix_operations([])


def trash_operations(rows: list[Row]) -> list[Operation]:
    return [aside("trash", TRASH, row, "set aside by hand") for row in rows]


def operation_line(op: Operation) -> str:
    return "\t".join(astuple(op))


def refresh_index(result: Applied) -> None:
    index, store = Index(db_path()), genre_store()
    for src, dst in result.moved.items():
        if (row := index.by_rel_path(src)) and (entry := store.get(row.fingerprint)):
            store.set(row.fingerprint, replace(entry, rel_path=dst))
        index.relocate(src, dst, library_root())
    for src in result.removed:
        index.remove(src)
    store.save()


def skip_reasons(skipped: list[str]) -> str:
    reasons = sorted({s.rpartition(": ")[2] for s in skipped})
    return ", ".join(reasons)


def apply_summary(result) -> str:
    if not result.skipped:
        return f"Applied {result.done}"
    return f"Applied {result.done}, skipped {len(result.skipped)} ({skip_reasons(result.skipped)})"


def rehome(row: Row, index: Index, store: GenreStore) -> tuple[bool, str]:
    op = relocation(row, all_rows(index), store)
    if op is None or op.kind != "move":
        return False, "stays put (no author or already home)"
    result = apply([op], library_root(), journal_path())
    refresh_index(result)
    if result.skipped:
        return False, f"not moved: {skip_reasons(result.skipped)}"
    return True, f"moved → {Path(op.dst).parent}/"


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
    if (copy := Index(db_path()).by_fingerprint(book.fingerprint)) is not None:
        return f"already in library: {copy.rel_path}"
    return ""


def transfer(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def not_in_library(rows: list[Row]) -> list[Row]:
    copies = Index(db_path()).fingerprints_among([r.fingerprint for r in rows]) if db_path().exists() else set()
    return [r for r in rows if r.fingerprint not in copies]
