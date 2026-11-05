"""Wall meshes -> .glb for the web viewer (glTF: metres, Y-up)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

# Plan (x, y, z-up, mm) -> glTF (x, y-up, z toward viewer, m): (x, z, -y) / 1000
PLAN_TO_GLTF = np.array(
    [
        [0.001, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.001, 0.0],
        [0.0, -0.001, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
)


def write_glb(meshes: dict[str, trimesh.Trimesh], path: Path) -> None:
    scene = trimesh.Scene()
    for wall_id, mesh in meshes.items():
        m = mesh.copy()
        m.apply_transform(PLAN_TO_GLTF)
        scene.add_geometry(m, node_name=wall_id, geom_name=wall_id)
    path.write_bytes(scene.export(file_type="glb"))
