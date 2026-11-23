"""Terraria with tModLoader: the code hooks of the terraria game package (game.yaml has the folders, saves, logs and launch).

tModLoader is its own free Steam app (1281930) next to Terraria (105600, which must be owned and installed: tModLoader reads its Content).
Its user folder (game.yaml folders.user) holds Mods/ (<Name>.tmod files + enabled.json, the list of enabled mods), ModSources/,
Players/ and Worlds/ (local saves; Steam Cloud saves live in Steam's userdata/<id>/1281930/remote and are not touched). The install
folder holds tModLoader.dll, tMLMod.targets (what a mod's .csproj imports) and tModLoader-Logs/ (client.log).

    build(src)          a mod source folder (build.txt + *.cs [+ <Name>.csproj]) -> <Name>.tmod. tModLoader 2022.x+ builds like this:
                        `dotnet build` of the mod's .csproj, which imports ModSources/tModLoader.targets -> <install>/tMLMod.targets;
                        that compiles the DLL with the .NET SDK, then its BuildMod target runs `dotnet tModLoader.dll -server -build
                        <dir> -eac <dll>` (tModLoader's own packer) which writes <save folder>/Mods/<Name>.tmod and enables it. GameAnything
                        builds in its own folder and passes `-tmlsavedirectory <gameanything build folder>` (ExtraBuildModFlags), so the .tmod
                        lands there, NOT in her Mods folder: `install` copies it in (saves backed up first) and enables it.
    check_installable   a .tmod whose header reads (magic, name = file name)
    after_install / after_uninstall   enabled.json gets / loses the mod's name (the game rewrites the file: it must be closed)
    check_mod(src, it)  `gameanything native check`: the .tmod's header, hash, Info and <Name>.dll, the DLL's references against
                        tModLoader.dll + its Libraries/ (names of assemblies, types and members), the tModLoader version it was built with
    running() / pids()  tModLoader runs as `dotnet tModLoader.dll` (the bundled dotnet in <install>/dotnet/ or a system one): found by
                        that command line (Linux: /proc, its working folder must be this install; macOS: ps; Windows: PowerShell's
                        Win32_Process command lines, untested)
Hot reload: none GameAnything can do (see game.yaml reload.none): tModLoader reloads mods only from its own menu (Workshop > Develop Mods >
Build + Reload, or Mods > Reload), a click in her game.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

from gameanything.native import steam
from gameanything.native.games import DeclarativeGame, NativeError, _run, dotnet

from . import tmod

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")          # a tModLoader mod name (the folder, the assembly, the .tmod)
_CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <!-- tModLoader mod project: ..\\tModLoader.targets is the file tModLoader writes into ModSources/ (GameAnything writes its own when building) -->
  <Import Project="..\\tModLoader.targets" />
  <PropertyGroup>
    <AssemblyName>{name}</AssemblyName>
  </PropertyGroup>
</Project>
"""
_TARGETS = """<Project ToolsVersion="14.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <!-- written by gameanything native build: tModLoader's packer writes the .tmod into this build folder, not into her Mods folder -->
  <PropertyGroup>
    <ExtraBuildModFlags>-tmlsavedirectory &quot;{save}&quot;</ExtraBuildModFlags>
  </PropertyGroup>
  <Import Project="{targets}" />
</Project>
"""


