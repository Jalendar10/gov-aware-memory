"""SQLite connection + schema bootstrap."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL" if path != ":memory:" else "PRAGMA journal_mode=MEMORY")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())


def file_bytes(path: str) -> int:
    if path == ":memory:":
        return 0
    total = 0
    for suffix in ("", "-wal", "-shm"):
        p = path + suffix
        if os.path.exists(p):
            total += os.path.getsize(p)
    return total


if __name__ == "__main__":  # `python -m govmem.db` : create/migrate the DB (used by docker db-init)
    from .config import Settings
    from .governance.policy_store import seed_defaults

    s = Settings.from_env()
    c = connect(s.db_path)
    init_schema(c)
    seed_defaults(c)
    print(f"initialized {s.db_path}")
