"""Event embeddings.

Default: signed feature hashing into DIM=32 dimensions (offline, deterministic).
Token weights emphasise structure over free text so that the same behavioural pattern
with different wording stays close, while a different context value moves it apart:

    a:<action> x3, r:<resource_class> x2, c:<k>=<v> x1 each, w:<word> x0.2 each

Optional: sentence-transformers (GOVMEM_EMBEDDER=st) projected to DIM with a seeded
random matrix, concatenated with the structural hash vector. Not required for tests.
"""

from __future__ import annotations

import math
import re
from typing import Any, Protocol, Sequence

from ..util import blake

DIM = 32
_WORD = re.compile(r"[a-z0-9_]+")


def structural_tokens(action: str, resource_class: str, context: dict[str, Any], text: str) -> list[tuple[str, float]]:
    toks: list[tuple[str, float]] = [(f"a:{action}", 3.0), (f"r:{resource_class}", 2.0)]
    for k in sorted(context):
        v = context[k]
        if isinstance(v, (str, int, bool)) or v is None:
            toks.append((f"c:{k}={v}", 1.0))
    for w in _WORD.findall(text.lower())[:32]:
        toks.append((f"w:{w}", 0.2))
    return toks


def normalize(v: Sequence[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 0 else list(v)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


class Embedder(Protocol):
    name: str

    def embed(self, action: str, resource_class: str, context: dict[str, Any], text: str) -> list[float]: ...


class HashEmbedder:
    name = "hash32"

    def embed(self, action: str, resource_class: str, context: dict[str, Any], text: str) -> list[float]:
        v = [0.0] * DIM
        for tok, w in structural_tokens(action, resource_class, context, text):
            h = int.from_bytes(blake(tok, 8), "little")
            idx = h % DIM
            sign = 1.0 if (h >> 32) & 1 else -1.0
            v[idx] += sign * w
        return normalize(v)


class SentenceTransformerEmbedder:  # pragma: no cover - optional dependency
    """Structural hash (weight 0.8) + projected sentence embedding of the text (weight 0.2)."""

    name = "st+hash32"

    def __init__(self, model_name: str) -> None:
        import random

        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        d = self._model.get_sentence_embedding_dimension()
        rng = random.Random(1234)
        self._proj = [[rng.gauss(0, 1) for _ in range(d)] for _ in range(DIM)]
        self._hash = HashEmbedder()

    def embed(self, action: str, resource_class: str, context: dict[str, Any], text: str) -> list[float]:
        base = self._hash.embed(action, resource_class, context, "")
        if not text:
            return base
        e = self._model.encode([text])[0]
        p = normalize([sum(r[i] * e[i] for i in range(len(e))) for r in self._proj])
        return normalize([0.8 * b + 0.2 * q for b, q in zip(base, p)])


def make_embedder(kind: str, st_model: str = "all-MiniLM-L6-v2") -> Embedder:
    if kind == "st":
        return SentenceTransformerEmbedder(st_model)
    return HashEmbedder()
