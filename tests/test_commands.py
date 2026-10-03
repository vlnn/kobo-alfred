import sqlite3
from pathlib import Path

import pytest

from kobolib.cli import main
from kobolib.commands import search_items


def titles(items: list[dict]) -> list[str]:
    return [i["title"] for i in items]


def books(items: list[dict]) -> list[dict]:
    return [i for i in items if "quicklookurl" in i]


def action_of(item: dict) -> str:
    return item.get("variables", {}).get("action", "")


def classify_inbox(library: Path, capsys) -> None:
    for name in ("Napkin.pdf", "Скиннер - Оперантное поведение.fb2"):
        main(["tag", str(library / "00_Inbox" / name), "genre=reference"])
    capsys.readouterr()


def test_empty_query_starts_with_the_inbox_reminder(indexed):
    reminder, *rest = search_items("")

    assert reminder["title"] == "2 books without a genre", "the reminder should count complete books without a genre"
    assert reminder["valid"] is False and reminder["autocomplete"] == "inbox ", "↩ on the reminder should complete to kb inbox"
    assert set(titles(rest)) == {"Deep Work", "Napkin", "Оперантное поведение"}, "recent complete books should follow the reminder"


def test_empty_query_has_no_reminder_when_the_inbox_is_empty(indexed, library, capsys):
    classify_inbox(library, capsys)

    assert all("quicklookurl" in i for i in search_items("")), "with an empty inbox, kb should list only books"


def test_command_rows_come_before_books_matching_the_whole_input(env, library, capsys):
    (library / "00_Inbox" / "Stats for Dummies - Anon.pdf").write_bytes(b"%PDF-1.4")
    main(["index"])
    capsys.readouterr()

    found = titles(search_items("stats"))

    assert found[-1] == "Stats for Dummies" and len(found) > 1, "the stats rows should come first, then the book matching the word"


def test_a_command_word_never_hides_a_book(env, library, capsys):
    (library / "00_Inbox" / "Update Your Life - Smith, John.pdf").write_bytes(b"%PDF-1.4")
    main(["index"])
    capsys.readouterr()

    items = search_items("update")

    assert action_of(items[0]) == "update", "the update row should come first"
    assert titles(books(items)) == ["Update Your Life"], "a book whose title holds the command word should still be listed"


def test_books_already_listed_by_the_command_are_not_repeated(indexed):
    uids = [i["uid"] for i in books(search_items("inbox"))]

    assert sorted(uids) == sorted(set(uids)) and len(uids) == 2, "each inbox book should appear once although it matches the word too"


def test_command_takes_the_remaining_words(indexed):
    items = search_items("rnd epub")

    assert titles(items) == ["Deep Work"], "kb rnd <words> should draw from books matching the words"
    assert action_of(items[0]) == "open", "a book row from a command opens like any other book"


@pytest.mark.parametrize("query", ["", "deep", "stats", "inbox", "classify", "rnd", "dups"])
def test_without_an_index_one_row_offers_to_build_it(env, query):
    items = search_items(query)

    assert titles(items) == ["No index yet"], f"kb {query} without an index should show a single feedback row"
    assert items[0]["valid"] is True and items[0]["arg"] == "", "↩ on the feedback row should be actionable"
    assert action_of(items[0]) == "update", "↩ on the feedback row should rebuild the index"


def test_an_index_from_an_older_version_offers_a_rebuild(indexed, tmp_path):
    with sqlite3.connect(tmp_path / "alfred-data" / "library.db") as conn:
        conn.execute("PRAGMA user_version = 0")

    items = search_items("deep")

    assert titles(items) == ["Index is from an older version"], "an old index should be explained, not read"
    assert action_of(items[0]) == "update", "↩ should rebuild it"


def test_an_empty_index_asks_whether_the_card_is_mounted(env, library, capsys):
    for book in [p for p in library.rglob("*") if p.is_file()]:
        book.unlink()
    main(["index"])
    capsys.readouterr()

    (item,) = search_items("")

    assert item["title"] == "Index is empty — is the card mounted? Alfred needs Removable Volumes access", (
        "the likely causes should be named"
    )
    assert action_of(item) == "update", "↩ should rebuild the index"


def test_no_matches_names_the_words(indexed):
    (item,) = search_items("zzz qqq")

    assert item["title"] == "No books match ‘zzz qqq’" and item["valid"] is False, "an empty result should repeat what was typed"


@pytest.mark.parametrize("fixture", ["env", "indexed"])
def test_update_row_rebuilds_the_index(request, fixture):
    request.getfixturevalue(fixture)

    item = search_items("update")[0]

    assert item["title"] == "Rebuild the index" and item["valid"] is True, "kb update should offer the rebuild, index or not"
    assert item["arg"] == "" and action_of(item) == "update", "↩ should run update with no argument"


@pytest.mark.parametrize("word", ["index", "sources"])
def test_retired_command_words_are_plain_search(indexed, word):
    assert titles(search_items(word)) == [f"No books match ‘{word}’"], f"{word!r} is no longer a command, just a word"


@pytest.mark.parametrize(
    "query, suggested",
    [
        ("up", ["update"]),
        ("IN", ["inbox"]),
        ("cl", ["classify"]),
        ("ra", ["random"]),
        ("sr", ["src"]),
        ("st", ["stats"]),
    ],
)
def test_prefix_suggests_commands(indexed, query, suggested):
    items = search_items(query)

    hints = [i for i in items if i.get("autocomplete", "").rstrip() in suggested]
    assert [h["autocomplete"] for h in hints] == [f"{s} " for s in suggested], f"kb {query} should offer to complete to kb {suggested}"
    assert all(h["valid"] is False and h["title"] == f"kb {h['autocomplete'].strip()}" for h in hints), (
        "a suggestion completes the word on ↩/⇥ rather than acting"
    )
    assert items[: len(hints)] == hints, "suggestions come before any books matching the letters"


@pytest.mark.parametrize("query", ["u", "up deep", "update", "zzz", "so", "ind"])
def test_other_input_suggests_no_command(indexed, query):
    items = search_items(query)

    assert not any(i.get("title", "").startswith("kb ") for i in items), f"{query!r} should not produce completion hints"


def test_suggestions_work_before_any_index(env):
    assert search_items("up")[0]["autocomplete"] == "update ", "completing to kb update must work before the first index exists"
