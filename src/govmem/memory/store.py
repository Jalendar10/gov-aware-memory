"""Persistence for episodic memory and promoted pattern memory."""

from __future__ import annotations

import sqlite3
import struct
from dataclasses import dataclass
from typing import Any, Iterable

from ..util import cjson
from .embed import DIM
from .encode import PatternState, decode, encode


def pack_vec(v: list[float]) -> bytes:
    return struct.pack(f"<{DIM}b", *[max(-127, min(127, round(x * 127))) for x in v])


def unpack_vec(b: bytes) -> list[float]:
    return [x / 127.0 for x in struct.unpack(f"<{DIM}b", b)]


@dataclass
class PatternRow:
    id: int
    status: str
    encoding: str
    byte_size: int
    state: PatternState
    created_at: float
    updated_at: float

    def to_dict(self) -> dict[str, Any]:
        s = self.state
        return {
            "id": self.id, "status": self.status, "version": s.version, "encoding": self.encoding,
            "byte_size": self.byte_size, "action": s.action, "resource_class": s.resource_class,
            "context_key": s.context_key, "signature": s.signature.hex(), "support": s.support,
            "alpha": round(s.alpha, 4), "beta": round(s.beta, 4), "risk": round(s.risk, 4),
            "ema_risk": round(s.ema_risk, 4), "reliability": round(s.reliability, 4),
            "usefulness": round(s.usefulness, 4), "first_seen": s.first_seen,
            "last_seen": s.last_seen, "windows": s.windows, "flags": s.flags,
        }


def insert_episode(conn: sqlite3.Connection, *, ts: float, user_id: str, source: str, action: str,
                   resource: str, resource_class: str, context_key: str, context: dict[str, Any],
                   text: str, embedding: list[float], provenance_hash: str) -> int:
    cur = conn.execute(
        "INSERT INTO episodic_memory (ts,user_id,source,action,resource,resource_class,context_key,"
        "context_json,text,embedding,provenance_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (ts, user_id, source, action, resource, resource_class, context_key, cjson(context), text,
         pack_vec(embedding), provenance_hash),
    )
    return int(cur.lastrowid)


def set_episode_route(conn: sqlite3.Connection, episode_id: int, route: str) -> None:
    conn.execute("UPDATE episodic_memory SET routed_to=? WHERE id=?", (route, episode_id))


def _row_to_pattern(r: sqlite3.Row) -> PatternRow:
    st = decode(r["record"], r["encoding"], r["action"], r["resource_class"], r["context_key"], r["version"])
    return PatternRow(r["id"], r["status"], r["encoding"], r["byte_size"], st, r["created_at"], r["updated_at"])


def insert_pattern(conn: sqlite3.Connection, st: PatternState, mode: str, ts: float,
                   source_candidate_id: int | None = None) -> int:
    blob = encode(st, mode)
    cur = conn.execute(
        "INSERT INTO pattern_memory (signature,action,resource_class,context_key,encoding,record,byte_size,"
        "status,version,source_candidate_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,'active',?,?,?,?)",
        (st.signature.hex(), st.action, st.resource_class, st.context_key, mode, blob, len(blob),
         st.version, source_candidate_id, ts, ts),
    )
    return int(cur.lastrowid)


def save_pattern(conn: sqlite3.Connection, pid: int, st: PatternState, mode: str, ts: float,
                 status: str | None = None) -> None:
    blob = encode(st, mode)
    if status is None:
        conn.execute(
            "UPDATE pattern_memory SET record=?, byte_size=?, version=?, context_key=?, updated_at=? WHERE id=?",
            (blob, len(blob), st.version, st.context_key, ts, pid),
        )
    else:
        conn.execute(
            "UPDATE pattern_memory SET record=?, byte_size=?, version=?, context_key=?, status=?, updated_at=? WHERE id=?",
            (blob, len(blob), st.version, st.context_key, status, ts, pid),
        )


def set_status(conn: sqlite3.Connection, pid: int, status: str, ts: float) -> None:
    conn.execute("UPDATE pattern_memory SET status=?, updated_at=? WHERE id=?", (status, ts, pid))


def get_pattern(conn: sqlite3.Connection, pid: int) -> PatternRow | None:
    r = conn.execute("SELECT * FROM pattern_memory WHERE id=?", (pid,)).fetchone()
    return _row_to_pattern(r) if r else None


def list_patterns(conn: sqlite3.Connection, status: str | None = "active",
                  action: str | None = None, resource_class: str | None = None) -> list[PatternRow]:
    q, args = "SELECT * FROM pattern_memory WHERE 1=1", []
    if status:
        q += " AND status=?"
        args.append(status)
    if action:
        q += " AND action=?"
        args.append(action)
    if resource_class is not None:
        q += " AND resource_class=?"
        args.append(resource_class)
    return [_row_to_pattern(r) for r in conn.execute(q + " ORDER BY id", args)]


def add_evidence(conn: sqlite3.Connection, entity_type: str, entity_id: int, episode_id: int,
                 source: str, prov: str, ts: float) -> None:
    conn.execute(
        "INSERT INTO evidence_refs (entity_type,entity_id,episode_id,source,provenance_hash,ts) VALUES (?,?,?,?,?,?)",
        (entity_type, entity_id, episode_id, source, prov, ts),
    )


def evidence_sources(conn: sqlite3.Connection, entity_type: str, entity_id: int) -> dict[str, int]:
    rows = conn.execute(
        "SELECT source, COUNT(*) n FROM evidence_refs WHERE entity_type=? AND entity_id=? GROUP BY source",
        (entity_type, entity_id),
    )
    return {r["source"]: r["n"] for r in rows}


def move_evidence(conn: sqlite3.Connection, from_type: str, from_id: int, to_type: str, to_id: int) -> None:
    conn.execute(
        "INSERT INTO evidence_refs (entity_type,entity_id,episode_id,source,provenance_hash,ts) "
        "SELECT ?,?,episode_id,source,provenance_hash,ts FROM evidence_refs WHERE entity_type=? AND entity_id=?",
        (to_type, to_id, from_type, from_id),
    )


def iter_ids(rows: Iterable[PatternRow]) -> list[int]:
    return [r.id for r in rows]
