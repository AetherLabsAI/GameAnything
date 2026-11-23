"""DDS (DXT5/DXT1) writer and reader for Sims 4 textures (resource type 0x00B2D882). numpy + PIL only.

The game's own textures are mostly "DST1/DST5" (DXT blocks shuffled into streams) but plain DXT1/DXT5 DDS files with a
standard 124-byte header are also present in the game data, so we write plain DXT5 with a full mip chain.
Header (copied from the game's own DDS): flags 0x000A1007 (caps|height|width|pixelformat|mipmapcount|linearsize),
linear size = size of the top level, depth field = 1, pixel format size 32 / flags 4 (FOURCC) / 'DXT5', caps 0x00401008.
"""
import struct
import numpy as np

DDS_FLAGS = 0x000A1007
DDS_CAPS = 0x00401008


def _pad4(a):
    h, w = a.shape[:2]
    ph, pw = (-h) % 4, (-w) % 4
    if ph or pw:
        a = np.pad(a, ((0, ph), (0, pw), (0, 0)), mode="edge")
    return a


def _blocks(a):
    """(H,W,C) -> (nblocks,16,C), raster order of 4x4 blocks."""
    a = _pad4(a)
    h, w, c = a.shape
    return a.reshape(h // 4, 4, w // 4, 4, c).transpose(0, 2, 1, 3, 4).reshape(-1, 16, c)


def _rgb565(rgb):
    r = np.clip(np.rint(rgb[..., 0] * 31 / 255), 0, 31).astype(np.uint16)
    g = np.clip(np.rint(rgb[..., 1] * 63 / 255), 0, 63).astype(np.uint16)
    b = np.clip(np.rint(rgb[..., 2] * 31 / 255), 0, 31).astype(np.uint16)
    return (r << 11) | (g << 5) | b


def _from565(c):
    r = ((c >> 11) & 31).astype(np.float32) * 255 / 31
    g = ((c >> 5) & 63).astype(np.float32) * 255 / 63
    b = (c & 31).astype(np.float32) * 255 / 31
    return np.stack([r, g, b], -1)


def _color_blocks(px):
    """px: (n,16,3) float32 -> (n,8) uint8 DXT1-style colour block (4-colour mode, c0 > c1)."""
    n = len(px)
    mean = px.mean(1, keepdims=True)
    d = px - mean
    cov = np.einsum("nki,nkj->nij", d, d)
    axis = np.tile(np.array([0.57735, 0.57735, 0.57735], np.float32), (n, 1))
    for _ in range(6):
        axis = np.einsum("nij,nj->ni", cov, axis)
        nrm = np.linalg.norm(axis, axis=1, keepdims=True)
        axis = np.where(nrm > 1e-6, axis / np.maximum(nrm, 1e-6), np.array([0.57735, 0.57735, 0.57735], np.float32))
    t = np.einsum("nki,ni->nk", d, axis)
    p0 = mean[:, 0] + axis * t.max(1, keepdims=True)
    p1 = mean[:, 0] + axis * t.min(1, keepdims=True)
    c0 = _rgb565(np.clip(p0, 0, 255)); c1 = _rgb565(np.clip(p1, 0, 255))
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    flat = c0 == c1
    pal = np.zeros((n, 4, 3), np.float32)
    e0, e1 = _from565(c0), _from565(c1)
    pal[:, 0], pal[:, 1] = e0, e1
    pal[:, 2] = (2 * e0 + e1) / 3
    pal[:, 3] = (e0 + 2 * e1) / 3
    dist = ((px[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1)  # n,16,4
    idx = dist.argmin(-1).astype(np.uint32)
    idx = np.where(flat[:, None], 0, idx)
    bits = np.zeros(n, np.uint32)
    for k in range(16):
        bits |= idx[:, k] << np.uint32(2 * k)
    out = np.zeros((n, 8), np.uint8)
    out[:, 0] = c0 & 255; out[:, 1] = c0 >> 8; out[:, 2] = c1 & 255; out[:, 3] = c1 >> 8
    for k in range(4):
        out[:, 4 + k] = (bits >> np.uint32(8 * k)) & 255
    return out


def _alpha_blocks(al):
    """al: (n,16) float -> (n,8) uint8 DXT5 alpha block (8-value mode, a0 > a1)."""
    n = len(al)
    amax = al.max(1); amin = al.min(1)
    a0 = np.rint(amax).astype(np.int32); a1 = np.rint(amin).astype(np.int32)
    flat = a0 == a1
    pal = np.zeros((n, 8), np.float32)
    pal[:, 0] = a0; pal[:, 1] = a1
    for i in range(1, 7):
        pal[:, 1 + i] = ((7 - i) * a0 + i * a1) / 7
    dist = np.abs(al[:, :, None] - pal[:, None, :])
    idx = dist.argmin(-1).astype(np.uint64)
    idx = np.where(flat[:, None], 0, idx)
    bits = np.zeros(n, np.uint64)
    for k in range(16):
        bits |= idx[:, k] << np.uint64(3 * k)
    out = np.zeros((n, 8), np.uint8)
    out[:, 0] = a0; out[:, 1] = a1
    for k in range(6):
        out[:, 2 + k] = (bits >> np.uint64(8 * k)) & np.uint64(255)
    return out


def compress_level(rgba, fmt="DXT5"):
    """rgba (H,W,4) uint8 -> compressed bytes of one mip level."""
    b = _blocks(rgba.astype(np.float32))
    col = _color_blocks(b[:, :, :3])
    if fmt == "DXT1":
        return col.tobytes()
    al = _alpha_blocks(b[:, :, 3])
    return np.concatenate([al, col], 1).tobytes()


def mip_chain(rgba):
    """Box-filter mip chain down to 1x1. rgba (H,W,4) uint8, power-of-two sides."""
    levels = [rgba]
    cur = rgba.astype(np.float32)
    while cur.shape[0] > 1 or cur.shape[1] > 1:
        h, w = cur.shape[:2]
        if h > 1:
            cur = (cur[0::2] + cur[1::2]) / 2
        if w > 1:
            cur = (cur[:, 0::2] + cur[:, 1::2]) / 2
        levels.append(np.clip(np.rint(cur), 0, 255).astype(np.uint8))
        cur = levels[-1].astype(np.float32)
    return levels


def level_size(w, h, fmt):
    return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * (8 if fmt == "DXT1" else 16)


def make_dds(rgba, fmt="DXT5"):
    """rgba (H,W,4) uint8 (H,W powers of two) -> full DDS file bytes with all mipmaps."""
    h, w = rgba.shape[:2]
    levels = mip_chain(rgba)
    body = b"".join(compress_level(l, fmt) for l in levels)
    hdr = bytearray(128)
    hdr[0:4] = b"DDS "
    struct.pack_into("<IIIIIII", hdr, 4, 124, DDS_FLAGS, h, w, level_size(w, h, fmt), 1, len(levels))
    struct.pack_into("<II4s", hdr, 76, 32, 4, fmt.encode())  # pixel format at 0x4C
    struct.pack_into("<I", hdr, 108, DDS_CAPS)
    return bytes(hdr) + body


def parse_dds_header(d):
    if d[:4] != b"DDS " or len(d) < 128:
        raise ValueError("not a DDS")
    size, flags, h, w, lin, depth, mips = struct.unpack_from("<IIIIIII", d, 4)
    pfsize, pfflags, fourcc = struct.unpack_from("<II4s", d, 76)
    caps = struct.unpack_from("<I", d, 108)[0]
    return dict(size=size, flags=flags, h=h, w=w, linear=lin, depth=depth, mips=mips, pfsize=pfsize,
                pfflags=pfflags, fourcc=fourcc.decode("latin1"), caps=caps)


def decode_dxt(data, w, h, fmt):
    """Decode one DXT1/DXT5 level to (h,w,4) uint8 (for validation/preview)."""
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    n = bw * bh
    bs = 8 if fmt == "DXT1" else 16
    blk = np.frombuffer(data[: n * bs], np.uint8).reshape(n, bs)
    cb = blk[:, bs - 8:]
    c0 = cb[:, 0].astype(np.uint16) | (cb[:, 1].astype(np.uint16) << 8)
    c1 = cb[:, 2].astype(np.uint16) | (cb[:, 3].astype(np.uint16) << 8)
    e0, e1 = _from565(c0), _from565(c1)
    pal = np.stack([e0, e1, (2 * e0 + e1) / 3, (e0 + 2 * e1) / 3], 1)
    bits = cb[:, 4].astype(np.uint32) | (cb[:, 5].astype(np.uint32) << 8) | (cb[:, 6].astype(np.uint32) << 16) | (cb[:, 7].astype(np.uint32) << 24)
    px = np.zeros((n, 16, 4), np.float32)
    px[:, :, 3] = 255
    for k in range(16):
        s = ((bits >> np.uint32(2 * k)) & 3).astype(int)
        px[:, k, :3] = pal[np.arange(n), s]
    if fmt == "DXT5":
        a0 = blk[:, 0].astype(np.float32); a1 = blk[:, 1].astype(np.float32)
        ap = np.zeros((n, 8), np.float32); ap[:, 0] = a0; ap[:, 1] = a1
        for i in range(1, 7):
            ap[:, 1 + i] = ((7 - i) * a0 + i * a1) / 7
        ab = np.zeros(n, np.uint64)
        for k in range(6):
            ab |= blk[:, 2 + k].astype(np.uint64) << np.uint64(8 * k)
        for k in range(16):
            s = ((ab >> np.uint64(3 * k)) & np.uint64(7)).astype(int)
            px[:, k, 3] = ap[np.arange(n), s]
    px = px.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return np.clip(px[:h, :w], 0, 255).astype(np.uint8)
