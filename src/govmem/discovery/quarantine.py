"""Candidate quarantine: create or join candidates. Candidates are never used in decisions."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..context import Ctx
from ..memory import store
from ..memory.embed import normalize
from ..util import signature
from .matcher import best_candidate


def upsert_candidate(ctx: Ctx, *, action: str, resource_class: str, context_key: str, emb: list[float],
                     ts: float, source: str, episode_id: int, prov: str) -> int:
    s = ctx.settings
    window = int(ts // s.window_seconds)
    m = best_candidate(ctx.conn, action, resource_class, emb, s.candidate_threshold)
    now = ctx.clock()
    if m is None:
        cur = ctx.conn.execute(
            "INSERT INTO candidate_quarantine (signature,action,resource_class,context_key,centroid,support,"
            "first_seen,last_seen,windows_json,sources_json,created_at,updated_at) VALUES (?,?,?,?,?,1,?,?,?,?,?,?)",
            (signature(action, resource_class, context_key).hex(), action, resource_class, context_key,
             store.pack_vec(emb), ts, ts, json.dumps([window]), json.dumps({source: 1}), now, now))
        cid = int(cur.lastrowid)
    else:
        cid = m.id
        r = ctx.conn.execute("SELECT * FROM candidate_quarantine WHERE id=?", (cid,)).fetchone()
        n = r["support"]
        centroid = store.unpack_vec(r["centroid"])
        centroid = normalize([(c * n + e) / (n + 1) for c, e in zip(centroid, emb)])
        windows = set(json.loads(r["windows_json"])) | {window}
        sources: dict[str, int] = json.loads(r["sources_json"])
        sources[source] = sources.get(source, 0) + 1
        ctx.conn.execute(
            "UPDATE candidate_quarantine SET centroid=?, support=support+1, first_seen=MIN(first_seen,?), "
            "last_seen=MAX(last_seen,?), windows_json=?, sources_json=?, updated_at=? WHERE id=?",
            (store.pack_vec(centroid), ts, ts, json.dumps(sorted(windows)), json.dumps(sources), now, cid))
    store.add_evidence(ctx.conn, "candidate", cid, episode_id, source, prov, ts)
    return cid


def get_candidate(conn: sqlite3.Connection, cid: int) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM candidate_quarantine WHERE id=?", (cid,)).fetchone()
    return candidate_dict(r) if r else None


def candidate_dict(r: sqlite3.Row) -> dict[str, Any]:
    d = {k: r[k] for k in r.keys() if k not in ("centroid", "windows_json", "sources_json", "flags_json")}
    d["windows"] = json.loads(r["windows_json"])
    d["sources"] = json.loads(r["sources_json"])
    d["flags"] = json.loads(r["flags_json"])
    return d


def list_candidates(conn: sqlite3.Connection, statuses: tuple[str, ...] = ("pending", "needs_review")) -> list[dict[str, Any]]:
    qs = ",".join("?" * len(statuses))
    rows = conn.execute(f"SELECT * FROM candidate_quarantine WHERE status IN ({qs}) ORDER BY id", statuses)
    return [candidate_dict(r) for r in rows]
