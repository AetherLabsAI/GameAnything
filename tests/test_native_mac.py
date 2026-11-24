"""What a real Mac test found (docs/cross-platform.md "Verified on real games", macOS rows, 2026-10-25), fixed in native mode and checked here with fakes only (no
game, no real input, no real window server):
  1. drive never clicks into another program: the windows in front of the game window (z-order + bounds) are checked first; covered ->
     refused (native_drive: always -> the game is brought to the front first); shot says when the game is covered
  2. games whose buttons ignore CGEventPostToPid clicks (Stardew Valley, Slay the Spire: Game.mac_click = "hid") get real cursor clicks,
     only while the game is the front window and she is away
  3. `gameanything native build --game stardew`: dotnet build with ModBuildConfig, deploy / zip off, staged with manifest.json
  4. `native close` on macOS asks the app to quit like Cmd-Q first; SIGTERM only after a while (Java games: SIGTERM at once)
  5. Valheim on macOS: no Steam launch option offered (m2w runs the start script itself since 0845c3f; why the option does not inject is open)
  6. the Steam launch option can be put on the clipboard (`doctor --copy`): pasting keeps straight quotes
"""
import os
import plistlib
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from gameanything import cli, osdirs, projects
from gameanything.native import games, hands, macapp, quiet
from test_native import _FakeRun, _env, _steam

POSIX = os.name != "nt"


class Proc:
    def __init__(self, pids=None): self.pids = list(pids or [])


def _game(tmp, gid="stardew", sys_="mac", proc=None):
    g = games.get(gid, sys_=sys_, home=tmp / "home", env=_env(tmp, sys_)); proc = proc or Proc()
    g.running = lambda: bool(proc.pids); g.pids = lambda: list(proc.pids)
    return g, proc


@pytest.fixture
def proj():
    e = projects.create("Mac 测试", "feature", game="stardew", build_mode="native"); return Path(e["path"])


def _pid(root): return projects.find(str(root))["id"]


def _open(root, g, proc, pid=None):
    quiet.set_policy(_pid(root), "always")

    def opener(url): proc.pids = [pid or os.getpid()]; return True
    r = quiet.launch(root, g, opener=opener, settle=5, sleep=lambda s: None); assert r["launched"]
    return r


GAME = {"id": 7, "pid": None, "layer": 0, "alpha": 1.0, "owner": "Stardew Valley", "title": "Stardew Valley", "x": 100, "y": 50, "w": 1280, "h": 720}


def _w(pid, x, y, w, h, owner="Claude", layer=0, alpha=1.0, id_=90):
    return {"id": id_, "pid": pid, "layer": layer, "alpha": alpha, "owner": owner, "title": owner, "x": x, "y": y, "w": w, "h": h}


class FakeMac:
    """The macOS backend's window list: `front` = the windows in front of the game window (front to back)."""
    name = "macOS"

    def __init__(self, front=None):
        self.front = list(front or []); self.sent = []; self.raised = 0; self.click_method = "pid"; self.on_raise = None

    def windows(self, pids): return [{**GAME, "pid": pids[0]}]
    def above(self, win): return list(self.front)
    def can_send(self, win, pids): return None
    def shot(self, win, out): out.write_bytes(b"\x89PNG fake"); return {}

    def bring_front(self, win):
        self.raised += 1
        if self.on_raise: self.on_raise(self)
        return True

    def send(self, win, step): self.sent.append((step, self.click_method))


