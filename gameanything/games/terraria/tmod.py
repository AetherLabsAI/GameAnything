"""tModLoader's .tmod file (TmodFile.cs of tModLoader, MIT): read what `gameanything native check` needs, and write a tiny one for tests.

    "TMOD"  string tml_version  hash[20] (SHA-1 of the rest)  signature[256]  int32 data_length
    string name  string version  int32 count  count x (string path, int32 length, int32 stored_length)  the files' bytes, in order
Strings are .NET BinaryWriter strings (a 7-bit encoded length, then UTF-8). A file is raw deflate when stored_length != length.
"""
import hashlib
import io
import struct
import zlib
from pathlib import Path


class BadTmod(ValueError):
    pass


def _rstr(f) -> str:
    n = shift = 0
    while True:
        b = f.read(1)
        if not b: raise BadTmod("unexpected end of file")
        n |= (b[0] & 0x7F) << shift; shift += 7
        if not b[0] & 0x80: break
        if shift > 35: raise BadTmod("bad string length")
    s = f.read(n)
    if len(s) != n: raise BadTmod("unexpected end of file")
    return s.decode("utf-8")


def _wstr(s: str) -> bytes:
    b = s.encode("utf-8"); n = len(b); out = bytearray()
    while True:
        x = n & 0x7F; n >>= 7
        out.append(x | (0x80 if n else 0))
        if not n: break
    return bytes(out) + b


def _i32(f) -> int:
    b = f.read(4)
    if len(b) != 4: raise BadTmod("unexpected end of file")
    return struct.unpack("<i", b)[0]


def read(path) -> dict:
    """-> {tml_version, name, version, hash_ok, files: {path: {length, stored, offset}}}; BadTmod when it is not a .tmod."""
    raw = Path(path).read_bytes(); f = io.BytesIO(raw)
    if f.read(4) != b"TMOD": raise BadTmod("not a .tmod (the file does not start with TMOD)")
    tml = _rstr(f); h = f.read(20); f.read(256); n = _i32(f); start = f.tell()
    if n != len(raw) - start: raise BadTmod(f"data length {n} != {len(raw) - start}: the file is cut off or corrupt")
    name, version = _rstr(f), _rstr(f)
    cnt = _i32(f)
    if not 0 <= cnt < 100000: raise BadTmod("bad file count")
    files = {}; table = []
    for _ in range(cnt):
        p = _rstr(f); ln = _i32(f); st = _i32(f); table.append((p, ln, st))
    off = f.tell()
    for p, ln, st in table:
        files[p] = {"length": ln, "stored": st, "offset": off}; off += st
    if off > len(raw): raise BadTmod("the file table points past the end of the file")
    return {"tml_version": tml, "name": name, "version": version, "hash_ok": hashlib.sha1(raw[start:]).digest() == h, "files": files}


def read_file(path, info: dict, name: str) -> bytes:
    e = info["files"][name]
    with open(path, "rb") as fh:
        fh.seek(e["offset"]); b = fh.read(e["stored"])
    return zlib.decompress(b, -15) if e["stored"] != e["length"] else b


def write(path, name: str, version: str, files: dict, tml_version="2025.1.0.0") -> Path:
    """A .tmod of these {path: bytes} (stored, not compressed): for tests only. tModLoader itself checks a signature only for
    Workshop / browser mods, not for local ones."""
    body = _wstr(name) + _wstr(version) + struct.pack("<i", len(files))
    for p, b in files.items(): body += _wstr(p) + struct.pack("<ii", len(b), len(b))
    for b in files.values(): body += b
    out = b"TMOD" + _wstr(tml_version) + hashlib.sha1(body).digest() + bytes(256) + struct.pack("<i", len(body)) + body
    Path(path).parent.mkdir(parents=True, exist_ok=True); Path(path).write_bytes(out); return Path(path)
