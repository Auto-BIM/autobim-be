"""DXF input path (issue #3). Test DXFs are generated in code; no .dxf file is committed."""

import io

import ezdxf
import pytest

from app.dxf_input.classify import classify
from app.dxf_input.entities import Entity
from app.dxf_input.reader import dxf_to_plan
from app.recognition.pipeline import RecognitionError
from app.schemas.plan import Plan, ReviewReason


def make_doc(units=4, scale=1.0, single=False, wall="A-WALL", door="A-DOOR", window="A-WINDOW", unit_header=True):
    """6000x4000 room (exterior 200, centerline (0,0)-(6000,4000)) + wall at x=3000 (120) + 2 door blocks + 1 window block."""
    doc = ezdxf.new("R2010")
    doc.units = units if unit_header else 0  # ezdxf.new() defaults to metres
    msp, k = doc.modelspace(), scale
    b = doc.blocks.new("DOOR900")
    b.add_line((0, 0), (900 * k, 0))
    b.add_arc((0, 0), 900 * k, 0, 90)
    b = doc.blocks.new("WIN1200")
    b.add_line((0, -60 * k), (1200 * k, -60 * k))
    b.add_line((0, 60 * k), (1200 * k, 60 * k))

    def line(a, c, layer=wall):
        msp.add_line((a[0] * k, a[1] * k), (c[0] * k, c[1] * k), dxfattribs={"layer": layer})

    if single:
        for a, c in [((0, 0), (6000, 0)), ((6000, 0), (6000, 4000)), ((6000, 4000), (0, 4000)),
                     ((0, 4000), (0, 0)), ((3000, 100), (3000, 3900))]:
            line(a, c)
    else:
        for a, c in [((-100, -100), (6100, -100)), ((100, 100), (5900, 100)), ((6100, -100), (6100, 4100)),
                     ((5900, 100), (5900, 3900)), ((6100, 4100), (-100, 4100)), ((5900, 3900), (100, 3900)),
                     ((-100, 4100), (-100, -100)), ((100, 3900), (100, 100)),
                     ((2940, 100), (2940, 3900)), ((3060, 100), (3060, 3900))]:
            line(a, c)
    msp.add_blockref("DOOR900", (1000 * k, -100 * k), dxfattribs={"layer": door})
    msp.add_blockref("DOOR900", (2940 * k, 2000 * k), dxfattribs={"layer": door, "rotation": 90})
    msp.add_blockref("WIN1200", (4000 * k, 0), dxfattribs={"layer": window})
    msp.add_line((0, 5000 * k), (1000 * k, 5000 * k), dxfattribs={"layer": "FURNITURE"})
    return doc


def to_bytes(doc) -> bytes:
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode()


def to_plan(doc, **kw) -> Plan:
    return dxf_to_plan(to_bytes(doc), filename="plan.dxf", **kw)


def opening_world(plan, o):
    w = plan.wall(o.wall_id)
    ux, uy = (w.end.x - w.start.x) / w.length, (w.end.y - w.start.y) / w.length
    return (w.start.x + ux * o.position, w.start.y + uy * o.position), o.width


def wall_key(w):
    return tuple(sorted([(round(w.start.x), round(w.start.y)), (round(w.end.x), round(w.end.y))]))


@pytest.mark.parametrize("units,scale", [(4, 1.0), (6, 0.001), (5, 0.1)])  # mm, m, cm
def test_double_line_room_with_blocks(units, scale):
    plan = to_plan(make_doc(units, scale))
    assert plan.source.type == "dxf" and plan.scale.source == "source_units" and not plan.scale.estimated
    walls = {wall_key(w): w for w in plan.walls}
    assert len(plan.walls) == 5
    for key in [((0, 0), (6000, 0)), ((6000, 0), (6000, 4000)), ((0, 4000), (6000, 4000)), ((0, 0), (0, 4000))]:
        assert walls[key].thickness == pytest.approx(200, abs=1)
    inner = next(w for w in plan.walls if abs(w.start.x - 3000) < 1 and abs(w.end.x - 3000) < 1)
    assert inner.thickness == pytest.approx(120, abs=1)
    found = sorted((o.type.value, *opening_world(plan, o)) for o in plan.openings)
    expected = [("door", (1450, 0), 900), ("door", (3000, 2450), 900), ("window", (4600, 0), 1200)]
    assert [f[0] for f in found] == [e[0] for e in expected]
    for (_, c, w), (_, ec, ew) in zip(found, expected):
        assert c == pytest.approx(ec, abs=1) and w == pytest.approx(ew, abs=1)
    assert [w.id for w in plan.walls] == [f"w{i}" for i in range(1, 6)]
    assert [o.id for o in plan.openings] == [f"o{i}" for i in range(1, 4)]
    assert plan.review_items == []


def test_unclassified_layer_ignored_and_single_line_walls_flagged():
    plan = to_plan(make_doc(single=True))
    assert len(plan.walls) == 5 and sorted(w.thickness for w in plan.walls) == [120, 200, 200, 200, 200]
    flagged = {r.element_id for r in plan.review_items if r.reason == ReviewReason.default_value_applied}
    assert {w.id for w in plan.walls} <= flagged


