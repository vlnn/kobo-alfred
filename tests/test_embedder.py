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
