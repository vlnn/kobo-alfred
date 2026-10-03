from __future__ import annotations


def headers(key: str) -> dict[str, str]:
    return {"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})}