class Terraria(DeclarativeGame):
    TERRARIA_APPID = 105600

    # ---- folders
    def terraria_dir(self):
        """Terraria itself (tModLoader loads its Content/): $GAMEANYTHING_TERRARIA_GAME_DIR, else its Steam folder."""
        for d in (self._env_dir("GAMEANYTHING_TERRARIA_GAME_DIR"), steam.app_dir(self.TERRARIA_APPID, self.sys, self.home, self.env)):
            if not d: continue
            for x in (d, d / "Terraria.app" / "Contents" / "Resources", d / "Terraria.app" / "Contents" / "MacOS"):
                if (x / "Content").is_dir(): return x
        return None

    def user_dir(self):
        """$GAMEANYTHING_TERRARIA_USER_DIR (the sandbox image sets it to /sandbox/saves, the folder ga-terraria starts tModLoader with as
        -tmlsavedirectory: else `native build --install` put the mod in ~/.local/share/... and the game never saw it), else game.yaml's."""
        return self._env_dir("GAMEANYTHING_TERRARIA_USER_DIR") or super().user_dir()

    def enabled_file(self) -> Path: return self.mods_dir() / "enabled.json"
    def save_dirs(self) -> list: return [p for p in self._saves() if p.is_dir()]

    def info(self):
        d = super().info(); td = self.terraria_dir()
        d["terraria_dir"] = str(td) if td else None
        d["save_dirs"] = [str(p) for p in self.save_dirs()]
        d["enabled_mods"] = self.enabled() if self.installed() else []
        return d

    # ---- loader and toolchain
    def loader(self):
        gd, td = self.game_dir(), self.terraria_dir()
        if gd and td: return {"ok": True, "name": "tModLoader", "detail": f"{gd} (Terraria: {td})"}
        miss = [n for n, p in (("tModLoader (free Steam app 1281930)", gd), ("Terraria (Steam app 105600, tModLoader needs it installed)", td)) if not p]
        return {"ok": False, "name": "tModLoader", "detail": "missing " + " and ".join(miss) + ": install it in Steam (never a copy from elsewhere)"}

    def _runtimes(self, exe) -> list:
        r = _run([exe, "--list-runtimes"])
        return [l.split()[1] for l in (r.stdout.splitlines() if r and r.returncode == 0 else []) if l.startswith("Microsoft.NETCore.App ")]

    def toolchain(self):
        """The .NET SDK (8+) compiles the mod; tModLoader's packer (tModLoader.dll, net8.0) runs on the same dotnet, so a .NET 8 runtime
        must be there too (an 8.x SDK brings it)."""
        d = dotnet(self.env, self.home)
        sdk_ok = any(s.split(".")[0].isdigit() and int(s.split(".")[0]) >= 8 for s in d["sdks"])
        rt = self._runtimes(d["path"]) if d["path"] else []
        rt_ok = any(v.startswith("8.") for v in rt) or any(s.startswith("8.") for s in d["sdks"])
        ok = sdk_ok and rt_ok
        return {"ok": ok, "name": ".NET SDK 8 (+ the .NET 8 runtime)", "detail": f"builds tModLoader mods (net8.0) and runs tModLoader's packer; found SDKs: "
                f"{', '.join(d['sdks']) or 'none'}; runtimes: {', '.join(rt) or 'none'}",
                "setup": "" if ok else "https://dotnet.microsoft.com/download/dotnet/8.0 (or on macOS: brew install --cask dotnet-sdk@8)"}

    # ---- is it running (dotnet tModLoader.dll)
    def _procs(self):
        """[(pid, argv)] of tModLoader client processes on this system, or None when it cannot tell."""
        out = []
        if self.sys == "linux":
            try: pids = [p for p in os.listdir("/proc") if p.isdigit()]
            except OSError: return None
            for p in pids:
                try:
                    argv = Path(f"/proc/{p}/cmdline").read_bytes().split(b"\0")
                    if Path(f"/proc/{p}/stat").read_text(encoding="utf-8", errors="replace").rpartition(")")[2].split()[0] == "Z": continue
                except (OSError, IndexError): continue
                argv = [os.fsdecode(a) for a in argv if a]
                if self._is_client(argv): out.append((int(p), argv))
            return out
        if self.sys == "mac":
            r = _run(["ps", "-Aww", "-o", "pid=,command="])
            if r is None or r.returncode != 0: return None
            for l in r.stdout.splitlines():
                pid, _, cmd = l.strip().partition(" ")
                if pid.isdigit() and self._is_client(cmd.split()): out.append((int(pid), cmd.split()))
            return out
        if self.sys == "windows":
            ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*tModLoader*' } | "
                  "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }")
            r = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=30)
            if r is None or r.returncode != 0: return None
            for l in r.stdout.splitlines():
                pid, _, cmd = l.strip().partition("\t")
                args = re.findall(r'"[^"]*"|\S+', cmd); args = [a.strip('"') for a in args]
                if pid.isdigit() and (self._is_client(args) or (args and Path(args[0]).name.lower() == "tmodloader.exe")): out.append((int(pid), args))
            return out
        return None

    @staticmethod
    def _is_client(argv) -> bool:
        if not argv or "-build" in argv or "-server" in argv: return False          # GameAnything's own build (the packer) is not the game
        exe = Path(argv[0]).name.lower()
        return exe.startswith("dotnet") and any(Path(a).name.lower() == "tmodloader.dll" for a in argv[1:3])

    def _this_install(self, pid, argv) -> bool:
        """Linux: the tModLoader.dll it runs is this install's (relative to its working folder). Unknown counts as this one."""
        gd = self.game_dir()
        if self.sys != "linux" or gd is None: return True
        dll = next((a for a in argv[1:3] if Path(a).name.lower() == "tmodloader.dll"), None)
        try:
            base = Path(os.readlink(f"/proc/{pid}/cwd"))
            return (base / dll).resolve().parent == gd.resolve()
        except (OSError, TypeError): return True

    def running(self):
        ps = self._procs()
        if ps is None: return None
        return any(self._this_install(p, a) for p, a in ps)

    def pids(self):
        ps = self._procs()
        if ps is None: return None
        return sorted(p for p, a in ps if self._this_install(p, a))

    # ---- enabled.json
    def enabled(self) -> list:
        try: v = json.loads(self.enabled_file().read_text(encoding="utf-8-sig"))
        except (OSError, ValueError): return []
        return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []

    def _set_enabled(self, mod: str, on: bool) -> dict:
        self._need_closed("改 enabled.json")
        f = self.enabled_file(); cur = self.enabled()
        new = (cur if mod in cur else cur + [mod]) if on else [m for m in cur if m != mod]
        if new != cur or not f.exists():
            f.parent.mkdir(parents=True, exist_ok=True); tmp = f.with_name(".enabled.json.m2w-tmp")
            tmp.write_text(json.dumps(new, indent=2), encoding="utf-8"); os.replace(tmp, f)
        return {"enabled": on, "switch": f"{mod} {'in' if on else 'out of'} enabled.json"}

    # ---- build
    def build(self, src, name=None) -> dict:
        src = Path(src).expanduser().resolve()
        if not src.is_dir(): raise NativeError(f"找不到 mod 文件夹：{src}")
        if not (src / "build.txt").is_file(): raise NativeError(f"{src} 里没有 build.txt：tModLoader 的 mod 要有它（displayName、author、version）")
        cs = [f for f in src.rglob("*.cs") if not ({"bin", "obj"} & set(f.relative_to(src).parts))]
        if not cs: raise NativeError(f"{src} 里没有 .cs 文件")
        projs = sorted(src.glob("*.csproj"))
        if len(projs) > 1: raise NativeError(f"{src} 里有好几个 .csproj（{', '.join(p.name for p in projs)}）：只留一个")
        asm = None
        if projs:
            t = projs[0].read_text(encoding="utf-8-sig", errors="replace")
            if "tModLoader.targets" not in t and "tMLMod.targets" not in t:
                raise NativeError(f"{projs[0].name} 没有导入 tModLoader 的构建文件：第一行之后加 <Import Project=\"..\\tModLoader.targets\" />，或删掉 .csproj 让 GameAnything 生成一个")
            m = re.search(r"<AssemblyName>\s*([^<\s]+)\s*</AssemblyName>", t); asm = m.group(1) if m else projs[0].stem
        name = name or asm or src.name
        if not NAME_RE.match(name): raise NativeError(f"tModLoader 的 mod 名字要是字母开头的字母、数字、下划线：{name}")
        if asm and asm != name: raise NativeError(f".csproj 的程序集名是 {asm}，mod 名字是 {name}：tModLoader 要求它们一样")
        gd = self.game_dir()
        if gd is None: raise NativeError(f"没有找到 tModLoader（Steam 里免费的 tModLoader，app 1281930；或设置 {self.pin_var}）")
        targets = gd / "tMLMod.targets"
        if not targets.is_file(): raise NativeError(f"{gd} 里没有 tMLMod.targets：tModLoader 太旧（要 2022.x 以后的版本）或没装完整")
        dn = dotnet(self.env, self.home)
        if not dn["ok"] or not self.toolchain()["ok"]: raise NativeError("没有能用的 .NET：" + self.toolchain()["detail"] + "\n  " + self.toolchain()["setup"])
        w = self.build_dir(name)
        if " " in str(w):                  # tMLMod.targets passes $(ProjectDir) to the packer unquoted: a space would split it
            w = Path(tempfile.gettempdir()) / "m2w-tmod-build" / name
            if " " in str(w): raise NativeError(f"构建文件夹的路径里有空格（{w}）：tModLoader 的打包器处理不了，设置 TMPDIR / TEMP 到一个没有空格的文件夹")
        if w.exists(): self._trash(w, "old-build")
        proj = w / "ModSources" / name
        shutil.copytree(src, proj, ignore=lambda d, fs: [f for f in fs if f in ("bin", "obj") and Path(d) == src])
        pf = proj / (projs[0].name if projs else f"{name}.csproj")
        if projs and projs[0].name != f"{name}.csproj": pf = pf.rename(proj / f"{name}.csproj")
        if not projs: pf.write_text(_CSPROJ.format(name=name), encoding="utf-8")
        save = w / "save"; save.mkdir(parents=True)
        (w / "ModSources" / "tModLoader.targets").write_text(_TARGETS.format(save=escape(str(save)), targets=escape(str(targets))), encoding="utf-8")
        env = {**self.env, "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1",       # the packer step runs plain `dotnet`: this one first
               "PATH": str(Path(dn["path"]).parent) + os.pathsep + self.env.get("PATH", os.environ.get("PATH", ""))}
        try: r = subprocess.run([dn["path"], "build", str(pf), "-c", "Release", "-nologo", "-clp:NoSummary"], cwd=str(proj),
                                capture_output=True, text=True, encoding="locale", errors="replace", timeout=900, env=env)
        except (OSError, subprocess.SubprocessError) as e: raise NativeError(f"dotnet build 没有跑起来：{e}")
        (w / "build.log").write_text(r.stdout + r.stderr, encoding="utf-8")
        built = save / "Mods" / f"{name}.tmod"
        if r.returncode != 0 or not built.is_file():
            errs = sorted({l.strip() for l in (r.stdout + r.stderr).splitlines() if " error " in l})
            raise NativeError("编译失败：\n" + "\n".join(errs[:20] or [(r.stdout + r.stderr)[-1500:]]) + f"\n（完整日志：{w / 'build.log'}）")
        st = w / "mod"; st.mkdir(); out = st / f"{name}.tmod"; shutil.copy2(built, out)
        return {"staged": str(out), "tmod": str(out), "log": str(w / "build.log"), "warnings": []}

    # ---- install
    def _tmod_name(self, name: str) -> str:
        return name if name.lower().endswith(".tmod") else f"{name}.tmod"

    def check_installable(self, src):
        if not (src.is_file() and src.suffix.lower() == ".tmod"): raise NativeError(f"要装的是一个 .tmod（gameanything native build --game {self.id} 生成）：{src}")
        try: i = tmod.read(src)
        except (tmod.BadTmod, OSError, UnicodeDecodeError) as e: raise NativeError(f"{src.name} 不是有效的 .tmod：{e}")
        if i["name"] != src.stem: raise NativeError(f"{src.name} 里的 mod 名字是 {i['name']}：tModLoader 要求文件名就是 mod 名字（{i['name']}.tmod）")

    def install(self, src, name=None):
        self._need_closed("安装")
        src = Path(src).expanduser()
        return super().install(src, self._tmod_name(name or src.stem))

    def after_install(self, dst): return self._set_enabled(Path(dst).stem, True)

    def uninstall(self, name):
        self._need_closed("卸载")
        return super().uninstall(name if name in self.mods() else self._tmod_name(name))

    def after_uninstall(self, dst): return self._set_enabled(Path(dst).stem, False)

    # ---- headless check (native/checks.py calls it)
    _TML_INFO = re.compile(rb"\d+\.\d+\.\d+(?:\.\d+)?\+(\d{4}\.\d{1,2}\.\d+(?:\.\d+)?)\|")

    def tml_version(self):
        """tModLoader's own version (2026.8.3.0), as the packer writes it into a .tmod. tModLoader.dll's AssemblyVersion is Terraria's
        (1.4.4.9); its AssemblyInformationalVersion is "<Terraria>+<tModLoader>|<branch>|stable|<commit>|..." (seen in 2026.08.3.0)."""
        gd = self.game_dir()
        if not gd: return None
        try: m = self._TML_INFO.search((gd / "tModLoader.dll").read_bytes())
        except OSError: return None
        return ".".join(str(int(x)) for x in m.group(1).decode().split(".")) if m else None

    def check_mod(self, src: Path, it: dict):
        from gameanything.native import checks
        src = Path(src)
        if src.is_dir():
            ts = sorted(src.glob("*.tmod"))
            if len(ts) != 1: it["errors"].append(f"{src} 里要正好有一个 .tmod"); return
            src = ts[0]
        try: self.check_installable(src)
        except NativeError as e: it["errors"].append(str(e)); return
        i = tmod.read(src)
        if not i["hash_ok"]: it["errors"].append(f"{src.name} 的校验和不对：文件坏了，重新构建")
        dll = f"{i['name']}.dll"
        for need in ("Info", dll):
            if need not in i["files"]: it["errors"].append(f"{src.name} 里没有 {need}：不是 tModLoader 打包出来的")
        it["notes"].append(f"{i['name']} {i['version']}，用 tModLoader {i['tml_version']} 打包，{len(i['files'])} 个文件")
        have = self.tml_version()
        try:
            if have and tuple(map(int, have.split(".")[:3])) < tuple(map(int, i["tml_version"].split(".")[:3])):
                it["warnings"].append(f"这个 mod 是用 tModLoader {i['tml_version']} 打包的，她装的是 {have}：游戏可能拒绝加载，先在 Steam 里更新 tModLoader")
        except ValueError: pass
        gd = self.game_dir()
        if gd is None or dll not in i["files"]: return
        dirs = [gd] + sorted({p.parent for p in (gd / "Libraries").rglob("*.dll")
                             if not ({"Native", "tModCodeAssist"} & set(p.parts)) and not any(x.startswith("runtime") for x in p.relative_to(gd).parts)}) \
            if (gd / "Libraries").is_dir() else [gd]
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / dll; f.write_bytes(tmod.read_file(src, i, dll))
            checks.check_dll(f, checks._Index(dirs), {i["name"].lower()}, it, None)
