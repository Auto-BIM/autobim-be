import io

import numpy as np
import trimesh

from app.models.base import WallMask
from app.schemas.jobs import Job, JobStatus


def _create(client, png_bytes, name="plan.png"):
    res = client.post("/api/jobs", files={"file": (name, png_bytes, "image/png")})
    assert res.status_code == 202, res.text
    return res.json()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_and_get_job(client, png_bytes):
    created = _create(client, png_bytes)
    assert created["status"] == "queued" and created["revision"] == 0
    assert created["result_revision"] is None and created["plan"] is None
    # TestClient runs background tasks before returning, so the job is done here.
    job = Job.model_validate(client.get(f"/api/jobs/{created['id']}").json())
    assert job.status == JobStatus.succeeded and job.result_revision == 0
    assert job.plan is not None and len(job.plan.walls) == 5
    assert set(job.files) == {"dxf", "glb", "json"}
    assert job.files["glb"] == f"/api/jobs/{job.id}/files/glb"


def test_download_files(client, png_bytes):
    job_id = _create(client, png_bytes)["id"]
    res = client.get(f"/api/jobs/{job_id}/files/json")
    assert res.status_code == 200 and res.json()["schema_version"] == "1.0"
    res = client.get(f"/api/jobs/{job_id}/files/glb")
    assert res.headers["content-type"] == "model/gltf-binary" and res.content[:4] == b"glTF"
    res = client.get(f"/api/jobs/{job_id}/files/dxf")
    assert res.status_code == 200 and b"SECTION" in res.content


def test_unknown_job_and_file_kind(client, png_bytes):
    res = client.get("/api/jobs/missing")
    assert res.status_code == 404 and res.json()["detail"]["code"] == "job_not_found"
    assert client.get("/api/jobs/missing/files/glb").status_code == 404
    job_id = _create(client, png_bytes)["id"]
    assert client.get(f"/api/jobs/{job_id}/files/obj").status_code == 422


def test_unsupported_upload(client):
    res = client.post("/api/jobs", files={"file": ("notes.txt", b"hi", "text/plain")})
    assert res.status_code == 415 and res.json()["detail"]["code"] == "unsupported_media_type"


def test_first_revision_failure_has_no_plan(client, png_bytes, monkeypatch):
    empty = WallMask(mask=np.zeros((10, 10), dtype=bool))
    monkeypatch.setattr(client.app.state.models.wall_segmenter, "segment", lambda image: empty)
    job = client.get(f"/api/jobs/{_create(client, png_bytes)['id']}").json()
    assert job["status"] == "failed" and job["error"]["code"] == "no_walls"
    assert job["plan"] is None and job["result_revision"] is None and job["files"] == {}
    res = client.get(f"/api/jobs/{job['id']}/files/glb")
    assert res.status_code == 409 and res.json()["detail"]["code"] == "not_ready"
    # nothing to patch: supplements to a job that never produced a plan are refused
    res = client.post(f"/api/jobs/{job['id']}/supplement", json={"resolved": []})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "no_plan"
    assert client.get(f"/api/jobs/{job['id']}").json()["revision"] == 0


def test_supplement_regenerates(client, png_bytes):
    job_id = _create(client, png_bytes)["id"]
    before = client.get(f"/api/jobs/{job_id}").json()
    assert [r["element_id"] for r in before["plan"]["review_items"]] == ["o3"]

    body = {
        "scale": {"building_width_mm": 16000},
        "walls": [{"id": "w4", "thickness": 150}],
        "resolved": ["o3"],
    }
    res = client.post(f"/api/jobs/{job_id}/supplement", json=body)
    assert res.status_code == 202 and res.json()["revision"] == 1

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "succeeded" and job["revision"] == job["result_revision"] == 1
    plan = job["plan"]
    assert plan["scale"]["source"] == "building_width"
    assert {w["id"]: w["thickness"] for w in plan["walls"]}["w4"] == 150
    assert plan["review_items"] == []
    # supplements accumulate: a second one keeps the first's edits
    client.post(f"/api/jobs/{job_id}/supplement", json={"openings": [{"id": "o1", "width": 1000}]})
    plan = client.get(f"/api/jobs/{job_id}").json()["plan"]
    assert plan["scale"]["source"] == "building_width"
    assert {o["id"]: o["width"] for o in plan["openings"]}["o1"] == 1000


