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
    import os, time
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

    def spying_records(root, cache):
        seen.append(index.count())
        yield from original(root, cache)

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
    import os, time
    from kobolib.index import lock_path

    lock = lock_path(index.db_path)
    lock.touch()
    os.utime(lock, (time.time() - 7200, time.time() - 7200))

    assert build_index(library, index.db_path, cover_cache=library / "c") == 4, "a stale lock should not block indexing"
    assert not lock.exists(), "lock should be removed after a successful build"


def test_metadata_pass_is_searchable_before_thumbnails(index: Index, library: Path, mocker):
    from kobolib.index import fill_thumbnails

    counts = []
    mocker.patch("kobolib.index.fill_thumbnails", side_effect=lambda db, cache: counts.append(Index(db).count()))

    build_index(library, index.db_path, cover_cache=library / "c")

    assert counts == [4], "the metadata pass should be committed before thumbnails start"


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
