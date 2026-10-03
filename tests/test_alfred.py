import json

import pytest

from kobolib.alfred import book_item, empty_item, render
from kobolib.model import Finding, Operation, Row

BASE_ROW = {
    "title": "Deep Work",
    "authors": "Cal Newport",
    "series": "Focus",
    "series_index": "2",
    "folder": "02_NonFiction",
    "rel_path": "02_NonFiction/x.epub",
    "root": "/lib",
    "format": "epub",
    "partial": False,
    "language": "en",
    "year": "2016",
    "cover": "/cache/abc.png",
    "size": 1_500_000,
    "mtime": 0.0,
    "norm_title": "deep work",
    "fingerprint": "f00",
    "genre": "",
    "subjects": "",
    "description": "",
}


def row(**overrides) -> Row:
    return Row(**{**BASE_ROW, **overrides})


def test_item_shows_metadata_and_relative_path():
    item = book_item(row())

    assert item["title"] == "Deep Work", "title should be the book title"
    assert item["subtitle"] == "Cal Newport · Focus #2 · 2016 · EPUB 1.4 MB · 02_NonFiction/x.epub", (
        "subtitle should show author, series, year, format, size and rel path"
    )
    assert item["arg"] == "/lib/02_NonFiction/x.epub", "arg should be the absolute path to open"
    assert item["icon"] == {"path": "/cache/abc.png"}, "cover should be used as the icon"
    assert item["quicklookurl"] == "/lib/02_NonFiction/x.epub", "quicklook should preview the book"
    assert item["text"]["copy"] == "02_NonFiction/x.epub", "copy should give the relative path"
    assert item["mods"]["alt"]["arg"] == "/lib/02_NonFiction/x.epub", "alt should still carry the path"


def test_item_without_cover_uses_file_icon():
    item = book_item(row(cover=""))
    assert item["icon"] == {"type": "fileicon", "path": "/lib/02_NonFiction/x.epub"}, "missing cover should fall back to file icon"


def test_book_item_offers_only_reveal_and_set_genre():
    mods = book_item(row())["mods"]

    assert set(mods) == {"alt", "shift"}, "a book row should have ⌥↩ reveal and ⇧↩ set genre, nothing else"
    assert mods["alt"] == {"arg": "/lib/02_NonFiction/x.epub", "subtitle": "Reveal in Finder"}, "⌥↩ should reveal the book"
    assert mods["shift"]["variables"] == {"book": "f00"} and mods["shift"]["arg"] == "", "⇧↩ should open the genre picker for the book"


def test_source_item_offers_only_reveal():
    from kobolib.alfred import source_item

    assert set(source_item(row())["mods"]) == {"alt"}, "a source book can only be revealed; it gets a genre after import"


@pytest.mark.parametrize("partial, mods", [(True, {"alt"}), (False, {"alt", "shift"})])
def test_trash_item_is_actionable_and_keeps_genre_only_for_complete_books(partial, mods):
    from kobolib.alfred import trash_item

    item = trash_item(row(partial=partial))

    assert item["valid"] is True and item["title"] == "Deep Work", "every trash row can be moved to _trash/"
    assert set(item["mods"]) == mods, "an unfinished download cannot be given a genre"


def test_head_row_carries_its_payload():
    from kobolib.alfred import head_row

    item = head_row("trash:all", "Trash all 2 books", "↩ moves them", arg="/a\n/b", variables={"book": "x\ny"})

    assert (item["uid"], item["title"], item["subtitle"]) == ("trash:all", "Trash all 2 books", "↩ moves them"), "the head row is labelled"
    assert item["arg"] == "/a\n/b" and item["variables"] == {"book": "x\ny"}, "the head row carries what ↩ acts on"
    assert item["valid"] is True and "mods" not in item, "↩ acts on the whole list; no modifier does"


def test_genre_item_creates_the_typed_text_on_shift():
    from kobolib.alfred import genre_item

    item = genre_item("fiction/spy", "f00", typed="spy thriller")

    assert item["arg"] == "fiction/spy", "↩ applies the listed genre"
    assert item["mods"]["shift"]["arg"] == "spy thriller", "⇧↩ creates the typed text as a new genre"
    assert item["mods"]["shift"]["variables"] == item["variables"] == {"book": "f00", "action": "genre"}, "both keys go to the genre step"
    assert "new genre" in item["mods"]["shift"]["subtitle"], "the shift subtitle should say it creates a new genre"


