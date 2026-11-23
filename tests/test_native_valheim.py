"""Valheim in native mode (BepInExPack_Valheim = BepInEx 5 on Unity Mono): the game folder, BepInEx / doorstop detection, the
launch-option hint, worlds and characters backed up before an install, BepInEx/plugins/<name>/, `build` from the lab's mod template,
`check` against the game's DLLs, `reload` through ScriptEngine, and the CLI round trip on Linux, macOS and Windows rules. Fake game
folders only; the one real compile uses the lab's Valheim on this server read-only when it is there (skipped elsewhere)."""
import json
import os
import re
import shutil
from pathlib import Path, PureWindowsPath

import pytest

from _fakedll import make_dll
from gameanything import cli, osdirs
from gameanything.native import checks, games, quiet
from test_native import _FakeRun, _env, _steam

WIN_HOME = "C:\\Users\\小雨"
_VH = os.environ.get("GAMEANYTHING_TEST_VALHEIM_GAME")
LAB_GAME = Path(_VH) if _VH else None


@pytest.fixture(autouse=True)
def _not_running(monkeypatch):
    monkeypatch.setattr(games.Game, "running", lambda self: False)


def _managed(d: Path, sys_: str) -> Path:
    return d / ("valheim.app/Contents/Resources/Data/Managed" if sys_ == "mac" else "valheim_Data/Managed")


def _vh_game(home: Path, sys_: str, bepinex=True, script="start_game_bepinex.sh") -> Path:
    d = _steam(home, sys_, 892970, "Valheim"); m = _managed(d, sys_); m.mkdir(parents=True)
    for n in ("assembly_valheim.dll", "assembly_utils.dll", "UnityEngine.dll", "UnityEngine.CoreModule.dll", "UnityEngine.IMGUIModule.dll",
              "UnityEngine.TextRenderingModule.dll", "mscorlib.dll", "netstandard.dll"): (m / n).write_bytes(b"MZ")
    if bepinex:
        (d / "BepInEx/core").mkdir(parents=True); (d / "BepInEx/core/BepInEx.dll").write_bytes(b"MZ"); (d / "BepInEx/core/0Harmony.dll").write_bytes(b"MZ")
        (d / "doorstop_libs").mkdir(); (d / "doorstop_config.ini").write_text("[General]\nenabled = true\n", encoding="utf-8")
        (d / ("winhttp.dll" if sys_ == "windows" else script)).write_bytes(b"x")
    return d


# ---------------------------------------------------------------- folders, loader, hint
@pytest.mark.parametrize("sys_", ["mac", "windows", "linux"])
def test_valheim_paths_and_loader(tmp_path, sys_):
    home = tmp_path / "home 小雨"; e = {**_env(tmp_path, sys_), "USERPROFILE": str(home)}
    if sys_ == "windows": e["GAMEANYTHING_STEAM_DIR"] = str(home / "Steam")
    g = games.get("valheim", sys_=sys_, home=home, env=e)
    assert not g.installed() and g.info()["game"] == "valheim"                    # not installed: no crash
    d = _vh_game(home, sys_, bepinex=False)
    assert g.game_dir() == d and g.mods_dir() == d / "BepInEx/plugins" and g.managed_dir() == _managed(d, sys_)
    lo = g.loader(); assert not lo["ok"] and "BepInExPack_Valheim" in lo["detail"] and "denikson" in lo["detail"] and str(d) in lo["detail"]
    (d / "BepInEx/core").mkdir(parents=True); (d / "BepInEx/core/BepInEx.dll").write_bytes(b"MZ")
    door = "winhttp.dll" if sys_ == "windows" else "start_game_bepinex.sh"
    assert not g.loader()["ok"] and door in g.loader()["detail"]
    (d / door).write_bytes(b"x")
    assert g.loader()["ok"] and "not run yet" in g.loader()["detail"] and g.loader()["name"].startswith("BepInExPack_Valheim")
    want = {"mac": home / "Library/Application Support/IronGate/Valheim", "windows": home / "AppData/LocalLow/IronGate/Valheim",
            "linux": home / ".config/unity3d/IronGate/Valheim"}[sys_]
    assert g.saves_dir() == want and g.user_dir() == want
    h = g.launch_hint()
    assert ("start_game_bepinex.sh\" %command%" in h) == (sys_ == "linux") and "LOCAL world" in h and "public" in h and "Move to local" in h
    assert g.launch_url() == ("script:" + str(d / "start_game_bepinex.sh") if sys_ == "mac" else "steam://rungameid/892970") and g.window_titles == ("Valheim",)
    assert (g.launch_option() is None) == (sys_ != "linux")                                     # macOS: m2w runs the script, no launch option
    if sys_ == "linux": assert g.launch_option() == f'"{d / "start_game_bepinex.sh"}" %command%' and "PASTE" not in h
    if sys_ == "mac": assert "hardened" not in h
    pl = g.log_files()[-1 if sys_ != "mac" else 1]; pl.parent.mkdir(parents=True, exist_ok=True); pl.write_text("unity", encoding="utf-8")
    assert g.log() == pl
    (d / "BepInEx/LogOutput.log").write_text("[Info   :   BepInEx] Loading [M2WSmoke 1.0.0]", encoding="utf-8")
    assert g.log() == d / "BepInEx/LogOutput.log" and "not run yet" not in g.loader()["detail"]


