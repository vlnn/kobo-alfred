import sqlite3
from pathlib import Path

import pytest

from kobold.cli import main
from kobold.commands import EMPTY_INDEX, search_items


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


def test_an_empty_index_asks_whether_the_library_folder_is_there(env, library, capsys):
    for book in [p for p in library.rglob("*") if p.is_file()]:
        book.unlink()
    main(["update"])
    capsys.readouterr()

    (item,) = search_items("")

    assert item["title"] == EMPTY_INDEX, "the likely causes should be named"
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
    from kobold.commands import COMMANDS

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
        "0 books embedded",
    ], "stats should count books, inbox, duplicate titles, pending fixes, unfinished downloads and embedded books"
    assert [r["autocomplete"] for r in rows] == ["", "inbox ", "dups ", "fix ", "trash ", "model "], "↩ on a row completes to its command"
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
    main(["fix", str(library / DEEP)])
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
    from kobold.commands import genre_picker_items

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


SPY, BUSINESS, HISTORY, SCIFI = "fiction/spy", "nonfiction/business", "nonfiction/history", "fiction/sci-fi_fantasy"


@pytest.mark.parametrize(
    "subjects, known, expected",
    [
        ("Business; Attention economy", [SPY, BUSINESS, "reference"], [BUSINESS, SPY, "reference"]),
        ("Science Fiction", [HISTORY, SCIFI, SPY], [SCIFI, SPY, HISTORY]),
        ("", [HISTORY, SPY], [HISTORY, SPY]),
        ("History", [HISTORY, "fiction/historical"], [HISTORY, "fiction/historical"]),
    ],
)
def test_genres_sharing_a_word_with_the_subjects_come_first(subjects, known, expected):
    from kobold.commands import subject_likely_first

    assert subject_likely_first(known, subjects) == expected, f"{subjects!r} should lift the genres that share a word with it"


def test_picker_lifts_genres_matching_the_books_subjects(indexed, library, capsys):
    for name, genre in (("Napkin.pdf", "fiction/spy"), ("Скиннер - Оперантное поведение.fb2", "nonfiction/business")):
        main(["genre", str(library / "00_Inbox" / name), genre])
    capsys.readouterr()
    deep = next(i for i in search_items("deep") if "quicklookurl" in i)["variables"]["book"]

    header, keep, *others = picker("", deep)

    assert keep["title"] == "Keep nonfiction", "the current genre still comes first"
    assert titles(others) == ["nonfiction/business", "fiction/spy"], "then the genre sharing a word with the book's subjects, then the rest"


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


def test_update_row_says_when_an_update_is_running(indexed, tmp_path):
    (tmp_path / "alfred-data" / "library.lock").write_text("1")

    (row,) = command_rows("update")

    assert row["title"] == "Update is running" and row["valid"] is False, "a running update should be stated, not started twice"


def test_headed_shows_every_head_row_only_for_a_batch():
    from kobold.commands import headed

    heads, items = [{"uid": "a"}, {"uid": "b"}], [{"uid": "x"}, {"uid": "y"}]

    assert headed(heads, items, 2) == [*heads, *items], "a list of several books starts with all its head rows"
    assert headed(heads, items[:1], 1) == items[:1], "a single book needs no head rows"


def suggest(tmp_path: Path, fingerprint: str, question: str, answer: dict) -> None:
    from kobold.suggestions import SuggestionStore

    store = SuggestionStore(tmp_path / "alfred-data" / "oracle.tsv").load()
    store.set(fingerprint, question, answer, "h")
    store.save()


def fingerprint_of(query: str) -> str:
    return next(i for i in search_items(query) if "quicklookurl" in i)["variables"]["book"]


@pytest.fixture
def suggested_napkin(indexed, tmp_path) -> str:
    napkin = fingerprint_of("napkin")
    suggest(tmp_path, napkin, "genre", {"genre": "reference"})
    suggest(tmp_path, fingerprint_of("оперантное"), "genre", {"genre": "none"})
    return napkin


