"""能不能操作屏幕 (native/ready.py, 2026-11-01) and 「测试时允许把游戏切到前面」 (hands.py, native_front: away): the caller's framework /
app / sandbox from its environment, the tiny capture probe (deleted at once, never a key), the level per system from fake permission
answers, the per-project record that is checked again after an agent / model change, her answer on the readiness card (「不给，我自己点」
-> native_hands: self, after which drive refuses), the menu summary, the CLI exit codes; on Windows drive brings ONLY the game m2w opened
to the front and ONLY while she is away. Fakes only: no screen, no window, no input."""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from gameanything import cli, projects, users
from gameanything.conversation import Thread
from gameanything.native import games, hands, idle, quiet, ready

PKG = Path(__file__).resolve().parent.parent / "gameanything"


@pytest.fixture
def proj():
    e = projects.create("能不能操作屏幕", "feature", game="stardew", build_mode="native"); return Path(e["path"])


def _pid(root): return projects.find(str(root))["id"]


def _ok(out="", rc=0, err=""): return SimpleNamespace(returncode=rc, stdout=out, stderr=err)


def _bmp(px: bytes, w=16, h=16, bpp=24) -> bytes:
    return (b"BM" + (54 + len(px)).to_bytes(4, "little") + b"\0" * 4 + (54).to_bytes(4, "little") + (40).to_bytes(4, "little")
            + w.to_bytes(4, "little") + h.to_bytes(4, "little") + (1).to_bytes(2, "little") + bpp.to_bytes(2, "little") + b"\0" * 24 + px)


VARIED = bytes(range(256)) * 3
FLAT = bytes([40, 40, 40]) * 256


def _perms(sys_, ax=True, scr=True, idle_ok=True):
    """A hands.permissions() answer without touching the system (the real one's shape, with needs)."""
    def f():
        if sys_ == "mac":
            items = [{"name": "辅助功能 Accessibility", "ok": ax, "why": "w", "how": "系统设置 > 隐私与安全性 > 辅助功能：打开 「Terminal.app」 的开关", "needs": "act"},
                     {"name": "屏幕录制 Screen Recording", "ok": scr, "why": "w", "how": "系统设置 > 隐私与安全性 > 录屏与系统录音：打开 「Terminal.app」 的开关", "needs": "look"},
                     {"name": "说明", "ok": None, "why": "w", "how": "", "needs": ""}]
        elif sys_ == "windows":
            items = [{"name": "发按键", "ok": True, "why": "", "how": "", "needs": "act"}, {"name": "截游戏窗口", "ok": True, "why": "", "how": "", "needs": "look"}]
        else: items = [{"name": "xdotool", "ok": True, "why": "", "how": "", "needs": "both"}]
        items.append({"name": "看她在不在用电脑", "ok": idle_ok, "why": "src", "how": "" if idle_ok else "看不出时：…", "needs": "idle"})
        return {"system": sys_, "items": items, "ok": True}
    return f


def _probe(ok=True, hint=False): return lambda: {"ok": ok, "why": "fake probe", **({"sandbox_hint": True} if hint else {})}


