from __future__ import annotations

import math
import sqlite3
from array import array
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from operator import mul
from pathlib import Path

from kobold.model import Row

NEIGHBOURS = 20
SCHEMA = """
CREATE TABLE IF NOT EXISTS vectors(
    model TEXT, fingerprint TEXT, dim INTEGER, vec BLOB, PRIMARY KEY(model, fingerprint));
CREATE TABLE IF NOT EXISTS neighbours(
    model TEXT, fingerprint TEXT, rank INTEGER, other TEXT, score REAL, PRIMARY KEY(model, fingerprint, rank));
"""
Vector = array
Scored = tuple[str, float]


def norm(values: Iterable[float]) -> float:
    return math.sqrt(sum(v * v for v in values))


def normalized(values: Iterable[float]) -> Vector:
    vector = array("f", values)
    length = norm(vector)
    return array("f", (v / length for v in vector)) if length else vector


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    a, b = array("f", a), array("f", b)
    lengths = norm(a) * norm(b)
    return sum(map(mul, a, b)) / lengths if lengths else 0.0


def unpack(blob: bytes) -> Vector:
    vector = array("f")
    vector.frombytes(blob)
    return vector


def ranked(scores: Iterable[Scored]) -> list[Scored]:
    return sorted(scores, key=lambda s: -s[1])[:NEIGHBOURS]


class VectorStore:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self, write: bool) -> Iterator[sqlite3.Connection]:
        if not write and not self.path.exists():
            yield None
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        try:
            conn.executescript(SCHEMA)
            with conn:
                yield conn
        finally:
            conn.close()

    def count(self, model: str) -> int:
        with self.connection(False) as conn:
            return conn.execute("SELECT count(*) FROM vectors WHERE model = ?", (model,)).fetchone()[0] if conn else 0

    def get(self, model: str, fingerprint: str) -> Vector | None:
        with self.connection(False) as conn:
            found = (
                conn.execute("SELECT vec FROM vectors WHERE model = ? AND fingerprint = ?", (model, fingerprint)).fetchone()
                if conn
                else None
            )
        return unpack(found[0]) if found else None

    def neighbours(self, model: str, fingerprint: str) -> list[Scored]:
        sql = "SELECT other, score FROM neighbours WHERE model = ? AND fingerprint = ? ORDER BY rank"
        with self.connection(False) as conn:
            return conn.execute(sql, (model, fingerprint)).fetchall() if conn else []

    def missing(self, model: str, rows: list[Row]) -> list[Row]:
        with self.connection(False) as conn:
            known = {fp for (fp,) in conn.execute("SELECT fingerprint FROM vectors WHERE model = ?", (model,))} if conn else set()
        return [r for r in rows if r.fingerprint not in known]

    def put(self, model: str, fingerprint: str, values: Iterable[float]) -> None:
        vector = normalized(values)
        with self.connection(True) as conn:
            others = [(fp, unpack(blob)) for fp, blob in conn.execute("SELECT fingerprint, vec FROM vectors WHERE model = ?", (model,))]
            conn.execute("INSERT OR REPLACE INTO vectors VALUES (?, ?, ?, ?)", (model, fingerprint, len(vector), vector.tobytes()))
            scores = [(fp, sum(map(mul, vector, other))) for fp, other in others if fp != fingerprint]
            write_list(conn, model, fingerprint, ranked(scores))
            for other, score in scores:
                adopt(conn, model, other, fingerprint, score)

    def prune(self, fingerprints: set[str]) -> None:
        with self.connection(True) as conn:
            stored = {fp for (fp,) in conn.execute("SELECT DISTINCT fingerprint FROM vectors")}
            for fp in stored - fingerprints:
                conn.execute("DELETE FROM vectors WHERE fingerprint = ?", (fp,))
                conn.execute("DELETE FROM neighbours WHERE fingerprint = ? OR other = ?", (fp, fp))


def write_list(conn: sqlite3.Connection, model: str, fingerprint: str, scored: list[Scored]) -> None:
    conn.execute("DELETE FROM neighbours WHERE model = ? AND fingerprint = ?", (model, fingerprint))
    conn.executemany(
        "INSERT INTO neighbours VALUES (?, ?, ?, ?, ?)",
        [(model, fingerprint, rank, other, score) for rank, (other, score) in enumerate(scored)],
    )


def adopt(conn: sqlite3.Connection, model: str, fingerprint: str, newcomer: str, score: float) -> None:
    sql = "SELECT other, score FROM neighbours WHERE model = ? AND fingerprint = ? ORDER BY rank"
    current = [(other, s) for other, s in conn.execute(sql, (model, fingerprint)) if other != newcomer]
    updated = ranked([*current, (newcomer, score)])
    if updated != current:
        write_list(conn, model, fingerprint, updated)
