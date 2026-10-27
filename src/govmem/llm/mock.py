"""Deterministic offline LLM stand-in (hash-derived JSON). Used by default and by tests."""

from __future__ import annotations

import hashlib
import re
from typing import Any


class MockLLM:
    name = "mock-llm"

    def complete_json(self, system: str, prompt: str) -> dict[str, Any]:
        h = hashlib.sha256((system + "\n" + prompt).encode()).digest()
        words = [w for w in re.findall(r"[a-z_]{4,}", prompt.lower())][:3]
        return {
            "summary": f"mock advisory for: {prompt.splitlines()[0] if prompt else ''}",
            "risk_hint": round(int.from_bytes(h[:4], "big") / 2**32, 3),
            "tags": words,
            "model": self.name,
        }
