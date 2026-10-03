from __future__ import annotations

import csv
from collections.abc import Hashable, Iterable
from pathlib import Path
from typing import Any


class TsvStore:
    fields: tuple[str, ...] = ()

    def __init__(self, path: Path):
        self.path = path
        self.entries: dict[Any, Any] = {}

    def to_fields(self, key: Hashable, entry: Any) -> dict:
        raise NotImplementedError

    def from_fields(self, record: dict) -> tuple[Hashable, Any]:
        raise NotImplementedError

    def fingerprint_of(self, key: Hashable) -> str:
        return str(key)

    def load(self):
        if self.path.exists():
            self.entries = dict(self.read())
        return self

    def read(self) -> Iterable[tuple[Hashable, Any]]:
        with self.path.open(newline="", encoding="utf-8") as handle:
            return [self.from_fields(r) for r in csv.DictReader(handle, delimiter="\t")]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, self.fields, delimiter="\t")
            writer.writeheader()
            writer.writerows(self.to_fields(key, entry) for key, entry in sorted(self.entries.items()))

    def get(self, key: Hashable) -> Any:
        return self.entries.get(key)

    def set(self, key: Hashable, entry: Any) -> None:
        self.entries[key] = entry

    def prune(self, fingerprints: set[str]) -> int:
        gone = [key for key in self.entries if self.fingerprint_of(key) not in fingerprints]
        for key in gone:
            del self.entries[key]
        return len(gone)