def test_classify_marks_suggested_genres_with_a_question_mark(suggested_napkin):
    rows = [r for r in command_rows("classify") if "quicklookurl" in r]

    by_title = {r["title"]: r["subtitle"] for r in rows}
    assert " · reference? · " in by_title["Napkin"], "a suggested genre shows where genre ? was, with a trailing ?"
    assert " · genre ? · " in by_title["Оперантное поведение"], "a none answer leaves the plain marker"


def test_classify_offers_to_accept_the_suggested_genres(suggested_napkin):
    head, accept, *rows = command_rows("classify")

    assert head["title"] == "Set genre for all 2 books", "the usual head row comes first"
    assert accept["title"] == "Accept 1 suggested genre" and accept["arg"] == "", "then the suggestions, as one head row"
    assert accept["variables"] == {"book": f"{suggested_napkin}\treference", "action": "genre"}, (
        "the head row carries fingerprint and genre pairs to the genre step"
    )
    assert "mods" not in accept, "bulk work is a head row, never a modifier"


def test_classify_without_suggestions_has_no_accept_row(indexed):
    assert not any(i["title"].startswith("Accept ") for i in command_rows("classify")), "nothing to accept, nothing offered"


def test_picker_puts_the_suggested_genre_first(suggested_napkin):
    header, suggested, *others = picker("", suggested_napkin)

    assert (suggested["title"], suggested["arg"], suggested["subtitle"]) == (
        "reference",
        "reference",
        "suggested · ↩ sets it and moves the book home",
    ), "the suggestion is the first row, marked as such"
    assert suggested["variables"] == {"book": suggested_napkin, "action": "genre"}, "↩ on it sets the genre like any other row"
    assert "reference" not in titles(others), "the suggested genre is not listed twice"


def test_picker_filters_the_suggestion_by_typed_text(suggested_napkin):
    assert titles(picker("non", suggested_napkin)) == ["Napkin", "nonfiction"], (
        "a suggestion that does not match the typed text is left out"
    )


@pytest.fixture
def oracle_on(indexed, monkeypatch):
    monkeypatch.setenv("KOBOLD_ORACLE_URL", "http://127.0.0.1:8080")


def test_the_ask_row_counts_every_candidate_the_pass_would_ask_about(oracle_on, mocker):
    from kobold.index import EVERYTHING, Index

    unclassified = mocker.spy(Index, "unclassified")
    search = mocker.spy(Index, "search")

    command_rows("classify")

    counted = [c.kwargs.get("limit") for c in unclassified.call_args_list + search.call_args_list if c.kwargs.get("limit")]
    assert EVERYTHING in counted and 1000 not in counted, "the row counts with the same limit the pass asks with"


@pytest.mark.parametrize("query", ["classify", "fix"])
def test_ask_the_model_row_appears_when_books_are_unasked(oracle_on, query):
    (ask,) = [i for i in command_rows(query) if i.get("uid") == "oracle:ask"]

    assert ask["title"] == "Ask the model about 2 inbox books and 1 unnamed file" and ask["valid"] is True, "the row counts what is unasked"
    assert ask["subtitle"] == "↩ runs in the background, then notifies" and action_of(ask) == "ask", "↩ runs kobold ask in the background"


@pytest.mark.parametrize("query", ["classify", "fix"])
def test_ask_the_model_row_is_absent_without_a_server(indexed, monkeypatch, query):
    monkeypatch.delenv("KOBOLD_ORACLE_URL", raising=False)

    assert not any(i.get("uid") == "oracle:ask" for i in command_rows(query)), "nothing mentions the oracle until it is configured"


def test_ask_the_model_row_is_absent_when_everything_is_asked(oracle_on, suggested_napkin, tmp_path):
    suggest(tmp_path, suggested_napkin, "name", {"title": "Napkin", "authors": [], "confident": False})

    assert not any(i.get("uid") == "oracle:ask" for i in command_rows("classify")), "answered books, none included, are not offered again"