# ---------------------------------------------------------------- (a) who runs this
def test_caller_from_the_environment():
    c = ready.caller({"CODEX_SANDBOX": "seatbelt", "CODEX_SANDBOX_NETWORK_DISABLED": "1", "TERM_PROGRAM": "Apple_Terminal"})
    assert c["framework"] == "codex" and c["sandbox"] == "Codex (seatbelt)" and c["app"] == "Terminal" and "CODEX_SANDBOX=seatbelt" in c["signs"]
    c = ready.caller({"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "claude-vscode", "TERM_PROGRAM": "vscode"})
    assert c["framework"] == "claude-code" and c["app"] == "VS Code / Cursor" and not c["sandbox"]
    assert ready.caller({"CLAUDECODE": "1", "__CFBundleIdentifier": "com.anthropic.claudefordesktop"})["app"] == "Claude 桌面 app"
    # --lang en printed "app Claude 桌面 app" (a real Windows 11 PC, 2026-11-02): the record keeps the Chinese name, English text translates it
    assert ready.app_text("Claude 桌面 app", "en") == "Claude desktop app" and ready.app_text("Claude 桌面 app") == "Claude 桌面 app"
    assert ready.app_text("Windows Terminal", "en") == "Windows Terminal"
    assert ready.caller({"__CFBundleIdentifier": "com.todesktop.230313mzl4w4u92"})["app"] == ""          # (an unknown bundle: not guessed)
    assert ready.caller({"__CFBundleIdentifier": "com.cursor.app"})["app"] == "Cursor"
    c = ready.caller({"GAMEANYTHING_INSTANCE": "r1", "SSH_CONNECTION": "1 2 3 4"}); assert c["framework"] == "agentd" and c["agentd"] and c["ssh"]
    assert ready.caller({"WT_SESSION": "x"})["app"] == "Windows Terminal" and ready.caller({"OPENCODE": "1"})["framework"] == "opencode"
    assert ready.caller({"GEMINI_CLI": "1"})["framework"] == "gemini" and ready.caller({"DSH_HOME": "/x"})["framework"] == "dsh"
    assert ready.caller({"APP_SANDBOX_CONTAINER_ID": "x"})["sandbox"] == "macOS App Sandbox"
    assert ready.caller({}) == {"framework": "", "agentd": False, "app": "", "ssh": False, "sandbox": "", "signs": []}


# ---------------------------------------------------------------- the capture probe
def test_pixels_and_bmp():
    assert ready.varied(VARIED, 3) and not ready.varied(FLAT, 3) and not ready.varied(b"", 3)
    assert not ready.varied(bytes([1, 2, 3, 255, 1, 2, 3, 0]), 4)                   # alpha alone does not count
    assert ready.bmp_pixels(_bmp(VARIED)) == (VARIED, 3) and ready.bmp_pixels(b"PNG") is None
    assert ready.bmp_pixels(_bmp(VARIED, bpp=8)) is None


def test_mac_probe_reads_a_tiny_region_and_deletes_it(tmp_path):
    tmp_path = tmp_path / "t"; tmp_path.mkdir(); seen = []

    def run(px, err=""):
        def f(args, timeout=20):
            seen.append(args); out = Path(args[-1])
            if px is not None: out.write_bytes(_bmp(px))
            return _ok(rc=0 if px is not None else 1, err=err)
        return f
    r = ready.capture_probe("mac", run=run(VARIED), tmp=tmp_path)
    assert r["ok"] is True and seen[0][:4] == ["screencapture", "-x", "-R0,0,16,16", "-t"] and not list(tmp_path.iterdir())   # gone at once
    assert ready.capture_probe("mac", run=run(FLAT), tmp=tmp_path)["ok"] is None
    r = ready.capture_probe("mac", run=run(None, "screencapture: Operation not permitted"), tmp=tmp_path)
    assert r["ok"] is False and r["sandbox_hint"] and "Operation not permitted" in r["why"] and not list(tmp_path.iterdir())

    def junk(args, timeout=20): Path(args[-1]).write_bytes(b"not a bmp"); return _ok()
    assert ready.capture_probe("mac", run=junk, tmp=tmp_path)["ok"] is None


def test_linux_and_windows_probes(tmp_path):
    tmp_path = tmp_path / "t"; tmp_path.mkdir()
    def run(args, timeout=20):
        Path(args[-1].removeprefix("rgb:")).write_bytes(VARIED); return _ok()
    r = ready.capture_probe("linux", env={"DISPLAY": ":0"}, run=run, which=lambda n: "/usr/bin/" + n if n == "ffmpeg" else None, tmp=tmp_path)
    assert r["ok"] is True and "ffmpeg" in r["why"]
    r = ready.capture_probe("linux", env={"DISPLAY": ":0"}, run=run, which=lambda n: "/usr/bin/import" if n == "import" else None, tmp=tmp_path)
    assert r["ok"] is True and "import" in r["why"] and not list(tmp_path.iterdir())
    assert ready.capture_probe("linux", env={"DISPLAY": ":0"}, run=run, which=lambda n: None, tmp=tmp_path)["ok"] is False
    assert ready.capture_probe("linux", env={"WAYLAND_DISPLAY": "w"}, run=run, tmp=tmp_path)["ok"] is False
    assert ready.capture_probe("windows", grab=lambda: bytes(range(256)) * 16)["ok"] is True
    r = ready.capture_probe("windows", grab=lambda: bytes(32 * 32 * 4)); assert r["ok"] is False and "全黑" in r["why"]       # session 0 / locked
    assert ready.capture_probe("windows", grab=lambda: bytes([9, 9, 9, 255]) * 1024)["ok"] is None
    assert ready.capture_probe("windows", grab=lambda: None)["ok"] is False
    # the middle of a plain dark window is one colour (a real Windows 11 PC 2026-11-02): a line across the screen decides
    flat = lambda: bytes([30, 30, 30, 255]) * 1024
    r = ready.capture_probe("windows", grab=flat, strips=lambda: [None, bytes([30, 30, 30, 255]) * 8 + bytes([200, 90, 10, 255]) * 8])
    assert r["ok"] is True and "一条线" in r["why"] and "line across" in r["why_en"]
    assert ready.capture_probe("windows", grab=flat, strips=lambda: [bytes([30, 30, 30, 255]) * 16])["ok"] is None
    assert ready.capture_probe("windows", grab=lambda: bytes(32 * 32 * 4), strips=lambda: [bytes(range(256))])["ok"] is False   # black: no fallback

    def boom(): raise OSError("access denied")
    r = ready.capture_probe("windows", grab=boom); assert r["ok"] is False and r["sandbox_hint"]


def test_win_desktop_from_fake_win32_calls():
    class K:
        def __init__(self, s): self.s = s
        def GetCurrentProcessId(self): return 42
        def ProcessIdToSessionId(self, pid, ref): ref._obj.value = self.s; return True
        def WTSGetActiveConsoleSessionId(self): return 1

    class U:
        def __init__(self, h): self.h = h; self.closed = []
        def OpenInputDesktop(self, f, inh, acc): return self.h
        def CloseDesktop(self, h): self.closed.append(h)
    u = U(77); assert ready.win_desktop(u, K(1)) == {"session": 1, "console": 1, "input_desktop": True} and u.closed == [77]
    assert ready.win_desktop(U(0), K(0)) == {"session": 0, "console": 1, "input_desktop": False}


# ---------------------------------------------------------------- the level
def test_levels_on_a_mac():
    r = ready.check(None, sys_="mac", env={"TERM_PROGRAM": "Apple_Terminal"}, perms=_perms("mac"), probe=_probe(True), who="Terminal.app")
    assert r["level"] == "full" and r["look"] and r["act"] and r["fix"] == [] and r["app"] == "Terminal.app"
    r = ready.check(None, sys_="mac", env={}, perms=_perms("mac", ax=False), probe=_probe(True), who="Terminal.app")
    assert r["level"] == "look" and any("辅助功能" in f and "「Terminal.app」" in f for f in r["fix"])
    r = ready.check(None, sys_="mac", env={}, perms=_perms("mac", scr=False), probe=_probe(True), who="Terminal.app")
    assert r["level"] == "none" and any("录屏与系统录音" in f for f in r["fix"])
    assert ready.check(None, sys_="mac", env={}, perms=_perms("mac"), probe=_probe(False), who="")["level"] == "none"
    assert ready.check(None, sys_="mac", env={}, perms=_perms("mac", ax=None, scr=None), probe=_probe(None), who="")["level"] == "full"   # cannot tell is no no
    r = ready.check(None, sys_="mac", env={}, perms=_perms("mac", idle_ok=False), probe=_probe(True), who="")      # drive refuses without idle
    assert r["level"] == "look" and any("我在用电脑时也可以操作游戏窗口" in f for f in r["fix"])


def test_idle_does_not_count_when_she_allows_driving_always(proj):
    quiet.set_policy(_pid(proj), "ask", drive="always")
    assert ready.check(proj, sys_="mac", env={}, perms=_perms("mac", idle_ok=False), probe=_probe(True), who="")["level"] == "full"


def test_codex_sandbox_is_named_and_never_weakened():
    r = ready.check(None, sys_="mac", env={"CODEX_SANDBOX": "seatbelt"}, perms=_perms("mac"), probe=_probe(False, hint=True), who="")
    assert r["level"] == "none" and r["caller"]["sandbox"].startswith("Codex")
    sb = next(i for i in r["items"] if i["name"] == "agent 的沙箱"); assert "不要为这个关掉或放宽" in sb["how"] and "未实测" in sb["why"]
    shot = next(i for i in r["items"] if i["name"].startswith("试截")); assert "不要为这个关掉或放宽沙箱" in shot["how"]
    r = ready.check(None, sys_="mac", env={"CODEX_SANDBOX": "seatbelt"}, perms=_perms("mac"), probe=_probe(True), who="")
    assert r["level"] == "full" and any(i["name"] == "agent 的沙箱" for i in r["items"])          # works in the sandbox: said, not blocked


def test_mac_menu_bar_probe_proves_nothing_without_screen_recording():
    """Real Mac, 2026-11-01: Terminal without 「屏幕录制」 still captured the menu bar corner: the probe is no evidence then."""
    r = ready.check(None, sys_="mac", env={}, perms=_perms("mac", scr=False), probe=_probe(True), who="Terminal.app")
    shot = next(i for i in r["items"] if i["name"].startswith("试截"))
    assert shot["ok"] is None and "说明不了" in shot["why"] and r["level"] == "none"


def test_mac_permissions_inside_codex_point_away_from_system_settings():
    """Real Mac, 2026-11-01: inside Codex both checks said no although the app above it had both: no System Settings steps then."""
    r = ready.check(None, sys_="mac", env={"CODEX_SANDBOX": "seatbelt"}, perms=_perms("mac", ax=False, scr=False), probe=_probe(False, hint=True), who="")
    assert r["level"] == "none" and r["fix"] and all("系统设置" not in f and "不要为这个关掉或放宽沙箱" in f for f in r["fix"])


def test_levels_on_windows():
    good = lambda: {"session": 1, "console": 1, "input_desktop": True}
    r = ready.check(None, sys_="windows", env={}, perms=_perms("windows"), probe=_probe(True), desktop=good, package=lambda: None)
    assert r["level"] == "full" and {i["name"] for i in r["items"]} >= {"她的桌面会话（看、按都要）", "打包的 app（MSIX）", "游戏不是管理员身份"}
    r = ready.check(None, sys_="windows", env={"SSH_CONNECTION": "x"}, perms=_perms("windows"), probe=_probe(False),
                    desktop=lambda: {"session": 0, "console": 1, "input_desktop": False}, package=lambda: None)
    assert r["level"] == "none" and any("SSH" in i["why"] for i in r["items"]) and any("Windows Terminal" in f for f in r["fix"])
    r = ready.check(None, sys_="windows", env={}, perms=_perms("windows"), probe=_probe(True), desktop=good, package=lambda: "Claude_pzs8sxrjxfjjc")
    pkg = next(i for i in r["items"] if i["name"].startswith("打包的 app"))
    assert r["level"] == "full" and pkg["ok"] is False and "Claude_pzs8sxrjxfjjc" in pkg["why"] and "Claude 桌面 app" in pkg["how"]     # a warning, not a block

    def broken(): raise OSError("no user32")
    assert ready.check(None, sys_="windows", env={}, perms=_perms("windows"), probe=_probe(True), desktop=broken, package=lambda: None)["level"] == "full"

    # the open game's own token (a real Windows 11 PC 2026-11-02, Valheim from Steam: a normal user); it was always "cannot tell"
    def admin_item(**kw):
        r = ready.check(None, sys_="windows", env={}, perms=_perms("windows"), probe=_probe(True), desktop=good, package=lambda: None, **kw)
        return r, next(i for i in r["items"] if i["name"] == "游戏不是管理员身份")
    r, i = admin_item(game_pids=lambda: [42], elevated=lambda p: False); assert i["ok"] is True and r["level"] == "full"
    r, i = admin_item(game_pids=lambda: [42], elevated=lambda p: True)
    assert i["ok"] is False and r["level"] == "look" and "UIPI" in i["why"] and "Run as administrator" in i["en"]["how"]
    assert admin_item(game_pids=lambda: [42], elevated=lambda p: None)[1]["ok"] is None          # its token cannot be read
    assert admin_item(game_pids=lambda: [], elevated=lambda p: True)[1]["ok"] is None            # the game is not open
    assert admin_item()[1]["ok"] is None                                                           # no project: no game to look at


def test_levels_on_linux(monkeypatch):
    monkeypatch.setattr(idle, "probe", lambda *a, **k: {"seconds": None, "source": "Wayland: x"})
    r = ready.check(None, sys_="linux", env={"WAYLAND_DISPLAY": "w"}, probe=_probe(False))           # the real permissions(): Wayland
    assert r["level"] == "none" and any("X11" in f for f in r["fix"])
    monkeypatch.setattr(idle, "probe", lambda *a, **k: {"seconds": 3.0, "source": "xprintidle"})
    monkeypatch.setattr(hands.shutil, "which", lambda n: "/usr/bin/" + n)
    assert ready.check(None, sys_="linux", env={"DISPLAY": ":0"}, probe=_probe(True))["level"] == "full"


def test_mac_permissions_name_python_without_a_terminal(monkeypatch):
    monkeypatch.setattr(idle, "probe", lambda *a, **k: {"seconds": 5.0, "source": "ioreg"})
    r = hands.permissions("mac", mac=lambda: [False, False], app="")
    assert "python" in r["items"][0]["how"] and os.path.realpath(__import__("sys").executable) in r["items"][0]["how"]
    assert [i["needs"] for i in r["items"]] == ["act", "look", "", "idle"]


# ---------------------------------------------------------------- the record, the card, her answer
KW = dict(sys_="mac", env={}, perms=_perms("mac", ax=False), probe=_probe(True), who="Terminal.app")


def test_record_is_per_agent_and_model(proj):
    r = ready.run(proj, "chat", **KW)
    assert r["level"] == "look" and not r["cached"] and r["next"] == "card" and r["for"]["agent"] == "claude-code"
    rec = ready.records(proj)["chat"]; assert rec["level"] == "look" and rec["for"] == r["for"] and "at" in rec
    st = ready.state(proj, "chat", "mac"); assert st["fresh"]
    r2 = ready.run(proj, "chat", if_needed=True, sys_="mac", perms=lambda: pytest.fail("a fresh record is not checked again"))
    assert r2["cached"] and r2["level"] == "look"
    users._write_cfg_key(proj, "chat_model", {"agent": "codex", "model": "gpt-6.1-sol"})          # she switched the chat agent
    st = ready.state(proj, "chat", "mac"); assert not st["fresh"] and "换了 agent" in st["why"]
    r3 = ready.run(proj, "chat", if_needed=True, **{**KW, "perms": _perms("mac")}); assert not r3["cached"] and r3["level"] == "full" and r3["for"]["agent"] == "codex"
    assert not ready.state(proj, "chat", "windows")["fresh"]                                       # another system
    assert ready.state(proj, "build", "mac")["rec"] is None and ready.default_role({"GAMEANYTHING_ROLE": "builder"}) == "build"


def test_card_flow_and_her_answers(proj, tmp_path):
    f = tmp_path / "card.yaml"
    r = ready.run(proj, "chat", card_file=f, game_title="星露谷物语", **KW)
    assert r["next"] == "card" and r["card"] == "none" and f.is_file()
    import yaml
    body = yaml.safe_load(f.read_text(encoding="utf-8"))
    assert body["key"] == ready.CARD_KEY and [i["key"] for i in body["items"]] == ["again", "self"]
    assert [i["title"] for i in body["items"]] == ["我打开了，再查一次", "不给，我自己点"] and "辅助功能" in body["items"][0]["desc"] and "「Terminal.app」" in body["items"][0]["desc"]
    assert "星露谷物语" in body["items"][0]["desc"] and body["en"]["items"][1]["title"] == "No, I'll click myself"
    assert body.pop("project") == _pid(proj)                                                     # stamped: never posted in another project's chat
    T = Thread(proj); ev = T.card(body, session="resident")                                        # what `gameanything chat card --file` posts
    assert ready.run(proj, "chat", **KW)["next"] == "wait"                                       # out and unanswered: never a second card
    T.answer(ev["id"], {"picked": ["again"]}, source="ui")
    r = ready.run(proj, "chat", **KW); assert r["card"] == "again" and r["next"] == "card"         # still not allowed: ONE new card (same key)
    ev2 = T.card(ready.card_body(r), session="resident"); assert len([c for c in T.cards().values() if c["card"]["key"] == ready.CARD_KEY]) == 1
    T.answer(ev2["id"], {"picked": ["self"]}, source="terminal")                                   # typed by an agent: not her click
    assert quiet.policy(proj)["hands"] == "agent"
    T.answer(ev2["id"], {"picked": ["self"]}, source="ui")
    r = ready.run(proj, "chat", **KW); assert r["next"] == "self" and quiet.policy(proj)["hands"] == "self" and "可以用 shot" in r["why"]
    assert not quiet.policy(proj)["chosen"]                                                     # her launch choice is untouched
    quiet.set_policy(_pid(proj), None, hands="agent")                                            # she changed it back in the menu: the old click is not re-applied
    assert ready.run(proj, "chat", **KW)["hands"] == "agent"
    r = ready.run(proj, "chat", **{**KW, "perms": _perms("mac")}); assert r["next"] == "ok"


def test_card_file_posts_through_chat_card(proj, tmp_path, capsys):
    f = tmp_path / "ready.yaml"; ready.run(proj, "chat", card_file=f, **KW)
    assert cli.main(["chat", "card", "--project", str(proj), "--file", str(f), "--session", "resident", "--text", "想让 agent 自己测"]) == 0
    c = next(v for v in Thread(proj).cards().values() if v["card"]["key"] == ready.CARD_KEY)
    assert c["card"]["title"] == "让 agent 能看、能点你的游戏窗口吗？" and "project" not in c["card"] and ready.run(proj, "chat", **KW)["next"] == "wait"


def test_self_without_look_asks_her_for_a_picture(proj):
    quiet.set_policy(_pid(proj), None, hands="self")
    r = ready.run(proj, "chat", **{**KW, "probe": _probe(False)}); assert r["level"] == "none" and r["next"] == "self" and "截图" in r["why"]


def test_drive_refuses_when_she_clicks_herself(proj, tmp_path):
    g = games.get("stardew", sys_="linux", home=tmp_path / "home", env={"GAMEANYTHING_DATA": str(tmp_path / "m2w")})
    quiet.set_policy(_pid(proj), None, hands="self")
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["key escape"], be=object(), idle=lambda: 999.0)
    assert e.value.code == "self" and not e.value.pending and "自己点" in e.value.why


def test_summary_for_the_menu(proj, monkeypatch):
    monkeypatch.setattr(ready.osdirs, "system", lambda: "mac")
    s = ready.summary(proj); assert s == {"hands": "agent", "front": "never", "chat": None, "build": None}
    ready.run(proj, "chat", **KW); s = ready.summary(proj)
    assert s["chat"]["level"] == "look" and s["chat"]["fresh"] and s["chat"]["who"].startswith("Claude Code") and s["chat"]["fix"]


def test_cli_ready_exit_codes(proj, monkeypatch, capsys, tmp_path):
    real = ready.check
    monkeypatch.setattr(ready, "check", lambda root, role, **k: real(root, role, **{**KW, **k}))
    f = tmp_path / "c.yaml"
    assert cli.main(["native", "ready", "--project", _pid(proj), "--card-file", str(f), "--lang", "zh"]) == 1
    o = capsys.readouterr().out; assert "只能看，不能点 (look)" in o and "next: card" in o and "gameanything chat card" in o and f.is_file()
    assert cli.main(["native", "ready", "--project", _pid(proj), "--if-needed", "--json"]) == 1 and '"cached": true' in capsys.readouterr().out
    monkeypatch.setattr(ready, "check", lambda root, role, **k: real(root, role, **{**KW, "probe": _probe(False), **k}))
    assert cli.main(["native", "ready"]) == 3 and "can neither look nor click (none)" in capsys.readouterr().out
    monkeypatch.setattr(ready, "check", lambda root, role, **k: real(root, role, **{**KW, "perms": _perms("mac"), **k}))
    assert cli.main(["native", "ready", "--project", _pid(proj)]) == 0 and "next: ok" in capsys.readouterr().out


def test_cli_set_launch_front_and_hands(proj, capsys):
    pid = _pid(proj)
    assert cli.main(["project", "set-launch", pid, "--front", "away", "--hands", "self"]) == 0
    o = capsys.readouterr().out; assert "native_launch=ask (default)" in o and "front=away  hands=self" in o
    cfg = projects.config_of(proj); assert cfg["native_front"] == "away" and cfg["native_hands"] == "self" and "native_launch" not in cfg
    for bad in (dict(front="always"), dict(hands="robot")):
        with pytest.raises(ValueError): quiet.set_policy(pid, "ask", **bad)


def test_launch_says_to_check_first(proj, tmp_path, monkeypatch, capsys):
    quiet.set_policy(_pid(proj), "ask")
    assert cli.main(["native", "launch", "--project", _pid(proj), "--dry-run"]) in (2, 3)
    assert "gameanything native ready --project" in capsys.readouterr().err


# ---------------------------------------------------------------- Windows: bring the game to the front only while she is away
class WinFake:
    """A Windows-like backend: keys reach only the foreground window (can_send), bring_front makes the game the foreground one."""
    name = "fake Windows"; needs_front = True

    def __init__(self, fg_is_game=False, front_works=True, minimized=False):
        self.sent = []; self.fg = fg_is_game; self.works = front_works; self.min = minimized; self.fronted = []

    def windows(self, pids): return [{"id": 7, "pid": pids[0], "title": "Stardew Valley", "x": 0, "y": 0, "w": 1280, "h": 720, "minimized": self.min}]
    def can_send(self, win, pids): return None if self.fg else "not in front"

    def bring_front(self, win):
        self.fronted.append(win["id"]); self.min = False
        if self.works: self.fg = True
        return {"ok": self.works, "prev": {"id": 99, "pid": 1, "title": "她的浏览器"}}

    def send(self, win, step): self.sent.append(step)


def _opened(proj, tmp_path):
    from test_native_hands import _game, _open_game
    g, proc = _game(tmp_path); _open_game(proj, g, proc); return g


def test_front_only_with_her_setting_and_only_while_she_is_away(proj, tmp_path):
    g = _opened(proj, tmp_path); pid = _pid(proj)
    be = WinFake()
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["key a"], be=be, idle=lambda: 300.0, sleep=lambda s: None)
    assert e.value.code == "not_foreground" and be.fronted == []                                 # setting off: as before
    quiet.set_policy(pid, None, front="away")
    r = hands.drive(proj, g, ["key a", "key b"], be=be, idle=lambda: 300.0, sleep=lambda s: None)
    assert r["done"] == 2 and be.fronted == [7] and r["fronted"]["prev"] == "她的浏览器" and r["fronted"]["ok"]
    rec = quiet.ledger(proj)["launches"][-1]["fronted"]; assert len(rec) == 1 and rec[0]["window"] == "Stardew Valley"


