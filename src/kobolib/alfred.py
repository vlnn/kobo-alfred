from __future__ import annotations

import json
from pathlib import PurePosixPath

from kobolib.model import DuplicateGroup, Finding, Operation, Row

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
        "shift": {"arg": "", "subtitle": "Fix: set genre, add or remove tags", "variables": {"book": row.fingerprint}},
        "fn": {"arg": row.path, "subtitle": "Move to its genre home now"},
    }


BATCH = "alt+shift"
LINE = "\n"


def batch_mod(subtitle: str, arg: str = "", variables: dict | None = None) -> dict:
    return {"arg": arg, "subtitle": subtitle, **({"variables": variables} if variables else {})}


def with_batch(items: list[dict], mod: dict) -> list[dict]:
    return [{**i, "mods": {**i.get("mods", {}), BATCH: mod}} if i.get("valid", True) else i for i in items]


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
        "variables": {"book": row.fingerprint},
    }


def classify_item(row: Row) -> dict:
    return {**inbox_item(row), "arg": "", "mods": {}, "subtitle": inbox_subtitle(row) + " · ↩ pick a genre"}


def fix_header(row: Row, genre: str, tags: list[str]) -> dict:
    state = SEPARATOR.join(p for p in (genre or "no genre", ", ".join(tags), row.rel_path) if p)
    return {**message_item(row.title, state), "icon": icon(row)}


def edit_item(edit: str, title: str, book: str) -> dict:
    return {"uid": f"edit:{edit}", "title": title, "arg": edit, "autocomplete": edit, "variables": {"book": book}}


def genre_item(genre: str, book: str) -> dict:
    return {**edit_item(f"genre={genre}", genre, book), "uid": f"genre:{genre}", "autocomplete": genre}


def source_item(row: Row) -> dict:
    return {
        **book_item(row),
        "variables": {},
        "mods": {
            "alt": {"arg": row.path, "subtitle": "Reveal in Finder"},
            "cmd": {"arg": row.path, "subtitle": f"Copy path: {row.path}"},
            "ctrl": {"arg": row.folder, "subtitle": f"Browse folder: {row.folder}"},
        },
    }


def inbox_subtitle(row: Row) -> str:
    parts = [row.authors or "author ?", series_label(row), row.genre or "genre ?", format_label(row), row.rel_path]
    return SEPARATOR.join(p for p in parts if p)


def inbox_item(row: Row) -> dict:
    return {**book_item(row), "subtitle": inbox_subtitle(row)}


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


def batch_item(uid: str, title: str, subtitle: str, arg: str = "", variables: dict | None = None) -> dict:
    return {
        "uid": uid,
        "title": title,
        "subtitle": subtitle,
        "arg": arg,
        "icon": {"type": "fileicon", "path": "/System/Applications/Utilities/Terminal.app"},
        **({"variables": variables} if variables else {}),
    }


def import_all_item(rows: list[Row]) -> dict:
    paths = LINE.join(r.path for r in rows)
    return batch_item("src:import-all", f"Import all {len(rows)} books", "↩ copies every book listed below into the library inbox", paths)


def classify_all_item(rows: list[Row]) -> dict:
    books = LINE.join(r.fingerprint for r in rows)
    return batch_item(
        "classify:all", f"Classify all {len(rows)} books", "↩ picks one genre for every book listed below", variables={"book": books}
    )


def apply_all_item(count: int) -> dict:
    return {
        "uid": "plan:apply-all",
        "title": f"Apply all {count} operations",
        "subtitle": "↩ runs the whole plan, then rebuilds the index · ↩ on a row below applies that row only",
        "arg": "",
        "icon": {"type": "fileicon", "path": "/System/Applications/Utilities/Terminal.app"},
    }


def plan_item(op: Operation, root: str) -> dict:
    src = f"{root}/{op.src}"
    skipped = op.kind == "skip"
    name = PurePosixPath(op.dst).name
    return {
        "uid": f"plan:{op.src}",
        "title": f"⚠︎ {name}" if skipped else name,
        "subtitle": SEPARATOR.join([op.kind, op.reason, f"{op.src} → {PurePosixPath(op.dst).parent}/"]),
        "arg": src,
        "valid": not skipped,
        "icon": {"type": "fileicon", "path": src},
        "quicklookurl": src,
        "text": {"copy": f"{op.src}\t{op.dst}", "largetype": f"{op.src}\n→ {op.dst}"},
        "mods": {"alt": {"arg": src, "subtitle": "Reveal in Finder"}},
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


def suggestion_item(command: str, help: str) -> dict:
    return {"uid": f"kb:{command}", "title": f"kb {command}", "subtitle": help, "autocomplete": f"{command} ", "valid": False}


def message_item(title: str, subtitle: str = "") -> dict:
    return {"title": title, "subtitle": subtitle, "valid": False}


def render(items: list[dict]) -> str:
    return json.dumps({"items": items}, ensure_ascii=False)
