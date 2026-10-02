from pathlib import Path

from kobolib.covers import cover_key, ensure_cover
from kobolib.model import Book
from tests.conftest import PNG_1X1


def make_book(tmp_path: Path, name: str, cover=None) -> Book:
    path = tmp_path / name
    path.write_bytes(b"")
    return Book(path=str(path), rel_path=name, format=name.rsplit(".", 1)[-1], partial=False, cover=cover)


def test_cover_key_is_stable_per_relative_path(tmp_path: Path):
    a = make_book(tmp_path, "a.epub")
    assert cover_key(a) == cover_key(a), "same rel_path should give same key"
    assert cover_key(a) != cover_key(make_book(tmp_path, "b.epub")), "different rel_path should give different key"


def test_embedded_cover_is_written_once(tmp_path: Path, mocker):
    cache = tmp_path / "cache"
    book = make_book(tmp_path, "x.epub", cover=("cover.png", PNG_1X1))
    run = mocker.patch("kobolib.covers.subprocess.run")

    first = ensure_cover(book, cache)
    second = ensure_cover(book, cache)

    assert first == second, "cover path should be stable across calls"
    assert first.read_bytes() == PNG_1X1, "embedded cover bytes should be written to cache"
    assert first.suffix == ".png", "cover extension should follow the embedded image name"
    run.assert_not_called()


def test_quicklook_thumbnail_for_pdf(tmp_path: Path, mocker):
    cache = tmp_path / "cache"
    book = make_book(tmp_path, "Napkin.pdf")

    def fake_qlmanage(cmd, **kwargs):
        out_dir = Path(cmd[cmd.index("-o") + 1])
        (out_dir / "Napkin.pdf.png").write_bytes(PNG_1X1)
        return mocker.Mock(returncode=0)

    mocker.patch("kobolib.covers.shutil.which", return_value="/usr/bin/qlmanage")
    mocker.patch("kobolib.covers.subprocess.run", side_effect=fake_qlmanage)

    result = ensure_cover(book, cache)

    assert result is not None and result.read_bytes() == PNG_1X1, "pdf should get a quicklook thumbnail"


def test_quicklook_timeout_gives_no_cover(tmp_path: Path, mocker):
    import subprocess

    book = make_book(tmp_path, "Huge.pdf")
    mocker.patch("kobolib.covers.shutil.which", return_value="/usr/bin/qlmanage")
    mocker.patch("kobolib.covers.subprocess.run", side_effect=subprocess.TimeoutExpired("qlmanage", 15))

    assert ensure_cover(book, tmp_path / "cache") is None, "a hanging qlmanage should be abandoned, not waited on"


def test_thumbnails_can_be_skipped(tmp_path: Path, mocker):
    book = make_book(tmp_path, "Napkin.pdf")
    mocker.patch("kobolib.covers.shutil.which", return_value="/usr/bin/qlmanage")
    run = mocker.patch("kobolib.covers.subprocess.run")

    assert ensure_cover(book, tmp_path / "cache", thumbnails=False) is None, "thumbnails=False should skip qlmanage"
    run.assert_not_called()


def test_no_cover_without_quicklook(tmp_path: Path, mocker):
    book = make_book(tmp_path, "Napkin.pdf")
    mocker.patch("kobolib.covers.shutil.which", return_value=None)

    assert ensure_cover(book, tmp_path / "cache") is None, "without qlmanage pdf gets no cover"


def test_partial_books_get_no_cover(tmp_path: Path, mocker):
    book = make_book(tmp_path, "x.epub", cover=("c.jpg", PNG_1X1))
    book.partial = True
    mocker.patch("kobolib.covers.shutil.which", return_value="/usr/bin/qlmanage")
    run = mocker.patch("kobolib.covers.subprocess.run")

    assert ensure_cover(book, tmp_path / "cache") is None, "partial downloads should not produce covers"
    run.assert_not_called()
