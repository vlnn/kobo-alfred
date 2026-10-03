from __future__ import annotations

import os
from pathlib import Path

from kobolib.genres import GenreStore


def library_root() -> Path:
    return Path(os.environ.get("KOBO_ROOT", "/Volumes/Transcend/kobo")).expanduser()


def sources() -> list[Path]:
    raw = os.environ.get("KOBO_SOURCES", "")
    return [Path(p).expanduser() for p in raw.replace("\n", os.pathsep).split(os.pathsep) if p.strip()]


def mounted_sources() -> tuple[list[Path], list[Path]]:
    found, missing = [], []
    for source in sources():
        (found if source.is_dir() else missing).append(source)
    return found, missing


def data_dir() -> Path:
    default = Path.home() / "Library" / "Application Support" / "kobolib"
    chosen = os.environ.get("KOBO_DATA") or os.environ.get("alfred_workflow_data") or str(default)
    return Path(chosen).expanduser()


def db_path() -> Path:
    return data_dir() / "library.db"


def sources_db_path() -> Path:
    return data_dir() / "sources.db"


def covers_dir() -> Path:
    return data_dir() / "covers"


def journal_path() -> Path:
    return data_dir() / "journal.jsonl"


def genre_store() -> GenreStore:
    return GenreStore(data_dir() / "genres.tsv").load()


def selected_book() -> str:
    return os.environ.get("book", "")


def selected_books() -> list[str]:
    return selected_book().splitlines()
