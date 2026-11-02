"""Wall mask + opening boxes (px) -> axis-aligned walls and openings (px). docs/recognition.md.

Pixel space only; `pipeline.image_to_plan` turns the result into a Plan in mm.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage as ndi

from app.core.config import RecognitionSettings
from app.models.base import OpeningDetection
from app.recognition.openings import PixelOpening, attach_openings
from app.recognition.topology import classify, keep_building, rasterize
from app.recognition.walls import (
    PixelWall,
    clean_mask,
    estimate_thickness,
    extend_open_ends,
    extract_axis_walls,
    finish_walls,
    merge_collinear,
    remove_duplicate_walls,
    snap_junctions,
)
from app.schemas.plan import WallKind


@dataclass
class Recognition:
    t_med: float  # typical wall thickness, px
    walls: list[PixelWall] = field(default_factory=list)
    kinds: list[WallKind] = field(default_factory=list)  # one per wall
    openings: list[PixelOpening] = field(default_factory=list)
    unexplained_wall_ratio: float = 0.0  # building wall pixels no wall explains
    outside_walls: list[PixelWall] = field(default_factory=list)  # dropped: not in the building
    outside_wall_ratio: float = 0.0  # share of all wall pixels in those dropped walls
    other_plans: bool = False  # the sheet has several plans; only the largest was kept
    dropped_openings: int = 0  # boxes too far from every wall to be attached


def _unexplained_ratio(m: np.ndarray, walls: list[PixelWall], outside_px: np.ndarray) -> float:
    """R8: share of the building's wall pixels that no recognised wall covers.

    The building is whatever touches a recognised wall or lies inside their outline.
    The pixels of the walls dropped as outside the building are left out on both sides.
    """
    covered = rasterize(walls, m.shape)
    lab, _ = ndi.label(m | covered, structure=np.ones((3, 3), bool))
    building = np.isin(lab, np.unique(lab[covered])) | ndi.binary_fill_holes(covered)
    scored = m & building & ~outside_px
    return float((scored & ~covered).sum()) / max(int(scored.sum()), 1)


def recognize(
    mask: np.ndarray,
    detections: list[OpeningDetection],
    p: RecognitionSettings | None = None,
) -> Recognition:
    p = p or RecognitionSettings()
    mask = np.asarray(mask, dtype=bool)
    t0 = estimate_thickness(mask)
    if t0 == 0:
        return Recognition(t_med=0.0)
    m = clean_mask(mask, t0, p)
    t_med = estimate_thickness(m)
    if t_med == 0:
        return Recognition(t_med=0.0)

    walls = remove_duplicate_walls(extract_axis_walls(m, t_med, p), p)
    walls, gap_hits = merge_collinear(walls, detections, t_med, p)
    split = keep_building(walls, detections, mask.shape, t_med, p)
    walls, outside = split.kept, split.outside
    open_ends = snap_junctions(walls, t_med, p)
    extend_open_ends(walls, detections, open_ends, gap_hits, t_med)
    snap_junctions(walls, t_med, p)
    walls = finish_walls(walls, t_med, p)
    walls.sort(key=lambda w: (not w.horizontal, w.center, w.a))
    if not walls:
        return Recognition(t_med=t_med, outside_walls=outside, other_plans=split.other_plans)

    outside_px = m & rasterize(outside, m.shape, close_ends=False)
    # gap_hits refer to walls by identity: drop the hits of walls that were filtered out
    gap_hits = {i: [h for h in v if any(h.wall is w for w in walls)] for i, v in gap_hits.items()}
    openings, dropped_openings = attach_openings(
        walls, detections, gap_hits, p.max_opening_dist_factor * t_med
    )
    return Recognition(
        t_med=t_med,
        walls=walls,
        kinds=classify(walls, mask.shape, t_med),
        openings=openings,
        unexplained_wall_ratio=_unexplained_ratio(m, walls, outside_px),
        outside_walls=outside,
        outside_wall_ratio=float(outside_px.sum()) / max(int(m.sum()), 1),
        other_plans=split.other_plans,
        dropped_openings=dropped_openings,
    )
