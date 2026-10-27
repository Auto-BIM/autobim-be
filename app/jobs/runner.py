"""Runs a job revision: (recognise once) -> apply supplements -> output files.

Called from FastAPI background tasks. Recognition runs only for the first revision;
later revisions replay supplements onto the stored base Plan.
"""

from __future__ import annotations

import logging

from app.core.config import Settings
from app.dxf_input.reader import dxf_to_plan
from app.export import write_outputs
from app.jobs.store import JobRecord, JobStore
from app.jobs.supplement import SupplementError, apply_supplements
from app.models.registry import Models
from app.preprocess.image import load_image
from app.recognition.pipeline import RecognitionError, image_to_plan
from app.schemas.jobs import FileKind, JobError, JobStatus
from app.schemas.plan import Plan, SourceType

log = logging.getLogger(__name__)


def file_url(job_id: str, kind: FileKind) -> str:
    return f"/api/jobs/{job_id}/files/{kind.value}"


def _recognise(record: JobRecord, models: Models, settings: Settings) -> Plan:
    data = record.input_path.read_bytes()
    if record.job.input.type == SourceType.dxf:
        return dxf_to_plan(data, filename=record.job.input.filename)
    return image_to_plan(
        load_image(data),
        models,
        filename=record.job.input.filename,
        review_threshold=settings.recognition.review_confidence_threshold,
    )


def _fail(store: JobStore, job_id: str, code: str, message: str) -> None:
    # plan/files/result_revision are left as they were: the last success stays visible
    store.update(job_id, status=JobStatus.failed, error=JobError(code=code, message=message))


def run_job(store: JobStore, job_id: str, models: Models, settings: Settings) -> None:
    record = store.get(job_id)
    if record is None:
        return
    job = store.update(job_id, status=JobStatus.running)
    try:
        if record.base_plan is None:
            store.set_base_plan(job_id, _recognise(record, models, settings))
        assert record.base_plan is not None
        plan = apply_supplements(record.base_plan, record.supplements)
        outputs = write_outputs(plan, record.dir / f"r{job.revision}")
    except (RecognitionError, SupplementError) as exc:
        _fail(store, job_id, exc.code, exc.message)
        return
    except NotImplementedError as exc:
        _fail(store, job_id, "not_implemented", str(exc))
        return
    except Exception as exc:  # noqa: BLE001 — a job must never stay "running"
        log.exception("job %s failed", job_id)
        _fail(store, job_id, "internal_error", str(exc))
        return
    urls = {kind: file_url(job_id, kind) for kind in outputs}
    store.set_result(job_id, job.revision, plan, outputs, urls)
