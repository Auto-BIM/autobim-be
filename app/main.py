"""FastAPI application entry point: `uvicorn app.main:app`."""

from __future__ import annotations

from fastapi import FastAPI

from app.api.jobs import router as jobs_router
from app.core.config import Settings, get_settings
from app.jobs.store import JobStore
from app.models.registry import build_models

API_VERSION = "0.1.0"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Auto-BIM API",
        version=API_VERSION,
        description="2D floor plan (image/DXF) -> Plan -> 3D (.glb) / per-wall .dxf / JSON",
    )
    app.state.settings = settings
    app.state.store = JobStore(settings.data_dir)
    app.state.models = build_models(settings.models)
    app.include_router(jobs_router)

    @app.get("/health", tags=["meta"], summary="Liveness check")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
