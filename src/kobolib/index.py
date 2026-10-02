from __future__ import annotations

import os
import re
import sqlite3
import time
from collections import defaultdict
from dataclasses import astuple, fields
from pathlib import Path

from kobolib.covers import THUMBNAIL_FORMATS, ensure_cover
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


def records(root: Path, cover_cache: Path, exclude: tuple[Path, ...], base: Path | None = None):
    for path in iter_books(root, exclude):
        book = read_book(path, base or root)
        yield to_record(book, ensure_cover(book, cover_cache, thumbnails=False))


def source_records(roots: list[Path], cover_cache: Path, exclude: tuple[Path, ...]):
    for root in roots:
        yield from records(root, cover_cache, exclude, base=root.parent)


def thumbnail_candidates(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    formats = ", ".join(f"'{f}'" for f in sorted(THUMBNAIL_FORMATS))
    return conn.execute(f"SELECT path, rel_path, format FROM books WHERE cover = '' AND partial = 0 AND format IN ({formats})").fetchall()


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


def build_sources_index(
    roots: list[Path], db_path: Path, cover_cache: Path, thumbnails: bool = True, exclude: tuple[Path, ...] = ()
) -> int:
    return rebuild(db_path, source_records(roots, cover_cache, exclude), cover_cache, thumbnails)


def add_book(db_path: Path, path: Path, root: Path, cover_cache: Path) -> Book:
    book = read_book(path, root)
    record = to_record(book, ensure_cover(book, cover_cache))
    with sqlite3.connect(db_path) as conn:
        conn.execute(INSERT_SQL, record)
    return book


TAG_SQL = "UPDATE books SET genre = ?, tags = ? WHERE fingerprint = ?"


def tag_values(fingerprint: str, tag: Tag) -> tuple[str, str, str]:
    return tag.genre, ",".join(tag.tags), fingerprint


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
        return self.one("fingerprint = ?", fingerprint)

    def by_rel_path(self, rel_path: str) -> Row | None:
        return self.one("rel_path = ?", rel_path)

    def one(self, condition: str, value: str) -> Row | None:
        with self.connect() as conn:
            return conn.execute(f"SELECT {', '.join(COLUMNS)} FROM books WHERE {condition}", (value,)).fetchone()

    def unclassified(self, query: str = "") -> list[Row]:
        with self.connect() as conn:
            rows = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM books WHERE genre = '' ORDER BY mtime").fetchall()
        return [r for r in rows if matches(r, query)]

    def genres(self) -> list[str]:
        return self.distinct("genre")

    def folders(self) -> list[str]:
        return self.distinct("folder")

    def distinct(self, column: str) -> list[str]:
        with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as conn:
            return [v for (v,) in conn.execute(f"SELECT DISTINCT {column} FROM books WHERE {column} != '' ORDER BY {column}")]

    def fingerprints_among(self, fingerprints: list[str]) -> set[str]:
        if not fingerprints:
            return set()
        marks = ", ".join("?" for _ in fingerprints)
        with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as conn:
            return {fp for (fp,) in conn.execute(f"SELECT fingerprint FROM books WHERE fingerprint IN ({marks})", fingerprints)}

    def write_genres(self, genres: dict[str, str]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany("UPDATE books SET genre = ? WHERE fingerprint = ?", [(g, fp) for fp, g in genres.items()])

    def write_tags(self, store: TagStore) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(TAG_SQL, [tag_values(fp, tag) for fp, tag in store.entries.items()])

    def write_tag(self, fingerprint: str, tag: Tag) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(TAG_SQL, tag_values(fingerprint, tag))

    def relocate(self, src: str, dst: str, root: Path) -> None:
        if set_aside(dst):
            return self.remove(src)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE books SET rel_path = ?, path = ?, folder = ? WHERE rel_path = ?",
                (dst, str(root / dst), str(Path(dst).parent), src),
            )

    def remove(self, rel_path: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM books WHERE rel_path = ?", (rel_path,))

    def duplicates(self) -> list[DuplicateGroup]:
        with self.connect() as conn:
            rows = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM books WHERE norm_title != '' ORDER BY norm_title, rel_path").fetchall()
        groups = defaultdict(list)
        for row in rows:
            groups[row.norm_title].append(row)
        return [DuplicateGroup(books[0].title, books) for books in groups.values() if len(books) > 1]


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
