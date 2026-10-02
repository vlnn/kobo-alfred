import pytest

from kobolib.query import parse_query


@pytest.mark.parametrize(
    "raw, terms, filters",
    [
        ("deep work", ["deep", "work"], {}),
        ("fmt:epub newport", ["newport"], {"fmt": "epub"}),
        ("in:inbox", [], {"in": "inbox"}),
        ("author:delany is:partial", [], {"author": "delany", "is": "partial"}),
        ("series:cadfael 03", ["03"], {"series": "cadfael"}),
        ("lang:uk  дюна", ["дюна"], {"lang": "uk"}),
        ("", [], {}),
        ("weird:prefix stays", ["weird:prefix", "stays"], {}),
    ],
)
def test_parse_query(raw, terms, filters):
    query = parse_query(raw)
    assert query.terms == terms, f"{raw!r} should give terms {terms}"
    assert query.filters == filters, f"{raw!r} should give filters {filters}"


@pytest.mark.parametrize(
    "raw, match",
    [
        ("deep work", '"deep"* "work"*'),
        ("author:delany", 'authors:"delany"*'),
        ("series:cadfael 03", 'series:"cadfael"* "03"*'),
        ('o"brian', '"o""brian"*'),
        ("fmt:epub", ""),
    ],
)
def test_fts_expression(raw, match):
    assert parse_query(raw).fts_match() == match, f"{raw!r} should build FTS match {match!r}"


def test_every_filter_key_has_exactly_one_meaning():
    from kobolib.query import FILTER_KEYS, FTS_COLUMNS, SQL_CLAUSES

    assert not FTS_COLUMNS.keys() & SQL_CLAUSES.keys(), "a key is either matched in the FTS index or in a SQL clause, never both"
    assert {"fmt", "in", "author", "series", "lang", "is", "year", "genre", "tag"} == FILTER_KEYS, (
        "the documented filter set is what parse_query accepts"
    )


@pytest.mark.parametrize("raw, clauses", [("is:partial", ["partial = 1"]), ("is:complete", ["partial = 0"]), ("is:odd", [])])
def test_state_filter_maps_to_its_clause(raw, clauses):
    from kobolib.index import where_clauses

    assert where_clauses(parse_query(raw))[0] == clauses, f"{raw!r} should narrow by {clauses or 'nothing'}"
