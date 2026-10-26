import pytest
from pydantic import ValidationError

from app.schemas.plan import SCHEMA_VERSION, Plan


def _plan(**overrides) -> dict:
    data = {
        "source": {"type": "image"},
        "scale": {"source": "dimension", "estimated": False, "mm_per_px": 10},
        "walls": [
            {"id": "w1", "start": {"x": 0, "y": 0}, "end": {"x": 4000, "y": 0},
             "thickness": 200, "height": 2400},
        ],
        "openings": [
            {"id": "o1", "type": "door", "wall_id": "w1", "position": 1000,
             "width": 900, "height": 2100},
        ],
        "review_items": [
            {"element_id": "o1", "element_kind": "opening", "reason": "low_confidence",
             "confidence": 0.4},
        ],
    }
    data.update(overrides)
    return data


def test_valid_plan_defaults():
    plan = Plan.model_validate(_plan())
    assert plan.schema_version == SCHEMA_VERSION == "1.0"
    assert plan.units == "mm"
    assert plan.walls[0].length == 4000
    assert plan.openings[0].sill_height == 0


def test_json_roundtrip(fake_plan):
    assert Plan.model_validate_json(fake_plan.model_dump_json()) == fake_plan


def test_rejects_other_schema_version():
    with pytest.raises(ValidationError):
        Plan.model_validate(_plan(schema_version="2.0"))


def test_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        Plan.model_validate(_plan(extra_field=1))


def test_rejects_opening_on_unknown_wall():
    bad = _plan()
    bad["openings"][0]["wall_id"] = "nope"
    with pytest.raises(ValidationError, match="unknown wall"):
        Plan.model_validate(bad)


def test_rejects_duplicate_ids():
    bad = _plan()
    bad["openings"][0]["id"] = "w1"
    with pytest.raises(ValidationError, match="duplicate"):
        Plan.model_validate(bad)


def test_rejects_review_item_for_unknown_element():
    bad = _plan()
    bad["review_items"][0]["element_id"] = "ghost"
    with pytest.raises(ValidationError, match="unknown element"):
        Plan.model_validate(bad)


@pytest.mark.parametrize("confidence", [-0.1, 1.5])
def test_review_confidence_range(confidence):
    bad = _plan()
    bad["review_items"][0]["confidence"] = confidence
    with pytest.raises(ValidationError):
        Plan.model_validate(bad)


def test_rejects_zero_length_wall():
    bad = _plan()
    bad["walls"][0]["end"] = {"x": 0, "y": 0}
    with pytest.raises(ValidationError, match="zero length"):
        Plan.model_validate(bad)
