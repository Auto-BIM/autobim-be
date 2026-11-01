import itertools
import math

import numpy as np
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


# ---- junctions (issue #2) ----

def _walls_plan(walls, openings=()):
    return Plan.model_validate({
        "source": {"type": "image"},
        "scale": {"source": "user", "estimated": False, "mm_per_px": 1},
        "walls": [{"id": i, "start": {"x": a[0], "y": a[1]}, "end": {"x": b[0], "y": b[1]},
                   "thickness": t, "height": H} for i, a, b, t in walls],
        "openings": list(openings),
    })


def _inside(mesh, pts, chunk=3000):
    """Point containment by ray-crossing parity (trimesh.contains needs rtree). Coincident faces
    of touching pieces cancel out, so only the closed outline of the mesh matters."""
    tri = mesh.triangles
    v0, e1, e2 = tri[:, 0], tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    ray = np.array([0.2718, 0.4143, 0.8688])
    h = np.cross(ray, e2)
    det = (e1 * h).sum(-1)
    ok = np.abs(det) > 1e-12
    f = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    out = np.zeros(len(pts), dtype=bool)
    for k in range(0, len(pts), chunk):
        s_ = pts[k:k + chunk, None, :] - v0[None]
        u = f * (s_ * h).sum(-1)
        q = np.cross(s_, e1[None])
        v = f * (q * ray).sum(-1)
        t = f * (q * e2[None]).sum(-1)
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-9)
        out[k:k + chunk] = hit.sum(-1) % 2 == 1
    return out


