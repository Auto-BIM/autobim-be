import importlib.util
import math
import statistics
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import ModelSettings, RecognitionSettings, load_settings
from app.main import create_app
from app.models.registry import build_models
from app.recognition import recognize as recognize_module
from app.recognition.openings import attach_openings
from app.recognition.pipeline import image_to_plan
from app.recognition.recognize import recognize
from app.recognition.topology import BuildingSplit
from app.recognition.walls import PixelWall, remove_duplicate_walls, snap_junctions
from app.schemas.jobs import ScaleHint
from app.schemas.plan import ReviewReason, ScaleSource, WallKind
from tests.synthetic_plans import (
    box,
    draw_wall,
    l_shaped,
    models_for,
    perturb,
    rectangle,
    square_with_a_line_beside_it,
    square_with_a_wing,
    square_with_corner_door,
    square_with_diagonal_wall,
    square_with_doors_at_both_ends_of_the_left_wall,
    two_plans_on_a_sheet,
    with_outside_clutter,
)

IMG = np.zeros((8, 8, 3), np.uint8)


def _plan(**kw):
    settings = ModelSettings(**kw.pop("models", {}))
    return image_to_plan(IMG, build_models(settings), **kw)


def test_fake_plan_walls(fake_plan):
    assert fake_plan.scale.source == ScaleSource.dimension
    assert fake_plan.scale.mm_per_px == pytest.approx(10.0)
    assert not fake_plan.scale.estimated
    kinds = [w.kind for w in fake_plan.walls]
    assert kinds.count(WallKind.exterior) == 4 and kinds.count(WallKind.interior) == 1
    # outer centerlines form an 8000 x 5000 mm rectangle
    xs = {p.x for w in fake_plan.walls for p in (w.start, w.end)}
    ys = {p.y for w in fake_plan.walls for p in (w.start, w.end)}
    assert (max(xs) - min(xs), max(ys) - min(ys)) == (8000, 5000)
    thick = {w.kind: w.thickness for w in fake_plan.walls}
    assert thick == {WallKind.exterior: 200, WallKind.interior: 120}


def test_fake_plan_openings(fake_plan):
    assert len(fake_plan.openings) == 5
    by_id = {o.id: o for o in fake_plan.openings}
    walls = {w.id: w for w in fake_plan.walls}
    for o in fake_plan.openings:
        assert 0 <= o.position <= walls[o.wall_id].length
    assert by_id["o1"].width == pytest.approx(900)
    assert by_id["o4"].width == pytest.approx(1200)
    assert by_id["o4"].sill_height == 900
    assert walls[by_id["o2"].wall_id].kind == WallKind.interior


def test_low_confidence_becomes_review_item(fake_plan):
    reviews = [(r.element_id, r.reason) for r in fake_plan.review_items]
    assert reviews == [("o3", ReviewReason.low_confidence)]


def test_scale_fallback_to_assumed_wall_thickness():
    plan = _plan(models={"dimension_reader": "none"})
    assert plan.scale.source == ScaleSource.assumed_wall_thickness
    assert plan.scale.estimated
    assert plan.scale.mm_per_px == pytest.approx(10.0)  # 200 mm / 20 px
    assert any(r.reason == ReviewReason.scale_estimated for r in plan.review_items)


def test_scale_hint_requires_exactly_one():
    with pytest.raises(ValueError):
        ScaleHint()
    with pytest.raises(ValueError):
        ScaleHint(mm_per_px=1, building_width_mm=2)


# ------------------------------------------------------------------ recognition v1 (synthetic)
TOL = 3.0  # px


def _match(r, expected, scale=1.0):
    got = [
        (w.horizontal, w.center / scale, w.a / scale, w.b / scale, k)
        for w, k in zip(r.walls, r.kinds)
    ]
    unmatched = list(got)
    for h, c, a, b, kind in expected:
        hit = next(
            (
                g
                for g in unmatched
                if g[0] == h
                and abs(g[1] - c) <= TOL
                and abs(g[2] - a) <= TOL
                and abs(g[3] - b) <= TOL
            ),
            None,
        )
        assert hit is not None, f"missing wall {(h, c, a, b)}; got {got}"
        assert hit[4] == kind, f"wall {(h, c, a, b)} classified {hit[4]}, expected {kind}"
        unmatched.remove(hit)
    assert not unmatched, f"extra walls {unmatched}"


