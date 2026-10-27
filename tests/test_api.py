from fastapi.testclient import TestClient

from govmem.api.app import create_app

from .conftest import HOUR, T0, make_platform


def client():
    return TestClient(create_app(make_platform()))


def _events(n=4, band="low"):
    return {"events": [{"action": "transfer", "resource": f"payments/acct/{i}", "context": {"amount_band": band},
                        "source": f"app:{i % 2}", "ts": T0 + i * 2 * HOUR} for i in range(n)]}


def test_health_and_dashboard():
    c = client()
    assert c.get("/health").json()["status"] == "ok"
    assert c.get("/api/health").json()["llm"] == "mock-llm"
    r = c.get("/dashboard/")
    assert r.status_code == 200 and "Governance-Aware" in r.text
    assert c.get("/dashboard/app.js").status_code == 200


def test_observe_patterns_stats_retrieve_feedback_roundtrip():
    c = client()
    res = c.post("/api/observe", json=_events()).json()
    assert any(r.get("status") == "promoted" for r in res)
    pats = c.get("/api/patterns").json()
    assert len(pats) == 1
    stats = c.get("/api/memory/stats").json()
    assert stats["pattern_bytes"] == 96
    hits = c.post("/api/memory/retrieve", json={"action": "transfer", "resource": "payments/acct/5",
                                                 "context": {"amount_band": "low"}}).json()
    assert hits[0]["id"] == pats[0]["id"]
    fb = c.post("/api/feedback", json={"reviewer_id": "r1", "outcome": "harmful", "pattern_id": pats[0]["id"]}).json()
    assert fb["after"]["risk"] > fb["before"]["risk"]
    assert c.post("/api/feedback", json={"reviewer_id": "r1", "outcome": "harmful"}).status_code == 422
    assert c.post("/api/consolidate").status_code == 200
    assert isinstance(c.post("/api/discover").json(), list)
    snaps = c.get(f"/api/patterns/{pats[0]['id']}/snapshots").json()
    rb = c.post("/api/rollback", json={"entity_type": "pattern", "pattern_id": pats[0]["id"],
                                       "to_version": snaps[0]["version"], "actor": "human:ops"})
    assert rb.status_code == 200 and rb.json()["risk"] == pats[0]["risk"]


def test_decide_and_decisions():
    c = client()
    d = c.post("/api/decide", json={"user_id": "a", "roles": [], "action": "export", "resource": "pii/x"}).json()
    assert d["decision"] == "deny" and d["authoritative"] == "external_policy"
    assert c.get("/api/decisions").json()[0]["id"] == d["decision_id"]


def test_policy_crud_requires_approval_and_human_actor():
    c = client()
    assert c.post("/api/policies", json={"key": "x", "effect": "deny", "match": {"actions": ["x"]},
                                         "proposed_by": "memory"}).status_code == 403
    prop = c.post("/api/policies", json={"key": "x", "effect": "deny", "match": {"actions": ["x"]},
                                         "priority": 5, "proposed_by": "human:bob"}).json()
    assert prop["status"] == "proposed"
    act = c.post(f"/api/policies/{prop['id']}/approve", json={"approver": "human:carol", "approved": True}).json()
    assert act["status"] == "active"
    assert c.post(f"/api/policies/{prop['id']}/approve",
                  json={"approver": "human:carol", "approved": True}).status_code == 409
    assert c.delete("/api/policies/x", params={"approver": "human:carol"}).json()["retired"] == 1
    assert any(p["policy_key"] == "x" for p in c.get("/api/policies").json())


def test_quarantine_review_and_audit_endpoints():
    c = client()
    evs = {"events": [{"action": "export", "resource": f"pii/u/{i}", "context": {"b": "1"}, "source": "evil",
                       "ts": T0 + i * 2 * HOUR} for i in range(6)] +
           [{"action": "export", "resource": "pii/u/z", "context": {"b": "1"}, "source": "ok", "ts": T0 + 30 * HOUR}]}
    c.post("/api/observe", json=evs)
    q = c.get("/api/quarantine").json()
    assert q and q[0]["status"] == "needs_review"
    r = c.post(f"/api/quarantine/{q[0]['id']}/review", json={"reviewer_id": "h", "verdict": "reject"}).json()
    assert r["status"] == "rejected"
    assert c.post("/api/rollback/source", json={"source": "evil", "actor": "human:sec"}).status_code == 200
    assert c.get("/api/sources/trust").json()["evil"] == 0.0
    assert c.get("/api/audit/verify").json()["ok"]
    assert len(c.get("/api/audit?limit=5").json()) == 5
    assert c.post("/api/reviewers/h/calibrate", json={"agreed": True}).json()["reliability"] > 0.8
    assert c.get("/api/reviewers").json()


def test_demo_seed_runs():
    c = client()
    out = c.post("/api/demo/seed", json={"n": 30}).json()
    assert out["observed"] >= 30 and out["synthetic"] is True
