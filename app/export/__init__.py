"""Plan -> output files (glb, dxf, json)."""

from __future__ import annotations

from pathlib import Path

from app.export.dxf import write_dxf
from app.export.glb import write_glb
from app.geometry.junctions import wall_junctions
from app.geometry.walls import build_wall_meshes
from app.schemas.jobs import FileKind
from app.schemas.plan import Plan

FILE_NAMES = {FileKind.json: "plan.json", FileKind.glb: "model.glb", FileKind.dxf: "model.dxf"}


def write_outputs(plan: Plan, out_dir: Path) -> dict[FileKind, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {kind: out_dir / name for kind, name in FILE_NAMES.items()}
    paths[FileKind.json].write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    junctions = wall_junctions(plan.walls)  # one computation for glb and dxf
    meshes = build_wall_meshes(plan, junctions)
    write_glb(meshes, paths[FileKind.glb])
    write_dxf(plan, meshes, paths[FileKind.dxf], junctions)
    return paths