def _counts(meshes, region, step=5.0):
    """(grid points, number of wall meshes containing each) over region (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = region
    pts = np.array([[x, y, H / 2] for x in np.arange(x0 + 0.5, x1, step)
                    for y in np.arange(y0 + 0.5, y1, step)])
    return pts, sum(_inside(m, pts).astype(int) for m in meshes.values())


@pytest.mark.parametrize("t1, t2", [(200, 200), (200, 120), (120, 200)])
def test_l_junction_fills_corner_without_overlap(t1, t2):
    plan = _walls_plan([("w1", (0, 0), (4000, 0), t1), ("w2", (0, 0), (0, 3000), t2)])
    meshes = build_wall_meshes(plan)
    expected = (4000 + t2 / 2) * t1 + t2 * (3000 - t1 / 2)
    assert sum(m.volume for m in meshes.values()) == pytest.approx(expected * H)
    assert all(m.is_watertight for m in meshes.values())
    # outer corner square is filled; the whole L footprint is covered exactly once
    corner = np.array([[-t2 / 2 + 1, -t1 / 2 + 1, H / 2], [t2 / 2 - 1, t1 / 2 - 1, H / 2]])
    assert sum(_inside(m, corner).astype(int) for m in meshes.values()).tolist() == [1, 1]
    _, counts = _counts(meshes, (-t2 / 2, -t1 / 2, 4000, t1 / 2))
    assert (counts == 1).all()


def test_t_junction_branch_stops_at_trunk_face():
    plan = _walls_plan([("w1", (0, 0), (4000, 0), 200), ("w2", (2000, 0), (2000, 3000), 120)])
    meshes = build_wall_meshes(plan)
    assert meshes["w1"].bounds.tolist() == [[0, -100, 0], [4000, 100, H]]
    assert meshes["w2"].bounds.tolist() == [[1940, 100, 0], [2060, 3000, H]]
    assert sum(m.volume for m in meshes.values()) == pytest.approx(
        (4000 * 200 + 120 * 2900) * H)


def test_cross_junction_two_branches_on_one_trunk():
    plan = _walls_plan([("w1", (0, 0), (4000, 0), 200), ("w2", (2000, 0), (2000, 3000), 120),
                        ("w3", (2000, 0), (2000, -3000), 120)])
    meshes = build_wall_meshes(plan)
    assert sum(m.volume for m in meshes.values()) == pytest.approx(
        (4000 * 200 + 2 * 120 * 2900) * H)


def test_four_ends_at_one_point_fill_node_once():
    plan = _walls_plan([("w1", (0, 0), (3000, 0), 200), ("w2", (0, 0), (0, 3000), 200),
                        ("w3", (0, 0), (-3000, 0), 200), ("w4", (0, 0), (0, -3000), 200)])
    meshes = build_wall_meshes(plan)
    _, counts = _counts(meshes, (-100, -100, 100, 100))
    assert (counts == 1).all()
    assert sum(m.volume for m in meshes.values()) == pytest.approx(
        (6000 * 200 + 2 * 200 * 2900) * H)


def test_oblique_junction_does_not_overlap():
    plan = _walls_plan([("w1", (0, 0), (4000, 0), 200), ("w2", (2000, 0), (3500, 2000), 120)])
    meshes = build_wall_meshes(plan)
    _, counts = _counts(meshes, (1500, -100, 4000, 700))
    assert counts.max() == 1


def test_junction_is_deterministic_and_order_independent():
    walls = [("w1", (0, 0), (4000, 0), 200), ("w2", (0, 0), (0, 3000), 120),
             ("w10", (4000, 0), (4000, 3000), 200)]
    a = build_wall_meshes(_walls_plan(walls))
    b = build_wall_meshes(_walls_plan(walls[::-1]))
    for wid in a:
        assert np.array_equal(a[wid].vertices, b[wid].vertices)


def test_openings_keep_volume_with_junctions():
    plan = _walls_plan(
        [("w1", (0, 0), (4000, 0), 200), ("w2", (0, 0), (0, 3000), 200)],
        [{**DOOR, "id": "d1", "position": 1000}, {**WINDOW, "id": "n1", "position": 3000}],
    )
    meshes = build_wall_meshes(plan)
    assert meshes["w1"].volume == pytest.approx(
        (4100 * H - 900 * 2100 - 1200 * 1200) * 200)


def test_overlapping_openings_cut_their_union():
    plan = _plan([DOOR, {**DOOR, "id": "d2", "position": 1500}])  # 550..1450 and 1050..1950
    assert build_wall_meshes(plan)["w1"].volume == pytest.approx(
        (4000 * H - 1400 * 2100) * T)



# ---- junction review fixes: shallow angles, skewed corners, ID independence ----

@pytest.mark.parametrize("deg", [2.0, 3.0, 3.6, 4.0, 6.0, 10.0])
def test_nearly_straight_l_is_trimmed_a_little_and_never_overlaps(deg):
    a = np.radians(deg)
    end = (-4000 * np.cos(a), -4000 * np.sin(a))  # continues w1 backwards, bent by `deg`
    plan = _walls_plan([("w1", (0, 0), (4000, 0), 200), ("w2", (0, 0), end, 200)])
    meshes = build_wall_meshes(plan)
    assert meshes["w2"].bounds[0][0] < -3800  # not cut by metres
    _, counts = _counts(meshes, (-1500, -400, 1500, 200), step=5.0)
    assert counts.max() == 1
    _, near = _counts(meshes, (-300, -300, 300, 300), step=2.0)  # 1-2 mm deep overlaps live here
    assert near.max() == 1


@pytest.mark.parametrize("deg", [179.0, 179.43, 179.5, 179.9])
def test_butt_joint_of_almost_straight_walls_of_different_thickness_does_not_overlap(deg):
    a = np.radians(deg)
    plan = _walls_plan([("a", (0, 0), (3000, 0), 250),
                        ("b", (0, 0), (3000 * np.cos(a), 3000 * np.sin(a)), 200)])
    meshes = build_wall_meshes(plan)
    _, counts = _counts(meshes, (-30, -130, 30, 130), step=0.5)
    assert counts.max() == 1


def test_branch_nearly_along_trunk_keeps_the_part_beyond_the_trunk_end():
    plan = _walls_plan([("w1", (0, 0), (4000, 0), 200), ("w2", (2000, 0), (5000, 190), 200)])
    meshes = build_wall_meshes(plan)
    pts, counts = _counts(meshes, (0, -150, 5200, 400), step=5.0)
    assert counts.max() == 1
    # w2's centerline is y = (x - 2000) * 190 / 3000; every sample beyond the trunk end is solid
    y = (pts[:, 0] - 2000) * 190 / 3000
    beyond = (pts[:, 0] > 4150) & (pts[:, 0] < 4950) & (abs(pts[:, 1] - y) < 90)
    assert (counts[beyond] == 1).all()


@pytest.mark.parametrize("deg, node_x", [(2.9, 3500), (10.0, 3700), (30.0, 3700)])
def test_shallow_branch_near_trunk_end_loses_only_the_overlapping_part(deg, node_x):
    a = np.radians(deg)
    plan = _walls_plan([("w1", (0, 0), (4000, 0), 200),
                        ("w2", (node_x, 0), (node_x + 4000 * np.cos(a), 4000 * np.sin(a)), 200)])
    meshes = build_wall_meshes(plan)
    _, counts = _counts(meshes, (3000, -150, 5500, 700), step=5.0)
    assert counts.max() == 1
    assert meshes["w2"].bounds[1][0] - meshes["w2"].bounds[0][0] > 3000  # not cut by metres


def test_acute_l_with_short_master_keeps_the_long_wall():
    a = np.radians(10)
    plan = _walls_plan([("w1", (0, 0), (400, 0), 200),
                        ("w2", (0, 0), (3000 * np.cos(a), 3000 * np.sin(a)), 120)])
    meshes = build_wall_meshes(plan)
    assert meshes["w2"].bounds[1][0] > 2800
    _, counts = _counts(meshes, (-200, -150, 1500, 500), step=5.0)
    assert counts.max() == 1


def _star(degs, t=200, length=3000):
    return [(f"w{k + 1}", (0, 0), (length * np.cos(np.radians(d)), length * np.sin(np.radians(d))), t)
            for k, d in enumerate(degs)]


@pytest.mark.parametrize("skew", [0.0, 1.5, 3.0, 8.0])
def test_skewed_l_outer_corner_is_filled(skew):
    x = -3000 * np.tan(np.radians(skew))
    plan = _walls_plan([("w1", (0, 0), (4000, 0), 200), ("w2", (0, 0), (x, 3000), 200)])
    meshes = build_wall_meshes(plan)
    pts, counts = _counts(meshes, (-150, -150, 150, 150), step=5.0)
    outer = (pts[:, 0] < -5) & (pts[:, 0] > -80) & (pts[:, 1] < -5) & (pts[:, 1] > -95)
    assert (counts[outer] >= 1).all()
    assert counts.max() == 1


@pytest.mark.parametrize("thick", [(120, 200, 200), (200, 120, 200), (200, 200, 120)])
def test_union_does_not_depend_on_wall_ids(thick):
    """Walls +x, -x and +y meet at the origin; relabelling them must not change the union."""
    def union(ids):
        plan = _walls_plan([(ids[0], (0, 0), (3000, 0), thick[0]),
                            (ids[1], (0, 0), (-3000, 0), thick[1]),
                            (ids[2], (0, 0), (0, 3000), thick[2])])
        return _counts(build_wall_meshes(plan), (-400, -150, 400, 400))

    pts, first = union(("w1", "w2", "w3"))
    assert first.max() == 1
    for ids in [("w3", "w2", "w1"), ("w2", "w3", "w1"), ("a", "b", "c")]:
        assert np.array_equal(first > 0, union(ids)[1] > 0)
    # the node square is solid: no groove next to the thin wall
    node = (abs(pts[:, 0]) < 95) & (pts[:, 1] > -min(thick[:2]) / 2 + 5) & (pts[:, 1] < 95)
    assert (first[node] == 1).all()


def test_thick_branch_on_thin_trunk():
    plan = _walls_plan([("w1", (0, 0), (4000, 0), 120), ("w2", (2000, 0), (2000, 3000), 200)])
    meshes = build_wall_meshes(plan)
    assert meshes["w2"].bounds.tolist() == [[1900, 60, 0], [2100, 3000, H]]
    assert sum(m.volume for m in meshes.values()) == pytest.approx(
        (4000 * 120 + 200 * 2940) * H)


# ---- openings at junctions (3D and DXF share the same clamping) ----

def test_door_at_a_corner_does_not_cut_the_partner_wall_face():
    plan = _walls_plan(
        [("w1", (0, 0), (4000, 0), 200), ("w2", (0, 0), (0, 3000), 200)],
        [{**DOOR, "position": 100}],  # span -350..550; w2's face is at s = 100
    )
    m = build_wall_meshes(plan)["w1"]
    solid = _inside(m, np.array([[50.0, 0.0, 1000.0], [50.0, 90.0, 1000.0], [-50.0, 0.0, 1000.0]]))
    assert solid.all()
    assert not _inside(m, np.array([[300.0, 0.0, 1000.0]])).any()  # the door itself
    assert m.is_watertight


def test_door_on_trunk_leaves_the_branch_root_supported():
    plan = _walls_plan(
        [("w1", (0, 0), (4000, 0), 200), ("w2", (2000, 0), (2000, 3000), 120)],
        [{**DOOR, "position": 2000}],  # 1550..2450 covers the branch footprint 1940..2060
    )
    m = build_wall_meshes(plan)["w1"]
    assert _inside(m, np.array([[2000.0, 0.0, 1000.0], [2050.0, 90.0, 1000.0]])).all()
    assert not _inside(m, np.array([[1700.0, 0.0, 1000.0], [2300.0, 0.0, 1000.0]])).any()
    assert m.volume == pytest.approx((4000 * H - (1940 - 1550 + 2450 - 2060) * 2100) * 200)


def test_dxf_opening_footprints_follow_the_3d_cut(tmp_path):
    import ezdxf

    from app.export.dxf import write_dxf

    plan = _walls_plan(
        [("w1", (0, 0), (4000, 0), 200), ("w2", (0, 0), (0, 3000), 200),
         ("w3", (2000, 0), (2000, -1500), 120)],
        [{**DOOR, "id": "d1", "position": 100},        # past the corner
         {**DOOR, "id": "d2", "position": 2000},       # over the branch root
         {**WINDOW, "id": "n1", "position": 3900}],    # past the far end
    )
    path = tmp_path / "m.dxf"
    write_dxf(plan, build_wall_meshes(plan), path)
    doc = ezdxf.readfile(path)

    def xs(name):
        return sorted(round(p[0]) for e in doc.blocks[name] for p in e.get_points("xy"))

    assert xs("DOOR_d1") == [100, 100, 550, 550]
    assert xs("DOOR_d2") == [1550, 1550, 1940, 1940, 2060, 2060, 2450, 2450]
    assert xs("WINDOW_n1") == [3300, 3300, 4000, 4000]
    assert len([e for e in doc.modelspace().query("INSERT") if e.dxf.name.startswith("WALL_")]) == 3


@pytest.mark.parametrize("deg", [45, 60, 75, 135])
@pytest.mark.parametrize("branch_t", [120, 200])
def test_door_on_trunk_keeps_an_oblique_branch_root_supported(deg, branch_t):
    r = np.radians(deg)
    plan = _walls_plan(
        [("t", (0, 0), (4000, 0), 200),
         ("b", (2000, 0), (2000 + 3000 * np.cos(r), 3000 * np.sin(r)), branch_t)],
        [{**DOOR, "wall_id": "t", "position": 2000}],  # cut 1550..2450 over the junction
    )
    meshes = build_wall_meshes(plan)
    # independent expectation: the branch's end face, read off its own mesh (lowest points along
    # its direction), rests on the trunk face; the trunk must stay solid between those corners
    d = np.array([np.cos(r), np.sin(r)])
    v = np.unique(meshes["b"].vertices[:, :2].round(6), axis=0)
    end = v[v @ d <= (v @ d).min() + 1e-6]
    x0, x1 = end[:, 0].min(), end[:, 0].max()
    xs = np.linspace(x0, x1, 7)[1:-1] if x1 - x0 > 1 else [x0]
    pts = np.array([[x, 0.0, 1000.0] for x in xs])
    assert _inside(meshes["t"], pts).all()
    # everything else inside the door span is cut: the trunk volume is independent of the zone
    protected = max(0.0, min(x1, 2450.0) - max(x0, 1550.0))
    assert meshes["t"].volume == pytest.approx((4000 * H - (900 - protected) * 2100) * 200)


def _quad(mesh):
    """Footprint corners of a plain box wall mesh (4 distinct xy points)."""
    return np.unique(mesh.vertices[:, :2].round(6), axis=0)


def _gap(m1, m2):
    """Distance between two disjoint box footprints: closest corner-to-edge, both ways."""
    def corner_to_edges(p, q):
        c = q.mean(0)
        q = q[np.argsort(np.arctan2(q[:, 1] - c[1], q[:, 0] - c[0]))]  # corners in order
        best = np.inf
        for a, b in zip(q, np.roll(q, -1, axis=0)):
            t = np.clip(((p - a) @ (b - a)) / ((b - a) @ (b - a)), 0, 1)
            best = min(best, np.linalg.norm(p - (a + t * (b - a))))
        return best
    a, b = _quad(m1), _quad(m2)
    return min([corner_to_edges(p, b) for p in a] + [corner_to_edges(p, a) for p in b])


@pytest.mark.parametrize("deg", [95, 120, 150])
@pytest.mark.parametrize("thick", [(200, 200), (200, 120), (120, 200)])
def test_obtuse_l_walls_touch_each_other(deg, thick):
    r = np.radians(deg)
    plan = _walls_plan([("m", (0, 0), (4000, 0), thick[0]),
                        ("o", (0, 0), (3000 * np.cos(r), 3000 * np.sin(r)), thick[1])])
    meshes = build_wall_meshes(plan)
    assert _gap(meshes["m"], meshes["o"]) <= 1.0


def test_y_junction_arms_touch_the_first_arm():
    plan = _walls_plan(_star((0, 120, 240)))
    meshes = build_wall_meshes(plan)
    assert _gap(meshes["w1"], meshes["w2"]) <= 1.0 and _gap(meshes["w1"], meshes["w3"]) <= 1.0


def test_branch_resting_on_a_non_master_wall_stays_supported_under_a_door():
    # w1 (0 deg) is the master; w3 (140 deg) ends on w2 (100 deg), which has a door at its root
    plan = _walls_plan(_star((0, 100, 140)),
                       [{**DOOR, "wall_id": "w2", "position": 350, "width": 700}])
    meshes = build_wall_meshes(plan)
    d2 = np.array([np.cos(np.radians(100)), np.sin(np.radians(100))])
    d3 = np.array([np.cos(np.radians(140)), np.sin(np.radians(140))])
    v = _quad(meshes["w3"])
    end = v[v @ d3 <= (v @ d3).min() + 1e-6]  # w3's end face, the corners nearest the node
    s_contact = max(end @ d2)  # the corner lying against w2's face (largest along w2)
    assert s_contact > 100 and s_contact < 700  # inside the door span
    assert _inside(meshes["w2"], np.array([[*(d2 * (s_contact - 1)), 1000.0]])).all()
    assert not _inside(meshes["w2"], np.array([[*(d2 * 600), 1000.0]])).any() or s_contact > 600


def test_walls_folded_onto_each_other_do_not_overlap():
    a, b = np.radians(120.0), np.radians(119.43)
    plan = _walls_plan([("w1", (0, 0), (3000 * np.cos(a), 3000 * np.sin(a)), 250),
                        ("w3", (0, 0), (3000 * np.cos(b), 3000 * np.sin(b)), 200)])
    meshes = build_wall_meshes(plan)
    _, counts = _counts(meshes, (-1700, -100, 100, 2700), step=10.0)
    # the folded wall lies inside the other one: only a MIN_LEN sliver (~200 mm²) is left of it
    assert (counts > 1).sum() * 10.0**2 <= 1000  # was ~200,000 mm²
    assert meshes["w3"].volume < 3 * 200 * H


def test_acute_corner_extension_is_capped_and_folded_walls_do_not_extend_the_master():
    from app.geometry.junctions import wall_junctions

    a = np.radians(10)  # acute: the exact corner would be > 1 m away
    acute = _walls_plan([("m", (0, 0), (4000, 0), 200),
                         ("o", (0, 0), (3000 * np.cos(a), 3000 * np.sin(a)), 200)])
    assert wall_junctions(acute.walls)[0]["m"][0] <= 3 * 200
    b = np.radians(0.3)  # folded back onto the master
    folded = _walls_plan([("m", (0, 0), (4000, 0), 200),
                          ("o", (0, 0), (3000 * np.cos(b), 3000 * np.sin(b)), 200)])
    assert wall_junctions(folded.walls)[0]["m"] == (0.0, 0.0)


# ---- seeded random properties: the invariants reviewers kept finding by hand ----

def _foot(w, e):
    """Corners (ccw) of a wall's solid footprint, ext e = (start, end) extension."""
    ux, uy = (w.end.x - w.start.x) / w.length, (w.end.y - w.start.y) / w.length
    h = w.thickness / 2
    return np.array([(w.start.x + ux * s - uy * q, w.start.y + uy * s + ux * q)
                     for s, q in ((-e[0], -h), (w.length + e[1], -h), (w.length + e[1], h), (-e[0], h))])


