from dataclasses import dataclass
from pathlib import Path

import pytest

from kobold.store import TsvStore


@dataclass
class Note:
    text: str


class NoteStore(TsvStore):
    fields = ("fingerprint", "text")

    def to_fields(self, key: str, entry: Note) -> dict:
        return {"fingerprint": key, "text": entry.text}

    def from_fields(self, record: dict) -> tuple[str, Note]:
        return record["fingerprint"], Note(record["text"])


@pytest.fixture
def store(tmp_path: Path) -> NoteStore:
    return NoteStore(tmp_path / "notes.tsv")


def test_store_roundtrips_through_its_subclass_fields(store: NoteStore):
    store.set("f1", Note("hello\tworld"))
    store.set("f2", Note("Привіт"))
    store.save()

    reloaded = NoteStore(store.path).load()

    assert reloaded.get("f1") == Note("hello\tworld") and reloaded.get("f2") == Note("Привіт"), (
        "entries should load back unchanged, tabs included"
    )
    assert store.path.read_text(encoding="utf-8").splitlines()[0] == "fingerprint\ttext", "the header names the subclass fields"


def test_missing_file_loads_empty(store: NoteStore):
    assert store.load().get("f1") is None, "a store without a file behaves as empty"


def test_save_creates_the_parent_folder(tmp_path: Path):
    store = NoteStore(tmp_path / "deep" / "er" / "notes.tsv")
    store.set("f1", Note("x"))

    store.save()

    assert store.path.exists(), "saving should create missing folders"


def test_entries_are_saved_sorted_by_key(store: NoteStore):
    store.set("zz", Note("last"))
    store.set("aa", Note("first"))
    store.save()

    lines = store.path.read_text(encoding="utf-8").splitlines()[1:]
    assert [line.split("\t")[0] for line in lines] == ["aa", "zz"], "a stable order keeps the file diffable"


def test_prune_drops_entries_whose_fingerprint_is_gone(store: NoteStore):
    store.set("kept", Note("a"))
    store.set("gone", Note("b"))

    dropped = store.prune({"kept", "other"})

    assert dropped == 1 and store.get("gone") is None and store.get("kept") == Note("a"), "only entries for absent fingerprints go"
