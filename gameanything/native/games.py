"""Per-game native adapters (D19): where the user's own copy of a game keeps its mods, saves and log on this system, and the
few safe things GameAnything does there.

    g = get("stardew")          # any id of the game registry (gameanything/games/, `gameanything game list`): the 7 code adapters below, and game
                                # packages (games/<id>/game.yaml -> DeclarativeGame, + adapter.py hooks, e.g. Terraria) or plugins
    g.info()                    found?, folders, mod loader, build toolchain, running?   (read only)
    g.backup(reason)            copy the saves (and the game's mod switches) to <data>/native/backups/<game>/<stamp>/
    g.restore(stamp)            put a backup back; what was there goes to <data>/native/.trash/ (the game must be closed)
    g.build(src, name)          Stardew Valley: dotnet build with ModBuildConfig (deploy off) -> a SMAPI mod folder with manifest.json;
                                Cities: compile the mod into a DLL and stage a mod folder (the macOS game has no compiler);
                                Sims 4: scripts/*.py -> <name>.ts4script (Python 3.7) and package/ -> <name>.package;
                                Slay the Spire: src/**/*.java -> <modid>.jar (javac --release 8, like the lab's sts-build);
                                Overcooked! 2: *.csproj -> the BepInEx plugin DLL (dotnet, net35 against the game's Managed/);
                                Valheim: the same with net462 (the lab's ModLab.csproj layout: *.csproj + Plugin.cs + Lib/ + assets/)
    g.install(src, name)        copy a built mod (folder, or a .jar for Minecraft) into the Mods folder; backs the saves up first
                                when they changed since the last backup; a mod of the same name goes to the trash, never deleted
    g.uninstall(name)           only mods GameAnything installed (<data>/native/installed.yaml)
    g.launch_url() / g.log()    how to start the game (a steam:// link; the caller tells the user first) / the newest log file
Rules: only the Mods folder and GameAnything's own folders are written (plus Cities' userGameState.cgs mod switches, and the two mod switches
in The Sims 4's Options.ini and its Mods/Resource.cfg); nothing is deleted; no mouse or keyboard control; no network. Paths can be
pinned with $GAMEANYTHING_STARDEW_DIR, $GAMEANYTHING_MINECRAFT_DIR, $GAMEANYTHING_CITIES_DIR, $GAMEANYTHING_SIMS4_DIR (the user folder; $GAMEANYTHING_SIMS4_GAME_DIR the install),
$GAMEANYTHING_STS_DIR, $GAMEANYTHING_OC2_DIR, $GAMEANYTHING_VALHEIM_DIR (the game folders). Slay the Spire keeps its saves in the game folder: there saves/, preferences/ and runs/
are backed up and restored too (still nothing outside mods/ is written by install).
"""
import glob
import json
import os
import plistlib
import re
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

import yaml

from .. import envcompat, osdirs
from . import cgs, s4pkg, steam


def data_root(env=None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("GAMEANYTHING_DATA") or osdirs.data_home()) / "native"


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _size(p: Path):
    if p.is_file(): return 1, p.stat().st_size
    n = b = 0
    for f in p.rglob("*"):
        if f.is_file(): n += 1; b += f.stat().st_size
    return n, b


def _newest_mtime(p: Path) -> float:
    if not p.exists(): return 0.0
    if p.is_file(): return p.stat().st_mtime
    return max([p.stat().st_mtime] + [f.stat().st_mtime for f in p.rglob("*")])


def _copy(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir(): shutil.copytree(src, dst, symlinks=True)
    else: shutil.copy2(src, dst)


def _run(args, timeout=20):
    try: return subprocess.run(args, capture_output=True, text=True, encoding="locale", errors="replace", timeout=timeout)   # Windows tools print in the OEM code page
    except (OSError, subprocess.SubprocessError): return None


class NativeError(Exception):
    pass


class Game:
    id = title = ""
    steam_appid = None
    process_names = ()                      # exact process names per system, for "is the game running"
    window_titles = ()                      # Linux X11: exact titles of a game window that carries no _NET_WM_PID (LWJGL 2), see hands.py
    loader_blocks_install = True            # install refuses while the mod loader is missing (Sims 4: the game's own switches, install sets them)
    # macOS, how `native drive` clicks (hands.py): "pid" = CGEventPostToPid (no cursor move, no focus change), "hid" = a real cursor move +
    # click (CGEventPost to the HID tap; only while the game is the front window and she is away). What worked, per game, on her Mac.
    mac_click = "pid"
    mac_keys = "pid"            # how drive sends keys on macOS: pid (posted to the process) or hid (the HID tap: only while she is away)
    # macOS, how `native close` asks the game to quit (quiet.py): "app" = the app's own Quit (NSRunningApplication terminate / AppleScript
    # quit, like Cmd-Q), SIGTERM only when it is still open after a while; "signal" = SIGTERM at once (a JVM exits cleanly on it)
    mac_quit = "app"

    def __init__(self, sys_=None, home=None, env=None):
        self.sys = sys_ or osdirs.system()
        self.home = Path(home) if home else Path.home()
        self.env = dict(os.environ if env is None else env)
        self.root = data_root(self.env)

    # ---- per game
    def game_dir(self): return None
    def user_dir(self) -> Path: raise NotImplementedError
    def mods_dir(self) -> Path: raise NotImplementedError
    def saves_dir(self) -> Path: raise NotImplementedError
    def log_files(self) -> list: return []
    def loader(self) -> dict: return {"ok": True, "name": "", "detail": ""}
    def toolchain(self) -> dict: return {"ok": True, "name": "", "detail": "", "setup": ""}
    def extra_files(self) -> list: return []            # backed up and restored with the saves
    def check_installable(self, src: Path): pass
    def build(self, src, name=None) -> dict: raise NativeError(f"{self.title} 的本机构建还没接上")
    def after_install(self, dst: Path): return {}
    def after_uninstall(self, dst: Path): return {}

    def _env_dir(self, var):
        """$var as a folder; a pin variable is read in both spellings (GAMEANYTHING_X_DIR, the old M2W_X_DIR; envcompat)."""
        v = next((self.env[k] for k in dict.fromkeys(envcompat.legacy_pin(var)) if self.env.get(k)), None)
        return Path(v).expanduser() if v else None

    def steam_dir(self):
        return steam.app_dir(self.steam_appid, self.sys, self.home, self.env) if self.steam_appid else None

    # ---- shared
    def installed(self) -> bool:
        return self.game_dir() is not None

    def log(self):
        fs = [f for f in self.log_files() if f.is_file()]
        return max(fs, key=lambda f: f.stat().st_mtime) if fs else None

    def running(self):
        """True / False, or None when this system cannot tell."""
        names = dict(self.process_names).get(self.sys, ())
        if not names: return None
        if self.sys == "windows":
            r = _run(["tasklist", "/FO", "CSV", "/NH"])
            return None if r is None else any(f'"{n}"' in r.stdout for n in names)
        if not shutil.which("pgrep"): return None
        if self.sys == "linux": names = [n[:15] for n in names]        # Linux pgrep matches the 15-character name in /proc/<pid>/stat (pgrep(1))
        pids = [p for n in names if (r := _run(["pgrep", "-x", n])) is not None and r.returncode == 0 for p in r.stdout.split()]
        return any(self._this_copy(p) for p in pids) if pids else False

    def pids(self):
        """The process ids of this copy of the game ([] when it is not running), or None when this system cannot tell. Used to close
        only the game GameAnything itself opened (quiet.py)."""
        names = dict(self.process_names).get(self.sys, ())
        if not names: return None
        if self.sys == "windows":
            r = _run(["tasklist", "/FO", "CSV", "/NH"])
            if r is None: return None
            out = []
            for l in r.stdout.splitlines():
                f = [x.strip().strip('"') for x in l.split('","')]
                if len(f) > 1 and f[0] in names and f[1].isdigit(): out.append(int(f[1]))
            return out
        if not shutil.which("pgrep"): return None
        if self.sys == "linux": names = [n[:15] for n in names]
        pids = [p for n in names if (r := _run(["pgrep", "-x", n])) is not None and r.returncode == 0 for p in r.stdout.split()]
        return sorted({int(p) for p in pids if p.isdigit() and self._this_copy(p)})

    def _this_copy(self, pid) -> bool:
        """Linux: a process whose program lies outside this game folder is another copy of the game (a second install, a lab
        container's copy seen 2026-10-24) and does not lock this one; nor does a zombie (exited, not yet reaped by its parent: pgrep
        lists it). Unknown (no /proc, unreadable, no game folder) counts as this copy."""
        if self.sys != "linux": return True
        try:
            if Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace").rpartition(")")[2].split()[0] == "Z": return False
        except (OSError, IndexError): pass
        gd = self.game_dir()
        if gd is None: return True
        try: exe = Path(os.readlink(f"/proc/{pid}/exe"))
        except OSError: return True
        try:
            if exe.name.startswith("wine"):                             # a Windows game under Wine: exe is Wine's loader (wine-preloader)
                return self._wine_this_copy(pid, gd)
            return exe.resolve().is_relative_to(gd.resolve())
        except OSError: return True

    def _wine_this_copy(self, pid, gd: Path) -> bool:
        """Under Wine /proc/<pid>/exe is Wine's own loader, never the game: the game's working folder (the EA app and Steam start it in
        its Bin folder) or its Wine prefix tells which copy it is. Unknown counts as this copy."""
        try:
            if Path(os.readlink(f"/proc/{pid}/cwd")).resolve().is_relative_to(gd.resolve()): return True
        except OSError: return True
        pfx = next((p.parent for p in gd.resolve().parents if p.name == "drive_c"), None)
        if pfx is None: return True
        try: env = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
        except OSError: return True
        wp = next((e[len(b"WINEPREFIX="):] for e in env if e.startswith(b"WINEPREFIX=")), None)
        if wp is None: return pfx == (self.home / ".wine").resolve()     # Wine's default prefix
        return Path(os.fsdecode(wp)).expanduser().resolve() == pfx

    def launch_url(self):
        return f"steam://rungameid/{self.steam_appid}" if self.steam_appid else None

    def prepare_launch(self) -> None: pass                  # called right before the game is started (Valheim on macOS makes its start script ready)
    def build_dir(self, name) -> Path:
        """Where a build of the mod `name` happens: per game, so mods of the same name in two games never share a folder (her Mac
        2026-10-30: a Mac disk ignores case, so Slay the Spire's and Minecraft's m2wsmoke and Terraria's M2WSmoke were ONE folder and
        each build moved the one before away)."""
        return self.root / "build" / self.id / name

    launch_needs_game_pid = True    # False: after_launch runs although the game's own process is not there yet (a launcher starts it)

    def after_launch(self, root, pids, sleep=None):         # called by launch once the game's process is there (Civ VI on macOS: press the
        return None                                         # launcher's PLAY, skip the intro); -> a dict for the launch result, or None

    def confirm_quit(self, root):
        """After the game was asked to quit and is still open: answer its own 「are you sure?」 box (`native close`). -> how, or None."""
        return None

    def launch_hint(self) -> str: return ""                # what the user picks / sets up so the game starts with its mod loader
    def extras(self) -> list:                              # optional frameworks some mods need (hints, never errors): [{name, ok, version, detail, url}]
        return []
    def launch_option(self): return None                   # the exact text for Steam's Launch Options box, when the game needs one

    def mac_app_bundle(self):
        """macOS: the game's .app bundle (the game folder is inside it, or the app lies in the game folder), or None."""
        gd = self.game_dir()
        if not gd: return None
        for a in getattr(self, "apps", ()):
            if (gd / a).is_dir(): return gd / a
        for p in (gd, *gd.parents[:3]):          # Steam's Stardew Valley folder is a bundle without the .app name (Contents/MacOS)
            if p.suffix == ".app" or (p / "Contents" / "Info.plist").is_file(): return p
        return None

    def mac_bundle_id(self):
        """macOS: CFBundleIdentifier from the app's Info.plist (for a graceful quit), or None."""
        b = self.mac_app_bundle()
        try:
            with open(b / "Contents" / "Info.plist", "rb") as fh: v = plistlib.load(fh).get("CFBundleIdentifier")
        except (OSError, TypeError, ValueError, plistlib.InvalidFileException): return None
        return v if isinstance(v, str) and re.fullmatch(r"[\w.-]+", v) else None

    def info(self) -> dict:
        gd = self.game_dir(); lg = self.log(); ok = self.installed()
        return {"game": self.id, "title": self.title, "installed": ok, "pin_var": self.pin_var, "game_dir": str(gd) if gd else None,
                "user_dir": str(self.user_dir()) if ok else None,
                "mods_dir": str(self.mods_dir()) if ok else None, "saves_dir": str(self.saves_dir()),
                "log": str(lg) if lg else None, "loader": self.loader() if ok else None, "toolchain": self.toolchain(),
                "running": self.running() if ok else False,       # a game not found is not running: the checks cost ~1-10 s each on Windows
                "launch": self.launch_url(), "launch_hint": self.launch_hint(), "launch_option": self.launch_option(),
                "extras": self.extras() if ok else []}

    def _need_closed(self, what):
        if self.running(): raise NativeError(f"{self.title} 正在运行：先退出游戏再{what}")

    # ---- backups
    def _bdir(self) -> Path: return self.root / "backups" / self.id

    def backups(self) -> list:
        out = []
        for d in sorted(self._bdir().glob("*/manifest.yaml")):
            try: out.append(yaml.safe_load(d.read_text(encoding="utf-8")))
            except (OSError, yaml.YAMLError): pass
        return out

    def needs_backup(self) -> bool:
        b = self.backups()
        if not b: return True
        return _newest_mtime(self.saves_dir()) > b[-1]["mtime"]        # the extra files change with every install: saves decide

    def backup(self, reason="manual") -> dict:
        st = _stamp(); d = self._bdir() / st; items = []
        for i, src in enumerate([self.saves_dir(), *self.extra_files()]):
            if not src.exists(): continue
            rel = "saves" if i == 0 else f"files/{src.name}"
            _copy(src, d / rel); n, b = _size(d / rel)
            items.append({"src": str(src), "in_backup": rel, "files": n, "bytes": b})
        m = {"game": self.id, "stamp": st, "at": datetime.now().astimezone().isoformat(timespec="seconds"), "reason": reason,
             "mtime": datetime.now().timestamp(), "items": items}
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.yaml").write_text(yaml.safe_dump(m, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return m

    def _trash(self, p: Path, tag: str) -> Path:
        t = self.root / ".trash" / f"{_stamp()}-{self.id}-{tag}" / p.name
        t.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(p), str(t)); return t

    def restore(self, stamp: str) -> dict:
        self._need_closed("还原")
        m = next((b for b in self.backups() if b["stamp"] == stamp), None)
        if m is None: raise NativeError(f"没有这个备份：{stamp}")
        moved = []
        for it in m["items"]:
            dst = Path(it["src"])
            if dst.exists(): moved.append(str(self._trash(dst, "before-restore")))
            _copy(self._bdir() / stamp / it["in_backup"], dst)
        return {"restored": stamp, "moved_to_trash": moved}

    # ---- mods
    def _reg_file(self) -> Path: return self.root / "installed.yaml"

    def _reg(self) -> dict:
        try: return yaml.safe_load(self._reg_file().read_text(encoding="utf-8")) or {}
        except FileNotFoundError: return {}

    def _save_reg(self, r):
        self.root.mkdir(parents=True, exist_ok=True); f = self._reg_file(); tmp = f.with_name(".installed.yaml.tmp")
        tmp.write_text(yaml.safe_dump(r, allow_unicode=True, sort_keys=False), encoding="utf-8"); os.replace(tmp, f)

    def mods(self) -> dict:
        return self._reg().get(self.id, {})

    name_re = r"[\w.+ -]+"         # a mod folder name: no path separators, no shell / glob specials

    def _check_name(self, name):
        if not re.fullmatch(self.name_re, name) or name.startswith("."): raise NativeError(f"mod 名字不合适：{name}")

    def install(self, src, name=None) -> dict:
        if not self.installed(): raise NativeError(f"没有找到 {self.title}：先装好游戏（或设置 {self.pin_var}）")
        src = Path(src).expanduser().resolve(); name = name or src.name
        if not src.exists(): raise NativeError(f"找不到要安装的 mod：{src}")
        self._check_name(name)
        lo = self.loader()
        if not lo["ok"] and self.loader_blocks_install: raise NativeError(f"还没装 {lo['name']}：{lo['detail']}")
        self.check_installable(src)
        out = {"name": name, "backup": None, "replaced_to_trash": None}
        if self.needs_backup(): out["backup"] = self.backup(f"before installing {name}")["stamp"]
        mods = self.mods_dir(); mods.mkdir(parents=True, exist_ok=True)
        dst = mods / name; tmp = mods / f".m2w-new-{name}"
        if tmp.exists(): self._trash(tmp, "stale")
        _copy(src, tmp)
        if dst.exists() or dst.is_symlink(): out["replaced_to_trash"] = str(self._trash(dst, "replaced"))
        os.replace(tmp, dst)
        out.update(self.after_install(dst) or {})
        r = self._reg(); r.setdefault(self.id, {})[name] = {"path": str(dst), "from": str(src),
                                                           "at": datetime.now().astimezone().isoformat(timespec="seconds")}
        self._save_reg(r); out["path"] = str(dst)
        return out

    def uninstall(self, name) -> dict:
        r = self._reg(); e = r.get(self.id, {}).get(name)
        if e is None: raise NativeError(f"{name} 不是 GameAnything 装的 mod，不动它")
        dst = Path(e["path"]); out = {"name": name, "moved_to_trash": None}
        if dst.exists(): out.update(self.after_uninstall(dst) or {}); out["moved_to_trash"] = str(self._trash(dst, "uninstalled"))
        del r[self.id][name]; self._save_reg(r)
        return out

    pin_var = ""


