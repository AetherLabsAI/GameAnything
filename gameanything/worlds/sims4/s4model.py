"""Sims 4 object resource formats (OBJD, COBJ, RCOL model chunks, FTPT) as reverse engineered from the game's own data.

Everything here was checked against real game resources (see CONVERTER_NOTES.md). All structures are little endian.

RCOL (type 0x01661233 'MODL' resource, also FTPT):
  u32 version=3, u32 public chunks, u32 0, u32 external count, u32 internal count,
  keys: (internal + external) x (u64 instance, u32 type, u32 group), then internal chunk table (u32 pos, u32 size) each,
  then the chunks, each starting 4-byte aligned (zero padding).
  Chunk references inside chunks: (nibble << 28) | index1based;  nibble 0 = public chunk (first `public` chunks),
  1 = private chunk (the chunks after the public ones), 3 = external key.
"""
import math
import struct

import numpy as np


FLT_MAX = 0x7F7FFFFF
T_DDS = 0x00B2D882

# ------------------------------------------------------------------------------------------------ RCOL


def parse_rcol(d):
    ver, pub, unused, ext, nint = struct.unpack_from("<5I", d, 0)
    p = 20
    keys = []
    for _ in range(nint + ext):
        inst, t, g = struct.unpack_from("<QII", d, p); p += 16
        keys.append((t, g, inst))
    table = []
    for _ in range(nint):
        table.append(struct.unpack_from("<II", d, p)); p += 8
    chunks = [bytes(d[a:a + s]) for a, s in table]
    if table and table[0][0] != p:
        raise ValueError("RCOL: first chunk does not follow the table")
    for (a, s), (a2, _) in zip(table, table[1:] + [(len(d), 0)]):
        pad = (-(a + s)) % 4 if a2 != len(d) else 0
        if a + s + pad != a2 or any(d[a + s:a + s + pad]):
            raise ValueError("RCOL: chunks are not contiguous (4 byte aligned, zero padded)")
    return dict(version=ver, public=pub, unused=unused, nint=nint, ext=ext, keys=keys, chunks=chunks)


def build_rcol(keys, chunks, public, ext=0, version=3):
    nint = len(chunks)
    if len(keys) != nint + ext:
        raise ValueError("keys must be internal + external")
    head = struct.pack("<5I", version, public, 0, ext, nint)
    kb = b"".join(struct.pack("<QII", i, t, g) for t, g, i in keys)
    pos = 20 + 16 * len(keys) + 8 * nint
    tb = b""; body = b""
    for k, c in enumerate(chunks):
        tb += struct.pack("<II", pos, len(c)); body += c; pos += len(c)
        if k < nint - 1:
            pad = (-pos) % 4
            body += b"\0" * pad; pos += pad
    return head + kb + tb + body


# ------------------------------------------------------------------------------------------------ OBJD
OBJD_TAG = dict(name=0xE7F07786, tuning_name=0x790FA4BC, tuning_id=0xB994039B, icon=0xCADED888, rig=0xE206AE4F,
                slot=0x8A85AFF3, model=0x8D20ACC6, footprint=0x6C737AD8, components=0xE6E421FB,
                variant=0xECD5A95F, price=0xE4F4FAA4)


def parse_objd(d):
    """-> (version, [(tag, bytes)] in file order). Fields are contiguous from offset 6 to the table."""
    ver, tp = struct.unpack_from("<HI", d, 0)
    n = struct.unpack_from("<H", d, tp)[0]
    ents = [struct.unpack_from("<II", d, tp + 2 + 8 * i) for i in range(n)]
    offs = [o for _, o in ents] + [tp]
    if offs[0] != 6 or offs != sorted(offs):
        raise ValueError("OBJD: unexpected field layout")
    return ver, [(t, bytes(d[o:offs[i + 1]])) for i, (t, o) in enumerate(ents)]


def build_objd(ver, fields):
    body = b"".join(b for _, b in fields)
    tp = 6 + len(body)
    table = struct.pack("<H", len(fields))
    o = 6
    for t, b in fields:
        table += struct.pack("<II", t, o); o += len(b)
    return struct.pack("<HI", ver, tp) + body + table


def objd_str(b):
    n = struct.unpack_from("<I", b, 0)[0]
    return b[4:4 + n].decode("latin1")


def objd_pack_str(s):
    e = s.encode("latin1")
    return struct.pack("<I", len(e)) + e


