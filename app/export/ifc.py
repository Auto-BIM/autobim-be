"""IFC4 export from the unchanged team Plan and wall meshes.

Walls use validated swept profiles where possible and connected BREP shells as a
fallback. Opening cuts follow the team junction and height rules. This module is
independent of the download API.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import ifcopenshell.guid
import trimesh

from app.export.ifc_profiles import swept_wall_solids
from app.geometry.junctions import unit, wall_junctions
from app.geometry.walls import opening_spans, wall_pieces
from app.schemas.plan import OpeningType, Plan

LEAF = 60.0  # door leaf / glass thickness (mm); no frame or handle is modelled
_IFC_CLASS = {OpeningType.door: "IfcDoor", OpeningType.window: "IfcWindow"}
# box corners: bottom 0-3, top 4-7; faces wound outward
_BOX_FACES = [
    [0, 3, 2, 1],
    [4, 5, 6, 7],
    [0, 1, 5, 4],
    [1, 2, 6, 5],
    [2, 3, 7, 6],
    [3, 0, 4, 7],
]


def _brep(f, vertices, faces):
    pts = [f.createIfcCartesianPoint(tuple(float(c) for c in v)) for v in vertices]
    return f.createIfcFacetedBrep(
        f.createIfcClosedShell(
            [
                f.createIfcFace(
                    [
                        f.createIfcFaceOuterBound(
                            f.createIfcPolyLoop([pts[i] for i in idx]), True
                        )
                    ]
                )
                for idx in faces
            ]
        )
    )


def _measure(f, solids):
    """Bounds (mm) and volume (mm3) of IFC solids, read back with the geometry kernel."""
    import ifcopenshell.geom
    import numpy as np

    pts, vol = [], 0.0
    for solid in solids:
        shape = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), solid)
        v = np.asarray(shape.verts).reshape(-1, 3) * 1000  # kernel returns metres
        t = np.asarray(shape.faces).reshape(-1, 3)
        pts.append(v)
        vol += abs(float(np.einsum("ij,ij->", v[t[:, 0]], np.cross(v[t[:, 1]], v[t[:, 2]])) / 6))
    allp = np.vstack(pts)
    return allp.min(0), allp.max(0), vol


def _swept_wall(f, wall, mesh, pieces):
    """One extruded solid per connected wall region, or None to fall back to the mesh.

    The region is the exact union of the team's wall pieces, so coplanar faces are not split
    and nothing is bridged. Accepted only if the result matches the team mesh (bounds, volume).
    """
    import numpy as np

    rectangles = [[p.s0, p.s1, p.z0, p.z1] for p in pieces]
    try:
        solids = swept_wall_solids(
            f,
            SimpleNamespace(start=(wall.start.x, wall.start.y), end=(wall.end.x, wall.end.y)),
            rectangles,
            wall.thickness,
        )
        lo, hi, vol = _measure(f, solids)
    except ValueError:
        return None  # point contact between pieces cannot be one manifold profile
    ok = np.allclose([lo, hi], mesh.bounds, atol=1e-6, rtol=0) and np.isclose(
        vol, mesh.volume, atol=1, rtol=1e-6
    )
    return solids if ok else None


def _shape(f, el, body, *breps):
    kind = "SweptSolid" if breps[0].is_a("IfcExtrudedAreaSolid") else "Brep"
    el.Representation = f.createIfcProductDefinitionShape(
        None, None, [f.createIfcShapeRepresentation(body, "Body", kind, list(breps))]
    )
    el.ObjectPlacement = f.createIfcLocalPlacement(
        None, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)))
    )
    return el


def _slab(wall, s0, s1, z0, z1, depth):
    ux, uy = unit(wall)
    h = depth / 2

    def pt(s, side, z):
        return (
            wall.start.x + ux * s - uy * h * side,
            wall.start.y + uy * s + ux * h * side,
            z,
        )

    return [
        pt(s0, -1, z0),
        pt(s1, -1, z0),
        pt(s1, 1, z0),
        pt(s0, 1, z0),
        pt(s0, -1, z1),
        pt(s1, -1, z1),
        pt(s1, 1, z1),
        pt(s0, 1, z1),
    ]


def write_ifc(
    plan: Plan,
    meshes: dict[str, trimesh.Trimesh],
    path: Path,
    junctions=None,
    swept: bool = True,
) -> None:
    f = ifcopenshell.file(schema="IFC4")
    project = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcProject", name="Auto-BIM"
    )
    ifcopenshell.api.unit.assign_unit(
        f, length={"is_metric": True, "raw": "MILLIMETERS"}
    )
    model = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        f,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model,
    )
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcBuilding", name="Building"
    )
    storey = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcBuildingStorey", name="Level 0"
    )
    ifcopenshell.api.aggregate.assign_object(
        f, products=[site], relating_object=project
    )
    ifcopenshell.api.aggregate.assign_object(
        f, products=[building], relating_object=site
    )
    ifcopenshell.api.aggregate.assign_object(
        f, products=[storey], relating_object=building
    )

    def add(ifc_class, name, *breps):
        el = _shape(
            f,
            ifcopenshell.api.root.create_entity(f, ifc_class=ifc_class, name=name),
            body,
            *breps,
        )
        if ifc_class != "IfcOpeningElement":
            ifcopenshell.api.spatial.assign_container(
                f, products=[el], relating_structure=storey
            )
        return el

    hosts = {}
    exts, zones = junctions or wall_junctions(plan.walls)
    for wall_id, mesh in meshes.items():
        # The 3D mesh concatenates separate closed pieces around openings.
        # Each piece needs its own ClosedShell/Brep; putting disconnected faces
        # into one ClosedShell can lose geometry in other IFC importers.
        wall = plan.wall(wall_id)
        pieces = wall_pieces(
            wall,
            [o for o in plan.openings if o.wall_id == wall_id],
            exts[wall_id],
            zones[wall_id],
        )
        breps = _swept_wall(f, wall, mesh, pieces) if swept else None
        if breps is None:
            breps = [
                _brep(f, part.vertices, part.faces)
                for part in mesh.split(only_watertight=False)
            ]
        hosts[wall_id] = add("IfcWall", f"WALL_{wall_id}", *breps)

    for o in plan.openings:
        wall = plan.wall(o.wall_id)
        # The team wall builder ignores intervals <= 1e-6 mm as numerical remnants.
        spans = [
            (a, b)
            for a, b in opening_spans(wall, o, exts[wall.id], zones[wall.id])
            if b - a > 1e-6
        ]
        if wall.id not in hosts or not spans:
            continue  # nothing was cut into the wall, so there is nothing to void or fill
        # Match the team's existing wall cut; never change the source Plan or mesh.
        z0, z1 = max(0.0, o.sill_height), min(wall.height, o.sill_height + o.height)
        if z1 - z0 <= 1e-6:
            continue
        # A junction may split an opening into several intervals. Never bridge
        # the protected root: IFC importers apply the void to the wall again.
        hole = add(
            "IfcOpeningElement",
            f"HOLE_{o.id}",
            *[
                _brep(f, _slab(wall, s0, s1, z0, z1, wall.thickness), _BOX_FACES)
                for s0, s1 in spans
            ],
        )
        f.createIfcRelVoidsElement(
            ifcopenshell.guid.new(), None, None, None, hosts[wall.id], hole
        )
        el = add(
            _IFC_CLASS[o.type],
            f"{o.type.value.upper()}_{o.id}",
            *[
                _brep(f, _slab(wall, s0, s1, z0, z1, LEAF), _BOX_FACES)
                for s0, s1 in spans
            ],
        )
        f.createIfcRelFillsElement(ifcopenshell.guid.new(), None, None, None, hole, el)

    f.write(str(path))
