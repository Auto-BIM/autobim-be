"""Opening boxes -> wall + interval along the wall (R9). docs/recognition.md section 3.

A door box encloses the swing arc, so it sticks out into the room: the wall is the one the box
crosses, not the one nearest to the box centre.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from app.models.base import OpeningDetection
from app.recognition.walls import GapHits, PixelWall, box_cross, box_interval, overlap
from app.schemas.plan import OpeningType


@dataclass
class PixelOpening:
    box_index: int
    type: OpeningType
    wall_index: int
    s0: float  # along-wall interval, axis coords (not relative to the wall start)
    s1: float
    source: Literal["gap", "box", "nearest"]
    dist: float = 0.0  # px from the box centre to the wall ("nearest" only)


def attach_openings(
    walls: list[PixelWall], detections: list[OpeningDetection], gap_hits: GapHits
) -> list[PixelOpening]:
    """R9, in order of preference:

    1. `gap`: the mask was cut here and the box explains it; the best-fitting gap wins.
    2. `box`: the box crosses a wall band (+-2 px); the wall it shares the most length with.
    3. `nearest`: nothing crosses; the wall closest to the box centre (a review item).

    Finally the interval is kept clear of crossing walls' thickness.
    """
    result: list[PixelOpening] = []
    for i, det in enumerate(detections):
        cx, cy = det.bbox.center
        if gap_hits.get(i):
            hit = max(gap_hits[i], key=lambda h: h.fit)
            j = next(k for k, w in enumerate(walls) if w is hit.wall)
            result.append(PixelOpening(i, det.type, j, hit.s0, hit.s1, "gap"))
            continue
        best = None  # (shared length, -distance to the wall's centerline, wall index)
        for j, w in enumerate(walls):
            b0, b1 = box_interval(det, w.horizontal)
            c0, c1 = box_cross(det, w.horizontal)
            if overlap(c0, c1, w.center - w.thickness / 2 - 2, w.center + w.thickness / 2 + 2) <= 0:
                continue
            shared = overlap(b0, b1, w.a, w.b)
            if shared <= 0:
                continue
            key = (shared, -abs((cy if w.horizontal else cx) - w.center), j)
            if best is None or key > best:
                best = key
        if best is not None:
            j = best[2]
            w = walls[j]
            b0, b1 = box_interval(det, w.horizontal)
            result.append(PixelOpening(i, det.type, j, max(b0, w.a), min(b1, w.b), "box"))
            continue
        near = _nearest(walls, i, det)
        if near is not None:
            result.append(near)
    for op in result:
        _clear_of_crossing_walls(op, walls)
    return result


def _nearest(walls: list[PixelWall], index: int, det: OpeningDetection) -> PixelOpening | None:
    cx, cy = det.bbox.center
    best_j, best_d = None, float("inf")
    for j, w in enumerate(walls):
        s, c = (cx, cy) if w.horizontal else (cy, cx)
        d = float(np.hypot(max(w.a - s, 0, s - w.b), c - w.center))
        if d < best_d:
            best_j, best_d = j, d
    if best_j is None:
        return None
    w = walls[best_j]
    b0, b1 = box_interval(det, w.horizontal)
    s0, s1 = max(b0, w.a), min(b1, w.b)
    if s1 <= s0:  # the box does not project onto the wall: centre it on the closest point
        mid = min(max((b0 + b1) / 2, w.a), w.b)
        half = (b1 - b0) / 2
        s0, s1 = mid - half, mid + half
    return PixelOpening(index, det.type, best_j, s0, s1, "nearest", best_d)


def _clear_of_crossing_walls(op: PixelOpening, walls: list[PixelWall]) -> None:
    """Keep the cut out of the thickness of the walls that cross this one.

    An end on a face counts as inside. A box that lies wholly within a crossing wall has no
    clear span to be cut back to: it keeps the interval it was detected with.
    """
    w = walls[op.wall_index]
    for o in walls:
        if o.horizontal == w.horizontal or not (o.a - 1 <= w.center <= o.b + 1):
            continue
        face_lo, face_hi = o.center - o.thickness / 2, o.center + o.thickness / 2
        s0, s1 = op.s0, op.s1
        if face_lo <= s0 < face_hi:
            s0 = face_hi
        if face_lo < s1 <= face_hi:
            s1 = face_lo
        if s1 > s0:
            op.s0, op.s1 = s0, s1
