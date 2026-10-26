"""Wall mask -> axis-aligned wall segments (pixel space).

Minimal implementation for the end-to-end path: finds horizontal/vertical bands of
wall pixels and snaps their ends onto crossing walls' centerlines. Diagonal walls,
gaps at openings and noisy masks are out of scope here (issue #5).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class PixelWall:
    horizontal: bool
    center: float  # y for horizontal walls, x for vertical walls (continuous px)
    a: float  # start along the wall axis (continuous px)
    b: float  # end along the wall axis
    thickness: float  # px

    def endpoints(self) -> tuple[tuple[float, float], tuple[float, float]]:
        if self.horizontal:
            return (self.a, self.center), (self.b, self.center)
        return (self.center, self.a), (self.center, self.b)

    @property
    def length(self) -> float:
        return self.b - self.a


def _runs(line: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    """Half-open [start, end) runs of True with length >= min_len."""
    padded = np.concatenate(([False], line, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(s), int(e)) for s, e in zip(edges[::2], edges[1::2]) if e - s >= min_len]


def _bands(mask: np.ndarray, min_len: int, horizontal: bool) -> list[PixelWall]:
    grid = mask if horizontal else mask.T
    done: list[list[int]] = []
    active: list[list[int]] = []  # [row_start, row_end_exclusive, a, b]
    for row in range(grid.shape[0]):
        still: list[list[int]] = []
        for s, e in _runs(grid[row], min_len):
            band = next((b for b in active if b[1] == row and s < b[3] and e > b[2]), None)
            if band is None:
                band = [row, row, s, e]
            active = [b for b in active if b is not band]
            band[1] = row + 1
            band[2], band[3] = min(band[2], s), max(band[3], e)
            still.append(band)
        done.extend(active)
        active = still
    done.extend(active)
    return [
        PixelWall(horizontal, (r0 + r1) / 2, float(a), float(b), float(r1 - r0))
        for r0, r1, a, b in done
    ]


def _snap(walls: list[PixelWall], tol: float) -> None:
    """Move wall ends that overlap a crossing wall onto that wall's centerline."""
    for w in walls:
        for other in walls:
            if other.horizontal == w.horizontal:
                continue
            # other must span w's centerline
            if not (other.a - tol <= w.center <= other.b + tol):
                continue
            half = other.thickness / 2 + tol
            if abs(w.a - (other.center - other.thickness / 2)) <= half:
                w.a = other.center
            if abs(w.b - (other.center + other.thickness / 2)) <= half:
                w.b = other.center


def extract_walls(mask: np.ndarray, min_len: int = 30, snap_tol: float = 2.0) -> list[PixelWall]:
    walls = _bands(mask, min_len, horizontal=True) + _bands(mask, min_len, horizontal=False)
    walls = [w for w in walls if w.length > w.thickness]
    _snap(walls, snap_tol)
    walls.sort(key=lambda w: (not w.horizontal, w.center, w.a))
    return walls
