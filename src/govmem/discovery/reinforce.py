"""Observation-side update for an EXISTING pattern: support, recency, temporal windows,
centroid drift. Risk/reliability scores are NOT touched here (see feedback/updates.py)."""

from __future__ import annotations

from ..context import Ctx
from ..memory import store
from ..memory.embed import normalize
from ..memory.store import PatternRow

CENTROID_RATE = 0.1


def reinforce(ctx: Ctx, row: PatternRow, emb: list[float], ts: float, episode_id: int, source: str, prov: str) -> None:
    st = row.state
    w = ctx.settings.window_seconds
    if int(ts // w) != int(st.last_seen // w):
        st.windows += 1
    st.support += 1
    st.last_seen = max(st.last_seen, ts)
    st.centroid = normalize([(1 - CENTROID_RATE) * c + CENTROID_RATE * e for c, e in zip(st.centroid, emb)])
    store.save_pattern(ctx.conn, row.id, st, row.encoding, ctx.clock())
    store.add_evidence(ctx.conn, "pattern", row.id, episode_id, source, prov, ts)
