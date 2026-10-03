from __future__ import annotations

import json
import time
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from kobolib.config import oracle_key, oracle_lock_base, oracle_log_path, oracle_model, oracle_status_path, oracle_url
from kobolib.index import acquire_lock, index_busy

TIMEOUT = 60
LOG_ENTRIES = 500
NONE = "none"
PROMPTS = {
    "genre": "You file ebooks in a personal library. Given what is known about one book, choose the genre it belongs under "
    "from the list of known genres. Answer none when you are not reasonably sure. Answer with JSON only.",
    "name": "You catalogue ebooks whose file names carry no usable information. Given what is known about one book, state "
    "its real title and its authors as a library catalogue would write them, each author as Surname, Given. Never invent: "
    "when the evidence does not say, answer confident false. Answer with JSON only.",
    "authors": "These are the author folders of a personal ebook library, named Surname, Given. Find folders that denote one "
    "and the same person spelled differently, transliterated or with and without initials. For each such group give the "
    "canonical spelling, Surname, Given, and the other folders as aliases. Leave out anyone who appears once. Answer with JSON only.",
}
AUTHORS_SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"canonical": {"type": "string"}, "aliases": {"type": "array", "items": {"type": "string"}}},
                "required": ["canonical", "aliases"],
            },
        }
    },
    "required": ["groups"],
}
MAX_TOKENS = {"genre": 64, "name": 256, "authors": 4096}
NAME_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "authors": {"type": "array", "items": {"type": "string"}},
        "confident": {"type": "boolean"},
    },
    "required": ["title", "authors", "confident"],
}


def configured() -> bool:
    return bool(oracle_url())


def request_body(question: str, evidence: str, schema: dict) -> dict:
    body = {
        "messages": [{"role": "system", "content": PROMPTS[question]}, {"role": "user", "content": evidence}],
        "temperature": 0,
        "max_tokens": MAX_TOKENS[question],
        "chat_template_kwargs": {"enable_thinking": False},
        "reasoning_effort": "low",
        "response_format": {"type": "json_schema", "json_schema": {"name": question, "schema": schema}},
    }
    return {**body, "model": oracle_model()} if oracle_model() else body


def headers(key: str) -> dict[str, str]:
    return {"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})}


def post(url: str, body: dict, timeout: float) -> dict:
    request = Request(url, data=json.dumps(body).encode(), headers=headers(oracle_key()))
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def reply_of(response: dict) -> dict | None:
    try:
        reply = json.loads(response["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return reply if isinstance(reply, dict) else None


def write_log(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def trim_log(path: Path) -> None:
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) > LOG_ENTRIES:
        path.write_text("".join(f"{line}\n" for line in lines[-LOG_ENTRIES:]), encoding="utf-8")


def busy() -> bool:
    return index_busy(oracle_lock_base())


def lock() -> Path:
    trim_log(oracle_log_path())
    return acquire_lock(oracle_lock_base())


def note_reachability(reachable: bool) -> None:
    status = oracle_status_path()
    if reachable:
        status.unlink(missing_ok=True)
    elif not status.exists():
        status.parent.mkdir(parents=True, exist_ok=True)
        status.write_text(oracle_url(), encoding="utf-8")


def unreachable() -> str:
    status = oracle_status_path()
    return status.read_text(encoding="utf-8").strip() if status.exists() else ""


def ask(question: str, evidence: str, schema: dict) -> dict | None:
    if not configured():
        return None
    entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "question": question, "prompt": evidence}
    started = time.monotonic()
    try:
        response = post(f"{oracle_url()}/v1/chat/completions", request_body(question, evidence, schema), TIMEOUT)
    except (OSError, HTTPException, ValueError) as error:
        note_reachability(not is_connection_failure(error))
        write_log(oracle_log_path(), {**entry, "error": str(error), "seconds": round(time.monotonic() - started, 2)})
        return None
    note_reachability(True)
    reply = reply_of(response)
    write_log(oracle_log_path(), {**entry, "reply": reply, "seconds": round(time.monotonic() - started, 2)})
    return reply


def is_connection_failure(error: Exception) -> bool:
    return isinstance(error, URLError) and not isinstance(error, HTTPError)


def genre_schema(genres: list[str]) -> dict:
    return {"type": "object", "properties": {"genre": {"type": "string", "enum": [*genres, NONE]}}, "required": ["genre"]}


def genre_of(evidence: str, genres: list[str]) -> str | None:
    reply = ask("genre", evidence, genre_schema(genres))
    genre = reply.get("genre") if reply else None
    return genre if genre in (*genres, NONE) else None


def well_formed_name(reply: dict | None) -> bool:
    if not reply or set(reply) != set(NAME_SCHEMA["properties"]):
        return False
    title, authors, confident = reply["title"], reply["authors"], reply["confident"]
    well_typed = isinstance(title, str) and isinstance(confident, bool) and isinstance(authors, list)
    return well_typed and bool(title) and all(isinstance(a, str) for a in authors)


def name_of(evidence: str) -> dict | None:
    reply = ask("name", evidence, NAME_SCHEMA)
    return reply if well_formed_name(reply) else None


def well_formed_group(group) -> bool:
    return isinstance(group, dict) and isinstance(group.get("canonical"), str) and isinstance(group.get("aliases"), list)


def known_group(group: dict, folders: list[str]) -> dict:
    aliases = [a for a in group["aliases"] if a in folders and a != group["canonical"]]
    return {"canonical": group["canonical"], "aliases": aliases}


def author_groups(folders: list[str]) -> list[dict] | None:
    reply = ask("authors", authors_evidence(folders), AUTHORS_SCHEMA)
    groups = reply.get("groups") if reply else None
    if not isinstance(groups, list) or not all(well_formed_group(g) for g in groups):
        return None
    known = (known_group(g, folders) for g in groups if g["canonical"])
    return [g for g in known if g["aliases"]]


def authors_evidence(folders: list[str]) -> str:
    return "\n".join(["Author folders:", *sorted(folders)])
