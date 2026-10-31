"""FastAPI application entry point: `uvicorn app.main:app`."""

from __future__ import annotations

from fastapi import FastAPI

from app.api.jobs import router as jobs_router
from app.core.config import ModelSettings, Settings, get_settings
from app.jobs.store import JobStore
from app.models.registry import Models, build_models
from app.schemas.jobs import HealthResponse

API_VERSION = "0.2.0"


def _model_name(models: Models, configured: ModelSettings) -> str:
    """`/health` `model`: the bundle name if the segmenter reports one, else what is configured.

    A model adapter that loads a bundle (issue #5) exposes its name as `model_name`.
    """
    name = getattr(models.wall_segmenter, "model_name", None)
    if isinstance(name, str) and name:
        return name
    names = dict.fromkeys([configured.wall_segmenter, configured.opening_detector])  # unique
    return "+".join(names)


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

    @app.get("/health", tags=["meta"], summary="Liveness check and the configured models")
    def health() -> HealthResponse:
        configured = settings.models
        return HealthResponse(
            status="ok",
            wall_segmenter=configured.wall_segmenter,
            opening_detector=configured.opening_detector,
            model=_model_name(app.state.models, configured),
        )

    return app


app = create_app()
