"""本机模式少打扰 (native/quiet.py, native/checks.py; 2026-10-24): her game is opened only with her yes recorded in the
thread (or in her time window / when she said always), a yes opens it once, a game she opened is never closed; the small-window settings
go back; hot reload where the game has it; headless checks against the game's assemblies and jars; the project setting, the page's
dialog API and its English. Fake folders and fake processes only: no game, no network."""
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from _fakedll import make_class, make_dll
from gameanything import cli, projects
from gameanything.conversation import Thread
from gameanything.native import checks, games, quiet, s4pkg, steam

POSIX = os.name != "nt"


# ---------------------------------------------------------------- helpers
def _env(tmp):
    return {"GAMEANYTHING_DATA": str(tmp / "m2w")}


def _steam(home: Path, sys_: str, appid: int, installdir: str) -> Path:
    root = steam.candidates(sys_, home, {})[0]
    (root / "steamapps").mkdir(parents=True, exist_ok=True)
    (root / "steamapps" / "libraryfolders.vdf").write_text(f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{root}"\n\t}}\n}}\n', encoding="utf-8")
    (root / "steamapps" / f"appmanifest_{appid}.acf").write_text(f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"installdir"\t\t"{installdir}"\n}}\n', encoding="utf-8")
    d = root / "steamapps" / "common" / installdir; d.mkdir(parents=True)
    return d


class Proc:
    """The game's processes as the adapter sees them."""
    def __init__(self, running=False, pids=None): self.running = running; self.pids = list(pids or [])


def _game(tmp, gid="stardew", proc=None, monkeypatch=None):
    g = games.get(gid, sys_="linux", home=tmp / "home", env=_env(tmp))
    proc = proc or Proc()
    g.running = lambda: proc.running or bool(proc.pids)
    g.pids = lambda: list(proc.pids)
    return g, proc


@pytest.fixture
def proj():
    e = projects.create("本机 测试", "feature", game="stardew", build_mode="native"); return Path(e["path"])


class Opener:
    def __init__(self, ok=True): self.urls = []; self.ok = ok

    def __call__(self, url): self.urls.append(url); return self.ok


def _launch(root, g, op, **kw):
    return quiet.launch(root, g, opener=op, settle=0, sleep=lambda s: None, **kw)


def _cards(root): return [e for e in Thread(root).events() if e["type"] == "card"]


def _answer(root, pick, note=None, source="ui"):
    T = Thread(root); cid = next(k for k, v in T.cards().items() if v["card"].get("key") == quiet.CARD_KEY)
    return T.answer(cid, {"picked": [pick], **({"note": note} if note else {})}, source=source)


# ---------------------------------------------------------------- the setting
def test_policy_default_set_and_cli(proj, capsys):
    assert quiet.policy(proj) == {"mode": "ask", "window": "22:00-08:00", "idle_minutes": 10, "drive": "idle", "front": "never", "hands": "agent", "chosen": False}
    pid = projects.find(str(proj))["id"]
    quiet.set_policy(pid, "window", "21:30-7:05")
    assert quiet.policy(proj) == {"mode": "window", "window": "21:30-07:05", "idle_minutes": 10, "drive": "idle", "front": "never", "hands": "agent", "chosen": True}
    cfg = projects.config_of(proj); assert cfg["title"] == "本机 测试" and cfg["build_mode"] == "native"       # other lines untouched
    quiet.set_policy(pid, "always"); assert quiet.policy(proj)["window"] == "21:30-07:05"                       # the window stays
    for bad in (("sometimes", None), ("window", "25:00-08:00"), ("window", "8-9"), ("window", "08:00-08:00")):
        with pytest.raises(ValueError): quiet.set_policy(pid, *bad)
    assert cli.main(["project", "set-launch", pid, "ask", "--window", "23:00-06:00"]) == 0
    assert "native_launch=ask  window=23:00-06:00  idle_minutes=10  drive=idle" in capsys.readouterr().out


def test_window_math():
    d = lambda h, m=0: datetime(2026, 10, 24, h, m)
    assert quiet.in_window("22:00-08:00", d(23)) and quiet.in_window("22:00-08:00", d(3)) and not quiet.in_window("22:00-08:00", d(8))
    assert quiet.in_window("09:00-17:00", d(9)) and not quiet.in_window("09:00-17:00", d(17, 30))
    assert quiet.window_opens("22:00-08:00", d(15)) == d(22) and quiet.window_opens("22:00-08:00", d(23)) == d(22) + timedelta(days=1)


# ---------------------------------------------------------------- ask: no yes, no launch
def test_no_yes_means_pending_and_one_card(proj, tmp_path):
    g, _ = _game(tmp_path); op = Opener()
    r = _launch(proj, g, op, reason="测三处改动：鸡舍、对话、节日")
    assert r["state"] == "pending" and r["code"] == "asked" and not r["launched"] and op.urls == []
    (c,) = _cards(proj); k = c["card"]
    assert k["kind"] == "options" and k["key"] == "native-launch" and k["multi"] is False and k["title"] == "要开游戏测一下，现在可以吗？"
    assert [i["key"] for i in k["items"]] == ["now", "wait", "later"] and [i["title"] for i in k["items"]][:2] == ["现在可以", "等我说"]
    assert k["items"][2]["title"] == "今晚 22:00 后" and c["card_en"]["items"][0]["title"] == "Now is fine" and c["text"] == "测三处改动：鸡舍、对话、节日"
    assert c["session"] == quiet.SESSION
    r = _launch(proj, g, op); assert r["code"] == "waiting" and len(_cards(proj)) == 1 and op.urls == []      # never a second card while she has not answered
    _answer(proj, "now", source="terminal")                                                                     # typed by someone else, not her click
    assert _launch(proj, g, op)["state"] == "pending" and op.urls == []


