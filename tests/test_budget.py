from govmem.audit import log
from govmem.memory import store
from govmem.memory.encode import PatternState
from govmem.memory.embed import HashEmbedder
from govmem.util import signature

from .conftest import HOUR, T0, ev, make_platform, promote_pattern


def test_forget_lowest_utility_under_budget():
    p = make_platform(byte_budget=96 * 3)
    bands = ["a", "b", "c", "d", "e"]
    ids = [promote_pattern(p, {"amount_band": b}) for b in bands]
    st = p.stats()
    assert st["pattern_bytes"] <= 96 * 3
    assert st["pattern_count"] == 3
    forgotten = [e for e in p.audit(200) if e["event_type"] == "pattern_forgotten"]
    assert len(forgotten) == 2
    assert all(e["payload"]["bytes_freed"] == 96 for e in forgotten)
    assert forgotten[0]["payload"]["bytes_after"] <= forgotten[0]["payload"]["budget"]
    statuses = {r["id"]: r["status"] for r in p.patterns(None)}
    assert sum(1 for s in statuses.values() if s == "forgotten") == 2
    assert set(statuses) == set(ids)


def test_high_utility_pattern_survives():
    p = make_platform(byte_budget=96 * 2)
    strong = promote_pattern(p, {"amount_band": "strong"})
    for i in range(20):  # heavy, recent support
        p.observe(ev(ctx={"amount_band": "strong"}, source=f"app:{i % 3}", ts=T0 + 90 * HOUR + i))
    promote_pattern(p, {"amount_band": "weak1"})
    promote_pattern(p, {"amount_band": "weak2"})
    active = {r["id"] for r in p.patterns()}
    assert strong in active and len(active) == 2


def test_merge_near_duplicates_frees_bytes():
    p = make_platform()
    c = HashEmbedder().embed("transfer", "payments", {"amount_band": "low"}, "")
    for sup in (5, 2):
        st = PatternState("transfer", "payments", "amount_band=low", signature("transfer", "payments", "amount_band=low"),
                          support=sup, first_seen=T0, last_seen=T0 + HOUR, windows=2, centroid=c)
        store.insert_pattern(p.conn, st, "full", T0)
    assert p.stats()["pattern_bytes"] == 192
    out = p.consolidate()
    assert len(out["merged"]) == 1
    assert p.stats()["pattern_bytes"] == 96
    assert p.patterns()[0]["support"] == 7
    assert log.verify(p.conn)["ok"]
