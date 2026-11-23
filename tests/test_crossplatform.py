"""What a real user does on Windows, macOS and Linux, with fake game folders and fake saves in tmp dirs (no real game, no network):
per-system default folders, the take-home round trip (backup -> install -> mods -> restore -> uninstall) through the CLI, paths with
spaces / Chinese / more than 260 characters, UTF-8 text and line endings, the conversation in Chinese, and the browser UI."""
import ast
import io
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PureWindowsPath
from urllib.parse import quote

import pytest
import yaml

from gameanything import cli, osdirs, projects, transfer
from gameanything.conversation import Thread
from gameanything.native import cgs, games, steam

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "gameanything"
WIN_HOME = "C:\\Users\\小雨"


def win(p) -> PureWindowsPath:
    """A path computed for Windows, compared the way Windows would (both separators, any host system)."""
    return PureWindowsPath(str(p))


def m2w(capsys, *args) -> str:
    """Run the CLI in this process (so the write audit sees it) -> stdout."""
    rc = cli.main([str(a) for a in args])
    assert rc in (0, None), rc
    return capsys.readouterr().out


def m2w_proc(*args, input=None, timeout=60) -> subprocess.CompletedProcess:
    """Run the CLI as its own process with a pipe for stdout, the way an agent runs it; output must be UTF-8 on every system."""
    r = subprocess.run([sys.executable, "-c", "import sys; from gameanything.cli import main; sys.exit(main())", *map(str, args)],
                       input=input.encode("utf-8") if input is not None else None, capture_output=True, timeout=timeout, env=dict(os.environ))
    r.out = r.stdout.decode("utf-8"); r.err = r.stderr.decode("utf-8")
    return r


@pytest.fixture
def not_running(monkeypatch):
    monkeypatch.setattr(games.Game, "running", lambda self: False)


def test_json_for_stdout_is_ascii_on_windows(monkeypatch, capsys):
    # Windows PowerShell 5.1 decodes a native command's output with the console code page: `--json > f` inside OpenCode turned
    # 发按键 into "σÅæµîë" (a real Windows 11 PC, 2026-11-02). ASCII JSON reads the same everywhere; macOS / Linux stay readable.
    monkeypatch.setattr(osdirs, "system", lambda: "windows")
    s = osdirs.json_text({"name": "发按键"}, indent=1); assert s.isascii() and json.loads(s) == {"name": "发按键"}
    monkeypatch.setattr(osdirs, "system", lambda: "mac")
    assert "发按键" in osdirs.json_text({"name": "发按键"})
    monkeypatch.setattr(osdirs, "system", lambda: "windows")             # a real --json command goes through it
    assert cli.main(["native", "minecraft", "status", "--json"]) == 0
    out = capsys.readouterr().out; assert out.isascii() and json.loads(out)["signed_in"] is False


# ---------------------------------------------------------------- default folders per system
@pytest.mark.skipif(os.name != "nt", reason="Windows file redirection of packaged apps")
def test_windows_package_redirection_is_found(tmp_path, monkeypatch):
    # inside the Claude desktop app (MSIX) a new AppData folder lands in Packages/<app>/LocalCache (a real Windows 11 PC, 2026-11-01)
    local = tmp_path / "Local"; monkeypatch.setenv("LOCALAPPDATA", str(local))
    (local / "Packages" / "Claude_x" / "LocalCache" / "Local" / f"gameanything-probe-{os.getpid()}").mkdir(parents=True)
    assert osdirs.windows_package() == "Claude_x" and not (local / f"gameanything-probe-{os.getpid()}").exists()
    (local / "Packages" / "Claude_x" / "LocalCache" / "Local" / f"gameanything-probe-{os.getpid()}").rmdir()
    assert osdirs.windows_package() is None


def test_windows_default_folders():
    env = {"APPDATA": WIN_HOME + "\\AppData\\Roaming", "LOCALAPPDATA": WIN_HOME + "\\AppData\\Local", "GAMEANYTHING_DATA": "unused"}
    sd = games.get("stardew", sys_="windows", home=Path(WIN_HOME), env=env)
    assert win(sd.saves_dir()) == PureWindowsPath(WIN_HOME + r"\AppData\Roaming\StardewValley\Saves")
    assert win(sd.log_files()[0]) == PureWindowsPath(WIN_HOME + r"\AppData\Roaming\StardewValley\ErrorLogs\SMAPI-latest.txt")
    mc = games.get("minecraft", sys_="windows", home=Path(WIN_HOME), env=env)
    assert win(mc.mods_dir()) == PureWindowsPath(WIN_HOME + r"\AppData\Roaming\.minecraft\mods")
    assert win(mc.saves_dir()) == PureWindowsPath(WIN_HOME + r"\AppData\Roaming\.minecraft\saves")
    cs = games.get("cities_skylines", sys_="windows", home=Path(WIN_HOME), env=env)
    assert win(cs.mods_dir()) == PureWindowsPath(WIN_HOME + r"\AppData\Local\Colossal Order\Cities_Skylines\Addons\Mods")
    assert win(cs.cgs_file()) == PureWindowsPath(WIN_HOME + r"\AppData\Local\Colossal Order\Cities_Skylines\userGameState.cgs")
    assert win(cs.log_files()[-1]) == PureWindowsPath(WIN_HOME + r"\AppData\LocalLow\Colossal Order\Cities_ Skylines\Player.log")
    # without %APPDATA% / %LOCALAPPDATA% (a stripped environment): the profile's own AppData
    sd2 = games.get("stardew", sys_="windows", home=Path(WIN_HOME), env={})
    assert win(sd2.saves_dir()) == PureWindowsPath(WIN_HOME + r"\AppData\Roaming\StardewValley\Saves")
    cs2 = games.get("cities_skylines", sys_="windows", home=Path(WIN_HOME), env={})
    assert win(cs2.saves_dir()) == PureWindowsPath(WIN_HOME + r"\AppData\Local\Colossal Order\Cities_Skylines\Saves")
    s4 = games.get("sims4", sys_="windows", home=Path(WIN_HOME), env={"USERPROFILE": WIN_HOME})
    assert win(s4.mods_dir()) == PureWindowsPath(WIN_HOME + r"\Documents\Electronic Arts\The Sims 4\Mods")
    assert win(s4.saves_dir()) == PureWindowsPath(WIN_HOME + r"\Documents\Electronic Arts\The Sims 4\saves")
    steams = [win(p) for p in steam.candidates("windows", Path(WIN_HOME), {"ProgramFiles(x86)": "D:\\Program Files (x86)"})]
    assert steams[0] == PureWindowsPath(r"D:\Program Files (x86)\Steam") and PureWindowsPath(r"C:\Program Files (x86)\Steam") in steams
    # dict(os.environ) on Windows has upper-case names (a real Windows 11 PC, 2026-11-01): the variable was never read
    steams = [win(p) for p in steam.candidates("windows", Path(WIN_HOME), {"PROGRAMFILES(X86)": "D:\\Program Files (x86)"})]
    assert steams[0] == PureWindowsPath(r"D:\Program Files (x86)\Steam")


