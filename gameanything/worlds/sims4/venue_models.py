"""Procedural props for the launch event (OBJ + texture atlas), pure numpy/PIL, no game needed.

  python -m gameanything.worlds.sims4.venue_models OUTDIR     writes stage.obj, ramp.obj and venue_tex.png

Two models, in metres, y up, built to be packed with obj2package (one material = one 1024 x 1024 atlas, flat-colour cells + the screen art):
  stage  (round 3) an open platform (22 x 9 x 0.5, front edge flush with the base game's 6 x 5 festival stage, which is kept hidden under it for the
         Sims' routing), glowing edge strips, a 20 x 9.5 m LED backdrop screen, two tall LED pylons and speaker stacks. Audience side = +z, origin at the stage centre.
  ramp   (round 3) a launch track: a flat run-in, then a LOOP-shaped curve of RAMP_ANGLE degrees (yellow with red rails, like the real launch video's
         track), held by ribs, braces and a steel truss tower. Travel direction = +z, origin at the start of the curve.
The converter's position quantisation renders a model at 1/ceil(max |coordinate|) of its size (measured live), so `finish()` scales each model by
ceil(M)/M so that M is an integer: the object scale to use in the game is then exactly that integer (returned by `build_all`).
"""
import math
import os

import numpy as np

ATLAS = 1024
CELLS = {                       # name -> (x0, y0, x1, y1) in pixels (y down); flat colours
    "black": (0, 0, 256, 256),
    "dark": (256, 0, 512, 256),
    "red": (512, 0, 768, 256),
    "yellow": (768, 0, 1024, 256),
    "steel": (0, 256, 256, 512),
    "steel_dark": (256, 256, 512, 512),
    "white": (512, 256, 768, 512),
    "glow": (768, 256, 1024, 512),
    "screen": (0, 512, 1024, 1024),
}
COLORS = {"black": (20, 22, 28), "dark": (128, 134, 150), "red": (236, 28, 44), "yellow": (190, 176, 150), "steel": (156, 162, 172),
          "steel_dark": (88, 94, 104), "white": (238, 238, 244), "glow": (255, 80, 90)}


