import asyncio
import logging
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.core.config import JobsSettings, load_settings
from app.jobs import runner
from app.jobs import store as store_module
from app.jobs.store import JobStore
from app.models.registry import build_models
from app.schemas.jobs import JobInput, JobStatus
from app.schemas.plan import SourceType


def create(store, data):
    return store.create(JobInput(filename="plan.png", type=SourceType.image), data)


@pytest.mark.parametrize("values", [{"max_concurrent": 0}, {"ttl_hours": 0},
                                    {"ttl_hours": float("inf")}, {"ttl_hours": 1e9}])
def test_invalid_job_settings(values):
    with pytest.raises(ValidationError):
        JobsSettings(**values)


def test_jobs_settings_file(tmp_path):
    config = tmp_path / "settings.yaml"
    config.write_text("jobs: {max_concurrent: 2, ttl_hours: 12}")
    settings = load_settings(config)
    assert settings.jobs == JobsSettings(max_concurrent=2, ttl_hours=12)


@pytest.mark.parametrize("fail_first", [False, True])
def test_recognition_waits_queued_and_releases_after_failure(
    tmp_path, settings, png_bytes, monkeypatch, fail_first
):
    store = JobStore(tmp_path / "jobs")
    models = build_models(settings.models)
    entered, release, waiting = threading.Event(), threading.Event(), threading.Event()
    segment = models.wall_segmenter.segment
    calls = 0

    def slow(image):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            assert release.wait(10)
            if fail_first:
                raise RuntimeError("controlled failure")
        return segment(image)

    monkeypatch.setattr(models.wall_segmenter, "segment", slow)
    slots = store.recognition_slots

    class ObservedSlots:
        def acquire(self):
            if entered.is_set():
                waiting.set()
            return slots.acquire()

        def release(self):
            slots.release()

    store.recognition_slots = ObservedSlots()
    first, second = create(store, png_bytes), create(store, png_bytes)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(runner.run_job, store, first.id, models, settings)
        try:
            assert entered.wait(10)
            two = pool.submit(runner.run_job, store, second.id, models, settings)
            assert waiting.wait(10)
            assert store.get(first.id).job.status == JobStatus.running
            assert store.get(second.id).job.status == JobStatus.queued
            assert calls == 1
        finally:
            release.set()
        one.result(timeout=10)
        two.result(timeout=10)
    assert calls == 2
    expected = JobStatus.failed if fail_first else JobStatus.succeeded
    assert store.get(first.id).job.status == expected
    assert store.get(second.id).job.status == JobStatus.succeeded


def test_ttl_cleanup_and_api_404(client, png_bytes, monkeypatch):
    store = client.app.state.store
    jobs = [create(store, png_bytes) for _ in range(4)]
    for job, status in zip(jobs, [JobStatus.succeeded, JobStatus.failed,
                                 JobStatus.queued, JobStatus.running], strict=True):
        store.update(job.id, status=status)
    now = store_module._now()
    monkeypatch.setattr(store_module, "_now", lambda: now + timedelta(hours=73))
    create(store, png_bytes)
    for job in jobs[:2]:
        assert client.get(f"/api/jobs/{job.id}").status_code == 404
        assert not (store.data_dir / job.id).exists()
    for job in jobs[2:]:
        assert client.get(f"/api/jobs/{job.id}").status_code == 200
        assert (store.data_dir / job.id).exists()


def test_startup_cleans_only_expired_uuid_folders(tmp_path):
    old = tmp_path / ("a" * 32)
    recent = tmp_path / ("b" * 32)
    unrelated = tmp_path / "keep"
    for folder in (old, recent, unrelated):
        folder.mkdir()
        (folder / "input.bin").write_bytes(b"test")
    os.utime(old, (0, 0))
    os.utime(unrelated, (0, 0))
    JobStore(tmp_path)
    assert not old.exists()
    assert recent.exists() and unrelated.exists()


def test_cleanup_failure_retains_record(tmp_path, png_bytes, monkeypatch, caplog):
    store = JobStore(tmp_path)
    job = create(store, png_bytes)
    store.update(job.id, status=JobStatus.failed)
    now = store_module._now()
    monkeypatch.setattr(store_module, "_now", lambda: now + timedelta(hours=73))

    def denied(path):
        raise PermissionError("busy")

    monkeypatch.setattr(store_module.shutil, "rmtree", denied)
    store.cleanup()
    assert store.get(job.id) is not None
    assert "cleanup_failed" in caplog.text


