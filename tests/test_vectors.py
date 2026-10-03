from pathlib import Path

import pytest

from kobolib.vectors import NEIGHBOURS, VectorStore, cosine
from tests.test_alfred import row


@pytest.fixture
def store(tmp_path: Path) -> VectorStore:
    return VectorStore(tmp_path / "vectors.db")


@pytest.mark.parametrize(
    "a, b, expected",
    [
        ([1.0, 0.0], [1.0, 0.0], 1.0),
        ([1.0, 0.0], [0.0, 1.0], 0.0),
        ([1.0, 0.0], [-1.0, 0.0], -1.0),
        ([3.0, 4.0], [6.0, 8.0], 1.0),
        ([1.0, 1.0], [1.0, 0.0], 0.7071),
        ([0.0, 0.0], [1.0, 0.0], 0.0),
    ],
)
def test_cosine(a, b, expected):
    assert cosine(a, b) == pytest.approx(expected, abs=1e-4), f"cosine of {a} and {b} should be {expected}"


def test_vectors_roundtrip_per_model(store: VectorStore):
    store.put("m1", "f1", [0.0, 3.0, 4.0])
    store.put("m2", "f1", [1.0, 0.0, 0.0])

    assert list(store.get("m1", "f1")) == pytest.approx([0.0, 0.6, 0.8]), "a vector is stored normalised, under its model"
    assert list(store.get("m2", "f1")) == [1.0, 0.0, 0.0], "another model's vector for the same book is separate"
    assert store.get("m3", "f1") is None and store.count("m1") == 1 and store.count("m3") == 0, "counts are per model"


def test_an_empty_store_reads_as_empty(store: VectorStore):
    assert store.count("m") == 0 and store.get("m", "x") is None and store.neighbours("m", "x") == [], "no file, no vectors"
    assert not store.path.exists(), "reading creates nothing"


def test_neighbours_are_ranked_by_similarity(store: VectorStore):
    store.put("m", "seed", [1.0, 0.0])
    store.put("m", "far", [0.0, 1.0])
    store.put("m", "near", [1.0, 0.1])
    store.put("m", "opposite", [-1.0, 0.0])

    others = [fp for fp, _ in store.neighbours("m", "seed")]
    assert others == ["near", "far", "opposite"], "nearest first; the book itself is left out"
    assert [round(s, 2) for _, s in store.neighbours("m", "seed")] == [1.0, 0.0, -1.0], "scores are cosines"


def test_a_later_vector_joins_the_lists_of_earlier_books(store: VectorStore):
    store.put("m", "a", [1.0, 0.0])
    store.put("m", "b", [0.0, 1.0])
    store.put("m", "c", [1.0, 0.05])

    assert [fp for fp, _ in store.neighbours("m", "a")] == ["c", "b"], "a's list is updated when c arrives, not only c's own"


def test_lists_keep_the_nearest_twenty(store: VectorStore):
    for i in range(25):
        store.put("m", f"f{i}", [1.0, i / 100])

    assert len(store.neighbours("m", "f0")) == NEIGHBOURS == 20, "a list holds at most twenty"
    assert [fp for fp, _ in store.neighbours("m", "f0")][:3] == ["f1", "f2", "f3"], "the nearest ones"


def test_replacing_a_vector_moves_it_in_every_list(store: VectorStore):
    store.put("m", "a", [1.0, 0.0])
    store.put("m", "b", [0.0, 1.0])
    store.put("m", "c", [1.0, 0.0])

    store.put("m", "c", [0.0, 1.0])

    assert [fp for fp, _ in store.neighbours("m", "a")] == ["b", "c"], "c dropped to the end of a's list"
    assert [fp for fp, _ in store.neighbours("m", "b")] == ["c", "a"], "and rose in b's"
    assert [fp for fp, _ in store.neighbours("m", "c")] == ["b", "a"], "its own list is recomputed"


def test_missing_lists_rows_without_a_vector_for_the_model(store: VectorStore):
    store.put("m", "f1", [1.0, 0.0])
    rows = [row(fingerprint="f1"), row(fingerprint="f2", rel_path="b.epub")]

    assert [r.fingerprint for r in store.missing("m", rows)] == ["f2"], "only the unembedded book is missing"
    assert [r.fingerprint for r in store.missing("other", rows)] == ["f1", "f2"], "another model has nothing yet"


def test_prune_drops_books_that_left(store: VectorStore):
    store.put("m", "kept", [1.0, 0.0])
    store.put("m", "gone", [0.0, 1.0])

    store.prune({"kept"})

    assert store.count("m") == 1 and store.neighbours("m", "kept") == [], "the vector and every mention of it go"
