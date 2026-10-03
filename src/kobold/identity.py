from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Callable, Iterable
from pathlib import Path
from xml.etree import ElementTree as ET

from kobold.scan import book_format, is_partial

TEXT_SUFFIXES = (".xhtml", ".html", ".htm")
CHUNK = 1 << 20


def digest_of(parts: Iterable[bytes]) -> str:
    digest = hashlib.sha1()
    for part in parts:
        digest.update(part)
    return digest.hexdigest()


def chunks(path: Path) -> Iterable[bytes]:
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            yield chunk


def file_hash(path: Path) -> str:
    return digest_of(chunks(path))


def unordered(parts: Iterable[bytes]) -> list[bytes]:
    return sorted(hashlib.sha1(part).digest() for part in parts)


def is_text_member(name: str) -> bool:
    return name.lower().endswith(TEXT_SUFFIXES)


def epub_text_hash(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        members = [n for n in zf.namelist() if is_text_member(n)]
        if not members:
            raise ValueError("no text in epub")
        return digest_of(unordered(zf.read(n) for n in members))


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def fb2_text_hash(path: Path) -> str:
    bodies = [e for e in ET.parse(path).getroot() if local_name(e.tag) == "body"]
    if not bodies:
        raise ValueError("no body in fb2")
    return digest_of(ET.tostring(b) for b in bodies)


TEXT_HASHES: dict[str, Callable[[Path], str]] = {"epub": epub_text_hash, "fb2": fb2_text_hash}


def text_hash(path: Path) -> str:
    strategy = TEXT_HASHES.get(book_format(path))
    if strategy is None or is_partial(path):
        return ""
    try:
        return strategy(path)
    except Exception:
        return ""


def fingerprint(path: Path) -> str:
    return text_hash(path) or file_hash(path)