def _check_openings(r, expected, scale=1.0):
    for op, ((h, c), s0, s1) in zip(r.openings, expected):
        w = r.walls[op.wall_index]
        assert w.horizontal == h and abs(w.center / scale - c) <= TOL, (op, w)
        assert abs(op.s0 / scale - s0) <= TOL and abs(op.s1 / scale - s1) <= TOL, (op, s0, s1)
    assert len(r.openings) == len(expected)


@pytest.mark.parametrize("noise", [False, True])
@pytest.mark.parametrize("scale", [1.0, 0.5, 2.0])
def test_l_shaped(noise, scale):
    mask, boxes, exp = l_shaped(noise=noise, scale=scale)
    r = recognize(mask, boxes)
    _match(r, exp["walls"], scale)
    _check_openings(r, exp["openings"], scale)
    ext_t = [w.thickness / scale for w, k in zip(r.walls, r.kinds) if k == WallKind.exterior]
    int_t = [w.thickness / scale for w, k in zip(r.walls, r.kinds) if k == WallKind.interior]
    assert all(abs(t - exp["t_ext"]) <= 1.5 for t in ext_t), ext_t
    assert all(abs(t - exp["t_int"]) <= 1.5 for t in int_t), int_t
    assert r.unexplained_wall_ratio < 0.05
    assert not r.outside_walls


@pytest.mark.parametrize("seed", range(10))
def test_perturbed_masks(seed):
    mask, boxes, exp = l_shaped(noise=True, seed=seed)
    r = recognize(perturb(mask, seed=seed), boxes)
    _match(r, exp["walls"])
    _check_openings(r, exp["openings"])


def test_door_at_corner():
    """The door label ate the end of the perpendicular wall; the corner must still close."""
    mask, boxes = square_with_corner_door()
    r = recognize(mask, boxes)
    _match(
        r,
        {
            (True, 50, 50, 450, WallKind.exterior),
            (True, 350, 50, 450, WallKind.exterior),
            (False, 50, 50, 350, WallKind.exterior),
            (False, 450, 50, 350, WallKind.exterior),
        },
    )
    (op,) = r.openings
    w = r.walls[op.wall_index]
    assert w.horizontal and w.center == 350
    assert abs(op.s0 - 60) <= TOL and abs(op.s1 - 150) <= TOL


def test_diagonal_wall_is_reported():
    mask, boxes = square_with_diagonal_wall()
    r = recognize(mask, boxes)
    assert len(r.walls) == 4
    assert r.unexplained_wall_ratio > 0.1
    plan = image_to_plan(IMG, models_for(mask, boxes))
    (item,) = [i for i in plan.review_items if i.reason == ReviewReason.other]
    assert item.element_id == "plan" and "인식되지 않은 벽 영역" in item.message


# ------------------------------------------------------------------ stray detections
def test_detections_outside_the_building_are_dropped():
    mask, boxes, exp = l_shaped(noise=False)
    r = recognize(with_outside_clutter(mask), boxes)
    _match(r, exp["walls"])
    _check_openings(r, exp["openings"])
    assert len(r.outside_walls) == 5  # the legend frame (4 walls) and the loose bar
    assert r.unexplained_wall_ratio < 0.05  # dropped walls are not "unexplained" either


def test_the_filter_is_what_drops_the_clutter(monkeypatch):
    mask, boxes, _ = l_shaped(noise=False)
    monkeypatch.setattr(
        recognize_module, "keep_building", lambda walls, *_: BuildingSplit(walls, [])
    )
    assert len(recognize(with_outside_clutter(mask), boxes).walls) == 13


