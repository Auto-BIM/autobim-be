"""Union wall-local rectangles before extruding: no hidden faces between pieces.

The grid uses exact break coordinates from build3d._pieces. It is independent of
wall rotation and introduces no geometry dependency or geometric tolerance.
"""
from collections import defaultdict


def rectangle_profiles(rectangles):
    """Return (outer, holes) polygons for each edge-connected component.

    Coordinates are wall-local (distance, elevation). Rings do not repeat the
    first vertex. Point-only contacts cannot form a manifold profile and raise
    ValueError instead of silently writing an invalid IFC solid.
    """
    if not rectangles:
        return []
    xs = sorted({x for x0, x1, _, _ in rectangles for x in (x0, x1)})
    zs = sorted({z for _, _, z0, z1 in rectangles for z in (z0, z1)})
    xi, zi = {v: i for i, v in enumerate(xs)}, {v: i for i, v in enumerate(zs)}
    cells = set()
    for x0, x1, z0, z1 in rectangles:
        cells.update((i, j) for i in range(xi[x0], xi[x1]) for j in range(zi[z0], zi[z1]))
    profiles = []
    while cells:
        start = min(cells)
        cells.remove(start)
        component, todo = {start}, [start]
        while todo:
            i, j = todo.pop()
            adjacent = {(i-1, j), (i+1, j), (i, j-1), (i, j+1)} & cells
            cells -= adjacent
            component.update(adjacent)
            todo.extend(adjacent)
        edges = set()
        for i, j in component:
            corners = [(i, j), (i+1, j), (i+1, j+1), (i, j+1)]
            for a, b in zip(corners, corners[1:] + corners[:1]):
                if (b, a) in edges:
                    edges.remove((b, a))
                else:
                    edges.add((a, b))
        following = defaultdict(list)
        for a, b in edges:
            following[a].append(b)
        if any(len(v) != 1 for v in following.values()):
            raise ValueError("Wall profile touches itself at a point; repair the opening layout")
        rings = []
        while edges:
            a, b = min(edges)
            ring = [a]
            edges.remove((a, b))
            while b != a:
                ring.append(b)
                c = following[b][0]
                edges.remove((b, c))
                b = c
            # Keep only corners. A long coplanar wall face should be one face.
            ring = [p for k, p in enumerate(ring)
                    if (p[0]-ring[k-1][0])*(ring[(k+1) % len(ring)][1]-p[1])
                    != (p[1]-ring[k-1][1])*(ring[(k+1) % len(ring)][0]-p[0])]
            points = [(xs[i], zs[j]) for i, j in ring]
            area = sum(a[0]*b[1]-b[0]*a[1]
                       for a, b in zip(points, points[1:]+points[:1])) / 2
            rings.append((area, points))
        outer = [p for area, p in rings if area > 0]
        holes = [p for area, p in rings if area < 0]
        if len(outer) != 1:
            raise ValueError("Wall profile has no unambiguous outer boundary")
        profiles.append((outer[0], holes))
    return profiles


def swept_wall_solids(f, wall, rectangles, depth):
    """Create IFC millimetre solids by extruding the wall elevation across depth."""
    import math

    def unit(w):
        length = math.dist(w.start, w.end)
        return (w.end[0] - w.start[0]) / length, (w.end[1] - w.start[1]) / length

    ux, uy = unit(wall)
    nx, ny = -uy, ux
    origin = f.createIfcCartesianPoint((float(wall.start[0]+nx*depth/2),
                                        float(wall.start[1]+ny*depth/2), 0.))
    # Profile X = wall direction, Y = elevation. X cross Y points along -normal.
    position = f.createIfcAxis2Placement3D(origin,
        f.createIfcDirection((-float(nx), -float(ny), 0.)),
        f.createIfcDirection((float(ux), float(uy), 0.)))
    direction = f.createIfcDirection((0., 0., 1.))

    def curve(points):
        vertices = [f.createIfcCartesianPoint((float(x), float(z))) for x, z in points]
        return f.createIfcPolyline(vertices + vertices[:1])

    solids = []
    for outer, holes in rectangle_profiles(rectangles):
        if holes:
            profile = f.createIfcArbitraryProfileDefWithVoids(
                "AREA", None, curve(outer), [curve(h) for h in holes])
        else:
            profile = f.createIfcArbitraryClosedProfileDef("AREA", None, curve(outer))
        solids.append(f.createIfcExtrudedAreaSolid(profile, position, direction, float(depth)))
    return solids


def swept_box(f, box):
    """Create a native rectangular extrusion for a vertical opening/leaf box."""
    import math

    width, depth = math.dist(box[0], box[1]), math.dist(box[0], box[3])
    height = box[4][2] - box[0][2]
    if min(width, depth, height) <= 0:
        raise ValueError("Opening solid dimensions must be positive")
    ux, uy = ((box[1][i] - box[0][i]) / width for i in (0, 1))
    profile = f.createIfcRectangleProfileDef("AREA", None,
        f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((width/2, depth/2)), None),
        float(width), float(depth))
    placement = f.createIfcAxis2Placement3D(
        f.createIfcCartesianPoint(tuple(float(c) for c in box[0])),
        f.createIfcDirection((0., 0., 1.)), f.createIfcDirection((float(ux), float(uy), 0.)))
    return f.createIfcExtrudedAreaSolid(profile, placement,
                                      f.createIfcDirection((0., 0., 1.)), float(height))
