"""Settings loaded from config/settings.yaml with env overrides."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT_DIR / "config" / "settings.yaml"


class SegSettings(BaseModel):
    bundle_dir: str | None = None  # model bundle folder (SYSTEM_SPEC 3.1); required when `seg` is used
    threads: int = Field(default=2, gt=0)  # ONNX Runtime intra-op threads


class ModelSettings(BaseModel):
    wall_segmenter: str = "fake"
    opening_detector: str = "fake"
    dimension_reader: str = "fake"
    seg: SegSettings = Field(default_factory=SegSettings)


class StorageSettings(BaseModel):
    data_dir: str = "data/jobs"


class LimitsSettings(BaseModel):
    max_upload_mb: int = Field(default=30, gt=0)
    max_pixels: int = Field(default=40_000_000, gt=0)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


class RecognitionSettings(BaseModel):
    review_confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)


class Settings(BaseModel):
    models: ModelSettings = Field(default_factory=ModelSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    limits: LimitsSettings = Field(default_factory=LimitsSettings)
    recognition: RecognitionSettings = Field(default_factory=RecognitionSettings)

    @property
    def data_dir(self) -> Path:
        path = Path(self.storage.data_dir)
        return path if path.is_absolute() else ROOT_DIR / path


_ENV_MODEL_OVERRIDES = {
    "AUTOBIM_WALL_SEGMENTER": "wall_segmenter",
    "AUTOBIM_OPENING_DETECTOR": "opening_detector",
    "AUTOBIM_DIMENSION_READER": "dimension_reader",
}
_ENV_SEG_OVERRIDES = {
    "AUTOBIM_SEG_BUNDLE": "bundle_dir",
    "AUTOBIM_SEG_THREADS": "threads",
}
_ENV_LIMIT_OVERRIDES = {
    "AUTOBIM_MAX_UPLOAD_MB": "max_upload_mb",
    "AUTOBIM_MAX_PIXELS": "max_pixels",
}


def load_settings(path: str | Path | None = None) -> Settings:
    path = Path(path or os.environ.get("AUTOBIM_CONFIG") or DEFAULT_CONFIG_PATH)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    limits = raw["limits"] = raw.get("limits") or {}
    for env, field in _ENV_LIMIT_OVERRIDES.items():
        if value := os.environ.get(env):
            limits[field] = value  # validated (and coerced to int) with the rest of the file
    models = raw["models"] = raw.get("models") or {}
    seg = models["seg"] = models.get("seg") or {}
    for env, field in _ENV_SEG_OVERRIDES.items():
        if value := os.environ.get(env):
            seg[field] = value  # validated (and coerced to int) with the rest of the file
    settings = Settings.model_validate(raw)
    for env, field in _ENV_MODEL_OVERRIDES.items():
        if value := os.environ.get(env):
            setattr(settings.models, field, value)
    if data_dir := os.environ.get("AUTOBIM_DATA_DIR"):
        settings.storage.data_dir = data_dir
    return settings


@lru_cache
def get_settings() -> Settings:
    return load_settings()
