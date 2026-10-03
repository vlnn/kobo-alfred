from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from kobold.genres import GenreStore, genre_from_folder
from kobold.index import series_key
from kobold.lint import all_folders
from kobold.model import Finding, Operation, Row
from kobold.naming import NO_ALIASES, Shelves, destination, shelves

FORMAT_RANK = ("epub", "fb2", "mobi", "azw3", "azw", "pdf", "djvu")
TRASH = "_trash"
DUPS = "_dups"


def format_rank(fmt: str) -> int:
    return FORMAT_RANK.index(fmt) if fmt in FORMAT_RANK else len(FORMAT_RANK)


def year_of(row: Row) -> int:
    return int(row.year) if row.year.isdigit() else 0


def in_unclassified_folder(row: Row) -> bool:
    return not genre_from_folder(row.folder)


def preference(indexed: tuple[int, Row]) -> tuple:
    position, row = indexed
    return (row.partial, in_unclassified_folder(row), format_rank(row.format), -year_of(row), -row.size, position)


def prefer(rows: list[Row]) -> Row:
    return min(enumerate(rows), key=preference)[1]


def aside(kind: str, folder: str, row: Row, reason: str) -> Operation:
    return Operation(kind, row.rel_path, f"{folder}/{row.rel_path}", reason)


def trash_junk(findings: list[Finding]) -> list[Operation]:
    return [Operation("trash", p, f"{TRASH}/{p}", f.detail) for f in findings if f.rule == "junk" for p in f.rel_paths]


def losers(finding: Finding, by_path: dict[str, Row]) -> list[Row]:
    group = [by_path[p] for p in finding.rel_paths if p in by_path]
    winner = prefer(group)
    return [r for r in group if r is not winner]


def set_aside_duplicates(findings: list[Finding], by_path: dict[str, Row]) -> list[Operation]:
    ops = []
    for finding in findings:
        if finding.rule == "exact_duplicate":
            ops += [aside("trash", TRASH, r, "identical copy") for r in losers(finding, by_path)]
        if finding.rule == "title_duplicate":
            ops += [aside("dups", DUPS, r, finding.detail) for r in losers(finding, by_path)]
    return ops


def move_reason(src: str, dst: str) -> str:
    same_folder = Path(src).parent == Path(dst).parent
    same_name = Path(src).name == Path(dst).name
    return "rename" if same_folder else "relocate" if same_name else "relocate + rename"


@dataclass(frozen=True)
class Shape:
    layout: Shelves
    series_counts: Counter


def shape_of(rows: list[Row], aliases: Mapping[str, str] = NO_ALIASES) -> Shape:
    counts = Counter(series_key(r.series) for r in rows if r.series and not r.partial)
    return Shape(shelves(all_folders(rows), aliases), counts)


def wants_home(row: Row, store: GenreStore) -> bool:
    return not row.partial and bool(row.authors) and bool(store.genre_of(row))


def home_of(row: Row, store: GenreStore, shape: Shape) -> str:
    return destination(row, store.genre_of(row), shape.layout, shape.series_counts[series_key(row.series)])


def desired(rows: list[Row], store: GenreStore, aliases: Mapping[str, str] = NO_ALIASES) -> dict[str, str]:
    shape = shape_of(rows, aliases)
    return {r.rel_path: home_of(r, store, shape) for r in rows if wants_home(r, store)}


def relocation(row: Row, rows: list[Row], store: GenreStore, aliases: Mapping[str, str] = NO_ALIASES) -> Operation | None:
    if not wants_home(row, store):
        return None
    dst = home_of(row, store, shape_of(rows, aliases))
    if dst == row.rel_path:
        return None
    if any(r.rel_path == dst for r in rows):
        return Operation("skip", row.rel_path, dst, f"destination taken by {dst}")
    return Operation("move", row.rel_path, dst, move_reason(row.rel_path, dst))


def relocations(rows: list[Row], store: GenreStore, settled: set[str], aliases: Mapping[str, str] = NO_ALIASES) -> list[Operation]:
    wanted = {src: dst for src, dst in desired(rows, store, aliases).items() if src not in settled}
    moving = {src for src, dst in wanted.items() if src != dst}
    occupied = {r.rel_path: r.rel_path for r in rows if r.rel_path not in moving}
    ops = []
    for src in sorted(moving):
        dst = wanted[src]
        if dst in occupied:
            ops.append(Operation("skip", src, dst, f"destination taken by {occupied[dst]}"))
            continue
        occupied[dst] = src
        ops.append(Operation("move", src, dst, move_reason(src, dst)))
    return ops


def plan(rows: list[Row], findings: list[Finding], store: GenreStore, aliases: Mapping[str, str] = NO_ALIASES) -> list[Operation]:
    by_path = {r.rel_path: r for r in rows}
    ops = trash_junk(findings) + set_aside_duplicates(findings, by_path)
    settled = {o.src for o in ops}
    return ops + relocations(rows, store, settled, aliases)
