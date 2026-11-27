"""IFC export regression tests using synthetic Plans and unchanged team meshes."""

from types import SimpleNamespace

import ifcopenshell
import ifcopenshell.geom
import numpy as np
import pytest


@pytest.fixture(scope="module")
def team():
    from app.export.ifc import write_ifc
    from app.geometry.walls import build_wall_meshes
    from app.schemas.plan import Plan

    return SimpleNamespace(Plan=Plan, meshes=build_wall_meshes, write=write_ifc)


def source_plan(team, *, sill=0, height=2100, position=2000, branch=False):
    walls = [
        {
            "id": "w1",
            "start": {"x": 0, "y": 0},
            "end": {"x": 4000, "y": 0},
            "thickness": 200,
            "height": 2400,
        }
    ]
    if branch:
        walls.append(
            {
                "id": "branch",
                "start": {"x": 2000, "y": 0},
                "end": {"x": 2000, "y": 3000},
                "thickness": 120,
                "height": 2400,
            }
        )
    return team.Plan(
        source={"type": "dxf"},
        scale={"source": "source_units", "estimated": False},
        walls=walls,
        openings=[
            {
                "id": "o1",
                "type": "window",
                "wall_id": "w1",
                "position": position,
                "width": 900,
                "height": height,
                "sill_height": sill,
            }
        ],
    )


def write(team, plan, tmp_path):
    before = plan.model_dump_json()
    meshes = team.meshes(plan)
    original = {wid: (m.vertices.copy(), m.faces.copy()) for wid, m in meshes.items()}
    path = tmp_path / "candidate.ifc"
    team.write(plan, meshes, path)
    assert plan.model_dump_json() == before
    for wid, mesh in meshes.items():
        assert np.array_equal(original[wid][0], mesh.vertices)
        assert np.array_equal(original[wid][1], mesh.faces)
    return ifcopenshell.open(str(path)), meshes


def geometry(element):
    shape = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), element)
    vertices = np.asarray(shape.geometry.verts).reshape(-1, 3) * 1000
    faces = np.asarray(shape.geometry.faces).reshape(-1, 3)
    volume = abs(
        np.einsum(
            "ij,ij->",
            vertices[faces[:, 0]],
            np.cross(vertices[faces[:, 1]], vertices[faces[:, 2]]),
        )
        / 6
    )
    return vertices, volume


@pytest.mark.parametrize(
    "sill,height,top", [(900, 2000, 2400), (2400, 1200, None), (0, 2100, 2100)]
)
def test_opening_matches_source_vertical_cut(team, tmp_path, sill, height, top):
    model, _ = write(team, source_plan(team, sill=sill, height=height), tmp_path)
    if top is None:
        assert not model.by_type("IfcWindow")
        assert not model.by_type("IfcOpeningElement")
    else:
        vertices, volume = geometry(model.by_type("IfcWindow")[0])
        assert vertices[:, 2].min() == pytest.approx(sill)
        assert vertices[:, 2].max() == pytest.approx(top)
        assert volume == pytest.approx(900 * 60 * (top - sill), rel=1e-6)


def test_numerical_remnant_does_not_create_degenerate_opening(team, tmp_path):
    model, _ = write(team, source_plan(team, position=4450 - 1e-10), tmp_path)
    assert not model.by_type("IfcWindow")
    assert not model.by_type("IfcOpeningElement")
    assert len(model.by_type("IfcWall")) == 1


def test_protected_junction_matches_unchanged_team_mesh_volume(team, tmp_path):
    model, meshes = write(team, source_plan(team, branch=True), tmp_path)
    assert (
        len(
            model.by_type("IfcOpeningElement")[0]
            .Representation.Representations[0]
            .Items
        )
        == 2
    )
    for element in model.by_type("IfcWall"):
        _, volume = geometry(element)
        assert volume == pytest.approx(
            meshes[element.Name.removeprefix("WALL_")].volume, rel=1e-6
        )


def wall_items(element):
    return element.Representation.Representations[0].Items


def test_walls_are_swept_solids_with_one_profile_per_connected_region(team, tmp_path):
    model, _ = write(team, source_plan(team, sill=900, height=1000), tmp_path)
    wall = model.by_type("IfcWall")[0]
    assert wall.Representation.Representations[0].RepresentationType == "SweptSolid"
    assert [i.is_a() for i in wall_items(wall)] == ["IfcExtrudedAreaSolid"]
    # a window hole inside the wall is one profile with a void, not extra faces on a mesh
    assert wall_items(wall)[0].SweptArea.is_a("IfcArbitraryProfileDefWithVoids")


def test_full_height_gap_keeps_real_pieces_apart(team, tmp_path):
    plan = source_plan(team, sill=0, height=2400)  # a full-height opening splits the wall
    model, meshes = write(team, plan, tmp_path)
    wall = model.by_type("IfcWall")[0]
    assert len(wall_items(wall)) == 2  # two solids; nothing bridges the gap
    _, volume = geometry(wall)
    assert volume == pytest.approx(meshes["w1"].volume, rel=1e-6)


def test_falls_back_to_mesh_when_profile_does_not_match(team, tmp_path):
    plan = source_plan(team)
    meshes = team.meshes(plan)
    path = tmp_path / "fallback.ifc"
    team.write(plan, meshes, path, swept=False)
    wall = ifcopenshell.open(str(path)).by_type("IfcWall")[0]
    assert wall.Representation.Representations[0].RepresentationType == "Brep"
