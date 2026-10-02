from __future__ import annotations

import filecmp
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from kobolib.koreader import fix_paths, sidecar_of
from kobolib.plan import Operation
from kobolib.scan import nfc

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


TEMP_SUFFIX = ".kobolib-renaming"


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


def move(step: Step, kind: str, root: Path) -> tuple[str, str]:
    if locate(root, step.src) is None:
        return "", "source missing"
    parent = settle_parents(root, step.dst)
    src = on_disk(root, step.src)
    name = PurePosixPath(step.dst).name
    if (taken := existing_destination(src, parent, name)) is not None:
        if reason := redundant(src, taken):
            return "", reason
        remove(src, root)
        return "delete", ""
    relocate(src, parent / name, root)
    return kind, ""


def execute(step: Step, kind: str, root: Path) -> tuple[str, str]:
    src, dst = on_disk(root, step.src), on_disk(root, step.dst)
    if step.action == "restore":
        if src.exists():
            return "", "already present"
        restore(src, dst)
        return "restore", ""
    if step.action == "delete":
        if not src.exists():
            return "", "source missing"
        if reason := redundant(src, dst):
            return "", reason
        remove(src, root)
        return "delete", ""
    return move(step, kind, root)


def run(kind: str, steps: list[Step], root: Path, journal: Path) -> Applied:
    result, entries, batch = Applied(), [], new_batch()
    for step in steps:
        entry_kind, reason = execute(step, kind, root)
        if reason:
            result.skipped.append(f"{step.src}: {reason}")
            continue
        entry = Entry(batch, entry_kind, step.src, step.dst)
        append(journal, [entry])
        entries.append(entry)
        result.done += 1
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