def _overlap_area(a, b):
    poly = [tuple(p) for p in a]
    for i in range(4):  # clip against each edge of convex b
        p, q = b[i], b[(i + 1) % 4]
        side = lambda x: (q[0] - p[0]) * (x[1] - p[1]) - (q[1] - p[1]) * (x[0] - p[0])  # noqa: E731
        out = []
        for u, v in zip(poly[-1:] + poly[:-1], poly):
            if side(v) >= 0:
                if side(u) < 0:
                    out.append(tuple(np.add(u, np.subtract(v, u) * side(u) / (side(u) - side(v)))))
                out.append(v)
            elif side(u) >= 0:
                out.append(tuple(np.add(u, np.subtract(v, u) * side(u) / (side(u) - side(v)))))
        poly = out
        if not poly:
            return 0.0
    x, y = np.array(poly).T
    return abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2


def _pt_dist(p, w, e):
    """Distance from a point to a wall's solid footprint."""
    ux, uy = (w.end.x - w.start.x) / w.length, (w.end.y - w.start.y) / w.length
    dx, dy = p[0] - w.start.x, p[1] - w.start.y
    s, q = dx * ux + dy * uy, -dx * uy + dy * ux
    return np.hypot(max(0.0, -e[0] - s, s - w.length - e[1]), max(0.0, abs(q) - w.thickness / 2))


