from __future__ import annotations

from ..config import Settings
from .base import FrozenLLM
from .http_client import HttpLLM
from .mock import MockLLM


def make_llm(s: Settings) -> FrozenLLM:
    if s.llm_backend == "http":
        return HttpLLM(s.llm_url, s.llm_model, s.llm_api_key, s.llm_timeout_s)
    return MockLLM()
