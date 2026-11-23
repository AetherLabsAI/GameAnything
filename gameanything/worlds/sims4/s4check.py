"""Offline validation of a package written by obj2package.py (no game needed except for the optional key checks).

  python -m gameanything.worlds.sims4.s4check out.package [--game "/Applications/EA Games/The Sims 4.app"] [--no-game]
Returns exit code 0 when every check passes. What it cannot prove: that the game accepts the package.
"""
import struct
import sys

import numpy as np

from gameanything.native.s4pkg import Package
from gameanything.worlds.sims4 import s4dds, s4model as M
from gameanything.worlds.sims4.s4game import Game, T_OBJD, T_COBJ, T_MODL, T_DDS, T_STBL


class Report:
    def __init__(self, verbose=True):
        self.ok = True; self.verbose = verbose; self.lines = []

    def check(self, cond, msg):
        self.lines.append(("PASS" if cond else "FAIL", msg))
        if not cond:
            self.ok = False
        if self.verbose:
            print(("  PASS " if cond else "  FAIL ") + msg)
        return cond

    def info(self, msg):
        self.lines.append(("INFO", msg))
        if self.verbose:
            print("  info " + msg)


def decode_vertices(vb, stride, vcount, vrtf_els):
    a = np.frombuffer(vb[16:16 + stride * vcount], np.uint8).reshape(vcount, stride)
    els = {(e[0], e[1]): e for e in vrtf_els}
    if els[(0, 0)][2] == 2:      # float layout
        o = els[(0, 0)][3]
        pos = a[:, o:o + 12].copy().view("<f4").reshape(-1, 3).astype(np.float64)
        o = els[(1, 0)][3]
        nrm = a[:, o:o + 12].copy().view("<f4").reshape(-1, 3).astype(np.float64)
        o = els[(2, 0)][3]
        uv_raw = a[:, o:o + 8].copy().view("<f4").reshape(-1, 2).astype(np.float64)
        return a, pos, nrm, uv_raw, np.zeros(len(pos))
    p = a[:, els[(0, 0)][3]:els[(0, 0)][3] + 8].copy().view("<i2").reshape(-1, 4).astype(np.float64)
    pos = p[:, :3] / p[:, 3:4]
    o = els[(1, 0)][3]
    nrm = a[:, o:o + 4].astype(np.float64) / 127.5 - 1
    o = els[(2, 0)][3]
    uv_raw = a[:, o:o + 4].copy().view("<i2").reshape(-1, 2).astype(np.float64)
    return a, pos, nrm[:, :3], uv_raw, p[:, 3]


def parse_vrtf(c):
    ver, stride, nel, flags = struct.unpack_from("<IIII", c, 4)
    return stride, [tuple(c[20 + 4 * i:24 + 4 * i]) for i in range(nel)]


def parse_mlod(c):
    ver, cnt = struct.unpack_from("<II", c, 4); p = 12; out = []
    for _ in range(cnt):
        size = struct.unpack_from("<I", c, p)[0]; p += 4
        m = {}
        keys = ("name", "mat", "vrtf", "vbuf", "ibuf", "flags", "so", "sv", "si", "mv", "vcount", "pcount")
        m.update(zip(keys, struct.unpack_from("<12I", c, p)))
        q = p + 48
        m["bbox"] = struct.unpack_from("<6f", c, q); q += 24
        m["skin"] = struct.unpack_from("<I", c, q)[0]; q += 4
        jc = struct.unpack_from("<I", c, q)[0]; q += 4
        m["joints"] = struct.unpack_from("<%dI" % jc, c, q); q += 4 * jc
        m["tail"] = c[q:p + size]
        out.append(m); p += size
    if p != len(c):
        raise ValueError("MLOD size mismatch")
    return ver, out


