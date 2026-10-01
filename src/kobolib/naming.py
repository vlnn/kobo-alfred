from __future__ import annotations

import re
from pathlib import Path

from kobolib.filenames import EDITOR
from kobolib.index import Row
from kobolib.scan import PARTIAL_SUFFIX
from kobolib.tags import genre_from_folder

UNSAFE = re.compile(r'[:?*|"<>/\\]')
SPACES = re.compile(r"\s+")
INDEX_PART = re.compile(r"\d+")
MAX_NAME_BYTES = 255
LEADING_ARTICLE_TITLE = re.compile(r"^(?:The|A|An)\s+")


def first_author(authors: str) -> str:
    return EDITOR.sub("", authors.split(";")[0]).strip()


def surname_first(author: str) -> str:
    if "," in author or " " not in author:
        return author
    *given, surname = author.split()
    return f"{surname}, {' '.join(given)}"


def resolve_known(candidate: str, known: set[str]) -> str:
    last, _, first = candidate.partition(", ")
    twin = f"{first}, {last}"
    return twin if twin in known and candidate not in known else candidate


def author_folder(authors: str, known: set[str] = frozenset()) -> str:
    candidate = surname_first(first_author(authors))
    return resolve_known(candidate, known) if candidate else ""


def pad_index(index: str) -> str:
    return INDEX_PART.sub(lambda m: m.group().zfill(2), index)


def series_part(row: Row) -> str:
    if not row.series:
        return ""
    return f" ({row.series} {pad_index(row.series_index)})" if row.series_index else f" ({row.series})"


def year_part(row: Row) -> str:
    return f" ({row.year})" if row.year else ""


def extension(row: Row) -> str:
    return f".{row.format}{PARTIAL_SUFFIX if row.partial else ''}"


def stem_for(row: Row, known: set[str] = frozenset()) -> str:
    author = author_folder(row.authors, known)
    head = f"{author} - {row.title}" if author else row.title
    return f"{head}{series_part(row)}{year_part(row)}"


def truncate_bytes(stem: str, limit: int) -> str:
    encoded = stem.encode()
    while len(encoded) > limit:
        stem = stem[:-1]
        encoded = stem.encode()
    return stem


def fat_safe(name: str) -> str:
    cleaned = SPACES.sub(" ", UNSAFE.sub("_", name)).strip(" .")
    path = Path(cleaned)
    suffix = "".join(path.suffixes[-2:]) if cleaned.endswith(PARTIAL_SUFFIX) else path.suffix
    stem = cleaned[: len(cleaned) - len(suffix)] if suffix else cleaned
    return truncate_bytes(stem, MAX_NAME_BYTES - len(suffix.encode())) + suffix


def canonical_name(row: Row, known: set[str] = frozenset()) -> str:
    return fat_safe(stem_for(row, known) + extension(row))


def known_authors(folders: set[str]) -> set[str]:
    return {Path(f).name for f in folders if "," in Path(f).name}


def depth(folder: str) -> int:
    return len(Path(folder).parts)


def folder_for_genre(genre: str, folders: set[str]) -> str:
    matches = sorted((f for f in folders if genre_from_folder(f) == genre), key=depth)
    return matches[0] if matches else ""


def genre_root(genre: str, folders: set[str]) -> str:
    if found := folder_for_genre(genre, folders):
        return found
    parent, _, leaf = genre.rpartition("/")
    if parent and (found := folder_for_genre(parent, folders)):
        return f"{found}/{leaf}"
    return genre


def series_folder_name(series: str) -> str:
    return LEADING_ARTICLE_TITLE.sub("", series).strip()


def destination_folder(row: Row, genre: str, folders: set[str], series_count: int) -> str:
    parts = [genre_root(genre, folders)]
    if author := author_folder(row.authors, known_authors(folders)):
        parts.append(fat_safe(author))
    if row.series and series_count > 1:
        parts.append(fat_safe(series_folder_name(row.series)))
    return "/".join(parts)


def destination(row: Row, genre: str, folders: set[str], series_count: int) -> str:
    return f"{destination_folder(row, genre, folders, series_count)}/{canonical_name(row, known_authors(folders))}"
