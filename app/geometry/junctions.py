"""Wall junctions (design.md §5): how far each wall end is extended (+) or trimmed (-), and where
other walls rest on a wall.

A junction is a wall end whose centerline point lies on another wall's centerline (1 mm).
Deterministic: walls are ordered by thickness (thick first), then ID length, then ID (w2 < w10).
"Within 1 mm" is always the straight-line distance: between two ends, and from an end to a centerline.
- End on the interior of another wall (T, +): trimmed until it no longer overlaps that wall.
- Ends meeting at one point (L, corners, 3+ walls): the first wall is the master and is extended
  backwards over the node so its square end reaches the outer corner of the others (half their
  thickness when perpendicular, the exact corner distance otherwise, capped for acute angles).
  Every other wall is trimmed until it no longer overlaps the walls before it (as they are at
  this node; a wall already trimmed away there is skipped), so the walls of a node touch each
  other.
- No mitre. Oblique joints leave a wedge gap. Below 90° the master's square end sticks out past
  the outer faces. 3+ walls leave a mitre hole between neighbouring arms, at most
  t_max / sin(θ_min / 2) wide (t_max: thickest wall of the node, θ_min: smallest angle between
  neighbouring arms; 120° Y: t / 2). Nearly straight ends (> ~179.4°) butt with a ~1 mm gap.
- Walls folded back onto another (< ~0.6°, e.g. one wall recognised twice) are cut up to its far
  end. A wall is never trimmed below MIN_LEN: a wall that lies wholly inside the others (e.g. a
  300 mm stub in an acute wedge) leaves a MIN_LEN sliver at its far tip that touches nothing,
  but it no longer keeps its neighbours away.
- Zones: wall-local intervals (end-face corners projected on the wall's axis) where the end face
  of a later wall touches it. Openings never cut there. An opening that spans a zone is cut
  around it, so 3D and DXF show it split while plan.json keeps its width (a 900 mm door over a T
  junction: 390 + 390 mm). At oblique joints that is only part of
  the wedge gap; a wall touching only another wall's end keeps a stretch of that end.
"""

from __future__ import annotations

import math

from app.schemas.plan import Wall

TOL = 1.0  # mm
MIN_LEN = 1.0  # mm
_PARALLEL = 0.01  # |sin| below this (~0.6°) a wall pointing the same way is 'folded back'
_MAX_GROW = 3.0  # acute corners: the master's extension is capped at this many thicknesses


def _key(w: Wall) -> tuple[float, int, str]:
    return (-w.thickness, len(w.id), w.id)  # thick first; shorter IDs first (w2 < w10)


def unit(w: Wall) -> tuple[float, float]:
    """Unit vector along a wall's centerline, start -> end."""
    return (w.end.x - w.start.x) / w.length, (w.end.y - w.start.y) / w.length


def _touches(p: tuple[float, float], w: Wall) -> bool:
    """p lies within TOL (straight-line distance, like the endpoint clustering) of w's centerline."""
    ux, uy = unit(w)
    dx, dy = p[0] - w.start.x, p[1] - w.start.y
    s = min(max(dx * ux + dy * uy, 0.0), w.length)
    return math.hypot(dx - ux * s, dy - uy * s) <= TOL


def _angle(d: tuple[float, float], master_dir: tuple[float, float]) -> tuple[float, float]:
    """(sin, cos) of the angle between two outward directions; sin >= 0."""
    return abs(d[0] * master_dir[1] - d[1] * master_dir[0]), d[0] * master_dir[0] + d[1] * master_dir[1]


def _clear(d, t, axis, rect_t, lo, hi):
    """Cut from a wall end (outward direction d, thickness t, at the node) so that it no longer
    overlaps a rectangle of thickness rect_t spanning [lo, hi] along `axis` (node-relative).

    Exact: the rectangle is clipped to the wall's strip |q·n| <= t/2 and the cut is the largest
    q·d of what is left. This covers leaving the rectangle's strip, running past its end, and
    walls folded back onto it (cut up to the rectangle's far end)."""
    ax, ay = axis
    h = rect_t / 2
    poly = [(lo * ax + h * ay, lo * ay - h * ax), (hi * ax + h * ay, hi * ay - h * ax),
            (hi * ax - h * ay, hi * ay + h * ax), (lo * ax - h * ay, lo * ay + h * ax)]
    nx, ny = -d[1], d[0]
    for sgn in (1, -1):  # clip to sgn * q·n <= t/2
        out = []
        for k, a in enumerate(poly):
            b = poly[(k + 1) % len(poly)]
            fa = sgn * (a[0] * nx + a[1] * ny) - t / 2
            fb = sgn * (b[0] * nx + b[1] * ny) - t / 2
            if fa <= 1e-9:
                out.append(a)
            if (fa > 1e-9) != (fb > 1e-9):
                r = fa / (fa - fb)
                out.append((a[0] + (b[0] - a[0]) * r, a[1] + (b[1] - a[1]) * r))
        poly = out
        if not poly:
            return 0.0
    return max(0.0, max(q[0] * d[0] + q[1] * d[1] for q in poly))


