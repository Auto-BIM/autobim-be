"""Plan -> per-wall solids (mm, Plan axes with z up).

Each wall is a box around its centerline (half thickness each side); door/window
intervals are cut out, leaving the lintel above doors, and the lintel above plus the
sill below windows.
Junctions (L/T/+ extend/trim, design.md §5) come from `junctions.wall_junctions`: a wall's
solid runs from s = -ext_start to s = length + ext_end. Openings are clamped to the original
centerline range (and to trimmed ends) and never cut into a junction's footprint
(`junctions.wall_junctions` zones), so corners and branch roots stay solid.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh

from app.geometry.junctions import unit, wall_junctions
from app.schemas.plan import Opening, Plan, Wall


@dataclass(frozen=True)
class Piece:
    """Solid part of a wall in wall-local coordinates (s along centerline from start, z up)."""

    s0: float
    s1: float
    z0: float
    z1: float


def _subtract(lo: float, hi: float, cuts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out, cursor = [], lo
    for a, b in sorted(cuts):
        a, b = max(a, lo), min(b, hi)
        if b <= a:
            continue
        if a > cursor:
            out.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < hi:
        out.append((cursor, hi))
    return out


def opening_spans(
    wall: Wall,
    opening: Opening,
    ext: tuple[float, float] = (0.0, 0.0),
    zones: list[tuple[float, float]] | None = None,
) -> list[tuple[float, float]]:
    """Wall-local intervals the opening really cuts: its span clamped to the original centerline
    range (and trimmed ends), minus junction zones (where other walls rest on this one).
    An opening lying entirely inside those limits is not cut at all (3D) / not drawn (DXF block
    stays empty): the Plan has no way to flag it."""
    lo, hi = max(0.0, -ext[0]), min(wall.length, wall.length + ext[1])
    a = min(max(opening.position - opening.width / 2, lo), hi)
    b = min(max(opening.position + opening.width / 2, lo), hi)
    return _subtract(a, b, zones or [])


def wall_pieces(
    wall: Wall,
    openings: list[Opening],
    ext: tuple[float, float] = (0.0, 0.0),
    zones: list[tuple[float, float]] | None = None,
) -> list[Piece]:
    length = wall.length
    lo, hi = -ext[0], length + ext[1]  # solid extent
    spans = [(a, b, o) for o in openings for a, b in opening_spans(wall, o, ext, zones)]
    breaks = sorted({lo, hi} | {v for a, b, _ in spans for v in (a, b)})
    pieces = []
    for s0, s1 in zip(breaks, breaks[1:]):
        if s1 - s0 <= 1e-6:
            continue
        mid = (s0 + s1) / 2
        cuts = [(o.sill_height, o.sill_height + o.height) for a, b, o in spans if a < mid < b]
        pieces.extend(Piece(s0, s1, z0, z1) for z0, z1 in _subtract(0.0, wall.height, cuts))
    return pieces


def _piece_mesh(wall: Wall, piece: Piece) -> trimesh.Trimesh:
    start = np.array([wall.start.x, wall.start.y, 0.0])
    u = np.array([*unit(wall), 0.0])
    n = np.array([-u[1], u[0], 0.0])
    z = np.array([0.0, 0.0, 1.0])
    transform = np.eye(4)
    transform[:3, 0], transform[:3, 1], transform[:3, 2] = u, n, z
    transform[:3, 3] = start + u * (piece.s0 + piece.s1) / 2 + z * (piece.z0 + piece.z1) / 2
    extents = (piece.s1 - piece.s0, wall.thickness, piece.z1 - piece.z0)
    return trimesh.creation.box(extents=extents, transform=transform)


def build_wall_meshes(plan: Plan, junctions=None) -> dict[str, trimesh.Trimesh]:
    """Wall ID -> mesh in mm (Plan x/y, z up). Pieces are separate shells within one mesh."""
    meshes = {}
    exts, zones = junctions or wall_junctions(plan.walls)  # callers may share one computation
    for wall in plan.walls:
        openings = [o for o in plan.openings if o.wall_id == wall.id]
        parts = [_piece_mesh(wall, p) for p in wall_pieces(wall, openings, exts[wall.id], zones[wall.id])]
        meshes[wall.id] = trimesh.util.concatenate(parts)
    return meshes
