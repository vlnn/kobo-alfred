import json
from pathlib import Path

import pytest

from kobolib.cli import main


@pytest.fixture
def env(library: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KOBO_ROOT", str(library))
    monkeypatch.setenv("alfred_workflow_data", str(tmp_path / "alfred-data"))
    monkeypatch.delenv("KOBO_DATA", raising=False)
    monkeypatch.setenv("book", "x")


def output(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_search_before_index_explains(env, capsys):
    main(["search", "deep"])
    assert output(capsys)["items"][0]["title"] == "No index yet", "search without index should tell how to build it"


def test_index_then_search(env, capsys):
    assert main(["index"]) == 0, "index should succeed on a mounted library"
    capsys.readouterr()

    main(["search", "deep"])

    items = output(capsys)["items"]
    assert [i["title"] for i in items] == ["Deep Work"], "search should hit the indexed epub"
    assert items[0]["subtitle"].endswith("02_NonFiction/Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"), (
        "subtitle should end with the library-relative path"
    )


def test_index_fails_when_root_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("KOBO_ROOT", str(tmp_path / "missing"))
    monkeypatch.setenv("alfred_workflow_data", str(tmp_path / "c"))
    assert main(["index"]) == 1, "index should fail when the volume is not mounted"


@pytest.mark.parametrize("command", ["dups", "stats", "random"])
def test_other_commands_emit_alfred_json(env, capsys, command):
    main(["index"])
    capsys.readouterr()
    main([command])
    assert "items" in output(capsys), f"{command} should emit Alfred items"


def test_kobo_data_overrides_alfred_data_dir(env, tmp_path, monkeypatch):
    monkeypatch.setenv("KOBO_DATA", str(tmp_path / "custom"))
    main(["index"])
    assert (tmp_path / "custom" / "library.db").exists(), "KOBO_DATA should decide where the index lives"


def test_index_reports_inaccessible_root(env, library, capsys, mocker):
    mocker.patch("kobolib.cli.build_index", return_value=0)
    mocker.patch("kobolib.cli.probe_root", return_value="permission denied reading root")

    assert main(["index"]) == 1, "index should fail when no books were found"
    assert "permission denied" in capsys.readouterr().out, "the failure message should explain why"


def test_index_notify_posts_notification(env, capsys, mocker):
    run = mocker.patch("kobolib.cli.subprocess.run")

    main(["index", "--notify"])

    scripts = [c.args[0][-1] for c in run.call_args_list if c.args[0][0] == "osascript"]
    assert "Indexed 4 books" in scripts[0], "first notification should carry the index summary"
    assert "PDF covers" in scripts[1], "second notification should report the thumbnail pass"


def test_index_busy_is_reported(env, capsys, mocker):
    from kobolib.index import IndexBusy

    mocker.patch("kobolib.cli.build_index", side_effect=IndexBusy("busy"))

    assert main(["index"]) == 1, "busy index should exit non-zero"
    assert "already running" in capsys.readouterr().out, "busy index should be explained"


def test_no_thumbnails_flag_skips_second_pass(env, capsys, mocker):
    fill = mocker.patch("kobolib.cli.fill_thumbnails")
    main(["index", "--no-thumbnails"])
    fill.assert_not_called()


def test_index_bootstraps_tags_from_folders(env, tmp_path, capsys):
    main(["index"])
    capsys.readouterr()

    main(["inbox"])

    titles = [i["title"] for i in output(capsys)["items"]]
    assert "Deep Work" not in titles, "a book in a genre folder should be classified by index"
    assert "Napkin" in titles, "an inbox book should wait for classification"


def test_lint_emits_findings_as_items(env, capsys):
    main(["index"])
    capsys.readouterr()

    main(["lint"])

    rules = {i["subtitle"].split(" · ")[0] for i in output(capsys)["items"]}
    assert {"partial", "unclassified"} <= rules, "lint should report the partial download and unclassified inbox books"


def test_lint_text_report_for_terminal(env, capsys):
    main(["index"])
    capsys.readouterr()

    main(["lint", "--text"])

    out = capsys.readouterr().out
    assert "partial\t" in out and "00_Inbox/Delany, Samuel R - Nova - 2014.epub.part" in out, (
        "text report should list rule and path per line"
    )


def test_lint_without_index_explains(env, capsys):
    main(["lint"])
    assert output(capsys)["items"][0]["title"] == "No index yet", "lint without index should tell how to build it"


def test_plan_writes_file_and_emits_items(env, tmp_path, capsys):
    main(["index"])
    capsys.readouterr()

    main(["plan"])

    items = output(capsys)["items"]
    plan_file = tmp_path / "alfred-data" / "plan.tsv"
    assert plan_file.exists(), "plan should be written next to the index"
    assert any(i["subtitle"].startswith("move") for i in items), "the misnamed epub in a genre folder should be planned for renaming"
    assert plan_file.read_text(encoding="utf-8").count("\n") == len(items), (
        "every operation should be in the file (header line stands in for the head row)"
    )


def test_plan_text_prints_tsv(env, capsys):
    main(["index"])
    capsys.readouterr()

    main(["plan", "--text"])

    assert capsys.readouterr().out.startswith("kind\tsrc\tdst\treason\n"), "text plan should be the TSV itself"


def test_apply_runs_plan_and_reindexes(env, library, tmp_path, capsys):
    main(["index"])
    main(["plan"])
    capsys.readouterr()

    assert main(["apply"]) == 0, "apply should succeed"

    out = capsys.readouterr().out
    assert out.startswith("Applied 1"), "the misnamed epub should be moved"
    assert (library / "02_NonFiction" / "Newport, Cal" / "Newport, Cal - Deep Work (Focus 02) (2016).epub").exists(), (
        "the book should be renamed into its author folder"
    )
    assert (tmp_path / "alfred-data" / "journal.jsonl").exists(), "the move should be journaled"
    main(["search", "deep"])
    assert "Newport, Cal/" in output(capsys)["items"][0]["subtitle"], "the index should be rebuilt after applying"


def test_apply_refuses_stale_plan(env, library, capsys):
    main(["index"])
    main(["plan"])
    import time

    time.sleep(0.02)
    main(["index"])
    capsys.readouterr()

    assert main(["apply"]) == 1, "a plan older than the index must not be applied"
    assert "stale" in capsys.readouterr().out, "the reason should be printed"


def test_apply_only_one_path(env, library, capsys):
    main(["index"])
    capsys.readouterr()
    book = library / "02_NonFiction" / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"

    assert main(["apply", "--only", str(book)]) == 0, "a single book can be applied without a plan file"
    assert not book.exists(), "the book should have moved"


def test_undo_restores_and_reindexes(env, library, capsys):
    main(["index"])
    main(["plan"])
    main(["apply"])
    capsys.readouterr()

    assert main(["undo"]) == 0, "undo should succeed"
    assert (library / "02_NonFiction" / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub").exists(), "the original name should be back"
    assert capsys.readouterr().out.startswith("Undid 1"), "undo should report what it reversed"


def test_apply_without_plan_explains(env, capsys):
    main(["index"])
    capsys.readouterr()
    assert main(["apply"]) == 1 and "kb:plan" in capsys.readouterr().out, "apply without a plan should point at kb:plan"


def test_tag_command_sets_genre_and_tags_by_path(env, library, capsys):
    main(["index"])
    capsys.readouterr()
    book = str(library / "00_Inbox" / "Napkin.pdf")

    assert main(["tag", book, "genre=reference", "+bought", "+now"]) == 0, "tagging by path should succeed"
    assert capsys.readouterr().out.startswith("Napkin → reference"), "the result should be reported"
    main(["search", "genre:reference tag:bought"])
    assert [i["title"] for i in output(capsys)["items"]] == ["Napkin"], "genre and tags should be searchable at once"
    main(["inbox"])
    assert "Napkin" not in [i["title"] for i in output(capsys)["items"]], "a classified book leaves the inbox"


def test_tag_command_removes_tags_and_accepts_fingerprint(env, library, capsys):
    main(["index"])
    capsys.readouterr()
    book = str(library / "00_Inbox" / "Napkin.pdf")
    main(["tag", book, "+now"])
    capsys.readouterr()
    main(["search", "tag:now"])
    fingerprint = output(capsys)["items"][0]["variables"]["book"]

    main(["tag", fingerprint, "-now"])
    capsys.readouterr()
    main(["search", "tag:now"])

    assert output(capsys)["items"][0]["title"] == "No books match “tag:now”", "a removed tag should not match"


def test_genres_lists_known_genres_filtered(env, library, capsys):
    main(["index"])
    main(["tag", str(library / "00_Inbox" / "Napkin.pdf"), "genre=games/go"])
    capsys.readouterr()

    main(["genres", "g"])

    items = output(capsys)["items"]
    assert [i["arg"] for i in items] == ["genre=games/go"], "genres should be filtered by the typed prefix and offered as edits"
    main(["genres", ""])
    assert [i["arg"] for i in output(capsys)["items"]] == ["genre=games/go", "genre=nonfiction"], (
        "all genres from tags and folders should be listed"
    )


def test_genres_offers_new_genre_from_query(env, library, capsys):
    main(["index"])
    capsys.readouterr()

    main(["genres", "fiction/mystery"])

    items = output(capsys)["items"]
    assert items[-1]["arg"] == "genre=fiction/mystery" and items[-1]["title"].startswith("New genre"), (
        "an unknown genre can be created from the query"
    )


def test_classify_lists_unclassified_with_book_variable(env, library, capsys):
    main(["index"])
    capsys.readouterr()

    main(["classify", "napkin"])

    items = output(capsys)["items"]
    assert [i["title"] for i in items] == ["Napkin"], "classify should filter the inbox by the query"
    assert items[0]["arg"] == "" and len(items[0]["variables"]["book"]) == 40, "the book travels as a variable, the query starts empty"


def test_genres_forwards_the_book_variable(env, library, capsys, monkeypatch):
    main(["index"])
    capsys.readouterr()
    monkeypatch.setenv("book", "abc123")

    main(["genres", "non"])

    out = output(capsys)
    assert out["items"][0]["variables"] == {"book": "abc123"}, "each genre item must carry the book on to the tag step"


def test_genres_without_book_explains(env, library, capsys, monkeypatch):
    main(["index"])
    capsys.readouterr()
    monkeypatch.delenv("book", raising=False)

    main(["genres", ""])

    assert output(capsys)["items"][0]["valid"] is False, "without a selected book the picker must not be actionable"


def test_search_items_offer_fix_on_shift(env, capsys):
    main(["index"])
    capsys.readouterr()

    main(["search", "deep"])

    item = output(capsys)["items"][0]
    assert item["mods"]["shift"]["arg"] == "", "shift+↩ should open the fix picker with an empty query"
    assert "genre" in item["mods"]["shift"]["subtitle"].lower(), "the shift subtitle should say it fixes genre/tags"
    assert item["variables"]["book"] == item["mods"]["shift"]["variables"]["book"], "the fingerprint must travel with the shift action"


def test_fix_lists_genres_and_current_tags(env, library, capsys, monkeypatch):
    main(["index"])
    main(["tag", str(library / "00_Inbox" / "Napkin.pdf"), "genre=games/go", "+now"])
    capsys.readouterr()
    main(["search", "napkin"])
    monkeypatch.setenv("book", output(capsys)["items"][0]["variables"]["book"])

    main(["fix", ""])

    items = output(capsys)["items"]
    assert items[0]["title"].startswith("Napkin") and items[0]["valid"] is False, "the first item should show the book being fixed"
    assert "games/go" in items[0]["subtitle"] and "now" in items[0]["subtitle"], "the header should show the current genre and tags"
    assert "-now" in [i.get("arg") for i in items], "each current tag should be removable"
    assert "genre=nonfiction" in [i.get("arg") for i in items], "known genres should be offered"


@pytest.mark.parametrize(
    "query, arg, title_start",
    [
        ("+read", "+read", "Add tag"),
        ("-old", "-old", "Remove tag"),
        ("fiction/mystery", "genre=fiction/mystery", "New genre"),
        ("non", "genre=nonfiction", "nonfiction"),
    ],
)
def test_fix_turns_query_into_an_edit(env, library, capsys, monkeypatch, query, arg, title_start):
    main(["index"])
    capsys.readouterr()
    main(["search", "napkin"])
    monkeypatch.setenv("book", output(capsys)["items"][0]["variables"]["book"])

    main(["fix", "--", query])

    edits = [i for i in output(capsys)["items"] if i.get("valid", True)]
    assert edits[0]["arg"] == arg, f"query {query!r} should offer the edit {arg!r}"
    assert edits[0]["title"].startswith(title_start), f"the offered edit should be labelled {title_start!r}"


def test_fix_without_book_explains(env, capsys, monkeypatch):
    main(["index"])
    capsys.readouterr()
    monkeypatch.delenv("book", raising=False)

    main(["fix", ""])

    assert output(capsys)["items"][0]["valid"] is False, "without a selected book the fix picker must not be actionable"


def test_tag_accepts_edit_from_fix_picker(env, library, capsys):
    main(["index"])
    capsys.readouterr()
    main(["search", "napkin"])
    fingerprint = output(capsys)["items"][0]["variables"]["book"]

    assert main(["tag", fingerprint, "+now"]) == 0, "an edit arg from the fix picker should be applied"
    assert capsys.readouterr().out.startswith("Napkin → no genre · now"), "the result should be reported"


def test_plan_list_starts_with_apply_all(env, capsys):
    main(["index"])
    capsys.readouterr()

    main(["plan"])

    items = output(capsys)["items"]
    assert items[0]["title"] == "Apply all 1 operations" and items[0]["arg"] == "", "↩ on the head row should apply the whole plan"
    assert all(i["subtitle"].startswith(("move", "trash", "dups", "skip")) for i in items[1:]), "the operations follow the head row"


def test_apply_with_empty_only_applies_the_whole_plan(env, capsys):
    main(["index"])
    main(["plan"])
    capsys.readouterr()

    assert main(["apply", "--only", ""]) == 0, "an empty --only (the plan list's head row) means the whole plan"
    assert capsys.readouterr().out.startswith("Applied 1"), "the plan should have been applied"


def test_apply_summary_names_the_skip_reason(env, library, tmp_path, capsys):
    main(["index"])
    main(["plan"])
    (library / "02_NonFiction" / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub").unlink()
    capsys.readouterr()

    main(["apply"])

    assert capsys.readouterr().out.startswith("Applied 0, skipped 1 (source missing)"), "the summary should say why operations were skipped"


def test_tag_with_genre_moves_the_book_to_its_genre_home(env, library, capsys):
    main(["index"])
    capsys.readouterr()
    book = library / "02_NonFiction" / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"

    assert main(["tag", str(book), "genre=productivity"]) == 0, "tagging with a genre should succeed"
    out = capsys.readouterr().out

    assert not book.exists(), "the book should leave its old folder as soon as the genre is set"
    moved = list(library.rglob("*.epub"))
    assert len(moved) == 1 and moved[0].parts[-3:-1] == ("productivity", "Newport, Cal"), "the book should land in genre/author"
    assert "Deep Work → productivity" in out and "→ productivity/Newport, Cal/" in out, "the report should name the new home"
    main(["search", "deep"])
    assert output(capsys)["items"][0]["subtitle"].count("productivity") >= 1, "the index should already know the new path"


def test_tag_without_genre_edit_leaves_the_file_alone(env, library, capsys):
    main(["index"])
    capsys.readouterr()
    book = library / "02_NonFiction" / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"

    assert main(["tag", str(book), "+now"]) == 0, "adding a tag should succeed"

    assert book.exists(), "a tag-only edit should not move anything"


def test_tag_with_genre_reports_when_there_is_no_home_yet(env, library, capsys):
    main(["index"])
    capsys.readouterr()
    book = library / "00_Inbox" / "Napkin.pdf"

    assert main(["tag", str(book), "genre=reference"]) == 0, "a book without an author can still be tagged"

    assert book.exists(), "a book whose home cannot be derived stays put"
    assert "stays put" in capsys.readouterr().out, "the report should say the book was not moved"


def test_tag_with_genre_accepts_notify_like_the_other_movers(env, library, mocker):
    main(["index"])
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
def test_search_runs_a_command_named_by_its_first_word(env, capsys, query, first_title, action):
    main(["index"])
    capsys.readouterr()

    main(["search", query])

    first = output(capsys)["items"][0]
    assert first["title"].startswith(first_title), f"kb {query} should show the same items as kb:{query}"
    assert first.get("variables", {}).get("action") == action, "every command item should say how ↩ dispatches it"


def test_search_command_items_come_before_matching_books(env, library, capsys):
    (library / "00_Inbox" / "Stats for Dummies - Anon.pdf").write_bytes(b"%PDF-1.4")
    main(["index"])
    capsys.readouterr()

    main(["search", "stats"])

    titles = [i["title"] for i in output(capsys)["items"]]
    assert titles[0] == "5 books indexed", "the command comes first"
    assert "Stats for Dummies" in titles, "books that happen to match the word still follow"


def test_search_command_takes_the_rest_as_its_query(env, capsys):
    main(["index"])
    capsys.readouterr()

    main(["search", "rnd fmt:epub"])

    items = output(capsys)["items"]
    assert [i["title"] for i in items] == ["Deep Work"], "kb rnd <query> should filter like kb:rnd <query>"
    assert items[0]["variables"]["action"] == "open", "a book item from a picker opens like any other book"


def test_search_action_item_is_actionable_and_has_no_arg(env, capsys):
    main(["index"])
    capsys.readouterr()

    main(["search", "index"])

    item = output(capsys)["items"][0]
    assert item["valid"] is True and item["arg"] == "", "↩ on a keyword command should fire it with an empty argument"


def test_search_plain_word_is_still_a_search(env, capsys):
    main(["index"])
    capsys.readouterr()

    main(["search", "deep"])

    assert output(capsys)["items"][0]["title"] == "Deep Work", "an ordinary word must not be mistaken for a command"
