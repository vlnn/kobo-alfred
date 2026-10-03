import io
import json
from pathlib import Path
from urllib.error import URLError

import pytest

from kobold import oracle


def reply(content) -> io.BytesIO:
    body = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    return io.BytesIO(json.dumps(body).encode())


class Responding:
    def __init__(self, content):
        self.body = reply(content)

    def __enter__(self):
        return self.body

    def __exit__(self, *_):
        return False


@pytest.fixture
def server(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("KOBOLD_ORACLE_URL", "http://127.0.0.1:8080/")
    monkeypatch.delenv("KOBOLD_ORACLE_MODEL", raising=False)
    monkeypatch.setenv("KOBOLD_DATA", str(tmp_path / "data"))


@pytest.fixture
def answering(server, mocker):
    return mocker.patch("kobold.oracle.urlopen", return_value=Responding(json.dumps({"genre": "fiction/spy"})))


def sent(urlopen) -> dict:
    request = urlopen.call_args.args[0]
    return json.loads(request.data)


def test_ask_posts_a_schema_constrained_request(answering):
    schema = {"type": "object", "properties": {"genre": {"enum": ["fiction/spy", "none"]}}}

    answer = oracle.ask("genre", "Title: Tinker Tailor", schema)

    request = answering.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:8080/v1/chat/completions", "the request goes to the OpenAI-compatible endpoint"
    assert request.get_header("Content-type") == "application/json", "the body is JSON"
    body = sent(answering)
    assert body["temperature"] == 0 and body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "genre", "schema": schema},
    }, "the schema becomes a grammar on the server; temperature 0 keeps answers stable"
    assert [m["role"] for m in body["messages"]] == ["system", "user"] and body["messages"][1]["content"] == "Title: Tinker Tailor", (
        "the evidence is the user message"
    )
    assert "model" not in body, "without a configured model the server's default answers"
    assert answering.call_args.kwargs["timeout"] == oracle.TIMEOUT, "every request has the design's timeout"
    assert answer == {"genre": "fiction/spy"}, "the reply content is parsed as JSON"


def test_ask_names_the_configured_model(answering, monkeypatch):
    monkeypatch.setenv("KOBOLD_ORACLE_MODEL", "qwen2.5-7b-instruct")

    oracle.ask("genre", "x", {})

    assert sent(answering)["model"] == "qwen2.5-7b-instruct", "a configured model is named so a router loads it"


def test_ask_without_a_url_does_nothing(monkeypatch, mocker):
    monkeypatch.delenv("KOBOLD_ORACLE_URL", raising=False)
    urlopen = mocker.patch("kobold.oracle.urlopen")

    assert oracle.ask("genre", "x", {}) is None and not urlopen.called, "the oracle is off until KOBOLD_ORACLE_URL is set"


@pytest.mark.parametrize("error", [URLError("connection refused"), TimeoutError("timed out"), OSError("reset")])
def test_connection_errors_and_timeouts_become_none(server, mocker, error):
    mocker.patch("kobold.oracle.urlopen", side_effect=error)

    assert oracle.ask("genre", "x", {}) is None, f"{error!r} is a skip, not a failure"


@pytest.mark.parametrize("content", ["not json", json.dumps(["a", "list"]), json.dumps(None)])
def test_malformed_replies_become_none(server, mocker, content):
    mocker.patch("kobold.oracle.urlopen", return_value=Responding(content))

    assert oracle.ask("genre", "x", {}) is None, f"{content!r} is not an answer"


def test_ask_logs_prompt_reply_and_duration(answering, tmp_path: Path):
    oracle.ask("genre", "Title: Tinker Tailor", {})

    (entry,) = [json.loads(line) for line in (tmp_path / "data" / "oracle.log").read_text(encoding="utf-8").splitlines()]
    assert entry["question"] == "genre" and entry["prompt"] == "Title: Tinker Tailor", "the log says what was asked"
    assert entry["reply"] == {"genre": "fiction/spy"} and entry["seconds"] >= 0, "and what came back, and how long it took"


def test_connection_failure_is_remembered_until_the_next_answer(server, mocker, tmp_path: Path):
    mocker.patch("kobold.oracle.urlopen", side_effect=URLError("connection refused"))
    oracle.ask("genre", "x", {})

    assert oracle.unreachable() == "http://127.0.0.1:8080", "a failed connection leaves a note for the script filters"

    mocker.patch("kobold.oracle.urlopen", return_value=Responding(json.dumps({"genre": "none"})))
    oracle.ask("genre", "x", {})

    assert oracle.unreachable() == "", "an answer clears the note"


def test_a_note_about_another_server_is_not_shown(server, mocker, monkeypatch):
    mocker.patch("kobold.oracle.urlopen", side_effect=URLError("connection refused"))
    oracle.ask("genre", "x", {})
    monkeypatch.setenv("KOBOLD_ORACLE_URL", "http://127.0.0.1:9090")

    assert oracle.unreachable() == "", "changing the server forgets that the old one was down"


