"""FastAPI application factory. Run: uvicorn --factory govmem.api.app:create_app"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..platform import Platform
from . import routes_admin, routes_governance, routes_memory

STATIC = Path(__file__).resolve().parent.parent / "dashboard" / "static"


def create_app(platform: Platform | None = None) -> FastAPI:
    app = FastAPI(title="Governance-Aware Adaptive Memory (V1)", version=__version__)
    app.state.platform = platform or Platform()
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")
    @app.get("/api/health")
    def health(request: Request) -> dict[str, Any]:
        p: Platform = request.app.state.platform
        return {"status": "ok", "version": __version__, "llm": p.llm.name, "embedder": p.ctx.embedder.name,
                "encoding": p.settings.encoding, "budget_bytes": p.settings.byte_budget,
                "architecture": "v1: frozen LLM + external adaptive memory; external policy authoritative"}

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/dashboard/")

    app.include_router(routes_governance.router)
    app.include_router(routes_memory.router)
    app.include_router(routes_admin.router)
    app.mount("/dashboard", StaticFiles(directory=STATIC, html=True), name="dashboard")
    return app
