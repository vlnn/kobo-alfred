from __future__ import annotations

import hashlib
import html
import re
import struct
import zipfile
from collections.abc import Callable
from pathlib import Path
from xml.etree import ElementTree as ET

from kobold.identity import is_text_member, local_name
from kobold.model import Row

SAMPLE_CHARS = 2000
TAG = re.compile(r"<[^>]*>")
HEAD = re.compile(r"<head\b.*?</head>", re.S | re.I)
PALM_HEADER = 78
PALMDOC = 2


def plain(markup: str) -> str:
    return " ".join(html.unescape(TAG.sub(" ", HEAD.sub(" ", markup))).split())


def epub_sample(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if is_text_member(name) and (text := plain(zf.read(name).decode("utf-8", "replace"))):
                return text
    return ""


def fb2_sample(path: Path) -> str:
    bodies = (e for e in ET.parse(path).getroot() if local_name(e.tag) == "body")
    return " ".join(" ".join(" ".join(body.itertext()).split()) for body in bodies)


def palmdoc_decompress(data: bytes) -> bytes:
    out, i = bytearray(), 0
    while i < len(data):
        byte = data[i]
        i += 1
        if byte == 0 or 9 <= byte <= 0x7F:
            out.append(byte)
        elif byte <= 8:
            out += data[i : i + byte]
            i += byte
        elif byte <= 0xBF:
            pair = (byte << 8) | data[i]
            i += 1
            distance, length = (pair >> 3) & 0x7FF, (pair & 7) + 3
            for _ in range(length):
                out.append(out[-distance])
        else:
            out += b" "
            out.append(byte ^ 0x80)
    return bytes(out)


def palm_records(data: bytes) -> list[bytes]:
    (count,) = struct.unpack_from(">H", data, 76)
    offsets = [struct.unpack_from(">I", data, PALM_HEADER + 8 * i)[0] for i in range(count)]
    return [data[start:end] for start, end in zip(offsets, [*offsets[1:], len(data)])]


def mobi_sample(path: Path) -> str:
    records = palm_records(path.read_bytes())
    (compression,) = struct.unpack_from(">H", records[0], 0)
    text = palmdoc_decompress(records[1]) if compression == PALMDOC else records[1]
    return plain(text.decode("utf-8", "replace"))


SAMPLERS: dict[str, Callable[[Path], str]] = {
    "epub": epub_sample,
    "fb2": fb2_sample,
    "mobi": mobi_sample,
    "azw": mobi_sample,
    "azw3": mobi_sample,
}


def text_sample(path: Path, fmt: str) -> str:
    sampler = SAMPLERS.get(fmt)
    if sampler is None:
        return ""
    try:
        return sampler(path)[:SAMPLE_CHARS]
    except Exception:
        return ""


def series_line(row: Row) -> str:
    if not row.series:
        return ""
    return f"{row.series} #{row.series_index}" if row.series_index else row.series


def language_code(row: Row) -> str:
    return row.language.split()[0] if row.language else ""


def described(row: Row) -> list[tuple[str, str]]:
    return [
        ("Title", row.title),
        ("Authors", row.authors),
        ("Series", series_line(row)),
        ("Language", language_code(row)),
        ("Year", row.year),
        ("Format", row.format),
        ("Path", row.rel_path),
        ("Subjects", row.subjects),
        ("Description", row.description),
        ("Text", text_sample(Path(row.path), row.format)),
    ]


def evidence_for(row: Row, genres: list[str] = ()) -> str:
    lines = [f"{label}: {value}" for label, value in described(row) if value]
    if genres:
        lines.append(f"Genres: {', '.join(genres)}")
    return "\n".join(lines)


def evidence_hash(evidence: str) -> str:
    stable = [line for line in evidence.splitlines() if not line.startswith("Path: ")]
    return hashlib.sha1("\n".join(stable).encode()).hexdigest()