# ---------------------------------------------------------------- toolchains
def dotnet(env=None, home=None) -> dict:
    """.NET SDK majors -> {ok, path, sdks}."""
    home = Path(home) if home else Path.home()
    exe = shutil.which("dotnet") or next((str(p) for p in (home / ".dotnet" / "dotnet", Path("/usr/local/share/dotnet/dotnet")) if p.is_file()), None)
    if not exe: return {"ok": False, "path": None, "sdks": []}
    r = _run([exe, "--list-sdks"])
    sdks = [l.split()[0] for l in (r.stdout.splitlines() if r and r.returncode == 0 else []) if l.strip()]
    return {"ok": bool(sdks), "path": exe, "sdks": sdks}


def java(sys_=None) -> dict:
    """The default Java -> {ok, path, version (major)}. On macOS /usr/bin/java is a stub that pops a dialog when no JDK is
    installed, so java_home is asked first."""
    sys_ = sys_ or osdirs.system()
    if sys_ == "mac":
        r = _run(["/usr/libexec/java_home"])
        if r is not None and r.returncode == 0: exe = str(Path(r.stdout.strip()) / "bin" / "java")
        else:                                  # a JDK unpacked by hand or `brew install openjdk` (keg-only): java_home does not know it, nor does $PATH's stub
            homes = [os.environ.get("JAVA_HOME") or ""] + sorted(glob.glob("/opt/homebrew/opt/openjdk*") + glob.glob("/usr/local/opt/openjdk*")
                                                                              + glob.glob(str(Path.home() / ".local/jdk/*/Contents/Home")), reverse=True)
            exe = next((str(Path(h) / "bin" / "java") for h in homes if h and (Path(h) / "bin" / "java").is_file()), None)
            if not exe: return {"ok": False, "path": None, "version": None}
    else:
        exe = shutil.which("java")
        if not exe: return {"ok": False, "path": None, "version": None}
    r = _run([exe, "-version"])
    m = re.search(r'version "(\d+)(?:\.(\d+))?', (r.stderr + r.stdout) if r else "")
    v = None if not m else int(m.group(2)) if m.group(1) == "1" else int(m.group(1))
    return {"ok": v is not None, "path": exe, "version": v}


def _pe_arch(p: Path):
    """A Windows .exe / .dll -> "x86" | "x64", or None (not there, not a PE file, another machine)."""
    try:
        with open(p, "rb") as f: h = f.read(4096)
        o = int.from_bytes(h[0x3C:0x40], "little")
        if h[:2] != b"MZ" or h[o:o + 4] != b"PE\0\0": return None
        return {0x14C: "x86", 0x8664: "x64"}.get(int.from_bytes(h[o + 4:o + 6], "little"))
    except (OSError, ValueError): return None


def _dotnet_need(major: int, purpose: str, env, home) -> dict:
    d = dotnet(env, home)
    ok = any(int(s.split(".")[0]) >= major for s in d["sdks"] if s.split(".")[0].isdigit())
    return {"ok": ok, "name": f".NET SDK {major}+", "detail": f"{purpose}; found: {', '.join(d['sdks']) or 'none'}",
            "setup": "" if ok else "https://dotnet.microsoft.com/download (or on macOS: brew install --cask dotnet-sdk)"}


# ---------------------------------------------------------------- Stardew Valley (SMAPI)
CONTENT_PATCHER = "Pathoschild.ContentPatcher"
CONTENT_PATCHER_URL = "https://www.nexusmods.com/stardewvalley/mods/1915"   # the only download of the built mod (the sandbox image builds 2.9.1 from source)
MODBUILDCONFIG = "4.3.2"                    # Pathoschild.Stardew.ModBuildConfig for a mod folder without a .csproj (the Linux test used 4.3.0)
_SD_CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <AssemblyName>{name}</AssemblyName>
    <RootNamespace>{name}</RootNamespace>
    <Version>1.0.0</Version>
    <TargetFramework>net6.0</TargetFramework>
    <LangVersion>latest</LangVersion>
    <Nullable>disable</Nullable>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Pathoschild.Stardew.ModBuildConfig" Version="{mbc}" />
  </ItemGroup>
