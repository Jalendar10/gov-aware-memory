from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..governance.models import Request as GovRequest
from ..governance.policy_store import PolicyWriteForbidden
from .schemas import DecideIn, PolicyApproveIn, PolicyProposeIn

router = APIRouter(prefix="/api", tags=["governance"])


def _p(request: Request):  # type: ignore[no-untyped-def]
    return request.app.state.platform


@router.post("/decide")
def decide(body: DecideIn, request: Request) -> dict[str, Any]:
    req = GovRequest(body.user_id, body.roles, body.action, body.resource, body.context, body.text, body.source)
    return _p(request).decide(req, observe_request=body.observe)


@router.get("/decisions")
def decisions(request: Request, limit: int = 25) -> list[dict[str, Any]]:
    return _p(request).decisions(limit)


@router.get("/policies")
def policies(request: Request, status: str | None = None) -> list[dict[str, Any]]:
    return _p(request).policies(status)


@router.post("/policies")
def propose(body: PolicyProposeIn, request: Request) -> dict[str, Any]:
    """Creates a PROPOSED version; it has no effect until approved via /approve with approved=true."""
    try:
        return _p(request).propose_policy(key=body.key, effect=body.effect, match=body.match, priority=body.priority,
                                          proposed_by=body.proposed_by,
                                          risk_review_threshold=body.risk_review_threshold)
    except PolicyWriteForbidden as e:
        raise HTTPException(403, str(e)) from e


@router.post("/policies/{pid}/approve")
def approve(pid: int, body: PolicyApproveIn, request: Request) -> dict[str, Any]:
    try:
        return _p(request).approve_policy(pid, body.approver, body.approved)
    except PolicyWriteForbidden as e:
        raise HTTPException(403, str(e)) from e
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@router.delete("/policies/{key}")
def retire(key: str, request: Request, approver: str) -> dict[str, Any]:
    try:
        return {"retired": _p(request).retire_policy(key, approver)}
    except PolicyWriteForbidden as e:
        raise HTTPException(403, str(e)) from e