@pytest.mark.parametrize("query", ["classify", "fix"])
def test_unreachable_model_is_reported(oracle_on, tmp_path, query):
    (tmp_path / "alfred-data" / "oracle.status").write_text("http://127.0.0.1:8080")

    (row,) = [i for i in command_rows(query) if i.get("uid") == "oracle:unreachable"]

    assert row["title"] == "Model not reachable at http://127.0.0.1:8080" and row["valid"] is False, "the last failed connection is shown"


NAPKIN_NAME = {"title": "Table Napkin Folding", "authors": ["Ivor Penhale"], "confident": True}


@pytest.fixture
def napkin_named(oracle_on, tmp_path) -> str:
    napkin = fingerprint_of("napkin")
    suggest(tmp_path, napkin, "name", NAPKIN_NAME)
    return napkin


def test_fix_lists_a_suggested_rename_below_the_automatic_operations(napkin_named, library):
    items = command_rows("fix")

    uids = [i["uid"] for i in items]
    assert uids == ["fix:all", "oracle:ask", "reminder:inbox", "reminder:partials", f"fix:{DEEP}", "fix:00_Inbox/Napkin.pdf"], (
        "the suggested rename comes after the certain operations and replaces the opaque-name problem"
    )
    head, rename = items[0], items[-1]
    assert (head["title"], head["subtitle"]) == ("Fix all 1", "1 move"), "Fix all counts only what is certain"
    assert rename["title"] == "Penhale, Ivor - Table Napkin Folding.pdf", "the row shows the canonical name built from the suggestion"
    assert rename["subtitle"] == "move · suggested title and author · 00_Inbox/Napkin.pdf → 00_Inbox/", "and says it is a suggestion"
    assert rename["arg"] == str(library / "00_Inbox" / "Napkin.pdf") and rename["valid"] is True, "↩ applies that one move"
    assert action_of(search_items("fix")[-1]) == "fix", "through the fix action"


def test_fix_all_with_words_carries_only_certain_paths(napkin_named, library):
    (head, *_) = command_rows("fix inbox")

    assert str(library / "00_Inbox" / "Napkin.pdf") not in head["arg"], "Fix all never applies a suggestion"


def test_an_unconfident_or_unchanged_name_is_not_offered(oracle_on, tmp_path):
    suggest(tmp_path, fingerprint_of("napkin"), "name", {**NAPKIN_NAME, "confident": False})
    suggest(tmp_path, fingerprint_of("deep"), "name", {"title": "Deep Work", "authors": ["Cal Newport", "Someone Else"], "confident": True})

    assert not any(i["subtitle"].startswith("move · suggested") for i in command_rows("fix")), (
        "neither an unsure answer nor one that changes nothing becomes a row"
    )


def test_fix_narrowed_to_one_book_offers_to_dismiss_its_suggestions(napkin_named):
    rows = command_rows("fix napkin")

    (dismiss,) = [i for i in rows if i["uid"] == "oracle:dismiss"]
    assert dismiss["title"] == "Dismiss suggestions for this book" and action_of(dismiss) == "dismiss", "↩ dismisses in the background"
    assert dismiss["variables"]["book"] == napkin_named, "the row carries the book"
    assert rows.index(dismiss) < rows.index(next(i for i in rows if i["uid"].startswith("fix:00_Inbox"))), "it is a head row"


@pytest.mark.parametrize("query", ["fix", "fix inbox", "fix deep"])
def test_dismiss_row_needs_exactly_one_book_with_suggestions(napkin_named, query):
    assert not any(i.get("uid") == "oracle:dismiss" for i in command_rows(query)), f"kb {query} is not narrowed to the suggested book"


