"""Fixed-size binary pattern records (see schema.sql for the byte layouts).

FULL      = 96 B  (within the 80-128 B design band)
COMPACT64 = 64 B  (lossy: f16 Beta params, u8 scores, int4 centroid)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from ..util import blake, h32
from .embed import DIM

FULL_FMT = "<8sIIIIfffffIIHBB8s32b"
COMPACT_FMT = "<8sIIIHeeBBBBIIHBB4s16s2x"
FULL_SIZE = struct.calcsize(FULL_FMT)
COMPACT_SIZE = struct.calcsize(COMPACT_FMT)
assert FULL_SIZE == 96, FULL_SIZE
assert COMPACT_SIZE == 64, COMPACT_SIZE

SIZES = {"full": FULL_SIZE, "compact64": COMPACT_SIZE}

FLAG_MERGED_INTO = 0x01   # record absorbed at least one other pattern
FLAG_HUMAN_APPROVED = 0x02
FLAG_POISON_SUSPECT = 0x04


@dataclass
class PatternState:
    action: str
    resource_class: str
    context_key: str
    signature: bytes
    support: int = 0
    alpha: float = 1.0
    beta: float = 3.0
    ema_risk: float = 0.25
    reliability: float = 1.0
    usefulness: float = 0.5
    first_seen: float = 0.0
    last_seen: float = 0.0
    windows: int = 0
    flags: int = 0
    version: int = 1
    provenance: bytes = b"\x00" * 8
    centroid: list[float] = field(default_factory=lambda: [0.0] * DIM)

    @property
    def risk(self) -> float:
        return self.alpha / (self.alpha + self.beta)


def _q8(v: float) -> int:
    return max(-127, min(127, round(v * 127)))


def _u8(x: float) -> int:
    return max(0, min(255, round(x * 255)))


def _pack_int4(vals: list[float]) -> bytes:
    q = [max(-7, min(7, round(v * 7))) & 0x0F for v in vals]
    return bytes((q[i] | (q[i + 1] << 4)) for i in range(0, len(q), 2))


def _unpack_int4(b: bytes) -> list[float]:
    out: list[float] = []
    for byte in b:
        for nib in (byte & 0x0F, byte >> 4):
            out.append((nib - 16 if nib > 7 else nib) / 7.0)
    return out


def encode(p: PatternState, mode: str) -> bytes:
    ah, rh, ch = h32(p.action), h32(p.resource_class), h32(p.context_key)
    if mode == "full":
        return struct.pack(
            FULL_FMT, p.signature, ah, rh, ch, min(p.support, 2**32 - 1),
            p.alpha, p.beta, p.ema_risk, p.reliability, p.usefulness,
            int(p.first_seen), int(p.last_seen), min(p.windows, 65535), p.flags & 0xFF,
            p.version & 0xFF, p.provenance[:8].ljust(8, b"\x00"), *[_q8(v) for v in p.centroid],
        )
    if mode == "compact64":
        return struct.pack(
            COMPACT_FMT, p.signature, ah, rh, ch, min(p.support, 65535),
            min(p.alpha, 65000.0), min(p.beta, 65000.0), _u8(p.ema_risk), _u8(p.reliability),
            _u8(p.usefulness), p.flags & 0xFF, int(p.first_seen), int(p.last_seen),
            min(p.windows, 65535), p.version & 0xFF, 0, p.provenance[:4].ljust(4, b"\x00"),
            _pack_int4(p.centroid),
        )
    raise ValueError(mode)


def decode(blob: bytes, mode: str, action: str, resource_class: str, context_key: str, version: int) -> PatternState:
    """Decode a record. Strings come from the index mirror; their hashes are verified."""
    if mode == "full":
        t = struct.unpack(FULL_FMT, blob)
        sig, ah, rh, ch, sup, a, b, ema, rel, use, fs, ls, win, flags, _v, prov = t[:16]
        centroid = [x / 127.0 for x in t[16:]]
    elif mode == "compact64":
        sig, ah, rh, ch, sup, a, b, ema, rel, use, flags, fs, ls, win, _v, _r, prov, c = struct.unpack(COMPACT_FMT, blob)
        ema, rel, use = ema / 255.0, rel / 255.0, use / 255.0
        centroid = _unpack_int4(c)
    else:
        raise ValueError(mode)
    if (ah, rh, ch) != (h32(action), h32(resource_class), h32(context_key)):
        raise ValueError("pattern record does not match its index mirror (possible tampering)")
    return PatternState(
        action=action, resource_class=resource_class, context_key=context_key, signature=sig,
        support=sup, alpha=float(a), beta=float(b), ema_risk=float(ema), reliability=float(rel),
        usefulness=float(use), first_seen=float(fs), last_seen=float(ls), windows=win,
        flags=flags, version=version, provenance=prov, centroid=centroid,
    )


def provenance_hash(parts: list[str]) -> bytes:
    return blake("|".join(sorted(parts)), 8)
