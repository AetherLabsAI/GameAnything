"""The round-2 launch event props (gameanything/worlds/sims4/venue_models.py): pure geometry + a texture atlas, no game needed."""
import math

import numpy as np

from gameanything.worlds.sims4 import venue_models as vm


def _load_obj(path):
    V, VT, F = [], [], []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("v "):
                V.append([float(x) for x in line.split()[1:4]])
            elif line.startswith("vt "):
                VT.append([float(x) for x in line.split()[1:3]])
            elif line.startswith("f "):
                F.append([tuple(int(i) - 1 for i in t.split("/")) for t in line.split()[1:]])
    return np.array(V), np.array(VT), F


def test_each_model_is_scaled_to_an_integer_max_coordinate(tmp_path):
    res = vm.build_all(str(tmp_path))
    assert res == {"stage": 13, "ramp": 25}                      # world.py / config.py use these as VENUE_STAGE_SCALE / VENUE_RAMP_SCALE
    for name, M in res.items():
        V, VT, F = _load_obj(str(tmp_path / (name + ".obj")))
        assert abs(np.abs(V).max() - M) < 1e-3, name         # object scale M renders it at its designed size
        assert len(V) <= 65535                                  # the converter's 16 bit index buffer
        assert VT.min() >= 0.0 and VT.max() <= 1.0
        assert len(F) > 100


def test_faces_point_outward():
    for fn in (vm.stage_mesh, vm.ramp_mesh):
        m = fn()
        bad = 0
        for tri in m.f:
            p = [np.array(m.v[t[0] - 1]) for t in tri]
            n = np.cross(p[1] - p[0], p[2] - p[0])
            nv = np.array(m.vn[tri[0][2] - 1])
            if np.linalg.norm(n) > 1e-9 and np.dot(n, nv) <= 0:
                bad += 1
        assert bad == 0                                          # winding agrees with the face normal (counter-clockwise from outside)


def test_stage_is_an_open_platform_with_a_backdrop_flush_with_the_real_stage():
    m = vm.stage_mesh()
    lo, hi = m.bounds()
    assert abs(hi[2] - vm.STAGE_FRONT) < 0.05                    # the front edge sits where the base game's stage ends (the real one is hidden under it)
    assert 22.0 < hi[0] - lo[0] < 26.0
    # nothing over the Sims' heads: everything tall (backdrop frame, speaker stacks) is at the back of the platform
    tall = [v for v in m.v if v[1] > vm.STAGE_H + 3.5]
    assert tall and all(v[2] <= vm.STAGE_BACK + 0.8 for v in tall)


def test_ramp_curve_matches_the_profile_and_rises_steeply():
    pts = vm.ramp_profile()
    assert pts[0][0] == -vm.RAMP_LEAD and pts[2][0] == 0.0
    top = pts[-1]
    assert abs(top[0] - vm.RAMP_R * math.sin(vm.RAMP_ANGLE)) < 1e-9
    assert abs(top[1] - (vm.RAMP_BASE + vm.RAMP_R * (1 - math.cos(vm.RAMP_ANGLE)))) < 1e-9
    last = math.degrees(math.atan2(pts[-1][1] - pts[-2][1], pts[-1][0] - pts[-2][0]))
    assert 160 < last < 170                                      # a loop: the track has turned past vertical when the car leaves it
    ys = [p[1] for p in pts]
    assert max(ys) == ys[-1] and ys[-1] > 20.0                  # the lip is the highest point of the loop (more than 20 m up)


def test_atlas_has_flat_cells_and_the_screen_art():
    im = vm.atlas_image()
    assert im.size == (vm.ATLAS, vm.ATLAS)
    for name, (x0, y0, x1, y1) in vm.CELLS.items():
        if name == "screen":
            continue
        assert im.getpixel(((x0 + x1) // 2, (y0 + y1) // 2)) == vm.COLORS[name]
    x0, y0, x1, y1 = vm.CELLS["screen"]
    assert len({im.getpixel((x0 + 300, y0 + y)) for y in range(0, 400, 20)}) > 5     # a gradient, not a flat colour
