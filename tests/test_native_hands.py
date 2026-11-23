"""本机模式少打扰, part 2 (native/idle.py, native/hands.py; 2026-10-24): idle time per system from fake tool output
and fake Win32 calls; `native_launch: idle` opens the game only after she has been away N minutes and asks with the card when the
computer cannot tell; shot / drive act only on the game m2w opened, refuse while she is at the computer (unless native_drive: always),
stop as soon as she comes back, never count m2w's own input as hers; the permission check's explanations; the X11 command lines; the
plain PNG writer; Application.runInBackground in the smoke plugins. Fakes only: no game, no real input, no real screen."""
import os
import struct
import zlib
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from gameanything import cli, projects
from gameanything.conversation import Thread
from gameanything.native import games, hands, idle, quiet

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "gameanything"


def _env(tmp): return {"GAMEANYTHING_DATA": str(tmp / "m2w")}


class Proc:
    def __init__(self, pids=None, running=False): self.pids = list(pids or []); self.running = running


def _game(tmp, gid="stardew", proc=None):
    g = games.get(gid, sys_="linux", home=tmp / "home", env=_env(tmp)); proc = proc or Proc()
    g.running = lambda: proc.running or bool(proc.pids); g.pids = lambda: list(proc.pids)
    return g, proc


@pytest.fixture
def proj():
    e = projects.create("少打扰 二", "feature", game="stardew", build_mode="native"); return Path(e["path"])


def _pid(root): return projects.find(str(root))["id"]


def _open_game(root, g, proc):
    """m2w opens 'the game' (this test process stands in for it) through the normal launch, with native_launch always."""
    quiet.set_policy(_pid(root), "always")

    def opener(url): proc.pids = [os.getpid()]; return True
    r = quiet.launch(root, g, opener=opener, settle=5, sleep=lambda s: None)
    assert r["launched"] and r["pids"] == [os.getpid()]
    return r


def _ok(out=""): return SimpleNamespace(returncode=0, stdout=out, stderr="")


# ---------------------------------------------------------------- idle time per system
IOREG = """+-o IOHIDSystem  <class IOHIDSystem, id 0x100000abc, registered, matched, active, busy 0 (0 ms), retain 30>
    {
      "HIDIdleTime" = 734125000000
      "HIDParameters" = {"HIDClickTime"=500000000}
      "IOClass" = "IOHIDSystem"
    }
+-o IOHIDSystem  <class IOHIDSystem, id 0x100000abd>
    {
      "HIDIdleTime" = 812000000000
    }
"""


def test_idle_parsers():
    assert idle.parse_ioreg(IOREG) == pytest.approx(734.125) and idle.parse_ioreg("no such key") is None and idle.parse_ioreg(None) is None
    assert idle.parse_xprintidle("45210\n") == pytest.approx(45.21) and idle.parse_xprintidle("") is None and idle.parse_xprintidle("err") is None
    assert idle.parse_mutter("(uint64 125000,)\n") == pytest.approx(125.0) and idle.parse_mutter("Error: no such name") is None


def test_idle_on_windows_from_fake_win32_calls():
    class User32:
        def __init__(self, t, ok=True): self.t = t; self.ok = ok

        def GetLastInputInfo(self, ref):
            ref._obj.dwTime = self.t; return self.ok
    k = lambda tick: SimpleNamespace(GetTickCount=lambda: tick)
    assert idle.win_idle(User32(1_000_000), k(1_090_500)) == pytest.approx(90.5)
    assert idle.win_idle(User32(0xFFFFFF00), k(0x000001F4)) == pytest.approx((0x1F4 + 0x100) / 1000)        # the 49.7-day wrap
    assert idle.win_idle(User32(5, ok=False), k(10)) is None


