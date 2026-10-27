"""Same-pattern vs coincidence filter.

A candidate is a *recurring pattern* (not a coincidence) only if ALL hold:
  support      >= min_support                      (enough repetitions)
  |windows|    >= min_windows                      (temporal diversity: not a single burst)
  |sources|    >= min_sources                      (provenance diversity: not one emitter)
  lift(a, ctx) >= min_lift                         (action/context co-occur at least as often
                                                    as expected under independence, computed
                                                    over the episodic log)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings


@dataclass
class CoincidenceResult:
    passed: bool
    support: int
    windows: int
    sources: int
    lift: float
    failures: list[str] = field(default_factory=list)


def lift(conn: sqlite3.Connection, action: str, context_key: str) -> float:
    q = conn.execute
    n = q("SELECT COUNT(*) c FROM episodic_memory").fetchone()["c"]
    n_a = q("SELECT COUNT(*) c FROM episodic_memory WHERE action=?", (action,)).fetchone()["c"]
    n_c = q("SELECT COUNT(*) c FROM episodic_memory WHERE context_key=?", (context_key,)).fetchone()["c"]
    n_ac = q("SELECT COUNT(*) c FROM episodic_memory WHERE action=? AND context_key=?",
             (action, context_key)).fetchone()["c"]
    if n == 0 or n_a == 0 or n_c == 0:
        return 0.0
    return (n_ac * n) / (n_a * n_c)


def evaluate(conn: sqlite3.Connection, cand: dict[str, Any], s: Settings) -> CoincidenceResult:
    sup, win, src = cand["support"], len(cand["windows"]), len(cand["sources"])
    lf = lift(conn, cand["action"], cand["context_key"])
    fails = []
    if sup < s.min_support:
        fails.append(f"support {sup} < {s.min_support}")
    if win < s.min_windows:
        fails.append(f"windows {win} < {s.min_windows}")
    if src < s.min_sources:
        fails.append(f"sources {src} < {s.min_sources}")
    if lf < s.min_lift:
        fails.append(f"lift {lf:.3f} < {s.min_lift}")
    return CoincidenceResult(not fails, sup, win, src, lf, fails)