def test_front_never_while_she_is_there_or_unknown(proj, tmp_path):
    g = _opened(proj, tmp_path); pid = _pid(proj); quiet.set_policy(pid, None, front="away")
    be = WinFake()
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["key a"], be=be, idle=lambda: 5.0)
    assert e.value.code == "active" and be.fronted == []                                         # she is there: refused before anything
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["key a"], be=be, idle=lambda: None)
    assert e.value.code == "unknown" and be.fronted == []
    quiet.set_policy(pid, None, drive="always")                                                  # "while I use it too" is not "take my foreground"
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["key a"], be=be, idle=lambda: 5.0)
    assert e.value.code == "not_foreground" and "她 5 秒前还在用" in e.value.why and be.fronted == []
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["key a"], be=be, idle=lambda: None)
    assert e.value.code == "not_foreground" and be.fronted == [] and be.sent == []
    assert hands.drive(proj, g, ["key a"], be=be, idle=lambda: 300.0, sleep=lambda s: None)["fronted"]   # away: allowed


def test_front_restores_a_minimized_game_and_reports_failure(proj, tmp_path):
    g = _opened(proj, tmp_path); quiet.set_policy(_pid(proj), None, front="away")
    be = WinFake(minimized=True)
    r = hands.drive(proj, g, ["key a"], be=be, idle=lambda: 300.0, sleep=lambda s: None)
    assert r["done"] == 1 and be.fronted == [7] and be.sent == [("key", "a")]
    be = WinFake(front_works=False)
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["key a"], be=be, idle=lambda: 300.0, sleep=lambda s: None)
    assert e.value.code == "not_foreground" and "Windows 没让切过去" in e.value.why and be.sent == []
    assert not quiet.ledger(proj)["launches"][-1]["fronted"][-1]["ok"]
    be = WinFake(minimized=True)
    quiet.set_policy(_pid(proj), None, front="never")
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["key a"], be=be, idle=lambda: 300.0)
    assert e.value.code == "no_window" and be.fronted == []


