"""DXF path (design.md §4): .dxf -> Plan.

ezdxf로 읽고 레이어·블록 이름으로 벽·문·창을 분류한 뒤(classify.py) 이중선 벽을 중심선 + 두께로 병합한다(extract.py).
단위는 $INSUNITS로 mm 환산하고, 단위가 없으면 mm로 가정해 확인 필요 요소를 남긴다.
"""

from __future__ import annotations

import os
import tempfile

import ezdxf

from app.core import defaults
from app.dxf_input.classify import KEYWORDS, classify
from app.dxf_input.entities import read_dxf
from app.dxf_input.extract import plan_from_entities
from app.recognition.pipeline import RecognitionError
from app.schemas.plan import (
    ElementKind,
    Opening,
    OpeningType,
    Plan,
    PlanSource,
    Point2D,
    ReviewItem,
    ReviewReason,
    Scale,
    ScaleSource,
    SourceType,
    Wall,
    WallKind,
)


def dxf_to_plan(
    data: bytes, *, filename: str | None = None, rules: dict[str, tuple[str, ...]] = KEYWORDS
) -> Plan:
    fd, path = tempfile.mkstemp(suffix=".dxf")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        dxf = read_dxf(path)
    except (ezdxf.DXFError, OSError, ValueError, UnicodeError) as exc:
        raise RecognitionError("invalid_dxf", f"cannot read the DXF file: {exc}") from exc
    finally:
        os.unlink(path)

    estimated = dxf.unit_assumed or dxf.unit_corrected
    draft = plan_from_entities([(e, classify(e, rules)) for e in dxf.entities], scale_estimated=estimated)
    if not draft.walls:
        raise RecognitionError("no_walls", "no walls found on the wall layers of the DXF")

    # Draft IDs (entity based) -> contract IDs w1.., o1.. in output order
    wid = {w.id: f"w{i + 1}" for i, w in enumerate(draft.walls)}
    oid = {o.id: f"o{i + 1}" for i, o in enumerate(draft.openings)}
    ids = {**wid, **oid, "plan": "plan"}
    walls = [
        Wall(
            id=wid[w.id], start=Point2D(x=w.start[0], y=w.start[1]), end=Point2D(x=w.end[0], y=w.end[1]),
            thickness=w.thickness, height=defaults.WALL_HEIGHT, kind=WallKind(w.kind), confidence=w.confidence,
        )
        for w in draft.walls
    ]
    openings = [
        Opening(
            id=oid[o.id], type=OpeningType(o.type), wall_id=wid[o.wall], position=o.position, width=o.width,
            height=o.height, sill_height=o.sill, confidence=o.confidence,
        )
        for o in draft.openings
    ]
    review = [
        ReviewItem(
            element_id=ids[r["element_id"]], element_kind=ElementKind(r["element_kind"]),
            reason=ReviewReason(r["reason"]), message=r["message"], confidence=r["confidence"],
        )
        for r in draft.review_items
    ]
    review += [
        ReviewItem(
            element_id="plan", element_kind=ElementKind.plan, reason=ReviewReason.unattached_opening,
            message=f"{u['type']} at ({u['center'][0]:.0f}, {u['center'][1]:.0f}) mm is not near any wall",
            confidence=0.5,
        )
        for u in draft.unplaced
    ]
    return Plan(
        source=PlanSource(type=SourceType.dxf, filename=filename),
        scale=Scale(source=ScaleSource.source_units, estimated=estimated),
        walls=walls, openings=openings, review_items=review,
    )