def objd_refs(b):
    """ref list field -> [(type, group, instance)]; instance is stored as (hi u32, lo u32)."""
    n = (len(b) - 4) // 16
    out = []
    for j in range(n):
        hi, lo, t, g = struct.unpack_from("<IIII", b, 4 + 16 * j)
        out.append((t, g, (hi << 32) | lo))
    return out


def objd_pack_refs(refs):
    return struct.pack("<I", 4 * len(refs)) + b"".join(
        struct.pack("<IIII", i >> 32, i & 0xFFFFFFFF, t, g) for t, g, i in refs)


# ------------------------------------------------------------------------------------------------ COBJ


def patch_cobj(c, name_hash, desc_hash, price, unique64):
    """Copy of a game catalog entry with our name/description string keys, price and a unique 64 bit id.
    Layout (v0x1A): u32 ver, u32 0x0B, u32 name key, u32 desc key, u32 price, ... The unique id is the 8 bytes right
    before the byte pattern 00 00 01 00 00 00 01 (after offset 0x80); in the game data this value differs per object."""
    c = bytearray(c)
    if struct.unpack_from("<II", c, 0) != (0x1A, 0x0B):
        raise ValueError("COBJ: unexpected version (expected 0x1A / 0x0B)")
    struct.pack_into("<III", c, 8, name_hash, desc_hash, price)
    pat = bytes([0, 0, 1, 0, 0, 0, 1])
    pos = bytes(c).find(pat, 0x80)
    if pos < 8:
        raise ValueError("COBJ: unique id pattern not found")
    struct.pack_into("<Q", c, pos - 8, unique64)
    return bytes(c)


# ------------------------------------------------------------------------------------------------ geometry
class Geometry:
    """Unique vertices (position, normal, uv in DirectX convention) and triangles."""
    def __init__(self, pos, nrm, uv, tris):
        self.pos, self.nrm, self.uv, self.tris = pos, nrm, uv, tris


def load_obj(path, flip_v=True, mirror_x=False, flip_winding=False):
    """Wavefront OBJ (v/vt/vn/f) -> Geometry. v is flipped (v_game = 1 - v_obj) because the game samples v=0 at the
    top row of the DDS (checked on the game's own car mesh+texture). Faces are fan-triangulated."""
    V, VT, VN = [], [], []
    faces = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line[:2] == "v ":
                V.append([float(x) for x in line.split()[1:4]])
            elif line[:3] == "vt ":
                VT.append([float(x) for x in line.split()[1:3]])
            elif line[:3] == "vn ":
                VN.append([float(x) for x in line.split()[1:4]])
            elif line[:2] == "f ":
                faces.append(line.split()[1:])
    if not V or not faces:
        raise ValueError("OBJ has no vertices or faces")
    V = np.array(V, np.float64); VT = np.array(VT, np.float64).reshape(-1, 2); VN = np.array(VN, np.float64).reshape(-1, 3)

    def ix(s, n):
        i = int(s)
        return i - 1 if i > 0 else n + i

    table = {}
    verts = []
    tris = []
    for fc in faces:
        ids = []
        for tok in fc:
            parts = tok.split("/")
            v = ix(parts[0], len(V))
            t = ix(parts[1], len(VT)) if len(parts) > 1 and parts[1] else -1
            n = ix(parts[2], len(VN)) if len(parts) > 2 and parts[2] else -1
            key = (v, t, n)
            j = table.get(key)
            if j is None:
                j = len(verts); table[key] = j; verts.append(key)
            ids.append(j)
        for k in range(1, len(ids) - 1):
            tris.append((ids[0], ids[k], ids[k + 1]))
    vi = np.array([k[0] for k in verts]); ti = np.array([k[1] for k in verts]); ni = np.array([k[2] for k in verts])
    pos = V[vi]
    uv = VT[ti] if len(VT) and (ti >= 0).all() else np.zeros((len(verts), 2))
    tris = np.array(tris, np.int64)
    if mirror_x:
        pos = pos * np.array([-1, 1, 1]); flip_winding = not flip_winding
    if flip_winding:
        tris = tris[:, ::-1].copy()
    if flip_v:
        uv = np.stack([uv[:, 0], 1.0 - uv[:, 1]], 1)
    if len(VN) and (ni >= 0).all():
        nrm = VN[ni]
        if mirror_x:
            nrm = nrm * np.array([-1, 1, 1])
    else:
        nrm = smooth_normals(pos, tris)
    ln = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = nrm / np.maximum(ln, 1e-12)
    return Geometry(pos, nrm, uv, tris)


def smooth_normals(pos, tris):
    n = np.zeros_like(pos)
    fn = np.cross(pos[tris[:, 1]] - pos[tris[:, 0]], pos[tris[:, 2]] - pos[tris[:, 0]])
    for k in range(3):
        np.add.at(n, tris[:, k], fn)
    return n


