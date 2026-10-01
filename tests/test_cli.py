import json
from pathlib import Path

import pytest

from kobolib.cli import main


@pytest.fixture
def env(library: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KOBO_ROOT", str(library))
    monkeypatch.setenv("alfred_workflow_data", str(tmp_path / "alfred-data"))
    monkeypatch.delenv("KOBO_DATA", raising=False)


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