def test_front_then_she_comes_back(proj, tmp_path):
    from test_native_hands import Clock
    g = _opened(proj, tmp_path); quiet.set_policy(_pid(proj), None, front="away"); be = WinFake(); clk = Clock()
    vals = iter([400.0, 400.5, 0.05])

    def her_idle():
        v = next(vals)
        if v < 1: clk.t += 5
        return v
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["key a", "key b"], be=be, idle=her_idle, clock=clk, sleep=lambda s: None)
    assert e.value.code == "active" and be.sent == [("key", "a")] and be.fronted == [7]


def test_macos_and_linux_never_use_the_windows_front(proj, tmp_path):
    from test_native_hands import FakeBackend
    g = _opened(proj, tmp_path); quiet.set_policy(_pid(proj), None, front="away")
    be = FakeBackend(fg=False); be.bring_front = lambda w: pytest.fail("no needs_front: unchanged behaviour")
    with pytest.raises(hands.Refused) as e: hands.drive(proj, g, ["key a"], be=be, idle=lambda: 300.0)
    assert e.value.code == "not_foreground"


def test_win_backend_bring_front_with_fake_user32():
    calls = []

    class U:
        def __init__(self): self.fg = 99
        def GetForegroundWindow(self): return self.fg
        def GetWindowTextW(self, h, buf, n): buf.value = {99: "她的浏览器", 7: "Stardew Valley"}[h]; return 1
        def GetWindowThreadProcessId(self, h, ref):
            if ref is not None: ref._obj.value = {99: 1, 7: 4242}[h]
            return {99: 555, 7: 777}[h]
        def IsIconic(self, h): return True
        def ShowWindow(self, h, n): calls.append(("show", h, n)); return True
        def AttachThreadInput(self, a, b, on): calls.append(("attach", a, b, on)); return True
        def AllowSetForegroundWindow(self, pid): return True
        def BringWindowToTop(self, h): return True
        def SetForegroundWindow(self, h): calls.append(("fg", h)); self.fg = h; return True
    be = object.__new__(hands.WinBackend); be.u = U(); be.k = SimpleNamespace(GetCurrentThreadId=lambda: 111)
    r = be.bring_front({"id": 7, "pid": 4242})
    assert r["ok"] and r["prev"]["title"] == "她的浏览器"
    assert calls == [("show", 7, 9), ("attach", 111, 555, True), ("fg", 7), ("attach", 111, 555, False)]
    assert be.can_send({"id": 7}, [4242]) is None


