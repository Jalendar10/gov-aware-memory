"""FrozenLLM protocol: inference only. There is deliberately no train/update method."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class FrozenLLM(Protocol):
    name: str

    def complete_json(self, system: str, prompt: str) -> dict[str, Any]:
        """Return a JSON object. Must not mutate model weights."""
        ...


ADVISORY_SYSTEM = (
    "You are an advisory assistant inside an AI governance service. You do NOT make the decision; "
    "an external deterministic policy engine does. Return JSON with keys: summary (string), "
    "risk_hint (number 0..1), tags (list of strings)."
)


def advisory_prompt(action: str, resource: str, context: dict[str, Any], text: str) -> str:
    return f"action={action}\nresource={resource}\ncontext={context}\nrequest_text={text}"
