from __future__ import annotations

from dataclasses import dataclass, field

Cover = tuple[str, bytes]


@dataclass
class Book:
    path: str
    rel_path: str
    format: str
    partial: bool
    broken: bool = False
    title: str = ""
    authors: list[str] = field(default_factory=list)
    series: str = ""
    series_index: str = ""
    language: str = ""
    year: str = ""
    publisher: str = ""
    source: str = "filename"
    cover: Cover | None = None
    size: int = 0
    mtime: float = 0.0
    fingerprint: str = ""


@dataclass
class Row:
    title: str
    authors: str
    series: str
    series_index: str
    folder: str
    rel_path: str
    path: str
    format: str
    partial: bool
    language: str
    year: str
    publisher: str
    source: str
    cover: str
    size: int
    mtime: float
    norm_title: str
    fingerprint: str
    genre: str


@dataclass
class DuplicateGroup:
    title: str
    books: list[Row]


@dataclass
class GenreEntry:
    genre: str = ""
    rel_path: str = ""


@dataclass
class Finding:
    rule: str
    detail: str
    rel_paths: list[str]


@dataclass
class Operation:
    kind: str
    src: str
    dst: str
    reason: str