def test_valheim_linux_lab_layout_and_mac_app_pin(tmp_path):
    """The lab renames the pack's start_game_bepinex.sh to run_bepinex.sh: either counts. A pin may point at the app bundle (macOS)."""
    home = tmp_path / "home"; d = _vh_game(home, "linux", script="run_bepinex.sh")
    g = games.get("valheim", sys_="linux", home=home, env=_env(tmp_path, "linux"))
    assert g.loader()["ok"] and g.start_script() == d / "run_bepinex.sh" and f'"{d / "run_bepinex.sh"}" %command%' in g.launch_hint()
    mac = tmp_path / "Mac 游戏" / "Valheim"; _managed(mac, "mac").mkdir(parents=True); (_managed(mac, "mac") / "assembly_valheim.dll").write_bytes(b"MZ")
    m = games.get("valheim", sys_="mac", home=home, env={**_env(tmp_path, "mac"), "GAMEANYTHING_VALHEIM_DIR": str(mac / "valheim.app")})
    assert m.game_dir() == mac and m.managed_dir() == _managed(mac, "mac")
    big = tmp_path / "Big" / "Valheim"; (big / "Valheim.app/Contents/Resources/Data/Managed").mkdir(parents=True)
    (big / "Valheim.app/Contents/Resources/Data/Managed/assembly_valheim.dll").write_bytes(b"MZ")
    assert games.get("valheim", sys_="mac", home=home, env={"GAMEANYTHING_VALHEIM_DIR": str(big)}).game_dir() == big   # either capitalisation
    other = tmp_path / "Not Valheim"; (other / "valheim_Data/Managed").mkdir(parents=True); (other / "valheim_Data/Managed/Assembly-CSharp.dll").write_bytes(b"MZ")
    assert games.get("valheim", sys_="linux", home=tmp_path / "empty", env={"GAMEANYTHING_VALHEIM_DIR": str(other)}).game_dir() is None   # no assembly_valheim.dll


