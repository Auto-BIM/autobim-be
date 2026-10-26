import numpy as np
import pytest

from app.core.config import ModelSettings, load_settings
from app.models.cubicasa import CubiCasaOpeningDetector, CubiCasaWallSegmenter
from app.models.fake import FakeDimensionReader, FakeOpeningDetector, FakeWallSegmenter
from app.models.registry import build_models

IMG = np.zeros((16, 16, 3), np.uint8)


def test_default_config_selects_fakes():
    models = build_models(load_settings().models)
    assert isinstance(models.wall_segmenter, FakeWallSegmenter)
    assert isinstance(models.opening_detector, FakeOpeningDetector)
    assert isinstance(models.dimension_reader, FakeDimensionReader)


def test_env_override(monkeypatch):
    monkeypatch.setenv("AUTOBIM_WALL_SEGMENTER", "cubicasa")
    assert load_settings().models.wall_segmenter == "cubicasa"


def test_fakes_are_deterministic():
    a, b = FakeWallSegmenter().segment(IMG), FakeWallSegmenter().segment(IMG)
    assert a.mask.dtype == bool and np.array_equal(a.mask, b.mask)
    dets = FakeOpeningDetector().detect(IMG)
    assert dets == FakeOpeningDetector().detect(IMG)
    assert all(0 <= d.confidence <= 1 for d in dets)
    dims = FakeDimensionReader().read(IMG)
    assert dims[0].value_mm == 8000 and dims[0].span_px == 800


def test_cubicasa_selected_but_not_implemented():
    models = build_models(ModelSettings(wall_segmenter="cubicasa", opening_detector="cubicasa"))
    assert isinstance(models.wall_segmenter, CubiCasaWallSegmenter)
    assert isinstance(models.opening_detector, CubiCasaOpeningDetector)
    with pytest.raises(NotImplementedError):
        models.wall_segmenter.segment(IMG)
    with pytest.raises(NotImplementedError):
        models.opening_detector.detect(IMG)


def test_unknown_implementation_name():
    with pytest.raises(ValueError, match="unknown wall_segmenter"):
        build_models(ModelSettings(wall_segmenter="nope"))
