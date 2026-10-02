from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from kobolib.model import Book

THUMBNAIL_FORMATS = {"pdf"}
QUICKLOOK_TIMEOUT = 15
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
THUMB_SIZE = "256"


def cover_key(book: Book) -> str:
    return hashlib.sha1(book.rel_path.encode()).hexdigest()


def existing_cover(book: Book, cache: Path) -> Path | None:
    key = cover_key(book)
    return next((p for p in cache.glob(f"{key}.*")), None)


def write_embedded(book: Book, cache: Path) -> Path | None:
    name, data = book.cover
    suffix = Path(name).suffix.lower()
    if suffix not in IMAGE_SUFFIXES or not data:
        return None
    target = cache / f"{cover_key(book)}{suffix}"
    target.write_bytes(data)
    return target


def quicklook_thumbnail(book: Book, cache: Path) -> Path | None:
    if book.format not in THUMBNAIL_FORMATS or not shutil.which("qlmanage"):
        return None
    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run(
                ["qlmanage", "-t", "-s", THUMB_SIZE, "-o", tmp, book.path],
                capture_output=True,
                check=False,
                timeout=QUICKLOOK_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return None
        produced = next(Path(tmp).glob("*.png"), None)
        if produced is None:
            return None
        target = cache / f"{cover_key(book)}.png"
        shutil.move(produced, target)
    return target


def ensure_cover(book: Book, cache: Path, thumbnails: bool = True) -> Path | None:
    if book.partial:
        return None
    cache.mkdir(parents=True, exist_ok=True)
    if found := existing_cover(book, cache):
        return found
    if book.cover and (written := write_embedded(book, cache)):
        return written
    return quicklook_thumbnail(book, cache) if thumbnails else None
