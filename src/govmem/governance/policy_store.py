"""Versioned policy store. Policies change only through propose -> approve (human), retire, or
rollback, each requiring an approver and each audited. Memory/discovery actors are refused."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..audit import log
from ..util import now as _now
from .models import Policy

FORBIDDEN_ACTOR_PREFIXES = ("memory", "discovery", "consolidation", "feedback", "llm")


class PolicyWriteForbidden(PermissionError):
    pass


def _check_actor(actor: str) -> None:
    if not actor or actor.lower().startswith(FORBIDDEN_ACTOR_PREFIXES):
        raise PolicyWriteForbidden(f"actor '{actor}' may not modify policies")


def _row(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    d["match"] = json.loads(d.pop("match_json"))
    return d


def active_policies(conn: sqlite3.Connection) -> list[Policy]:
    rows = conn.execute("SELECT * FROM policies WHERE status='active'")
    return [Policy(r["id"], r["policy_key"], r["version"], r["effect"], r["priority"],
                   json.loads(r["match_json"]), r["risk_review_threshold"]) for r in rows]


def list_policies(conn: sqlite3.Connection, status: str | None = None) -> list[dict[str, Any]]:
    if status:
        rows = conn.execute("SELECT * FROM policies WHERE status=? ORDER BY policy_key, version", (status,))
    else:
        rows = conn.execute("SELECT * FROM policies ORDER BY policy_key, version")
    return [_row(r) for r in rows]


def propose(conn: sqlite3.Connection, key: str, effect: str, match: dict[str, Any], priority: int,
            proposed_by: str, risk_review_threshold: float | None = None, ts: float | None = None) -> dict[str, Any]:
    _check_actor(proposed_by)
    if effect not in ("allow", "deny", "review"):
        raise ValueError("effect must be allow|deny|review")
    ts = ts or _now()
    v = conn.execute("SELECT COALESCE(MAX(version),0)+1 v FROM policies WHERE policy_key=?", (key,)).fetchone()["v"]
    cur = conn.execute(
        "INSERT INTO policies (policy_key,version,effect,priority,match_json,risk_review_threshold,status,"
        "proposed_by,created_at,updated_at) VALUES (?,?,?,?,?,?,'proposed',?,?,?)",
        (key, v, effect, priority, json.dumps(match, sort_keys=True), risk_review_threshold, proposed_by, ts, ts))
    pid = int(cur.lastrowid)
    log.append(conn, ts, proposed_by, "policy_proposed", "policy", pid, {"key": key, "version": v, "effect": effect})
    return get(conn, pid)


def get(conn: sqlite3.Connection, pid: int) -> dict[str, Any]:
    r = conn.execute("SELECT * FROM policies WHERE id=?", (pid,)).fetchone()
    if r is None:
        raise KeyError(pid)
    return _row(r)


def approve(conn: sqlite3.Connection, pid: int, approver: str, approved: bool, ts: float | None = None) -> dict[str, Any]:
    """Approval flag must be explicitly True to activate. Activation retires the previous active version."""
    _check_actor(approver)
    ts = ts or _now()
    p = get(conn, pid)
    if p["status"] != "proposed":
        raise ValueError(f"policy {pid} is {p['status']}, not proposed")
    if not approved:
        conn.execute("UPDATE policies SET status='rejected', approved_by=?, updated_at=? WHERE id=?", (approver, ts, pid))
        log.append(conn, ts, approver, "policy_rejected", "policy", pid, {"key": p["policy_key"]})
        return get(conn, pid)
    conn.execute("UPDATE policies SET status='retired', updated_at=? WHERE policy_key=? AND status='active'",
                 (ts, p["policy_key"]))
    conn.execute("UPDATE policies SET status='active', approved_by=?, updated_at=? WHERE id=?", (approver, ts, pid))
    log.append(conn, ts, approver, "policy_activated", "policy", pid, {"key": p["policy_key"], "version": p["version"]})
    return get(conn, pid)


def retire(conn: sqlite3.Connection, key: str, approver: str, ts: float | None = None) -> int:
    _check_actor(approver)
    ts = ts or _now()
    n = conn.execute("UPDATE policies SET status='retired', approved_by=?, updated_at=? WHERE policy_key=? AND status='active'",
                     (approver, ts, key)).rowcount
    log.append(conn, ts, approver, "policy_retired", "policy", key, {"rows": n})
    return n


def rollback(conn: sqlite3.Connection, key: str, to_version: int, approver: str, ts: float | None = None) -> dict[str, Any]:
    """Re-activate an earlier version of a policy (requires an approver)."""
    _check_actor(approver)
    ts = ts or _now()
    r = conn.execute("SELECT id FROM policies WHERE policy_key=? AND version=?", (key, to_version)).fetchone()
    if r is None:
        raise KeyError(f"{key} v{to_version}")
    conn.execute("UPDATE policies SET status='retired', updated_at=? WHERE policy_key=? AND status='active'", (ts, key))
    conn.execute("UPDATE policies SET status='active', approved_by=?, updated_at=? WHERE id=?", (approver, ts, r["id"]))
    log.append(conn, ts, approver, "policy_rollback", "policy", r["id"], {"key": key, "to_version": to_version})
    return get(conn, r["id"])


DEFAULT_POLICIES: list[dict[str, Any]] = [
    {"key": "deny-pii-export", "effect": "deny", "priority": 100,
     "match": {"actions": ["export"], "resource_prefix": "pii/", "roles_none": ["privacy_officer"]}},
    {"key": "review-high-value-transfer", "effect": "review", "priority": 50,
     "match": {"actions": ["transfer"], "context_equals": {"amount_band": "high"}}},
    {"key": "allow-read", "effect": "allow", "priority": 10, "match": {"actions": ["read"]}},
    {"key": "allow-transfer", "effect": "allow", "priority": 10, "match": {"actions": ["transfer"]},
     "risk_review_threshold": 0.6},
]


def seed_defaults(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) c FROM policies").fetchone()["c"]:
        return
    for p in DEFAULT_POLICIES:
        row = propose(conn, p["key"], p["effect"], p["match"], p["priority"], "seed:admin",
                      p.get("risk_review_threshold"))
        approve(conn, row["id"], "seed:admin", True)
