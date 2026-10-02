from pathlib import Path

import pytest

from kobolib.tags import Tag, TagStore, genre_from_folder
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
    store = TagStore(tmp_path / "tags.tsv")
    store.set("f1", Tag(genre="fiction/sci-fi", tags=["now", "bought"], rel_path="a.epub"))
    store.save()

    reloaded = TagStore(tmp_path / "tags.tsv").load()

    assert reloaded.get("f1") == Tag(genre="fiction/sci-fi", tags=["bought", "now"], rel_path="a.epub"), (
        "saved tags should load back unchanged"
    )


def test_missing_file_loads_empty(tmp_path: Path):
    assert TagStore(tmp_path / "none.tsv").load().get("f1") is None, "missing store should behave as empty"


def test_bootstrap_fills_only_unknown_genres(tmp_path: Path):
    store = TagStore(tmp_path / "tags.tsv")
    store.set("manual", Tag(genre="fiction/classics", rel_path="old.epub"))
    rows = [
        row(fingerprint="manual", folder="00_Inbox", rel_path="00_Inbox/x.epub"),
        row(fingerprint="auto", folder="02_NonFiction/Leadership", rel_path="02_NonFiction/Leadership/y.epub"),
        row(fingerprint="inbox", folder="00_Inbox", rel_path="00_Inbox/z.epub"),
    ]

    added = store.bootstrap(rows)

    assert added == 1, "only books in a genre folder without a tag should be added"
    assert store.genre_of(rows[0]) == "fiction/classics", "a manual genre should never be overwritten"
    assert store.genre_of(rows[1]) == "nonfiction/leadership", "genre should be derived from the folder"
    assert store.genre_of(rows[2]) == "", "inbox books stay unclassified"


def test_bootstrap_refreshes_last_seen_path(tmp_path: Path):
    store = TagStore(tmp_path / "tags.tsv")
    store.set("f1", Tag(genre="fiction/sci-fi", rel_path="old/place.epub"))

    store.bootstrap([row(fingerprint="f1", rel_path="new/place.epub", folder="new")])

    assert store.get("f1").rel_path == "new/place.epub", "bootstrap should record where the book was last seen"


def test_tags_are_sorted_and_unique(tmp_path: Path):
    store = TagStore(tmp_path / "tags.tsv")
    store.set("f1", Tag(tags=["now", "bought", "now"]))
    store.save()

    assert TagStore(tmp_path / "tags.tsv").load().get("f1").tags == ["bought", "now"], "tags should be stored sorted without duplicates"
