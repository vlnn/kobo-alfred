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
from kobolib.tags import TagStore

SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS books USING fts5(
    title, authors, series, series_index, folder, rel_path,
    path UNINDEXED, format UNINDEXED, partial UNINDEXED, language UNINDEXED,
    year UNINDEXED, publisher UNINDEXED, source UNINDEXED, cover UNINDEXED,
    size UNINDEXED, mtime UNINDEXED, norm_title UNINDEXED, fingerprint UNINDEXED,
    genre UNINDEXED, tags UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""

COLUMNS = (
    "title", "authors", "series", "series_index", "folder", "rel_path", "path", "format",
    "partial", "language", "year", "publisher", "source", "cover", "size", "mtime", "norm_title",
    "fingerprint", "genre", "tags",
)

FILTER_SQL = {
    "fmt": "format = :fmt",
    "in": "lower(folder) LIKE '%' || :in || '%'",
    "lang": "lower(language) = :lang",
    "year": "year = :year",
    "genre": "(genre = :genre OR genre LIKE :genre || '/%')",
    "tag": "',' || tags || ',' LIKE '%,' || :tag || ',%'",
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
    fingerprint: str
    genre: str
    tags: str


@dataclass
class DuplicateGroup:
    title: str
    books: list[Row]


LEADING_ARTICLE = re.compile(r"^(?:the|a|an)\s+")


def normalize_title(title: str) -> str:
    return re.sub(r"[^\w]+", " ", title.lower()).strip()


def series_key(series: str) -> str:
    return LEADING_ARTICLE.sub("", normalize_title(series))


def to_record(book: Book, cover: Path | None) -> tuple:
    return (
        book.title, "; ".join(book.authors), book.series, book.series_index,
        str(Path(book.rel_path).parent), book.rel_path, book.path, book.format,
        int(book.partial), book.language, book.year, book.publisher, book.source,
        str(cover) if cover else "", book.size, book.mtime, normalize_title(book.title),
        book.fingerprint, "", "",
    )


def records(root: Path, cover_cache: Path, exclude: tuple[Path, ...], base: Path | None = None):
    for path in iter_books(root, exclude):
        book = read_book(path, base or root)
        yield to_record(book, ensure_cover(book, cover_cache, thumbnails=False))


def source_records(roots: list[Path], cover_cache: Path, exclude: tuple[Path, ...]):
    for root in roots:
        yield from records(root, cover_cache, exclude, base=root.parent)


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


def index_busy(db_path: Path) -> bool:
    lock = lock_path(db_path)
    return lock.exists() and time.time() - lock.stat().st_mtime < LOCK_MAX_AGE


def acquire_lock(db_path: Path) -> Path:
    lock = lock_path(db_path)
    if index_busy(db_path):
        raise IndexBusy(f"another index run is in progress ({lock})")
    lock.write_text(str(os.getpid()))
    return lock


INSERT_SQL = f"INSERT INTO books ({', '.join(COLUMNS)}) VALUES ({', '.join('?' for _ in COLUMNS)})"


def write_database(target: Path, rows) -> int:
    with sqlite3.connect(target) as conn:
        conn.executescript(SCHEMA)
        return conn.executemany(INSERT_SQL, rows).rowcount


def rebuild(db_path: Path, rows, cover_cache: Path, thumbnails: bool) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    lock = acquire_lock(db_path)
    temp = db_path.with_suffix(".tmp")
    try:
        temp.unlink(missing_ok=True)
        count = write_database(temp, rows)
        os.replace(temp, db_path)
        if thumbnails and count:
            fill_thumbnails(db_path, cover_cache)
        return count
    finally:
        temp.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def build_index(root: Path, db_path: Path, cover_cache: Path, thumbnails: bool = True, exclude: tuple[Path, ...] = ()) -> int:
    return rebuild(db_path, records(root, cover_cache, exclude), cover_cache, thumbnails)


def build_sources_index(roots: list[Path], db_path: Path, cover_cache: Path, thumbnails: bool = True, exclude: tuple[Path, ...] = ()) -> int:
    return rebuild(db_path, source_records(roots, cover_cache, exclude), cover_cache, thumbnails)


def add_book(db_path: Path, path: Path, root: Path, cover_cache: Path) -> Book:
    book = read_book(path, root)
    record = to_record(book, ensure_cover(book, cover_cache))
    with sqlite3.connect(db_path) as conn:
        conn.execute(INSERT_SQL, record)
    return book


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

    def by_fingerprint(self, fingerprint: str) -> Row | None:
        with self.connect() as conn:
            return conn.execute(f"SELECT {', '.join(COLUMNS)} FROM books WHERE fingerprint = ?", (fingerprint,)).fetchone()

    def write_tags(self, store: TagStore) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "UPDATE books SET genre = ?, tags = ? WHERE fingerprint = ?",
                [(tag.genre, ",".join(tag.tags), fp) for fp, tag in store.entries.items()],
            )

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
