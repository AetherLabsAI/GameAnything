"""Walk sprites made from the game's own villagers (the approach proven on the HDSI characters 2026-10-11): pick a vanilla
villager for the upper body and one for the lower body, cut each 16x32 frame at a row, and recolour every material (hair,
skin, clothes ...) to the person's look. Animation, proportions and style stay the game's own.

Materials per villager live in villagers.yaml: each colour of the sheet -> a material name. `gameanything art label <villager>`
proposes labels automatically and draws a material map to check them; mistakes are fixed in villagers.yaml.

Look spec (one per person), e.g.
    upper: Harvey            # head and torso from this villager
    lower: Harvey            # legs / skirt from this one (default: upper)
    cut: 25                  # frame row where lower starts (0-31)
    colors: {hair: "#1d1b24", skin: "#f6cfb0", jacket: "#22304f", shirt: "#f4f2ec", tie: "#2b3f74", pants: "#1f2740"}
    # a material can be turned into another one's colour, e.g. Harvey's mustache: colors: {mustache: <a skin shade>}
"""
from collections import defaultdict
from pathlib import Path

import yaml
from PIL import Image

from . import palette as pal

HERE = Path(__file__).parent
FW, FH, ROWS = 16, 32, 4                  # frame size; walk rows: down, right, up, left
MATERIAL_COLORS = {"outline": "#000000", "hair": "#ffcc00", "skin": "#ff9a8a", "eyes": "#00b7ff", "top": "#2e7d32", "shirt": "#a5d6a7",
                   "jacket": "#1b5e20", "tie": "#d50000", "bottom": "#3949ab", "skirt": "#7986cb", "pants": "#283593", "shoes": "#6d4c41",
                   "accent": "#ff00ff", "glasses": "#00e5ff", "keep": "#9e9e9e"}


def sheet(content: Path, villager: str) -> Image.Image:
    return Image.open(content / "Characters" / f"{villager}.png").convert("RGBA").crop((0, 0, FW * 4, FH * ROWS))


def villagers() -> dict:
    f = HERE / "villagers.yaml"
    return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f.exists() else {}


def colours(im: Image.Image):
    """-> {rgb: {count, ys (frame-local rows), xs}} for every opaque colour."""
    px = im.load(); out = defaultdict(lambda: {"count": 0, "ys": [], "xs": []})
    for y in range(im.height):
        for x in range(im.width):
            p = px[x, y]
            if p[3] == 0: continue
            e = out[p[:3]]; e["count"] += 1; e["ys"].append(y % FH); e["xs"].append(x % FW)
    return dict(out)


def auto_label(im: Image.Image) -> dict:
    """First guess of each colour's material from where it sits in the frame and what it looks like; always checked by eye."""
    labels = {}
    for c, e in colours(im).items():
        h, s, v = pal.hsv(c); L = pal.lum(c); my = sum(e["ys"]) / len(e["ys"]); top = min(e["ys"])
        skinlike = 5 <= h <= 40 and 0.2 <= s <= 0.75 and v >= 0.55
        if L < 0.25 and e["count"] > 40: m = "outline"
        elif skinlike and 6 <= my <= 22: m = "skin"
        elif e["count"] < 12 and 9 <= my <= 14: m = "eyes"
        elif my < 10 or top <= 2: m = "hair"
        elif my < 24: m = "top"
        elif my < 29: m = "bottom"
        else: m = "shoes"
        labels[pal.rgb2hex(c)] = m
    return labels


