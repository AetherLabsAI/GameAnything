"""A small reader of .NET assembly metadata (ECMA-335 II.24, II.22), pure Python, read only: what a mod DLL references and what a game
assembly defines, so `gameanything native check` finds a wrong reference without opening the game.

    a = Assembly.read(path)
    a.name, a.version                      the assembly's own name and version
    a.refs        [{name, version}]        AssemblyRef: the assemblies it needs
    a.typerefs    [(scope assembly or None, "Ns.Type" / "Ns.Outer/Inner")]   types it uses from other assemblies
    a.memberrefs  [(scope assembly, "Ns.Type", member name)]               methods / fields it calls on those types (name only, no signature)
    a.types       {"Ns.Type": {"base": (scope, full name) | (TYPESPEC, "") | None, "members": {names}}}   what it defines
    a.exported    {"Ns.Type": assembly name}  type forwarders (ExportedType -> AssemblyRef)
Raises NotManaged for a file that is not a .NET assembly (a native DLL, a truncated file)."""
import struct
from pathlib import Path


class NotManaged(ValueError):
    pass


TYPESPEC = "<typespec>"


# table number -> columns; a column is an int (fixed size in bytes), "s" / "g" / "b" (string / guid / blob heap index),
# ("t", table) (a simple index) or ("c", coded index name)
_C = lambda n: ("c", n)
_T = lambda n: ("t", n)
TABLES = {
    0x00: [2, "s", "g", "g", "g"],                                   # Module
    0x01: [_C("ResolutionScope"), "s", "s"],                         # TypeRef
    0x02: [4, "s", "s", _C("TypeDefOrRef"), _T(0x04), _T(0x06)],     # TypeDef
    0x03: [_T(0x04)], 0x04: [2, "s", "b"], 0x05: [_T(0x06)],         # FieldPtr, Field, MethodPtr
    0x06: [4, 2, 2, "s", "b", _T(0x08)],                             # MethodDef
    0x07: [_T(0x08)], 0x08: [2, 2, "s"],                             # ParamPtr, Param
    0x09: [_T(0x02), _C("TypeDefOrRef")],                            # InterfaceImpl
    0x0A: [_C("MemberRefParent"), "s", "b"],                         # MemberRef
    0x0B: [2, _C("HasConstant"), "b"],                               # Constant
    0x0C: [_C("HasCustomAttribute"), _C("CustomAttributeType"), "b"],
    0x0D: [_C("HasFieldMarshal"), "b"], 0x0E: [2, _C("HasDeclSecurity"), "b"],
    0x0F: [2, 4, _T(0x02)], 0x10: [4, _T(0x04)], 0x11: ["b"],         # ClassLayout, FieldLayout, StandAloneSig
    0x12: [_T(0x02), _T(0x14)], 0x13: [_T(0x14)], 0x14: [2, "s", _C("TypeDefOrRef")],     # EventMap, EventPtr, Event
    0x15: [_T(0x02), _T(0x17)], 0x16: [_T(0x17)], 0x17: [2, "s", "b"],                     # PropertyMap, PropertyPtr, Property
    0x18: [2, _T(0x06), _C("HasSemantics")], 0x19: [_T(0x02), _C("MethodDefOrRef"), _C("MethodDefOrRef")],
    0x1A: ["s"], 0x1B: ["b"], 0x1C: [2, _C("MemberForwarded"), "s", _T(0x1A)], 0x1D: [4, _T(0x04)],
    0x1E: [4, 4], 0x1F: [4],                                         # EncLog, EncMap
    0x20: [4, 2, 2, 2, 2, 4, "b", "s", "s"],                         # Assembly
    0x21: [4], 0x22: [4, 4, 4],
    0x23: [2, 2, 2, 2, 4, "b", "s", "s", "b"],                       # AssemblyRef
    0x24: [4, _T(0x23)], 0x25: [4, 4, 4, _T(0x23)],
    0x26: [4, "s", "b"], 0x27: [4, 4, "s", "s", _C("Implementation")],                     # File, ExportedType
    0x28: [4, 4, "s", _C("Implementation")], 0x29: [_T(0x02), _T(0x02)],                   # ManifestResource, NestedClass
    0x2A: [2, 2, _C("TypeOrMethodDef"), "s"], 0x2B: [_C("MethodDefOrRef"), "b"], 0x2C: [_T(0x2A), _C("TypeDefOrRef")],
}
CODED = {   # name -> (tag bits, tables; None = an unused tag)
    "TypeDefOrRef": (2, [0x02, 0x01, 0x1B]), "HasConstant": (2, [0x04, 0x08, 0x17]),
    "HasCustomAttribute": (5, [0x06, 0x04, 0x01, 0x02, 0x08, 0x09, 0x0A, 0x00, 0x0E, 0x17, 0x14, 0x11, 0x1A, 0x1B, 0x20, 0x23, 0x26, 0x27,
                               0x28, 0x2A, 0x2C, 0x2B]),
    "HasFieldMarshal": (1, [0x04, 0x08]), "HasDeclSecurity": (2, [0x02, 0x06, 0x20]), "MemberRefParent": (3, [0x02, 0x01, 0x1A, 0x06, 0x1B]),
    "HasSemantics": (1, [0x14, 0x17]), "MethodDefOrRef": (1, [0x06, 0x0A]), "MemberForwarded": (1, [0x04, 0x06]),
    "Implementation": (2, [0x26, 0x23, 0x27]), "CustomAttributeType": (3, [None, None, 0x06, 0x0A, None]),
    "ResolutionScope": (2, [0x00, 0x1A, 0x23, 0x01]), "TypeOrMethodDef": (1, [0x02, 0x06]),
}


