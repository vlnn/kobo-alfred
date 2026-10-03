from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from kobold.filenames import EDITOR, STOPWORDS
from kobold.genres import genre_from_folder
from kobold.model import Row
from kobold.scan import PARTIAL_SUFFIX

UNSAFE = re.compile(r'[:?*|"<>/\\]')
SPACES = re.compile(r"\s+")
INDEX_PART = re.compile(r"\d+")
MAX_NAME_BYTES = 255
LEADING_ARTICLE_TITLE = re.compile(r"^(?:The|A|An)\s+")


def first_author(authors: str) -> str:
    return EDITOR.sub("", authors.split(";")[0]).strip()


CYRILLIC = re.compile(r"^[\u0400-\u04FF\s\-'’.]+$")
PATRONYMIC = re.compile(r"(?:ович|евич|йович|ич|овна|евна|ївна|івна)$", re.I)
WESTERN_FIRST_NAMES = {"артур", "александр", "чарлз", "чарльз", "роберт", "джон", "джеймс", "ада", "дэниел"}


def cyrillic_surname_first(tokens: list[str]) -> bool:
    if PATRONYMIC.search(tokens[-1]):
        return True
    return len(tokens) == 2 and tokens[0].lower() not in WESTERN_FIRST_NAMES


def surname_first(author: str) -> str:
    if "," in author or " " not in author:
        return author
    tokens = author.split()
    if CYRILLIC.match(author) and cyrillic_surname_first(tokens):
        return f"{tokens[0]}, {' '.join(tokens[1:])}"
    *given, surname = tokens
    return f"{surname}, {' '.join(given)}"


def resolve_known(candidate: str, known: frozenset[str]) -> str:
    last, _, first = candidate.partition(", ")
    twin = f"{first}, {last}"
    return twin if twin in known and candidate not in known else candidate


def author_folder(authors: str, known: frozenset[str] = frozenset()) -> str:
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


def stem_for(row: Row, known: frozenset[str] = frozenset()) -> str:
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


def canonical_name(row: Row, known: frozenset[str] = frozenset()) -> str:
    return fat_safe(stem_for(row, known) + extension(row))


def looks_like_person(name: str) -> bool:
    tokens = name.split()
    return 2 <= len(tokens) <= 3 and all(t[0].isupper() for t in tokens) and not any(t.lower() in STOPWORDS for t in tokens)


def known_authors(folders: set[str]) -> set[str]:
    names = (Path(f).name for f in folders)
    return {surname_first(n) for n in names if "," in n or looks_like_person(n)}


def depth(folder: str) -> int:
    return len(Path(folder).parts)


@dataclass(frozen=True)
class Shelves:
    authors: frozenset[str]
    genre_homes: dict[str, str]


def genre_homes(folders: set[str]) -> dict[str, str]:
    homes = defaultdict(list)
    for folder in folders:
        if genre := genre_from_folder(folder):
            homes[genre].append(folder)
    return {genre: min(candidates, key=lambda f: (depth(f), f)) for genre, candidates in homes.items()}


def shelves(folders: set[str]) -> Shelves:
    return Shelves(frozenset(known_authors(folders)), genre_homes(folders))


def genre_root(genre: str, layout: Shelves) -> str:
    if found := layout.genre_homes.get(genre):
        return found
    parent, _, leaf = genre.rpartition("/")
    if parent and (found := layout.genre_homes.get(parent)):
        return f"{found}/{leaf}"
    return genre


def series_folder_name(series: str) -> str:
    return LEADING_ARTICLE_TITLE.sub("", series).strip()


def destination_folder(row: Row, genre: str, layout: Shelves, series_count: int) -> str:
    parts = [genre_root(genre, layout)]
    if author := author_folder(row.authors, layout.authors):
        parts.append(fat_safe(author))
    if row.series and series_count > 1:
        parts.append(fat_safe(series_folder_name(row.series)))
    return "/".join(parts)


def destination(row: Row, genre: str, layout: Shelves, series_count: int) -> str:
    return f"{destination_folder(row, genre, layout, series_count)}/{canonical_name(row, layout.authors)}"
