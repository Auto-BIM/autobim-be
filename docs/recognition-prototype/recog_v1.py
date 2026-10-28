"""Recognition v1 prototype: wall mask + opening boxes (px) -> axis-aligned walls + openings (px).

Validates docs/recognition.md before the backend implements it in app/recognition/.
Only numpy + scipy. Pixel coordinates: origin top-left, x right, y down.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage as ndi


# ----------------------------------------------------------------------------- types
@dataclass
class PixelWall:
    horizontal: bool
    center: float  # y for horizontal walls, x for vertical walls
    a: float  # start along the axis (a < b)
    b: float
    thickness: float
    gaps: list = field(default_factory=list)  # [(s0, s1)] bridged gaps, axis coords

    @property
    def length(self) -> float:
        return self.b - self.a

    def endpoints(self):
        if self.horizontal:
            return (self.a, self.center), (self.b, self.center)
        return (self.center, self.a), (self.center, self.b)


@dataclass
class Box:  # opening detection in px
    kind: str  # "door" | "window"
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float = 1.0


@dataclass
class PixelOpening:
    box_index: int
    kind: str
    wall_index: int | None
    s0: float  # along-wall interval (axis coords, not yet relative to wall start)
    s1: float
    source: str  # "gap" | "box" | "nearest"
    dist: float = 0.0


@dataclass
class Params:
    min_component_area_factor: float = 4.0  # R1: drop blobs smaller than f * t_med^2
    run_len_factor: float = 2.5  # R3: min run length L = max(f * t_med, 15)
    thin_factor: float = 0.4  # R3: drop bands thinner than f * t_med
    collinear_tol_factor: float = 0.5  # R5: centers within f * max(t)
    noise_gap_factor: float = 1.0  # R5: join gaps <= f * t_med even without an opening
    gap_cover_ratio: float = 0.5  # R5: an opening must cover >= this share of the gap
    snap_factor: float = 1.0  # R6: snap ends within t_other/2 + f * t_med
    min_len_factor: float = 1.0  # R6: drop walls shorter than f * t_med (after snapping)


# ----------------------------------------------------------------------------- R0..R2
def clean_mask(mask: np.ndarray, t_med: float, p: Params) -> np.ndarray:
    """R1: drop small components, close 1-px breaks."""
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
    """R2: typical wall thickness (px) = median of short runs across both axes.

    Cross-sections of walls are by far the most frequent runs (one per pixel of wall
    length), so the median of all runs shorter than a cut-off is the typical thickness.
    """
    runs = np.concatenate([_run_lengths(mask), _run_lengths(mask.T)])
    if runs.size == 0:
        return 0.0
    cut = np.percentile(runs, 90)
    short = runs[runs <= cut]
    return float(np.median(short)) if short.size else float(np.median(runs))


# ----------------------------------------------------------------------------- R3
def _runs(line: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    padded = np.concatenate(([False], line, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(s), int(e)) for s, e in zip(edges[::2], edges[1::2]) if e - s >= min_len]


def _bands(mask: np.ndarray, min_len: int, horizontal: bool) -> list[PixelWall]:
    """Group per-row runs (>= min_len) of consecutive rows into bands (one wall each)."""
    grid = mask if horizontal else mask.T
    done, active = [], []  # band: [row0, row1_excl, a, b, per-row runs]
    for row in range(grid.shape[0]):
        still = []
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
    for r0, r1, a, b, runs in done:
        # extent = median run ends, robust to a few longer rows (e.g. text touching the wall)
        aa = float(np.median([s for s, _ in runs]))
        bb = float(np.median([e for _, e in runs]))
        walls.append(PixelWall(horizontal, (r0 + r1) / 2, aa, bb, float(r1 - r0)))
    return walls


def extract_axis_walls(mask: np.ndarray, t_med: float, p: Params) -> list[PixelWall]:
    """R3: horizontal/vertical wall bands. Runs >= L px only, so cross-sections of
    perpendicular walls (~t px) and text are ignored."""
    min_len = int(max(p.run_len_factor * t_med, 15))
    walls = _bands(mask, min_len, True) + _bands(mask, min_len, False)
    return [w for w in walls if w.thickness >= p.thin_factor * t_med and w.length > w.thickness]


# ----------------------------------------------------------------------------- R5
def _box_interval(box: Box, horizontal: bool) -> tuple[float, float]:
    return (box.x0, box.x1) if horizontal else (box.y0, box.y1)


def _box_cross(box: Box, horizontal: bool) -> tuple[float, float]:
    return (box.y0, box.y1) if horizontal else (box.x0, box.x1)


def _overlap(a0, a1, b0, b1) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def merge_collinear(walls: list[PixelWall], boxes: list[Box], t_med: float, p: Params):
    """R5: join collinear pieces split by openings (or 1-2 px noise). Returns new walls and
    {box_index: [(fit, wall, s0, s1), ...]} for gaps explained by an opening box."""
    out: list[PixelWall] = []
    gap_hits: dict[int, list[tuple[float, PixelWall, float, float]]] = {}
    for horizontal in (True, False):
        group = sorted([w for w in walls if w.horizontal == horizontal], key=lambda w: w.center)
        # cluster by center line
        clusters: list[list[PixelWall]] = []
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
                if gap1 <= gap0:  # overlapping pieces: merge
                    joined = True
                else:
                    g = gap1 - gap0
                    lo = min(cur.center - cur.thickness / 2, w.center - w.thickness / 2)
                    hi = max(cur.center + cur.thickness / 2, w.center + w.thickness / 2)
                    covering = []
                    for i, box in enumerate(boxes):
                        b0, b1 = _box_interval(box, horizontal)
                        c0, c1 = _box_cross(box, horizontal)
                        if _overlap(c0, c1, lo - 2, hi + 2) <= 0:
                            continue  # box does not touch this wall line
                        if _overlap(b0, b1, gap0, gap1) >= p.gap_cover_ratio * g:
                            covering.append(i)
                    if covering:
                        joined = True
                        for i in covering:
                            b0, b1 = _box_interval(boxes[i], horizontal)
                            s0, s1 = max(b0, gap0), min(b1, gap1)
                            if len(covering) == 1:
                                s0, s1 = gap0, gap1  # whole gap belongs to the opening
                            # a box may explain gaps in two walls (door next to a corner):
                            # keep every candidate, attach_openings picks the best fit
                            fit = min(s1 - s0, b1 - b0) / max(s1 - s0, b1 - b0)
                            gap_hits.setdefault(i, []).append((fit, cur, s0, s1))
                            cur.gaps.append((s0, s1))
                    elif g <= p.noise_gap_factor * t_med:
                        joined = True  # mask break, not an opening
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


# ----------------------------------------------------------------------------- R6
def _snap_end(w: PixelWall, end: str, walls: list[PixelWall], t_med: float, p: Params) -> bool:
    """Move one end onto the centerline of a crossing wall it ends in (or just short of)."""
    e = getattr(w, end)
    best = None
    for o in walls:
        if o.horizontal == w.horizontal:
            continue
        if not (o.a - t_med <= w.center <= o.b + t_med):  # o must span w's center line
            continue
        d = abs(e - o.center)
        if d <= o.thickness / 2 + p.snap_factor * t_med and (best is None or d < best[0]):
            best = (d, o)
    if best is None:
        return False
    o = best[1]
    setattr(w, end, o.center)
    # o may stop just short of w's line (L corner): let it reach w's centerline too
    if o.a > w.center and o.a - w.center <= o.thickness / 2 + p.snap_factor * t_med:
        o.a = w.center
    elif o.b < w.center and w.center - o.b <= o.thickness / 2 + p.snap_factor * t_med:
        o.b = w.center
    return True


def snap_junctions(walls: list[PixelWall], t_med: float, p: Params) -> set[tuple[int, str]]:
    """R6: snap ends onto crossing walls (L, T, + junctions). Returns ends left open."""
    open_ends = set()
    for i, w in enumerate(walls):
        for end in ("a", "b"):
            if not _snap_end(w, end, walls, t_med, p):
                open_ends.add((i, end))
    return {(i, e) for i, e in open_ends if not _snap_end(walls[i], e, walls, t_med, p)}


def extend_open_ends(walls, boxes, open_ends, gap_hits, t_med: float) -> None:
    """R6b: an open end that runs into an opening box continues through it (door at a
    corner: the door label ate the wall end). The extension is a gap explained by the box."""
    for i, end in sorted(open_ends):
        w = walls[i]
        lo, hi = w.center - w.thickness / 2, w.center + w.thickness / 2
        for k, box in enumerate(boxes):
            b0, b1 = _box_interval(box, w.horizontal)
            c0, c1 = _box_cross(box, w.horizontal)
            if _overlap(c0, c1, lo - 2, hi + 2) <= 0:
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
            gap_hits.setdefault(k, []).append((fit, w, s0, s1))
            w.gaps.append((s0, s1))
            break


def finish_walls(walls: list[PixelWall], t_med: float, p: Params) -> list[PixelWall]:
    return [w for w in walls if w.length >= max(p.min_len_factor * t_med, 1.0)]


# ----------------------------------------------------------------------------- R7
def rasterize(walls: list[PixelWall], shape) -> np.ndarray:
    m = np.zeros(shape, bool)
    h, w_ = shape
    for w in walls:
        half = w.thickness / 2
        lo, hi = int(np.floor(w.center - half)), int(np.ceil(w.center + half))
        a, b = int(np.floor(w.a - half)), int(np.ceil(w.b + half))  # close corners
        if w.horizontal:
            m[max(lo, 0):min(hi, h), max(a, 0):min(b, w_)] = True
        else:
            m[max(a, 0):min(b, h), max(lo, 0):min(hi, w_)] = True
    return m


def exterior_region(walls: list[PixelWall], shape) -> np.ndarray:
    """R7: free space connected to the image border (walls bridged over openings)."""
    free = ~rasterize(walls, shape)
    lab, _ = ndi.label(free)
    border = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    border = border[border > 0]
    return np.isin(lab, border)


def classify(walls: list[PixelWall], shape, t_med: float) -> list[str]:
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
        kinds.append("exterior" if hit else "interior")
    return kinds


# ----------------------------------------------------------------------------- R9
def attach_openings(walls: list[PixelWall], boxes: list[Box], gap_hits) -> list[PixelOpening]:
    result = []
    for i, box in enumerate(boxes):
        if gap_hits.get(i):
            _, wall, s0, s1 = max(gap_hits[i], key=lambda h: h[0])
            j = next(k for k, w in enumerate(walls) if w is wall)
            result.append(PixelOpening(i, box.kind, j, s0, s1, "gap"))
            continue
        best = None  # (overlap, -distance, index)
        for j, w in enumerate(walls):
            b0, b1 = _box_interval(box, w.horizontal)
            c0, c1 = _box_cross(box, w.horizontal)
            lo, hi = w.center - w.thickness / 2 - 2, w.center + w.thickness / 2 + 2
            if _overlap(c0, c1, lo, hi) <= 0:
                continue
            ov = _overlap(b0, b1, w.a, w.b)
            if ov <= 0:
                continue
            cx, cy = (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2
            dist = abs((cy if w.horizontal else cx) - w.center)
            key = (ov, -dist, j)
            if best is None or key > best:
                best = key
        if best is not None:
            j = best[2]
            w = walls[j]
            b0, b1 = _box_interval(box, w.horizontal)
            result.append(PixelOpening(i, box.kind, j, max(b0, w.a), min(b1, w.b), "box"))
            continue
        # nothing intersects: nearest wall, flagged for review
        cx, cy = (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2
        best_j, best_d = None, float("inf")
        for j, w in enumerate(walls):
            s, c = (cx, cy) if w.horizontal else (cy, cx)
            ds = max(w.a - s, 0, s - w.b)
            d = float(np.hypot(ds, c - w.center))
            if d < best_d:
                best_j, best_d = j, d
        if best_j is None:
            continue
        w = walls[best_j]
        b0, b1 = _box_interval(box, w.horizontal)
        s0, s1 = max(b0, w.a), min(b1, w.b)
        if s1 <= s0:  # projection misses the wall: centre it on the closest point
            mid = min(max((b0 + b1) / 2, w.a), w.b)
            half = (b1 - b0) / 2
            s0, s1 = mid - half, mid + half
        result.append(PixelOpening(i, box.kind, best_j, s0, s1, "nearest", best_d))
    for op in result:  # keep the cut inside the clear span between crossing walls
        w = walls[op.wall_index]
        for o in walls:
            if o.horizontal == w.horizontal or not (o.a - 1 <= w.center <= o.b + 1):
                continue
            face_lo, face_hi = o.center - o.thickness / 2, o.center + o.thickness / 2
            if face_lo < op.s0 < face_hi:
                op.s0 = face_hi
            if face_lo < op.s1 < face_hi:
                op.s1 = face_lo
    return result


# ----------------------------------------------------------------------------- driver
def recognize(mask: np.ndarray, boxes: list[Box], p: Params | None = None):
    p = p or Params()
    t0 = estimate_thickness(mask)
    m = clean_mask(mask, t0, p)
    t_med = estimate_thickness(m)
    walls = extract_axis_walls(m, t_med, p)
    walls, gap_hits = merge_collinear(walls, boxes, t_med, p)
    open_ends = snap_junctions(walls, t_med, p)
    extend_open_ends(walls, boxes, open_ends, gap_hits, t_med)
    snap_junctions(walls, t_med, p)
    walls = finish_walls(walls, t_med, p)
    walls.sort(key=lambda w: (not w.horizontal, w.center, w.a))
    # gap_hits keep object identity; drop hits whose wall was filtered out
    gap_hits = {i: [h for h in v if any(h[1] is w for w in walls)] for i, v in gap_hits.items()}
    kinds = classify(walls, mask.shape, t_med)
    openings = attach_openings(walls, boxes, gap_hits)
    covered = rasterize(walls, mask.shape)
    unexplained = float((m & ~covered).sum()) / max(int(m.sum()), 1)
    return {"t_med": t_med, "walls": walls, "kinds": kinds, "openings": openings,
            "unexplained_wall_ratio": unexplained}
