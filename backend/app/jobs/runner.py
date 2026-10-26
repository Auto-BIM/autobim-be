"""Runs a job: input -> Plan -> output files. Called from FastAPI background tasks."""

from __future__ import annotations

import logging

from app.core.config import Settings
from app.dxf_input.reader import dxf_to_plan
from app.export import write_outputs
from app.jobs.store import JobStore
from app.jobs.supplement import apply_supplements, latest_scale_hint
from app.models.registry import Models
from app.preprocess.image import load_image
from app.recognition.pipeline import RecognitionError, image_to_plan
from app.schemas.jobs import FileKind, JobError, JobStatus
from app.schemas.plan import SourceType

log = logging.getLogger(__name__)


def file_url(job_id: str, kind: FileKind) -> str:
    return f"/api/jobs/{job_id}/files/{kind.value}"


def _fail(store: JobStore, job_id: str, code: str, message: str) -> None:
    store.update(job_id, status=JobStatus.failed, error=JobError(code=code, message=message))


def run_job(store: JobStore, job_id: str, models: Models, settings: Settings) -> None:
    record = store.get(job_id)
    if record is None:
        return
    job = store.update(job_id, status=JobStatus.running)
    try:
        data = record.input_path.read_bytes()
        if job.input.type == SourceType.dxf:
            plan = dxf_to_plan(data, filename=job.input.filename)
        else:
            plan = image_to_plan(
                load_image(data),
                models,
                filename=job.input.filename,
                review_threshold=settings.recognition.review_confidence_threshold,
                scale_hint=latest_scale_hint(record.supplements),
            )
        plan = apply_supplements(plan, record.supplements)
        outputs = write_outputs(plan, record.dir / f"r{job.revision}")
    except RecognitionError as exc:
        _fail(store, job_id, exc.code, exc.message)
        return
    except NotImplementedError as exc:
        _fail(store, job_id, "not_implemented", str(exc))
        return
    except Exception as exc:  # noqa: BLE001 — a job must never stay "running"
        log.exception("job %s failed", job_id)
        _fail(store, job_id, "internal_error", str(exc))
        return
    record.outputs = outputs
    store.update(
        job_id,
        status=JobStatus.succeeded,
        plan=plan,
        files={kind: file_url(job_id, kind) for kind in outputs},
    )
