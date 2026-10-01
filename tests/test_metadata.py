from pathlib import Path

import pytest

from kobolib.metadata import read_book
from tests.conftest import PNG_1X1


def test_epub_metadata(epub_file: Path):
    book = read_book(epub_file, epub_file.parent)

    assert book.title == "Deep Work", "epub title should come from dc:title"
    assert book.authors == ["Cal Newport", "Someone Else"], "epub should list all dc:creator"
    assert book.language == "en", "epub language should come from dc:language"
    assert book.year == "2016", "epub year should be first 4 digits of dc:date"
    assert book.publisher == "Grand Central", "epub publisher should come from dc:publisher"
    assert book.series == "Focus", "epub series should come from calibre:series"
    assert book.series_index == "2", "epub series index should come from calibre:series_index"
    assert book.cover == ("cover.png", PNG_1X1), "epub cover should be resolved via meta name=cover"
    assert book.source == "epub", "epub metadata source should be marked"


def test_fb2_metadata(fb2_file: Path):
    book = read_book(fb2_file, fb2_file.parent)

    assert book.title == "Оперантное поведение", "fb2 title should come from book-title"
    assert book.authors == ["Беррес Фредерик Скиннер"], "fb2 author should join name parts"
    assert book.language == "ru", "fb2 language should come from lang"
    assert book.series == "Психология", "fb2 series should come from sequence name"
    assert book.series_index == "3", "fb2 series index should come from sequence number"
    assert book.year == "1971", "fb2 year should come from publish-info"
    assert book.cover == ("cover.png", PNG_1X1), "fb2 cover should decode the referenced binary"


@pytest.mark.parametrize("name", ["Napkin.pdf", "Make It Stick - Peter C. Brown.mobi"])
def test_filename_fallback(tmp_path: Path, name: str):
    path = tmp_path / name
    path.write_bytes(b"")

    book = read_book(path, tmp_path)

    assert book.title, f"{name} should get a title from its filename"
    assert book.source == "filename", "unparseable formats should fall back to filename"
    assert book.cover is None, "no cover should be extracted from unknown formats"


def test_partial_file_is_flagged_and_uses_filename(tmp_path: Path):
    path = tmp_path / "Delany, Samuel R - Nova - 2014.epub.part"
    path.write_bytes(b"not a zip")

    book = read_book(path, tmp_path)

    assert book.partial is True, "a .part file should be flagged partial"
    assert book.format == "epub", "format should look past the .part suffix"
    assert book.title == "Nova", "partial files should be described from their filename"
    assert book.rel_path == path.name, "rel_path should be relative to the library root"


def test_corrupt_epub_falls_back_to_filename(tmp_path: Path):
    path = tmp_path / "Greg Bear - Dead Lines.epub"
    path.write_bytes(b"garbage")

    book = read_book(path, tmp_path)

    assert book.title == "Dead Lines", "corrupt epub should still be indexed from filename"
    assert book.source == "filename", "corrupt epub should be marked as filename-sourced"


def test_filename_metadata_is_nfc_normalized(tmp_path):
    import unicodedata
    from kobolib.metadata import read_book

    name = unicodedata.normalize("NFD", "Вайс Йосип - Пісня.fb2")
    path = tmp_path / name
    path.write_bytes(b"not xml")

    book = read_book(path, tmp_path)

    assert book.authors == ["Вайс Йосип"] and book.title == "Пісня", "decomposed macOS filenames should yield composed metadata"
    assert unicodedata.is_normalized("NFC", book.rel_path), "rel_path should be composed too"
