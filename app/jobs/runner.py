"""Runs a job revision: (recognise once) -> apply supplements -> output files.

Called from FastAPI background tasks. Recognition runs only for the first revision;
later revisions replay supplements onto the stored base Plan.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from time import perf_counter

import anyio

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

# Inherit the server handler and INFO level used by the default uvicorn command.
log = logging.getLogger("uvicorn.error.jobs")


def file_url(job_id: str, kind: FileKind) -> str:
    return f"/api/jobs/{job_id}/files/{kind.value}"


def _recognise(record: JobRecord, models: Models, settings: Settings, timings: dict) -> Plan:
    with _timed(timings, "decode"):
        data = record.input_path.read_bytes()
        image = None if record.job.input.type == SourceType.dxf else load_image(data)
    with _timed(timings, "plan"):
        if image is None:
            return dxf_to_plan(data, filename=record.job.input.filename)
        return image_to_plan(
            image, models, filename=record.job.input.filename,
            settings=settings.recognition,
        )


@contextmanager
def _timed(timings: dict, stage: str):
    start = perf_counter()
    try:
        yield
    finally:
        timings[stage] += perf_counter() - start


def _fail(store: JobStore, job_id: str, code: str, message: str) -> None:
    # plan/files/result_revision are left as they were: the last success stays visible
    store.update(job_id, status=JobStatus.failed, error=JobError(code=code, message=message))


async def run_job_background(store: JobStore, job_id: str, models: Models, settings: Settings) -> None:
    """Queue without borrowing API thread tokens; bound job workers independently."""
    await anyio.to_thread.run_sync(
        run_job, store, job_id, models, settings, perf_counter(), limiter=store.runner_limiter,
    )


def run_job(
    store: JobStore, job_id: str, models: Models, settings: Settings, queued_at: float | None = None,
) -> None:
    record = store.get(job_id)
    if record is None:
        return
    timings = dict.fromkeys(("wait", "decode", "plan", "supplement", "export"), 0.0)
    started = queued_at if queued_at is not None else perf_counter()
    timings["wait"] = perf_counter() - started
    outcome = "failed"
    code = "none"
    error_info = None
    try:
        if record.base_plan is None:
            with _timed(timings, "wait"):
                store.recognition_slots.acquire()
            try:
                job = store.update(job_id, status=JobStatus.running)
                log.info("job %s started revision=%s wait=%.6fs", job_id, job.revision, timings["wait"])
                store.set_base_plan(job_id, _recognise(record, models, settings, timings))
            finally:
                store.recognition_slots.release()
        else:
            job = store.update(job_id, status=JobStatus.running)
            log.info("job %s started revision=%s wait=0.000000s", job_id, job.revision)
        assert record.base_plan is not None
        with _timed(timings, "supplement"):
            plan = apply_supplements(record.base_plan, record.supplements)
        with _timed(timings, "export"):
            outputs = write_outputs(plan, record.dir / f"r{job.revision}")
        urls = {kind: file_url(job_id, kind) for kind in outputs}
        store.set_result(job_id, job.revision, plan, outputs, urls)
        outcome = "completed"
    except (RecognitionError, SupplementError) as exc:
        code = exc.code
        _fail(store, job_id, code, exc.message)
    except NotImplementedError as exc:
        code = "not_implemented"
        _fail(store, job_id, code, str(exc))
    except Exception as exc:  # noqa: BLE001 — a job must never stay "running"
        error_info = (type(exc), exc, exc.__traceback__)
        code = "internal_error"
        _fail(store, job_id, code, str(exc))
    finally:
        log.log(
            logging.ERROR if code == "internal_error" else logging.INFO,
            "job %s %s code=%s %s total=%.6fs",
            job_id, outcome, code,
            " ".join(f"{stage}={duration:.6f}s" for stage, duration in timings.items()),
            perf_counter() - started,
            exc_info=error_info,
        )