@pytest.mark.parametrize("failure", [False, True])
def test_job_logs_have_id_and_stage_timings(
    tmp_path, settings, png_bytes, monkeypatch, caplog, failure
):
    store = JobStore(tmp_path)
    models = build_models(settings.models)
    if failure:
        def broken(image):
            raise RuntimeError("failure\nwith newline")
        monkeypatch.setattr(models.wall_segmenter, "segment", broken)
    job = create(store, png_bytes)
    with caplog.at_level(logging.INFO, logger=runner.log.name):
        runner.run_job(store, job.id, models, settings)
    messages = [r.getMessage() for r in caplog.records if r.name == runner.log.name]
    assert len(messages) == 2
    assert all(job.id in message and "\n" not in message for message in messages)
    assert "started" in messages[0]
    assert ("failed" if failure else "completed") in messages[1]
    for stage in ("wait", "decode", "plan", "supplement", "export", "total"):
        assert f"{stage}=" in messages[1]


def test_expired_record_without_folder_is_removed(tmp_path, png_bytes, monkeypatch):
    store = JobStore(tmp_path)
    job = create(store, png_bytes)
    store.update(job.id, status=JobStatus.failed)
    store_module.shutil.rmtree(store.get(job.id).dir)
    now = store_module._now()
    monkeypatch.setattr(store_module, "_now", lambda: now + timedelta(hours=73))
    store.cleanup()
    assert store.get(job.id) is None


def test_recognition_slot_is_released_before_export(
    tmp_path, settings, png_bytes, monkeypatch
):
    store = JobStore(tmp_path)
    models = build_models(settings.models)
    exporting, release = threading.Event(), threading.Event()
    original = runner.write_outputs
    first, second = create(store, png_bytes), create(store, png_bytes)

    def blocked_export(plan, path):
        if path.parent.name == first.id:
            exporting.set()
            assert release.wait(10)
        return original(plan, path)

    monkeypatch.setattr(runner, "write_outputs", blocked_export)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(runner.run_job, store, first.id, models, settings)
        try:
            assert exporting.wait(10)
            two = pool.submit(runner.run_job, store, second.id, models, settings)
            two.result(timeout=10)
            assert store.get(second.id).job.status == JobStatus.succeeded
            assert store.get(first.id).job.status == JobStatus.running
        finally:
            release.set()
        one.result(timeout=10)


def test_store_uses_configured_jobs_at_startup(tmp_path, settings, png_bytes, monkeypatch):
    settings.jobs = JobsSettings(max_concurrent=2, ttl_hours=1)
    old = tmp_path / ("c" * 32)
    old.mkdir()
    now = store_module._now().timestamp()
    os.utime(old, (now - 7200, now - 7200))
    store = JobStore(tmp_path, settings.jobs)
    assert not old.exists()
    assert store.recognition_slots.acquire(blocking=False)
    assert store.recognition_slots.acquire(blocking=False)
    assert not store.recognition_slots.acquire(blocking=False)
    store.recognition_slots.release()
    store.recognition_slots.release()
    job = create(store, png_bytes)
    store.update(job.id, status=JobStatus.failed)
    clock = store_module._now()
    monkeypatch.setattr(store_module, "_now", lambda: clock + timedelta(hours=2))
    create(store, png_bytes)
    assert store.get(job.id) is None


def test_default_uvicorn_config_emits_job_logs(tmp_path):
    script = r"""
import io
import sys
from pathlib import Path
from PIL import Image
from uvicorn.config import Config
from app.core.config import Settings
from app.jobs.runner import run_job
from app.jobs.store import JobStore
from app.models.registry import build_models
from app.schemas.jobs import JobInput
from app.schemas.plan import SourceType
Config("app.main:app").configure_logging()
settings = Settings()
store = JobStore(Path(sys.argv[1]))
buf = io.BytesIO()
Image.new("RGB", (100, 70), "white").save(buf, format="PNG")
job = store.create(JobInput(filename="plan.png", type=SourceType.image), buf.getvalue())
print(job.id)
run_job(store, job.id, build_models(settings.models), settings)
"""
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", script, str(tmp_path / "jobs")],
        capture_output=True, text=True, check=True, timeout=30,
    )
    job_id = result.stdout.strip()
    lines = [line for line in result.stderr.splitlines() if job_id in line]
    assert len(lines) == 2
    assert "started" in lines[0] and "completed" in lines[1]
    assert "decode=" in lines[1] and "total=" in lines[1]


