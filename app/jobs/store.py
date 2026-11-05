"""Job storage: in-memory index + one local directory per job.

Layout: <data_dir>/<job_id>/input.<ext>, <data_dir>/<job_id>/r<revision>/{plan.json,model.glb,model.dxf}
Earlier revisions' files stay on disk so the last success remains downloadable while
a new revision regenerates.
Not shared across processes and lost on restart (issue #4 replaces this).
"""

from __future__ import annotations

import logging
import re
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
from fastapi import HTTPException

from app.core.config import JobsSettings
from app.schemas.jobs import (
    FileKind,
    Job,
    JobInput,
    JobStatus,
    RemovedElement,
    SupplementRequest,
)
from app.schemas.plan import Plan


@dataclass
class JobRecord:
    job: Job
    dir: Path
    input_path: Path
    supplements: list[SupplementRequest] = field(default_factory=list)
    base_plan: Plan | None = None  # first recognition result; supplements replay onto it
    outputs: dict[FileKind, Path] = field(default_factory=dict)  # of job.result_revision
    downloads: int = 0  # active responses; TTL cleanup must wait for them


def _now() -> datetime:
    return datetime.now(UTC)


class JobStore:
    def __init__(self, data_dir: Path, settings: JobsSettings | None = None) -> None:
        self.data_dir = data_dir
        self._records: dict[str, JobRecord] = {}
        self._lock = threading.Lock()
        self.settings = settings or JobsSettings()
        self.recognition_slots = threading.BoundedSemaphore(self.settings.max_concurrent)
        # Waiting jobs use async capacity acquisition, independent of the API thread pool.
        # One extra worker permits export and the next recognition to overlap.
        self.runner_limiter = anyio.CapacityLimiter(self.settings.max_concurrent + 1)
        self.cleanup()

    def cleanup(self) -> None:
        """Expire inactive records and UUID folders left by earlier processes.

        Hold the index lock through removal so queued/running records cannot be
        deleted while a revision starts. Orphans use directory mtime after restart.
        """
        cutoff = _now() - timedelta(hours=self.settings.ttl_hours)
        with self._lock:
            for job_id, record in list(self._records.items()):
                try:
                    if (not record.downloads
                            and record.job.status not in (JobStatus.queued, JobStatus.running)
                            and record.job.updated_at < cutoff and not record.dir.exists()):
                        self._records.pop(job_id)
                except OSError:
                    logging.getLogger(__name__).warning("job %s cleanup_failed", job_id)
            try:
                folders = list(self.data_dir.iterdir())
            except FileNotFoundError:
                return
            except OSError:
                logging.getLogger(__name__).warning("jobs cleanup_scan_failed")
                return
            for folder in folders:
                if not re.fullmatch(r"[0-9a-f]{32}", folder.name):
                    continue
                try:
                    if folder.is_symlink() or not folder.is_dir():
                        continue
                    record = self._records.get(folder.name)
                    if record is not None:
                        if record.downloads or record.job.status in (JobStatus.queued, JobStatus.running):
                            continue
                        timestamp = record.job.updated_at
                    else:
                        timestamp = datetime.fromtimestamp(folder.stat().st_mtime, UTC)
                    if timestamp >= cutoff:
                        continue
                    shutil.rmtree(folder)
                except OSError:
                    logging.getLogger(__name__).warning("job %s cleanup_failed", folder.name)
                    continue
                self._records.pop(folder.name, None)

    def create(self, job_input: JobInput, data: bytes) -> Job:
        self.cleanup()
        with self._lock:
            job_id = uuid.uuid4().hex
            job_dir = self.data_dir / job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            suffix = Path(job_input.filename).suffix.lower() or ".bin"
            input_path = job_dir / f"input{suffix}"
            input_path.write_bytes(data)
            now = _now()
            job = Job(
                id=job_id,
                status=JobStatus.queued,
                revision=0,
                created_at=now,
                updated_at=now,
                input=job_input,
            )
            self._records[job_id] = JobRecord(job=job, dir=job_dir, input_path=input_path)
        return job

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._records.get(job_id)

    def acquire_download(self, job_id: str) -> JobRecord | None:
        """Pin the record and its files atomically with respect to TTL cleanup."""
        with self._lock:
            record = self._records.get(job_id)
            if record is not None:
                record.downloads += 1
            return record

    def release_download(self, job_id: str) -> None:
        with self._lock:
            self._records[job_id].downloads -= 1

    def update(self, job_id: str, **changes) -> Job:
        with self._lock:
            record = self._records[job_id]
            record.job = record.job.model_copy(update={**changes, "updated_at": _now()})
            return record.job

    def set_base_plan(self, job_id: str, plan: Plan) -> None:
        with self._lock:
            self._records[job_id].base_plan = plan

    def set_result(
        self, job_id: str, revision: int, plan: Plan, outputs: dict[FileKind, Path], urls: dict
    ) -> Job:
        with self._lock:
            record = self._records[job_id]
            record.outputs = outputs
            record.job = record.job.model_copy(
                update={
                    "status": JobStatus.succeeded,
                    "result_revision": revision,
                    "plan": plan,
                    "files": urls,
                    "error": None,
                    "updated_at": _now(),
                }
            )
            return record.job

    def add_supplement(
        self, job_id: str, supplement: SupplementRequest, removed: list[RemovedElement]
    ) -> Job:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                # TTL cleanup can run while the API validates a supplement.
                raise HTTPException(
                    status_code=404,
                    detail={"code": "job_not_found", "message": f"job {job_id!r} not found"},
                )
            record.supplements.append(supplement)
            record.job = record.job.model_copy(
                update={
                    "revision": record.job.revision + 1,
                    "removed": removed,
                    "status": JobStatus.queued,
                    "error": None,
                    "updated_at": _now(),
                }
            )
            return record.job
