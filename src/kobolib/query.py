from __future__ import annotations

from dataclasses import dataclass, field

FTS_COLUMNS = {"author": "authors", "series": "series"}
SQL_CLAUSES = {
    "fmt": "format = :fmt",
    "in": "fold(folder) LIKE '%' || :in || '%'",
    "lang": "fold(language) = :lang",
    "year": "year = :year",
    "genre": "(genre = :genre OR genre LIKE :genre || '/%')",
}
STATE_CLAUSES = {"partial": "partial = 1", "complete": "partial = 0"}
FILTER_KEYS = FTS_COLUMNS.keys() | SQL_CLAUSES.keys() | {"is"}


@dataclass
class Query:
    terms: list[str] = field(default_factory=list)
    filters: dict[str, str] = field(default_factory=dict)

    def fts_match(self) -> str:
        column_terms = [f"{column}:{fts_token(self.filters[key])}" for key, column in FTS_COLUMNS.items() if key in self.filters]
        return " ".join(column_terms + [fts_token(t) for t in self.terms])

    def is_empty(self) -> bool:
        return not self.terms and not self.filters


def fts_token(term: str) -> str:
    escaped = term.replace('"', '""')
    return f'"{escaped}"*'


def split_filter(word: str) -> tuple[str, str] | None:
    key, sep, value = word.partition(":")
    if sep and value and key.lower() in FILTER_KEYS:
        return key.lower(), value.casefold()
    return None


def parse_query(raw: str) -> Query:
    query = Query()
    for word in raw.split():
        if parsed := split_filter(word):
            key, value = parsed
            query.filters[key] = value
        else:
            query.terms.append(word)
    return query
