"""Plan + wall meshes -> .ifc (IFC4): one IfcWall per wall, IfcDoor/IfcWindow per opening.

Unlike DXF, IFC stores objects (name, GUID) in the file itself, so SketchUp / Revit / FreeCAD
import every wall and door as its own object. Each opening is an IfcOpeningElement that voids its
wall and is filled by the door/window; the wall mesh already has the hole cut (same clamping as
the 3D model), so a viewer cutting it again changes nothing.
"""

from __future__ import annotations

from pathlib import Path

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import ifcopenshell.guid
import trimesh

from app.geometry.junctions import wall_junctions
from app.geometry.walls import opening_spans
from app.schemas.plan import OpeningType, Plan

LEAF = 60.0  # door leaf / glass thickness (mm); no frame or handle is modelled
_IFC_CLASS = {OpeningType.door: "IfcDoor", OpeningType.window: "IfcWindow"}
# box corners: bottom 0-3, top 4-7; faces wound outward
_BOX_FACES = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]


def _brep(f, vertices, faces):
    pts = [f.createIfcCartesianPoint(tuple(float(c) for c in v)) for v in vertices]
    return f.createIfcFacetedBrep(f.createIfcClosedShell([
        f.createIfcFace([f.createIfcFaceOuterBound(f.createIfcPolyLoop([pts[i] for i in idx]), True)])
        for idx in faces
    ]))


def _shape(f, el, body, brep):
    el.Representation = f.createIfcProductDefinitionShape(
        None, None, [f.createIfcShapeRepresentation(body, "Body", "Brep", [brep])])
    el.ObjectPlacement = f.createIfcLocalPlacement(
        None, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))))
    return el


def _slab(wall, s0, s1, z0, z1, depth):
    ux = (wall.end.x - wall.start.x) / wall.length
    uy = (wall.end.y - wall.start.y) / wall.length
    h = depth / 2

    def pt(s, side, z):
        return (wall.start.x + ux * s - uy * h * side, wall.start.y + uy * s + ux * h * side, z)

    return [pt(s0, -1, z0), pt(s1, -1, z0), pt(s1, 1, z0), pt(s0, 1, z0),
            pt(s0, -1, z1), pt(s1, -1, z1), pt(s1, 1, z1), pt(s0, 1, z1)]


def write_ifc(plan: Plan, meshes: dict[str, trimesh.Trimesh], path: Path) -> None:
    f = ifcopenshell.file(schema="IFC4")
    project = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="Auto-BIM")
    ifcopenshell.api.unit.assign_unit(f, length={"is_metric": True, "raw": "MILLIMETERS"})
    model = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model)
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding", name="Building")
    storey = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name="Level 0")
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(f, products=[building], relating_object=site)
    ifcopenshell.api.aggregate.assign_object(f, products=[storey], relating_object=building)

    def add(ifc_class, name, brep):
        el = _shape(f, ifcopenshell.api.root.create_entity(f, ifc_class=ifc_class, name=name), body, brep)
        if ifc_class != "IfcOpeningElement":
            ifcopenshell.api.spatial.assign_container(f, products=[el], relating_structure=storey)
        return el

    hosts = {}
    for wall_id, mesh in meshes.items():
        hosts[wall_id] = add("IfcWall", f"WALL_{wall_id}", _brep(f, mesh.vertices, mesh.faces))

    exts, zones = wall_junctions(plan.walls)
    for o in plan.openings:
        wall = plan.wall(o.wall_id)
        spans = opening_spans(wall, o, exts[wall.id], zones[wall.id])
        if wall.id not in hosts or not spans:
            continue  # nothing was cut into the wall, so there is nothing to void or fill
        s0, s1 = spans[0][0], spans[-1][1]
        z0, z1 = o.sill_height, o.sill_height + o.height
        hole = add("IfcOpeningElement", f"HOLE_{o.id}",
                   _brep(f, _slab(wall, s0, s1, z0, z1, wall.thickness), _BOX_FACES))
        f.createIfcRelVoidsElement(ifcopenshell.guid.new(), None, None, None, hosts[wall.id], hole)
        el = add(_IFC_CLASS[o.type], f"{o.type.value.upper()}_{o.id}",
                 _brep(f, _slab(wall, s0, s1, z0, z1, LEAF), _BOX_FACES))
        f.createIfcRelFillsElement(ifcopenshell.guid.new(), None, None, None, hole, el)

    f.write(str(path))
