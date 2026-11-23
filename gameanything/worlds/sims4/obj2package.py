#!/usr/bin/env python3
"""obj2package.py - turn a static OBJ + PNG texture into a placeable Sims 4 Buy-mode decor object (.package).

  python obj2package.py model.obj texture.png out.package --name m2w_flying_car [--clone object_sculpture]
        [--title "Flying Car"] [--desc "..."] [--price 500] [--game "/Applications/EA Games/The Sims 4.app"]
        [--template-id 0x33D24] [--no-flip-v] [--mirror-x] [--flip-winding]

How it works (no Sims 4 Studio): the game's own packages (read-only) supply templates of a real catalog decor object whose
OBJD uses the tuning named by --clone (default object_sculpture). We write NEW resources only:
  OBJD  object definition (clone of the template with our name, model/footprint keys, price)
  COBJ  catalog entry (clone of the template with our name/description string keys, price, unique id)
  MODL  RCOL with MODL, MLOD, MATD, VRTF, VBUF, IBUF, SKIN, MATD, info chunk (our mesh; one LOD, one mesh, one material)
  FTPT  footprint (template rectangle patched to the mesh bbox)
  DDS   diffuse texture, DXT5 with full mip chain
  STBL  name/description (written for all 18 languages)
The rig, slot and tuning of the template, the flat normal map, the specular map and the environment map are referenced
from the base game by key (they are shared base-game resources), nothing is copied from the game into the package
except the small structural chunks (SKIN, default MATD, material parameter block, FTPT/COBJ/OBJD skeletons) which are
patched; no game geometry or texture is included.

Nothing is installed anywhere; copy the package into Documents/Electronic Arts/The Sims 4/Mods yourself.
Run `python -m gameanything.worlds.sims4.s4check out.package` for the offline validation report.
"""
import argparse
import struct
import sys

import numpy as np
from PIL import Image

from gameanything.native.s4pkg import fnv32, fnv64, write_package
from gameanything.worlds.sims4 import s4dds, s4model as M
from gameanything.worlds.sims4.s4game import (Game, T_OBJD, T_COBJ, T_MODL, T_FTPT, T_DDS, T_STBL)

DEFAULT_CLONE = "object_sculpture"
PREFERRED = {"object_sculpture": [0x33D24]}   # a known good template first (rig+slot+skin, direct phong material)
CHUNK_SIG = [b"MODL", b"MLOD", b"MATD", b"VRTF", b"VBUF", b"IBUF", b"SKIN", b"MATD"]   # + unnamed info chunk


class Template:
    """A real catalog decor object of the game used as the structural template."""
    def __init__(self, game, oid):
        self.oid = oid
        self.objd_ver, self.fields = M.parse_objd(game.read(T_OBJD, 0, oid))
        self.f = dict(self.fields)
        self.name = M.objd_str(self.f[M.OBJD_TAG["name"]])
        self.cobj = game.read(T_COBJ, 0, oid)
        t, g, i = M.objd_refs(self.f[M.OBJD_TAG["model"]])[0]
        self.model_key = (t, g, i)
        self.rcol = M.parse_rcol(game.read(t, g, i))
        ch = self.rcol["chunks"]
        self.main_matd = ch[2]
        self.skin = ch[6]
        self.default_matd = ch[7]
        self.rig = M.objd_refs(self.f[M.OBJD_TAG["rig"]])[0]
        self.slot = M.objd_refs(self.f[M.OBJD_TAG["slot"]])[0]
        ft = M.objd_refs(self.f[M.OBJD_TAG["footprint"]])[0]
        self.ftpt = game.read(*ft) if game.has(*ft) else None