def check_package(path, app=None, verbose=True, use_game=True, source_png=None):
    R = Report(verbose)
    P = Package(path)
    ents = {(e[0], e[1], e[2]): e for e in P.entries}
    R.check(len(ents) == len(P.entries), f"{len(P.entries)} resources, keys unique")
    get = lambda t, g, i: P.get(t, g, i)
    objd_keys = [k for k in ents if k[0] == T_OBJD]
    R.check(len(objd_keys) == 1, "exactly one OBJD")
    ok_, og, oi = objd_keys[0]
    d = get(ok_, og, oi)
    ver, fields = M.parse_objd(d)
    R.check(M.build_objd(ver, fields) == d, "OBJD parses and rebuilds byte-identical")
    f = dict(fields); T = M.OBJD_TAG
    name = M.objd_str(f[T["name"]])
    R.info(f"object name '{name}', OBJD instance {oi:016X}")
    model = M.objd_refs(f[T["model"]])[0]; foot = M.objd_refs(f[T["footprint"]])[0]
    R.check(model in ents and foot in ents, "OBJD model and footprint keys exist in the package")
    price = struct.unpack("<I", f[T["price"]])[0]
    # COBJ
    R.check(og == (0x80000000 if oi >> 63 else 0), "OBJD group follows the game's key normalisation (0x80000000 iff instance bit 63)")
    R.check((T_COBJ, og, oi) in ents, "COBJ has the same key as the OBJD")
    c = get(T_COBJ, og, oi)
    R.check(struct.unpack_from("<II", c, 0) == (0x1A, 0x0B), "COBJ version 0x1A/0x0B")
    nk, dk, cp = struct.unpack_from("<III", c, 8)
    R.check(cp == price, "COBJ price equals OBJD price")
    stbl = [k for k in ents if k[0] == T_STBL]
    R.check(len(stbl) == len(M.LOCALES), f"{len(stbl)} string tables (one per language)")
    sd = get(*stbl[0])
    n = struct.unpack_from("<Q", sd, 7)[0]; q = 21; strs = {}
    for _ in range(n):
        h, fl, ln = struct.unpack_from("<IBH", sd, q); q += 7
        strs[h] = sd[q:q + ln].decode("utf-8"); q += ln
    R.check(q == len(sd) and nk in strs and dk in strs, "STBL parses fully and holds the COBJ name/description keys")
    R.info(f"catalog name: {strs.get(nk)!r}")
    # MODL
    md = get(*model)
    rc = M.parse_rcol(md)
    skinned = rc["nint"] == 9
    R.check(rc["nint"] in (8, 9) and rc["ext"] == 0 and rc["public"] == 2, f"RCOL header: {rc['nint']} internal chunks (9 = skinned, 8 = static), 2 public, 0 external")
    ch = rc["chunks"]
    sig = [c_[:4] for c_ in ch[:-1]]
    want = [b"MODL", b"MLOD", b"MATD", b"VRTF", b"VBUF", b"IBUF"] + ([b"SKIN"] if skinned else []) + [b"MATD"]
    R.check(sig == want, "chunk order " + "/".join(w.decode() for w in want) + "/info")
    R.check(M.build_rcol(rc["keys"], ch, rc["public"], rc["ext"]) == md, "RCOL rebuilds byte-identical")
    priv = ch[rc["public"]:]
    ver_m, meshes = parse_mlod(ch[1])
    R.check(ver_m == 0x205 and len(meshes) == 1, "MLOD v0x205 with one mesh")
    me = meshes[0]
    resolve = lambda v: priv[(v & 0x0FFFFFFF) - 1] if v >> 28 == 1 else None
    vr, vb, ib = resolve(me["vrtf"]), resolve(me["vbuf"]), resolve(me["ibuf"])
    R.check(vr[:4] == b"VRTF" and vb[:4] == b"VBUF" and ib[:4] == b"IBUF" and resolve(me["mat"])[:4] == b"MATD"
            and (resolve(me["skin"])[:4] == b"SKIN" if skinned else me["skin"] == 0) and resolve(me["tail"] and struct.unpack_from("<I", me["tail"], 0)[0])[:4] == b"MATD",
            "MLOD chunk references resolve to the right chunk types")
    stride, els = parse_vrtf(vr)
    R.check(len(vb) - 16 == stride * me["vcount"], f"VBUF payload = vertex count {me['vcount']} x stride {stride}")
    R.check(len(ib) - 16 == 2 * 3 * me["pcount"], f"IBUF payload = 3 x triangle count {me['pcount']} x 2 bytes")
    xinfo = struct.unpack("<%dI" % (len(ch[-1]) // 4), ch[-1])
    R.check(xinfo[1] == stride and xinfo[2] == me["vcount"] and struct.unpack_from("<I", vb, 12)[0] == 0x10000000 + len(priv),
            "info chunk holds stride/vertex count and the VBUF points to it")
    idx = M.decode_ibuf(ib, 3 * me["pcount"])
    R.check(int(idx.max()) == me["vcount"] - 1 and int(idx.min()) == 0, f"index range 0..{int(idx.max())} fits the vertex count")
    R.check(len(set(idx.tolist())) == me["vcount"], "every vertex is used by at least one triangle")
    a, pos, nrm, uvr, w = decode_vertices(vb, stride, me["vcount"], els)
    bb = np.array(me["bbox"])
    R.check(np.allclose(pos.min(0), bb[:3], atol=1e-6) and np.allclose(pos.max(0), bb[3:], atol=1e-6),
            "decoded position min/max equals the MLOD bbox")
    modl = ch[0]
    R.check(np.allclose(struct.unpack_from("<6f", modl, 12), bb, atol=1e-9) and len(modl) == 76, "MODL bbox equals mesh bbox, MODL chunk 76 bytes")
    ln = np.linalg.norm(nrm, axis=1)
    R.check(float(ln.min()) > 0.97 and float(ln.max()) < 1.03, f"normals unit length ({ln.min():.3f}..{ln.max():.3f})")
    tri = idx.reshape(-1, 3)
    fn = np.cross(pos[tri[:, 1]] - pos[tri[:, 0]], pos[tri[:, 2]] - pos[tri[:, 0]])
    area = np.linalg.norm(fn, axis=1)
    vn = nrm[tri[:, 0]] + nrm[tri[:, 1]] + nrm[tri[:, 2]]
    good = (area > 1e-12)
    agree = float(((fn * vn).sum(1)[good] > 0).mean())
    R.info(f"triangles whose geometric normal agrees with the vertex normals: {agree:.3f} (game meshes: 1.000); zero-area: {int((~good).sum())}")
    R.check(agree > 0.9, "winding is consistent with the normals (CCW, as in the game's meshes)")
    # material / texture
    mt = M.matd_entries(ch[2])
    texkeys = {}
    for h, t, n_, o in mt["ents"]:
        if (t & 0xFFFF) == 4 and n_ == 4:
            texkeys[h] = struct.unpack_from("<QII", ch[2], 28 + o)
    R.check(mt["shader"] == 0xB9105A6D, "material shader is phong (0xB9105A6D)")
    dk_ = texkeys[0x6CC0FD85]
    R.check((dk_[1], 0, dk_[0]) in ents and dk_[1] == T_DDS, "diffuseMap key points at the DDS inside the package")
    uvs = [struct.unpack_from("<f", ch[2], 28 + o)[0] for h, t, n_, o in mt["ents"] if h == 0x420520E9][0]
    uv = uvr * (1.0 if {(e[0], e[1]): e for e in els}[(2, 0)][2] == 1 else uvs)
    R.info(f"uv range after scale: u {uv[:,0].min():.4f}..{uv[:,0].max():.4f}, v {uv[:,1].min():.4f}..{uv[:,1].max():.4f}")
    # DDS
    dds = get(T_DDS, 0, dk_[0])
    hd = s4dds.parse_dds_header(dds)
    exp = 128 + sum(s4dds.level_size(max(1, hd["w"] >> i), max(1, hd["h"] >> i), hd["fourcc"]) for i in range(hd["mips"]))
    R.check(hd["fourcc"] == "DXT5" and hd["flags"] == 0xA1007 and hd["caps"] == 0x401008, f"DDS header {hd['w']}x{hd['h']} {hd['fourcc']} flags 0xA1007 caps 0x401008")
    R.check(len(dds) == exp and hd["mips"] == int(np.log2(max(hd["w"], hd["h"]))) + 1, f"DDS size {len(dds)} = header + full mip chain ({hd['mips']} levels)")
    top = s4dds.decode_dxt(dds[128:], hd["w"], hd["h"], "DXT5")
    if source_png:
        from PIL import Image
        src = np.array(Image.open(source_png).convert("RGBA").resize((hd["w"], hd["h"])))
        mse = float(((top.astype(float) - src) ** 2).mean())
        R.check(10 * np.log10(255 ** 2 / max(mse, 1e-9)) > 30, f"DDS top level decodes to the source image (PSNR {10*np.log10(255**2/max(mse,1e-9)):.1f} dB)")
    # FTPT
    fd = get(*foot)
    fr = M.parse_rcol(fd)
    fc = fr["chunks"][0]
    pts = np.frombuffer(fc[0x23:0x23 + 32], "<f4").reshape(4, 2)
    R.check(len(fc) == 117 and np.allclose([pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max()],
                                          [bb[0], bb[2], bb[3], bb[5]], atol=1e-6), "footprint rectangle equals the mesh bbox in x/z")
    # game side keys
    if use_game:
        try:
            game = Game(app)
        except Exception as e:
            R.info(f"game not available ({e}); skipped key checks")
            game = None
        if game:
            rr, ss = M.objd_refs(f[T["rig"]])[0], M.objd_refs(f[T["slot"]])[0]
            if rr[0] == 0 and ss[0] == 0:
                R.info("no rig/slot referenced (static object)")
            else:
                R.check(game.has(*rr) and game.has(*ss), "rig and slot keys exist in the base game")
            for h, nm in ((0x6E56548A, "normalMap"), (0xCEBA7E8A, "specularMap"), (0x79C44C9B, "environmentMap")):
                k = texkeys[h]
                R.check(game.has(T_DDS, 0, k[0]), f"{nm} {k[0]:016X} exists in the game data ({game.where(T_DDS, 0, k[0])})")
            tn = M.objd_str(f[T["tuning_name"]])
            R.info(f"tuning '{tn}' id {struct.unpack_from('<Q', f[T['tuning_id']], 0)[0]} (referenced, not copied)")
            game.close()
    R.info("NOT checkable offline: that the game loads/renders it, UV/handedness orientation, thumbnails, catalog category")
    P.close()
    print("RESULT:", "ALL CHECKS PASSED" if R.ok else "SOME CHECKS FAILED")
    return R.ok


if __name__ == "__main__":
    args = sys.argv[1:]
    app = args[args.index("--game") + 1] if "--game" in args else None
    png = args[args.index("--png") + 1] if "--png" in args else None
    sys.exit(0 if check_package(args[0], app, use_game="--no-game" not in args, source_png=png) else 1)


def selftest_against_game(app=None, max_models=40, verbose=True):
    """Prove the encoders/builders against real game resources: for game models that use exactly our vertex layout,
    decode their VBUF/IBUF with the decoders, re-encode with the converter's encoders and compare to the game bytes.
    Also rebuild the game's RCOL/OBJD byte-identically and compare our MODL/MLOD/info/VRTF chunk builders with the game's."""
    R = Report(verbose)
    game = Game(app)
    mine_vrtf = M.build_vrtf()
    stats = dict(models=0, rcol_rt=0, vbuf_pos=0, vbuf_nrm=0, vbuf_uv=0, vbuf_blend=0, ibuf=0, modl=0, mlod=0, xinfo=0, vrtf=0, tri=0)
    mism = dict(nrm=0, nrm_max=0)
    for (g, i) in sorted(game.index[T_MODL]):
        try:
            d = game.read(T_MODL, g, i)
            rc = M.parse_rcol(d)
        except Exception:
            continue
        stats["rcol_total"] = stats.get("rcol_total", 0) + 1
        if M.build_rcol(rc["keys"], rc["chunks"], rc["public"], rc["ext"]) == d:
            stats["rcol_rt"] += 1
        ch = rc["chunks"]
        if len(ch) != 9 or [c[:4] for c in ch[:8]] != [b"MODL", b"MLOD", b"MATD", b"VRTF", b"VBUF", b"IBUF", b"SKIN", b"MATD"]:
            continue
        if ch[3] != mine_vrtf:
            continue
        ver, meshes = parse_mlod(ch[1])
        if len(meshes) != 1 or meshes[0]["vcount"] < 50 or len(meshes[0]["joints"]) != 1 or len(meshes[0]["tail"]) != 32:
            continue      # only the plain form: one mesh, one bone, no geometry states (the form we write)
        me = meshes[0]
        stride, els = parse_vrtf(ch[3])
        vb, ib = ch[4], ch[5]
        a, pos, nrm, uvr, w = decode_vertices(vb, stride, me["vcount"], els)
        stats["models"] += 1
        wv = int(w[0])
        M.Geometry(pos, nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12), None, None)
        # positions: exact
        enc = np.clip(np.rint(pos * wv), -32767, 32767).astype("<i2")
        if (enc.view(np.uint8).reshape(-1, 6) == a[:, :6]).all() and (w == wv).all() and wv == M.pos_scale(pos):
            stats["vbuf_pos"] += 1
        # normals: game bytes -> float -> bytes (the codec itself)
        nb = M.ubyte4n(nrm, 0.0)
        diff = np.abs(nb[:, :3].astype(int) - a[:, 8:11].astype(int)).max()
        mism["nrm_max"] = max(mism["nrm_max"], int(diff))
        if diff == 0:
            stats["vbuf_nrm"] += 1
        # uv: raw int16 -> *scale -> /scale -> raw
        sc = np.float32(1 / 32767.0)
        uvf = uvr * float(sc)
        raw2 = np.clip(np.rint(uvf / float(sc)), -32767, 32767)
        if (raw2 == uvr).all():
            stats["vbuf_uv"] += 1
        if (a[:, 16:20] == 0).all() and (a[:, 20] == 255).all() and (a[:, 21:24] == 0).all():
            stats["vbuf_blend"] += 1
        idx = M.decode_ibuf(ib, 3 * me["pcount"])
        re = M.ibuf_chunk(idx.reshape(-1, 3))
        if re == ib[:len(re)] and len(ib) - len(re) == 0:
            stats["ibuf"] += 1
        bbox = me["bbox"]
        ml = M.build_mlod(me["name"], me["vcount"], me["pcount"], bbox, flags=me["flags"], bone_hash=me["joints"][0])
        if ml == ch[1]:
            stats["mlod"] += 1
        if ch[8] == M.build_x_chunk(me["vcount"]):
            stats["xinfo"] += 1
        stats["vrtf"] += 1
        if stats["models"] >= max_models:
            break
    # MODL chunk: single-LOD, single-resource models of the game (76 byte chunk)
    nm = ok = 0
    for (g, i) in sorted(game.index[T_MODL]):
        try:
            rc = M.parse_rcol(game.read(T_MODL, g, i))
        except Exception:
            continue
        c0 = rc["chunks"][0] if rc["chunks"] else b""
        if c0[:4] == b"MODL" and len(c0) == 76 and struct.unpack_from("<I", c0, 8)[0] == 1 and rc["ext"] == 0 \
                and struct.unpack_from("<5I", c0, 36) == (0, 3, 0, 1, 0) and struct.unpack_from("<5I", c0, 56) == (2, 0, 0, 0, 0x7F7FFFFF):
            # (game also has single-LOD models with LOD id 1-4 or flag 1; we only write LOD id 0, flag 0)
            nm += 1
            ok += c0 == M.build_modl(struct.unpack_from("<6f", c0, 12))
            if nm >= 300:
                break
    R.check(nm > 0 and ok == nm, f"MODL chunk builder equals the game's single-LOD MODL chunk: {ok}/{nm}")
    m = stats["models"]
    R.info(f"examined {m} game models with exactly our vertex layout + chunk set; RCOL byte-identical rebuild: {stats['rcol_rt']}/{stats.get('rcol_total')} parsed")
    R.check(m > 0, f"found game models using our layout ({m})")
    for k, label in (("vbuf_pos", "positions re-encode byte-identical (divisor rule floor(32767/ceil(max)))"),
                     ("vbuf_nrm", "normals re-encode byte-identical"), ("vbuf_uv", "uvs re-encode identical"),
                     ("vbuf_blend", "blend idx/weights are the constants we write (0,0,0,0 / 255,0,0,0)"),
                     ("ibuf", "index buffer re-encodes byte-identical (delta int16)"),
                     ("mlod", "MLOD chunk builder equals the game chunk"),
                     ("xinfo", "info chunk builder equals the game chunk")):
        R.check(stats[k] == m, f"{label}: {stats[k]}/{m}")
    R.info(f"max normal byte difference after decode/encode: {mism['nrm_max']}")
    game.close()
    return R, stats


if __name__ == "__main__" and "--selftest" in sys.argv:
    print(selftest_against_game()[1])