def test_idle_probe_per_system(monkeypatch):
    assert idle.x11_idle(SimpleNamespace(XOpenDisplay=lambda d: None), SimpleNamespace()) is None                   # no display
    runs = []

    def run(args, timeout=20):
        runs.append(args[0])
        return {"ioreg": _ok(IOREG), "xprintidle": _ok("3000\n"), "gdbus": _ok("(uint64 61000,)")}[args[0]]
    assert idle.probe("mac", run=run) == {"seconds": pytest.approx(734.125), "source": "ioreg HIDIdleTime"}
    monkeypatch.setattr(idle, "win_idle", lambda: 12.0)
    assert idle.probe("windows") == {"seconds": 12.0, "source": "GetLastInputInfo"}
    monkeypatch.setattr(idle.shutil, "which", lambda n: "/usr/bin/" + n)
    assert idle.probe("linux", env={"DISPLAY": ":0"}, run=run)["seconds"] == pytest.approx(3.0)
    assert idle.probe("linux", env={"WAYLAND_DISPLAY": "wayland-0"}, run=run) == {"seconds": pytest.approx(61.0), "source": "GNOME Mutter IdleMonitor (Wayland)"}
    monkeypatch.setattr(idle.shutil, "which", lambda n: None)                                   # Wayland without GNOME: unknown, never X11 under XWayland
    p = idle.probe("linux", env={"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}, run=run); assert p["seconds"] is None and "Wayland" in p["source"]
    monkeypatch.setattr(idle, "x11_idle", lambda: 7.5)
    assert idle.probe("linux", env={"DISPLAY": ":1"}, run=run) == {"seconds": 7.5, "source": "XScreenSaver extension"}
    assert idle.probe("linux", env={}, run=run)["seconds"] is None
    assert runs.count("ioreg") == 1


def test_cli_idle(monkeypatch, capsys):
    monkeypatch.setattr(idle, "probe", lambda *a, **k: {"seconds": 734.4, "source": "ioreg HIDIdleTime"})
    assert cli.main(["native", "idle"]) == 0; o = capsys.readouterr(); assert o.out.strip() == "734" and "ioreg" in o.err
    monkeypatch.setattr(idle, "probe", lambda *a, **k: {"seconds": None, "source": "Wayland: ..."})
    assert cli.main(["native", "idle"]) == 0 and capsys.readouterr().out.strip() == "unknown"


# ---------------------------------------------------------------- native_launch: idle
def test_idle_setting_and_cli(proj, capsys):
    pid = _pid(proj)
    assert cli.main(["project", "set-launch", pid, "idle", "--minutes", "15", "--drive", "always"]) == 0
    assert "native_launch=idle  window=22:00-08:00  idle_minutes=15  drive=always" in capsys.readouterr().out
    cfg = projects.config_of(proj); assert cfg["native_launch_idle_minutes"] == 15 and cfg["native_drive"] == "always" and cfg["build_mode"] == "native"
    for bad in (dict(minutes=0), dict(minutes="ten"), dict(minutes=721), dict(drive="sometimes")):
        with pytest.raises(ValueError): quiet.set_policy(pid, "idle", **bad)
    quiet.set_policy(pid, "ask"); p = quiet.policy(proj); assert p["mode"] == "ask" and p["idle_minutes"] == 15 and p["drive"] == "always"   # the rest stays


def test_idle_launch_gating(proj, tmp_path, monkeypatch):
    g, proc = _game(tmp_path); opened = []
    quiet.set_policy(_pid(proj), "idle", minutes=10)
    monkeypatch.setattr(idle, "seconds", lambda *a, **k: 95.0)                                   # she touched the mouse 95 s ago
    d = quiet.decide(proj, g); assert d["state"] == "pending" and d["code"] == "busy" and "10 分钟" in d["why"]
    assert Thread(proj).cards() == {}                                                       # no card, no question
    monkeypatch.setattr(idle, "seconds", lambda *a, **k: 11 * 60.0)
    r = quiet.launch(proj, g, opener=lambda u: opened.append(u) or True, settle=0, sleep=lambda s: None)
    assert r["launched"] and r["code"] == "idle" and opened == ["steam://rungameid/413150"]
    quiet.close(proj, g)
    assert quiet.decide(proj, g)["state"] == "go"                                                # no waiting between launches (her call, 2026-10-29)
    later = datetime.now().replace(microsecond=0) + __import__("datetime").timedelta(minutes=11)
    assert quiet.decide(proj, g, now=later)["state"] == "go"
    monkeypatch.setattr(idle, "seconds", lambda *a, **k: None)                                   # this computer cannot tell: ask with the card
    d = quiet.decide(proj, g, now=later); assert d["code"] == "asked" and d["why"].startswith("看不出她在不在用电脑") and len(Thread(proj).cards()) == 1


def test_idle_wait_picks_up_her_leaving(proj, tmp_path, monkeypatch):
    g, _ = _game(tmp_path); quiet.set_policy(_pid(proj), "idle", minutes=10); seq = iter([30.0, 200.0, 650.0])
    monkeypatch.setattr(idle, "seconds", lambda *a, **k: next(seq))
    d = quiet.wait_decision(proj, g, 60, poll=0, sleep=lambda s: None); assert d["state"] == "go" and d["code"] == "idle"


# ---------------------------------------------------------------- shot / drive: only m2w's game, never while she is there
class FakeBackend:
    name = "fake"

    def __init__(self, fg=True, wins=None):
        self.sent = []; self.fg = fg; self.wins = wins

    def windows(self, pids):
        return self.wins if self.wins is not None else [{"id": 7, "pid": pids[0], "title": "Stardew Valley", "x": 100, "y": 50, "w": 1280, "h": 720},
                                                          {"id": 8, "pid": pids[0], "title": "", "x": 0, "y": 0, "w": 10, "h": 10}]

    def shot(self, win, out): out.write_bytes(b"\x89PNG fake"); return {}
    def can_send(self, win, pids): return None if self.fg else "not in front"
    def send(self, win, step): self.sent.append((win["id"], step))


class Clock:
    def __init__(self, t=1_000_000.0): self.t = t

    def __call__(self): self.t += 0.1; return self.t


def test_steps_are_checked_first():
    assert hands.parse_steps(["key Enter", "click 640 360", "click 1 2 right", "type 你好 abc", "sleep 200", "key F5"]) == [
        ("key", "return"), ("click", 640, 360, "left"), ("click", 1, 2, "right"), ("type", "你好 abc"), ("sleep", 200), ("key", "f5")]
    for bad in (["key ctrl"], ["click 1"], ["click a b"], ["click 1 2 middle"], ["type"], ["sleep x"], ["sleep 999999"], ["jump"], []):
        with pytest.raises(ValueError): hands.parse_steps(bad)
    for k in hands.KEY_NAMES: assert k in hands.MAC_KEYS and k in hands.WIN_VK and k in hands.X11_KEYS


def test_shot_and_drive_refuse_what_m2w_did_not_open(proj, tmp_path):
    g, proc = _game(tmp_path); be = FakeBackend()
    with pytest.raises(hands.Refused) as e: hands.shot(proj, g, be=be)
    assert e.value.code == "none" and not e.value.pending
    proc.pids = [os.getpid()]                                                                    # she opened the game herself
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["key escape"], be=be, idle=lambda: 9999.0)
    assert e.value.code == "not_ours" and be.sent == []
    with pytest.raises(hands.Refused) as e: hands.shot(proj, g, be=be)
    assert e.value.code == "not_ours"
    quiet.set_policy(_pid(proj), "always", drive="always")          # her rule 2026-10-29: then her running game is the test game
    assert hands.shot(proj, g, be=be)["window"]["id"] == 7 and quiet.ledger(proj)["launches"][-1]["took_over"]
    assert hands.drive(proj, g, ["key escape"], be=be, idle=lambda: 0.0)["done"] == 1


def test_shot_of_the_game_window_only(proj, tmp_path):
    g, proc = _game(tmp_path); _open_game(proj, g, proc)
    r = hands.shot(proj, g, be=FakeBackend())
    assert r["window"]["id"] == 7 and Path(r["path"]).parent == proj / "5_build" / "native-shots" and Path(r["path"]).read_bytes().startswith(b"\x89PNG")
    assert "scale" not in r                                                                      # (not a real PNG: no size to compare)

    class Retina(FakeBackend):
        def shot(self, win, out): hands.write_png(out, 2560, 2, bytes(2560 * 2 * 3)); return {}
    r = hands.shot(proj, g, be=Retina()); assert r["scale"] == 2 and "÷ 2" in r["note"]
    with pytest.raises(hands.Refused) as e: hands.shot(proj, g, be=FakeBackend(wins=[]))
    assert e.value.code == "no_window"
    proc.pids = []                                                                               # the game exited
    with pytest.raises(hands.Refused) as e: hands.shot(proj, g, be=FakeBackend())
    assert e.value.code == "gone"


def test_drive_waits_for_her_to_be_away(proj, tmp_path):
    g, proc = _game(tmp_path); _open_game(proj, g, proc); be = FakeBackend()
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["key escape"], be=be, idle=lambda: 12.0)
    assert e.value.code == "active" and e.value.pending and be.sent == [] and quiet.ledger(proj)["launches"][-1]["paused"]
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["key escape"], be=be, idle=lambda: None)      # cannot tell: never drives
    assert e.value.code == "unknown" and not e.value.pending and be.sent == []
    r = hands.drive(proj, g, ["key escape", "sleep 10", "click 640 360"], be=be, idle=lambda: 300.0, sleep=lambda s: None)
    assert r["done"] == 2 and be.sent == [(7, ("key", "escape")), (7, ("click", 640, 360, "left"))]
    assert quiet.ledger(proj)["launches"][-1]["paused"] is None
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["key a"], be=FakeBackend(fg=False), idle=lambda: 300.0)
    assert e.value.code == "not_foreground"                                                      # Windows: never brought to the front


