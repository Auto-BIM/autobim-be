"""분류된 DXF 엔티티 → Draft (reader.py가 Plan으로 바꾼다).

벽은 두 가지로 읽는다.
 - 이중선: 서로 평행하고 벽 두께만큼 떨어져 겹치는 선 쌍 → 중심선 + 두께 (한국 도면의 일반적인 표현)
 - 단선: 짝이 없는 선 하나 → 중심선 (기본 두께)
ponytail: 짝짓기는 거리와 겹침만 본다. 벽 두께 범위 안에 평행한 선이 따로 있으면(옷장 등) 잘못 짝지어질 수 있다.
"""
import math
from collections import deque

from .classify import Prediction
from .draft import (
    EXTERIOR_THICKNESS,
    INTERIOR_THICKNESS,
    OPENING_DEFAULTS,
    Draft,
    Wall,
    make_opening,
)
from .entities import Entity

WALL_PAIR_THICKNESS = (80, 450)  # 평행선 쌍이 이 간격이면 이중선 벽으로 본다
PAIR_MIN_OVERLAP = 0.5  # 짧은 선 길이 대비 겹침 비율
SNAP = 300  # 개구부가 벽에서 이 거리 이내면 그 벽에 속한 것으로 본다 (mm)
DOOR_WIDTH_RANGE = (600, 1200)  # 이 밖의 호는 문이 아닌 것으로 본다 (가구, 위생기구 등)
WINDOW_SIZE_RANGE = (400, 6000)  # 거실 큰 창 포함


def _unit(w: Wall):
    length = math.dist(w.start, w.end)
    return (w.end[0] - w.start[0]) / length, (w.end[1] - w.start[1]) / length, length


def _project(p, wall: Wall):
    """점 p의 벽 위 투영: (벽 시작점부터 거리, 벽 직선까지 수직 거리)."""
    ux, uy, _ = _unit(wall)
    s = (p[0] - wall.start[0]) * ux + (p[1] - wall.start[1]) * uy
    d = abs(-(p[0] - wall.start[0]) * uy + (p[1] - wall.start[1]) * ux)
    return s, d


def _nearest_wall(p, walls: list[Wall]):
    best = None
    for w in walls:
        if w.start == w.end:
            continue
        s, d = _project(p, w)
        if -SNAP <= s <= math.dist(w.start, w.end) + SNAP and d <= SNAP and (best is None or d < best[2]):
            best = (w, s, d)
    return best


def _insert_on_wall(e, walls):
    """INSERT의 bbox 모서리를 가장 가까운 벽에 투영한 구간 → (벽 위 중점, 폭). 열림 호가 들어 있어 bbox 중심이 벽에서 멀어도 맞는다.
    벽이 없으면 None."""
    x0, y0, x1, y1 = e.bbox
    pts = [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]
    best = None
    for w in walls:
        if w.start == w.end:
            continue
        proj = [_project(q, w) for q in pts]
        d = min(dd for _, dd in proj)
        lo, hi = min(s for s, _ in proj), max(s for s, _ in proj)
        if d <= SNAP and hi >= -SNAP and lo <= math.dist(w.start, w.end) + SNAP:
            # 정사각형 bbox는 이웃 벽 면에도 닿는다. 벽 면 안에 닿는 벽을 먼저, 그중 bbox 중심이 벽에 가까운 쪽을 고른다
            key = (d - w.thickness / 2 > 10, _project(e.points[0], w)[1])
            if best is None or key < best[0]:
                ux, uy, _ = _unit(w)
                mid = (lo + hi) / 2
                best = (key, (w.start[0] + ux * mid, w.start[1] + uy * mid), hi - lo)
    return best and best[1:]


def _candidates(items, walls):
    """개구부 후보: (id, type, 중심, 폭 또는 None, 신뢰도)."""
    out = []
    for e, p in items:
        if p.label == "door" and e.kind == "ARC":
            hinge, a, b = e.points
            far = min((a, b), key=lambda q: (_nearest_wall(q, walls) or (None, 0, 1e9))[2])
            width = math.dist(hinge, far)
            if DOOR_WIDTH_RANGE[0] <= width <= DOOR_WIDTH_RANGE[1] and _nearest_wall(hinge, walls):
                mid = ((hinge[0] + far[0]) / 2, (hinge[1] + far[1]) / 2)
                out.append((f"o{e.id}", "door", mid, width, p.confidence))
        elif p.label == "window" and e.kind == "LINE":  # 창 레이어에 선으로 그린 창: 선의 중점, 길이 = 폭
            a, b = e.points
            width = math.dist(a, b)
            if WINDOW_SIZE_RANGE[0] <= width <= WINDOW_SIZE_RANGE[1]:
                out.append((f"o{e.id}", "window", ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), width, p.confidence))
        elif p.label == "door" and e.kind == "INSERT":  # 문 블록: 폭 범위 밖이면 기본 폭 + 확인 필요
            hit = _insert_on_wall(e, walls) if e.bbox else None
            c, width = hit or (e.points[0], e.size)
            ok = width is not None and DOOR_WIDTH_RANGE[0] <= width <= DOOR_WIDTH_RANGE[1]
            out.append((f"o{e.id}", "door", c, width if ok else None, p.confidence))
        elif p.label == "window" and e.kind == "INSERT":
            ok = e.size is not None and WINDOW_SIZE_RANGE[0] <= e.size <= WINDOW_SIZE_RANGE[1]
            out.append((f"o{e.id}", "window", e.points[0], e.size if ok else None, p.confidence))
    return out


