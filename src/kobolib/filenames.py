from __future__ import annotations

import re
from dataclasses import dataclass, field

NOISE = [
    re.compile(r"\s*-\s*libgen(?:[._]li)?(?:_\d+)?$", re.I),
    re.compile(r"\s+libgen(?:[._]li)?$", re.I),
    re.compile(r"\s*--\s*Anna['’]s Archive$", re.I),
    re.compile(r"\s*--\s*[0-9a-f]{32}$"),
    re.compile(r"\s*\{\d+\}$"),
]
BRACKET_SERIES = re.compile(r"^\[(?P<body>[^\]]+)\]\s*")
PAREN_SERIES = re.compile(r"^\((?P<series>.+?)\s+(?P<index>\d+(?:-\d+)?)\)\s*")
SERIES_BODY = re.compile(r"^(?P<series>.+?)\s*(?:№|#)?\s*(?P<index>\d+(?:-\d+)?)?\s*$")
INLINE_SERIES = re.compile(r"\s*\((?P<series>[^()]+?)\s+(?P<index>\d+(?:-\d+)?)\)\s*$")
BRACED_AUTHOR = re.compile(r"\{(?P<author>[^}]+)\}")
PUBLICATION = re.compile(r"\s*\((?P<year>\d{4})?(?:_\d{4})?,?\s*[^)]*\)\s*$")
TRAILING_YEAR = re.compile(r"^\d{4}$")
LEADING_NUMBER = re.compile(r"^\d{1,3}(?:-\d{1,3})?\s+")
AUTHOR_LIKE = re.compile(r"^\S+(?:\s\S+){0,2},\s*\S")
EDITOR = re.compile(r"\s*\((?:ed|eds|ed\.|eds\.)\)$", re.I)
TRAILING_ARTICLE = re.compile(r"^(?P<title>.+),\s*(?P<article>The|A|An)$")
AUTHOR_SEPARATOR = re.compile(r"\s*(?:_|&|;)\s*")
COMMA = re.compile(r"\s*,\s*")
BRACKETED_ALIAS = re.compile(r"\s*\[[^\]]*\]")
ANNA_SERIES = re.compile(r"^(?P<series>.+?)\s*,?\s*#?(?P<index>\d+(?:-\d+)?)\s*,\s*(?P<year>\d{4})\b")
ANNA_YEAR = re.compile(r"\b(?P<year>\d{4})\b")
PAREN_SERIES_TAIL = re.compile(r"\s*\((?P<series>[^()#]+?),?\s*#(?P<index>\d+(?:-\d+)?)\)\s*$")
INITIAL = re.compile(r"^[A-ZА-ЯІЇЄҐ]\.?$")
YEAR_SUFFIX = re.compile(r"\s-\s(?P<year>\d{4})$")
STOPWORDS = {"of", "the", "a", "an", "and", "in", "on", "to", "for", "it", "is", "at", "with", "from"}
WORD_BREAK = re.compile(r"[\s_\-]+")


@dataclass
class FilenameGuess:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    series: str = ""
    series_index: str = ""
    year: str = ""


def usable_title(title: str) -> bool:
    return " " in title.strip() or len(WORD_BREAK.split(title.strip())) > 2


def strip_noise(stem: str) -> str:
    previous = None
    while previous != stem:
        previous = stem
        for pattern in NOISE:
            stem = pattern.sub("", stem)
    return stem.strip()


def take_leading_series(stem: str) -> tuple[str, str, str]:
    if match := BRACKET_SERIES.match(stem):
        body = match.group("body").split(" - ")[0].strip()
        parsed = SERIES_BODY.match(body)
        return stem[match.end() :], parsed.group("series").strip(" _"), parsed.group("index") or ""
    if match := PAREN_SERIES.match(stem):
        return stem[match.end() :], match.group("series"), match.group("index")
    return stem, "", ""


def take_trailing_series(stem: str) -> tuple[str, str, str]:
    if match := INLINE_SERIES.search(stem):
        return stem[: match.start()], match.group("series"), match.group("index")
    return stem, "", ""


def take_braced_author(stem: str) -> tuple[str, list[str]]:
    if match := BRACED_AUTHOR.search(stem):
        return stem[: match.start()] + stem[match.end() :], split_authors(match.group("author"))
    return stem, []


def take_publication(stem: str) -> tuple[str, str]:
    if match := PUBLICATION.search(stem):
        return stem[: match.start()], match.group("year") or ""
    return stem, ""


