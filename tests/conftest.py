from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import ModelSettings, Settings, StorageSettings
from app.main import create_app
from app.models.registry import build_models
from app.recognition.pipeline import image_to_plan
from app.schemas.plan import Plan


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        models=ModelSettings(wall_segmenter="fake", opening_detector="fake", dimension_reader="fake"),
        storage=StorageSettings(data_dir=str(tmp_path / "jobs")),
    )


@pytest.fixture
def client(settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture
def png_bytes() -> bytes:
    """Any image works: the fake models ignore its content. Generated, not committed."""
    buf = io.BytesIO()
    Image.fromarray(np.full((70, 100, 3), 255, dtype=np.uint8)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def fake_plan() -> Plan:
    return image_to_plan(np.zeros((8, 8, 3), np.uint8), build_models(ModelSettings()))