def tangents(pos, nrm, uv, tris):
    """Per-vertex tangent (unit xyz) and handedness w (+1/-1) from UV derivatives."""
    t = np.zeros_like(pos); b = np.zeros_like(pos)
    p0, p1, p2 = pos[tris[:, 0]], pos[tris[:, 1]], pos[tris[:, 2]]
    u0, u1, u2 = uv[tris[:, 0]], uv[tris[:, 1]], uv[tris[:, 2]]
    e1, e2 = p1 - p0, p2 - p0
    d1, d2 = u1 - u0, u2 - u0
    det = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    r = np.where(np.abs(det) > 1e-20, 1.0 / np.where(np.abs(det) > 1e-20, det, 1), 0.0)[:, None]
    tt = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) * r
    bb = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) * r
    for k in range(3):
        np.add.at(t, tris[:, k], tt); np.add.at(b, tris[:, k], bb)
    t = t - nrm * (nrm * t).sum(1, keepdims=True)
    ln = np.linalg.norm(t, axis=1, keepdims=True)
    fallback = np.cross(nrm, np.array([0.0, 1.0, 0.0]))
    fl = np.linalg.norm(fallback, axis=1, keepdims=True)
    fallback = np.where(fl > 1e-6, fallback / np.maximum(fl, 1e-12), np.array([1.0, 0.0, 0.0]))
    t = np.where(ln > 1e-9, t / np.maximum(ln, 1e-12), fallback)
    w = np.where((np.cross(nrm, t) * b).sum(1) < 0, -1.0, 1.0)
    return t, w


def ubyte4n(v3, w=0.0):
    """unit vector -> 4 bytes, byte = round((v+1)*127.5) (game: 0xFF = +1, 0x80 ~ 0)."""
    a = np.clip(np.rint((np.asarray(v3) + 1.0) * 127.5), 0, 255).astype(np.uint8)
    wb = np.full((len(a), 1), int(round((w + 1.0) * 127.5)) if np.isscalar(w) else 0, np.uint8)
    if not np.isscalar(w):
        wb = np.clip(np.rint((np.asarray(w)[:, None] + 1.0) * 127.5), 0, 255).astype(np.uint8)
    return np.concatenate([a, wb], 1)


# VRTF used for the object: stride 28, 6 elements (the layout of the game's rigged decor, 3404 meshes)
#  (usage, usage index, format, offset): pos Short4@0, normal UByte4N@8, uv Short2@12, blend idx UByte4@16,
#  blend weights UByte4N@20, tangent UByte4N@24
VRTF_ELEMENTS = [(0, 0, 7, 0), (1, 0, 8, 8), (2, 0, 6, 12), (3, 0, 4, 16), (4, 0, 8, 20), (5, 0, 8, 24)]
STRIDE = 28
# Layouts seen in the game: 'skin28' (rigged decor, above), 'static20' (Short4 pos, normal, uv, tangent; static props and
# vehicles, no SKIN chunk) and 'float32' (Float3 pos, Float3 normal, Float2 uv, no quantisation; 652 static game models).
LAYOUTS = {
    "skin28": dict(elements=VRTF_ELEMENTS, stride=28, skinned=True, info=(2, 2, 1, 2, 1, 1, 1)),
    "static20": dict(elements=[(0, 0, 7, 0), (1, 0, 8, 8), (2, 0, 6, 12), (5, 0, 8, 16)], stride=20, skinned=False,
                     info=(2, 2, 1, 2, 1)),
    "float32": dict(elements=[(0, 0, 2, 0), (1, 0, 2, 12), (2, 0, 1, 24)], stride=32, skinned=False,
                    info=(1, 1, 1, 1, 1, 1, 1, 1)),
}


def build_vrtf(layout="skin28"):
    L = LAYOUTS[layout]
    return b"VRTF" + struct.pack("<IIII", 2, L["stride"], len(L["elements"]), 0) + b"".join(bytes(e) for e in L["elements"])


def pos_scale(pos):
    """Short4 position divisor w: positions are int16 / w. w = floor(32767 / ceil(max |coord|)) (as in game data)."""
    m = float(np.abs(pos).max())
    c = max(1, int(math.ceil(m - 1e-9)))
    return 32767 // c


def uv_scale(uv):
    """UV raw int16 * scale; scale = ceil(max|uv|) / 32767 (stored as float32 in the material 'UVScales')."""
    m = max(1, int(math.ceil(float(np.abs(uv).max()) - 1e-9)))
    return np.float32(m / 32767.0)


