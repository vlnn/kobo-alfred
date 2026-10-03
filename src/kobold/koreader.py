from __future__ import annotations

import os
import unicodedata
from pathlib import Path

from kobold.paths import SIDECAR_SUFFIX, nfc, sidecar_of

KOREADER_DIR = ".adds/koreader"
SETTINGS_FILES = ("collection.lua", "history.lua", "bookmarks.lua")


def settings_dir(root: Path) -> Path:
    return root / KOREADER_DIR / "settings"


def docsettings_dir(root: Path) -> Path:
    return root / KOREADER_DIR / "docsettings"


def settings_files(root: Path) -> list[Path]:
    return [p for name in SETTINGS_FILES if (p := settings_dir(root) / name).exists()]


def spellings(path: str) -> set[str]:
    return {unicodedata.normalize(form, path) for form in ("NFC", "NFD")}


def rewrite_lua(text: str, moves: dict[str, str]) -> str:
    for src, dst in moves.items():
        for spelling in spellings(src):
            text = text.replace(f'/{spelling}"', f'/{dst}"')
    return text


def rewrite_file(path: Path, moves: dict[str, str]) -> bool:
    original = path.read_text(encoding="utf-8")
    updated = rewrite_lua(original, moves)
    if updated == original:
        return False
    path.with_suffix(path.suffix + ".bak").write_text(original, encoding="utf-8")
    path.write_text(updated, encoding="utf-8")
    return True


def mirrored_sidecar(src: str) -> str:
    return sidecar_of(Path(src)).as_posix()


def ends_with_sidecar_of(path: Path, src: str) -> bool:
    tail = "/" + mirrored_sidecar(src)
    return nfc(path.as_posix()).endswith(nfc(tail))


def mirrored_candidates(root: Path, src: str) -> list[Path]:
    return [p for p in docsettings_dir(root).rglob("*" + SIDECAR_SUFFIX) if p.is_dir() and ends_with_sidecar_of(p, src)]


def move_mirrored_sidecars(root: Path, moves: dict[str, str]) -> None:
    if not docsettings_dir(root).is_dir():
        return
    for src, dst in moves.items():
        for found in mirrored_candidates(root, src):
            base = found.parents[len(Path(mirrored_sidecar(src)).parts) - 1]
            target = base / mirrored_sidecar(dst)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(found, target)


def fix_paths(root: Path, moves: dict[str, str]) -> list[Path]:
    move_mirrored_sidecars(root, moves)
    return [p for p in settings_files(root) if rewrite_file(p, moves)]