def test_dialog_has_front_and_hands():
    m = (PKG / "ui/static/manage.js").read_text(encoding="utf-8")
    assert 'id="lfrt"' in m and 'front: $("#lfrt", d).checked ? "away" : "never"' in m and 'hopt("self", "我自己点"' in m and "readyHtml()" in m
    assert {"测试时允许把游戏切到前面", "谁来点游戏", "我自己点", "能看、能点", "{who}，{t} 查的"} <= quiet.TEXTS


# ---------------------------------------------------------------- English (2026-11-01: "外国用户怎么办")
REAL_PERMISSIONS = hands.permissions
CJK = __import__("re").compile(r"[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]")


def _en_texts(r):
    """Everything an English-speaking user reads from a check: the items, the fix lines, the card's English, the next step."""
    out = [hands.text(i, k, "en") for i in r["items"] for k in ("name", "why", "how")] + r["fix_en"]
    if "why_en" in r: out.append(r["why_en"])
    if r["level"] != "full":
        en = ready.card_body(r)["en"]; out += [en["title"]] + [x[k] for x in en["items"] for k in ("title", "desc")]
    return out


@pytest.mark.parametrize("case", ["mac", "mac-codex", "mac-python", "windows-ssh-msix", "linux-wayland", "linux-x11-bare"])
def test_every_text_a_user_reads_has_english(case, monkeypatch):
    sys_ = case.split("-")[0]
    monkeypatch.setattr(idle, "probe", lambda *a, **k: {"seconds": None, "source": "ioreg HIDIdleTime"})
    monkeypatch.setattr(hands, "mac_permissions", lambda: (False, False))
    monkeypatch.setattr(hands, "mac_app", lambda: "" if case == "mac-python" else "Terminal.app")
    monkeypatch.setattr(hands.shutil, "which", lambda n: None)
    env = {"mac": {"TERM_PROGRAM": "Apple_Terminal"}, "mac-codex": {"CODEX_SANDBOX": "seatbelt"}, "mac-python": {},
           "windows-ssh-msix": {"SSH_CONNECTION": "x"}, "linux-wayland": {"WAYLAND_DISPLAY": "w"}, "linux-x11-bare": {"DISPLAY": ":0"}}[case]
    kw = dict(desktop=lambda: {"session": 0, "console": 1, "input_desktop": False}, package=lambda: "Claude_pzs8sxrjxfjjc") if sys_ == "windows" else {}
    pr = {"ok": True, "why": "x", "why_en": "got a small picture"} if case == "mac" else \
        {"ok": False, "why": "x", "why_en": "no picture came back", "sandbox_hint": case == "mac-codex"}
    r = ready.check(None, sys_=sys_, env=env, probe=lambda: pr, **kw)            # the real hands.permissions() for that system
    assert r["level"] != "full" and all((i.get("en") or {}).get("name") for i in r["items"])
    bad = [t for t in _en_texts(r) if CJK.search(t)]
    assert not bad, bad