def test_valheim_windows_default_folders(tmp_path):
    env = {"USERPROFILE": WIN_HOME, "GAMEANYTHING_DATA": "unused"}
    g = games.get("valheim", sys_="windows", home=Path(WIN_HOME), env=env)
    assert PureWindowsPath(str(g.saves_dir())) == PureWindowsPath(WIN_HOME + r"\AppData\LocalLow\IronGate\Valheim")
    assert PureWindowsPath(str(g.log_files()[-1])) == PureWindowsPath(WIN_HOME + r"\AppData\LocalLow\IronGate\Valheim\Player.log")
    assert dict(g.process_names)["windows"] == ("valheim.exe",) and dict(g.process_names)["linux"] == ("valheim.x86_64",)
    # the default Steam library on Windows: C:\Program Files (x86)\Steam\steamapps\common\Valheim
    home = tmp_path / "home"; d = _vh_game(home, "windows")
    w = games.get("valheim", sys_="windows", home=home, env=_env(tmp_path, "windows"))
    assert w.game_dir() == d and d.parts[-3:] == ("steamapps", "common", "Valheim") and w.loader()["ok"]
    assert "winhttp.dll next to valheim.exe" in w.launch_hint()
    assert games.get("valheim", sys_="linux", home=home, env={}).saves_dir() == home / ".config/unity3d/IronGate/Valheim"
    assert games.get("valheim", sys_="linux", home=home, env={"XDG_CONFIG_HOME": str(tmp_path / "xdg")}).saves_dir() == tmp_path / "xdg/unity3d/IronGate/Valheim"
    old = home / "Library/Application Support/unity.IronGate.Valheim"; old.mkdir(parents=True)
    assert games.get("valheim", sys_="mac", home=home, env={}).saves_dir() == old              # an older Unity player's folder name


# ---------------------------------------------------------------- install, backup, restore
def test_valheim_install_backs_up_worlds_and_characters(tmp_path, monkeypatch):
    home = tmp_path / "home 小雨"; d = _vh_game(home, "linux")
    (d / "BepInEx/plugins").mkdir(); (d / "BepInEx/plugins/她的插件.dll").write_bytes(b"MZ")
    g = games.get("valheim", sys_="linux", home=home, env=_env(tmp_path, "linux"))
    u = g.user_dir(); (u / "worlds_local/北境").mkdir(parents=True); (u / "characters_local").mkdir()
    (u / "worlds_local/北境.fwl").write_bytes(b"world v1"); (u / "worlds_local/北境.db").write_bytes(b"\x00db v1")
    (u / "characters_local/维京人.fch").write_bytes(b"char v1"); (u / "worlds").mkdir(); (u / "worlds/steam_autocloud.vdf").write_text("x", encoding="utf-8")
    assert [p.name for p in g.save_dirs()] == ["worlds_local", "characters_local", "worlds"] and g.info()["save_dirs"]
    src = tmp_path / "构建 out/Our Hall"; (src / "assets/模型").mkdir(parents=True); (src / "OurHall.dll").write_bytes(b"MZ1")
    (src / "assets/模型/hall.glb").write_bytes(b"glTF")
    with pytest.raises(games.NativeError, match="dll"): g.install(src / "assets")
    bad = tmp_path / "bad"; bad.mkdir(); (bad / "ValheimBridge.dll").write_bytes(b"MZ")
    with pytest.raises(games.NativeError, match="ValheimBridge"): g.install(bad)
    r = g.install(src, "OurHall"); dst = d / "BepInEx/plugins/OurHall"
    assert r["backup"] and (dst / "assets/模型/hall.glb").is_file() and (dst / "OurHall.dll").read_bytes() == b"MZ1"
    bk = g._bdir() / r["backup"] / "saves"
    assert (bk / "worlds_local/北境.db").read_bytes() == b"\x00db v1" and (bk / "characters_local/维京人.fch").read_bytes() == b"char v1"
    (u / "Player.log").write_text("a new start", encoding="utf-8"); assert not g.needs_backup()    # Player.log is not a save
    (u / "worlds_local/北境.db").write_bytes(b"broken"); (u / "characters_local/维京人.fch").write_bytes(b"broken")
    assert g.needs_backup()
    g.restore(r["backup"])
    assert (u / "worlds_local/北境.db").read_bytes() == b"\x00db v1" and (u / "characters_local/维京人.fch").read_bytes() == b"char v1"
    monkeypatch.setattr(games.Game, "running", lambda self: True)
    with pytest.raises(games.NativeError, match="正在运行"): g.install(src, "OurHall")
    with pytest.raises(games.NativeError, match="正在运行"): g.uninstall("OurHall")
    with pytest.raises(games.NativeError, match="正在运行"): g.restore(r["backup"])
    monkeypatch.setattr(games.Game, "running", lambda self: False)
    assert g.uninstall("OurHall")["moved_to_trash"] and not dst.exists()
    with pytest.raises(games.NativeError): g.uninstall("她的插件.dll")
    assert (d / "BepInEx/plugins/她的插件.dll").is_file()


