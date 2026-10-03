from __future__ import annotations


def query_words(raw: str) -> list[str]:
    return raw.split()


def fts_token(word: str) -> str:
    escaped = word.replace('"', '""')
    return f'"{escaped}"*'


def fts_match(words: list[str]) -> str:
    return " ".join(fts_token(w) for w in words)