def test_missing_units_assumes_mm_and_flags_scale():
    plan = to_plan(make_doc(unit_header=False))
    assert len(plan.walls) == 5 and len(plan.openings) == 3
    assert plan.scale.source == "source_units" and plan.scale.estimated
    assert [(r.element_id, r.reason) for r in plan.review_items] == [("plan", ReviewReason.scale_estimated)]


def test_korean_layers():
    plan = to_plan(make_doc(wall="A-벽체", door="출입문", window="유리창"))
    assert len(plan.walls) == 5 and sorted(o.type.value for o in plan.openings) == ["door", "door", "window"]


def test_rules_table_is_configurable():
    doc = make_doc(wall="XW", door="XD", window="XN")
    with pytest.raises(RecognitionError) as exc:
        to_plan(doc)  # not classified by the default rules
    assert exc.value.code == "no_walls"
    plan = to_plan(doc, rules={"wall": ("xw",), "door": ("xd",), "window": ("xn",)})
    assert len(plan.walls) == 5 and len(plan.openings) == 3


@pytest.mark.parametrize("layer,label", [("OUTDOOR", "unknown"), ("문자", "unknown"), ("창고", "unknown"),
                                         ("A-DOOR", "door"), ("현관문", "door"), ("유리창", "window"),
                                         ("0_WALL", "wall"), ("벽", "wall")])
def test_layer_matching_avoids_common_false_positives(layer, label):
    assert classify(Entity(0, "LINE", layer, [(0, 0), (1, 0)])).label == label


def test_door_block_with_odd_size_gets_default_width_and_review():
    doc = make_doc()
    doc.blocks.new("BIGDOOR").add_line((0, 0), (2000, 0))
    doc.modelspace().add_blockref("BIGDOOR", (4200, 0), dxfattribs={"layer": "A-DOOR"})
    plan = to_plan(doc)
    odd = next(o for o in plan.openings if abs(opening_world(plan, o)[0][0] - 5200) < 1)
    assert odd.width == 900 and any(r.element_id == odd.id and r.reason == ReviewReason.default_value_applied
                                    for r in plan.review_items)


def test_door_far_from_any_wall_becomes_unattached_review_item():
    doc = make_doc()
    doc.modelspace().add_blockref("DOOR900", (20000, 20000), dxfattribs={"layer": "A-DOOR"})
    plan = to_plan(doc)
    assert len(plan.openings) == 3
    assert [r.reason for r in plan.review_items] == [ReviewReason.unattached_opening]


def test_unreadable_dxf_and_no_walls_are_recognition_errors():
    with pytest.raises(RecognitionError) as exc:
        dxf_to_plan(b"not a dxf file")
    assert exc.value.code == "invalid_dxf"
    empty = ezdxf.new("R2010")
    empty.units = 4
    with pytest.raises(RecognitionError) as exc:
        to_plan(empty)
    assert exc.value.code == "no_walls"


def test_dxf_upload_runs_through_to_glb_dxf_and_json(client):
    data = to_bytes(make_doc())
    res = client.post("/api/jobs", files={"file": ("plan.dxf", data, "application/dxf")})
    assert res.status_code == 202
    job_id = res.json()["id"]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["input"]["type"] == "dxf" and job["status"] == "succeeded", job["error"]
    assert len(job["plan"]["walls"]) == 5 and len(job["plan"]["openings"]) == 3
    for kind in ("glb", "dxf", "json"):
        out = client.get(f"/api/jobs/{job_id}/files/{kind}")
        assert out.status_code == 200 and out.content


def test_unreadable_dxf_upload_fails_with_a_clear_error(client):
    res = client.post("/api/jobs", files={"file": ("plan.dxf", b"0\nEOF\n", "application/dxf")})
    job = client.get(f"/api/jobs/{res.json()['id']}").json()
    assert job["status"] == "failed" and job["error"]["code"] in {"invalid_dxf", "no_walls"}


@pytest.mark.parametrize("at,center_x", [((2040, -100), 2490), ((50, -100), 500)])
def test_door_next_to_a_perpendicular_wall_stays_on_its_own_wall(at, center_x):
    doc = make_doc()
    doc.modelspace().add_blockref("DOOR900", at, dxfattribs={"layer": "A-DOOR"})
    plan = to_plan(doc)
    mine = [o for o in plan.openings if o.type.value == "door" and abs(opening_world(plan, o)[0][1]) < 1
            and abs(opening_world(plan, o)[0][0] - center_x) < 1]
    assert len(mine) == 1 and mine[0].width == pytest.approx(900, abs=1)


def single_line_plan(polygon, *partitions):
    doc = ezdxf.new("R2010")
    doc.units = 4
    msp = doc.modelspace()
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL"})
    for a, b in partitions:
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL"})
    return to_plan(doc)


def kinds(plan):
    return {wall_key(w): (w.kind.value, round(w.thickness)) for w in plan.walls}


def test_single_line_room_exterior_200_interior_120():
    got = kinds(to_plan(make_doc(single=True)))
    assert got[((3000, 100), (3000, 3900))] == ("interior", 120)
    assert [v for k, v in got.items() if k != ((3000, 100), (3000, 3900))] == [("exterior", 200)] * 4


