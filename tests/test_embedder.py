import io
import json
from urllib.error import URLError

import pytest

from kobolib import embedder


class Responding:
    def __init__(self, body: dict):
        self.body = io.BytesIO(json.dumps(body).encode())

    def __enter__(self):
        return self.body

    def __exit__(self, *_):
        return False


def test_models_lists_what_the_server_serves(mocker):
    body = {"object": "list", "data": [{"id": "qwen2.5-7b-instruct", "object": "model"}, {"id": "bge-m3", "object": "model"}]}
    urlopen = mocker.patch("kobolib.embedder.urlopen", return_value=Responding(body))

    assert embedder.models("http://127.0.0.1:8080") == ["qwen2.5-7b-instruct", "bge-m3"], "the ids are the rows kb model shows"
    assert urlopen.call_args.args[0].full_url == "http://127.0.0.1:8080/v1/models", "the list comes from the OpenAI-compatible endpoint"
    assert urlopen.call_args.kwargs["timeout"] == embedder.LIST_TIMEOUT == 0.5, "the only request on the hot path has a half-second timeout"


@pytest.mark.parametrize("error", [URLError("refused"), TimeoutError(), OSError("reset")])
def test_models_is_none_when_the_server_is_down(mocker, error):
    mocker.patch("kobolib.embedder.urlopen", side_effect=error)

    assert embedder.models("http://127.0.0.1:8080") is None, "a server that does not answer has no list"


@pytest.mark.parametrize("body", [{"data": "nope"}, {"nothing": []}, {"data": [{"name": "x"}]}])
def test_models_is_none_for_a_malformed_list(mocker, body):
    mocker.patch("kobolib.embedder.urlopen", return_value=Responding(body))

    assert embedder.models("http://127.0.0.1:8080") is None, f"{body!r} is not a model list"


@pytest.fixture
def embedding_server(monkeypatch):
    monkeypatch.setenv("KOBO_ORACLE_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("KOBO_EMBED_URL", "http://127.0.0.1:8081/")
    monkeypatch.setenv("KOBO_EMBED_MODEL", "bge-m3")


def test_embed_posts_the_text_to_the_embedding_server(embedding_server, mocker):
    urlopen = mocker.patch("kobolib.embedder.urlopen", return_value=Responding({"data": [{"embedding": [0.1, 0.2, 0.3]}]}))

    assert embedder.embed("Title: Nova") == [0.1, 0.2, 0.3], "the embedding comes back as a list of floats"

    request = urlopen.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:8081/v1/embeddings", "the embedding server has its own URL"
    assert json.loads(request.data) == {"model": "bge-m3", "input": "Title: Nova"}, "the configured model embeds the text"
    assert urlopen.call_args.kwargs["timeout"] == embedder.EMBED_TIMEOUT, "an embedding request has the design's timeout"


@pytest.mark.parametrize("body", [{"data": []}, {"data": [{"embedding": "x"}]}, {"data": [{"embedding": [1, "a"]}]}, {}])
def test_embed_is_none_for_a_malformed_reply(embedding_server, mocker, body):
    mocker.patch("kobolib.embedder.urlopen", return_value=Responding(body))

    assert embedder.embed("x") is None, f"{body!r} is not an embedding"


def test_embed_is_none_without_an_embedding_model(embedding_server, monkeypatch, mocker):
    monkeypatch.delenv("KOBO_EMBED_MODEL")
    urlopen = mocker.patch("kobolib.embedder.urlopen")

    assert embedder.embed("x") is None and not urlopen.called, "no model, no request"


def test_embed_and_models_send_the_embedding_servers_key(embedding_server, monkeypatch, mocker):
    monkeypatch.setenv("KOBO_ORACLE_KEY", "sk-oracle")
    monkeypatch.setenv("KOBO_EMBED_KEY", "sk-embed")
    urlopen = mocker.patch("kobolib.embedder.urlopen", return_value=Responding({"data": [{"embedding": [0.1]}]}))

    embedder.embed("x")
    assert urlopen.call_args.args[0].get_header("Authorization") == "Bearer sk-embed", "the embedding server has its own key"

    embedder.models("http://127.0.0.1:8081")
    assert urlopen.call_args.args[0].get_header("Authorization") == "Bearer sk-embed", "the list uses the key of the server it asks"

    embedder.models("http://127.0.0.1:8080")
    assert urlopen.call_args.args[0].get_header("Authorization") == "Bearer sk-oracle", "the oracle server's list uses the oracle key"


@pytest.mark.parametrize(
    ("url", "key"),
    [("http://127.0.0.1:8081", "sk-embed"), ("http://127.0.0.1:8080", "sk-oracle"), ("http://127.0.0.1:7070", "sk-oracle")],
)
def test_key_for_is_the_embedding_key_only_on_the_embedding_server(embedding_server, monkeypatch, url, key):
    monkeypatch.setenv("KOBO_ORACLE_KEY", "sk-oracle")
    monkeypatch.setenv("KOBO_EMBED_KEY", "sk-embed")

    assert embedder.key_for(url) == key, f"{url} should be sent {key}"


def test_the_oracle_and_the_embedder_build_the_same_headers():
    from kobolib import oracle, server

    assert oracle.headers is embedder.headers is server.headers, "one place decides how a key is sent"
    assert server.headers("") == {"Content-Type": "application/json"}, "no key, no Authorization header"
    assert server.headers("sk")["Authorization"] == "Bearer sk", "a key goes as a bearer token"


def test_embed_key_falls_back_to_the_oracle_key(embedding_server, monkeypatch, mocker):
    monkeypatch.setenv("KOBO_ORACLE_KEY", "sk-one")
    monkeypatch.delenv("KOBO_EMBED_KEY", raising=False)
    urlopen = mocker.patch("kobolib.embedder.urlopen", return_value=Responding({"data": [{"embedding": [0.1]}]}))

    embedder.embed("x")

    assert urlopen.call_args.args[0].get_header("Authorization") == "Bearer sk-one", "one key for both servers is the common case"