def test_ask_the_model_row_counts_unnamed_files(oracle_on):
    (ask,) = [i for i in command_rows("fix") if i.get("uid") == "oracle:ask"]

    assert ask["title"] == "Ask the model about 2 inbox books and 1 unnamed file", "books whose name is a guess are counted too"


@pytest.fixture
def delany_merge(env, library, tmp_path, capsys, monkeypatch) -> None:
    from tests.test_cli import BABEL_ALIAS, GROUPS, NOVA_HOME, author_epub

    author_epub(library / NOVA_HOME, "Nova", "Samuel Ray Delany")
    author_epub(library / BABEL_ALIAS, "Babel-17", "Samuel Delany")
    author_epub(library / "01_Fiction/02_Sci-Fi/Delany, Samuel/Delany, Samuel - Dhalgren (2016).epub", "Dhalgren", "Samuel Delany")
    monkeypatch.setenv("KOBOLD_ORACLE_URL", "http://127.0.0.1:8080")
    main(["update"])
    capsys.readouterr()
    suggest(tmp_path, "*", "authors", GROUPS)


def test_fix_lists_one_merge_row_per_author_group(delany_merge, library):
    from tests.test_cli import BABEL_ALIAS

    (merge,) = [i for i in command_rows("fix") if i["uid"].startswith("oracle:merge")]

    assert merge["title"] == "Merge 1 author folder into Delany, Samuel Ray" and merge["subtitle"] == "↩ moves 2 books · ⌥↩ reveals", (
        "a group is one row, counting its folders and books"
    )
    assert merge["arg"].splitlines() == sorted(
        [str(library / BABEL_ALIAS), str(library / "01_Fiction/02_Sci-Fi/Delany, Samuel/Delany, Samuel - Dhalgren (2016).epub")]
    ), "↩ passes every book of the group to fix"
    assert merge["mods"]["alt"]["arg"] == str(library / "01_Fiction" / "02_Sci-Fi" / "Delany, Samuel"), "⌥↩ reveals the alias folder"
    assert action_of(next(i for i in search_items("fix") if i["uid"].startswith("oracle:merge"))) == "fix", "through the fix action"


def test_merge_rows_come_after_the_automatic_operations(delany_merge):
    uids = [i["uid"] for i in command_rows("fix")]

    merge = next(i for i, uid in enumerate(uids) if uid.startswith("oracle:merge"))
    assert merge > max(i for i, uid in enumerate(uids) if uid.startswith("fix:")), "merges follow the certain operations"
    assert merge < min(i for i, uid in enumerate(uids) if uid.startswith("problem:")), "and come before problems by hand"


@pytest.mark.parametrize("words, shown", [("dhalgren", True), ("delany", True), ("newport", False)])
def test_merge_rows_follow_the_words(delany_merge, words, shown):
    assert any(i["uid"].startswith("oracle:merge") for i in command_rows(f"fix {words}")) is shown, (
        f"kb fix {words} should {'show' if shown else 'hide'} the merge"
    )


SERVED = ["qwen2.5-7b-instruct", "gemma-3-4b-it", "bge-m3"]


@pytest.fixture
def served(oracle_on, monkeypatch, mocker):
    monkeypatch.setenv("KOBOLD_ORACLE_MODEL", "qwen2.5-7b-instruct")
    monkeypatch.setenv("KOBOLD_EMBED_MODEL", "bge-m3")
    return mocker.patch("kobold.embedder.models", return_value=SERVED)


def test_model_lists_the_servers_models_with_their_roles(served):
    oracle_row, embed_row, *models = command_rows("model")

    assert (oracle_row["title"], oracle_row["subtitle"], oracle_row["valid"]) == (
        "Oracle: qwen2.5-7b-instruct",
        "http://127.0.0.1:8080 · reachable",
        False,
    ), "the header shows the oracle's model and server"
    assert embed_row["title"] == "Embeddings: bge-m3", "then the embedding model"
    assert titles(models) == SERVED, "then every model the server lists"
    assert [m["subtitle"] for m in models] == [
        "✓ oracle · ↩ choose what it is for",
        "↩ choose what it is for",
        "✓ embeddings · ↩ choose what it is for",
    ], "the current choices are marked"
    assert all(m["arg"] == m["title"] and m["variables"] == {"model": m["title"], "action": "model"} for m in models), (
        "↩ on a model opens the chooser for it"
    )
    served.assert_called_once_with("http://127.0.0.1:8080")


