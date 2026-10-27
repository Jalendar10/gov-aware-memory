from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EventIn(BaseModel):
    action: str
    resource: str
    context: dict[str, Any] = Field(default_factory=dict)
    text: str = ""
    source: str = "api"
    user_id: str = "anon"
    ts: float | None = None


class ObserveIn(BaseModel):
    events: list[EventIn]


class DecideIn(BaseModel):
    user_id: str
    roles: list[str] = Field(default_factory=list)
    action: str
    resource: str
    context: dict[str, Any] = Field(default_factory=dict)
    text: str = ""
    source: str = "api"
    observe: bool = False


class RetrieveIn(BaseModel):
    action: str
    resource: str
    context: dict[str, Any] = Field(default_factory=dict)
    text: str = ""
    k: int = 5


class FeedbackIn(BaseModel):
    reviewer_id: str
    outcome: Literal["harmful", "benign"]
    pattern_id: int | None = None
    decision_id: int | None = None


class CandidateReviewIn(BaseModel):
    reviewer_id: str
    verdict: Literal["approve", "reject"]


class PolicyProposeIn(BaseModel):
    key: str
    effect: Literal["allow", "deny", "review"]
    match: dict[str, Any]
    priority: int = 0
    proposed_by: str
    risk_review_threshold: float | None = None


class PolicyApproveIn(BaseModel):
    approver: str
    approved: bool


class RollbackIn(BaseModel):
    entity_type: Literal["pattern", "policy"]
    to_version: int
    actor: str
    pattern_id: int | None = None
    policy_key: str | None = None


class PurgeIn(BaseModel):
    source: str
    actor: str


class TrustIn(BaseModel):
    source: str
    trust: float = Field(ge=0.0, le=1.0)
    actor: str


class CalibrateIn(BaseModel):
    agreed: bool


class DemoIn(BaseModel):
    n: int = Field(default=30, ge=1, le=500)
    seed: int = 7
    include_poison: bool = True
