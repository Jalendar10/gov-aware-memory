from __future__ import annotations

import pytest

from govmem.config import Settings
from govmem.discovery.pipeline import Event
from govmem.platform import Platform

T0 = 1_700_000_000.0
HOUR = 3600.0


class Clock:
    def __init__(self, t: float = T0 + 100 * HOUR) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def make_platform(**overrides) -> Platform:  # type: ignore[no-untyped-def]
    s = Settings(db_path=":memory:", **overrides)
    return Platform(s, clock=Clock())


@pytest.fixture
def platform() -> Platform:
    return make_platform()


def ev(action: str = "transfer", resource: str = "payments/acct/1", ctx: dict | None = None,
       source: str = "app:a", ts: float = T0, text: str = "pay invoice") -> Event:
    return Event(action, resource, ctx if ctx is not None else {"amount_band": "low", "channel": "web"},
                 text, source, "u1", ts)


def promote_pattern(p: Platform, ctx: dict | None = None, action: str = "transfer",
                    resource: str = "payments/acct/1", n: int = 4) -> int:
    """Feed n diverse observations (distinct windows + sources) and return the promoted pattern id."""
    out = None
    for i in range(n):
        out = p.observe(ev(action, resource, ctx, source=f"app:{i % 2}", ts=T0 + i * 2 * HOUR))
        if out.get("status") == "promoted":
            return int(out["pattern_id"])
    raise AssertionError(f"not promoted: {out}")
