from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from kobold.paths import in_sidecar, is_empty_dir, nfc

BOOK_SUFFIXES = {".epub", ".fb2", ".mobi", ".azw", ".azw3", ".pdf", ".djvu"}
PARTIAL_SUFFIX = ".part"
SKIP_FOLDERS = {"_trash", "_dups"}


def book_format(path: Path) -> str:
    suffixes = [s.lower() for s in path.suffixes]
    if suffixes and suffixes[-1] == PARTIAL_SUFFIX:
        suffixes = suffixes[:-1]
    return suffixes[-1].lstrip(".") if suffixes else ""


def is_partial(path: Path) -> bool:
    return path.suffix.lower() == PARTIAL_SUFFIX


def is_junk(name: str) -> bool:
    return name.startswith((".", "FSCK"))


def is_book(path: Path) -> bool:
    return f".{book_format(path)}" in BOOK_SUFFIXES


def is_skipped(path: Path, root: Path, exclude: tuple[Path, ...]) -> bool:
    parts = path.relative_to(root).parts
    return bool(SKIP_FOLDERS & set(parts)) or in_sidecar(path, root) or any(path == e or e in path.parents for e in exclude)


def iter_books(root: Path, exclude: tuple[Path, ...] = ()) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if is_skipped(path, root, exclude):
            continue
        if path.is_file() and not is_junk(path.name) and is_book(path):
            yield path


def is_hidden(path: Path, root: Path) -> bool:
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def iter_junk(root: Path, exclude: tuple[Path, ...] = ()) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if is_hidden(path, root) or is_skipped(path, root, exclude):
            continue
        if is_empty_dir(path) or (path.is_file() and not is_book(path)):
            yield path


def display_stem(path: Path) -> str:
    name = path.name[: -len(PARTIAL_SUFFIX)] if is_partial(path) else path.name
    return nfc(Path(name).stem.strip())


def probe_root(root: Path) -> str:
    try:
        entries = os.listdir(root)
    except PermissionError as error:
        hint = "grant Alfred access to Removable Volumes / Files and Folders in System Settings → Privacy & Security"
        return f"permission denied reading {root} ({error}); {hint}"
    except OSError as error:
        return f"cannot read {root}: {error}"
    return f"{root} is empty" if not entries else ""