def test_real_probe_texts_have_english(tmp_path):
    r = ready.capture_probe("mac", run=lambda *a, **k: _ok(err="could not create image from display"), tmp=tmp_path)
    assert r["ok"] is False and r["why_en"].startswith("16x16 at the menu bar") and not CJK.search(r["why_en"])
    assert not CJK.search(ready.capture_probe("linux", env={"WAYLAND_DISPLAY": "w"}, tmp=tmp_path)["why_en"])


def test_cli_prints_english_by_default_and_the_projects_language(proj, monkeypatch, capsys):
    real = ready.check; monkeypatch.setattr(idle, "probe", lambda *a, **k: {"seconds": 1.0, "source": "ioreg HIDIdleTime"})
    perms = lambda: REAL_PERMISSIONS("mac", {}, mac=lambda: (False, True), app="Terminal.app")
    monkeypatch.setattr(ready, "check", lambda root, role, **k: real(root, role, **{**KW, "perms": perms, **k}))
    assert cli.main(["native", "ready", "--project", _pid(proj)]) == 1          # projects are en unless made in Chinese
    o = capsys.readouterr().out; assert "can look, cannot click (look)" in o and "next: card - Can look, cannot click: post one card" in o
    assert "System Settings > Privacy & Security > Accessibility" in o and not CJK.search(o)
    zh = Path(projects.create("中文项目", "feature", game="stardew", build_mode="native", lang="zh")["path"])
    assert cli.main(["native", "ready", "--project", _pid(zh)]) == 1 and "只能看，不能点 (look)" in capsys.readouterr().out


def test_cli_permissions_in_english(monkeypatch, capsys):
    monkeypatch.setattr(hands, "permissions", lambda *a, **k: REAL_PERMISSIONS("mac", {}, mac=lambda: (False, True), app="Terminal.app"))
    monkeypatch.setattr(idle, "probe", lambda *a, **k: {"seconds": 1.0, "source": "ioreg HIDIdleTime"})
    cli.main(["native", "permissions"]); o = capsys.readouterr().out
    assert "System Settings > Privacy & Security > Accessibility: turn on \"Terminal.app\"" in o and not CJK.search(o)
    cli.main(["native", "permissions", "--lang", "zh"]); assert "系统设置 > 隐私与安全性 > 辅助功能" in capsys.readouterr().out


def test_menu_summary_has_english_fix(proj, monkeypatch):
    monkeypatch.setattr(ready.osdirs, "system", lambda: "mac")
    ready.run(proj, "chat", **{**KW, "perms": lambda: REAL_PERMISSIONS("mac", {}, mac=lambda: (False, True), app="Terminal.app")})
    s = ready.summary(proj)["chat"]; assert s["fix"] and s["fix_en"] and s["fix_en"][0].startswith("Accessibility") and not CJK.search(" ".join(s["fix_en"]))