def build_vbuf(g, w, uvs, layout="skin28"):
    n = len(g.pos)
    if layout == "float32":
        buf = np.zeros((n, 32), np.uint8)
        buf[:, 0:12] = g.pos.astype("<f4").view(np.uint8).reshape(n, 12)
        buf[:, 12:24] = g.nrm.astype("<f4").view(np.uint8).reshape(n, 12)
        buf[:, 24:32] = g.uv.astype("<f4").view(np.uint8).reshape(n, 8)
        return buf
    if layout == "static20":
        t, tw = tangents(g.pos, g.nrm, g.uv, g.tris)
        buf = np.zeros((n, 20), np.uint8)
        p = np.clip(np.rint(g.pos * w), -32767, 32767).astype("<i2")
        buf[:, 0:8] = np.concatenate([p, np.full((n, 1), w, "<i2")], 1).view(np.uint8).reshape(n, 8)
        buf[:, 8:12] = ubyte4n(g.nrm, 0.0)
        buf[:, 12:16] = np.clip(np.rint(g.uv / float(uvs)), -32767, 32767).astype("<i2").view(np.uint8).reshape(n, 4)
        buf[:, 16:20] = ubyte4n(t, tw)
        return buf
    t, tw = tangents(g.pos, g.nrm, g.uv, g.tris)
    buf = np.zeros((n, STRIDE), np.uint8)
    p = np.clip(np.rint(g.pos * w), -32767, 32767).astype("<i2")
    pos4 = np.concatenate([p, np.full((n, 1), w, "<i2")], 1)
    buf[:, 0:8] = pos4.view(np.uint8).reshape(n, 8)
    buf[:, 8:12] = ubyte4n(g.nrm, 0.0)
    ruv = np.clip(np.rint(g.uv / float(uvs)), -32767, 32767).astype("<i2")
    buf[:, 12:16] = ruv.view(np.uint8).reshape(n, 4)
    buf[:, 16:20] = 0
    buf[:, 20] = 255
    buf[:, 24:28] = ubyte4n(t, tw)
    return buf


def vbuf_chunk(buf, x_ref):
    return b"VBUF" + struct.pack("<III", 0x101, 0, x_ref) + buf.tobytes()


def ibuf_chunk(tris):
    """int16 delta coded indices (first index relative to 0), header (ver 2, flags 1, 0)."""
    idx = tris.reshape(-1).astype(np.int64)
    d = np.diff(idx, prepend=0)
    d = ((d + 32768) % 65536 - 32768).astype("<i2")
    return b"IBUF" + struct.pack("<III", 2, 1, 0) + d.tobytes()


def decode_ibuf(c, n_idx):
    d = np.frombuffer(c[16:16 + 2 * n_idx], "<i2").astype(np.int64)
    return (np.cumsum(d) & 0xFFFF)


def build_x_chunk(vcount, layout="skin28"):
    """Unnamed info chunk the game writes last: [1, stride, vertex count, 0, <per element codes>] (skin28: 2,2,1,2,1,1,1)."""
    L = LAYOUTS[layout]
    return struct.pack("<%dI" % (4 + len(L["info"])), 1, L["stride"], vcount, 0, *L["info"])


def build_modl(bbox, ):
    """MODL chunk, ver 0x300, one LOD (id 0) stored in this resource (public chunk #2)."""
    return (b"MODL" + struct.pack("<II", 0x300, 1) + struct.pack("<6f", *bbox) +
            struct.pack("<5I", 0, 3, 0, 1, 0) + struct.pack("<IIIfI", 2, 0, 0, 0.0, FLT_MAX))


def build_mlod(name_hash, vcount, pcount, bbox, flags=0x185003, bone_hash=0xCD68F001, layout="skin28"):
    """MLOD chunk ver 0x205 with a single mesh. Chunk refs: material=private#1, VRTF=#2, VBUF=#3, IBUF=#4, SKIN=#5,
    default MATD=#6 (private chunk numbers, 1-based, counted after the two public chunks)."""
    skinned = LAYOUTS[layout]["skinned"]
    m = struct.pack("<I", name_hash)
    m += struct.pack("<4I", 0x10000001, 0x10000002, 0x10000003, 0x10000004)
    m += struct.pack("<I", flags) + struct.pack("<4I", 0, 0, 0, 0)
    m += struct.pack("<2I", vcount, pcount) + struct.pack("<6f", *bbox)
    if skinned:      # skin ref=#5, one bone, default material=#6;  static: no skin, default material=#5
        m += struct.pack("<I", 0x10000005) + struct.pack("<II", 1, bone_hash)
    else:
        m += struct.pack("<II", 0, 0)
    m += struct.pack("<I", 0x10000006 if skinned else 0x10000005) + struct.pack("<4I", 0, 0, 0, 0) + struct.pack("<f", 1.0) + struct.pack("<2I", 0, 0)
    return b"MLOD" + struct.pack("<III", 0x205, 1, len(m)) + m