def test_model_asks_both_servers_when_embeddings_live_elsewhere(served, monkeypatch):
    monkeypatch.setenv("KOBOLD_EMBED_URL", "http://127.0.0.1:8081")
    served.side_effect = lambda url: ["bge-m3"] if url.endswith("8081") else ["qwen2.5-7b-instruct"]

    rows = command_rows("model")

    assert titles(rows[2:]) == ["qwen2.5-7b-instruct", "bge-m3"], "the rows are what both servers list"
    assert served.call_count == 2, "each server is asked once"


def test_model_with_the_server_down_says_so(served):
    served.return_value = None

    rows = command_rows("model")

    assert titles(rows) == ["Oracle: qwen2.5-7b-instruct", "Embeddings: bge-m3", "Model not reachable at http://127.0.0.1:8080"], (
        "instead of the list, one row explains"
    )
    assert rows[0]["subtitle"] == "http://127.0.0.1:8080 · not reachable", "the header says so too"


def test_model_without_a_server_explains(indexed, monkeypatch):
    monkeypatch.delenv("KOBOLD_ORACLE_URL", raising=False)

    (row,) = command_rows("model")

    assert row["title"] == "No model server" and "KOBOLD_ORACLE_URL" in row["subtitle"], "the setting to fill is named"


def test_model_without_chosen_models_names_the_defaults(served, monkeypatch):
    monkeypatch.delenv("KOBOLD_ORACLE_MODEL")
    monkeypatch.delenv("KOBOLD_EMBED_MODEL")

    oracle_row, embed_row, *models = command_rows("model")

    assert oracle_row["title"] == "Oracle: server default", "without a choice the server's default model answers"
    assert embed_row["title"] == "Embeddings: none" and "↩ on a model" in embed_row["subtitle"], (
        "without an embedding model there is no kb like"
    )
    assert not any("✓" in m["subtitle"] for m in models), "nothing is marked"


def test_model_needs_no_index(env, monkeypatch, mocker):
    monkeypatch.setenv("KOBOLD_ORACLE_URL", "http://127.0.0.1:8080")
    mocker.patch("kobold.embedder.models", return_value=["bge-m3"])

    assert titles(search_items("model"))[-1] == "bge-m3", "kb model works before the first index, so you can see whether the server is up"


def test_chooser_offers_the_two_roles():
    from kobold.commands import chooser_items

    oracle_row, embed_row = chooser_items("", "gemma-3-4b-it")

    assert oracle_row["title"] == "Use gemma-3-4b-it for the oracle" and oracle_row["arg"] == "oracle", "↩ makes it the oracle"
    assert embed_row["title"] == "Use gemma-3-4b-it for embeddings" and embed_row["arg"] == "embed", "or the embedding model"
    assert "re-embeds everything" in embed_row["subtitle"] and "kept" in embed_row["subtitle"], "switching embeddings is explained"
    assert all(r["variables"] == {"model": "gemma-3-4b-it", "action": "choose"} for r in (oracle_row, embed_row)), (
        "both rows carry the model"
    )


def test_chooser_filters_by_typed_text():
    from kobold.commands import chooser_items

    assert [r["arg"] for r in chooser_items("emb", "gemma-3-4b-it")] == ["embed"], "typed text narrows the two rows"


def test_chooser_without_a_model_explains():
    from kobold.commands import chooser_items

    (row,) = chooser_items("", "")

    assert row["title"] == "No model selected" and row["valid"] is False, "the chooser needs a model from kb model"


