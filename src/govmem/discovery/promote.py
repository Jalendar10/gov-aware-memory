"""Validation pass over quarantine and promotion into compact pattern memory."""

from __future__ import annotations

import json
from typing import Any

from ..audit import log, rollback
from ..context import Ctx
from ..memory import store
from ..memory.encode import FLAG_HUMAN_APPROVED, PatternState, provenance_hash
from ..util import signature
from . import coincidence, consolidate
from .quarantine import get_candidate
from .reviewer import SyntheticReviewer, source_trust_mean
from .trust import get_trust

_reviewer = SyntheticReviewer()


def evaluate_candidate(ctx: Ctx, cid: int, actor: str = "discovery") -> dict[str, Any]:
    """Run coincidence filter + reviewer on one candidate; promote if approved."""
    s, conn = ctx.settings, ctx.conn
    cand = get_candidate(conn, cid)
    if cand is None or cand["status"] in ("promoted", "rejected"):
        return {"candidate_id": cid, "status": cand["status"] if cand else "missing"}
    trust = {src: get_trust(conn, src, s.default_source_trust) for src in cand["sources"]}
    co = coincidence.evaluate(conn, cand, s)
    v = _reviewer.review(cand, co, trust, s)
    now = ctx.clock()
    new_status = {"approve": "pending", "hold": "pending", "needs_review": "needs_review",
                  "reject": "rejected"}[v.verdict]
    conn.execute("UPDATE candidate_quarantine SET validation_score=?, flags_json=?, status=?, updated_at=? WHERE id=?",
                 (v.score, json.dumps(v.flags), new_status, now, cid))
    if new_status != cand["status"]:
        log.append(conn, now, actor, f"candidate_{new_status}", "candidate", cid,
                   {"score": v.score, "flags": v.flags, "reason": v.reason})
    result = {"candidate_id": cid, "verdict": v.verdict, "score": v.score, "flags": v.flags,
              "reason": v.reason, "lift": round(co.lift, 4), "status": new_status}
    if v.verdict == "approve":
        pid = _promote(ctx, cand, trust, human=cand.get("review_verdict") == "approve", actor=actor, score=v.score)
        result.update(status="promoted", pattern_id=pid)
    return result


def _promote(ctx: Ctx, cand: dict[str, Any], trust: dict[str, float], human: bool, actor: str, score: float) -> int:
    s, conn, now = ctx.settings, ctx.conn, ctx.clock()
    r = conn.execute("SELECT centroid FROM candidate_quarantine WHERE id=?", (cand["id"],)).fetchone()
    centroid = store.unpack_vec(r["centroid"])
    ev = [f"{e['episode_id']}:{e['source']}" for e in conn.execute(
        "SELECT episode_id, source FROM evidence_refs WHERE entity_type='candidate' AND entity_id=?", (cand["id"],))]
    st = PatternState(
        action=cand["action"], resource_class=cand["resource_class"], context_key=cand["context_key"],
        signature=signature(cand["action"], cand["resource_class"], cand["context_key"]),
        support=cand["support"], alpha=s.prior_alpha, beta=s.prior_beta,
        ema_risk=s.prior_alpha / (s.prior_alpha + s.prior_beta),
        reliability=source_trust_mean(cand["sources"], trust), usefulness=0.5,
        first_seen=cand["first_seen"], last_seen=cand["last_seen"], windows=len(cand["windows"]),
        flags=FLAG_HUMAN_APPROVED if human else 0, version=1, provenance=provenance_hash(ev), centroid=centroid,
    )
    pid = store.insert_pattern(conn, st, s.encoding, now, source_candidate_id=cand["id"])
    store.move_evidence(conn, "candidate", cand["id"], "pattern", pid)
    conn.execute("UPDATE candidate_quarantine SET status='promoted', promoted_pattern_id=?, updated_at=? WHERE id=?",
                 (pid, now, cand["id"]))
    rollback.snapshot(conn, pid, "promoted", now)
    log.append(conn, now, actor, "pattern_promoted", "pattern", pid,
               {"candidate_id": cand["id"], "score": score, "human_approved": human,
                "signature": st.signature.hex(), "bytes": store.get_pattern(conn, pid).byte_size})
    consolidate.consolidate(ctx, actor=actor)
    return pid


def discover(ctx: Ctx, actor: str = "discovery") -> list[dict[str, Any]]:
    """Batch validation pass over all quarantined candidates."""
    ids = [r["id"] for r in ctx.conn.execute(
        "SELECT id FROM candidate_quarantine WHERE status IN ('pending','needs_review') ORDER BY id")]
    return [evaluate_candidate(ctx, cid, actor) for cid in ids]
