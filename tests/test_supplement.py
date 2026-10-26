"""Supplements patch the stored Plan; they never re-run recognition or renumber elements."""

import numpy as np
import pytest

from app.core.config import ModelSettings
from app.jobs.supplement import SupplementError, apply_supplements
from app.models.registry import build_models
from app.recognition.pipeline import image_to_plan
from app.schemas.jobs import SupplementRequest
from app.schemas.plan import ReviewReason, ScaleSource


def _sup(**kw) -> SupplementRequest:
    return SupplementRequest.model_validate(kw)


def _ids(plan):
    return [w.id for w in plan.walls], [o.id for o in plan.openings]


@pytest.fixture
def estimated_plan():
    """Fake plan with no dimension reading: scale is assumed from 200 mm exterior walls."""
    models = build_models(ModelSettings(dimension_reader="none"))
    return image_to_plan(np.zeros((8, 8, 3), np.uint8), models)


def test_no_supplements_is_identity(fake_plan):
    assert apply_supplements(fake_plan, []) == fake_plan


def test_building_width_rescales_coordinates_only(estimated_plan):
    plan = apply_supplements(estimated_plan, [_sup(scale={"building_width_mm": 16000})])
    assert plan.scale.source == ScaleSource.building_width and not plan.scale.estimated
    assert plan.scale.mm_per_px == pytest.approx(20.0)
    for before, after in zip(estimated_plan.walls, plan.walls):
        assert after.start.x == pytest.approx(before.start.x * 2)
        assert after.thickness == pytest.approx(before.thickness * 2)
        assert after.height == before.height  # heights are defaults, not measurements
    for before, after in zip(estimated_plan.openings, plan.openings):
        assert after.position == pytest.approx(before.position * 2)
        assert after.height == before.height
    assert ReviewReason.scale_estimated not in {r.reason for r in plan.review_items}


def test_reference_and_mm_per_px_hints(fake_plan):
    plan = apply_supplements(
        fake_plan, [_sup(scale={"reference": {"wall_id": "w1", "length_mm": 4000}})]
    )
    assert plan.wall("w1").length == pytest.approx(4000)
    plan = apply_supplements(fake_plan, [_sup(scale={"mm_per_px": 5})])
    assert plan.scale.mm_per_px == 5 and plan.wall("w1").length == pytest.approx(4000)
    with pytest.raises(SupplementError):
        apply_supplements(fake_plan, [_sup(scale={"reference": {"wall_id": "w99", "length_mm": 1}})])


def test_latest_scale_wins_and_patches_accumulate(fake_plan):
    plan = apply_supplements(
        fake_plan,
        [
            _sup(scale={"mm_per_px": 5}, walls=[{"id": "w4", "thickness": 150}]),
            _sup(scale={"mm_per_px": 20}),
        ],
    )
    assert plan.scale.mm_per_px == 20
    assert plan.wall("w4").thickness == 150  # user value survives the later rescale


def test_existing_ids_never_change(fake_plan):
    walls0, openings0 = _ids(fake_plan)
    sups = [
        _sup(scale={"building_width_mm": 12000}),
        _sup(
            walls=[{"id": "w2", "height": 2700}],
            openings=[{"id": "o3", "width": 1000}],
            add_walls=[{"start": {"x": 1000, "y": 3500}, "end": {"x": 5000, "y": 3500}}],
            add_openings=[{"type": "door", "wall_id": "w4", "position": 4000}],
        ),
        _sup(add_openings=[{"type": "window", "wall_id": "w6", "position": 2000}]),
    ]
    for n in range(1, len(sups) + 1):
        walls, openings = _ids(apply_supplements(fake_plan, sups[:n]))
        assert walls[: len(walls0)] == walls0
        assert openings[: len(openings0)] == openings0
    plan = apply_supplements(fake_plan, sups)
    assert _ids(plan) == (walls0 + ["w6"], openings0 + ["o6", "o7"])
    assert plan.wall("w6").thickness == 120 and plan.wall("w6").height == 2400
    new_door = next(o for o in plan.openings if o.id == "o6")
    assert (new_door.width, new_door.height, new_door.sill_height) == (900, 2100, 0)
    new_window = next(o for o in plan.openings if o.id == "o7")
    assert (new_window.width, new_window.height, new_window.sill_height) == (1200, 1200, 900)


def test_patched_or_resolved_elements_leave_review(fake_plan):
    assert [r.element_id for r in fake_plan.review_items] == ["o3"]
    assert apply_supplements(fake_plan, [_sup(openings=[{"id": "o3", "width": 950}])]).review_items == []
    assert apply_supplements(fake_plan, [_sup(resolved=["o3"])]).review_items == []


@pytest.mark.parametrize(
    "body",
    [
        {"walls": [{"id": "w99", "height": 1}]},
        {"openings": [{"id": "o99", "width": 1}]},
        {"openings": [{"id": "o1", "wall_id": "w99"}]},
        {"add_openings": [{"type": "door", "wall_id": "w99", "position": 0}]},
        {"resolved": ["ghost"]},
    ],
)
def test_unknown_elements_rejected(fake_plan, body):
    with pytest.raises(SupplementError) as exc:
        apply_supplements(fake_plan, [_sup(**body)])
    assert exc.value.code == "unknown_element"