# ---------------------------------------------------------------- 1. z-order + bounds
def test_covering_and_in_front():
    me = 4242; game = {**GAME, "pid": me}
    above = [_w(1, 0, 0, 3000, 30, "Menu bar", layer=24), _w(2, 0, 1000, 3000, 80, "Dock", layer=20),
             _w(3, 900, 600, 600, 400, "Claude"), _w(4, 0, 0, 3000, 2000, "invisible overlay", alpha=0.0),
             _w(me, 200, 200, 100, 100, "Stardew Valley")]                                  # the game's own popup
    r = lambda x, y: (game["x"] + x, game["y"] + y, 1, 1)
    assert hands.covering(above, [me], r(10, 10)) == []                                     # menu bar / Dock / transparent / its own: no
    assert [w["owner"] for w in hands.covering(above, [me], r(1000, 700))] == ["Claude"]    # under Claude's window
    assert [w["owner"] for w in hands.covering(above, [me], (100, 50, 1280, 720))] == ["Claude"]
    assert not hands.in_front(above, [me]) and hands.in_front(above[:2] + above[3:], [me])
    far = [_w(5, 2000, 0, 300, 300, "Notes")]                                                # in front, but elsewhere on the screen
    assert hands.covering(far, [me], (100, 50, 1280, 720)) == [] and not hands.in_front(far, [me])
    floating = [_w(6, 150, 60, 50, 50, "Stickies", layer=3)]
    assert hands.covering(floating, [me], r(60, 20)) and hands.in_front(floating, [me])


def test_a_covered_click_is_refused_keys_still_go(proj, tmp_path):
    g, proc = _game(tmp_path, "overcooked2"); _open(proj, g, proc)
    be = FakeMac([_w(1, 900, 600, 600, 400, "Claude")])
    quiet.set_policy(_pid(proj), "always", drive="idle")
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["key escape", "click 1000 700"], be=be, idle=lambda: 300.0)
    assert e.value.code == "covered" and e.value.pending and "Claude" in e.value.why and be.sent == [] and be.raised == 0
    r = hands.drive(proj, g, ["click 10 10"], be=be, idle=lambda: 300.0)                     # a point Claude's window does not cover
    assert r["done"] == 1 and r["click_method"] == "pid" and be.sent == [(("click", 10, 10, "left"), "pid")]
    be.sent.clear(); r = hands.drive(proj, g, ["key escape", "type hi"], be=be, idle=lambda: 300.0)   # keys are posted to the game process
    assert r["done"] == 2 and "click_method" not in r


def test_drive_always_brings_the_game_to_the_front_first(proj, tmp_path):
    g, proc = _game(tmp_path, "overcooked2"); _open(proj, g, proc)
    quiet.set_policy(_pid(proj), "always", drive="always")
    be = FakeMac([_w(1, 0, 0, 3000, 2000, "Claude")]); be.on_raise = lambda b: b.front.clear()
    r = hands.drive(proj, g, ["click 640 360"], be=be, idle=lambda: 0.0, sleep=lambda s: None)
    assert be.raised == 1 and r["done"] == 1
    be = FakeMac([_w(1, 0, 0, 3000, 2000, "Claude", layer=3)])                                # raising did not help (a floating window)
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["click 640 360"], be=be, idle=lambda: 0.0, sleep=lambda s: None)
    assert e.value.code == "covered" and be.raised == 1 and be.sent == []


def test_a_window_that_comes_up_mid_run_stops_the_clicks(proj, tmp_path):
    g, proc = _game(tmp_path, "overcooked2"); _open(proj, g, proc); be = FakeMac()
    quiet.set_policy(_pid(proj), "always", drive="idle")
    orig = be.send

    def send(win, step):
        orig(win, step); be.front.append(_w(1, 0, 0, 3000, 2000, "Notification"))
    be.send = send
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["click 1 1", "click 2 2"], be=be, idle=lambda: 300.0, sleep=lambda s: None)
    assert e.value.code == "covered" and "做了 1 步" in e.value.why and len(be.sent) == 1


# ---------------------------------------------------------------- 2. real cursor clicks for the games that need them
def test_stardew_and_sts_click_with_the_real_cursor():
    assert games.Stardew.mac_click == "hid" and games.SlayTheSpire.mac_click == "hid"
    assert games.Overcooked2.mac_click == "pid" and games.Game.mac_click == "pid"


