"""Minecraft: Java Edition version files (<.minecraft>/versions/<id>/<id>.json, the launcher format). Stdlib only.

Used by `gameanything native build --game minecraft` (the classpath a Fabric mod is compiled against) and by the sandbox tool ga-mc
(lab/images/minecraft), which starts the game offline from the user's own files with the same classpath.

    load(root, vid)            the version, merged with the ones it inherits from (Fabric's profile inherits the game's version)
    classpath(root, v, os)     the library jars allowed on this system + the game's client jar, in launcher order
    newest_fabric(root)        the newest Fabric profile in versions/ (fabric-loader-<loader>-<game> or portablemc's fabric-<game>-<loader>)
    arguments(v, values, os)   the JVM and game arguments with ${...} filled in (rules: os name / arch / features)
"""
import json
import platform
import re
from pathlib import Path

OS_NAMES = {"linux": "linux", "windows": "windows", "mac": "osx", "osx": "osx"}


def _arch():
    m = platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64") else ("x86" if m in ("i386", "i686", "x86") else "x86_64")


def _os_version(os_name):
    """This computer's OS version ("10.0.26200", "15.1", "6.8.0-45-generic") when os_name is this computer's system, else None."""
    here = {"Windows": "windows", "Darwin": "osx", "Linux": "linux"}.get(platform.system())
    if OS_NAMES.get(os_name, os_name) != here: return None
    return platform.mac_ver()[0] if here == "osx" else platform.version() if here == "windows" else platform.release()


def _vtuple(s):
    return tuple(int(x) for x in re.findall(r"\d+", str(s))[:4])


def _version_ok(o, ver) -> bool:
    """The os rule's version conditions: "versionRange" {min (inclusive), max (exclusive)} (26.x: ZGC from Windows 10.0.17134, G1
    before it; a real Windows 11 PC 2026-11-01 got both and the JVM refused to start) and the older "version" regex. An unknown
    version (another system's files) counts as a current one: min holds, max does not."""
    vr = o.get("versionRange") or {}
    if vr.get("min") and ver is not None and _vtuple(ver) < _vtuple(vr["min"]): return False
    if vr.get("max") and (ver is None or _vtuple(ver) >= _vtuple(vr["max"])): return False
    if o.get("version") and not (ver is not None and re.search(o["version"], ver)): return False
    return True


def allowed(rules, os_name="linux", arch=None, features=None, os_version=None) -> bool:
    """The launcher's rules: the last matching rule wins; no rules = allowed."""
    if not rules: return True
    arch = arch or _arch(); features = features or {}; ok = False
    ver = os_version if os_version is not None else _os_version(os_name)
    for r in rules:
        match = True
        o = r.get("os") or {}
        if "name" in o and o["name"] != OS_NAMES.get(os_name, os_name): match = False
        if "arch" in o and o["arch"] != arch: match = False
        if match and not _version_ok(o, ver): match = False
        for k, v in (r.get("features") or {}).items():
            if bool(features.get(k)) != bool(v): match = False
        if match: ok = r.get("action") == "allow"
    return ok


def load(root, vid) -> dict:
    """versions/<vid>/<vid>.json merged down its inheritsFrom chain: libraries child first, arguments parent first, the rest child wins."""
    root = Path(root); chain = []; seen = set()
    while vid:
        if vid in seen: raise ValueError(f"inheritsFrom loop at {vid}")
        seen.add(vid)
        p = root / "versions" / vid / f"{vid}.json"
        d = json.loads(p.read_text(encoding="utf-8")); d["_dir"] = str(p.parent); chain.append(d)
        vid = d.get("inheritsFrom")
    out, args = {}, {}
    for d in reversed(chain):                       # base first, then each child on top
        out.update({k: v for k, v in d.items() if k not in ("libraries", "arguments")})
        for k, a in (d.get("arguments") or {}).items(): args[k] = list(args.get(k) or []) + list(a)
    out["libraries"] = [lib for d in chain for lib in d.get("libraries") or []]
    if args: out["arguments"] = args
    out["id"] = chain[0]["id"]
    out["jar_version"] = next((d.get("jar") or d["id"] for d in reversed(chain) if (Path(d["_dir"]) / f"{d.get('jar') or d['id']}.jar").is_file()), chain[-1]["id"])
    return out


