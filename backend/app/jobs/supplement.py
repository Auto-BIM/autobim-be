"""Apply user supplements (보충 입력) to a Plan."""

from __future__ import annotations

from app.recognition.pipeline import RecognitionError
from app.schemas.jobs import ScaleHint, SupplementRequest
from app.schemas.plan import Plan


def latest_scale_hint(supplements: list[SupplementRequest]) -> ScaleHint | None:
    hints = [s.scale for s in supplements if s.scale is not None]
    return hints[-1] if hints else None


def apply_supplements(plan: Plan, supplements: list[SupplementRequest]) -> Plan:
    """Apply wall/opening patches and resolutions cumulatively, in submission order."""
    data = plan.model_dump()
    walls = {w["id"]: w for w in data["walls"]}
    openings = {o["id"]: o for o in data["openings"]}
    resolved: set[str] = set()
    for sup in supplements:
        for patch in sup.walls:
            if patch.id not in walls:
                raise RecognitionError("unknown_element", f"wall {patch.id!r} not found")
            walls[patch.id].update(patch.model_dump(exclude={"id"}, exclude_none=True))
        for patch in sup.openings:
            if patch.id not in openings:
                raise RecognitionError("unknown_element", f"opening {patch.id!r} not found")
            openings[patch.id].update(patch.model_dump(exclude={"id"}, exclude_none=True))
        resolved.update(sup.resolved)
        # an edited element counts as confirmed
        resolved.update(p.id for p in sup.walls)
        resolved.update(p.id for p in sup.openings)
    data["review_items"] = [r for r in data["review_items"] if r["element_id"] not in resolved]
    try:
        return Plan.model_validate(data)
    except ValueError as exc:
        raise RecognitionError("invalid_supplement", str(exc)) from exc