def wall_junctions(
    walls: list[Wall],
) -> tuple[dict[str, tuple[float, float]], dict[str, list[tuple[float, float]]]]:
    """(extensions, zones). Extensions: wall ID -> (extension at start, at end) in mm along the
    centerline. Zones: wall ID -> wall-local s intervals (from the wall's start) where other walls'
    end faces rest on this wall (their final end corners projected on this wall's axis);
    openings must not cut there, so corners and branch roots stay supported."""
    ordered = sorted(walls, key=_key)
    ext = {w.id: [0.0, 0.0] for w in ordered}
    ends = [(w, i, (w.start.x, w.start.y) if i == 0 else (w.end.x, w.end.y))
            for w in ordered for i in (0, 1)]

    clusters: list[list[tuple[Wall, int, tuple[float, float]]]] = []
    for e in ends:
        # ponytail: each end joins the first cluster whose first end is within TOL (no chaining)
        for c in clusters:
            if math.dist(c[0][2], e[2]) <= TOL:
                c.append(e)
                break
        else:
            clusters.append([e])

    def outward(w: Wall, i: int) -> tuple[float, float]:
        ux, uy = unit(w)
        return (ux, uy) if i == 0 else (-ux, -uy)

    nodes = []  # (cluster, through walls)
    for c in clusters:
        member_ids = {w.id for w, _, _ in c}
        through = [b for b in ordered if b.id not in member_ids and _touches(c[0][2], b)]
        nodes.append((c, through))

    # Pass 1: the master of every plain corner grows over the node (depends on angles only).
    for c, through in nodes:
        if through or len(c) < 2:
            continue
        mw, mi, _ = c[0]
        md = outward(mw, mi)
        for w, i, _ in c[1:]:
            sin, cos = _angle(outward(w, i), md)
            if sin > 1e-6 and (cos < 0 or sin >= _PARALLEL):  # not folded back; near-straight -> ~0
                corner = (w.thickness / 2 + mw.thickness / 2 * cos) / sin
                ext[mw.id][mi] = max(
                    ext[mw.id][mi], min(corner, _MAX_GROW * max(w.thickness, mw.thickness))
                )

    # Pass 2: every other wall is trimmed to clear the through walls and the earlier members
    # (thickest/lowest ID first) at its node. An earlier member counts as it really is at this
    # node (its trim here is final); extents at other nodes are not final yet, so nominal.
    for c, through in nodes:
        if not through and len(c) < 2:
            continue
        for j, (w, i, _) in enumerate(c):
            if not through and j == 0:
                continue
            d, trim = outward(w, i), 0.0
            for b in through:
                bx, by = unit(b)
                s0 = (c[0][2][0] - b.start.x) * bx + (c[0][2][1] - b.start.y) * by
                lo = -(s0 + max(ext[b.id][0], 0.0))
                hi = b.length + max(ext[b.id][1], 0.0) - s0
                trim = max(trim, _clear(d, w.thickness, (bx, by), b.thickness, lo, hi))
            for mw, mi, _ in c[:j]:
                lo, hi = -ext[mw.id][mi], mw.length + max(ext[mw.id][1 - mi], 0.0)
                if hi - lo < MIN_LEN:
                    continue  # trimmed away at this node: nothing left to clear
                trim = max(trim, _clear(d, w.thickness, outward(mw, mi), mw.thickness, lo, hi))
            ext[w.id][i] = -trim

    out = {}
    for w in walls:
        e0, e1 = ext[w.id]
        target = min(MIN_LEN, w.length)
        if w.length + e0 + e1 < target:  # trimmed away: keep a sliver, never restore the overlap
            neg = min(e0, 0.0) + min(e1, 0.0)
            f = (target - w.length) / neg if neg < 0 else 0.0
            e0, e1 = min(e0, 0.0) * f, min(e1, 0.0) * f
        out[w.id] = (e0, e1)

    # Zones: where the end faces of later walls touch a wall (see pass 2): the end-face corners
    # projected on that wall's axis. Openings must not cut there.
    def rest(b: Wall, w: Wall, i: int, p) -> list[float]:
        """Projections on b's axis of w's end-face corners, if that face touches b's solid."""
        bx, by = unit(b)
        d, k, h = outward(w, i), -out[w.id][i], w.thickness / 2
        loc = []
        for sgn in (-1, 1):
            x = p[0] + d[0] * k - d[1] * h * sgn - b.start.x
            y = p[1] + d[1] * k + d[0] * h * sgn - b.start.y
            loc.append((x * bx + y * by, -x * by + y * bx))
        lo, hi = -out[b.id][0], b.length + out[b.id][1]

        def dist(u: float) -> float:  # from the point at fraction u along the face to b's solid
            x, y = loc[0][0] + (loc[1][0] - loc[0][0]) * u, loc[0][1] + (loc[1][1] - loc[0][1]) * u
            return math.hypot(max(0.0, lo - x, x - hi), max(0.0, abs(y) - b.thickness / 2))

        a, c = 0.0, 1.0
        for _ in range(40):  # ponytail: ternary search, the distance is convex along the face
            m1, m2 = a + (c - a) / 3, c - (c - a) / 3
            a, c = (a, m2) if dist(m1) < dist(m2) else (m1, c)
        return [s_ for s_, _ in loc] if dist((a + c) / 2) <= TOL else []

    zones: dict[str, list[tuple[float, float]]] = {w.id: [] for w in walls}
    for c, through in nodes:
        for b, members in [(b, c) for b in through] + [(c[k][0], c[k + 1:]) for k in range(len(c))]:
            lo, hi = -out[b.id][0], b.length + out[b.id][1]
            for w, i, p in members:  # one zone per wall (a swallowed sliver must not widen another's)
                proj = rest(b, w, i, p)
                if not proj or max(proj) <= min(proj):
                    continue
                z0, z1 = min(proj), max(proj)
                if z1 <= lo + TOL:  # touches only b's end face: keep a stretch of it as wide as the face
                    z0, z1 = lo, lo + z1 - z0
                elif z0 >= hi - TOL:
                    z0, z1 = hi - (z1 - z0), hi
                zones[b.id].append((z0, z1))
    return out, zones
