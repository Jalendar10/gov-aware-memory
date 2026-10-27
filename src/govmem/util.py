"""Small shared helpers: hashing, canonical JSON, time."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any


def now() -> float:
    return time.time()


def cjson(obj: Any) -> str:
    """Canonical JSON (sorted keys, no whitespace) for hashing and storage."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def blake(data: str | bytes, size: int) -> bytes:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.blake2b(data, digest_size=size).digest()


def h32(s: str) -> int:
    return int.from_bytes(blake(s, 4), "little")


def signature(action: str, resource_class: str, context_key: str) -> bytes:
    return blake(f"{action}|{resource_class}|{context_key}", 8)


def resource_class(resource: str) -> str:
    """Coarse resource class: the first path segment ("pii/users/42" -> "pii")."""
    return resource.split("/", 1)[0] if resource else ""


def context_key(context: dict[str, Any]) -> str:
    """Canonical key over scalar context fields. Callers should bucket numerics (e.g. amount_band)."""
    items = []
    for k in sorted(context):
        v = context[k]
        if isinstance(v, (str, int, bool)) or v is None:
            items.append(f"{k}={v}")
    return ";".join(items)
