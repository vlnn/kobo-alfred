from pathlib import Path

import pytest

from kobolib.index import Index, build_index
from kobolib.query import parse_query


@pytest.fixture
def index(library: Path, tmp_path: Path) -> Index:
    db = tmp_path / "cache" / "library.db"
    build_index(library, db, cover_cache=tmp_path / "cache" / "covers")
    return Index(db)


def titles(rows) -> list[str]:
    return [r.title for r in rows]


def test_build_indexes_all_books(index: Index):
    assert index.count() == 4, "all four scanned files should be indexed"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("deep", ["Deep Work"]),
        ("newport", ["Deep Work"]),
        ("author:newport", ["Deep Work"]),
        ("оперант", ["Оперантное поведение"]),
        ("скинн", ["Оперантное поведение"]),
        ("fmt:fb2", ["Оперантное поведение"]),
        ("in:inbox fmt:epub", ["Nova"]),
        ("is:partial", ["Nova"]),
        ("lang:en", ["Deep Work"]),
        ("series:focus", ["Deep Work"]),
        ("year:2016", ["Deep Work"]),
        ("in:nonfiction", ["Deep Work"]),
        ("nothing-here", []),
    ],
)
def test_search(index: Index, raw, expected):
    assert titles(index.search(parse_query(raw))) == expected, f"{raw!r} should find {expected}"


def test_empty_query_lists_recent_first(index: Index, library: Path):
    import os
    import time

    newest = library / "00_Inbox" / "Napkin.pdf"
    os.utime(newest, (time.time() + 100, time.time() + 100))
    build_index(library, index.db_path, cover_cache=library / "c")

    assert titles(index.search(parse_query("")))[0] == "Napkin", "empty query should list most recently added first"


def test_rel_path_and_cover_stored(index: Index):
    (row,) = index.search(parse_query("deep"))
    assert row.rel_path.startswith("02_NonFiction/"), "rel_path should be relative to the library root"
    assert row.cover and Path(row.cover).exists(), "epub cover should be extracted into the cache"


def test_duplicates_group_by_normalized_title(index: Index, library: Path):
    (library / "00_Inbox" / "Newport, Cal - Deep Work.fb2.part").write_bytes(b"")
    build_index(library, index.db_path, cover_cache=library / "c")

    groups = index.duplicates()

    assert [g.title for g in groups] == ["Deep Work"], "same title in different files should be reported as duplicate"
    assert sorted(b.format for b in groups[0].books) == ["epub", "fb2"], "duplicate group should list both formats"


def test_rebuild_replaces_old_rows(index: Index, library: Path):
    (library / "00_Inbox" / "Napkin.pdf").unlink()
    build_index(library, index.db_path, cover_cache=library / "c")

    assert index.count() == 3, "rebuild should drop books that no longer exist"


def test_rebuild_swaps_atomically_and_keeps_old_index_readable(index: Index, library: Path, mocker):
    import kobolib.index as mod

    seen = []
    original = mod.records

    def spying_records(root, cache, exclude):
        seen.append(index.count())
        yield from original(root, cache, exclude)

    mocker.patch("kobolib.index.records", side_effect=spying_records)
    build_index(library, index.db_path, cover_cache=library / "c")

    assert seen == [4], "old index should stay readable while the new one is being built"
    assert not index.db_path.with_suffix(".tmp").exists(), "temporary database should be swapped away"


def test_concurrent_build_is_refused(index: Index, library: Path):
    from kobolib.index import IndexBusy, lock_path

    lock_path(index.db_path).touch()
    with pytest.raises(IndexBusy):
        build_index(library, index.db_path, cover_cache=library / "c")


def test_stale_lock_is_ignored(index: Index, library: Path):
    import os
    import time

    from kobolib.index import lock_path

    lock = lock_path(index.db_path)
    lock.touch()
    os.utime(lock, (time.time() - 7200, time.time() - 7200))

    assert build_index(library, index.db_path, cover_cache=library / "c") == 4, "a stale lock should not block indexing"
    assert not lock.exists(), "lock should be removed after a successful build"


