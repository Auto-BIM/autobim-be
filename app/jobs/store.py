"""Job storage: in-memory index + one local directory per job.

Layout: <data_dir>/<job_id>/input.<ext>, <data_dir>/<job_id>/r<revision>/{plan.json,model.glb,model.dxf}
Earlier revisions' files stay on disk so the last success remains downloadable while
a new revision regenerates.
Not shared across processes and lost on restart (next-tasks #3 replaces this).
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.schemas.jobs import FileKind, Job, JobInput, JobStatus, SupplementRequest
from app.schemas.plan import Plan


@dataclass
class JobRecord:
    job: Job
    dir: Path
    input_path: Path
    supplements: list[SupplementRequest] = field(default_factory=list)
    base_plan: Plan | None = None  # first recognition result; supplements replay onto it
    outputs: dict[FileKind, Path] = field(default_factory=dict)  # of job.result_revision


def _now() -> datetime:
    return datetime.now(UTC)


class JobStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self._records: dict[str, JobRecord] = {}
        self._lock = threading.Lock()

    def create(self, job_input: JobInput, data: bytes) -> Job:
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
        with self._lock:
            self._records[job_id] = JobRecord(job=job, dir=job_dir, input_path=input_path)
        return job

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._records.get(job_id)

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

    def add_supplement(self, job_id: str, supplement: SupplementRequest) -> Job:
        with self._lock:
            record = self._records[job_id]
            record.supplements.append(supplement)
            record.job = record.job.model_copy(
                update={
                    "revision": record.job.revision + 1,
                    "status": JobStatus.queued,
                    "error": None,
                    "updated_at": _now(),
                }
            )
            return record.job