def test_drive_stops_when_she_comes_back(proj, tmp_path):
    g, proc = _game(tmp_path); _open_game(proj, g, proc); be = FakeBackend(); clk = Clock()
    vals = iter([400.0, 400.1, 400.2, 0.05])                  # at the start and before steps 1, 2: away (the same old input); before step 3: she just moved

    def her_idle():
        v = next(vals)
        if v < 1: clk.t += 5                                  # (her move comes a few seconds after m2w's key, not within OWN_INPUT_SLACK)
        return v
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["key w", "key a", "key s"], be=be, idle=her_idle, clock=clk)
    assert e.value.code == "active" and e.value.pending and [s for _, s in be.sent] == [("key", "w"), ("key", "a")]
    assert quiet.ledger(proj)["launches"][-1]["paused"]


def test_drive_notices_her_during_a_sleep_step(proj, tmp_path):
    g, proc = _game(tmp_path); _open_game(proj, g, proc); be = FakeBackend(); clk = Clock(); state = {"back": False}

    def sleep(s): clk.t += s; state["back"] = True              # she moves the mouse during the 5 s wait
    with pytest.raises(hands.Refused) as e:
        hands.drive(proj, g, ["sleep 5000", "key escape"], be=be, idle=lambda: 0.5 if state["back"] else 300.0, clock=clk, sleep=sleep)
    assert e.value.code == "active" and be.sent == []


