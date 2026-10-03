from __future__ import annotations

import filecmp
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath

from kobold.koreader import fix_paths
from kobold.model import Operation
from kobold.paths import is_empty_dir, nfc, sidecar_of

EXECUTABLE = {"move", "trash", "dups"}


class Action(str, Enum):
    MOVE = "move"
    DELETE = "delete"
    RESTORE = "restore"


class Recorded(str, Enum):
    APPLY = "apply"
    UNDO = "undo"
    DELETE = "delete"
    RESTORE = "restore"


MOVES = {Recorded.APPLY, Recorded.UNDO}


@dataclass
class Entry:
    batch: str
    kind: str
    src: str
    dst: str


@dataclass
class Step:
    action: Action
    src: str
    dst: str


@dataclass(frozen=True)
class Outcome:
    recorded: str = ""
    reason: str = ""

    @property
    def skipped(self) -> bool:
        return bool(self.reason)


def done(recorded: Recorded) -> Outcome:
    return Outcome(recorded=recorded.value)


def skip(reason: str) -> Outcome:
    return Outcome(reason=reason)


@dataclass
class Applied:
    done: int = 0
    skipped: list[str] = field(default_factory=list)
    moved: dict[str, str] = field(default_factory=dict)
    removed: list[str] = field(default_factory=list)

    def record(self, entry: Entry) -> None:
        self.done += 1
        if entry.kind in MOVES:
            self.moved[entry.src] = entry.dst
        if entry.kind == Recorded.DELETE:
            self.removed.append(entry.src)


def same_name(a: str, b: str) -> bool:
    return nfc(a) == nfc(b)


def similar_name(a: str, b: str) -> bool:
    return nfc(a).casefold() == nfc(b).casefold()


def child_named(folder: Path, name: str) -> Path | None:
    try:
        entries = os.listdir(folder)
    except OSError:
        return None
    exact = next((folder / e for e in entries if same_name(e, name)), None)
    return exact or next((folder / e for e in entries if similar_name(e, name)), None)


def locate(root: Path, rel: str) -> Path | None:
    current = root
    for part in PurePosixPath(rel).parts:
        current = child_named(current, part)
        if current is None:
            return None
    return current


def on_disk(root: Path, rel: str) -> Path:
    return locate(root, rel) or root / rel


def is_same_file(a: Path, b: Path) -> bool:
    try:
        return a == b or a.samefile(b)
    except OSError:
        return False


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


TEMP_SUFFIX = ".kobold-renaming"


def respell(path: Path, name: str) -> Path:
    if path.name == name:
        return path
    temp = path.with_name(name + TEMP_SUFFIX)
    os.replace(path, temp)
    os.replace(temp, path.with_name(name))
    return path.with_name(name)


def settle_parents(root: Path, rel: str) -> Path:
    current = root
    for part in PurePosixPath(rel).parts[:-1]:
        found = child_named(current, part)
        current = respell(found, part) if found else current / part
        current.mkdir(exist_ok=True)
    return current


def place(src: Path, dst: Path) -> None:
    if src.parent == dst.parent:
        respell(src, dst.name)
    else:
        os.replace(src, dst)


def carry_sidecar(src: Path, dst: Path) -> None:
    sidecar = sidecar_of(src)
    if not sidecar.is_dir():
        return
    existing = child_named(dst.parent, sidecar_of(dst).name)
    if existing is None or is_same_file(existing, sidecar):
        place(sidecar, sidecar_of(dst))


def relocate(src: Path, dst: Path, root: Path) -> None:
    place(src, dst)
    carry_sidecar(src, dst)
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


def existing_destination(src: Path, parent: Path, name: str) -> Path | None:
    found = child_named(parent, name)
    return None if found is None or is_same_file(found, src) else found


def move(step: Step, label: Recorded, root: Path) -> Outcome:
    if locate(root, step.src) is None:
        return skip("source missing")
    parent = settle_parents(root, step.dst)
    src = on_disk(root, step.src)
    name = PurePosixPath(step.dst).name
    if (taken := existing_destination(src, parent, name)) is not None:
        if reason := redundant(src, taken):
            return skip(reason)
        remove(src, root)
        return done(Recorded.DELETE)
    relocate(src, parent / name, root)
    return done(label)


def put_back(step: Step, root: Path) -> Outcome:
    src, kept = on_disk(root, step.src), on_disk(root, step.dst)
    if src.exists():
        return skip("already present")
    restore(src, kept)
    return done(Recorded.RESTORE)


def delete(step: Step, root: Path) -> Outcome:
    src, kept = on_disk(root, step.src), on_disk(root, step.dst)
    if not src.exists():
        return skip("source missing")
    if reason := redundant(src, kept):
        return skip(reason)
    remove(src, root)
    return done(Recorded.DELETE)


def execute(step: Step, label: Recorded, root: Path) -> Outcome:
    if step.action is Action.RESTORE:
        return put_back(step, root)
    if step.action is Action.DELETE:
        return delete(step, root)
    return move(step, label, root)


def run(label: Recorded, steps: list[Step], root: Path, journal: Path) -> Applied:
    result, batch = Applied(), new_batch()
    for step in steps:
        outcome = execute(step, label, root)
        if outcome.skipped:
            result.skipped.append(f"{step.src}: {outcome.reason}")
            continue
        entry = Entry(batch, outcome.recorded, step.src, step.dst)
        append(journal, [entry])
        result.record(entry)
    fix_paths(root, result.moved)
    return result


def apply(ops: list[Operation], root: Path, journal: Path) -> Applied:
    steps = [Step(Action.MOVE, o.src, o.dst) for o in ops if o.kind in EXECUTABLE]
    return run(Recorded.APPLY, steps, root, journal)


def last_batch(entries: list[Entry]) -> list[Entry]:
    if not entries:
        return []
    return [e for e in entries if e.batch == entries[-1].batch]


def reverse(entry: Entry) -> Step:
    if entry.kind == Recorded.DELETE:
        return Step(Action.RESTORE, entry.src, entry.dst)
    if entry.kind == Recorded.RESTORE:
        return Step(Action.DELETE, entry.src, entry.dst)
    return Step(Action.MOVE, entry.dst, entry.src)


def undo(root: Path, journal: Path) -> int:
    steps = [reverse(e) for e in reversed(last_batch(read_journal(journal)))]
    return run(Recorded.UNDO, steps, root, journal).done
