import pytest

from kobolib.query import fts_match, query_words


@pytest.mark.parametrize(
    "raw, words",
    [
        ("deep work", ["deep", "work"]),
        ("  delany   epub ", ["delany", "epub"]),
        ("author:delany", ["author:delany"]),
        ("lang:uk  дюна", ["lang:uk", "дюна"]),
        ("", []),
    ],
)
def test_query_words_split_on_whitespace_only(raw, words):
    assert query_words(raw) == words, f"{raw!r} should become the words {words}"


@pytest.mark.parametrize(
    "words, match",
    [
        (["deep", "work"], '"deep"* "work"*'),
        (["delany"], '"delany"*'),
        (['o"brian'], '"o""brian"*'),
        ([], ""),
    ],
)
def test_fts_match_prefixes_every_word(words, match):
    assert fts_match(words) == match, f"{words} should build the FTS match {match!r}"


def test_query_module_has_no_filters():
    import kobolib.query as query

    leftovers = {"FILTER_KEYS", "SQL_CLAUSES", "STATE_CLAUSES", "FTS_COLUMNS"} & set(vars(query))
    assert not leftovers, f"filters are gone from the query grammar, found {leftovers}"