def test_fill_thumbnails_updates_pdf_rows(index: Index, library: Path, mocker):
    from kobolib.index import fill_thumbnails
    from tests.conftest import PNG_1X1

    def fake_qlmanage(cmd, **kwargs):
        out_dir = Path(cmd[cmd.index("-o") + 1])
        (out_dir / "thumb.png").write_bytes(PNG_1X1)
        return mocker.Mock(returncode=0)

    mocker.patch("kobolib.covers.shutil.which", return_value="/usr/bin/qlmanage")
    mocker.patch("kobolib.covers.subprocess.run", side_effect=fake_qlmanage)

    made = fill_thumbnails(index.db_path, library / "c")

    (napkin,) = index.search(parse_query("napkin"))
    assert made == 1, "only the pdf without a cover should get a thumbnail"
    assert napkin.cover.endswith(".png"), "the pdf row should now carry its thumbnail path"


def test_fingerprint_stored_per_book(index: Index):
    (row,) = index.search(parse_query("deep"))
    assert len(row.fingerprint) == 40, "each indexed book should carry a fingerprint"


def test_write_genres_updates_rows_and_search_filters(index: Index):
    (deep,) = index.search(parse_query("deep"))

    index.write_genres({deep.fingerprint: "nonfiction/focus"})

    assert titles(index.search(parse_query("genre:nonfiction"))) == ["Deep Work"], "genre: should match by prefix"
    assert titles(index.search(parse_query("genre:nonfiction/focus"))) == ["Deep Work"], "genre: should match the full genre"


def test_relocate_moves_a_row_to_its_new_path(index: Index, library: Path):
    src = "02_NonFiction/Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"
    dst = "02_NonFiction/Newport, Cal/Newport, Cal - Deep Work (2016).epub"

    index.relocate(src, dst, library)

    row = index.by_rel_path(dst)
    assert row is not None and row.folder == "02_NonFiction/Newport, Cal", "the moved row should carry its new path and folder"
    assert row.path == str(library / dst), "the absolute path should follow the move"
    assert index.by_rel_path(src) is None, "the old path should be gone"
    assert titles(index.search(parse_query("in:newport"))) == ["Deep Work"], "the new folder should be searchable at once"


@pytest.mark.parametrize("aside", ["_trash", "_dups"])
def test_relocate_into_a_set_aside_folder_drops_the_row(index: Index, library: Path, aside):
    src = "00_Inbox/Napkin.pdf"

    index.relocate(src, f"{aside}/{src}", library)

    assert index.by_rel_path(src) is None and index.count() == 3, f"a book moved to {aside} leaves the index like the scanner would skip it"


def test_remove_drops_a_row(index: Index):
    index.remove("00_Inbox/Napkin.pdf")
    assert index.count() == 3 and index.by_rel_path("00_Inbox/Napkin.pdf") is None, "a removed path should leave the index"


def test_unclassified_lists_books_without_genre_oldest_first(index: Index, library: Path):
    import os

    os.utime(library / "00_Inbox" / "Napkin.pdf", (1, 1))
    build_index(library, index.db_path, cover_cache=library / "c")
    classified = index.by_rel_path("02_NonFiction/Newport, Cal - Deep Work (2016, GC) - libgen.li.epub")
    with_genre = index.by_fingerprint(classified.fingerprint)
    index.write_genres({with_genre.fingerprint: "nonfiction"})

    listed = titles(index.unclassified())
    assert listed[0] == "Napkin" and set(listed) == {"Napkin", "Оперантное поведение", "Nova"}, "books with no genre, oldest first"
    assert titles(index.unclassified("napk")) == ["Napkin"], "the query narrows by title, author or path, case-insensitively"


def test_genres_and_folders_are_distinct_columns(index: Index):
    index.write_genres({index.by_rel_path("00_Inbox/Napkin.pdf").fingerprint: "games/go"})

    assert index.genres() == ["games/go"], "only genres that are set should be listed"
    assert index.folders() == ["00_Inbox", "02_NonFiction"], "every folder that holds a book, once"


def test_fingerprints_among_returns_only_the_known_ones(index: Index):
    known = index.by_rel_path("00_Inbox/Napkin.pdf").fingerprint
    assert index.fingerprints_among([known, "nope"]) == {known}, "only fingerprints that are in the index come back"
    assert index.fingerprints_among([]) == set(), "nothing asked, nothing found"


def test_write_genres_touches_only_the_named_book(index: Index):
    napkin = index.by_rel_path("00_Inbox/Napkin.pdf")
    index.write_genres({napkin.fingerprint: "games/go"})

    assert index.by_fingerprint(napkin.fingerprint).genre == "games/go", "the one book carries its genre"
    assert index.genres() == ["games/go"], "no other book gained a genre"