def _on_center(p, w):
    ux, uy = (w.end.x - w.start.x) / w.length, (w.end.y - w.start.y) / w.length
    dx, dy = p[0] - w.start.x, p[1] - w.start.y
    return abs(-dx * uy + dy * ux) <= 1.0 and -1.0 <= dx * ux + dy * uy <= w.length + 1.0


def _quad_gap(a, wa, ea, b, wb, eb):
    if _overlap_area(a, b) > 1e-6:
        return 0.0
    return min([_pt_dist(p, wb, eb) for p in a] + [_pt_dist(p, wa, ea) for p in b])


def _random_plan(rng):
    T = [100, 120, 150, 200, 250]
    walls, k = [], 0

    def add(a, b, t):
        nonlocal k
        k += 1
        walls.append((f"w{k}", a, b, t))

    def ray(deg, length):
        return (length * np.cos(np.radians(deg)), length * np.sin(np.radians(deg)))

    def spread(n, lo=0.0, hi=360.0, sep=8.0):
        while True:
            d = sorted(rng.uniform(lo, hi) for _ in range(n))
            if all(b - a >= sep for a, b in zip(d, d[1:])) and (hi - lo < 360 or d[0] + 360 - d[-1] >= sep):
                return d

    kind = rng.choice(["node", "node", "tee", "room", "cornertee", "tt"])
    if kind == "node":
        for d in spread(rng.randint(2, 5)):  # short stubs too, also between acute neighbours
            add((0, 0), ray(d, rng.choice([300, 600, 1500, 3000])), rng.choice(T))
    elif kind == "cornertee":  # an L corner with a branch resting on one arm close to the corner
        add((0, 0), (4000, 0), rng.choice(T))
        a = rng.uniform(60, 140)
        add((0, 0), ray(a, 3000), rng.choice(T))
        dx, dy = ray(rng.uniform(30, a - 12), 3000)  # diverges from the arm: no crossing
        x = rng.choice([400, 600])
        add((x, 0), (x + dx, dy), rng.choice(T))
    elif kind == "tt":  # a branch on a trunk whose end itself rests on another wall
        add((4000, -2000), (4000, 2000), rng.choice(T))
        add((0, 0), (4000, 0), rng.choice(T))
        x = 4000 - rng.choice([300, 450, 600])
        dx, dy = ray(rng.uniform(95, 175) * rng.choice([1, -1]), rng.choice([1500, 3000]))
        add((x, 0), (x + dx, dy), rng.choice(T))
    elif kind == "tee":
        add((0, 0), (4000, 0), rng.choice(T))
        x = rng.choice([30, 50, 100, 2000, 3900, 3970])
        for d in spread(rng.randint(1, 3), 5, 175):
            dx, dy = ray(d, rng.choice([1500, 3000]))
            add((x, 0), (x + dx, dy), rng.choice(T))
    else:
        w, h, te = rng.choice([3000, 6000]), rng.choice([2500, 5000]), rng.choice([150, 200, 250])
        for a, b in [((0, 0), (w, 0)), ((w, 0), (w, h)), ((w, h), (0, h)), ((0, h), (0, 0))]:
            add(a, b, te)
        xs = sorted(rng.sample([300, w / 3, w / 2, 2 * w / 3, w - 300], rng.randint(0, 2)))
        for n, x in enumerate(xs):  # partitions must not cross each other or touch the far wall
            room = (xs[n + 1] if n + 1 < len(xs) else w) - 600 - x
            add((x, 0), (x + (900 if room >= 900 and rng.random() < 0.5 else 0), h),
                rng.choice([100, 120, 150]))
    ops = []
    for wid, a, b, t in walls:
        length = float(np.hypot(b[0] - a[0], b[1] - a[1]))
        for _ in range(rng.randint(0, 3)):
            typ = rng.choice(["door", "window"])
            ops.append({"id": f"o{len(ops)}", "type": typ, "wall_id": wid,
                        "position": rng.uniform(-150, length + 150), "width": rng.uniform(600, 1600),
                        "height": 2100 if typ == "door" else 1200,
                        "sill_height": 0 if typ == "door" else 900})
    return _walls_plan(walls, ops)