def test_hid_clicks_only_in_front_and_while_she_is_away(proj, tmp_path):
    g, proc = _game(tmp_path, "stardew"); _open(proj, g, proc)
    quiet.set_policy(_pid(proj), "always", drive="idle")
    be = FakeMac([_w(1, 2000, 0, 300, 300, "Notes")])                                         # not covering, but Notes is the front app
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["click 640 360"], be=be, idle=lambda: 300.0)
    assert e.value.code == "not_frontmost" and "Notes" in e.value.why and be.sent == []
    r = hands.drive(proj, g, ["click 640 360"], be=be, idle=lambda: 300.0, click="pid")       # her override: posted to the process
    assert r["click_method"] == "pid" and be.sent == [(("click", 640, 360, "left"), "pid")]
    be = FakeMac()                                                                              # the game is in front
    r = hands.drive(proj, g, ["click 640 360", "key escape"], be=be, idle=lambda: 300.0)
    assert r["click_method"] == "hid" and be.sent[0] == (("click", 640, 360, "left"), "hid")
    quiet._update(proj, lambda L: L["launches"][-1].pop("drove_until", None))                # (else her input 3 s ago would count as m2w's own)
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["click 640 360"], be=FakeMac(), idle=lambda: 3.0)   # she is there
    assert e.value.code == "active"
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["click 1 1"], be=FakeMac(), idle=lambda: None)
    assert e.value.code == "unknown" and not e.value.pending
    quiet.set_policy(_pid(proj), "always", drive="always")          # her rule 2026-10-29: 「我在用电脑时也可以」 covers her cursor too
    r = hands.drive(proj, g, ["click 640 360", "key escape"], be=FakeMac(), idle=lambda: 3.0)
    assert r["done"] == 2 and r["click_method"] == "hid"
    with pytest.raises(ValueError): hands.drive(proj, g, ["click 1 1"], be=FakeMac(), idle=lambda: 300.0, click="usb")


def test_shot_says_when_the_game_is_covered(proj, tmp_path):
    g, proc = _game(tmp_path, "overcooked2"); _open(proj, g, proc)
    r = hands.shot(proj, g, be=FakeMac([_w(1, 900, 600, 600, 400, "Claude")]))
    assert r["covered_by"] == ["Claude"] and "Claude" in r["warning"]
    assert "covered_by" not in hands.shot(proj, g, be=FakeMac([_w(1, 2000, 0, 300, 300, "Notes")]))


