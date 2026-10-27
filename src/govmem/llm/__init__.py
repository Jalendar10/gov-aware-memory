"""Frozen LLM adapter. The LLM is never trained or fine-tuned by this system."""

from .base import FrozenLLM
from .factory import make_llm
from .mock import MockLLM

__all__ = ["FrozenLLM", "MockLLM", "make_llm"]
