from __future__ import annotations

import os
import re
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from kobolib.covers import THUMBNAIL_FORMATS, ensure_cover
from kobolib.metadata import Book, read_book
from kobolib.query import Query
from kobolib.scan import iter_books

SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS books USING fts5(
    title, authors, series, series_index, folder, rel_path,
    path UNINDEXED, format UNINDEXED, partial UNINDEXED, language UNINDEXED,
    year UNINDEXED, publisher UNINDEXED, source UNINDEXED, cover UNINDEXED,
    size UNINDEXED, mtime UNINDEXED, norm_title UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""

COLUMNS = (
    "title", "authors", "series", "series_index", "folder", "rel_path", "path", "format",
    "partial", "language", "year", "publisher", "source", "cover", "size", "mtime", "norm_title",
)

FILTER_SQL = {
    "fmt": "format = :fmt",
    "in": "lower(folder) LIKE '%' || :in || '%'",
    "lang": "lower(language) = :lang",
    "year": "year = :year",
}


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


@dataclass
class DuplicateGroup:
    title: str
    books: list[Row]


def normalize_title(title: str) -> str:
    return re.sub(r"[^\w]+", " ", title.lower()).strip()


def to_record(book: Book, cover: Path | None) -> tuple:
    return (
        book.title, "; ".join(book.authors), book.series, book.series_index,
        str(Path(book.rel_path).parent), book.rel_path, book.path, book.format,
        int(book.partial), book.language, book.year, book.publisher, book.source,
        str(cover) if cover else "", book.size, book.mtime, normalize_title(book.title),
    )


def records(root: Path, cover_cache: Path):
    for path in iter_books(root):
        book = read_book(path, root)
        yield to_record(book, ensure_cover(book, cover_cache, thumbnails=False))


def thumbnail_candidates(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    formats = ", ".join(f"'{f}'" for f in sorted(THUMBNAIL_FORMATS))
    return conn.execute(
        f"SELECT path, rel_path, format FROM books WHERE cover = '' AND partial = 0 AND format IN ({formats})"
    ).fetchall()


def fill_thumbnails(db_path: Path, cover_cache: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        candidates = thumbnail_candidates(conn)
    made = 0
    for path, rel_path, fmt in candidates:
        book = Book(path=path, rel_path=rel_path, format=fmt, partial=False)
        cover = ensure_cover(book, cover_cache)
        if cover is None:
            continue
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE books SET cover = ? WHERE rel_path = ?", (str(cover), rel_path))
        made += 1
    return made


LOCK_MAX_AGE = 3600


class IndexBusy(RuntimeError):
    pass


def lock_path(db_path: Path) -> Path:
    return db_path.with_suffix(".lock")


def acquire_lock(db_path: Path) -> Path:
    lock = lock_path(db_path)
    if lock.exists() and time.time() - lock.stat().st_mtime < LOCK_MAX_AGE:
        raise IndexBusy(f"another index run is in progress ({lock})")
    lock.write_text(str(os.getpid()))
    return lock


def write_database(target: Path, root: Path, cover_cache: Path) -> int:
    placeholders = ", ".join("?" for _ in COLUMNS)
    with sqlite3.connect(target) as conn:
        conn.executescript(SCHEMA)
        cursor = conn.executemany(
            f"INSERT INTO books ({', '.join(COLUMNS)}) VALUES ({placeholders})",
            records(root, cover_cache),
        )
        return cursor.rowcount


def build_index(root: Path, db_path: Path, cover_cache: Path, thumbnails: bool = True) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    lock = acquire_lock(db_path)
    temp = db_path.with_suffix(".tmp")
    try:
        temp.unlink(missing_ok=True)
        count = write_database(temp, root, cover_cache)
        os.replace(temp, db_path)
        if thumbnails and count:
            fill_thumbnails(db_path, cover_cache)
        return count
    finally:
        temp.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def row_factory(cursor, values) -> Row:
    data = dict(zip([c[0] for c in cursor.description], values))
    data["partial"] = bool(data["partial"])
    return Row(**data)


class Index:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = row_factory
        return conn

    def count(self) -> int:
        with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as conn:
            return conn.execute("SELECT count(*) FROM books").fetchone()[0]

    def search(self, query: Query, limit: int = 40) -> list[Row]:
        clauses, params = where_clauses(query)
        order = "rank, title" if query.fts_match() else "mtime DESC"
        sql = f"SELECT {', '.join(COLUMNS)} FROM books"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += f" ORDER BY {order} LIMIT :limit"
        with self.connect() as conn:
            return conn.execute(sql, {**params, "limit": limit}).fetchall()

    def duplicates(self) -> list[DuplicateGroup]:
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT {', '.join(COLUMNS)} FROM books WHERE norm_title != '' ORDER BY norm_title, rel_path"
            ).fetchall()
        groups = defaultdict(list)
        for row in rows:
            groups[row.norm_title].append(row)
        return [DuplicateGroup(books[0].title, books) for books in groups.values() if len(books) > 1]


def where_clauses(query: Query) -> tuple[list[str], dict]:
    clauses, params = [], {}
    if match := query.fts_match():
        clauses.append("books MATCH :match")
        params["match"] = match
    for key, sql in FILTER_SQL.items():
        if key in query.filters:
            clauses.append(sql)
            params[key] = query.filters[key]
    if query.filters.get("is") == "partial":
        clauses.append("partial = 1")
    if query.filters.get("is") == "complete":
        clauses.append("partial = 0")
    return clauses, params