def test_cleanup_cannot_delete_a_job_during_input_write(tmp_path, png_bytes, monkeypatch):
    store = JobStore(tmp_path)
    written, release = threading.Event(), threading.Event()
    original_write = type(tmp_path).write_bytes
    original_lock = store._lock
    creator = None

    class ObservedLock:
        def __enter__(self):
            if written.is_set() and threading.get_ident() != creator:
                release.set()
            original_lock.acquire()

        def __exit__(self, *args):
            original_lock.release()

    def blocked_write(path, data):
        result = original_write(path, data)
        os.utime(path.parent, (0, 0))
        written.set()
        assert release.wait(10)
        return result

    def create_in_thread():
        nonlocal creator
        creator = threading.get_ident()
        return create(store, png_bytes)

    store._lock = ObservedLock()
    monkeypatch.setattr(type(tmp_path), "write_bytes", blocked_write)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(create_in_thread)
        try:
            assert written.wait(10)
            assert original_lock.locked()
            store.cleanup()
        finally:
            release.set()
        job = future.result(timeout=10)
    assert store.get(job.id).job.status == JobStatus.queued
    assert store.get(job.id).input_path.read_bytes() == png_bytes


def test_cleanup_during_supplement_validation_returns_404(client, png_bytes, monkeypatch):
    from app.api import jobs as jobs_api

    response = client.post("/api/jobs", files={"file": ("plan.png", png_bytes, "image/png")})
    job_id = response.json()["id"]
    store = client.app.state.store
    assert store.get(job_id).job.status == JobStatus.succeeded
    now = store_module._now()
    monkeypatch.setattr(store_module, "_now", lambda: now + timedelta(hours=73))
    replay = jobs_api.replay_supplements

    def expire_during_validation(*args, **kwargs):
        result = replay(*args, **kwargs)
        store.cleanup()
        return result

    monkeypatch.setattr(jobs_api, "replay_supplements", expire_during_validation)
    response = client.post(f"/api/jobs/{job_id}/supplement", json={})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "job_not_found"


def test_app_passes_job_settings_to_store(settings, tmp_path):
    from app.main import create_app

    settings.jobs = JobsSettings(max_concurrent=2, ttl_hours=1)
    old = settings.data_dir / ("d" * 32)
    old.mkdir(parents=True)
    os.utime(old, (0, 0))
    store = create_app(settings).state.store
    assert store.settings == settings.jobs
    assert not old.exists()
    assert store.recognition_slots.acquire(blocking=False)
    assert store.recognition_slots.acquire(blocking=False)
    assert not store.recognition_slots.acquire(blocking=False)
    store.recognition_slots.release()
    store.recognition_slots.release()


@pytest.mark.parametrize("failure", [None, RuntimeError, asyncio.CancelledError])
def test_download_pin_covers_response_and_releases_on_failure(
    client, png_bytes, monkeypatch, failure
):
    from types import SimpleNamespace

    from app.api.jobs import get_job_file
    from app.schemas.jobs import FileKind

    job = client.post("/api/jobs", files={"file": ("plan.png", png_bytes, "image/png")}).json()
    store = client.app.state.store
    record = store.get(job["id"])
    expected = record.outputs[FileKind.glb].read_bytes()
    request = SimpleNamespace(app=client.app)
    response = get_job_file(request, job["id"], FileKind.glb)
    now = store_module._now()
    monkeypatch.setattr(store_module, "_now", lambda: now + timedelta(hours=73))
    store.cleanup()  # Before FileResponse stats/opens the file.
    assert store.get(job["id"]) is record
    chunks = []

    async def send(message):
        store.cleanup()  # Also protect the response while it sends data.
        assert record.dir.exists()
        if failure is not None:
            raise failure()
        if message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    async def receive():
        return {"type": "http.disconnect"}

    async def serve():
        await response(
            {"type": "http", "method": "GET", "headers": [],
             "asgi": {"spec_version": "2.4"}}, receive, send,
        )

    if failure is None:
        asyncio.run(serve())
        assert b"".join(chunks) == expected
    else:
        with pytest.raises(failure):
            asyncio.run(serve())
    assert record.downloads == 0
    store.cleanup()
    assert store.get(job["id"]) is None
    assert not record.dir.exists()
    assert client.get(f"/api/jobs/{job['id']}/files/glb").status_code == 404


