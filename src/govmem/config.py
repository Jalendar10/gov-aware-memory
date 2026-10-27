"""Runtime settings, loaded from GOVMEM_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields


def _env(name: str, default: str) -> str:
    return os.environ.get(f"GOVMEM_{name.upper()}", default)


@dataclass
class Settings:
    # storage
    db_path: str = "data/govmem.db"
    byte_budget: int = 4096                 # budget B for pattern_memory encoded bytes
    encoding: str = "full"                  # full (96 B) | compact64 (64 B)

    # discovery: same-pattern vs coincidence
    match_threshold: float = 0.95           # cosine to route an event to an EXISTING pattern
    candidate_threshold: float = 0.95       # cosine to join an existing quarantine candidate
    merge_threshold: float = 0.98           # cosine for consolidation merge of two patterns
    min_support: int = 3
    min_windows: int = 2                    # temporal diversity: distinct time windows
    min_sources: int = 2                    # provenance diversity: distinct sources
    min_lift: float = 1.0                   # co-occurrence lift(action, context) vs independence
    window_seconds: int = 3600
    promote_threshold: float = 0.5          # validation score needed for synthetic approval
    require_human_review: bool = False      # if true, every candidate needs a human approve

    # poisoning protection
    burst_fraction: float = 0.8             # one source contributing >= this share => flag
    min_source_trust: float = 0.3
    default_source_trust: float = 1.0

    # governance
    default_effect: str = "review"          # when no policy matches
    risk_review_threshold: float = 0.6      # memory risk at/above which Allow -> Review
    risk_min_evidence: float = 2.0          # feedback mass required before memory may escalate

    # feedback / adaptation (no LLM fine-tuning)
    prior_alpha: float = 1.0
    prior_beta: float = 3.0
    ema_lambda: float = 0.2
    min_reviewer_reliability: float = 0.2
    reviewer_prior_alpha: float = 4.0
    reviewer_prior_beta: float = 1.0

    # forgetting utility
    recency_half_life_s: float = 7 * 86400.0
    w_support: float = 0.3
    w_reliability: float = 0.25
    w_recency: float = 0.2
    w_usefulness: float = 0.25

    # frozen LLM adapter
    llm_backend: str = "mock"               # mock | http (OpenAI-compatible: vLLM, llama.cpp, Ollama)
    llm_url: str = "http://localhost:8001/v1"
    llm_model: str = "Qwen/Qwen2.5-7B-Instruct"
    llm_api_key: str = ""
    llm_timeout_s: float = 30.0

    # embedder
    embedder: str = "hash"                  # hash | st (sentence-transformers, optional)
    st_model: str = "all-MiniLM-L6-v2"

    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls()
        for f in fields(cls):
            if f.name == "extra":
                continue
            raw = os.environ.get(f"GOVMEM_{f.name.upper()}")
            if raw is None:
                continue
            cur = getattr(s, f.name)
            if isinstance(cur, bool):
                val: object = raw.strip().lower() in ("1", "true", "yes", "on")
            elif isinstance(cur, int):
                val = int(raw)
            elif isinstance(cur, float):
                val = float(raw)
            else:
                val = raw
            setattr(s, f.name, val)
        if s.encoding not in ("full", "compact64"):
            raise ValueError("GOVMEM_ENCODING must be 'full' or 'compact64'")
        return s