def test_cli_drive_click_option(proj, tmp_path, monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(hands, "drive", lambda root, g, steps, click=None: seen.update(click=click, steps=steps) or
                        {"done": 1, "window": {"id": 7, "title": "Stardew Valley"}, "backend": "macOS", "why": "away", "click_method": "pid"})
    assert cli.main(["native", "drive", "--project", str(proj), "--click", "pid", "click 1 2"]) == 0
    assert seen == {"click": "pid", "steps": ["click 1 2"]} and "clicks: pid" in capsys.readouterr().out


# ---------------------------------------------------------------- 3. Stardew native build
def _sd_game(home, sys_="mac"):
    if sys_ == "mac":
        app = _steam(home, "mac", 413150, "Stardew Valley"); d = app / "Contents" / "MacOS"; d.mkdir(parents=True)   # her Mac: common/Stardew Valley/Contents/MacOS
        with open(app / "Contents" / "Info.plist", "wb") as fh: plistlib.dump({"CFBundleIdentifier": "com.chucklefish.stardewvalley"}, fh)
    else: d = _steam(home, sys_, 413150, "Stardew Valley")
    for f in ("Stardew Valley.dll", "StardewModdingAPI.dll", "MonoGame.Framework.dll"): (d / f).write_bytes(b"MZ")
    (d / "smapi-internal").mkdir(); (d / "smapi-internal" / "0Harmony.dll").write_bytes(b"MZ")
    return d


def _sd_src(tmp, csproj=None, manifest=None):
    src = tmp / "星露谷 mod" / "Hello"; (src / "assets").mkdir(parents=True); (src / "bin/Debug").mkdir(parents=True)
    (src / "ModEntry.cs").write_text("class ModEntry {}", encoding="utf-8"); (src / "assets" / "说明.txt").write_text("你好", encoding="utf-8")
    (src / "bin/Debug/Old.dll").write_bytes(b"MZ")
    (src / "manifest.json").write_text(manifest or '{\n // a comment\n "Name": "Hello", "UniqueID": "m2w.Hello", "EntryDll": "Hello.dll",\n}', encoding="utf-8")
    if csproj: (src / "Hello.csproj").write_text(csproj, encoding="utf-8")
    return src


def _fake_sd_dotnet(monkeypatch):
    monkeypatch.setattr(games, "dotnet", lambda *a, **k: {"ok": True, "path": "/usr/local/share/dotnet/dotnet", "sdks": ["8.0.100"]})

    def make(args, kw):
        o = Path(args[args.index("-o") + 1]); o.mkdir(parents=True)
        import re
        asm = re.search(r"<AssemblyName>(\w+)</AssemblyName>", Path(args[2]).read_text(encoding="utf-8")).group(1)
        for n in (f"{asm}.dll", f"{asm}.pdb", "Newtonsoft.Extra.dll", "StardewModdingAPI.dll", "MonoGame.Framework.dll", "0Harmony.dll"): (o / n).write_bytes(b"MZ")
    fake = _FakeRun(make); monkeypatch.setattr(games.subprocess, "run", fake)
    return fake


@pytest.mark.parametrize("sys_", ["mac", "linux"])
def test_stardew_build_with_modbuildconfig(tmp_path, monkeypatch, sys_):
    home = tmp_path / "home"; d = _sd_game(home, sys_)
    g = games.get("stardew", sys_=sys_, home=home, env=_env(tmp_path, sys_))
    fake = _fake_sd_dotnet(monkeypatch)
    b = g.build(_sd_src(tmp_path))
    args = fake.calls[0][0]
    assert args[1] == "build" and f"-p:GamePath={d}" in args and "-p:EnableModDeploy=false" in args and "-p:EnableModZip=false" in args
    proj = Path(args[2]).read_text(encoding="utf-8")
    assert "Pathoschild.Stardew.ModBuildConfig" in proj and f'Version="{games.MODBUILDCONFIG}"' in proj and "<TargetFramework>net6.0</TargetFramework>" in proj
    assert (Path(args[2]).parent / "ModEntry.cs").is_file() and not (Path(args[2]).parent / "bin").exists()
    st = Path(b["staged"]); assert st.name == "Hello" and Path(b["dll"]) == st / "Hello.dll" and not b["warnings"]
    assert sorted(p.relative_to(st).as_posix() for p in st.rglob("*") if p.is_file()) == [
        "Hello.dll", "Hello.pdb", "Newtonsoft.Extra.dll", "assets/说明.txt", "manifest.json"]      # never the game's / SMAPI's DLLs
    assert not (d / "Mods").exists()                                                            # build writes nothing into the game
    g.check_installable(st)
    assert g.install(st)["path"] == str(d / "Mods" / "Hello") and (d / "Mods/Hello/manifest.json").is_file()


def test_stardew_build_refuses_what_smapi_would_not_load(tmp_path, monkeypatch):
    home = tmp_path / "home"; d = _sd_game(home, "linux")
    g = games.get("stardew", sys_="linux", home=home, env=_env(tmp_path, "linux")); _fake_sd_dotnet(monkeypatch)
    src = _sd_src(tmp_path); (src / "manifest.json").unlink()
    with pytest.raises(games.NativeError, match="manifest.json"): g.build(src)
    shutil.rmtree(src.parent)
    with pytest.raises(games.NativeError, match="EntryDll"): g.build(_sd_src(tmp_path, manifest='{"UniqueID": "a.b"}'))
    shutil.rmtree(tmp_path / "星露谷 mod")
    own = ('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><AssemblyName>Hello</AssemblyName><TargetFramework>net6.0</TargetFramework></PropertyGroup>'
           '<ItemGroup><PackageReference Include="Pathoschild.Stardew.ModBuildConfig" Version="4.3.0" /></ItemGroup></Project>')
    with pytest.raises(games.NativeError, match="EntryDll 是 Other.dll"): g.build(_sd_src(tmp_path, csproj=own, manifest='{"UniqueID": "a.b", "EntryDll": "Other.dll"}'))
    shutil.rmtree(tmp_path / "星露谷 mod")
    with pytest.raises(games.NativeError, match="ModBuildConfig"):
        g.build(_sd_src(tmp_path, csproj='<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><AssemblyName>Hello</AssemblyName></PropertyGroup></Project>'))
    shutil.rmtree(tmp_path / "星露谷 mod")
    b = g.build(_sd_src(tmp_path, manifest='{"UniqueID": "a.b", "EntryDll": "Other.dll"}'))     # no csproj: the generated one is named after EntryDll
    assert Path(b["dll"]).name == "Other.dll"
    shutil.rmtree(tmp_path / "星露谷 mod")
    fake = _fake_sd_dotnet(monkeypatch); b = g.build(_sd_src(tmp_path, csproj=own))
    assert Path(fake.calls[0][0][2]).name == "Hello.csproj" and 'Version="4.3.0"' in Path(fake.calls[0][0][2]).read_text(encoding="utf-8")
    assert Path(b["dll"]).name == "Hello.dll"
    (d / "StardewModdingAPI.dll").unlink()
    with pytest.raises(games.NativeError, match="SMAPI"): g.build(_sd_src(tmp_path / "again"))


def test_cli_stardew_build_and_install(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"; d = _sd_game(home, "linux"); _fake_sd_dotnet(monkeypatch)
    monkeypatch.setattr(osdirs, "system", lambda: "linux"); monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("GAMEANYTHING_STARDEW_DIR", str(d)); monkeypatch.setenv("GAMEANYTHING_DATA", str(tmp_path / "m2w"))
    assert cli.main(["native", "build", "--game", "stardew", str(_sd_src(tmp_path)), "--install"]) == 0
    out = capsys.readouterr().out
    assert "[native] built" in out and "installed Hello" in out and (d / "Mods/Hello/Hello.dll").is_file()


def _cp_pack(tmp, content=True, manifest=None):
    src = tmp / "星露谷 mod" / "MyPack"; (src / "assets").mkdir(parents=True); (src / ".git").mkdir()
    (src / "manifest.json").write_text(manifest or '{"Name": "My pack", "Author": "m2w", "Version": "1.0.0", "UniqueID": "m2w.MyPack",'
                                       ' "ContentPackFor": {"UniqueID": "Pathoschild.ContentPatcher"}}', encoding="utf-8")
    if content: (src / "content.json").write_text('{"Format": "2.9.0", "Changes": []}', encoding="utf-8")
    (src / "assets" / "花.png").write_bytes(b"PNG"); (src / ".git" / "HEAD").write_text("x", encoding="utf-8")
    return src


def test_stardew_content_pack_builds_without_compiling(tmp_path, monkeypatch):
    """Sandbox recheck 2026-11-01 (#57): `lab sandbox build` (= native build --install) refused a content pack ("no .cs files"), the only
    way a builder installs into her sandbox; the skill prefers content packs for Stardew content."""
    home = tmp_path / "home"; d = _sd_game(home, "linux")
    g = games.get("stardew", sys_="linux", home=home, env=_env(tmp_path, "linux")); fake = _fake_sd_dotnet(monkeypatch)
    b = g.build(_cp_pack(tmp_path))
    assert not fake.calls and b["dll"] is None and b["content_pack"] == "Pathoschild.ContentPatcher"   # no dotnet, no SMAPI needed
    st = Path(b["staged"])
    assert sorted(p.relative_to(st).as_posix() for p in st.rglob("*") if p.is_file()) == ["assets/花.png", "content.json", "manifest.json"]
    assert any("Pathoschild.ContentPatcher" in w for w in b["warnings"])            # not installed in Mods/ yet: said
    cp = d / "Mods" / "ContentPatcher"; cp.mkdir(parents=True)
    (cp / "manifest.json").write_text('{"UniqueID": "Pathoschild.ContentPatcher", "Version": "2.9.1"}', encoding="utf-8")
    shutil.rmtree(tmp_path / "星露谷 mod")
    assert not g.build(_cp_pack(tmp_path))["warnings"]
    shutil.rmtree(tmp_path / "星露谷 mod")
    assert any("content.json" in w for w in g.build(_cp_pack(tmp_path, content=False))["warnings"])
    shutil.rmtree(tmp_path / "星露谷 mod")
    with pytest.raises(games.NativeError, match="ContentPackFor"): g.build(_cp_pack(tmp_path, manifest='{"UniqueID": "a.b"}'))


def test_cli_installs_a_content_pack(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"; d = _sd_game(home, "linux"); _fake_sd_dotnet(monkeypatch)
    monkeypatch.setattr(osdirs, "system", lambda: "linux"); monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("GAMEANYTHING_STARDEW_DIR", str(d)); monkeypatch.setenv("GAMEANYTHING_DATA", str(tmp_path / "m2w"))
    assert cli.main(["native", "build", "--game", "stardew", str(_cp_pack(tmp_path)), "--install"]) == 0
    out = capsys.readouterr().out
    assert "content pack for Pathoschild.ContentPatcher: nothing to compile" in out and "installed MyPack" in out
    assert (d / "Mods/MyPack/content.json").is_file() and not (d / "Mods/MyPack/.git").exists()



def test_cli_installs_a_content_pack_named_the_usual_cp_way(tmp_path, monkeypatch, capsys):
    """Round 10 (2026-11-02): "[CP] Name" (Content Patcher's naming custom) was refused as "mod 名字不合适"; her decision: allow brackets
    for Stardew. Other games keep the old rule; a path separator is still refused."""
    home = tmp_path / "home"; d = _sd_game(home, "linux"); _fake_sd_dotnet(monkeypatch)
    monkeypatch.setattr(osdirs, "system", lambda: "linux"); monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("GAMEANYTHING_STARDEW_DIR", str(d)); monkeypatch.setenv("GAMEANYTHING_DATA", str(tmp_path / "m2w"))
    src = _cp_pack(tmp_path); cp = src.with_name("[CP] MyPack"); src.rename(cp)
    assert cli.main(["native", "build", "--game", "stardew", str(cp), "--install"]) == 0
    assert "installed [CP] MyPack" in capsys.readouterr().out and (d / "Mods/[CP] MyPack/content.json").is_file()
    g = games.get("stardew", sys_="linux", home=home, env=_env(tmp_path, "linux"))
    for bad in ("a/b", "..", ".hidden", "x*y"):
        with pytest.raises(games.NativeError, match="名字不合适"): g._check_name(bad)
    with pytest.raises(games.NativeError, match="名字不合适"): games.get("sims4", sys_="linux", home=home)._check_name("[CP] x")

_SD = os.environ.get("GAMEANYTHING_TEST_STARDEW_GAME")
REAL_SD = Path(_SD) if _SD else None


def _dotnet():
    p = os.environ.get("GAMEANYTHING_TEST_DOTNET")
    return (p if p and os.access(p, os.X_OK) else None) or shutil.which("dotnet")


@pytest.mark.skipif(not (REAL_SD and (REAL_SD / "Stardew Valley.dll").is_file() and (REAL_SD / "StardewModdingAPI.dll").is_file() and _dotnet()),
                    reason="needs a Stardew Valley with SMAPI and a .NET SDK (set GAMEANYTHING_TEST_STARDEW_GAME; GAMEANYTHING_TEST_DOTNET if dotnet is not on PATH)")
def test_stardew_compiles_against_the_real_game(tmp_path, monkeypatch):
    """Reads the game only (deploy / zip off): the game folder must be unchanged. NuGet needs the network for ModBuildConfig."""
    def snap(): return {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in REAL_SD.rglob("*") if p.is_file() and "ErrorLogs" not in p.parts}
    before = snap()
    src = tmp_path / "mod" / "Hello"; src.mkdir(parents=True)
    (src / "ModEntry.cs").write_text("using StardewModdingAPI;\nnamespace Hello { public class ModEntry : Mod { public override void Entry(IModHelper helper) "
                                     "{ Monitor.Log(\"[M2W-smoke] loaded\", LogLevel.Info); } } }\n", encoding="utf-8")
    (src / "manifest.json").write_text('{"Name": "Hello", "Author": "m2w", "Version": "1.0.0", "UniqueID": "m2w.Hello", "EntryDll": "Hello.dll"}', encoding="utf-8")
    monkeypatch.setenv("PATH", str(Path(_dotnet()).parent) + os.pathsep + os.environ.get("PATH", ""))
    env = {**os.environ, "GAMEANYTHING_STARDEW_DIR": str(REAL_SD), "GAMEANYTHING_DATA": str(tmp_path / "m2w data"), "DOTNET_CLI_HOME": str(tmp_path / "dotnet home"),
           "NUGET_PACKAGES": os.environ.get("NUGET_PACKAGES") or str(Path.home() / ".nuget/packages")}
    g = games.get("stardew", sys_="linux", env=env)
    try: b = g.build(src)
    except games.NativeError as e:
        if "联网" in str(e) or "NU1301" in str(e): pytest.skip(f"no network for NuGet: {e}")
        raise
    st = Path(b["staged"]); assert sorted(p.name for p in st.iterdir()) in (["Hello.dll", "manifest.json"], ["Hello.dll", "Hello.pdb", "manifest.json"])
    assert snap() == before


# ---------------------------------------------------------------- 4. close: the app's own Quit first on macOS
def test_bundle_of_the_game(tmp_path):
    home = tmp_path / "home"; _sd_game(home, "mac")
    g = games.get("stardew", sys_="mac", home=home, env=_env(tmp_path, "mac"))
    assert g.mac_app_bundle().name == "Stardew Valley" and g.mac_bundle_id() == "com.chucklefish.stardewvalley"
    assert games.get("overcooked2", sys_="mac", home=home, env=_env(tmp_path, "mac")).mac_bundle_id() is None      # not installed
    assert games.Stardew.mac_quit == "app" and games.SlayTheSpire.mac_quit == "signal" and games.Minecraft.mac_quit == "app"


def test_macapp_osascript_and_clipboard():
    calls = []
    run = lambda args, timeout=20: calls.append(args) or subprocess.CompletedProcess(args, 0, "", "")
    assert macapp.quit_bundle("com.chucklefish.stardewvalley", run=run)
    assert calls == [["osascript", "-e", 'tell application id "com.chucklefish.stardewvalley" to quit']]
    assert not macapp.quit_bundle('x" to do shell script "rm', run=run) and len(calls) == 1          # never a script from a bad id
    got = []; assert macapp.copy('"/a b/run_bepinex.sh" %command%', run=lambda t: got.append(t) or True) and got == ['"/a b/run_bepinex.sh" %command%']
    if sys.platform != "darwin": assert macapp.terminate(os.getpid()) is False and macapp.activate(os.getpid()) is False   # no AppKit: False, no crash


def _child():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])


@pytest.mark.skipif(not POSIX, reason="a real child process stands in for the game")
def test_close_on_mac_quits_like_cmd_q_first(proj, tmp_path, monkeypatch):
    g, proc = _game(tmp_path, "stardew"); game = _child(); sigterm = []
    real_term = quiet._terminate
    monkeypatch.setattr(quiet, "_terminate", lambda pid: sigterm.append(pid) or real_term(pid))
    try:
        _open(proj, g, proc, pid=game.pid)
        asked = []
        monkeypatch.setattr(quiet, "_mac_quit", lambda g_, pid, ours: asked.append((pid, ours)) or (os.kill(pid, signal.SIGINT) or "NSRunningApplication"))
        c = quiet.close(proj, g, sleep=lambda s: (game.poll(), time.sleep(0.05)))
        assert c["closed"] and c["how"] == "NSRunningApplication" and asked == [(game.pid, True)] and sigterm == []
        assert quiet.ledger(proj)["launches"][-1]["how"] == "NSRunningApplication"
    finally:
        if game.poll() is None: game.kill()


@pytest.mark.skipif(not POSIX, reason="a real child process stands in for the game")
def test_close_on_mac_falls_back_to_sigterm(proj, tmp_path, monkeypatch):
    g, proc = _game(tmp_path, "stardew"); game = _child()
    monkeypatch.setattr(quiet, "QUIT_WAIT_SECS", 0.3)
    try:
        _open(proj, g, proc, pid=game.pid)
        monkeypatch.setattr(quiet, "_mac_quit", lambda g_, pid, ours: "NSRunningApplication")      # asked, but the game stays open
        c = quiet.close(proj, g, sleep=lambda s: (game.poll(), time.sleep(0.05)))
        assert c["closed"] and c["how"] == "NSRunningApplication -> SIGTERM"
    finally:
        if game.poll() is None: game.kill()
    g, proc = _game(tmp_path, "slay_the_spire"); game = _child()                                  # a JVM: SIGTERM at once
    try:
        _open(proj, g, proc, pid=game.pid)
        monkeypatch.setattr(quiet, "_mac_quit", lambda *a: pytest.fail("a Java game is closed with SIGTERM"))
        c = quiet.close(proj, g, sleep=lambda s: (game.poll(), time.sleep(0.05)))
        assert c["closed"] and c["how"] == "SIGTERM"
    finally:
        if game.poll() is None: game.kill()


def test_mac_quit_uses_applescript_only_for_our_copy(tmp_path, monkeypatch):
    home = tmp_path / "home"; _sd_game(home, "mac"); g = games.get("stardew", sys_="mac", home=home, env=_env(tmp_path, "mac"))
    monkeypatch.setattr(macapp, "terminate", lambda pid: False); asked = []
    monkeypatch.setattr(macapp, "quit_bundle", lambda bid, run=None: asked.append(bid) or True)
    assert quiet._mac_quit(g, 123, only_ours=False) == "" and asked == []
    assert quiet._mac_quit(g, 123, only_ours=True) == "AppleScript" and asked == ["com.chucklefish.stardewvalley"]
    monkeypatch.setattr(macapp, "terminate", lambda pid: True)
    assert quiet._mac_quit(g, 123, only_ours=True) == "NSRunningApplication"


# ---------------------------------------------------------------- 5 / 6. doctor: Valheim on macOS, the launch option on the clipboard
def _bepinex_mac(home, appid, installdir, app, managed_marker, script):
    d = _steam(home, "mac", appid, installdir); m = d / app / "Contents/Resources/Data/Managed"; m.mkdir(parents=True)
    (m / managed_marker).write_bytes(b"MZ"); (d / "BepInEx/core").mkdir(parents=True); (d / "BepInEx/core/BepInEx.dll").write_bytes(b"MZ")
    (d / script).write_text("#!/bin/sh\n", encoding="utf-8")
    return d


def test_doctor_on_mac(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home 小雨"
    monkeypatch.setattr(osdirs, "system", lambda: "mac"); monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("GAMEANYTHING_DATA", str(tmp_path / "m2w"))
    oc = _bepinex_mac(home, 728880, "Overcooked! 2", "Overcooked2.app", "Assembly-CSharp.dll", "run_bepinex.sh")
    _bepinex_mac(home, 892970, "Valheim", "valheim.app", "assembly_valheim.dll", "start_game_bepinex.sh")
    assert cli.main(["native", "doctor", "--game", "valheim"]) == 0
    out = capsys.readouterr().out
    assert "start_game_bepinex.sh itself" in out and "%command%" not in out and "hardened" not in out and "\n  option " not in out   # 0845c3f: m2w runs it
    assert cli.main(["native", "doctor", "--game", "overcooked2"]) == 0
    out = capsys.readouterr().out
    want = f'"{oc / "run_bepinex.sh"}" %command%'
    assert f"option {want}" in out and "PASTE it" in out and "--copy" in out
    got = []; monkeypatch.setattr(macapp, "copy", lambda t, run=None: got.append(t) or True)
    assert cli.main(["native", "doctor", "--game", "overcooked2", "--copy"]) == 0 and got == [want]
    assert "Cmd-V" in capsys.readouterr().err
    with pytest.raises(SystemExit, match="has none here"): cli.main(["native", "doctor", "--game", "valheim", "--copy"])
    with pytest.raises(SystemExit, match="needs --game"): cli.main(["native", "doctor", "--copy"])


def test_shot_finds_a_full_screen_game_in_its_own_space():
    """Cities: Skylines' first start on her Mac (2026-10-31) went full screen into its own Space: no on-screen window, but
    `screencapture -l <id>` still takes it. shot looks off screen too; drive (clicks) does not."""
    class Spaces:
        def windows(self, pids): return []                                    # nothing on the current desktop
        def _list(self, option, rel=0, pids=None):
            return [{"id": 9, "pid": 42, "layer": 0, "w": 1470, "h": 37}, {"id": 8, "pid": 42, "layer": 0, "w": 1470, "h": 956}]
    assert hands._window(Spaces(), [42], any_space=True)["id"] == 8
    with pytest.raises(hands.Refused) as e: hands._window(Spaces(), [42])
    assert e.value.code == "no_window"
