"""Read and write The Sims 4 .package files (DBPF 2.1) and build one from a mod folder. Pure Python 3, no dependencies.

Ported from gamebench (hosting/modlab/sims4/bin/s4pkg.py + s4build.py, the Sims 4 lab). Changes: library only (no s4build/s4pkg
split, no /lab paths), the resource type ids come from s4_types.json next to this file, files are closed, log lines go to a
callback, and the string table instance is salted with the mod name (not the folder name "package").

  python -m gameanything.native.s4pkg ls <file.package> [--type HEX]            list resources (type group instance size compression)
  python -m gameanything.native.s4pkg cat <file.package> <type> <group> <inst>   print one resource (decompressed) to stdout
  python -m gameanything.native.s4pkg find-tuning <file.package> <name>          tuning XML resources whose n="..." contains <name>

Resource keys are (type, group, instance): 32, 32 and 64 bit. Tuning XML instance ids are the FNV-64 hash of the tuning
name (fnv64); string tables (STBL) map FNV-32 hashes of keys to text.

build_from_dir(src, out) packs a folder:
  tuning/**/*.xml   tuning XML. The root's i="..." (buff, interaction, snippet, recipe, object, venue, situation, ...)
                    picks the resource type; s="..." is the instance id (decimal or 0x hex). Without s, the instance is
                    fnv64(n) with the high bit set. Write {{str:KEY}} anywhere to get the 0xHASH of string KEY, and
                    {{inst:NAME}} for the instance id (decimal) of your tuning NAME (so tuning can reference tuning).
  strings.json      {"KEY": "English text", ...} -> one string table (STBL, English); key hash = fnv32(KEY).
                    Keys may also be literal hashes ("0x1A2B3C4D").
  raw/TTTTTTTT_GGGGGGGG_IIIIIIIIIIIIIIII[.ext]   any other resource, copied as is (images, cloned object definitions, ...)
"""
import io, json, os, re, struct, sys, zlib
from pathlib import Path

FLAG_EXT = 0x80000000
COMP_NONE, COMP_ZLIB, COMP_REFPACK, COMP_STREAM, COMP_DELETED = 0x0000, 0x5A42, 0xFFFF, 0xFFFE, 0xFFE0
STBL_TYPE, STBL_GROUP = 0x220557DA, 0x80000000


def fnv64(s, high_bit=False):
    h = 0xCBF29CE484222325
    for b in s.lower().encode("utf-8"):
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF; h ^= b
    return h | (1 << 63) if high_bit else h


def fnv32(s, high_bit=False):
    h = 0x811C9DC5
    for b in s.lower().encode("utf-8"):
        h = (h * 0x01000193) & 0xFFFFFFFF; h ^= b
    return h | (1 << 31) if high_bit else h


def refpack_decompress(data):
    """EA RefPack / QFS ("internal compression", type 0xFFFF)."""
    src = memoryview(data); pos = 0
    flags = src[0]; pos = 2
    big = flags & 0x80
    if big: size = int.from_bytes(src[pos:pos + 4], "big"); pos += 4
    else: size = int.from_bytes(src[pos:pos + 3], "big"); pos += 3
    out = bytearray(); n = len(src)
    while pos < n:
        b0 = src[pos]
        if b0 < 0x80:
            b1 = src[pos + 1]; pos += 2
            plain = b0 & 3; cnt = ((b0 & 0x1C) >> 2) + 3; off = ((b0 & 0x60) << 3) + b1 + 1
        elif b0 < 0xC0:
            b1, b2 = src[pos + 1], src[pos + 2]; pos += 3
            plain = (b1 >> 6) & 3; cnt = (b0 & 0x3F) + 4; off = ((b1 & 0x3F) << 8) + b2 + 1
        elif b0 < 0xE0:
            b1, b2, b3 = src[pos + 1], src[pos + 2], src[pos + 3]; pos += 4
            plain = b0 & 3; cnt = ((b0 & 0x0C) << 6) + b3 + 5; off = ((b0 & 0x10) << 12) + (b1 << 8) + b2 + 1
        elif b0 < 0xFC:
            plain = ((b0 & 0x1F) << 2) + 4; pos += 1
            out += src[pos:pos + plain]; pos += plain; continue
        else:
            plain = b0 & 3; pos += 1
            out += src[pos:pos + plain]; break
        out += src[pos:pos + plain]; pos += plain
        start = len(out) - off
        for i in range(cnt):
            out.append(out[start + i])
    return bytes(out[:size])


