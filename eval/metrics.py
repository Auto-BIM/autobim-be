"""Plan-level metrics (docs/project/EVALUATION_PLAN.md §3). Pure functions, units are px.

A Plan is turned back into pixels with its own `scale.mm_per_px`, so every variant is
compared in the same ground-truth pixel space.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from app.models.base import OpeningDetection
from app.recognition.topology import rasterize
from app.recognition.walls import PixelWall
from app.schemas.plan import Plan, ReviewReason


@dataclass
class PxOpening:
    id: str
    type: str
    cx: float
    cy: float
    width: float  # px, along the wall
    horizontal: bool
    defaulted: bool  # width was replaced by a default, not measured


def _scale_height(plan: Plan) -> tuple[float, int]:
    if plan.scale.mm_per_px is None or plan.source.height_px is None:
        raise ValueError("plan needs scale.mm_per_px and source.height_px to be drawn back")
    return plan.scale.mm_per_px, plan.source.height_px


def _wall_px(plan: Plan):
    """Yield (wall, start, end) in px; image y points down, Plan y up."""
    s, h = _scale_height(plan)
    for w in plan.walls:
        yield (
            w,
            (w.start.x / s, h - w.start.y / s),
            (w.end.x / s, h - w.end.y / s),
        )


def _pixel_wall(w, a, b, s: float) -> PixelWall:
    # ponytail: axis-aligned only (recognition only emits those); a slanted wall is drawn
    # along its dominant axis. Upgrade to polygon fill if slanted walls get recognised.
    horizontal = abs(b[0] - a[0]) >= abs(b[1] - a[1])
    i = 0 if horizontal else 1
    j = 1 - i
    return PixelWall(
        horizontal, (a[j] + b[j]) / 2, min(a[i], b[i]), max(a[i], b[i]), w.thickness / s
    )


def plan_openings_px(plan: Plan) -> list[PxOpening]:
    s, _ = _scale_height(plan)
    walls = {w.id: (w, a, b) for w, a, b in _wall_px(plan)}
    defaulted = {
        r.element_id for r in plan.review_items if r.reason == ReviewReason.default_value_applied
    }
    out = []
    for o in plan.openings:
        w, a, b = walls[o.wall_id]
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        t = o.position / s / length
        out.append(
            PxOpening(
                o.id, o.type.value, a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t,
                o.width / s, abs(b[0] - a[0]) >= abs(b[1] - a[1]), o.id in defaulted,
            )
        )
    return out


def render_plan_walls(plan: Plan, shape: tuple[int, int]) -> np.ndarray:
    """Draw walls at their thickness, corners closed like the recogniser draws them, openings cut out."""
    s, _ = _scale_height(plan)
    pws = [_pixel_wall(w, a, b, s) for w, a, b in _wall_px(plan)]
    mask = rasterize(pws, shape, close_ends=True)
    by_id = {w.id: pw for (w, _, _), pw in zip(_wall_px(plan), pws)}
    for o, p in zip(plan.openings, plan_openings_px(plan)):
        pw = by_id[o.wall_id]
        c = p.cx if pw.horizontal else p.cy
        cut = PixelWall(pw.horizontal, pw.center, c - p.width / 2, c + p.width / 2, pw.thickness)
        mask &= ~rasterize([cut], shape, close_ends=False)
    return mask


def iou(pred: np.ndarray, gt: np.ndarray, ignore: np.ndarray | None = None) -> float:
    if ignore is not None:
        pred, gt = pred & ~ignore, gt & ~ignore
    union = np.logical_or(pred, gt).sum()
    return float(np.logical_and(pred, gt).sum() / union) if union else 1.0


def _run_lengths(m: np.ndarray) -> np.ndarray:
    """Length of the horizontal run each True pixel belongs to (0 elsewhere)."""
    p = np.pad(m, ((0, 0), (1, 1))).ravel()
    edges = np.flatnonzero(p[1:] != p[:-1])
    lengths = edges[1::2] - edges[::2]
    out = np.zeros(p.size, np.int32)
    out[np.flatnonzero(p)] = np.repeat(lengths, lengths)
    return out.reshape(m.shape[0], m.shape[1] + 2)[:, 1:-1]


def skeleton_length(mask: np.ndarray) -> float:
    """Centreline length (px) = sum over wall pixels of 1 / (thickness across the wall).

    Independent of wall thickness, unlike area / t_med. Pixels where two walls meet (both runs
    long) are weighted as a band pixel, so an L corner counts to the corner centre like the
    Plan centreline does. A thickness only counts if enough pixels share it to form a band
    four times longer than thick (a junction square has only ~t^2 of them), so walls of
    different thickness do not get mistaken for junctions. ponytail: T/+ junctions stay
    ~0.5t/1t short and slanted walls are undercounted
    (about 70% of the true length at 45 degrees); swap in real thinning if that matters.
    """
    across = np.minimum(_run_lengths(mask), _run_lengths(mask.T).T)[mask]
    if not across.size:
        return 0.0
    vals, counts = np.unique(across, return_counts=True)
    bands = vals[counts >= 4 * vals.astype(float) ** 2]
    cap = 1.5 * bands.max() if bands.size else float(np.median(across))
    t = float(np.median(across[across <= cap]))
    return float((1.0 / np.where(across > cap, t, across)).sum())


def plan_length_px(plan: Plan) -> float:
    """Wall centreline length minus opening widths (px)."""
    s, _ = _scale_height(plan)
    return sum(w.length for w in plan.walls) / s - sum(p.width for p in plan_openings_px(plan))


def length_error(plan: Plan, gt_mask: np.ndarray) -> tuple[float, float, float | None]:
    """(L_plan, L_gt, |L_plan - L_gt| / L_gt or None when the ground truth has no wall)."""
    l_plan, l_gt = plan_length_px(plan), skeleton_length(gt_mask)
    return l_plan, l_gt, (abs(l_plan - l_gt) / l_gt if l_gt else None)


@dataclass
class Matching:
    tp: dict[str, int]
    fp: dict[str, int]
    fn: dict[str, int]
    pos_err: list[float]  # px, along the wall, matched pairs
    width_err: list[float]  # px, matched pairs whose width was measured


def match_openings(gt: list[OpeningDetection], pred: list[PxOpening], t_med: float) -> Matching:
    """Same type, centre distance <= max(0.5 * long side of the gt box, 2 * t_med); greedy by distance."""
    pairs = []
    for gi, g in enumerate(gt):
        b = g.bbox
        gx, gy = b.center
        radius = max(0.5 * max(b.x1 - b.x0, b.y1 - b.y0), 2 * t_med)
        for pi, p in enumerate(pred):
            d = math.hypot(gx - p.cx, gy - p.cy)
            if g.type.value == p.type and d <= radius:
                pairs.append((d, gi, pi))
    used_g, used_p, matched = set(), set(), []
    for _, gi, pi in sorted(pairs):
        if gi not in used_g and pi not in used_p:
            used_g.add(gi)
            used_p.add(pi)
            matched.append((gi, pi))
    types = {g.type.value for g in gt} | {p.type for p in pred}
    m = Matching(
        tp={t: 0 for t in types}, fp={t: 0 for t in types}, fn={t: 0 for t in types},
        pos_err=[], width_err=[],
    )
    for gi, pi in matched:
        g, p = gt[gi].bbox, pred[pi]
        m.tp[p.type] += 1
        gx, gy = g.center
        m.pos_err.append(abs(gx - p.cx) if p.horizontal else abs(gy - p.cy))
        if not p.defaulted:
            m.width_err.append(abs(((g.x1 - g.x0) if p.horizontal else (g.y1 - g.y0)) - p.width))
    for gi, g in enumerate(gt):
        if gi not in used_g:
            m.fn[g.type.value] += 1
    for pi, p in enumerate(pred):
        if pi not in used_p:
            m.fp[p.type] += 1
    return m


def prf(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else None
    return {"precision": p, "recall": r, "f1": f}
