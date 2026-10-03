import base64
import zipfile
from pathlib import Path

import pytest

from kobolib.cli import main

PNG_1X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0">
  <metadata>
    <dc:title>Deep Work</dc:title>
    <dc:creator>Cal Newport</dc:creator>
    <dc:creator>Someone Else</dc:creator>
    <dc:language>en</dc:language>
    <dc:date>2016-01-05</dc:date>
    <dc:publisher>Grand Central</dc:publisher>
    <meta name="calibre:series" content="Focus"/>
    <meta name="calibre:series_index" content="2"/>
    <meta name="cover" content="cover-img"/>
  </metadata>
  <manifest>
    <item id="cover-img" href="images/cover.png" media-type="image/png"/>
    <item id="text" href="text.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
</package>
"""

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""

FB2 = """<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">
  <description>
    <title-info>
      <author><first-name>Беррес</first-name><middle-name>Фредерик</middle-name><last-name>Скиннер</last-name></author>
      <book-title>Оперантное поведение</book-title>
      <lang>ru</lang>
      <sequence name="Психология" number="3"/>
      <coverpage><image l:href="#cover.png"/></coverpage>
    </title-info>
    <publish-info><year>1971</year><publisher>Наука</publisher></publish-info>
  </description>
  <body><section><p>text</p></section></body>
  <binary id="cover.png" content-type="image/png">{cover}</binary>
</FictionBook>
"""


@pytest.fixture
def epub_file(tmp_path: Path) -> Path:
    path = tmp_path / "Newport, Cal - Deep Work (2016, GC) - libgen.li.epub"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", OPF)
        zf.writestr("OEBPS/images/cover.png", PNG_1X1)
    return path


@pytest.fixture
def fb2_file(tmp_path: Path) -> Path:
    path = tmp_path / "Скиннер - Оперантное поведение.fb2"
    path.write_text(FB2.format(cover=base64.b64encode(PNG_1X1).decode()), encoding="utf-8")
    return path


@pytest.fixture
def library(tmp_path: Path, epub_file: Path, fb2_file: Path) -> Path:
    (tmp_path / "00_Inbox").mkdir()
    (tmp_path / "02_NonFiction").mkdir()
    epub_file.rename(tmp_path / "02_NonFiction" / epub_file.name)
    fb2_file.rename(tmp_path / "00_Inbox" / fb2_file.name)
    (tmp_path / "00_Inbox" / "Delany, Samuel R - Nova - 2014.epub.part").write_bytes(b"")
    (tmp_path / "00_Inbox" / "Napkin.pdf").write_bytes(b"%PDF-1.4")
    return tmp_path


@pytest.fixture
def env(library: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KOBO_ROOT", str(library))
    monkeypatch.setenv("alfred_workflow_data", str(tmp_path / "alfred-data"))
    monkeypatch.delenv("KOBO_DATA", raising=False)
    monkeypatch.setenv("book", "x")


@pytest.fixture
def indexed(env, capsys):
    main(["update"])
    capsys.readouterr()
