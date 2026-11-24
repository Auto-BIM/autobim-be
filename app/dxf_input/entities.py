"""DXF → 평탄화된 엔티티 목록 (mm 단위로 변환). 이후 분류/기하 단계의 공통 입력."""
from dataclasses import dataclass

import ezdxf
from ezdxf import bbox, units

MIN_PLAN_SPAN_MM = 100  # 이보다 작으면 단위가 잘못 표기된 것으로 본다


@dataclass
class Entity:
    id: int
    kind: str  # LINE | POLYLINE | ARC | INSERT
    layer: str
    points: list[tuple[float, float]]  # ARC: 중심, 시작점, 끝점 / INSERT: 블록 bbox 중심
    block: str | None = None  # INSERT일 때 블록 이름
    size: float | None = None  # INSERT일 때 블록 bbox의 긴 변
    bbox: tuple[float, float, float, float] | None = None  # INSERT일 때 블록 bbox (x0, y0, x1, y1)


@dataclass
class DxfData:
    entities: list[Entity]
    unit_assumed: bool = False  # $INSUNITS가 없어 mm로 가정함
    unit_corrected: bool = False  # 표기 단위와 좌표 크기가 어긋나 m로 보정함


def _as_arc(pts):
    """열린 폴리라인의 점들이 원호 위에 있으면 [중심, 시작점, 끝점]을, 아니면 None을 돌려준다.
    짧은 직선으로 근사한 호는 점이 6개 이상이고, 반지름 편차가 2% 이하이며, 각도가 60~120도인 경우만 호로 본다."""
    if len(pts) < 6:
        return None
    import numpy as np

    a = np.array(pts, dtype=float)
    m = np.c_[2 * a[:, 0], 2 * a[:, 1], np.ones(len(a))]
    sol, *_ = np.linalg.lstsq(m, (a ** 2).sum(axis=1), rcond=None)
    cx, cy = sol[0], sol[1]
    r = float(np.sqrt(max(sol[2] + cx * cx + cy * cy, 0.0)))
    if r <= 0 or np.abs(np.hypot(a[:, 0] - cx, a[:, 1] - cy) - r).max() > 0.02 * r:
        return None
    v0, v1 = a[0] - (cx, cy), a[-1] - (cx, cy)
    sweep = np.degrees(np.arccos(np.clip(v0 @ v1 / (np.linalg.norm(v0) * np.linalg.norm(v1)), -1, 1)))
    if not 60 <= sweep <= 120:
        return None
    return [(float(cx), float(cy)), tuple(map(float, a[0])), tuple(map(float, a[-1]))]


def _add_missing_subclass(text: str) -> str:
    """일부 도구가 만든 DXF는 LWPOLYLINE에 서브클래스 표시(100/AcDbEntity, 100/AcDbPolyline)가 빠져 있다. 레이어(8) 뒤에 넣어 준다."""
    lines = text.splitlines()
    out, i, in_lw, has_sub = [], 0, False, True
    while i + 1 < len(lines):
        code, val = lines[i].strip(), lines[i + 1]
        if code == "0":
            in_lw = val.strip() == "LWPOLYLINE"
            has_sub = any(lines[j].strip() == "100" and lines[j + 1].strip() == "AcDbPolyline"
                          for j in range(i + 2, min(i + 40, len(lines) - 1), 2) if lines[j].strip() != "0")
        out += [lines[i], lines[i + 1]]
        if in_lw and code == "0" and not has_sub:
            out += ["100", "AcDbEntity"]
        if in_lw and code == "8" and not has_sub:
            out += ["100", "AcDbPolyline"]
        i += 2
    return chr(10).join(out + lines[i:]) + chr(10)


def _read_doc(path: str):
    try:
        return ezdxf.readfile(path)
    except ezdxf.DXFStructureError:
        with open(path, encoding="utf-8", errors="replace") as f:
            fixed = _add_missing_subclass(f.read())
        import io

        return ezdxf.read(io.StringIO(fixed))


def read_entities(path: str) -> list[Entity]:
    return read_dxf(path).entities


def read_dxf(path: str) -> DxfData:
    doc = _read_doc(path)
    # 단위 미지정(0)이면 mm로 가정
    k = units.conversion_factor(doc.units, units.MM) if doc.units else 1.0

    def p(x, y):
        return (x * k, y * k)

    out: list[Entity] = []
    for i, e in enumerate(doc.modelspace()):
        t = e.dxftype()
        layer = e.dxf.layer
        if t == "LINE":
            s, d = e.dxf.start, e.dxf.end
            out.append(Entity(i, "LINE", layer, [p(s.x, s.y), p(d.x, d.y)]))
        elif t == "LWPOLYLINE":
            pts = [p(x, y) for x, y in e.get_points("xy")]
            arc = None if e.closed else _as_arc(pts)
            if arc:  # 짧은 직선으로 근사한 호 (문 열림 궤적 등)
                out.append(Entity(i, "ARC", layer, arc))
                continue
            if e.closed and pts:
                pts.append(pts[0])
            out.append(Entity(i, "POLYLINE", layer, pts))
        elif t == "ARC":
            c, a, b = e.dxf.center, e.start_point, e.end_point
            out.append(Entity(i, "ARC", layer, [p(c.x, c.y), p(a.x, a.y), p(b.x, b.y)]))
        elif t == "INSERT":
            box = bbox.extents(e.virtual_entities())
            if box.has_data:
                c, size = box.center, max(box.size.x, box.size.y) * k
                out.append(Entity(i, "INSERT", layer, [p(c.x, c.y)], block=e.dxf.name, size=size,
                                  bbox=(box.extmin.x * k, box.extmin.y * k, box.extmax.x * k, box.extmax.y * k)))
            else:
                ins = e.dxf.insert
                out.append(Entity(i, "INSERT", layer, [p(ins.x, ins.y)], block=e.dxf.name))

    # 단위 표기가 틀린 도면(mm로 적혀 있지만 좌표는 m) 보정: 건물 전체가 10cm 안에 들어오면 m로 본다
    xs = [pt[0] for e in out for pt in e.points]
    ys = [pt[1] for e in out for pt in e.points]
    corrected = bool(xs) and max(max(xs) - min(xs), max(ys) - min(ys)) < MIN_PLAN_SPAN_MM
    if corrected:
        for e in out:
            e.points = [(x * 1000, y * 1000) for x, y in e.points]
            e.size = e.size * 1000 if e.size else e.size
            e.bbox = tuple(v * 1000 for v in e.bbox) if e.bbox else None
    return DxfData(out, unit_assumed=not doc.units, unit_corrected=corrected)
