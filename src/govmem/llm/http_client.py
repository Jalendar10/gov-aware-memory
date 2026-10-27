"""Thin client for an OpenAI-compatible /chat/completions endpoint serving an open-weight model
(e.g. Qwen2.5 or Llama 3 via vLLM, llama.cpp server, or Ollama). Enabled by GOVMEM_LLM_BACKEND=http.
Inference only; never sends training or fine-tuning requests."""

from __future__ import annotations

import json
import urllib.request
from typing import Any


class HttpLLM:
    def __init__(self, base_url: str, model: str, api_key: str = "", timeout_s: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.name = f"http:{model}"

    def complete_json(self, system: str, prompt: str) -> dict[str, Any]:
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.loads(resp.read())
            content = data["choices"][0]["message"]["content"]
            out = json.loads(content)
            return out if isinstance(out, dict) else {"value": out, "model": self.name}
        except Exception as e:  # advisory only: failure never blocks governance
            return {"error": f"{type(e).__name__}: {e}", "model": self.name}
