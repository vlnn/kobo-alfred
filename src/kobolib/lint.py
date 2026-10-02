from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from kobolib.filenames import BRACED_AUTHOR, strip_noise
from kobolib.index import Row, series_key
from kobolib.scan import BOOK_SUFFIXES, display_stem, iter_junk, relative_path
from kobolib.tags import TagStore

WORD_BREAK = re.compile(r"[\s_\-]+")
JOINED_WORDS = re.compile(r"\w[_\-]\w")
MIN_FOLDER_KEY = 4
OPAQUE_STEMS = [
    re.compile(r"^\d+_\d+$"),
    re.compile(r"^smp\d+_[0-9a-f]+$", re.I),
    re.compile(r"^annas-arch-", re.I),
    re.compile(r"^[0-9a-f]{10,}(?:[_-]|$)", re.I),
    re.compile(r"^fb\d+u?_", re.I),
]


@dataclass
class Finding:
    rule: str
    detail: str
    rel_paths: list[str]


def stem_of(row: Row) -> str:
    return display_stem(Path(row.rel_path))


def filename_of(row: Row) -> str:
    return Path(row.rel_path).name


def single(rule: str, detail: str, row: Row) -> Finding:
    return Finding(rule, detail, [row.rel_path])


def flag(
    rule: str, rows: Iterable[Row], predicate: Callable[[Row], bool], detail: Callable[[Row], str] = lambda r: r.title
) -> list[Finding]:
    return [single(rule, detail(r), r) for r in rows if predicate(r)]


def looks_opaque(row: Row) -> bool:
    stem = stem_of(row)
    if any(p.match(stem) for p in OPAQUE_STEMS):
        return True
    title = row.title.strip()
    return not row.authors and " " not in title and len(WORD_BREAK.split(title)) <= 2


def has_double_extension(row: Row) -> bool:
    return Path(stem_of(row)).suffix.lower() in BOOK_SUFFIXES


def is_noisy(row: Row) -> bool:
    name, stem = filename_of(row), stem_of(row)
    return (
        name != name.strip()
        or strip_noise(stem) != stem
        or "&amp" in name
        or " -- " in stem
        or bool(BRACED_AUTHOR.search(stem))
        or (" " not in stem and bool(JOINED_WORDS.search(stem)))
    )


def partials(rows: list[Row]) -> list[Finding]:
    return flag("partial", rows, lambda r: r.partial)


def opaque_names(rows: list[Row]) -> list[Finding]:
    return flag("opaque", rows, looks_opaque, lambda r: f"{r.title}: no usable title in the filename")


def double_extensions(rows: list[Row]) -> list[Finding]:
    return flag("double_extension", rows, has_double_extension, lambda r: f"{filename_of(r)}: two book extensions")


def noisy_names(rows: list[Row]) -> list[Finding]:
    return flag("noisy_name", rows, is_noisy, lambda r: f"{r.title}: filename carries download noise")


def grouped(rows: Iterable[Row], key: Callable[[Row], str]) -> list[list[Row]]:
    groups: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        if k := key(row):
            groups[k].append(row)
    return [g for g in groups.values() if len(g) > 1]


def exact_duplicates(rows: list[Row]) -> list[Finding]:
    return [
        Finding("exact_duplicate", f"{g[0].title} ×{len(g)}: identical files", [r.rel_path for r in g])
        for g in grouped(rows, lambda r: r.fingerprint)
    ]


def distinct_files(rows: list[Row]) -> list[Row]:
    seen: dict[str, Row] = {}
    for row in rows:
        seen.setdefault(row.fingerprint or row.rel_path, row)
    return list(seen.values())


def title_duplicate(group: list[Row]) -> Finding:
    return Finding("title_duplicate", f"{group[0].title}: {', '.join(r.format for r in group)}", [r.rel_path for r in group])


def title_duplicates(rows: list[Row]) -> list[Finding]:
    complete = [r for r in rows if not r.partial]
    groups = (distinct_files(g) for g in grouped(complete, lambda r: r.norm_title))
    return [title_duplicate(g) for g in groups if len(g) > 1]


def ancestors(folder: str) -> list[str]:
    path = Path(folder)
    return [p.as_posix() for p in (path, *path.parents) if p.as_posix() not in (".", "")]


def all_folders(rows: Iterable[Row]) -> set[str]:
    return {a for r in rows for a in ancestors(r.folder)}


def names_overlap(series_key: str, folder_key: str) -> bool:
    if not series_key or len(folder_key) < MIN_FOLDER_KEY:
        return False
    return series_key in folder_key or folder_key in series_key


def folder_keys(folders: set[str]) -> dict[str, str]:
    return {f: series_key(Path(f).name) for f in sorted(folders)}


def series_folder(series: str, keys: dict[str, str]) -> str:
    key = series_key(series)
    return next((f for f, folder_key in keys.items() if names_overlap(key, folder_key)), "")


def author_folders(rows: Iterable[Row]) -> Counter:
    return Counter(r.folder for r in rows if "," in Path(r.folder).name)


def swapped(name: str) -> str:
    last, _, first = name.partition(", ")
    return f"{first}, {last}"


def inverted_folder(folder: str, counts: Counter) -> str:
    twin = str(Path(folder).with_name(swapped(Path(folder).name)))
    return twin if counts.get(twin, 0) > counts[folder] else ""


def author_inversions(rows: list[Row]) -> list[Finding]:
    counts = author_folders(rows)
    return [
        single("author_inversion", f"{Path(r.folder).name} looks inverted → {home}", r)
        for r in rows
        if r.folder in counts and (home := inverted_folder(r.folder, counts))
    ]


def is_under(folder: str, home: str) -> bool:
    return folder == home or folder.startswith(home + "/")


def misfiled_series(rows: list[Row]) -> list[Finding]:
    keys = folder_keys(all_folders(rows))
    findings = []
    for row in rows:
        home = series_folder(row.series, keys) if row.series else ""
        if home and not is_under(row.folder, home):
            findings.append(single("misfiled_series", f"{row.title} → {home}", row))
    return findings


def unclassified(rows: list[Row], store: TagStore) -> list[Finding]:
    return flag("unclassified", rows, lambda r: not store.genre_of(r), lambda r: f"{r.title}: no genre yet")


def junk(root: Path, exclude: tuple[Path, ...] = ()) -> list[Finding]:
    return [Finding("junk", f"{p.name}: not a book", [relative_path(p, root)]) for p in iter_junk(root, exclude)]


def lint(rows: list[Row], store: TagStore, root: Path, exclude: tuple[Path, ...] = ()) -> list[Finding]:
    return [
        *junk(root, exclude),
        *partials(rows),
        *double_extensions(rows),
        *noisy_names(rows),
        *opaque_names(rows),
        *exact_duplicates(rows),
        *title_duplicates(rows),
        *misfiled_series(rows),
        *author_inversions(rows),
        *unclassified(rows, store),
    ]