def _suitable(game, oid):
    try:
        ver, fields = M.parse_objd(game.read(T_OBJD, 0, oid))
    except Exception:
        return None
    f = dict(fields)
    if not game.has(T_COBJ, 0, oid):
        return None
    for tag in ("model", "rig", "slot"):
        r = M.objd_refs(f[M.OBJD_TAG[tag]])
        if len(r) != 1 or r[0][0] == 0 or not game.has(*r[0]):
            return None
    t, g, i = M.objd_refs(f[M.OBJD_TAG["model"]])[0]
    if t != T_MODL:
        return None
    try:
        rc = M.parse_rcol(game.read(t, g, i))
    except Exception:
        return None
    ch = rc["chunks"]
    if len(ch) != 9 or [c[:4] for c in ch[:8]] != CHUNK_SIG or ch[8][:4].isalpha():
        return None
    if len(ch[2]) < 600:
        return None
    try:
        M.matd_entries(ch[2])
    except Exception:
        return None
    cobj = game.read(T_COBJ, 0, oid)
    if cobj[:8] != struct.pack("<II", 0x1A, 0x0B) or struct.unpack_from("<I", cobj, 0x1C)[0] != 0x80:
        return None
    if struct.unpack_from("<I", cobj, 16)[0] == 0:
        return None
    return True


def find_template(game, tuning):
    cands = list(PREFERRED.get(tuning, []))
    seen = set(cands)
    for (g, i) in sorted(game.index[T_OBJD]):
        if i not in seen:
            cands.append(i)
    tried = 0
    for oid in cands:
        if (0, oid) not in game.index[T_OBJD]:
            continue
        try:
            ver, fields = M.parse_objd(game.read(T_OBJD, 0, oid))
        except Exception:
            continue
        f = dict(fields)
        tn = M.objd_str(f[M.OBJD_TAG["tuning_name"]]) if M.OBJD_TAG["tuning_name"] in f else ""
        if tn != tuning:
            continue
        if _suitable(game, oid):
            return Template(game, oid)
        tried += 1
    raise SystemExit(f"no suitable template object with tuning '{tuning}' found in the game data")


def find_footprint_template(game, tuning):
    """A 117-byte single-rectangle footprint of a floor object with the same tuning (flags 7 / 0 are the common form)."""
    for (g, i) in sorted(game.index[T_OBJD]):
        f = dict(M.parse_objd(game.read(T_OBJD, 0, i))[1])
        if M.OBJD_TAG["tuning_name"] not in f or M.objd_str(f[M.OBJD_TAG["tuning_name"]]) != tuning:
            continue
        ft = M.objd_refs(f[M.OBJD_TAG["footprint"]])[0]
        if ft[0] != T_FTPT or not game.has(*ft):
            continue
        d = game.read(*ft)
        try:
            c = M.parse_rcol(d)["chunks"][0]
        except Exception:
            continue
        if len(c) == 117 and c[0x22] == 4 and struct.unpack_from("<I", c, 0x1E)[0] == 7:
            return d
    raise SystemExit("no 117-byte footprint template found")


def load_texture(path):
    im = Image.open(path).convert("RGBA")
    w, h = im.size

    def p2(n):
        return 1 << max(2, int(round(np.log2(max(n, 4)))))
    nw, nh = min(p2(w), 4096), min(p2(h), 4096)
    if (nw, nh) != (w, h):
        print(f"warning: texture {w}x{h} resized to power of two {nw}x{nh}", file=sys.stderr)
        im = im.resize((nw, nh), Image.LANCZOS)
    return np.array(im)


