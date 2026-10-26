import numpy as np
import pytest

from app.core.config import ModelSettings
from app.models.registry import build_models
from app.recognition.pipeline import RecognitionError, image_to_plan
from app.schemas.jobs import ScaleHint, WallReference
from app.schemas.plan import ReviewReason, ScaleSource, WallKind

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


def test_scale_hints():
    plan = _plan(models={"dimension_reader": "none"}, scale_hint=ScaleHint(building_width_mm=16000))
    assert plan.scale.source == ScaleSource.building_width
    assert plan.scale.mm_per_px == pytest.approx(20.0)
    assert not any(r.reason == ReviewReason.scale_estimated for r in plan.review_items)

    plan = _plan(scale_hint=ScaleHint(reference=WallReference(wall_id="w1", length_mm=4000)))
    assert plan.walls[0].length == pytest.approx(4000)

    with pytest.raises(RecognitionError):
        _plan(scale_hint=ScaleHint(reference=WallReference(wall_id="w99", length_mm=1)))


def test_scale_hint_requires_exactly_one():
    with pytest.raises(ValueError):
        ScaleHint()
    with pytest.raises(ValueError):
        ScaleHint(mm_per_px=1, building_width_mm=2)