def test_mac_default_folders(tmp_path):
    home = tmp_path / "Users" / "小雨"
    sd = games.get("stardew", sys_="mac", home=home, env={})
    assert sd.saves_dir() == home / ".config/StardewValley/Saves"           # Stardew on macOS keeps saves in ~/.config, like Linux
    mc = games.get("minecraft", sys_="mac", home=home, env={})
    assert mc.mods_dir() == home / "Library/Application Support/minecraft/mods"
    cs = games.get("cities_skylines", sys_="mac", home=home, env={})
    assert cs.mods_dir() == home / "Library/Application Support/Colossal Order/Cities_Skylines/Addons/Mods"
    assert cs.log_files() == [home / "Library/Logs/Unity/Player.log"] and not cs.compiles_source()
    assert steam.candidates("mac", home, {}) == [home / "Library/Application Support/Steam"]


def test_linux_default_folders(tmp_path):
    home = tmp_path / "home" / "wenyi"
    sd = games.get("stardew", sys_="linux", home=home, env={})
    assert sd.saves_dir() == home / ".config/StardewValley/Saves"
    assert games.get("stardew", sys_="linux", home=home, env={"XDG_CONFIG_HOME": str(tmp_path / "cfg")}).saves_dir() == tmp_path / "cfg/StardewValley/Saves"
    assert games.get("minecraft", sys_="linux", home=home, env={}).mods_dir() == home / ".minecraft/mods"
    cs = games.get("cities_skylines", sys_="linux", home=home, env={})
    assert cs.mods_dir() == home / ".local/share/Colossal Order/Cities_Skylines/Addons/Mods" and cs.compiles_source()
    assert cs.log_files() == [home / ".config/unity3d/Colossal Order/Cities_ Skylines/Player.log"]
    assert home / ".local/share/Steam" in steam.candidates("linux", home, {})


def test_m2w_own_folders(monkeypatch, tmp_path):
    monkeypatch.setattr(osdirs, "system", lambda: "windows")
    monkeypatch.setenv("APPDATA", WIN_HOME + "\\AppData\\Roaming"); monkeypatch.setenv("LOCALAPPDATA", WIN_HOME + "\\AppData\\Local")
    assert win(osdirs.config_home()) == PureWindowsPath(WIN_HOME + r"\AppData\Roaming\gameanything")
    assert win(osdirs.data_home()) == PureWindowsPath(WIN_HOME + r"\AppData\Local\gameanything")
    monkeypatch.setattr(osdirs, "system", lambda: "mac"); monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c"))
    assert osdirs.config_home() == tmp_path / "c" / "gameanything"


def test_running_check_uses_exact_names(monkeypatch):
    calls = []
    monkeypatch.setattr(games, "_run", lambda args, timeout=20: calls.append(args) or subprocess.CompletedProcess(args, 1, "", ""))
    monkeypatch.setattr(games.shutil, "which", lambda n: "/usr/bin/" + n)
    assert games.get("stardew", sys_="linux", env={}).running() is False
    # Linux pgrep -x compares with the 15-character process name (procps pgrep(1)): "StardewModdingAPI" would never match
    assert ["pgrep", "-x", "StardewModdingA"] in calls and all(len(a[2]) <= 15 for a in calls)
    calls.clear(); games.get("cities_skylines", sys_="windows", env={}).running()
    assert calls == [["tasklist", "/FO", "CSV", "/NH"]]                     # no shell, no POSIX tools on Windows


def test_running_ignores_another_copy_on_linux(monkeypatch, tmp_path):
    """Linux: a Stardew started from another folder (a second install, a lab container's copy) does not lock this copy."""
    mine, other = tmp_path / "mine", tmp_path / "other"
    for d in (mine, other): d.mkdir(); (d / "Stardew Valley.dll").write_bytes(b""); (d / "StardewModdingAPI").write_bytes(b"")
    monkeypatch.setattr(games, "_run", lambda args, timeout=20: subprocess.CompletedProcess(args, 0, "4242\n", ""))
    monkeypatch.setattr(games.shutil, "which", lambda n: "/usr/bin/" + n)
    g = games.get("stardew", sys_="linux", env={"GAMEANYTHING_STARDEW_DIR": str(mine)})
    monkeypatch.setattr(games.os, "readlink", lambda p: str(other / "StardewModdingAPI"))
    assert g.running() is False
    monkeypatch.setattr(games.os, "readlink", lambda p: str(mine / "StardewModdingAPI"))
    assert g.running() is True
    def denied(p): raise PermissionError(p)
    monkeypatch.setattr(games.os, "readlink", denied)
    assert g.running() is True                                              # cannot tell: careful, counts as this copy
    real_read = Path.read_text
    monkeypatch.setattr(games.Path, "read_text", lambda self, *a, **k: "4242 (StardewModdingA) Z 1 4242" if self.as_posix().startswith("/proc/") else real_read(self, *a, **k))
    assert g.running() is False                                             # a zombie (exited, not reaped yet) is not running