def test_own_input_is_not_hers(proj, tmp_path):
    """Windows counts SendInput as input: right after m2w drove, the idle time is ~0 but the newest input was m2w's own."""
    g, proc = _game(tmp_path); _open_game(proj, g, proc); be = FakeBackend(); clk = Clock()
    hands.drive(proj, g, ["key w"], be=be, idle=lambda: 500.0, clock=clk)
    ours = quiet.ledger(proj)["launches"][-1]["drove_until"]
    clk.t = ours + 5                                           # 5 s later, the newest input is m2w's key (idle ~5 s)
    hands.drive(proj, g, ["key a"], be=be, idle=lambda: 5.0, clock=clk)
    assert [s for _, s in be.sent] == [("key", "w"), ("key", "a")]
    clk.t += 5                                                 # she typed 1 s ago, after m2w's last key: paused
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["key s"], be=be, idle=lambda: 1.0, clock=clk)
    assert e.value.code == "active"


def test_drive_always_when_she_allows_it(proj, tmp_path):
    g, proc = _game(tmp_path); _open_game(proj, g, proc); be = FakeBackend()
    quiet.set_policy(_pid(proj), "always", drive="always")
    assert hands.drive(proj, g, ["type hi", "key return"], be=be, idle=lambda: 0.0)["done"] == 2