def test_not_ready_download_does_not_leak_pin(client, png_bytes):
    store = client.app.state.store
    job = create(store, png_bytes)
    assert client.get(f"/api/jobs/{job.id}/files/glb").status_code == 409
    assert store.get(job.id).downloads == 0


def test_multiple_downloads_keep_independent_pins(client, png_bytes, monkeypatch):
    store = client.app.state.store
    job = client.post("/api/jobs", files={"file": ("plan.png", png_bytes, "image/png")}).json()
    record = store.acquire_download(job["id"])
    store.acquire_download(job["id"])
    now = store_module._now()
    monkeypatch.setattr(store_module, "_now", lambda: now + timedelta(hours=73))
    store.release_download(job["id"])
    store.cleanup()
    assert store.get(job["id"]) is record and record.downloads == 1
    store.release_download(job["id"])
    store.cleanup()
    assert store.get(job["id"]) is None


def test_internal_error_keeps_traceback(tmp_path, settings, png_bytes, monkeypatch, caplog):
    store = JobStore(tmp_path)
    job = create(store, png_bytes)

    def broken(*args):
        raise RuntimeError("specific model failure detail")

    monkeypatch.setattr(runner, "_recognise", broken)
    with caplog.at_level(logging.INFO, logger=runner.log.name):
        runner.run_job(store, job.id, build_models(settings.models), settings)
    failures = [r for r in caplog.records if r.exc_info]
    assert len(failures) == 1
    assert failures[0].exc_info[0] is RuntimeError
    assert "specific model failure detail" in caplog.text
    assert "Traceback" in caplog.text


@pytest.mark.parametrize("operation", ["iterdir", "stat", "is_dir"])
def test_cleanup_metadata_errors_do_not_break_creation(tmp_path, png_bytes, monkeypatch, operation):
    store = JobStore(tmp_path)
    orphan = tmp_path / ("e" * 32)
    orphan.mkdir()
    method = getattr(type(tmp_path), operation)

    def denied(path, *args, **kwargs):
        if path == (tmp_path if operation == "iterdir" else orphan):
            raise PermissionError("controlled metadata failure")
        return method(path, *args, **kwargs)

    monkeypatch.setattr(type(tmp_path), operation, denied)
    job = create(store, png_bytes)
    assert store.get(job.id).job.status == JobStatus.queued


def test_many_queued_uploads_leave_api_threads_available(settings, png_bytes, fake_plan, monkeypatch):
    import anyio
    import httpx

    from app.main import create_app

    app = create_app(settings)
    store = app.state.store
    release = threading.Event()
    started = threading.Event()

    def recognise(*args):
        started.set()
        assert release.wait(15)
        return fake_plan

    monkeypatch.setattr(runner, "_recognise", recognise)
    monkeypatch.setattr(runner, "write_outputs", lambda *args: {})

    async def scenario():
        limiter = anyio.to_thread.current_default_thread_limiter()
        previous = limiter.total_tokens
        limiter.total_tokens = 2
        created = asyncio.Event()
        original = store.create
        ids = []

        def tracked(*args):
            job = original(*args)
            ids.append(job.id)
            if len(ids) == 40:
                created.set()
            return job

        monkeypatch.setattr(store, "create", tracked)
        tasks = []
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                tasks = [asyncio.create_task(client.post(
                    "/api/jobs", files={"file": ("plan.png", png_bytes, "image/png")}
                )) for _ in range(40)]
                await asyncio.wait_for(created.wait(), 10)
                health = await asyncio.wait_for(client.get("/health"), 5)
                status = await asyncio.wait_for(client.get(f"/api/jobs/{ids[-1]}"), 5)
                assert health.status_code == status.status_code == 200
                assert status.json()["status"] == "queued"
                assert limiter.borrowed_tokens == 0
                release.set()
                responses = await asyncio.wait_for(asyncio.gather(*tasks), 15)
                assert all(response.status_code == 202 for response in responses)
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            limiter.total_tokens = previous

    asyncio.run(scenario())