def _check_plan(plan):
    """Return a list of violated invariants (empty = fine)."""
    from app.geometry.junctions import wall_junctions
    from app.geometry.walls import opening_spans

    bad = []
    ext, zones = wall_junctions(plan.walls)
    W = {w.id: w for w in plan.walls}
    foot = {i: _foot(W[i], ext[i]) for i in W}
    for i, w in W.items():
        if w.length + sum(ext[i]) < min(1.0, w.length) - 1e-6:
            bad.append(f"{i}: length lost")
    for i, j in itertools.combinations(W, 2):  # no overlap beyond a MIN_LEN sliver
        if _overlap_area(foot[i], foot[j]) > 600:
            bad.append(f"{i}/{j}: overlap {_overlap_area(foot[i], foot[j]):.0f} mm2")
    # nodes: walls ending within 1 mm of each other plus walls running through that point
    ends = []  # (wall, end point, direction pointing into the wall)
    for w in plan.walls:
        for p, q in (((w.start.x, w.start.y), (w.end.x, w.end.y)), ((w.end.x, w.end.y), (w.start.x, w.start.y))):
            ends.append((w.id, p, math.atan2(q[1] - p[1], q[0] - p[0])))
    for _, p, _ in ends:
        mem = [(i, a) for i, q, a in ends if math.dist(p, q) <= 1.0]
        members = {i for i, _ in mem}
        group = members | {i for i, w in W.items() if _on_center(p, w)}
        group = {i for i in group if W[i].length + sum(ext[i]) > 1.0 + 1e-6}  # swallowed stubs vanish
        if not group:
            continue
        # connected: walls of one node touch each other (a hole between two arms is fine)
        seen, todo = set(), [min(group)]
        while todo:
            a = todo.pop()
            seen.add(a)
            todo += [b for b in group - seen if _quad_gap(foot[a], W[a], ext[a], foot[b], W[b], ext[b]) <= 1.0]
        if seen != group:
            bad.append(f"node {p}: {sorted(group - seen)} touch nothing")
        if group == members and len(mem) >= 3:  # mitre hole between neighbouring arms is bounded
            mem.sort(key=lambda m: m[1])
            turns = [(b - a) % (2 * np.pi) for (_, a), (_, b) in zip(mem, mem[1:] + mem[:1])]
            cap = max(W[i].thickness for i in members) / np.sin(min(turns) / 2) + 1
            for (a, _), (b, _) in zip(mem, mem[1:] + mem[:1]):
                if _quad_gap(foot[a], W[a], ext[a], foot[b], W[b], ext[b]) > cap:
                    bad.append(f"node {p}: hole between {a} and {b} exceeds {cap:.0f} mm")
    # zones only where a wall end really rests, and every contact point stays solid
    for i, w in W.items():
        ux, uy = (w.end.x - w.start.x) / w.length, (w.end.y - w.start.y) / w.length
        cuts = [c for o in plan.openings if o.wall_id == i for c in opening_spans(w, o, ext[i], zones[i])]
        rest = []
        for j, v in W.items():
            if j == i:
                continue
            for k, p in enumerate(((v.start.x, v.start.y), (v.end.x, v.end.y))):
                # a face rests on a thicker/earlier wall or on one it ends on (not by accident)
                through = _on_center(p, w) and min(math.dist(p, (w.start.x, w.start.y)), math.dist(p, (w.end.x, w.end.y))) > 1.0
                if not (through or (-w.thickness, len(i), i) < (-v.thickness, len(j), j)):
                    continue
                d = np.array([v.end.x - v.start.x, v.end.y - v.start.y]) / v.length * (1 if k == 0 else -1)
                c0 = np.array(p) + d * -ext[j][k]
                face = [c0 + np.array([-d[1], d[0]]) * v.thickness / 2 * f for f in np.linspace(-1, 1, 401)]
                hit = [(f[0] - w.start.x) * ux + (f[1] - w.start.y) * uy for f in face
                       if _pt_dist(f, w, ext[i]) <= 1.0]
                rest += hit
        if zones[i] and not rest:
            bad.append(f"{i}: zone {zones[i]} protects nobody")
        for s in rest:
            if any(a + 1.5 < s < b - 1.5 for a, b in cuts):
                bad.append(f"{i}: a wall rests at s={s:.0f} inside an opening cut")
    flipped = plan.model_copy(update={"walls": [
        w.model_copy(update={"start": w.end, "end": w.start}) if n % 2 else w
        for n, w in enumerate(reversed(plan.walls))]})
    ext2, _ = wall_junctions(flipped.walls)
    for i, w in W.items():
        f2 = _foot(next(v for v in flipped.walls if v.id == i), ext2[i])
        if not np.allclose(sorted(map(tuple, foot[i].round(3))), sorted(map(tuple, f2.round(3))), atol=0.01):
            bad.append(f"{i}: result depends on wall order / direction")
    meshes = build_wall_meshes(plan)
    for i, m in meshes.items():
        if not m.is_watertight or m.volume <= 0:
            bad.append(f"{i}: mesh not watertight / empty")
    return bad


