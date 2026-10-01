from __future__ import annotations

import json

from kobolib.index import DuplicateGroup, Row
from kobolib.lint import Finding

SEPARATOR = " · "


def human_size(size: int) -> str:
    if size <= 0:
        return ""
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return ""


def series_label(row: Row) -> str:
    if not row.series:
        return ""
    return f"{row.series} #{row.series_index}" if row.series_index else row.series


def format_label(row: Row) -> str:
    return " ".join(p for p in (row.format.upper(), human_size(row.size)) if p)


def subtitle(row: Row) -> str:
    parts = [row.authors, series_label(row), row.year, format_label(row), row.rel_path]
    return SEPARATOR.join(p for p in parts if p)


def icon(row: Row) -> dict:
    if row.cover:
        return {"path": row.cover}
    return {"type": "fileicon", "path": row.path}


def modifiers(row: Row) -> dict:
    return {
        "alt": {"arg": row.path, "subtitle": "Reveal in Finder"},
        "cmd": {"arg": row.rel_path, "subtitle": f"Copy relative path: {row.rel_path}"},
        "ctrl": {"arg": row.folder, "subtitle": f"Browse folder: {row.folder}"},
        "shift": {"arg": row.path, "subtitle": "Quick Look"},
    }


def book_item(row: Row) -> dict:
    title = f"⚠︎ {row.title} (incomplete download)" if row.partial else row.title
    return {
        "uid": row.rel_path,
        "title": title,
        "subtitle": subtitle(row),
        "arg": row.path,
        "valid": not row.partial,
        "icon": icon(row),
        "quicklookurl": row.path,
        "autocomplete": row.title,
        "text": {"copy": row.rel_path, "largetype": f"{row.title}\n{row.authors}\n{row.rel_path}"},
        "mods": modifiers(row),
    }


def inbox_subtitle(row: Row, genre: str) -> str:
    parts = [row.authors or "author ?", series_label(row), genre or "genre ?", format_label(row), row.rel_path]
    return SEPARATOR.join(p for p in parts if p)


def inbox_item(row: Row, genre: str) -> dict:
    return {**book_item(row), "subtitle": inbox_subtitle(row, genre)}


def finding_item(finding: Finding, root: str) -> dict:
    first = finding.rel_paths[0]
    path = f"{root}/{first}"
    count = f"{len(finding.rel_paths)} file" + ("s" if len(finding.rel_paths) > 1 else "")
    return {
        "uid": f"{finding.rule}:{first}",
        "title": finding.detail,
        "subtitle": SEPARATOR.join([finding.rule.replace("_", " "), count, first]),
        "arg": path,
        "icon": {"type": "fileicon", "path": path},
        "quicklookurl": path,
        "text": {"copy": "\n".join(finding.rel_paths), "largetype": "\n".join(finding.rel_paths)},
        "mods": {"alt": {"arg": path, "subtitle": "Reveal in Finder"}},
    }


def duplicate_item(group: DuplicateGroup) -> dict:
    paths = "\n".join(b.rel_path for b in group.books)
    formats = ", ".join(b.format + ("(part)" if b.partial else "") for b in group.books)
    return {
        "uid": f"dup:{group.title}",
        "title": f"{group.title}  ×{len(group.books)}",
        "subtitle": f"{formats} — {group.books[0].folder}",
        "arg": group.books[0].path,
        "icon": icon(group.books[0]),
        "text": {"copy": paths, "largetype": paths},
        "mods": {"alt": {"arg": group.books[0].path, "subtitle": "Reveal first copy in Finder"}},
    }


def empty_item(query: str) -> dict:
    return {
        "title": f"No books match “{query}”",
        "subtitle": "Try fmt:epub, in:inbox, author:…, series:…, lang:…, is:partial — or kb:index to rebuild",
        "valid": False,
    }


def message_item(title: str, subtitle: str = "") -> dict:
    return {"title": title, "subtitle": subtitle, "valid": False}


def render(items: list[dict], rerun: float | None = None) -> str:
    payload = {"items": items}
    if rerun:
        payload["rerun"] = rerun
    return json.dumps(payload, ensure_ascii=False)
