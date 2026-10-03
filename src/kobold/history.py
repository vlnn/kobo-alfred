from __future__ import annotations

import re
from pathlib import Path

from kobold.koreader import settings_dir
from kobold.paths import nfc

ENTRY = re.compile(r"\{[^{}]*\}")
FILE = re.compile(r'\["file"\]\s*=\s*"((?:[^"\\]|\\.)*)"')
TIME = re.compile(r'\["time"\]\s*=\s*(\d+)')
ESCAPE = re.compile(r"\\(.)")


def unescape(lua: str) -> str:
    return ESCAPE.sub(r"\1", lua)


def entries(text: str) -> list[tuple[int, str]]:
    found = []
    for position, block in enumerate(ENTRY.findall(text)):
        if (file := FILE.search(block)) is not None:
            time = TIME.search(block)
            found.append((int(time.group(1)) if time else -position, unescape(file.group(1))))
    return found


def latest_file(text: str) -> str | None:
    return max(entries(text), default=(0, None))[1]


def in_library(file: str, root: Path) -> str | None:
    parts = file.split("/")
    for start in range(len(parts)):
        rel = "/".join(parts[start:])
        if rel and (root / rel).is_file():
            return nfc(rel)
    return None


def last_opened(root: Path) -> str | None:
    history = settings_dir(root) / "history.lua"
    if not history.exists():
        return None
    file = latest_file(history.read_text(encoding="utf-8"))
    return in_library(file, root) if file else None
