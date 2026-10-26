"""Deterministic fake models. They ignore the image and describe one fixed floor plan.

Fixed plan (pixels, 1 px = 10 mm via the dimension reading):

    (100,100) ┌──────────────W──┬──────────────┐ (900,100)
              │                 │              │
              D                 D              │
              │                 │              W
              │                 │              │
    (100,600) └─────D───────────┴──────────────┘ (900,600)

Outer walls 20 px thick (200 mm), one interior wall at x=500, 12 px (120 mm).
"""

from __future__ import annotations

import numpy as np

from app.models.base import (
    BBox,
    DimensionReader,
    DimensionText,
    OpeningDetection,
    OpeningDetector,
    WallMask,
    WallSegmenter,
)
from app.schemas.plan import OpeningType

FAKE_SIZE = (700, 1000)  # (H, W) of the fake scene
OUTER = (100, 100, 900, 600)  # x0, y0, x1, y1 of exterior wall centerlines
OUTER_T = 20
INNER_X = 500
INNER_T = 12


def fake_wall_mask() -> np.ndarray:
    h, w = FAKE_SIZE
    mask = np.zeros((h, w), dtype=bool)
    x0, y0, x1, y1 = OUTER
    half = OUTER_T // 2
    mask[y0 - half : y0 + half, x0 - half : x1 + half] = True  # top
    mask[y1 - half : y1 + half, x0 - half : x1 + half] = True  # bottom
    mask[y0 - half : y1 + half, x0 - half : x0 + half] = True  # left
    mask[y0 - half : y1 + half, x1 - half : x1 + half] = True  # right
    ih = INNER_T // 2
    mask[y0:y1, INNER_X - ih : INNER_X + ih] = True  # interior
    return mask


FAKE_OPENINGS = [
    # front door on the bottom wall: 90 px wide
    OpeningDetection(OpeningType.door, BBox(205, 590, 295, 610), 0.95),
    # door in the interior wall
    OpeningDetection(OpeningType.door, BBox(494, 255, 506, 345), 0.90),
    # door on the left exterior wall, low confidence -> review item
    OpeningDetection(OpeningType.door, BBox(90, 300, 110, 390), 0.40),
    # window on the top wall: 120 px wide
    OpeningDetection(OpeningType.window, BBox(240, 90, 360, 110), 0.92),
    # window on the right wall
    OpeningDetection(OpeningType.window, BBox(890, 290, 910, 410), 0.88),
]

FAKE_DIMENSIONS = [
    DimensionText(
        text="8,000",
        value_mm=8000.0,
        bbox=BBox(460, 40, 540, 60),
        span=((100.0, 50.0), (900.0, 50.0)),
        confidence=0.97,
    )
]


class FakeWallSegmenter(WallSegmenter):
    def segment(self, image: np.ndarray) -> WallMask:
        return WallMask(mask=fake_wall_mask(), confidence=0.99)


class FakeOpeningDetector(OpeningDetector):
    def detect(self, image: np.ndarray) -> list[OpeningDetection]:
        return list(FAKE_OPENINGS)


class FakeDimensionReader(DimensionReader):
    def read(self, image: np.ndarray) -> list[DimensionText]:
        return list(FAKE_DIMENSIONS)


class NullDimensionReader(DimensionReader):
    """No OCR: forces the scale fallback (assumed exterior wall thickness)."""

    def read(self, image: np.ndarray) -> list[DimensionText]:
        return []
