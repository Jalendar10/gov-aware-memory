"""Pure, deterministic decision function G(u, a, r, c, p).

1. Collect policies p_i in p whose matcher accepts (u, a, r, c).
2. Deny-overrides: any matching deny -> DENY. Else any review -> REVIEW. Else any allow -> ALLOW.
   No match -> settings.default_effect.
3. Memory may only ESCALATE: if base == ALLOW and a validated pattern has
   risk >= threshold with evidence >= risk_min_evidence -> REVIEW.
   Memory can never turn DENY/REVIEW into ALLOW and never edits a policy.
Same inputs always yield the same output (policies are ordered by (-priority, key, version)).
"""

from __future__ import annotations

from typing import Any, Iterable

from .models import ALLOW, DENY, REVIEW, MemorySignal, Outcome, Policy, Request


def matches(m: dict[str, Any], req: Request) -> bool:
    actions = m.get("actions", ["*"])
    if "*" not in actions and req.action not in actions:
        return False
    rp = m.get("resource_prefix")
    if rp and not req.resource.startswith(rp):
        return False
    roles = set(req.roles)
    if m.get("roles_any") and not roles & set(m["roles_any"]):
        return False
    if m.get("roles_none") and roles & set(m["roles_none"]):
        return False
    for k, v in (m.get("context_equals") or {}).items():
        if str(req.context.get(k)) != str(v):
            return False
    return True


def decide(req: Request, policies: Iterable[Policy], memory: MemorySignal | None,
           default_effect: str, risk_threshold: float, min_evidence: float) -> Outcome:
    ordered = sorted(policies, key=lambda p: (-p.priority, p.key, p.version))
    hits = [p for p in ordered if matches(p.match, req)]
    refs = [{"id": p.id, "key": p.key, "version": p.version, "effect": p.effect} for p in hits]
    reasons: list[str] = []
    effects = {p.effect for p in hits}
    if DENY in effects:
        base = DENY
        reasons.append(f"deny by policy {next(p.key for p in hits if p.effect == DENY)}")
    elif REVIEW in effects:
        base = REVIEW
        reasons.append(f"review by policy {next(p.key for p in hits if p.effect == REVIEW)}")
    elif ALLOW in effects:
        base = ALLOW
        reasons.append(f"allow by policy {next(p.key for p in hits if p.effect == ALLOW)}")
    else:
        base = default_effect
        reasons.append(f"no matching policy; default {default_effect}")

    decision = base
    if base == ALLOW and memory is not None:
        allow_pol = next(p for p in hits if p.effect == ALLOW)
        thr = allow_pol.risk_review_threshold if allow_pol.risk_review_threshold is not None else risk_threshold
        if memory.evidence >= min_evidence and memory.risk >= thr:
            decision = REVIEW
            reasons.append(f"memory escalation: pattern {memory.pattern_id} risk {memory.risk:.3f} >= {thr}")
        else:
            reasons.append(f"memory consulted: pattern {memory.pattern_id} risk {memory.risk:.3f}, "
                           f"evidence {memory.evidence:.2f}")
    return Outcome(decision, base, refs, reasons, memory)
