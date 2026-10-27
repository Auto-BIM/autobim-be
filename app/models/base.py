"""Recognition model interfaces.

CONTRACT — change only in a contract PR.

All coordinates are image pixels: origin top-left, x right, y down.
Images are `np.ndarray` of shape (H, W, 3), dtype uint8, RGB.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from app.schemas.plan import OpeningType


@dataclass(frozen=True)
class BBox:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)


@dataclass(frozen=True)
class WallMask:
    mask: np.ndarray  # (H, W) bool, True = wall pixel
    confidence: float = 1.0


@dataclass(frozen=True)
class OpeningDetection:
    type: OpeningType
    bbox: BBox
    confidence: float


@dataclass(frozen=True)
class DimensionText:
    text: str  # raw OCR text, e.g. "3,600"
    value_mm: float | None  # parsed value; None if unparseable
    bbox: BBox  # where the text is
    span: tuple[tuple[float, float], tuple[float, float]]  # the measured span's two end points
    confidence: float

    @property
    def span_px(self) -> float:
        (ax, ay), (bx, by) = self.span
        return float(np.hypot(bx - ax, by - ay))


class WallSegmenter(ABC):
    @abstractmethod
    def segment(self, image: np.ndarray) -> WallMask: ...


class OpeningDetector(ABC):
    @abstractmethod
    def detect(self, image: np.ndarray) -> list[OpeningDetection]: ...


class DimensionReader(ABC):
    @abstractmethod
    def read(self, image: np.ndarray) -> list[DimensionText]: ...