def _rva_to_off(secs, rva):
    for va, vsize, raw, rawsize in secs:
        if va <= rva < va + max(vsize, rawsize): return rva - va + raw
    raise NotManaged("RVA outside every section")


def _metadata(data: bytes):
    """-> (version string, {stream name: bytes})."""
    try:
        if data[:2] != b"MZ": raise NotManaged("not a PE file")
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe:pe + 4] != b"PE\0\0": raise NotManaged("not a PE file")
        nsec, optsize = struct.unpack_from("<H", data, pe + 6)[0], struct.unpack_from("<H", data, pe + 20)[0]
        opt = pe + 24; magic = struct.unpack_from("<H", data, opt)[0]
        dd = opt + (96 if magic == 0x10B else 112 if magic == 0x20B else -1)
        if dd < opt: raise NotManaged("unknown PE optional header")
        ndirs = struct.unpack_from("<I", data, dd - 4)[0]
        if ndirs < 15: raise NotManaged("no CLI header (a native DLL)")
        cli_rva, cli_size = struct.unpack_from("<II", data, dd + 14 * 8)
        if not cli_rva: raise NotManaged("no CLI header (a native DLL)")
        secs = []
        for i in range(nsec):
            s = opt + optsize + 40 * i
            vsize, va, rawsize, raw = struct.unpack_from("<IIII", data, s + 8)
            secs.append((va, vsize, raw, rawsize))
        cli = _rva_to_off(secs, cli_rva)
        md_rva, md_size = struct.unpack_from("<II", data, cli + 8)
        md = _rva_to_off(secs, md_rva)
        if data[md:md + 4] != b"BSJB": raise NotManaged("no metadata signature")
        vlen = struct.unpack_from("<I", data, md + 12)[0]
        version = data[md + 16:md + 16 + vlen].split(b"\0")[0].decode("ascii", "replace")
        p = md + 16 + vlen + 2; n = struct.unpack_from("<H", data, p)[0]; p += 2
        streams = {}
        for _ in range(n):
            off, size = struct.unpack_from("<II", data, p); p += 8
            e = data.index(b"\0", p); name = data[p:e].decode("ascii", "replace"); p = (e + 4) & ~3
            streams[name] = data[md + off:md + off + size]
        return version, streams
    except (struct.error, ValueError) as e:
        if isinstance(e, NotManaged): raise
        raise NotManaged(f"unreadable: {e}")


