import json
import unicodedata
from pathlib import Path

import pytest

from kobolib.apply import Applied, apply, prune_empty_dirs, undo
from kobolib.koreader import sidecar_of
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
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_apply_moves_files_with_sidecar_and_journals(library: Path, tmp_path: Path):
    journal = tmp_path / "journal.jsonl"
    ops = [
        Operation("move", "00_Inbox/a.epub", "01_Fiction/Teague, Rowan/Teague, Rowan - Ash.epub", "relocate + rename"),
        Operation("trash", "00_Inbox/FSCK0000.000", "_trash/00_Inbox/FSCK0000.000", "junk"),
    ]

    result = apply(ops, library, journal)

    assert result == Applied(done=2, skipped=[]), "both operations should run"
    assert (library / "01_Fiction/Teague, Rowan/Teague, Rowan - Ash.epub").read_bytes() == b"a", "the book should be at its destination"
    assert (library / "01_Fiction/Teague, Rowan/Teague, Rowan - Ash.sdr/metadata.epub.lua").exists(), (
        "the KOReader sidecar should travel with the book"
    )
    assert (library / "_trash/00_Inbox/FSCK0000.000").exists(), "junk should be in _trash"
    assert [line["src"] for line in journal_lines(journal)] == ["00_Inbox/a.epub", "00_Inbox/FSCK0000.000"], (
        "every move should be journaled"
    )
    assert len({line["batch"] for line in journal_lines(journal)}) == 1, "one apply is one batch"


def test_apply_skips_missing_sources_and_occupied_destinations(library: Path, tmp_path: Path):
    (library / "taken.epub").write_bytes(b"t")
    ops = [
        Operation("move", "00_Inbox/none.epub", "x/none.epub", ""),
        Operation("move", "00_Inbox/a.epub", "taken.epub", ""),
        Operation("skip", "00_Inbox/a.epub", "y.epub", "collision"),
    ]

    result = apply(ops, library, tmp_path / "j.jsonl")

    assert result.done == 0, "nothing should move"
    assert [s.split(":")[0] for s in result.skipped] == ["00_Inbox/none.epub", "00_Inbox/a.epub"], (
        "missing and occupied should be reported; skip lines ignored silently"
    )
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


def test_apply_fixes_koreader_collections(library: Path, tmp_path: Path):
    settings = library / ".adds/koreader/settings"
    settings.mkdir(parents=True)
    (settings / "collection.lua").write_text('return { ["/mnt/sd/00_Inbox/a.epub"] = 1 }')

    apply([Operation("move", "00_Inbox/a.epub", "01_Fiction/a.epub", "")], library, tmp_path / "j.jsonl")

    assert "/mnt/sd/01_Fiction/a.epub" in (settings / "collection.lua").read_text(), "collections should point at the new path"


def test_apply_finds_sources_whose_names_are_not_nfc(tmp_path):
    root = tmp_path / "lib"
    nfd = unicodedata.normalize("NFD", "Čapek - Válka.epub")
    (root / "inbox").mkdir(parents=True)
    (root / "inbox" / nfd).write_bytes(b"book")
    op = Operation("move", "inbox/Čapek - Válka.epub", "fiction/Čapek, Karel/Čapek - Válka.epub", "relocate")

    result = apply([op], root, tmp_path / "journal.jsonl")

    assert result.done == 1 and not result.skipped, "an NFD-named file must be found by its NFC plan path"
    assert (root / "fiction" / "Čapek, Karel" / "Čapek - Válka.epub").exists(), "the book should have moved"


def test_apply_sees_an_nfd_named_file_at_the_destination(tmp_path):
    root = tmp_path / "lib"
    nfd = unicodedata.normalize("NFD", "Čapek - Válka.epub")
    (root / "inbox").mkdir(parents=True)
    (root / "fiction").mkdir()
    (root / "inbox" / "Čapek - Válka.epub").write_bytes(b"book")
    (root / "fiction" / nfd).write_bytes(b"other")
    op = Operation("move", "inbox/Čapek - Válka.epub", "fiction/Čapek - Válka.epub", "relocate")

    result = apply([op], root, tmp_path / "journal.jsonl")

    assert result.skipped == ["inbox/Čapek - Válka.epub: destination exists, different content"], (
        "a differently normalized file at the destination still blocks the move"
    )


def test_identical_source_is_removed_when_destination_exists(library: Path, tmp_path: Path):
    journal = tmp_path / "journal.jsonl"
    (library / "kept.epub").write_bytes(b"a")

    result = apply([Operation("move", "00_Inbox/a.epub", "kept.epub", "")], library, journal)

    assert result == Applied(done=1, skipped=[]), "a byte-identical source is cleaned up, not skipped"
    assert not (library / "00_Inbox" / "a.epub").exists(), "the redundant copy should be gone"
    assert (library / "kept.epub").read_bytes() == b"a", "the kept file is untouched"
    assert journal_lines(journal)[0]["kind"] == "delete", "the removal should be journaled as a delete"


def test_empty_source_folder_is_removed_when_destination_exists(library: Path, tmp_path: Path):
    (library / "00_Inbox" / "Empty").mkdir()
    (library / "_trash" / "00_Inbox" / "Empty").mkdir(parents=True)

    result = apply([Operation("trash", "00_Inbox/Empty", "_trash/00_Inbox/Empty", "junk")], library, tmp_path / "j.jsonl")

    assert result.done == 1 and not (library / "00_Inbox" / "Empty").exists(), "an empty folder already trashed before is simply removed"


