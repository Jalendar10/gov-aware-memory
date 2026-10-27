"""Source trust registry used by the poisoning filter."""

from __future__ import annotations

import sqlite3


def get_trust(conn: sqlite3.Connection, source: str, default: float) -> float:
    r = conn.execute("SELECT trust FROM source_trust WHERE source=?", (source,)).fetchone()
    return float(r["trust"]) if r else default


def set_trust(conn: sqlite3.Connection, source: str, trust: float, ts: float) -> None:
    conn.execute("INSERT OR REPLACE INTO source_trust (source,trust,updated_at) VALUES (?,?,?)",
                 (source, max(0.0, min(1.0, trust)), ts))


def list_trust(conn: sqlite3.Connection) -> dict[str, float]:
    return {r["source"]: r["trust"] for r in conn.execute("SELECT source, trust FROM source_trust")}
