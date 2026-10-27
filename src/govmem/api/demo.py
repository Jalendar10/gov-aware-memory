"""Synthetic event generator for the dashboard demo. Output is synthetic, not experimental data."""

from __future__ import annotations

import random

from ..discovery.pipeline import Event

TEMPLATES = [
    ("transfer", "payments/acct", {"amount_band": "low", "channel": "web"}, "pay vendor invoice"),
    ("transfer", "payments/acct", {"amount_band": "medium", "channel": "api"}, "batch payout to supplier"),
    ("read", "reports/q3", {"channel": "web"}, "open quarterly report"),
    ("read", "pii/users", {"channel": "api"}, "lookup customer profile"),
    ("export", "pii/users", {"channel": "api"}, "export customer list"),
]
SOURCES = ["app:erp", "app:crm", "agent:payments-bot", "user:analyst"]


def generate(n: int, seed: int, base_ts: float, include_poison: bool) -> list[Event]:
    rng = random.Random(seed)
    events = []
    for i in range(n):
        a, r, c, t = rng.choice(TEMPLATES)
        events.append(Event(a, f"{r}/{rng.randint(1, 50)}", dict(c), t, rng.choice(SOURCES),
                            f"u{rng.randint(1, 9)}", base_ts + i * 1800 + rng.randint(0, 600)))
    if include_poison:  # single-source burst trying to plant a "low-risk export" pattern
        for i in range(max(3, n // 6)):
            events.append(Event("export", f"pii/users/{i}", {"amount_band": "low", "channel": "web"},
                                "routine safe export", "agent:untrusted-plugin", "attacker", base_ts + i * 5))
    return events
