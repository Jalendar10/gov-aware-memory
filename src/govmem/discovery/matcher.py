"""Similarity routing: does an event belong to an existing pattern / candidate?"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from ..memory import store
from ..memory.embed import cosine
from ..memory.store import PatternRow


@dataclass
class Match:
    id: int
    similarity: float


def best_pattern(conn: sqlite3.Connection, action: str, resource_class: str, emb: list[float],
                 threshold: float) -> tuple[PatternRow, float] | None:
    best: tuple[PatternRow, float] | None = None
    for row in store.list_patterns(conn, "active", action, resource_class):
        sim = cosine(emb, row.state.centroid)
        if sim >= threshold and (best is None or sim > best[1]):
            best = (row, sim)
    return best


def best_candidate(conn: sqlite3.Connection, action: str, resource_class: str, emb: list[float],
                   threshold: float) -> Match | None:
    best: Match | None = None
    rows = conn.execute(
        "SELECT id, centroid FROM candidate_quarantine WHERE status IN ('pending','needs_review') "
        "AND action=? AND resource_class=?", (action, resource_class))
    for r in rows:
        sim = cosine(emb, store.unpack_vec(r["centroid"]))
        if sim >= threshold and (best is None or sim > best.similarity):
            best = Match(r["id"], sim)
    return best


def top_k_patterns(conn: sqlite3.Connection, emb: list[float], k: int, action: str | None = None,
                   resource_class: str | None = None) -> list[tuple[PatternRow, float]]:
    scored = [(row, cosine(emb, row.state.centroid))
              for row in store.list_patterns(conn, "active", action, resource_class)]
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:k]


def candidate_sources(row: sqlite3.Row) -> dict[str, int]:
    return json.loads(row["sources_json"])