def test_yes_opens_once(proj, tmp_path):
    g, _ = _game(tmp_path); op = Opener()
    _launch(proj, g, op); a = _answer(proj, "now")
    r = _launch(proj, g, op, round_="m1-r1")
    assert r["state"] == "go" and r["launched"] and op.urls == ["steam://rungameid/413150"]
    L = quiet.ledger(proj); assert L["used"] == {a["id"]: r["launch_id"]} and L["launches"][0]["round"] == "m1-r1"
    r2 = _launch(proj, g, op)                                                                                   # the same yes does not open it again
    assert r2["state"] == "pending" and r2["code"] == "asked" and len(op.urls) == 1 and len(_cards(proj)) == 2
    assert [x["round"] for x in quiet.launches(proj, "m1-r1")] == ["m1-r1"]


def test_stale_yes_wait_and_later(proj, tmp_path):
    g, _ = _game(tmp_path)
    quiet.decide(proj, g); _answer(proj, "now")
    assert quiet.decide(proj, g, now=datetime.now() + timedelta(hours=3))["code"] == "asked"                    # 3 hours later: ask again
    _answer(proj, "wait")
    d = quiet.decide(proj, g); assert d["code"] == "wait" and len(_cards(proj)) == 2
    assert quiet.decide(proj, g, ask_again=True)["code"] == "asked" and len(_cards(proj)) == 3
    a = _answer(proj, "later"); at = datetime.fromisoformat(a["at"])
    t = at.replace(hour=22, minute=0, second=0); t = t if t > at else t + timedelta(days=1)
    d = quiet.decide(proj, g, now=t - timedelta(minutes=1)); assert d["code"] == "later" and d["until"] == t.isoformat(timespec="seconds")
    assert quiet.decide(proj, g, now=t + timedelta(minutes=1))["state"] == "go"
    quiet.decide(proj, g, ask_again=True); a = _answer(proj, "later", note="23:30 以后吧"); at = datetime.fromisoformat(a["at"])
    t = at.replace(hour=23, minute=30, second=0); t = t if t > at else t + timedelta(days=1)
    assert quiet.decide(proj, g, now=t - timedelta(minutes=5))["until"] == t.isoformat(timespec="seconds")


def test_wait_decision_picks_up_her_answer(proj, tmp_path):
    g, _ = _game(tmp_path); n = {"i": 0}

    def sleep(_):
        n["i"] += 1
        if n["i"] == 2: _answer(proj, "now")
    d = quiet.wait_decision(proj, g, 60, poll=0, sleep=sleep)
    assert d["state"] == "go" and len(_cards(proj)) == 1


# ---------------------------------------------------------------- window / always
def test_window_and_always(proj, tmp_path):
    g, _ = _game(tmp_path); op = Opener(); pid = projects.find(str(proj))["id"]
    quiet.set_policy(pid, "window", "22:00-08:00")
    d = quiet.decide(proj, g, now=datetime(2026, 10, 24, 15, 0)); assert d["code"] == "window" and d["until"] == "2026-10-24T22:00:00"
    assert _cards(proj) == []                                                                                   # outside her window: not even a card
    r = _launch(proj, g, op, now=datetime(2026, 10, 24, 23, 0)); assert r["launched"] and r["code"] == "window"
    quiet.close(proj, g)
    assert quiet.decide(proj, g, now=datetime(2026, 10, 24, 23, 5))["state"] == "go"          # no waiting between launches (her call, 2026-10-29)
    quiet.set_policy(pid, "always")
    assert quiet.decide(proj, g, now=datetime(2026, 10, 24, 23, 11))["state"] == "go" and _cards(proj) == []


def test_failed_url_open_does_not_start_launch_gap(proj, tmp_path):
    g, _ = _game(tmp_path); pid = projects.find(str(proj))["id"]
    quiet.set_policy(pid, "always")
    with pytest.raises(games.NativeError, match="没能打开"):
        _launch(proj, g, Opener(False), now=datetime(2026, 10, 24, 23, 0))
    assert quiet.ledger(proj)["launches"][-1]["state"] == "failed"
    d = quiet.decide(proj, g, now=datetime(2026, 10, 24, 23, 1))
    assert d["state"] == "go" and d["code"] == "always"


# ---------------------------------------------------------------- never her game
def test_her_running_game_is_never_opened_or_closed(proj, tmp_path, monkeypatch):
    g, proc = _game(tmp_path, proc=Proc(pids=[4242])); op = Opener(); killed = []
    monkeypatch.setattr(quiet, "_terminate", lambda pid: killed.append(pid) or True)
    quiet.set_policy(projects.find(str(proj))["id"], "always")
    r = _launch(proj, g, op); assert r["state"] == "refused" and r["code"] == "running" and op.urls == []
    c = quiet.close(proj, g); assert not c["closed"] and c["code"] == "not_ours" and killed == []




def test_after_launch_runs_detached_and_records_its_result(proj, tmp_path, monkeypatch):
    """Her Mac 2026-10-29: the agent's session ended during Civ VI's intro and the launch command went with it, so the intro was never
    skipped. A game's after_launch runs in its own detached process (afterlaunch.py) and writes its result into the launch record."""
    g, proc = _game(tmp_path); quiet.set_policy(projects.find(str(proj))["id"], "always"); seen = []

    def opener(url): proc.pids = [4242]; return True
    r = quiet.launch(proj, g, opener=opener, settle=5, sleep=lambda s: None, spawner=lambda *a: seen.append(a))
    assert r["after"] is None and seen == []                                         # no after_launch: nothing started
    quiet._update(proj, lambda L: L["launches"][-1].update(state="closed")); proc.pids = []   # (never close() a made-up pid: a real
                                                                                              # process 4242 on a Linux host could get SIGTERM)
    monkeypatch.setattr(type(g), "after_launch", lambda self, root, pids, sleep=None: {"intro": f"skipped {pids}"})
    r = quiet.launch(proj, g, opener=opener, settle=5, sleep=lambda s: None, spawner=lambda *a: seen.append(a) or Path("log"))
    assert "background" in r["after"]["after_launch"] and seen[0][2] == r["launch_id"] and seen[0][3] == [4242]
    from gameanything.native import afterlaunch
    monkeypatch.setattr("gameanything.native.get", lambda gid: g)
    assert afterlaunch.main([str(proj), g.id, r["launch_id"], "4242"]) == 0
    assert quiet.ledger(proj)["launches"][-1]["after"] == {"intro": "skipped [4242]"}

