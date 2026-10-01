from __future__ import annotations

import csv
from collections import Counter
from dataclasses import astuple, dataclass
from pathlib import Path

from kobolib.index import Row
from kobolib.lint import Finding, all_folders
from kobolib.naming import destination
from kobolib.tags import TagStore, genre_from_folder

FORMAT_RANK = ("epub", "kepub", "fb2", "mobi", "azw3", "azw", "pdf", "djvu")
TRASH = "_trash"
DUPS = "_dups"
FIELDS = ("kind", "src", "dst", "reason")


@dataclass
class Operation:
    kind: str
    src: str
    dst: str
    reason: str


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


def desired(rows: list[Row], store: TagStore) -> dict[str, str]:
    folders = all_folders(rows)
    series_counts = Counter(r.series for r in rows if r.series and not r.partial)
    return {
        r.rel_path: destination(r, store.genre_of(r), folders, series_counts[r.series])
        for r in rows
        if not r.partial and store.genre_of(r)
    }


def relocations(rows: list[Row], store: TagStore, settled: set[str]) -> list[Operation]:
    wanted = {src: dst for src, dst in desired(rows, store).items() if src not in settled}
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


def plan(rows: list[Row], findings: list[Finding], store: TagStore) -> list[Operation]:
    by_path = {r.rel_path: r for r in rows}
    ops = trash_junk(findings) + set_aside_duplicates(findings, by_path)
    settled = {o.src for o in ops}
    return ops + relocations(rows, store, settled)


def write_plan(ops: list[Operation], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(FIELDS)
        writer.writerows(astuple(o) for o in ops)


def read_plan(path: Path) -> list[Operation]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle, delimiter="\t")
        next(reader, None)
        return [Operation(*fields) for fields in reader if fields]
