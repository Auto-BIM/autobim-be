from __future__ import annotations

import ezdxf
import pytest

from app.export.dxf import wall_block_name, wall_layer_name, write_dxf
from app.geometry.walls import build_wall_meshes


def _read(plan, path, **kw):
    write_dxf(plan, build_wall_meshes(plan), path, **kw)
    return ezdxf.readfile(path)


def test_default_has_one_block_per_wall_and_three_layers(fake_plan, tmp_path):
    doc = _read(fake_plan, tmp_path / "m.dxf")
    walls = {w.id for w in fake_plan.walls}
    inserts = [e for e in doc.modelspace().query("INSERT") if e.dxf.name.startswith("WALL_")]
    assert {e.dxf.name for e in inserts} == {wall_block_name(i) for i in walls}
    assert {e.dxf.layer for e in inserts} == {"A-WALL"}
    assert doc.header["$INSUNITS"] == 4
    assert {"A-WALL", "A-DOOR", "A-WINDOW"} <= {la.dxf.name for la in doc.layers}


def test_layer_per_wall_gives_each_wall_its_own_layer(fake_plan, tmp_path):
    doc = _read(fake_plan, tmp_path / "m.dxf", layer_per_wall=True)
    inserts = [e for e in doc.modelspace().query("INSERT") if e.dxf.name.startswith("WALL_")]
    assert len(inserts) == len(fake_plan.walls)
    for e in inserts:
        wall_id = e.dxf.name.removeprefix("WALL_")
        assert e.dxf.layer == wall_layer_name(wall_id)
        assert {x.dxf.layer for x in doc.blocks[e.dxf.name]} == {e.dxf.layer}
        assert e.dxf.layer in doc.layers


@pytest.mark.parametrize("faces_3d, kind", [(False, "POLYLINE"), (True, "3DFACE")])
def test_mesh_entity_kind(fake_plan, tmp_path, faces_3d, kind):
    doc = _read(fake_plan, tmp_path / "m.dxf", faces_3d=faces_3d)
    name = wall_block_name(fake_plan.walls[0].id)
    assert {e.dxftype() for e in doc.blocks[name]} == {kind}
