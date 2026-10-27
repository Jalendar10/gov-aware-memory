import pytest

from .conftest import promote_pattern


def test_feedback_updates_beta_ema_and_is_reliability_weighted(platform):
    pid = promote_pattern(platform)
    out = platform.feedback("rev-1", True, pattern_id=pid)
    w = out["reviewer_reliability"]
    assert w == pytest.approx(0.8)
    assert out["after"]["alpha"] == pytest.approx(1.0 + w, abs=1e-5)
    assert out["after"]["risk"] > out["before"]["risk"]
    assert out["after"]["ema_risk"] == pytest.approx(0.8 * 0.25 + 0.2, abs=1e-5)
    out2 = platform.feedback("rev-1", False, pattern_id=pid)
    assert out2["after"]["risk"] < out["after"]["risk"]


def test_decision_feedback_updates_usefulness(platform):
    from govmem.governance.models import Request
    pid = promote_pattern(platform)
    d = platform.decide(Request("a", [], "transfer", "payments/acct/2", {"amount_band": "low", "channel": "web"}))
    out = platform.feedback("rev-1", False, decision_id=d["decision_id"])  # allow + benign -> useful
    assert out["pattern_id"] == pid and out["after"]["usefulness"] > out["before"]["usefulness"]


def test_byte_size_constant_under_feedback(platform):
    pid = promote_pattern(platform)
    b0 = platform.stats()["pattern_bytes"]
    for _ in range(10):
        platform.feedback("rev-1", True, pattern_id=pid)
    assert platform.stats()["pattern_bytes"] == b0


def test_rollback_restores_scores(platform):
    pid = promote_pattern(platform)
    v1 = platform.patterns()[0]
    for _ in range(3):
        platform.feedback("rev-1", True, pattern_id=pid)
    assert platform.patterns()[0]["risk"] > v1["risk"]
    restored = platform.rollback_pattern(pid, 1, "human:ops")
    assert restored["risk"] == v1["risk"] and restored["version"] > v1["version"]


def test_audit_chain_verifies_and_detects_tamper(platform):
    pid = promote_pattern(platform)
    platform.feedback("rev-1", True, pattern_id=pid)
    assert platform.verify_audit()["ok"]
    platform.conn.execute("UPDATE audit_events SET payload_json='{}' WHERE id=3")
    v = platform.verify_audit()
    assert not v["ok"] and v["first_bad_id"] == 3
