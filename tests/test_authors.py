from pathlib import Path

import pytest

from kobold.authors import AuthorStore, obvious_groups
from kobold.naming import author_folder, canonical_name, destination, shelves
from tests.test_alfred import row


def test_store_roundtrips_aliases(tmp_path: Path):
    store = AuthorStore(tmp_path / "authors.tsv")
    store.learn({"Delany, Samuel": "Delany, Samuel R", "Night, Damon": "Knight, Damon"})
    store.save()

    assert AuthorStore(tmp_path / "authors.tsv").load().aliases == {
        "Delany, Samuel": "Delany, Samuel R",
        "Night, Damon": "Knight, Damon",
    }, "aliases survive a save and load"


def test_learning_follows_a_renamed_canonical(tmp_path: Path):
    store = AuthorStore(tmp_path / "authors.tsv")
    store.learn({"Delany, Samuel": "Delany, Samuel R"})

    store.learn({"Delany, Samuel R": "Delany, Samuel Ray"})

    assert store.aliases == {"Delany, Samuel": "Delany, Samuel Ray", "Delany, Samuel R": "Delany, Samuel Ray"}, (
        "an alias of an alias points at the final spelling"
    )


@pytest.mark.parametrize(
    "authors, aliases, folder",
    [
        ("Samuel Delany", {"Delany, Samuel": "Delany, Samuel R"}, "Delany, Samuel R"),
        ("Samuel R. Delany", {"Delany, Samuel R": "Delany, Samuel Ray"}, "Delany, Samuel Ray"),
        ("Samuel Delany", {}, "Delany, Samuel"),
        ("Cal Newport", {"Delany, Samuel": "Delany, Samuel R"}, "Newport, Cal"),
    ],
)
def test_author_folder_follows_aliases(authors, aliases, folder):
    assert author_folder(authors, aliases=aliases) == folder, f"{authors!r} with {aliases} should file under {folder!r}"


def test_canonical_name_and_destination_use_the_alias():
    book = row(authors="Samuel Delany", title="Babel-17", series="", year="2013")
    layout = shelves({"01_Fiction"}, aliases={"Delany, Samuel": "Delany, Samuel R"})

    assert canonical_name(book, aliases=layout.aliases) == "Delany, Samuel R - Babel-17 (2013).epub", (
        "the file name carries the canonical author"
    )
    assert destination(book, "fiction", layout, 0) == "01_Fiction/Delany, Samuel R/Delany, Samuel R - Babel-17 (2013).epub", (
        "the book goes to the canonical folder"
    )


@pytest.mark.parametrize(
    "counts, groups",
    [
        ({"Delany, Samuel": 4, "Delany, Samuel R": 30}, [{"canonical": "Delany, Samuel R", "aliases": ["Delany, Samuel"]}]),
        (
            {"Bayley, Barrington J": 3, "Bayley, Barrington John": 1},
            [{"canonical": "Bayley, Barrington John", "aliases": ["Bayley, Barrington J"]}],
        ),
        ({"Bentley, Jon": 1, "Bentley, Jon Louis": 1}, [{"canonical": "Bentley, Jon Louis", "aliases": ["Bentley, Jon"]}]),
        ({"Illich, Ivan": 1, "Illich, Ivan, 1926-2002": 1}, [{"canonical": "Illich, Ivan", "aliases": ["Illich, Ivan, 1926-2002"]}]),
        ({"Ann, Leckie": 1, "Leckie, Ann": 2}, [{"canonical": "Leckie, Ann", "aliases": ["Ann, Leckie"]}]),
        ({"Ann, Leckie": 1, "Leckie, Ann": 1}, []),
        ({"Smith, John": 2, "Smith, Jane": 2}, []),
        (
            {"Delany, Samuel R": 30, "Delany, Samuel": 4, "Delany, Sam": 1},
            [{"canonical": "Delany, Samuel R", "aliases": ["Delany, Samuel"]}],
        ),
    ],
)
def test_obvious_groups(counts, groups):
    assert obvious_groups(counts) == groups, f"{counts} should yield {groups}"
