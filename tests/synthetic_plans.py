"""Synthetic labelled floor plans for the recognition tests (pixels, y down).

Everything is drawn in code; no drawing or mask is committed.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi

from app.models.base import (
    BBox,
    DimensionReader,
    DimensionText,
    OpeningDetection,
    OpeningDetector,
    WallMask,
    WallSegmenter,
)
from app.models.registry import Models
from app.schemas.plan import OpeningType


def box(kind: str, x0: float, y0: float, x1: float, y1: float, conf: float = 1.0):
    return OpeningDetection(OpeningType(kind), BBox(x0, y0, x1, y1), conf)


def draw_wall(m, x0, y0, x1, y1, t):
    """Axis-aligned wall with centerline (x0,y0)-(x1,y1) and thickness t; ends extended by t/2."""
    h = t / 2
    if y0 == y1:
        xa, xb = sorted((x0, x1))
        m[int(y0 - h) : int(y0 + h), int(xa - h) : int(xb + h)] = True
    else:
        ya, yb = sorted((y0, y1))
        m[int(ya - h) : int(yb + h), int(x0 - h) : int(x0 + h)] = True


def cut(m, x0, y0, x1, y1):
    m[int(y0) : int(y1), int(x0) : int(x1)] = False


def rectangle(m, x0, y0, x1, y1, t):
    for (ax, ay), (bx, by) in [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
                               ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]:  # fmt: skip
        draw_wall(m, ax, ay, bx, by, t)


def l_shaped(seed: int = 0, noise: bool = True, scale: float = 1.0):
    """L-shaped flat: 6 exterior walls (t=24), 2 interior walls (t=14), 2 doors, 2 windows.

    Returns (mask, boxes, expected). The mask is cut where the openings are, like a model's.
    """
    s = scale
    H, W = int(700 * s), int(1000 * s)
    m = np.zeros((H, W), bool)
    te, ti = 24 * s, 14 * s
    ext = [((100, 100), (900, 100)), ((900, 100), (900, 400)), ((900, 400), (600, 400)),
           ((600, 400), (600, 600)), ((600, 600), (100, 600)), ((100, 600), (100, 100))]  # fmt: skip
    for (x0, y0), (x1, y1) in ext:
        draw_wall(m, x0 * s, y0 * s, x1 * s, y1 * s, te)
    draw_wall(m, 400 * s, 100 * s, 400 * s, 600 * s, ti)  # interior vertical
    draw_wall(m, 100 * s, 350 * s, 400 * s, 350 * s, ti)  # interior horizontal (T into x=400)
    boxes = []
    # front door, bottom wall y=600, x 200..290, swings up into the room
    cut(m, 200 * s, (600 - 12) * s, 290 * s, (600 + 12) * s)
    boxes.append(box("door", 200 * s, 510 * s, 290 * s, 612 * s, 0.95))
    # window, top wall y=100, x 600..720
    cut(m, 600 * s, 88 * s, 720 * s, 112 * s)
    boxes.append(box("window", 600 * s, 88 * s, 720 * s, 112 * s, 0.9))
    # wide balcony window, right wall x=900, y 150..350
    cut(m, 888 * s, 150 * s, 912 * s, 350 * s)
    boxes.append(box("window", 888 * s, 150 * s, 912 * s, 350 * s, 0.85))
    # interior door, wall x=400, y 200..280, swings left
    cut(m, 393 * s, 200 * s, 407 * s, 280 * s)
    boxes.append(box("door", 320 * s, 200 * s, 407 * s, 280 * s, 0.4))
    if noise:
        rng = np.random.default_rng(seed)
        cut(m, 88 * s, 450 * s, 112 * s, 451 * s)  # 1 px break in the left wall
        for _ in range(40):  # speckles (furniture, text) inside the rooms
            y = rng.integers(int(130 * s), int(570 * s))
            x = rng.integers(int(130 * s), int(570 * s))
            m[y : y + 3, x : x + 3] = True
        for _ in range(6):  # text-like thin strokes
            y = rng.integers(int(150 * s), int(550 * s))
            x = rng.integers(int(150 * s), int(300 * s))
            m[y : y + 2, x : x + 60] = True
    expected = {
        "walls": {  # (horizontal, center, a, b, kind)
            (True, 100, 100, 900, "exterior"),
            (True, 350, 100, 400, "interior"),
            (True, 400, 600, 900, "exterior"),
            (True, 600, 100, 600, "exterior"),
            (False, 100, 100, 600, "exterior"),
            (False, 400, 100, 600, "interior"),
            (False, 600, 400, 600, "exterior"),
            (False, 900, 100, 400, "exterior"),
        },  # fmt: skip
        "openings": [  # box index -> (wall (horizontal, center), s0, s1)
            ((True, 600), 200, 290),
            ((True, 100), 600, 720),
            ((False, 900), 150, 350),
            ((False, 400), 200, 280),
        ],  # fmt: skip
        "t_ext": 24,
        "t_int": 14,
    }
    return m, boxes, expected


def perturb(mask, seed=0, edge_p=0.3, holes=8, hole_size=6, blobs=4):
    """Model-like errors: ragged edges, small false negatives, blobs stuck to walls."""
    rng = np.random.default_rng(seed)
    m = mask.copy()
    edge = m & ~ndi.binary_erosion(m)
    m[edge & (rng.random(m.shape) < edge_p)] = False  # eaten boundary pixels
    outer = ndi.binary_dilation(mask) & ~mask
    m[outer & (rng.random(m.shape) < edge_p)] = True  # bleeding boundary pixels
    ys, xs = np.nonzero(mask)
    for _ in range(holes):  # small bites out of walls
        k = rng.integers(len(ys))
        m[ys[k] : ys[k] + hole_size, xs[k] : xs[k] + 2] = False
    for _ in range(blobs):  # blobs touching walls (furniture predicted as wall)
        k = rng.integers(len(ys))
        m[ys[k] : ys[k] + 18, xs[k] : xs[k] + 18] = True
    return m


def square_with_corner_door():
    """Rectangle where the door label ate the end of the left wall (door at the corner)."""
    m = np.zeros((400, 500), bool)
    rectangle(m, 50, 50, 450, 350, 20)
    cut(m, 60, 340, 150, 360)
    cut(m, 40, 255, 60, 340)
    return m, [box("door", 58, 255, 150, 360, 0.9)]


def square_with_doors_at_both_ends_of_the_left_wall():
    """The left wall is cut off from the rest by a door at each corner: only the door boxes
    still connect it to the building."""
    m = np.zeros((400, 500), bool)
    rectangle(m, 50, 50, 450, 350, 20)
    cut(m, 40, 40, 150, 130)  # top-left corner: door label ate both wall ends
    cut(m, 40, 270, 150, 360)  # bottom-left corner
    return m, [box("door", 40, 40, 150, 130, 0.9), box("door", 40, 270, 150, 360, 0.9)]


def square_with_diagonal_wall():
    m = np.zeros((400, 500), np.uint8)
    rectangle(m, 50, 50, 450, 350, 20)
    for k in range(-10, 10):  # 45-degree band, ~20 px thick
        idx = np.arange(60, 300)
        m[np.clip(idx + k, 0, 399), idx] = 1
    return m.astype(bool), []


def with_outside_clutter(mask):
    """The L-shaped flat on a taller sheet with a legend frame and a loose bar below it."""
    m = np.pad(mask, ((0, 260), (0, 0)))
    top = mask.shape[0]
    rectangle(m, 150, top + 60, 450, top + 190, 14)
    draw_wall(m, 600, top + 120, 900, top + 120, 14)
    return m


class _Segmenter(WallSegmenter):
    def __init__(self, mask):
        self.mask = mask

    def segment(self, image):
        return WallMask(mask=self.mask, confidence=0.9)


class _Detector(OpeningDetector):
    def __init__(self, boxes):
        self.boxes = boxes

    def detect(self, image):
        return list(self.boxes)


class _Reader(DimensionReader):
    def __init__(self, mm_per_px):
        self.mm_per_px = mm_per_px

    def read(self, image):
        if self.mm_per_px is None:
            return []
        span = ((0.0, 0.0), (1000.0, 0.0))
        return [DimensionText("dim", 1000.0 * self.mm_per_px, BBox(0, 0, 1, 1), span, 0.9)]


def models_for(mask, boxes, mm_per_px: float | None = None) -> Models:
    """Models that return this mask and these boxes. No `mm_per_px`: the scale is estimated."""
    return Models(_Segmenter(mask), _Detector(boxes), _Reader(mm_per_px))
