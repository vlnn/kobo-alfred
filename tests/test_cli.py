import json
from pathlib import Path

import pytest

from kobolib.cli import main, notify
from kobolib.index import IndexBusy


def inbox_rows() -> list[dict]:
    from kobolib.commands import inbox_items

    return [i for i in inbox_items([]) if "quicklookurl" in i]


def output(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def run(argv: list[str], capsys) -> dict:
    main(argv)
    return output(capsys)


def test_search_before_index_explains(env, capsys):
    assert run(["search", "deep"], capsys)["items"][0]["title"] == "No index yet", "search without index should tell how to build it"


def test_index_then_search(env, capsys):
    assert main(["update"]) == 0, "index should succeed on a mounted library"
    capsys.readouterr()

    items = run(["search", "deep"], capsys)["items"]
    assert [i["title"] for i in items] == ["Deep Work"], "search should hit the indexed epub"
    assert items[0]["subtitle"].endswith("02_NonFiction/Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"), (
        "subtitle should end with the library-relative path"
    )


def test_update_ends_with_the_inbox_count(env, capsys):
    assert main(["update", "--no-thumbnails"]) == 0, "update should succeed on a mounted library"

    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith("Indexed 4 books from ") and first.endswith(" · 2 books without a genre"), (
        "the update summary should end with the inbox count"
    )


@pytest.mark.parametrize("retired", ["index", "index-sources"])
def test_index_subcommands_are_gone(env, retired):
    with pytest.raises(SystemExit):
        main([retired])


def test_index_fails_when_root_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("KOBO_ROOT", str(tmp_path / "missing"))
    monkeypatch.setenv("alfred_workflow_data", str(tmp_path / "c"))
    assert main(["update"]) == 1, "index should fail when the volume is not mounted"


def test_kobo_data_overrides_alfred_data_dir(env, tmp_path, monkeypatch):
    monkeypatch.setenv("KOBO_DATA", str(tmp_path / "custom"))
    main(["update"])
    assert (tmp_path / "custom" / "library.db").exists(), "KOBO_DATA should decide where the index lives"


def test_index_reports_inaccessible_root(env, library, capsys, mocker):
    mocker.patch("kobolib.library.build_index", return_value=0)
    mocker.patch("kobolib.library.probe_root", return_value="permission denied reading root")

    assert main(["update"]) == 1, "index should fail when no books were found"
    assert "permission denied" in capsys.readouterr().out, "the failure message should explain why"


def test_index_notify_posts_notification(env, capsys, mocker):
    run = mocker.patch("kobolib.cli.subprocess.run")

    main(["update", "--notify"])

    scripts = [c.args[0][-1] for c in run.call_args_list if c.args[0][0] == "osascript"]
    assert "Indexed 4 books" in scripts[0], "first notification should carry the index summary"
    assert "PDF covers" in scripts[1], "second notification should report the thumbnail pass"


def test_index_busy_is_reported(env, capsys, mocker):
    mocker.patch("kobolib.library.build_index", side_effect=IndexBusy("busy"))

    assert main(["update"]) == 1, "busy index should exit non-zero"
    assert "already running" in capsys.readouterr().out, "busy index should be explained"


def test_no_thumbnails_flag_skips_second_pass(env, capsys, mocker):
    fill = mocker.patch("kobolib.cli.fill_thumbnails")
    main(["update", "--no-thumbnails"])
    fill.assert_not_called()


def test_index_bootstraps_genres_from_folders(indexed, tmp_path, capsys):

    titles = [i["title"] for i in inbox_rows()]
    assert "Deep Work" not in titles, "a book in a genre folder should be classified by index"
    assert "Napkin" in titles, "an inbox book should wait for classification"


def test_genre_command_sets_genre_by_path(indexed, library, capsys):
    book = str(library / "00_Inbox" / "Napkin.pdf")

    assert main(["genre", book, "reference"]) == 0, "setting a genre by path should succeed"
    assert capsys.readouterr().out.startswith("Napkin → reference"), "the result should be reported"
    assert [i["title"] for i in run(["search", "reference"], capsys)["items"]] == ["Napkin"], "the genre should be searchable"
    assert "Napkin" not in [i["title"] for i in inbox_rows()], "a classified book leaves the inbox"


def test_genre_command_accepts_a_fingerprint(indexed, capsys):
    fingerprint = run(["search", "napkin"], capsys)["items"][0]["variables"]["book"]

    assert main(["genre", fingerprint, "reference"]) == 0, "a fingerprint from the picker should identify the book"
    assert capsys.readouterr().out.startswith("Napkin → reference"), "the result should be reported"


@pytest.mark.parametrize("argv", [["genre", "reference"], ["genre"]])
def test_genre_needs_books_then_a_genre(indexed, argv):
    with pytest.raises(SystemExit):
        main(argv)


def test_genre_lowercases_and_trims_the_genre(indexed, library, capsys):
    main(["genre", str(library / "00_Inbox" / "Napkin.pdf"), "  Games/Go "])

    assert capsys.readouterr().out.startswith("Napkin → games/go"), "genres are stored trimmed and in lower case"


def test_genres_renders_the_picker_for_the_selected_book(indexed, capsys, monkeypatch):
    monkeypatch.setenv("book", run(["search", "napkin"], capsys)["items"][0]["variables"]["book"])

    items = run(["genres", "non"], capsys)["items"]

    assert [i["title"] for i in items] == ["Napkin", "nonfiction"], "the picker shows the book, then genres matching the typed text"


def test_index_writes_the_genre_store(indexed, tmp_path):
    assert (tmp_path / "alfred-data" / "genres.tsv").exists(), "indexing should save genres to genres.tsv"


def test_classify_lists_unclassified_with_book_variable(indexed, library, capsys):

    items = run(["search", "classify napkin"], capsys)["items"]
    assert [i["title"] for i in items] == ["Napkin"], "classify should filter the inbox by the query"
    assert items[0]["arg"] == "" and len(items[0]["variables"]["book"]) == 40, "the book travels as a variable, the query starts empty"


@pytest.mark.parametrize("book", ["one", "one\ntwo"])
def test_genres_before_any_index_explains(env, capsys, monkeypatch, book):
    monkeypatch.setenv("book", book)

    assert run(["genres", ""], capsys)["items"][0]["title"] == "No index yet", "the genre picker without an index should explain"


def test_genres_without_book_explains(indexed, library, capsys, monkeypatch):
    monkeypatch.delenv("book", raising=False)

    assert run(["genres", ""], capsys)["items"][0]["valid"] is False, "without a selected book the picker must not be actionable"


def test_search_items_offer_the_genre_picker_on_shift(indexed, capsys):

    item = run(["search", "deep"], capsys)["items"][0]
    assert item["mods"]["shift"]["arg"] == "", "shift+↩ should open the genre picker with an empty query"
    assert "genre" in item["mods"]["shift"]["subtitle"].lower(), "the shift subtitle should say it sets the genre"
    assert item["variables"]["book"] == item["mods"]["shift"]["variables"]["book"], "the fingerprint must travel with the shift action"


def test_genre_moves_the_book_to_its_genre_home(indexed, library, capsys):
    book = library / "02_NonFiction" / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"

    assert main(["genre", str(book), "productivity"]) == 0, "tagging with a genre should succeed"
    out = capsys.readouterr().out

    assert not book.exists(), "the book should leave its old folder as soon as the genre is set"
    moved = list(library.rglob("*.epub"))
    assert len(moved) == 1 and moved[0].parts[-3:-1] == ("productivity", "Newport, Cal"), "the book should land in genre/author"
    assert "Deep Work → productivity" in out and "→ productivity/Newport, Cal/" in out, "the report should name the new home"
    assert run(["search", "deep"], capsys)["items"][0]["subtitle"].count("productivity") >= 1, "the index should already know the new path"


def test_single_book_moves_update_the_index_in_place(indexed, library, capsys, mocker):
    rebuild = mocker.patch("kobolib.library.build_index")
    book = library / "02_NonFiction" / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"

    main(["genre", str(book), "productivity"])
    capsys.readouterr()

    rebuild.assert_not_called()
    items = run(["search", "deep"], capsys)["items"]
    assert items[0]["subtitle"].endswith("productivity/Newport, Cal/Newport, Cal - Deep Work (Focus 02) (2016).epub"), (
        "one moved book should not re-read every other book; the row itself is relocated"
    )
    assert "No books match" in run(["search", "nonfiction"], capsys)["items"][0]["title"], "the old path should be gone from the index"


def test_single_book_move_updates_the_genre_store_path(indexed, library, tmp_path, capsys):
    import csv

    main(["genre", str(library / "02_NonFiction" / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"), "productivity"])

    with (tmp_path / "alfred-data" / "genres.tsv").open(newline="", encoding="utf-8") as handle:
        paths = {r["rel_path"] for r in csv.DictReader(handle, delimiter="\t")}
    assert "productivity/Newport, Cal/Newport, Cal - Deep Work (Focus 02) (2016).epub" in paths, (
        "genres.tsv should name the book's new path right away"
    )


def test_genre_reports_when_there_is_no_home_yet(indexed, library, capsys):
    book = library / "00_Inbox" / "Napkin.pdf"

    assert main(["genre", str(book), "reference"]) == 0, "a book without an author can still be tagged"

    assert book.exists(), "a book whose home cannot be derived stays put"
    assert "stays put" in capsys.readouterr().out, "the report should say the book was not moved"


def test_genre_accepts_notify_like_the_other_movers(indexed, library, mocker):
    notify = mocker.patch("kobolib.cli.notify")
    book = library / "02_NonFiction" / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"

    assert main(["genre", "--notify", str(book), "productivity"]) == 0, "--notify should be accepted before the book"

    assert notify.call_count == 1 and "moved → productivity/" in notify.call_args.args[0], "the notification should name the new home"


def test_notify_passes_the_message_as_an_argument(mocker):
    run = mocker.patch("kobolib.cli.subprocess.run")
    message = 'Deep "Work" → C:\\Users'

    notify(message)

    argv = run.call_args.args[0]
    assert argv[-1] == message, "the message must reach osascript verbatim, never spliced into the script"
    assert not any(message in a for a in argv[:-1]), "the message must not be interpolated into the AppleScript source"


def fingerprints_of(items: list[dict]) -> list[str]:
    return [i["variables"]["book"] for i in items if "mods" in i and i.get("valid", True)]


def test_genre_classifies_many_books_at_once(indexed, library, capsys):
    books = "\n".join(fingerprints_of(inbox_rows()))

    assert main(["genre", books, "reference"]) == 0, "setting the genre of several books should succeed"

    assert capsys.readouterr().out.startswith("2 books → reference · 1 moved, 1 stayed put"), "the summary counts moved and unmoved books"
    assert fingerprints_of(inbox_rows()) == [], "both books leave the inbox; only the partial download stays"
    assert len(run(["search", "reference"], capsys)["items"]) == 2, "both books carry the genre"


def test_genre_skips_unknown_references_in_a_batch(indexed, library, capsys):
    known = fingerprints_of(inbox_rows())[0]

    assert main(["genre", f"{known}\nnope", "reference"]) == 0, "one unknown reference does not fail the batch"
    assert "skipped 1" in capsys.readouterr().out, "the unknown reference should be mentioned"


DEEP_WORK = "02_NonFiction/Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"
DEEP_WORK_HOME = "02_NonFiction/Newport, Cal/Newport, Cal - Deep Work (Focus 02) (2016).epub"
NOVA = "00_Inbox/Delany, Samuel R - Nova - 2014.epub.part"


def test_fix_dry_run_prints_one_operation_per_line(indexed, library, capsys):
    assert main(["fix", "--dry-run"]) == 0, "a dry run should succeed"

    assert capsys.readouterr().out == f"move\t{DEEP_WORK}\t{DEEP_WORK_HOME}\trelocate + rename\n", (
        "one line per operation: kind, src, dst, reason"
    )
    assert (library / DEEP_WORK).exists(), "a dry run must not move anything"


def test_fix_applies_everything_then_rebuilds_the_index(indexed, library, tmp_path, capsys):
    assert main(["fix"]) == 0, "fix should succeed"

    assert capsys.readouterr().out.startswith("Applied 1"), "the summary should count what was applied"
    assert (library / DEEP_WORK_HOME).exists(), "the misnamed epub should be renamed into its author folder"
    assert (tmp_path / "alfred-data" / "journal.jsonl").exists(), "the move should be journaled"
    assert "Newport, Cal/" in run(["search", "deep"], capsys)["items"][0]["subtitle"], "the index should know the new path"


@pytest.fixture
def junk(library: Path) -> Path:
    path = library / "00_Inbox" / "FSCK0000.000"
    path.write_bytes(b"")
    return path


def test_fix_with_a_path_applies_only_that_operation_without_a_full_rebuild(indexed, library, junk, capsys, mocker):
    rebuild = mocker.patch("kobolib.library.build_index")

    assert main(["fix", str(library / DEEP_WORK)]) == 0, "fixing one book should succeed"
    capsys.readouterr()

    rebuild.assert_not_called()
    assert (library / DEEP_WORK_HOME).exists() and junk.exists(), "only the named book's operation should run"
    assert run(["search", "deep"], capsys)["items"][0]["subtitle"].endswith(DEEP_WORK_HOME), "the index row should follow the move"


def test_fix_takes_paths_one_per_line(indexed, library, junk, capsys):
    assert main(["fix", f"{library / DEEP_WORK}\n{junk}"]) == 0, "the narrowed Fix all row passes its paths one per line"

    assert (library / DEEP_WORK_HOME).exists() and (library / "_trash" / "00_Inbox" / "FSCK0000.000").exists(), "both should be fixed"


def test_fix_with_words_applies_only_what_concerns_matching_books(indexed, library, junk, capsys):
    assert main(["fix", "newport"]) == 0, "fixing by words should succeed"

    assert (library / DEEP_WORK_HOME).exists() and junk.exists(), "only operations on books matching the words should run"


def test_fix_computes_operations_when_it_runs(indexed, library, junk, capsys):
    main(["genre", str(library / "00_Inbox" / "Napkin.pdf"), "reference"])
    capsys.readouterr()

    assert main(["fix", str(junk)]) == 0, "↩ on a row still works after the library changed"
    assert (library / "_trash" / "00_Inbox" / "FSCK0000.000").exists(), "the operation is recomputed from the current library"


def test_fix_summary_names_the_skip_reason(indexed, library, capsys):
    (library / DEEP_WORK).unlink()

    main(["fix", str(library / DEEP_WORK)])

    assert capsys.readouterr().out.startswith("Applied 0, skipped 1 (source missing)"), "the summary should say why it skipped"


def test_undo_reverses_the_last_fix(indexed, library, capsys):
    main(["fix"])
    capsys.readouterr()

    assert main(["undo"]) == 0, "undo should succeed"
    assert (library / DEEP_WORK).exists(), "the original name should be back"
    assert capsys.readouterr().out.startswith("Undid 1"), "undo should report what it reversed"


def test_fix_is_refused_without_an_index(env, capsys):
    assert main(["fix"]) == 1 and "No index yet" in capsys.readouterr().out, "fix needs a current index"


def test_trash_sets_an_unfinished_download_aside(indexed, library, tmp_path, capsys):
    assert main(["trash", str(library / NOVA)]) == 0, "trashing a download should succeed"

    assert capsys.readouterr().out.startswith("Moved 1 book to _trash/"), "the summary should count the books"
    assert (library / "_trash" / NOVA).exists() and not (library / NOVA).exists(), "the file should move to _trash/<original path>"
    assert [i["title"] for i in run(["search", "trash"], capsys)["items"]] == ["Nothing to trash"], "it should leave the index"
    assert (tmp_path / "alfred-data" / "journal.jsonl").exists(), "the move should be journaled"


def test_trash_takes_several_books_and_undo_brings_them_back(indexed, library, capsys):
    napkin = library / "00_Inbox" / "Napkin.pdf"

    assert main(["trash", f"{library / NOVA}\n{napkin}"]) == 0, "the Trash all row passes its paths one per line"
    assert capsys.readouterr().out.startswith("Moved 2 books to _trash/"), "both books should be counted"

    main(["undo"])
    assert napkin.exists() and (library / NOVA).exists(), "undo should bring both back"


def test_trash_reports_unknown_paths(indexed, library, capsys):
    unknown = library / "00_Inbox" / "Nope.epub"

    assert main(["trash", str(unknown)]) == 1, "nothing known to trash is a failure"
    assert capsys.readouterr().out == f"Not indexed: {unknown}\n", "the unknown path should be named exactly as given"


def test_genre_names_unknown_references_exactly(indexed, library, capsys):
    unknown = library / "00_Inbox" / "Nope.epub"

    assert main(["genre", str(unknown), "reference"]) == 1, "nothing known to classify is a failure"
    assert capsys.readouterr().out == f"Not indexed: {unknown}\n", "the unknown path should be named exactly as given"


@pytest.mark.parametrize("retired", ["dups", "random", "inbox", "classify", "sources", "stats"])
def test_one_purpose_subcommands_are_gone(env, retired):
    with pytest.raises(SystemExit):
        main([retired])


def oracle_store(tmp_path: Path):
    from kobolib.suggestions import SuggestionStore

    return SuggestionStore(tmp_path / "alfred-data" / "oracle.tsv").load()


def test_update_prunes_suggestions_for_books_that_left(indexed, library, tmp_path, capsys):
    napkin = run(["search", "napkin"], capsys)["items"][0]["variables"]["book"]
    store = oracle_store(tmp_path)
    store.set(napkin, "genre", {"genre": "none"}, "h")
    store.set("vanished", "genre", {"genre": "none"}, "h")
    store.save()

    main(["update"])

    store = oracle_store(tmp_path)
    assert store.get("vanished", "genre") is None and store.get(napkin, "genre") is not None, "only answers about absent books are pruned"


def test_trash_prunes_the_books_suggestions(indexed, library, tmp_path, capsys):
    napkin = run(["search", "napkin"], capsys)["items"][0]["variables"]["book"]
    store = oracle_store(tmp_path)
    store.set(napkin, "genre", {"genre": "reference"}, "h")
    store.save()

    main(["trash", str(library / "00_Inbox" / "Napkin.pdf")])

    assert oracle_store(tmp_path).get(napkin, "genre") is None, "a book set aside takes its suggestions with it"


def test_update_does_not_create_an_empty_oracle_store(indexed, tmp_path):
    assert not (tmp_path / "alfred-data" / "oracle.tsv").exists(), "nothing mentions the oracle until there is something to store"


@pytest.fixture
def oracle_env(indexed, monkeypatch):
    monkeypatch.setenv("KOBO_ORACLE_URL", "http://127.0.0.1:8080")


def test_ask_is_refused_without_a_model_server(indexed, monkeypatch, capsys):
    monkeypatch.delenv("KOBO_ORACLE_URL", raising=False)

    assert main(["ask", "genre"]) == 1, "nothing to ask without a server"
    assert "KOBO_ORACLE_URL" in capsys.readouterr().out, "the message should name the setting"


def test_ask_genre_stores_an_answer_per_inbox_book(oracle_env, tmp_path, capsys, mocker):
    ask = mocker.patch("kobolib.oracle.ask", side_effect=[{"genre": "nonfiction"}, {"genre": "none"}])

    assert main(["ask", "genre"]) == 0, "asking should succeed"

    assert capsys.readouterr().out.strip() == "Asked about 2 books: 1 genre suggested, 1 without an answer", "the summary counts answers"
    assert ask.call_count == 2, "one request per inbox book"
    answers = oracle_store(tmp_path).answers("genre")
    assert sorted(a["genre"] for a in answers.values()) == ["none", "nonfiction"], "both answers are kept, none included"
    assert ask.call_args_list[0].args[0] == "genre" and "Genres: nonfiction" in ask.call_args_list[0].args[1], (
        "the known genres are part of the evidence"
    )


def test_ask_twice_asks_nothing_the_second_time(oracle_env, capsys, mocker):
    ask = mocker.patch("kobolib.oracle.ask", return_value={"genre": "none"})
    main(["ask", "genre"])
    capsys.readouterr()

    main(["ask", "genre"])

    assert ask.call_count == 2, "answered books are not asked again"
    assert capsys.readouterr().out.strip() == "The model had no suggestions", "nothing new is said plainly"


def test_ask_force_asks_again(oracle_env, capsys, mocker):
    ask = mocker.patch("kobolib.oracle.ask", return_value={"genre": "none"})
    main(["ask", "genre"])

    main(["ask", "--force", "genre"])

    assert ask.call_count == 4, "--force re-asks every book"


def test_ask_counts_skipped_requests(oracle_env, capsys, mocker):
    mocker.patch("kobolib.oracle.ask", side_effect=[{"genre": "nonfiction"}, None])

    main(["ask", "genre"])

    assert capsys.readouterr().out.strip() == "Asked about 2 books: 1 genre suggested, 1 skipped", "a timeout is counted, not fatal"


def test_ask_dry_run_prints_the_evidence_and_writes_nothing(oracle_env, tmp_path, capsys, mocker):
    ask = mocker.patch("kobolib.oracle.ask")

    assert main(["ask", "--dry-run", "genre"]) == 0, "a dry run succeeds"

    out = capsys.readouterr().out
    assert out.count("Title: ") == 2 and "Genres: nonfiction" in out, "one block per book, exactly what the model would see"
    assert not ask.called and not (tmp_path / "alfred-data" / "oracle.tsv").exists(), "a dry run neither asks nor stores"


def test_ask_words_narrow_the_books(oracle_env, capsys, mocker):
    ask = mocker.patch("kobolib.oracle.ask", return_value={"genre": "none"})

    main(["ask", "genre", "napkin"])

    assert ask.call_count == 1 and "Title: Napkin" in ask.call_args.args[1], "only books matching the words are asked about"
