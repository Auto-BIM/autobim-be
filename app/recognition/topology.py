"""Where the walls are in the picture: building vs. stray detections, exterior vs. interior (R7).

Walls are drawn back at their thickness with the openings bridged (R5 joined the pieces), so
the exterior ring is closed even where doors and windows cut the mask.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi

from app.models.base import OpeningDetection
from app.recognition.walls import PixelWall
from app.schemas.plan import WallKind

_EIGHT = np.ones((3, 3), bool)


def _span(lo: float, hi: float) -> slice:
    return slice(max(int(np.floor(lo)), 0), max(int(np.ceil(hi)), 0))


def _rect(w: PixelWall, close_ends: bool) -> tuple[slice, slice]:
    """Pixels a wall covers: its thickness across, its length along. numpy clips to the image.

    Snapped walls end on the other wall's centerline, so `close_ends` adds half a thickness at
    each end to fill the corner. A band straight from the mask already has its corners.
    """
    half = w.thickness / 2
    reach = half if close_ends else 0.0
    across, along = _span(w.center - half, w.center + half), _span(w.a - reach, w.b + reach)
    return (across, along) if w.horizontal else (along, across)


def rasterize(
    walls: list[PixelWall], shape: tuple[int, int], close_ends: bool = True
) -> np.ndarray:
    m = np.zeros(shape, bool)
    for w in walls:
        m[_rect(w, close_ends)] = True
    return m


def _box_rect(det: OpeningDetection) -> tuple[slice, slice]:
    b = det.bbox
    return _span(b.y0, b.y1), _span(b.x0, b.x1)


def keep_building(
    walls: list[PixelWall], detections: list[OpeningDetection], shape: tuple[int, int]
) -> tuple[list[PixelWall], list[PixelWall]]:
    """Keep the largest connected body of walls and whatever lies inside its outline.

    Anything else was found outside the building (a legend, a neighbour sketch, a page
    frame). Walls are connected when their drawn rectangles touch; the opening boxes count
    too, because a door at a corner leaves the wall ends it ate apart. A free-standing
    partition inside the outline is kept. Returns (kept, outside).

    This runs before junctions are snapped: a stray wall next to a corner would otherwise
    pull the building's wall ends onto itself and join the building.
    """
    if not walls:
        return [], []
    drawn = rasterize(walls, shape, close_ends=False)
    linked = drawn.copy()
    for det in detections:
        linked[_box_rect(det)] = True
    lab, n = ndi.label(linked, structure=_EIGHT)
    areas = ndi.sum(drawn, lab, index=np.arange(1, n + 1))  # wall pixels, not box pixels
    main = int(np.argmax(areas)) + 1
    outline = ndi.binary_fill_holes(lab == main)
    kept, outside = [], []
    for w in walls:
        rect = _rect(w, close_ends=False)
        labels = lab[rect]
        if labels.size == 0 or labels.max() == main or outline[rect].all():
            kept.append(w)
        else:
            outside.append(w)
    return kept, outside


def exterior_region(walls: list[PixelWall], shape: tuple[int, int]) -> np.ndarray:
    """R7: free space connected to the image border."""
    free = ~rasterize(walls, shape)
    lab, _ = ndi.label(free)
    border = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    border = border[border > 0]
    return np.isin(lab, border)


def classify(walls: list[PixelWall], shape: tuple[int, int], t_med: float) -> list[WallKind]:
    """R7: a wall is exterior when its outside is reached from the image border.

    The two sides of the wall are sampled at 25, 50 and 75% of its length; one hit is enough.
    """
    ext = exterior_region(walls, shape)
    h, w_ = shape
    kinds = []
    for w in walls:
        off = w.thickness / 2 + max(2.0, 0.25 * t_med)
        hit = False
        for f in (0.25, 0.5, 0.75):
            s = w.a + f * w.length
            for side in (-1, 1):
                c = w.center + side * off
                x, y = (s, c) if w.horizontal else (c, s)
                xi, yi = int(round(x)), int(round(y))
                if not (0 <= xi < w_ and 0 <= yi < h) or ext[yi, xi]:
                    hit = True
        kinds.append(WallKind.exterior if hit else WallKind.interior)
    return kinds
