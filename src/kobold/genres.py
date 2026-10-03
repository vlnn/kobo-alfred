from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from kobold.filenames import STOPWORDS
from kobold.model import GenreEntry, Row
from kobold.store import TsvStore

GENRE_DEPTH = 2
ORDER_PREFIX = re.compile(r"^\d+_")
UNCLASSIFIED_FOLDERS = {"inbox", "archives", "system_files", "_inbox", "_dups", "_trash", "_broken"}


def folder_slug(name: str) -> str:
    return ORDER_PREFIX.sub("", name).lower()


def looks_like_person(name: str) -> bool:
    tokens = name.split()
    return 2 <= len(tokens) <= 3 and all(t[0].isupper() for t in tokens) and not any(t.lower() in STOPWORDS for t in tokens)


def is_author_folder(name: str) -> bool:
    return ", " in name or looks_like_person(name)


def genre_segments(parts: list[str]) -> list[str]:
    segments = []
    for part in parts[:GENRE_DEPTH]:
        if is_author_folder(part):
            break
        segments.append(folder_slug(part))
    return segments


def genre_from_folder(folder: str) -> str:
    parts = [p for p in Path(folder).parts if p not in (".", "")]
    if not parts or folder_slug(parts[0]) in UNCLASSIFIED_FOLDERS:
        return ""
    return "/".join(genre_segments(parts))


def without_author(genre: str) -> str:
    parent, _, leaf = genre.rpartition("/")
    return parent if parent and ", " in leaf else genre


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
            genre = without_author(current.genre) or genre_from_folder(row.folder)
            added += int(not current.genre and bool(genre))
            self.set(row.fingerprint, replace(current, genre=genre, rel_path=row.rel_path))
        return added