def test_random_plans_keep_every_junction_invariant():
    import random

    rng = random.Random(20260101)
    fails = []
    for n in range(200):
        plan = _random_plan(rng)
        fails += [f"plan {n}: {b}" for b in _check_plan(plan)]
    assert not fails, "\n".join(fails[:10])


@pytest.mark.parametrize("flip", [False, True])  # flip: the contact is at the trunk's end, not start
@pytest.mark.parametrize("x, deg", [(30, 145), (50, 130), (50, 170)])
def test_branch_touching_the_trunk_end_keeps_the_contact_under_a_door(x, deg, flip):
    r = np.radians(deg)  # leans back over the trunk's start: it meets the trunk's end corner/face
    sgn, off = (-1, 4000) if flip else (1, 0)  # mirror in x: start <-> end
    plan = _walls_plan(
        [("t", (0, 0), (4000, 0), 200),
         ("b", (off + sgn * x, 0), (off + sgn * (x + 3000 * np.cos(r)), 3000 * np.sin(r)), 120)],
        [{**DOOR, "wall_id": "t", "position": 3550 if flip else 450}],  # the door reaches the trunk end
    )
    meshes = build_wall_meshes(plan)
    d = np.array([sgn * np.cos(r), np.sin(r)])
    v = np.unique(meshes["b"].vertices[:, :2].round(6), axis=0)
    a, b = v[v @ d <= (v @ d).min() + 1e-6]  # the branch's end face
    face = [a + (b - a) * u for u in np.linspace(0, 1, 801)]
    # where the end face touches the trunk's footprint (x 0..4000, |y| <= 100), within 1 mm
    touch = [p for p in face if -1 <= p[0] <= 4001 and abs(p[1]) <= 101]
    assert touch
    pts = np.array([[min(max(p[0], 0.5), 3999.5), 0.0, 1000.0] for p in touch])
    assert _inside(meshes["t"], pts).all()
    assert not _inside(meshes["t"], np.array([[3400.0 if flip else 600.0, 0.0, 1000.0]])).any()  # the door


