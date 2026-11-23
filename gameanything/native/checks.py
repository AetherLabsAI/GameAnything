"""本机模式少打扰, part 2: catch errors without opening her game, and reload a changed mod into a game that is already open.

    check(g, src=None, server=False, gametest=False)   headless checks of a built mod (default: every mod GameAnything installed for the game):
        stardew          manifest.json (fields, EntryDll there, a content pack's framework installed), the DLL's references against the game
                         folder and smapi-internal (assemblies, types, members by name), the .NET version (the game runs .NET 6)
        cities_skylines  the DLL against the game's Managed/ (mscorlib 2.0 = .NET 3.5, ICities.IUserMod, types and members)
        overcooked2      the plugin DLL against Managed/ + BepInEx/core (mscorlib 2.0, [BepInPlugin], types and members)
        valheim          the same against Valheim's Managed/ (net462 / netstandard on the game's Mono: no .NET Core / 5+ references)
        slay_the_spire   ModTheSpire.json, Java 8 bytecode, every class it names in the game / ModTheSpire / BaseMod / StSLib jars
        minecraft        fabric.mod.json (id, entrypoint classes, mixin configs and their classes, access widener, Fabric API in mods/);
                         server=True: the mod in a headless Fabric dedicated server (her one-time setup in <data>/native/mc-server, see
                         docs/cross-platform.md), gametest=True with -Dfabric-api.gametest (the mod's GameTests, then the server exits)
        sims4            .ts4script = .pyc of Python 3.7, at most one folder deep; .package readable (DBPF)
      -> {ok, mods: [{mod, path, errors, warnings, notes}]}
    reload(g, src, name=None, setup=False)    hot reload where the game has it (no restart):
        overcooked2      BepInEx ScriptEngine (BepInEx.Debug, MIT): the DLL goes to BepInEx/scripts/, ScriptEngine reloads it
        valheim          the same (ScriptEngine in BepInEx/plugins/; she installs it once)
        cities_skylines  the game notices a changed DLL in an installed mod folder and reloads it (most reliable in the main menu;
                         Windows / macOS, untested; on Linux it did not: NoReload)
        others           NoReload with the reason (restart needed)
Only mod folders, BepInEx/scripts (with setup: ScriptEngine's own config file) and GameAnything's folders are written; nothing is deleted."""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

from .. import games as registry
from . import clrmeta, jvmclass, s4pkg
from .games import CONTENT_PATCHER, CONTENT_PATCHER_URL, BepInExGame, NativeError, java

FRAMEWORK = re.compile(r"^(mscorlib|netstandard|System(\..+)?|Microsoft\..+|Mono\..+|WindowsBase|PresentationCore|PresentationFramework)$")
PY37_MAGIC = b"\x42\x0d\x0d\x0a"
MC_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
LOG_BAD = re.compile(r"Incompatible mods? (found|set)|Mixin apply.*failed|Could not execute entrypoint|Exception in thread|Caused by:|"
                     r"crash report|Failed to start the minecraft server|NoClassDefFoundError|ClassNotFoundException|test .* failed", re.I)


class NoReload(NativeError):
    pass


def _item(mod, path): return {"mod": mod, "path": str(path), "errors": [], "warnings": [], "notes": []}


# ---------------------------------------------------------------- .NET
class _Index:
    """The assemblies a mod may use: name -> path, from the given folders (not recursive); read on first use."""
    def __init__(self, dirs):
        self.paths = {}; self._cache = {}
        for d in dirs:
            for f in sorted(Path(d).glob("*.dll")) if d and Path(d).is_dir() else []:
                self.paths.setdefault(f.stem.lower(), f)

    def get(self, name):
        k = str(name).lower()
        if k not in self.paths: return None
        if k not in self._cache:
            try: self._cache[k] = clrmeta.Assembly.read(self.paths[k])
            except clrmeta.NotManaged: self._cache[k] = None
        return self._cache[k]

    def type(self, scope, full, depth=0):
        """-> (assembly, type record) following type forwarders, or (None, None) when it is not there, or "unknown" (not loaded)."""
        a = self.get(scope)
        if a is None: return "unknown"
        if full in a.types: return a, a.types[full]
        top = full.split("/")[0]
        if top in a.exported and depth < 5:
            r = self.type(a.exported[top], full, depth + 1)
            return r
        return None, None

    def has_member(self, scope, full, member, depth=0):
        r = self.type(scope, full)
        if r == "unknown": return None
        a, t = r
        if t is None: return False
        if member in t["members"]: return True
        b = t["base"]
        if b and b[0] == clrmeta.TYPESPEC: return None                       # a generic base type: not followed, unknown
        if not b or depth > 30: return False
        bscope = b[0] or a.name
        return self.has_member(bscope, b[1], member, depth + 1)


