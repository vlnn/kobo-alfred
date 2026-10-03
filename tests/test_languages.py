import pytest

from kobolib.languages import searchable_language


@pytest.mark.parametrize(
    "raw, indexed",
    [
        ("en", "en english"),
        ("uk", "uk ukrainian"),
        ("ru", "ru russian"),
        ("eng", "eng english"),
        ("ukr", "ukr ukrainian"),
        ("en-US", "en-US english"),
        ("pt_BR", "pt_BR portuguese"),
        ("UK", "UK ukrainian"),
        ("xx", "xx"),
        ("", ""),
    ],
)
def test_searchable_language_adds_the_english_name(raw, indexed):
    assert searchable_language(raw) == indexed, f"{raw!r} should be indexed as {indexed!r}"
