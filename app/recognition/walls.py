"""Wall mask -> axis-aligned wall segments (pixel space). docs/recognition.md section 3, R1-R6c.

Pixel coordinates: origin top-left, x right, y down. Every threshold is a factor of the
drawing's typical wall thickness `t_med`, so resolution and scale do not matter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple

import numpy as np
from scipy import ndimage as ndi

from app.core.config import RecognitionSettings
from app.models.base import OpeningDetection


@dataclass
class PixelWall:
    horizontal: bool
    center: float  # y for horizontal walls, x for vertical walls (continuous px)
    a: float  # start along the wall axis (continuous px)
    b: float  # end along the wall axis
    thickness: float  # px
    gaps: list[tuple[float, float]] = field(default_factory=list)  # bridged gaps, axis coords

    def endpoints(self) -> tuple[tuple[float, float], tuple[float, float]]:
        if self.horizontal:
            return (self.a, self.center), (self.b, self.center)
        return (self.center, self.a), (self.center, self.b)

    @property
    def length(self) -> float:
        return self.b - self.a


class GapHit(NamedTuple):
    """A gap (or an extension) in `wall` that the opening box explains, along [s0, s1]."""

    fit: float  # min/max of gap width and box width: 1.0 = same size
    wall: PixelWall
    s0: float
    s1: float


GapHits = dict[int, list[GapHit]]  # detection index -> candidate gaps


def box_interval(det: OpeningDetection, horizontal: bool) -> tuple[float, float]:
    """The box's extent along a wall of this orientation."""
    b = det.bbox
    return (b.x0, b.x1) if horizontal else (b.y0, b.y1)


def box_cross(det: OpeningDetection, horizontal: bool) -> tuple[float, float]:
    """The box's extent across a wall of this orientation."""
    b = det.bbox
    return (b.y0, b.y1) if horizontal else (b.x0, b.x1)


def overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


# ------------------------------------------------------------------------------ R1, R2
def clean_mask(mask: np.ndarray, t_med: float, p: RecognitionSettings) -> np.ndarray:
    """R1: close 1 px breaks, then drop components too small to be a wall."""
    m = ndi.binary_closing(mask, structure=np.ones((3, 3), bool))
    lab, n = ndi.label(m)
    if n == 0:
        return m
    areas = ndi.sum(m, lab, index=np.arange(1, n + 1))
    keep = np.zeros(n + 1, bool)
    keep[1:] = areas >= p.min_component_area_factor * t_med * t_med
    return keep[lab]


def _run_lengths(grid: np.ndarray) -> np.ndarray:
    """Lengths of all True runs along axis 1 of a 2D bool array."""
    padded = np.pad(grid, ((0, 0), (1, 1)))
    d = np.diff(padded.astype(np.int8), axis=1)
    starts = np.flatnonzero(d.ravel() == 1)
    ends = np.flatnonzero(d.ravel() == -1)
    return ends - starts


def estimate_thickness(mask: np.ndarray) -> float:
    """R2: typical wall thickness (px) = median of the shorter 90% of runs on both axes.

    Wall cross-sections are by far the most frequent runs (one per pixel of wall length),
    so the median of the runs below the 90th percentile is the typical thickness.
    """
    runs = np.concatenate([_run_lengths(mask), _run_lengths(mask.T)])
    if runs.size == 0:
        return 0.0
    cut = np.percentile(runs, 90)
    short = runs[runs <= cut]
    return float(np.median(short)) if short.size else float(np.median(runs))


