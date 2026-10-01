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
    assert items[0]["subtitle"].endswith("02_NonFiction/Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"), "subtitle should end with the library-relative path"


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
    assert "partial\t" in out and "00_Inbox/Delany, Samuel R - Nova - 2014.epub.part" in out, "text report should list rule and path per line"


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
    assert plan_file.read_text(encoding="utf-8").count("\n") == len(items) + 1, "every operation should be in the file"


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
    assert (library / "02_NonFiction" / "Newport, Cal" / "Newport, Cal - Deep Work (Focus 02) (2016).epub").exists(), "the book should be renamed into its author folder"
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
    assert [i["arg"] for i in output(capsys)["items"]] == ["genre=games/go", "genre=nonfiction"], "all genres from tags and folders should be listed"


def test_genres_offers_new_genre_from_query(env, library, capsys):
    main(["index"])
    capsys.readouterr()

    main(["genres", "fiction/mystery"])

    items = output(capsys)["items"]
    assert items[-1]["arg"] == "genre=fiction/mystery" and items[-1]["title"].startswith("New genre"), "an unknown genre can be created from the query"


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
