"""Candidate validation: poisoning flags, validation score, synthetic reviewer.

validation_score = trust * (0.4*min(1, support/(2*min_support))
                           + 0.3*min(1, windows/(2*min_windows))
                           + 0.3*min(1, sources/(2*min_sources)))
where trust = support-weighted mean trust of contributing sources.

Poison flags (any => candidate needs an explicit human approve):
  burst_source    one source contributed >= burst_fraction of the support
  untrusted_source a contributing source has trust < min_source_trust
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import Settings
from .coincidence import CoincidenceResult


@dataclass
class Verdict:
    verdict: str          # approve | hold | needs_review | reject
    score: float
    flags: list[str]
    reason: str


def source_trust_mean(sources: dict[str, int], trust: dict[str, float]) -> float:
    total = sum(sources.values())
    return sum(trust[s] * n for s, n in sources.items()) / total if total else 0.0


def poison_flags(sources: dict[str, int], trust: dict[str, float], s: Settings) -> list[str]:
    flags = []
    total = sum(sources.values())
    if total and max(sources.values()) / total >= s.burst_fraction and total >= s.min_support:
        flags.append("burst_source")
    if any(trust[src] < s.min_source_trust for src in sources):
        flags.append("untrusted_source")
    return flags


def validation_score(c: CoincidenceResult, trust_mean: float, s: Settings) -> float:
    base = (0.4 * min(1.0, c.support / (2 * s.min_support))
            + 0.3 * min(1.0, c.windows / (2 * s.min_windows))
            + 0.3 * min(1.0, c.sources / (2 * s.min_sources)))
    return round(trust_mean * base, 4)


class SyntheticReviewer:
    """Deterministic stand-in for a human reviewer. Human verdicts always take precedence."""

    def review(self, cand: dict[str, Any], c: CoincidenceResult, trust: dict[str, float], s: Settings) -> Verdict:
        tm = source_trust_mean(cand["sources"], trust)
        score = validation_score(c, tm, s)
        flags = poison_flags(cand["sources"], trust, s)
        human = cand.get("review_verdict")
        if human == "reject":
            return Verdict("reject", score, flags, "rejected by reviewer")
        if not c.passed:
            return Verdict("hold", score, flags, "; ".join(c.failures))
        if human == "approve":
            return Verdict("approve", score, flags, "approved by reviewer")
        if flags:
            return Verdict("needs_review", score, flags, "poisoning flags: " + ",".join(flags))
        if s.require_human_review:
            return Verdict("needs_review", score, flags, "human review required by configuration")
        if score >= s.promote_threshold:
            return Verdict("approve", score, flags, f"synthetic approve (score {score} >= {s.promote_threshold})")
        return Verdict("hold", score, flags, f"score {score} < {s.promote_threshold}")
