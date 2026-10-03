from __future__ import annotations

import base64
import posixpath
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from kobolib.filenames import guess_from_stem
from kobolib.identity import fingerprint
from kobolib.model import Book, Cover
from kobolib.paths import relative_path
from kobolib.scan import book_format, display_stem, is_partial

NS = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "oc": "urn:oasis:names:tc:opendocument:xmlns:container",
    "fb": "http://www.gribuser.ru/xml/fictionbook/2.0",
    "xl": "http://www.w3.org/1999/xlink",
}


def text_of(root: ET.Element, xpath: str) -> str:
    node = root.find(xpath, NS)
    return (node.text or "").strip() if node is not None else ""


def texts_of(root: ET.Element, xpath: str) -> list[str]:
    return [t for n in root.findall(xpath, NS) if (t := (n.text or "").strip())]


def opf_path(zf: zipfile.ZipFile) -> str:
    container = ET.fromstring(zf.read("META-INF/container.xml"))
    return container.find("oc:rootfiles/oc:rootfile", NS).get("full-path")


def opf_meta(package: ET.Element, name: str) -> str:
    for meta in package.iter(f"{{{NS['opf']}}}meta"):
        if meta.get("name") == name:
            return meta.get("content", "")
    return ""


def cover_href(package: ET.Element) -> str:
    items = package.findall("opf:manifest/opf:item", NS)
    cover_id = opf_meta(package, "cover")
    for item in items:
        if "cover-image" in item.get("properties", "").split() or item.get("id") == cover_id:
            return item.get("href", "")
    for item in items:
        if item.get("media-type", "").startswith("image/") and "cover" in item.get("id", "").lower():
            return item.get("href", "")
    return ""


def epub_cover(zf: zipfile.ZipFile, opf: str, package: ET.Element) -> Cover | None:
    href = cover_href(package)
    if not href:
        return None
    full = posixpath.normpath(posixpath.join(posixpath.dirname(opf), href))
    try:
        return posixpath.basename(full), zf.read(full)
    except KeyError:
        return None


def flat_text(node: ET.Element | None) -> str:
    return " ".join(" ".join(node.itertext()).split()) if node is not None else ""


def read_epub(path: Path, book: Book) -> Book:
    with zipfile.ZipFile(path) as zf:
        opf = opf_path(zf)
        package = ET.fromstring(zf.read(opf))
        book.title = text_of(package, "opf:metadata/dc:title")
        book.authors = texts_of(package, "opf:metadata/dc:creator")
        book.language = text_of(package, "opf:metadata/dc:language")
        book.year = text_of(package, "opf:metadata/dc:date")[:4]
        book.series = opf_meta(package, "calibre:series")
        book.series_index = opf_meta(package, "calibre:series_index").removesuffix(".0")
        book.subjects = texts_of(package, "opf:metadata/dc:subject")
        book.description = flat_text(package.find("opf:metadata/dc:description", NS))
        book.cover = epub_cover(zf, opf, package)
    return book


def fb2_author(node: ET.Element) -> str:
    parts = (text_of(node, f"fb:{tag}") for tag in ("first-name", "middle-name", "last-name"))
    return " ".join(p for p in parts if p) or text_of(node, "fb:nickname")


def fb2_cover(root: ET.Element) -> Cover | None:
    image = root.find("fb:description/fb:title-info/fb:coverpage/fb:image", NS)
    if image is None:
        return None
    href = image.get(f"{{{NS['xl']}}}href", "").lstrip("#")
    for binary in root.findall("fb:binary", NS):
        if binary.get("id") == href:
            return href, base64.b64decode(re.sub(r"\s", "", binary.text or ""))
    return None


def read_fb2(path: Path, book: Book) -> Book:
    root = ET.parse(path).getroot()
    info = root.find("fb:description/fb:title-info", NS)
    book.title = text_of(info, "fb:book-title")
    book.authors = [a for n in info.findall("fb:author", NS) if (a := fb2_author(n))]
    book.language = text_of(info, "fb:lang")
    sequence = info.find("fb:sequence", NS)
    if sequence is not None:
        book.series = sequence.get("name", "")
        book.series_index = sequence.get("number", "")
    book.year = text_of(root, "fb:description/fb:publish-info/fb:year")
    book.subjects = texts_of(info, "fb:genre")
    book.description = flat_text(info.find("fb:annotation", NS))
    book.cover = fb2_cover(root)
    return book


READERS = {"epub": read_epub, "fb2": read_fb2}
MAGIC = {
    "pdf": (0, (b"%PDF",)),
    "djvu": (0, (b"AT&TFORM",)),
    "mobi": (60, (b"BOOKMOBI", b"TEXtREAd")),
    "azw": (60, (b"BOOKMOBI", b"TEXtREAd")),
    "azw3": (60, (b"BOOKMOBI",)),
}


def looks_like(path: Path, fmt: str) -> bool:
    if fmt not in MAGIC:
        return True
    offset, signatures = MAGIC[fmt]
    with path.open("rb") as handle:
        handle.seek(offset)
        head = handle.read(max(map(len, signatures)))
    return head.startswith(signatures)


def read_metadata(path: Path, book: Book) -> Book:
    reader = READERS.get(book.format)
    if reader is None:
        book.broken = not looks_like(path, book.format)
        return book
    try:
        return reader(path, book)
    except Exception:
        book.broken = True
        return book


def is_sound(book: Book) -> bool:
    return not book.partial and not book.broken


def from_filename(path: Path, book: Book) -> Book:
    guess = guess_from_stem(display_stem(path))
    book.title = book.title or guess.title
    book.authors = book.authors or guess.authors
    book.series = book.series or guess.series
    book.series_index = book.series_index or guess.series_index
    book.year = book.year or guess.year
    return book


def read_book(path: Path, root: Path) -> Book:
    stat = path.stat()
    book = Book(
        path=str(path),
        rel_path=relative_path(path, root),
        format=book_format(path),
        partial=is_partial(path),
        size=stat.st_size,
        mtime=stat.st_mtime,
        fingerprint=fingerprint(path),
    )
    if not book.partial:
        book = read_metadata(path, book)
    return from_filename(path, book)
