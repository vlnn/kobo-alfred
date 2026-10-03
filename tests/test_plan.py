from pathlib import Path

import pytest

from kobold.genres import GenreStore
from kobold.model import Finding, GenreEntry, Operation
from kobold.plan import plan, prefer
from tests.test_lint import named


def store_with(tmp_path: Path, **genres) -> GenreStore:
    store = GenreStore(tmp_path / "t.tsv")
    for fingerprint, genre in genres.items():
        store.set(fingerprint, GenreEntry(genre=genre))
    return store


def ops(result: list[Operation]) -> list[tuple[str, str, str]]:
    return [(o.kind, o.src, o.dst) for o in result]


@pytest.mark.parametrize(
    "candidates, winner",
    [
        ([("a.fb2", "fb2", "2001"), ("a.epub", "epub", "2001")], "a.epub"),
        ([("a.pdf", "pdf", "2020"), ("a.fb2", "fb2", "1999")], "a.fb2"),
        ([("a.epub", "epub", "2001"), ("b.epub", "epub", "2014")], "b.epub"),
        ([("00_Inbox/a.epub", "epub", ""), ("01_Fiction/a.epub", "epub", "")], "01_Fiction/a.epub"),
    ],
)
def test_prefer_picks_the_best_copy(candidates, winner):
    rows = [named(Path(p).name, folder=str(Path(p).parent) or "x", format=f, year=y) for p, f, y in candidates]
    for r, (p, _, _) in zip(rows, candidates):
        r.rel_path = p
    assert prefer(rows).rel_path == winner, f"{[c[0] for c in candidates]} should keep {winner}"


def test_junk_goes_to_trash(tmp_path):
    findings = [Finding("junk", "FSCK0000.000: not a book", ["00_Inbox/FSCK0000.000"])]
    result = plan([], findings, store_with(tmp_path))
    assert ops(result) == [("trash", "00_Inbox/FSCK0000.000", "_trash/00_Inbox/FSCK0000.000")], (
        "junk should move to _trash keeping its path"
    )


def test_exact_duplicates_keep_one_trash_the_rest(tmp_path):
    rows = [
        named("hlaskvyl.epub", folder="00_Inbox/bought", fingerprint="same"),
        named("hlaskvyl.epub", folder="00_Inbox/NOW", fingerprint="same"),
    ]
    findings = [Finding("exact_duplicate", "x", [r.rel_path for r in rows])]

    result = [o for o in plan(rows, findings, store_with(tmp_path)) if o.kind == "trash"]

    assert ops(result) == [("trash", "00_Inbox/NOW/hlaskvyl.epub", "_trash/00_Inbox/NOW/hlaskvyl.epub")], (
        "identical copies are trash, the first path survives"
    )


def test_title_duplicates_move_losers_to_dups(tmp_path):
    rows = [
        named("Verdigris.fb2", title="Verdigris", format="fb2", fingerprint="a"),
        named("Verdigris.epub", title="Verdigris", format="epub", fingerprint="b"),
    ]
    findings = [Finding("title_duplicate", "x", [r.rel_path for r in rows])]

    result = [o for o in plan(rows, findings, store_with(tmp_path)) if o.kind == "dups"]

    assert ops(result) == [("dups", "00_Inbox/Verdigris.fb2", "_dups/00_Inbox/Verdigris.fb2")], (
        "the less preferred format goes to _dups for review"
    )


def test_classified_books_move_to_their_destination(tmp_path):
    rows = [
        named(
            "x.epub",
            folder="01_Fiction/01_Sci-Fi_Fantasy/Standalone",
            title="Ash",
            authors="Rowan Teague",
            series="",
            year="2011",
            fingerprint="f",
        ),
        named("y.epub", folder="00_Inbox", title="Ember", authors="Rowan Teague", series="", year="", fingerprint="u"),
    ]
    store = store_with(tmp_path, f="fiction/sci-fi_fantasy")

    result = plan(rows, [], store)

    assert ops(result) == [
        (
            "move",
            "01_Fiction/01_Sci-Fi_Fantasy/Standalone/x.epub",
            "01_Fiction/01_Sci-Fi_Fantasy/Teague, Rowan/Teague, Rowan - Ash (2011).epub",
        )
    ], "classified books move; unclassified wait"
    assert result[0].reason == "relocate + rename", "reason should say what changes"


def test_book_already_in_place_is_not_moved(tmp_path):
    folder = "01_Fiction/01_Sci-Fi_Fantasy/Teague, Rowan"
    rows = [
        named(
            "Teague, Rowan - Ash (2011).epub", folder=folder, title="Ash", authors="Rowan Teague", series="", year="2011", fingerprint="f"
        )
    ]

    assert plan(rows, [], store_with(tmp_path, f="fiction/sci-fi_fantasy")) == [], "a correctly placed book yields no operation"


def test_series_folder_only_when_several_books(tmp_path):
    common = {"folder": "00_Inbox", "authors": "Rowan Teague", "series": "Grey Tide", "year": ""}
    rows = [
        named("a.epub", title="Ash", series_index="1", fingerprint="a", **common),
        named("b.epub", title="Ember", series_index="2", fingerprint="b", **common),
    ]
    store = store_with(tmp_path, a="fiction", b="fiction")

    dsts = [o.dst for o in plan(rows, [], store)]

    assert all("/Grey Tide/" in d for d in dsts), "two books of a series get a series folder"


