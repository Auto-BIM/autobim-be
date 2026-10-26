"""Request/response models for the async jobs API.

CONTRACT — change only in a contract PR. docs/openapi.json is generated from these.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.plan import OpeningType, Plan, SourceType, WallKind


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


class Job(_Model):
    id: str
    status: JobStatus
    revision: int = Field(description="0 on creation; +1 for each accepted supplement")
    created_at: datetime
    updated_at: datetime
    input: JobInput
    plan: Plan | None = Field(default=None, description="Present once the job has succeeded")
    error: JobError | None = None
    files: dict[FileKind, str] = Field(
        default_factory=dict, description="Download URLs, present once the job has succeeded"
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
        default=None, description="Known centerline length of one wall"
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


class SupplementRequest(_Model):
    """User-supplied corrections. Applied in order: scale -> walls -> openings -> resolved."""

    scale: ScaleHint | None = None
    walls: list[WallPatch] = Field(default_factory=list)
    openings: list[OpeningPatch] = Field(default_factory=list)
    resolved: list[str] = Field(
        default_factory=list, description="Element IDs whose review items the user has confirmed"
    )


class ErrorDetail(_Model):
    code: str
    message: str


class ErrorResponse(_Model):
    detail: ErrorDetail
