from __future__ import annotations

import csv
import re
from dataclasses import replace
from pathlib import Path

from kobolib.model import Row, Tag

GENRE_DEPTH = 2
ORDER_PREFIX = re.compile(r"^\d+_")
UNCLASSIFIED_FOLDERS = {"inbox", "archives", "system_files", "_inbox", "_dups", "_trash", "_broken"}
FIELDS = ("fingerprint", "genre", "tags", "rel_path")
TAG_SEPARATOR = ","


def folder_slug(name: str) -> str:
    return ORDER_PREFIX.sub("", name).lower()


def genre_from_folder(folder: str) -> str:
    parts = [folder_slug(p) for p in Path(folder).parts if p not in (".", "")]
    if not parts or parts[0] in UNCLASSIFIED_FOLDERS:
        return ""
    return "/".join(parts[:GENRE_DEPTH])


def unique_sorted(tags: list[str]) -> list[str]:
    return sorted({t.strip().lower() for t in tags if t.strip()})


def to_fields(fingerprint: str, tag: Tag) -> dict:
    return {
        "fingerprint": fingerprint,
        "genre": tag.genre,
        "tags": TAG_SEPARATOR.join(unique_sorted(tag.tags)),
        "rel_path": tag.rel_path,
    }


def from_fields(record: dict) -> tuple[str, Tag]:
    tags = [t for t in record["tags"].split(TAG_SEPARATOR) if t]
    return record["fingerprint"], Tag(genre=record["genre"], tags=tags, rel_path=record["rel_path"])


class TagStore:
    def __init__(self, path: Path):
        self.path = path
        self.entries: dict[str, Tag] = {}

    def load(self) -> TagStore:
        if self.path.exists():
            with self.path.open(newline="", encoding="utf-8") as handle:
                self.entries = dict(from_fields(r) for r in csv.DictReader(handle, delimiter="\t"))
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, FIELDS, delimiter="\t")
            writer.writeheader()
            writer.writerows(to_fields(fp, tag) for fp, tag in sorted(self.entries.items()))

    def get(self, fingerprint: str) -> Tag | None:
        return self.entries.get(fingerprint)

    def set(self, fingerprint: str, tag: Tag) -> None:
        self.entries[fingerprint] = replace(tag, tags=unique_sorted(tag.tags))

    def genre_of(self, row: Row) -> str:
        tag = self.get(row.fingerprint)
        return tag.genre if tag else ""

    def bootstrap(self, rows: list[Row]) -> int:
        added = 0
        for row in rows:
            current = self.get(row.fingerprint) or Tag()
            genre = current.genre or genre_from_folder(row.folder)
            added += int(not current.genre and bool(genre))
            self.set(row.fingerprint, replace(current, genre=genre, rel_path=row.rel_path))
        return added