def _merge_gaps(walls: list[Wall], cands) -> None:
    """개구부 자리에서 끊긴 같은 직선 위의 두 벽을 하나로 합친다 (상인방/창대를 만들기 위해)."""
    for _, typ, c, width, _ in cands:
        w = width or OPENING_DEFAULTS[typ][0]
        # 무한 직선이 아니라 선분 범위 안(개구부 폭의 절반까지 여유)에 있는 벽만 본다
        near = []
        for x in walls:
            if x.start == x.end:
                continue
            s, d = _project(c, x)
            if d <= SNAP and -(w / 2 + SNAP) <= s <= math.dist(x.start, x.end) + w / 2 + SNAP:
                near.append(x)
        if not near:
            continue
        ux, uy, _ = _unit(near[0])
        rel = lambda q: (q[0] - c[0]) * ux + (q[1] - c[1]) * uy
        left = right = None
        for x in near:
            vx, vy, _ = _unit(x)
            if abs(vx * uy - vy * ux) > 0.1:
                continue
            a, b = sorted((rel(x.start), rel(x.end)))
            if abs(b + w / 2) <= SNAP:
                left = x
            elif abs(a - w / 2) <= SNAP:
                right = x
        if left and right and left is not right:
            pts = sorted([left.start, left.end, right.start, right.end], key=rel)
            left.start, left.end = pts[0], pts[-1]
            walls.remove(right)


def _join_collinear(segs):
    """같은 직선 위에서 간격이 벽 두께 이하인 선들을 이어 붙인다 (T/십자 접합에서 한 면이 끊긴 이중선 대응).
    문 자리(보통 600 이상)는 합치지 않는다."""
    segs = [list(x) for x in segs]
    changed = True
    while changed:
        changed = False
        for i in range(len(segs)):
            a, b, ci = segs[i]
            n = math.dist(a, b)
            if not n:
                continue
            ux, uy = (b[0] - a[0]) / n, (b[1] - a[1]) / n
            for j in range(i + 1, len(segs)):
                c, d, cj = segs[j]
                if not math.dist(c, d):
                    continue
                if abs((d[0] - c[0]) * uy - (d[1] - c[1]) * ux) > 0.02 * math.dist(c, d):
                    continue
                if abs((c[0] - a[0]) * -uy + (c[1] - a[1]) * ux) > 5:  # 같은 직선이 아님
                    continue
                t = [0.0, n] + [(q[0] - a[0]) * ux + (q[1] - a[1]) * uy for q in (c, d)]
                gap = max(min(t[0], t[1]), min(t[2], t[3])) - min(max(t[0], t[1]), max(t[2], t[3]))
                if gap <= WALL_PAIR_THICKNESS[1]:
                    lo, hi = min(t), max(t)
                    segs[i] = [(a[0] + ux * lo, a[1] + uy * lo), (a[0] + ux * hi, a[1] + uy * hi), min(ci, cj)]
                    del segs[j]
                    changed = True
                    break
            if changed:
                break
    return [tuple(x) for x in segs]


