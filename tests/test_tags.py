from pathlib import Path

import pytest

from kobolib.model import Tag
from kobolib.tags import GenreStore, genre_from_folder
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
    ],
)
def test_genre_from_folder(folder, genre):
    assert genre_from_folder(folder) == genre, f"{folder!r} should map to genre {genre!r}"


def test_store_roundtrips(tmp_path: Path):
    store = GenreStore(tmp_path / "genres.tsv")
    store.set("f1", Tag(genre="fiction/sci-fi", rel_path="a.epub"))
    store.save()

    reloaded = GenreStore(tmp_path / "genres.tsv").load()

    assert reloaded.get("f1") == Tag(genre="fiction/sci-fi", rel_path="a.epub"), "saved genres should load back unchanged"


def test_store_writes_only_genre_columns(tmp_path: Path):
    store = GenreStore(tmp_path / "genres.tsv")
    store.set("f1", Tag(genre="fiction/sci-fi", rel_path="a.epub"))
    store.save()

    header = (tmp_path / "genres.tsv").read_text(encoding="utf-8").splitlines()[0]
    assert header.split("\t") == ["fingerprint", "genre", "rel_path"], "the store should no longer carry a tags column"


LEGACY = "fingerprint\tgenre\ttags\trel_path\nf1\tfiction/spy\tbought,now\t01_Fiction/x.epub\n"


def test_store_reads_a_legacy_tags_file_when_genres_file_is_missing(tmp_path: Path):
    (tmp_path / "tags.tsv").write_text(LEGACY, encoding="utf-8")

    store = GenreStore(tmp_path / "genres.tsv").load()

    assert store.get("f1") == Tag(genre="fiction/spy", rel_path="01_Fiction/x.epub"), "an old tags.tsv should seed the genres, tags ignored"


def test_store_saves_legacy_entries_to_the_new_file(tmp_path: Path):
    (tmp_path / "tags.tsv").write_text(LEGACY, encoding="utf-8")
    GenreStore(tmp_path / "genres.tsv").load().save()

    (tmp_path / "tags.tsv").write_text("fingerprint\tgenre\ttags\trel_path\n", encoding="utf-8")

    assert GenreStore(tmp_path / "genres.tsv").load().genre_of(row(fingerprint="f1")) == "fiction/spy", (
        "once genres.tsv exists the old tags.tsv should not be read again"
    )


def test_store_prefers_genres_file_over_legacy_tags_file(tmp_path: Path):
    (tmp_path / "tags.tsv").write_text(LEGACY, encoding="utf-8")
    (tmp_path / "genres.tsv").write_text("fingerprint\tgenre\trel_path\nf1\treference\tr.epub\n", encoding="utf-8")

    assert GenreStore(tmp_path / "genres.tsv").load().get("f1").genre == "reference", "genres.tsv wins over a leftover tags.tsv"


def test_missing_file_loads_empty(tmp_path: Path):
    assert GenreStore(tmp_path / "none.tsv").load().get("f1") is None, "missing store should behave as empty"


def test_bootstrap_fills_only_unknown_genres(tmp_path: Path):
    store = GenreStore(tmp_path / "genres.tsv")
    store.set("manual", Tag(genre="fiction/classics", rel_path="old.epub"))
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
    store.set("f1", Tag(genre="fiction/sci-fi", rel_path="old/place.epub"))

    store.bootstrap([row(fingerprint="f1", rel_path="new/place.epub", folder="new")])

    assert store.get("f1").rel_path == "new/place.epub", "bootstrap should record where the book was last seen"


def test_bootstrap_carries_the_genre_over_to_a_new_fingerprint(tmp_path: Path):
    store = GenreStore(tmp_path / "genres.tsv")
    store.set("old", Tag(genre="fiction/spy", rel_path="01_Fiction/x.epub"))
    rows = [row(fingerprint="new", folder="01_Fiction", rel_path="01_Fiction/x.epub")]

    store.bootstrap(rows)

    assert store.get("new") == Tag(genre="fiction/spy", rel_path="01_Fiction/x.epub"), (
        "a book whose fingerprint changed should keep its genre by path"
    )
    assert store.get("old") is None, "the stale fingerprint should be dropped"


def test_bootstrap_keeps_entries_for_moved_and_absent_books(tmp_path: Path):
    store = GenreStore(tmp_path / "genres.tsv")
    store.set("moved", Tag(genre="fiction/spy", rel_path="00_Inbox/a.epub"))
    store.set("absent", Tag(genre="reference", rel_path="04_Reference/gone.epub"))
    rows = [row(fingerprint="moved", folder="01_Fiction", rel_path="01_Fiction/a.epub")]

    store.bootstrap(rows)

    assert store.get("moved").rel_path == "01_Fiction/a.epub", "a known fingerprint follows the book to its new path"
    assert store.get("absent") == Tag(genre="reference", rel_path="04_Reference/gone.epub"), "an unmounted book's genre is kept"