def _ver(v): return ".".join(map(str, v[:2])) if v else "?"


def check_dll(dll: Path, idx: _Index, own: set, it: dict, runtime=None, need_types=()):
    """References of one mod DLL. runtime: "net35" (Unity's old Mono: mscorlib 2.0, no netstandard) | "mono4" (a newer Unity Mono: .NET
    Framework 4.x + netstandard, never .NET Core / 5+) | "net6" (Stardew) | None."""
    try: a = clrmeta.Assembly.read(dll)
    except clrmeta.NotManaged as e:
        it["warnings"].append(f"{dll.name} 不是 .NET 程序集（{e}），跳过"); return
    names = {r["name"] for r in a.refs}
    for r in a.refs:
        n = r["name"]
        if n.lower() in own: continue
        tgt = idx.get(n)
        if tgt is not None:
            if tgt.version and r["version"] and tuple(tgt.version) < tuple(r["version"]) and not FRAMEWORK.match(n):
                it["warnings"].append(f"{dll.name} 是按 {n} {_ver(r['version'])} 编的，游戏里是 {_ver(tgt.version)}：游戏可能比编译时用的旧")
            continue
        if idx.paths.get(n.lower()): continue                                # there but not managed (cannot happen for a real reference)
        if FRAMEWORK.match(n): continue                                      # resolved by the runtime
        it["errors"].append(f"{dll.name} 需要 {n}.dll，游戏和 mod 文件夹里都没有：把它放进 mod 文件夹，或去掉这个引用")
    if runtime == "net35":
        ms = next((r for r in a.refs if r["name"] == "mscorlib"), None)
        if ms and ms["version"][0] >= 4: it["errors"].append(f"{dll.name} 是按 .NET {_ver(ms['version'])} 编的：这个游戏的 Mono 只认 .NET 3.5（mscorlib 2.0），用 net35 重新编")
        if "netstandard" in names: it["errors"].append(f"{dll.name} 引用了 netstandard：这个游戏的 Mono 不支持，用 net35 重新编")
    if runtime == "mono4":
        sr = next((r for r in a.refs if r["name"] in ("System.Runtime", "System.Private.CoreLib")), None)
        if sr and (sr["name"] == "System.Private.CoreLib" or sr["version"][0] >= 5):
            it["errors"].append(f"{dll.name} 是按 .NET {sr['version'][0]} 编的：这个游戏跑的是 Mono（.NET Framework 4.x），TargetFramework 要 net462（或 netstandard2.0）")
    if runtime == "net6":
        sr = next((r for r in a.refs if r["name"] in ("System.Runtime", "System.Private.CoreLib")), None)
        if sr and sr["version"][0] > 6: it["errors"].append(f"{dll.name} 是按 .NET {sr['version'][0]} 编的：游戏用 .NET 6，TargetFramework 要 net6.0")
    bad_t = set(); bad_m = set()
    for scope, full in a.typerefs:
        if not scope or scope.lower() in own or idx.get(scope) is None: continue
        r = idx.type(scope, full)
        if r != "unknown" and r[1] is None: bad_t.add(f"{scope}: {full}")
    for scope, full, m in a.memberrefs:
        if scope.lower() in own or idx.get(scope) is None or f"{scope}: {full}" in bad_t: continue
        if idx.has_member(scope, full, m) is False: bad_m.add(f"{full}.{m}")
    for x in sorted(bad_t)[:20]: it["errors"].append(f"{dll.name} 用到的类型游戏里没有：{x}（游戏更新改名了？或者写错了）")
    for x in sorted(bad_m)[:20]: it["errors"].append(f"{dll.name} 调用的成员游戏里没有：{x}（只按名字查，不看参数）")
    for scope, full, what in need_types:
        if not any(s == scope and f == full for s, f in a.typerefs) and a.name != scope:
            it[what].append(f"{dll.name} 没有用到 {full}：{'游戏不会把它当成 mod' if what == 'errors' else 'BepInEx 可能不会加载它（没有 [BepInPlugin]）'}")
    it["notes"].append(f"{dll.name}: {len(a.refs)} 个程序集、{len(a.typerefs)} 个类型、{len(a.memberrefs)} 个成员引用已对照游戏")