@pytest.mark.skipif(not POSIX, reason="a real child process stands in for her game")
def test_drive_always_takes_over_her_running_game_but_never_kills_it(proj, tmp_path, monkeypatch):
    """Her rule 2026-10-29 (「6 和 8 都改」, 3 and 4 not needed): with native_drive: always a running game is the test game, whoever opened it;
    later processes of the game count too (no ADOPT_SECS window); her game is asked to quit but never SIGTERMed."""
    g, proc = _game(tmp_path); op = Opener(); killed = []
    monkeypatch.setattr(quiet, "_terminate", lambda pid: killed.append(pid) or True)
    quiet.set_policy(projects.find(str(proj))["id"], "always", drive="always")
    her = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    late = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        proc.pids = [her.pid]
        d = _launch(proj, g, op); assert d["state"] == "open" and d["code"] == "took_over" and op.urls == []
        x, ps = quiet.current(proj, g); assert x["took_over"] and [p["pid"] for p in ps] == [her.pid]
        proc.pids = [her.pid, late.pid]                                              # a launcher's game process, long after
        x, ps = quiet.current(proj, g, now=datetime.now() + timedelta(hours=2)); assert {p["pid"] for p in ps} == {her.pid, late.pid}
        assert quiet.decide(proj, g)["code"] == "took_over" and len(quiet.ledger(proj)["launches"]) == 1      # one record, no second take-over
        c = quiet.close(proj, g, wait=0, sleep=lambda s: None)
        assert not c["closed"] and c["code"] == "still_running" and killed == [] and her.poll() is None
    finally:
        for q in (her, late): q.kill(); q.wait(10)
        proc.pids = []
    c = quiet.close(proj, g); assert c["closed"] and c["code"] == "gone"

@pytest.mark.skipif(not POSIX, reason="a real child process stands in for the game; taskkill without /F needs a window")
def test_close_ends_only_the_game_m2w_opened(proj, tmp_path):
    g, proc = _game(tmp_path); op = Opener()
    quiet.set_policy(projects.find(str(proj))["id"], "always")
    game = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        def opener(url): op.urls.append(url); proc.pids = [game.pid]; return True       # Steam starts "the game"
        r = quiet.launch(proj, g, opener=opener, settle=5, sleep=lambda s: None)
        assert r["launched"] and r["pids"] == [game.pid]
        assert quiet.decide(proj, g)["code"] == "open"                               # one open game at a time
        c = quiet.close(proj, g, sleep=lambda s: game.poll()); assert c["closed"] and c["code"] == "closed"
        assert game.wait(10) is not None and quiet.ledger(proj)["launches"][-1]["state"] == "closed"
    finally:
        if game.poll() is None: game.kill()
    her = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])    # she opens the game herself afterwards
    try:
        proc.pids = [her.pid]
        c = quiet.close(proj, g); assert not c["closed"] and c["code"] == "not_ours" and her.poll() is None
    finally: her.kill(); her.wait(10)


def test_a_reused_pid_is_not_closed(proj, tmp_path, monkeypatch):
    g, proc = _game(tmp_path); killed = []
    monkeypatch.setattr(quiet, "_terminate", lambda pid: killed.append(pid) or True)
    quiet.set_policy(projects.find(str(proj))["id"], "always")
    _launch(proj, g, Opener())
    quiet._update(proj, lambda L: L["launches"][-1].update(pids=[{"pid": os.getpid(), "start": "not-this-process"}]))
    proc.pids = [os.getpid()]
    monkeypatch.setattr(quiet, "proc_start", lambda pid: "another-start")
    c = quiet.close(proj, g); assert c["code"] == "gone" and killed == []


