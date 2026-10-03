from __future__ import annotations

import os
from pathlib import Path

from kobold.authors import AuthorStore
from kobold.genres import GenreStore
from kobold.index import Index
from kobold.suggestions import SuggestionStore
from kobold.vectors import VectorStore


def library_root() -> Path:
    return Path(os.environ.get("KOBOLD_ROOT", "/Volumes/Transcend/kobo")).expanduser()


def sources() -> list[Path]:
    raw = os.environ.get("KOBOLD_SOURCES", "")
    return [Path(p.strip()).expanduser() for p in raw.replace("\n", os.pathsep).split(os.pathsep) if p.strip()]


def mounted_sources() -> tuple[list[Path], list[Path]]:
    found, missing = [], []
    for source in sources():
        (found if source.is_dir() else missing).append(source)
    return found, missing


def data_dir() -> Path:
    explicit = os.environ.get("KOBOLD_DATA")
    if explicit:
        return Path(explicit).expanduser()
    default = Path.home() / "Library" / "Application Support" / "kobold"
    chosen = Path(os.environ.get("alfred_workflow_data") or default).expanduser()
    adopt_predecessor_data(chosen)
    return chosen


def adopt_predecessor_data(chosen: Path) -> None:
    predecessor = chosen.with_name(chosen.name.replace("kobold", "kobolib"))
    if predecessor != chosen and predecessor.is_dir() and not chosen.exists():
        predecessor.rename(chosen)


def db_path() -> Path:
    return data_dir() / "library.db"


def sources_db_path() -> Path:
    return data_dir() / "sources.db"


def library_index() -> Index:
    return Index(db_path(), library_root())


def sources_index() -> Index:
    return Index(sources_db_path(), library_root())


def covers_dir() -> Path:
    return data_dir() / "covers"


def journal_path() -> Path:
    return data_dir() / "journal.jsonl"


def genre_store() -> GenreStore:
    return GenreStore(data_dir() / "genres.tsv").load()


def author_store() -> AuthorStore:
    return AuthorStore(data_dir() / "authors.tsv").load()


def oracle_url() -> str:
    return os.environ.get("KOBOLD_ORACLE_URL", "").strip().rstrip("/")


def oracle_model() -> str:
    return os.environ.get("KOBOLD_ORACLE_MODEL", "").strip()


def oracle_key() -> str:
    return os.environ.get("KOBOLD_ORACLE_KEY", "").strip()


def embed_key() -> str:
    return os.environ.get("KOBOLD_EMBED_KEY", "").strip() or oracle_key()


def embed_url() -> str:
    return os.environ.get("KOBOLD_EMBED_URL", "").strip().rstrip("/") or oracle_url()


def embed_model() -> str:
    return os.environ.get("KOBOLD_EMBED_MODEL", "").strip()


def model_on_update() -> bool:
    return os.environ.get("KOBOLD_MODEL_ON_UPDATE", "").strip().lower() in ("1", "true", "yes", "on")


def oracle_log_path() -> Path:
    return data_dir() / "oracle.log"


def oracle_lock_base() -> Path:
    return data_dir() / "oracle"


def oracle_status_path() -> Path:
    return data_dir() / "oracle.status"


def suggestion_store() -> SuggestionStore:
    return SuggestionStore(data_dir() / "oracle.tsv").load()


def vector_store() -> VectorStore:
    return VectorStore(data_dir() / "vectors.db")


def selected_books() -> list[str]:
    return os.environ.get("book", "").splitlines()
