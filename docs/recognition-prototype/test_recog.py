from __future__ import annotations

import pytest
from recog_v1 import recognize
from synth import l_shaped

TOL = 3.0  # px


def _match(walls, kinds, exp_walls, scale=1.0):
    got = [(w.horizontal, w.center / scale, w.a / scale, w.b / scale, k)
           for w, k in zip(walls, kinds)]
    unmatched = list(got)
    for h, c, a, b, kind in exp_walls:
        hit = next((g for g in unmatched if g[0] == h and abs(g[1] - c) <= TOL
                    and abs(g[2] - a) <= TOL and abs(g[3] - b) <= TOL), None)
        assert hit is not None, f"missing wall {(h, c, a, b)}; got {got}"
        assert hit[4] == kind, f"wall {(h, c, a, b)} classified {hit[4]}, expected {kind}"
        unmatched.remove(hit)
    assert not unmatched, f"extra walls {unmatched}"


@pytest.mark.parametrize("noise", [False, True])
@pytest.mark.parametrize("scale", [1.0, 0.5, 2.0])
def test_l_shaped(noise, scale):
    mask, boxes, exp = l_shaped(noise=noise, scale=scale)
    r = recognize(mask, boxes)
    _match(r["walls"], r["kinds"], exp["walls"], scale)
    walls = r["walls"]
    for op, ((h, c), s0, s1) in zip(r["openings"], exp["openings"]):
        w = walls[op.wall_index]
        assert (w.horizontal, round(w.center / scale)) == (h, c) or abs(w.center / scale - c) <= TOL
        assert w.horizontal == h
        assert abs(op.s0 / scale - s0) <= TOL and abs(op.s1 / scale - s1) <= TOL, (op, s0, s1)
    ext_t = [w.thickness / scale for w, k in zip(walls, r["kinds"]) if k == "exterior"]
    int_t = [w.thickness / scale for w, k in zip(walls, r["kinds"]) if k == "interior"]
    assert all(abs(t - exp["t_ext"]) <= 1.5 for t in ext_t), ext_t
    assert all(abs(t - exp["t_int"]) <= 1.5 for t in int_t), int_t
    assert r["unexplained_wall_ratio"] < 0.05, r["unexplained_wall_ratio"]


@pytest.mark.parametrize("seed", range(10))
def test_perturbed(seed):
    from synth import perturb

    mask, boxes, exp = l_shaped(noise=True, seed=seed)
    r = recognize(perturb(mask, seed=seed), boxes)
    _match(r["walls"], r["kinds"], exp["walls"])
    for op, ((h, c), s0, s1) in zip(r["openings"], exp["openings"]):
        w = r["walls"][op.wall_index]
        assert w.horizontal == h and abs(w.center - c) <= TOL
        assert abs(op.s0 - s0) <= TOL and abs(op.s1 - s1) <= TOL, (op, s0, s1)


def test_door_at_corner():
    """The door label ate the end of the perpendicular wall; the corner must still close."""
    import numpy as np
    from recog_v1 import Box
    from synth import cut, draw_wall

    m = np.zeros((400, 500), bool)
    for (x0, y0), (x1, y1) in [((50, 50), (450, 50)), ((450, 50), (450, 350)),
                               ((450, 350), (50, 350)), ((50, 350), (50, 50))]:
        draw_wall(m, x0, y0, x1, y1, 20)
    cut(m, 60, 340, 150, 360)
    cut(m, 40, 255, 60, 340)
    r = recognize(m, [Box("door", 58, 255, 150, 360, 0.9)])
    _match(r["walls"], r["kinds"], {
        (True, 50, 50, 450, "exterior"), (True, 350, 50, 450, "exterior"),
        (False, 50, 50, 350, "exterior"), (False, 450, 50, 350, "exterior")})
    (op,) = r["openings"]
    w = r["walls"][op.wall_index]
    assert w.horizontal and w.center == 350
    assert abs(op.s0 - 60) <= TOL and abs(op.s1 - 150) <= TOL


def test_diagonal_wall_is_reported():
    import numpy as np
    from synth import draw_wall

    m = np.zeros((400, 500), np.uint8)
    for (x0, y0), (x1, y1) in [((50, 50), (450, 50)), ((450, 50), (450, 350)),
                               ((450, 350), (50, 350)), ((50, 350), (50, 50))]:
        draw_wall(m, x0, y0, x1, y1, 20)
    for k in range(-10, 10):  # 45-degree band, ~20 px thick
        idx = np.arange(60, 300)
        m[np.clip(idx + k, 0, 399), idx] = 1
    r = recognize(m.astype(bool), [])
    assert len(r["walls"]) == 4
    assert r["unexplained_wall_ratio"] > 0.1