def test_double_line_room_kinds_keep_measured_thickness():
    got = kinds(to_plan(make_doc()))
    assert sorted(got.values()) == [("exterior", 200)] * 4 + [("interior", 120)]
    assert not [r for r in to_plan(make_doc()).review_items if r.reason == ReviewReason.other]


@pytest.mark.parametrize("polygon,partition", [
    ([(0, 0), (6000, 0), (6000, 2000), (3000, 2000), (3000, 4000), (0, 4000)], ((1500, 0), (1500, 4000))),  # L
    ([(0, 0), (9000, 0), (9000, 6000), (6000, 6000), (6000, 2000), (3000, 2000), (3000, 6000), (0, 6000)],
     ((1500, 0), (1500, 6000))),  # U: the courtyard opens to the outside
])
def test_non_convex_outline_walls_are_exterior(polygon, partition):
    plan = single_line_plan(polygon, partition)
    interior = [w for w in plan.walls if w.kind.value == "interior"]
    assert len(interior) == 1 and wall_key(interior[0]) == tuple(sorted(partition)) and interior[0].thickness == 120
    assert all(w.thickness == 200 for w in plan.walls if w.kind.value == "exterior")


def test_open_outline_falls_back_to_exterior_default_and_is_flagged():
    doc = ezdxf.new("R2010")
    doc.units = 4
    for a, b in [((0, 0), (6000, 0)), ((0, 0), (0, 4000)), ((3000, 0), (3000, 4000))]:
        doc.modelspace().add_line(a, b, dxfattribs={"layer": "A-WALL"})
    plan = to_plan(doc)
    assert {(w.kind.value, w.thickness) for w in plan.walls} == {("exterior", 200)}
    assert [(r.element_id, r.reason) for r in plan.review_items if r.reason == ReviewReason.other] == [("plan", ReviewReason.other)]


def test_closed_single_room_without_partitions_is_exterior_without_review():
    plan = single_line_plan([(0, 0), (6000, 0), (6000, 4000), (0, 4000)])
    assert {(w.kind.value, w.thickness) for w in plan.walls} == {("exterior", 200)}
    assert [r for r in plan.review_items if r.reason == ReviewReason.other] == []


@pytest.mark.parametrize("gap", [100_000, 500_000])  # floors drawn far apart in one modelspace
def test_far_apart_copies_are_judged_consistently(gap):
    doc = ezdxf.new("R2010")
    doc.units = 4
    msp = doc.modelspace()
    for dx in (0, gap):
        pts = [(dx, 0), (dx + 6000, 0), (dx + 6000, 4000), (dx, 4000)]
        for a, b in zip(pts, pts[1:] + pts[:1]):
            msp.add_line(a, b, dxfattribs={"layer": "A-WALL"})
        msp.add_line((dx + 3000, 0), (dx + 3000, 4000), dxfattribs={"layer": "A-WALL"})
    plan = to_plan(doc)
    assert sorted((w.kind.value, w.thickness) for w in plan.walls) == [("exterior", 200)] * 8 + [("interior", 120)] * 2


def test_double_line_outline_with_single_line_partition():
    doc = make_doc()
    msp = doc.modelspace()
    for e in [e for e in msp if e.dxftype() == "LINE" and min(abs(e.dxf.start.x - 2940), abs(e.dxf.start.x - 3060)) < 1]:
        msp.delete_entity(e)  # 이중선 내벽을 지우고 단선 칸막이로 바꾼다
    msp.add_line((3000, 100), (3000, 3900), dxfattribs={"layer": "A-WALL"})
    got = kinds(to_plan(doc))
    assert got[((3000, 100), (3000, 3900))] == ("interior", 120)
    assert sorted(v for k, v in got.items() if k != ((3000, 100), (3000, 3900))) == [("exterior", 200)] * 4


def test_arc_on_an_unclassified_layer_is_ignored():
    doc = make_doc()
    doc.modelspace().add_arc((4500, 4000), 800, 180, 270, dxfattribs={"layer": "FURNITURE"})
    plan = to_plan(doc)
    assert len(plan.openings) == 3


def test_window_drawn_with_several_lines_is_one_opening():
    doc = make_doc()
    msp = doc.modelspace()
    # one window on the top wall as two full-width lines and a cross mullion
    for a, b in [((1000, 3975), (2600, 3975)), ((2600, 4025), (1000, 4025)),
                 ((1800, 3900), (1800, 4100)),
                 # two separate windows side by side on the same wall
                 ((3400, 4000), (4400, 4000)), ((4600, 4000), (5600, 4000))]:
        msp.add_line(a, b, dxfattribs={"layer": "A-WINDOW"})
    plan = to_plan(doc)
    top = [(opening_world(plan, o)[0], o.width) for o in plan.openings
           if abs(opening_world(plan, o)[0][1] - 4000) < 1]
    assert sorted((round(c[0]), round(w)) for c, w in top) == [(1800, 1600), (3900, 1000), (5100, 1000)]