def _pair_double_lines(segs):
    """[(a, b, 신뢰도)] → (이중선에서 만든 벽 [(시작, 끝, 두께, 신뢰도)], 짝 없는 선 목록)."""
    units = []
    for a, b, _ in segs:
        n = math.dist(a, b)
        units.append(((b[0] - a[0]) / n, (b[1] - a[1]) / n, n) if n else None)

    cands = []
    for i, (a, b, _) in enumerate(segs):
        if units[i] is None:
            continue
        ux, uy, li = units[i]
        for j in range(i + 1, len(segs)):
            if units[j] is None:
                continue
            c, d, _ = segs[j]
            vx, vy, lj = units[j]
            if abs(ux * vy - uy * vx) > 0.02:  # 평행하지 않음
                continue
            if ux * vx + uy * vy < 0:
                c, d = d, c  # 같은 방향으로 맞춘다
            side = (c[0] - a[0]) * -uy + (c[1] - a[1]) * ux  # i번 선 기준 j번 선의 부호 있는 거리
            if not WALL_PAIR_THICKNESS[0] <= abs(side) <= WALL_PAIR_THICKNESS[1]:
                continue
            sc = (c[0] - a[0]) * ux + (c[1] - a[1]) * uy
            sd = (d[0] - a[0]) * ux + (d[1] - a[1]) * uy
            overlap = min(li, sd) - max(0.0, sc)
            if overlap >= PAIR_MIN_OVERLAP * min(li, lj):
                cands.append((overlap, i, j, side, sc, sd, li, lj))

    used, walls = set(), []
    # 겹침 비율이 큰 쌍을 먼저, 같으면 간격이 좁은 쌍을 먼저 (입력 순서에 결과가 좌우되지 않게)
    order = sorted(cands, key=lambda c: (-round(c[0] / min(c[6], c[7]), 2), abs(c[3])))
    for overlap, i, j, side, sc, sd, li, lj in order:
        if i in used or j in used:
            continue
        used |= {i, j}
        a, (ux, uy, _) = segs[i][0], units[i]
        tol = WALL_PAIR_THICKNESS[1]
        # 두 선 끝점의 평균 = 모서리 중심 (L자 접합이 맞는다). 끝이 많이 다르면 겹치는 구간의 끝을 쓴다
        s0 = sc / 2 if abs(sc) <= tol else max(0.0, sc)
        s1 = (li + sd) / 2 if abs(li - sd) <= tol else min(li, sd)
        nx, ny = -uy, ux
        origin = (a[0] + nx * side / 2, a[1] + ny * side / 2)  # 두 선의 한가운데
        walls.append(((origin[0] + ux * s0, origin[1] + uy * s0), (origin[0] + ux * s1, origin[1] + uy * s1),
                      abs(side), min(segs[i][2], segs[j][2])))
    return walls, [segs[k] for k in range(len(segs)) if k not in used]


def _review(element_id, kind, reason, message):
    return {"element_id": element_id, "element_kind": kind, "reason": reason, "message": message, "confidence": 0.5}


MAX_CELLS = 500_000