def test_running_sims4_under_wine(monkeypatch, tmp_path):
    """Under Wine /proc/<pid>/exe is Wine's loader: the game's working folder or its WINEPREFIX decides which copy runs."""
    pfx, other = tmp_path / "pfx", tmp_path / "other"
    gd = pfx / "drive_c/Program Files/EA Games/The Sims 4"; (gd / "Game/Bin").mkdir(parents=True)
    monkeypatch.setattr(games, "_run", lambda args, timeout=20: subprocess.CompletedProcess(args, 0, "4242\n", ""))
    monkeypatch.setattr(games.shutil, "which", lambda n: "/usr/bin/" + n)
    g = games.get("sims4", sys_="linux", env={"WINEPREFIX": str(pfx), "USER": "player"})
    links = {"exe": "/opt/wine/lib/wine/x86_64-unix/wine-preloader", "cwd": str(gd / "Game/Bin")}
    monkeypatch.setattr(games.os, "readlink", lambda p: links[str(p).rsplit("/", 1)[1]])
    environ = {"v": b"WINEPREFIX=" + str(other).encode() + b"\0"}
    real_rb = Path.read_bytes
    monkeypatch.setattr(games.Path, "read_bytes", lambda self: environ["v"] if self.as_posix().startswith("/proc/") else real_rb(self))
    assert g.running() is True                                              # started in its Bin folder: this copy
    links["cwd"] = str(tmp_path)
    assert g.running() is False                                             # another prefix's copy
    environ["v"] = b"WINEPREFIX=" + str(pfx).encode() + b"\0"
    assert g.running() is True                                              # same prefix, other working folder


# ---------------------------------------------------------------- the take-home round trip, through the CLI
def _base(tmp_path, kind):
    if kind == "plain": return tmp_path / "plain"
    if kind.startswith("unicode"): return tmp_path / "Users" / "小雨" / "My Games" / "星露谷 物语"
    b = tmp_path / "Users" / "小雨"
    while len(str(b)) < 240: b = b / "a long folder name 很长的文件夹"
    return b


@pytest.mark.parametrize("kind", ["plain", "unicode", "long", "unicode-as-windows"])
def test_take_home_stardew(tmp_path, kind, monkeypatch, capsys, writes, assert_inside, not_running):
    """The 带回家 step: back the saves up, install the mod, check it, put a save back, uninstall. "-as-windows" runs the Windows
    rules (%APPDATA%, tasklist, UTF-8 stdio) on whatever system the test runs on."""
    if kind.endswith("as-windows"): monkeypatch.setattr(osdirs, "system", lambda: "windows")
    base = _base(tmp_path, kind)
    game = base / "Steam Library" / "Stardew Valley"; cfg = base / "AppData" / "Roaming"
    try:
        game.mkdir(parents=True); (game / "Stardew Valley.dll").write_bytes(b"MZ"); (game / "StardewModdingAPI.dll").write_bytes(b"MZ")
    except OSError as e:                                                    # Windows without long-path support (LongPathsEnabled = 0)
        if kind == "long" and os.name == "nt": pytest.skip(f"this Windows has no long-path support: {e}")
        raise
    xdg = tmp_path / "xdg-must-not-be-used" if kind.endswith("as-windows") else cfg       # Windows reads %APPDATA% only
    for k, v in {"GAMEANYTHING_STARDEW_DIR": game, "APPDATA": cfg, "XDG_CONFIG_HOME": xdg, "GAMEANYTHING_DATA": base / "m2w data"}.items(): monkeypatch.setenv(k, str(v))
    saves = cfg / "StardewValley" / "Saves" / "小雨的农场_123"; saves.mkdir(parents=True)
    (saves / "小雨的农场_123").write_text("<Farmer><name>小雨</name><day>1</day></Farmer>", encoding="utf-8")
    src = base / "build" / "Our Wedding"; (src / "i18n").mkdir(parents=True)
    (src / "manifest.json").write_text(json.dumps({"Name": "我们的婚礼", "UniqueID": "Example.OurWedding"}, ensure_ascii=False), encoding="utf-8")
    (src / "i18n" / "zh.json").write_text('{"greeting": "欢迎来到婚礼"}', encoding="utf-8"); (src / "OurWedding.dll").write_bytes(b"MZ\x00\x01")
    log = cfg / "StardewValley" / "ErrorLogs" / "SMAPI-latest.txt"; log.parent.mkdir(parents=True)
    log.write_text("[SMAPI] Loaded 1 mod\n[OurWedding] 婚礼开始了\n", encoding="utf-8")
    name = "我们的婚礼 Mod" if kind.startswith("unicode") else "Our Wedding"
    before = {p: p.read_bytes() for p in game.rglob("*") if p.is_file()}

    with writes() as w:
        d = json.loads(m2w(capsys, "native", "doctor", "--game", "stardew", "--json"))
        g = d["games"][0]
        assert g["installed"] and Path(g["mods_dir"]) == game / "Mods" and Path(g["saves_dir"]) == cfg / "StardewValley" / "Saves"
        assert g["loader"]["ok"] and "婚礼开始了" not in json.dumps(d)
        assert "backup" in m2w(capsys, "native", "backup", "--game", "stardew")
        stamp = m2w(capsys, "native", "backups", "--game", "stardew").split()[0]
        out = m2w(capsys, "native", "install", "--game", "stardew", src, "--name", name)
        assert "saves backed up first" not in out                         # nothing changed since the manual backup
        dst = game / "Mods" / name
        assert (dst / "i18n" / "zh.json").read_text(encoding="utf-8") == '{"greeting": "欢迎来到婚礼"}'
        assert json.loads((dst / "manifest.json").read_text(encoding="utf-8"))["Name"] == "我们的婚礼"
        assert name in m2w(capsys, "native", "mods", "--game", "stardew")
        assert "婚礼开始了" in m2w(capsys, "native", "log", "--game", "stardew", "--grep", "婚礼")
        # the game broke the save: put the backup back; what was there goes to the trash, not deleted
        (saves / "小雨的农场_123").write_text("broken", encoding="utf-8")
        m2w(capsys, "native", "restore", "--game", "stardew", stamp)
        assert (saves / "小雨的农场_123").read_text(encoding="utf-8").startswith("<Farmer><name>小雨")
        trash = base / "m2w data" / "native" / ".trash"
        assert [p.read_text(encoding="utf-8") for p in trash.rglob("小雨的农场_123") if p.is_file()] == ["broken"]
        # uninstall: the mod folder goes to the trash with everything in it
        m2w(capsys, "native", "uninstall", "--game", "stardew", name)
        assert not dst.exists() and name not in m2w(capsys, "native", "mods", "--game", "stardew")
        kept = [p for p in trash.glob(f"*-stardew-uninstalled/{name}")]
        assert len(kept) == 1 and (kept[0] / "i18n" / "zh.json").read_text(encoding="utf-8") == '{"greeting": "欢迎来到婚礼"}'
        with pytest.raises(SystemExit, match="不是 GameAnything 装的"): cli.main(["native", "uninstall", "--game", "stardew", "SomeoneElsesMod"])
    assert_inside(w, tmp_path)
    after = {p: p.read_bytes() for p in game.rglob("*") if p.is_file() and "Mods" not in p.relative_to(game).parts}
    assert after == before                                                 # only the Mods folder of the game changed
    assert all(p.exists() for p in src.rglob("*"))                         # the build output is only read