def test_supplement_remove_reports_cascaded_openings(client, png_bytes):
    job_id = _create(client, png_bytes)["id"]
    res = client.post(f"/api/jobs/{job_id}/supplement", json={"remove": ["w4"]})
    assert res.status_code == 202
    # the 202 response already says which openings went with the wall
    assert res.json()["removed"] == [
        {"id": "w4", "element_kind": "wall", "revision": 1, "cascade_from": None},
        {"id": "o2", "element_kind": "opening", "revision": 1, "cascade_from": "w4"},
    ]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "succeeded"
    assert "w4" not in [w["id"] for w in job["plan"]["walls"]]
    assert "o2" not in [o["id"] for o in job["plan"]["openings"]]
    glb = client.get(f"/api/jobs/{job_id}/files/glb").content
    scene = trimesh.load(io.BytesIO(glb), file_type="glb")
    assert "w4" not in scene.geometry and len(scene.geometry) == 4

    # removals accumulate across supplements; removed IDs are not reused
    body = {"remove": ["o5"], "add_walls": [{"start": {"x": 5000, "y": 1000}, "end": {"x": 5000, "y": 6000}}]}
    job = client.post(f"/api/jobs/{job_id}/supplement", json=body).json()
    assert [(r["id"], r["revision"]) for r in job["removed"]] == [("w4", 1), ("o2", 1), ("o5", 2)]
    walls = [w["id"] for w in client.get(f"/api/jobs/{job_id}").json()["plan"]["walls"]]
    assert walls == ["w1", "w2", "w3", "w5", "w6"]


def test_supplement_remove_unknown_is_400(client, png_bytes):
    job_id = _create(client, png_bytes)["id"]
    res = client.post(f"/api/jobs/{job_id}/supplement", json={"remove": ["o99"]})
    assert res.status_code == 400 and res.json()["detail"]["code"] == "unknown_element"
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["revision"] == 0 and job["removed"] == []


def test_supplement_rejects_unknown_element(client, png_bytes):
    job_id = _create(client, png_bytes)["id"]
    res = client.post(f"/api/jobs/{job_id}/supplement", json={"walls": [{"id": "w99", "height": 1}]})
    assert res.status_code == 400 and res.json()["detail"]["code"] == "unknown_element"
    assert client.get(f"/api/jobs/{job_id}").json()["revision"] == 0


def test_supplement_does_not_rerun_models(client, png_bytes, monkeypatch):
    job_id = _create(client, png_bytes)["id"]
    before = client.get(f"/api/jobs/{job_id}").json()["plan"]
    models = client.app.state.models

    def boom(image):
        raise AssertionError("models must not run for a supplement")

    monkeypatch.setattr(models.wall_segmenter, "segment", boom)
    monkeypatch.setattr(models.opening_detector, "detect", boom)
    body = {"add_openings": [{"type": "window", "wall_id": "w2", "position": 6000}]}
    client.post(f"/api/jobs/{job_id}/supplement", json=body)
    after = client.get(f"/api/jobs/{job_id}").json()
    assert after["status"] == "succeeded", after["error"]
    assert [w["id"] for w in after["plan"]["walls"]] == [w["id"] for w in before["walls"]]
    assert [o["id"] for o in after["plan"]["openings"]] == [o["id"] for o in before["openings"]] + ["o6"]


def test_last_success_kept_while_regenerating_and_after_failure(client, png_bytes, monkeypatch):
    job_id = _create(client, png_bytes)["id"]
    glb0 = client.get(f"/api/jobs/{job_id}/files/glb").content

    import app.jobs.runner as runner

    def broken(plan, out_dir):
        raise RuntimeError("disk full")

    monkeypatch.setattr(runner, "write_outputs", broken)
    res = client.post(f"/api/jobs/{job_id}/supplement", json={"walls": [{"id": "w1", "height": 3000}]})
    # the 202 body is the queued state: revision 1 requested, revision 0 still shown
    queued = res.json()
    assert queued["status"] == "queued" and queued["revision"] == 1
    assert queued["result_revision"] == 0 and queued["plan"] is not None and queued["files"]

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed" and job["error"]["code"] == "internal_error"
    assert job["revision"] == 1 and job["result_revision"] == 0
    assert {w["id"]: w["height"] for w in job["plan"]["walls"]}["w1"] == 2400
    assert client.get(f"/api/jobs/{job_id}/files/glb").content == glb0


def test_supplement_rejects_busy_job(client, png_bytes):
    job_id = _create(client, png_bytes)["id"]
    store = client.app.state.store
    store.update(job_id, status=JobStatus.running)
    res = client.post(f"/api/jobs/{job_id}/supplement", json={"resolved": ["o3"]})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "job_busy"


def test_supplement_validation_error(client, png_bytes):
    job_id = _create(client, png_bytes)["id"]
    res = client.post(f"/api/jobs/{job_id}/supplement", json={"scale": {}})
    assert res.status_code == 422
