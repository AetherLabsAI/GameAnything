"""Kerbal Space Program (ksp): the game package against fake folders (no game, no network; Linux, Windows and macOS paths): the game
folder and its Managed/ per system, GameData install / uninstall (never the game's own Squad/), backup -> restore byte-identical
(saves/ + settings.cfg), refusing while the game runs, the build flow (a stand-in dotnet), check, reload and the wizard rules."""
import os
import stat
import sys
import textwrap
from pathlib import Path

import pytest

from gameanything import buildmode, games as registry, native, projects
from gameanything.games import testing, tools
from gameanything.games.ksp import adapter as kadapter
from gameanything.native import NativeError, checks

MANAGED = {"linux": "KSP_Data/Managed", "windows": "KSP_x64_Data/Managed", "mac": "KSP.app/Contents/Resources/Data/Managed"}
PLAYER = {"linux": ".config/unity3d/Squad/Kerbal Space Program/Player.log",
          "windows": "AppData/LocalLow/Squad/Kerbal Space Program/Player.log", "mac": "Library/Logs/Squad/KSP/Player.log"}      # macOS: Squad/KSP (seen on her Mac, 2026-10-29)


def _game(tmp_path, sys_="linux"):
    m = MANAGED[sys_]
    env = testing.fake_steam_app(tmp_path, 220200, "Kerbal Space Program",
                                 files=["GameData/Squad/", f"{m}/Assembly-CSharp.dll", f"{m}/UnityEngine.CoreModule.dll", f"{m}/mscorlib.dll"])
    if sys_ == "linux": env["XDG_CONFIG_HOME"] = str(tmp_path / "home" / ".config")
    g = testing.make("ksp", tmp_path, env=env, sys_=sys_)
    d = tmp_path / "steam" / "steamapps" / "common" / "Kerbal Space Program"
    (d / "saves" / "her-career" / "Ships" / "VAB").mkdir(parents=True); (d / "saves" / "training").mkdir()
    (d / "saves" / "her-career" / "persistent.sfs").write_bytes(b"GAME\n{\n\tversion = 1.12.5\n}\n")
    (d / "saves" / "her-career" / "Ships" / "VAB" / "Rocket.craft").write_bytes(b"ship = Rocket")
    (d / "saves" / "training" / "B_flightBasics.sfs").write_bytes(b"training")
    (d / "settings.cfg").write_bytes(b"FULLSCREEN = True\r\n")
    (d / "GameData" / "HerMod" / "Plugins").mkdir(parents=True); (d / "GameData" / "HerMod" / "Plugins" / "HerMod.dll").write_bytes(b"MZ")
    return g, d


def _mod(tmp_path, name="M2WSmoke", files=("Plugins/{n}.dll",)):
    src = tmp_path / "built" / name
    for f in files:
        p = src / f.format(n=name); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"MZ-not-really")
    return src


def test_package_is_valid():
    r = tools.check("ksp")
    assert r["ok"], [i for i in r["items"] if i["level"] == "error"]
    s = registry.get("ksp")
    assert s.source == "builtin" and s["loader"]["type"] == "builtin" and (s.smoke_dir() / "M2WSmoke.cs").is_file()
    assert "ksp" in projects.GAMES and native.GAMES["ksp"] is kadapter.Ksp
    t = (s.smoke_dir() / "M2WSmoke.cs").read_text(encoding="utf-8")
    assert "[M2W-smoke] loaded" in t and "KSPAddon" in t and "runInBackground = true" in t and "PostScreenMessage" in t


@pytest.mark.parametrize("sys_", ["linux", "windows", "mac"])
def test_folders_on_each_system(tmp_path, sys_):
    g, d = _game(tmp_path, sys_)
    i = g.info()
    assert i["installed"] and i["loader"]["ok"], i["loader"]
    assert Path(i["game_dir"]) == d and Path(i["user_dir"]) == d and Path(i["mods_dir"]) == d / "GameData"
    assert Path(i["saves_dir"]) == d / "saves" and Path(i["managed_dir"]) == d / MANAGED[sys_]
    assert i["save_dirs"] == [str(d / "saves" / "her-career")]                        # not the game's training/ and scenarios/
    assert g.extra_files() == [d / "settings.cfg"]
    assert g.log_files()[0] == d / "KSP.log" and g.log_files()[1] == tmp_path / "home" / PLAYER[sys_]
    # macOS opens the game's own KSP.app (the Steam link left the game stuck at 0 % CPU on her Mac, 2026-10-29)
    assert i["launch"] == (str(d / "KSP.app") if sys_ == "mac" else "steam://rungameid/220200") and "throwaway save" in i["launch_hint"]
    assert dict(g.process_names)[sys_] == {"linux": ("KSP.x86_64",), "windows": ("KSP_x64.exe",), "mac": ("KSP",)}[sys_]
    if sys_ == "mac": (d / "KSP.app" / "Contents").mkdir(parents=True, exist_ok=True); assert g.mac_app_bundle() == d / "KSP.app"


