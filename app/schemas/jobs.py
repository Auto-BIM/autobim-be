"""Request/response models for the async jobs API.

CONTRACT — change only in a contract PR. docs/openapi.json is generated from these.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.plan import ElementKind, OpeningType, Plan, Point2D, SourceType, WallKind


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class FileKind(str, Enum):
    dxf = "dxf"
    glb = "glb"
    json = "json"


class JobInput(_Model):
    filename: str
    type: SourceType
    content_type: str | None = None


class JobError(_Model):
    code: str
    message: str


class RemovedElement(_Model):
    id: str
    element_kind: ElementKind = Field(description="wall or opening")
    revision: int = Field(description="Revision whose supplement removed it")
    cascade_from: str | None = Field(
        default=None,
        description="Wall whose removal took this opening with it; null if removed directly",
    )


class Job(_Model):
    id: str
    status: JobStatus
    revision: int = Field(
        description="Requested revision: 0 on creation, +1 for each accepted supplement"
    )
    result_revision: int | None = Field(
        default=None,
        description=(
            "Revision that `plan` and `files` belong to: the last successful one. "
            "Lags `revision` while regenerating or after a failed regeneration; null until "
            "the first success"
        ),
    )
    created_at: datetime
    updated_at: datetime
    input: JobInput
    plan: Plan | None = Field(default=None, description="Plan of `result_revision`")
    error: JobError | None = Field(default=None, description="Why the latest revision failed")
    files: dict[FileKind, str] = Field(
        default_factory=dict, description="Download URLs for `result_revision`'s outputs"
    )
    removed: list[RemovedElement] = Field(
        default_factory=list,
        description=(
            "Elements removed by supplements up to `revision`, including openings removed "
            "together with their wall. Removed IDs are never reused"
        ),
    )


class WallReference(_Model):
    wall_id: str
    length_mm: float = Field(gt=0)


class ScaleHint(_Model):
    """Exactly one way to fix the plan's scale."""

    mm_per_px: float | None = Field(default=None, gt=0)
    building_width_mm: float | None = Field(
        default=None,
        gt=0,
        description="Building width (x extent) between the outermost wall centerlines, mm",
    )
    reference: WallReference | None = Field(
        default=None, description="Known centerline length of one recognized wall"
    )

    @model_validator(mode="after")
    def _exactly_one(self) -> ScaleHint:
        given = [v for v in (self.mm_per_px, self.building_width_mm, self.reference) if v is not None]
        if len(given) != 1:
            raise ValueError("set exactly one of mm_per_px, building_width_mm, reference")
        return self


class WallPatch(_Model):
    id: str
    thickness: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)
    kind: WallKind | None = None


class OpeningPatch(_Model):
    id: str
    type: OpeningType | None = None
    wall_id: str | None = None
    position: float | None = None
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)
    sill_height: float | None = Field(default=None, ge=0)


class NewWall(_Model):
    """A wall the recognizer missed. Omitted sizes fall back to docs/ASSUMPTIONS.md."""

    start: Point2D
    end: Point2D
    thickness: float | None = Field(
        default=None, gt=0, description="Default: exterior/interior wall thickness by `kind`"
    )
    height: float | None = Field(default=None, gt=0, description="Default: wall height")
    kind: WallKind = WallKind.interior


class NewOpening(_Model):
    """A door/window the recognizer missed. Omitted sizes fall back to docs/ASSUMPTIONS.md."""

    type: OpeningType
    wall_id: str = Field(description="An existing wall (not one added in the same request)")
    position: float
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)
    sill_height: float | None = Field(default=None, ge=0)


class SupplementRequest(_Model):
    """User-supplied corrections, applied to the stored Plan without re-running the models.

    Order: scale -> walls -> openings -> remove -> add_walls -> add_openings -> resolved.
    Existing element IDs never change; added elements get new IDs; removed IDs are never reused.
    """

    scale: ScaleHint | None = None
    walls: list[WallPatch] = Field(default_factory=list)
    openings: list[OpeningPatch] = Field(default_factory=list)
    remove: list[str] = Field(
        default_factory=list,
        description="Wall/opening IDs to delete. Removing a wall also removes its openings",
    )
    add_walls: list[NewWall] = Field(default_factory=list)
    add_openings: list[NewOpening] = Field(default_factory=list)
    resolved: list[str] = Field(
        default_factory=list, description="Element IDs whose review items the user has confirmed"
    )


class ErrorDetail(_Model):
    code: str
    message: str


class ErrorResponse(_Model):
    detail: ErrorDetail
