"""Integration: a fixed fake floor plan goes through the API and comes out as glb + .dxf."""

import io

import ezdxf
import pytest
import trimesh


def test_fake_floor_plan_to_glb_and_dxf(client, png_bytes, tmp_path):
    res = client.post("/api/jobs", files={"file": ("plan.png", png_bytes, "image/png")})
    job_id = res.json()["id"]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "succeeded", job["error"]
    plan = job["plan"]
    wall_ids = [w["id"] for w in plan["walls"]]

    # --- glb: one node per wall, metres, Y-up, matching the Plan's extent
    glb = client.get(f"/api/jobs/{job_id}/files/glb").content
    scene = trimesh.load(io.BytesIO(glb), file_type="glb")
    assert sorted(scene.geometry) == sorted(wall_ids)
    (x0, y0, z0), (x1, y1, z1) = scene.bounds
    # exterior centerlines 1000..9000 x 1000..6000 mm, 200 mm thick, 2400 mm tall
    assert (x0, x1) == pytest.approx((0.9, 9.1), abs=1e-4)
    assert (y0, y1) == pytest.approx((0.0, 2.4), abs=1e-4)
    assert (z0, z1) == pytest.approx((-6.1, -0.9), abs=1e-4)

    # --- dxf: mm, one polyface block + INSERT per wall, separate layers
    path = tmp_path / "model.dxf"
    path.write_bytes(client.get(f"/api/jobs/{job_id}/files/dxf").content)
    doc = ezdxf.readfile(path)
    assert doc.header["$INSUNITS"] == 4
    for layer in ("A-WALL", "A-DOOR", "A-WINDOW"):
        assert layer in doc.layers
    inserts = doc.modelspace().query("INSERT")
    walls = [e for e in inserts if e.dxf.layer == "A-WALL"]
    assert sorted(e.dxf.name for e in walls) == sorted(f"WALL_{w}" for w in wall_ids)
    for wid in wall_ids:
        polyfaces = [e for e in doc.blocks[f"WALL_{wid}"] if e.dxftype() == "POLYLINE"]
        assert len(polyfaces) == 1 and polyfaces[0].is_poly_face_mesh
    doors = [e for e in inserts if e.dxf.layer == "A-DOOR"]
    windows = [e for e in inserts if e.dxf.layer == "A-WINDOW"]
    assert (len(doors), len(windows)) == (3, 2)