def test_stats_counts_embedded_books(indexed, tmp_path, monkeypatch):
    from kobold.vectors import VectorStore

    monkeypatch.setenv("KOBOLD_EMBED_MODEL", "bge-m3")
    VectorStore(tmp_path / "alfred-data" / "vectors.db").put("bge-m3", fingerprint_of("napkin"), [1.0, 0.0])

    (row,) = [r for r in command_rows("stats") if "embedded" in r["title"]]

    assert row["title"] == "1 book embedded" and row["autocomplete"] == "model ", "the count is for the current model; ↩ goes to kb model"


def test_model_header_offers_to_embed_the_rest(served, tmp_path):
    from kobold.vectors import VectorStore

    VectorStore(tmp_path / "alfred-data" / "vectors.db").put("bge-m3", fingerprint_of("napkin"), [1.0, 0.0])

    embed_row = command_rows("model")[1]

    assert embed_row["subtitle"] == "1 of 3 books embedded · ↩ embeds the rest" and action_of(embed_row) == "embed", "↩ runs kobold embed"
    assert embed_row["valid"] is True, "the header is actionable while books are missing"


def test_model_header_is_quiet_when_everything_is_embedded(served, tmp_path):
    from kobold.vectors import VectorStore

    store = VectorStore(tmp_path / "alfred-data" / "vectors.db")
    for word in ("napkin", "deep", "оперантное"):
        store.put("bge-m3", fingerprint_of(word), [1.0, 0.0])

    embed_row = command_rows("model")[1]

    assert embed_row["subtitle"] == "3 books embedded" and embed_row["valid"] is False, "nothing left to embed"


def test_like_without_an_embedding_model_points_at_kb_model(indexed, monkeypatch):
    monkeypatch.delenv("KOBOLD_EMBED_MODEL", raising=False)

    row = command_rows("like deep")[0]

    assert (row["title"], row["subtitle"], row["autocomplete"]) == ("No embedding model", "↩ opens kb model", "model "), (
        "kb like needs an embedding model"
    )


@pytest.fixture
def embeddings(indexed, tmp_path, monkeypatch):
    from kobold.vectors import VectorStore

    monkeypatch.setenv("KOBOLD_EMBED_MODEL", "bge-m3")
    store = VectorStore(tmp_path / "alfred-data" / "vectors.db")
    store.put("bge-m3", fingerprint_of("deep"), [1.0, 0.0])
    store.put("bge-m3", fingerprint_of("оперантное"), [1.0, 0.3])
    store.put("bge-m3", fingerprint_of("napkin"), [0.0, 1.0])
    return store


def test_like_without_vectors_offers_to_embed(indexed, monkeypatch):
    monkeypatch.setenv("KOBOLD_EMBED_MODEL", "bge-m3")

    (row,) = command_rows("like deep")

    assert row["title"] == "No embeddings yet" and action_of(row) == "embed", "↩ embeds in the background"


def test_like_lists_the_seeds_neighbours_with_their_similarity(embeddings, library):
    header, first, second = command_rows("like deep")

    assert header["title"] == "Like Deep Work" and header["valid"] is False and header["icon"], (
        "the seed heads the list and is not actionable"
    )
    assert header["subtitle"].startswith("Cal Newport; Someone Else · Focus #2 · "), "with its usual subtitle"
    assert titles([first, second]) == ["Оперантное поведение", "Napkin"], "nearest first"
    assert first["subtitle"].startswith("96% · ") and second["subtitle"].startswith("0% · "), "the subtitle leads with the similarity"
    assert first["arg"] == str(library / "00_Inbox" / "Скиннер - Оперантное поведение.fb2") and "mods" in first, (
        "rows are ordinary book rows"
    )


