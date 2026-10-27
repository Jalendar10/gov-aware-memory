import hashlib

import pytest

from govmem.governance.decide import decide, matches
from govmem.governance.models import Policy, Request
from govmem.governance.policy_store import PolicyWriteForbidden

from .conftest import promote_pattern


def R(action, resource, roles=("analyst",), **ctx):
    return Request("alice", list(roles), action, resource, ctx)


def policies_digest(p):
    rows = p.conn.execute("SELECT * FROM policies ORDER BY id").fetchall()
    return hashlib.sha256(repr([tuple(r) for r in rows]).encode()).hexdigest()


def test_deny_allow_review_and_default(platform):
    assert platform.decide(R("export", "pii/users/1"))["decision"] == "deny"
    assert platform.decide(R("transfer", "payments/acct/1", amount_band="high"))["decision"] == "review"
    assert platform.decide(R("read", "reports/q3"))["decision"] == "allow"
    assert platform.decide(R("delete", "reports/q3"))["decision"] == "review"   # no policy -> default


def test_role_exemption(platform):
    out = platform.decide(R("export", "pii/users/1", roles=["privacy_officer"]))
    assert out["decision"] == "review"  # not denied, but nothing allows it either


def test_deny_overrides_allow():
    pols = [Policy(1, "allow-all", 1, "allow", 100, {"actions": ["*"]}),
            Policy(2, "deny-x", 1, "deny", 0, {"actions": ["x"]})]
    assert decide(R("x", "r"), pols, None, "review", 0.6, 2.0).decision == "deny"


def test_matcher_context_equals():
    assert matches({"actions": ["t"], "context_equals": {"band": "high"}}, R("t", "r", band="high"))
    assert not matches({"actions": ["t"], "context_equals": {"band": "high"}}, R("t", "r", band="low"))


def test_decision_is_deterministic(platform):
    a = platform.decide(R("transfer", "payments/acct/1", amount_band="low", channel="web"))
    b = platform.decide(R("transfer", "payments/acct/1", amount_band="low", channel="web"))
    for k in ("decision", "base_decision", "policy_refs", "reasons"):
        assert a[k] == b[k]


def test_memory_escalates_allow_to_review_only_after_evidence(platform):
    pid = promote_pattern(platform)
    req = R("transfer", "payments/acct/9", amount_band="low", channel="web")
    first = platform.decide(req)
    assert first["decision"] == "allow" and first["memory"]["pattern_id"] == pid
    for _ in range(5):
        platform.feedback("rev-1", True, pattern_id=pid)
    out = platform.decide(req)
    assert out["base_decision"] == "allow" and out["decision"] == "review"
    assert any("memory escalation" in r for r in out["reasons"])


def test_memory_never_relaxes_deny(platform):
    pid = promote_pattern(platform, {"channel": "api"}, action="export", resource="pii/users/1")
    for _ in range(10):
        platform.feedback("rev-1", False, pattern_id=pid)
    out = platform.decide(R("export", "pii/users/2", channel="api"))
    assert out["decision"] == "deny"


def test_memory_and_feedback_never_rewrite_policies(platform):
    before = policies_digest(platform)
    pid = promote_pattern(platform)
    for _ in range(5):
        platform.feedback("rev-1", True, pattern_id=pid)
    platform.consolidate()
    platform.discover()
    assert policies_digest(platform) == before


def test_policy_writes_refuse_memory_actors(platform):
    for actor in ("memory", "discovery:auto", "feedback-loop", "llm"):
        with pytest.raises(PolicyWriteForbidden):
            platform.propose_policy(key="k", effect="allow", match={"actions": ["*"]}, priority=1, proposed_by=actor)


def test_proposed_policy_needs_explicit_approval(platform):
    prop = platform.propose_policy(key="deny-delete", effect="deny", match={"actions": ["delete"]}, priority=90,
                                   proposed_by="human:bob")
    assert platform.decide(R("delete", "reports/1"))["decision"] == "review"
    platform.approve_policy(prop["id"], "human:carol", approved=True)
    assert platform.decide(R("delete", "reports/1"))["decision"] == "deny"
    platform.rollback_policy("allow-read", 1, "human:carol")
    assert platform.decide(R("read", "reports/1"))["decision"] == "allow"