def _ray(deg, length):
    return (length * np.cos(np.radians(deg)), length * np.sin(np.radians(deg)))


def test_a_swallowed_neighbour_is_not_cleared_any_more():
    """Five arms; the 300 mm stubs vanish into the others. The long arm must not keep away from them."""
    plan = _walls_plan([("w1", (0, 0), _ray(18.2, 3000), 150), ("w2", (0, 0), _ray(48.6, 300), 200),
                        ("w3", (0, 0), _ray(90, 600), 250), ("w4", (0, 0), _ray(-175.5, 300), 200),
                        ("w5", (0, 0), _ray(-124.6, 300), 250)])
    meshes = build_wall_meshes(plan)
    assert _gap(meshes["w1"], meshes["w3"]) <= 1.0  # was 147 mm
    assert meshes["w1"].bounds[1][0] > 2800


def test_a_swallowed_wall_does_not_widen_another_walls_protected_zone():
    plan = _walls_plan(
        [("w1", (0, 0), (-1796.6, 2402.6), 150), ("w2", (0, 0), (-1473.8, 279.4), 250),
         ("w3", (0, 0), (-1498.3, 70.7), 250)],  # w3 lies inside w2 and shrinks to a sliver
        [{**DOOR, "wall_id": "w2", "position": 800, "width": 1600}],
    )
    w2 = build_wall_meshes(plan)["w2"]
    mid = np.array([[800 * -0.9856, 800 * 0.1868, 1000.0]])  # the middle of the door, on w2's centerline
    assert not _inside(w2, mid).any()
    assert w2.volume < 0.65e9  # the door is cut over ~1.2 m (was 1.27e9 m3 with the zone widened)


