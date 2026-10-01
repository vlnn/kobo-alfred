from __future__ import annotations

import filecmp
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from kobolib.koreader import fix_paths, sidecar_of
from kobolib.scan import nfc
from kobolib.plan import Operation

EXECUTABLE = {"move", "trash", "dups"}
MOVES = {"apply", "undo"}


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


@dataclass
class Step:
    action: str
    src: str
    dst: str


def child_named(folder: Path, name: str) -> Path | None:
    try:
        entries = os.listdir(folder)
    except OSError:
        return None
    return next((folder / e for e in entries if nfc(e) == nfc(name)), None)


def locate(root: Path, rel: str) -> Path | None:
    current = root
    for part in PurePosixPath(rel).parts:
        current = child_named(current, part)
        if current is None:
            return None
    return current


def on_disk(root: Path, rel: str) -> Path:
    return locate(root, rel) or root / rel


def is_empty_dir(path: Path) -> bool:
    return path.is_dir() and not any(path.iterdir())


def same_content(a: Path, b: Path) -> bool:
    return a.is_file() and b.is_file() and filecmp.cmp(a, b, shallow=False)


def redundant(src: Path, dst: Path) -> str:
    if is_empty_dir(src) or same_content(src, dst):
        return ""
    return "destination exists, different content"


def prune_empty_dirs(folder: Path, root: Path) -> None:
    while folder != root and folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
        folder = folder.parent


def remove(src: Path, root: Path) -> None:
    src.rmdir() if src.is_dir() else src.unlink()
    prune_empty_dirs(src.parent, root)


def restore(src: Path, kept: Path) -> None:
    src.parent.mkdir(parents=True, exist_ok=True)
    src.mkdir() if kept.is_dir() else shutil.copy2(kept, src)


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


def execute(step: Step, kind: str, src: Path, dst: Path, root: Path) -> tuple[str, str]:
    if step.action == "restore":
        if src.exists():
            return "", "already present"
        restore(src, dst)
        return "restore", ""
    if not src.exists():
        return "", "source missing"
    if step.action == "delete" or dst.exists():
        if reason := redundant(src, dst):
            return "", reason
        remove(src, root)
        return "delete", ""
    relocate(src, dst, root)
    return kind, ""


def run(kind: str, steps: list[Step], root: Path, journal: Path) -> Applied:
    result, entries, batch = Applied(), [], new_batch()
    for step in steps:
        entry_kind, reason = execute(step, kind, on_disk(root, step.src), on_disk(root, step.dst), root)
        if reason:
            result.skipped.append(f"{step.src}: {reason}")
            continue
        entries.append(Entry(batch, entry_kind, step.src, step.dst))
        result.done += 1
    append(journal, entries)
    fix_paths(root, {e.src: e.dst for e in entries if e.kind in MOVES})
    return result


def apply(ops: list[Operation], root: Path, journal: Path) -> Applied:
    steps = [Step("move", o.src, o.dst) for o in ops if o.kind in EXECUTABLE]
    return run("apply", steps, root, journal)


def last_batch(entries: list[Entry]) -> list[Entry]:
    if not entries:
        return []
    return [e for e in entries if e.batch == entries[-1].batch]


def reverse(entry: Entry) -> Step:
    if entry.kind == "delete":
        return Step("restore", entry.src, entry.dst)
    if entry.kind == "restore":
        return Step("delete", entry.src, entry.dst)
    return Step("move", entry.dst, entry.src)


def undo(root: Path, journal: Path) -> int:
    steps = [reverse(e) for e in reversed(last_batch(read_journal(journal)))]
    return run("undo", steps, root, journal).done
