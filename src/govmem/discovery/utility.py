"""Retention utility used for forgetting under the byte budget.

U(p) = w_s * log(1+support)/log(1+max_support)
     + w_r * reliability
     + w_t * 2^(-(now - last_seen)/half_life)
     + w_g * governance_usefulness
"""

from __future__ import annotations

import math

from ..config import Settings
from ..memory.encode import PatternState


def utility(p: PatternState, now: float, max_support: int, s: Settings) -> float:
    sup = math.log1p(p.support) / math.log1p(max(max_support, 1))
    rec = 2 ** (-(max(0.0, now - p.last_seen)) / s.recency_half_life_s)
    return s.w_support * sup + s.w_reliability * p.reliability + s.w_recency * rec + s.w_usefulness * p.usefulness