@pytest.mark.parametrize("seed", range(3))
def test_clutter_does_not_change_the_plan(seed):
    mask, boxes, _ = l_shaped(noise=True, seed=seed)
    clean = image_to_plan(IMG, models_for(mask, boxes))
    cluttered = image_to_plan(IMG, models_for(with_outside_clutter(mask), boxes))
    assert cluttered.scale.mm_per_px == pytest.approx(clean.scale.mm_per_px)
    # the one difference: a lot of wall was dropped as outside the building, and it says so
    assert [r.reason for r in cluttered.review_items] == [
        *(r.reason for r in clean.review_items),
        ReviewReason.other,
    ]
    dropped = cluttered.review_items[-1]
    assert dropped.element_id == "plan" and "건물 밖으로 보고 제외한 벽 영역" in dropped.message
    assert len(cluttered.walls) == len(clean.walls) == 8
    assert [o.wall_id for o in cluttered.openings] == [o.wall_id for o in clean.openings]


# 34 px off the right wall's face. Walls closer than 1 t (24 px here) are one body, so a stray
# bar has to be farther than that to be dropped (test_walls_within_one_thickness_are_one_body)
STRAY_BAR_X = 953


def test_a_stray_wall_next_to_a_corner_does_not_pull_the_building_to_it():
    """A bar beside the corner, beyond the link distance, is dropped and the corner still
    closes on the right wall."""
    mask, boxes, exp = l_shaped(noise=False)
    draw_wall(mask, STRAY_BAR_X, 20, STRAY_BAR_X, 200, 14)
    r = recognize(mask, boxes)
    _match(r, exp["walls"])
    assert len(r.outside_walls) == 1


def test_a_wall_joined_to_the_building_only_by_door_boxes_is_kept():
    mask, boxes = square_with_doors_at_both_ends_of_the_left_wall()
    r = recognize(mask, boxes)
    assert not r.outside_walls
    assert any(not w.horizontal and w.center == 50 for w in r.walls), r.walls


def test_a_small_stray_wall_is_dropped_without_a_review_item():
    mask, boxes, _ = l_shaped(noise=False)
    draw_wall(mask, STRAY_BAR_X, 20, STRAY_BAR_X, 200, 14)
    assert 0 < recognize(mask, boxes).outside_wall_ratio < 0.05
    plan = _synthetic_plan(mask, boxes)
    assert [r.reason for r in plan.review_items] == [ReviewReason.low_confidence]  # only o4


def test_dropped_wall_share_is_measured_on_all_wall_pixels():
    mask, boxes, _ = l_shaped(noise=False)
    clutter = with_outside_clutter(mask)
    ratio = recognize(clutter, boxes).outside_wall_ratio
    assert ratio == pytest.approx(
        1 - mask.sum() / clutter.sum(), abs=0.02
    )  # the clutter is everything the clean flat does not have
    assert recognize(mask, boxes).outside_wall_ratio == 0.0


def test_partition_inside_the_building_is_kept_even_when_it_touches_nothing():
    mask, boxes, exp = l_shaped(noise=False)
    draw_wall(mask, 150, 500, 350, 500, 14)
    r = recognize(mask, boxes)
    _match(r, exp["walls"] | {(True, 500, 143, 357, WallKind.interior)})
    assert not r.outside_walls


# ------------------------------------------------------------------ one body, several plans
def test_walls_within_one_thickness_are_one_body():
    """A 20 px gap (t = 20) between a plan and its wing is a door leaf, not a split."""
    mask, boxes = square_with_a_wing(gap=20)
    r = recognize(mask, boxes)
    assert not r.outside_walls and not r.other_plans
    assert len(r.walls) == 8


def test_walls_farther_apart_than_one_thickness_are_two_bodies():
    mask, boxes = square_with_a_wing(gap=60)
    r = recognize(mask, boxes)
    assert len(r.walls) == 4 and len(r.outside_walls) == 4
    assert r.other_plans  # the wing is plan-sized next to the plan: say so


def test_the_link_distance_is_what_joins_the_wing():
    mask, boxes = square_with_a_wing(gap=20)
    r = recognize(mask, boxes, RecognitionSettings(building_link_factor=0.0))
    assert len(r.walls) == 4 and len(r.outside_walls) == 4