def test_index_has_no_tags_column():
    from kobolib.index import COLUMNS

    assert "tags" not in COLUMNS, "tags are gone from the index"


def test_columns_follow_the_row_dataclass():
    from dataclasses import fields

    from kobolib.index import COLUMNS, SCHEMA
    from kobolib.model import Row

    assert tuple(f.name for f in fields(Row)) == COLUMNS, "the insert order and the Row field order are one and the same"
    assert all(column in SCHEMA for column in COLUMNS), "every Row field is a column of the books table"


def test_every_connection_is_closed_after_use(index: Index, mocker):
    import sqlite3

    opened = []
    real_connect = sqlite3.connect

    def tracked(*args, **kwargs):
        opened.append(conn := real_connect(*args, **kwargs))
        return conn

    mocker.patch("kobolib.index.sqlite3.connect", side_effect=tracked)
    index.count()
    index.search(parse_query("deep"))
    index.write_genres({"nope": "x"})

    assert len(opened) == 3, "each operation opens its own connection"
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


@pytest.mark.parametrize("raw", ["in:пригоди", "in:Пригоди", "in:ПРИГОДИ", "lang:EN"])
def test_filters_fold_case_beyond_ascii(index: Index, library: Path, raw):
    import shutil

    (library / "03_Пригоди").mkdir()
    shutil.move(library / "02_NonFiction" / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub", library / "03_Пригоди")
    build_index(library, index.db_path, cover_cache=library / "c")

    assert titles(index.search(parse_query(raw))) == ["Deep Work"], f"{raw!r} should match regardless of case, Cyrillic included"


def test_relocate_carries_the_cover_to_the_new_key(index: Index, library: Path):
    from kobolib.covers import cover_key

    src = "02_NonFiction/Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"
    dst = "02_NonFiction/Newport, Cal/Newport, Cal - Deep Work (2016).epub"
    old_cover = Path(index.by_rel_path(src).cover)

    index.relocate(src, dst, library)

    new_cover = Path(index.by_rel_path(dst).cover)
    assert new_cover.name == f"{cover_key(dst)}{old_cover.suffix}" and new_cover.exists(), (
        "the cover file follows the book under its new key"
    )
    assert not old_cover.exists(), "no orphan is left under the old key"
    assert index.by_rel_path(dst).cover == str(new_cover), "the row points at the renamed cover"


@pytest.fixture
def indexed(library: Path, tmp_path: Path, monkeypatch) -> Path:
    from kobolib.cli import main

    monkeypatch.setenv("KOBO_ROOT", str(library))
    monkeypatch.setenv("alfred_workflow_data", str(tmp_path / "alfred-data"))
    monkeypatch.delenv("KOBO_DATA", raising=False)
    main(["index"])
    return tmp_path / "alfred-data" / "library.db"


def age(db: Path) -> None:
    import sqlite3

    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA user_version = 0")


def first_title(capsys) -> str:
    import json

    return json.loads(capsys.readouterr().out)["items"][0]["title"]


@pytest.mark.parametrize("command", [["search", "deep"], ["inbox"], ["dups"], ["stats"], ["random", ""], ["lint"], ["plan"]])
def test_index_from_an_older_version_asks_for_a_rebuild(indexed: Path, capsys, command):
    from kobolib.cli import main

    age(indexed)
    main(command)

    assert first_title(capsys) == "Index is from an older version", f"{command[0]} should not read an index whose fingerprints are stale"


def test_old_index_refuses_writes(indexed: Path, library: Path, capsys):
    from kobolib.cli import main

    age(indexed)

    assert main(["import", str(library / "00_Inbox" / "Napkin.pdf")]) == 1, "an old index cannot tell what the library already holds"
    assert main(["tag", str(library / "00_Inbox" / "Napkin.pdf"), "genre=reference"]) == 1, "tagging would key on a stale fingerprint"
    assert "older version" in capsys.readouterr().out, "the reason should name the rebuild"


def test_reindex_brings_an_old_index_up_to_date(indexed: Path, capsys):
    from kobolib.cli import main

    age(indexed)
    main(["index"])
    capsys.readouterr()
    main(["search", "deep"])

    assert first_title(capsys) == "Deep Work", "kb:index should rewrite the index at the current version"
