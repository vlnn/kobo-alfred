from __future__ import annotations

from dataclasses import dataclass, field

FILTER_KEYS = {"fmt", "in", "author", "series", "lang", "is", "year", "genre", "tag"}
FTS_COLUMN_FILTERS = {"author": "authors", "series": "series"}


@dataclass
class Query:
    terms: list[str] = field(default_factory=list)
    filters: dict[str, str] = field(default_factory=dict)

    def fts_match(self) -> str:
        column_terms = [
            f"{column}:{fts_token(self.filters[key])}"
            for key, column in FTS_COLUMN_FILTERS.items()
            if key in self.filters
        ]
        return " ".join(column_terms + [fts_token(t) for t in self.terms])

    def is_empty(self) -> bool:
        return not self.terms and not self.filters


def fts_token(term: str) -> str:
    escaped = term.replace('"', '""')
    return f'"{escaped}"*'


def split_filter(word: str) -> tuple[str, str] | None:
    key, sep, value = word.partition(":")
    if sep and value and key.lower() in FILTER_KEYS:
        return key.lower(), value.lower()
    return None


def parse_query(raw: str) -> Query:
    query = Query()
    for word in raw.split():
        if parsed := split_filter(word):
            query.filters.__setitem__(*parsed)
        else:
            query.terms.append(word)
    return query
