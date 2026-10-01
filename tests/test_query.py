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
