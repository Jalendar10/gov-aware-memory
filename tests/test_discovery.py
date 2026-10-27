from govmem.discovery.coincidence import lift

from .conftest import HOUR, T0, ev, promote_pattern


def test_single_window_burst_is_treated_as_coincidence(platform):
    # many events, two sources, but all inside one time window -> not promoted
    for i in range(6):
        r = platform.observe(ev(source=f"app:{i % 2}", ts=T0 + i * 10))
    assert r["status"] == "pending"
    assert "windows" in r["reason"]
    assert platform.patterns() == []


def test_single_source_is_not_promoted(platform):
    for i in range(6):
        r = platform.observe(ev(source="app:only", ts=T0 + i * 2 * HOUR))
    assert r["status"] != "promoted"
    assert platform.patterns() == []


def test_diverse_recurrence_is_promoted(platform):
    pid = promote_pattern(platform)
    pats = platform.patterns()
    assert [p["id"] for p in pats] == [pid]
    assert pats[0]["support"] >= 3 and pats[0]["windows"] >= 2


def test_existing_pattern_routes_to_reinforce_not_new_candidate(platform):
    pid = promote_pattern(platform)
    before = platform.patterns()[0]
    r = platform.observe(ev(source="app:z", ts=T0 + 50 * HOUR, text="different wording entirely"))
    assert r["routed"] == "existing_pattern" and r["pattern_id"] == pid
    after = platform.patterns()[0]
    assert after["support"] == before["support"] + 1
    # observation path does not change risk scores (score update is the feedback path)
    assert after["risk"] == before["risk"] and after["alpha"] == before["alpha"]
    assert platform.quarantine() == []


def test_different_context_value_is_a_different_pattern(platform):
    promote_pattern(platform, {"amount_band": "low", "channel": "web"})
    r = platform.observe(ev(ctx={"amount_band": "medium", "channel": "web"}, ts=T0 + 40 * HOUR))
    assert r["routed"] == "candidate"


def test_lift_against_independence(platform):
    for i in range(4):
        platform.observe(ev(ctx={"k": "x"}, ts=T0 + i))
        platform.observe(ev(action="read", resource="reports/1", ctx={"k": "y"}, ts=T0 + i))
    assert lift(platform.conn, "transfer", "k=x") == 2.0
    assert lift(platform.conn, "transfer", "k=y") == 0.0


def test_discover_pass_is_idempotent(platform):
    promote_pattern(platform)
    n = len(platform.patterns())
    platform.discover()
    platform.discover()
    assert len(platform.patterns()) == n
