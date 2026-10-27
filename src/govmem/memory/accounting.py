"""Byte accounting. The storage budget B applies to active pattern records only."""

from __future__ import annotations

import sqlite3
from typing import Any

from ..db import file_bytes
from .encode import SIZES


def pattern_bytes(conn: sqlite3.Connection, status: str = "active") -> int:
    r = conn.execute("SELECT COALESCE(SUM(byte_size),0) b FROM pattern_memory WHERE status=?", (status,)).fetchone()
    return int(r["b"])


def stats(conn: sqlite3.Connection, budget: int, encoding: str, db_path: str) -> dict[str, Any]:
    q = conn.execute
    by_status = {r["status"]: {"count": r["n"], "bytes": r["b"]} for r in q(
        "SELECT status, COUNT(*) n, COALESCE(SUM(byte_size),0) b FROM pattern_memory GROUP BY status")}
    active = by_status.get("active", {"count": 0, "bytes": 0})
    index_overhead = q(
        "SELECT COALESCE(SUM(LENGTH(signature)+LENGTH(action)+LENGTH(resource_class)+LENGTH(context_key)),0) b "
        "FROM pattern_memory WHERE status='active'").fetchone()["b"]
    epi = q("SELECT COUNT(*) n, COALESCE(SUM(LENGTH(context_json)+LENGTH(text)+LENGTH(embedding)+"
            "LENGTH(action)+LENGTH(resource)+LENGTH(source)+LENGTH(user_id)),0) b FROM episodic_memory").fetchone()
    cand = q("SELECT COUNT(*) n, COALESCE(SUM(LENGTH(centroid)+LENGTH(windows_json)+LENGTH(sources_json)+"
             "LENGTH(context_key)),0) b FROM candidate_quarantine WHERE status IN ('pending','needs_review')").fetchone()
    return {
        "encoding": encoding,
        "record_size_bytes": SIZES[encoding],
        "budget_bytes": budget,
        "pattern_count": active["count"],
        "pattern_bytes": active["bytes"],
        "budget_utilization": round(active["bytes"] / budget, 4) if budget else None,
        "index_overhead_bytes": int(index_overhead),
        "patterns_by_status": by_status,
        "episodic_count": epi["n"],
        "episodic_raw_bytes": int(epi["b"]),
        "quarantine_count": cand["n"],
        "quarantine_bytes": int(cand["b"]),
        "db_file_bytes": file_bytes(db_path),
    }
