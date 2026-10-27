from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..governance.policy_store import PolicyWriteForbidden
from .schemas import CalibrateIn, PurgeIn, RollbackIn, TrustIn

router = APIRouter(prefix="/api", tags=["audit"])


def _p(request: Request):  # type: ignore[no-untyped-def]
    return request.app.state.platform


@router.post("/rollback")
def rollback(body: RollbackIn, request: Request) -> dict[str, Any]:
    p = _p(request)
    try:
        if body.entity_type == "pattern":
            if body.pattern_id is None:
                raise HTTPException(422, "pattern_id required")
            return p.rollback_pattern(body.pattern_id, body.to_version, body.actor)
        if not body.policy_key:
            raise HTTPException(422, "policy_key required")
        return p.rollback_policy(body.policy_key, body.to_version, body.actor)
    except PolicyWriteForbidden as e:
        raise HTTPException(403, str(e)) from e
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/rollback/source")
def purge(body: PurgeIn, request: Request) -> dict[str, Any]:
    return _p(request).purge_source(body.source, body.actor)


@router.get("/sources/trust")
def get_trust(request: Request) -> dict[str, float]:
    return _p(request).source_trust()


@router.post("/sources/trust")
def set_trust(body: TrustIn, request: Request) -> dict[str, Any]:
    return _p(request).set_source_trust(body.source, body.trust, body.actor)


@router.get("/reviewers")
def reviewers(request: Request) -> list[dict[str, Any]]:
    return _p(request).reviewers()


@router.post("/reviewers/{rid}/calibrate")
def calibrate(rid: str, body: CalibrateIn, request: Request) -> dict[str, Any]:
    return {"reviewer_id": rid, "reliability": _p(request).calibrate_reviewer(rid, body.agreed)}


@router.get("/audit")
def audit(request: Request, limit: int = 50, event_type: str | None = None) -> list[dict[str, Any]]:
    return _p(request).audit(limit, event_type)


@router.get("/audit/verify")
def verify(request: Request) -> dict[str, Any]:
    return _p(request).verify_audit()
