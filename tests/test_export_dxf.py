from __future__ import annotations

import ezdxf

from app.export.dxf import wall_block_name, write_dxf
from app.geometry.walls import build_wall_meshes


def test_one_block_per_wall_mm_and_three_layers(fake_plan, tmp_path):
    path = tmp_path / "m.dxf"
    write_dxf(fake_plan, build_wall_meshes(fake_plan), path)
    doc = ezdxf.readfile(path)
    inserts = [e for e in doc.modelspace().query("INSERT") if e.dxf.name.startswith("WALL_")]
    assert {e.dxf.name for e in inserts} == {wall_block_name(w.id) for w in fake_plan.walls}
    assert len(inserts) == len(fake_plan.walls)
    assert {e.dxf.layer for e in inserts} == {"A-WALL"}
    assert doc.header["$INSUNITS"] == 4
    assert {"A-WALL", "A-DOOR", "A-WINDOW"} <= {la.dxf.name for la in doc.layers}