def _dlls(src: Path, skip=()):
    if src.is_file(): return [src] if src.suffix.lower() == ".dll" else []
    return sorted(f for f in src.rglob("*.dll") if f.is_file() and f.name.lower() not in skip)


def _loose_json(t: str):
    """SMAPI's manifest.json may hold comments and trailing commas."""
    t = re.sub(r'("(?:[^"\\]|\\.)*")|//[^\n]*|/\*.*?\*/', lambda m: m.group(1) or "", t, flags=re.S)
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", t))


# ---------------------------------------------------------------- per game
def _stardew(g, src, it):
    if not src.is_dir(): it["errors"].append("要查的是一个 mod 文件夹（manifest.json + DLL）"); return
    mf = next((f for f in src.rglob("manifest.json") if f.is_file()), None)
    if mf is None: it["errors"].append("没有 manifest.json：SMAPI 不会加载它"); return
    try: m = _loose_json(mf.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as e: it["errors"].append(f"manifest.json 读不了：{e}"); return
    m = {k.lower(): v for k, v in m.items()} if isinstance(m, dict) else {}
    for k in ("name", "author", "version", "uniqueid"):
        if not m.get(k): it["errors"].append(f"manifest.json 缺少 {k}")
    gd = g.game_dir()
    if m.get("contentpackfor"):
        need = str((m["contentpackfor"] or {}).get("UniqueID") or (m["contentpackfor"] or {}).get("uniqueid") or "")
        have = set()
        for f in (gd / "Mods").rglob("manifest.json") if gd and (gd / "Mods").is_dir() else []:
            try: have.add(str({k.lower(): v for k, v in _loose_json(f.read_text(encoding="utf-8-sig")).items()}.get("uniqueid") or "").lower())
            except (ValueError, OSError, AttributeError): pass
        if need and gd and need.lower() not in have:
            it["errors"].append(f"这是 {need} 的内容包，但 Mods 里没有装 {need}"
                                + (f"：先装 Content Patcher（{CONTENT_PATCHER_URL}，或用沙箱模式：沙箱自带 2.9.1）" if need.lower() == CONTENT_PATCHER.lower() else ""))
        it["notes"].append("内容包：没有 DLL 要查"); return
    entry = m.get("entrydll")
    if not entry: it["errors"].append("manifest.json 没有 EntryDll（C# mod）也没有 ContentPackFor（内容包）"); return
    dll = mf.parent / entry
    if not dll.is_file(): it["errors"].append(f"manifest.json 的 EntryDll 是 {entry}，文件夹里没有这个文件"); return
    if gd is None: it["warnings"].append("没找到游戏：只查了 manifest.json"); return
    own = {f.stem.lower() for f in _dlls(src)}
    check_dll(dll, _Index([gd, gd / "smapi-internal"]), own, it, runtime="net6")


def _cities(g, src, it):
    man = g.managed_dir()
    ds = _dlls(src)
    if not ds:
        if src.is_dir() and list(src.glob("Source/*.cs")):
            it["notes"].append("只有源码：游戏启动时自己编译（Windows / Linux）；要先查，先 gameanything native build 出 DLL")
        else: it["errors"].append("没有 DLL")
        return
    if man is None: it["warnings"].append("没找到游戏：没法对照游戏的程序集"); return
    own = {f.stem.lower() for f in ds}; idx = _Index([man])
    for d in ds: check_dll(d, idx, own, it, runtime="net35", need_types=[("ICities", "ICities.IUserMod", "errors")])


BEPINEX_THEIRS = {"0harmony", "0harmony20", "bepinex", "bepinex.harmony", "bepinex.preloader", "harmonyxinterop"}
OC2_THEIRS = BEPINEX_THEIRS | {"oc2bridge"}


def _theirs(g) -> set:
    """BepInEx's own DLLs and the lab's bridge plugin: never a mod's plugin."""
    return BEPINEX_THEIRS | ({g.bridge.lower().removesuffix(".dll")} if g.bridge else set())


def _bepinex(g, src, it):
    ds = [d for d in _dlls(src) if d.stem.lower() not in _theirs(g)]
    if not ds: it["errors"].append("没有插件 DLL"); return
    man = g.managed_dir()
    if man is None: it["warnings"].append("没找到游戏：没法对照游戏的程序集"); return
    own = {f.stem.lower() for f in _dlls(src)}; idx = _Index([man, g.bepinex_dir() / "core"])
    for d in ds: check_dll(d, idx, own, it, runtime=g.runtime, need_types=[("BepInEx", "BepInEx.BepInPlugin", "warnings")])


def _sts(g, src, it):
    if not (src.is_file() and src.suffix.lower() == ".jar"): it["errors"].append("要查的是一个 .jar"); return
    try:
        with zipfile.ZipFile(src) as z:
            names = z.namelist()
            try: mtj = json.loads(z.read("ModTheSpire.json").decode("utf-8-sig"))
            except (KeyError, ValueError): mtj = None
            classes = {n: z.read(n) for n in names if n.endswith(".class")}
    except (zipfile.BadZipFile, OSError) as e: it["errors"].append(f"不是有效的 jar：{e}"); return
    if not mtj or not mtj.get("modid"): it["errors"].append("没有带 modid 的 ModTheSpire.json"); return
    gd = g.game_dir(); cp = set(); own = {n[:-6] for n in classes}
    jars = [gd / "desktop-1.0.jar" if gd else None, *(g._jar(x) for x in ("ModTheSpire", "BaseMod", "StSLib"))] if gd else []
    for j in jars:
        if j and j.is_file():
            try: cp |= jvmclass.jar_classes(j)
            except (zipfile.BadZipFile, OSError): it["warnings"].append(f"{j.name} 读不了")
    hi = 0; missing = {}
    for n, data in classes.items():
        try: ci = jvmclass.info(data)
        except jvmclass.BadClass as e: it["errors"].append(f"{n}: {e}"); continue
        hi = max(hi, ci["major"])
        if not cp: continue
        for r in ci["refs"]:
            if r.split("/")[0] in ("java", "javax", "sun", "jdk") or r in own or r in cp: continue
            missing.setdefault(r, n[:-6])
    if hi > 52: it["errors"].append(f"有 Java {jvmclass.JAVA.get(hi, hi)} 的字节码：游戏带的是 Java 8，要用 javac --release 8 编（gameanything native build 就是这样编的）")
    if not cp: it["warnings"].append("没找到游戏或 ModTheSpire / BaseMod：只查了 jar 本身"); return
    for r, by in sorted(missing.items())[:25]: it["errors"].append(f"{by.replace('/', '.')} 用到的类游戏、ModTheSpire、BaseMod、StSLib 里都没有：{r.replace('/', '.')}")
    it["notes"].append(f"{len(classes)} 个类已对照游戏和 ModTheSpire / BaseMod 的 jar")


def _mc_meta(src):
    with zipfile.ZipFile(src) as z:
        names = set(z.namelist())
        try: fmj = json.loads(z.read("fabric.mod.json").decode("utf-8-sig"))
        except KeyError: fmj = None
        mixins = {}
        for m in (fmj or {}).get("mixins") or []:
            cfg = m if isinstance(m, str) else (m or {}).get("config")
            if not cfg: continue
            try: mixins[cfg] = json.loads(z.read(cfg).decode("utf-8-sig"))
            except KeyError: mixins[cfg] = None
            except ValueError as e: mixins[cfg] = e
        majors = [jvmclass.info(z.read(n))["major"] for n in list(n for n in names if n.endswith(".class"))[:50]]
    return names, fmj, mixins, majors


def _minecraft(g, src, it, server=False, gametest=False, timeout=300):
    if not (src.is_file() and src.suffix.lower() == ".jar"): it["errors"].append("要查的是一个 .jar"); return
    try: names, fmj, mixins, majors = _mc_meta(src)
    except (zipfile.BadZipFile, OSError, ValueError, jvmclass.BadClass) as e: it["errors"].append(f"jar 读不了：{e}"); return
    if fmj is None: it["errors"].append("没有 fabric.mod.json：不是 Fabric mod"); return
    if not MC_ID.match(str(fmj.get("id") or "")): it["errors"].append(f"mod id {fmj.get('id')!r} 不合 Fabric 的规矩（小写字母开头，2–64 个小写字母、数字、- 或 _）")
    if not fmj.get("version"): it["errors"].append("fabric.mod.json 缺少 version")
    for kind, es in (fmj.get("entrypoints") or {}).items():
        for e in es or []:
            v = e if isinstance(e, str) else (e or {}).get("value", "")
            cls = str(v).split("::")[0].replace(".", "/") + ".class"
            if v and cls not in names: it["errors"].append(f"入口 {kind}: {v} 在 jar 里没有这个类")
    for cfg, m in mixins.items():
        if m is None: it["errors"].append(f"mixin 配置 {cfg} 在 jar 里没有"); continue
        if isinstance(m, Exception): it["errors"].append(f"mixin 配置 {cfg} 读不了：{m}"); continue
        pkg = str(m.get("package") or "").replace(".", "/")
        for side in ("mixins", "client", "server"):
            for c in m.get(side) or []:
                if f"{pkg}/{str(c).replace('.', '/')}.class" not in names: it["errors"].append(f"mixin {c}（{cfg}）在 jar 里没有这个类")
    aw = fmj.get("accessWidener")
    if aw and aw not in names: it["errors"].append(f"accessWidener 文件 {aw} 在 jar 里没有")
    dep = fmj.get("depends") or {}
    if any(k in dep for k in ("fabric-api", "fabric")) and not list(g.mods_dir().glob("fabric-api-*.jar")):
        it["errors"].append("这个 mod 需要 Fabric API，但 mods/ 里没有 fabric-api-*.jar")
    if majors: it["notes"].append(f"类文件是 Java {jvmclass.JAVA.get(max(majors), max(majors))} 的字节码")
    vers = sorted(p.name for p in (g.user_dir() / "versions").glob("*") if p.is_dir() and not p.name.startswith("fabric-loader"))
    if dep.get("minecraft"): it["notes"].append(f"要求 Minecraft {dep['minecraft']}；这台电脑上有：{', '.join(vers) or '无'}")
    if not server and not gametest: return
    if fmj.get("environment") == "client": it["notes"].append("这个 mod 只在客户端运行（environment: client）：服务器测不了，只做了静态检查"); return
    if it["errors"]: it["notes"].append("静态检查有错：先改，没有跑服务器"); return
    mc_server(g, src, fmj, it, gametest=gametest, timeout=timeout)


def server_dir(g) -> Path:
    return Path(g.env["GAMEANYTHING_MC_SERVER_DIR"]).expanduser() if g.env.get("GAMEANYTHING_MC_SERVER_DIR") else g.root / "mc-server"


SERVER_PROPS = "# written by gameanything native check (a local test server, nobody joins)\nserver-ip=127.0.0.1\nserver-port=25599\nonline-mode=false\n" \
               "level-name=m2w-check\nmax-players=1\nview-distance=3\nsimulation-distance=3\nspawn-protection=0\nsync-chunk-writes=false\n"


def mc_server(g, jar, fmj, it, gametest=False, timeout=300, java_exe=None):
    """Run the mod in the headless Fabric server she set up once (her own download and EULA). Logs to <server>/m2w-check.log."""
    d = server_dir(g)                                                   # the Fabric installer's `server` output, or the launcher jar of fabricmc.net/use/server
    launcher = next((p for p in [d / "fabric-server-launch.jar", *sorted(d.glob("fabric-server-mc.*.jar"))] if p.is_file()), d / "fabric-server-launch.jar")
    if not launcher.is_file():
        it["errors"].append(f"还没有测试用的服务器：{d} 里没有 fabric-server-launch.jar（一次性准备，见 docs/cross-platform.md「本机模式少打扰」）"); return
    eula = d / "eula.txt"
    if not (eula.is_file() and re.search(r"(?m)^eula\s*=\s*true\s*$", eula.read_text(encoding="utf-8", errors="replace"))):
        it["errors"].append(f"{eula} 里还没有 eula=true：Minecraft 的 EULA 要她自己同意（打开这个文件改成 eula=true），GameAnything 不替她同意"); return
    jx = java_exe or g.env.get("GAMEANYTHING_JAVA") or java(g.sys)["path"]
    if not jx: it["errors"].append("没有 Java：" + g.toolchain()["setup"]); return
    mods = d / "mods"
    if mods.exists():
        t = g.root / ".trash" / f"{datetime.now():%Y%m%d-%H%M%S-%f}-mc-server-mods"; t.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(mods), str(t))
    mods.mkdir(parents=True)
    shutil.copy2(jar, mods / Path(jar).name)
    want = set((fmj.get("depends") or {}).keys()) - {"minecraft", "java", "fabricloader"}
    if "fabric" in want: want.add("fabric-api")
    for f in sorted(g.mods_dir().glob("*.jar")) if g.mods_dir().is_dir() else []:   # her copies of the mods it depends on
        try:
            with zipfile.ZipFile(f) as z: mid = json.loads(z.read("fabric.mod.json").decode("utf-8-sig")).get("id")
        except (KeyError, ValueError, zipfile.BadZipFile, OSError): continue
        if mid in want and f.name != Path(jar).name: shutil.copy2(f, mods / f.name)
    if not (d / "server.properties").exists(): (d / "server.properties").write_text(SERVER_PROPS, encoding="utf-8")
    args = [jx, "-Xmx2G", *(["-Dfabric-api.gametest"] if gametest else []), "-jar", launcher.name, "nogui"]
    log = d / "m2w-check.log"
    try: p = subprocess.Popen(args, cwd=str(d), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace")
    except OSError as e: it["errors"].append(f"服务器没有跑起来：{e}"); return
    lines = []; done = threading.Event()

    def pump():
        for l in p.stdout:
            lines.append(l.rstrip("\n"))
            if re.search(r"\bDone \(\d", l): done.set()
        done.set()
    th = threading.Thread(target=pump, daemon=True); th.start()
    end = time.monotonic() + timeout; ok = None
    try:
        if gametest:
            try: rc = p.wait(timeout=timeout)
            except subprocess.TimeoutExpired: rc = None
            ok = rc == 0
            if rc is None: it["errors"].append(f"GameTest {timeout} 秒内没有跑完")
            elif rc != 0: it["errors"].append(f"GameTest 没通过（退出码 {rc}）")
        else:
            while time.monotonic() < end and not done.is_set(): done.wait(1)
            started = any(re.search(r"\bDone \(\d", l) for l in lines)
            ok = started and p.poll() is None
            if not started: it["errors"].append("服务器没有启动完" + (f"（{timeout} 秒内）" if p.poll() is None else f"（退出码 {p.returncode}）"))
    finally:
        if p.poll() is None:
            try: p.stdin.write("stop\n"); p.stdin.flush()
            except (OSError, ValueError): pass
            try: p.wait(timeout=60)
            except subprocess.TimeoutExpired: p.terminate(); p.wait(timeout=30)
        th.join(timeout=5)
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    bad = [l.strip() for l in lines if LOG_BAD.search(l)]
    if bad: it["errors"] += [f"服务器日志：{l[:300]}" for l in bad[:12]]; ok = False
    it["notes"].append(f"无界面服务器：{'加载通过' if ok else '没通过'}（日志 {log}）")
    it["server"] = bool(ok)


def _sims4(g, src, it):
    try: g.check_installable(src)
    except NativeError as e: it["errors"].append(str(e)); return
    for f in sorted(src.rglob("*.ts4script")):
        try:
            with zipfile.ZipFile(f) as z:
                pycs = [n for n in z.namelist() if n.endswith(".pyc")]
                old = [n for n in pycs if z.read(n)[:4] != PY37_MAGIC]
                if not pycs: it["errors"].append(f"{f.name} 里没有 .pyc")
                if old: it["errors"].append(f"{f.name} 里有不是 Python 3.7 编的 .pyc（{', '.join(old[:3])}）：游戏不会加载，用 gameanything native build 重新编")
                if any(n.endswith(".py") for n in z.namelist()): it["warnings"].append(f"{f.name} 里带了 .py 源码：游戏用的是 .pyc")
        except (zipfile.BadZipFile, OSError) as e: it["errors"].append(f"{f.name} 读不了：{e}")
    for f in sorted(src.rglob("*.package")):
        try:
            with s4pkg.Package(f) as p: n = len(p.entries)
            if not n: it["warnings"].append(f"{f.name} 是空的")
            else: it["notes"].append(f"{f.name}: {n} 个资源")
        except (ValueError, OSError, KeyError) as e: it["errors"].append(f"{f.name} 读不了：{e}")


def check(g, src=None, server=False, gametest=False, timeout=300) -> dict:
    """Headless checks; src: the built mod (folder, .jar, .dll). None: every mod GameAnything installed for this game."""
    srcs = [(Path(src).name, Path(src).expanduser().resolve())] if src else [(n, Path(e["path"])) for n, e in g.mods().items()]
    if not srcs: raise NativeError("没有要查的 mod：给出构建好的 mod（--src），或者先 install")
    out = []
    for name, p in srcs:
        it = _item(name, p)
        if not p.exists(): it["errors"].append(f"找不到 {p}")
        elif g.id == "stardew": _stardew(g, p, it)
        elif g.id == "cities_skylines": _cities(g, p, it)
        elif isinstance(g, BepInExGame): _bepinex(g, p, it)
        elif g.id == "slay_the_spire": _sts(g, p, it)
        elif g.id == "minecraft": _minecraft(g, p, it, server, gametest, timeout)
        elif g.id == "sims4": _sims4(g, p, it)
        elif callable(getattr(g, "check_mod", None)): g.check_mod(p, it)          # a game package's own check (games/<id>/adapter.py)
        else:
            try: g.check_installable(p); it["notes"].append(f"{g.title}: 只查了能不能安装（这个游戏的适配器没有更深的检查）")
            except NativeError as e: it["errors"].append(str(e))
        out.append(it)
    return {"ok": not any(i["errors"] for i in out), "mods": out}


# ---------------------------------------------------------------- hot reload
NO_RELOAD = registry.no_reload()     # {game id: why it cannot hot reload}: game.yaml `reload.none`
SCRIPTENGINE_CFG = "com.bepis.bepinex.scriptengine.cfg"
# Linux, 2026-10-25 (game 1.21.1-f9, real Steam): the DLL of an installed mod replaced in the city, then again in the main menu, by
# rename and by an in-place write: no OnDisabled / OnEnabled of the mod within a minute (inotify works on that folder). So no hot reload there.
CITIES_LINUX_NO_RELOAD = ("Linux 版城市：天际线实测不会重新加载换掉的 mod DLL（城市里、主菜单都试过）：改了要重开游戏。"
                          "把这一轮的改动攒在一起，开一次测完")


def _replace(src: Path, dst: Path, g):
    out = None
    if dst.exists(): out = str(g._trash(dst, "reloaded"))
    tmp = dst.with_name(f".m2w-new-{dst.name}.part")      # not *.dll: ScriptEngine watches and loads every scripts/*.dll
    shutil.copy2(src, tmp); os.replace(tmp, dst)
    return out


def scriptengine(g) -> dict:
    """BepInEx ScriptEngine in this copy of the game (Overcooked 2, Valheim): {installed, dll, scripts, cfg, watcher (True / False / None = no cfg yet)}."""
    b = g.bepinex_dir(); dll = next(iter(sorted((b / "plugins").rglob("ScriptEngine.dll"))), None) if (b / "plugins").is_dir() else None
    cfg = b / "config" / SCRIPTENGINE_CFG; w = start = None
    if cfg.is_file():
        t = cfg.read_text(encoding="utf-8", errors="replace")
        val = lambda k: (lambda m: m.group(1).lower() == "true" if m else None)(re.search(rf"(?mi)^\s*{k}\s*=\s*(\w+)", t))
        w, start = val("EnableFileSystemWatcher"), val("LoadOnStart")
    return {"installed": dll is not None, "dll": str(dll) if dll else None, "scripts": str(b / "scripts"), "cfg": str(cfg), "watcher": w, "load_on_start": start}


def reload(g, src, name=None, setup=False) -> dict:
    """Copy the newly built mod where the running game reloads it. -> {copied: [paths], how, warnings}. NoReload where the game cannot."""
    if g.id in NO_RELOAD: raise NoReload(NO_RELOAD[g.id])
    if callable(getattr(g, "reload_mod", None)): return g.reload_mod(src, name=name, setup=setup)   # a game package's own hot reload
    src = Path(src).expanduser().resolve()
    if not src.exists(): raise NativeError(f"找不到要重载的 mod：{src}")
    out = {"copied": [], "replaced_to_trash": [], "warnings": []}
    if isinstance(g, BepInExGame):
        se = scriptengine(g)
        if not se["installed"]:
            raise NoReload(f"这个 {g.title} 里没有 BepInEx ScriptEngine，不能热重载：要么重开游戏，要么请她一次性装上 ScriptEngine"
                           "（BepInEx.Debug 的 ScriptEngine.dll 放进 BepInEx/plugins/，见 docs/cross-platform.md「本机模式少打扰」）")
        ds = [d for d in _dlls(src) if d.stem.lower() not in _theirs(g)]
        if not ds: raise NativeError(f"{src} 里没有插件 DLL：先 gameanything native build --game {g.id} …")
        scripts = Path(se["scripts"]); scripts.mkdir(parents=True, exist_ok=True)
        r = g._reg(); reg = r.setdefault(g.id, {})
        for d in ds:
            t = _replace(d, scripts / d.name, g)
            if t: out["replaced_to_trash"].append(t)
            reg[f"scripts/{d.name}"] = {"path": str(scripts / d.name), "from": str(d), "at": datetime.now().astimezone().isoformat(timespec="seconds")}
            out["copied"].append(str(scripts / d.name))
            # ScriptEngine reads every scripts/*.dll with ReadSymbols = true: without its .pdb the load fails (SymbolsNotFoundException,
            # seen with ScriptEngine r11.2 on Linux 2026-10-25), so the symbols go along and a stale .pdb of an older build never stays
            pdb, old_pdb = d.with_suffix(".pdb"), scripts / (d.stem + ".pdb")
            if pdb.is_file():
                t = _replace(pdb, old_pdb, g)
                if t: out["replaced_to_trash"].append(t)
                out["copied"].append(str(old_pdb))
            else:
                if old_pdb.exists(): out["replaced_to_trash"].append(str(g._trash(old_pdb, "reloaded")))
                out["warnings"].append(f"{d.name} 旁边没有 {d.stem}.pdb：ScriptEngine 读 DLL 时要符号文件，没有会加载失败（SymbolsNotFoundException）。"
                                       "用 gameanything native build 构建（会带上 .pdb）")
            for n, e in reg.items():
                if not n.startswith("scripts/") and (Path(e["path"]) / d.name).is_file():
                    out["warnings"].append(f"{d.name} 也装在 plugins/{n}/ 里：同一个插件会加载两次，先 gameanything native uninstall --game {g.id} {n}")
        g._save_reg(r)
        if setup and (se["watcher"] is False or se["load_on_start"] is False):       # ScriptEngine's own settings (keys of BepInEx.Debug's ScriptEngine.cs)
            cfg = Path(se["cfg"]); bk = g.root / "config-backups" / f"{datetime.now():%Y%m%d-%H%M%S}-{cfg.name}"
            bk.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(cfg, bk)
            t = cfg.read_text(encoding="utf-8")
            for k in ("EnableFileSystemWatcher", "LoadOnStart"): t = re.sub(rf"(?mi)^(\s*{k}\s*=\s*)\w+", r"\1true", t)
            cfg.write_text(t, encoding="utf-8"); se["watcher"] = se["load_on_start"] = True
            out["setup"] = f"ScriptEngine 的自动重载（EnableFileSystemWatcher）和开游戏时加载（LoadOnStart）打开了（原文件备份在 {bk}）"
        if se["load_on_start"] is False: out["warnings"].append("ScriptEngine 的 LoadOnStart 是 false：游戏重开时不会从 scripts/ 加载（--setup 打开它）")
        if out.get("setup"):                                                 # ScriptEngine binds its settings once, in Awake (ScriptEngine.cs)
            out["how"] = ("设置刚改好：ScriptEngine 只在开游戏时读一次设置，所以下次开游戏起才会开游戏时加载 scripts/、文件变了自己重载；"
                          "现在开着的游戏要重开（或在游戏里按 F6，GameAnything 不按键盘）")
            return out
        out["how"] = ("ScriptEngine 看到文件变了，大约 3 秒后自己重载（游戏开着也行；旧插件的 GameObject 会被销毁，Harmony 补丁要在 OnDestroy 里 UnpatchSelf）" if se["watcher"] else
                      "ScriptEngine 的自动重载没打开：加 --setup 打开它（改 BepInEx/config 里 ScriptEngine 自己的设置），否则要在游戏里按 F6，GameAnything 不按键盘"
                      if se["watcher"] is False else "ScriptEngine 的设置文件还没有（游戏带着它开过一次才会有）；默认 LoadOnStart 是 false，开过一次后再用 --setup 打开自动重载和开游戏时加载")
        return out
    if g.id == "cities_skylines":
        if g.sys == "linux": raise NoReload(CITIES_LINUX_NO_RELOAD)
        name = name or src.name; e = g.mods().get(name)
        if e is None: raise NativeError(f"{name} 还没装过：先在游戏关着的时候 gameanything native install 一次（会打开 mod 开关），之后的改动再用 reload")
        ds = _dlls(src)
        if not ds: raise NativeError(f"{src} 里没有 DLL：先 gameanything native build --game cities_skylines …")
        for d in ds:
            t = _replace(d, Path(e["path"]) / d.name, g)
            if t: out["replaced_to_trash"].append(t)
            out["copied"].append(str(Path(e["path"]) / d.name))
        out["how"] = "游戏会发现 DLL 变了并重新加载这个 mod（在主菜单时最稳；mod 里改过的静态数据、Harmony 补丁要自己在 OnDisabled 里清掉）"
        return out
    raise NoReload(f"{g.title} 还不能热重载：改了要重开游戏")