class Package:
    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb")
        try: self._index()
        except Exception: self.f.close(); raise

    def _index(self):
        path = self.path
        h = self.f.read(96)
        if h[:4] != b"DBPF": raise ValueError(f"{path}: not a DBPF package")
        major, minor = struct.unpack_from("<II", h, 4)
        count = struct.unpack_from("<I", h, 36)[0]
        index_size = struct.unpack_from("<I", h, 44)[0]
        index_pos = struct.unpack_from("<I", h, 64)[0] or struct.unpack_from("<I", h, 40)[0]
        self.f.seek(index_pos); idx = self.f.read(index_size)
        flags = struct.unpack_from("<I", idx, 0)[0]; p = 4
        const = {}
        for bit, name in ((1, "type"), (2, "group"), (4, "ihi")):
            if flags & bit: const[name] = struct.unpack_from("<I", idx, p)[0]; p += 4
        self.entries = []
        for _ in range(count):
            vals = {}
            for name in ("type", "group", "ihi"):
                if name in const: vals[name] = const[name]
                else: vals[name] = struct.unpack_from("<I", idx, p)[0]; p += 4
            ilo, pos, size, dsize = struct.unpack_from("<IIII", idx, p); p += 16
            comp = COMP_NONE
            if size & FLAG_EXT:
                comp = struct.unpack_from("<H", idx, p)[0]; p += 4
            self.entries.append((vals["type"], vals["group"], (vals["ihi"] << 32) | ilo, pos, size & 0x7FFFFFFF, dsize, comp))

    def close(self): self.f.close()
    def __enter__(self): return self
    def __exit__(self, *a): self.close()

    def read(self, e):
        t, g, i, pos, size, dsize, comp = e
        self.f.seek(pos); raw = self.f.read(size)
        if comp == COMP_NONE: return raw
        if comp == COMP_ZLIB: return zlib.decompress(raw)
        if comp == COMP_REFPACK: return refpack_decompress(raw)
        raise ValueError(f"unsupported compression {comp:#x}")

    def get(self, t, g, i):
        for e in self.entries:
            if e[0] == t and e[1] == g and e[2] == i: return self.read(e)
        raise KeyError(f"{t:08X}:{g:08X}:{i:016X}")


def write_package(out, resources):
    """resources: list of (type, group, instance, bytes); zlib-compressed when that helps."""
    out = str(out)
    body = io.BytesIO(); body.write(b"\0" * 96); index = []
    for t, g, i, data in resources:
        z = zlib.compress(data, 9)
        use = z if len(z) < len(data) else data
        pos = body.tell(); body.write(use)
        index.append((t, g, i, pos, len(use), len(data), COMP_ZLIB if use is z else COMP_NONE))
    idx = io.BytesIO(); idx.write(struct.pack("<I", 0))
    for t, g, i, pos, size, dsize, comp in index:
        idx.write(struct.pack("<IIIIIII", t, g, i >> 32, i & 0xFFFFFFFF, pos, size | FLAG_EXT, dsize))
        idx.write(struct.pack("<HH", comp, 1))
    ipos = body.tell(); body.write(idx.getvalue())
    hdr = bytearray(96); hdr[0:4] = b"DBPF"
    struct.pack_into("<II", hdr, 4, 2, 1)
    struct.pack_into("<I", hdr, 36, len(index)); struct.pack_into("<I", hdr, 44, len(idx.getvalue()))
    struct.pack_into("<I", hdr, 60, 3); struct.pack_into("<I", hdr, 64, ipos)
    b = bytearray(body.getvalue()); b[0:96] = hdr
    tmp = out + ".tmp"
    with open(tmp, "wb") as f: f.write(b)
    os.replace(tmp, out)


TUNING_ROOT = re.compile(rb'<(I|M)\s[^>]*?\bn="([^"]+)"[^>]*?>', re.S)


def tuning_name(data):
    m = TUNING_ROOT.search(data[:2000]); return m.group(2).decode() if m else None


# ---------------------------------------------------------------- build a package from a folder
def types():
    """Tuning kind (the i="..." of a tuning XML root) -> resource type id; exported from the game."""
    with open(Path(__file__).with_name("s4_types.json"), encoding="utf-8") as f: return json.load(f)


def stbl(strings):
    entries = []
    for k, text in strings.items():
        h = int(k, 16) if re.fullmatch(r"0x[0-9a-fA-F]{1,8}", k) else fnv32(k)
        b = text.encode("utf-8"); entries.append((h, b))
    body = b"".join(struct.pack("<IBH", h, 0, len(b)) + b for h, b in entries)
    hdr = b"STBL" + struct.pack("<HBQH", 5, 0, len(entries), 0) + struct.pack("<I", sum(len(b) + 1 for _, b in entries))
    return hdr + body


