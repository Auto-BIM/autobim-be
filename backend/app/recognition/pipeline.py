"""Image path: model outputs -> Plan (mm)."""

from __future__ import annotations

import statistics

import numpy as np

from app.core import defaults
from app.models.base import DimensionText, OpeningDetection
from app.models.registry import Models
from app.preprocess.image import preprocess
from app.recognition.walls import PixelWall, extract_walls
from app.schemas.jobs import ScaleHint
from app.schemas.plan import (
    ElementKind,
    Opening,
    OpeningType,
    Plan,
    PlanSource,
    Point2D,
    ReviewItem,
    ReviewReason,
    Scale,
    ScaleSource,
    SourceType,
    Wall,
    WallKind,
)

DIMENSION_CONFLICT_RATIO = 0.05


class RecognitionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _wall_ids(walls: list[PixelWall]) -> list[str]:
    return [f"w{i + 1}" for i in range(len(walls))]


def _classify(walls: list[PixelWall]) -> list[WallKind]:
    """Walls lying on the bounding box of all centerlines are exterior."""
    xs = [w.center for w in walls if not w.horizontal]
    ys = [w.center for w in walls if w.horizontal]
    kinds = []
    for w in walls:
        edges = ys if w.horizontal else xs
        on_edge = bool(edges) and (
            abs(w.center - min(edges)) <= w.thickness or abs(w.center - max(edges)) <= w.thickness
        )
        kinds.append(WallKind.exterior if on_edge else WallKind.interior)
    return kinds


def _resolve_scale(
    walls: list[PixelWall],
    kinds: list[WallKind],
    dimensions: list[DimensionText],
    hint: ScaleHint | None,
    review: list[ReviewItem],
) -> Scale:
    if hint is not None:
        if hint.mm_per_px is not None:
            return Scale(source=ScaleSource.user, estimated=False, mm_per_px=hint.mm_per_px)
        if hint.building_width_mm is not None:
            xs = [w.center for w in walls if not w.horizontal]
            if len(xs) < 2 or max(xs) == min(xs):
                raise RecognitionError("scale_unresolvable", "no vertical walls to measure width")
            mm_per_px = hint.building_width_mm / (max(xs) - min(xs))
            return Scale(source=ScaleSource.building_width, estimated=False, mm_per_px=mm_per_px)
        assert hint.reference is not None
        ids = _wall_ids(walls)
        if hint.reference.wall_id not in ids:
            raise RecognitionError(
                "unknown_element", f"reference wall {hint.reference.wall_id!r} not found"
            )
        w = walls[ids.index(hint.reference.wall_id)]
        return Scale(
            source=ScaleSource.user, estimated=False, mm_per_px=hint.reference.length_mm / w.length
        )

    ratios = [d.value_mm / d.span_px for d in dimensions if d.value_mm and d.span_px > 0]
    if ratios:
        mm_per_px = statistics.median(ratios)
        if max(ratios) - min(ratios) > DIMENSION_CONFLICT_RATIO * mm_per_px:
            review.append(
                ReviewItem(
                    element_id="plan",
                    element_kind=ElementKind.plan,
                    reason=ReviewReason.dimension_conflict,
                    message="dimension readings disagree; using the median scale",
                    confidence=min(d.confidence for d in dimensions),
                )
            )
        return Scale(source=ScaleSource.dimension, estimated=False, mm_per_px=mm_per_px)

    exterior = [w.thickness for w, k in zip(walls, kinds) if k == WallKind.exterior]
    if not exterior:
        raise RecognitionError("scale_unresolvable", "no exterior walls to estimate scale from")
    mm_per_px = defaults.EXTERIOR_WALL_THICKNESS / statistics.median(exterior)
    review.append(
        ReviewItem(
            element_id="plan",
            element_kind=ElementKind.plan,
            reason=ReviewReason.scale_estimated,
            message=(
                "no dimensions found; scale assumes exterior walls are "
                f"{defaults.EXTERIOR_WALL_THICKNESS:g} mm thick"
            ),
            confidence=0.3,
        )
    )
    return Scale(source=ScaleSource.assumed_wall_thickness, estimated=True, mm_per_px=mm_per_px)