def test_write_audit_sees_outside_writes(tmp_path, writes):
    from conftest import outside
    inside = tmp_path / "in" / "x.txt"; out = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    with writes() as w:
        inside.parent.mkdir(); inside.write_text("1", encoding="utf-8"); out.write_text("2", encoding="utf-8"); os.replace(out, str(out) + ".2")
    assert outside(w, tmp_path) == sorted({os.path.realpath(out), os.path.realpath(str(out) + ".2")})
    os.replace(str(out) + ".2", tmp_path / "back-inside.txt")


def test_take_home_minecraft_jar(tmp_path, monkeypatch, writes, assert_inside):
    mc = tmp_path / "Users" / "小雨" / "AppData" / "Roaming" / ".minecraft"; (mc / "versions" / "fabric-loader-0.19.5-26.3").mkdir(parents=True)
    (mc / "saves" / "我的世界").mkdir(parents=True); (mc / "saves" / "我的世界" / "level.dat").write_bytes(b"\x0a\x00level")
    monkeypatch.setenv("GAMEANYTHING_MINECRAFT_DIR", str(mc)); monkeypatch.setenv("GAMEANYTHING_DATA", str(tmp_path / "data"))
    jar = tmp_path / "build" / "memory-bridge 1.0.jar"; jar.parent.mkdir()
    with zipfile.ZipFile(jar, "w") as z: z.writestr("fabric.mod.json", '{"id": "memory_bridge", "name": "回忆"}'); z.writestr("org/m2w/Bridge.class", b"\xca\xfe\xba\xbe")
    with writes() as w:
        g = games.get("minecraft")
        r = g.install(jar)
        assert r["backup"] and (mc / "mods" / jar.name).is_file() and g.mods()[jar.name]["path"] == str(mc / "mods" / jar.name)
        assert g.uninstall(jar.name)["moved_to_trash"] and not (mc / "mods" / jar.name).exists()
        b = g.backups()[0]; assert b["items"][0]["files"] == 1
    assert_inside(w, tmp_path)


def test_take_home_cities_on_this_system(tmp_path, monkeypatch, writes, assert_inside, not_running):
    """The real system's folder rules (Path.home() and %LOCALAPPDATA% point into tmp): the mod switch key is built from the path as this
    system writes it (backslashes on Windows)."""
    sd = tmp_path / "Steam" / "steamapps" / "common" / "Cities_Skylines"
    m = sd / ("Cities.app/Contents/Resources/Data/Managed" if osdirs.system() == "mac" else "Cities_Data/Managed"); m.mkdir(parents=True); (m / "ICities.dll").write_bytes(b"MZ")
    monkeypatch.setenv("GAMEANYTHING_CITIES_DIR", str(sd)); monkeypatch.setenv("GAMEANYTHING_DATA", str(tmp_path / "data"))
    src = tmp_path / "build" / "Memory2World"; (src / "Source").mkdir(parents=True)
    (src / "Source" / "Mod.cs").write_text('// 圣地亚哥的回忆\npublic class Mod {}\n', encoding="utf-8"); (src / "Memory2World.dll").write_bytes(b"MZ")
    with writes() as w:
        g = games.get("cities_skylines")
        assert Path(g.user_dir()).is_relative_to(tmp_path / "env")             # the isolated profile, never the real one
        g.saves_dir().mkdir(parents=True); (g.saves_dir() / "圣地亚哥.crp").write_bytes(b"CRAP")
        r = g.install(src); dst = g.mods_dir() / "Memory2World"
        key = cgs.mod_key(str(dst), "\\" if os.name == "nt" else "/")
        assert key.startswith("Memory2World") and key.endswith(".enabled") and r["switch"] == key
        assert cgs.read(g.cgs_file())["bool"][key] is True
        g.uninstall("Memory2World"); assert key not in cgs.read(g.cgs_file())["bool"]           # off = no key (the game's default)
    assert_inside(w, tmp_path)


def test_cgs_key_windows_path():
    p = WIN_HOME + r"\AppData\Local\Colossal Order\Cities_Skylines\Addons\Mods\Memory2World"
    k = cgs.mod_key(p, "\\")
    assert k == f"Memory2World{cgs.mono_hash(p)}.enabled" and cgs.mod_key(p + "\\", "\\") == k
    assert cgs.mono_hash("小雨") == ((ord("小") * 31 + ord("雨")) & 0x7FFFFFFF)   # UTF-16 code units, not UTF-8 bytes



