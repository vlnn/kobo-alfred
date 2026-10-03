from __future__ import annotations

import json
import time
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from kobolib.config import oracle_log_path, oracle_model, oracle_status_path, oracle_url

TIMEOUT = 60
LOG_ENTRIES = 500
NONE = "none"
PROMPTS = {
    "genre": "You file ebooks in a personal library. Given what is known about one book, choose the genre it belongs under "
    "from the list of known genres. Answer none when you are not reasonably sure. Answer with JSON only.",
    "name": "You catalogue ebooks whose file names carry no usable information. Given what is known about one book, state "
    "its real title and its authors as a library catalogue would write them, each author as Surname, Given. Never invent: "
    "when the evidence does not say, answer confident false. Answer with JSON only.",
}
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
        "response_format": {"type": "json_schema", "json_schema": {"name": question, "schema": schema}},
    }
    return {**body, "model": oracle_model()} if oracle_model() else body


def post(url: str, body: dict, timeout: float) -> dict:
    data = json.dumps(body).encode()
    request = Request(url, data=data, headers={"Content-Type": "application/json"})
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
    kept = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [*kept, json.dumps(entry, ensure_ascii=False)][-LOG_ENTRIES:]
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


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
