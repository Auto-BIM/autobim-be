"""DXF 입력의 중간 결과(튜플 좌표). reader.py가 팀 Plan(pydantic)으로 바꾼다. 치수 기본값은 app.core.defaults."""
from dataclasses import dataclass, field

from app.core import defaults

EXTERIOR_THICKNESS = defaults.EXTERIOR_WALL_THICKNESS  # 단선 벽 기본 두께: 외벽 / 내벽
INTERIOR_THICKNESS = defaults.INTERIOR_WALL_THICKNESS
WALL_THICKNESS = EXTERIOR_THICKNESS
# 개구부 종류별 (폭, 높이, 바닥에서 시작 높이)
OPENING_DEFAULTS = {
    "door": (defaults.DOOR_WIDTH, defaults.DOOR_HEIGHT, 0.0),
    "window": (defaults.WINDOW_WIDTH, defaults.WINDOW_HEIGHT, defaults.WINDOW_SILL_HEIGHT),
}


@dataclass
class Wall:
    id: str
    start: tuple[float, float]
    end: tuple[float, float]
    thickness: float = WALL_THICKNESS
    confidence: float = 1.0
    kind: str = "unknown"  # exterior | interior | unknown


@dataclass
class Opening:
    id: str
    type: str  # door | window
    wall: str
    position: float  # 벽 시작점에서 개구부 중심까지의 거리
    width: float
    height: float
    sill: float
    confidence: float = 1.0


@dataclass
class Draft:
    walls: list[Wall] = field(default_factory=list)
    openings: list[Opening] = field(default_factory=list)
    unplaced: list[dict] = field(default_factory=list)  # 소속 벽을 찾지 못한 개구부 후보
    review_items: list[dict] = field(default_factory=list)  # element_id는 위 id (도면 전체는 "plan")


def make_opening(id: str, type: str, wall: str, position: float, width: float | None = None,
                 confidence: float = 1.0) -> Opening:
    w, h, sill = OPENING_DEFAULTS[type]
    return Opening(id, type, wall, position, width or w, h, sill, confidence)