# ---------------------------------------------------------------- Slay the Spire and Overcooked! 2
def test_sts_oc2_default_folders(tmp_path):
    env = {"USERPROFILE": WIN_HOME, "GAMEANYTHING_DATA": "unused"}
    oc = games.get("overcooked2", sys_="windows", home=Path(WIN_HOME), env=env)
    assert win(oc.saves_dir()) == PureWindowsPath(WIN_HOME + r"\AppData\LocalLow\Team17\Overcooked2")
    assert win(oc.log_files()[-1]) == PureWindowsPath(WIN_HOME + r"\AppData\LocalLow\Team17\Overcooked2\Player.log")
    st = games.get("slay_the_spire", sys_="windows", home=Path(WIN_HOME), env=env)
    assert win(st.saves_dir()) == PureWindowsPath(r"C:\Program Files (x86)\Steam\steamapps\common\SlayTheSpire\saves")
    home = tmp_path / "Users" / "小雨"
    assert games.get("slay_the_spire", sys_="mac", home=home, env={}).mods_dir() == \
        home / "Library/Application Support/Steam/steamapps/common/SlayTheSpire/SlayTheSpire.app/Contents/Resources/mods"
    assert games.get("slay_the_spire", sys_="linux", home=home, env={}).saves_dir() == home / ".local/share/Steam/steamapps/common/SlayTheSpire/saves"
    assert games.get("overcooked2", sys_="mac", home=home, env={}).saves_dir() == home / "Library/Application Support/Team17/Overcooked2"
    assert games.get("overcooked2", sys_="mac", home=home, env={}).log_files()[1] == home / "Library/Logs/Unity/Player.log"
    assert games.get("overcooked2", sys_="linux", home=home, env={}).saves_dir() == home / ".config/unity3d/Team17/Overcooked2"


def _game_files(d: Path, skip: str):
    return {p: p.read_bytes() for p in d.rglob("*") if p.is_file() and skip not in p.relative_to(d).parts}


@pytest.mark.parametrize("kind", ["plain", "unicode", "unicode-as-windows"])
def test_take_home_sts(tmp_path, kind, monkeypatch, capsys, writes, assert_inside, not_running):
    """Slay the Spire keeps its saves in the game folder: backup / restore cover saves/ and preferences/; install only adds to mods/."""
    if kind.endswith("as-windows"): monkeypatch.setattr(osdirs, "system", lambda: "windows")
    base = _base(tmp_path, kind); gd = base / "Steam Library" / "SlayTheSpire"
    gd.mkdir(parents=True); (gd / "desktop-1.0.jar").write_bytes(b"PK"); (gd / "ModTheSpire.jar").write_bytes(b"PK")
    (gd / "mods").mkdir(); (gd / "mods" / "BaseMod.jar").write_bytes(b"PK"); (gd / "mods" / "她自己的 mod.jar").write_bytes(b"PK")
    (gd / "saves").mkdir(); (gd / "saves" / "THE_RESEARCHER.autosave").write_text("第 1 层", encoding="utf-8")
    (gd / "preferences").mkdir(); (gd / "preferences" / "STSPlayer").write_text('{"name": "小雨"}', encoding="utf-8")
    lg = gd / "sendToDevs" / "logs"; lg.mkdir(parents=True); (lg / "SlayTheSpire.log").write_text("INFO phd> [phd] 读博 loaded\n", encoding="utf-8")
    for k, v in {"GAMEANYTHING_STS_DIR": gd, "GAMEANYTHING_DATA": base / "m2w data"}.items(): monkeypatch.setenv(k, str(v))
    jar = base / "build" / "phd.jar"; jar.parent.mkdir(parents=True)
    with zipfile.ZipFile(jar, "w") as z: z.writestr("ModTheSpire.json", json.dumps({"modid": "phd", "name": "读博"}, ensure_ascii=False))
    name = "读博 PhD" if kind.startswith("unicode") else "phd"
    before = _game_files(gd, "mods")
    with writes() as w:
        g = json.loads(m2w(capsys, "native", "doctor", "--game", "slay_the_spire", "--json"))["games"][0]
        assert g["installed"] and g["loader"]["ok"] and Path(g["mods_dir"]) == gd / "mods" and g["launch"] == "steam://run/646570"
        m2w(capsys, "native", "backup", "--game", "slay_the_spire")
        stamp = m2w(capsys, "native", "backups", "--game", "slay_the_spire").split()[0]
        out = m2w(capsys, "native", "install", "--game", "slay_the_spire", jar, "--name", name)
        dst = gd / "mods" / f"{name}.jar"; assert dst.is_file() and "saves backed up first" not in out
        assert f"{name}.jar" in m2w(capsys, "native", "mods", "--game", "slay_the_spire")
        assert "读博 loaded" in m2w(capsys, "native", "log", "--game", "slay_the_spire", "--grep", "phd")
        (gd / "preferences" / "STSPlayer").write_text("broken", encoding="utf-8")
        m2w(capsys, "native", "restore", "--game", "slay_the_spire", stamp)
        assert (gd / "preferences" / "STSPlayer").read_text(encoding="utf-8") == '{"name": "小雨"}'
        m2w(capsys, "native", "uninstall", "--game", "slay_the_spire", f"{name}.jar")
        assert not dst.exists() and list((base / "m2w data" / "native" / ".trash").glob(f"*-slay_the_spire-uninstalled/{name}.jar"))
        with pytest.raises(SystemExit, match="不是 GameAnything 装的"): cli.main(["native", "uninstall", "--game", "slay_the_spire", "她自己的 mod.jar"])
    assert_inside(w, tmp_path)
    assert _game_files(gd, "mods") == before and (gd / "mods" / "她自己的 mod.jar").is_file()