@pytest.mark.parametrize("off, joined", [(0.6, True), (1.5, False)])
def test_endpoints_within_one_millimetre_of_each_other_form_a_junction(off, joined):
    from app.geometry.junctions import wall_junctions

    plan = _walls_plan([("w1", (0, 0), (4000, 0), 200), ("w2", (off, off), (0, 3000), 200)])
    assert (wall_junctions(plan.walls)[0]["w2"][0] != 0) is joined  # ends 0.85 mm / 2.1 mm apart


@pytest.mark.parametrize("off, joined", [(0.5, True), (2.0, False)])
def test_end_within_one_millimetre_of_a_centerline_is_a_t_junction(off, joined):
    from app.geometry.junctions import wall_junctions

    plan = _walls_plan([("t", (0, 0), (4000, 0), 200), ("b", (2000, off), (2000, 3000), 200)])
    assert (wall_junctions(plan.walls)[0]["b"][0] != 0) is joined


@pytest.mark.parametrize("deg, extended", [(0.5, False), (0.8, True)])
def test_walls_closer_than_about_half_a_degree_count_as_folded_not_as_a_corner(deg, extended):
    from app.geometry.junctions import wall_junctions

    plan = _walls_plan([("m", (0, 0), (4000, 0), 200), ("o", (0, 0), _ray(deg, 3000), 200)])
    assert (wall_junctions(plan.walls)[0]["m"][0] > 0) is extended
