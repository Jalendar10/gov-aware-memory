"""Append-only, hash-chained audit log: hash_i = sha256(prev_hash || canonical(event_i))."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from ..util import cjson

GENESIS = "0" * 64


def _digest(prev: str, ts: float, actor: str, event_type: str, entity_type: str, entity_id: str, payload: str) -> str:
    body = cjson([prev, repr(ts), actor, event_type, entity_type, entity_id, payload])
    return hashlib.sha256(body.encode()).hexdigest()


def append(conn: sqlite3.Connection, ts: float, actor: str, event_type: str, entity_type: str,
           entity_id: Any, payload: dict[str, Any] | None = None) -> int:
    prev_row = conn.execute("SELECT hash FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
    prev = prev_row["hash"] if prev_row else GENESIS
    p = cjson(payload or {})
    eid = str(entity_id)
    h = _digest(prev, ts, actor, event_type, entity_type, eid, p)
    cur = conn.execute(
        "INSERT INTO audit_events (ts,actor,event_type,entity_type,entity_id,payload_json,prev_hash,hash) "
        "VALUES (?,?,?,?,?,?,?,?)", (ts, actor, event_type, entity_type, eid, p, prev, h))
    return int(cur.lastrowid)


def recent(conn: sqlite3.Connection, limit: int = 50, event_type: str | None = None) -> list[dict[str, Any]]:
    q, args = "SELECT * FROM audit_events", []
    if event_type:
        q += " WHERE event_type=?"
        args.append(event_type)
    rows = conn.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
    return [{**dict(r), "payload": json.loads(r["payload_json"])} for r in rows]


def verify(conn: sqlite3.Connection) -> dict[str, Any]:
    prev = GENESIS
    n = 0
    for r in conn.execute("SELECT * FROM audit_events ORDER BY id"):
        n += 1
        expect = _digest(prev, r["ts"], r["actor"], r["event_type"], r["entity_type"], r["entity_id"], r["payload_json"])
        if r["prev_hash"] != prev or r["hash"] != expect:
            return {"ok": False, "events": n, "first_bad_id": r["id"]}
        prev = r["hash"]
    return {"ok": True, "events": n, "first_bad_id": None}