def build_from_dir(src, out, name=None, log=None):
    """Pack <src> (layout above) into the .package <out> -> number of resources. `name` salts the string table's instance id
    (default: the folder name); `log(line)` gets one line per resource. Bad input raises ValueError."""
    src = str(src); tp = types(); res = []; log = log or (lambda s: None)
    name = name or os.path.basename(os.path.abspath(src))
    sj = os.path.join(src, "strings.json")
    if os.path.exists(sj):
        with open(sj, encoding="utf-8-sig") as f: strings = json.load(f)
    else: strings = {}
    str_hash = lambda k: "0x%08X" % (int(k, 16) if k.startswith("0x") else fnv32(k))
    tuning_files = []
    for root, _, files in os.walk(os.path.join(src, "tuning")):
        tuning_files += [os.path.join(root, f) for f in sorted(files) if f.endswith(".xml")]
    tuning_files.sort()
    # first pass: names -> instance ids (so {{inst:NAME}} works across files)
    inst_of = {}
    parsed = []
    for f in tuning_files:
        with open(f, encoding="utf-8") as fh: x = fh.read()
        m = re.search(r"<(I|M)\s([^>]*)>", x)
        if not m: raise ValueError(f"{f}: no <I ...> root")
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(2)))
        kind, nm = attrs.get("i"), attrs.get("n")
        if kind not in tp: raise ValueError(f"{f}: unknown tuning kind i=\"{kind}\" (known: buff, interaction, snippet, ...)")
        if not nm: raise ValueError(f"{f}: the root has no n=\"...\" name")
        s = attrs.get("s")
        inst = (int(s, 16) if s and s.startswith("0x") else int(s)) if s else fnv64(nm, high_bit=True)
        inst_of[nm] = inst; parsed.append((f, x, kind, nm, inst, bool(s)))
    for f, x, kind, nm, inst, had_s in parsed:
        def sub(m):
            k, v = m.group(1), m.group(2)
            if k == "str":
                if v not in strings: raise ValueError(f"{f}: {{{{str:{v}}}}} not in strings.json")
                return str_hash(v)
            if v not in inst_of: raise ValueError(f"{f}: {{{{inst:{v}}}}}: no tuning named {v}")
            return str(inst_of[v])
        x = re.sub(r"\{\{(str|inst):([^}]+)\}\}", sub, x)
        if not had_s:
            x = re.sub(r"<(I|M)\s", lambda m: f'<{m.group(1)} s="{inst}" ', x, count=1)
        res.append((tp[kind], 0, inst, x.encode("utf-8"))); log(f"tuning  {tp[kind]:08X}:00000000:{inst:016X}  {kind} {nm}")
    if strings:
        inst = fnv64("m2w_strings_" + name) & 0x00FFFFFFFFFFFFFF   # top byte 00 = English
        res.append((STBL_TYPE, STBL_GROUP, inst, stbl(strings))); log(f"strings {STBL_TYPE:08X}:{STBL_GROUP:08X}:{inst:016X}  {len(strings)} entries")
    rawdir = os.path.join(src, "raw")
    if os.path.isdir(rawdir):
        for f in sorted(os.listdir(rawdir)):
            m = re.fullmatch(r"([0-9A-Fa-f]{8})_([0-9A-Fa-f]{8})_([0-9A-Fa-f]{16})(\..*)?", f)
            if not m: raise ValueError(f"raw/{f}: name must be TTTTTTTT_GGGGGGGG_IIIIIIIIIIIIIIII[.ext]")
            t, g, i = (int(m.group(n), 16) for n in (1, 2, 3))
            with open(os.path.join(rawdir, f), "rb") as fh: res.append((t, g, i, fh.read()))
            log(f"raw     {t:08X}:{g:08X}:{i:016X}  {f}")
    write_package(out, res)
    return len(res)


def main(a):
    if len(a) < 2: print(__doc__); return
    c = a[0]
    if c == "ls":
        want = int(a[a.index("--type") + 1], 16) if "--type" in a else None
        with Package(a[1]) as P:
            for t, g, i, pos, size, dsize, comp in P.entries:
                if want is None or t == want: print(f"{t:08X} {g:08X} {i:016X} {dsize:9d} {comp:04X}")
    elif c == "cat":
        with Package(a[1]) as P: sys.stdout.buffer.write(P.get(int(a[2], 16), int(a[3], 16), int(a[4], 16)))
    elif c == "find-tuning":
        key = a[2].lower()
        with Package(a[1]) as P:
            for e in P.entries:
                if e[5] > 5_000_000: continue
                try: d = P.read(e)
                except Exception: continue
                if d[:1] == b"<" or d[:5] == b"<?xml":
                    n = tuning_name(d)
                    if n and key in n.lower(): print(f"{e[0]:08X} {e[1]:08X} {e[2]:016X} {n}")
    else: print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
