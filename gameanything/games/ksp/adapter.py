"""Kerbal Space Program (KSP 1): the code hooks of the ksp game package (game.yaml has the folders, saves, logs and launch).

KSP is a Unity 2019.4 Mono game that loads plugins itself: at start-up its AssemblyLoader loads every DLL under GameData/ (by
convention GameData/<Mod>/Plugins/<Mod>.dll) and its AddonLoader starts each MonoBehaviour marked [KSPAddon(startup, once)]. Saves
(saves/<profile>/), settings.cfg and KSP.log are in the game folder itself. The game's own assemblies are in
    Linux   KSP_Data/Managed            Windows  KSP_x64_Data/Managed            macOS  KSP.app/Contents/Resources/Data/Managed

    build(src, name)    *.cs (+ an optional *.csproj: its AssemblyName and <Reference Include> names) -> a net472 DLL compiled against
                        that Managed/ folder (NoStdLib + FrameworkPathOverride: the game's own Mono class libraries, so no NuGet
                        reference packs and no network), staged as <data>/native/build/<name>/mod/<name>/Plugins/<name>.dll plus every
                        non-source file of src (part .cfg files, textures) at its relative path. Never written into GameData.
    check_installable   a mod folder with a DLL or a .cfg in it, never the game's own Squad / SquadExpansion
    install / uninstall the game must be closed (it reads GameData only at start-up); GameData/<name>/
    check_mod(src, it)  `gameanything native check`: every DLL's references against Managed/ (+ other mods' Plugins/ DLLs), Mono 4.x rules, and
                        whether it uses KSPAddon (else the game loads the DLL but starts nothing)
Hot reload: none (game.yaml reload.none): KSP loads plugins only at start-up.
"""
import re
import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

from gameanything.native.games import DeclarativeGame, NativeError, _copy, dotnet

NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,63}$")
GAME_OWN = {"squad", "squadexpansion"}                      # the game's own GameData folders (the base game, the DLCs)
ENTRY_TYPES = {"KSPAddon", "PartModule", "ScenarioModule", "VesselModule"}     # what makes the game start code from a plugin DLL
REFS = ["mscorlib", "System", "System.Core", "System.Xml", "UnityEngine", "UnityEngine.CoreModule", "UnityEngine.IMGUIModule",
        "UnityEngine.TextRenderingModule", "UnityEngine.InputLegacyModule", "UnityEngine.PhysicsModule", "UnityEngine.AnimationModule",
        "UnityEngine.AudioModule", "UnityEngine.ImageConversionModule", "UnityEngine.UI", "UnityEngine.UIModule",
        "Assembly-CSharp", "Assembly-CSharp-firstpass", "KSPAssets"]
_CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <!-- written by gameanything native build: a KSP plugin compiled against the game's own Managed/ assemblies (never shipped with the mod) -->
  <PropertyGroup>
    <TargetFramework>net472</TargetFramework><AssemblyName>{name}</AssemblyName><LangVersion>9.0</LangVersion>
    <Nullable>disable</Nullable><GenerateAssemblyInfo>true</GenerateAssemblyInfo><Version>1.0.0</Version>
    <NoStdLib>true</NoStdLib><AutomaticallyUseReferenceAssemblyPackages>false</AutomaticallyUseReferenceAssemblyPackages>
    <FrameworkPathOverride>{managed}</FrameworkPathOverride><DisableImplicitFrameworkReferences>true</DisableImplicitFrameworkReferences>
    <ImplicitlyExpandNETStandardFacades>false</ImplicitlyExpandNETStandardFacades><ImplicitlyExpandDesignTimeFacades>false</ImplicitlyExpandDesignTimeFacades>
    <AppendTargetFrameworkToOutputPath>false</AppendTargetFrameworkToOutputPath><CopyLocalLockFileAssemblies>false</CopyLocalLockFileAssemblies>
    <NoWarn>CS1701;CS1702;CS0649;CS0169;CS0414;CS0436</NoWarn>
  </PropertyGroup>
  <ItemGroup>
{refs}
  </ItemGroup>