# ---------------------------------------------------------------- build (fake dotnet) from the lab's template layout
LAB_CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net462</TargetFramework><AssemblyName>ModLab</AssemblyName><NoStdLib>true</NoStdLib>
    <FrameworkPathOverride>$(GameDir)/valheim_Data/Managed</FrameworkPathOverride>
    <GameDir Condition="'$(GameDir)' == ''">/home/player/.steam/debian-installation/steamapps/common/Valheim</GameDir>
    <Managed>$(GameDir)/valheim_Data/Managed</Managed>
  </PropertyGroup>
  <ItemGroup>
    <Reference Include="assembly_valheim"><HintPath>$(Managed)/assembly_valheim.dll</HintPath><Private>false</Private></Reference>
    <Reference Include="BepInEx"><HintPath>$(GameDir)/BepInEx/core/BepInEx.dll</HintPath><Private>false</Private></Reference>
  </ItemGroup>
  <ItemGroup><None Include="assets/**" CopyToOutputDirectory="PreserveNewest" /></ItemGroup>
</Project>
"""


def _fake_dotnet(monkeypatch):
    monkeypatch.setattr(games, "dotnet", lambda *a, **k: {"ok": True, "path": "/usr/bin/dotnet", "sdks": ["8.0.426"]})

    def make(args, kw):
        o = Path(args[args.index("-o") + 1]); o.mkdir(parents=True)
        asm = re.search(r"<AssemblyName>(\w+)</AssemblyName>", Path(args[2]).read_text(encoding="utf-8")).group(1)
        for n in (f"{asm}.dll", f"{asm}.pdb", "assembly_valheim.dll", "BepInEx.dll", "ValheimBridge.dll", "MiniGlb.dll"): (o / n).write_bytes(b"MZ")
    fake = _FakeRun(make); monkeypatch.setattr(games.subprocess, "run", fake)
    return fake


@pytest.mark.parametrize("sys_", ["mac", "linux"])
def test_valheim_build_from_the_lab_template(tmp_path, monkeypatch, sys_):
    home = tmp_path / "home"; d = _vh_game(home, sys_)
    g = games.get("valheim", sys_=sys_, home=home, env=_env(tmp_path, sys_))
    src = tmp_path / "北欧 长屋/mod"; (src / "Lib").mkdir(parents=True); (src / "assets").mkdir()
    (src / "ModLab.csproj").write_text(LAB_CSPROJ, encoding="utf-8"); (src / "NuGet.config").write_text("<configuration/>", encoding="utf-8")
    (src / "Plugin.cs").write_text('class Plugin { const string Dir = "/home/player/vhlab/mod/assets/"; }', encoding="utf-8")
    (src / "Lib/PrefabKit.cs").write_text("class PrefabKit {}", encoding="utf-8"); (src / "assets/README.txt").write_text("长屋", encoding="utf-8")
    (src / "bin/Release").mkdir(parents=True); (src / "bin/Release/Old.dll").write_bytes(b"MZ")
    fake = _fake_dotnet(monkeypatch)
    b = g.build(src)
    args = fake.calls[0][0]; man = _managed(d, sys_)
    assert f"-p:M2wManaged={man}" in args and f"-p:M2wBepInExCore={d / 'BepInEx/core'}" in args and f"-p:GameDir={d}" in args
    proj = Path(args[2]).read_text(encoding="utf-8")
    assert "<Managed>$(M2wManaged)</Managed>" in proj and "<FrameworkPathOverride>$(M2wManaged)</FrameworkPathOverride>" in proj
    assert "$(M2wBepInExCore)/BepInEx.dll" in proj and "valheim_Data" not in proj
    assert (Path(args[2]).parent / "Lib/PrefabKit.cs").is_file() and not (Path(args[2]).parent / "NuGet.config").exists()
    st = Path(b["staged"]); assert st.name == "ModLab" and Path(b["dll"]) == st / "ModLab.dll"
    assert sorted(p.relative_to(st).as_posix() for p in st.rglob("*") if p.is_file()) == ["MiniGlb.dll", "ModLab.dll", "ModLab.pdb", "assets/README.txt"]
    assert len(b["warnings"]) == 1 and "/home/player/vhlab/mod/assets/" in b["warnings"][0]
    g.check_installable(st)
    # no csproj (the smoke plugin): a minimal net462 one with what this copy has, TextRenderingModule included (FontStyle, lab 2026-10-25)
    from gameanything.worlds import valheim
    fake.calls.clear(); b = g.build(valheim.SMOKE, "M2WSmoke")
    proj = Path(fake.calls[0][0][2]).read_text(encoding="utf-8")
    assert "<AssemblyName>M2WSmoke</AssemblyName>" in proj and "<TargetFramework>net462</TargetFramework>" in proj
    assert "$(M2wManaged)/UnityEngine.TextRenderingModule.dll" in proj and "$(M2wManaged)/assembly_valheim.dll" in proj
    assert "UnityEngine.UI.dll" not in proj and "$(M2wBepInExCore)/0Harmony.dll" in proj


def test_valheim_build_needs_the_game_and_bepinex(tmp_path, monkeypatch):
    home = tmp_path / "home"; g = games.get("valheim", sys_="linux", home=home, env=_env(tmp_path, "linux"))
    from gameanything.worlds import valheim
    with pytest.raises(games.NativeError, match="没有找到 Valheim"): g.build(valheim.SMOKE)
    _vh_game(home, "linux", bepinex=False)
    with pytest.raises(games.NativeError, match="BepInExPack_Valheim"): g.build(valheim.SMOKE)


def test_valheim_smoke_plugin():
    from gameanything.worlds import valheim
    t = (valheim.SMOKE / "Plugin.cs").read_text(encoding="utf-8")
    assert "[M2W-smoke] loaded" in t and "Application.runInBackground = true;" in t and "GUI.Box(" in t and "M2W smoke: plugin loaded" in t
    assert not list(valheim.SMOKE.glob("*.csproj"))                     # built with the minimal csproj against her copy


# ---------------------------------------------------------------- check and reload
def _vh(tmp):
    home = tmp / "home"; d = _steam(home, "linux", 892970, "Valheim"); m = d / "valheim_Data/Managed"; m.mkdir(parents=True)
    make_dll(m / "assembly_valheim.dll", "assembly_valheim", refs=[("mscorlib", (4, 0, 0, 0))], types=[("", "ZNetScene", None, [], ["Awake", "GetPrefab"])])
    make_dll(m / "mscorlib.dll", "mscorlib", (4, 0, 0, 0), types=[("System", "Object", None, [], [".ctor", "ToString"])])
    (d / "BepInEx/core").mkdir(parents=True); (d / "start_game_bepinex.sh").write_text("x", encoding="utf-8")
    make_dll(d / "BepInEx/core/BepInEx.dll", "BepInEx", types=[("BepInEx", "BepInPlugin", None, [], [".ctor"]), ("BepInEx", "BaseUnityPlugin", None, [], ["get_Logger"])])
    g = games.get("valheim", sys_="linux", home=home, env=_env(tmp, "linux")); g.running = lambda: False
    return g, d


def _plugin(p, corlib=("mscorlib", (4, 0, 0, 0)), member="GetPrefab", attr=True):
    trs = [(1, "System", "Object"), (2, "", "ZNetScene")] + ([(3, "BepInEx", "BepInPlugin")] if attr else [])
    return make_dll(p, p.stem, refs=[corlib, ("assembly_valheim", (0, 0, 0, 0)), ("BepInEx", (0, 0, 0, 0))], typerefs=trs,
                    types=[("M2W", "Plugin", 1, [], ["Awake"])], memberrefs=[(1, ".ctor"), (2, member)] + ([(3, ".ctor")] if attr else []))


def test_check_valheim_plugin(tmp_path):
    g, d = _vh(tmp_path)
    ok = checks.check(g, _plugin(tmp_path / "ok" / "Good.dll")); assert ok["ok"], ok                  # mscorlib 4.0 is right here (not net35)
    bad = checks.check(g, _plugin(tmp_path / "bad" / "Bad.dll", corlib=("System.Runtime", (8, 0, 0, 0)), member="GetPrefabs", attr=False))
    e = " ".join(bad["mods"][0]["errors"]); w = " ".join(bad["mods"][0]["warnings"])
    assert not bad["ok"] and "net462" in e and "ZNetScene.GetPrefabs" in e and "BepInPlugin" in w
    br = tmp_path / "with bridge"; _plugin(br / "Mine.dll"); _plugin(br / "ValheimBridge.dll")
    assert [i["mod"] for i in checks.check(g, br)["mods"]] == ["with bridge"] and checks.check(g, br)["ok"]
    only = tmp_path / "only bridge"; _plugin(only / "ValheimBridge.dll")
    assert "没有插件 DLL" in checks.check(g, only)["mods"][0]["errors"][0]


def test_reload_valheim_through_scriptengine(tmp_path):
    g, d = _vh(tmp_path); built = tmp_path / "build 构建" / "M2WSmoke"; _plugin(built / "M2WSmoke.dll")
    with pytest.raises(checks.NoReload, match="Valheim 里没有 BepInEx ScriptEngine"): checks.reload(g, built)
    (d / "BepInEx/plugins/ScriptEngine").mkdir(parents=True); (d / "BepInEx/plugins/ScriptEngine/ScriptEngine.dll").write_bytes(b"MZ")
    (built / "M2WSmoke.pdb").write_bytes(b"BSJB")
    r = checks.reload(g, built)
    assert r["copied"] == [str(d / "BepInEx/scripts/M2WSmoke.dll"), str(d / "BepInEx/scripts/M2WSmoke.pdb")] and "--setup" in r["how"]
    cfg = d / "BepInEx/config" / checks.SCRIPTENGINE_CFG; cfg.parent.mkdir(parents=True)
    cfg.write_text("[General]\nLoadOnStart = false\n\n[AutoReload]\nEnableFileSystemWatcher = false\n", encoding="utf-8")
    r = checks.reload(g, built, setup=True); assert "EnableFileSystemWatcher = true" in cfg.read_text(encoding="utf-8") and r.get("setup")
    r = checks.reload(g, built); assert "自己重载" in r["how"] and not r["warnings"]
    inst = d / "BepInEx/plugins/M2WSmoke"; inst.mkdir(); shutil.copy2(built / "M2WSmoke.dll", inst / "M2WSmoke.dll")
    reg = g._reg(); reg["valheim"]["M2WSmoke"] = {"path": str(inst), "from": "x", "at": "now"}; g._save_reg(reg)
    r = checks.reload(g, built); assert any("--game valheim M2WSmoke" in w for w in r["warnings"])   # loaded twice otherwise
    out = g.uninstall("scripts/M2WSmoke.dll"); assert out["pdb_to_trash"] and not (d / "BepInEx/scripts/M2WSmoke.pdb").exists()


def test_valheim_window_hint_and_no_settings_edit(tmp_path):
    g = games.get("valheim", sys_="linux", home=tmp_path / "home", env=_env(tmp_path, "linux"))
    assert quiet.window_plan(g) == [] and "-screen-fullscreen 0" in quiet.small_window(g)["how"]


# ---------------------------------------------------------------- the CLI round trip (Linux, macOS and Windows rules)
def _files(d: Path, skip: str):
    return {p: p.read_bytes() for p in d.rglob("*") if p.is_file() and skip not in p.relative_to(d).parts}


@pytest.mark.parametrize("sys_", ["linux", "mac", "windows"])
def test_take_home_valheim(tmp_path, sys_, monkeypatch, capsys, writes, assert_inside):
    monkeypatch.setattr(osdirs, "system", lambda: sys_)
    base = tmp_path / "Users" / "小雨" / "My Games" / "北欧 英灵神殿"; gd = base / "Steam Library" / "Valheim"
    man = _managed(gd, sys_); man.mkdir(parents=True); (man / "assembly_valheim.dll").write_bytes(b"MZ")
    (gd / "BepInEx/core").mkdir(parents=True); (gd / "BepInEx/core/BepInEx.dll").write_bytes(b"MZ")
    (gd / ("winhttp.dll" if sys_ == "windows" else "start_game_bepinex.sh")).write_bytes(b"x")
    (gd / "BepInEx/plugins").mkdir(); (gd / "BepInEx/plugins/她的插件.dll").write_bytes(b"MZ")
    (gd / "BepInEx/LogOutput.log").write_text("[Info   :   BepInEx] Loading [北欧长屋 1.0.0]\n", encoding="utf-8")
    for k, v in {"GAMEANYTHING_VALHEIM_DIR": gd, "GAMEANYTHING_DATA": base / "m2w data", "USERPROFILE": str(tmp_path / "Users" / "小雨")}.items(): monkeypatch.setenv(k, str(v))
    g0 = games.get("valheim"); u = g0.saves_dir(); assert Path(u).is_relative_to(tmp_path)
    (u / "worlds_local").mkdir(parents=True); (u / "characters_local").mkdir()
    (u / "worlds_local/我的世界.db").write_bytes(b"\x01\x02 v1"); (u / "characters_local/小雨.fch").write_bytes(b"\x03 v1")
    src = base / "build" / "Longhouse"; (src / "assets/长屋").mkdir(parents=True); (src / "Longhouse.dll").write_bytes(b"MZ\x00")
    (src / "assets/长屋/hall.json").write_text('{"name": "长屋"}', encoding="utf-8")
    name = "北欧 Longhouse"
    before = _files(gd, "plugins")
    with writes() as w:
        g = json.loads(_m2w(capsys, "native", "doctor", "--game", "valheim", "--json"))["games"][0]
        assert g["installed"] and g["loader"]["ok"] and Path(g["mods_dir"]) == gd / "BepInEx" / "plugins" and g["launch"] == ("script:" + str(gd / "start_game_bepinex.sh") if sys_ == "mac" else "steam://rungameid/892970")
        assert len(g["save_dirs"]) == 2 and "LOCAL world" in g["launch_hint"]
        out = _m2w(capsys, "native", "install", "--game", "valheim", src, "--name", name)
        assert "saves backed up first" in out
        dst = gd / "BepInEx" / "plugins" / name; assert (dst / "assets/长屋/hall.json").read_text(encoding="utf-8") == '{"name": "长屋"}'
        assert name in _m2w(capsys, "native", "mods", "--game", "valheim")
        assert "北欧长屋" in _m2w(capsys, "native", "log", "--game", "valheim", "--grep", "Loading")
        stamp = _m2w(capsys, "native", "backups", "--game", "valheim").split()[0]
        (u / "worlds_local/我的世界.db").write_bytes(b"broken"); (u / "characters_local/小雨.fch").unlink()
        _m2w(capsys, "native", "restore", "--game", "valheim", stamp)
        assert (u / "worlds_local/我的世界.db").read_bytes() == b"\x01\x02 v1" and (u / "characters_local/小雨.fch").read_bytes() == b"\x03 v1"
        _m2w(capsys, "native", "uninstall", "--game", "valheim", name)
        assert not dst.exists() and list((base / "m2w data" / "native" / ".trash").glob(f"*-valheim-uninstalled/{name}/Longhouse.dll"))
        with pytest.raises(SystemExit, match="不是 GameAnything 装的"): cli.main(["native", "uninstall", "--game", "valheim", "她的插件.dll"])
    assert_inside(w, tmp_path)
    after = _files(gd, "plugins")
    assert after == before and (gd / "BepInEx/plugins/她的插件.dll").is_file()


def _m2w(capsys, *args) -> str:
    rc = cli.main([str(a) for a in args]); assert rc in (0, None), rc
    return capsys.readouterr().out


# ---------------------------------------------------------------- a real compile (the lab's game on this server, read only)
def _dotnet():
    p = os.environ.get("GAMEANYTHING_TEST_DOTNET")
    return (p if p and os.access(p, os.X_OK) else None) or shutil.which("dotnet")


@pytest.mark.skipif(not (LAB_GAME and (LAB_GAME / "valheim_Data/Managed/assembly_valheim.dll").is_file() and (LAB_GAME / "BepInEx/core/BepInEx.dll").is_file() and _dotnet()),
                    reason="needs a Valheim with BepInExPack_Valheim and a .NET SDK (set GAMEANYTHING_TEST_VALHEIM_GAME; GAMEANYTHING_TEST_DOTNET if dotnet is not on PATH)")
def test_valheim_smoke_compiles_against_the_real_game(tmp_path, monkeypatch):
    """Reads the game's Managed/ and BepInEx/core/ only: the output goes to tmp; the game folder must be unchanged afterwards."""
    from gameanything.worlds import valheim
    def snap(): return {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in (LAB_GAME / "BepInEx").rglob("*") if p.is_file() and p.name != "LogOutput.log"}
    before = snap()
    env = {**os.environ, "PATH": str(Path(_dotnet()).parent) + os.pathsep + os.environ.get("PATH", ""), "GAMEANYTHING_VALHEIM_DIR": str(LAB_GAME),
           "GAMEANYTHING_DATA": str(tmp_path / "m2w data"), "DOTNET_CLI_HOME": str(tmp_path / "dotnet home")}
    monkeypatch.setenv("PATH", env["PATH"])
    g = games.get("valheim", sys_="linux", env=env)
    b = g.build(valheim.SMOKE, "M2WSmoke")
    st = Path(b["staged"]); assert (st / "M2WSmoke.dll").is_file() and (st / "M2WSmoke.pdb").is_file() and not b["warnings"]
    assert sorted(p.name for p in st.iterdir()) == ["M2WSmoke.dll", "M2WSmoke.pdb"]
    r = checks.check(g, st); assert r["ok"], r
    assert snap() == before