def material_map(im: Image.Image, labels: dict, scale=6) -> Image.Image:
    """The sheet's first frame of each walk row next to the same frames painted by material (to check labels by eye)."""
    out = Image.new("RGBA", (FW * 8 * scale, FH * ROWS * scale // 2), (120, 120, 120, 255))
    for r in range(ROWS):
        fr = im.crop((0, r * FH, FW, r * FH + FH)); mm = Image.new("RGBA", (FW, FH), (0, 0, 0, 0)); mp = mm.load(); fp = fr.load()
        for y in range(FH):
            for x in range(FW):
                p = fp[x, y]
                if p[3]: mp[x, y] = pal.hex2rgb(MATERIAL_COLORS.get(labels.get(pal.rgb2hex(p), "keep"), "#9e9e9e")) + (255,)
        s = scale // 2
        out.alpha_composite(fr.resize((FW * s, FH * s), Image.NEAREST), (r * FW * 2 * s, 0))
        out.alpha_composite(mm.resize((FW * s, FH * s), Image.NEAREST), (r * FW * 2 * s + FW * s, 0))
    return out


def resolve(spec, ly):
    """A villagers.yaml colour entry -> the material at frame-local row ly."""
    if isinstance(spec, str): return spec
    for m, y0, y1 in spec:
        if y0 <= ly <= y1: return m
    return None


def build(content: Path, look: dict) -> Image.Image:
    """-> a 64x128 walk sheet (4 rows x 4 frames of 16x32) for one person. Each material's shades become shades of the
    look's colour for it (palette.ramp); materials the look does not name keep their vanilla colours."""
    V = villagers()
    up, lo = look["upper"], look.get("lower", look["upper"]); cut = look.get("cut", FH)
    dflt = V.get(up, {}).get("defaults") or {}            # per-base defaults (e.g. Kent's spiky highlights need less contrast)
    targets = {**(dflt.get("colors") or {}), **(look.get("colors") or {})}
    look = {**look, "contrast": {**(dflt.get("contrast") or {}), **(look.get("contrast") or {})}}
    src, tables, cmaps = {}, {}, {}
    for v in {up, lo}:
        if v not in V: raise KeyError(f"{v}: no materials in villagers.yaml yet (label it first)")
        src[v] = sheet(content, v); counts = colours(src[v])
        tables[v] = {pal.hex2rgb(k): spec for k, spec in V[v]["colors"].items()}
        bym = defaultdict(set)
        for c, spec in tables[v].items():
            for m in ([spec] if isinstance(spec, str) else [x[0] for x in spec]): bym[m].add(c)
        cmaps[v] = {}
        for m, cs in bym.items():
            if m not in targets: continue
            w = {c: counts.get(c, {"count": 1})["count"] for c in cs}
            cmaps[v][m] = pal.ramp(sorted(cs), w, targets[m], (look.get("contrast") or {}).get(m, 1.0))
    out = Image.new("RGBA", (FW * 4, FH * ROWS), (0, 0, 0, 0)); op = out.load()
    mat = [[None] * (FW * 4) for _ in range(FH * ROWS)]      # material of every output pixel (for accessories)
    unknown = defaultdict(int)
    for y in range(FH * ROWS):
        ly = y % FH; v = up if ly < cut else lo
        sp = src[v].load()
        for x in range(FW * 4):
            p = sp[x, y]
            if not p[3]: continue
            spec = tables[v].get(p[:3])
            if spec is None: unknown[(v, pal.rgb2hex(p))] += 1; op[x, y] = p; continue
            m = resolve(spec, ly); mat[y][x] = m
            op[x, y] = cmaps[v].get(m, {}).get(p[:3], p[:3]) + (p[3],)
    if unknown: print("[sprite] colours without a material (kept as is):", dict(unknown))
    for acc in look.get("accessories") or []:
        ACCESSORIES[acc["type"] if isinstance(acc, dict) else acc](out, mat, acc if isinstance(acc, dict) else {})
    return out


def _blend(a, b, t): return tuple(round(a[i] * (1 - t) + b[i] * t) for i in range(3))


def veil(out, mat, opt):
    """A long sheer bridal veil, drawn per walking direction from the hair's position in each frame: from the back of the
    head down to `length` (frame row); over the sprite it is see-through (`opacity`), outside it is solid veil colour."""
    px = out.load(); L = opt.get("length", 28); op_ = opt.get("opacity", 0.62); op_hair = opt.get("opacity_over_hair", 0.38)
    light, mid, edge = (pal.hex2rgb(opt.get(k, d)) for k, d in (("color", "#f5f4f8"), ("fold", "#e2e1ea"), ("edge", "#c3c1cf")))
    for r in range(ROWS):
        for f in range(4):
            X0, Y0 = f * FW, r * FH
            hair = [(x, y) for y in range(FH) for x in range(FW) if mat[Y0 + y][X0 + x] == "hair"]
            if not hair: continue
            ht = min(y for _, y in hair); hb = max(y for _, y in hair)
            solid = lambda x, y: 0 <= x < FW and 0 <= y < FH and px[X0 + x, Y0 + y][3] > 0
            def put(x, y, c):
                if not (0 <= x < FW and 0 <= y < FH): return
                p = px[X0 + x, Y0 + y]
                t = op_hair if mat[Y0 + y][X0 + x] == "hair" else op_
                px[X0 + x, Y0 + y] = (_blend(p[:3], c, t) if p[3] else c) + (255,)
            start = ht + (hb - ht) // 2                      # it hangs from the back of the head (the bun), not the crown
            for y in range(start, L + 1):
                row = [x for x in range(FW) if solid(x, y)]
                if not row: continue
                lft, rgt = min(row), max(row); grow = (y - start) // 5
                if r == 2:                                   # back view: the veil covers the back
                    hx = [x for x, yy in hair if yy == min(y, hb)] or [lft, rgt]
                    cx = (min(hx) + max(hx)) // 2; half = min((max(hx) - min(hx)) // 2, 2 + grow)
                    a, b = cx - half, cx + half
                    for x in range(a, b + 1): put(x, y, edge if x in (a, b) else (mid if (x - a) % 3 == 2 else light))
                elif r == 0:                                 # front view: only the edges show, behind the body
                    for x in (lft - 1, rgt + 1):
                        if y > hb - 3 and not solid(x, y): put(x, y, edge if y == L else light)
                else:                                        # side views: it falls behind, on the side away from the face
                    back = lft if r == 1 else rgt; d = -1 if r == 1 else 1
                    w = min(3, 1 + grow)
                    for k in range(0, w + 1):
                        x = back + d * k
                        if not solid(x, y) or k == 0: put(x, y, edge if k == w else (mid if k == w - 1 else light))
    return out


def glasses(out, mat, opt):
    """Glasses for a base villager without them: frames drawn around the eyes found in each frame (front: two lenses and a
    bridge; sides: one lens and the temple; back: the temples at the sides of the head)."""
    px = out.load(); frame = pal.hex2rgb(opt.get("color", "#26252c")); lens = pal.hex2rgb(opt.get("lens", "#cfe3f0"))
    for r in range(ROWS):
        for f in range(4):
            X0, Y0 = f * FW, r * FH
            eyes = [(x, y) for y in range(FH) for x in range(FW) if mat[Y0 + y][X0 + x] == "eyes"]
            hair = [(x, y) for y in range(FH) for x in range(FW) if mat[Y0 + y][X0 + x] == "hair"]
            set_ = lambda x, y, c: (0 <= x < FW and 0 <= y < FH) and px.__setitem__((X0 + x, Y0 + y), c + (255,))
            if r == 2:                                       # back: two dark pixels where the temples meet the hair
                if not hair: continue
                ys = sorted(y for _, y in hair); ey = ys[len(ys) * 2 // 3]
                row = [x for x, y in hair if y == ey]
                if row: set_(min(row), ey, frame); set_(max(row), ey, frame)
                continue
            if not eyes: continue
            ys = [y for _, y in eyes]; ey = max(set(ys), key=ys.count)   # the eye row (brows share the material in some sheets)
            pts = sorted(x for x, y in eyes if abs(y - ey) <= 1)
            groups = [[pts[0]]]
            for x in pts[1:]:
                (groups[-1].append(x) if x - groups[-1][-1] <= 1 else groups.append([x]))
            for g in groups:
                x0, x1 = min(g) - 1, max(g) + 1
                for x in range(x0, x1 + 1): set_(x, ey - 1, frame)          # top rim
                set_(x0, ey, frame); set_(x1, ey, frame)                      # sides
                for x in range(x0 + 1, x1):
                    p = px[X0 + x, Y0 + ey]
                    if mat[Y0 + ey][X0 + x] != "eyes": set_(x, ey, _blend(p[:3], lens, 0.35))
            if r == 0 and len(groups) >= 2:                  # bridge
                for x in range(max(groups[0]) + 2, min(groups[1]) - 1): set_(x, ey - 1, frame)
            if r in (1, 3) and groups:                       # temple towards the ear
                g = groups[0]; d = -1 if r == 1 else 1; x = (min(g) - 2) if r == 1 else (max(g) + 2)
                for k in range(3): set_(x + d * k, ey - 1, frame)
    return out


ACCESSORIES = {"veil": veil, "glasses": glasses}


def preview(im: Image.Image, scale=6, bg=(118, 150, 106, 255)) -> Image.Image:
    big = Image.new("RGBA", (im.width * scale, im.height * scale), bg)
    big.alpha_composite(im.resize((im.width * scale, im.height * scale), Image.NEAREST)); return big
