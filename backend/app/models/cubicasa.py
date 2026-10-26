"""CubiCasa5k baseline adapter — placeholder.

Real model loading and inference land in next-tasks #4. Kept import-light on purpose
(no torch import here) so the default fake configuration has no heavy dependencies.
"""

from __future__ import annotations

import numpy as np

from app.models.base import OpeningDetection, OpeningDetector, WallMask, WallSegmenter

_TODO = "CubiCasa adapter is not implemented yet (see docs/next-tasks.md #4)"


class CubiCasaWallSegmenter(WallSegmenter):
    def __init__(self, weights_path: str | None = None) -> None:
        self.weights_path = weights_path

    def segment(self, image: np.ndarray) -> WallMask:
        raise NotImplementedError(_TODO)


class CubiCasaOpeningDetector(OpeningDetector):
    def __init__(self, weights_path: str | None = None) -> None:
        self.weights_path = weights_path

    def detect(self, image: np.ndarray) -> list[OpeningDetection]:
        raise NotImplementedError(_TODO)
