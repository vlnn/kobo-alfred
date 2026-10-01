import pytest

from kobolib.scan import iter_books, is_junk, probe_root, relative_path


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
