"""Apply user supplements (보충 입력) to a stored Plan — no model re-run.

The base Plan (first recognition result) is kept untouched; every regeneration replays
all supplements on it: rescale to the latest scale hint, then patches/removals/additions
in submission order. Existing element IDs never change; added elements get fresh IDs;
removed IDs are never reused.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core import defaults
from app.schemas.jobs import NewOpening, NewWall, RemovedElement, ScaleHint, SupplementRequest
from app.schemas.plan import (
    ElementKind,
    OpeningType,
    Plan,
    ReviewReason,
    Scale,
    ScaleSource,
    WallKind,
)

# review reasons that a user-supplied scale settles
_SCALE_REASONS = {ReviewReason.scale_estimated.value, ReviewReason.dimension_conflict.value}


class SupplementError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def latest_scale_hint(supplements: list[SupplementRequest]) -> ScaleHint | None:
    hints = [s.scale for s in supplements if s.scale is not None]
    return hints[-1] if hints else None


def _scale_factor(plan: Plan, hint: ScaleHint) -> tuple[float, ScaleSource]:
    if hint.mm_per_px is not None:
        if plan.scale.mm_per_px is None:
            raise SupplementError("invalid_supplement", "mm_per_px needs an image-based plan")
        return hint.mm_per_px / plan.scale.mm_per_px, ScaleSource.user
    if hint.building_width_mm is not None:
        xs = [p.x for w in plan.walls for p in (w.start, w.end)]
        width = max(xs) - min(xs) if xs else 0.0
        if width <= 0:
            raise SupplementError("invalid_supplement", "plan has no width to scale")
        return hint.building_width_mm / width, ScaleSource.building_width
    assert hint.reference is not None
    ref = next((w for w in plan.walls if w.id == hint.reference.wall_id), None)
    if ref is None:
        raise SupplementError("unknown_element", f"wall {hint.reference.wall_id!r} not found")
    return hint.reference.length_mm / ref.length, ScaleSource.user


def rescale(plan: Plan, hint: ScaleHint) -> Plan:
    """Recompute pixel-derived lengths (coordinates, positions, widths, thicknesses).

    Heights are defaults, not measurements, so they are left alone.
    """
    factor, source = _scale_factor(plan, hint)
    data = plan.model_dump(mode="json")
    for w in data["walls"]:
        for key in ("start", "end"):
            w[key] = {"x": w[key]["x"] * factor, "y": w[key]["y"] * factor}
        w["thickness"] *= factor
    for o in data["openings"]:
        o["position"] *= factor
        o["width"] *= factor
    mm_per_px = plan.scale.mm_per_px * factor if plan.scale.mm_per_px is not None else None
    data["scale"] = Scale(source=source, estimated=False, mm_per_px=mm_per_px).model_dump(
        mode="json"
    )
    data["review_items"] = [
        r
        for r in data["review_items"]
        if not (r["element_kind"] == ElementKind.plan.value and r["reason"] in _SCALE_REASONS)
    ]
    return Plan.model_validate(data)


def _next_id(prefix: str, taken: set[str]) -> str:
    nums = [int(m.group(1)) for i in taken if (m := re.fullmatch(rf"{prefix}(\d+)", i))]
    return f"{prefix}{max(nums, default=0) + 1}"


def _new_wall(new: NewWall, wall_id: str) -> dict:
    default_t = (
        defaults.EXTERIOR_WALL_THICKNESS
        if new.kind == WallKind.exterior
        else defaults.INTERIOR_WALL_THICKNESS
    )
    return {
        "id": wall_id,
        "start": new.start.model_dump(),
        "end": new.end.model_dump(),
        "thickness": new.thickness or default_t,
        "height": new.height or defaults.WALL_HEIGHT,
        "kind": new.kind.value,
    }


def _new_opening(new: NewOpening, opening_id: str) -> dict:
    door = new.type == OpeningType.door
    return {
        "id": opening_id,
        "type": new.type.value,
        "wall_id": new.wall_id,
        "position": new.position,
        "width": new.width or (defaults.DOOR_WIDTH if door else defaults.WINDOW_WIDTH),
        "height": new.height or (defaults.DOOR_HEIGHT if door else defaults.WINDOW_HEIGHT),
        "sill_height": (
            new.sill_height
            if new.sill_height is not None
            else (0.0 if door else defaults.WINDOW_SILL_HEIGHT)
        ),
    }


@dataclass(frozen=True)
class Replay:
    plan: Plan
    removed: list[RemovedElement]


def _remove(
    ids: list[str],
    walls: dict[str, dict],
    openings: dict[str, dict],
    revision: int,
) -> list[RemovedElement]:
    if unknown := [i for i in ids if i not in walls and i not in openings]:
        raise SupplementError("unknown_element", f"cannot remove unknown elements {unknown}")
    requested = set(ids)
    removed = []
    for wall_id in [i for i in ids if i in walls]:
        del walls[wall_id]
        removed.append(RemovedElement(id=wall_id, element_kind=ElementKind.wall, revision=revision))
        for oid in [o for o, op in openings.items() if op["wall_id"] == wall_id]:
            del openings[oid]
            removed.append(
                RemovedElement(
                    id=oid,
                    element_kind=ElementKind.opening,
                    revision=revision,
                    # an opening also listed explicitly counts as a direct removal
                    cascade_from=None if oid in requested else wall_id,
                )
            )
    for oid in [i for i in ids if i in openings]:
        del openings[oid]
        removed.append(RemovedElement(id=oid, element_kind=ElementKind.opening, revision=revision))
    return removed


def replay_supplements(base: Plan, supplements: list[SupplementRequest]) -> Replay:
    """Replay supplements onto the base Plan. `supplements[i]` produces revision i + 1."""
    hint = latest_scale_hint(supplements)
    plan = rescale(base, hint) if hint is not None else base
    data = plan.model_dump(mode="json")
    walls = {w["id"]: w for w in data["walls"]}
    openings = {o["id"]: o for o in data["openings"]}
    resolved: set[str] = set()
    removed: list[RemovedElement] = []

    def taken() -> set[str]:  # removed IDs stay taken forever
        return set(walls) | set(openings) | {r.id for r in removed}

    for revision, sup in enumerate(supplements, start=1):
        for patch in sup.walls:
            if patch.id not in walls:
                raise SupplementError("unknown_element", f"wall {patch.id!r} not found")
            walls[patch.id].update(patch.model_dump(mode="json", exclude={"id"}, exclude_none=True))
            resolved.add(patch.id)  # an edited element counts as confirmed
        for patch in sup.openings:
            if patch.id not in openings:
                raise SupplementError("unknown_element", f"opening {patch.id!r} not found")
            if patch.wall_id is not None and patch.wall_id not in walls:
                raise SupplementError("unknown_element", f"wall {patch.wall_id!r} not found")
            openings[patch.id].update(
                patch.model_dump(mode="json", exclude={"id"}, exclude_none=True)
            )
            resolved.add(patch.id)
        removed.extend(_remove(sup.remove, walls, openings, revision))
        for new in sup.add_walls:
            wall_id = _next_id("w", taken())
            walls[wall_id] = _new_wall(new, wall_id)
        for new in sup.add_openings:
            if new.wall_id not in walls:
                raise SupplementError("unknown_element", f"wall {new.wall_id!r} not found")
            opening_id = _next_id("o", taken())
            openings[opening_id] = _new_opening(new, opening_id)
        known = set(walls) | set(openings) | {"plan"}
        if unknown := sorted(set(sup.resolved) - known):
            raise SupplementError("unknown_element", f"cannot resolve unknown elements {unknown}")
        resolved.update(sup.resolved)

    gone = {r.id for r in removed}
    data["walls"] = list(walls.values())
    data["openings"] = list(openings.values())
    data["review_items"] = [
        r for r in data["review_items"] if r["element_id"] not in resolved | gone
    ]
    try:
        return Replay(plan=Plan.model_validate(data), removed=removed)
    except ValueError as exc:
        raise SupplementError("invalid_supplement", str(exc)) from exc


def apply_supplements(base: Plan, supplements: list[SupplementRequest]) -> Plan:
    return replay_supplements(base, supplements).plan
