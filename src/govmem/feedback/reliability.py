"""Reviewer reliability: Beta(alpha, beta) over agreement with gold labels / consensus.
reliability = alpha / (alpha + beta). Hooks:
  calibrate()          explicit gold-label agreement (e.g. seeded audit items)
  consensus_hook()     agreement with a pattern posterior that is already confident
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..config import Settings

CONSENSUS_MIN_EVIDENCE = 10.0
CONSENSUS_WEIGHT = 0.25


def _ensure(conn: sqlite3.Connection, rid: str, s: Settings, ts: float) -> None:
    conn.execute("INSERT OR IGNORE INTO reviewers (reviewer_id,alpha,beta,updated_at) VALUES (?,?,?,?)",
                 (rid, s.reviewer_prior_alpha, s.reviewer_prior_beta, ts))


def get(conn: sqlite3.Connection, rid: str, s: Settings, ts: float) -> float:
    _ensure(conn, rid, s, ts)
    r = conn.execute("SELECT alpha, beta FROM reviewers WHERE reviewer_id=?", (rid,)).fetchone()
    return r["alpha"] / (r["alpha"] + r["beta"])


def calibrate(conn: sqlite3.Connection, rid: str, agreed: bool, s: Settings, ts: float, weight: float = 1.0) -> float:
    _ensure(conn, rid, s, ts)
    col = "alpha" if agreed else "beta"
    conn.execute(f"UPDATE reviewers SET {col}={col}+?, updated_at=? WHERE reviewer_id=?", (weight, ts, rid))
    return get(conn, rid, s, ts)


def consensus_hook(conn: sqlite3.Connection, rid: str, harmful: bool, prior_risk: float, prior_evidence: float,
                   s: Settings, ts: float) -> float | None:
    if prior_evidence < CONSENSUS_MIN_EVIDENCE:
        return None
    agreed = (prior_risk >= 0.5) == harmful
    return calibrate(conn, rid, agreed, s, ts, CONSENSUS_WEIGHT)


def list_reviewers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [{"reviewer_id": r["reviewer_id"], "alpha": r["alpha"], "beta": r["beta"],
             "reliability": round(r["alpha"] / (r["alpha"] + r["beta"]), 4)}
            for r in conn.execute("SELECT * FROM reviewers ORDER BY reviewer_id")]
