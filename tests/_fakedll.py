"""Tiny .NET assemblies for the tests (no compiler on the runners): a PE file with a CLI header and the metadata tables that
`gameanything native check` reads (Module, TypeRef, TypeDef, Field, MethodDef, MemberRef, Assembly, AssemblyRef, ExportedType). The reader
(gameanything/native/clrmeta.py) was checked against a real compiler-made DLL (pythonnet's Python.Runtime.dll) by hand."""
import struct
from pathlib import Path


def _pad4(b: bytes) -> bytes: return b + b"\0" * (-len(b) % 4)


def make_dll(path, name, version=(1, 0, 0, 0), refs=(), typerefs=(), types=(), memberrefs=(), exported=()):
    """refs: [(name, version)]; typerefs: [(ref no. 1-based, namespace, name)]; types: [(namespace, name, base typeref no. or None,
    [field names], [method names])]; memberrefs: [(typeref no., member name)]; exported: [(namespace, name, ref no.)]."""
    strings = bytearray(b"\0"); idx = {}

    def s(x):
        if x not in idx: idx[x] = len(strings); strings.extend(x.encode() + b"\0")
        return idx[x]
    rows = {}
    rows[0x00] = [[(0, 2), (s(name + ".dll"), 2), (1, 2), (0, 2), (0, 2)]]
    if typerefs: rows[0x01] = [[((r << 2) | 2, 2), (s(n), 2), (s(ns), 2)] for r, ns, n in typerefs]
    tds = [[(0, 4), (s("<Module>"), 2), (0, 2), (0, 2), (1, 2), (1, 2)]]; fields = []; methods = []
    for ns, n, base, fs, ms in types:
        tds.append([(0x100001, 4), (s(n), 2), (s(ns), 2), (((base << 2) | 1) if base else 0, 2), (len(fields) + 1, 2), (len(methods) + 1, 2)])
        fields += [[(0x6, 2), (s(f), 2), (0, 2)] for f in fs]
        methods += [[(0, 4), (0, 2), (0x86, 2), (s(m), 2), (0, 2), (1, 2)] for m in ms]
    rows[0x02] = tds
    if fields: rows[0x04] = fields
    if methods: rows[0x06] = methods
    if memberrefs: rows[0x0A] = [[((t << 3) | 1, 2), (s(n), 2), (0, 2)] for t, n in memberrefs]
    rows[0x20] = [[(0x8004, 4), *[(v, 2) for v in version], (0, 4), (0, 2), (s(name), 2), (0, 2)]]
    if refs: rows[0x23] = [[*[(v, 2) for v in ver], (0, 4), (0, 2), (s(n), 2), (0, 2), (0, 2)] for n, ver in refs]
    if exported: rows[0x27] = [[(0, 4), (0, 4), (s(n), 2), (s(ns), 2), ((r << 2) | 1, 2)] for ns, n, r in exported]
    valid = sum(1 << t for t in rows)
    tb = struct.pack("<IBBBBQQ", 0, 2, 0, 0, 1, valid, 0) + b"".join(struct.pack("<I", len(rows[t])) for t in sorted(rows))
    for t in sorted(rows):
        for r in rows[t]: tb += b"".join(v.to_bytes(n, "little") for v, n in r)
    streams = [("#~", _pad4(tb)), ("#Strings", _pad4(bytes(strings))), ("#GUID", b"\x11" * 16), ("#Blob", _pad4(b"\0"))]
    ver = _pad4(b"v4.0.30319\0")
    hdr_len = 16 + len(ver) + 4 + sum(8 + len(_pad4(n.encode() + b"\0")) for n, _ in streams)
    md = b"BSJB" + struct.pack("<HHII", 1, 1, 0, len(ver)) + ver + struct.pack("<HH", 0, len(streams))
    off = hdr_len; data = b""
    for n, b in streams:
        md += struct.pack("<II", off, len(b)) + _pad4(n.encode() + b"\0"); off += len(b); data += b
    md += data
    body = struct.pack("<IHHII", 72, 2, 5, 0x2000 + 72, len(md)) + struct.pack("<I", 1) + b"\0" * (72 - 20) + md
    pe = bytearray(0x200)
    pe[:2] = b"MZ"; struct.pack_into("<I", pe, 0x3C, 0x80); pe[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", pe, 0x84, 0x14C, 1, 0, 0, 0, 224, 0x2102)
    opt = 0x98; struct.pack_into("<H", pe, opt, 0x10B); struct.pack_into("<I", pe, opt + 92, 16)
    struct.pack_into("<II", pe, opt + 96 + 14 * 8, 0x2000, 72)
    sec = opt + 224; pe[sec:sec + 8] = b".text\0\0\0"
    raw = len(body) + (-len(body) % 0x200)
    struct.pack_into("<IIII", pe, sec + 8, len(body), 0x2000, raw, 0x200)
    out = bytes(pe) + body + b"\0" * (raw - len(body))
    Path(path).parent.mkdir(parents=True, exist_ok=True); Path(path).write_bytes(out)
    return Path(path)


def make_class(name, refs=(), major=52) -> bytes:
    """A .class file whose constant pool names these classes (this_class = name, super = java/lang/Object)."""
    pool = []; utf = {}

    def u(x):
        if x not in utf: pool.append(b"\x01" + struct.pack(">H", len(x.encode())) + x.encode()); utf[x] = len(pool)
        return utf[x]
    cls = {}

    def c(x):
        if x not in cls: i = u(x); pool.append(b"\x07" + struct.pack(">H", i)); cls[x] = len(pool)
        return cls[x]
    this = c(name); sup = c("java/lang/Object")
    for r in refs: c(r)
    return (b"\xca\xfe\xba\xbe" + struct.pack(">HHH", 0, major, len(pool) + 1) + b"".join(pool)
            + struct.pack(">HHHHHHH", 0x21, this, sup, 0, 0, 0, 0))
