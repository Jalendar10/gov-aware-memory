"""Facade wiring all Version 1 components together. The API and tests both use this."""

from __future__ import annotations

import threading
from typing import Any, Callable

from . import db
from .audit import log as audit_log
from .audit import rollback
from .config import Settings
from .context import Ctx
from .discovery import consolidate as consolidation
from .discovery import promote, trust
from .discovery.matcher import top_k_patterns
from .discovery.pipeline import Event, observe
from .discovery.quarantine import get_candidate, list_candidates
from .feedback import reliability, updates
from .governance import policy_store, service
from .governance.models import Request
from .llm import FrozenLLM, make_llm
from .memory import accounting, store
from .memory.embed import make_embedder
from .util import now as wall_clock
from .util import resource_class


class Platform:
    def __init__(self, settings: Settings | None = None, llm: FrozenLLM | None = None,
                 clock: Callable[[], float] = wall_clock) -> None:
        self.settings = settings or Settings.from_env()
        self.conn = db.connect(self.settings.db_path)
        db.init_schema(self.conn)
        policy_store.seed_defaults(self.conn)
        self.llm = llm if llm is not None else make_llm(self.settings)
        self.ctx = Ctx(self.conn, self.settings, make_embedder(self.settings.embedder, self.settings.st_model), clock)
        self.lock = threading.RLock()

    def _tx(self, fn: Callable[[], Any]) -> Any:
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                out = fn()
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            self.conn.execute("COMMIT")
            return out

    # ---- discovery / memory ----
    def observe(self, ev: Event) -> dict[str, Any]:
        return self._tx(lambda: observe(self.ctx, ev))

    def discover(self) -> list[dict[str, Any]]:
        return self._tx(lambda: promote.discover(self.ctx))

    def consolidate(self) -> dict[str, Any]:
        return self._tx(lambda: consolidation.consolidate(self.ctx))

    def review_candidate(self, cid: int, verdict: str, reviewer_id: str) -> dict[str, Any]:
        if verdict not in ("approve", "reject"):
            raise ValueError("verdict must be approve|reject")

        def run() -> dict[str, Any]:
            if get_candidate(self.conn, cid) is None:
                raise KeyError(f"candidate {cid}")
            self.conn.execute("UPDATE candidate_quarantine SET review_verdict=?, reviewer_id=?, updated_at=? WHERE id=?",
                              (verdict, reviewer_id, self.ctx.clock(), cid))
            audit_log.append(self.conn, self.ctx.clock(), f"reviewer:{reviewer_id}", "candidate_reviewed",
                             "candidate", cid, {"verdict": verdict})
            return promote.evaluate_candidate(self.ctx, cid, actor=f"reviewer:{reviewer_id}")
        return self._tx(run)

    def retrieve(self, action: str, resource: str, context: dict[str, Any], text: str = "", k: int = 5) -> list[dict[str, Any]]:
        with self.lock:
            rc = resource_class(resource)
            emb = self.ctx.embedder.embed(action, rc, context, text)
            return [{**row.to_dict(), "similarity": round(sim, 4)}
                    for row, sim in top_k_patterns(self.conn, emb, k, action=action)]

    def patterns(self, status: str | None = "active") -> list[dict[str, Any]]:
        with self.lock:
            return [r.to_dict() for r in store.list_patterns(self.conn, status)]

    def quarantine(self, include_closed: bool = False) -> list[dict[str, Any]]:
        statuses = ("pending", "needs_review", "promoted", "rejected") if include_closed else ("pending", "needs_review")
        with self.lock:
            return list_candidates(self.conn, statuses)

    def stats(self) -> dict[str, Any]:
        with self.lock:
            return accounting.stats(self.conn, self.settings.byte_budget, self.settings.encoding, self.settings.db_path)

    # ---- governance ----
    def decide(self, req: Request, observe_request: bool = False) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            out = service.govern(self.ctx, req, self.llm)
            if observe_request:
                out["observation"] = observe(self.ctx, Event(req.action, req.resource, req.context, req.text,
                                                             req.source, req.user_id))
            return out
        return self._tx(run)

    def decisions(self, limit: int = 25) -> list[dict[str, Any]]:
        with self.lock:
            return service.recent_decisions(self.ctx, limit)

    # ---- feedback ----
    def feedback(self, reviewer_id: str, harmful: bool, pattern_id: int | None = None,
                 decision_id: int | None = None) -> dict[str, Any]:
        return self._tx(lambda: updates.apply_outcome(self.ctx, reviewer_id=reviewer_id, harmful=harmful,
                                                      pattern_id=pattern_id, decision_id=decision_id))

    def calibrate_reviewer(self, reviewer_id: str, agreed: bool) -> float:
        return self._tx(lambda: reliability.calibrate(self.conn, reviewer_id, agreed, self.settings, self.ctx.clock()))

    def reviewers(self) -> list[dict[str, Any]]:
        with self.lock:
            return reliability.list_reviewers(self.conn)

    def set_source_trust(self, source: str, value: float, actor: str) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            trust.set_trust(self.conn, source, value, self.ctx.clock())
            audit_log.append(self.conn, self.ctx.clock(), actor, "source_trust_set", "source", source, {"trust": value})
            return {"source": source, "trust": value}
        return self._tx(run)

    def source_trust(self) -> dict[str, float]:
        with self.lock:
            return trust.list_trust(self.conn)

    # ---- policies (human-governed only) ----
    def policies(self, status: str | None = None) -> list[dict[str, Any]]:
        with self.lock:
            return policy_store.list_policies(self.conn, status)

    def propose_policy(self, **kw: Any) -> dict[str, Any]:
        return self._tx(lambda: policy_store.propose(self.conn, ts=self.ctx.clock(), **kw))

    def approve_policy(self, pid: int, approver: str, approved: bool) -> dict[str, Any]:
        return self._tx(lambda: policy_store.approve(self.conn, pid, approver, approved, self.ctx.clock()))

    def retire_policy(self, key: str, approver: str) -> int:
        return self._tx(lambda: policy_store.retire(self.conn, key, approver, self.ctx.clock()))

    def rollback_policy(self, key: str, to_version: int, approver: str) -> dict[str, Any]:
        return self._tx(lambda: policy_store.rollback(self.conn, key, to_version, approver, self.ctx.clock()))

    # ---- audit / rollback ----
    def rollback_pattern(self, pid: int, to_version: int, actor: str) -> dict[str, Any]:
        return self._tx(lambda: rollback.rollback_pattern(self.conn, pid, to_version, actor, self.ctx.clock()))

    def snapshots(self, pid: int) -> list[dict[str, Any]]:
        with self.lock:
            return rollback.list_snapshots(self.conn, pid)

    def purge_source(self, source: str, actor: str) -> dict[str, Any]:
        return self._tx(lambda: rollback.purge_source(self.conn, source, actor, self.ctx.clock()))

    def audit(self, limit: int = 50, event_type: str | None = None) -> list[dict[str, Any]]:
        with self.lock:
            return audit_log.recent(self.conn, limit, event_type)

    def verify_audit(self) -> dict[str, Any]:
        with self.lock:
            return audit_log.verify(self.conn)