class Assembly:
    def __init__(self, data: bytes, path=None):
        self.path = path
        self.runtime, st = _metadata(data)
        tb = st.get("#~") or st.get("#-")
        if tb is None: raise NotManaged("no metadata tables")
        self._str = st.get("#Strings", b""); self._blob = st.get("#Blob", b"")
        self._tables(tb)
        self._read()

    @classmethod
    def read(cls, path):
        p = Path(path)
        try: data = p.read_bytes()
        except OSError as e: raise NotManaged(f"cannot read {p.name}: {e}")
        return cls(data, p)

    # ---- the tables stream
    def _tables(self, tb: bytes):
        try:
            heaps = tb[6]; valid = struct.unpack_from("<Q", tb, 8)[0]
            p = 24; rows = {}
            for t in range(64):
                if valid >> t & 1: rows[t] = struct.unpack_from("<I", tb, p)[0]; p += 4
            if heaps & 0x40: p += 4                                       # #- streams may carry 4 bytes of extra data
        except (IndexError, struct.error) as e: raise NotManaged(f"bad tables header: {e}")
        unknown = [t for t in rows if t not in TABLES]
        if unknown: raise NotManaged(f"unknown metadata tables {unknown}")
        hs = {"s": 4 if heaps & 1 else 2, "g": 4 if heaps & 2 else 2, "b": 4 if heaps & 4 else 2}

        def size(col):
            if isinstance(col, int): return col
            if isinstance(col, str): return hs[col]
            if col[0] == "t": return 2 if rows.get(col[1], 0) < 1 << 16 else 4
            bits, ts = CODED[col[1]]
            return 2 if max(rows.get(t, 0) for t in ts if t is not None) < 1 << (16 - bits) else 4

        self._rows = {}
        for t in sorted(rows):
            cols = TABLES[t]; sizes = [size(c) for c in cols]; w = sum(sizes); out = []
            for i in range(rows[t]):
                q = p + i * w; r = []
                for c, s in zip(cols, sizes):
                    v = int.from_bytes(tb[q:q + s], "little"); q += s
                    if isinstance(c, tuple) and c[0] == "c":
                        bits, ts = CODED[c[1]]; tag = v & ((1 << bits) - 1)
                        v = (ts[tag] if tag < len(ts) else None, v >> bits)
                    r.append(v)
                out.append(r)
            if p + rows[t] * w > len(tb): raise NotManaged("metadata tables are cut short")
            self._rows[t] = out; p += rows[t] * w

    def _s(self, i):
        e = self._str.find(b"\0", i)
        return self._str[i:e if e >= 0 else None].decode("utf-8", "replace")

    def _row(self, t, i):                                                 # 1-based; None for a null index
        rs = self._rows.get(t, [])
        return rs[i - 1] if 0 < i <= len(rs) else None

    # ---- what it says
    def _read(self):
        R = self._rows
        a = R.get(0x20, [])
        self.name = self._s(a[0][7]) if a else (self._s(R[0x00][0][1]) if R.get(0x00) else "")
        self.version = tuple(a[0][1:5]) if a else None
        self.refs = [{"name": self._s(r[6]), "version": tuple(r[0:4])} for r in R.get(0x23, [])]
        self._tr_cache = {}
        self.typerefs = [self._typeref(i) for i in range(1, len(R.get(0x01, [])) + 1)]
        nest = {r[0]: r[1] for r in R.get(0x29, [])}
        tds = R.get(0x02, []); fields = R.get(0x04, []); methods = R.get(0x06, [])
        def tdname(i, depth=0):
            r = tds[i - 1]; n = self._s(r[1]); ns = self._s(r[2])
            if i in nest and depth < 20: return tdname(nest[i], depth + 1) + "/" + n
            return f"{ns}.{n}" if ns else n
        self.types = {}
        for i, r in enumerate(tds, 1):
            nxt = tds[i] if i < len(tds) else None
            f_end = nxt[4] if nxt else len(fields) + 1; m_end = nxt[5] if nxt else len(methods) + 1
            mem = {self._s(fields[k - 1][1]) for k in range(r[4], f_end) if 0 < k <= len(fields)}
            mem |= {self._s(methods[k - 1][3]) for k in range(r[5], m_end) if 0 < k <= len(methods)}
            t, idx = r[3]; base = None
            if t == 0x01 and idx: base = self._typeref(idx)
            elif t == 0x02 and 0 < idx <= len(tds): base = (None, tdname(idx))
            elif t == 0x1B and idx: base = (TYPESPEC, "")                  # a generic instantiation (class X : List<int>): not followed
            self.types[tdname(i)] = {"base": base, "members": mem}
        self.exported = {}
        for r in R.get(0x27, []):
            t, idx = r[4]
            if t == 0x23 and self._row(0x23, idx):
                n, ns = self._s(r[2]), self._s(r[3]); self.exported[f"{ns}.{n}" if ns else n] = self._s(self._row(0x23, idx)[6])
        self.memberrefs = []
        for r in R.get(0x0A, []):
            t, idx = r[0]
            if t == 0x01 and idx:
                scope, full = self._typeref(idx)
                if scope: self.memberrefs.append((scope, full, self._s(r[1])))

    def _typeref(self, i, depth=0):
        """-> (assembly name it lives in, or None for this module / unknown; full name with / for nesting)."""
        if i in self._tr_cache: return self._tr_cache[i]
        r = self._row(0x01, i)
        if r is None: return (None, "?")
        (t, idx), n, ns = r[0], self._s(r[1]), self._s(r[2])
        full = f"{ns}.{n}" if ns else n
        if t == 0x23 and self._row(0x23, idx): out = (self._s(self._row(0x23, idx)[6]), full)
        elif t == 0x01 and depth < 20:
            sc, outer = self._typeref(idx, depth + 1); out = (sc, f"{outer}/{n}")
        else: out = (None, full)                                         # this module, a ModuleRef, or no scope (an exported type)
        self._tr_cache[i] = out
        return out
