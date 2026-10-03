from pathlib import Path

import pytest

from kobolib.suggestions import ANY_EVIDENCE, SuggestionStore


@pytest.fixture
def store(tmp_path: Path) -> SuggestionStore:
    return SuggestionStore(tmp_path / "oracle.tsv")


def test_answers_roundtrip_per_fingerprint_and_question(store: SuggestionStore):
    store.set("f1", "genre", {"genre": "fiction/sci-fi"}, "h1")
    store.set("f1", "name", {"title": "Nova", "authors": ["Delany, Samuel R."], "confident": True}, "h2")
    store.save()

    reloaded = SuggestionStore(store.path).load()

    assert reloaded.get("f1", "genre").answer == {"genre": "fiction/sci-fi"}, "the genre answer should load back as JSON"
    assert reloaded.get("f1", "name").answer["authors"] == ["Delany, Samuel R."], "the name answer should load back as JSON"
    assert reloaded.get("f1", "genre").asked_at, "the store should record when a question was asked"
    assert store.path.read_text(encoding="utf-8").splitlines()[0] == "fingerprint\tquestion\tanswer\tevidence_hash\tasked_at", (
        "the columns are the ones the design names"
    )


@pytest.mark.parametrize(
    "stored, asked, stale",
    [
        (None, "h1", True),
        ("h1", "h1", False),
        ("h1", "h2", True),
        (ANY_EVIDENCE, "h2", False),
    ],
)
def test_a_suggestion_is_stale_when_the_evidence_changed(store: SuggestionStore, stored, asked, stale):
    if stored is not None:
        store.set("f1", "genre", {"genre": "none"}, stored)

    assert store.stale("f1", "genre", asked) is stale, f"stored hash {stored!r} against evidence {asked!r} should be stale={stale}"


def test_dismiss_silences_every_question_for_the_book(store: SuggestionStore):
    store.set("f1", "genre", {"genre": "fiction/spy"}, "h1")

    store.dismiss("f1")

    assert store.get("f1", "genre").answer == {} and store.get("f1", "name").answer == {}, "dismissed questions hold no suggestion"
    assert not store.stale("f1", "genre", "anything"), "a dismissed question is not asked again whatever the evidence"


def test_drop_forgets_one_question(store: SuggestionStore):
    store.set("f1", "genre", {"genre": "fiction/spy"}, "h1")
    store.set("f1", "name", {"title": "X", "authors": [], "confident": True}, "h1")

    store.drop("f1", "genre")

    assert store.get("f1", "genre") is None and store.get("f1", "name") is not None, "only the one question goes"


def test_prune_keeps_library_wide_answers(store: SuggestionStore):
    store.set("gone", "genre", {"genre": "none"}, "h1")
    store.set("kept", "genre", {"genre": "none"}, "h1")
    store.set("*", "authors", {"groups": []}, "h2")

    store.prune({"kept"})

    assert store.get("gone", "genre") is None, "a book that left the index takes its answers with it"
    assert store.get("kept", "genre") and store.get("*", "authors"), "answers about present books and about the whole library stay"


def test_answers_for_a_question_leave_out_empty_ones(store: SuggestionStore):
    store.set("a", "genre", {"genre": "fiction/spy"}, "h")
    store.set("b", "genre", {"genre": "none"}, "h")
    store.dismiss("c")

    assert store.answers("genre") == {"a": {"genre": "fiction/spy"}, "b": {"genre": "none"}}, (
        "answers are keyed by fingerprint; dismissed ones are empty"
    )
