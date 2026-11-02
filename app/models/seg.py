"""`seg` adapter: the `autobim_seg` model bundle behind the backend model interfaces.

One `SegModel` is both the `WallSegmenter` and the `OpeningDetector`; the registry shares one
instance so the model is loaded once. `image_to_plan` calls `segment` and `detect` on the same
image object, so the last image is remembered and `predict` runs once per image.

`autobim_seg` is imported only when the model is built (never at module import), so the default
install and the Fake models do not need onnxruntime. The bundle's `pkg/` must be on `PYTHONPATH`
(or `autobim_seg` installed) so the code matches the bundle (docs/project/SYSTEM_SPEC.md 3.1-3.3).
"""

from __future__ import annotations

import importlib
import json
import threading
from pathlib import Path
from typing import Any

import numpy as np

from app.models.base import (
    BBox,
    OpeningDetection,
    OpeningDetector,
    WallMask,
    WallSegmenter,
)
from app.schemas.plan import OpeningType

WALL_LABEL = 1


class SegBundleError(RuntimeError):
    """The model bundle is missing or does not match the installed `autobim_seg`."""


class SegModel(WallSegmenter, OpeningDetector):
    def __init__(self, bundle_dir: str | Path | None, threads: int = 2) -> None:
        if not bundle_dir:
            raise SegBundleError(
                "the seg model needs a bundle folder: set models.seg.bundle_dir "
                "or AUTOBIM_SEG_BUNDLE"
            )
        bundle = Path(bundle_dir)
        info_path = bundle / "model.json"
        if not info_path.is_file():
            raise SegBundleError(f"model bundle not found: {info_path} does not exist")
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except ValueError as error:
            raise SegBundleError(f"{info_path} is not valid JSON: {error}") from error
        if not isinstance(info, dict) or not isinstance(info.get("name"), str) or not info["name"]:
            raise SegBundleError(f"{info_path} has no 'name' (the bundle name)")

        autobim_seg = self._import_autobim_seg(bundle)
        wanted, installed = info.get("autobim_seg_version"), autobim_seg.__version__
        if wanted != installed:
            raise SegBundleError(
                f"bundle {info['name']!r} needs autobim_seg {wanted}, installed {installed}; "
                f"put {bundle / 'pkg'} on PYTHONPATH"
            )
        try:
            self._seg = autobim_seg.load(str(bundle), runtime="onnx", threads=threads)
        except Exception as error:  # autobim_seg.BundleError, onnxruntime failures
            raise SegBundleError(f"cannot load model bundle {bundle}: {error}") from error

        self.model_name: str = info["name"]  # shown in /health
        self._lock = threading.Lock()
        # Keep the image itself, not id(image): an id can be reused after the array is freed.
        self._last_image: np.ndarray | None = None
        self._last_result: Any = None

    @staticmethod
    def _import_autobim_seg(bundle: Path) -> Any:
        try:
            return importlib.import_module("autobim_seg")
        except ImportError as error:
            raise SegBundleError(
                f"cannot import autobim_seg ({error}); install the 'seg' extra (EXTRAS=seg) "
                f"and put {bundle / 'pkg'} on PYTHONPATH"
            ) from error

    def _predict(self, image: np.ndarray) -> Any:
        with self._lock:
            if image is not self._last_image:
                self._last_result = self._seg.predict(image)
                self._last_image = image
            return self._last_result

    def segment(self, image: np.ndarray) -> WallMask:
        result = self._predict(image)
        return WallMask(
            mask=result.labels == WALL_LABEL,
            confidence=float(result.mean_confidence(WALL_LABEL)),
        )

    def detect(self, image: np.ndarray) -> list[OpeningDetection]:
        return [
            OpeningDetection(
                type=OpeningType(kind),
                bbox=BBox(float(x0), float(y0), float(x1), float(y1)),
                confidence=float(confidence),
            )
            for kind, (x0, y0, x1, y1), confidence in self._predict(image).openings()
        ]