def test_partials_and_duplicate_losers_are_not_relocated(tmp_path):
    rows = [
        named("p.epub.part", partial=True, fingerprint="p"),
        named("loser.fb2", title="Verdigris", format="fb2", fingerprint="l"),
        named("winner.epub", title="Verdigris", format="epub", fingerprint="w"),
    ]
    findings = [Finding("title_duplicate", "x", ["00_Inbox/loser.fb2", "00_Inbox/winner.epub"])]
    store = store_with(tmp_path, p="fiction", l="fiction", w="fiction")

    result = plan(rows, findings, store)

    assert [o.kind for o in result if o.src.endswith("loser.fb2")] == ["dups"], "a duplicate loser gets exactly one operation"
    assert not [o for o in result if o.src.endswith(".part")], "partial downloads are left alone"


def test_books_without_author_stay_where_they_are(tmp_path):
    rows = [named("Хроніки 2.fb2", folder="01_Fiction/01_Sci-Fi_Fantasy/Series/Amber", title="Хроніки 2", authors="", fingerprint="f")]

    assert plan(rows, [], store_with(tmp_path, f="fiction/sci-fi_fantasy")) == [], (
        "without an author there is no destination worth moving to"
    )


def test_destination_collisions_are_reported_not_planned(tmp_path):
    common = {"folder": "00_Inbox", "title": "Ash", "authors": "Rowan Teague", "series": "", "year": "2011"}
    rows = [named("one.epub", fingerprint="a", **common), named("two.epub", fingerprint="b", **common)]
    store = store_with(tmp_path, a="fiction", b="fiction")

    result = plan(rows, [], store)

    assert [o.kind for o in result] == ["move", "skip"], "the second book cannot take the same destination"
    assert "one.epub" in result[1].reason, "the skip should name the conflicting source"


def test_series_counted_across_article_variants(tmp_path):
    common = {"folder": "00_Inbox", "authors": "Rowan Teague", "year": ""}
    rows = [
        named("a.epub", title="Ash", series="Grey Tide", series_index="1", fingerprint="a", **common),
        named("b.epub", title="Ember", series="The Grey Tide", series_index="2", fingerprint="b", **common),
    ]

    dsts = [o.dst for o in plan(rows, [], store_with(tmp_path, a="fiction", b="fiction"))]

    assert all("/Grey Tide/" in d for d in dsts), "both books belong to one series folder named without the article"


def test_relocation_for_one_book_matches_the_plan(tmp_path):
    from kobold.plan import relocation

    rows = [
        named("Deep Work.epub", title="Deep Work", authors="Cal Newport", series="", year="", fingerprint="a"),
        named("Other.epub", folder="01_Fiction", title="Other", authors="Someone", series="", year="", fingerprint="b"),
    ]
    store = store_with(tmp_path, a="fiction", b="fiction")

    assert relocation(rows[0], rows, store) == plan(rows, [], store)[0], "a single book's move should be what the plan would do"
    assert relocation(rows[1], rows, store) == Operation(
        "move", "01_Fiction/Other.epub", "01_Fiction/Someone/Someone - Other.epub", "relocate + rename"
    ), "the move should be computed against the whole library's folders"


def test_relocation_reports_a_taken_destination(tmp_path):
    from kobold.plan import relocation

    rows = [
        named("Dup.epub", title="Dup", authors="Someone", series="", year="", fingerprint="a"),
        named("Someone - Dup.epub", folder="01_Fiction/Someone", title="Dup", authors="Someone", series="", year="", fingerprint="b"),
    ]
    store = store_with(tmp_path, a="fiction", b="fiction")

    assert relocation(rows[0], rows, store).kind == "skip", "a destination held by another book is a skip, not a move"
    assert relocation(rows[1], rows, store) is None, "a book already at its destination needs nothing"


def test_relocation_is_none_for_books_that_stay(tmp_path):
    from kobold.plan import relocation

    rows = [named("x.epub", title="x", authors="", fingerprint="a"), named("y.epub.part", partial=True, authors="A B", fingerprint="b")]
    store = store_with(tmp_path, a="fiction", b="fiction")

    assert [relocation(r, rows, store) for r in rows] == [None, None], "no author or a partial download never moves"


def test_a_genre_that_swallowed_the_author_unnests_the_book(tmp_path):
    rows = [
        named(
            "Amini, Kamran - Extreme C (2019).epub",
            folder="reference/amini, kamran/Amini, Kamran",
            title="Extreme C",
            authors="Kamran Amini",
            series="",
            year="2019",
            fingerprint="f",
        )
    ]
    store = store_with(tmp_path, f="reference/amini, kamran")
    store.bootstrap(rows)

    result = plan(rows, [], store)

    assert ops(result) == [
        (
            "move",
            "reference/amini, kamran/Amini, Kamran/Amini, Kamran - Extreme C (2019).epub",
            "reference/Amini, Kamran/Amini, Kamran - Extreme C (2019).epub",
        )
    ], "the author folder sits directly under the genre, not under a lowercase copy of itself"