# ------------------------------------------------------------------------------------------------ MATD
def matd_entries(c):
    ver, nameh, shader, mlen = struct.unpack_from("<IIII", c, 4)
    if c[28:32] != b"MTRL":
        raise ValueError("MATD: no MTRL block")
    cnt = struct.unpack_from("<I", c, 40)[0]
    ents = [struct.unpack_from("<IIII", c, 44 + 16 * i) for i in range(cnt)]
    return dict(name=nameh, shader=shader, ents=ents)


def patch_matd(c, name_hash, tex_inst, uv_scale_f32):
    """Copy a game material (phong) replacing: material name, diffuse/alpha texture key, and the UV scale floats."""
    c = bytearray(c)
    M = matd_entries(c)
    struct.pack_into("<I", c, 8, name_hash)
    old_scale = None
    for h, t, n, o in M["ents"]:
        if h == 0x420520E9 and t == 1:           # UVScales
            old_scale = struct.unpack_from("<I", c, 28 + o)[0]
    new_bits = struct.unpack("<I", struct.pack("<f", float(uv_scale_f32)))[0]
    found_diffuse = False
    for h, t, n, o in M["ents"]:
        if h in (0x6CC0FD85, 0xC3FAAC4F) and (t & 0xFFFF) == 4:   # diffuseMap, alphaMap
            struct.pack_into("<QII", c, 28 + o, tex_inst, T_DDS, 0)
            found_diffuse = found_diffuse or h == 0x6CC0FD85
        elif t == 1 and old_scale is not None:
            for k in range(n):
                if struct.unpack_from("<I", c, 28 + o + 4 * k)[0] == old_scale:
                    struct.pack_into("<I", c, 28 + o + 4 * k, new_bits)
    if not found_diffuse:
        raise ValueError("template material has no diffuseMap parameter")
    return bytes(c)


# ------------------------------------------------------------------------------------------------ FTPT
def patch_ftpt(res, inst, bbox):
    """res = a game FTPT resource (RCOL with one 117 byte footprint chunk with one 4 point polygon).
    Replaces the instance, polygon (x,z rectangle of the bbox), min/max and the two height floats."""
    r = parse_rcol(res)
    c = bytearray(r["chunks"][0])
    if len(c) != 117 or c[:4] != b"FTPT" or c[0x22] != 4:
        raise ValueError("FTPT template is not the 117 byte single rectangle form")
    x0, y0, z0, x1, y1, z1 = bbox
    pts = [(x1, z1), (x1, z0), (x0, z0), (x0, z1)]
    for k, (x, z) in enumerate(pts):
        struct.pack_into("<2f", c, 0x23 + 8 * k, x, z)
    struct.pack_into("<4f", c, 0x54, x0, z0, x1, z1)
    struct.pack_into("<f", c, 0x68, y1)
    struct.pack_into("<f", c, 0x6D, y1)
    keys = [(0xD382BF57, 0, inst)]
    return build_rcol(keys, [bytes(c)], public=r["public"])


# ------------------------------------------------------------------------------------------------ STBL
LOCALES = {"ENG_US": 0x00, "CHS_CN": 0x01, "CHT_CN": 0x02, "CZE_CZ": 0x03, "DAN_DK": 0x04, "DUT_NL": 0x05,
           "FIN_FI": 0x06, "FRE_FR": 0x07, "GER_DE": 0x08, "ITA_IT": 0x0B, "JPN_JP": 0x0C, "KOR_KR": 0x0D,
           "NOR_NO": 0x0E, "POL_PL": 0x0F, "POR_BR": 0x11, "RUS_RU": 0x12, "SPA_ES": 0x13, "SWE_SE": 0x15}


def build_stbl(entries):
    """entries: {key hash u32: text}. Same layout as the game's own string tables."""
    items = [(h, t.encode("utf-8")) for h, t in entries.items()]
    body = b"".join(struct.pack("<IBH", h, 0, len(b)) + b for h, b in items)
    hdr = b"STBL" + struct.pack("<HBQH", 5, 0, len(items), 0) + struct.pack("<I", sum(len(b) + 1 for _, b in items))
    return hdr + body