</Project>
"""


class Ksp(DeclarativeGame):
    apps = ("KSP.app",)                                     # macOS: the bundle in the game folder (Game.mac_app_bundle)

    # ---- folders
    @staticmethod
    def _managed(d: Path):
        for m in (d / "KSP_Data" / "Managed", d / "KSP_x64_Data" / "Managed", d / "KSP.app" / "Contents" / "Resources" / "Data" / "Managed"):
            if (m / "Assembly-CSharp.dll").is_file(): return m
        return None

    def managed_dir(self):
        """The game's own assemblies (Assembly-CSharp, UnityEngine*): referenced to build a plugin, never copied into one."""
        gd = self.game_dir(); return self._managed(gd) if gd else None

    def save_dirs(self) -> list:
        """Her save profiles (saves/<name>/, not the game's scenarios/ and training/; all of saves/ is backed up anyway)."""
        s = self.saves_dir()
        return sorted(p for p in s.iterdir() if p.is_dir() and p.name not in ("scenarios", "training")) if s.is_dir() else []

    def info(self):
        d = super().info(); m = self.managed_dir()
        d["managed_dir"] = str(m) if m else None
        d["save_dirs"] = [str(p) for p in self.save_dirs()]
        return d

    # ---- build
    def build(self, src, name=None) -> dict:
        src = Path(src).expanduser().resolve()
        if not src.is_dir(): raise NativeError(f"找不到 mod 文件夹：{src}")
        cs = [f for f in src.rglob("*.cs") if not ({"bin", "obj"} & set(f.relative_to(src).parts))]
        if not cs: raise NativeError(f"{src} 里没有 .cs 文件")
        projs = sorted(src.glob("*.csproj"))
        if len(projs) > 1: raise NativeError(f"{src} 里有好几个 .csproj（{', '.join(p.name for p in projs)}）：只留一个")
        asm, extra = None, []
        if projs:
            t = projs[0].read_text(encoding="utf-8-sig", errors="replace")
            m = re.search(r"<AssemblyName>\s*([^<\s]+)\s*</AssemblyName>", t); asm = m.group(1) if m else projs[0].stem
            extra = re.findall(r'<Reference\s+Include="([^",\s]+)', t)
        name = name or asm or src.name
        if not NAME_RE.match(name): raise NativeError(f"mod 名字要能当程序集名（字母、数字、下划线、点，字母开头）：{name}")
        if name.lower() in GAME_OWN: raise NativeError(f"{name} 是游戏自己的 GameData 文件夹：换一个名字")
        asm = asm or name
        man = self.managed_dir()
        if man is None: raise NativeError(f"没有找到坎巴拉太空计划（Steam app {self.steam_appid}，或设置 {self.pin_var} 到游戏文件夹）")
        dn = dotnet(self.env, self.home)
        if not dn["ok"]: raise NativeError("没有 .NET SDK：" + self.toolchain()["setup"])
        w = self.build_dir(name)
        if w.exists(): self._trash(w, "old-build")
        for f in cs: _copy(f, w / "proj" / f.relative_to(src))
        names = list(dict.fromkeys(REFS + [r for r in extra if r not in REFS]))
        refs = "\n".join(f'    <Reference Include="{escape(r)}"><HintPath>{escape(str(man / (r + ".dll")))}</HintPath><Private>false</Private></Reference>'
                         for r in names if (man / f"{r}.dll").is_file())
        (w / "proj" / "Mod.csproj").write_text(_CSPROJ.format(name=escape(asm), managed=escape(str(man)), refs=refs), encoding="utf-8")
        env = {**self.env, "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"}
        try: r = subprocess.run([dn["path"], "build", str(w / "proj" / "Mod.csproj"), "-c", "Release", "-o", str(w / "out"), "-nologo", "-clp:NoSummary"],
                                capture_output=True, text=True, encoding="locale", errors="replace", timeout=600, env=env)
        except (OSError, subprocess.SubprocessError) as e: raise NativeError(f"dotnet build 没有跑起来：{e}")
        (w / "build.log").write_text(r.stdout + r.stderr, encoding="utf-8")
        dll = w / "out" / f"{asm}.dll"
        if r.returncode != 0 or not dll.is_file():
            errs = sorted({l.strip() for l in (r.stdout + r.stderr).splitlines() if " error " in l})
            raise NativeError("编译失败：\n" + "\n".join(errs[:20] or [(r.stdout + r.stderr)[-1500:]]) + f"\n（完整日志：{w / 'build.log'}）")
        st = w / "mod" / name; (st / "Plugins").mkdir(parents=True)
        theirs = {p.name.lower() for p in man.glob("*.dll")}
        for d in sorted((w / "out").glob("*.dll")):
            if d.name.lower() not in theirs: shutil.copy2(d, st / "Plugins" / d.name)      # the plugin (+ its own libraries), never the game's
        for f in src.rglob("*"):
            rel = f.relative_to(src)
            if f.is_file() and rel.parts[0] not in ("bin", "obj") and f.suffix.lower() not in (".cs", ".csproj", ".sln") and f.name != "README.md":
                _copy(f, st / rel)
        return {"staged": str(st), "dll": str(st / "Plugins" / dll.name), "log": str(w / "build.log"), "warnings": []}

    # ---- install
    def check_installable(self, src):
        src = Path(src)
        if not src.is_dir(): raise NativeError(f"要装的是一个 mod 文件夹（会放进 GameData/<名字>/）：{src}；先 gameanything native build --game {self.id} …")
        if src.name.lower() in GAME_OWN: raise NativeError(f"{src.name} 是游戏自己的文件夹，不装")
        if not any(f.suffix.lower() in (".dll", ".cfg") for f in src.rglob("*") if f.is_file()):
            raise NativeError(f"{src} 里没有插件 .dll 也没有 .cfg：游戏不会加载它（先 gameanything native build --game {self.id} …）")

    def install(self, src, name=None):
        self._need_closed("安装")
        n = name or Path(src).expanduser().name
        if n.lower() in GAME_OWN: raise NativeError(f"{n} 是游戏自己的 GameData 文件夹：换一个名字")
        return super().install(src, name)

    def uninstall(self, name):
        self._need_closed("卸载")
        return super().uninstall(name)

    # ---- launch
    def launch_url(self):
        """macOS: open the game's own KSP.app (`open -g`). Through steam://rungameid the game process started and then sat at 0 % CPU
        without a window or a log line (2026-10-29, KSP 1.12.5 on an external Steam library); KSP 1 is DRM-free and runs without Steam."""
        if self.sys == "mac":
            app = self.mac_app_bundle()
            if app: return str(app)
        return super().launch_url()

    # ---- headless check (native/checks.py calls it)
    def check_mod(self, src: Path, it: dict):
        from gameanything.native import checks
        src = Path(src)
        try: self.check_installable(src)
        except NativeError as e: it["errors"].append(str(e)); return
        ds = sorted(f for f in src.rglob("*.dll") if f.is_file())
        if not ds: it["notes"].append("只有 .cfg（零件 / 配置），没有插件 DLL"); return
        for d in ds:
            if d.parent.name != "Plugins": it["warnings"].append(f"{d.relative_to(src).as_posix()} 不在 Plugins/ 里：游戏也会加载，但习惯放在 <Mod>/Plugins/")
        man = self.managed_dir()
        if man is None: it["warnings"].append("没找到游戏：没法对照游戏的程序集"); return
        gd = self.mods_dir()
        others = sorted({p.parent for p in gd.glob("*/Plugins/*.dll")} - {gd / src.name / "Plugins"}) if gd.is_dir() else []
        own = {f.stem.lower() for f in ds}; idx = checks._Index([man, *others])
        from gameanything.native import clrmeta
        used, read = set(), False
        for d in ds:
            checks.check_dll(d, idx, own, it, runtime="mono4")
            try: used |= {f for s, f in clrmeta.Assembly.read(d).typerefs if s == "Assembly-CSharp"}; read = True
            except (clrmeta.NotManaged, OSError, ValueError): pass
        if read and not used & ENTRY_TYPES:
            it["warnings"].append("没有一个 DLL 用到 KSPAddon / PartModule / ScenarioModule / VesselModule：游戏会加载它们，但不会启动里面的任何东西")
