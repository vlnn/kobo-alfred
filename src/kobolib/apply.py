from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from kobolib.koreader import fix_paths, sidecar_of
from kobolib.plan import Operation

EXECUTABLE = {"move", "trash", "dups"}


@dataclass
class Applied:
    done: int = 0
    skipped: list[str] = field(default_factory=list)


@dataclass
class Entry:
    batch: str
    kind: str
    src: str
    dst: str


def blocked(src: Path, dst: Path) -> str:
    if not src.exists():
        return "source missing"
    if dst.exists():
        return "destination exists"
    return ""


def prune_empty_dirs(folder: Path, root: Path) -> None:
    while folder != root and folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
        folder = folder.parent


def relocate(src: Path, dst: Path, root: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)
    if sidecar_of(src).is_dir() and not sidecar_of(dst).exists():
        os.replace(sidecar_of(src), sidecar_of(dst))
    prune_empty_dirs(src.parent, root)


def append(journal: Path, entries: list[Entry]) -> None:
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry.__dict__, ensure_ascii=False) + "\n")


def read_journal(journal: Path) -> list[Entry]:
    if not journal.exists():
        return []
    return [Entry(**json.loads(line)) for line in journal.read_text(encoding="utf-8").splitlines() if line]


def new_batch() -> str:
    return str(time.time_ns())


def run(kind: str, pairs: list[tuple[str, str]], root: Path, journal: Path) -> Applied:
    result, entries, batch = Applied(), [], new_batch()
    for src, dst in pairs:
        if reason := blocked(root / src, root / dst):
            result.skipped.append(f"{src}: {reason}")
            continue
        relocate(root / src, root / dst, root)
        entries.append(Entry(batch, kind, src, dst))
        result.done += 1
    append(journal, entries)
    fix_paths(root, {e.src: e.dst for e in entries})
    return result


def apply(ops: list[Operation], root: Path, journal: Path) -> Applied:
    pairs = [(o.src, o.dst) for o in ops if o.kind in EXECUTABLE]
    return run("apply", pairs, root, journal)


def last_batch(entries: list[Entry]) -> list[Entry]:
    if not entries:
        return []
    return [e for e in entries if e.batch == entries[-1].batch]


def undo(root: Path, journal: Path) -> int:
    batch = last_batch(read_journal(journal))
    reversed_pairs = [(e.dst, e.src) for e in reversed(batch)]
    return run("undo", reversed_pairs, root, journal).done
