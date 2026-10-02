import pytest

from kobolib.paths import relative_path
from kobolib.scan import is_junk, iter_books, probe_root


@pytest.mark.parametrize(
    "name, junk",
    [
        ("FSCK0000.000", True),
        ("FSCK0000.005", True),
        (".DS_Store", True),
        ("qualia1 13.21.25.textClipping", True),
        ("Napkin.pdf", False),
        ("book.epub.part", False),
        ("Lasker_Borba.229539.fb2.mobi", False),
    ],
)
def test_is_junk(name, junk):
    assert is_junk(name) is junk, f"{name!r} junk should be {junk}"


def test_iter_books_skips_junk_and_keeps_partials(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.epub").write_bytes(b"")
    (tmp_path / "a" / "two.fb2.part").write_bytes(b"")
    (tmp_path / "a" / "FSCK0000.000").write_bytes(b"")
    (tmp_path / "a" / "notes.txt").write_bytes(b"")

    found = sorted(p.name for p in iter_books(tmp_path))

    assert found == ["one.epub", "two.fb2.part"], "scan should keep books and partials, drop junk"


def test_relative_path_uses_posix_and_library_root(tmp_path):
    path = tmp_path / "01_Fiction" / "x.epub"
    assert relative_path(path, tmp_path) == "01_Fiction/x.epub", "relative path should be posix from root"


def test_probe_reports_permission_error(tmp_path, mocker):

    mocker.patch("kobolib.scan.os.listdir", side_effect=PermissionError("Operation not permitted"))

    assert "permission" in probe_root(tmp_path).lower(), "permission errors on the root should be reported"


def test_probe_reports_empty_root(tmp_path):

    assert "empty" in probe_root(tmp_path).lower(), "an empty root should be reported"


def test_probe_ok(tmp_path):

    (tmp_path / "x.epub").write_bytes(b"")
    assert probe_root(tmp_path) == "", "a readable non-empty root should produce no message"


def test_fingerprint_is_stable_across_moves(tmp_path):
    from kobolib.scan import fingerprint

    original = tmp_path / "a.epub"
    original.write_bytes(b"x" * 200_000)
    before = fingerprint(original)
    moved = original.rename(tmp_path / "b.epub")

    assert fingerprint(moved) == before, "renaming a file should not change its fingerprint"


def test_fingerprint_differs_for_different_content(tmp_path):
    from kobolib.scan import fingerprint

    (tmp_path / "a.epub").write_bytes(b"x" * 1000)
    (tmp_path / "b.epub").write_bytes(b"y" * 1000)

    assert fingerprint(tmp_path / "a.epub") != fingerprint(tmp_path / "b.epub"), "different content should fingerprint differently"


def test_fingerprint_sees_the_end_of_large_files(tmp_path):
    from kobolib.scan import FINGERPRINT_BYTES, fingerprint

    body = b"x" * (FINGERPRINT_BYTES * 3)
    (tmp_path / "a.epub").write_bytes(body)
    (tmp_path / "b.epub").write_bytes(body[:-1] + b"y")

    assert fingerprint(tmp_path / "a.epub") != fingerprint(tmp_path / "b.epub"), "a change in the tail should alter the fingerprint"


def test_iter_junk_reports_non_books_and_empty_dirs(tmp_path):
    from kobolib.scan import iter_junk

    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "FSCK0000.000").write_bytes(b"")
    (tmp_path / "a" / "note.textClipping").write_bytes(b"")
    (tmp_path / "a" / "x.fb2.zip").write_bytes(b"")
    (tmp_path / "a" / ".DS_Store").write_bytes(b"")
    (tmp_path / "a" / "ok.epub").write_bytes(b"")
    (tmp_path / "zip").mkdir()

    found = sorted(p.relative_to(tmp_path).as_posix() for p in iter_junk(tmp_path))

    assert found == ["a/FSCK0000.000", "a/note.textClipping", "a/x.fb2.zip", "zip"], (
        "junk should list non-book files and empty directories, skipping hidden files"
    )


def test_scanners_skip_trash_dups_and_excluded_dirs(tmp_path):
    from kobolib.scan import iter_books, iter_junk

    for folder in ("_trash/x", "_dups/y", "data", "ok"):
        (tmp_path / folder).mkdir(parents=True)
        (tmp_path / folder / "book.epub").write_bytes(b"")
        (tmp_path / folder / "junk.txt").write_bytes(b"")

    books = [p.relative_to(tmp_path).as_posix() for p in iter_books(tmp_path, exclude=(tmp_path / "data",))]
    junk = [p.relative_to(tmp_path).as_posix() for p in iter_junk(tmp_path, exclude=(tmp_path / "data",))]

    assert books == ["ok/book.epub"], "books under _trash, _dups and the excluded dir should be ignored"
    assert junk == ["ok/junk.txt"], "junk under _trash, _dups and the excluded dir should be ignored"


def test_junk_scan_ignores_hidden_trees_and_sidecars(tmp_path):
    from kobolib.scan import iter_books, iter_junk

    (tmp_path / ".adds" / "koreader" / "settings").mkdir(parents=True)
    (tmp_path / ".adds" / "koreader" / "settings" / "collection.lua").write_text("return {}")
    (tmp_path / "Book.sdr").mkdir()
    (tmp_path / "Book.sdr" / "metadata.epub.lua").write_text("return {}")
    (tmp_path / "Book.sdr" / "stray.epub").write_bytes(b"")
    (tmp_path / "Book.epub").write_bytes(b"")

    assert list(iter_junk(tmp_path)) == [], "KOReader's hidden tree and sidecar contents are not junk"
    assert [p.name for p in iter_books(tmp_path)] == ["Book.epub"], "nothing inside a sidecar is a library book"