def take_trailing_year(parts: list[str]) -> tuple[list[str], str]:
    if len(parts) > 1 and TRAILING_YEAR.match(parts[-1].strip()):
        return parts[:-1], parts[-1].strip()
    return parts, ""


def person_score(text: str) -> int:
    if TRAILING_ARTICLE.match(text):
        return -5
    if EDITOR.search(text):
        return 3
    tokens = text.replace(",", "").split()
    surname_first = 2 * int(bool(AUTHOR_LIKE.match(text)))
    if not 2 <= len(tokens) <= 4:
        return surname_first
    capitalized = all(t[0].isupper() for t in tokens)
    initials = sum(1 for t in tokens if INITIAL.match(t))
    stopwords = sum(1 for t in tokens if t.lower() in STOPWORDS)
    return int(capitalized) + initials + surname_first - stopwords


def looks_like_full_name(piece: str) -> bool:
    tokens = piece.split()
    return len(tokens) >= 2 and not tokens[0].endswith(".")


def is_name_list(part: str) -> bool:
    pieces = COMMA.split(part)
    return len(pieces) > 1 and all(looks_like_full_name(p) for p in pieces)


def split_commas(part: str) -> list[str]:
    return COMMA.split(part) if is_name_list(part) else [part]


def split_authors(raw: str) -> list[str]:
    cleaned = BRACKETED_ALIAS.sub("", raw.replace("&amp_", "&").replace("&amp;", "&"))
    parts = (name for part in AUTHOR_SEPARATOR.split(cleaned) for name in split_commas(part))
    return [a for part in parts if (a := part.strip(" _,"))]


def title_first(first: str, rest: str) -> bool:
    bare = LEADING_NUMBER.sub("", first)
    if LEADING_NUMBER.match(first):
        return person_score(rest) >= person_score(bare)
    return person_score(rest) > person_score(bare)


def anna_edition(segment: str) -> tuple[str, str, str]:
    if match := ANNA_SERIES.match(segment):
        return match.group("series").strip(), match.group("index"), match.group("year")
    if match := ANNA_YEAR.search(segment):
        return "", "", match.group("year")
    return "", "", ""


def split_anna(stem: str) -> tuple[str, list[str], str, str, str]:
    title, author, *rest = stem.split(" -- ")
    series, index, year = anna_edition(rest[0]) if rest else ("", "", "")
    if match := PAREN_SERIES_TAIL.search(title):
        title, series, index = title[: match.start()], match.group("series").strip(), match.group("index")
    return title.strip(), split_authors(author), series, index, year


def split_title_author(stem: str) -> tuple[str, list[str], str]:
    if " -- " in stem:
        title, authors, _, _, year = split_anna(stem)
        return title, authors, year
    parts = stem.split(" - ")
    parts, year = take_trailing_year(parts)
    if len(parts) < 2:
        return LEADING_NUMBER.sub("", stem).strip(), [], year
    first, rest = parts[0], " - ".join(parts[1:])
    bare_first = LEADING_NUMBER.sub("", first).strip(" _")
    if title_first(first, rest):
        return bare_first, split_authors(rest), year
    return rest.strip(), split_authors(bare_first), year


def clean_title(title: str) -> str:
    title = re.sub(r"(?<=\w)_(?=\s)", ":", title).strip(" _")
    if match := TRAILING_ARTICLE.match(title):
        return f"{match.group('article')} {match.group('title')}"
    return title


def take_year_suffix(stem: str) -> tuple[str, str]:
    if match := YEAR_SUFFIX.search(stem):
        return stem[: match.start()], match.group("year")
    return stem, ""


def guess_from_stem(stem: str) -> FilenameGuess:
    stem = strip_noise(stem)
    stem, series, index = take_leading_series(stem)
    stem, braced = take_braced_author(stem)
    stem, year = take_publication(stem)
    stem, suffix_year = take_year_suffix(stem)
    stem, inline_series, inline_index = take_trailing_series(stem)
    anna_series, anna_index = split_anna(stem)[2:4] if " -- " in stem else ("", "")
    title, authors, split_year = split_title_author(stem)
    return FilenameGuess(
        title=clean_title(title),
        authors=braced or authors,
        series=series or inline_series or anna_series,
        series_index=index or inline_index or anna_index,
        year=year or suffix_year or split_year,
    )
