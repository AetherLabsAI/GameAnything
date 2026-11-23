"""Terraria (tModLoader), the first game brought in through the game-package framework: folders on Linux / Windows / macOS, the .tmod
format, install -> enabled.json -> uninstall, backup / restore, the build flow (a stand-in dotnet), check, reload and the wizard / lab rules.
No game, no Steam, no network: fake folders in tmp_path."""
import json
import os
import shutil
import stat
import sys
import textwrap
from pathlib import Path

import pytest

from gameanything import buildmode, games as registry, native, projects
from gameanything.games import testing, tools
from gameanything.games.terraria import adapter as tadapter, tmod
from gameanything.native import NativeError, checks

USER = {"linux": ".local/share/Terraria/tModLoader", "windows": "Documents/My Games/Terraria/tModLoader",
        "mac": "Library/Application Support/Terraria/tModLoader"}


def _game(tmp_path, sys_="linux", terraria=True):
    env = testing.fake_steam_app(tmp_path, 1281930, "tModLoader", files=["tModLoader.dll", "tMLMod.targets", "tModLoader-Logs/"])
    if terraria: testing.fake_steam_app(tmp_path, 105600, "Terraria", files=["Content/"])
    home = tmp_path / "home"
    env.update({"XDG_DATA_HOME": str(home / ".local" / "share")} if sys_ == "linux" else {})
    g = testing.make("terraria", tmp_path, env=env, sys_=sys_)
    u = home / USER[sys_]; (u / "Players").mkdir(parents=True); (u / "Worlds").mkdir()
    (u / "Players" / "Tester.plr").write_bytes(b"player-1"); (u / "Worlds" / "Test.wld").write_bytes(b"world-1")
    (u / "Mods").mkdir(); (u / "Mods" / "enabled.json").write_text('[\n  "HerMod"\n]', encoding="utf-8")
    return g, u


def _tmod(p, name="M2WSmoke", files=None):
    return tmod.write(p, name, "0.1", files if files is not None else {"Info": b"\x07version\x030.1\x00", f"{name}.dll": b"MZ-not-really"})


def test_package_is_valid():
    r = tools.check("terraria")
    assert r["ok"], [i for i in r["items"] if i["level"] == "error"]
    s = registry.get("terraria")
    assert s.source == "builtin" and s["loader"]["type"] == "tmodloader" and s.smoke_dir().is_dir()
    assert "terraria" in projects.GAMES and "terraria" in native.GAMES and native.GAMES["terraria"] is tadapter.Terraria


@pytest.mark.parametrize("sys_", ["linux", "windows", "mac"])
def test_folders_on_each_system(tmp_path, sys_):
    g, u = _game(tmp_path, sys_)
    i = g.info()
    assert i["installed"] and i["loader"]["ok"], i["loader"]
    assert Path(i["game_dir"]) == tmp_path / "steam" / "steamapps" / "common" / "tModLoader"
    assert Path(i["user_dir"]) == u and Path(i["mods_dir"]) == u / "Mods" and Path(i["saves_dir"]) == u / "Players"
    assert [Path(p) for p in i["save_dirs"]] == [u / "Players", u / "Worlds"] and i["enabled_mods"] == ["HerMod"]
    assert g.log_files() == [Path(i["game_dir"]) / "tModLoader-Logs" / "client.log"]
    assert i["launch"] == "steam://rungameid/1281930" and "LOCAL" in i["launch_hint"]
    assert Path(i["terraria_dir"]).name == "Terraria"


def test_windows_documents_follow_onedrive(tmp_path):
    g, _ = _game(tmp_path, "windows")
    od = tmp_path / "OneDrive"; (od / "Documents").mkdir(parents=True)
    g.env["OneDrive"] = str(od)
    assert g.user_dir() == od / "Documents" / "My Games" / "Terraria" / "tModLoader"
    # dict(os.environ) on Windows has ONEDRIVE in upper case (a real Windows 11 PC, 2026-11-01): the mod went to a Documents
    # folder tModLoader never reads while %USERPROFILE%\Documents existed too
    (Path(g.env["USERPROFILE"]) / "Documents").mkdir(parents=True, exist_ok=True)
    del g.env["OneDrive"]; g.env["ONEDRIVE"] = str(od)
    assert g.user_dir() == od / "Documents" / "My Games" / "Terraria" / "tModLoader"


def test_loader_needs_terraria_too(tmp_path):
    g, _ = _game(tmp_path, terraria=False)
    lo = g.loader()
    assert not lo["ok"] and "105600" in lo["detail"]
    with pytest.raises(NativeError, match="tModLoader"): g.install(_tmod(tmp_path / "M2WSmoke.tmod"))


