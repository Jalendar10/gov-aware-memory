from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..discovery.pipeline import Event
from . import demo
from .schemas import CandidateReviewIn, DemoIn, EventIn, FeedbackIn, ObserveIn, RetrieveIn

router = APIRouter(prefix="/api", tags=["memory"])


def _p(request: Request):  # type: ignore[no-untyped-def]
    return request.app.state.platform


@router.post("/observe")
def observe(body: ObserveIn, request: Request) -> list[dict[str, Any]]:
    p = _p(request)
    return [p.observe(Event(**e.model_dump())) for e in body.events]


@router.post("/discover")
def discover(request: Request) -> list[dict[str, Any]]:
    return _p(request).discover()


@router.post("/consolidate")
def consolidate(request: Request) -> dict[str, Any]:
    return _p(request).consolidate()


@router.post("/feedback")
def feedback(body: FeedbackIn, request: Request) -> dict[str, Any]:
    if body.pattern_id is None and body.decision_id is None:
        raise HTTPException(422, "pattern_id or decision_id required")
    try:
        return _p(request).feedback(body.reviewer_id, body.outcome == "harmful", body.pattern_id, body.decision_id)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/memory/retrieve")
def retrieve(body: RetrieveIn, request: Request) -> list[dict[str, Any]]:
    return _p(request).retrieve(body.action, body.resource, body.context, body.text, body.k)


@router.get("/memory/stats")
def memory_stats(request: Request) -> dict[str, Any]:
    return _p(request).stats()


@router.get("/patterns")
def list_patterns(request: Request, status: str = "active") -> list[dict[str, Any]]:
    return _p(request).patterns(None if status == "all" else status)


@router.get("/patterns/{pid}/snapshots")
def snapshots(pid: int, request: Request) -> list[dict[str, Any]]:
    return _p(request).snapshots(pid)


@router.get("/quarantine")
def quarantine(request: Request, include_closed: bool = False) -> list[dict[str, Any]]:
    return _p(request).quarantine(include_closed)


@router.post("/quarantine/{cid}/review")
def review(cid: int, body: CandidateReviewIn, request: Request) -> dict[str, Any]:
    try:
        return _p(request).review_candidate(cid, body.verdict, body.reviewer_id)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/demo/seed")
def demo_seed(body: DemoIn, request: Request) -> dict[str, Any]:
    p = _p(request)
    base = p.ctx.clock() - body.n * 1800
    results = [p.observe(e) for e in demo.generate(body.n, body.seed, base, body.include_poison)]
    promoted = sum(1 for r in results if r.get("status") == "promoted")
    return {"observed": len(results), "promotions": promoted, "synthetic": True}
