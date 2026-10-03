from __future__ import annotations

import csv
import re
from dataclasses import replace
from pathlib import Path

from kobolib.model import GenreEntry, Row

GENRE_DEPTH = 2
ORDER_PREFIX = re.compile(r"^\d+_")
UNCLASSIFIED_FOLDERS = {"inbox", "archives", "system_files", "_inbox", "_dups", "_trash", "_broken"}
FIELDS = ("fingerprint", "genre", "rel_path")


def folder_slug(name: str) -> str:
    return ORDER_PREFIX.sub("", name).lower()


def genre_from_folder(folder: str) -> str:
    parts = [folder_slug(p) for p in Path(folder).parts if p not in (".", "")]
    if not parts or parts[0] in UNCLASSIFIED_FOLDERS:
        return ""
    return "/".join(parts[:GENRE_DEPTH])


def to_fields(fingerprint: str, entry: GenreEntry) -> dict:
    return {"fingerprint": fingerprint, "genre": entry.genre, "rel_path": entry.rel_path}


def from_fields(record: dict) -> tuple[str, GenreEntry]:
    return record["fingerprint"], GenreEntry(genre=record["genre"], rel_path=record["rel_path"])


def read_entries(path: Path) -> dict[str, GenreEntry]:
    with path.open(newline="", encoding="utf-8") as handle:
        return dict(from_fields(r) for r in csv.DictReader(handle, delimiter="\t"))


class GenreStore:
    def __init__(self, path: Path):
        self.path = path
        self.entries: dict[str, GenreEntry] = {}

    def load(self) -> GenreStore:
        if self.path.exists():
            self.entries = read_entries(self.path)
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, FIELDS, delimiter="\t")
            writer.writeheader()
            writer.writerows(to_fields(fp, entry) for fp, entry in sorted(self.entries.items()))

    def get(self, fingerprint: str) -> GenreEntry | None:
        return self.entries.get(fingerprint)

    def set(self, fingerprint: str, entry: GenreEntry) -> None:
        self.entries[fingerprint] = entry

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