def test_a_second_plan_on_the_sheet_is_dropped_and_reported():
    mask, boxes = two_plans_on_a_sheet()
    plan = _synthetic_plan(mask, boxes)
    assert len(plan.walls) == 4 and max(w.start.x for w in plan.walls) < 500 * 5.0
    others = [r for r in plan.review_items if r.reason == ReviewReason.other]
    messages = [r.message for r in others]
    assert "도면에 평면이 여러 개로 보여 가장 큰 평면만 변환했습니다" in messages
    assert not any("건물 밖으로 보고 제외한" in m for m in messages)  # not "an outbuilding"
    assert all(r.element_id == "plan" for r in others)


def test_the_other_plan_warning_is_what_replaces_the_outside_message():
    mask, boxes = two_plans_on_a_sheet()
    r = recognize(mask, boxes)
    assert r.other_plans and r.outside_wall_ratio > 0.3


def test_a_legend_next_to_the_plan_is_not_a_second_plan():
    mask, boxes, _ = l_shaped(noise=False)
    r = recognize(with_outside_clutter(mask), boxes)
    assert not r.other_plans and r.outside_walls  # dropped, but too small to be a plan


def test_a_long_line_beside_the_plan_is_not_a_second_plan():
    """Frame lines and the like run one way only; a plan has walls both ways."""
    mask, boxes = square_with_a_line_beside_it()
    r = recognize(mask, boxes)
    assert len(r.walls) == 4 and len(r.outside_walls) == 1
    assert r.outside_wall_ratio > 0.25  # 35% of the plan's wall pixels: over the 30% line
    assert not r.other_plans


# ------------------------------------------------------------------ the same wall twice
def _wall(horizontal, center, a, b, t):
    return PixelWall(horizontal, center, a, b, t)


def test_the_same_wall_recognised_twice_is_one_wall():
    big, twin = _wall(True, 100, 100, 500, 24), _wall(True, 113, 200, 600, 14)
    (wall,) = remove_duplicate_walls([big, twin], RecognitionSettings())
    assert wall is big
    assert (wall.center, wall.a, wall.b, wall.thickness) == (100, 100, 600, 24)


def test_a_hole_inside_a_wall_does_not_thin_it():
    """The rows around the hole split in two runs; the second one is a band inside the wall."""
    mask, boxes, exp = l_shaped(noise=False)
    mask[94:104, 400:410] = False
    r = recognize(mask, boxes)
    _match(r, exp["walls"])
    top = next(w for w in r.walls if w.horizontal and abs(w.center - 100) <= TOL)
    assert abs(top.thickness - 24) <= 1.0 and abs(top.center - 100) <= 1.0


@pytest.mark.parametrize(
    "other",
    [
        _wall(True, 124, 100, 500, 24),  # touching walls
        _wall(True, 123, 100, 500, 24),  # one ragged pixel shared
        _wall(True, 100, 500, 900, 24),  # end to end
        _wall(False, 100, 50, 150, 24),  # crossing
    ],
)
def test_neighbouring_walls_are_not_duplicates(other):
    first = _wall(True, 100, 100, 500, 24)
    assert len(remove_duplicate_walls([first, other], RecognitionSettings())) == 2


# ------------------------------------------------------------------ Plan invariants
def _cases():
    for scale in (0.5, 1.0, 2.0):
        for noise in (False, True):
            mask, boxes, _ = l_shaped(noise=noise, scale=scale)
            yield f"l-{scale}-{'noisy' if noise else 'clean'}", mask, boxes
    for seed in range(10):
        mask, boxes, _ = l_shaped(noise=True, seed=seed)
        yield f"perturbed-{seed}", perturb(mask, seed=seed), boxes
    mask, boxes = square_with_corner_door()
    yield "corner-door", mask, boxes
    mask, boxes, _ = l_shaped(noise=True)
    yield "clutter", with_outside_clutter(mask), boxes
    mask, boxes, _ = l_shaped(noise=False)
    draw_wall(mask, STRAY_BAR_X, 20, STRAY_BAR_X, 200, 14)
    yield "bar-by-the-corner", mask, boxes


CASES = list(_cases())


def _is_horizontal(w):
    return w.start.y == w.end.y