def test_like_takes_the_top_search_match_as_the_seed(embeddings):
    assert command_rows("like napkin")[0]["title"] == "Like Napkin", "the words pick the seed"
    assert titles(command_rows("like")[:1]) == ["Like Napkin"], "without words and without KOReader history, the newest book"


def test_like_seeds_from_the_book_koreader_opened_last(embeddings, library):
    from tests.test_history import write_history

    write_history(
        library, 'return { { ["file"] = "/mnt/onboard/02_NonFiction/Newport, Cal - Deep Work (2016, GC) - libgen.li.epub", ["time"] = 5 } }'
    )

    assert command_rows("like")[0]["title"] == "Like Deep Work", "the last book read on the Kobo is the seed"


def test_like_leaves_out_other_editions_of_the_seed(embeddings, library, capsys, tmp_path):
    (library / "00_Inbox" / "Newport, Cal - Deep Work.pdf").write_bytes(b"%PDF-1.4")
    main(["update"])
    capsys.readouterr()
    other = next(i for i in search_items("deep pdf") if "quicklookurl" in i)["variables"]["book"]
    embeddings.put("bge-m3", other, [1.0, 0.0])

    assert "Deep Work" not in titles(command_rows("like deep epub")[1:]), "another file of the same title is not a book like it"


def test_like_offers_to_embed_new_books(embeddings, library, capsys):
    (library / "00_Inbox" / "Fresh.pdf").write_bytes(b"%PDF-1.4 fresh")
    main(["update"])
    capsys.readouterr()

    rows = command_rows("like deep")

    assert rows[-1]["title"] == "Embed 1 new book" and action_of(rows[-1]) == "embed", "books without a vector can be embedded from here"


def test_like_on_an_unembedded_seed_says_so(embeddings, library, capsys):
    (library / "00_Inbox" / "Fresh.pdf").write_bytes(b"%PDF-1.4 fresh")
    main(["update"])
    capsys.readouterr()

    header, note, embed = command_rows("like fresh")

    assert note["title"] == "Fresh is not embedded yet" and note["valid"] is False, "a seed without a vector has no neighbours yet"
    assert embed["title"] == "Embed 1 new book", "and the embed row follows"


def test_like_with_no_match_says_so(embeddings):
    assert titles(command_rows("like zzz")) == ["No books match ‘zzz’"], "no seed, no list"


@pytest.mark.parametrize("query", ["classify napkin", "fix napkin"])
def test_ask_the_model_row_follows_the_words(oracle_on, query):
    (ask,) = [i for i in command_rows(query) if i.get("uid") == "oracle:ask"]

    assert ask["title"] == "Ask the model about 1 inbox book and 1 unnamed file matching ‘napkin’", "only matching books are counted"
    assert ask["arg"] == "napkin", "↩ asks about the matching books only"


def test_ask_the_model_row_is_absent_when_no_matching_book_is_unasked(oracle_on):
    assert not any(i.get("uid") == "oracle:ask" for i in command_rows("classify deep")), "a classified, named book leaves nothing to ask"


@pytest.mark.parametrize("query", ["classify", "fix"])
def test_a_running_pass_replaces_the_ask_row(oracle_on, tmp_path, query):
    (tmp_path / "alfred-data" / "oracle.lock").write_text("1")

    rows = [i for i in command_rows(query) if i.get("uid", "").startswith("oracle:")]

    assert [(r["title"], r["valid"]) for r in rows] == [("Asking the model… a notification follows", False)], (
        "while a pass runs the row reports it instead of starting another"
    )


def test_a_running_pass_replaces_the_embed_row(embeddings, library, tmp_path, capsys):
    (library / "00_Inbox" / "Fresh.pdf").write_bytes(b"%PDF-1.4 fresh")
    main(["update"])
    capsys.readouterr()
    (tmp_path / "alfred-data" / "oracle.lock").write_text("1")

    assert command_rows("like deep")[-1]["title"] == "Embedding… a notification follows", "kb like says a pass is running"