</Project>
"""


def _json_loose(t: str):
    """SMAPI reads manifest.json with comments and trailing commas allowed: drop those, then json; None when it still is not JSON."""
    t = re.sub(r'("(?:[^"\\]|\\.)*")|//[^\n]*|/\*.*?\*/', lambda m: m.group(1) or "", t, flags=re.S)
    t = re.sub(r",(\s*[}\]])", r"\1", t)
    try: return json.loads(t)
    except ValueError: return None


class Stardew(Game):
    # Content Patcher packs are by convention named "[CP] Name" (her decision 2026-11-02): brackets are allowed for Stardew. The name is only
    # ever a path part and an argv item (never a shell string or a glob pattern), so [ ] are harmless here.
    name_re = r"[\w.+ \[\]-]+"
    id, title, steam_appid, pin_var = "stardew", "Stardew Valley", 413150, "GAMEANYTHING_STARDEW_DIR"
    process_names = (("mac", ("StardewModdingAPI", "Stardew Valley")), ("linux", ("StardewModdingAPI", "Stardew Valley")),
                     ("windows", ("StardewModdingAPI.exe", "Stardew Valley.exe")))
    mac_click = "hid"           # her Mac 2026-10-25: CGEventPostToPid clicks did not press the title screen's buttons; real cursor clicks did

    def game_dir(self):
        """The folder that holds Stardew Valley.dll and Mods/ (on macOS inside the app bundle: Contents/MacOS)."""
        gog = {"mac": [Path("/Applications/Stardew Valley.app")],
               "windows": [Path("C:/Program Files (x86)/GOG Galaxy/Games/Stardew Valley"), Path("C:/GOG Games/Stardew Valley")]}.get(self.sys, [])
        for d in [self._env_dir(self.pin_var), self.steam_dir(), *gog]:
            if not d: continue
            for x in (d / "Contents" / "MacOS", d):
                if (x / "Stardew Valley.dll").is_file(): return x
        return None

    def user_dir(self):
        if self.sys == "windows": return Path(self.env.get("APPDATA") or self.home / "AppData" / "Roaming") / "StardewValley"
        return Path(self.env.get("XDG_CONFIG_HOME") or self.home / ".config") / "StardewValley"

    def mods_dir(self): return self.game_dir() / "Mods"
    def saves_dir(self): return self.user_dir() / "Saves"
    def log_files(self): return [self.user_dir() / "ErrorLogs" / "SMAPI-latest.txt"]

    def loader(self):
        gd = self.game_dir(); ok = bool(gd and (gd / "StardewModdingAPI.dll").is_file())
        return {"ok": ok, "name": "SMAPI", "detail": "installed" if ok else "install SMAPI from https://smapi.io (its installer finds the game)"}

    def _smapi_exe(self):
        gd = self.game_dir(); x = gd / "StardewModdingAPI.exe" if gd else None
        return x if x and x.is_file() else None

    def launch_url(self):
        # Windows: the SMAPI installer leaves Steam alone, so steam://rungameid starts the plain Stardew Valley.exe and no mod loads
        # (a real Windows 11 PC, 2026-11-01). Start SMAPI itself; Steam is running, so the game still has its Steam API.
        if self.sys == "windows" and self._smapi_exe(): return f"script:{self._smapi_exe()}"
        return super().launch_url()

    def launch_option(self):
        return f"\"{self._smapi_exe()}\" %command%" if self.sys == "windows" and self._smapi_exe() else None

    def launch_hint(self):
        if self.sys != "windows": return ""
        opt = self.launch_option() or '"<game folder>\\StardewModdingAPI.exe" %command%'
        return ("GameAnything starts StardewModdingAPI.exe itself. To play with mods from Steam's Play button, put  "
                f"{opt}  in Steam > Stardew Valley > Properties > Launch Options (once)")

    def toolchain(self):
        return _dotnet_need(6, "builds SMAPI C# mods (net6.0)", self.env, self.home)

    def installed_mods(self) -> dict:
        """{unique id (lower case): version} of every mod folder in Mods/ (one level of nesting, like SMAPI's grouping folders)."""
        gd = self.game_dir(); out = {}
        if not gd or not (gd / "Mods").is_dir(): return out
        for f in [*(gd / "Mods").glob("*/manifest.json"), *(gd / "Mods").glob("*/*/manifest.json")]:
            if any(p.startswith(".") for p in f.relative_to(gd / "Mods").parts): continue        # SMAPI skips dot folders
            m = _json_loose(f.read_text(encoding="utf-8-sig", errors="replace")) if f.is_file() else None
            if isinstance(m, dict):
                m = {k.lower(): v for k, v in m.items()}
                if m.get("uniqueid"): out[str(m["uniqueid"]).lower()] = str(m.get("version") or "")
        return out

    def extras(self):
        v = self.installed_mods().get(CONTENT_PATCHER.lower())
        return [{"name": "Content Patcher", "ok": v is not None, "version": v or None, "url": CONTENT_PATCHER_URL,
                 "detail": f"{v or '?'} installed (content packs work)" if v is not None else
                           f"not installed; only content packs (ContentPackFor {CONTENT_PATCHER}) need it: {CONTENT_PATCHER_URL}"}]

    def build(self, src, name=None) -> dict:
        """A SMAPI C# mod: `dotnet build` of <src>/*.csproj (Pathoschild.Stardew.ModBuildConfig; a minimal net6.0 one with it when there is
        none) against this copy of the game (-p:GamePath), with ModBuildConfig's deploy and zip OFF (it would write into Mods/ without
        a backup; `install` does that). NuGet fetches ModBuildConfig on the first build (network). Staged under
        <data>/native/build/<name>/mod/<name>/: the mod DLL + .pdb + its own libraries (never the game's / SMAPI's), manifest.json and
        every other file of src except *.cs, *.csproj, bin/, obj/ -> {staged, dll, log, warnings}."""
        src = Path(src).expanduser().resolve()
        if not src.is_dir(): raise NativeError(f"找不到 mod 文件夹：{src}")
        cs = [f for f in src.rglob("*.cs") if not ({"bin", "obj"} & set(f.relative_to(src).parts))]
        if not cs:
            pack = self._manifest(src)
            if pack and pack.get("contentpackfor"): return self._stage_pack(src, name, pack)
            raise NativeError(f"{src} 里没有 .cs 文件：C# mod 要有 .cs；内容包要在 manifest.json 写 "
                              f"\"ContentPackFor\": {{\"UniqueID\": \"{CONTENT_PATCHER}\"}}")
        mf = src / "manifest.json"
        if not mf.is_file(): raise NativeError(f"{src} 里没有 manifest.json：SMAPI 不会加载它（要有 Name、Author、Version、UniqueID、EntryDll）")
        man = _json_loose(mf.read_text(encoding="utf-8-sig", errors="replace"))
        if not isinstance(man, dict): raise NativeError(f"{mf} 不是有效的 JSON")
        man = {k.lower(): v for k, v in man.items()}
        entry = man.get("entrydll")
        if not entry: raise NativeError(f"{mf} 里没有 EntryDll：C# mod 要写 \"EntryDll\": \"<程序集名>.dll\"")
        projs = sorted(src.glob("*.csproj"))
        if len(projs) > 1: raise NativeError(f"{src} 里有好几个 .csproj（{', '.join(p.name for p in projs)}）：只留一个")
        proj = projs[0] if projs else None
        asm = None
        if proj:
            m = re.search(r"<AssemblyName>\s*([^<\s]+)\s*</AssemblyName>", proj.read_text(encoding="utf-8-sig", errors="replace"))
            asm = m.group(1) if m else proj.stem
        asm = asm or Path(str(entry)).stem
        if Path(str(entry)).name.lower() != f"{asm}.dll".lower():
            raise NativeError(f"manifest.json 的 EntryDll 是 {entry}，但编出来的是 {asm}.dll：SMAPI 会找不到它，改成一样的名字")
        name = name or src.name
        self._check_name(name)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", asm): raise NativeError(f"程序集名要是字母、数字、下划线、点：{asm}")
        gd = self.game_dir()
        if gd is None: raise NativeError(f"没有找到 {self.title}（或设置 {self.pin_var}）")
        if not self.loader()["ok"]: raise NativeError("还没装 SMAPI：" + self.loader()["detail"])
        dn = dotnet(self.env, self.home)
        if not dn["ok"]: raise NativeError("没有 .NET SDK：" + self.toolchain()["setup"])
        w = self.build_dir(name)
        if w.exists(): self._trash(w, "old-build")
        shutil.copytree(src, w / "proj", ignore=lambda d, fs: [f for f in fs if f in ("bin", "obj") and Path(d) == src])
        pf = w / "proj" / (proj.name if proj else f"{asm}.csproj")
        if proj is None: pf.write_text(_SD_CSPROJ.format(name=asm, mbc=MODBUILDCONFIG), encoding="utf-8")
        elif "ModBuildConfig" not in pf.read_text(encoding="utf-8-sig", errors="replace"):
            raise NativeError(f"{proj.name} 没用 Pathoschild.Stardew.ModBuildConfig：加上 <PackageReference Include=\"Pathoschild.Stardew.ModBuildConfig\" "
                              f"Version=\"{MODBUILDCONFIG}\" />（它找到游戏和 SMAPI 的 DLL），或删掉 .csproj 让 GameAnything 生成一个")
        env = {**self.env, "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"}
        try: r = subprocess.run([dn["path"], "build", str(pf), "-c", "Release", f"-p:GamePath={gd}", "-p:EnableModDeploy=false", "-p:EnableModZip=false",
                                 "-o", str(w / "out"), "-nologo", "-clp:NoSummary"],
                                capture_output=True, text=True, encoding="locale", errors="replace", timeout=900, env=env)
        except (OSError, subprocess.SubprocessError) as e: raise NativeError(f"dotnet build 没有跑起来：{e}")
        (w / "build.log").write_text(r.stdout + r.stderr, encoding="utf-8")
        dll = w / "out" / f"{asm}.dll"
        if r.returncode != 0 or not dll.is_file():
            errs = sorted({l.strip() for l in (r.stdout + r.stderr).splitlines() if " error " in l})
            hint = "\n（NuGet 下载 ModBuildConfig 要联网）" if any("NU1101" in e or "NU1301" in e for e in errs) else ""
            raise NativeError("编译失败：\n" + "\n".join(errs[:20] or [(r.stdout + r.stderr)[-1500:]]) + hint + f"\n（完整日志：{w / 'build.log'}）")
        theirs = {p.name.lower() for p in [*gd.glob("*.dll"), *(gd / "smapi-internal").glob("*.dll")]}
        st = w / "mod" / name; st.mkdir(parents=True)
        for d in sorted((w / "out").glob("*.dll")):
            if d.name.lower() not in theirs or d.name.lower() == dll.name.lower():
                shutil.copy2(d, st / d.name)
                if d.with_suffix(".pdb").is_file(): shutil.copy2(d.with_suffix(".pdb"), st / (d.stem + ".pdb"))
        for f in src.rglob("*"):
            rel = f.relative_to(src)
            if f.is_file() and rel.parts[0] not in ("bin", "obj") and f.suffix.lower() not in (".cs", ".csproj", ".sln") and f.name != "NuGet.config": _copy(f, st / rel)
        warn = [] if str(man.get("uniqueid") or "").strip() else ["manifest.json 没有 UniqueID：SMAPI 会拒绝加载"]
        return {"staged": str(st), "dll": str(st / dll.name), "log": str(w / "build.log"), "warnings": warn}

    @staticmethod
    def _manifest(src: Path):
        """<src>/manifest.json with lower-case keys, or None."""
        try: m = _json_loose((src / "manifest.json").read_text(encoding="utf-8-sig", errors="replace"))
        except OSError: return None
        return {k.lower(): v for k, v in m.items()} if isinstance(m, dict) else None

    def _stage_pack(self, src: Path, name, man) -> dict:
        """A content pack (manifest.json with ContentPackFor, no code): nothing to compile; its files staged like a built mod, so
        `native build --install` (and `lab sandbox build`, which runs it in the sandbox) installs it too -> {staged, dll None, warnings}."""
        name = name or src.name
        self._check_name(name)
        if self.game_dir() is None: raise NativeError(f"没有找到 {self.title}（或设置 {self.pin_var}）")
        w = self.build_dir(name)
        if w.exists(): self._trash(w, "old-build")
        st = w / "mod" / name; st.mkdir(parents=True)
        for f in src.rglob("*"):
            rel = f.relative_to(src)
            if f.is_file() and not any(p.startswith(".") or p in ("bin", "obj") for p in rel.parts): _copy(f, st / rel)
        cpf = man.get("contentpackfor") if isinstance(man.get("contentpackfor"), dict) else {}
        need = str(cpf.get("UniqueID") or cpf.get("uniqueid") or "")
        warn = [] if str(man.get("uniqueid") or "").strip() else ["manifest.json 没有 UniqueID：SMAPI 会拒绝加载"]
        if not need: warn.append("manifest.json 的 ContentPackFor 没有 UniqueID：SMAPI 不知道它是谁的内容包")
        elif need.lower() not in self.installed_mods():
            warn.append(f"Mods 里没有装 {need}：游戏会跳过这个内容包" + (f"（{CONTENT_PATCHER_URL}；沙箱的 ga-sdv layer 自带）" if need.lower() == CONTENT_PATCHER.lower() else ""))
        if need.lower() == CONTENT_PATCHER.lower() and not (src / "content.json").is_file():
            warn.append("Content Patcher 内容包要有 content.json（Format + Changes）")
        return {"staged": str(st), "dll": None, "log": None, "warnings": warn, "content_pack": need or True}

    def check_installable(self, src):
        """SMAPI loads a folder with a manifest.json and skips anything else without a word in the game. ModBuildConfig's
        bin/Release/net6.0 holds no manifest.json when deploy is off (seen 2026-10-24), so that folder is refused here."""
        if not src.is_dir(): raise NativeError(f"要装的是一个 mod 文件夹（里面有 manifest.json 和 DLL）：{src}")
        if not any(f.name.lower() == "manifest.json" for f in src.rglob("*") if f.is_file()):
            raise NativeError(f"{src} 里没有 manifest.json，SMAPI 不会加载它：把 manifest.json 放到 DLL 旁边（dotnet build 的 bin/ 输出里没有它；"
                              "或打开 ModBuildConfig 的 EnableModZip，解压 bin/ 里的 zip，安装里面的文件夹）")


# ---------------------------------------------------------------- Minecraft: Java Edition (Fabric)
class Minecraft(Game):
    id, title, pin_var = "minecraft", "Minecraft: Java Edition", "GAMEANYTHING_MINECRAFT_DIR"
    process_names = ()                      # the game is a plain java process: told apart by its --gameDir (running() below)
    # macOS: the app's own Quit (NSRunningApplication terminate = Cmd-Q): the game logs "Stopping!" and exits in ~2 s (her Mac 2026-10-30).
    # SIGTERM (the old way, kept as the fallback) also ends the JVM cleanly, but the Launcher then shows a crash report (exit code 143)
    # at its next start, a dialog in front of PLAY.
    mac_quit = "app"
    mac_click = "hid"                       # the Launcher (and the game) take real clicks only
    launch_needs_game_pid = False           # macOS: launch opens the Launcher; after_launch presses its PLAY, then the game's java appears
    # The Launcher on her Mac (2026-10-30, 1280x748): PLAY under the banner, at these fractions of its window (two layouts seen: with
    # and without the small button next to PLAY; this point is inside both). It draws its page only while it is the front app.
    LAUNCHER_PLAY = (0.54, 0.763)
    MAC_APPS = (Path("/Applications"),)

    def running(self):
        """Every launcher (the official one, portablemc, Prism) starts the client with `--gameDir <this folder>`: look for that in
        the process list (restoring saves under a running game would be overwritten by it, seen 2026-10-24). Windows: tasklist shows no
        arguments -> None (cannot tell)."""
        if self.sys == "windows" or not shutil.which("ps"): return None
        r = _run(["ps", "-Aww", "-o", "command="])
        if r is None or r.returncode != 0: return None
        arg = "--gameDir " + str(self.user_dir())
        return any(arg + " " in l or l.rstrip().endswith(arg) for l in r.stdout.splitlines())

    def pids(self):
        if self.sys == "windows" or not shutil.which("ps"): return None
        r = _run(["ps", "-Aww", "-o", "pid=,command="])
        if r is None or r.returncode != 0: return None
        arg = "--gameDir " + str(self.user_dir()); out = []
        for l in r.stdout.splitlines():
            pid, _, cmd = l.strip().partition(" ")
            if pid.isdigit() and (arg + " " in cmd or cmd.rstrip().endswith(arg)): out.append(int(pid))
        return out

    def user_dir(self):
        if self._env_dir(self.pin_var): return self._env_dir(self.pin_var)
        if self.sys == "mac": return self.home / "Library" / "Application Support" / "minecraft"
        if self.sys == "windows": return Path(self.env.get("APPDATA") or self.home / "AppData" / "Roaming") / ".minecraft"
        return self.home / ".minecraft"

    def game_dir(self):
        d = self.user_dir()
        return d if (d / "versions").is_dir() or (d / "launcher_profiles.json").is_file() else None

    def mods_dir(self): return self.user_dir() / "mods"
    def saves_dir(self): return self.user_dir() / "saves"
    def log_files(self): return [self.user_dir() / "logs" / "latest.log"]
    def launch_url(self):
        """macOS: the Minecraft Launcher app (after_launch presses PLAY with the last used installation, checked to be Fabric). Elsewhere
        None: the Launcher has no link to start a profile, the user picks the Fabric profile."""
        if self.sys == "mac":
            for d in (*self.MAC_APPS, self.home / "Applications"):
                if (d / "Minecraft.app").is_dir(): return str(d / "Minecraft.app")
        return None

    def last_installation(self):
        """The Launcher's most recently used installation -> (name, lastVersionId), or None (launcher_profiles.json)."""
        try: p = json.loads((self.user_dir() / "launcher_profiles.json").read_text(encoding="utf-8"))
        except (OSError, ValueError): return None
        ps = [v for v in (p.get("profiles") or {}).values() if isinstance(v, dict)]
        if not ps: return None
        v = max(ps, key=lambda v: str(v.get("lastUsed") or ""))
        return v.get("name") or v.get("lastVersionId") or "", v.get("lastVersionId") or ""

    def _launchers(self):
        r = _run(["pgrep", "-f", "Minecraft.app/Contents/MacOS/launcher"])
        return [int(x) for x in r.stdout.split()] if r is not None and r.returncode == 0 else []

    def after_launch(self, root, pids, sleep=None):
        """macOS: press the Launcher's PLAY when its last used installation is the Fabric one, then record the game's java process.
        Only PLAY: accounts, settings and the installation list are never touched; another installation -> the user picks Fabric."""
        if self.sys != "mac": return None
        import time
        from . import hands, macapp, quiet
        sleep = sleep or time.sleep
        last = self.last_installation()
        if not last or "fabric" not in (last[1] or last[0]).lower():
            return {"launcher": f"the last used installation is {last[0] if last else 'unknown'}, not Fabric: pick the Fabric "
                                "installation in the Launcher and press PLAY"}
        be = hands.backend(); win = None; end = time.monotonic() + 60
        while time.monotonic() < end and not self.pids():
            ls = set(self._launchers())
            ws = [w for w in be._list(1 | 16, 0) if int(w.get("pid", 0)) in ls and w.get("layer") == 0 and w.get("w", 0) >= 600]
            if ws: win = ws[0]; break
            sleep(2)
        if win is None: return {"launcher": "no Launcher window: press PLAY in the Minecraft Launcher (Fabric installation)"}
        out = {}
        if not self.pids():
            macapp.activate(int(win["pid"])); sleep(8)              # it draws its page only in front, and takes a few seconds for it
            x, y = round(win["w"] * self.LAUNCHER_PLAY[0]), round(win["h"] * self.LAUNCHER_PLAY[1])
            try: hands.drive(root, self, [f"click {x} {y}"], click="hid", launcher=[int(win["pid"])]); out["launcher"] = f"PLAY pressed ({last[0]})"
            except hands.Refused as e: return {"launcher": "waiting for PLAY (press it in the Launcher)", "why": e.why}
        end = time.monotonic() + 90
        while time.monotonic() < end and not self.pids(): sleep(2)
        game = self.pids()
        if not game:
            return {**out, "game": "the game did not start: a dialog in the Launcher (a crash report: Do not share) may be in front of PLAY"}
        quiet.add_pids(root, self, game); out["game"] = f"java {game}"
        return out

    def loader(self):
        from . import mcversion
        v = [n for n in [mcversion.newest_fabric(self.user_dir(), need_json=False)] if n]       # the Fabric installer's fabric-loader-<loader>-<game> (or portablemc's fabric-<game>-<loader>)
        api = sorted(p.name for p in self.mods_dir().glob("fabric-api-*.jar"))
        detail = (f"{v[-1]}" + (f", {api[-1]}" if api else ", Fabric API not in mods/ yet")) if v else \
                 "install the Fabric loader from https://fabricmc.net/use/installer/ (then put Fabric API in mods/)"
        return {"ok": bool(v), "name": "Fabric", "detail": detail}

    def check_installable(self, src):
        """Fabric loads only mod .jar files straight in mods/ (not folders). `gradlew build` puts two jars in build/libs: the mod and
        a *-sources.jar with the same fabric.mod.json but no classes, which crashes the game or clashes with the real one (2026-10-24)."""
        if not (src.is_file() and src.suffix.lower() == ".jar"):
            raise NativeError(f"要装的是一个 .jar 文件（Fabric 只加载 mods/ 里的 .jar，不加载文件夹）：{src}")
        try:
            with zipfile.ZipFile(src) as z: names = z.namelist()
        except (zipfile.BadZipFile, OSError): raise NativeError(f"{src.name} 不是有效的 jar（zip）文件")
        if "fabric.mod.json" not in names: raise NativeError(f"{src.name} 里没有 fabric.mod.json：不是 Fabric mod")
        if not any(n.endswith(".class") for n in names):
            raise NativeError(f"{src.name} 里没有编译好的 .class（像是 -sources.jar）：装 build/libs 里不带 -sources 的那个 jar")

    def toolchain(self):
        # the JDK must be at least the game's own Java (26.3: 25): an older javac cannot read its class files (a real Windows PC, 2026-11-01)
        from . import mcversion
        vid = mcversion.newest_fabric(self.user_dir()) if self.game_dir() else None
        try: need = max(21, mcversion.java_major(mcversion.load(self.user_dir(), vid))) if vid else 21
        except (OSError, ValueError, KeyError): need = 21
        j = java(self.sys); ok = bool(j["ok"] and j["version"] >= need)
        return {"ok": ok, "name": f"JDK {need}+" + (f" (the game {vid.rsplit('-', 1)[-1]} needs Java {need})" if vid else " (the bridge targets 25)"),
                "detail": f"builds Fabric mods (javac against the game's own files, or Gradle); found: {j['version'] or 'none'}",
                "setup": "" if ok else "https://adoptium.net (or on macOS: brew install --cask temurin)"}

    def build(self, src, name=None) -> dict:
        """A Fabric mod without Gradle (Minecraft 26.x ships unobfuscated, so no remapping): <src>/src/main/java/**/*.java (or <src>/src/**)
        compiled with the JDK's javac against the newest Fabric profile in versions/ (its libraries + the game's client jar, all from her own
        .minecraft, offline) + mods/fabric-api-*.jar + <src>/libs/*.jar, then one jar of the classes + fabric.mod.json + resources at
        <data>/native/build/<modid>/<modid>-<version>.jar -> {staged, jar, modid, log}. Older (obfuscated) versions need the Gradle setup."""
        from . import mcversion
        src = Path(src).expanduser().resolve()
        res = src / "src" / "main" / "resources"
        fj = next((p for p in (res / "fabric.mod.json", src / "fabric.mod.json") if p.is_file()), None)
        if fj is None: raise NativeError(f"{src} 里没有 fabric.mod.json（放在最上层或 src/main/resources/）")
        try: meta = json.loads(fj.read_text(encoding="utf-8-sig")); modid = meta["id"]
        except (ValueError, KeyError) as e: raise NativeError(f"fabric.mod.json 读不了或没有 id：{e}")
        name = name or modid
        if not re.fullmatch(r"[\w.+-]+", name) or name.startswith("."): raise NativeError(f"mod 名字不合适：{name}")
        jroot = src / "src" / "main" / "java" if (src / "src" / "main" / "java").is_dir() else src / "src"
        javas = sorted(p.relative_to(src).as_posix() for p in jroot.rglob("*.java")) if jroot.is_dir() else []
        if not javas: raise NativeError(f"{jroot} 里没有 .java 文件")
        root = self.user_dir(); vid = mcversion.newest_fabric(root)
        if not vid: raise NativeError(f"{root}/versions 里没有 Fabric：" + self.loader()["detail"])
        try: v = mcversion.load(root, vid)
        except (OSError, ValueError, KeyError) as e: raise NativeError(f"读不了 {vid} 的版本文件：{e}")
        cp = mcversion.classpath(root, v, self.sys)
        missing = [p for p in cp if not p.is_file()]
        if missing: raise NativeError(f"{vid} 缺 {len(missing)} 个文件（先用启动器开一次这个版本）：{missing[0]}")
        extra = sorted(self.mods_dir().glob("fabric-api-*.jar")) + (sorted((src / "libs").glob("*.jar")) if (src / "libs").is_dir() else [])
        j = java(self.sys)
        jc = Path(j["path"]).with_name("javac.exe" if self.sys == "windows" else "javac") if j["path"] else None
        if not (jc and jc.is_file()): jc = Path(shutil.which("javac")) if shutil.which("javac") else None
        if not (jc and j["version"] and j["version"] >= 17): raise NativeError("没有能用的 JDK（要 javac，17 以上）：" + self.toolchain()["setup"])
        if j["version"] < mcversion.java_major(v):       # javac cannot read the game's newer class files (26.3: class version 69)
            raise NativeError(f"{vid} 是用 Java {mcversion.java_major(v)} 编的，这台电脑的 JDK 是 {j['version']}：装 JDK {mcversion.java_major(v)}："
                              + self.toolchain()["setup"])
        release = min(j["version"], mcversion.java_major(v))
        w = self.build_dir(name)
        if w.exists(): self._trash(w, "old-build")
        (w / "classes").mkdir(parents=True)
        for jar in extra:                                # Fabric API is a jar of jars (META-INF/jars/*.jar): javac needs the inner ones
            cp.append(jar)
            try:
                with zipfile.ZipFile(jar) as z:
                    for n in z.namelist():
                        if n.startswith("META-INF/jars/") and n.endswith(".jar"):
                            d = w / "deps" / jar.stem / Path(n).name; d.parent.mkdir(parents=True, exist_ok=True); d.write_bytes(z.read(n)); cp.append(d)
            except (zipfile.BadZipFile, OSError) as e: raise NativeError(f"{jar.name} 读不了：{e}")
        args = w / "sources.txt"
        args.write_text("".join(f'"{s}"\n' for s in javas), encoding="utf-8")
        try: r = subprocess.run([str(jc), "--release", str(release), "-nowarn", "-encoding", "UTF-8", "-cp", os.pathsep.join(map(str, cp)),
                                 "-d", str(w / "classes"), f"@{args}"], cwd=str(src), capture_output=True, text=True, encoding="locale", errors="replace", timeout=900)
        except (OSError, subprocess.SubprocessError) as e: raise NativeError(f"javac 没有跑起来：{e}")
        out = r.stdout + r.stderr
        (w / "build.log").write_text(f"javac --release {release} against {vid} ({len(cp)} jars)\n" + out, encoding="utf-8")
        if r.returncode != 0:
            errs = [l for l in out.splitlines() if ": error:" in l or l.startswith("error:")]
            raise NativeError("编译失败：\n" + "\n".join(errs[:20] or [out[-1500:]]) + f"\n（完整日志：{w / 'build.log'}）")
        jar = w / f"{name}-{meta.get('version') or '0'}.jar"
        with zipfile.ZipFile(jar, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("META-INF/MANIFEST.MF", _MANIFEST)
            for f in sorted((w / "classes").rglob("*")):
                if f.is_file(): z.write(f, f.relative_to(w / "classes").as_posix())
            if res.is_dir():
                for f in sorted(res.rglob("*")):
                    if f.is_file() and f != fj: z.write(f, f.relative_to(res).as_posix())
            z.write(fj, "fabric.mod.json")
        return {"staged": str(jar), "jar": str(jar), "modid": modid, "version": vid, "log": str(w / "build.log")}


# ---------------------------------------------------------------- Cities: Skylines 1 (the game's own mod loader)
class CitiesSkylines(Game):
    id, title, steam_appid, pin_var = "cities_skylines", "Cities: Skylines", 255710, "GAMEANYTHING_CITIES_DIR"
    process_names = (("mac", ("Cities",)), ("linux", ("Cities.x64",)), ("windows", ("Cities.exe",)))
    # macOS: the Steam start opens the Paradox Launcher first (Cities.app/Contents/Launcher/dowser; its window belongs to a process
    # named "Paradox Launcher"), the game starts after its PLAY. Her Mac 2026-10-31, launcher 2026.13, window 1280x670: PLAY here.
    LAUNCHER_PLAY = (0.673, 0.387)

    @property
    def launch_needs_game_pid(self): return self.sys != "mac"     # macOS: after_launch presses the launcher's PLAY, then the game starts

    def after_launch(self, root, pids, sleep=None):
        """macOS: press the Paradox Launcher's PLAY (only PLAY: not RESUME, account, DLC or store), then record the game's process."""
        if self.sys != "mac": return None
        import time
        from . import hands, macapp, quiet
        sleep = sleep or time.sleep
        be = hands.backend(); win = None; end = time.monotonic() + 1800        # the first start from a USB drive: macOS verifies it first
        while time.monotonic() < end and not self.pids():
            ws = [w for w in be._list(1 | 16, 0) if w.get("owner") == "Paradox Launcher" and w.get("layer") == 0 and w.get("w", 0) >= 600]
            if ws: win = ws[0]; break
            sleep(3)
        out = {}
        if win is not None and not self.pids():
            macapp.activate(int(win["pid"])); sleep(3)
            x, y = round(win["w"] * self.LAUNCHER_PLAY[0]), round(win["h"] * self.LAUNCHER_PLAY[1])
            for attempt in range(5):
                try: hands.drive(root, self, [f"click {x} {y}"], click="hid", launcher=[int(win["pid"])]); out["launcher"] = "PLAY pressed"; break
                except hands.Refused as e:
                    if e.code not in ("covered", "not_frontmost") or attempt == 4:
                        return {"launcher": "waiting for PLAY (press it in the Paradox Launcher)", "why": e.why}
                    sleep(2)
        end = time.monotonic() + 600
        while time.monotonic() < end and not self.pids(): sleep(3)
        game = self.pids()
        if not game: return {**out, "game": "the game did not start yet (press PLAY in the Paradox Launcher)"}
        quiet.add_pids(root, self, game); out["game"] = f"Cities {game}"
        return out

    def game_dir(self):
        for d in (self._env_dir(self.pin_var), self.steam_dir()):
            if d and self._managed(d): return d
        return None

    @staticmethod
    def _managed(d: Path):
        for m in (d / "Cities.app" / "Contents" / "Resources" / "Data" / "Managed", d / "Cities_Data" / "Managed"):
            if (m / "ICities.dll").is_file(): return m
        return None

    def managed_dir(self):
        """The game's own assemblies (ICities, Assembly-CSharp, UnityEngine): reference them to build a DLL mod; never ship them."""
        gd = self.game_dir(); return self._managed(gd) if gd else None

    def user_dir(self):
        if self.sys == "mac": return self.home / "Library" / "Application Support" / "Colossal Order" / "Cities_Skylines"
        if self.sys == "windows": return Path(self.env.get("LOCALAPPDATA") or self.home / "AppData" / "Local") / "Colossal Order" / "Cities_Skylines"
        return Path(self.env.get("XDG_DATA_HOME") or self.home / ".local" / "share") / "Colossal Order" / "Cities_Skylines"

    def mods_dir(self): return self.user_dir() / "Addons" / "Mods"
    def saves_dir(self): return self.user_dir() / "Saves"
    def cgs_file(self): return self.user_dir() / "userGameState.cgs"
    def extra_files(self): return [self.cgs_file()]

    def log_files(self):
        if self.sys == "mac": return [self.home / "Library" / "Logs" / "Unity" / "Player.log"]
        if self.sys == "windows":
            gd = self.game_dir()
            return ([gd / "Cities_Data" / "output_log.txt"] if gd else []) + \
                   [self.home / "AppData" / "LocalLow" / "Colossal Order" / "Cities_ Skylines" / "Player.log"]
        return [Path(self.env.get("XDG_CONFIG_HOME") or self.home / ".config") / "unity3d" / "Colossal Order" / "Cities_ Skylines" / "Player.log"]

    def compiles_source(self) -> bool:
        """Windows / Linux builds compile Addons/Mods/<Mod>/Source/*.cs at start-up; the macOS build ships no compiler (no Mono/bin,
        no gmcs: 'Cannot find the specified file', seen 2026-10-17), so there a mod must be a prebuilt DLL (`build`)."""
        return self.sys != "mac"

    def loader(self):
        return {"ok": True, "name": "built-in", "detail": "the game compiles Addons/Mods/<Mod>/Source/*.cs itself at start-up" if self.compiles_source()
                else "the game loads Addons/Mods/<Mod>/*.dll (the macOS build cannot compile source: `gameanything native build` first)"}

    def toolchain(self):
        need = not self.compiles_source()
        t = _dotnet_need(8, ("needed on macOS" if need else "optional") + ": builds the mod DLL (net35 against the game's Managed assemblies)", self.env, self.home)
        if not need: t["ok"] = True
        return t

    def build(self, src, name=None) -> dict:
        """Compile <src>/Source/*.cs into <name>.dll against the game's own assemblies and stage a mod folder (the DLL + every
        other file of src except Source/, *.csproj, bin/, obj/) under <data>/native/build/<name>/mod/<name> -> {staged, log}."""
        src = Path(src).expanduser().resolve(); name = name or src.name
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name): raise NativeError(f"mod 名字要能当程序集名（字母、数字、下划线）：{name}")
        man = self.managed_dir()
        if man is None: raise NativeError(f"没有找到 {self.title}")
        dn = dotnet(self.env, self.home)
        if not dn["ok"]: raise NativeError("没有 .NET SDK：" + self.toolchain()["setup"])
        if not list((src / "Source").glob("*.cs")): raise NativeError(f"{src}/Source/ 里没有 .cs 文件")
        from ..worlds.cities_skylines import TEMPLATE
        w = self.build_dir(name)
        if w.exists(): self._trash(w, "old-build")
        shutil.copytree(src / "Source", w / "proj" / "Source")
        csproj = next(src.glob("*.csproj"), TEMPLATE / "Mod.csproj"); shutil.copy2(csproj, w / "proj" / "Mod.csproj")
        env = {**self.env, "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"}
        try: r = subprocess.run([dn["path"], "build", str(w / "proj" / "Mod.csproj"), "-c", "Release", f"-p:Managed={man}", f"-p:AssemblyName={name}",
                                 "-o", str(w / "out"), "-nologo", "-clp:NoSummary"], capture_output=True, text=True, encoding="locale", errors="replace", timeout=600, env=env)
        except (OSError, subprocess.SubprocessError) as e: raise NativeError(f"dotnet build 没有跑起来：{e}")
        (w / "build.log").write_text(r.stdout + r.stderr, encoding="utf-8")
        dll = w / "out" / f"{name}.dll"
        if r.returncode != 0 or not dll.is_file():
            errs = sorted({l.strip() for l in (r.stdout + r.stderr).splitlines() if " error " in l})
            raise NativeError("编译失败：\n" + "\n".join(errs[:20] or [(r.stdout + r.stderr)[-1500:]]) + f"\n（完整日志：{w / 'build.log'}）")
        st = w / "mod" / name; st.mkdir(parents=True); shutil.copy2(dll, st / dll.name)
        for f in src.rglob("*"):
            rel = f.relative_to(src)
            if f.is_file() and rel.parts[0] not in ("Source", "bin", "obj") and f.suffix != ".csproj": _copy(f, st / rel)
        return {"staged": str(st), "dll": str(st / dll.name), "log": str(w / "build.log")}

    def _switch(self, dst: Path, on: bool):
        self._need_closed("改 mod 开关")
        sep = "\\" if self.sys == "windows" else "/"
        return {"switch": cgs.enable(self.cgs_file(), [str(dst)], on=on, sep=sep)[0], "enabled": on}

    def check_installable(self, src):
        if not self.compiles_source() and src.is_dir() and not list(src.glob("*.dll")):
            raise NativeError(f"macOS 版的游戏不能编译源码：先 gameanything native build --game {self.id} {src}，再安装它给出的文件夹")

    def after_install(self, dst): return self._switch(dst, True)
    def after_uninstall(self, dst): return self._switch(dst, False)


# ---------------------------------------------------------------- The Sims 4 (the game's own mod loader: Options.ini switches, .ts4script + .package)
def python37(sys_=None, home=None, env=None):
    """CPython 3.7 (the game's own version; its .pyc must match) -> the argv prefix that runs it, or None. Looks at $GAMEANYTHING_PYTHON37,
    `py -3.7` (Windows launcher), python3.7 on PATH, then pyenv's 3.7.x. Never the current interpreter."""
    sys_ = sys_ or osdirs.system(); home = Path(home) if home else Path.home(); env = dict(os.environ if env is None else env)
    cands = []
    if env.get("GAMEANYTHING_PYTHON37"): cands.append([env["GAMEANYTHING_PYTHON37"]])
    if sys_ == "windows" and shutil.which("py"): cands.append(["py", "-3.7"])
    if shutil.which("python3.7"): cands.append(["python3.7"])
    pyenv = Path(env.get("PYENV_ROOT") or home / ".pyenv") / "versions"
    cands += [[str(p)] for p in sorted(pyenv.glob("3.7.*/bin/python"), reverse=True)]
    for c in cands:
        r = _run([*c, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"])
        if r is not None and r.returncode == 0 and r.stdout.strip() == "3.7": return c
    return None


_S4_COMPILE = r"""
import json, os, py_compile, shutil, sys, tempfile, zipfile
scripts, out = sys.argv[1], sys.argv[2]
tmp = tempfile.mkdtemp(); mods = []
try:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for root, dirs, files in os.walk(scripts):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for f in sorted(files):
                if not f.endswith(".py"): continue
                rel = os.path.relpath(os.path.join(root, f), scripts)
                pyc = os.path.join(tmp, rel + "c"); os.makedirs(os.path.dirname(pyc), exist_ok=True)
                try: py_compile.compile(os.path.join(root, f), cfile=pyc, dfile=rel, doraise=True)
                except py_compile.PyCompileError as e:
                    sys.stdout.write(json.dumps({"error": e.msg})); sys.exit(1)
                z.write(pyc, rel.replace(os.sep, "/") + "c"); mods.append(rel)
finally: shutil.rmtree(tmp, ignore_errors=True)
sys.stdout.write(json.dumps({"modules": mods}))
"""

# the standard Resource.cfg: the game reads .package files up to 5 folders under Mods
_RESOURCE_CFG = ["Priority 500", "PackedFile *.package", *[f"PackedFile {'*/' * n}*.package" for n in range(1, 6)]]


class Sims4(Game):
    id, title, steam_appid, pin_var = "sims4", "The Sims 4", 1222670, "GAMEANYTHING_SIMS4_DIR"
    process_names = (("windows", ("TS4_x64.exe",)), ("mac", ("The Sims 4",)), ("linux", ("TS4_x64.exe",)))   # Linux: under Wine / Proton
    loader_blocks_install = False           # install switches the two Options.ini keys on itself
    _SWITCHES = (("modsdisabled", "0"), ("scriptmodsenabled", "1"))
    _FOLDER = "The Sims 4"

    # ---- folders
    def _docs(self) -> list:
        """Candidate Documents folders. Windows: OneDrive may redirect it (and name it 文档), so every spelling is a candidate."""
        if self.sys == "linux":                                         # a Steam Proton prefix, or the EA app in a plain Wine prefix
            out = []
            for r in steam.roots(self.sys, self.home, self.env):
                for lib in steam.libraries(r):
                    out.append(lib / "steamapps" / "compatdata" / str(self.steam_appid) / "pfx" / "drive_c" / "users" / "steamuser" / "Documents")
            return out + [p / "drive_c" / "users" / self._wine_user() / "Documents" for p in self._wine_prefixes()]
        if self.sys == "mac": return [self.home / "Documents"]
        prof = Path(self.env.get("USERPROFILE") or self.home)
        od = [Path(steam.env_get(self.env, k)) for k in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial") if steam.env_get(self.env, k)] + [prof / "OneDrive"]
        out = []
        for base in [*od, prof]:
            out += [base / n for n in ("Documents", "文档")]
        out.append(self.home / "Documents")
        return [p for i, p in enumerate(out) if p not in out[:i]]

    def _pick(self, ea: Path):
        """The game's folder under <Documents>/Electronic Arts/: other game languages may name it differently, so it is the one
        that holds Options.ini or Mods (preferring 'The Sims 4')."""
        def mark(d): return (d / "Options.ini").is_file() or (d / "Mods").is_dir()
        try: subs = sorted(d for d in ea.iterdir() if d.is_dir())
        except OSError: return None
        std = ea / self._FOLDER
        if std in subs and mark(std): return std
        for d in subs:
            if mark(d): return d
        return std if std in subs else None

    def _wine_prefixes(self) -> list:
        """Linux without Steam: the EA app installed into a Wine prefix ($WINEPREFIX, else Wine's default ~/.wine)."""
        return [self._env_dir("WINEPREFIX") or self.home / ".wine"]

    def _wine_user(self) -> str:
        """Wine names the Windows user after the Linux user."""
        return self.env.get("USER") or self.env.get("LOGNAME") or self.home.name

    def user_dir(self):
        if self._env_dir(self.pin_var): return self._env_dir(self.pin_var)
        docs = self._docs()
        for d in docs:
            if (d / "Electronic Arts").is_dir() and (u := self._pick(d / "Electronic Arts")): return u
        for d in docs:                                                  # not created yet: where it will appear (the Documents that exists)
            if d.is_dir(): return d / "Electronic Arts" / self._FOLDER
        return self.home / "Documents" / "Electronic Arts" / self._FOLDER

    def installed(self): return self.user_dir().is_dir()               # the game creates it at its first start

    def game_dir(self):
        """The install (informational: install needs the user folder): Steam, the EA app's default folder, /Applications."""
        pf = [steam.env_get(self.env, "ProgramFiles"), "C:/Program Files"]
        ea = {"windows": [Path(p) / "EA Games" / self._FOLDER for p in pf if p], "mac": [Path("/Applications/The Sims 4.app")],
              "linux": [p / "drive_c" / "Program Files" / "EA Games" / self._FOLDER for p in self._wine_prefixes()]}.get(self.sys, [])
        for d in [self._env_dir("GAMEANYTHING_SIMS4_GAME_DIR"), self.steam_dir(), *ea]:
            if d and d.is_dir(): return d
        return None

    def mods_dir(self): return self.user_dir() / "Mods"
    def saves_dir(self): return self.user_dir() / "saves"
    def options_file(self): return self.user_dir() / "Options.ini"
    def resource_cfg(self): return self.mods_dir() / "Resource.cfg"
    def extra_files(self): return [f for f in (self.options_file(), self.resource_cfg()) if f.is_file()]

    def log_files(self):
        u = self.user_dir(); out = []
        for pat in ("lastException*.txt", "lastUIException*.txt"):
            fs = [f for f in u.glob(pat) if f.is_file()]
            if fs: out.append(max(fs, key=lambda f: f.stat().st_mtime))
        return out + [f for f in self.mods_dir().glob("*/*.log") if f.is_file()]      # a mod's own log: Mods/<name>/<name>.log

    # macOS: the EA App has no link that starts the game, and opening The Sims 4.app only brings the EA App up (her Mac 2026-10-31).
    # So launch opens the EA App and after_launch clicks the game in its sidebar ("My Mac games"), then the page's PLAY (EA App
    # window 1176x717; these fractions, measured that night). The first start of a copy on a USB drive waits ~20 min for macOS.
    EA_SIDEBAR_GAME, EA_PLAY = (0.10, 0.597), (0.627, 0.778)
    MAC_EA_APP = Path("/Applications/EA app.app")

    def launch_url(self):
        if self.steam_dir(): return super().launch_url()
        if self.sys == "mac" and self.MAC_EA_APP.is_dir(): return str(self.MAC_EA_APP)
        return None                                                     # the EA app has no link that starts the game

    @property
    def launch_needs_game_pid(self): return not (self.sys == "mac" and not self.steam_dir())

    def after_launch(self, root, pids, sleep=None):
        """macOS with the EA App: click The Sims 4 in its sidebar, then PLAY, and record the game's process. Nothing else in the EA App
        (store, account, downloads) is touched. Promos in the game (Esc) and saves are for the caller: never save."""
        if self.sys != "mac" or self.steam_dir(): return None
        import time
        from . import hands, macapp, quiet
        sleep = sleep or time.sleep
        be = hands.backend(); win = None; end = time.monotonic() + 120
        while time.monotonic() < end and not self.pids():
            ws = [w for w in be._list(1 | 16, 0) if w.get("owner") == "EA app" and w.get("layer") == 0 and w.get("w", 0) >= 600]
            if ws: win = ws[0]; break
            sleep(2)
        out = {}
        if win is not None and not self.pids():
            macapp.activate(int(win["pid"])); sleep(6)                  # the EA App draws its pages after a few seconds
            steps = [(self.EA_SIDEBAR_GAME, 3), (self.EA_PLAY, 0)]
            try:
                for (fx, fy), wait in steps:
                    hands.drive(root, self, [f"click {round(win['w'] * fx)} {round(win['h'] * fy)}"], click="hid", launcher=[int(win["pid"])])
                    sleep(wait)
                out["ea_app"] = "PLAY pressed"
            except hands.Refused as e: return {"ea_app": "waiting for PLAY (press it in the EA App)", "why": e.why}
        end = time.monotonic() + 1800                                   # the first start from a USB drive: macOS verifies it first
        while time.monotonic() < end and not self.pids(): sleep(3)
        game = self.pids()
        if not game: return {**out, "game": "the game did not start yet (press PLAY in the EA App)"}
        quiet.add_pids(root, self, game); out["game"] = f"The Sims 4 {game}"
        return out

    # ---- the game's own loader
    def _options(self) -> dict:
        try: raw = self.options_file().read_bytes()
        except OSError: return {}
        return {m.group(1).decode("latin-1").lower(): m.group(2).decode("latin-1").strip()
                for m in re.finditer(rb"^[ \t]*([\w]+)[ \t]*=[ \t]*([^\r\n]*)", raw, re.M)}

    def loader(self):
        o = self._options(); ok = all(o.get(k) == v for k, v in self._SWITCHES)
        how = "gameanything native install 会打开 Options.ini 里的两个开关；或在游戏里：选项 > 其他 > 勾选「启用自定义内容和模组」和「允许脚本模组」"
        return {"ok": ok, "name": "built-in (Options.ini)", "detail": "modsdisabled = 0, scriptmodsenabled = 1" if ok else
                (how if o else "Options.ini 还没有（游戏第一次退出时才写它）：" + how)}

    def set_switches(self) -> dict:
        """Set modsdisabled = 0 and scriptmodsenabled = 1 in Options.ini; every other byte stays (line endings, BOM, order). The game
        rewrites the file when it exits, so it must be closed."""
        self._need_closed("改 Options.ini")
        f = self.options_file()
        try: raw = f.read_bytes()
        except FileNotFoundError: return {"options": "no Options.ini yet: switch 'Enable Custom Content and Mods' and 'Script Mods Allowed' on in the game"}
        nl = b"\r\n" if b"\r\n" in raw else b"\n"; changed = []
        for k, v in self._SWITCHES:
            pat = re.compile(rb"^([ \t]*" + k.encode() + rb"[ \t]*=[ \t]*)([^\r\n]*)", re.M | re.I)
            m = pat.search(raw)
            if m and m.group(2).strip() == v.encode(): continue
            line = k.encode() + b" = " + v.encode()
            if m: raw = raw[:m.start(2)] + v.encode() + raw[m.end(2):]
            elif (h := re.search(rb"^[ \t]*\[options\][ \t]*(\r?\n|$)", raw, re.M | re.I)):
                ins = (b"" if h.group(1) else nl) + line + nl
                raw = raw[:h.end()] + ins + raw[h.end():]
            else: raw += (b"" if not raw or raw.endswith(b"\n") else nl) + b"[options]" + nl + line + nl
            changed.append(k)
        if changed:
            tmp = f.with_name(".Options.ini.m2w-tmp"); tmp.write_bytes(raw); os.replace(tmp, f)
        return {"options": "ok" if not changed else "set " + ", ".join(changed)}

    def ensure_resource_cfg(self) -> bool:
        """Mods/Resource.cfg tells the game how deep to look for .package files; write the standard one when it is missing."""
        f = self.resource_cfg()
        if f.exists(): return False
        nl = "\r\n" if self.sys == "windows" else "\n"
        f.parent.mkdir(parents=True, exist_ok=True); f.write_bytes((nl.join(_RESOURCE_CFG) + nl).encode("ascii")); return True

    # ---- build
    def toolchain(self):
        py = python37(self.sys, self.home, self.env)
        return {"ok": py is not None, "name": "Python 3.7", "detail": ("found: " + " ".join(py)) if py else
                "the game runs Python 3.7: script mods (.ts4script) are compiled with it; a mod with only a package/ builds without",
                "setup": "" if py else "https://www.python.org/downloads/release/python-379/ (the last 3.7 with installers: Windows x86-64, or macOS 64-bit; on "
                         "Apple silicon that Intel build runs under Rosetta, which is enough to compile; 3.7.10+ are source only; Linux: pyenv install 3.7.17)"}

    def build(self, src, name=None) -> dict:
        """<src>/scripts/**/*.py -> <name>.ts4script (a zip of .pyc, compiled by a Python 3.7 subprocess) and <src>/package/ -> <name>.package;
        staged under <data>/native/build/<name>/mod/<name> -> {staged, log, modules, resources}."""
        src = Path(src).expanduser().resolve(); name = name or src.name
        self._check_name(name)
        scripts, pkg = src / "scripts", src / "package"
        pys = [f for f in scripts.rglob("*.py") if "__pycache__" not in f.parts] if scripts.is_dir() else []
        if not pys and not pkg.is_dir(): raise NativeError(f"{src} 里没有 scripts/*.py，也没有 package/ 文件夹：没有可以构建的东西")
        py = python37(self.sys, self.home, self.env) if pys else None
        if pys and py is None:
            raise NativeError("这个 mod 带脚本（scripts/*.py），要用 Python 3.7 编译（游戏自带的就是 3.7，字节码版本必须一致），但这台电脑上没找到：\n"
                              f"  {self.toolchain()['setup']}\n  装好后重试；也可以用 GAMEANYTHING_PYTHON37=<python3.7 的路径> 指定。只有 package/ 的 mod 不需要它。")
        w = self.build_dir(name)
        if w.exists(): self._trash(w, "old-build")
        st = w / "mod" / name; st.mkdir(parents=True); lines = []; mods = []
        if pys:
            try: r = subprocess.run([*py, "-I", "-c", _S4_COMPILE, str(scripts), str(st / f"{name}.ts4script")],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
            except (OSError, subprocess.SubprocessError) as e: raise NativeError(f"Python 3.7 没有跑起来：{e}")
            try: res = json.loads(r.stdout)
            except ValueError: res = {"error": (r.stdout + r.stderr)[-1500:]}
            if r.returncode != 0 or "error" in res:
                (w / "build.log").write_text(r.stdout + r.stderr, encoding="utf-8")
                raise NativeError("脚本编译失败：\n" + str(res.get("error", "")).strip() + f"\n（完整日志：{w / 'build.log'}）")
            mods = res["modules"]; lines.append(f"scripts: {len(mods)} modules -> {name}.ts4script")
        n = 0
        if pkg.is_dir():
            try: n = s4pkg.build_from_dir(pkg, st / f"{name}.package", name=name, log=lines.append)
            except (ValueError, OSError, KeyError) as e: raise NativeError(f"package/ 打包失败：{e}")
            lines.append(f"package: {n} resources -> {name}.package")
        (w / "build.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"staged": str(st), "log": str(w / "build.log"), "modules": len(mods), "resources": n}

    # ---- install
    def check_installable(self, src):
        """Mods/<name>/ holds <name>.ts4script and/or <name>.package. The game reads scripts at most ONE folder deep under Mods and
        packages at most 5 (Resource.cfg); anything deeper is silently ignored, so refuse it here."""
        if not src.is_dir(): raise NativeError(f"要装的是一个文件夹（里面放 .ts4script 和 / 或 .package）：{src}")
        scr = [f for f in src.rglob("*") if f.suffix.lower() == ".ts4script" and f.is_file()]
        pk = [f for f in src.rglob("*") if f.suffix.lower() == ".package" and f.is_file()]
        if not scr and not pk: raise NativeError(f"{src} 里没有 .ts4script 也没有 .package：先 gameanything native build --game sims4 …")
        for f in scr:
            if f.parent != src:
                raise NativeError(f"{f.relative_to(src)}：脚本（.ts4script）在 Mods 下最多只能放一层文件夹，再深游戏就不会加载它；把它放到 {src.name}/ 的最上层")
            if not zipfile.is_zipfile(f): raise NativeError(f"{f.name} 不是 zip（.ts4script 是 .pyc 打成的 zip）：用 gameanything native build 生成")
        for f in pk:
            if len(f.relative_to(src).parts) > 5:           # Mods/<name>/ + 4 more levels = the 5 folders Resource.cfg covers
                raise NativeError(f"{f.relative_to(src)}：.package 在 Mods 下最多只能放 5 层文件夹，再深游戏就不会读它")
        # a script module is imported once by name: another installed .ts4script with the same top-level module shadows the new one
        # (her Mac 2026-10-30: an old Mods/m2w_smoke/ ran instead of the new smoke mod; its log showed the load)
        mods = self.mods_dir(); mine = set().union(*(_ts4_modules(f) for f in scr)) if scr else set()
        if mine and mods.is_dir():
            for f in mods.glob("*/*.ts4script"):
                if f.parent.name == src.name: continue                  # the copy this install replaces
                both = mine & _ts4_modules(f)
                if both:
                    raise NativeError(f"Mods 里的 {f.parent.name}/{f.name} 也有脚本模块 {', '.join(sorted(both))}：游戏只会导入其中一个，"
                                      f"新装的可能不生效。先卸载那个（gameanything native uninstall --game sims4 {f.parent.name}）或给模块换个名字")

    def install(self, src, name=None):
        self._need_closed("安装")                                      # the game rewrites Options.ini when it exits
        return super().install(src, name)

    def after_install(self, dst):
        out = self.set_switches()
        out["resource_cfg"] = "created" if self.ensure_resource_cfg() else "ok"
        return out

    def after_uninstall(self, dst): return {}                           # the switches stay on


def _ts4_modules(f: Path) -> set:
    """The top-level Python modules / packages in a .ts4script (a zip of .pyc / .py)."""
    try:
        with zipfile.ZipFile(f) as z: names = z.namelist()
    except (OSError, zipfile.BadZipFile): return set()
    out = set()
    for n in names:
        top = n.split("/", 1)[0]
        if "/" in n: out.add(top)
        elif top.endswith((".pyc", ".py")): out.add(top.rsplit(".", 1)[0])
    return out


# ---------------------------------------------------------------- shared by the two games below
def _steamapps_of(d: Path):
    """The steamapps folder a game folder lies in (…/steamapps/common/<game>/…), or None."""
    return next((p for p in d.parents if p.name == "steamapps"), None) if d else None


def _newest_mtime_except(paths, skip=()) -> float:
    t = 0.0
    for p in paths:
        if not p.exists(): continue
        fs = [p] if p.is_file() else [*([] if skip else [p]), *p.rglob("*")]     # a skipped file changes its folder's mtime too
        t = max([t] + [f.stat().st_mtime for f in fs if not any(f.name.startswith(s) for s in skip)])
    return t


# ---------------------------------------------------------------- Slay the Spire (ModTheSpire + BaseMod)
# Steam Workshop items (the GitHub releases of ModTheSpire / BaseMod are from 2018 and crash on the current game, 2.3.4)
_STS_WORKSHOP = {"ModTheSpire": (1605060445, "ModTheSpire.jar"), "BaseMod": (1605833019, "BaseMod.jar"), "StSLib": (1609158507, "StSLib.jar")}
_MANIFEST = b"Manifest-Version: 1.0\r\nCreated-By: gameanything\r\n\r\n"


class SlayTheSpire(Game):
    """The game keeps saves/, preferences/ (unlocks, settings) and runs/ (run history) in its own folder; ModTheSpire loads the jars in
    <game>/mods/ plus the subscribed Workshop items. On macOS the game folder is SlayTheSpire.app/Contents/Resources."""
    id, title, steam_appid, pin_var = "slay_the_spire", "Slay the Spire", 646570, "GAMEANYTHING_STS_DIR"
    process_names = (("mac", ("SlayTheSpire",)), ("linux", ("SlayTheSpire",)), ("windows", ("SlayTheSpire.exe",)))
    window_titles = ("Modded Slay the Spire", "Slay the Spire")    # LWJGL 2 sets no _NET_WM_PID: by pid xdotool finds only ModTheSpire's window
    mac_click = "hid"           # her Mac 2026-10-25: CGEventPostToPid clicks did not press buttons (LWJGL); real cursor clicks did
    mac_quit = "signal"         # ModTheSpire's game is a JVM: it exits cleanly on SIGTERM

    def game_dir(self):
        """The folder that holds desktop-1.0.jar (and mods/)."""
        for d in (self._env_dir(self.pin_var), self.steam_dir()):
            if not d: continue
            for x in (d / "SlayTheSpire.app" / "Contents" / "Resources", d / "Contents" / "Resources", d):
                if (x / "desktop-1.0.jar").is_file(): return x
        return None

    def _default_dir(self) -> Path:
        if self.sys == "mac": return self.home / "Library/Application Support/Steam/steamapps/common/SlayTheSpire/SlayTheSpire.app/Contents/Resources"
        if self.sys == "windows": return Path(steam.env_get(self.env, "ProgramFiles(x86)") or "C:/Program Files (x86)") / "Steam" / "steamapps" / "common" / "SlayTheSpire"
        return self.home / ".local/share/Steam/steamapps/common/SlayTheSpire"

    def user_dir(self): return self.game_dir() or self._default_dir()
    def mods_dir(self): return self.user_dir() / "mods"
    def saves_dir(self): return self.user_dir() / "saves"
    def extra_files(self): return [p for p in (self.user_dir() / "preferences", self.user_dir() / "runs") if p.exists()]
    def log_files(self): return [self.user_dir() / "sendToDevs" / "logs" / "SlayTheSpire.log"]      # the game's log4j file; mods log there too
    def launch_url(self): return f"steam://run/{self.steam_appid}"

    def launch_hint(self):
        return ("Steam asks how to start: pick 'Play With Mods' (needs ModTheSpire from the Workshop), then tick the mods in ModTheSpire's "
                "window and press Play. Without that choice: open a terminal in the game folder and run  jre/bin/java -jar ModTheSpire.jar")

    def needs_backup(self) -> bool:
        b = self.backups()                                              # unlocks live in preferences/: they count as saves here
        return not b or _newest_mtime_except([self.saves_dir(), *self.extra_files()]) > b[-1]["mtime"]

    def running(self):
        """The game is a Java program: the app's own launcher (SlayTheSpire / SlayTheSpire.exe), or ModTheSpire's java process
        (macOS / Linux: found by its jar on the command line; on Windows that java process cannot be told apart: unknown)."""
        if super().running(): return True
        if self.sys == "windows" or not shutil.which("pgrep"): return None
        p = _run(["pgrep", "-f", r"(ModTheSpire|mts-launcher|desktop-1\.0)\.jar"])
        if p is None: return None
        for pid in p.stdout.split():                                    # a shell whose command line names the jar is not the game: java only
            c = _run(["ps", "-o", "comm=", "-p", pid])
            if c is not None and "java" in Path(c.stdout.strip()).name.lower(): return True
        return False

    def pids(self):
        base = super().pids()
        if self.sys == "windows" or not shutil.which("pgrep"): return base
        p = _run(["pgrep", "-f", r"(ModTheSpire|mts-launcher|desktop-1\.0)\.jar"])
        if p is None: return base
        out = set(base or [])
        for pid in p.stdout.split():
            c = _run(["ps", "-o", "comm=", "-p", pid])
            if pid.isdigit() and c is not None and "java" in Path(c.stdout.strip()).name.lower(): out.add(int(pid))
        return sorted(out)

    def _jar(self, what):
        """ModTheSpire / BaseMod / StSLib: the copy in the game folder (ModTheSpire.jar next to the game, the others in mods/) or the
        subscribed Workshop item -> Path or None."""
        wid, fn = _STS_WORKSHOP[what]; gd = self.game_dir()
        if gd and (p := gd / fn if what == "ModTheSpire" else gd / "mods" / fn).is_file(): return p
        libs = [s for s in [_steamapps_of(gd)] if s] + [lib / "steamapps" for r in steam.roots(self.sys, self.home, self.env) for lib in steam.libraries(r)]
        for s in libs:
            p = s / "workshop" / "content" / str(self.steam_appid) / str(wid) / fn
            if p.is_file(): return p
        return None

    def loader(self):
        mts, bm = self._jar("ModTheSpire"), self._jar("BaseMod")
        if mts and bm: return {"ok": True, "name": "ModTheSpire + BaseMod", "detail": f"{mts}; {bm}"}
        miss = [n for n, p in (("ModTheSpire", mts), ("BaseMod", bm)) if not p]
        return {"ok": False, "name": "ModTheSpire + BaseMod",
                "detail": f"missing {' and '.join(miss)}: subscribe in the Steam Workshop (ModTheSpire {_STS_WORKSHOP['ModTheSpire'][0]}, BaseMod "
                          f"{_STS_WORKSHOP['BaseMod'][0]}) and let Steam download them, or put ModTheSpire.jar in the game folder and BaseMod.jar in mods/"}

    def _javac(self):
        j = java(self.sys)
        if not j["path"]: return None, j
        jc = Path(j["path"]).with_name("javac.exe" if self.sys == "windows" else "javac")
        return (jc if jc.is_file() else (shutil.which("javac") and Path(shutil.which("javac")))), j

    def toolchain(self):
        jc, j = self._javac(); ok = bool(jc and j["version"] and j["version"] >= 9)
        return {"ok": ok, "name": "JDK 11+ (javac --release 8; the lab uses 25)",
                "detail": f"builds ModTheSpire mods (Java 8 bytecode, like the lab's sts-build; no Gradle / Maven); found: {j['version'] or 'none'}"
                          + ("" if jc or not j["path"] else " (a JRE without javac)"),
                "setup": "" if ok else "https://adoptium.net (or on macOS: brew install --cask temurin)"}

    def build(self, src, name=None) -> dict:
        """The lab's sts-build without bash: <src>/src/**/*.java compiled with javac --release 8 against desktop-1.0.jar, ModTheSpire and
        BaseMod (+ StSLib when found, + <src>/libs/*.jar), then one jar of the classes + ModTheSpire.json + resources/** (+ the libs'
        classes) at <data>/native/build/<name>/<name>.jar (name: the modid) -> {staged, jar, modid, log}."""
        src = Path(src).expanduser().resolve()
        mj = next((p for p in (src / "resources" / "ModTheSpire.json", src / "ModTheSpire.json") if p.is_file()), None)
        if mj is None: raise NativeError(f"{src} 里没有 ModTheSpire.json（放在 resources/ 或最上层）")
        try: modid = json.loads(mj.read_text(encoding="utf-8-sig"))["modid"]
        except (ValueError, KeyError) as e: raise NativeError(f"ModTheSpire.json 读不了或没有 modid：{e}")
        name = name or modid
        if not re.fullmatch(r"[\w.+-]+", name) or name.startswith("."): raise NativeError(f"mod 名字不合适：{name}")
        javas = sorted(p.relative_to(src).as_posix() for p in (src / "src").rglob("*.java")) if (src / "src").is_dir() else []
        if not javas: raise NativeError(f"{src}/src/ 里没有 .java 文件")
        gd = self.game_dir()
        if gd is None: raise NativeError(f"没有找到 {self.title}（或设置 {self.pin_var}）")
        mts, bm, sl = self._jar("ModTheSpire"), self._jar("BaseMod"), self._jar("StSLib")
        if not (mts and bm): raise NativeError("还没装 ModTheSpire + BaseMod：" + self.loader()["detail"])
        jc, _ = self._javac()
        if not self.toolchain()["ok"]: raise NativeError("没有能用的 JDK（要 javac，版本 11 以上）：" + self.toolchain()["setup"])
        libs = sorted((src / "libs").glob("*.jar")) if (src / "libs").is_dir() else []
        cp = [gd / "desktop-1.0.jar", mts, bm, *([sl] if sl else []), *libs]
        w = self.build_dir(name)
        if w.exists(): self._trash(w, "old-build")
        (w / "classes").mkdir(parents=True)
        args = w / "sources.txt"                                         # relative, quoted, forward slashes: spaces and Windows work
        args.write_text("".join(f'"{s}"\n' for s in javas), encoding="utf-8")
        try: r = subprocess.run([str(jc), "--release", "8", "-nowarn", "-encoding", "UTF-8", "-cp", (";" if self.sys == "windows" else ":").join(map(str, cp)),
                                 "-d", str(w / "classes"), f"@{args}"], cwd=str(src), capture_output=True, text=True, encoding="locale", errors="replace", timeout=600)
        except (OSError, subprocess.SubprocessError) as e: raise NativeError(f"javac 没有跑起来：{e}")
        out = r.stdout + r.stderr
        (w / "build.log").write_text(out, encoding="utf-8")
        if r.returncode != 0:
            errs = [l for l in out.splitlines() if ": error:" in l or l.startswith("error:")]
            raise NativeError("编译失败：\n" + "\n".join(errs[:20] or [out[-1500:]]) + f"\n（完整日志：{w / 'build.log'}）")
        files = {}                                                       # arcname -> bytes source; later entries win, as in sts-build
        for f in sorted((w / "classes").rglob("*")):
            if f.is_file(): files[f.relative_to(w / "classes").as_posix()] = f
        files["ModTheSpire.json"] = mj
        if (src / "resources").is_dir():
            for f in sorted((src / "resources").rglob("*")):
                if f.is_file(): files[f.relative_to(src / "resources").as_posix()] = f
        lib_entries = {}
        for l in libs:
            with zipfile.ZipFile(l) as z:
                for n in z.namelist():
                    if not n.endswith("/") and not n.upper().startswith("META-INF/"): lib_entries[n] = (l, n); files.pop(n, None)
        jar = w / f"{name}.jar"
        with zipfile.ZipFile(jar, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("META-INF/MANIFEST.MF", _MANIFEST)
            for n, f in files.items(): z.write(f, n)
            for n, (l, inner) in lib_entries.items():
                with zipfile.ZipFile(l) as lz: z.writestr(n, lz.read(inner))
        return {"staged": str(jar), "jar": str(jar), "modid": modid, "log": str(w / "build.log")}

    def check_installable(self, src):
        if not (src.is_file() and src.suffix.lower() == ".jar"): raise NativeError(f"要装的是一个 .jar（gameanything native build --game {self.id} 生成）：{src}")
        try:
            with zipfile.ZipFile(src) as z: json.loads(z.read("ModTheSpire.json").decode("utf-8-sig"))["modid"]
        except (zipfile.BadZipFile, KeyError, ValueError, OSError):
            raise NativeError(f"{src.name} 里没有带 modid 的 ModTheSpire.json：ModTheSpire 不会加载它")

    def install(self, src, name=None):
        self._need_closed("安装")
        if name and not name.lower().endswith(".jar"): name += ".jar"          # ModTheSpire only reads *.jar in mods/
        return super().install(src, name)

    def uninstall(self, name):
        self._need_closed("卸载")
        if name not in self.mods() and f"{name}.jar" in self.mods(): name += ".jar"
        return super().uninstall(name)


# ---------------------------------------------------------------- BepInEx 5 on a Unity Mono game (Overcooked! 2, Valheim)
_OC2_CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net35</TargetFramework><AssemblyName>{name}</AssemblyName><LangVersion>7.3</LangVersion>
    <NoStdLib>true</NoStdLib><DisableImplicitFrameworkReferences>true</DisableImplicitFrameworkReferences>
    <AppendTargetFrameworkToOutputPath>false</AppendTargetFrameworkToOutputPath><NoWarn>CS1701;CS1702;CS0649;CS0169;CS0414</NoWarn>
  </PropertyGroup>
  <ItemGroup>
{refs}
  </ItemGroup>
</Project>
"""
_OC2_REFS = ["mscorlib", "System", "System.Core", "UnityEngine", "UnityEngine.CoreModule", "UnityEngine.IMGUIModule", "UnityEngine.TextRenderingModule",
             "UnityEngine.PhysicsModule", "UnityEngine.UI", "Assembly-CSharp", "Assembly-CSharp-firstpass"]
# Valheim: the lab's ModLab.csproj (gamebench hosting/modlab/valheim/rt/template/mod): net462 against the game's own Mono class libraries
_VH_CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net462</TargetFramework><AssemblyName>{name}</AssemblyName><LangVersion>9.0</LangVersion>
    <GenerateAssemblyInfo>false</GenerateAssemblyInfo><Nullable>disable</Nullable><AllowUnsafeBlocks>true</AllowUnsafeBlocks>
    <NoStdLib>true</NoStdLib><AutomaticallyUseReferenceAssemblyPackages>false</AutomaticallyUseReferenceAssemblyPackages>
    <FrameworkPathOverride>$(M2wManaged)</FrameworkPathOverride><DisableImplicitFrameworkReferences>true</DisableImplicitFrameworkReferences>
    <ImplicitlyExpandNETStandardFacades>false</ImplicitlyExpandNETStandardFacades><ImplicitlyExpandDesignTimeFacades>false</ImplicitlyExpandDesignTimeFacades>
    <AppendTargetFrameworkToOutputPath>false</AppendTargetFrameworkToOutputPath><NoWarn>CS1701;CS1702;CS0649;CS0169;CS0414;CS0436</NoWarn>
  </PropertyGroup>
  <ItemGroup>
{refs}
  </ItemGroup>
</Project>
"""
_VH_REFS = ["mscorlib", "System", "System.Core", "System.Memory", "netstandard", "UnityEngine", "UnityEngine.CoreModule", "UnityEngine.IMGUIModule",
            "UnityEngine.TextRenderingModule", "UnityEngine.InputLegacyModule", "UnityEngine.PhysicsModule", "UnityEngine.ImageConversionModule",
            "UnityEngine.AudioModule", "UnityEngine.AnimationModule", "UnityEngine.ParticleSystemModule", "UnityEngine.UI", "UnityEngine.UIModule",
            "Unity.TextMeshPro", "assembly_valheim", "assembly_utils", "assembly_guiutils", "gui_framework", "SoftReferenceableAssets"]


class BepInExGame(Game):
    """BepInEx 5 loads the plugin DLLs in <game>/BepInEx/plugins/ (sub-folders too). Windows: winhttp.dll (+ doorstop_config.ini) next to
    the game's .exe; macOS / Linux: a doorstop start script the game must be started through (a Steam launch option). Saves are Unity's
    persistentDataPath (<company>/<product>). Per game: the names below."""
    exe = ""                                # <exe>_Data/Managed on Windows / Linux; the app bundle on macOS is one of `apps`
    apps = ()
    marker = "Assembly-CSharp.dll"          # a file of Managed/ that tells this game's folder
    company = product = ""
    unix_doorstop = ("run_bepinex.sh",)      # macOS / Linux: any one of these start scripts
    loader_name = "BepInEx 5"
    framework, runtime = "net35", "net35"    # what `build` targets / what `check` expects (checks.check_dll)
    csproj, refs = _OC2_CSPROJ, _OC2_REFS
    bridge = ""                             # the lab's own tool plugin: never installed into her game
    lab_paths = r"/home/player|/lab|/work"

    def _managed(self, d: Path):
        for m in [*(d / a / "Contents" / "Resources" / "Data" / "Managed" for a in self.apps), d / f"{self.exe}_Data" / "Managed"]:
            if (m / self.marker).is_file(): return m
        return None

    def game_dir(self):
        """The folder that holds the app (macOS) or <exe>_Data (Windows / Linux), and BepInEx/."""
        for d in (self._env_dir(self.pin_var), self.steam_dir()):
            if not d: continue
            if d.suffix == ".app": d = d.parent                         # pinned to the app bundle itself
            if self._managed(d): return d
        return None

    def managed_dir(self):
        """The game's own assemblies (Assembly-CSharp, UnityEngine): reference them to build a plugin; never ship them."""
        gd = self.game_dir(); return self._managed(gd) if gd else None

    def user_dir(self):
        """Unity's persistentDataPath for this company / product."""
        if self.sys == "windows": return Path(self.env.get("USERPROFILE") or self.home) / "AppData" / "LocalLow" / self.company / self.product
        if self.sys == "mac":
            c = [self.home / "Library/Application Support" / self.company / self.product, self.home / "Library/Application Support" / f"unity.{self.company}.{self.product}"]
            return next((p for p in c if p.is_dir()), c[0])           # older Unity players on macOS used the unity.<company>.<product> name
        return Path(self.env.get("XDG_CONFIG_HOME") or self.home / ".config") / "unity3d" / self.company / self.product

    def bepinex_dir(self): return (self.game_dir() or Path("BepInEx-not-found")) / "BepInEx"
    def mods_dir(self): return self.bepinex_dir() / "plugins"
    def saves_dir(self): return self.user_dir()

    def needs_backup(self) -> bool:
        b = self.backups()                                              # Player.log changes with every start: only the saves decide
        return not b or _newest_mtime_except([self.saves_dir()], skip=("Player",)) > b[-1]["mtime"]

    def log_files(self):
        u = self.user_dir()
        unity = {"mac": [self.home / "Library/Logs/Unity/Player.log", self.home / "Library/Logs" / self.company / self.product / "Player.log"]}.get(self.sys, [u / "Player.log"])
        return [self.bepinex_dir() / "LogOutput.log", *unity]

    def log(self):
        """BepInEx's LogOutput.log first (plugins log there); Unity's Player.log when BepInEx never ran."""
        f = self.bepinex_dir() / "LogOutput.log"
        return f if f.is_file() else super().log()

    def _doorstop(self):
        gd = self.game_dir() or Path("game-not-found")
        if self.sys == "windows": return [gd / "winhttp.dll"]
        return [gd / n for n in self.unix_doorstop]

    def start_script(self):
        """macOS / Linux: the start script that is there (the first of unix_doorstop when none is)."""
        ds = self._doorstop(); return next((p for p in ds if p.is_file()), ds[0])

    def launch_option(self):
        if self.sys == "windows": return None
        s = self.start_script() if self.game_dir() else Path("<game folder>") / self.unix_doorstop[0]
        return f"\"{s}\" %command%"

    def launch_hint(self):
        if self.sys == "windows": return f"BepInEx starts with the game (winhttp.dll next to {self.exe}.exe)"
        s = self.start_script() if self.game_dir() else Path("<game folder>") / self.unix_doorstop[0]
        paste = (f"; PASTE it, do not type it (gameanything native doctor --game {self.id} --copy puts it on the clipboard, then Cmd-V in the box): "
                 "typing can turn the quotes into curly quotes and Steam then cannot start the script") if self.sys == "mac" else ""
        return (f"BepInEx only loads when the game is started through {s.name}: in Steam > {self.title} > Properties > Launch Options put  "
                f"{self.launch_option()}  (once){paste}")

    def _setup(self, kind):
        return f"unpack BepInEx 5 ({kind}, https://github.com/BepInEx/BepInEx/releases, 5.4.x) into {self.game_dir()}"

    def _win_kind(self):
        """Windows: the BepInEx build that matches the game's exe. Overcooked! 2 is a 32-bit game (2026-11-01, a real Windows 11 PC):
        the x64 winhttp.dll is never loaded by it, so BepInEx silently does not start."""
        a = _pe_arch(self.game_dir() / f"{self.exe}.exe") if self.game_dir() else None
        return f"{a} build for Windows (BepInEx_win_{a})" if a else "x64 build for Windows (BepInEx_win_x64; BepInEx_win_x86 for a 32-bit game)"

    def loader(self):
        b = self.bepinex_dir()
        core = (b / "core" / "BepInEx.dll").is_file()
        door = self._doorstop()
        dok = any(p.is_file() for p in door)
        ran = (b / "LogOutput.log").is_file()
        if core and dok and self.sys == "windows":
            ga, da = _pe_arch(self.game_dir() / f"{self.exe}.exe"), _pe_arch(next(p for p in door if p.is_file()))
            if ga and da and ga != da:
                return {"ok": False, "name": self.loader_name,
                        "detail": f"the {da} BepInEx is installed but {self.exe}.exe is {ga}: the game never loads it: " + self._setup(self._win_kind())}
        if core and dok: return {"ok": True, "name": self.loader_name, "detail": "installed" + ("" if ran else " (it has not run yet: no BepInEx/LogOutput.log)")}
        kind = self._win_kind() if self.sys == "windows" else "macOS build (BepInEx_macos_x64 / unix)" if self.sys == "mac" else "Linux build (unix)"
        return {"ok": False, "name": self.loader_name,
                "detail": ("BepInEx/core is there but " + " / ".join(p.name for p in door) + " is missing" if core else "not installed") + ": " + self._setup(kind)}

    def toolchain(self):
        return _dotnet_need(6, f"builds the BepInEx plugin DLL ({self.framework} against the game's Managed assemblies)", self.env, self.home)

    def build(self, src, name=None) -> dict:
        """The lab's build without the install: dotnet build of <src>/*.csproj (or a minimal one when there is none) against this copy's
        Managed/ and BepInEx/core/ (the lab csproj's $(GameDir)/<exe>_Data/Managed hint paths are pointed at the right folder, which on
        macOS is inside the app). Staged under <data>/native/build/<name>/mod/<name>/: the plugin DLL(s) plus every other file of src except
        *.cs, *.csproj, bin/, obj/, NuGet.config; the plugin's .pdb too (ScriptEngine reads symbols) -> {staged, dll, log, warnings}."""
        src = Path(src).expanduser().resolve()
        cs = [f for f in src.rglob("*.cs") if not ({"bin", "obj"} & set(f.relative_to(src).parts))]
        if not cs: raise NativeError(f"{src} 里没有 .cs 文件")
        proj = next(iter(sorted(src.glob("*.csproj"))), None)
        asm = None
        if proj:
            m = re.search(r"<AssemblyName>\s*([^<\s]+)\s*</AssemblyName>", proj.read_text(encoding="utf-8-sig"))
            asm = m.group(1) if m else proj.stem
        name = name or asm or src.name
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", name): raise NativeError(f"mod 名字要能当程序集名（字母、数字、下划线、点）：{name}")
        asm = asm or name
        man = self.managed_dir()
        if man is None: raise NativeError(f"没有找到 {self.title}（或设置 {self.pin_var}）")
        core = self.bepinex_dir() / "core"
        if not (core / "BepInEx.dll").is_file(): raise NativeError(f"还没装 {self.loader_name}：" + self.loader()["detail"])
        dn = dotnet(self.env, self.home)
        if not dn["ok"]: raise NativeError("没有 .NET SDK：" + self.toolchain()["setup"])
        w = self.build_dir(name)
        if w.exists(): self._trash(w, "old-build")
        for f in cs: _copy(f, w / "proj" / f.relative_to(src))
        if proj:
            t = proj.read_text(encoding="utf-8-sig")
            for a, b in ((f"$(GameDir)/{self.exe}_Data/Managed", "$(M2wManaged)"), (f"$(GameDir)\\{self.exe}_Data\\Managed", "$(M2wManaged)"),
                         ("$(GameDir)/BepInEx/core", "$(M2wBepInExCore)"), ("$(GameDir)\\BepInEx\\core", "$(M2wBepInExCore)")): t = t.replace(a, b)
        else:
            refs = [f'    <Reference Include="{r}"><HintPath>$(M2wManaged)/{r}.dll</HintPath><Private>false</Private></Reference>' for r in self.refs if (man / f"{r}.dll").is_file()]
            refs += [f'    <Reference Include="{r}"><HintPath>$(M2wBepInExCore)/{r}.dll</HintPath><Private>false</Private></Reference>' for r in ("BepInEx", "0Harmony")]
            t = self.csproj.format(name=asm, refs="\n".join(refs))
        (w / "proj" / "Mod.csproj").write_text(t, encoding="utf-8")            # the lab's NuGet.config (an offline package folder) is left out
        env = {**self.env, "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"}
        try: r = subprocess.run([dn["path"], "build", str(w / "proj" / "Mod.csproj"), "-c", "Release", f"-p:M2wManaged={man}", f"-p:M2wBepInExCore={core}",
                                 f"-p:GameDir={self.game_dir()}", "-o", str(w / "out"), "-nologo", "-clp:NoSummary"],
                                capture_output=True, text=True, encoding="locale", errors="replace", timeout=600, env=env)
        except (OSError, subprocess.SubprocessError) as e: raise NativeError(f"dotnet build 没有跑起来：{e}")
        (w / "build.log").write_text(r.stdout + r.stderr, encoding="utf-8")
        dll = w / "out" / f"{asm}.dll"
        if r.returncode != 0 or not dll.is_file():
            errs = sorted({l.strip() for l in (r.stdout + r.stderr).splitlines() if " error " in l})
            raise NativeError("编译失败：\n" + "\n".join(errs[:20] or [(r.stdout + r.stderr)[-1500:]]) + f"\n（完整日志：{w / 'build.log'}）")
        theirs = {p.name.lower() for p in [*man.glob("*.dll"), *core.glob("*.dll")]} | ({self.bridge.lower()} if self.bridge else set())
        st = w / "mod" / name; st.mkdir(parents=True)
        for d in sorted((w / "out").glob("*.dll")):
            if d.name.lower() not in theirs:                                # the plugin + its own libraries, never the game's / BepInEx's
                shutil.copy2(d, st / d.name)
                if d.with_suffix(".pdb").is_file(): shutil.copy2(d.with_suffix(".pdb"), st / (d.stem + ".pdb"))   # ScriptEngine (reload) needs it
        for f in src.rglob("*"):
            rel = f.relative_to(src)
            if f.is_file() and rel.parts[0] not in ("bin", "obj") and f.suffix.lower() not in (".cs", ".csproj") and f.name != "NuGet.config": _copy(f, st / rel)
        warn = []
        for f in cs:                                                     # data read from a lab path is not there on this machine
            for m in re.finditer(rf'"((?:{self.lab_paths})/[^"]*)"', f.read_text(encoding="utf-8", errors="replace")):
                warn.append(f"{f.relative_to(src).as_posix()}: 读的是实验室的路径 {m.group(1)}（这台电脑上没有）：改成插件自己的文件夹，"
                            "例如 Path.GetDirectoryName(typeof(Plugin).Assembly.Location)，再把数据文件放进 mod 文件夹")
        return {"staged": str(st), "dll": str(st / dll.name), "log": str(w / "build.log"), "warnings": sorted(set(warn))}

    def check_installable(self, src):
        dlls = [src] if src.is_file() else [f for f in src.rglob("*.dll") if f.is_file()]
        if not dlls or (src.is_file() and src.suffix.lower() != ".dll"):
            raise NativeError(f"{src} 里没有插件 .dll：先 gameanything native build --game {self.id} …")
        if self.bridge and any(f.name == self.bridge for f in dlls): raise NativeError(f"{self.bridge} 是实验室的工具插件，不装到你的游戏里")

    def install(self, src, name=None):
        self._need_closed("安装")
        return super().install(src, name)

    def uninstall(self, name):
        self._need_closed("卸载")
        e = self.mods().get(name); out = super().uninstall(name)
        pdb = Path(e["path"]).with_suffix(".pdb") if e and name.startswith("scripts/") else None
        if pdb and pdb.is_file(): out["pdb_to_trash"] = str(self._trash(pdb, "uninstalled"))   # `reload` put it next to the DLL
        return out


# ---------------------------------------------------------------- Overcooked! 2 (BepInEx 5, Unity 2017.4 Mono)
class Overcooked2(BepInExGame):
    """Saves: Team17/Overcooked2/<steam id>/*.save. Windows: winhttp.dll + doorstop_config.ini next to Overcooked2.exe; macOS / Linux:
    run_bepinex.sh."""
    id, title, steam_appid, pin_var = "overcooked2", "Overcooked! 2", 728880, "GAMEANYTHING_OC2_DIR"
    process_names = (("mac", ("Overcooked2",)), ("linux", ("Overcooked2.x86_64", "Overcooked2.x86")), ("windows", ("Overcooked2.exe",)))
    exe, apps, company, product, bridge = "Overcooked2", ("Overcooked2.app",), "Team17", "Overcooked2", "OC2Bridge.dll"


# ---------------------------------------------------------------- Valheim (BepInExPack_Valheim = BepInEx 5 + Doorstop 4, Unity 6 Mono)
class Valheim(BepInExGame):
    """BepInExPack_Valheim (denikson, Thunderstore; the lab pins 5.4.2351) unpacked into the game folder: BepInEx/, doorstop_libs/,
    doorstop_config.ini, winhttp.dll (Windows) and start_game_bepinex.sh (Linux / macOS; the lab renames it run_bepinex.sh). Saves: Unity's
    persistentDataPath IronGate/Valheim with worlds_local/ + characters_local/ (and the older worlds/ + characters/; Steam-cloud worlds
    live in Steam's userdata and are not touched). Valheim has online play: tests use a local world only, never a public server."""
    id, title, steam_appid, pin_var = "valheim", "Valheim", 892970, "GAMEANYTHING_VALHEIM_DIR"
    process_names = (("mac", ("valheim", "Valheim")), ("linux", ("valheim.x86_64",)), ("windows", ("valheim.exe",)))
    window_titles = ("Valheim",)
    exe, apps, marker, company, product, bridge = "valheim", ("valheim.app", "Valheim.app"), "assembly_valheim.dll", "IronGate", "Valheim", "ValheimBridge.dll"
    unix_doorstop = ("start_game_bepinex.sh", "run_bepinex.sh")
    loader_name = "BepInExPack_Valheim (BepInEx 5)"
    framework, runtime, csproj, refs = "net462", "mono4", _VH_CSPROJ, _VH_REFS
    SAVE_DIRS = ("worlds_local", "characters_local", "worlds", "characters")

    def _setup(self, kind):
        return (f"install BepInExPack_Valheim (denikson, https://thunderstore.io/c/valheim/p/denikson/BepInExPack_Valheim/ , 5.4.2351 like the lab): "
                f"unpack what is inside its BepInExPack_Valheim/ folder into {self.game_dir()}")

    # written into her game folder: the marker and M2W_ROSETTA keep their names from before the rename (a script hooked then is recognised)
    _ROSETTA_HOOK = ("# m2w: the doorstop library is x86_64 only: run the whole script (and the universal game binary it starts) under Rosetta\n"
                     'if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ] && [ -z "$M2W_ROSETTA" ]; then\n'
                     '    M2W_ROSETTA=1 exec arch -x86_64 "$0" "$@"\nfi\n')

    def mac_script(self, write=False):
        """macOS: the BepInExPack start script, made ready (idempotent): executable_name is the .app, and on Apple silicon it re-runs itself
        under Rosetta (the pack's Doorstop is x86_64 only, the game is universal; `write=True`, called by prepare_launch). Steam's launch option does NOT inject on macOS (tested
        2026-10-25: the game starts without BepInEx), so GameAnything runs this script itself. -> the script path, or None when the pack is not there."""
        d = self.game_dir()
        sc = next((d / n for n in self.unix_doorstop if d and (d / n).is_file()), None) if d else None
        if sc is None: return None
        if not write: return sc
        txt = sc.read_text(encoding="utf-8")
        new = re.sub(r'(?m)^executable_name="[^"]*"', 'executable_name="valheim.app"', txt, count=1)
        if "M2W_ROSETTA" not in new:
            i = new.index("\n", new.index("#!")) + 1 if new.startswith("#!") else 0
            new = new[:i] + self._ROSETTA_HOOK + new[i:]
        if new != txt: sc.write_text(new, encoding="utf-8")
        sc.chmod(sc.stat().st_mode | 0o111)
        return sc

    def prepare_launch(self):
        if self.sys == "mac": self.mac_script(write=True)

    def launch_url(self):
        if self.sys == "mac":                                 # run the script directly (see mac_script); Steam must be running for the game's login
            sc = self.mac_script()
            if sc: return "script:" + str(sc)
        return super().launch_url()

    def launch_option(self):
        return None if self.sys == "mac" else super().launch_option()    # macOS: GameAnything runs the start script itself (no launch option)

    def launch_hint(self):
        local = ("  Test in a LOCAL world (Start Game > your world, 'Start server' off); never join a public or community server with a test mod. "
                 "New characters / worlds are Steam Cloud saves by default and GameAnything backs up only local ones: use local saves for tests "
                 "(Manage saves > Move to local).")
        if self.sys == "mac":
            return ("macOS: GameAnything starts the game by running BepInExPack's start_game_bepinex.sh itself (it makes the script ready: the game .app as "
                    "executable_name, and a Rosetta re-run on Apple silicon). No Steam launch option: on macOS Steam's launch option starts the game "
                    "without BepInEx. Steam has to be running." + local)
        return super().launch_hint() + "." + local

    def save_dirs(self) -> list:
        """The world and character folders that exist (what `backup` is about; the whole persistentDataPath folder is copied)."""
        return [self.user_dir() / n for n in self.SAVE_DIRS if (self.user_dir() / n).is_dir()]

    def info(self):
        d = super().info(); d["save_dirs"] = [str(p) for p in self.save_dirs()]; return d


# ---------------------------------------------------------------- a game described by its game.yaml alone (games/<id>/game.yaml)
class DeclarativeGame(Game):
    """A game whose folders, saves, logs, process names and launch come from its game.yaml (gameanything/games/, the registry). A game
    package's adapter.py subclasses this to add code hooks (build, check_installable, after_install, check_mod, ...). Paths are strings
    with placeholders, one string, a list of candidates (the first that exists wins, else the first), or a per-system map of those:

        {home} {documents} (Windows: the real Documents, OneDrive too) {appdata} {localappdata} {xdg_data} {xdg_config}
        {game} (the install: folders.game) {user} (folders.user) {mods} (folders.mods)
    """
    spec = None

    @classmethod
    def apply_spec(cls, spec):
        """Copy the identity fields of game.yaml onto the class (what Game reads as class attributes)."""
        cls.spec = spec
        cls.id, cls.title = spec["id"], spec["title"]
        cls.steam_appid = spec.get("steam_appid")
        cls.pin_var = spec.get("pin_var") or f"GAMEANYTHING_{spec['id'].upper()}_DIR"
        pn = spec.get("process_names") or {}
        cls.process_names = tuple((s, tuple(pn.get(s) or ())) for s in ("mac", "linux", "windows") if pn.get(s))
        cls.window_titles = tuple(spec.get("window_titles") or ())
        for k in ("mac_click", "mac_keys", "mac_quit"):
            if spec.get(k) in ("pid", "hid", "app", "signal"): setattr(cls, k, spec[k])
        return cls

    def _s(self, *keys, default=None):
        v = self.spec or {}
        for k in keys: v = v.get(k) if isinstance(v, dict) else None
        return default if v is None else v

    def _documents(self) -> Path:
        if self.sys != "windows": return self.home / "Documents"
        prof = Path(self.env.get("USERPROFILE") or self.home)
        cands = [Path(steam.env_get(self.env, k)) / "Documents" for k in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial") if steam.env_get(self.env, k)]
        cands += [prof / "Documents", prof / "文档", self.home / "Documents"]
        return next((c for c in cands if c.is_dir()), prof / "Documents")

    def _vars(self, skip=()) -> dict:
        h = self.home
        v = {"home": str(h), "documents": str(self._documents()),
             "appdata": self.env.get("APPDATA") or str(h / "AppData" / "Roaming"),
             "localappdata": self.env.get("LOCALAPPDATA") or str(h / "AppData" / "Local"),
             "xdg_data": self.env.get("XDG_DATA_HOME") or str(h / ".local" / "share"),
             "xdg_config": self.env.get("XDG_CONFIG_HOME") or str(h / ".config")}
        if "game" not in skip: v["game"] = str(self.game_dir() or Path("game-not-found"))
        if "user" not in skip: v["user"] = str(self.user_dir())
        if "mods" not in skip and "user" not in skip: v["mods"] = str(self.mods_dir())
        return v

    def _cands(self, val, skip=()) -> list:
        """A path value of game.yaml -> its candidate Paths on this system ([] when it has none here)."""
        if isinstance(val, dict): val = val.get(self.sys)
        if val is None: return []
        vals = [val] if isinstance(val, str) else list(val)
        vs = self._vars(skip); out = []
        for x in vals:
            try: out.append(Path(str(x).format(**vs)).expanduser())
            except (KeyError, IndexError, ValueError): pass
        return out

    def _pick(self, val, skip=()):
        c = self._cands(val, skip)
        return next((p for p in c if p.exists()), c[0] if c else None)

    def game_dir(self):
        g = self._s("folders", "game", default={})
        if isinstance(g, (str, list)): g = {"windows": g, "mac": g, "linux": g}
        markers = g.get("marker") or []
        if isinstance(markers, dict): markers = markers.get(self.sys) or []        # per system: the installs share no file (Civ VI)
        markers = [markers] if isinstance(markers, str) else list(markers)
        appid = g.get("steam_appid", self.steam_appid)
        steam_d = steam.app_dir(appid, self.sys, self.home, self.env) if appid else None
        for d in [self._env_dir(self.pin_var), steam_d, *self._cands(g, skip=("game", "user", "mods"))]:
            if not d: continue
            for x in (d, *(d / sub for sub in (g.get("subdirs") or ()))):
                if (all((x / m).exists() for m in markers) if markers else x.is_dir()): return x
        return None

    def user_dir(self):
        u = self._s("folders", "user")
        if u is None: return self.game_dir() or Path("game-not-found")
        return self._pick(u, skip=("user", "mods")) or Path("user-folder-unknown")

    def installed(self) -> bool:
        need = self._s("installed_when", default="game")
        return self.user_dir().is_dir() if need == "user" else self.game_dir() is not None

    def mods_dir(self):
        return self._pick(self._s("folders", "mods", default="{user}/Mods"), skip=("mods",))

    def _saves(self) -> list:
        out = []
        for v in self._s("saves", default=[]) or []:
            p = self._pick(v)
            if p: out.append(p)
        return out

    def saves_dir(self):
        s = self._saves(); return s[0] if s else self.user_dir() / "saves"

    def extra_files(self):
        out = self._saves()[1:]
        for v in self._s("extra_files", default=[]) or []:
            p = self._pick(v)
            if p: out.append(p)
        return out

    def needs_backup(self) -> bool:
        b = self.backups()                      # every save folder counts (the extra files change with every install)
        return not b or _newest_mtime_except(self._saves()) > b[-1]["mtime"]

    def log_files(self):
        out = []
        for v in self._s("logs", default=[]) or []: out += self._cands(v)
        return out

    def loader(self):
        lo = self._s("loader", default={}) or {}
        need = [p for v in (lo.get("check") or []) for p in self._cands(v)[:1]]
        miss = [p for p in need if not p.exists()]
        return {"ok": not miss, "name": lo.get("name") or "", "detail": "installed" if not miss else
                (lo.get("fix_en") or lo.get("fix") or "install the mod loader") + f" (missing: {', '.join(str(p) for p in miss)})"}

    def toolchain(self):
        t = self._s("toolchain", default={}) or {}
        kind = t.get("kind")
        if kind == "dotnet": return _dotnet_need(int(t.get("major") or 6), t.get("purpose") or "builds the mod", self.env, self.home)
        if kind == "java":
            j = java(self.sys); need = int(t.get("major") or 8); ok = bool(j["ok"] and j["version"] >= need)
            return {"ok": ok, "name": f"JDK {need}+", "detail": f"{t.get('purpose') or 'builds the mod'}; found: {j['version'] or 'none'}",
                    "setup": "" if ok else "https://adoptium.net"}
        return {"ok": True, "name": t.get("name") or "", "detail": t.get("purpose") or "", "setup": ""}

    def launch_url(self):
        u = self._s("launch", "url")
        return u if u else super().launch_url()

    def launch_hint(self): return self._s("launch", "hint", default="") or ""
    def launch_option(self): return self._s("launch", "option")


def declarative(spec):
    """A DeclarativeGame subclass for one game.yaml without an adapter."""
    return type(f"Declarative_{spec['id']}", (DeclarativeGame,), {}).apply_spec(spec)


# the games: the registry (gameanything/games/: built-in game packages + plugins of the `gameanything.games` entry point group)
from .. import games as _registry  # noqa: E402
GAMES = _registry.native_classes()


def get(game: str, **kw) -> Game:
    if game not in GAMES: raise NativeError(f"不支持的游戏：{game}（可选：{', '.join(GAMES)}）")
    return GAMES[game](**kw)
