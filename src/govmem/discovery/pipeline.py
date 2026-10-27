"""Observation entry point: observe -> route to existing pattern or to quarantine discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..context import Ctx
from ..memory import store
from ..util import blake, cjson, context_key, resource_class
from . import promote, quarantine, reinforce
from .matcher import best_pattern


@dataclass
class Event:
    action: str
    resource: str
    context: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    source: str = "unknown"
    user_id: str = "anon"
    ts: float | None = None


def observe(ctx: Ctx, ev: Event, actor: str = "discovery") -> dict[str, Any]:
    ts = ev.ts if ev.ts is not None else ctx.clock()
    rc, ck = resource_class(ev.resource), context_key(ev.context)
    emb = ctx.embedder.embed(ev.action, rc, ev.context, ev.text)
    prov = blake(cjson([ts, ev.user_id, ev.source, ev.action, ev.resource, ev.context, ev.text]), 16).hex()
    eid = store.insert_episode(ctx.conn, ts=ts, user_id=ev.user_id, source=ev.source, action=ev.action,
                               resource=ev.resource, resource_class=rc, context_key=ck, context=ev.context,
                               text=ev.text, embedding=emb, provenance_hash=prov)
    hit = best_pattern(ctx.conn, ev.action, rc, emb, ctx.settings.match_threshold)
    if hit is not None:
        row, sim = hit
        reinforce.reinforce(ctx, row, emb, ts, eid, ev.source, prov)
        store.set_episode_route(ctx.conn, eid, f"pattern:{row.id}")
        return {"episode_id": eid, "routed": "existing_pattern", "pattern_id": row.id, "similarity": round(sim, 4)}
    cid = quarantine.upsert_candidate(ctx, action=ev.action, resource_class=rc, context_key=ck, emb=emb,
                                      ts=ts, source=ev.source, episode_id=eid, prov=prov)
    store.set_episode_route(ctx.conn, eid, f"candidate:{cid}")
    res = promote.evaluate_candidate(ctx, cid, actor)
    return {"episode_id": eid, "routed": "candidate", **res}
