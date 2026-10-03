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
        main(["genre", str(library / "00_Inbox" / name), "reference"])
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
    main(["update"])
    capsys.readouterr()

    found = titles(search_items("stats"))

    assert found[-1] == "Stats for Dummies" and len(found) > 1, "the stats rows should come first, then the book matching the word"


def test_a_command_word_never_hides_a_book(env, library, capsys):
    (library / "00_Inbox" / "Update Your Life - Smith, John.pdf").write_bytes(b"%PDF-1.4")
    main(["update"])
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
    main(["update"])
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


def command_rows(query: str) -> list[dict]:
    from kobolib.commands import COMMANDS

    word, *rest = query.split()
    return COMMANDS[word].items(rest)


def age(path: Path, seconds: int) -> None:
    import os

    os.utime(path, (seconds, seconds))


@pytest.fixture
def aged_inbox(library: Path, capsys) -> None:
    age(library / "00_Inbox" / "Napkin.pdf", 2)
    age(library / "00_Inbox" / "Скиннер - Оперантное поведение.fb2", 1)
    main(["update"])
    capsys.readouterr()


def no_bulk_modifier(items: list[dict]) -> bool:
    return not any("alt+shift" in i.get("mods", {}) for i in items)


def test_inbox_lists_complete_books_without_a_genre_oldest_first(env, aged_inbox):
    items = command_rows("inbox")

    assert titles(items) == ["Оперантное поведение", "Napkin"], "inbox should list complete unclassified books, oldest first"
    assert {action_of(i) for i in search_items("inbox")[:2]} == {"open"}, "↩ on an inbox book opens it"
    assert no_bulk_modifier(items), "bulk work is a head row, never a modifier"


def test_inbox_is_narrowed_by_words(indexed):
    assert titles(search_items("inbox napkin")) == ["Napkin"], "the words narrow the inbox, and the book is listed once"


def test_empty_inbox_says_so(indexed, library, capsys):
    classify_inbox(library, capsys)

    assert titles(command_rows("inbox")) == ["Inbox is empty"], "an empty inbox should be stated"


def test_classify_without_words_lists_the_inbox_under_a_head_row(env, aged_inbox):
    head, *rows = search_items("classify")

    assert head["title"] == "Set genre for all 2 books" and head["arg"] == "", "the head row opens the picker for every listed book"
    assert head["variables"] == {"book": "\n".join(r["variables"]["book"] for r in rows), "action": "classify"}, (
        "the head row should carry every listed fingerprint to the genre picker"
    )
    assert titles(rows) == ["Оперантное поведение", "Napkin"], "without words classify lists the inbox"
    assert all(r["arg"] == "" and action_of(r) == "classify" for r in rows), "↩ on a row picks a genre for that book"
    assert no_bulk_modifier(rows), "bulk work is a head row, never a modifier"


@pytest.mark.parametrize("words, expected", [("deep", ["Deep Work"]), ("nonfiction", ["Deep Work"]), ("napkin", ["Napkin"])])
def test_classify_with_words_lists_matching_library_books_of_any_genre(indexed, words, expected):
    rows = command_rows(f"classify {words}")

    assert titles(rows) == expected, f"classify {words} should list every matching library book, classified or not"
    assert action_of(search_items(f"classify {words}")[0]) == "classify", "↩ should open the genre picker"


def test_classify_with_nothing_to_do_says_so(indexed, library, capsys):
    classify_inbox(library, capsys)

    assert titles(command_rows("classify")) == ["Nothing to classify"], "an empty inbox leaves nothing to classify"


@pytest.fixture
def second_deep_work(env, library: Path, capsys) -> None:
    (library / "00_Inbox" / "Newport, Cal - Deep Work.pdf").write_bytes(b"%PDF-1.4")
    main(["update"])
    capsys.readouterr()


def test_dups_lists_every_copy_as_a_book_row(second_deep_work):
    rows = command_rows("dups")

    assert titles(rows) == ["Deep Work", "Deep Work"], "each copy should be its own row, the copies side by side"
    assert all(r["subtitle"].startswith("×2 · ") for r in rows), "the subtitle should start with the number of copies"
    assert {action_of(i) for i in search_items("dups")[:2]} == {"open"}, "↩ opens the copy"
    assert len({r["uid"] for r in rows}) == 2, "each row is a real file"


def test_dups_ignores_unfinished_downloads(indexed, library, capsys):
    (library / "00_Inbox" / "Newport, Cal - Deep Work.fb2.part").write_bytes(b"")
    main(["update"])
    capsys.readouterr()

    assert titles(command_rows("dups")) == ["No duplicate titles"], "a .part file is not a copy"


