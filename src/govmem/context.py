"""Shared runtime context passed to the component modules."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable

from .config import Settings
from .memory.embed import Embedder


@dataclass
class Ctx:
    conn: sqlite3.Connection
    settings: Settings
    embedder: Embedder
    clock: Callable[[], float]
