from __future__ import annotations

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import numpy as np
import pytest

from app.export.ifc import write_ifc
from app.geometry.walls import build_wall_meshes


def _write(plan, tmp_path):
    path = tmp_path / "m.ifc"
    write_ifc(plan, build_wall_meshes(plan), path)
    return ifcopenshell.open(str(path))


def test_every_wall_and_opening_is_its_own_named_object(fake_plan, tmp_path):
    f = _write(fake_plan, tmp_path)
    assert sorted(w.Name for w in f.by_type("IfcWall")) == sorted(f"WALL_{w.id}" for w in fake_plan.walls)
    assert len(f.by_type("IfcDoor")) == sum(o.type.value == "door" for o in fake_plan.openings)
    assert len(f.by_type("IfcWindow")) == sum(o.type.value == "window" for o in fake_plan.openings)
    assert all(ifcopenshell.util.element.get_container(w).Name == "Level 0" for w in f.by_type("IfcWall"))


def test_openings_void_a_wall_and_are_filled(fake_plan, tmp_path):
    f = _write(fake_plan, tmp_path)
    holes = f.by_type("IfcOpeningElement")
    assert holes and len(f.by_type("IfcRelVoidsElement")) == len(holes) == len(f.by_type("IfcRelFillsElement"))
    for rel in f.by_type("IfcRelVoidsElement"):
        assert rel.RelatingBuildingElement.is_a("IfcWall")


def test_wall_volume_matches_the_3d_mesh(fake_plan, tmp_path):
    f = _write(fake_plan, tmp_path)
    meshes = build_wall_meshes(fake_plan)
    settings = ifcopenshell.geom.settings()
    for w in f.by_type("IfcWall"):
        geo = ifcopenshell.geom.create_shape(settings, w).geometry
        v = np.array(geo.verts).reshape(-1, 3)
        t = np.array(geo.faces).reshape(-1, 3)
        vol = np.einsum("ij,ij->", v[t[:, 0]], np.cross(v[t[:, 1]], v[t[:, 2]])) / 6
        # IfcOpenShell geometry is in metres, the mesh in mm
        assert vol * 1e9 == pytest.approx(meshes[w.Name.removeprefix("WALL_")].volume, rel=1e-6)


def test_opening_that_cuts_nothing_gets_no_door(tmp_path):
    from tests.test_geometry import DOOR, _walls_plan

    # the door sits entirely past the wall end, so the 3D wall has no hole and IFC has no door either
    plan = _walls_plan([("w1", (0, 0), (4000, 0), 200)], [{**DOOR, "position": 4500}])
    f = _write(plan, tmp_path)
    assert [w.Name for w in f.by_type("IfcWall")] == ["WALL_w1"]
    assert not f.by_type("IfcDoor") and not f.by_type("IfcOpeningElement")