def _span(w):
    """(across lo, across hi, along lo, along hi) of the wall's footprint, mm."""
    if _is_horizontal(w):
        along = sorted((w.start.x, w.end.x))
        return w.start.y - w.thickness / 2, w.start.y + w.thickness / 2, *along
    along = sorted((w.start.y, w.end.y))
    return w.start.x - w.thickness / 2, w.start.x + w.thickness / 2, *along


def _distance_to_segment(p, w):
    (ax, ay), (bx, by) = (w.start.x, w.start.y), (w.end.x, w.end.y)
    t = ((p.x - ax) * (bx - ax) + (p.y - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2)
    t = min(1.0, max(0.0, t))
    return math.hypot(p.x - (ax + t * (bx - ax)), p.y - (ay + t * (by - ay)))


@pytest.mark.parametrize("mm_per_px", [None, 5.0], ids=["estimated-scale", "known-scale"])
@pytest.mark.parametrize("name,mask,boxes", CASES, ids=[c[0] for c in CASES])
def test_plan_walls_are_clean(name, mask, boxes, mm_per_px):
    plan = image_to_plan(IMG, models_for(mask, boxes, mm_per_px))
    walls = plan.walls
    assert len(walls) == (8 if name != "corner-door" else 4)

    # no wall is in the plan twice: parallel walls never share floor area
    for i, w in enumerate(walls):
        for o in walls[i + 1 :]:
            if _is_horizontal(w) != _is_horizontal(o):
                continue
            (wl, wh, wa, wb), (ol, oh, oa, ob) = _span(w), _span(o)
            across, along = min(wh, oh) - max(wl, ol), min(wb, ob) - max(wa, oa)
            assert not (across > 1.0 and along > 1.0), (w.id, o.id)

    # a wall end that reaches another wall lies on its centerline, to the millimetre: the
    # geometry stage only joins ends that are within 1 mm of the other wall's centerline
    reach = statistics.median(w.thickness for w in walls)
    for w in walls:
        for end in (w.start, w.end):
            for o in walls:
                if _is_horizontal(o) == _is_horizontal(w):
                    continue
                line = o.start.y if _is_horizontal(o) else o.start.x
                across = end.y if _is_horizontal(o) else end.x
                along = end.x if _is_horizontal(o) else end.y
                lo, hi = sorted((o.start.x, o.end.x) if _is_horizontal(o) else (o.start.y, o.end.y))
                if (
                    abs(across - line) <= o.thickness / 2 + reach
                    and lo - reach <= along <= hi + reach
                ):
                    assert _distance_to_segment(end, o) <= 1.0, (w.id, o.id)


# ------------------------------------------------------------------ Plan conversion (docs/recognition.md section 4)
def _synthetic_plan(mask, boxes, mm_per_px=5.0):
    return image_to_plan(IMG, models_for(mask, boxes, mm_per_px))


def test_openings_land_on_the_wall_they_cross():
    mask, boxes, _ = l_shaped(noise=False)
    plan = _synthetic_plan(mask, boxes)
    assert plan.scale.mm_per_px == pytest.approx(5.0) and not plan.scale.estimated
    assert [o.id for o in plan.openings] == ["o1", "o2", "o3", "o4"]
    walls = {w.id: w for w in plan.walls}
    # the front door's box sticks into the room, but the door is in the bottom wall (y = 600)
    door = plan.openings[0]
    wall = walls[door.wall_id]
    assert wall.start.y == wall.end.y == pytest.approx((700 - 600) * 5.0)
    assert door.width == pytest.approx(90 * 5.0, abs=TOL * 5)
    assert door.position == pytest.approx((245 - 100) * 5.0, abs=TOL * 5)  # from the wall start
    assert (door.height, door.sill_height) == (2100.0, 0.0)
    # the interior door is in the interior wall x = 400, though its box reaches x = 320
    assert walls[plan.openings[3].wall_id].kind == WallKind.interior
    assert plan.review_items[0].element_id == "o4"  # confidence 0.4
    assert [r.reason for r in plan.review_items] == [ReviewReason.low_confidence]


@pytest.mark.parametrize(
    "span,mm_per_px,defaulted",
    [
        ((500, 504), 5.0, True),
        ((300, 500), 5.0, False),
        ((100, 900), 7.0, True),
    ],  # mm: 20 1000 5600
)
def test_implausible_opening_width_gets_the_default(span, mm_per_px, defaulted):
    mask = np.zeros((700, 1000), bool)
    rectangle(mask, 100, 100, 900, 600, 24)
    window = box("window", span[0], 90, span[1], 110, 0.9)  # on the top wall, which is not cut
    plan = _synthetic_plan(mask, [window], mm_per_px)
    (opening,) = plan.openings
    assert (opening.width == 1200.0) == defaulted
    assert [r.reason for r in plan.review_items] == (
        [ReviewReason.default_value_applied] if defaulted else []
    )


def test_a_box_that_crosses_no_wall_is_attached_to_the_nearest_and_flagged():
    mask, _, _ = l_shaped(noise=False)
    plan = _synthetic_plan(mask, [box("door", 940, 640, 980, 680, 0.9)])
    assert ("o1", ReviewReason.unattached_opening) in [
        (r.element_id, r.reason) for r in plan.review_items
    ]
    assert plan.openings[0].wall_id in {w.id for w in plan.walls}


def _padded_flat_with_two_boxes():
    """The L-shaped flat on a sheet 700 px taller. A box 40 px off the corner is close, one
    at the bottom of the sheet is over 600 px from every wall (20 t = 480 px)."""
    mask, boxes, _ = l_shaped(noise=False)
    near = box("door", 940, 640, 980, 680, 0.9)
    far = box("window", 940, 1280, 980, 1320, 0.9)
    return np.pad(mask, ((0, 700), (0, 0))), [*boxes, near, far]


def test_a_box_far_from_every_wall_is_dropped_and_a_near_one_is_kept():
    mask, boxes = _padded_flat_with_two_boxes()
    plan = _synthetic_plan(mask, boxes)
    ids = [o.id for o in plan.openings]
    assert ids == ["o1", "o2", "o3", "o4", "o5"]  # o6 (the far box) is gone, IDs are not reused
    flagged = [(r.element_id, r.reason) for r in plan.review_items]
    assert ("o5", ReviewReason.unattached_opening) in flagged  # near, but attached by distance
    (dropped,) = [r for r in plan.review_items if "제외한 개구부" in r.message]
    assert dropped.element_id == "plan" and dropped.reason == ReviewReason.other
    assert "1개" in dropped.message


def test_the_distance_limit_is_what_drops_the_far_box():
    mask, boxes = _padded_flat_with_two_boxes()
    settings = RecognitionSettings(max_opening_dist_factor=1000.0)
    plan = image_to_plan(IMG, models_for(mask, boxes, 5.0), settings=settings)
    assert len(plan.openings) == 6
    assert not any("제외한 개구부" in r.message for r in plan.review_items)


def test_attach_openings_counts_the_boxes_it_dropped():
    walls = _t_junction()
    near, far = box("window", 100, 140, 140, 180, 0.9), box("window", 100, 900, 140, 940, 0.9)
    ops, dropped = attach_openings(walls, [near, far], {}, max_dist=200.0)
    assert [o.box_index for o in ops] == [0] and ops[0].source == "nearest" and dropped == 1
    ops, dropped = attach_openings(walls, [near, far], {})  # no limit
    assert len(ops) == 2 and dropped == 0


# ------------------------------------------------------------------ settings
def test_recognition_settings_in_the_yaml_are_the_code_defaults():
    assert load_settings().recognition == RecognitionSettings()


def test_job_runner_hands_the_recognition_settings_to_recognition(settings, png_bytes):
    settings.recognition = RecognitionSettings(run_len_factor=1000.0)  # no run is long enough
    client = TestClient(create_app(settings))
    res = client.post("/api/jobs", files={"file": ("plan.png", png_bytes, "image/png")})
    job = client.get(f"/api/jobs/{res.json()['id']}").json()
    assert job["status"] == "failed" and job["error"]["code"] == "no_walls"


@pytest.mark.slow
def test_a3_sized_mask_is_recognised_within_ten_seconds():
    mask, boxes, expected = l_shaped(noise=True, scale=5.0)  # 3500 x 5000
    assert mask.shape == (3500, 5000)
    start = time.perf_counter()
    r = recognize(mask, boxes)
    assert time.perf_counter() - start < 10.0
    _match(r, expected["walls"], 5.0)


# ------------------------------------------------------------------ scripts/debug_overlay.py
def test_debug_overlay_marks_walls_openings_and_review_items(fake_plan):
    spec = importlib.util.spec_from_file_location(
        "debug_overlay", Path(__file__).parents[1] / "scripts" / "debug_overlay.py"
    )
    overlay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(overlay)
    image = Image.new("RGB", (1000, 700), "white")  # the fake scene's size
    out = overlay.draw_overlay(fake_plan, image)
    assert out.size == image.size and out.getpixel((100, 98)) != (255, 255, 255)
    colors = {c for _, c in out.getcolors(maxcolors=1 << 20)}
    assert {(255, 0, 0), (0, 0, 255), (0, 128, 0), (255, 165, 0)} <= colors  # o3 is flagged


# ------------------------------------------------------------------ R9 and R6 edges
def _t_junction():
    """Wall y=100 (x 0..500, t=20) crossed by a wall at x=250 (faces 240..260)."""
    return [_wall(True, 100, 0, 500, 20), _wall(False, 250, 0, 300, 20)]


@pytest.mark.parametrize(
    "span,expected",
    [
        ((244, 256), (244, 256)),  # wholly inside the crossing wall: kept as detected
        ((240, 300), (260, 300)),  # starts on the face
        ((200, 260), (200, 240)),  # ends on the face
        ((230, 255), (230, 240)),  # ends inside the crossing wall
        ((245, 300), (260, 300)),  # starts inside it
        ((260, 300), (260, 300)),  # already clear
    ],
)
def test_opening_is_cut_back_to_the_crossing_walls_faces(span, expected):
    walls = _t_junction()
    window = box("window", span[0], 95, span[1], 105, 0.9)  # narrower than the crossing wall
    (op,), _ = attach_openings(walls, [window], {})
    assert (op.wall_index, op.source) == (0, "box")
    assert (op.s0, op.s1) == expected and op.s1 > op.s0


def test_a_small_window_on_a_t_junction_has_a_positive_measured_width():
    mask = np.zeros((700, 1000), bool)
    rectangle(mask, 100, 100, 900, 600, 24)
    draw_wall(mask, 400, 100, 400, 600, 14)  # interior wall, T into the top wall
    plan = _synthetic_plan(mask, [box("window", 394, 90, 406, 110, 0.9)])
    (item,) = plan.review_items
    assert item.reason == ReviewReason.default_value_applied
    assert "-" not in item.message.split("measured width")[1].split("mm")[0]


@pytest.mark.parametrize("short_first", [False, True], ids=["short-last", "short-first"])
@pytest.mark.parametrize(
    "short,reach",
    [
        (_wall(False, 450, 112, 400, 40), "a"),  # stops 12 px short of y=100, below it
        (_wall(False, 450, 0, 88, 40), "b"),  # stops 12 px short of y=100, above it
    ],
    ids=["below", "above"],
)
def test_l_corner_both_walls_end_on_each_others_centerline(short, reach, short_first):
    """Whichever wall comes first, the corner closes on both centerlines.

    Pins the behaviour only: snap_junctions retries open ends, so deleting the reach in
    `_snap_end` changes nothing for layouts with walls apart (fuzzed, 60000 layouts).
    """
    thin = _wall(True, 100, 100, 460, 10)  # its end is 10 px past x=450
    short = PixelWall(short.horizontal, short.center, short.a, short.b, short.thickness)
    walls = [short, thin] if short_first else [thin, short]
    snap_junctions(walls, 20.0, RecognitionSettings())
    assert thin.b == 450  # onto the thick wall's centerline
    assert getattr(short, reach) == 100  # and the thick wall onto the thin one's