def _point_segment(px: float, py: float, w: PixelWall) -> tuple[float, float]:
    """(distance, t along wall from its start) in px."""
    (ax, ay), (bx, by) = w.endpoints()
    dx, dy = bx - ax, by - ay
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = min(1.0, max(0.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return float(np.hypot(px - cx, py - cy)), t * w.length


def _attach_openings(
    detections: list[OpeningDetection],
    walls: list[PixelWall],
    ids: list[str],
    mm_per_px: float,
    threshold: float,
    review: list[ReviewItem],
) -> list[Opening]:
    openings = []
    for i, det in enumerate(detections):
        oid = f"o{i + 1}"
        cx, cy = det.bbox.center
        hits = [_point_segment(cx, cy, w) for w in walls]
        idx = min(range(len(walls)), key=lambda j: hits[j][0])
        dist, along = hits[idx]
        wall = walls[idx]
        span_px = det.bbox.width if wall.horizontal else det.bbox.height
        is_door = det.type == OpeningType.door
        openings.append(
            Opening(
                id=oid,
                type=det.type,
                wall_id=ids[idx],
                position=along * mm_per_px,
                width=span_px * mm_per_px if span_px > 0 else (
                    defaults.DOOR_WIDTH if is_door else defaults.WINDOW_WIDTH
                ),
                height=defaults.DOOR_HEIGHT if is_door else defaults.WINDOW_HEIGHT,
                sill_height=0.0 if is_door else defaults.WINDOW_SILL_HEIGHT,
                confidence=det.confidence,
            )
        )
        if dist > max(wall.thickness * 1.5, 5.0):
            review.append(
                ReviewItem(
                    element_id=oid,
                    element_kind=ElementKind.opening,
                    reason=ReviewReason.unattached_opening,
                    message=f"nearest wall {ids[idx]} is {dist * mm_per_px:.0f} mm away",
                    confidence=det.confidence,
                )
            )
        if det.confidence < threshold:
            review.append(
                ReviewItem(
                    element_id=oid,
                    element_kind=ElementKind.opening,
                    reason=ReviewReason.low_confidence,
                    message=f"{det.type.value} detected with low confidence",
                    confidence=det.confidence,
                )
            )
    return openings


def image_to_plan(
    image: np.ndarray,
    models: Models,
    *,
    filename: str | None = None,
    review_threshold: float = 0.5,
    scale_hint: ScaleHint | None = None,
) -> Plan:
    image = preprocess(image)
    wall_mask = models.wall_segmenter.segment(image)
    detections = models.opening_detector.detect(image)
    dimensions = models.dimension_reader.read(image)

    walls = extract_walls(wall_mask.mask)
    if not walls:
        raise RecognitionError("no_walls", "no walls found in the wall mask")
    ids = _wall_ids(walls)
    kinds = _classify(walls)
    review: list[ReviewItem] = []
    scale = _resolve_scale(walls, kinds, dimensions, scale_hint, review)
    s = scale.mm_per_px
    assert s is not None
    height_px = wall_mask.mask.shape[0]

    def to_mm(p: tuple[float, float]) -> Point2D:
        # image y points down; Plan y points up
        return Point2D(x=p[0] * s, y=(height_px - p[1]) * s)

    plan_walls = []
    for wid, w, kind in zip(ids, walls, kinds):
        start, end = w.endpoints()
        plan_walls.append(
            Wall(
                id=wid,
                start=to_mm(start),
                end=to_mm(end),
                thickness=w.thickness * s,
                height=defaults.WALL_HEIGHT,
                kind=kind,
                confidence=wall_mask.confidence,
            )
        )
    openings = _attach_openings(detections, walls, ids, s, review_threshold, review)

    return Plan(
        source=PlanSource(
            type=SourceType.image,
            filename=filename,
            width_px=int(wall_mask.mask.shape[1]),
            height_px=int(height_px),
        ),
        scale=scale,
        walls=plan_walls,
        openings=openings,
        review_items=review,
    )