def test_valheim_mac_runs_the_start_script_under_rosetta(tmp_path):
    home = tmp_path / "home"; g = games.get("valheim", sys_="mac", home=home, env=_env(tmp_path, "mac"))
    d = _vh_game(home, "mac")
    (d / "start_game_bepinex.sh").write_text('#!/bin/sh\n# BepInEx start script\nexecutable_name="valheim.x86_64"\nexec "$executable_name"\n', encoding="utf-8")
    assert g.launch_url() == "script:" + str(d / "start_game_bepinex.sh")
    assert (d / "start_game_bepinex.sh").read_text(encoding="utf-8").count("M2W_ROSETTA") == 0          # a getter does not write
    g.prepare_launch()
    txt = (d / "start_game_bepinex.sh").read_text(encoding="utf-8")
    assert 'executable_name="valheim.app"' in txt and txt.count("M2W_ROSETTA=1 exec arch -x86_64") == 1 and txt.startswith("#!/bin/sh\n# m2w:")
    assert os.access(d / "start_game_bepinex.sh", os.X_OK)
    g.prepare_launch(); assert (d / "start_game_bepinex.sh").read_text(encoding="utf-8") == txt      # idempotent
    (d / "start_game_bepinex.sh").unlink(); assert g.launch_url() == "steam://rungameid/892970"      # no pack: nothing to run


def test_open_link_runs_a_script_detached(tmp_path, monkeypatch):
    sc = tmp_path / "run.sh"; sc.write_text("#!/bin/sh\n", encoding="utf-8"); calls = []
    monkeypatch.setattr(quiet.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
    assert quiet.open_link("script:" + str(sc), "mac") is True
    assert calls[0][0][0] == [str(sc)] and calls[0][1]["start_new_session"] is True and calls[0][1]["cwd"] == str(tmp_path)
