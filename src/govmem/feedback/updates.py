"""Score updates for EXISTING patterns (separate from new-pattern discovery).

Outcome y in {1 harmful, 0 benign} from reviewer with reliability w:
  alpha += w*y ; beta += w*(1-y)                 (reliability-weighted Beta posterior)
  ema_risk    = (1-l)*ema_risk + l*y
  reliability = (1-l)*reliability + l*w
  usefulness  = (1-l)*usefulness + l*u,  u = 1 if the linked decision was right
                (allow & benign, or review/deny & harmful) else 0
Every update is snapshotted (rollback) and audited. Policies are never touched.
"""

from __future__ import annotations

from typing import Any

from ..audit import log, rollback
from ..context import Ctx
from ..memory import accounting, store
from . import reliability


def apply_outcome(ctx: Ctx, *, reviewer_id: str, harmful: bool, pattern_id: int | None = None,
                  decision_id: int | None = None) -> dict[str, Any]:
    s, conn, now = ctx.settings, ctx.conn, ctx.clock()
    decision = None
    if decision_id is not None:
        d = conn.execute("SELECT decision, pattern_id FROM governance_decisions WHERE id=?", (decision_id,)).fetchone()
        if d is None:
            raise KeyError(f"decision {decision_id}")
        decision = d["decision"]
        pattern_id = pattern_id or d["pattern_id"]
    if pattern_id is None:
        log.append(conn, now, f"reviewer:{reviewer_id}", "feedback_unlinked", "decision", decision_id,
                   {"harmful": harmful})
        return {"applied": False, "reason": "decision had no validated pattern to update"}
    row = store.get_pattern(conn, pattern_id)
    if row is None or row.status != "active":
        raise KeyError(f"active pattern {pattern_id}")
    w = reliability.get(conn, reviewer_id, s, now)
    if w < s.min_reviewer_reliability:
        log.append(conn, now, f"reviewer:{reviewer_id}", "feedback_ignored", "pattern", pattern_id,
                   {"reliability": w, "min": s.min_reviewer_reliability})
        return {"applied": False, "reason": f"reviewer reliability {w:.3f} below minimum"}

    st = row.state
    before = {"risk": round(st.risk, 4), "ema_risk": round(st.ema_risk, 4), "alpha": st.alpha, "beta": st.beta,
              "usefulness": round(st.usefulness, 4), "version": st.version}
    prior_evidence = st.alpha + st.beta - s.prior_alpha - s.prior_beta
    prior_risk = st.risk
    rollback.snapshot(conn, pattern_id, "pre-feedback", now)
    y = 1.0 if harmful else 0.0
    lam = s.ema_lambda
    st.alpha += w * y
    st.beta += w * (1 - y)
    st.ema_risk = (1 - lam) * st.ema_risk + lam * y
    st.reliability = (1 - lam) * st.reliability + lam * w
    if decision is not None:
        right = (decision == "allow" and not harmful) or (decision in ("review", "deny") and harmful)
        st.usefulness = (1 - lam) * st.usefulness + lam * (1.0 if right else 0.0)
    st.version += 1
    store.save_pattern(conn, pattern_id, st, row.encoding, now)
    rollback.snapshot(conn, pattern_id, "feedback", now)
    new_rel = reliability.consensus_hook(conn, reviewer_id, harmful, prior_risk, prior_evidence, s, now)
    saved = store.get_pattern(conn, pattern_id)
    assert saved is not None
    after = {"risk": round(saved.state.risk, 4), "ema_risk": round(saved.state.ema_risk, 4),
             "alpha": saved.state.alpha, "beta": saved.state.beta,
             "usefulness": round(saved.state.usefulness, 4), "version": saved.state.version}
    log.append(conn, now, f"reviewer:{reviewer_id}", "pattern_feedback", "pattern", pattern_id,
               {"harmful": harmful, "weight": round(w, 4), "decision_id": decision_id, "before": before, "after": after})
    return {"applied": True, "pattern_id": pattern_id, "reviewer_reliability": round(w, 4),
            "reviewer_reliability_after": new_rel, "before": before, "after": after,
            "pattern_bytes": accounting.pattern_bytes(conn)}
