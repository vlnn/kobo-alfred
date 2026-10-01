from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from pathlib import Path

BOOK_SUFFIXES = {".epub", ".fb2", ".mobi", ".azw", ".azw3", ".pdf", ".djvu"}
PARTIAL_SUFFIX = ".part"
JUNK_SUFFIXES = {".textclipping", ".txt", ".zip"}
FINGERPRINT_BYTES = 64 * 1024


def book_format(path: Path) -> str:
    suffixes = [s.lower() for s in path.suffixes]
    if suffixes and suffixes[-1] == PARTIAL_SUFFIX:
        suffixes = suffixes[:-1]
    return suffixes[-1].lstrip(".") if suffixes else ""


def is_partial(path: Path) -> bool:
    return path.suffix.lower() == PARTIAL_SUFFIX


def is_junk(name: str) -> bool:
    lowered = name.lower()
    return name.startswith((".", "FSCK")) or any(lowered.endswith(s) for s in JUNK_SUFFIXES)


def is_book(path: Path) -> bool:
    return f".{book_format(path)}" in BOOK_SUFFIXES


def iter_books(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and not is_junk(path.name) and is_book(path):
            yield path


def is_empty_dir(path: Path) -> bool:
    return path.is_dir() and not any(path.iterdir())


def is_hidden(path: Path) -> bool:
    return path.name.startswith(".")


def iter_junk(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if is_hidden(path):
            continue
        if is_empty_dir(path) or (path.is_file() and not is_book(path)):
            yield path


def fingerprint(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha1(str(size).encode())
    with path.open("rb") as handle:
        digest.update(handle.read(FINGERPRINT_BYTES))
        if size > 2 * FINGERPRINT_BYTES:
            handle.seek(-FINGERPRINT_BYTES, os.SEEK_END)
        digest.update(handle.read(FINGERPRINT_BYTES))
    return digest.hexdigest()


def relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def display_stem(path: Path) -> str:
    name = path.name[: -len(PARTIAL_SUFFIX)] if is_partial(path) else path.name
    return Path(name).stem.strip()


def probe_root(root: Path) -> str:
    try:
        entries = os.listdir(root)
    except PermissionError as error:
        return f"permission denied reading {root} ({error}); grant Alfred access to Removable Volumes / Files and Folders in System Settings → Privacy & Security"
    except OSError as error:
        return f"cannot read {root}: {error}"
    return f"{root} is empty" if not entries else ""