@pytest.mark.parametrize("words, count", [("newport", 2), ("pdf", 2), ("napkin", 0)])
def test_dups_words_keep_whole_groups(second_deep_work, words, count):
    rows = [r for r in command_rows(f"dups {words}") if "quicklookurl" in r]

    assert len(rows) == count, f"dups {words} should keep every copy of a title when any copy matches"


def test_stats_rows_count_and_complete_to_their_command(indexed):
    rows = command_rows("stats")

    assert titles(rows) == [
        "3 books",
        "2 books without a genre",
        "0 duplicate titles",
        "1 pending fix",
        "1 unfinished download",
    ], "stats should count books, inbox, duplicate titles, pending fixes and unfinished downloads"
    assert [r["autocomplete"] for r in rows] == ["", "inbox ", "dups ", "fix ", "trash "], "↩ on a row completes to its command"
    assert all(r["valid"] is False for r in rows), "stats rows navigate rather than act"


NOVA = "00_Inbox/Delany, Samuel R - Nova - 2014.epub.part"
DEEP = "02_NonFiction/Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"


def test_trash_without_words_lists_unfinished_downloads(indexed, library):
    (row,) = search_items("trash")

    assert row["title"] == "Nova" and row["valid"] is True, "an unfinished download is actionable in kb trash"
    assert row["subtitle"].startswith("unfinished download · "), "the subtitle should say why it is listed"
    assert row["arg"] == str(library / NOVA) and action_of(row) == "trash", "↩ should move that file to _trash/"


def test_trash_with_words_lists_downloads_then_library_books_under_a_head_row(indexed, library):
    head, *rows = search_items("trash inbox")

    assert titles(rows)[0] == "Nova", "unfinished downloads matching the words come first"
    assert set(titles(rows[1:])) == {"Napkin", "Оперантное поведение"}, "then every library book matching the words"
    assert head["title"] == "Trash all 3 books" and action_of(head) == "trash", "two or more rows start with a head row"
    assert head["arg"] == "\n".join(r["arg"] for r in rows), "the head row carries every listed path"


def test_trash_with_nothing_to_trash_says_so(indexed, library, capsys):
    (library / NOVA).unlink()
    main(["update"])
    capsys.readouterr()

    assert titles(search_items("trash")) == ["Nothing to trash"], "without unfinished downloads there is nothing to list"


def by_uid(items: list[dict], prefix: str) -> list[dict]:
    return [i for i in items if i.get("uid", "").startswith(prefix)]


def test_fix_lists_head_row_reminders_operations_then_problems(indexed, library):
    items = command_rows("fix")

    assert [i["uid"].split(":")[0] for i in items] == ["fix", "reminder", "reminder", "fix", "problem"], (
        "fix should list: fix all, reminders, operations, then problems by hand"
    )
    head, inbox, partial, move, napkin = items
    assert (head["title"], head["subtitle"]) == ("Fix all 1", "1 move"), "the head row should count operations by kind"
    assert (inbox["title"], inbox["autocomplete"]) == ("2 books without a genre", "classify "), (
        "the inbox reminder completes to kb classify"
    )
    assert (partial["title"], partial["autocomplete"]) == ("1 unfinished download", "trash "), "the partial reminder completes to kb trash"
    assert move["arg"] == str(library / DEEP) and move["subtitle"].startswith("move · "), "an operation row carries the file it moves"
    assert napkin["arg"] == str(library / "00_Inbox" / "Napkin.pdf"), "a problem row carries the file to fix by hand"


def test_fix_rows_carry_their_own_actions(indexed):
    items = search_items("fix")

    assert [action_of(i) for i in by_uid(items, "fix")] == ["fix", "fix"], "↩ on fix all or on an operation applies it"
    assert [action_of(i) for i in by_uid(items, "problem")] == ["reveal"], "↩ on a problem reveals the file"
    assert all(i["valid"] is False for i in by_uid(items, "reminder")), "reminders complete the query instead of acting"


def test_fix_offers_undo_after_a_batch(indexed, library, capsys):
    main(["apply", "--only", str(library / DEEP)])
    capsys.readouterr()

    (undo,) = by_uid(search_items("fix"), "undo")

    assert undo["title"] == "Undo last batch (1 move)" and action_of(undo) == "undo", "a journaled batch can be undone from kb fix"
    assert not by_uid(command_rows("fix"), "fix"), "the applied move is no longer offered"