def test_genre_item_without_typed_text_has_no_shift():
    from kobolib.alfred import genre_item

    assert "mods" not in genre_item("fiction/spy", "f00"), "with nothing typed there is nothing to create"


def test_new_genre_item_creates_only_on_shift():
    from kobolib.alfred import new_genre_item

    item = new_genre_item("xyz", "f00")

    assert item["title"] == "No genre ‘xyz’ — ⇧↩ creates it" and item["valid"] is False, "plain ↩ should do nothing"
    assert (item["mods"]["shift"]["arg"], item["mods"]["shift"]["valid"]) == ("xyz", True), "⇧↩ should create it"
    assert item["variables"] == {"book": "f00", "action": "genre"}, "the book travels on to the genre step"


def test_item_omits_empty_parts():
    item = book_item(row(authors="", series="", series_index="", year="", size=0))
    assert item["subtitle"] == "EPUB · 02_NonFiction/x.epub", "empty metadata should not leave stray separators"


def test_render_keeps_the_order_it_is_given():
    output = json.loads(render([book_item(row())]))

    assert output["skipknowledge"] is True, "Alfred must not reorder rows it has learned, so head rows and reminders stay on top"


def test_render_and_empty():
    output = json.loads(render([book_item(row())]))
    assert len(output["items"]) == 1, "render should wrap items in Alfred JSON"
    assert empty_item("zzz")["valid"] is False, "no-match item should not be actionable"
    assert "subjects" in empty_item("zzz")["subtitle"], "the no-match row should list subjects among the searched fields"


def test_problem_item_points_at_first_file_and_copies_all():
    from kobolib.alfred import problem_item

    finding = Finding("exact_duplicate", "Glasswing ×2: identical files", ["00_Inbox/bought/a.epub", "00_Inbox/NOW/a.epub"])

    item = problem_item(finding, "/lib")

    assert item["title"] == "Glasswing ×2: identical files", "title should be the finding detail"
    assert item["subtitle"] == "exact duplicate · 2 files · 00_Inbox/bought/a.epub", "subtitle should show rule, count and first path"
    assert item["arg"] == "/lib/00_Inbox/bought/a.epub", "arg should be the absolute path of the first file"
    assert item["text"]["copy"] == "00_Inbox/bought/a.epub\n00_Inbox/NOW/a.epub", "copy should give every path"
    assert item["uid"] == "problem:exact_duplicate:00_Inbox/bought/a.epub", "uid should be stable per finding"
    assert item["variables"] == {"action": "reveal"}, "↩ on a problem should reveal the file"


def test_inbox_item_shows_what_is_missing():
    from kobolib.alfred import inbox_item

    item = inbox_item(row(authors="", series="", rel_path="00_Inbox/x.epub"))

    assert item["subtitle"] == "author ? · genre ? · EPUB 1.4 MB · 00_Inbox/x.epub", "unknown author and genre should be marked"


def test_inbox_item_shows_known_genre():
    from kobolib.alfred import inbox_item

    item = inbox_item(row(genre="fiction/sci-fi"))

    assert item["subtitle"].startswith("Cal Newport · Focus #2 · fiction/sci-fi · "), "known author, series and genre should be shown"


def test_plan_item_shows_source_and_destination():
    from kobolib.alfred import plan_item

    op = Operation("move", "00_Inbox/a.epub", "01_Fiction/Teague, Rowan/Teague, Rowan - Ash (2011).epub", "relocate + rename")

    item = plan_item(op, "/lib")

    assert item["title"] == "Teague, Rowan - Ash (2011).epub", "title should be the destination file name"
    assert item["subtitle"] == "move · relocate + rename · 00_Inbox/a.epub → 01_Fiction/Teague, Rowan/", (
        "subtitle should show kind, reason, source and destination folder"
    )
    assert item["arg"] == "/lib/00_Inbox/a.epub", "arg should point at the current file"
    assert item["text"]["copy"] == "00_Inbox/a.epub\t01_Fiction/Teague, Rowan/Teague, Rowan - Ash (2011).epub", (
        "copy should give the plan line"
    )


def test_skip_item_is_not_actionable():
    from kobolib.alfred import plan_item

    item = plan_item(Operation("skip", "a.epub", "b.epub", "destination taken by c.epub"), "/lib")

    assert item["valid"] is False and item["title"].startswith("⚠︎ "), "skipped operations should be visible but not actionable"
