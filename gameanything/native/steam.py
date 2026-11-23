"""Find a Steam game the user owns and installed: Steam's own files say where (libraryfolders.vdf, appmanifest_<id>.acf).

    roots(sys, home, env)    where the Steam client keeps its files on this system (the ones that exist)
    app_dir(appid, ...)      <library>/steamapps/common/<installdir> of an installed app, or None
Only reads Steam's files; never starts or logs in to Steam.
"""
import os
import re
from pathlib import Path

_TOK = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


def parse_vdf(text: str) -> dict:
    """Valve KeyValues text (the format of libraryfolders.vdf and *.acf) -> nested dicts."""
    stack = [{}]; key = None
    for m in _TOK.finditer(text):
        s, brace = m.group(1), m.group(2)
        if brace == "{":
            d = {}; stack[-1][key] = d; stack.append(d); key = None
        elif brace == "}":
            if len(stack) > 1: stack.pop()
            key = None
        elif key is None: key = s.replace("\\\\", "\\")
        else: stack[-1][key] = s.replace("\\\\", "\\"); key = None
    return stack[0]


def env_get(env: dict, k: str):
    """env[k] for a Windows variable such as ProgramFiles(x86): dict(os.environ) on Windows has the names in upper case."""
    return env.get(k) or env.get(k.upper())


def candidates(sys_: str, home: Path, env: dict) -> list:
    if sys_ == "mac": return [home / "Library" / "Application Support" / "Steam"]
    if sys_ == "windows":
        pf = [env_get(env, "ProgramFiles(x86)"), env_get(env, "ProgramFiles"), "C:\\Program Files (x86)", "C:\\Program Files"]
        return [Path(p) / "Steam" for p in pf if p]
    return [home / ".steam" / "steam", home / ".local" / "share" / "Steam", home / ".steam" / "debian-installation",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam"]


def roots(sys_: str, home: Path, env: dict = None) -> list:
    env = os.environ if env is None else env
    out = []
    # A pinned Steam folder comes first, then the default ones: a user who pins a second library still has the games in the default
    # one (her decision 2026-11-01). Tests stay away from a PC's real C:\Program Files (x86)\Steam through conftest (roots under tmp only).
    for p in ([Path(env["GAMEANYTHING_STEAM_DIR"])] if env.get("GAMEANYTHING_STEAM_DIR") else []) + candidates(sys_, home, env):
        if (p / "steamapps").is_dir() and p.resolve() not in [o.resolve() for o in out]: out.append(p)
    return out


def libraries(root: Path) -> list:
    libs = [root]
    try: d = parse_vdf((root / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace"))
    except OSError: return libs
    for v in (d.get("libraryfolders") or {}).values():
        if isinstance(v, dict) and v.get("path"):
            p = Path(v["path"])
            if p not in libs: libs.append(p)
    return libs


def app_dir(appid: int, sys_: str, home: Path, env: dict = None):
    for r in roots(sys_, home, env):
        for lib in libraries(r):
            acf = lib / "steamapps" / f"appmanifest_{appid}.acf"
            try: st = parse_vdf(acf.read_text(encoding="utf-8", errors="replace")).get("AppState") or {}
            except OSError: continue
            d = lib / "steamapps" / "common" / st.get("installdir", "")
            if st.get("installdir") and d.is_dir(): return d
    return None