@pytest.mark.parametrize(
    "words, uids",
    [
        ("newport", ["fix:all", f"fix:{DEEP}"]),
        ("napkin", ["reminder:inbox", "problem:opaque:00_Inbox/Napkin.pdf"]),
        ("delany", ["reminder:partials"]),
    ],
)
def test_fix_words_narrow_every_list(indexed, words, uids):
    assert [i["uid"] for i in command_rows(f"fix {words}")] == uids, f"kb fix {words} should only show what concerns matching books"


def test_fix_reminders_keep_the_words(indexed):
    (reminder,) = command_rows("fix napkin")[:1]

    assert reminder["autocomplete"] == "classify napkin ", "the reminder should complete to kb classify with the same words"


def test_fix_head_row_carries_the_listed_paths_when_narrowed(indexed, library):
    assert command_rows("fix")[0]["arg"] == "", "unnarrowed, fix all applies everything"
    assert command_rows("fix newport")[0]["arg"] == str(library / DEEP), "narrowed, fix all applies only what is listed"


def test_fix_with_nothing_to_show_says_so(indexed):
    assert titles(command_rows("fix zzz")) == ["Nothing to fix for ‘zzz’"], "an empty fix list should say so"


@pytest.mark.parametrize("word", ["lint", "plan", "apply", "undo"])
def test_fix_replaces_the_old_commands(indexed, word):
    assert titles(search_items(word)) == [f"No books match ‘{word}’"], f"{word!r} is now a plain word; kb fix replaces it"


@pytest.fixture
def napkin(indexed, library, capsys) -> str:
    main(["genre", str(library / "00_Inbox" / "Napkin.pdf"), "fiction/spy"])
    capsys.readouterr()
    return next(i for i in search_items("napkin") if "quicklookurl" in i)["variables"]["book"]


def picker(typed: str, books: str) -> list[dict]:
    from kobolib.commands import genre_picker_items

    return genre_picker_items(typed, books.splitlines())


def test_picker_shows_the_book_then_keeps_its_genre_first(napkin):
    header, keep, *others = picker("", napkin)

    assert (header["title"], header["subtitle"], header["valid"]) == ("Napkin", "fiction/spy · 00_Inbox/Napkin.pdf", False), (
        "the header should show the book, its genre and path"
    )
    assert (keep["title"], keep["subtitle"], keep["arg"]) == ("Keep fiction/spy", "moves the book home if it isn't", "fiction/spy"), (
        "the current genre comes first, offered as keep"
    )
    assert titles(others) == ["nonfiction"], "the other known genres follow"


@pytest.mark.parametrize("typed, genres", [("SPY", ["fiction/spy"]), ("tion/sp", ["fiction/spy"]), ("non", ["nonfiction"])])
def test_picker_matches_typed_text_anywhere_in_the_genre(napkin, typed, genres):
    assert [i["arg"] for i in picker(typed, napkin)[1:]] == genres, f"{typed!r} should match a genre anywhere in its path, ignoring case"


def test_picker_rows_create_the_typed_text_on_shift(napkin):
    keep = picker("spy", napkin)[1]

    assert keep["mods"]["shift"]["arg"] == "spy", "⇧↩ on any row creates the typed text as a new genre"


def test_picker_offers_a_single_create_row_when_nothing_matches(napkin):
    header, only = picker("zzz", napkin)

    assert only["title"] == "No genre ‘zzz’ — ⇧↩ creates it" and only["valid"] is False, "↩ does nothing; ⇧↩ creates the genre"


def test_picker_rows_carry_the_book_and_the_genre_action(napkin):
    rows = picker("", napkin)[1:]

    assert all(r["variables"] == {"book": napkin, "action": "genre"} for r in rows), "every row should send the book to the genre step"
    assert [r["autocomplete"] for r in rows] == [r["arg"] for r in rows], "⇥ should complete the genre itself"


def test_picker_for_a_book_without_genre_has_no_keep_row(indexed):
    book = next(i for i in search_items("napkin") if "quicklookurl" in i)["variables"]["book"]

    assert not any(i["title"].startswith("Keep ") for i in picker("", book)), "there is nothing to keep without a genre"


def test_picker_for_several_books_says_how_many(napkin, indexed):
    other = next(i for i in search_items("deep") if "quicklookurl" in i)["variables"]["book"]
    books = f"{napkin}\n{other}"

    header, *rows = picker("", books)

    assert header["title"] == "2 books" and header["valid"] is False, "the header should count the books"
    assert not any(r["title"].startswith("Keep ") for r in rows), "a bulk pick has no single current genre"
    assert all(r["variables"]["book"] == books for r in rows), "every row carries all the books"


@pytest.mark.parametrize("books", ["", "nope"])
def test_picker_without_a_known_book_explains(indexed, books):
    assert titles(picker("", books)) == ["No book selected"], "the picker needs a book to set the genre of"