@pytest.mark.parametrize("kind", ["plain", "unicode", "unicode-as-windows"])
def test_take_home_oc2(tmp_path, kind, monkeypatch, capsys, writes, assert_inside, not_running):
    """Overcooked! 2: the plugin folder goes to BepInEx/plugins/<name>/, the saves (Unity's persistentDataPath) are backed up first."""
    if kind.endswith("as-windows"): monkeypatch.setattr(osdirs, "system", lambda: "windows")
    sys_ = osdirs.system()
    base = _base(tmp_path, kind); gd = base / "Steam Library" / "Overcooked! 2"
    man = gd / ("Overcooked2.app/Contents/Resources/Data/Managed" if sys_ == "mac" else "Overcooked2_Data/Managed"); man.mkdir(parents=True)
    (man / "Assembly-CSharp.dll").write_bytes(b"MZ"); (gd / "BepInEx" / "core").mkdir(parents=True); (gd / "BepInEx" / "core" / "BepInEx.dll").write_bytes(b"MZ")
    (gd / ("winhttp.dll" if sys_ == "windows" else "run_bepinex.sh")).write_bytes(b"x")
    (gd / "BepInEx" / "plugins").mkdir(); (gd / "BepInEx" / "plugins" / "她的插件.dll").write_bytes(b"MZ")
    (gd / "BepInEx" / "LogOutput.log").write_text("[Info   :   BepInEx] Loading [港式茶餐厅 1.0.0]\n", encoding="utf-8")
    for k, v in {"GAMEANYTHING_OC2_DIR": gd, "GAMEANYTHING_DATA": base / "m2w data"}.items(): monkeypatch.setenv(k, str(v))
    g0 = games.get("overcooked2"); sv = g0.saves_dir() / "76561199810022756"; sv.mkdir(parents=True)
    assert Path(sv).is_relative_to(tmp_path)
    (sv / "CoopSlot_SaveFile_0.save").write_bytes(b"\x01\x02 v1")
    src = base / "build" / "HkFood"; (src / "models" / "菠萝包").mkdir(parents=True); (src / "HkFood.dll").write_bytes(b"MZ\x00")
    (src / "models" / "菠萝包" / "transform.json").write_text('{"node": "Cake_Plain"}', encoding="utf-8")
    name = "港式 HkFood" if kind.startswith("unicode") else "HkFood"
    before = _game_files(gd, "plugins")
    with writes() as w:
        g = json.loads(m2w(capsys, "native", "doctor", "--game", "overcooked2", "--json"))["games"][0]
        assert g["installed"] and g["loader"]["ok"] and Path(g["mods_dir"]) == gd / "BepInEx" / "plugins"
        out = m2w(capsys, "native", "install", "--game", "overcooked2", src, "--name", name)
        assert "saves backed up first" in out
        dst = gd / "BepInEx" / "plugins" / name; assert (dst / "models" / "菠萝包" / "transform.json").is_file()
        assert "港式茶餐厅" in m2w(capsys, "native", "log", "--game", "overcooked2", "--grep", "Loading")
        stamp = m2w(capsys, "native", "backups", "--game", "overcooked2").split()[0]
        (sv / "CoopSlot_SaveFile_0.save").write_bytes(b"broken")
        m2w(capsys, "native", "restore", "--game", "overcooked2", stamp)
        assert (sv / "CoopSlot_SaveFile_0.save").read_bytes() == b"\x01\x02 v1"
        m2w(capsys, "native", "uninstall", "--game", "overcooked2", name)
        assert not dst.exists() and list((base / "m2w data" / "native" / ".trash").glob(f"*-overcooked2-uninstalled/{name}/HkFood.dll"))
        with pytest.raises(SystemExit, match="不是 GameAnything 装的"): cli.main(["native", "uninstall", "--game", "overcooked2", "她的插件.dll"])
    assert_inside(w, tmp_path)
    after = _game_files(gd, "plugins"); after.pop(gd / "BepInEx" / "LogOutput.log", None); before.pop(gd / "BepInEx" / "LogOutput.log", None)
    assert after == before and (gd / "BepInEx" / "plugins" / "她的插件.dll").is_file()


# ---------------------------------------------------------------- text, files and processes


def _text_io_without_encoding(tree):
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call): continue
        fn = n.func; kws = {k.arg: k.value for k in n.keywords}
        name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else None
        if name in ("read_text", "write_text") or (name == "open" and isinstance(fn, ast.Name)):
            mode = n.args[1] if name == "open" and len(n.args) > 1 else kws.get("mode")
            if isinstance(mode, ast.Constant) and "b" in str(mode.value): continue
            if "encoding" not in kws: yield n
        if name == "run" and isinstance(kws.get("text"), ast.Constant) and kws["text"].value and not ({"encoding", "errors"} & set(kws)): yield n


def test_text_files_are_utf8_everywhere():
    """Windows opens text in the ANSI code page (cp1252 / cp936) unless told otherwise: Chinese breaks. Every text open / read_text /
    write_text in the package names its encoding, and every text-mode subprocess says how to decode."""
    bad = [f"{f.relative_to(ROOT)}:{n.lineno}" for f in sorted(PKG.rglob("*.py"))
           for n in _text_io_without_encoding(ast.parse(f.read_text(encoding="utf-8")))]
    assert not bad, "text IO without encoding=\"utf-8\": " + ", ".join(bad)


def test_no_posix_only_process_calls():
    bad = []
    for f in sorted(PKG.rglob("*.py")):
        t = f.read_text(encoding="utf-8")
        for n in ast.walk(ast.parse(t)):
            if isinstance(n, ast.keyword) and n.arg == "shell" and not (isinstance(n.value, ast.Constant) and n.value.value is False): bad.append(f"{f.name}:{n.value.lineno} shell=")
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "os" and n.attr in ("system", "fork", "kill", "getuid", "setsid", "killpg"):
                bad.append(f"{f.name}:{n.lineno} os.{n.attr}")
            if isinstance(n, (ast.Import, ast.ImportFrom)) and any(a.name in ("fcntl", "pwd", "grp", "termios", "resource") for a in n.names) and f.name != "osdirs.py":
                bad.append(f"{f.name}:{n.lineno} import")
    assert not bad, bad