def test_genre_of_accepts_only_known_genres_or_none(server, mocker):
    ask = mocker.patch("kobold.oracle.ask", side_effect=[{"genre": "fiction/spy"}, {"genre": "none"}, {"genre": "made/up"}, None])

    assert oracle.genre_of("evidence", ["fiction/spy"]) == "fiction/spy", "a listed genre is accepted"
    assert oracle.genre_of("evidence", ["fiction/spy"]) == "none", "none is an answer too"
    assert oracle.genre_of("evidence", ["fiction/spy"]) is None, "a genre outside the list is no answer"
    assert oracle.genre_of("evidence", ["fiction/spy"]) is None, "no reply is no answer"
    assert ask.call_args.args[2]["properties"]["genre"]["enum"] == ["fiction/spy", "none"], "the schema offers the known genres and none"


@pytest.mark.parametrize(
    "reply, expected",
    [
        (
            {"title": "Nova", "authors": ["Delany, Samuel R."], "confident": True},
            {"title": "Nova", "authors": ["Delany, Samuel R."], "confident": True},
        ),
        ({"title": "Nova", "authors": [], "confident": False}, {"title": "Nova", "authors": [], "confident": False}),
        ({"title": "", "authors": ["x"], "confident": True}, None),
        ({"title": "Nova", "authors": "Delany", "confident": True}, None),
        ({"title": "Nova", "authors": [1], "confident": True}, None),
        ({"title": "Nova", "authors": []}, None),
        (None, None),
    ],
)
def test_name_of_accepts_only_a_well_formed_answer(server, mocker, reply, expected):
    ask = mocker.patch("kobold.oracle.ask", return_value=reply)

    assert oracle.name_of("evidence") == expected, f"{reply!r} should give {expected!r}"
    assert set(ask.call_args.args[2]["properties"]) == {"title", "authors", "confident"}, (
        "the schema asks for title, authors and confidence only"
    )


FOLDERS = ["Delany, Samuel R.", "Delany, Samuel", "Дилэни, Сэмюэл", "Newport, Cal"]


@pytest.mark.parametrize(
    "reply, expected",
    [
        (
            {"groups": [{"canonical": "Delany, Samuel R.", "aliases": ["Delany, Samuel", "Дилэни, Сэмюэл"]}]},
            [{"canonical": "Delany, Samuel R.", "aliases": ["Delany, Samuel", "Дилэни, Сэмюэл"]}],
        ),
        (
            {"groups": [{"canonical": "Delany, Samuel R.", "aliases": ["Delany, Samuel R.", "Delany, Samuel", "Nobody, At All"]}]},
            [{"canonical": "Delany, Samuel R.", "aliases": ["Delany, Samuel"]}],
        ),
        ({"groups": [{"canonical": "Delany, Samuel R.", "aliases": ["Nobody, At All"]}]}, []),
        ({"groups": [{"canonical": "", "aliases": ["Delany, Samuel"]}]}, []),
        ({"groups": "nope"}, None),
        ({"groups": [{"canonical": "x"}]}, None),
        (None, None),
    ],
)
def test_author_groups_keeps_only_groups_of_known_folders(server, mocker, reply, expected):
    ask = mocker.patch("kobold.oracle.ask", return_value=reply)

    assert oracle.author_groups(FOLDERS) == expected, f"{reply!r} should give {expected!r}"
    assert "Delany, Samuel R." in ask.call_args.args[1] and "Дилэни, Сэмюэл" in ask.call_args.args[1], "the evidence is the folder list"


def test_ask_sends_the_api_key_when_one_is_configured(answering, monkeypatch):
    monkeypatch.setenv("KOBOLD_ORACLE_KEY", "sk-local")

    oracle.ask("genre", "x", {})

    assert answering.call_args.args[0].get_header("Authorization") == "Bearer sk-local", (
        "a server started with --api-key wants a bearer token"
    )


def test_ask_sends_no_authorization_without_a_key(answering):
    oracle.ask("genre", "x", {})

    assert answering.call_args.args[0].get_header("Authorization") is None, "without a key the request carries no token"


@pytest.mark.parametrize("question, budget", [("genre", 64), ("name", 256), ("authors", 4096)])
def test_ask_caps_the_answer_and_turns_thinking_off(answering, question, budget):
    oracle.ask(question, "x", {})

    body = sent(answering)
    assert body["max_tokens"] == budget, "a runaway answer stops short of the timeout"
    assert body["chat_template_kwargs"] == {"enable_thinking": False} and body["reasoning_effort"] == "low", (
        "a thinking model is asked to answer, not to reason first"
    )


def test_log_is_appended_not_rewritten(answering, tmp_path: Path, mocker):
    log = tmp_path / "data" / "oracle.log"
    log.parent.mkdir()
    log.write_text('{"prompt": "older"}\n', encoding="utf-8")
    write_text = mocker.spy(Path, "write_text")

    oracle.ask("genre", "newer", {})

    assert [json.loads(line)["prompt"] for line in log.read_text(encoding="utf-8").splitlines()] == ["older", "newer"], "one line appended"
    assert not any(c.args[0] == log for c in write_text.call_args_list), "concurrent passes must not rewrite each other's lines"


def test_trim_log_keeps_the_newest_entries(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(oracle, "LOG_ENTRIES", 2)
    log = tmp_path / "oracle.log"
    log.write_text("".join(f'{{"prompt": "{i}"}}\n' for i in range(5)), encoding="utf-8")

    oracle.trim_log(log)

    assert [json.loads(line)["prompt"] for line in log.read_text(encoding="utf-8").splitlines()] == ["3", "4"], "trimmed to the newest"
    oracle.trim_log(tmp_path / "missing.log")
