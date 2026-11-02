"""Image path: model outputs -> Plan (mm)."""

from __future__ import annotations

import statistics

import numpy as np

from app.core import defaults
from app.core.config import RecognitionSettings
from app.models.base import DimensionText, OpeningDetection
from app.models.registry import Models
from app.preprocess.image import preprocess
from app.recognition.openings import PixelOpening
from app.recognition.recognize import recognize
from app.recognition.walls import PixelWall
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
UNEXPLAINED_REVIEW_RATIO = 0.05  # wall pixels no recognised wall explains
OPENING_WIDTH_RANGE = (300.0, 5000.0)  # mm; outside it the default width is used


class RecognitionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _resolve_scale(
    walls: list[PixelWall],
    kinds: list[WallKind],
    dimensions: list[DimensionText],
    review: list[ReviewItem],
) -> Scale:
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


def _opening_width(op: PixelOpening, mm_per_px: float) -> tuple[float, bool]:
    """(width in mm, whether the default had to replace an implausible width)."""
    width = (op.s1 - op.s0) * mm_per_px
    if OPENING_WIDTH_RANGE[0] <= width <= OPENING_WIDTH_RANGE[1]:
        return width, False
    is_door = op.type == OpeningType.door
    return (defaults.DOOR_WIDTH if is_door else defaults.WINDOW_WIDTH), True


def _plan_openings(
    pixel_openings: list[PixelOpening],
    detections: list[OpeningDetection],
    walls: list[PixelWall],
    ids: list[str],
    mm_per_px: float,
    threshold: float,
    review: list[ReviewItem],
) -> list[Opening]:
    openings = []
    for op in pixel_openings:
        det = detections[op.box_index]
        oid = f"o{op.box_index + 1}"
        wall = walls[op.wall_index]
        is_door = op.type == OpeningType.door
        width, defaulted = _opening_width(op, mm_per_px)
        centre = ((op.s0 + op.s1) / 2 - wall.a) * mm_per_px
        openings.append(
            Opening(
                id=oid,
                type=op.type,
                wall_id=ids[op.wall_index],
                position=min(max(centre, 0.0), wall.length * mm_per_px),
                width=width,
                height=defaults.DOOR_HEIGHT if is_door else defaults.WINDOW_HEIGHT,
                sill_height=0.0 if is_door else defaults.WINDOW_SILL_HEIGHT,
                confidence=det.confidence,
            )
        )
        if det.confidence < threshold:
            review.append(
                ReviewItem(
                    element_id=oid,
                    element_kind=ElementKind.opening,
                    reason=ReviewReason.low_confidence,
                    message=f"{op.type.value} detected with low confidence",
                    confidence=det.confidence,
                )
            )
        if op.source == "nearest":
            review.append(
                ReviewItem(
                    element_id=oid,
                    element_kind=ElementKind.opening,
                    reason=ReviewReason.unattached_opening,
                    message=(
                        f"no wall crosses this {op.type.value}; "
                        f"nearest wall {ids[op.wall_index]} is {op.dist * mm_per_px:.0f} mm away"
                    ),
                    confidence=det.confidence,
                )
            )
        if defaulted:
            review.append(
                ReviewItem(
                    element_id=oid,
                    element_kind=ElementKind.opening,
                    reason=ReviewReason.default_value_applied,
                    message=(
                        f"measured width {(op.s1 - op.s0) * mm_per_px:.0f} mm is implausible; "
                        f"using the default {width:g} mm"
                    ),
                    confidence=det.confidence,
                )
            )
    return openings


def image_to_plan(
    image: np.ndarray,
    models: Models,
    *,
    filename: str | None = None,
    review_threshold: float | None = None,
    settings: RecognitionSettings | None = None,
) -> Plan:
    settings = settings or RecognitionSettings()
    if review_threshold is None:
        review_threshold = settings.review_confidence_threshold
    image = preprocess(image)
    wall_mask = models.wall_segmenter.segment(image)
    detections = models.opening_detector.detect(image)
    dimensions = models.dimension_reader.read(image)

    found = recognize(wall_mask.mask, detections, settings)
    walls, kinds = found.walls, found.kinds
    if not walls:
        raise RecognitionError("no_walls", "no walls found in the wall mask")
    ids = [f"w{i + 1}" for i in range(len(walls))]
    review: list[ReviewItem] = []
    scale = _resolve_scale(walls, kinds, dimensions, review)
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
    openings = _plan_openings(found.openings, detections, walls, ids, s, review_threshold, review)
    if found.unexplained_wall_ratio > UNEXPLAINED_REVIEW_RATIO:
        review.append(
            ReviewItem(
                element_id="plan",
                element_kind=ElementKind.plan,
                reason=ReviewReason.other,
                message=f"인식되지 않은 벽 영역 {found.unexplained_wall_ratio:.0%}(사선 벽 등)",
                confidence=1.0 - found.unexplained_wall_ratio,
            )
        )

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
