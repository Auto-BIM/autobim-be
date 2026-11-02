import json
import os
import subprocess
import sys
import textwrap
import threading
import time
import types
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core.config import ModelSettings, SegSettings, Settings, StorageSettings, load_settings
from app.main import create_app
from app.models.base import BBox, OpeningDetection
from app.models.fake import FakeDimensionReader, FakeOpeningDetector, FakeWallSegmenter
from app.models.registry import build_models
from app.models.seg import RECENT_IMAGES, SegBundleError, SegModel
from app.recognition.pipeline import image_to_plan
from app.schemas.plan import OpeningType

IMG = np.zeros((16, 16, 3), np.uint8)


def test_default_config_selects_fakes():
    models = build_models(load_settings().models)
    assert isinstance(models.wall_segmenter, FakeWallSegmenter)
    assert isinstance(models.opening_detector, FakeOpeningDetector)
    assert isinstance(models.dimension_reader, FakeDimensionReader)


def test_env_override(monkeypatch):
    monkeypatch.setenv("AUTOBIM_WALL_SEGMENTER", "seg")
    assert load_settings().models.wall_segmenter == "seg"


def test_seg_env_overrides(monkeypatch):
    monkeypatch.setenv("AUTOBIM_SEG_BUNDLE", "/models/current")
    monkeypatch.setenv("AUTOBIM_SEG_THREADS", "3")
    seg = load_settings().models.seg
    assert (seg.bundle_dir, seg.threads) == ("/models/current", 3)


def test_fakes_are_deterministic():
    a, b = FakeWallSegmenter().segment(IMG), FakeWallSegmenter().segment(IMG)
    assert a.mask.dtype == bool and np.array_equal(a.mask, b.mask)
    dets = FakeOpeningDetector().detect(IMG)
    assert dets == FakeOpeningDetector().detect(IMG)
    assert all(0 <= d.confidence <= 1 for d in dets)
    dims = FakeDimensionReader().read(IMG)
    assert dims[0].value_mm == 8000 and dims[0].span_px == 800


def test_unknown_implementation_name():
    with pytest.raises(ValueError, match="unknown wall_segmenter"):
        build_models(ModelSettings(wall_segmenter="nope"))


# --- seg adapter, against a fake `autobim_seg` (no onnxruntime, no real bundle) ---------------


class _FakeResult:
    labels = np.array([[0, 1], [2, 3]], np.uint8)

    def mean_confidence(self, label):
        return np.float32(0.75)

    def openings(self):
        return [("door", (np.int64(1), 2, 3.5, 4), np.float32(0.5)), ("window", (0, 0, 2, 2), 0.9)]


class _FakeSegmenter:
    def __init__(self):
        self.calls = 0

    def predict(self, image):
        self.calls += 1
        return _FakeResult()


@pytest.fixture
def fake_autobim_seg(monkeypatch):
    module = types.ModuleType("autobim_seg")
    module.__version__ = "0.1.0"
    module.segmenter = _FakeSegmenter()
    module.loaded = []

    def load(path, runtime="onnx", threads=2):
        module.loaded.append((path, runtime, threads))
        return module.segmenter

    module.load = load
    monkeypatch.setitem(sys.modules, "autobim_seg", module)
    return module


def _write_bundle(root: Path, name="seg-v1", version="0.1.0") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "model.json").write_text(
        json.dumps({"name": name, "autobim_seg_version": version}), encoding="utf-8"
    )
    return root


@pytest.fixture
def bundle(tmp_path) -> Path:
    return _write_bundle(tmp_path / "seg-v1")


def _seg_settings(bundle_dir, **kw) -> ModelSettings:
    return ModelSettings(
        wall_segmenter="seg",
        opening_detector="seg",
        dimension_reader="none",
        seg=SegSettings(bundle_dir=str(bundle_dir), **kw),
    )


