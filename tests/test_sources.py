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
    (root / "Nova.epub.part").write_bytes(b"half a zip")
    (root / "Dead Lines.epub").write_bytes(b"garbage")
    (root / "Not Found.pdf").write_bytes(b"<html>404</html>")
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
    return [i["title"] for i in output(capsys)["items"] if i.get("uid") != "src:import-all"]


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
        ("downloads", ["No books match “downloads”"]),
        ("calibre slow", ["Slow Productivity"]),
        ("epub newport", ["A World Without Email", "Slow Productivity"]),
    ],
)
def test_sources_search_uses_words(env, capsys, query, expected):
    main(["index-sources"])
    capsys.readouterr()

    main(["sources", query])

    assert sorted(titles(capsys)) == expected, "the source folder is a word; books the library already holds are hidden"


@pytest.mark.parametrize("query", ["nova", "dead", "found", "part"])
def test_sources_skip_partial_and_broken_files(env, capsys, query):
    main(["index-sources"])
    capsys.readouterr()

    main(["sources", query])

    assert titles(capsys)[0].startswith("No books match"), f"{query}: unfinished and unreadable files are not worth importing"


def test_import_refuses_broken_file(env, downloads, capsys):
    assert main(["import", str(downloads / "Dead Lines.epub")]) == 1, "an unreadable file is not imported"
    assert "unreadable" in capsys.readouterr().out, "the reason should be reported"


def test_sources_search_before_index_explains(env, capsys, tmp_path):
    (tmp_path / "alfred-data" / "sources.db").unlink()
    main(["sources", "slow"])
    assert output(capsys)["items"][0]["title"] == "No sources index yet", "searching sources without an index should tell how to build it"


def test_sources_hides_books_already_in_library(env, capsys):
    main(["index-sources"])
    capsys.readouterr()

    main(["sources", "deep"])

    item = output(capsys)["items"][0]
    assert item["title"].startswith("No books match"), "a book already in the library is not offered again"


def test_sources_empty_query_hides_library_copies_too(env, capsys):
    main(["index-sources"])
    capsys.readouterr()

    main(["sources", ""])

    assert "Deep Work" not in titles(capsys), "the newest-first listing should skip what the library already holds"


def test_index_also_rebuilds_the_sources_index(env, tmp_path, capsys):
    (tmp_path / "alfred-data" / "sources.db").unlink(missing_ok=True)
    capsys.readouterr()

    assert main(["index"]) == 0, "index should succeed"

    out = capsys.readouterr().out
    assert "Indexed 4 books from" in out and "Indexed 3 books from 2 sources" in out, "one command reports both indexes"
    assert (tmp_path / "alfred-data" / "sources.db").exists(), "the sources index should be rebuilt alongside the library"


def test_index_without_sources_stays_quiet_about_them(env, capsys, monkeypatch):
    monkeypatch.setenv("KOBO_SOURCES", "")
    capsys.readouterr()

    assert main(["index"]) == 0, "no sources is not an error for index"

    assert "from 2 sources" not in capsys.readouterr().out and "No sources" not in capsys.readouterr().out, (
        "nothing to say about sources when none are configured"
    )


def test_index_reports_unmounted_sources_without_failing(env, capsys, monkeypatch, tmp_path, calibre):
    monkeypatch.setenv("KOBO_SOURCES", f"{calibre}:{tmp_path / 'absent'}")
    capsys.readouterr()

    assert main(["index"]) == 0, "an unmounted source should not fail the library index"

    assert "skipped 1 unmounted" in capsys.readouterr().out, "the unmounted source should be mentioned"


def test_sources_items_carry_import_actions(env, capsys):
    main(["index-sources"])
    capsys.readouterr()

    main(["sources", "slow"])

    item = output(capsys)["items"][0]
    assert item["valid"] is True and item["arg"].endswith("Slow Productivity - Cal Newport.epub"), "↩ passes the absolute path to import"
    assert "reveal" in item["mods"]["alt"]["subtitle"].lower(), "⌥↩ reveals the source file, as in kb"
    assert "copy" in item["mods"]["cmd"]["subtitle"].lower(), "⌘↩ copies the path, as in kb"
    assert item["mods"]["alt"]["arg"] == item["mods"]["cmd"]["arg"] == item["arg"], "both modifiers act on the source file itself"


def test_sources_rows_offer_importing_the_whole_list(env, capsys):
    main(["index-sources"])
    capsys.readouterr()

    items = [i for i in run_items(["sources", ""], capsys) if "mods" in i]

    everyone = "\n".join(i["arg"] for i in items)
    for item in items:
        assert item["mods"]["alt+shift"]["arg"] == everyone, "⌥⇧↩ imports every listed book"
        assert item["mods"]["alt+shift"]["subtitle"] == f"Import all {len(items)} shown", "the subtitle should count the books"


def test_sources_list_starts_with_import_all(env, capsys):
    main(["index-sources"])
    capsys.readouterr()

    items = run_items(["sources", ""], capsys)

    head, *books = items
    assert head["title"] == f"Import all {len(books)} books" and head.get("valid", True), "the first row imports every book listed"
    assert head["arg"] == "\n".join(b["arg"] for b in books), "its argument is the listed paths, one per line"
    assert head["uid"] == "src:import-all", "a stable uid keeps the head row on top"


def test_single_source_result_has_no_head_row(env, capsys):
    main(["index-sources"])
    capsys.readouterr()

    items = run_items(["sources", "slow"], capsys)

    assert [i["title"] for i in items] == ["Slow Productivity"], "one book needs no 'import all' row"


def run_items(argv: list[str], capsys) -> list[dict]:
    main(argv)
    return output(capsys)["items"]


def test_import_copies_many_books_at_once(env, library, calibre, capsys):
    paths = "\n".join(str(p) for p in sorted(calibre.rglob("*.epub")))

    assert main(["import", paths]) == 0, "a batch import should succeed"

    assert capsys.readouterr().out.startswith("Imported 2 books → 00_Inbox/"), "the summary should count the books"
    assert sorted(p.name for p in (library / "00_Inbox").glob("*.epub")) == [
        "A World Without Email.epub",
        "Slow Productivity - Cal Newport.epub",
    ], "both books should land in the inbox"


def test_import_batch_reports_what_it_skipped(env, calibre, downloads, capsys):
    paths = f"{calibre / 'Misc' / 'A World Without Email.epub'}\n{downloads / 'deep_work_copy.epub'}"

    assert main(["import", paths]) == 0, "one blocked book does not fail the batch"

    out = capsys.readouterr().out
    assert out.startswith("Imported A World Without Email → 00_Inbox/") and "skipped 1: already in library" in out, (
        "a single import is named, skipped ones are counted with their reason"
    )


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


def test_import_only_copies(env, calibre):
    src = calibre / "Misc" / "A World Without Email.epub"
    with pytest.raises(SystemExit):
        main(["import", "--move", str(src)])
    assert src.exists(), "there is no way to move a source book into the library"


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
