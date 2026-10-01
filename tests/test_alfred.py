import json

from kobolib.alfred import book_item, empty_item, render
from kobolib.index import Row


def row(**overrides) -> Row:
    base = dict(
        title="Deep Work", authors="Cal Newport", series="Focus", series_index="2",
        folder="02_NonFiction", rel_path="02_NonFiction/x.epub", path="/lib/02_NonFiction/x.epub",
        format="epub", partial=False, language="en", year="2016", publisher="GC",
        source="epub", cover="/cache/abc.png", size=1_500_000, mtime=0.0, norm_title="deep work", fingerprint="f00",
    )
    return Row(**{**base, **overrides})


def test_item_shows_metadata_and_relative_path():
    item = book_item(row())

    assert item["title"] == "Deep Work", "title should be the book title"
    assert item["subtitle"] == "Cal Newport · Focus #2 · 2016 · EPUB 1.4 MB · 02_NonFiction/x.epub", "subtitle should show author, series, year, format, size and rel path"
    assert item["arg"] == "/lib/02_NonFiction/x.epub", "arg should be the absolute path to open"
    assert item["icon"] == {"path": "/cache/abc.png"}, "cover should be used as the icon"
    assert item["quicklookurl"] == "/lib/02_NonFiction/x.epub", "quicklook should preview the book"
    assert item["text"]["copy"] == "02_NonFiction/x.epub", "copy should give the relative path"
    assert item["mods"]["alt"]["arg"] == "/lib/02_NonFiction/x.epub", "alt should still carry the path"


def test_item_without_cover_uses_file_icon():
    item = book_item(row(cover=""))
    assert item["icon"] == {"type": "fileicon", "path": "/lib/02_NonFiction/x.epub"}, "missing cover should fall back to file icon"


def test_partial_item_is_marked_and_not_actionable():
    item = book_item(row(partial=True, cover=""))
    assert item["title"].startswith("⚠︎ "), "partial download should be flagged in the title"
    assert item["valid"] is False, "partial download should not be opened"


def test_item_omits_empty_parts():
    item = book_item(row(authors="", series="", series_index="", year="", size=0))
    assert item["subtitle"] == "EPUB · 02_NonFiction/x.epub", "empty metadata should not leave stray separators"


def test_render_and_empty():
    output = json.loads(render([book_item(row())]))
    assert len(output["items"]) == 1, "render should wrap items in Alfred JSON"
    assert empty_item("zzz")["valid"] is False, "no-match item should not be actionable"


def test_finding_item_points_at_first_file_and_copies_all():
    from kobolib.alfred import finding_item
    from kobolib.lint import Finding

    finding = Finding("exact_duplicate", "Glasswing ×2: identical files", ["00_Inbox/bought/a.epub", "00_Inbox/NOW/a.epub"])

    item = finding_item(finding, "/lib")

    assert item["title"] == "Glasswing ×2: identical files", "title should be the finding detail"
    assert item["subtitle"] == "exact duplicate · 2 files · 00_Inbox/bought/a.epub", "subtitle should show rule, count and first path"
    assert item["arg"] == "/lib/00_Inbox/bought/a.epub", "arg should be the absolute path of the first file"
    assert item["text"]["copy"] == "00_Inbox/bought/a.epub\n00_Inbox/NOW/a.epub", "copy should give every path"
    assert item["uid"] == "exact_duplicate:00_Inbox/bought/a.epub", "uid should be stable per finding"


def test_inbox_item_shows_what_is_missing():
    from kobolib.alfred import inbox_item

    item = inbox_item(row(authors="", series="", rel_path="00_Inbox/x.epub"), genre="")

    assert item["subtitle"] == "author ? · genre ? · EPUB 1.4 MB · 00_Inbox/x.epub", "unknown author and genre should be marked"


def test_inbox_item_shows_known_genre():
    from kobolib.alfred import inbox_item

    item = inbox_item(row(), genre="fiction/sci-fi")

    assert item["subtitle"].startswith("Cal Newport · Focus #2 · fiction/sci-fi · "), "known author, series and genre should be shown"


def test_plan_item_shows_source_and_destination():
    from kobolib.alfred import plan_item
    from kobolib.plan import Operation

    op = Operation("move", "00_Inbox/a.epub", "01_Fiction/Teague, Rowan/Teague, Rowan - Ash (2011).epub", "relocate + rename")

    item = plan_item(op, "/lib")

    assert item["title"] == "Teague, Rowan - Ash (2011).epub", "title should be the destination file name"
    assert item["subtitle"] == "move · relocate + rename · 00_Inbox/a.epub → 01_Fiction/Teague, Rowan/", "subtitle should show kind, reason, source and destination folder"
    assert item["arg"] == "/lib/00_Inbox/a.epub", "arg should point at the current file"
    assert item["text"]["copy"] == "00_Inbox/a.epub\t01_Fiction/Teague, Rowan/Teague, Rowan - Ash (2011).epub", "copy should give the plan line"


def test_skip_item_is_not_actionable():
    from kobolib.alfred import plan_item
    from kobolib.plan import Operation

    item = plan_item(Operation("skip", "a.epub", "b.epub", "destination taken by c.epub"), "/lib")

    assert item["valid"] is False and item["title"].startswith("⚠︎ "), "skipped operations should be visible but not actionable"
