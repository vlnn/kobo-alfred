import json
from pathlib import Path

import pytest

from kobolib.apply import Applied, apply, prune_empty_dirs, sidecar_of, undo
from kobolib.plan import Operation


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "card"
    (root / "00_Inbox").mkdir(parents=True)
    (root / "00_Inbox" / "a.epub").write_bytes(b"a")
    (root / "00_Inbox" / "a.sdr").mkdir()
    (root / "00_Inbox" / "a.sdr" / "metadata.epub.lua").write_text("return {}")
    (root / "00_Inbox" / "FSCK0000.000").write_bytes(b"")
    return root


def journal_lines(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines()]


def test_apply_moves_files_with_sidecar_and_journals(library: Path, tmp_path: Path):
    journal = tmp_path / "journal.jsonl"
    ops = [
        Operation("move", "00_Inbox/a.epub", "01_Fiction/Teague, Rowan/Teague, Rowan - Ash.epub", "relocate + rename"),
        Operation("trash", "00_Inbox/FSCK0000.000", "_trash/00_Inbox/FSCK0000.000", "junk"),
    ]

    result = apply(ops, library, journal)

    assert result == Applied(done=2, skipped=[]), "both operations should run"
    assert (library / "01_Fiction/Teague, Rowan/Teague, Rowan - Ash.epub").read_bytes() == b"a", "the book should be at its destination"
    assert (library / "01_Fiction/Teague, Rowan/Teague, Rowan - Ash.sdr/metadata.epub.lua").exists(), "the KOReader sidecar should travel with the book"
    assert (library / "_trash/00_Inbox/FSCK0000.000").exists(), "junk should be in _trash"
    assert [l["src"] for l in journal_lines(journal)] == ["00_Inbox/a.epub", "00_Inbox/FSCK0000.000"], "every move should be journaled"
    assert len({l["batch"] for l in journal_lines(journal)}) == 1, "one apply is one batch"


def test_apply_skips_missing_sources_and_occupied_destinations(library: Path, tmp_path: Path):
    (library / "taken.epub").write_bytes(b"t")
    ops = [
        Operation("move", "00_Inbox/none.epub", "x/none.epub", ""),
        Operation("move", "00_Inbox/a.epub", "taken.epub", ""),
        Operation("skip", "00_Inbox/a.epub", "y.epub", "collision"),
    ]

    result = apply(ops, library, tmp_path / "j.jsonl")

    assert result.done == 0, "nothing should move"
    assert [s.split(":")[0] for s in result.skipped] == ["00_Inbox/none.epub", "00_Inbox/a.epub"], "missing and occupied should be reported; skip lines ignored silently"
    assert (library / "00_Inbox/a.epub").exists(), "a blocked move leaves the source alone"


def test_undo_reverses_last_batch(library: Path, tmp_path: Path):
    journal = tmp_path / "journal.jsonl"
    apply([Operation("move", "00_Inbox/a.epub", "01_Fiction/a.epub", "")], library, journal)

    undone = undo(library, journal)

    assert undone == 1, "one move should be reversed"
    assert (library / "00_Inbox/a.epub").exists() and (library / "00_Inbox/a.sdr").is_dir(), "book and sidecar should be back"
    assert not (library / "01_Fiction").exists(), "emptied destination folders should be pruned"
    assert journal_lines(journal)[-1]["kind"] == "undo", "the undo itself should be journaled"


def test_undo_twice_redoes(library: Path, tmp_path: Path):
    journal = tmp_path / "journal.jsonl"
    apply([Operation("move", "00_Inbox/a.epub", "01_Fiction/a.epub", "")], library, journal)
    undo(library, journal)

    undo(library, journal)

    assert (library / "01_Fiction/a.epub").exists(), "undoing an undo reapplies the batch"


def test_undo_with_empty_journal_does_nothing(library: Path, tmp_path: Path):
    assert undo(library, tmp_path / "missing.jsonl") == 0, "no journal means nothing to undo"


def test_prune_empty_dirs_stops_at_root(tmp_path: Path):
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)

    prune_empty_dirs(deep, tmp_path)

    assert not (tmp_path / "a").exists() and tmp_path.exists(), "empty chain should be removed but never the root"


@pytest.mark.parametrize(
    "book, sidecar",
    [
        ("x/Book.epub", "x/Book.sdr"),
        ("x/Book.epub.part", "x/Book.epub.sdr"),
        ("x/Tom 1.0.pdf", "x/Tom 1.0.sdr"),
    ],
)
def test_sidecar_of(book, sidecar):
    assert sidecar_of(Path(book)) == Path(sidecar), f"{book} sidecar should be {sidecar}"