def test_stdout_is_utf8_on_windows(monkeypatch):
    """A Windows pipe uses the ANSI code page: printing Chinese raised UnicodeEncodeError (cp1252) before cli set UTF-8."""
    raw = io.BytesIO(); out = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", out); monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO("你好".encode("utf-8")), encoding="cp1252"))
    monkeypatch.setattr(osdirs, "system", lambda: "windows")
    cli._utf8_stdio(); print("[chat] 用户说话了"); out.flush()
    assert raw.getvalue().decode("utf-8") == "[chat] 用户说话了" + os.linesep and sys.stdin.read() == "你好"


def test_lock_many_times():
    """osdirs.lock: fcntl on Linux / macOS, msvcrt on Windows; released on close, again and again; a held lock refuses a non-blocking try."""
    f = Path(os.environ["GAMEANYTHING_DATA"]) / ".lock"
    for _ in range(50):
        with open(f, "a", encoding="utf-8") as lk: osdirs.lock(lk)
    with open(f, "a", encoding="utf-8") as a, open(f, "a", encoding="utf-8") as b:
        osdirs.lock(a)
        with pytest.raises(OSError): osdirs.lock(b, block=False)


def test_hf_token_file_on_windows(monkeypatch):
    from gameanything import backup
    f = backup.token_file(); f.parent.mkdir(parents=True, exist_ok=True); f.write_text("hf_abc\n", encoding="utf-8"); os.chmod(f, 0o644)
    monkeypatch.setattr(osdirs, "system", lambda: "windows")          # no keyring on Windows; NTFS has no mode bits (stat says 0o666)
    assert backup.get_token() == "hf_abc"
    monkeypatch.setattr(osdirs, "system", lambda: "linux"); monkeypatch.setattr(osdirs, "secret_get", lambda *a: None)
    if os.name != "nt":
        with pytest.raises(backup.BackupError, match="chmod 600"): backup.get_token()


def test_keys_file_with_bom(tmp_path, monkeypatch):
    from gameanything import keys
    f = tmp_path / "我的 keys.env"; f.write_bytes("\ufeffOPENROUTER_API_KEY=sk-test\r\n# 注释\r\n".encode("utf-8"))    # Windows Notepad
    projects.save_settings({"keys_file": str(f)})
    assert keys.get("OPENROUTER_API_KEY") == "sk-test"


# ---------------------------------------------------------------- projects and the conversation in Chinese
def test_project_and_thread_in_chinese(tmp_path, writes, assert_inside):
    with writes() as w:
        e = projects.create("我们的婚礼 · 2026", "memory", tmp_path / "项目" / "我们的 婚礼", "zh", "stardew")
        root = Path(e["path"])
        assert projects.config_of(root) == {"title": "我们的婚礼 · 2026", "kind": "memory", "game": "stardew", "lang": "zh", "id": e["id"], "decisions": "strict"}
        assert projects.find(e["id"])["title"] == "我们的婚礼 · 2026" and projects.last_opened() == root
        projects.set_game(e["id"], "cities_skylines"); assert projects.game_of(root) == "cities_skylines"
        T = Thread(root)
        T.user_text("我妈妈在婚礼上哭了，\n她说：“你长大了。”")
        att = tmp_path / "回忆 清单.txt"; att.write_text("第一行\n第二行\n", encoding="utf-8")
        T.agent_text("收到，我记下了。", "Got it.", session="测试", attach=[att])
        T.card({"kind": "options", "key": "who", "title": "谁来演妈妈？", "items": [{"key": "a", "title": "原版村民"}, {"key": "b", "title": "新角色"}]}, session="测试")
        lines, mine = T.read()
    assert_inside(w, tmp_path)
    assert lines and "你长大了" in lines[0]
    raw = (root / "conversation" / "thread.jsonl").read_bytes()
    assert b"\r\n" not in raw and raw.count(b"\n") == 3                    # one event per line, the same bytes on every system
    assert [ev["text"] for ev in T.events()][:2] == ["我妈妈在婚礼上哭了，\n她说：“你长大了。”", "收到，我记下了。"]
    md = (root / "feedback" / "answers.md").read_text(encoding="utf-8")
    assert "- 我妈妈在婚礼上哭了，\n  她说：“你长大了。”" in md
    assert (root / "conversation" / "files" / "回忆 清单.txt").read_text(encoding="utf-8") == "第一行\n第二行\n"


def test_cli_in_chinese_through_a_pipe(tmp_path):
    """The agent runs m2w with stdout / stdin on a pipe: on Windows that used the ANSI code page."""
    r = m2w_proc("project", "new", "--title", "我们的婚礼", "--lang", "zh", "--dir", tmp_path / "我的 项目")
    assert r.returncode == 0, r.err
    r = m2w_proc("project", "list"); assert r.returncode == 0 and "我们的婚礼" in r.out and "我的 项目" in r.out, r.err
    P = tmp_path / "我的 项目"
    r = m2w_proc("chat", "say", "--project", P, "--session", "测试", "--text-en", "Hello", input="你好，我接手了。")
    assert r.returncode == 0, r.err
    assert Thread(P).events()[-1]["text"] == "你好，我接手了。"
    Thread(P).user_text("把妈妈的台词改短一点")
    r = m2w_proc("chat", "read", "--project", P, "--session", "测试"); assert r.returncode == 0 and "把妈妈的台词改短一点" in r.out, r.err
    r = m2w_proc("native", "doctor"); assert r.returncode == 0 and "Stardew Valley" in r.out, r.err
    r = m2w_proc("project", "open", "没有这个项目"); assert r.returncode != 0 and "没有这个项目" in r.err