def test_cli_shot_and_drive_exit_codes(proj, tmp_path, monkeypatch, capsys):
    g, proc = _game(tmp_path)
    monkeypatch.setattr(games.Game, "running", lambda self: bool(proc.pids)); monkeypatch.setattr(games.Game, "pids", lambda self: list(proc.pids))
    monkeypatch.setattr(hands, "backend", lambda *a, **k: FakeBackend())
    pid = _pid(proj)
    assert cli.main(["native", "drive", "--project", pid, "key escape"]) == 3 and "refused (none)" in capsys.readouterr().out
    assert cli.main(["native", "shot", "--project", pid]) == 3
    _open_game(proj, g, proc)
    monkeypatch.setattr(idle, "seconds", lambda *a, **k: 3.0)
    assert cli.main(["native", "drive", "--project", pid, "key escape"]) == 2 and "paused (active)" in capsys.readouterr().out
    monkeypatch.setattr(idle, "seconds", lambda *a, **k: 3000.0)
    assert cli.main(["native", "drive", "--project", pid, "key escape", "click 10 20"]) == 0 and "sent 2 step(s)" in capsys.readouterr().out
    out = tmp_path / "她的 截图.png"
    assert cli.main(["native", "shot", "--project", pid, "--out", str(out)]) == 0 and out.is_file() and str(out) in capsys.readouterr().out
    with pytest.raises(SystemExit): cli.main(["native", "drive", "--project", pid, "key ctrl"])


# ---------------------------------------------------------------- permissions
def test_permissions_explain_how(monkeypatch):
    monkeypatch.setattr(idle, "probe", lambda *a, **k: {"seconds": 5.0, "source": "ioreg HIDIdleTime"})
    r = hands.permissions("mac", mac=lambda: [False, True], app="Terminal.app")
    assert not r["ok"] and [i["ok"] for i in r["items"]] == [False, True, None, True]
    ax = r["items"][0]; assert "辅助功能" in ax["how"] and "Privacy & Security > Accessibility" in ax["how"] and "「Terminal.app」" in ax["how"]
    assert "录屏与系统录音" in r["items"][1]["how"] and "屏幕录制" in r["items"][1]["how"]
    assert hands.permissions("mac", mac=lambda: [None, None], app="")["ok"]                       # cannot tell is not a no
    monkeypatch.setattr(idle, "probe", lambda *a, **k: {"seconds": None, "source": "Wayland: x"})
    w = hands.permissions("linux", env={"WAYLAND_DISPLAY": "w"}); assert not w["ok"] and "X11" in w["items"][0]["how"]
    x = hands.permissions("linux", env={"DISPLAY": ":0"}, which=lambda n: None)
    assert [i["ok"] for i in x["items"]] == [False, False, False] and "xprintidle" in x["items"][-1]["how"]
    assert hands.permissions("windows")["items"][0]["ok"] is True


def test_mac_app_is_the_parent_app():
    ps = {str(os.getpid()): "4321 /Users/w/gameanything/.venv/bin/python", "4321": "4000 -zsh", "4000": "1 /System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal"}
    assert hands.mac_app(lambda a, timeout=20: _ok(ps.get(a[-1], ""))) == "Terminal.app"
    assert hands.mac_app(lambda a, timeout=20: _ok("")) == ""
    fw = "/opt/homebrew/Cellar/python@3.14/3.14.8/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python"
    ps = {str(os.getpid()): f"4321 {fw}", "4321": "4000 /bin/zsh", "4000": "3999 /Applications/Visual Studio Code.app/Contents/MacOS/Electron"}
    assert hands.mac_app(lambda a, timeout=20: _ok(ps.get(a[-1], ""))) == "Visual Studio Code.app"      # the interpreter's bundle is skipped
    ps = {str(os.getpid()): f"1 {fw}"}
    assert hands.mac_app(lambda a, timeout=20: _ok(ps.get(a[-1], ""))) == "Python.app"                 # started by launchd: python itself


