import json
import zipfile
from pathlib import Path

import pytest

from kobolib.cli import main
from tests.conftest import CONTAINER, OPF, PNG_1X1


def write_epub(path: Path, title: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", OPF.replace("Deep Work", title))
        zf.writestr("OEBPS/images/cover.png", PNG_1X1)
    return path


@pytest.fixture
def elsewhere(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("elsewhere")


@pytest.fixture
def calibre(elsewhere: Path) -> Path:
    root = elsewhere / "Calibre Library"
    write_epub(root / "Cal Newport" / "Slow Productivity" / "Slow Productivity - Cal Newport.epub", "Slow Productivity")
    write_epub(root / "Misc" / "A World Without Email.epub", "A World Without Email")
    return root


@pytest.fixture
def downloads(elsewhere: Path, library: Path) -> Path:
    root = elsewhere / "Downloads"
    root.mkdir()
    deep = library / "02_NonFiction" / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"
    (root / "deep_work_copy.epub").write_bytes(deep.read_bytes())
    return root


@pytest.fixture
def env(library: Path, calibre: Path, downloads: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KOBO_ROOT", str(library))
    monkeypatch.setenv("KOBO_SOURCES", f"{calibre}:{downloads}")
    monkeypatch.setenv("alfred_workflow_data", str(tmp_path / "alfred-data"))
    monkeypatch.delenv("KOBO_DATA", raising=False)
    main(["index"])


def output(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def titles(capsys) -> list[str]:
    return [i["title"] for i in output(capsys)["items"]]


def test_index_sources_builds_a_separate_index(env, tmp_path, capsys):
    assert main(["index-sources"]) == 0, "indexing sources should succeed"
    assert "Indexed 3 books from 2 sources" in capsys.readouterr().out, "the summary should count books and sources"
    assert (tmp_path / "alfred-data" / "sources.db").exists(), "sources get their own index file"
    main(["search", "slow"])
    assert titles(capsys)[0].startswith("No books match"), "source books must not leak into the library index"


def test_index_sources_without_sources_explains(env, capsys, monkeypatch):
    monkeypatch.setenv("KOBO_SOURCES", "")
    assert main(["index-sources"]) == 1, "no sources configured should fail"
    assert "KOBO_SOURCES" in capsys.readouterr().out, "the message should name the setting"


def test_index_sources_skips_unmounted_source(env, tmp_path, capsys, monkeypatch, calibre):
    monkeypatch.setenv("KOBO_SOURCES", f"{calibre}:{tmp_path / 'missing'}")
    assert main(["index-sources"]) == 0, "one missing source should not block the others"
    assert "skipped 1 unmounted" in capsys.readouterr().out, "missing sources should be reported"


@pytest.mark.parametrize(
    "query, expected",
    [
        ("in:downloads", ["Deep Work"]),
        ("in:calibre slow", ["Slow Productivity"]),
        ("fmt:epub newport", ["A World Without Email", "Deep Work", "Slow Productivity"]),
    ],
)
def test_sources_search_uses_query_syntax(env, capsys, query, expected):
    main(["index-sources"])
    capsys.readouterr()

    main(["sources", query])

    assert sorted(titles(capsys)) == expected, "the source folder name is part of the path, so in: narrows by source"


def test_sources_search_before_index_explains(env, capsys):
    main(["sources", "slow"])
    assert output(capsys)["items"][0]["title"] == "No sources index yet", "searching sources without an index should tell how to build it"


def test_sources_marks_books_already_in_library(env, capsys):
    main(["index-sources"])
    capsys.readouterr()

    main(["sources", "deep"])

    item = output(capsys)["items"][0]
    assert item["valid"] is False, "a book already in the library cannot be imported again"
    assert item["subtitle"].startswith("✓ in library"), "the subtitle should say the book is already there"
    assert "02_NonFiction/" in item["subtitle"], "and where it is"


def test_sources_items_carry_import_actions(env, capsys):
    main(["index-sources"])
    capsys.readouterr()

    main(["sources", "slow"])

    item = output(capsys)["items"][0]
    assert item["valid"] is True and item["arg"].endswith("Slow Productivity - Cal Newport.epub"), "↩ passes the absolute path to import"
    assert "move" in item["mods"]["alt"]["subtitle"].lower(), "⌥↩ moves instead of copying"


def test_import_copies_into_inbox_and_indexes(env, library, calibre, capsys):
    main(["index-sources"])
    capsys.readouterr()
    src = calibre / "Misc" / "A World Without Email.epub"

    assert main(["import", str(src)]) == 0, "import should succeed"

    assert capsys.readouterr().out.startswith("Imported A World Without Email → 00_Inbox/"), "import should report the destination"
    assert (library / "00_Inbox" / "A World Without Email.epub").exists(), "the book should land in the inbox"
    assert src.exists(), "copying leaves the source in place"
    main(["search", "email"])
    assert titles(capsys) == ["A World Without Email"], "the imported book should be searchable without a full reindex"
    main(["inbox"])
    assert "A World Without Email" in titles(capsys), "an imported book waits in the inbox for classification"


def test_import_move_removes_source(env, library, calibre, capsys):
    src = calibre / "Misc" / "A World Without Email.epub"
    assert main(["import", "--move", str(src)]) == 0, "import --move should succeed"
    assert not src.exists() and (library / "00_Inbox" / "A World Without Email.epub").exists(), "moving relocates the file"


def test_import_refuses_known_fingerprint(env, downloads, capsys):
    assert main(["import", str(downloads / "deep_work_copy.epub")]) == 1, "a book already in the library is not imported twice"
    assert "already in library" in capsys.readouterr().out, "the reason should be reported"


def test_import_refuses_occupied_destination(env, library, calibre, capsys):
    src = calibre / "Misc" / "A World Without Email.epub"
    (library / "00_Inbox" / "A World Without Email.epub").write_bytes(b"other")
    assert main(["import", str(src)]) == 1, "an existing file in the inbox must not be overwritten"
    assert "exists" in capsys.readouterr().out, "the reason should be reported"


def test_import_creates_inbox_when_library_has_none(env, library, calibre, capsys):
    for path in (library / "00_Inbox").iterdir():
        path.unlink()
    (library / "00_Inbox").rmdir()
    main(["index"])
    capsys.readouterr()

    main(["import", str(calibre / "Misc" / "A World Without Email.epub")])

    assert (library / "_inbox" / "A World Without Email.epub").exists(), "without an inbox folder a new _inbox is created"


def test_import_is_refused_while_indexing(env, tmp_path, calibre, capsys):
    (tmp_path / "alfred-data" / "library.lock").write_text("1")
    assert main(["import", str(calibre / "Misc" / "A World Without Email.epub")]) == 1, "import must not write to a database being rebuilt"


def test_stats_counts_sources(env, capsys):
    main(["index-sources"])
    capsys.readouterr()
    main(["stats"])
    assert any(t.startswith("3 books in 2 sources") for t in titles(capsys)), "stats should mention the sources index"
