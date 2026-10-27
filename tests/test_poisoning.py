from govmem.governance.models import Request

from .conftest import HOUR, T0, ev, make_platform, promote_pattern


def _burst(p, n=8):
    # attacker floods one source; one benign event from elsewhere supplies "diversity"
    out = None
    for i in range(n):
        out = p.observe(ev("export", f"pii/users/{i}", {"amount_band": "low"}, source="agent:evil", ts=T0 + i * 2 * HOUR))
    out = p.observe(ev("export", "pii/users/x", {"amount_band": "low"}, source="app:ok", ts=T0 + 40 * HOUR))
    return out


def test_single_source_burst_is_quarantined_for_review(platform):
    out = _burst(platform)
    assert out["status"] == "needs_review"
    assert "burst_source" in out["flags"]
    assert platform.patterns() == []
    q = platform.quarantine()
    assert len(q) == 1 and q[0]["status"] == "needs_review"


def test_quarantined_candidates_are_not_used_in_decisions(platform):
    _burst(platform)
    out = platform.decide(Request("u", [], "export", "pii/users/1", {"amount_band": "low"}))
    assert out["memory"] is None and out["decision"] == "deny"


def test_untrusted_source_flagged(platform):
    platform.set_source_trust("app:shady", 0.1, "human:admin")
    out = None
    for i in range(4):
        out = platform.observe(ev(source="app:shady" if i % 2 else "app:ok", ts=T0 + i * 2 * HOUR))
    assert out["status"] == "needs_review" and "untrusted_source" in out["flags"]


def test_human_approve_and_reject_paths(platform):
    out = _burst(platform)
    cid = out["candidate_id"]
    rej = platform.review_candidate(cid, "reject", "human:alice")
    assert rej["status"] == "rejected"
    assert platform.patterns() == []

    p2 = make_platform()
    cid2 = _burst(p2)["candidate_id"]
    ok = p2.review_candidate(cid2, "approve", "human:alice")
    assert ok["status"] == "promoted" and len(p2.patterns()) == 1


def test_source_purge_requarantines_and_is_audited(platform):
    pid = promote_pattern(platform)  # evidence: app:0 x2, app:1 x1
    for i in range(3):
        platform.observe(ev(source="app:1", ts=T0 + (20 + i) * HOUR))  # now app:1 x4 of 6
    res = platform.purge_source("app:0", "human:sec")  # minority source -> pattern kept
    assert pid not in res["requarantined_patterns"]
    res = platform.purge_source("app:1", "human:sec")  # majority source -> re-quarantined
    assert pid in res["requarantined_patterns"]
    assert platform.patterns() == []
    assert any(e["event_type"] == "source_purged" for e in platform.audit(10))
    # reversible via snapshot rollback
    snaps = platform.snapshots(pid)
    active_v = max(s["version"] for s in snaps if s["status"] == "active")
    platform.rollback_pattern(pid, active_v, "human:sec")
    assert [p["id"] for p in platform.patterns()] == [pid]


def test_low_reliability_reviewer_is_ignored(platform):
    pid = promote_pattern(platform)
    for _ in range(30):
        platform.calibrate_reviewer("rev-bad", agreed=False)
    out = platform.feedback("rev-bad", True, pattern_id=pid)
    assert out["applied"] is False
    assert platform.patterns()[0]["alpha"] == 1.0
