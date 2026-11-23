"""Cities: Skylines 1 settings files (*.cgs, ColossalFramework.SettingsFile v4) and the mod on/off switches in userGameState.cgs.

A local mod is on when the bool `<mod folder name><hash>.enabled` is true, hash = Mono's String.GetHashCode of the mod folder's
full path as the game sees it (verified on Linux against a file the game wrote). New mods are off by default, so `enable`
sets the switch while the game is closed (the game rewrites the file when it exits); `enable(on=False)` removes the key.

Format (little endian): "CGSF", uint16 version (4), then six sections, each int32 count + entries of
(7-bit-length-prefixed UTF-8 key, value): int32, bool (1 byte), float32, string, input key (int32), int64.
"""
import struct
from pathlib import Path

KINDS = ("int", "bool", "float", "string", "inputkey", "long")


def mono_hash(s: str) -> int:
    """Mono 2.x String.GetHashCode (the game's runtime): h = h*31 + c over UTF-16 code units."""
    units = s.encode("utf-16-le"); h = 0
    for i in range(0, len(units), 2): h = (h * 31 + (units[i] | units[i + 1] << 8)) & 0xFFFFFFFF
    return h - (1 << 32) if h >= 1 << 31 else h


def _rstr(b, i):
    n = 0; shift = 0
    while True:
        x = b[i]; i += 1; n |= (x & 0x7F) << shift; shift += 7
        if not x & 0x80: break
    return b[i:i + n].decode("utf-8"), i + n


def _wstr(s):
    d = s.encode("utf-8"); n = len(d); out = bytearray()
    while True:
        x = n & 0x7F; n >>= 7
        out.append(x | (0x80 if n else 0))
        if not n: break
    return bytes(out) + d


def read(path) -> dict:
    b = Path(path).read_bytes()
    if b[:4] != b"CGSF": raise ValueError(f"{path}: not a CGSF settings file")
    out = {"_version": struct.unpack_from("<H", b, 4)[0]}; i = 6
    for kind in KINDS:
        sec = {}
        if i < len(b):
            n = struct.unpack_from("<i", b, i)[0]; i += 4
            for _ in range(n):
                k, i = _rstr(b, i)
                if kind in ("int", "inputkey"): v = struct.unpack_from("<i", b, i)[0]; i += 4
                elif kind == "bool": v = bool(b[i]); i += 1
                elif kind == "float": v = struct.unpack_from("<f", b, i)[0]; i += 4
                elif kind == "string": v, i = _rstr(b, i)
                else: v = struct.unpack_from("<q", b, i)[0]; i += 8
                sec[k] = v
        out[kind] = sec
    return out


def write(path, d: dict):
    b = bytearray(b"CGSF") + struct.pack("<H", d.get("_version", 4))
    for kind in KINDS:
        sec = d.get(kind) or {}; b += struct.pack("<i", len(sec))
        for k, v in sec.items():
            b += _wstr(k)
            if kind in ("int", "inputkey"): b += struct.pack("<i", int(v))
            elif kind == "bool": b += bytes([1 if v else 0])
            elif kind == "float": b += struct.pack("<f", float(v))
            elif kind == "string": b += _wstr(str(v))
            else: b += struct.pack("<q", int(v))
    tmp = Path(str(path) + ".tmp"); tmp.write_bytes(bytes(b)); tmp.replace(path)


def mod_key(mod_dir: str, sep: str = "/") -> str:
    p = str(mod_dir).rstrip(sep)
    return f"{p.rsplit(sep, 1)[-1]}{mono_hash(p)}.enabled"


def enable(path, mod_dirs, on=True, sep="/") -> list:
    """Switch each mod (full folder paths as the game sees them) on or off in userGameState.cgs (created if missing) -> the keys.
    Off removes the key (a mod without one is off, the game's default), so `restore` + `uninstall` leaves her file as it was
    (writing `false` left a key for a mod folder that no longer exists, seen on Linux 2026-10-25)."""
    path = Path(path)
    keys = [mod_key(m, sep) for m in mod_dirs]
    if not on and not path.exists(): return keys
    d = read(path) if path.exists() else {"_version": 4, **{k: {} for k in KINDS}}
    if not on and not any(k in d["bool"] for k in keys): return keys          # nothing to switch off: leave the file untouched
    for k in keys:
        if on: d["bool"][k] = True
        else: d["bool"].pop(k, None)
    write(path, d)
    return keys