def wall_kinds(walls: list[Wall]) -> tuple[list[str], bool]:
    """벽마다 exterior | interior. 벽을 격자에 칠하고 격자 가장자리에서 흘러 닿는 빈 공간을 '바깥'으로 본다(팀 이미지 경로 R7과 같은 기준).
    벽 양쪽을 길이의 25/50/75% 지점에서 보아 한 점이라도 바깥이면 외벽이다.
    돌려주는 값: (벽별 종류, 양쪽이 모두 바깥인 벽이 있는지). 후자는 외곽이 닫히지 않은 도면의 신호다.
    ponytail: 셀(두께의 절반 정도)보다 좁은 틈은 막힌 것으로 본다. 도면이 너무 커서 셀이 가장 얇은 벽보다 커지면 믿을 수 없어 전부 외벽으로 둔다(확인 필요가 남는다)."""
    xs = [v for w in walls for v in (w.start[0], w.end[0])]
    ys = [v for w in walls for v in (w.start[1], w.end[1])]
    tmax = max(w.thickness for w in walls)
    cell = max(min(w.thickness for w in walls) / 2,
               math.sqrt((max(xs) - min(xs) + 4 * tmax) * (max(ys) - min(ys) + 4 * tmax) / MAX_CELLS))
    if cell > min(w.thickness for w in walls):
        return ["exterior"] * len(walls), True
    margin = max(2 * tmax, 3 * cell)  # 바깥 테두리는 벽·탐침이 닿지 않게 셀 몇 개 이상 비운다
    x0, y0 = min(xs) - margin, min(ys) - margin
    nx_mm, ny_mm = max(xs) + margin - x0, max(ys) + margin - y0
    nx, ny = int(nx_mm / cell) + 1, int(ny_mm / cell) + 1
    solid = bytearray(nx * ny)

    def index(x, y):
        i, j = int((x - x0) / cell), int((y - y0) / cell)
        return j * nx + i if 0 <= i < nx and 0 <= j < ny else None

    for w in walls:  # 끝을 두께/2 늘려 모서리를 닫고, 셀의 절반 간격으로 찍어 구멍이 없게 한다
        ux, uy, length = _unit(w)
        step, half = cell / 2, w.thickness / 2
        for a in range(int((length + w.thickness) / step) + 1):
            s = -half + a * step
            for b in range(int(w.thickness / step) + 1):
                t = -half + b * step
                k = index(w.start[0] + ux * s - uy * t, w.start[1] + uy * s + ux * t)
                if k is not None:
                    solid[k] = 1
    outside = bytearray(nx * ny)
    queue = deque(k for k in range(nx * ny) if not solid[k] and (k % nx in (0, nx - 1) or k // nx in (0, ny - 1)))
    for k in queue:
        outside[k] = 1
    while queue:
        k = queue.popleft()
        i, j = k % nx, k // nx
        for ni, nj in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
            if 0 <= ni < nx and 0 <= nj < ny and not solid[nj * nx + ni] and not outside[nj * nx + ni]:
                outside[nj * nx + ni] = 1
                queue.append(nj * nx + ni)

    kinds, floating = [], False
    for w in walls:
        ux, uy, length = _unit(w)
        off = w.thickness / 2 + 1.5 * cell
        sides = [
            any((k := index(w.start[0] + ux * length * f - uy * off * side, w.start[1] + uy * length * f + ux * off * side))
                is not None and outside[k] for f in (0.25, 0.5, 0.75))
            for side in (-1, 1)
        ]
        kinds.append("exterior" if any(sides) else "interior")
        floating = floating or all(sides)
    return kinds, floating


def plan_from_entities(items: list[tuple[Entity, Prediction]], scale_estimated: bool = False) -> Draft:
    """scale_estimated: 단위를 파일에서 읽지 못해 mm로 가정했거나 보정한 경우 (확인 필요 요소를 남긴다)."""
    plan = Draft()
    if scale_estimated:
        plan.review_items.append(_review("plan", "plan", "scale_estimated",
                                         "DXF에 단위($INSUNITS)가 없거나 좌표와 맞지 않아 mm로 가정했습니다"))
    segs = []
    for e, p in items:
        if p.label == "wall" and e.kind in ("LINE", "POLYLINE"):
            segs += [(a, b, p.confidence) for a, b in zip(e.points, e.points[1:])]
    doubles, singles = _pair_double_lines(_join_collinear(segs))
    if doubles:  # 문틀 막음선 등 두께 이하의 짧은 단선은 벽이 아니다
        singles = [s for s in singles if math.dist(s[0], s[1]) > WALL_PAIR_THICKNESS[1]]
    for start, end, thickness, conf in doubles:
        plan.walls.append(Wall(f"w{len(plan.walls)}", start, end, thickness=thickness, confidence=conf))
    single_ids = []
    for a, b, conf in singles:
        single_ids.append(f"w{len(plan.walls)}")
        plan.walls.append(Wall(single_ids[-1], a, b, confidence=conf))

    cands = _candidates(items, plan.walls)
    _merge_gaps(plan.walls, cands)
    for id_, typ, c, width, conf in cands:
        hit = _nearest_wall(c, plan.walls)
        if hit is None:  # 버리지 않고 기록해 사용자에게 확인을 요청한다
            plan.unplaced.append({"id": id_, "type": typ, "center": c, "width": width})
            continue
        wall, s, _ = hit
        length = math.dist(wall.start, wall.end)
        w = width or OPENING_DEFAULTS[typ][0]
        half = min(w / 2, length / 2)  # 개구부는 host 벽 범위 안에 둔다
        plan.openings.append(make_opening(id_, typ, wall.id, min(max(s, half), length - half), width, conf))
        if width is None:
            plan.review_items.append(_review(id_, "opening", "default_value_applied", f"{typ} 폭을 읽지 못해 기본값을 적용했습니다"))
    kinds, floating = wall_kinds(plan.walls) if plan.walls else ([], False)
    for w, kind in zip(plan.walls, kinds):
        w.kind = kind
        if w.id in single_ids:  # 단선 벽의 기본 두께는 종류에 따른다. 이중선은 실측을 유지한다
            w.thickness = EXTERIOR_THICKNESS if kind == "exterior" else INTERIOR_THICKNESS
    if len(plan.walls) > 1 and (floating or set(kinds) == {"interior"}):  # 양쪽이 바깥인 벽이 있거나 외벽이 하나도 없으면 외곽이 닫히지 않은 것: 판정을 믿기 어렵다
        plan.review_items.append(_review("plan", "plan", "other", "외벽/내벽을 구분하지 못했습니다(외곽이 닫혀 있지 않거나 벽이 하나로만 이뤄짐)"))
    alive = {w.id for w in plan.walls}  # 개구부 자리에서 합쳐지며 사라진 벽은 제외
    plan.review_items += [_review(i, "wall", "default_value_applied", "단선 벽이라 기본 두께(외벽 200 / 내벽 120)를 적용했습니다")
                          for i in single_ids if i in alive]
    return plan