def lib_path(lib) -> str:
    """A library's path under libraries/: downloads.artifact.path, else from its maven name group:artifact:version[:classifier]."""
    a = ((lib.get("downloads") or {}).get("artifact") or {}).get("path")
    if a: return a
    parts = lib["name"].split(":")
    g, art, ver = parts[:3]; cls = f"-{parts[3]}" if len(parts) > 3 else ""
    return f"{g.replace('.', '/')}/{art}/{ver}/{art}-{ver}{cls}.jar"


def libraries(v, os_name="linux", arch=None) -> list:
    """The library entries allowed here; the first of each group:artifact[:classifier] wins (Fabric's newer ASM over the game's)."""
    out = []; seen = set()
    for lib in v.get("libraries") or []:
        if not allowed(lib.get("rules"), os_name, arch): continue
        parts = lib["name"].split(":")
        key = ":".join(parts[:2] + parts[3:4])
        if key not in seen: seen.add(key); out.append(lib)
    return out


def lib_url(lib):
    """(url, sha1) a library is downloaded from (public: Mojang's and Fabric's maven, no account), or (None, None)."""
    a = (lib.get("downloads") or {}).get("artifact") or {}
    if a.get("url"): return a["url"], a.get("sha1")
    if lib.get("url"): return lib["url"].rstrip("/") + "/" + lib_path(lib), lib.get("sha1")
    return None, None


def classpath(root, v, os_name="linux", arch=None, extra_roots=()) -> list:
    """Library jars allowed here (each from root/libraries, else the first of extra_roots that has it) + the client jar."""
    root = Path(root); out = []
    for lib in libraries(v, os_name, arch):
        rel = lib_path(lib); p = root / "libraries" / rel
        if not p.is_file(): p = next((Path(r) / rel for r in extra_roots if (Path(r) / rel).is_file()), p)
        out.append(p)
    out.append(root / "versions" / v["jar_version"] / f"{v['jar_version']}.jar")
    return out


def java_major(v) -> int:
    return int((v.get("javaVersion") or {}).get("majorVersion") or 8)


def newest_fabric(root, need_json=True):
    """The newest Fabric profile in <root>/versions -> its id, or None (need_json=False: any folder of that name counts)."""
    vs = [p.name for p in (Path(root) / "versions").glob("fabric-*") if p.is_dir() and (not need_json or (p / f"{p.name}.json").is_file())] if (Path(root) / "versions").is_dir() else []
    def nums(s): return tuple(int(x) for x in re.findall(r"\d+", s))
    def key(n):                                     # (game version, loader version) from either naming
        m = re.match(r"^fabric-loader-([^-]+)-(.+)$", n) or re.match(r"^fabric-(.+)-([^-]+)$", n)
        if not m: return ((), ())
        loader, game = (m.group(1), m.group(2)) if n.startswith("fabric-loader-") else (m.group(2), m.group(1))
        return (nums(game), nums(loader))
    return sorted(vs, key=key)[-1] if vs else None


_VAR = re.compile(r"\$\{([a-zA-Z_]+)\}")


def arguments(v, values, os_name="linux", arch=None, features=None):
    """-> (jvm args, main class, game args): the version's arguments (default-user-jvm, jvm, game) for this system, ${name} -> values[name]."""
    def walk(items):
        out = []
        for it in items or []:
            if isinstance(it, str): out.append(it); continue
            if not allowed(it.get("rules"), os_name, arch, features): continue
            val = it.get("value"); out += [val] if isinstance(val, str) else list(val or [])
        return [_VAR.sub(lambda m: str(values.get(m.group(1), "")), a) for a in out]
    a = v.get("arguments") or {}
    jvm = walk(a.get("default-user-jvm")) + walk(a.get("jvm"))
    game = walk(a.get("game")) if a.get("game") else _VAR.sub(lambda m: str(values.get(m.group(1), "")), v.get("minecraftArguments") or "").split()
    return jvm, v["mainClass"], game
