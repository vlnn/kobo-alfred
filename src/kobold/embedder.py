from __future__ import annotations

import json
from http.client import HTTPException
from urllib.request import Request, urlopen

from kobold.config import embed_key, embed_model, embed_url, oracle_key
from kobold.server import headers

LIST_TIMEOUT = 0.5
EMBED_TIMEOUT = 60


def key_for(url: str) -> str:
    return embed_key() if url == embed_url() else oracle_key()


def fetch(url: str, timeout: float, body: dict | None = None) -> dict | None:
    data = json.dumps(body).encode() if body is not None else None
    request = Request(url, data=data, headers=headers(key_for(url.rsplit("/v1/", 1)[0])))
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except (OSError, HTTPException, ValueError):
        return None


def model_ids(listing: dict | None) -> list[str] | None:
    data = listing.get("data") if isinstance(listing, dict) else None
    if not isinstance(data, list) or not all(isinstance(m, dict) and isinstance(m.get("id"), str) for m in data):
        return None
    return [m["id"] for m in data]


def models(url: str) -> list[str] | None:
    return model_ids(fetch(f"{url}/v1/models", LIST_TIMEOUT))


def embedding_of(reply: dict | None) -> list[float] | None:
    try:
        values = reply["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError):
        return None
    return values if isinstance(values, list) and all(isinstance(v, (int, float)) for v in values) else None


def embed(text: str) -> list[float] | None:
    if not embed_model():
        return None
    return embedding_of(fetch(f"{embed_url()}/v1/embeddings", EMBED_TIMEOUT, {"model": embed_model(), "input": text}))
