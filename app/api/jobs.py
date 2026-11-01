"""Async jobs API. Paths and request/response shapes are CONTRACT (see docs/api.md)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from PIL import Image

from app.core.config import LimitsSettings
from app.jobs.runner import run_job
from app.jobs.store import JobRecord, JobStore
from app.jobs.supplement import SupplementError, replay_supplements
from app.schemas.jobs import ErrorResponse, FileKind, Job, JobInput, JobStatus, SupplementRequest
from app.schemas.plan import SourceType

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
MEDIA_TYPES = {
    FileKind.json: "application/json",
    FileKind.glb: "model/gltf-binary",
    FileKind.dxf: "image/vnd.dxf",
}

_404 = {404: {"model": ErrorResponse, "description": "Job not found"}}
_409 = {409: {"model": ErrorResponse, "description": "Job is not in a state that allows this"}}


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _store(request: Request) -> JobStore:
    return request.app.state.store


def _record(request: Request, job_id: str) -> JobRecord:
    record = _store(request).get(job_id)
    if record is None:
        raise _error(404, "job_not_found", f"job {job_id!r} not found")
    return record


def _source_type(upload: UploadFile) -> SourceType:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix == ".dxf":
        return SourceType.dxf
    if suffix in IMAGE_SUFFIXES or (upload.content_type or "").startswith("image/"):
        return SourceType.image
    raise _error(415, "unsupported_media_type", "upload an image (png/jpg/...) or a .dxf file")


def _check_image(data: bytes, limits: LimitsSettings) -> None:
    """Reject images over the pixel limit or that cannot be decoded, without decoding pixels.

    `Image.open` reads only the header. `verify()` walks PNG chunks and checks CRCs, which
    catches truncated PNGs; for other formats it checks nothing beyond the header.
    """
    try:
        with Image.open(io.BytesIO(data)) as img:
            pixels = img.width * img.height
            if pixels > limits.max_pixels:
                raise _image_too_large(f"{pixels} px", limits)
            img.verify()
    except Image.DecompressionBombError:  # Pillow refuses absurd headers before we can look
        raise _image_too_large("a decompression bomb", limits) from None
    except (OSError, SyntaxError, ValueError) as exc:  # includes UnidentifiedImageError
        raise _error(
            415, "unsupported_media_type", "cannot decode the image (corrupt or unsupported format)"
        ) from exc


def _image_too_large(size: str, limits: LimitsSettings) -> HTTPException:
    return _error(413, "image_too_large", f"image is {size}; the limit is {limits.max_pixels} px")


def _schedule(request: Request, background: BackgroundTasks, job_id: str) -> None:
    state = request.app.state
    background.add_task(run_job, state.store, job_id, state.models, state.settings)


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Job,
    responses={
        413: {"model": ErrorResponse, "description": "File or image too large"},
        415: {
            "model": ErrorResponse,
            "description": "Unsupported file type, or an image that cannot be decoded",
        },
    },
    summary="Create a conversion job from an uploaded floor plan (image or .dxf)",
)
async def create_job(
    request: Request,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File(description="Floor plan image (png/jpg/...) or .dxf")],
) -> Job:
    source_type = _source_type(file)
    limits = request.app.state.settings.limits
    data = await file.read(limits.max_upload_bytes + 1)  # never hold more than the limit
    if len(data) > limits.max_upload_bytes:
        raise _error(
            413, "file_too_large", f"file is over the {limits.max_upload_mb} MB upload limit"
        )
    if source_type == SourceType.image:
        _check_image(data, limits)
    job_input = JobInput(
        filename=file.filename or "upload", type=source_type, content_type=file.content_type
    )
    job = _store(request).create(job_input, data)
    _schedule(request, background, job.id)
    return job


@router.get("/{job_id}", response_model=Job, responses=_404, summary="Get job status and Plan")
def get_job(request: Request, job_id: str) -> Job:
    return _record(request, job_id).job


@router.post(
    "/{job_id}/supplement",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Job,
    responses={
        **_404,
        **_409,
        400: {"model": ErrorResponse, "description": "Supplement references unknown elements"},
    },
    summary="Submit user corrections and regenerate (increments revision)",
)
def supplement_job(
    request: Request, background: BackgroundTasks, job_id: str, body: SupplementRequest
) -> Job:
    record = _record(request, job_id)
    if record.job.status in (JobStatus.queued, JobStatus.running):
        raise _error(409, "job_busy", f"job is {record.job.status.value}; retry when it finishes")
    if record.job.plan is None or record.base_plan is None:
        raise _error(409, "no_plan", "job has no plan to supplement (it never succeeded)")
    try:  # dry run so a bad supplement is rejected now instead of failing the job later
        replay = replay_supplements(record.base_plan, [*record.supplements, body])
    except SupplementError as exc:
        raise _error(400, exc.code, exc.message) from exc
    job = _store(request).add_supplement(job_id, body, removed=replay.removed)
    _schedule(request, background, job_id)
    return job


@router.get(
    "/{job_id}/files/{kind}",
    response_class=FileResponse,
    responses={
        **_404,
        **_409,
        200: {
            "description": "The requested output file",
            "content": {media: {} for media in MEDIA_TYPES.values()},
        },
    },
    summary="Download an output file (dxf | glb | json)",
)
def get_job_file(request: Request, job_id: str, kind: FileKind) -> FileResponse:
    record = _record(request, job_id)
    path = record.outputs.get(kind)  # last successful revision, even while regenerating
    if path is None:
        raise _error(409, "not_ready", f"job is {record.job.status.value}; no files yet")
    return FileResponse(path, media_type=MEDIA_TYPES[kind], filename=f"{job_id}.{kind.value}")
