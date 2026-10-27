"""Governance service: retrieve memory signal, run deterministic G, record decision + stats."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from ..audit import log
from ..context import Ctx
from ..discovery.matcher import best_pattern
from ..llm.base import ADVISORY_SYSTEM, FrozenLLM, advisory_prompt
from ..util import cjson, resource_class
from . import policy_store
from .decide import decide
from .models import MemorySignal, Request


def memory_signal(ctx: Ctx, req: Request) -> MemorySignal | None:
    """Only ACTIVE (validated) patterns are consulted; quarantined candidates never are."""
    rc = resource_class(req.resource)
    emb = ctx.embedder.embed(req.action, rc, req.context, req.text)
    hit = best_pattern(ctx.conn, req.action, rc, emb, ctx.settings.match_threshold)
    if hit is None:
        return None
    row, sim = hit
    st = row.state
    evidence = (st.alpha + st.beta) - (ctx.settings.prior_alpha + ctx.settings.prior_beta)
    return MemorySignal(row.id, round(st.risk, 6), round(evidence, 6), round(sim, 6))


def govern(ctx: Ctx, req: Request, llm: FrozenLLM | None) -> dict[str, Any]:
    s, conn, now = ctx.settings, ctx.conn, ctx.clock()
    sig = memory_signal(ctx, req)
    out = decide(req, policy_store.active_policies(conn), sig, s.default_effect,
                 s.risk_review_threshold, s.risk_min_evidence)
    advisory = llm.complete_json(ADVISORY_SYSTEM, advisory_prompt(req.action, req.resource, req.context, req.text)) \
        if llm is not None else None
    cur = conn.execute(
        "INSERT INTO governance_decisions (ts,request_json,decision,base_decision,policy_refs_json,pattern_id,risk,"
        "reasons_json,llm_advisory_json) VALUES (?,?,?,?,?,?,?,?,?)",
        (now, cjson(asdict(req)), out.decision, out.base_decision, cjson(out.policy_refs),
         sig.pattern_id if sig else None, sig.risk if sig else None, cjson(out.reasons),
         cjson(advisory) if advisory is not None else None))
    did = int(cur.lastrowid)
    if sig is not None:
        esc = int(out.decision != out.base_decision)
        conn.execute(
            "INSERT INTO governance_stats (pattern_id,decision,count,escalations,updated_at) VALUES (?,?,1,?,?) "
            "ON CONFLICT(pattern_id,decision) DO UPDATE SET count=count+1, escalations=escalations+?, updated_at=?",
            (sig.pattern_id, out.decision, esc, now, esc, now))
    log.append(conn, now, f"user:{req.user_id}", "decision", "decision", did,
               {"decision": out.decision, "base": out.base_decision, "pattern_id": sig.pattern_id if sig else None})
    return {
        "decision_id": did, "decision": out.decision, "base_decision": out.base_decision,
        "policy_refs": out.policy_refs, "reasons": out.reasons,
        "memory": asdict(sig) if sig else None, "llm_advisory": advisory,
        "authoritative": "external_policy",
    }


def recent_decisions(ctx: Ctx, limit: int = 25) -> list[dict[str, Any]]:
    rows = ctx.conn.execute("SELECT * FROM governance_decisions ORDER BY id DESC LIMIT ?", (limit,))
    out = []
    for r in rows:
        out.append({"id": r["id"], "ts": r["ts"], "request": json.loads(r["request_json"]),
                    "decision": r["decision"], "base_decision": r["base_decision"],
                    "policy_refs": json.loads(r["policy_refs_json"]), "pattern_id": r["pattern_id"],
                    "risk": r["risk"], "reasons": json.loads(r["reasons_json"])})
    return out
