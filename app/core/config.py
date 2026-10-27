"""Settings loaded from config/settings.yaml with env overrides."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT_DIR / "config" / "settings.yaml"


class CubiCasaSettings(BaseModel):
    weights_path: str | None = None


class ModelSettings(BaseModel):
    wall_segmenter: str = "fake"
    opening_detector: str = "fake"
    dimension_reader: str = "fake"
    cubicasa: CubiCasaSettings = Field(default_factory=CubiCasaSettings)


class StorageSettings(BaseModel):
    data_dir: str = "data/jobs"


class RecognitionSettings(BaseModel):
    review_confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)


class Settings(BaseModel):
    models: ModelSettings = Field(default_factory=ModelSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
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


def load_settings(path: str | Path | None = None) -> Settings:
    path = Path(path or os.environ.get("AUTOBIM_CONFIG") or DEFAULT_CONFIG_PATH)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
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