def test_not_found_and_loader(tmp_path):
    g = testing.make("ksp", tmp_path, env={"GAMEANYTHING_STEAM_DIR": str(tmp_path / "none")})
    assert not g.installed() and g.managed_dir() is None
    with pytest.raises(NativeError, match="220200"): g.build(registry.get("ksp").smoke_dir())
    pin = tmp_path / "drm-free-copy"; (pin / "GameData" / "Squad").mkdir(parents=True)
    g2 = testing.make("ksp", tmp_path, env={"GAMEANYTHING_STEAM_DIR": str(tmp_path / "none"), "GAMEANYTHING_KSP_DIR": str(pin)})
    assert g2.game_dir() == pin and g2.loader()["ok"]                                   # a copy outside Steam (the game is DRM-free)


def test_install_uninstall_backup_restore(tmp_path):
    g, d = _game(tmp_path)
    keep = [d / "saves" / "her-career" / "persistent.sfs", d / "saves" / "her-career" / "Ships" / "VAB" / "Rocket.craft",
            d / "saves" / "training" / "B_flightBasics.sfs", d / "settings.cfg"]
    before = {p: p.read_bytes() for p in keep}
    r = g.install(_mod(tmp_path))
    assert r["backup"] and (d / "GameData" / "M2WSmoke" / "Plugins" / "M2WSmoke.dll").is_file()
    assert g.mods()["M2WSmoke"]["path"] == str(d / "GameData" / "M2WSmoke")
    # she plays: a quicksave, a changed settings.cfg, a new ship
    (d / "saves" / "her-career" / "quicksave.sfs").write_bytes(b"quick"); (d / "settings.cfg").write_bytes(b"FULLSCREEN = False\r\n")
    (d / "saves" / "her-career" / "persistent.sfs").write_bytes(b"changed")
    out = g.uninstall("M2WSmoke")
    assert out["moved_to_trash"] and not (d / "GameData" / "M2WSmoke").exists()
    assert (d / "GameData" / "Squad").is_dir() and (d / "GameData" / "HerMod" / "Plugins" / "HerMod.dll").is_file()
    with pytest.raises(NativeError): g.uninstall("HerMod")                                  # not m2w's
    g.restore(g.backups()[0]["stamp"])
    assert {p: p.read_bytes() for p in keep} == before and not (d / "saves" / "her-career" / "quicksave.sfs").exists()


def test_install_refusals(tmp_path):
    g, d = _game(tmp_path)
    with pytest.raises(NativeError, match="游戏自己"): g.install(_mod(tmp_path, "Squad"))
    with pytest.raises(NativeError, match="游戏自己"): g.install(_mod(tmp_path), name="SquadExpansion")
    f = tmp_path / "M2WSmoke.dll"; f.write_bytes(b"MZ")
    with pytest.raises(NativeError, match="mod 文件夹"): g.install(f)
    (tmp_path / "Empty" / "Plugins").mkdir(parents=True); (tmp_path / "Empty" / "readme.txt").write_text("x", encoding="utf-8")
    with pytest.raises(NativeError, match="没有插件"): g.install(tmp_path / "Empty")
    assert sorted(p.name for p in (d / "GameData").iterdir()) == ["HerMod", "Squad"]
    assert g.install(_mod(tmp_path, "PartsOnly", files=("Parts/thing.cfg",)))["path"] == str(d / "GameData" / "PartsOnly")   # a .cfg mod


def test_refuses_while_running(tmp_path, monkeypatch):
    g, _ = _game(tmp_path)
    monkeypatch.setattr(kadapter.Ksp, "running", lambda self: True)
    for f in (lambda: g.install(_mod(tmp_path)), lambda: g.uninstall("M2WSmoke"), lambda: g.restore("x")):
        with pytest.raises(NativeError, match="正在运行"): f()


