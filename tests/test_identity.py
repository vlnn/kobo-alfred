import base64
import zipfile
from pathlib import Path

import pytest

from kobolib.identity import file_hash, fingerprint
from tests.conftest import CONTAINER, FB2, OPF, PNG_1X1

CHAPTERS = {"OEBPS/ch1.xhtml": "<p>Deep work is</p>", "OEBPS/ch2.xhtml": "<p>the ability to focus</p>"}
OTHER_PNG = PNG_1X1[:-8] + b"\0" * 8


def write_epub(path: Path, chapters=CHAPTERS, opf=OPF, cover=PNG_1X1, css="p {}", compression=zipfile.ZIP_STORED) -> Path:
    with zipfile.ZipFile(path, "w", compression) as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/style.css", css)
        zf.writestr("OEBPS/images/cover.png", cover)
        for name, text in chapters.items():
            zf.writestr(name, text)
    return path


def renamed_chapters() -> dict:
    return {"OEBPS/text/part0001.html": CHAPTERS["OEBPS/ch1.xhtml"], "OEBPS/text/part0002.html": CHAPTERS["OEBPS/ch2.xhtml"]}


def reversed_chapters() -> dict:
    return dict(reversed(list(CHAPTERS.items())))


@pytest.mark.parametrize(
    "variant, description",
    [
        ({}, "a byte-identical copy"),
        ({"compression": zipfile.ZIP_DEFLATED}, "the same book zipped differently"),
        ({"chapters": renamed_chapters()}, "chapter files renamed inside the epub"),
        ({"chapters": reversed_chapters()}, "chapter files stored in another order"),
        ({"cover": OTHER_PNG}, "a replaced cover image"),
        ({"opf": OPF.replace("Deep Work", "Deep Work (Polished)")}, "edited metadata"),
        ({"css": "p { margin: 0 }"}, "a changed stylesheet"),
    ],
)
def test_epub_fingerprint_ignores_packaging(tmp_path: Path, variant, description):
    original = write_epub(tmp_path / "a.epub")
    other = write_epub(tmp_path / "b.epub", **variant)

    assert fingerprint(other) == fingerprint(original), f"{description} should keep the fingerprint"


@pytest.mark.parametrize(
    "variant, description",
    [
        ({"chapters": {**CHAPTERS, "OEBPS/ch1.xhtml": "<p>Deep work was</p>"}}, "a change in the text"),
        ({"chapters": {**CHAPTERS, "OEBPS/ch3.xhtml": "<p>Afterword</p>"}}, "an added chapter"),
        ({"chapters": {"OEBPS/ch1.xhtml": CHAPTERS["OEBPS/ch1.xhtml"]}}, "a removed chapter"),
    ],
)
def test_epub_fingerprint_follows_the_text(tmp_path: Path, variant, description):
    original = write_epub(tmp_path / "a.epub")
    other = write_epub(tmp_path / "b.epub", **variant)

    assert fingerprint(other) != fingerprint(original), f"{description} should change the fingerprint"


def test_fingerprint_is_stable_across_renames(tmp_path: Path):
    original = write_epub(tmp_path / "a.epub")
    before = fingerprint(original)

    moved = original.rename(tmp_path / "Newport, Cal - Deep Work.epub")

    assert fingerprint(moved) == before, "renaming a file should not change its fingerprint"


def write_fb2(path: Path, text: str = FB2, body: str = "<p>text</p>", cover: bytes = PNG_1X1) -> Path:
    content = text.format(cover=base64.b64encode(cover).decode()).replace("<p>text</p>", body)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "variant, description",
    [
        ({}, "a byte-identical copy"),
        ({"cover": OTHER_PNG}, "a replaced cover binary"),
        ({"text": FB2.replace("Оперантное поведение", "Поведение")}, "an edited title"),
        ({"text": FB2.replace("<year>1971</year>", "<year>1972</year>")}, "edited publish info"),
    ],
)
def test_fb2_fingerprint_ignores_description(tmp_path: Path, variant, description):
    original = write_fb2(tmp_path / "a.fb2")
    other = write_fb2(tmp_path / "b.fb2", **variant)

    assert fingerprint(other) == fingerprint(original), f"{description} should keep the fingerprint"


def test_fb2_fingerprint_follows_the_body(tmp_path: Path):
    original = write_fb2(tmp_path / "a.fb2")
    other = write_fb2(tmp_path / "b.fb2", body="<p>other text</p>")

    assert fingerprint(other) != fingerprint(original), "a change in the body should change the fingerprint"


@pytest.mark.parametrize(
    "name, content",
    [
        ("corrupt.epub", b"garbage"),
        ("no-text.epub", b""),
        ("broken.fb2", b"<FictionBook><description>"),
        ("Nova.epub.part", b"half a zip"),
        ("Napkin.pdf", b"%PDF-1.4 ..."),
        ("Make It Stick.mobi", b"\0" * 60 + b"BOOKMOBI"),
    ],
)
def test_fingerprint_falls_back_to_the_whole_file(tmp_path: Path, name: str, content: bytes):
    path = tmp_path / name
    if name == "no-text.epub":
        write_epub(path, chapters={})
    else:
        path.write_bytes(content)

    assert fingerprint(path) == file_hash(path), f"{name} should be identified by its bytes"


def test_file_hash_covers_every_byte(tmp_path: Path):
    body = b"x" * 300_000
    (tmp_path / "a.pdf").write_bytes(body)
    (tmp_path / "b.pdf").write_bytes(body[:150_000] + b"y" + body[150_001:])

    assert file_hash(tmp_path / "a.pdf") != file_hash(tmp_path / "b.pdf"), "a change in the middle should alter the hash"