def test_cli_permissions(monkeypatch, capsys):
    monkeypatch.setattr(hands, "permissions", lambda *a, **k: {"system": "mac", "ok": False, "items": [
        {"name": "辅助功能 Accessibility", "ok": False, "why": "w", "how": "系统设置 > 隐私与安全性 > 辅助功能"}]})
    opened = []; monkeypatch.setattr(hands, "open_panes", lambda: opened.append(1))
    assert cli.main(["native", "permissions", "--open"]) == 1 and opened == [1]
    assert "NO  辅助功能 Accessibility" in (o := capsys.readouterr().out) and "how: 系统设置" in o


# ---------------------------------------------------------------- X11 command lines, PNG
def test_x11_backend_commands():
    calls = []
    geo = "WINDOW=4194305\nX=10\nY=20\nWIDTH=1280\nHEIGHT=720\nSCREEN=0\n"

    def run(args, timeout=20):
        calls.append(args)
        if args[1] == "search": return _ok("4194305\n4194306\n")
        if args[1] == "getwindowgeometry": return _ok(geo if args[-1] == "4194305" else "WINDOW=4194306\nX=0\nY=0\nWIDTH=1\nHEIGHT=1\n")
        if args[1] == "getwindowname": return _ok("Stardew Valley\n")
        return _ok()
    be = hands.X11Backend(run=run, which=lambda n: "/usr/bin/" + n, env={"DISPLAY": ":0"})
    w = hands.pick(be.windows([4242]), [4242]); assert w == {"id": 4194305, "pid": 4242, "title": "Stardew Valley", "x": 10, "y": 20, "w": 1280, "h": 720}
    calls.clear()
    for st in hands.parse_steps(["key esc", "type hi there", "click 5 6 right"]): be.send(w, st)
    assert calls == [["xdotool", "key", "--window", "4194305", "Escape"], ["xdotool", "type", "--window", "4194305", "--", "hi there"],
                     ["xdotool", "mousemove", "--window", "4194305", "5", "6", "click", "--window", "4194305", "3"]]
    assert not any("windowactivate" in a or "windowfocus" in a for c in calls for a in c)         # never brought to the front


def test_x11_window_without_pid_found_by_title():
    """Slay the Spire on Linux (seen 2026-10-24): the LWJGL 2 game window carries no _NET_WM_PID, so by pid xdotool finds only
    ModTheSpire's launcher window, and shot / drive went to the launcher. The game's exact window title finds the game window, unless
    another process owns a window of that title."""
    geo = {"11": (235, 105, 810, 510), "22": (0, 0, 1280, 720), "33": (0, 0, 1920, 1080)}
    names = {"11": "ModTheSpire 3.30.3", "22": "Modded Slay the Spire", "33": "Slay the Spire"}
    owner = {"11": "4242", "33": "777"}                    # 22: no _NET_WM_PID (xdotool getwindowpid fails); 33: someone else's copy
    calls = []

    def run(args, timeout=20):
        calls.append(args)
        if args[1:3] == ["search", "--onlyvisible"] and args[3] == "--pid": return _ok("11\n")
        if args[1:4] == ["search", "--onlyvisible", "--name"]:
            return _ok({"^Modded Slay the Spire$": "22\n", "^Slay the Spire$": "33\n"}.get(args[4], ""))
        if args[1] == "getwindowpid":
            return _ok(owner[args[2]] + "\n") if args[2] in owner else SimpleNamespace(returncode=1, stdout="", stderr="no pid")
        if args[1] == "getwindowgeometry":
            x, y, w, h = geo[args[-1]]; return _ok(f"WINDOW={args[-1]}\nX={x}\nY={y}\nWIDTH={w}\nHEIGHT={h}\nSCREEN=0\n")
        if args[1] == "getwindowname": return _ok(names[args[-1]] + "\n")
        return _ok()
    be = hands.X11Backend(run=run, which=lambda n: "/usr/bin/" + n, env={"DISPLAY": ":0"})
    g = games.SlayTheSpire(sys_="linux")
    assert [w["id"] for w in be.windows([4242])] == [11]                                   # by pid only: the launcher
    w = hands._window(be, [4242], g.window_titles)
    assert (w["id"], w["pid"], w["title"], w["w"]) == (22, 4242, "Modded Slay the Spire", 1280)    # not 33: another process's window
    assert hands._window(be, [4242])["id"] == 11                                           # games without titles: unchanged
    assert hands._window(FakeBackend(), [5], g.window_titles)["id"] == 7                    # other backends are called as before