def test_different_content_at_destination_still_skips(library: Path, tmp_path: Path):
    (library / "taken.epub").write_bytes(b"different")

    result = apply([Operation("move", "00_Inbox/a.epub", "taken.epub", "")], library, tmp_path / "j.jsonl")

    assert result.skipped == ["00_Inbox/a.epub: destination exists, different content"], "a different file at the destination needs a human"
    assert (library / "00_Inbox" / "a.epub").exists(), "the source is left alone"


def test_undo_restores_deleted_copy_and_folder(library: Path, tmp_path: Path):
    journal = tmp_path / "journal.jsonl"
    (library / "kept.epub").write_bytes(b"a")
    (library / "00_Inbox" / "Empty").mkdir()
    (library / "_trash" / "00_Inbox" / "Empty").mkdir(parents=True)
    apply(
        [
            Operation("move", "00_Inbox/a.epub", "kept.epub", ""),
            Operation("trash", "00_Inbox/Empty", "_trash/00_Inbox/Empty", "junk"),
        ],
        library,
        journal,
    )

    assert undo(library, journal) == 2, "both deletions should be undone"
    assert (library / "00_Inbox" / "a.epub").read_bytes() == b"a", "the deleted copy comes back from the kept file"
    assert (library / "00_Inbox" / "Empty").is_dir(), "the deleted folder is recreated"
    assert undo(library, journal) == 2 and not (library / "00_Inbox" / "a.epub").exists(), "undoing the undo deletes again"


def test_case_only_folder_rename_renames_the_folder_in_place(tmp_path: Path):
    root = tmp_path / "card"
    old = root / "Wolfe, Gene" / "Book of The New Sun"
    old.mkdir(parents=True)
    (old / "Wolfe, Gene - Claw.fb2").write_bytes(b"claw")
    (old / "Wolfe, Gene - Claw.sdr").mkdir()
    op = Operation(
        "move",
        "Wolfe, Gene/Book of The New Sun/Wolfe, Gene - Claw.fb2",
        "Wolfe, Gene/Book of the New Sun/Wolfe, Gene - Claw.fb2",
        "relocate",
    )

    result = apply([op], root, tmp_path / "j.jsonl")

    assert result == Applied(done=1, skipped=[]), "a case-only folder rename is a real operation"
    assert (root / "Wolfe, Gene" / "Book of the New Sun" / "Wolfe, Gene - Claw.fb2").read_bytes() == b"claw", (
        "the book is under the respelled folder, intact"
    )
    assert (root / "Wolfe, Gene" / "Book of the New Sun" / "Wolfe, Gene - Claw.sdr").is_dir(), "the sidecar stays beside it"
    assert not old.exists(), "the old spelling of the folder is gone"


def test_case_only_file_rename_keeps_the_file(tmp_path: Path):
    root = tmp_path / "card"
    (root / "Chess").mkdir(parents=True)
    (root / "Chess" / "БРИНИХ - Шахмати.fb2").write_bytes(b"chess")
    op = Operation("move", "Chess/БРИНИХ - Шахмати.fb2", "Chess/Бриних - Шахмати.fb2", "rename")

    result = apply([op], root, tmp_path / "j.jsonl")

    assert result.done == 1, "a case-only file rename should be applied"
    assert (root / "Chess" / "Бриних - Шахмати.fb2").read_bytes() == b"chess", "the file is renamed, not deleted"


def test_the_same_file_is_never_treated_as_a_duplicate(tmp_path: Path, mocker):
    root = tmp_path / "card"
    (root / "a").mkdir(parents=True)
    (root / "a" / "x.epub").write_bytes(b"x")
    mocker.patch(
        "kobolib.apply.child_named",
        side_effect=lambda folder, name: (
            (folder / "x.epub")
            if name.lower() == "x.epub" and (folder / "x.epub").exists()
            else (folder / name if (folder / name).exists() else None)
        ),
    )
    op = Operation("move", "a/x.epub", "a/X.epub", "rename")

    result = apply([op], root, tmp_path / "j.jsonl")

    assert result.done == 1 and (root / "a" / "X.epub").read_bytes() == b"x", (
        "a case-insensitive hit on the source itself is an in-place rename"
    )
    assert not any(line["kind"] == "delete" for line in journal_lines(tmp_path / "j.jsonl")), "nothing is deleted"


def test_journal_is_written_step_by_step(library: Path, tmp_path: Path, mocker):
    journal = tmp_path / "journal.jsonl"
    real = __import__("kobolib.apply", fromlist=["relocate"]).relocate
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("card yanked")
        return real(*args, **kwargs)

    mocker.patch("kobolib.apply.relocate", side_effect=flaky)
    ops = [
        Operation("move", "00_Inbox/a.epub", "01_Fiction/a.epub", ""),
        Operation("trash", "00_Inbox/FSCK0000.000", "_trash/00_Inbox/FSCK0000.000", "junk"),
    ]

    with pytest.raises(OSError):
        apply(ops, library, journal)

    assert [line["src"] for line in journal_lines(journal)] == ["00_Inbox/a.epub"], (
        "the step that succeeded before the crash must be journaled"
    )