class Mesh(object):
    def __init__(self):
        self.v, self.vt, self.vn, self.f = [], [], [], []

    def quad(self, p, cell, uv=None):
        """A quad (4 points, counter-clockwise seen from outside) with a flat colour cell (centre of the cell) or a full-cell uv mapping
        (uv = 4 (u, v) in 0..1 of the cell, v up)."""
        p = [np.asarray(q, float) for q in p]
        n = np.cross(p[1] - p[0], p[2] - p[0])
        ln = np.linalg.norm(n)
        if ln < 1e-12:
            n = np.cross(p[2] - p[0], p[3] - p[0])
            ln = np.linalg.norm(n)
        if ln < 1e-12:
            return
        n = n / ln
        x0, y0, x1, y1 = CELLS[cell]
        if uv is None:
            cu, cv = (x0 + x1) / 2.0 / ATLAS, 1.0 - (y0 + y1) / 2.0 / ATLAS
            uvs = [(cu, cv)] * 4
        else:
            uvs = [((x0 + (x1 - x0) * a) / ATLAS, 1.0 - (y0 + (y1 - y0) * (1.0 - b)) / ATLAS) for a, b in uv]
        base_v, base_t, base_n = len(self.v), len(self.vt), len(self.vn)
        self.v.extend(p)
        self.vt.extend(uvs)
        self.vn.append(n)
        for k in range(1, 3):
            self.f.append([(base_v + 0 + 1, base_t + 0 + 1, base_n + 1), (base_v + k + 1, base_t + k + 1, base_n + 1), (base_v + k + 2, base_t + k + 2, base_n + 1)])
        # the second triangle of the quad uses points 0, 2, 3 (the loop above gives (0,1,2) and (0,2,3))

    def solid(self, c, cell, top_cell=None, face_cells=None, face_uv=None):
        """A hexahedron from 8 corners [bottom quad b0..b3, top quad t0..t3]. Faces are oriented outward automatically.
        `cell` colours the sides, `top_cell` the top (default `cell`); `face_cells` {"front"/"back"/..: cell} not used here."""
        c = [np.asarray(q, float) for q in c]
        mid = sum(c) / 8.0
        faces = {"bottom": (0, 1, 2, 3), "top": (4, 5, 6, 7), "s0": (0, 1, 5, 4), "s1": (1, 2, 6, 5), "s2": (2, 3, 7, 6), "s3": (3, 0, 4, 7)}
        for name, idx in faces.items():
            p = [c[i] for i in idx]
            n = np.cross(p[1] - p[0], p[2] - p[0])
            if np.dot(n, sum(p) / 4.0 - mid) < 0:
                p = p[::-1]
            cell_name = top_cell if (name == "top" and top_cell) else cell
            if face_cells and name in face_cells:
                cell_name = face_cells[name]
            self.quad(p, cell_name, uv=(face_uv or {}).get(name))

    def box(self, x0, x1, y0, y1, z0, z1, cell, top_cell=None, face_cells=None, face_uv=None):
        b = [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)]
        t = [(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)]
        self.solid(b + t, cell, top_cell, face_cells, face_uv)

    def beam(self, p0, p1, t, cell):
        """A square-section beam of side t from p0 to p1."""
        p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
        a = p1 - p0
        L = np.linalg.norm(a)
        if L < 1e-9:
            return
        a /= L
        ref = np.array([0.0, 1.0, 0.0]) if abs(a[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
        u = np.cross(a, ref)
        u /= np.linalg.norm(u)
        w = np.cross(a, u)
        h = t / 2.0
        ring = [(-h, -h), (h, -h), (h, h), (-h, h)]
        b = [p0 + u * x + w * y for x, y in ring]
        tt = [p1 + u * x + w * y for x, y in ring]
        self.solid(b + tt, cell)

    def bounds(self):
        a = np.array(self.v)
        return a.min(0), a.max(0)

    def scale(self, k):
        self.v = [np.asarray(q) * k for q in self.v]

    def write_obj(self, path, mtl_name="venue.mtl", tex="venue_tex.png"):
        out = ["mtllib %s" % mtl_name, "usemtl venue"]
        out += ["v %.5f %.5f %.5f" % tuple(q) for q in self.v]
        out += ["vt %.6f %.6f" % tuple(q) for q in self.vt]
        out += ["vn %.5f %.5f %.5f" % tuple(q) for q in self.vn]
        for tri in self.f:
            out.append("f " + " ".join("%d/%d/%d" % t for t in tri))
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(out) + "\n")
        with open(os.path.join(os.path.dirname(path), mtl_name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("newmtl venue\nKd 1 1 1\nmap_Kd %s\n" % tex)


def finish(mesh):
    """Scale so that max |coordinate| is an integer M (the converter's quantisation then renders it at exactly 1/M). Returns M."""
    lo, hi = mesh.bounds()
    m = float(max(abs(lo).max(), abs(hi).max()))
    M = int(math.ceil(m - 1e-9))
    mesh.scale(M / m)
    return M


# ------------------------------------------------------------------------------------------------ the stage
STAGE_W, STAGE_FRONT, STAGE_BACK, STAGE_H = 22.0, 2.5, -6.5, 0.5
SCREEN_W, SCREEN_H = 20.0, 9.5


def stage_mesh():
    m = Mesh()
    x = STAGE_W / 2.0
    # platform slab: dark top, black sides; glowing strips run along the front and both sides just under the top edge
    m.box(-x, x, 0.0, STAGE_H, STAGE_BACK, STAGE_FRONT, "black", top_cell="dark")
    s = 0.04
    m.box(-x - s, x + s, STAGE_H - 0.20, STAGE_H - 0.06, STAGE_FRONT, STAGE_FRONT + s, "red")
    m.box(-x - s, -x, STAGE_H - 0.20, STAGE_H - 0.06, STAGE_BACK, STAGE_FRONT, "red")
    m.box(x, x + s, STAGE_H - 0.20, STAGE_H - 0.06, STAGE_BACK, STAGE_FRONT, "red")
    # two bright strips on the top surface: along the front edge, and a long "runway" line in the middle
    m.box(-x + 0.5, x - 0.5, STAGE_H, STAGE_H + 0.014, STAGE_FRONT - 0.34, STAGE_FRONT - 0.2, "white")
    m.box(-x + 0.5, x - 0.5, STAGE_H, STAGE_H + 0.012, STAGE_FRONT - 0.7, STAGE_FRONT - 0.62, "glow")
    # backdrop: black frame box with the screen art on its front (+z) face
    zb = STAGE_BACK + 0.35
    sx, sy0, sy1 = SCREEN_W / 2.0, STAGE_H + 0.5, STAGE_H + 0.5 + SCREEN_H
    m.box(-sx - 0.2, sx + 0.2, sy0 - 0.2, sy1 + 0.2, zb - 0.35, zb, "black")
    m.quad([(-sx, sy0, zb + 0.005), (sx, sy0, zb + 0.005), (sx, sy1, zb + 0.005), (-sx, sy1, zb + 0.005)], "screen", uv=[(0, 0), (1, 0), (1, 1), (0, 1)])
    # light frame around the screen (thin glowing bars, not a cage: nothing is in front of the screen)
    t = 0.18
    m.box(-sx - 0.2, sx + 0.2, sy1 + 0.2, sy1 + 0.2 + t, zb, zb + 0.08, "glow")
    m.box(-sx - 0.2 - t, -sx - 0.2, sy0 - 0.2, sy1 + 0.2 + t, zb, zb + 0.08, "glow")
    m.box(sx + 0.2, sx + 0.2 + t, sy0 - 0.2, sy1 + 0.2 + t, zb, zb + 0.08, "glow")
    # two tall LED pylons at the ends of the platform and speaker stacks beside the screen
    for sgn in (-1, 1):
        cx = sgn * (x - 0.9)
        m.box(cx - 0.45, cx + 0.45, STAGE_H, STAGE_H + 12.0, zb - 0.6, zb + 0.3, "steel_dark")
        m.box(cx - 0.3, cx + 0.3, STAGE_H + 0.4, STAGE_H + 11.6, zb + 0.3, zb + 0.34, "glow")
        cx2 = sgn * (sx + 1.3)
        m.box(cx2 - 0.6, cx2 + 0.6, STAGE_H, STAGE_H + 3.2, zb - 0.7, zb + 0.2, "steel_dark")
        m.box(cx2 - 0.5, cx2 + 0.5, STAGE_H + 0.3, STAGE_H + 2.9, zb + 0.2, zb + 0.23, "black")
    return m


# ------------------------------------------------------------------------------------------------ the ramp
RAMP_W = 2.4            # half width of the track
RAMP_THICK = 0.35
RAMP_R = 11.0           # radius of the loop
RAMP_ANGLE = math.radians(165.0)     # the track turns this far (90 = a quarter pipe, 180 = the top of a loop): the car leaves it nose-up, going backwards
RAMP_LEAD = 14.0        # flat run-in before the loop
RAMP_BASE = 0.15        # the run-in's top surface above the ground
RAMP_SEGS = 44


def ramp_profile(r=RAMP_R, ang=RAMP_ANGLE, lead=RAMP_LEAD, base=RAMP_BASE, segs=RAMP_SEGS):
    """[(z, y)] of the track's top surface: flat run-in (z -lead..0) then the arc. The car's path is this polyline (+ lift)."""
    pts = [(-lead, base), (-lead * 0.5, base)]
    for i in range(segs + 1):
        a = ang * i / segs
        pts.append((r * math.sin(a), base + r * (1.0 - math.cos(a))))
    return pts


def ramp_mesh():
    m = Mesh()
    pts = ramp_profile()
    w = RAMP_W
    normals = []
    for i in range(len(pts) - 1):
        dz, dy = pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]
        L = math.hypot(dz, dy)
        normals.append((-dy / L, dz / L))                       # (nz, ny) of segment i
    pn = []
    for i, p in enumerate(pts):
        a = normals[max(i - 1, 0)]
        b = normals[min(i, len(normals) - 1)]
        nz, ny = a[0] + b[0], a[1] + b[1]
        L = math.hypot(nz, ny)
        pn.append((nz / L, ny / L))
    for i in range(len(pts) - 1):
        (z0, y0), (z1, y1) = pts[i], pts[i + 1]
        (n0z, n0y), (n1z, n1y) = pn[i], pn[i + 1]
        t = RAMP_THICK
        # the slab is built on the OUTSIDE of the turn (away from the centre): top surface = the road the car drives on
        bot = [(-w, y0 - t * n0y, z0 - t * n0z), (w, y0 - t * n0y, z0 - t * n0z), (w, y1 - t * n1y, z1 - t * n1z), (-w, y1 - t * n1y, z1 - t * n1z)]
        top = [(-w, y0, z0), (w, y0, z0), (w, y1, z1), (-w, y1, z1)]
        m.solid(bot + top, "dark", top_cell="yellow")
        for sgn in (-1, 1):
            xa, xb = sgn * w, sgn * (w - 0.25)
            h = 0.24
            rc = [(xa, y0, z0), (xb, y0, z0), (xb, y1, z1), (xa, y1, z1)]
            rt = [(xa, y0 + h * n0y, z0 + h * n0z), (xb, y0 + h * n0y, z0 + h * n0z), (xb, y1 + h * n1y, z1 + h * n1z), (xa, y1 + h * n1y, z1 + h * n1z)]
            m.solid(rc + rt, "steel_dark")
    # ribs: vertical posts under the lower part of the curve
    for i in range(4, len(pts), 4):
        z, y = pts[i]
        if y > RAMP_BASE + 0.5 and pts[i][0] >= pts[i - 1][0]:
            for sgn in (-1, 1):
                m.box(sgn * (w - 0.35) - 0.13, sgn * (w - 0.35) + 0.13, 0.0, y - RAMP_THICK, z - 0.13, z + 0.13, "steel_dark")
    # steel truss towers on both sides of the loop, behind its vertical part, with braces to the loop
    hh = pts[-1][1] + 2.5
    zf = RAMP_R + 1.2
    zr = RAMP_R + 3.4
    for sgn in (-1, 1):
        x = sgn * (w + 0.8)
        m.beam((x, 0.0, zf), (x, hh, zf), 0.26, "steel")
        m.beam((x, 0.0, zr), (x, hh, zr), 0.26, "steel")
        k = 12
        for j in range(k + 1):
            y = hh * j / k
            m.beam((x, y, zf), (x, y, zr), 0.12, "steel")
            if j < k:
                y2 = hh * (j + 1) / k
                a, b = ((zf, zr) if j % 2 == 0 else (zr, zf))
                m.beam((x, y, a), (x, y2, b), 0.12, "steel_dark")
    for y in (hh, hh * 0.66, hh * 0.33):
        m.beam((-w - 0.8, y, zf), (w + 0.8, y, zf), 0.24, "steel")
        m.beam((-w - 0.8, y, zr), (w + 0.8, y, zr), 0.24, "steel")
    # braces from the outside of the loop's upper half to the towers
    for i in range(len(pts)):
        z, y = pts[i]
        if i % 5 == 0 and y > 8.0 and z > 0.0 and pts[i][0] < RAMP_R - 0.2 and i > 28:
            pass
    for ang in (100, 125, 150):
        a = math.radians(ang)
        z, y = RAMP_R * math.sin(a), RAMP_BASE + RAMP_R * (1.0 - math.cos(a))
        for sgn in (-1, 1):
            m.beam((sgn * (w + 0.8), y, zf), (sgn * (w - 0.2), y, z + 0.1), 0.2, "steel")
    return m


# ------------------------------------------------------------------------------------------------ texture
def atlas_image(text_lines=("FLYING CAR 001", "LAUNCH EVENT")):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (ATLAS, ATLAS), (0, 0, 0))
    d = ImageDraw.Draw(im)
    for name, (x0, y0, x1, y1) in CELLS.items():
        if name == "screen":
            continue
        d.rectangle([x0, y0, x1 - 1, y1 - 1], fill=COLORS[name])
    x0, y0, x1, y1 = CELLS["screen"]
    w, h = x1 - x0, y1 - y0
    px = im.load()
    for yy in range(h):                      # a bright blue-to-magenta sky, light at the horizon (the screen must glow even at dusk)
        t = yy / float(h - 1)
        for xx in range(w):
            u = xx / float(w - 1)
            r = int(30 + 190 * t * (0.4 + 0.6 * u))
            gg = int(70 + 130 * (1 - abs(t - 0.55) * 1.6 if t < 0.55 else 1 - (t - 0.55) * 2.2))
            b = int(150 + 100 * (1 - t))
            px[x0 + xx, y0 + yy] = (min(r, 255), max(0, min(gg, 255)), min(b, 255))
    # light rays and a bright launch-track arc
    for k in range(-9, 10):
        d.line([x0 + w // 2 + k * 40, y0 + h, x0 + w // 2 + k * 90, y0], fill=(150, 190, 255), width=1)
    for k in range(-8, 9):
        d.arc([x0 + 60 + k, y0 + 20 + k, x0 + 980 + k, y0 + 980 + k], 195, 335, fill=(255, 224, 90), width=3)
    d.rectangle([x0, y0 + h - 56, x1 - 1, y1 - 1], fill=(255, 235, 240))
    try:
        big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 118)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 54)
    except Exception:
        big = small = ImageFont.load_default()
    for i, line in enumerate(text_lines):
        f = big if i == 0 else small
        wd = d.textlength(line, font=f)
        d.text((x0 + (w - wd) / 2.0 + 3, y0 + 170 + i * 150 + 3), line, fill=(20, 30, 90), font=f)
        d.text((x0 + (w - wd) / 2.0, y0 + 170 + i * 150), line, fill=(255, 255, 255), font=f)
    return im


def build_all(outdir):
    """Write stage.obj, ramp.obj, venue.mtl, venue_tex.png into outdir. Returns {"stage": M, "ramp": M} (the object scale to use in the game)."""
    os.makedirs(outdir, exist_ok=True)
    res = {}
    for name, fn in (("stage", stage_mesh), ("ramp", ramp_mesh)):
        m = fn()
        res[name] = finish(m)
        m.write_obj(os.path.join(outdir, name + ".obj"))
    atlas_image().save(os.path.join(outdir, "venue_tex.png"))
    return res


if __name__ == "__main__":
    import sys
    print(build_all(sys.argv[1] if len(sys.argv) > 1 else "."))
