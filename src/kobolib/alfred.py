from __future__ import annotations

import json
from pathlib import PurePosixPath

from kobolib.model import Finding, Operation, Row

SEPARATOR = " · "


def counted(n: int, noun: str, plural: str = "") -> str:
    return f"{n} {noun if n == 1 else plural or noun + 's'}"


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


LINE = "\n"
TERMINAL_ICON = {"type": "fileicon", "path": "/System/Applications/Utilities/Terminal.app"}


def reveal(path: str) -> dict:
    return {"arg": path, "subtitle": "Reveal in Finder"}


def modifiers(row: Row) -> dict:
    return {
        "alt": reveal(row.path),
        "shift": {"arg": "", "subtitle": "Set genre", "variables": {"book": row.fingerprint}},
    }


def book_item(row: Row) -> dict:
    return {
        "uid": row.rel_path,
        "title": row.title,
        "subtitle": subtitle(row),
        "arg": row.path,
        "valid": True,
        "icon": icon(row),
        "quicklookurl": row.path,
        "autocomplete": row.title,
        "text": {"copy": row.rel_path, "largetype": f"{row.title}\n{row.authors}\n{row.rel_path}"},
        "mods": modifiers(row),
        "variables": {"book": row.fingerprint},
    }


def copy_item(row: Row, copies: int) -> dict:
    return {**book_item(row), "subtitle": f"×{copies}{SEPARATOR}{subtitle(row)}"}


def trash_subtitle(row: Row) -> str:
    return SEPARATOR.join(["unfinished download", subtitle(row)]) if row.partial else subtitle(row)


def trash_item(row: Row) -> dict:
    item = {**book_item(row), "subtitle": trash_subtitle(row)}
    return {**item, "mods": {"alt": reveal(row.path)}} if row.partial else item


def classify_item(row: Row) -> dict:
    return {**inbox_item(row), "arg": "", "mods": {}, "subtitle": inbox_subtitle(row) + " · ↩ pick a genre"}


def genre_header(row: Row, genre: str) -> dict:
    state = SEPARATOR.join((genre or "no genre", row.rel_path))
    return {**message_item(row.title, state), "icon": icon(row)}


def genre_variables(book: str) -> dict:
    return {"book": book, "action": "genre"}


def new_genre_mod(typed: str, book: str) -> dict:
    return {"arg": typed, "subtitle": f"Create ‘{typed}’ as a new genre", "valid": True, "variables": genre_variables(book)}


def genre_item(genre: str, book: str, typed: str = "") -> dict:
    item = {"uid": f"genre:{genre}", "title": genre, "arg": genre, "autocomplete": genre, "variables": genre_variables(book)}
    return {**item, "mods": {"shift": new_genre_mod(typed, book)}} if typed else item


def keep_genre_item(item: dict) -> dict:
    return {**item, "title": f"Keep {item['arg']}", "subtitle": "moves the book home if it isn't"}


def new_genre_item(typed: str, book: str) -> dict:
    return {
        "uid": f"genre-new:{typed}",
        "title": f"No genre ‘{typed}’ — ⇧↩ creates it",
        "valid": False,
        "variables": genre_variables(book),
        "mods": {"shift": new_genre_mod(typed, book)},
    }


def source_item(row: Row) -> dict:
    return {**book_item(row), "variables": {}, "mods": {"alt": reveal(row.path)}}


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
        "mods": {"alt": reveal(path)},
    }


def problem_item(finding: Finding, root: str) -> dict:
    item = finding_item(finding, root)
    return {**item, "uid": f"problem:{item['uid']}", "variables": {"action": "reveal"}}


def conflict_item(op: Operation, root: str) -> dict:
    return {**plan_item(op, root), "uid": f"problem:conflict:{op.src}", "valid": True, "variables": {"action": "reveal"}}


def head_row(uid: str, title: str, subtitle: str, arg: str = "", variables: dict | None = None) -> dict:
    payload = {"variables": variables} if variables else {}
    return {"uid": uid, "title": title, "subtitle": subtitle, "arg": arg, "valid": True, "icon": TERMINAL_ICON, **payload}


def import_all_item(rows: list[Row]) -> dict:
    paths = LINE.join(r.path for r in rows)
    return head_row("src:import-all", f"Import all {len(rows)} books", "↩ copies every book listed below into the library inbox", paths)


def classify_all_item(rows: list[Row]) -> dict:
    books = LINE.join(r.fingerprint for r in rows)
    title = f"Set genre for all {len(rows)} books"
    return head_row("classify:all", title, "↩ picks one genre for every book listed below", variables={"book": books})


def apply_all_item(count: int) -> dict:
    subtitle = "↩ runs the whole plan, then rebuilds the index · ↩ on a row below applies that row only"
    return head_row("plan:apply-all", f"Apply all {count} operations", subtitle)


def plan_item(op: Operation, root: str) -> dict:
    src = f"{root}/{op.src}"
    skipped = op.kind == "skip"
    name = PurePosixPath(op.dst).name
    return {
        "uid": f"fix:{op.src}",
        "title": f"⚠︎ {name}" if skipped else name,
        "subtitle": SEPARATOR.join([op.kind, op.reason, f"{op.src} → {PurePosixPath(op.dst).parent}/"]),
        "arg": src,
        "valid": not skipped,
        "icon": {"type": "fileicon", "path": src},
        "quicklookurl": src,
        "text": {"copy": f"{op.src}\t{op.dst}", "largetype": f"{op.src}\n→ {op.dst}"},
        "mods": {"alt": reveal(src)},
    }


def empty_item(query: str) -> dict:
    return {
        "title": f"No books match ‘{query}’",
        "subtitle": "Words match title, author, series, path, genre, format, language and year",
        "valid": False,
    }


def navigation_item(title: str, subtitle: str, completion: str) -> dict:
    return {"title": title, "subtitle": subtitle, "autocomplete": completion, "valid": False}


def action_item(title: str, subtitle: str, action: str, arg: str = "") -> dict:
    return {"title": title, "subtitle": subtitle, "arg": arg, "valid": True, "variables": {"action": action}}


def suggestion_item(command: str, help: str) -> dict:
    return {"uid": f"kb:{command}", **navigation_item(f"kb {command}", help, f"{command} ")}


def message_item(title: str, subtitle: str = "") -> dict:
    return {"title": title, "subtitle": subtitle, "valid": False}


def render(items: list[dict]) -> str:
    return json.dumps({"items": items}, ensure_ascii=False)
