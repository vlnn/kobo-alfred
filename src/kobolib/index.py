from __future__ import annotations

import os
import re
import sqlite3
import time
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import astuple, fields
from pathlib import Path

from kobolib.covers import THUMBNAIL_FORMATS, cover_key, ensure_cover
from kobolib.metadata import read_book
from kobolib.model import Book, DuplicateGroup, Row, Tag
from kobolib.query import SQL_CLAUSES, STATE_CLAUSES, Query
from kobolib.scan import SKIP_FOLDERS, iter_books
from kobolib.tags import TagStore

COLUMNS = tuple(f.name for f in fields(Row))
SEARCHABLE = {"title", "authors", "series", "series_index", "folder", "rel_path"}
SCHEMA = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS books USING fts5(
    {", ".join(c if c in SEARCHABLE else f"{c} UNINDEXED" for c in COLUMNS)},
    tokenize = 'unicode61 remove_diacritics 2'
);
"""

LEADING_ARTICLE = re.compile(r"^(?:the|a|an)\s+")


def normalize_title(title: str) -> str:
    return re.sub(r"[^\w]+", " ", title.lower()).strip()


def series_key(series: str) -> str:
    return LEADING_ARTICLE.sub("", normalize_title(series))


def to_row(book: Book, cover: Path | None) -> Row:
    return Row(
        title=book.title,
        authors="; ".join(book.authors),
        series=book.series,
        series_index=book.series_index,
        folder=str(Path(book.rel_path).parent),
        rel_path=book.rel_path,
        path=book.path,
        format=book.format,
        partial=book.partial,
        language=book.language,
        year=book.year,
        publisher=book.publisher,
        source=book.source,
        cover=str(cover) if cover else "",
        size=book.size,
        mtime=book.mtime,
        norm_title=normalize_title(book.title),
        fingerprint=book.fingerprint,
        genre="",
        tags="",
    )


def to_record(book: Book, cover: Path | None) -> tuple:
    return astuple(to_row(book, cover))


def records(root: Path, cover_cache: Path, exclude: tuple[Path, ...], base: Path | None = None) -> Iterator[tuple]:
    for path in iter_books(root, exclude):
        book = read_book(path, base or root)
        yield to_record(book, ensure_cover(book, cover_cache, thumbnails=False))


def source_records(roots: list[Path], cover_cache: Path, exclude: tuple[Path, ...]) -> Iterator[tuple]:
    for root in roots:
        yield from records(root, cover_cache, exclude, base=root.parent)


@contextmanager
def reading(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.create_function("fold", 1, str.casefold, deterministic=True)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def writing(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def thumbnail_candidates(db_path: Path) -> list[Book]:
    formats = ", ".join(f"'{f}'" for f in sorted(THUMBNAIL_FORMATS))
    with reading(db_path) as conn:
        found = conn.execute(
            f"SELECT path, rel_path, format FROM books WHERE cover = '' AND partial = 0 AND format IN ({formats})"
        ).fetchall()
    return [Book(path=path, rel_path=rel_path, format=fmt, partial=False) for path, rel_path, fmt in found]


def fill_thumbnails(db_path: Path, cover_cache: Path) -> int:
    made = 0
    for book in thumbnail_candidates(db_path):
        cover = ensure_cover(book, cover_cache)
        if cover is None:
            continue
        with writing(db_path) as conn:
            conn.execute("UPDATE books SET cover = ? WHERE rel_path = ?", (str(cover), book.rel_path))
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


def write_database(target: Path, rows: Iterator[tuple]) -> int:
    with writing(target) as conn:
        conn.executescript(SCHEMA)
        return conn.executemany(INSERT_SQL, rows).rowcount


def rebuild(db_path: Path, rows: Iterator[tuple]) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    lock = acquire_lock(db_path)
    temp = db_path.with_suffix(".tmp")
    try:
        temp.unlink(missing_ok=True)
        count = write_database(temp, rows)
        os.replace(temp, db_path)
        return count
    finally:
        temp.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def build_index(root: Path, db_path: Path, cover_cache: Path, exclude: tuple[Path, ...] = ()) -> int:
    return rebuild(db_path, records(root, cover_cache, exclude))


def build_sources_index(roots: list[Path], db_path: Path, cover_cache: Path, exclude: tuple[Path, ...] = ()) -> int:
    return rebuild(db_path, source_records(roots, cover_cache, exclude))


def add_book(db_path: Path, path: Path, root: Path, cover_cache: Path) -> Book:
    book = read_book(path, root)
    record = to_record(book, ensure_cover(book, cover_cache))
    with writing(db_path) as conn:
        conn.execute(INSERT_SQL, record)
    return book


TAG_SQL = "UPDATE books SET genre = ?, tags = ? WHERE fingerprint = ?"


def tag_values(fingerprint: str, tag: Tag) -> tuple[str, str, str]:
    return tag.genre, ",".join(tag.tags), fingerprint


def row_factory(cursor, values) -> Row:
    data = dict(zip([c[0] for c in cursor.description], values))
    data["partial"] = bool(data["partial"])
    return Row(**data)


SELECT_ROWS = f"SELECT {', '.join(COLUMNS)} FROM books"


class Index:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def rows(self, sql: str, params: tuple | dict = ()) -> list[Row]:
        with reading(self.db_path) as conn:
            cursor = conn.execute(sql, params)
            cursor.row_factory = row_factory
            return cursor.fetchall()

    def values(self, sql: str, params: tuple | list = ()) -> list:
        with reading(self.db_path) as conn:
            return [value for (value,) in conn.execute(sql, params)]

    def execute(self, sql: str, params: tuple = ()) -> None:
        with writing(self.db_path) as conn:
            conn.execute(sql, params)

    def execute_many(self, sql: str, rows: list[tuple]) -> None:
        with writing(self.db_path) as conn:
            conn.executemany(sql, rows)

    def count(self) -> int:
        return self.values("SELECT count(*) FROM books")[0]

    def search(self, query: Query, limit: int = 40) -> list[Row]:
        clauses, params = where_clauses(query)
        order = "rank, title" if query.fts_match() else "mtime DESC"
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.rows(f"{SELECT_ROWS}{where} ORDER BY {order} LIMIT :limit", {**params, "limit": limit})

    def by_fingerprint(self, fingerprint: str) -> Row | None:
        return self.one("fingerprint = ?", fingerprint)

    def by_rel_path(self, rel_path: str) -> Row | None:
        return self.one("rel_path = ?", rel_path)

    def one(self, condition: str, value: str) -> Row | None:
        return next(iter(self.rows(f"{SELECT_ROWS} WHERE {condition}", (value,))), None)

    def unclassified(self, query: str = "") -> list[Row]:
        return [r for r in self.rows(f"{SELECT_ROWS} WHERE genre = '' ORDER BY mtime") if matches(r, query)]

    def genres(self) -> list[str]:
        return self.distinct("genre")

    def folders(self) -> list[str]:
        return self.distinct("folder")

    def tags(self) -> list[str]:
        return self.distinct("tags")

    def distinct(self, column: str) -> list[str]:
        return self.values(f"SELECT DISTINCT {column} FROM books WHERE {column} != '' ORDER BY {column}")

    def fingerprints_among(self, fingerprints: list[str]) -> set[str]:
        if not fingerprints:
            return set()
        marks = ", ".join("?" for _ in fingerprints)
        return set(self.values(f"SELECT fingerprint FROM books WHERE fingerprint IN ({marks})", fingerprints))

    def write_genres(self, genres: dict[str, str]) -> None:
        self.execute_many("UPDATE books SET genre = ? WHERE fingerprint = ?", [(g, fp) for fp, g in genres.items()])

    def write_tags(self, store: TagStore) -> None:
        self.execute_many(TAG_SQL, [tag_values(fp, tag) for fp, tag in store.entries.items()])

    def write_tag(self, fingerprint: str, tag: Tag) -> None:
        self.execute(TAG_SQL, tag_values(fingerprint, tag))

    def relocate(self, src: str, dst: str, root: Path) -> None:
        if set_aside(dst):
            return self.remove(src)
        row = self.by_rel_path(src)
        cover = carry_cover(row.cover, dst) if row else ""
        moved = (dst, str(root / dst), str(Path(dst).parent), cover, src)
        self.execute("UPDATE books SET rel_path = ?, path = ?, folder = ?, cover = ? WHERE rel_path = ?", moved)

    def remove(self, rel_path: str) -> None:
        self.execute("DELETE FROM books WHERE rel_path = ?", (rel_path,))

    def duplicates(self) -> list[DuplicateGroup]:
        groups = defaultdict(list)
        for row in self.rows(f"{SELECT_ROWS} WHERE norm_title != '' ORDER BY norm_title, rel_path"):
            groups[row.norm_title].append(row)
        return [DuplicateGroup(books[0].title, books) for books in groups.values() if len(books) > 1]


def carry_cover(cover: str, dst: str) -> str:
    if not cover:
        return ""
    old = Path(cover)
    new = old.with_name(cover_key(dst) + old.suffix)
    if old.exists():
        os.replace(old, new)
    return str(new)


def set_aside(rel_path: str) -> bool:
    return bool(SKIP_FOLDERS & set(Path(rel_path).parts))


def matches(row: Row, query: str) -> bool:
    return query.lower() in f"{row.title} {row.authors} {row.rel_path}".lower()


def where_clauses(query: Query) -> tuple[list[str], dict]:
    clauses, params = [], {}
    if match := query.fts_match():
        clauses.append("books MATCH :match")
        params["match"] = match
    for key, sql in SQL_CLAUSES.items():
        if key in query.filters:
            clauses.append(sql)
            params[key] = query.filters[key]
    if state := STATE_CLAUSES.get(query.filters.get("is", "")):
        clauses.append(state)
    return clauses, params
