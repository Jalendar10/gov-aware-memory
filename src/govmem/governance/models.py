from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ALLOW, DENY, REVIEW = "allow", "deny", "review"


@dataclass(frozen=True)
class Policy:
    id: int
    key: str
    version: int
    effect: str
    priority: int
    match: dict[str, Any]
    risk_review_threshold: float | None = None


@dataclass
class Request:
    user_id: str
    roles: list[str]
    action: str
    resource: str
    context: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    source: str = "api"


@dataclass(frozen=True)
class MemorySignal:
    pattern_id: int
    risk: float            # Beta posterior mean P(harmful)
    evidence: float        # feedback mass beyond the prior
    similarity: float


@dataclass
class Outcome:
    decision: str
    base_decision: str
    policy_refs: list[dict[str, Any]]
    reasons: list[str]
    memory: MemorySignal | None
