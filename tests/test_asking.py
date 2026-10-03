import pytest

from kobold.asking import Asked, AskedLibrary, Embedded, author_folder_names, embed_summary, name_is_a_guess, summary
from tests.test_alfred import row


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"guessed": True, "format": "pdf"}, True),
        ({"guessed": True, "format": "epub", "title": "7_815203", "authors": ""}, True),
        ({"guessed": True, "format": "epub", "rel_path": "00_Inbox/Deep Work -- libgen.epub"}, True),
        ({"guessed": True, "format": "epub"}, False),
        ({"guessed": False, "format": "pdf"}, False),
        ({"guessed": True, "format": "pdf", "partial": True}, False),
    ],
)
def test_name_is_a_guess_for_opaque_or_noisy_names_without_metadata(overrides, expected):
    assert name_is_a_guess(row(**overrides)) is expected, f"{overrides} should {'' if expected else 'not '}be asked about"


@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        (Asked(books=3, suggested=2, none=1), "Asked about 3 books: 2 genres suggested, 1 without an answer"),
        (Asked(books=1, suggested=1), "Asked about 1 book: 1 genre suggested"),
        (Asked(books=4, suggested=1, none=1, skipped=2), "Asked about 4 books: 1 genre suggested, 1 without an answer, 2 skipped"),
        (Asked(books=2, none=2), "The model had no suggestions"),
        (Asked(books=2, skipped=2), "The model had no suggestions (2 skipped)"),
        (Asked(), "The model had no suggestions"),
        (AskedLibrary(books=1, suggested=2), "Asked about the author folders: 2 merges suggested"),
    ],
)
def test_summary_counts_what_came_back(asked, expected, mocker):
    mocker.patch("kobold.oracle.unreachable", return_value="")
    noun = "merge" if isinstance(asked, AskedLibrary) else "genre"

    assert summary(noun, asked) == expected, f"{asked} should be summarised as {expected!r}"


def test_summary_names_the_server_when_skips_came_from_a_dead_connection(mocker):
    mocker.patch("kobold.oracle.unreachable", return_value="http://127.0.0.1:8080")
    down = "Model not reachable at http://127.0.0.1:8080"

    assert summary("genre", Asked(books=2, skipped=2)) == down, "skips plus a note mean the server is down"
    assert summary("genre", Asked(books=2, none=2)) == "The model had no suggestions", "answers that came back are not a connection problem"


@pytest.mark.parametrize(
    ("embedded", "nothing_to_do", "expected"),
    [
        (Embedded(done=3), False, "Embedded 3 books"),
        (Embedded(done=1, skipped=2), False, "Embedded 1 book, skipped 2"),
        (Embedded(), True, "Every book is embedded"),
    ],
)
def test_embed_summary(embedded, nothing_to_do, expected):
    assert embed_summary(embedded, nothing_to_do) == expected, f"{embedded} should be summarised as {expected!r}"


def test_author_folder_names_are_the_distinct_surname_given_folders():
    delany, le_guin = "01_Fiction/Delany, Samuel R", "01_Fiction/Le Guin, Ursula"
    rows = [row(folder=delany), row(folder=delany), row(folder="00_Inbox"), row(folder=le_guin)]

    assert author_folder_names(rows) == ["Delany, Samuel R", "Le Guin, Ursula"], "folders named Surname, Given, once each, sorted"
