"""Pattern snapshots + rollback, and a provenance-based source purge (poisoning response)."""

from __future__ import annotations

import sqlite3
from typing import Any

from ..memory import store
from . import log


def snapshot(conn: sqlite3.Connection, pid: int, reason: str, ts: float) -> None:
    r = conn.execute("SELECT * FROM pattern_memory WHERE id=?", (pid,)).fetchone()
    if r is None:
        return
    conn.execute(
        "INSERT OR REPLACE INTO pattern_snapshots (pattern_id,version,status,record,context_key,reason,ts) "
        "VALUES (?,?,?,?,?,?,?)", (pid, r["version"], r["status"], r["record"], r["context_key"], reason, ts))


def list_snapshots(conn: sqlite3.Connection, pid: int) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT pattern_id,version,status,reason,ts,LENGTH(record) bytes FROM pattern_snapshots "
                        "WHERE pattern_id=? ORDER BY version", (pid,))
    return [dict(r) for r in rows]


def rollback_pattern(conn: sqlite3.Connection, pid: int, to_version: int, actor: str, ts: float) -> dict[str, Any]:
    snap = conn.execute("SELECT * FROM pattern_snapshots WHERE pattern_id=? AND version=?", (pid, to_version)).fetchone()
    cur = conn.execute("SELECT * FROM pattern_memory WHERE id=?", (pid,)).fetchone()
    if snap is None or cur is None:
        raise KeyError(f"no snapshot v{to_version} for pattern {pid}")
    snapshot(conn, pid, "pre-rollback", ts)
    new_version = int(cur["version"]) + 1
    conn.execute(
        "UPDATE pattern_memory SET record=?, byte_size=?, status=?, context_key=?, version=?, updated_at=? WHERE id=?",
        (snap["record"], len(snap["record"]), snap["status"], snap["context_key"], new_version, ts, pid))
    snapshot(conn, pid, f"rollback-to-v{to_version}", ts)
    log.append(conn, ts, actor, "pattern_rollback", "pattern", pid,
               {"from_version": cur["version"], "restored_version": to_version, "new_version": new_version})
    row = store.get_pattern(conn, pid)
    return row.to_dict() if row else {}


def purge_source(conn: sqlite3.Connection, source: str, actor: str, ts: float) -> dict[str, Any]:
    """Reject pending candidates and re-quarantine active patterns whose evidence is dominated
    (>50%) by `source`. Patterns are snapshotted, not deleted, so this is itself reversible."""
    cands = [r["entity_id"] for r in conn.execute(
        "SELECT DISTINCT entity_id FROM evidence_refs WHERE entity_type='candidate' AND source=?", (source,))]
    rejected = []
    for cid in cands:
        c = conn.execute("SELECT status FROM candidate_quarantine WHERE id=?", (cid,)).fetchone()
        if c and c["status"] in ("pending", "needs_review"):
            conn.execute("UPDATE candidate_quarantine SET status='rejected', review_verdict='reject', "
                         "reviewer_id=?, updated_at=? WHERE id=?", (actor, ts, cid))
            rejected.append(cid)
    requarantined = []
    pids = [r["entity_id"] for r in conn.execute(
        "SELECT DISTINCT entity_id FROM evidence_refs WHERE entity_type='pattern' AND source=?", (source,))]
    for pid in pids:
        srcs = store.evidence_sources(conn, "pattern", pid)
        total = sum(srcs.values()) or 1
        row = conn.execute("SELECT status FROM pattern_memory WHERE id=?", (pid,)).fetchone()
        if row and row["status"] == "active" and srcs.get(source, 0) / total > 0.5:
            snapshot(conn, pid, f"pre-purge:{source}", ts)
            conn.execute("UPDATE pattern_memory SET status='quarantined', version=version+1, updated_at=? WHERE id=?",
                         (ts, pid))
            snapshot(conn, pid, f"purged:{source}", ts)
            requarantined.append(pid)
    conn.execute("INSERT OR REPLACE INTO source_trust (source,trust,updated_at) VALUES (?,0.0,?)", (source, ts))
    log.append(conn, ts, actor, "source_purged", "source", source,
               {"rejected_candidates": rejected, "requarantined_patterns": requarantined})
    return {"source": source, "rejected_candidates": rejected, "requarantined_patterns": requarantined}
