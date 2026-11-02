"""Plan + wall meshes -> .dxf: one block (polyface mesh) per wall, layers per element type."""

from __future__ import annotations

from pathlib import Path

import ezdxf
import trimesh
from ezdxf.render import MeshBuilder

from app.geometry.junctions import unit, wall_junctions
from app.geometry.walls import opening_spans
from app.schemas.plan import OpeningType, Plan

LAYER_WALL = "A-WALL"
LAYER_DOOR = "A-DOOR"
LAYER_WINDOW = "A-WINDOW"
_OPENING_LAYER = {OpeningType.door: LAYER_DOOR, OpeningType.window: LAYER_WINDOW}


def wall_block_name(wall_id: str) -> str:
    return f"WALL_{wall_id}"


def opening_block_name(opening_id: str, type_: OpeningType) -> str:
    return f"{type_.value.upper()}_{opening_id}"


def write_dxf(plan: Plan, meshes: dict[str, trimesh.Trimesh], path: Path, junctions=None) -> None:
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4  # millimetres
    doc.layers.add(LAYER_WALL, color=7)
    doc.layers.add(LAYER_DOOR, color=3)
    doc.layers.add(LAYER_WINDOW, color=5)
    msp = doc.modelspace()

    # Block geometry is in world coordinates; inserts are at the origin.
    for wall_id, mesh in meshes.items():
        name = wall_block_name(wall_id)
        block = doc.blocks.new(name)
        builder = MeshBuilder()
        builder.add_mesh(vertices=mesh.vertices.tolist(), faces=mesh.faces.tolist())
        builder.render_polyface(block, dxfattribs={"layer": LAYER_WALL})
        msp.add_blockref(name, (0, 0, 0), dxfattribs={"layer": LAYER_WALL})

    # Openings: plan-view footprint (cut width x wall thickness) at the opening's sill height.
    # Same clamping as the 3D cut: inside the wall's solid, outside junction footprints, so a
    # footprint can be split in two or empty (the block is kept so IDs stay stable).
    exts, zones = junctions or wall_junctions(plan.walls)
    for o in plan.openings:
        wall = plan.wall(o.wall_id)
        ux, uy = unit(wall)
        nx, ny = -uy, ux
        ht = wall.thickness / 2
        layer = _OPENING_LAYER[o.type]
        name = opening_block_name(o.id, o.type)
        block = doc.blocks.new(name)
        for s0, s1 in opening_spans(wall, o, exts[wall.id], zones[wall.id]):
            corners = [
                (wall.start.x + ux * s + nx * sb * ht, wall.start.y + uy * s + ny * sb * ht)
                for s, sb in ((s0, -1), (s1, -1), (s1, 1), (s0, 1))
            ]
            block.add_lwpolyline(
                corners, close=True, dxfattribs={"layer": layer, "elevation": o.sill_height}
            )
        msp.add_blockref(name, (0, 0, 0), dxfattribs={"layer": layer})

    doc.saveas(path)