def test_cli_launch_needs_her_yes(proj, tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"; d = _steam(home, "linux", 413150, "Stardew Valley"); (d / "Stardew Valley.dll").touch()
    monkeypatch.setenv("HOME", str(home)); monkeypatch.setattr(games.Game, "running", lambda self: False); monkeypatch.setattr(games.Game, "pids", lambda self: [])
    opened = []; monkeypatch.setattr(quiet, "open_link", lambda url, sys_=None: opened.append(url) or True)
    pid = projects.find(str(proj))["id"]
    assert cli.main(["native", "launch", "--project", pid, "--yes", "--settle", "0"]) == 2 and opened == []    # --yes is not her yes
    assert "--yes no longer opens the game" in capsys.readouterr().err
    assert cli.main(["native", "launch", "--project", pid, "--settle", "0"]) == 2 and len(_cards(proj)) == 1
    _answer(proj, "now")
    assert cli.main(["native", "launch", "--project", pid, "--dry-run"]) == 0 and opened == []
    assert cli.main(["native", "launch", "--project", pid, "--settle", "0", "--round", "r1"]) == 0 and opened == ["steam://rungameid/413150"]
    assert cli.main(["native", "launches", "--project", pid]) == 0 and "r1: 1" in capsys.readouterr().out
    assert cli.main(["native", "close", "--project", pid]) == 0


def test_minecraft_cannot_be_opened_from_here(tmp_path):
    e = projects.create("MC", "feature", game="minecraft", build_mode="native"); root = Path(e["path"])
    g, _ = _game(tmp_path, "minecraft"); quiet.set_policy(e["id"], "always")
    r = _launch(root, g, Opener()); assert r["manual"] and not r["launched"] and "她开的游戏 GameAnything 不会关" in r["why"]
    assert quiet.close(root, g)["code"] == "none"


def test_pids_from_tasklist(tmp_path, monkeypatch):
    g = games.get("stardew", sys_="windows", home=tmp_path, env=_env(tmp_path))
    out = '"System","4","Services","0","1 K"\n"StardewModdingAPI.exe","9120","Console","1","300,000 K"\n"Stardew Valley.exe","77","Console","1","5 K"\n'
    monkeypatch.setattr(games, "_run", lambda args, timeout=20: subprocess.CompletedProcess(args, 0, out, ""))
    assert g.pids() == [9120, 77]


# ---------------------------------------------------------------- the small window, put back
def test_small_window_and_put_back(tmp_path):
    home = tmp_path / "home"; gd = _steam(home, "linux", 646570, "SlayTheSpire"); (gd / "desktop-1.0.jar").write_bytes(b"PK")
    g = games.get("slay_the_spire", sys_="linux", home=home, env=_env(tmp_path)); g.running = lambda: False
    cfg = gd / "info.displayconfig"; orig = b"1920\r\n1080\r\n60\r\ntrue\r\nfalse\r\ntrue\r\n"; cfg.write_bytes(orig)
    w = quiet.small_window(g); assert w["changed"] == ["width", "height", "fullscreen"]
    assert cfg.read_bytes() == b"1280\r\n720\r\n60\r\nfalse\r\nfalse\r\ntrue\r\n"
    assert quiet.small_window(g)["changed"] == []                                     # twice: the old values stay hers
    r = quiet.restore_window(g); assert sorted(r["restored"]) == ["fullscreen", "height", "width"] and cfg.read_bytes() == orig
    assert quiet.restore_window(g) == {}
    quiet.small_window(g); cfg.write_bytes(b"1600\r\n720\r\n60\r\nfalse\r\nfalse\r\ntrue\r\n")          # she changed the width meanwhile
    r = quiet.restore_window(g); assert r["kept"] == ["width"] and cfg.read_bytes() == b"1600\r\n1080\r\n60\r\ntrue\r\nfalse\r\ntrue\r\n"
    g.running = lambda: True; quiet.small_window(g); assert quiet.restore_window(g) == {"pending": True}     # not while the game runs
    mc = games.get("minecraft", sys_="linux", home=home, env=_env(tmp_path)); mc.running = lambda: False
    (home / ".minecraft").mkdir(); o = home / ".minecraft" / "options.txt"; o.write_text("version:3953\nfullscreen:true\npauseOnLostFocus:true\nlang:zh_cn\n", encoding="utf-8")
    assert quiet.small_window(mc)["changed"] == ["fullscreen", "pauseOnLostFocus"] and "fullscreen:false\npauseOnLostFocus:false" in o.read_text(encoding="utf-8")
    quiet.restore_window(mc); assert o.read_text(encoding="utf-8") == "version:3953\nfullscreen:true\npauseOnLostFocus:true\nlang:zh_cn\n"
    assert quiet.small_window(games.get("stardew", sys_="linux", home=home, env=_env(tmp_path)))["how"]   # no file edited: what she can set


def test_launch_uses_the_small_window_and_close_puts_it_back(tmp_path):
    e = projects.create("STS", "gameplay", game="slay_the_spire", build_mode="native"); root = Path(e["path"]); quiet.set_policy(e["id"], "always")
    home = tmp_path / "home"; gd = _steam(home, "linux", 646570, "SlayTheSpire"); (gd / "desktop-1.0.jar").write_bytes(b"PK")
    g = games.get("slay_the_spire", sys_="linux", home=home, env=_env(tmp_path)); g.running = lambda: False; g.pids = lambda: []
    cfg = gd / "info.displayconfig"; cfg.write_text("1920\n1080\n60\ntrue\nfalse\ntrue\n", encoding="utf-8")
    r = _launch(root, g, Opener()); assert r["launched"] and r["window"]["changed"] and cfg.read_text(encoding="utf-8").startswith("1280\n720")
    c = quiet.close(root, g); assert c["code"] == "gone" and cfg.read_text(encoding="utf-8") == "1920\n1080\n60\ntrue\nfalse\ntrue\n"


# ---------------------------------------------------------------- hot reload
def _oc2(tmp):
    home = tmp / "home"; d = _steam(home, "linux", 728880, "Overcooked! 2"); m = d / "Overcooked2_Data/Managed"; m.mkdir(parents=True)
    make_dll(m / "Assembly-CSharp.dll", "Assembly-CSharp", refs=[("mscorlib", (2, 0, 0, 0))], types=[("", "ClientKitchenLoader", None, [], ["Load"])])
    make_dll(m / "mscorlib.dll", "mscorlib", (2, 0, 0, 0), types=[("System", "Object", None, [], [".ctor", "ToString"])])
    (d / "BepInEx/core").mkdir(parents=True); (d / "run_bepinex.sh").write_text("x", encoding="utf-8")
    make_dll(d / "BepInEx/core/BepInEx.dll", "BepInEx", types=[("BepInEx", "BepInPlugin", None, [], [".ctor"]), ("BepInEx", "BaseUnityPlugin", None, [], ["get_Logger"])])
    g = games.get("overcooked2", sys_="linux", home=home, env=_env(tmp)); g.running = lambda: False
    return g, d


def _plugin(p, mscorlib=(2, 0, 0, 0), member="Load", attr=True):
    trs = [(1, "System", "Object"), (2, "", "ClientKitchenLoader")] + ([(3, "BepInEx", "BepInPlugin")] if attr else [])
    return make_dll(p, p.stem, refs=[("mscorlib", mscorlib), ("Assembly-CSharp", (0, 0, 0, 0)), ("BepInEx", (0, 0, 0, 0))], typerefs=trs,
                    types=[("M2W", "Plugin", 1, [], ["Awake"])], memberrefs=[(1, ".ctor"), (2, member)] + ([(3, ".ctor")] if attr else []))


def test_reload_overcooked2_through_scriptengine(tmp_path):
    g, d = _oc2(tmp_path); built = tmp_path / "build" / "M2WSmoke"; _plugin(built / "M2WSmoke.dll")
    with pytest.raises(checks.NoReload, match="ScriptEngine"): checks.reload(g, built)
    (d / "BepInEx/plugins/ScriptEngine").mkdir(parents=True); (d / "BepInEx/plugins/ScriptEngine/ScriptEngine.dll").write_bytes(b"MZ")
    r = checks.reload(g, built); assert r["copied"] == [str(d / "BepInEx/scripts/M2WSmoke.dll")] and "--setup" in r["how"]
    assert "scripts/M2WSmoke.dll" in g.mods()
    cfg = d / "BepInEx/config" / checks.SCRIPTENGINE_CFG; cfg.parent.mkdir(parents=True)
    cfg.write_text("[General]\nLoadOnStart = false\nReloadKey = F6\n\n[AutoReload]\nEnableFileSystemWatcher = false\n", encoding="utf-8")
    r = checks.reload(g, built); assert "--setup" in r["how"] and r["replaced_to_trash"]                     # the old copy goes to the trash
    assert any("LoadOnStart" in w for w in r["warnings"]) and any("SymbolsNotFoundException" in w for w in r["warnings"])   # no .pdb next to it
    (built / "M2WSmoke.pdb").write_bytes(b"BSJB")                              # ScriptEngine reads symbols: the .pdb must go along
    r = checks.reload(g, built, setup=True); c = cfg.read_text(encoding="utf-8")
    assert "EnableFileSystemWatcher = true" in c and "LoadOnStart = true" in c and "ReloadKey = F6" in c and "下次开游戏" in r["how"] and not r["warnings"]
    r = checks.reload(g, built); assert "自己重载" in r["how"] and not r.get("setup")                       # the settings were on already
    assert str(d / "BepInEx/scripts/M2WSmoke.pdb") in r["copied"] and (d / "BepInEx/scripts/M2WSmoke.pdb").read_bytes() == b"BSJB"
    assert not [p for p in (d / "BepInEx/scripts").iterdir() if p.name.startswith(".m2w-new-")]   # no temp file left (and none ends in .dll)
    assert list((g.root / "config-backups").glob("*" + checks.SCRIPTENGINE_CFG))
    out = g.uninstall("scripts/M2WSmoke.dll"); assert not (d / "BepInEx/scripts/M2WSmoke.dll").exists()
    assert out["pdb_to_trash"] and not (d / "BepInEx/scripts/M2WSmoke.pdb").exists()


def test_reload_cities_and_the_games_without_it(tmp_path):
    home = tmp_path / "home"
    for gid in ("stardew", "slay_the_spire", "minecraft", "sims4"):
        with pytest.raises(checks.NoReload, match="重开游戏"): checks.reload(games.get(gid, sys_="linux", home=home, env=_env(tmp_path)), tmp_path)
    with pytest.raises(checks.NoReload, match="Linux.*重开游戏"):                  # the Linux game did not reload a replaced DLL (2026-10-25)
        checks.reload(games.get("cities_skylines", sys_="linux", home=home, env=_env(tmp_path)), tmp_path)
    g = games.get("cities_skylines", sys_="mac", home=home, env=_env(tmp_path))
    built = tmp_path / "build" / "Memories"; built.mkdir(parents=True); (built / "Memories.dll").write_bytes(b"v2")
    with pytest.raises(games.NativeError, match="还没装过"): checks.reload(g, built)
    inst = g.mods_dir() / "Memories"; inst.mkdir(parents=True); (inst / "Memories.dll").write_bytes(b"v1")
    r = g._reg(); r["cities_skylines"] = {"Memories": {"path": str(inst), "from": "x", "at": "now"}}; g._save_reg(r)
    out = checks.reload(g, built); assert (inst / "Memories.dll").read_bytes() == b"v2" and out["replaced_to_trash"] and "主菜单" in out["how"]


# ---------------------------------------------------------------- headless checks
def test_check_overcooked2_plugin(tmp_path):
    g, d = _oc2(tmp_path)
    ok = checks.check(g, _plugin(tmp_path / "ok" / "Good.dll")); assert ok["ok"], ok
    bad = checks.check(g, _plugin(tmp_path / "bad" / "Bad.dll", mscorlib=(4, 0, 0, 0), member="LoadAll", attr=False))
    e = " ".join(bad["mods"][0]["errors"]); w = " ".join(bad["mods"][0]["warnings"])
    assert not bad["ok"] and ".NET 3.5" in e and "ClientKitchenLoader.LoadAll" in e and "BepInPlugin" in w


def test_check_cities_references(tmp_path):
    home = tmp_path / "home"; d = _steam(home, "linux", 255710, "Cities_Skylines"); m = d / "Cities_Data/Managed"; m.mkdir(parents=True)
    make_dll(m / "ICities.dll", "ICities", types=[("ICities", "IUserMod", None, [], ["get_Name", "get_Description"]), ("ICities", "LoadingExtensionBase", None, [], ["OnLevelLoaded"])])
    make_dll(m / "mscorlib.dll", "mscorlib", (2, 0, 0, 0), types=[("System", "Object", None, [], [".ctor"])])
    g = games.get("cities_skylines", sys_="linux", home=home, env=_env(tmp_path))
    good = make_dll(tmp_path / "Good/Good.dll", "Good", refs=[("mscorlib", (2, 0, 0, 0)), ("ICities", (1, 0, 0, 0))],
                    typerefs=[(1, "System", "Object"), (2, "ICities", "IUserMod"), (2, "ICities", "LoadingExtensionBase")],
                    types=[("M", "Mod", 1, [], ["get_Name"]), ("M", "Loader", 3, [], ["OnLevelLoaded"])], memberrefs=[(1, ".ctor"), (3, "OnLevelLoaded")])
    assert checks.check(g, good.parent)["ok"]
    bad = make_dll(tmp_path / "Bad/Bad.dll", "Bad", refs=[("mscorlib", (2, 0, 0, 0)), ("ICities", (1, 0, 0, 0)), ("CitiesHarmony.API", (2, 0, 0, 0))],
                   typerefs=[(1, "System", "Object"), (2, "ICities", "ILoadingThing")], types=[("M", "Mod", 1, [], [])])
    e = " ".join(checks.check(g, bad.parent)["mods"][0]["errors"])
    assert "CitiesHarmony.API.dll" in e and "ICities: ICities.ILoadingThing" in e and "IUserMod" in e
    src_only = tmp_path / "Src"; (src_only / "Source").mkdir(parents=True); (src_only / "Source/Mod.cs").write_text("//", encoding="utf-8")
    n = checks.check(g, src_only)["mods"][0]; assert not n["errors"] and "自己编译" in n["notes"][0]


def test_check_stardew_manifest_and_dll(tmp_path):
    home = tmp_path / "home"; d = _steam(home, "linux", 413150, "Stardew Valley")
    make_dll(d / "Stardew Valley.dll", "Stardew Valley", types=[("StardewValley", "Game1", None, ["player"], ["get_player"])])
    make_dll(d / "StardewModdingAPI.dll", "StardewModdingAPI", types=[("StardewModdingAPI", "Mod", None, [], ["get_Helper", "Entry"])])
    g = games.get("stardew", sys_="linux", home=home, env=_env(tmp_path))
    mod = tmp_path / "Hello"; mod.mkdir()
    (mod / "manifest.json").write_text('{\n  // comments are fine\n  "Name": "Hello", "Author": "m2w", "Version": "1.0.0", "UniqueID": "m2w.Hello", "EntryDll": "Hello.dll",\n}', encoding="utf-8")
    make_dll(mod / "Hello.dll", "Hello", refs=[("System.Runtime", (6, 0, 0, 0)), ("StardewModdingAPI", (4, 0, 0, 0)), ("Stardew Valley", (1, 6, 0, 0))],
             typerefs=[(2, "StardewModdingAPI", "Mod"), (3, "StardewValley", "Game1")], types=[("Hello", "ModEntry", 1, [], ["Entry"])],
             memberrefs=[(2, "get_player"), (1, "get_Helper")])
    assert checks.check(g, mod)["ok"]
    make_dll(mod / "Hello.dll", "Hello", refs=[("System.Runtime", (8, 0, 0, 0)), ("StardewModdingAPI", (4, 0, 0, 0))], typerefs=[(2, "StardewModdingAPI", "Mod")],
             memberrefs=[(1, "get_Monitor")])
    e = " ".join(checks.check(g, mod)["mods"][0]["errors"]); assert ".NET 8" in e and "Mod.get_Monitor" in e
    (mod / "manifest.json").write_text('{"Name": "Hello", "Version": "1", "UniqueID": "x", "EntryDll": "Nope.dll"}', encoding="utf-8")
    e = " ".join(checks.check(g, mod)["mods"][0]["errors"]); assert "author" in e and "Nope.dll" in e
    cp = tmp_path / "[CP] Hello"; cp.mkdir()
    (cp / "manifest.json").write_text('{"Name": "H", "Author": "a", "Version": "1", "UniqueID": "a.h", "ContentPackFor": {"UniqueID": "Pathoschild.ContentPatcher"}}', encoding="utf-8")
    e = checks.check(g, cp)["mods"][0]["errors"][0]
    assert "Pathoschild.ContentPatcher" in e and "https://www.nexusmods.com/stardewvalley/mods/1915" in e
    assert g.extras() == [{"name": "Content Patcher", "ok": False, "version": None, "url": "https://www.nexusmods.com/stardewvalley/mods/1915",
                           "detail": "not installed; only content packs (ContentPackFor Pathoschild.ContentPatcher) need it: https://www.nexusmods.com/stardewvalley/mods/1915"}]
    (d / "Mods/ContentPatcher").mkdir(parents=True); (d / "Mods/ContentPatcher/manifest.json").write_text('{"UniqueID": "Pathoschild.ContentPatcher"}', encoding="utf-8")
    assert checks.check(g, cp)["ok"]
    (d / "Mods/ContentPatcher/manifest.json").write_text('{"UniqueID": "Pathoschild.ContentPatcher", "Version": "2.9.1", // ok\n}', encoding="utf-8")
    x = g.info()["extras"][0]; assert x["ok"] and x["version"] == "2.9.1" and "2.9.1 installed" in x["detail"]
    other = tmp_path / "[CP] Other"; other.mkdir()             # a pack for another framework: no Content Patcher link in its message
    (other / "manifest.json").write_text('{"Name": "O", "Author": "a", "Version": "1", "UniqueID": "a.o", "ContentPackFor": {"UniqueID": "x.Json"}}', encoding="utf-8")
    e = checks.check(g, other)["mods"][0]["errors"][0]; assert "x.Json" in e and "nexusmods" not in e


def test_check_slay_the_spire_jar(tmp_path):
    home = tmp_path / "home"; gd = _steam(home, "linux", 646570, "SlayTheSpire")
    with zipfile.ZipFile(gd / "desktop-1.0.jar", "w") as z:
        z.writestr("com/megacrit/cardcrawl/cards/AbstractCard.class", make_class("com/megacrit/cardcrawl/cards/AbstractCard"))
        z.writestr("com/badlogic/gdx/graphics/Color.class", make_class("com/badlogic/gdx/graphics/Color"))
    (gd / "ModTheSpire.jar").write_bytes(b"")
    with zipfile.ZipFile(gd / "ModTheSpire.jar", "w") as z: z.writestr("com/evacipated/cardcrawl/modthespire/lib/SpirePatch.class", make_class("com/evacipated/cardcrawl/modthespire/lib/SpirePatch"))
    (gd / "mods").mkdir()
    with zipfile.ZipFile(gd / "mods/BaseMod.jar", "w") as z: z.writestr("basemod/BaseMod.class", make_class("basemod/BaseMod"))
    g = games.get("slay_the_spire", sys_="linux", home=home, env=_env(tmp_path))

    def jar(p, refs, major=52):
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("ModTheSpire.json", json.dumps({"modid": "phd"}))
            z.writestr("phd/Card.class", make_class("phd/Card", ["com/megacrit/cardcrawl/cards/AbstractCard", "basemod/BaseMod", "phd/Util", *refs], major))
            z.writestr("phd/Util.class", make_class("phd/Util", ["java/util/List"]))
        return p
    assert checks.check(g, jar(tmp_path / "ok.jar", ["[Lcom/badlogic/gdx/graphics/Color;"]))["ok"]
    e = " ".join(checks.check(g, jar(tmp_path / "bad.jar", ["com/megacrit/cardcrawl/cards/AbstractKard"], major=55))["mods"][0]["errors"])
    assert "Java 11" in e and "com.megacrit.cardcrawl.cards.AbstractKard" in e


def _fabric_jar(p, fmj, classes=(), extra=None):
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("fabric.mod.json", json.dumps(fmj))
        for c in classes: z.writestr(c + ".class", make_class(c, major=65))
        for n, b in (extra or {}).items(): z.writestr(n, b)
    return p


def _mc(tmp):
    home = tmp / "home"; u = home / ".minecraft"; (u / "versions/1.21.1").mkdir(parents=True); (u / "versions/fabric-loader-0.16.5-1.21.1").mkdir(); (u / "mods").mkdir()
    return games.get("minecraft", sys_="linux", home=home, env=_env(tmp)), u


def test_check_minecraft_jar(tmp_path):
    g, u = _mc(tmp_path)
    fmj = {"schemaVersion": 1, "id": "m2w_hello", "version": "1.0", "entrypoints": {"main": ["m2w.Hello"], "client": [{"value": "m2w.HelloClient::init"}]},
           "mixins": ["m2w.mixins.json"], "depends": {"fabricloader": ">=0.16", "minecraft": "~1.21.1", "fabric-api": "*"}}
    mix = json.dumps({"package": "m2w.mixin", "mixins": ["TitleMixin"], "client": ["client.HudMixin"]})
    good = _fabric_jar(tmp_path / "hello.jar", fmj, ["m2w/Hello", "m2w/HelloClient", "m2w/mixin/TitleMixin", "m2w/mixin/client/HudMixin"], {"m2w.mixins.json": mix})
    r = checks.check(g, good); e = r["mods"][0]["errors"]; assert e == ["这个 mod 需要 Fabric API，但 mods/ 里没有 fabric-api-*.jar"]
    _fabric_jar(u / "mods/fabric-api-0.100.0.jar", {"id": "fabric-api", "version": "0.100.0"})
    r = checks.check(g, good); assert r["ok"] and any("Java 21" in n for n in r["mods"][0]["notes"]) and any("1.21.1" in n for n in r["mods"][0]["notes"])
    bad = _fabric_jar(tmp_path / "bad.jar", {**fmj, "id": "M2W Hello"}, ["m2w/Hello"], {"m2w.mixins.json": mix})
    e = " ".join(checks.check(g, bad)["mods"][0]["errors"])
    assert "M2W Hello" in e and "m2w.HelloClient::init" in e and "TitleMixin" in e and "client.HudMixin" in e


FAKE_JAVA = r'''#!{py}
import sys
mode = open(sys.argv[0] + ".mode", encoding="utf-8").read().strip()
if "-Dfabric-api.gametest" in sys.argv:
    print("[Server thread/INFO]: All 3 required tests passed :)"); sys.exit(0 if mode == "ok" else 1)
if mode == "bad":
    print("[main/ERROR]: Incompatible mods found!"); sys.exit(1)
print("[Server thread/INFO]: Loading 2 mods"); print('[Server thread/INFO]: Done (1.234s)! For help, type "help"'); sys.stdout.flush()
for line in sys.stdin:
    if line.strip() == "stop": print("[Server thread/INFO]: Stopping the server"); sys.exit(0)
'''


@pytest.mark.skipif(not POSIX, reason="the fake java is a script with a #! line")
def test_check_minecraft_headless_server(tmp_path):
    g, u = _mc(tmp_path)
    _fabric_jar(u / "mods/fabric-api-0.100.0.jar", {"id": "fabric-api", "version": "0.100.0"}); _fabric_jar(u / "mods/sodium.jar", {"id": "sodium", "version": "1"})
    jar = _fabric_jar(tmp_path / "hello.jar", {"id": "m2w_hello", "version": "1", "entrypoints": {"main": ["m2w.Hello"]}, "depends": {"fabric-api": "*"}}, ["m2w/Hello"])
    java = tmp_path / "bin" / "java"; java.parent.mkdir(); java.write_text(FAKE_JAVA.replace("{py}", sys.executable), encoding="utf-8"); java.chmod(0o755)
    g.env["GAMEANYTHING_JAVA"] = str(java); (java.parent / "java.mode").write_text("ok", encoding="utf-8")
    e = checks.check(g, jar, server=True)["mods"][0]["errors"]; assert "fabric-server-launch.jar" in e[0]
    sd = checks.server_dir(g); sd.mkdir(parents=True); (sd / "fabric-server-launch.jar").write_bytes(b"PK")
    e = checks.check(g, jar, server=True)["mods"][0]["errors"]; assert "eula=true" in e[0] and not (sd / "eula.txt").exists()   # never accepted for her
    (sd / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    r = checks.check(g, jar, server=True, timeout=30); it = r["mods"][0]
    assert r["ok"] and it["server"] and sorted(p.name for p in (sd / "mods").iterdir()) == ["fabric-api-0.100.0.jar", "hello.jar"]     # not her other mods
    assert "Done (" in (sd / "m2w-check.log").read_text(encoding="utf-8") and "online-mode=false" in (sd / "server.properties").read_text(encoding="utf-8")
    assert checks.check(g, jar, gametest=True, timeout=30)["ok"]
    (java.parent / "java.mode").write_text("bad", encoding="utf-8")
    r = checks.check(g, jar, server=True, timeout=30); assert not r["ok"] and any("Incompatible mods" in x for x in r["mods"][0]["errors"])
    assert list((g.root / ".trash").glob("*mc-server-mods"))                         # the earlier server mods went to the trash
    client = _fabric_jar(tmp_path / "c.jar", {"id": "m2w_c", "version": "1", "environment": "client"})
    assert "只在客户端" in checks.check(g, client, server=True)["mods"][0]["notes"][-1]


def test_check_sims4(tmp_path):
    home = tmp_path / "home"; u = home / "Documents/Electronic Arts/The Sims 4"; u.mkdir(parents=True)
    g = games.get("sims4", sys_="mac", home=home, env=_env(tmp_path))
    mod = tmp_path / "Hello"; mod.mkdir()
    with zipfile.ZipFile(mod / "Hello.ts4script", "w") as z: z.writestr("hello.pyc", checks.PY37_MAGIC + b"\0" * 12)
    s4pkg.write_package(mod / "Hello.package", [(0x220557DA, 0, 1, b"strings")])
    r = checks.check(g, mod); assert r["ok"] and "1 个资源" in r["mods"][0]["notes"][0]
    with zipfile.ZipFile(mod / "Hello.ts4script", "w") as z: z.writestr("hello.pyc", b"\x55\x0d\x0d\x0a" + b"\0" * 12)      # 3.8+
    assert "Python 3.7" in checks.check(g, mod)["mods"][0]["errors"][0]


def test_check_cli(proj, tmp_path, monkeypatch, capsys):
    pid = projects.find(str(proj))["id"]
    assert cli.main(["native", "reload", "--project", pid, str(tmp_path)]) == 3 and "no hot reload" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="没有要查的 mod"): cli.main(["native", "check", "--project", pid])


# ---------------------------------------------------------------- the page: the dialog's API and its English
@pytest.fixture
def server():
    from gameanything.ui import serve
    box, ready = {}, threading.Event()

    def up(srv): box["srv"] = srv; ready.set()
    threading.Thread(target=serve, args=(None,), kwargs={"port": 0, "ready": up}, daemon=True).start()
    assert ready.wait(20)
    yield f"http://127.0.0.1:{box['srv'].server_port}"
    box["srv"].shutdown(); box["srv"].server_close()


def _req(url, data=None, lang=None):
    h = {"Content-Type": "application/json", **({"X-Lang": lang} if lang else {})}
    r = urllib.request.Request(url, json.dumps(data).encode() if data is not None else None, h)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp: return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")


def test_project_menu_api(proj, server):
    pid = projects.find(str(proj))["id"]; _req(server + "/api/projects/open", {"id": pid})
    sh = _req(server + "/api/shell")[1]; assert sh["native_launch"]["mode"] == "ask"
    st, r = _req(server + "/api/projects/launch", {"id": pid, "mode": "window", "window": "23:00-07:00"})
    assert st == 200 and r["native_launch"] == {"mode": "window", "window": "23:00-07:00", "idle_minutes": 10, "drive": "idle", "front": "never", "hands": "agent", "chosen": True} and quiet.policy(proj)["mode"] == "window"
    st, r = _req(server + "/api/projects/launch", {"id": pid, "mode": "idle", "window": "23:00-07:00", "minutes": "25", "drive": "always"})
    assert st == 200 and r["native_launch"] == {"mode": "idle", "window": "23:00-07:00", "idle_minutes": 25, "drive": "always", "front": "never", "hands": "agent", "chosen": True}
    assert sh["native_ready"] == {"hands": "agent", "front": "never", "chat": None, "build": None}          # 能不能操作屏幕 (ready.py, 2026-11-01)
    st, r = _req(server + "/api/projects/launch", {"id": pid, "mode": "idle", "front": "away", "hands": "self"})
    assert st == 200 and (r["native_launch"]["front"], r["native_launch"]["hands"]) == ("away", "self") and r["native_ready"]["hands"] == "self"
    for k, v, msg in (("front", "always", "Bringing the game to the front should be never or away"), ("hands", "robot", "Who clicks should be agent or self")):
        st, bad = _req(server + "/api/projects/launch", {"id": pid, "mode": "idle", k: v}, lang="en"); assert st == 400 and bad["error"] == msg
    st, bad = _req(server + "/api/projects/launch", {"id": pid, "mode": "sometimes"}, lang="en")
    assert st == 400 and bad["error"] == "When to open the game should be ask, window, always or idle"
    st, bad = _req(server + "/api/projects/launch", {"id": pid, "mode": "idle", "minutes": "0"}, lang="en")
    assert st == 400 and bad["error"] == "The minutes away from the computer should be a whole number from 1 to 720"
    st, bad = _req(server + "/api/projects/launch", {"id": pid, "mode": "idle", "drive": "sometimes"}, lang="en")
    assert st == 400 and bad["error"] == "Driving the game should be idle or always"
    st, bad = _req(server + "/api/projects/launch", {"id": pid, "mode": "window", "window": "late"}, lang="en")
    assert st == 400 and bad["error"] == "The time window should look like 22:00-08:00"


@pytest.mark.skipif(not __import__("shutil").which("node"), reason="node is not installed")
def test_dialog_texts_have_english():
    static = Path(quiet.__file__).parent.parent / "ui" / "static"
    from test_ui_onboard import NODE_PRELUDE, _node
    keys = sorted(quiet.TEXTS)
    miss = _node(NODE_PRELUDE + (static / "i18n.js").read_text(encoding="utf-8") + f"\nconsole.log(JSON.stringify({json.dumps(keys, ensure_ascii=False)}.filter(k => !(k in EN))))")
    assert miss == []
    m = (static / "manage.js").read_text(encoding="utf-8")
    assert '["launch", "play", "什么时候开游戏"]' in m and "launch: launchDialog" in m and "launch: H.can.edit" in m


def test_doctor_names_content_patcher_as_a_hint(tmp_path, monkeypatch, capsys):
    """`native doctor --game stardew`: Content Patcher missing is a hint with the Nexus link (only content packs need it), not an error."""
    from gameanything import cli
    gd = tmp_path / "Stardew Valley"; (gd / "Mods").mkdir(parents=True)
    (gd / "Stardew Valley.dll").write_bytes(b"MZ"); (gd / "StardewModdingAPI.dll").write_bytes(b"MZ")
    for k, v in {"GAMEANYTHING_STARDEW_DIR": gd, "GAMEANYTHING_DATA": tmp_path / "data"}.items(): monkeypatch.setenv(k, str(v))
    assert cli.main(["native", "doctor", "--game", "stardew"]) == 0
    out = capsys.readouterr().out
    assert "loader SMAPI: ok" in out and "extra  Content Patcher: not installed; only content packs" in out
    assert "https://www.nexusmods.com/stardewvalley/mods/1915" in out
    (gd / "Mods/Group/ContentPatcher").mkdir(parents=True)
    (gd / "Mods/Group/ContentPatcher/manifest.json").write_text('{"UniqueID": "Pathoschild.ContentPatcher", "Version": "2.9.1"}', encoding="utf-8")
    assert cli.main(["native", "doctor", "--game", "stardew"]) == 0
    assert "extra  Content Patcher: 2.9.1 installed (content packs work)" in capsys.readouterr().out
    assert cli.main(["native", "doctor", "--game", "stardew", "--json"]) == 0
    x = json.loads(capsys.readouterr().out)["games"][0]["extras"][0]; assert x["ok"] and x["version"] == "2.9.1"