# ------------------------------------------------------------------------------ R3
def _runs(line: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    """Half-open [start, end) runs of True with length >= min_len."""
    padded = np.concatenate(([False], line, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(s), int(e)) for s, e in zip(edges[::2], edges[1::2]) if e - s >= min_len]


def _bands(mask: np.ndarray, min_len: int, horizontal: bool) -> list[PixelWall]:
    """Group the long runs of consecutive rows into bands (one wall each)."""
    grid = mask if horizontal else mask.T
    done: list[list] = []
    active: list[list] = []  # [row_start, row_end_exclusive, a, b, per-row runs]
    for row in range(grid.shape[0]):
        still: list[list] = []
        for s, e in _runs(grid[row], min_len):
            band = next((b for b in active if b[1] == row and s < b[3] and e > b[2]), None)
            if band is None:
                band = [row, row, s, e, []]
            else:
                active = [b for b in active if b is not band]
            band[1] = row + 1
            band[2], band[3] = min(band[2], s), max(band[3], e)
            band[4].append((s, e))
            still.append(band)
        done.extend(active)
        active = still
    done.extend(active)
    walls = []
    for r0, r1, _, _, runs in done:
        # median of the run ends: a few longer rows (text touching the wall) do not drag it
        a = float(np.median([s for s, _ in runs]))
        b = float(np.median([e for _, e in runs]))
        walls.append(PixelWall(horizontal, (r0 + r1) / 2, a, b, float(r1 - r0)))
    return walls


def extract_axis_walls(mask: np.ndarray, t_med: float, p: RecognitionSettings) -> list[PixelWall]:
    """R3: horizontal and vertical wall bands.

    Only runs of at least L px count, so the cross-sections of perpendicular walls (~t px) and
    text are ignored. Bands thinner than `thin_factor * t_med` (dimension lines) are dropped.
    """
    min_len = int(max(p.run_len_factor * t_med, 15))
    walls = _bands(mask, min_len, True) + _bands(mask, min_len, False)
    return [w for w in walls if w.thickness >= p.thin_factor * t_med and w.length > w.thickness]


# ------------------------------------------------------------------------------ R5
def merge_collinear(
    walls: list[PixelWall],
    detections: list[OpeningDetection],
    t_med: float,
    p: RecognitionSettings,
) -> tuple[list[PixelWall], GapHits]:
    """R5: join pieces on one line that an opening (or a 1-2 px noise break) split apart.

    Returns the merged walls and, per detection, the gaps it explains.
    """
    out: list[PixelWall] = []
    gap_hits: GapHits = {}
    for horizontal in (True, False):
        group = sorted([w for w in walls if w.horizontal == horizontal], key=lambda w: w.center)
        clusters: list[list[PixelWall]] = []  # pieces whose centerlines coincide
        for w in group:
            for c in clusters:
                ref = c[0]
                tol = p.collinear_tol_factor * max(w.thickness, ref.thickness)
                if abs(w.center - ref.center) <= tol:
                    c.append(w)
                    break
            else:
                clusters.append([w])
        for c in clusters:
            c.sort(key=lambda w: w.a)
            cur = PixelWall(horizontal, c[0].center, c[0].a, c[0].b, c[0].thickness)
            pieces = [c[0]]
            for w in c[1:]:
                gap0, gap1 = cur.b, w.a
                joined = False
                if gap1 <= gap0:  # overlapping pieces
                    joined = True
                else:
                    g = gap1 - gap0
                    lo = min(cur.center - cur.thickness / 2, w.center - w.thickness / 2)
                    hi = max(cur.center + cur.thickness / 2, w.center + w.thickness / 2)
                    covering = []
                    for i, det in enumerate(detections):
                        b0, b1 = box_interval(det, horizontal)
                        c0, c1 = box_cross(det, horizontal)
                        if overlap(c0, c1, lo - 2, hi + 2) <= 0:
                            continue  # the box does not touch this wall line
                        if overlap(b0, b1, gap0, gap1) >= p.gap_cover_ratio * g:
                            covering.append(i)
                    if covering:
                        joined = True
                        for i in covering:
                            b0, b1 = box_interval(detections[i], horizontal)
                            s0, s1 = max(b0, gap0), min(b1, gap1)
                            if len(covering) == 1:
                                s0, s1 = gap0, gap1  # the whole gap belongs to the opening
                            # a box may explain gaps in two walls (door next to a corner):
                            # keep every candidate, attach_openings picks the best fit
                            fit = min(s1 - s0, b1 - b0) / max(s1 - s0, b1 - b0)
                            gap_hits.setdefault(i, []).append(GapHit(fit, cur, s0, s1))
                            cur.gaps.append((s0, s1))
                    elif g <= p.noise_gap_factor * t_med:
                        joined = True  # a mask break, not an opening
                if joined:
                    pieces.append(w)
                    total = sum(x.length for x in pieces)
                    cur.center = sum(x.center * x.length for x in pieces) / total
                    cur.thickness = sum(x.thickness * x.length for x in pieces) / total
                    cur.b = max(cur.b, w.b)
                else:
                    out.append(cur)
                    cur = PixelWall(horizontal, w.center, w.a, w.b, w.thickness)
                    pieces = [w]
            out.append(cur)
    return out, gap_hits


def remove_duplicate_walls(walls: list[PixelWall], p: RecognitionSettings) -> list[PixelWall]:
    """The same wall found twice: parallel bands that share at least `duplicate_overlap_ratio`
    of the thinner one's thickness and of the shorter one's length.

    A hole inside a wall splits the rows around it into two runs; the second run starts a
    band of its own that lies inside the first. Two real walls cannot occupy the same space,
    so the larger band absorbs the other. Bands that only touch, or share a ragged pixel or
    two, are left alone. Runs before R5, which would average the two bands into one wall.
    """
    walls = list(walls)
    ratio = p.duplicate_overlap_ratio
    merged = True
    while merged:
        merged = False
        for i, w in enumerate(walls):
            for o in walls[i + 1 :]:
                if o.horizontal != w.horizontal:
                    continue
                across = overlap(
                    w.center - w.thickness / 2,
                    w.center + w.thickness / 2,
                    o.center - o.thickness / 2,
                    o.center + o.thickness / 2,
                )
                along = overlap(w.a, w.b, o.a, o.b)
                if across < ratio * min(w.thickness, o.thickness) or across <= 0:
                    continue
                if along < ratio * min(w.length, o.length) or along <= 0:
                    continue
                keep, drop = (w, o) if w.thickness * w.length >= o.thickness * o.length else (o, w)
                keep.a, keep.b = min(keep.a, drop.a), max(keep.b, drop.b)
                walls = [x for x in walls if x is not drop]
                merged = True
                break
            if merged:
                break
    return walls


# ------------------------------------------------------------------------------ R6
def _snap_end(
    w: PixelWall, end: str, walls: list[PixelWall], t_med: float, p: RecognitionSettings
) -> bool:
    """Move one end onto the centerline of a crossing wall it ends in (or just short of)."""
    e = getattr(w, end)
    best = None
    for o in walls:
        if o.horizontal == w.horizontal:
            continue
        if not (o.a - t_med <= w.center <= o.b + t_med):  # o must span w's centerline
            continue
        d = abs(e - o.center)
        if d <= o.thickness / 2 + p.snap_factor * t_med and (best is None or d < best[0]):
            best = (d, o)
    if best is None:
        return False
    o = best[1]
    setattr(w, end, o.center)
    # o may stop just short of w's line (L corner): let it reach w's centerline too
    reach = o.thickness / 2 + p.snap_factor * t_med
    if o.a > w.center and o.a - w.center <= reach:
        o.a = w.center
    elif o.b < w.center and w.center - o.b <= reach:
        o.b = w.center
    return True


def snap_junctions(
    walls: list[PixelWall], t_med: float, p: RecognitionSettings
) -> set[tuple[int, str]]:
    """R6: snap ends onto the centerline of the wall they meet (L, T and + junctions).

    Returns the ends that met nothing. Snapping sets the end to the other wall's centerline
    exactly, so a junction is aligned to well under a millimetre in the Plan.
    """
    open_ends = set()
    for i, w in enumerate(walls):
        for end in ("a", "b"):
            if not _snap_end(w, end, walls, t_med, p):
                open_ends.add((i, end))
    # a wall that stopped short may have been extended since: look at the open ends again
    return {(i, e) for i, e in open_ends if not _snap_end(walls[i], e, walls, t_med, p)}


def extend_open_ends(
    walls: list[PixelWall],
    detections: list[OpeningDetection],
    open_ends: set[tuple[int, str]],
    gap_hits: GapHits,
    t_med: float,
) -> None:
    """R6b: an open end that runs into an opening box continues through it.

    That is a door at a corner whose label ate the neighbouring wall's end. The extension is
    recorded as a gap the box explains.
    """
    for i, end in sorted(open_ends):
        w = walls[i]
        lo, hi = w.center - w.thickness / 2, w.center + w.thickness / 2
        for k, det in enumerate(detections):
            b0, b1 = box_interval(det, w.horizontal)
            c0, c1 = box_cross(det, w.horizontal)
            if overlap(c0, c1, lo - 2, hi + 2) <= 0:
                continue
            if end == "b" and b1 > w.b and b0 <= w.b + t_med:
                s0, s1 = w.b, b1
                w.b = b1
            elif end == "a" and b0 < w.a and b1 >= w.a - t_med:
                s0, s1 = b0, w.a
                w.a = b0
            else:
                continue
            fit = min(s1 - s0, b1 - b0) / max(s1 - s0, b1 - b0)
            gap_hits.setdefault(k, []).append(GapHit(fit, w, s0, s1))
            w.gaps.append((s0, s1))
            break


def finish_walls(walls: list[PixelWall], t_med: float, p: RecognitionSettings) -> list[PixelWall]:
    """R6c: drop walls shorter than `min_len_factor * t_med`."""
    return [w for w in walls if w.length >= max(p.min_len_factor * t_med, 1.0)]
