from __future__ import annotations

import json
from http.client import HTTPException
from urllib.request import Request, urlopen

LIST_TIMEOUT = 0.5


def fetch(url: str, timeout: float, body: dict | None = None) -> dict | None:
    data = json.dumps(body).encode() if body is not None else None
    request = Request(url, data=data, headers={"Content-Type": "application/json"})
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
