"""IFC contract integration tests, Fake model only."""

from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import numpy as np

from app.models.base import WallMask


def upload(client, png_bytes):
    created = client.post("/api/jobs", files={"file": ("synthetic.png", png_bytes, "image/png")})
    assert created.status_code == 202
    job = client.get("/api/jobs/" + created.json()["id"]).json()
    assert job["status"] == "succeeded", job
    return job


def downloaded(client, job):
    response = client.get(job["files"]["ifc"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-step"
    assert job["id"] + ".ifc" in response.headers["content-disposition"]
    model = ifcopenshell.file.from_string(response.content.decode())
    assert model.schema == "IFC4"
    assert {e.Name for e in model.by_type("IfcWall")} == {
        "WALL_" + w["id"] for w in job["plan"]["walls"]
    }
    expected = {o["type"].upper() + "_" + o["id"] for o in job["plan"]["openings"]}
    actual = {e.Name for e in model.by_type("IfcDoor") + model.by_type("IfcWindow")}
    assert actual == expected
    assert len(model.by_type("IfcOpeningElement")) == len(expected)
    return model


def test_ifc_download_and_supplement_regeneration(client, png_bytes):
    job = upload(client, png_bytes)
    assert set(job["files"]) == {"json", "glb", "dxf", "ifc"}
    downloaded(client, job)
    wall_id = job["plan"]["walls"][0]["id"]
    response = client.post(
        "/api/jobs/" + job["id"] + "/supplement", json={"walls": [{"id": wall_id, "height": 2600}]}
    )
    assert response.status_code == 202
    updated = client.get("/api/jobs/" + job["id"]).json()
    assert updated["result_revision"] == 1
    for kind in ("walls", "openings"):
        assert [e["id"] for e in updated["plan"][kind]] == [e["id"] for e in job["plan"][kind]]
    model = downloaded(client, updated)
    element = next(w for w in model.by_type("IfcWall") if w.Name == "WALL_" + wall_id)
    shape = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), element)
    vertices = np.asarray(shape.geometry.verts).reshape(-1, 3) * 1000
    assert abs(vertices[:, 2].max() - 2600) < 0.001
    for kind in ["json", "glb", "dxf"]:
        assert client.get(updated["files"][kind]).status_code == 200


def test_ifc_cascades_removed_wall_and_openings(client, png_bytes):
    job = upload(client, png_bytes)
    wall_id = job["plan"]["openings"][0]["wall_id"]
    response = client.post("/api/jobs/" + job["id"] + "/supplement", json={"remove": [wall_id]})
    assert response.status_code == 202
    updated = client.get("/api/jobs/" + job["id"]).json()
    model = downloaded(client, updated)
    assert "WALL_" + wall_id not in {w.Name for w in model.by_type("IfcWall")}


def test_ifc_unknown_job_and_output_only_upload_contract(client, png_bytes):
    assert client.get("/api/jobs/missing/files/ifc").status_code == 404
    response = client.post(
        "/api/jobs", files={"file": ("input.ifc", b"ISO-10303-21;", "application/x-step")}
    )
    assert response.status_code == 415


def test_missing_ifc_artifact_returns_structured_404(client, png_bytes, settings):
    job = upload(client, png_bytes)
    files = list(Path(settings.storage.data_dir).rglob("model.ifc"))
    assert len(files) == 1
    files[0].unlink()
    response = client.get(job["files"]["ifc"])
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "file_not_found"
    assert client.app.state.store.get(job["id"]).downloads == 0
    assert client.get(job["files"]["glb"]).status_code == 200


def test_failed_job_does_not_offer_ifc_download(client, png_bytes, monkeypatch):
    empty = WallMask(mask=np.zeros((10, 10), dtype=bool))
    monkeypatch.setattr(client.app.state.models.wall_segmenter, "segment", lambda image: empty)
    response = client.post("/api/jobs", files={"file": ("synthetic.png", png_bytes, "image/png")})
    assert response.status_code == 202
    job_url = "/api/jobs/" + response.json()["id"]
    job = client.get(job_url).json()
    assert job["status"] == "failed" and job["files"] == {}
    response = client.get(job_url + "/files/ifc")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_ready"
