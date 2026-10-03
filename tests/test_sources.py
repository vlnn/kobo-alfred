import json
import os
import zipfile
from pathlib import Path

import pytest

from kobold.cli import main
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
    monkeypatch.setenv("KOBOLD_ROOT", str(library))
    monkeypatch.setenv("KOBOLD_SOURCES", f"{calibre}:{downloads}")
    monkeypatch.setenv("alfred_workflow_data", str(tmp_path / "alfred-data"))
    monkeypatch.delenv("KOBOLD_DATA", raising=False)
    main(["update"])


def output(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def titles(capsys) -> list[str]:
    return [i["title"] for i in output(capsys)["items"] if i.get("uid") != "src:import-all"]


def test_update_builds_a_separate_sources_index(env, tmp_path, capsys):
    capsys.readouterr()
    assert main(["update"]) == 0, "updating with sources configured should succeed"
    assert "Indexed 3 books from 2 sources" in capsys.readouterr().out, "the summary should count books and sources"
    assert (tmp_path / "alfred-data" / "sources.db").exists(), "sources get their own index file"
    main(["search", "slow"])
    assert titles(capsys)[0].startswith("No books match"), "source books must not leak into the library index"


@pytest.mark.parametrize(
    "query, expected",
    [
        ("downloads", ["1 book matches ‘downloads’, already in the library"]),
        ("calibre slow", ["Slow Productivity"]),
        ("epub newport", ["A World Without Email", "Slow Productivity"]),
    ],
)
def test_sources_search_uses_words(env, capsys, query, expected):

    main(["search", "src " + query])

    assert sorted(titles(capsys)) == expected, "the source folder is a word; books the library already holds are hidden"


@pytest.mark.parametrize("query", ["nova", "dead", "found", "part"])
def test_sources_skip_partial_and_broken_files(env, capsys, query):

    main(["search", "src " + query])

    assert titles(capsys)[0].startswith("No books match"), f"{query}: unfinished and unreadable files are not worth importing"


def test_import_refuses_broken_file(env, downloads, capsys):
    assert main(["import", str(downloads / "Dead Lines.epub")]) == 1, "an unreadable file is not imported"
    assert "unreadable" in capsys.readouterr().out, "the reason should be reported"


def test_sources_search_before_index_explains(env, capsys, tmp_path):
    (tmp_path / "alfred-data" / "sources.db").unlink()
    main(["search", "src slow"])
    assert output(capsys)["items"][0]["title"] == "No sources index yet", "searching sources without an index should tell how to build it"


def test_sources_hides_books_already_in_library(env, capsys):

    main(["search", "src deep"])

    item = output(capsys)["items"][0]
    assert item["title"].endswith("already in the library") and not item.get("valid", True), (
        "a book already in the library is not offered again"
    )


def test_sources_empty_query_hides_library_copies_too(env, capsys):

    main(["search", "src "])

    assert "Deep Work" not in titles(capsys), "the newest-first listing should skip what the library already holds"


def test_update_also_rebuilds_the_sources_index(env, tmp_path, capsys):
    (tmp_path / "alfred-data" / "sources.db").unlink(missing_ok=True)
    capsys.readouterr()

    assert main(["update"]) == 0, "index should succeed"

    out = capsys.readouterr().out
    assert "Indexed 4 books from" in out and "Indexed 3 books from 2 sources" in out, "one command reports both indexes"
    assert (tmp_path / "alfred-data" / "sources.db").exists(), "the sources index should be rebuilt alongside the library"


def test_update_without_sources_stays_quiet_about_them(env, capsys, monkeypatch):
    monkeypatch.setenv("KOBOLD_SOURCES", "")
    capsys.readouterr()

    assert main(["update"]) == 0, "no sources is not an error for index"

    assert "from 2 sources" not in capsys.readouterr().out and "No sources" not in capsys.readouterr().out, (
        "nothing to say about sources when none are configured"
    )


def test_update_reports_unmounted_sources_without_failing(env, capsys, monkeypatch, tmp_path, calibre):
    monkeypatch.setenv("KOBOLD_SOURCES", f"{calibre}:{tmp_path / 'absent'}")
    capsys.readouterr()

    assert main(["update"]) == 0, "an unmounted source should not fail the library index"

    assert f"skipped 1 unmounted: {tmp_path / 'absent'}" in capsys.readouterr().out, "the unmounted source should be named"


def test_sources_items_carry_import_actions(env, capsys, calibre):

    main(["search", "src slow"])

    item = output(capsys)["items"][0]
    assert item["valid"] is True and item["arg"].startswith(str(calibre)), "↩ passes the absolute path inside the source"
    assert "reveal" in item["mods"]["alt"]["subtitle"].lower(), "⌥↩ reveals the source file, as in kb"
    assert item["mods"]["alt"]["arg"] == item["arg"], "⌥↩ acts on the source file itself"


def test_sources_rows_carry_no_bulk_modifier(env, capsys):

    items = run_items(["search", "src"], capsys)

    assert not any("alt+shift" in i.get("mods", {}) for i in items), "importing everything is the head row's job, not a modifier"


def test_sources_list_starts_with_import_all(env, capsys):

    items = run_items(["search", "src"], capsys)

    head, *books = items
    assert head["title"] == f"Import all {len(books)} books" and head.get("valid", True), "the first row imports every book listed"
    assert head["arg"] == "\n".join(b["arg"] for b in books), "its argument is the listed paths, one per line"
    assert head["uid"] == "src:import-all", "a stable uid keeps the head row on top"


def test_single_source_result_has_no_head_row(env, capsys):

    items = run_items(["search", "src slow"], capsys)

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


def test_import_summary_ends_with_the_inbox_count(env, calibre, capsys):
    capsys.readouterr()

    main(["import", str(calibre / "Misc" / "A World Without Email.epub")])

    assert capsys.readouterr().out.rstrip().endswith(" · 3 books without a genre"), "the import summary should end with the inbox count"


def test_import_copies_into_inbox_and_indexes(env, library, calibre, capsys):
    src = calibre / "Misc" / "A World Without Email.epub"

    assert main(["import", str(src)]) == 0, "import should succeed"

    assert capsys.readouterr().out.startswith("Imported A World Without Email → 00_Inbox/"), "import should report the destination"
    assert (library / "00_Inbox" / "A World Without Email.epub").exists(), "the book should land in the inbox"
    assert src.exists(), "copying leaves the source in place"
    main(["search", "email"])
    assert titles(capsys) == ["A World Without Email"], "the imported book should be searchable without a full reindex"
    main(["search", "inbox"])
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
    main(["update"])
    capsys.readouterr()

    main(["import", str(calibre / "Misc" / "A World Without Email.epub")])

    assert (library / "_inbox" / "A World Without Email.epub").exists(), "without an inbox folder a new _inbox is created"


def test_import_is_refused_while_indexing(env, tmp_path, calibre, capsys):
    (tmp_path / "alfred-data" / "library.lock").write_text("1")
    assert main(["import", str(calibre / "Misc" / "A World Without Email.epub")]) == 1, "import must not write to a database being rebuilt"


def test_stats_source_row_completes_to_its_search(env, capsys):
    main(["search", "stats"])
    row = next(i for i in output(capsys)["items"] if i["title"].endswith("in Calibre Library"))
    assert row["autocomplete"] == "src Calibre Library ", "the source row should complete to kb src for that source"


def test_sources_hide_library_copies_before_cutting_the_list(env, library, elsewhere, capsys):
    backup = elsewhere / "backup"
    deep = library / "02_NonFiction" / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"
    for n in range(45):
        (backup / f"copy_{n:02d}.epub").parent.mkdir(exist_ok=True)
        (backup / f"copy_{n:02d}.epub").write_bytes(deep.read_bytes())
    older = write_epub(backup / "old" / "Older Book.epub", "Older Book")
    os.utime(older, (older.stat().st_mtime - 10_000,) * 2)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("KOBOLD_SOURCES", str(backup))
        main(["update"])
        capsys.readouterr()

        main(["search", "src"])

    assert titles(capsys) == ["Older Book"], "a book older than 40 library copies should still be offered"


def test_sources_say_when_every_match_is_already_in_the_library(env, capsys):

    main(["search", "src deep"])

    item = output(capsys)["items"][0]
    assert item["title"] == "1 book matches ‘deep’, already in the library", "the user should learn the source works but holds nothing new"


def test_stats_counts_new_books_per_source(env, capsys, calibre, downloads):

    main(["search", "stats"])

    items = output(capsys)["items"]
    assert any(i["title"] == "2 new of 2 books in Calibre Library" for i in items), "each source should report its new and total books"
    assert any(i["title"] == "0 new of 1 book in Downloads" for i in items), "a source holding only library copies should say so"


def test_sources_paths_are_trimmed(monkeypatch, tmp_path):
    from kobold.config import sources

    monkeypatch.setenv("KOBOLD_SOURCES", f" {tmp_path / 'a'} : {tmp_path / 'b'}")
    assert sources() == [tmp_path / "a", tmp_path / "b"], "spaces around ':' should not become part of a path"


@pytest.fixture
def many_new(env, elsewhere, capsys) -> Path:
    pile = elsewhere / "pile"
    for n in range(45):
        write_epub(pile / ("a" if n % 2 else "b") / f"Book {n:02d}.epub", f"Book {n:02d}")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("KOBOLD_SOURCES", str(pile))
        main(["update"])
        capsys.readouterr()
        yield pile


def test_src_lists_every_new_book_without_paging(many_new, capsys):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("KOBOLD_SOURCES", str(many_new))
        head, *books = run_items(["search", "src"], capsys)

    assert len(books) == 45, "kb src is not cut to a page: every new book from every source is listed"
    assert head["title"] == "Import all 45 books" and len(head["arg"].splitlines()) == 45, "↩ imports all of them"
