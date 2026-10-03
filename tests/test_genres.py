from pathlib import Path

import pytest

from kobold.genres import GenreStore, genre_from_folder, without_author
from kobold.model import GenreEntry
from tests.test_alfred import row


@pytest.mark.parametrize(
    "folder, genre",
    [
        ("01_Fiction/01_Sci-Fi_Fantasy/Series/Rowan Teague", "fiction/sci-fi_fantasy"),
        ("01_Fiction/02_Adventure_Historical", "fiction/adventure_historical"),
        ("02_NonFiction/Tech_Programming", "nonfiction/tech_programming"),
        ("04_Reference", "reference"),
        ("01_Fiction", "fiction"),
        ("00_Inbox", ""),
        ("00_Inbox/2026", ""),
        ("00_Inbox/NOW", ""),
        ("99_Archives/LIBRARY/CODING", ""),
        ("99_Archives/System_Files", ""),
        (".", ""),
        ("programming/Dietrich, Erik", "programming"),
        ("reference/amini, kamran/Amini, Kamran", "reference"),
        ("fiction/Ві Кіланд, Пенелопа Ворд", "fiction"),
        ("music/Monteiro, Marcus", "music"),
        ("01_Fiction/Rowan Teague", "fiction"),
        ("games/go/Kato, Masao", "games/go"),
    ],
)
def test_genre_from_folder(folder, genre):
    assert genre_from_folder(folder) == genre, f"{folder!r} should map to genre {genre!r}"


@pytest.mark.parametrize(
    "stored, healed",
    [
        ("programming/dietrich, erik", "programming"),
        ("nonfiction/shea, ammon", "nonfiction"),
        ("fiction/sci-fi_fantasy", "fiction/sci-fi_fantasy"),
        ("games/go", "games/go"),
        ("", ""),
    ],
)
def test_without_author_drops_an_author_segment(stored, healed):
    assert without_author(stored) == healed, f"{stored!r} should heal to {healed!r}"


def test_bootstrap_heals_a_genre_that_swallowed_the_author(tmp_path: Path):
    store = GenreStore(tmp_path / "genres.tsv")
    store.set("fp1", GenreEntry(genre="programming/dietrich, erik", rel_path="x"))

    store.bootstrap([row(fingerprint="fp1", folder="programming/dietrich, erik/Dietrich, Erik")])

    assert store.genre_of(row(fingerprint="fp1")) == "programming", "a stored genre ending in an author name loses that segment"


def test_store_roundtrips(tmp_path: Path):
    store = GenreStore(tmp_path / "genres.tsv")
    store.set("f1", GenreEntry(genre="fiction/sci-fi", rel_path="a.epub"))
    store.save()

    reloaded = GenreStore(tmp_path / "genres.tsv").load()

    assert reloaded.get("f1") == GenreEntry(genre="fiction/sci-fi", rel_path="a.epub"), "saved genres should load back unchanged"


def test_store_writes_only_genre_columns(tmp_path: Path):
    store = GenreStore(tmp_path / "genres.tsv")
    store.set("f1", GenreEntry(genre="fiction/sci-fi", rel_path="a.epub"))
    store.save()

    header = (tmp_path / "genres.tsv").read_text(encoding="utf-8").splitlines()[0]
    assert header.split("\t") == ["fingerprint", "genre", "rel_path"], "the store should write these columns only"


def test_missing_file_loads_empty(tmp_path: Path):
    assert GenreStore(tmp_path / "none.tsv").load().get("f1") is None, "missing store should behave as empty"


def test_bootstrap_fills_only_unknown_genres(tmp_path: Path):
    store = GenreStore(tmp_path / "genres.tsv")
    store.set("manual", GenreEntry(genre="fiction/classics", rel_path="old.epub"))
    rows = [
        row(fingerprint="manual", folder="00_Inbox", rel_path="00_Inbox/x.epub"),
        row(fingerprint="auto", folder="02_NonFiction/Leadership", rel_path="02_NonFiction/Leadership/y.epub"),
        row(fingerprint="inbox", folder="00_Inbox", rel_path="00_Inbox/z.epub"),
    ]

    added = store.bootstrap(rows)

    assert added == 1, "only books in a genre folder without a genre should be added"
    assert store.genre_of(rows[0]) == "fiction/classics", "a manual genre should never be overwritten"
    assert store.genre_of(rows[1]) == "nonfiction/leadership", "genre should be derived from the folder"
    assert store.genre_of(rows[2]) == "", "inbox books stay unclassified"


def test_bootstrap_refreshes_last_seen_path(tmp_path: Path):
    store = GenreStore(tmp_path / "genres.tsv")
    store.set("f1", GenreEntry(genre="fiction/sci-fi", rel_path="old/place.epub"))

    store.bootstrap([row(fingerprint="f1", rel_path="new/place.epub", folder="new")])

    assert store.get("f1").rel_path == "new/place.epub", "bootstrap should record where the book was last seen"


def test_bootstrap_carries_the_genre_over_to_a_new_fingerprint(tmp_path: Path):
    store = GenreStore(tmp_path / "genres.tsv")
    store.set("old", GenreEntry(genre="fiction/spy", rel_path="01_Fiction/x.epub"))
    rows = [row(fingerprint="new", folder="01_Fiction", rel_path="01_Fiction/x.epub")]

    store.bootstrap(rows)

    assert store.get("new") == GenreEntry(genre="fiction/spy", rel_path="01_Fiction/x.epub"), (
        "a book whose fingerprint changed should keep its genre by path"
    )
    assert store.get("old") is None, "the stale fingerprint should be dropped"


def test_bootstrap_keeps_entries_for_moved_and_absent_books(tmp_path: Path):
    store = GenreStore(tmp_path / "genres.tsv")
    store.set("moved", GenreEntry(genre="fiction/spy", rel_path="00_Inbox/a.epub"))
    store.set("absent", GenreEntry(genre="reference", rel_path="04_Reference/gone.epub"))
    rows = [row(fingerprint="moved", folder="01_Fiction", rel_path="01_Fiction/a.epub")]

    store.bootstrap(rows)

    assert store.get("moved").rel_path == "01_Fiction/a.epub", "a known fingerprint follows the book to its new path"
    assert store.get("absent") == GenreEntry(genre="reference", rel_path="04_Reference/gone.epub"), "an unmounted book's genre is kept"