def test_export_import_chinese(tmp_path):
    e = projects.create("海边的回忆", "memory", tmp_path / "海边 的回忆", "zh")
    root = Path(e["path"]); d = root / "1_ingest" / "derived" / "照片"; d.mkdir(parents=True); (d / "日落 1.jpg").write_bytes(b"\xff\xd8 jpeg")
    (root / "4_design" / "world_plan.yaml").write_text(yaml.safe_dump({"world_plan": {"title": "日落"}}, allow_unicode=True), encoding="utf-8")
    z = transfer.export_project(root, tmp_path / "out" / "海边.zip")
    with zipfile.ZipFile(z["path"]) as zf:
        assert "project/1_ingest/derived/照片/日落 1.jpg" in zf.namelist() and not any("\\" in n for n in zf.namelist())
    r = transfer.import_project(z["path"], tmp_path / "导入", "回来了")
    back = Path(r["path"])
    assert (back / "1_ingest/derived/照片/日落 1.jpg").read_bytes() == b"\xff\xd8 jpeg" and r["title"] == "海边的回忆"
    assert yaml.safe_load((back / "4_design/world_plan.yaml").read_text(encoding="utf-8"))["world_plan"]["title"] == "日落"


# ---------------------------------------------------------------- the browser UI
def _free_port():
    with socket.socket() as s: s.bind(("127.0.0.1", 0)); return s.getsockname()[1]


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=20) as r: return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


def _start_ui(root, port):
    """`gameanything ui` as its own process -> (process, base url); the server says which port it took."""
    p = subprocess.Popen([sys.executable, "-c", "import sys; from gameanything.cli import main; sys.exit(main())", "ui", "--project", str(root),
                          "--port", str(port)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=dict(os.environ))
    q = queue.Queue(); threading.Thread(target=lambda: [q.put(l) for l in iter(p.stdout.readline, b"")], daemon=True).start()
    end = time.time() + 60; seen = []
    while time.time() < end:
        try: line = q.get(timeout=1).decode("utf-8")
        except queue.Empty: line = ""
        seen.append(line)
        if "open http://127.0.0.1:" in line: return p, line.split("open ")[1].split()[0].rstrip("/")
        if p.poll() is not None and q.empty(): break
    p.kill(); pytest.fail("gameanything ui did not start:\n" + "".join(seen))


def _stop(p):
    p.terminate()
    try: p.wait(15)
    except subprocess.TimeoutExpired: p.kill()


@pytest.fixture
def ui(tmp_path):
    e = projects.create("界面 测试", "memory", tmp_path / "界面 测试", "zh"); root = Path(e["path"])
    p, url = _start_ui(root, _free_port())
    yield url, root
    _stop(p)


def test_second_ui_takes_the_next_port(ui):
    """Two `gameanything ui` on one port (an agent restarting it, a second project): the second moves on; on Windows SO_REUSEADDR let both bind."""
    url, root = ui
    p2, url2 = _start_ui(root, int(url.rsplit(":", 1)[1]))
    try: assert url2 != url and _get(url2 + "/api/shell")[0] == 200
    finally: _stop(p2)


def test_ui_serves_pages_and_unicode_files(ui):
    url, root = ui
    s, ct, body = _get(url + "/"); assert s == 200 and ct.startswith("text/html") and b"<html" in body.lower()
    s, ct, body = _get(url + "/api/shell"); assert s == 200 and json.loads(body)
    s, ct, _ = _get(url + "/app.js"); assert s == 200 and ct.startswith("text/javascript")
    s, ct, _ = _get(url + "/app.css"); assert s == 200 and ct.startswith("text/css")
    s, ct, _ = _get(url + "/shell.js"); assert s == 200
    d = root / "1_ingest" / "derived" / "海边"; d.mkdir(parents=True); (d / "日落 1.jpg").write_bytes(b"\xff\xd8jpeg")
    s, ct, body = _get(url + "/media/" + quote("1_ingest/derived/海边/日落 1.jpg")); assert (s, body) == (200, b"\xff\xd8jpeg")
    a = root / "4_design" / "art" / "头像"; a.mkdir(parents=True); (a / "妈妈.png").write_bytes(b"\x89PNG")
    s, _, body = _get(url + "/art/" + quote("头像/妈妈.png")); assert (s, body) == (200, b"\x89PNG")
    pl = root / "5_build" / "m1" / "play"; pl.mkdir(parents=True); (pl / "录像.mp4").write_bytes(b"\x00\x00\x00\x18ftyp")
    s, _, body = _get(url + "/build/m1/" + quote("录像.mp4")); assert s == 200 and body.endswith(b"ftyp")
    f = root.parent / "清单 1.txt"; f.write_text("你好", encoding="utf-8"); Thread(root).agent_text("附件", attach=[f])
    s, _, body = _get(url + "/conv/" + quote("清单 1.txt")); assert (s, body.decode("utf-8")) == (200, "你好")
    for bad in ("/media/" + quote("../config/project.yaml", safe=""), "/media/1_ingest/derived/../../config/project.yaml",
                "/art/" + quote("..\\..\\config\\project.yaml", safe=""), "/build/m1/" + quote("../../../config/project.yaml", safe="")):
        assert _get(url + bad)[0] == 404, bad


def test_a_pinned_steam_library_comes_first_and_the_default_one_is_still_found(tmp_path):
    # her decision 2026-11-01: GAMEANYTHING_STEAM_DIR pinned to a second library must not hide the games in the default Steam folder
    from gameanything.native import steam
    home = tmp_path / "home"; default = home / ".local" / "share" / "Steam"; second = tmp_path / "Games" / "SteamLibrary"
    for d in (default, second): (d / "steamapps").mkdir(parents=True)
    assert steam.roots("linux", home, {"GAMEANYTHING_STEAM_DIR": str(second)}) == [second, default]
    assert steam.roots("linux", home, {"GAMEANYTHING_STEAM_DIR": str(default)}) == [default]