def test_x11_shot_commands(tmp_path):
    calls = []
    run = lambda args, timeout=20: calls.append(args) or _ok()
    w = {"id": 99, "pid": 1, "x": 10, "y": 20, "w": 640, "h": 480}
    hands.X11Backend(run=run, which=lambda n: "/usr/bin/" + n).shot(w, tmp_path / "a.png")
    assert calls[-1] == ["import", "-silent", "-window", "99", str(tmp_path / "a.png")]
    r = hands.X11Backend(run=run, which=lambda n: "/usr/bin/ffmpeg" if n == "ffmpeg" else None, env={"DISPLAY": ":1"}).shot(w, tmp_path / "b.png")
    assert calls[-1][calls[-1].index("-i") + 1] == ":1+10,20" and "640x480" in calls[-1] and "warning" in r
    with pytest.raises(games.NativeError): hands.X11Backend(run=run, which=lambda n: None).shot(w, tmp_path / "c.png")


def test_png_writer(tmp_path):
    bgra = bytes([0, 0, 255, 0, 0, 255, 0, 0, 255, 0, 0, 0, 255, 255, 255, 0])      # red, green, blue, white (2x2)
    rgb = hands.bgra_to_rgb(bgra); assert rgb == bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255])
    f = tmp_path / "x.png"; hands.write_png(f, 2, 2, rgb); b = f.read_bytes()
    assert b[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", b[16:24]) == (2, 2)
    i = b.index(b"IDAT"); n = struct.unpack(">I", b[i - 4:i])[0]
    assert zlib.decompress(b[i + 4:i + 4 + n]) == b"\x00" + rgb[:6] + b"\x00" + rgb[6:]


# ---------------------------------------------------------------- the game keeps running unfocused
def test_smoke_plugins_run_in_background():
    w = PKG / "worlds"
    for f in (w / "overcooked2/smoke/Plugin.cs", w / "cities_skylines/smoke/Source/Smoke.cs", w / "cities_skylines/template/Source/Mod.cs",
              w / "cities_skylines/citybuilder/Source/Host.cs"):
        assert "Application.runInBackground = true;" in f.read_text(encoding="utf-8"), f


def test_stardew_and_minecraft_keep_running_unfocused(tmp_path):
    home = tmp_path / "home"; sd = games.get("stardew", sys_="linux", home=home, env=_env(tmp_path)); sd.running = lambda: False
    sd.user_dir().mkdir(parents=True); f = sd.user_dir() / "startup_preferences"
    orig = '<?xml version="1.0"?><StartupPreferences><clientOptions><pauseWhenOutOfFocus>true</pauseWhenOutOfFocus></clientOptions></StartupPreferences>'
    f.write_text(orig, encoding="utf-8")
    w = quiet.small_window(sd); assert w["changed"] == ["pauseWhenOutOfFocus"] and w["how"] and "<pauseWhenOutOfFocus>false<" in f.read_text(encoding="utf-8")
    quiet.restore_window(sd); assert f.read_text(encoding="utf-8") == orig
    mc = games.get("minecraft", sys_="linux", home=home, env=_env(tmp_path))
    assert ("pauseOnLostFocus", r"(?m)^pauseOnLostFocus:([^\r\n]*)", "false") in quiet.window_plan(mc)[0][1]


def test_dialog_has_the_idle_choice():
    m = (PKG / "ui/static/manage.js").read_text(encoding="utf-8")
    assert 'opt("idle", "我没在用电脑时"' in m and 'id="lmin"' in m and 'id="ldrv"' in m and 'drive: $("#ldrv", d).checked ? "always" : "idle"' in m
    assert {"我没在用电脑时", "分钟", "我在用电脑时也可以操作游戏窗口"} <= quiet.TEXTS