def test_tmod_round_trip_and_damage(tmp_path):
    f = _tmod(tmp_path / "M2WSmoke.tmod")
    i = tmod.read(f)
    assert (i["name"], i["version"], i["hash_ok"]) == ("M2WSmoke", "0.1", True) and set(i["files"]) == {"Info", "M2WSmoke.dll"}
    assert tmod.read_file(f, i, "M2WSmoke.dll") == b"MZ-not-really"
    b = bytearray(f.read_bytes()); b[-1] ^= 0xFF; f.write_bytes(bytes(b))
    assert tmod.read(f)["hash_ok"] is False
    f.write_bytes(f.read_bytes()[:-3])
    with pytest.raises(tmod.BadTmod): tmod.read(f)
    (tmp_path / "x.tmod").write_bytes(b"PK\x03\x04")
    with pytest.raises(tmod.BadTmod): tmod.read(tmp_path / "x.tmod")


def test_install_enable_uninstall_restore(tmp_path):
    g, u = _game(tmp_path)
    before = {p: p.read_bytes() for p in (u / "Players" / "Tester.plr", u / "Worlds" / "Test.wld", u / "Mods" / "enabled.json")}
    with pytest.raises(NativeError, match=r"\.tmod"): g.install(tmp_path)                     # a folder is not a mod
    with pytest.raises(NativeError, match="Other"): g.install(_tmod(tmp_path / "x" / "M2WSmoke.tmod", name="Other"))
    r = g.install(_tmod(tmp_path / "b" / "M2WSmoke.tmod"))
    assert r["backup"] and r["enabled"] is True and (u / "Mods" / "M2WSmoke.tmod").is_file()
    assert json.loads((u / "Mods" / "enabled.json").read_text(encoding="utf-8")) == ["HerMod", "M2WSmoke"]
    assert g.mods()["M2WSmoke.tmod"]["path"] == str(u / "Mods" / "M2WSmoke.tmod")
    (u / "Worlds" / "Test.wld").write_bytes(b"world-2-played")                              # she plays
    r2 = g.install(_tmod(tmp_path / "c" / "M2WSmoke.tmod"), name="M2WSmoke")               # same name: the old one goes to the trash
    assert r2["replaced_to_trash"] and r2["backup"] is not None
    assert json.loads((u / "Mods" / "enabled.json").read_text(encoding="utf-8")) == ["HerMod", "M2WSmoke"]   # not twice
    out = g.uninstall("M2WSmoke")
    assert out["moved_to_trash"] and not (u / "Mods" / "M2WSmoke.tmod").exists()
    assert json.loads((u / "Mods" / "enabled.json").read_text(encoding="utf-8")) == ["HerMod"]
    with pytest.raises(NativeError): g.uninstall("HerMod")                                  # not m2w's
    g.restore(g.backups()[0]["stamp"])
    assert {p: p.read_bytes() for p in before} == before                                     # byte-identical, enabled.json too


def test_refuses_while_running(tmp_path, monkeypatch):
    g, _ = _game(tmp_path)
    monkeypatch.setattr(tadapter.Terraria, "running", lambda self: True)
    for f in (lambda: g.install(_tmod(tmp_path / "M2WSmoke.tmod")), lambda: g.uninstall("M2WSmoke"), lambda: g.restore("x")):
        with pytest.raises(NativeError, match="正在运行"): f()


def test_process_lookup_rules(tmp_path, monkeypatch):
    T = tadapter.Terraria
    assert T._is_client(["/x/dotnet/8.0.0/dotnet", "tModLoader.dll"]) and T._is_client(["dotnet", "/g/tModLoader.dll", "-steam"])
    assert not T._is_client(["dotnet", "tModLoader.dll", "-server", "-build", "/m"])        # m2w's own build (the packer)
    assert not T._is_client(["python3", "tModLoader.dll"]) and not T._is_client([])
    g, _ = _game(tmp_path)
    monkeypatch.setattr(T, "_procs", lambda self: [(4242, ["dotnet", "tModLoader.dll"])])
    monkeypatch.setattr(T, "_this_install", lambda self, pid, argv: pid == 4242)
    assert g.running() is True and g.pids() == [4242]
    monkeypatch.setattr(T, "_procs", lambda self: None)
    assert g.running() is None and g.pids() is None


@pytest.mark.skipif(sys.platform != "linux", reason="reads /proc")
def test_linux_proc_scan_sees_no_game_here(tmp_path):
    g, _ = _game(tmp_path)
    assert g._procs() == [] and g.running() is False                                       # this test's own python is not tModLoader


def test_check_and_reload(tmp_path):
    g, _ = _game(tmp_path)
    good = _tmod(tmp_path / "ok" / "M2WSmoke.tmod")
    r = checks.check(g, good)
    m = r["mods"][0]
    assert not [e for e in m["errors"] if "Info" in e or "校验" in e] and any("M2WSmoke 0.1" in n for n in m["notes"])
    bad = _tmod(tmp_path / "bad" / "M2WSmoke.tmod", files={"Info": b""})
    assert any("M2WSmoke.dll" in e for e in checks.check(g, bad)["mods"][0]["errors"])
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    assert not checks.check(g, tmp_path / "x.txt")["ok"]
    with pytest.raises(checks.NoReload, match="tModLoader"): checks.reload(g, good)


