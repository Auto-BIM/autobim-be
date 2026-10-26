"""Plan: the intermediate representation between recognition and 3D generation.

CONTRACT — change only in a contract PR (bump SCHEMA_VERSION).

Conventions (see docs/design.md §2):
- Units are millimetres. Axes follow CAD: x right, y up.
- `Opening.position` is the distance along the wall centerline from `Wall.start`
  to the opening's centre.
- `Opening.sill_height` is measured from the floor to the bottom of the opening (doors: 0).
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Point2D(_Model):
    x: float
    y: float


class WallKind(str, Enum):
    exterior = "exterior"
    interior = "interior"
    unknown = "unknown"


class Wall(_Model):
    id: str = Field(min_length=1)
    start: Point2D = Field(description="Centerline start point (mm)")
    end: Point2D = Field(description="Centerline end point (mm)")
    thickness: float = Field(gt=0, description="mm")
    height: float = Field(gt=0, description="mm")
    kind: WallKind = WallKind.unknown
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @property
    def length(self) -> float:
        return math.hypot(self.end.x - self.start.x, self.end.y - self.start.y)

    @model_validator(mode="after")
    def _non_degenerate(self) -> Wall:
        if self.length <= 0:
            raise ValueError(f"wall {self.id!r} has zero length")
        return self


class OpeningType(str, Enum):
    door = "door"
    window = "window"


class Opening(_Model):
    id: str = Field(min_length=1)
    type: OpeningType
    wall_id: str = Field(description="ID of the wall this opening is cut into")
    position: float = Field(description="mm from wall start to opening centre, along the centerline")
    width: float = Field(gt=0, description="mm, along the wall")
    height: float = Field(gt=0, description="mm")
    sill_height: float = Field(default=0.0, ge=0, description="mm from floor to opening bottom")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ElementKind(str, Enum):
    wall = "wall"
    opening = "opening"
    dimension = "dimension"
    plan = "plan"


class ReviewReason(str, Enum):
    low_confidence = "low_confidence"
    scale_estimated = "scale_estimated"
    default_value_applied = "default_value_applied"
    unattached_opening = "unattached_opening"
    dimension_conflict = "dimension_conflict"
    other = "other"


class ReviewItem(_Model):
    """An element the user should confirm (확인 필요 요소)."""

    element_id: str = Field(description="Wall/opening ID, or 'plan' for plan-wide issues")
    element_kind: ElementKind
    reason: ReviewReason
    message: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


class ScaleSource(str, Enum):
    dimension = "dimension"  # from OCR'd dimension text
    building_width = "building_width"  # from a user-supplied overall width
    assumed_wall_thickness = "assumed_wall_thickness"  # exterior wall assumed 200 mm
    user = "user"  # explicit mm_per_px supplied by the user
    source_units = "source_units"  # DXF input; units taken from the file


class Scale(_Model):
    """How pixel measurements were converted to mm (크기 추정 여부)."""

    source: ScaleSource
    estimated: bool = Field(description="True when the scale is a guess, not a measurement")
    mm_per_px: float | None = Field(default=None, gt=0, description="None for DXF input")


class SourceType(str, Enum):
    image = "image"
    dxf = "dxf"


class PlanSource(_Model):
    type: SourceType
    filename: str | None = None
    width_px: int | None = None
    height_px: int | None = None


class Plan(_Model):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    units: Literal["mm"] = "mm"
    source: PlanSource
    scale: Scale
    walls: list[Wall] = Field(default_factory=list)
    openings: list[Opening] = Field(default_factory=list)
    review_items: list[ReviewItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_references(self) -> Plan:
        ids = [w.id for w in self.walls] + [o.id for o in self.openings]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate element ids: {sorted(dupes)}")
        wall_ids = {w.id for w in self.walls}
        for o in self.openings:
            if o.wall_id not in wall_ids:
                raise ValueError(f"opening {o.id!r} references unknown wall {o.wall_id!r}")
        known = set(ids) | {"plan"}
        for r in self.review_items:
            if r.element_kind != ElementKind.dimension and r.element_id not in known:
                raise ValueError(f"review item references unknown element {r.element_id!r}")
        return self

    def wall(self, wall_id: str) -> Wall:
        return next(w for w in self.walls if w.id == wall_id)