def build(obj, png, name, clone=DEFAULT_CLONE, title=None, desc=None, price=500, app=None, flip_v=True,
          mirror_x=False, flip_winding=False, template_id=None, clear_id_bit=False, layout="skin28", scale=1.0, footprint=None, render_bbox=False, log=print):
    """Build the resource list [(type, group, instance, bytes)] for the package."""
    game = Game(app)
    if template_id:
        if not _suitable(game, template_id):
            raise SystemExit(f'object 0x{template_id:X} is not usable as template (needs rig+slot+skin, direct material, price>0)')
        tpl = Template(game, template_id)
    else:
        tpl = find_template(game, clone)
    log(f"template object: {tpl.name} (OBJD 0x{tpl.oid:X}), model {tpl.model_key[2]:016X}, rig/slot {tpl.rig[2]:016X}")
    geo = M.load_obj(obj, flip_v=flip_v, mirror_x=mirror_x, flip_winding=flip_winding)
    if scale != 1.0:
        geo.pos = geo.pos * scale
    nv, nt = len(geo.pos), len(geo.tris)
    if nv > 65535:
        raise SystemExit(f"{nv} unique vertices after OBJ expansion; the 16 bit index buffer allows 65535 (decimate the mesh)")
    log(f"mesh: {nv} vertices, {nt} triangles")
    bb = np.concatenate([geo.pos.min(0), geo.pos.max(0)])
    w = M.pos_scale(geo.pos)
    uvs = np.float32(1.0) if layout == "float32" else M.uv_scale(geo.uv)
    log(f"bbox {np.round(bb, 4).tolist()} position divisor {w}, uv scale {float(uvs):.8g}")
    # quantised bbox is what the game decodes; keep bbox as float of the quantised positions
    q = geo.pos if layout == "float32" else np.rint(geo.pos * w) / w
    bbq = tuple(float(x) for x in np.concatenate([q.min(0), q.max(0)]))
    if render_bbox and layout != "float32":
        # The game decodes Short4 positions as int16 / 32767, ignoring w (measured live: a model renders at 1/ceil(max |coordinate|)), so the
        # object scale has to be ceil(max). Its bounding box (frustum culling!) must describe the geometry as it is RENDERED, otherwise a
        # scaled-up object is culled whenever the camera is near it ("the stage vanishes in close shots").
        k = w / 32767.0
        bbq = tuple(c * k for c in bbq)

    O = fnv64(name, True)
    if clear_id_bit:
        O &= 0x7FFFFFFFFFFFFFFF
    # The game normalises OBJD/COBJ keys: instance with bit 63 set -> group 0x80000000 (checked live with
    # sims4.resources.get_normalized_key; with group 0 such a resource is listed but cannot be loaded).
    OG = 0x80000000 if O >> 63 else 0
    Mi = fnv64(name + "_model", True)
    Ti = fnv64(name + "_diffuse", True)
    Mat = fnv64(name + "_material", True)
    name_key = fnv32(name + "_name"); desc_key = fnv32(name + "_desc")
    title = title or name.replace("_", " ")
    desc = desc or f"{title} (imported with the gameanything OBJ converter)."

    # ---- MODL RCOL
    skinned = M.LAYOUTS[layout]["skinned"]
    buf = M.build_vbuf(geo, w, uvs, layout)
    chunks = [
        M.build_modl(bbq),
        M.build_mlod(fnv32(name + "_mesh"), nv, nt, bbq, layout=layout),
        M.patch_matd(tpl.main_matd, fnv32(name + "_material"), Ti, uvs),
        M.build_vrtf(layout),
        M.vbuf_chunk(buf, 0x10000007 if skinned else 0x10000006),
        M.ibuf_chunk(geo.tris),
    ]
    keys = [(T_MODL, 0, Mi), (0x01D10F34, 0, Mi), (0x01D0E75D, 0, Mat), (0x01D0E723, 0, 0), (0x01D0E6FB, 0, Mi),
            (0x01D0E70F, 0, Mi)]
    if skinned:
        chunks.append(tpl.skin); keys.append((0x01D0E76B, 0, 0))
    chunks += [tpl.default_matd, M.build_x_chunk(nv, layout)]
    keys += [(0x01D0E75D, 0, 0), (0, 0, 0)]
    modl = M.build_rcol(keys, chunks, public=2, ext=0)

    # ---- FTPT
    fpb = bbq if footprint is None else (footprint[0], bbq[1], footprint[1], footprint[2], bbq[4], footprint[3])   # footprint = (x0, z0, x1, z1)
    ftpt = M.patch_ftpt(find_footprint_template(game, clone), Mi, fpb)

    # ---- DDS
    rgba = load_texture(png)
    dds = s4dds.make_dds(rgba, "DXT5")

    # ---- OBJD
    F = dict(tpl.fields)
    T = M.OBJD_TAG
    F[T["name"]] = M.objd_pack_str(name)
    F[T["model"]] = M.objd_pack_refs([(T_MODL, 0, Mi)])
    F[T["footprint"]] = M.objd_pack_refs([(T_FTPT, 0, Mi)])
    F[T["variant"]] = struct.pack("<I", 0)
    if not skinned:     # static mesh: no rig/slot (as the game's rig-less sculptures)
        F[T["rig"]] = M.objd_pack_refs([(0, 0, 0)]); F[T["slot"]] = M.objd_pack_refs([(0, 0, 0)])
    F[T["price"]] = struct.pack("<I", price)
    objd = M.build_objd(tpl.objd_ver, [(t, F[t]) for t, _ in tpl.fields])

    # ---- COBJ
    cobj = M.patch_cobj(tpl.cobj, name_key, desc_key, price, fnv64(name + "_catalog", True))

    # ---- STBL (all languages, same English text)
    strings = {name_key: title, desc_key: desc}
    res = [(T_OBJD, OG, O, objd), (T_COBJ, OG, O, cobj), (T_MODL, 0, Mi, modl), (T_FTPT, 0, Mi, ftpt),
           (T_DDS, 0, Ti, dds)]
    for loc, hi in M.LOCALES.items():
        res.append((T_STBL, 0x80000000, (hi << 56) | (fnv64("m2w_strings_" + name) & 0x00FFFFFFFFFFFFFF), M.build_stbl(strings)))
    game.close()
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("obj"); ap.add_argument("texture"); ap.add_argument("out")
    ap.add_argument("--name", required=True, help="object name, e.g. m2w_flying_car (also seeds all resource ids)")
    ap.add_argument("--clone", default=DEFAULT_CLONE, help="object tuning name of the template family (default object_sculpture)")
    ap.add_argument("--title"); ap.add_argument("--desc")
    ap.add_argument("--price", type=int, default=500)
    ap.add_argument("--game", help="path of The Sims 4.app (default /Applications/EA Games/The Sims 4.app)")
    ap.add_argument("--template-id", type=lambda x: int(x, 0), help="OBJD id of the game object to clone instead of the automatic choice")
    ap.add_argument("--clear-id-bit", action="store_true", help="object id < 2^63 (group 0) instead of the default high-bit id (group 0x80000000)")
    ap.add_argument("--layout", choices=list(M.LAYOUTS), default="skin28", help="vertex layout: skin28 (rigged, default), static20 (Short4, no rig), float32 (floats, no rig)")
    ap.add_argument("--scale", type=float, default=1.0, help="scale the model (mesh, bbox and footprint)")
    ap.add_argument("--footprint", help="x0,z0,x1,z1 of the footprint rectangle in metres (default: the mesh bbox); a tiny one keeps Sims able to walk through a big prop")
    ap.add_argument("--render-bbox", action="store_true", help="declare the bounding box of the rendered size (model / ceil(max |coordinate|)); use it with an object scale of that integer")
    ap.add_argument("--no-flip-v", action="store_true", help="keep OBJ v (default flips: v_game = 1 - v)")
    ap.add_argument("--mirror-x", action="store_true"); ap.add_argument("--flip-winding", action="store_true")
    a = ap.parse_args(argv)
    res = build(a.obj, a.texture, a.name, a.clone, a.title, a.desc, a.price, a.game,
                flip_v=not a.no_flip_v, mirror_x=a.mirror_x, flip_winding=a.flip_winding, template_id=a.template_id, clear_id_bit=a.clear_id_bit, layout=a.layout, scale=a.scale,
                footprint=[float(x) for x in a.footprint.split(",")] if a.footprint else None, render_bbox=a.render_bbox)
    write_package(a.out, res)
    for t, g, i, d in res:
        print(f"  {t:08X} {g:08X} {i:016X} {len(d):9d} bytes")
    print("wrote", a.out)
    from gameanything.worlds.sims4 import s4check
    ok = s4check.check_package(a.out, a.game, verbose=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
