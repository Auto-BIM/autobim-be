import pytest

from app.geometry.walls import Piece, build_wall_meshes, wall_pieces
from app.schemas.plan import Plan

T, H = 200.0, 2400.0


def _plan(openings) -> Plan:
    return Plan.model_validate({
        "source": {"type": "image"},
        "scale": {"source": "user", "estimated": False, "mm_per_px": 1},
        "walls": [{"id": "w1", "start": {"x": 0, "y": 0}, "end": {"x": 4000, "y": 0},
                   "thickness": T, "height": H}],
        "openings": openings,
    })


DOOR = {"id": "d", "type": "door", "wall_id": "w1", "position": 1000, "width": 900, "height": 2100}
WINDOW = {"id": "n", "type": "window", "wall_id": "w1", "position": 3000, "width": 1200,
          "height": 1200, "sill_height": 900}


def test_plain_wall_is_one_box():
    plan = _plan([])
    assert wall_pieces(plan.walls[0], []) == [Piece(0, 4000, 0, H)]
    mesh = build_wall_meshes(plan)["w1"]
    assert mesh.volume == pytest.approx(4000 * T * H)
    assert mesh.bounds.tolist() == [[0, -T / 2, 0], [4000, T / 2, H]]


def test_door_leaves_lintel_only():
    plan = _plan([DOOR])
    pieces = wall_pieces(plan.walls[0], plan.openings)
    assert pieces == [Piece(0, 550, 0, H), Piece(550, 1450, 2100, H), Piece(1450, 4000, 0, H)]
    assert build_wall_meshes(plan)["w1"].volume == pytest.approx((4000 * H - 900 * 2100) * T)


def test_window_leaves_sill_and_lintel():
    plan = _plan([WINDOW])
    pieces = wall_pieces(plan.walls[0], plan.openings)
    assert Piece(2400, 3600, 0, 900) in pieces  # sill
    assert Piece(2400, 3600, 2100, H) in pieces  # lintel
    assert build_wall_meshes(plan)["w1"].volume == pytest.approx((4000 * H - 1200 * 1200) * T)


def test_opening_past_wall_end_is_clipped():
    plan = _plan([{**DOOR, "position": 100}])
    pieces = wall_pieces(plan.walls[0], plan.openings)
    assert pieces[0] == Piece(0, 550, 2100, H)


def test_wall_direction_and_normal():
    plan = Plan.model_validate({
        "source": {"type": "image"},
        "scale": {"source": "user", "estimated": False, "mm_per_px": 1},
        "walls": [{"id": "v", "start": {"x": 0, "y": 0}, "end": {"x": 0, "y": 3000},
                   "thickness": 120, "height": H}],
    })
    bounds = build_wall_meshes(plan)["v"].bounds
    assert bounds.ravel().tolist() == pytest.approx([-60, 0, 0, 60, 3000, H])