@pytest.mark.skipif(os.name == "nt", reason="the stand-in dotnet is a shell script")
def test_build_stages_plugins_folder_outside_gamedata(tmp_path, monkeypatch):
    """`native build` writes a net472 csproj against the game's Managed/ (FrameworkPathOverride, no NuGet) and runs `dotnet build`; a
    stand-in dotnet checks the csproj and writes the plugin DLL (and a copy of a game DLL, which must not be staged)."""
    g, d = _game(tmp_path)
    man = d / MANAGED["linux"]
    fake = tmp_path / "bin" / "dotnet"; fake.parent.mkdir()
    fake.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{tmp_path / "bin" / "fake.py"}" "$@"\n', encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "bin" / "fake.py").write_text(textwrap.dedent(f"""\
        import re, sys, pathlib
        proj = pathlib.Path(sys.argv[2]); t = proj.read_text(encoding="utf-8"); out = pathlib.Path(sys.argv[sys.argv.index("-o") + 1])
        assert "<TargetFramework>net472</TargetFramework>" in t and "<FrameworkPathOverride>{man}</FrameworkPathOverride>" in t
        assert "<HintPath>{man / 'Assembly-CSharp.dll'}</HintPath>" in t and "UnityEngine.UI.dll" not in t      # only what this copy has
        assert list(proj.parent.glob("*.cs"))
        asm = re.search(r"<AssemblyName>(.*?)</AssemblyName>", t).group(1)
        out.mkdir(parents=True, exist_ok=True); (out / (asm + ".dll")).write_bytes(b"MZ"); (out / "Assembly-CSharp.dll").write_bytes(b"MZ")
        print("Build succeeded.")
        """), encoding="utf-8")
    monkeypatch.setattr(kadapter, "dotnet", lambda env=None, home=None: {"ok": True, "path": str(fake), "sdks": ["8.0.100"]})
    src = tmp_path / "src" / "M2WSmoke"; src.mkdir(parents=True)
    (src / "M2WSmoke.cs").write_text((registry.get("ksp").smoke_dir() / "M2WSmoke.cs").read_text(encoding="utf-8"), encoding="utf-8")
    (src / "Parts").mkdir(); (src / "Parts" / "part.cfg").write_text("PART {}", encoding="utf-8")
    b = g.build(src)
    st = Path(b["staged"])
    assert st.name == "M2WSmoke" and str(st).startswith(str(g.root)) and not (d / "GameData" / "M2WSmoke").exists()
    assert sorted(p.relative_to(st).as_posix() for p in st.rglob("*") if p.is_file()) == ["Parts/part.cfg", "Plugins/M2WSmoke.dll"]
    assert g.install(st)["path"] == str(d / "GameData" / "M2WSmoke")
    (src / "Mod.csproj").write_text('<Project><PropertyGroup><AssemblyName>Other</AssemblyName></PropertyGroup></Project>', encoding="utf-8")
    assert Path(g.build(src)["dll"]).name == "Other.dll"                                    # the csproj's AssemblyName
    with pytest.raises(NativeError, match="游戏自己"): g.build(src, name="Squad")
    with pytest.raises(NativeError, match=".cs"): g.build(tmp_path / "src" / "M2WSmoke" / "Parts")


def test_check_and_reload(tmp_path):
    g, _ = _game(tmp_path)
    m = checks.check(g, _mod(tmp_path, files=("{n}.dll",)))["mods"][0]                     # fake DLL bytes: not .NET, and not in Plugins/
    assert any("Plugins/" in w for w in m["warnings"]) and any("不是 .NET" in w for w in m["warnings"]) and not m["errors"]
    assert not checks.check(g, tmp_path / "missing")["ok"]
    with pytest.raises(checks.NoReload, match="热重载"): checks.reload(g, _mod(tmp_path))


def test_wizard_rules():
    m = {"system": "linux", "docker": True, "kit": True, "headless": False, "scripts": {"ksp"},
         "pool": {"games": {"ksp": {"gpu": True}}, "sandboxes": {"s": {"kind": "lab", "games": ["ksp"], "gpu": True}}}}
    o = buildmode.options("ksp", m, {"installed": True})          # lab since 2026-10-28 (gamebench kslab_rt.py in mclab-hlm-m1)
    assert next(x for x in o["options"] if x["mode"] == "lab")["ok"] is True and o["recommended"] == "native"     # installed: she can play it
    assert buildmode.options("ksp", m, {"installed": True}, hub=True)["recommended"] == "lab"
    assert buildmode.options("ksp", m, {"installed": False})["recommended"] == "lab"
    no_gpu = dict(m, pool={"games": {"ksp": {"gpu": True}}, "sandboxes": {"s": {"kind": "lab", "games": ["ksp"], "gpu": False}}})
    assert next(x for x in buildmode.options("ksp", no_gpu, {"installed": True})["options"] if x["mode"] == "lab")["ok"] is False
    assert registry.lab_supported("ksp") and buildmode.lab_runs("ksp", None, {"ksp"}) and not buildmode.lab_runs("ksp", None, set())
    info = registry.ui_info()
    k = info["games"]["ksp"]
    assert k["title"] == "Kerbal Space Program" and k["desc"] and k["desc_en"] and info["texts"][registry.get("ksp")["loader"]["fix"]]
