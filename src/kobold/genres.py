from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from kobold.model import GenreEntry, Row
from kobold.store import TsvStore

GENRE_DEPTH = 2
ORDER_PREFIX = re.compile(r"^\d+_")
UNCLASSIFIED_FOLDERS = {"inbox", "archives", "system_files", "_inbox", "_dups", "_trash", "_broken"}


def folder_slug(name: str) -> str:
    return ORDER_PREFIX.sub("", name).lower()


def genre_from_folder(folder: str) -> str:
    parts = [folder_slug(p) for p in Path(folder).parts if p not in (".", "")]
    if not parts or parts[0] in UNCLASSIFIED_FOLDERS:
        return ""
    return "/".join(parts[:GENRE_DEPTH])


class GenreStore(TsvStore):
    fields = ("fingerprint", "genre", "rel_path")

    def to_fields(self, key: str, entry: GenreEntry) -> dict:
        return {"fingerprint": key, "genre": entry.genre, "rel_path": entry.rel_path}

    def from_fields(self, record: dict) -> tuple[str, GenreEntry]:
        return record["fingerprint"], GenreEntry(genre=record["genre"], rel_path=record["rel_path"])

    def genre_of(self, row: Row) -> str:
        entry = self.get(row.fingerprint)
        return entry.genre if entry else ""

    def rekey(self, rows: list[Row]) -> None:
        current = {row.fingerprint for row in rows}
        by_path = {row.rel_path: row.fingerprint for row in rows}
        stale = [fp for fp, entry in self.entries.items() if fp not in current and entry.rel_path in by_path]
        for old in stale:
            entry = self.entries.pop(old)
            self.entries[by_path[entry.rel_path]] = entry

    def bootstrap(self, rows: list[Row]) -> int:
        self.rekey(rows)
        added = 0
        for row in rows:
            current = self.get(row.fingerprint) or GenreEntry()
            genre = current.genre or genre_from_folder(row.folder)
            added += int(not current.genre and bool(genre))
            self.set(row.fingerprint, replace(current, genre=genre, rel_path=row.rel_path))
        return added
