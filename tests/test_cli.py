import json
import os
from pathlib import Path

import pytest

from kobolib.cli import main, notify
from kobolib.index import IndexBusy


@pytest.fixture
def env(library: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KOBO_ROOT", str(library))
    monkeypatch.setenv("alfred_workflow_data", str(tmp_path / "alfred-data"))
    monkeypatch.delenv("KOBO_DATA", raising=False)
    monkeypatch.setenv("book", "x")


@pytest.fixture
def indexed(env, capsys):
    main(["index"])
    capsys.readouterr()


def output(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def run(argv: list[str], capsys) -> dict:
    main(argv)
    return output(capsys)


def test_search_before_index_explains(env, capsys):
    assert run(["search", "deep"], capsys)["items"][0]["title"] == "No index yet", "search without index should tell how to build it"


def test_index_then_search(env, capsys):
    assert main(["index"]) == 0, "index should succeed on a mounted library"
    capsys.readouterr()

    items = run(["search", "deep"], capsys)["items"]
    assert [i["title"] for i in items] == ["Deep Work"], "search should hit the indexed epub"
    assert items[0]["subtitle"].endswith("02_NonFiction/Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"), (
        "subtitle should end with the library-relative path"
    )


def test_index_fails_when_root_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("KOBO_ROOT", str(tmp_path / "missing"))
    monkeypatch.setenv("alfred_workflow_data", str(tmp_path / "c"))
    assert main(["index"]) == 1, "index should fail when the volume is not mounted"


@pytest.mark.parametrize("command", ["dups", "stats", "random"])
def test_other_commands_emit_alfred_json(indexed, capsys, command):
    assert "items" in run([command], capsys), f"{command} should emit Alfred items"


def test_kobo_data_overrides_alfred_data_dir(env, tmp_path, monkeypatch):
    monkeypatch.setenv("KOBO_DATA", str(tmp_path / "custom"))
    main(["index"])
    assert (tmp_path / "custom" / "library.db").exists(), "KOBO_DATA should decide where the index lives"


def test_index_reports_inaccessible_root(env, library, capsys, mocker):
    mocker.patch("kobolib.library.build_index", return_value=0)
    mocker.patch("kobolib.library.probe_root", return_value="permission denied reading root")

    assert main(["index"]) == 1, "index should fail when no books were found"
    assert "permission denied" in capsys.readouterr().out, "the failure message should explain why"


def test_index_notify_posts_notification(env, capsys, mocker):
    run = mocker.patch("kobolib.cli.subprocess.run")

    main(["index", "--notify"])

    scripts = [c.args[0][-1] for c in run.call_args_list if c.args[0][0] == "osascript"]
    assert "Indexed 4 books" in scripts[0], "first notification should carry the index summary"
    assert "PDF covers" in scripts[1], "second notification should report the thumbnail pass"


def test_index_busy_is_reported(env, capsys, mocker):
    mocker.patch("kobolib.library.build_index", side_effect=IndexBusy("busy"))

    assert main(["index"]) == 1, "busy index should exit non-zero"
    assert "already running" in capsys.readouterr().out, "busy index should be explained"


def test_no_thumbnails_flag_skips_second_pass(env, capsys, mocker):
    fill = mocker.patch("kobolib.cli.fill_thumbnails")
    main(["index", "--no-thumbnails"])
    fill.assert_not_called()


def test_index_bootstraps_tags_from_folders(indexed, tmp_path, capsys):

    titles = [i["title"] for i in run(["inbox"], capsys)["items"]]
    assert "Deep Work" not in titles, "a book in a genre folder should be classified by index"
    assert "Napkin" in titles, "an inbox book should wait for classification"


def test_lint_emits_findings_as_items(indexed, capsys):

    rules = {i["subtitle"].split(" · ")[0] for i in run(["lint"], capsys)["items"]}
    assert {"partial", "unclassified"} <= rules, "lint should report the partial download and unclassified inbox books"


def test_lint_text_report_for_terminal(indexed, capsys):

    main(["lint", "--text"])

    out = capsys.readouterr().out
    assert "partial\t" in out and "00_Inbox/Delany, Samuel R - Nova - 2014.epub.part" in out, (
        "text report should list rule and path per line"
    )


def test_lint_without_index_explains(env, capsys):
    assert run(["lint"], capsys)["items"][0]["title"] == "No index yet", "lint without index should tell how to build it"


def test_plan_writes_file_and_emits_items(indexed, tmp_path, capsys):

    items = run(["plan"], capsys)["items"]
    plan_file = tmp_path / "alfred-data" / "plan.tsv"
    assert plan_file.exists(), "plan should be written next to the index"
    assert any(i["subtitle"].startswith("move") for i in items), "the misnamed epub in a genre folder should be planned for renaming"
    assert plan_file.read_text(encoding="utf-8").count("\n") == len(items), (
        "every operation should be in the file (header line stands in for the head row)"
    )


def test_plan_text_prints_tsv(indexed, capsys):

    main(["plan", "--text"])

    assert capsys.readouterr().out.startswith("kind\tsrc\tdst\treason\n"), "text plan should be the TSV itself"


def test_apply_runs_plan_and_reindexes(indexed, library, tmp_path, capsys):
    main(["plan"])
    capsys.readouterr()

    assert main(["apply"]) == 0, "apply should succeed"

    out = capsys.readouterr().out
    assert out.startswith("Applied 1"), "the misnamed epub should be moved"
    assert (library / "02_NonFiction" / "Newport, Cal" / "Newport, Cal - Deep Work (Focus 02) (2016).epub").exists(), (
        "the book should be renamed into its author folder"
    )
    assert (tmp_path / "alfred-data" / "journal.jsonl").exists(), "the move should be journaled"
    assert "Newport, Cal/" in run(["search", "deep"], capsys)["items"][0]["subtitle"], "the index should be rebuilt after applying"


def test_apply_refuses_stale_plan(indexed, tmp_path, capsys):
    main(["plan"])
    os.utime(tmp_path / "alfred-data" / "plan.tsv", (0, 0))
    capsys.readouterr()

    assert main(["apply"]) == 1, "a plan older than the index must not be applied"
    assert "stale" in capsys.readouterr().out, "the reason should be printed"


def test_apply_only_one_path(indexed, library, capsys):
    book = library / "02_NonFiction" / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"

    assert main(["apply", "--only", str(book)]) == 0, "a single book can be applied without a plan file"
    assert not book.exists(), "the book should have moved"


def test_undo_restores_and_reindexes(indexed, library, capsys):
    main(["plan"])
    main(["apply"])
    capsys.readouterr()

    assert main(["undo"]) == 0, "undo should succeed"
    assert (library / "02_NonFiction" / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub").exists(), "the original name should be back"
    assert capsys.readouterr().out.startswith("Undid 1"), "undo should report what it reversed"


def test_apply_without_plan_explains(indexed, capsys):
    assert main(["apply"]) == 1 and "kb:plan" in capsys.readouterr().out, "apply without a plan should point at kb:plan"


def test_tag_command_sets_genre_by_path(indexed, library, capsys):
    book = str(library / "00_Inbox" / "Napkin.pdf")

    assert main(["tag", book, "genre=reference"]) == 0, "setting a genre by path should succeed"
    assert capsys.readouterr().out.startswith("Napkin → reference"), "the result should be reported"
    assert [i["title"] for i in run(["search", "genre:reference"], capsys)["items"]] == ["Napkin"], "the genre should be searchable"
    assert "Napkin" not in [i["title"] for i in run(["inbox"], capsys)["items"]], "a classified book leaves the inbox"


def test_tag_command_accepts_a_fingerprint(indexed, capsys):
    fingerprint = run(["search", "napkin"], capsys)["items"][0]["variables"]["book"]

    assert main(["tag", fingerprint, "genre=reference"]) == 0, "a fingerprint from the picker should identify the book"
    assert capsys.readouterr().out.startswith("Napkin → reference"), "the result should be reported"


def test_index_writes_the_genre_store(indexed, tmp_path):
    assert (tmp_path / "alfred-data" / "genres.tsv").exists(), "indexing should save genres to genres.tsv"
    assert not (tmp_path / "alfred-data" / "tags.tsv").exists(), "no tags.tsv should be written any more"


def test_genres_lists_known_genres_filtered(indexed, library, capsys):
    main(["tag", str(library / "00_Inbox" / "Napkin.pdf"), "genre=games/go"])
    capsys.readouterr()

    items = run(["genres", "g"], capsys)["items"]
    assert [i["arg"] for i in items] == ["genre=games/go", "genre=g"], "matching genres are offered as edits, the fragment itself last"
    assert [i["arg"] for i in run(["genres", ""], capsys)["items"]] == ["genre=games/go", "genre=nonfiction"], (
        "all genres from tags and folders should be listed"
    )


def test_genres_offers_new_genre_from_query(indexed, library, capsys):

    items = run(["genres", "fiction/mystery"], capsys)["items"]
    assert items[-1]["arg"] == "genre=fiction/mystery" and items[-1]["title"].startswith("New genre"), (
        "an unknown genre can be created from the query"
    )


def test_classify_lists_unclassified_with_book_variable(indexed, library, capsys):

    items = run(["classify", "napkin"], capsys)["items"]
    assert [i["title"] for i in items] == ["Napkin"], "classify should filter the inbox by the query"
    assert items[0]["arg"] == "" and len(items[0]["variables"]["book"]) == 40, "the book travels as a variable, the query starts empty"


def test_genres_forwards_the_book_variable(indexed, library, capsys, monkeypatch):
    monkeypatch.setenv("book", "abc123")

    out = run(["genres", "non"], capsys)
    assert out["items"][0]["variables"] == {"book": "abc123"}, "each genre item must carry the book on to the tag step"


@pytest.mark.parametrize("book", ["one", "one\ntwo"])
def test_genres_before_any_index_explains(env, capsys, monkeypatch, book):
    monkeypatch.setenv("book", book)

    assert run(["genres", ""], capsys)["items"][0]["title"] == "No index yet", "the genre picker without an index should explain"


def test_genres_without_book_explains(indexed, library, capsys, monkeypatch):
    monkeypatch.delenv("book", raising=False)

    assert run(["genres", ""], capsys)["items"][0]["valid"] is False, "without a selected book the picker must not be actionable"


def test_search_items_offer_fix_on_shift(indexed, capsys):

    item = run(["search", "deep"], capsys)["items"][0]
    assert item["mods"]["shift"]["arg"] == "", "shift+↩ should open the fix picker with an empty query"
    assert "genre" in item["mods"]["shift"]["subtitle"].lower(), "the shift subtitle should say it fixes genre/tags"
    assert item["variables"]["book"] == item["mods"]["shift"]["variables"]["book"], "the fingerprint must travel with the shift action"


def test_fix_lists_genres_under_the_book(indexed, library, capsys, monkeypatch):
    main(["tag", str(library / "00_Inbox" / "Napkin.pdf"), "genre=games/go"])
    capsys.readouterr()
    main(["search", "napkin"])
    monkeypatch.setenv("book", output(capsys)["items"][0]["variables"]["book"])

    items = run(["fix", ""], capsys)["items"]
    assert items[0]["title"].startswith("Napkin") and items[0]["valid"] is False, "the first item should show the book being fixed"
    assert items[0]["subtitle"] == "games/go · 00_Inbox/Napkin.pdf", "the header should show the current genre and path"
    assert not [i for i in items if i.get("arg", "").startswith(("+", "-"))], "tags can no longer be added or removed"
    assert "genre=nonfiction" in [i.get("arg") for i in items], "known genres should be offered"


@pytest.mark.parametrize(
    "query, arg, title_start",
    [
        ("fiction/mystery", "genre=fiction/mystery", "New genre"),
        ("non", "genre=nonfiction", "nonfiction"),
    ],
)
def test_fix_turns_query_into_an_edit(indexed, library, capsys, monkeypatch, query, arg, title_start):
    main(["search", "napkin"])
    monkeypatch.setenv("book", output(capsys)["items"][0]["variables"]["book"])

    edits = [i for i in run(["fix", "--", query], capsys)["items"] if i.get("valid", True)]
    assert edits[0]["arg"] == arg, f"query {query!r} should offer the edit {arg!r}"
    assert edits[0]["title"].startswith(title_start), f"the offered edit should be labelled {title_start!r}"


@pytest.fixture
def spy_book(indexed, library, capsys, monkeypatch):
    main(["tag", str(library / "00_Inbox" / "Napkin.pdf"), "genre=fiction/spy"])
    capsys.readouterr()
    monkeypatch.setenv("book", run(["search", "napkin"], capsys)["items"][0]["variables"]["book"])


def offered(items: list[dict], prefix: str) -> list[str]:
    return [i["arg"] for i in items if i.get("arg", "").startswith(prefix) and not i["title"].startswith("New genre")]


@pytest.mark.parametrize("query", ["spy", "SPY", "fiction/", "tion/sp"])
def test_fix_matches_a_genre_anywhere_in_its_path(spy_book, capsys, query):
    items = run(["fix", query], capsys)["items"]
    assert offered(items, "genre=") == ["genre=fiction/spy"], f"{query!r} should match the genre anywhere in its path, case-insensitively"
    assert items[1]["autocomplete"] == "fiction/spy", "⇥ on a genre row completes to the genre itself, not to the edit"


def test_fix_offers_a_partial_match_as_a_new_genre_too(spy_book, capsys):
    last = run(["fix", "spy"], capsys)["items"][-1]
    assert last["arg"] == "genre=spy" and last["title"].startswith("New genre"), (
        "a fragment that is not itself a genre can still become one"
    )


def test_fix_does_not_offer_an_existing_genre_as_new(spy_book, capsys):
    titles = [i["title"] for i in run(["fix", "fiction/spy"], capsys)["items"]]
    assert not any(t.startswith("New genre") for t in titles), "an exact existing genre is not offered again as new"


def test_genres_picker_matches_like_fix(spy_book, capsys):
    args = [i["arg"] for i in run(["genres", "SP"], capsys)["items"]]
    assert args == ["genre=fiction/spy", "genre=sp"], "kb:classify's genre step uses the same matching as the fix picker"


def test_fix_without_book_explains(indexed, capsys, monkeypatch):
    monkeypatch.delenv("book", raising=False)

    assert run(["fix", ""], capsys)["items"][0]["valid"] is False, "without a selected book the fix picker must not be actionable"


def test_plan_list_starts_with_apply_all(indexed, capsys):

    items = run(["plan"], capsys)["items"]
    assert items[0]["title"] == "Apply all 1 operations" and items[0]["arg"] == "", "↩ on the head row should apply the whole plan"
    assert all(i["subtitle"].startswith(("move", "trash", "dups", "skip")) for i in items[1:]), "the operations follow the head row"


def test_apply_with_empty_only_applies_the_whole_plan(indexed, capsys):
    main(["plan"])
    capsys.readouterr()

    assert main(["apply", "--only", ""]) == 0, "an empty --only (the plan list's head row) means the whole plan"
    assert capsys.readouterr().out.startswith("Applied 1"), "the plan should have been applied"


def test_apply_summary_names_the_skip_reason(indexed, library, tmp_path, capsys):
    main(["plan"])
    (library / "02_NonFiction" / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub").unlink()
    capsys.readouterr()

    main(["apply"])

    assert capsys.readouterr().out.startswith("Applied 0, skipped 1 (source missing)"), "the summary should say why operations were skipped"


def test_tag_with_genre_moves_the_book_to_its_genre_home(indexed, library, capsys):
    book = library / "02_NonFiction" / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"

    assert main(["tag", str(book), "genre=productivity"]) == 0, "tagging with a genre should succeed"
    out = capsys.readouterr().out

    assert not book.exists(), "the book should leave its old folder as soon as the genre is set"
    moved = list(library.rglob("*.epub"))
    assert len(moved) == 1 and moved[0].parts[-3:-1] == ("productivity", "Newport, Cal"), "the book should land in genre/author"
    assert "Deep Work → productivity" in out and "→ productivity/Newport, Cal/" in out, "the report should name the new home"
    assert run(["search", "deep"], capsys)["items"][0]["subtitle"].count("productivity") >= 1, "the index should already know the new path"


def test_single_book_moves_update_the_index_in_place(indexed, library, capsys, mocker):
    rebuild = mocker.patch("kobolib.library.build_index")
    book = library / "02_NonFiction" / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"

    main(["tag", str(book), "genre=productivity"])
    capsys.readouterr()

    rebuild.assert_not_called()
    items = run(["search", "deep"], capsys)["items"]
    assert items[0]["subtitle"].endswith("productivity/Newport, Cal/Newport, Cal - Deep Work (Focus 02) (2016).epub"), (
        "one moved book should not re-read every other book; the row itself is relocated"
    )
    assert "No books match" in run(["search", "in:nonfiction"], capsys)["items"][0]["title"], "the old path should be gone from the index"


def test_apply_only_moves_one_book_without_a_full_rebuild(indexed, library, capsys, mocker):
    rebuild = mocker.patch("kobolib.library.build_index")
    book = library / "02_NonFiction" / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"

    assert main(["apply", "--only", str(book)]) == 0, "a single book can be moved home without a plan file"
    capsys.readouterr()

    rebuild.assert_not_called()
    assert run(["search", "deep"], capsys)["items"][0]["subtitle"].count("Newport, Cal/") == 1, "the index should know the new path"


def test_single_book_move_updates_the_genre_store_path(indexed, library, tmp_path, capsys):
    import csv

    main(["tag", str(library / "02_NonFiction" / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"), "genre=productivity"])

    with (tmp_path / "alfred-data" / "genres.tsv").open(newline="", encoding="utf-8") as handle:
        paths = {r["rel_path"] for r in csv.DictReader(handle, delimiter="\t")}
    assert "productivity/Newport, Cal/Newport, Cal - Deep Work (Focus 02) (2016).epub" in paths, (
        "genres.tsv should name the book's new path right away"
    )


def test_apply_only_runs_a_plan_row_even_when_the_plan_went_stale(indexed, library, capsys):
    (library / "00_Inbox" / "FSCK0000.000").write_bytes(b"")
    main(["plan"])
    main(["tag", str(library / "00_Inbox" / "Napkin.pdf"), "genre=reference"])
    capsys.readouterr()

    assert main(["apply", "--only", str(library / "00_Inbox" / "FSCK0000.000")]) == 0, "↩ on a row still works after the index changed"
    assert (library / "_trash" / "00_Inbox" / "FSCK0000.000").exists(), "the row's own operation runs, recomputed from the current library"


def test_apply_only_follows_a_fresh_plan_row(indexed, library, capsys):
    (library / "00_Inbox" / "FSCK0000.000").write_bytes(b"")
    main(["plan"])
    capsys.readouterr()

    assert main(["apply", "--only", str(library / "00_Inbox" / "FSCK0000.000")]) == 0, "↩ on a plan row applies that row"
    assert (library / "_trash" / "00_Inbox" / "FSCK0000.000").exists(), "the trash row from the plan is what runs, not a genre move"


def test_tag_with_genre_reports_when_there_is_no_home_yet(indexed, library, capsys):
    book = library / "00_Inbox" / "Napkin.pdf"

    assert main(["tag", str(book), "genre=reference"]) == 0, "a book without an author can still be tagged"

    assert book.exists(), "a book whose home cannot be derived stays put"
    assert "stays put" in capsys.readouterr().out, "the report should say the book was not moved"


def test_tag_with_genre_accepts_notify_like_the_other_movers(indexed, library, mocker):
    notify = mocker.patch("kobolib.cli.notify")
    book = library / "02_NonFiction" / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"

    assert main(["tag", "--notify", str(book), "genre=productivity"]) == 0, "--notify should be accepted before the book"

    assert notify.call_count == 1 and "moved → productivity/" in notify.call_args.args[0], "the notification should name the new home"


@pytest.mark.parametrize(
    "query, first_title, action",
    [
        ("stats", "4 books indexed", "stats"),
        ("dups", "No duplicate titles", "dups"),
        ("plan", "Apply all 1 operations", "apply-one"),
        ("inbox", "", "open"),
        ("classify", "", "classify"),
        ("lint", "", "open"),
        ("index", "Rebuild the index", "index"),
        ("update", "Rebuild the index", "index"),
        ("apply", "Apply the plan", "apply"),
        ("undo", "Undo the last apply", "undo"),
        ("src", "No sources index yet", "import"),
    ],
)
def test_search_runs_a_command_named_by_its_first_word(indexed, capsys, query, first_title, action):

    first = run(["search", query], capsys)["items"][0]
    assert first["title"].startswith(first_title), f"kb {query} should show the same items as kb:{query}"
    assert first.get("variables", {}).get("action") == action, "every command item should say how ↩ dispatches it"


def test_search_command_items_come_before_matching_books(env, library, capsys):
    (library / "00_Inbox" / "Stats for Dummies - Anon.pdf").write_bytes(b"%PDF-1.4")
    main(["index"])
    capsys.readouterr()

    titles = [i["title"] for i in run(["search", "stats"], capsys)["items"]]
    assert titles[0] == "5 books indexed", "the command comes first"
    assert "Stats for Dummies" in titles, "books that happen to match the word still follow"


def test_search_command_takes_the_rest_as_its_query(indexed, capsys):

    items = run(["search", "rnd fmt:epub"], capsys)["items"]
    assert [i["title"] for i in items] == ["Deep Work"], "kb rnd <query> should filter like kb:rnd <query>"
    assert items[0]["variables"]["action"] == "open", "a book item from a picker opens like any other book"


def test_search_action_item_is_actionable_and_has_no_arg(indexed, capsys):

    item = run(["search", "index"], capsys)["items"][0]
    assert item["valid"] is True and item["arg"] == "", "↩ on a keyword command should fire it with an empty argument"


def test_search_plain_word_is_still_a_search(indexed, capsys):

    assert run(["search", "deep"], capsys)["items"][0]["title"] == "Deep Work", "an ordinary word must not be mistaken for a command"


@pytest.mark.parametrize("query, title", [("index", "Rebuild the index"), ("update", "Rebuild the index"), ("src", "No sources index yet")])
def test_search_offers_index_free_commands_before_any_index(env, capsys, query, title):
    first = run(["search", query], capsys)["items"][0]
    assert first["title"] == title, f"kb {query} should work before the first index exists"
    assert first.get("variables", {}).get("action"), "the command must still carry its dispatch action"


@pytest.mark.parametrize("query", ["stats", "dups", "plan", "inbox", "classify", "lint", "rnd"])
def test_search_explains_index_bound_commands_before_any_index(env, capsys, query):
    first = run(["search", query], capsys)["items"][0]
    assert first["title"] == "No index yet" and first["valid"] is False, f"kb {query} without an index should point at kb:index, not crash"


@pytest.mark.parametrize(
    "query, suggested",
    [
        ("ind", ["index"]),
        ("IN", ["inbox", "index"]),
        ("cl", ["classify"]),
        ("so", ["sources"]),
        ("ap", ["apply"]),
        ("ra", ["random"]),
        ("sr", ["src"]),
    ],
)
def test_search_suggests_commands_matching_a_typed_prefix(indexed, capsys, query, suggested):
    items = run(["search", query], capsys)["items"]

    hints = [i for i in items if i.get("autocomplete", "").rstrip() in suggested]
    assert [h["autocomplete"] for h in hints] == [f"{s} " for s in suggested], f"kb {query} should offer to complete to kb {suggested}"
    assert all(h["valid"] is False and h["title"] == f"kb {h['autocomplete'].strip()}" for h in hints), (
        "a suggestion completes the word on ↩/⇥ rather than acting"
    )
    assert items[: len(hints)] == hints, "suggestions come before any books matching the letters"


def test_search_suggestions_follow_the_prefix_into_the_books(indexed, library, capsys):
    (library / "00_Inbox" / "Index Cards - Smith, John.pdf").write_bytes(b"%PDF-1.4")
    main(["index"])
    capsys.readouterr()

    titles = [i["title"] for i in run(["search", "ind"], capsys)["items"]]
    assert titles == ["kb index", "Index Cards"], "the completion hint sits above the books that match the letters"


@pytest.mark.parametrize("query", ["i", "ind deep", "index", "zzz"])
def test_search_does_not_suggest_commands_for_other_input(indexed, capsys, query):
    items = run(["search", query], capsys)["items"]
    assert not any(i.get("autocomplete", "").endswith(" ") and i.get("valid") is False for i in items), (
        "a single letter, a prefix followed by more words, a complete command or a non-prefix should not produce completion hints"
    )


def test_search_suggests_commands_before_any_index(env, capsys):
    items = run(["search", "ind"], capsys)["items"]
    assert items[0]["autocomplete"] == "index ", "completing to kb index must work before the first index exists"


def test_notify_passes_the_message_as_an_argument(mocker):
    run = mocker.patch("kobolib.cli.subprocess.run")
    message = 'Deep "Work" → C:\\Users'

    notify(message)

    argv = run.call_args.args[0]
    assert argv[-1] == message, "the message must reach osascript verbatim, never spliced into the script"
    assert not any(message in a for a in argv[:-1]), "the message must not be interpolated into the AppleScript source"


def fingerprints_of(items: list[dict]) -> list[str]:
    return [i["variables"]["book"] for i in items if "mods" in i and i.get("valid", True)]


def test_classify_rows_offer_the_whole_list_on_alt_shift(indexed, capsys):
    items = run(["classify", ""], capsys)["items"]
    everyone = "\n".join(fingerprints_of(items))

    for item in (i for i in items if "mods" in i and i.get("valid", True)):
        batch = item["mods"]["alt+shift"]
        assert batch["arg"] == "" and batch["variables"]["book"] == everyone, "⌥⇧↩ opens the genre picker for every listed book"
        assert batch["subtitle"] == f"Classify all {len(fingerprints_of(items))} shown", "the subtitle should count the books"
    assert len(fingerprints_of(items)) == 2, "partial downloads are listed but not part of the batch"


def test_inbox_rows_offer_classifying_the_whole_list(indexed, capsys):
    items = run(["inbox", ""], capsys)["items"]

    batch = next(i for i in items if i.get("valid", True))["mods"]["alt+shift"]
    assert batch["variables"]["action"] == "classify", "from kb inbox the batch must be routed to the genre picker"
    assert batch["variables"]["book"].count("\n") == 1, "both complete inbox books travel together"


def test_tag_classifies_many_books_at_once(indexed, library, capsys):
    books = "\n".join(fingerprints_of(run(["inbox", ""], capsys)["items"]))

    assert main(["tag", books, "genre=reference"]) == 0, "tagging several books should succeed"

    assert capsys.readouterr().out.startswith("2 books → reference"), "the summary should count the books"
    assert fingerprints_of(run(["inbox", ""], capsys)["items"]) == [], "both books leave the inbox; only the partial download stays"
    assert len(run(["search", "genre:reference"], capsys)["items"]) == 2, "both books carry the genre"


def test_tag_skips_unknown_references_in_a_batch(indexed, library, capsys):
    known = fingerprints_of(run(["inbox", ""], capsys)["items"])[0]

    assert main(["tag", f"{known}\nnope", "genre=reference"]) == 0, "one unknown reference does not fail the batch"
    assert "skipped 1" in capsys.readouterr().out, "the unknown reference should be mentioned"


def test_genres_for_many_books_says_so(indexed, capsys, monkeypatch):
    monkeypatch.setenv("book", "aaa\nbbb")

    items = run(["genres", ""], capsys)["items"]

    assert items[0]["title"] == "Genre for 2 books" and items[0]["valid"] is False, "a header should say the pick applies to all"
    assert items[1]["variables"] == {"book": "aaa\nbbb"}, "every genre item carries all the books on"


def test_plan_rows_offer_apply_all_on_alt_shift(indexed, capsys):
    items = run(["plan"], capsys)["items"]
    rows = [i for i in items if i["uid"] != "plan:apply-all"]

    assert rows, "the fixture library should have something to plan"
    for row in rows:
        assert row["mods"]["alt+shift"]["arg"] == "" and row["mods"]["alt+shift"]["subtitle"].startswith("Apply all"), (
            "⌥⇧↩ on a plan row applies the whole plan, like the head row"
        )


def test_classify_list_starts_with_classify_all(indexed, capsys):
    items = run(["classify", ""], capsys)["items"]

    head = items[0]
    assert head["title"] == "Classify all 2 books" and head["arg"] == "", "the first row opens the genre picker for every complete book"
    assert head["variables"]["book"] == "\n".join(fingerprints_of(items[1:])), "the batch is the listed complete books"
    assert run(["classify", "napkin"], capsys)["items"][0]["title"] == "Napkin", "one book needs no 'classify all' row"