def test_seg_converts_results(fake_autobim_seg, bundle):
    model = SegModel(bundle, threads=3)
    assert fake_autobim_seg.loaded == [(str(bundle), "onnx", 3)]
    wall = model.segment(IMG)
    assert wall.mask.dtype == bool
    assert wall.mask.tolist() == [[False, True], [False, False]]
    assert type(wall.confidence) is float and wall.confidence == 0.75
    door, window = model.detect(IMG)
    assert door == OpeningDetection(OpeningType.door, BBox(1.0, 2.0, 3.5, 4.0), 0.5)
    assert type(door.confidence) is float and type(door.bbox.x0) is float
    assert window.type is OpeningType.window


def test_seg_predicts_once_per_image(fake_autobim_seg, bundle):
    model = SegModel(bundle)
    model.segment(IMG)
    model.detect(IMG)
    model.segment(IMG)
    assert fake_autobim_seg.segmenter.calls == 1
    other = IMG.copy()  # equal content, different object
    model.detect(other)
    assert fake_autobim_seg.segmenter.calls == 2


def test_seg_interleaved_jobs_predict_once_each(fake_autobim_seg, bundle):
    """Two jobs run in threads: A segment, B segment, A detect. B must not evict A's result."""
    model = SegModel(bundle)
    image_a, image_b = IMG.copy(), IMG.copy()
    a_segmented, b_segmented = threading.Event(), threading.Event()

    def job_a():
        model.segment(image_a)
        a_segmented.set()
        assert b_segmented.wait(5)
        model.detect(image_a)

    def job_b():
        assert a_segmented.wait(5)
        model.segment(image_b)
        b_segmented.set()
        model.detect(image_b)

    threads = [threading.Thread(target=job_a), threading.Thread(target=job_b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert not any(t.is_alive() for t in threads)
    assert fake_autobim_seg.segmenter.calls == 2


def test_seg_keeps_only_recent_images(fake_autobim_seg, bundle):
    model = SegModel(bundle)
    images = [IMG.copy() for _ in range(RECENT_IMAGES + 1)]
    for image in images:
        model.segment(image)
    assert fake_autobim_seg.segmenter.calls == RECENT_IMAGES + 1
    model.detect(images[-1])  # still remembered
    assert fake_autobim_seg.segmenter.calls == RECENT_IMAGES + 1
    model.detect(images[0])  # evicted
    assert fake_autobim_seg.segmenter.calls == RECENT_IMAGES + 2


def test_seg_lock_serializes_concurrent_predict(fake_autobim_seg, bundle):
    """Without the lock, both threads miss the cache and predict the same image."""
    slow = fake_autobim_seg.segmenter
    original = slow.predict

    def slow_predict(image):
        time.sleep(0.2)
        return original(image)

    slow.predict = slow_predict
    model = SegModel(bundle)
    start = threading.Barrier(2)

    def call():
        start.wait()
        model.segment(IMG)

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert slow.calls == 1


def test_seg_in_pipeline_predicts_once(fake_autobim_seg, bundle):
    """`image_to_plan` hands the same image to `segment` and `detect`."""

    class Result(_FakeResult):
        def __init__(self, image):
            self.labels = labels = np.zeros(image.shape[:2], np.uint8)
            labels[4:60, 10:14] = labels[4:60, 86:90] = 1  # a closed room
            labels[4:8, 10:90] = labels[56:60, 10:90] = 1

        def openings(self):
            return [("door", (40, 3, 60, 9), 0.8)]

    fake_autobim_seg.segmenter.predict = lambda image: (
        setattr(fake_autobim_seg.segmenter, "calls", fake_autobim_seg.segmenter.calls + 1)
        or Result(image)
    )
    plan = image_to_plan(np.full((64, 100, 3), 255, np.uint8), build_models(_seg_settings(bundle)))
    assert fake_autobim_seg.segmenter.calls == 1
    assert len(plan.walls) == 4 and len(plan.openings) == 1


def test_seg_roles_share_one_instance(fake_autobim_seg, bundle):
    models = build_models(_seg_settings(bundle))
    assert models.wall_segmenter is models.opening_detector
    assert len(fake_autobim_seg.loaded) == 1
    assert build_models(_seg_settings(bundle)).wall_segmenter is not models.wall_segmenter


def test_seg_for_one_role_only(fake_autobim_seg, bundle):
    settings = _seg_settings(bundle)
    settings.opening_detector = "fake"
    models = build_models(settings)
    assert isinstance(models.wall_segmenter, SegModel)
    assert isinstance(models.opening_detector, FakeOpeningDetector)


def test_health_shows_bundle_name(fake_autobim_seg, tmp_path):
    bundle = _write_bundle(tmp_path / "seg-v7", name="seg-v7")
    settings = Settings(
        models=_seg_settings(bundle), storage=StorageSettings(data_dir=str(tmp_path / "jobs"))
    )
    body = TestClient(create_app(settings)).get("/health").json()
    assert body["model"] == "seg-v7"
    assert body["wall_segmenter"] == body["opening_detector"] == "seg"


def test_seg_without_bundle_dir_fails_at_startup(fake_autobim_seg, tmp_path):
    with pytest.raises(SegBundleError, match="AUTOBIM_SEG_BUNDLE"):
        create_app(
            Settings(
                models=ModelSettings(wall_segmenter="seg"),
                storage=StorageSettings(data_dir=str(tmp_path / "jobs")),
            )
        )


def test_seg_missing_bundle(fake_autobim_seg, tmp_path):
    with pytest.raises(SegBundleError, match="model.json"):
        build_models(_seg_settings(tmp_path / "nope"))


def test_seg_bad_model_json(fake_autobim_seg, tmp_path):
    (tmp_path / "model.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SegBundleError, match="not valid JSON"):
        SegModel(tmp_path)
    (tmp_path / "model.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SegBundleError, match="'name'"):
        SegModel(tmp_path)


def test_seg_version_mismatch(fake_autobim_seg, tmp_path):
    bundle = _write_bundle(tmp_path / "seg-v2", name="seg-v2", version="0.2.0")
    with pytest.raises(SegBundleError, match=r"needs autobim_seg 0\.2\.0, installed 0\.1\.0"):
        build_models(_seg_settings(bundle))
    assert fake_autobim_seg.loaded == []


def test_seg_package_not_installed(monkeypatch, bundle):
    monkeypatch.setitem(sys.modules, "autobim_seg", None)  # makes `import autobim_seg` fail
    with pytest.raises(SegBundleError, match="EXTRAS=seg"):
        SegModel(bundle)


def test_seg_load_failure_is_wrapped(fake_autobim_seg, bundle):
    def boom(*args, **kwargs):
        raise RuntimeError("sha256 mismatch")

    fake_autobim_seg.load = boom
    with pytest.raises(SegBundleError, match="sha256 mismatch"):
        SegModel(bundle)


def test_default_app_does_not_import_heavy_modules():
    """Fake models only: neither autobim_seg nor onnxruntime/torch gets imported. Own process,
    so the result does not depend on what other tests already imported."""
    root = Path(__file__).resolve().parents[1]
    code = textwrap.dedent(
        f"""
        import sys, tempfile
        from pathlib import Path
        import app
        assert Path(app.__file__).resolve().is_relative_to(Path({str(root)!r})), app.__file__
        from app.core.config import ModelSettings, Settings, StorageSettings
        from app.main import create_app
        create_app(Settings(models=ModelSettings(), storage=StorageSettings(data_dir=tempfile.mkdtemp())))
        heavy = [m for m in ("autobim_seg", "onnxruntime", "torch", "cv2") if m in sys.modules]
        assert not heavy, heavy
        """
    )
    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root)},
    )


# --- real bundle: opt in with AUTOBIM_SEG_BUNDLE and `pytest -m model` ---------------------------


@pytest.mark.model
@pytest.mark.skipif(not os.environ.get("AUTOBIM_SEG_BUNDLE"), reason="AUTOBIM_SEG_BUNDLE not set")
def test_real_bundle():
    pytest.importorskip("onnxruntime")
    model = SegModel(os.environ["AUTOBIM_SEG_BUNDLE"], threads=2)
    image = np.full((256, 256, 3), 255, np.uint8)
    wall = model.segment(image)
    assert wall.mask.shape == image.shape[:2] and wall.mask.dtype == bool
    assert 0.0 <= wall.confidence <= 1.0
    assert all(0.0 <= d.confidence <= 1.0 for d in model.detect(image))
    assert isinstance(model.model_name, str) and model.model_name