@pytest.mark.skipif(os.name == "nt", reason="the stand-in dotnet is a shell script")
def test_build_writes_the_tmod_into_m2w_folder_not_hers(tmp_path, monkeypatch):
    """`native build` stages the source as ModSources/<Name>/, writes its own tModLoader.targets (-tmlsavedirectory = its build folder)
    and runs `dotnet build`; a stand-in dotnet plays tModLoader's packer: it writes <save>/Mods/<Name>.tmod as the real one does."""
    g, u = _game(tmp_path)
    fake = tmp_path / "bin" / "dotnet"; fake.parent.mkdir()
    fake.write_text(textwrap.dedent(f"""\
        #!/bin/sh
        exec "{sys.executable}" -I "{tmp_path / 'bin' / 'pack.py'}" "$@"
        """), encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "bin" / "pack.py").write_text(textwrap.dedent(f"""\
        import re, sys, pathlib
        sys.path.insert(0, {str(Path(tmod.__file__).parent)!r})
        import tmod
        proj = pathlib.Path(sys.argv[2]); t = (proj.parent.parent / "tModLoader.targets").read_text(encoding="utf-8")
        assert "tMLMod.targets" in t and proj.parent.name == proj.stem
        save = re.search(r"-tmlsavedirectory &quot;(.*?)&quot;", t).group(1)
        assert (proj.parent / "build.txt").is_file() and "tModLoader.targets" in proj.read_text(encoding="utf-8")
        tmod.write(pathlib.Path(save) / "Mods" / (proj.stem + ".tmod"), proj.stem, "0.1", {{"Info": b"", proj.stem + ".dll": b"MZ"}})
        print("Build succeeded.")
        """), encoding="utf-8")
    monkeypatch.setattr(tadapter, "dotnet", lambda env=None, home=None: {"ok": True, "path": str(fake), "sdks": ["8.0.100"]})
    monkeypatch.setattr(tadapter.Terraria, "toolchain", lambda self: {"ok": True, "name": "", "detail": "", "setup": ""})
    b = g.build(registry.get("terraria").smoke_dir())
    out = Path(b["staged"])
    assert out.name == "M2WSmoke.tmod" and out.is_file() and tmod.read(out)["name"] == "M2WSmoke"
    assert str(out).startswith(str(g.root)) and not (u / "Mods" / "M2WSmoke.tmod").exists()         # nothing in her Mods folder
    r = g.install(out); assert r["path"] == str(u / "Mods" / "M2WSmoke.tmod")
    src = tmp_path / "BadName"; shutil.copytree(registry.get("terraria").smoke_dir(), src)
    assert Path(g.build(src)["staged"]).name == "M2WSmoke.tmod"                                   # the name is the csproj's AssemblyName
    with pytest.raises(NativeError, match="程序集名"): g.build(src, name="Other")                  # --name != AssemblyName
    (src / "M2WSmoke.csproj").write_text("<Project/>", encoding="utf-8")
    with pytest.raises(NativeError, match="tModLoader.targets"): g.build(src)


def test_build_needs_the_install(tmp_path):
    g = testing.make("terraria", tmp_path, env={"GAMEANYTHING_STEAM_DIR": str(tmp_path / "none")})
    with pytest.raises(NativeError, match="1281930"): g.build(registry.get("terraria").smoke_dir())


def test_wizard_and_lab_rules():
    m = {"system": "linux", "docker": True, "kit": True, "headless": False, "scripts": {"terraria"},
         "pool": {"games": {"terraria": {"steam": True}}, "sandboxes": {"s": {"kind": "steam"}}}}
    o = buildmode.options("terraria", m, {"installed": True})
    lab = next(x for x in o["options"] if x["mode"] == "lab")
    assert lab["ok"] is True and lab["note"] == buildmode.NOTE["lab_steam"]                     # the gamebench lab on the Steam sandbox
    assert buildmode.lab_runs("terraria", m["pool"]) and not buildmode.lab_runs("terraria", {"games": {"terraria": {"steam": True}},
                                                                                               "sandboxes": {"s": {"kind": "lab"}}})
    info = registry.ui_info()
    t = info["games"]["terraria"]
    assert t["title"] == "Terraria" and t["desc"] and t["desc_en"] and info["texts"][registry.get("terraria")["loader"]["fix"]]


def test_tml_version_is_tmodloaders_not_terrarias(tmp_path):
    """tModLoader.dll's AssemblyVersion is Terraria's 1.4.4.9; the version a .tmod records is tModLoader's own (2026.8.3.0, from the
    informational version "1.4.4.9+2026.08.3.0|..."). Comparing the two warned about every freshly built mod (real install, 2026-10-28)."""
    g, _ = _game(tmp_path)
    dll = g.game_dir() / "tModLoader.dll"
    dll.write_bytes(b"MZ\0\x071.4.4.9\0\0k\x01\0f1.4.4.9+2026.08.3.0|2026.08|stable|Stable|c9545cf|52509501173523\0")
    assert g.tml_version() == "2026.8.3.0"
    m = {"errors": [], "warnings": [], "notes": []}
    g.check_mod(_tmod(tmp_path / "ok" / "M2WSmoke.tmod"), m)
    assert not [w for w in m["warnings"] if "1.4.4.9" in w]
    dll.write_bytes(b"MZ no version here")
    assert g.tml_version() is None
