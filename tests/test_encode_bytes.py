import pytest

from govmem.memory.embed import HashEmbedder
from govmem.memory.encode import COMPACT_SIZE, FULL_SIZE, PatternState, decode, encode
from govmem.util import signature

from .conftest import make_platform, promote_pattern


def _state() -> PatternState:
    c = HashEmbedder().embed("transfer", "payments", {"amount_band": "low"}, "")
    return PatternState("transfer", "payments", "amount_band=low", signature("transfer", "payments", "amount_band=low"),
                        support=42, alpha=2.5, beta=7.25, ema_risk=0.3, reliability=0.9, usefulness=0.6,
                        first_seen=1_700_000_000, last_seen=1_700_090_000, windows=5, flags=2, version=3,
                        provenance=b"12345678", centroid=c)


def test_record_sizes_match_design_band():
    assert FULL_SIZE == 96 and 80 <= FULL_SIZE <= 128
    assert COMPACT_SIZE == 64
    assert len(encode(_state(), "full")) == 96
    assert len(encode(_state(), "compact64")) == 64


def test_full_roundtrip():
    s = _state()
    d = decode(encode(s, "full"), "full", s.action, s.resource_class, s.context_key, s.version)
    assert d.support == 42 and d.windows == 5 and d.flags == 2
    assert d.alpha == pytest.approx(2.5) and d.beta == pytest.approx(7.25)
    assert max(abs(a - b) for a, b in zip(d.centroid, s.centroid)) <= 1 / 127


def test_compact_roundtrip_is_bounded_lossy():
    s = _state()
    d = decode(encode(s, "compact64"), "compact64", s.action, s.resource_class, s.context_key, s.version)
    assert d.support == 42
    assert d.alpha == pytest.approx(2.5, abs=0.01) and d.beta == pytest.approx(7.25, abs=0.01)
    assert d.ema_risk == pytest.approx(0.3, abs=1 / 255)
    assert max(abs(a - b) for a, b in zip(d.centroid, s.centroid)) <= 1 / 14 + 1e-9


def test_mirror_tamper_detected():
    s = _state()
    with pytest.raises(ValueError):
        decode(encode(s, "full"), "full", "export", s.resource_class, s.context_key, 1)


@pytest.mark.parametrize("mode,size", [("full", 96), ("compact64", 64)])
def test_stats_count_exact_record_bytes(mode, size):
    p = make_platform(encoding=mode)
    promote_pattern(p, {"amount_band": "low"})
    promote_pattern(p, {"amount_band": "medium"})
    st = p.stats()
    assert st["pattern_count"] == 2
    assert st["pattern_bytes"] == 2 * size
    assert st["record_size_bytes"] == size
    assert st["episodic_count"] >= 6
