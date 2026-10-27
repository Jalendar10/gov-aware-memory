"""Consolidation: merge near-duplicate patterns, then forget lowest-utility patterns until the
active pattern bytes fit within budget B. Every merge/forget is snapshotted and audited."""

from __future__ import annotations

from typing import Any

from ..audit import log, rollback
from ..context import Ctx
from ..memory import accounting, store
from ..memory.embed import cosine, normalize
from ..memory.encode import FLAG_MERGED_INTO
from .utility import utility


def merge_pass(ctx: Ctx, actor: str) -> list[dict[str, Any]]:
    s, conn = ctx.settings, ctx.conn
    merges: list[dict[str, Any]] = []
    rows = store.list_patterns(conn, "active")
    alive = {r.id: r for r in rows}
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if a.id not in alive or b.id not in alive:
                continue
            if (a.state.action, a.state.resource_class) != (b.state.action, b.state.resource_class):
                continue
            sim = cosine(a.state.centroid, b.state.centroid)
            if sim < s.merge_threshold:
                continue
            keep, drop = (a, b) if a.state.support >= b.state.support else (b, a)
            merges.append(_merge(ctx, keep, drop, sim, actor))
            alive.pop(drop.id)
    return merges


def _merge(ctx: Ctx, keep: store.PatternRow, drop: store.PatternRow, sim: float, actor: str) -> dict[str, Any]:
    s, conn, now = ctx.settings, ctx.conn, ctx.clock()
    k, d = keep.state, drop.state
    rollback.snapshot(conn, keep.id, "pre-merge", now)
    rollback.snapshot(conn, drop.id, "pre-merge", now)
    nk, nd = max(k.support, 1), max(d.support, 1)
    k.centroid = normalize([(x * nk + y * nd) / (nk + nd) for x, y in zip(k.centroid, d.centroid)])
    k.alpha += d.alpha - s.prior_alpha
    k.beta += d.beta - s.prior_beta
    k.ema_risk = (k.ema_risk * nk + d.ema_risk * nd) / (nk + nd)
    k.reliability = (k.reliability * nk + d.reliability * nd) / (nk + nd)
    k.usefulness = max(k.usefulness, d.usefulness)
    k.support += d.support
    k.windows += d.windows
    k.first_seen, k.last_seen = min(k.first_seen, d.first_seen), max(k.last_seen, d.last_seen)
    k.flags |= FLAG_MERGED_INTO
    k.version += 1
    store.save_pattern(conn, keep.id, k, keep.encoding, now)
    store.move_evidence(conn, "pattern", drop.id, "pattern", keep.id)
    d.version += 1
    store.save_pattern(conn, drop.id, d, drop.encoding, now, status="merged")
    rollback.snapshot(conn, keep.id, "merged", now)
    rollback.snapshot(conn, drop.id, "merged-away", now)
    info = {"kept": keep.id, "merged": drop.id, "similarity": round(sim, 4)}
    log.append(conn, now, actor, "pattern_merged", "pattern", keep.id, info)
    return info


def forget_pass(ctx: Ctx, actor: str) -> list[dict[str, Any]]:
    s, conn, now = ctx.settings, ctx.conn, ctx.clock()
    forgotten: list[dict[str, Any]] = []
    while accounting.pattern_bytes(conn) > s.byte_budget:
        rows = store.list_patterns(conn, "active")
        if not rows:
            break
        max_sup = max(r.state.support for r in rows)
        scored = sorted(((utility(r.state, now, max_sup, s), r) for r in rows), key=lambda t: (t[0], t[1].id))
        u, victim = scored[0]
        rollback.snapshot(conn, victim.id, "pre-forget", now)
        victim.state.version += 1
        store.save_pattern(conn, victim.id, victim.state, victim.encoding, now, status="forgotten")
        rollback.snapshot(conn, victim.id, "forgotten", now)
        info = {"pattern_id": victim.id, "utility": round(u, 4), "bytes_freed": victim.byte_size,
                "bytes_after": accounting.pattern_bytes(conn), "budget": s.byte_budget}
        log.append(conn, now, actor, "pattern_forgotten", "pattern", victim.id, info)
        forgotten.append(info)
    return forgotten


def consolidate(ctx: Ctx, actor: str = "consolidation") -> dict[str, Any]:
    merges = merge_pass(ctx, actor)
    forgotten = forget_pass(ctx, actor)
    return {"merged": merges, "forgotten": forgotten,
            "pattern_bytes": accounting.pattern_bytes(ctx.conn), "budget": ctx.settings.byte_budget}
