"""QA2 2026-10-30: what the page says while an agent CLI is backed off or crashing, the notices' wording, the log's run count."""
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from gameanything import activity, agentd
from test_agentd import Clock, Spawner, daemon, new_project, statuses
from test_agentd_failures import fail_with

STATIC = Path(agentd.__file__).parent / "ui" / "static"


@pytest.fixture
def spawner():
    s = Spawner(); yield s; s.stop_all()


def test_retry_time_is_friendly():
    """「大约 10-30 00:12」 read like a date code: tomorrow says 明天 / tomorrow, another day says the month and day in words."""
    now = datetime.now().replace(second=0, microsecond=0)
    tom = (now + timedelta(days=1)).replace(hour=0, minute=12)
    assert activity.hhmm(tom.timestamp()) == "明天 00:12"
    assert activity.hhmm(tom.timestamp(), "en") == "tomorrow 00:12"
    later = (now + timedelta(days=5)).replace(hour=9, minute=5)
    assert activity.hhmm(later.timestamp()) == f"{later.month}月{later.day}日 09:05"
    assert activity.hhmm(later.timestamp(), "en") == later.strftime("%b ") + str(later.day) + " 09:05"
    assert activity.hhmm(now.timestamp()) == now.strftime("%H:%M")


def test_backoff_is_its_own_phase_and_stays(spawner):
    """Login back-off: the line under her words says the agent is paused and when it tries again, the same on every poll (no flipping
    between 「正在叫」 / 「等 agent 读取」 / 「没能回复」)."""
    _, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"}); T.user_text("你好")
    clk = Clock(); D = daemon(spawner, clk); D.tick()
    fail_with(T, spawner, '{"type":"result","is_error":true,"result":"Not logged in"}'); D.tick()
    seen = set()
    for w in ("在吗", "还在吗"):
        T.user_text(w); D.tick()
        for _ in range(3): seen.add(T.online()["phase"]); D.tick()
    assert seen == {"paused"}
    b = T.online()["backoff"]
    assert b["kind"] == "auth" and b["until_at"] and "登录" in b["text"]


def test_crash_retry_says_got_it_at_once():
    """85 s without a word while a crashing CLI was retried (the 「收到」 line is posted at most every 10 min): a retry says so at once."""
    _, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"}); T.user_text("你好")

    class Crash(Spawner):
        def __call__(self, cmd, cwd, env, log):
            p = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(3)"], stdout=log, stderr=log)
            self.calls.append({"cmd": cmd}); self.procs.append(p); return p
    sp = Crash(); clk = Clock(); D = daemon(sp, clk)
    (T.dir / ".agent_calling_line").write_text(agentd.now(), encoding="utf-8")     # a 「收到」 line was posted a minute ago (an earlier message)
    D.tick(); sp.procs[-1].wait(10); D.tick()
    st = statuses(T)
    assert any(s.startswith("收到") and "再叫" in s for s in st), st
    assert T.online()["phase"] == "calling"


def test_give_up_logs_the_real_run_count(spawner, tmp_path):
    _, T = new_project()
    D = daemon(spawner); logs = []
    D.log = logs.append
    r = {"key": "e_x", "agent_provider": "opencode", "log": None}
    D._give_up({"id": "p"}, T, r, {"key": "e_x", "n": 1}, "loop", ("a", "b"))
    assert any("after 1 run(s) (loop)" in x for x in logs), logs


def test_pill_honours_backoff_and_failure():
    js = (STATIC / "shell.js").read_text(encoding="utf-8")
    pill = js[js.index("function renderPills"):js.index("const tip =")]
    assert "AGENT.backoff" in pill and "AGENT.failed" in pill, "the green 「agent 随叫随到」 is not shown while backed off or after giving up"
    assert '"paused"' in js[js.index("const LINE ="):js.index("const LINE =") + 1200]


def test_login_notice_fits_the_mode():
    """Single-user mode has no 「我的 agent」 page: the notice says what to do there."""
    from gameanything import agentd as A
    for prov in ("opencode", "gemini"):
        zh_hub, en_hub = A.auth_notice(prov, hub=True); zh, en = A.auth_notice(prov, hub=False)
        assert "我的 agent" in zh_hub and "My agent" in en_hub
        assert "我的 agent" not in zh and "My agent" not in en and "启动 GameAnything 的环境" in zh and "environment" in en


def test_waiting_line_is_short_and_whole(spawner):
    """「这句话先记下了。」 + the whole notice + 「，大约 07:00 恢复，大约 07:00 后台会自动再试一次」 ran on: one short line now."""
    _, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"}); T.user_text("你好")
    clk = Clock(); D = daemon(spawner, clk); D.tick()
    fail_with(T, spawner, '{"type":"result","is_error":true,"result":"Not logged in"}'); D.tick()
    T.user_text("在吗"); D.tick()
    w = [s for s in statuses(T) if s.startswith("这句话先记下了")]
    assert len(w) == 1 and len(w[0]) < 60 and w[0].count("大约") == 1 and w[0].endswith("。"), w


def test_402_is_not_logged_as_not_logged_in(spawner):
    _, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"}); T.user_text("你好")
    clk = Clock(); D = agentd.Agentd(provider="opencode", agent="/bin/false", spawn=spawner, quiet=True, clock=clk); logs = []
    D.log = logs.append; D.tick()
    fail_with(T, spawner, '{"type":"error","error":{"name":"APIError","data":{"message":"Insufficient balance","statusCode":402}}}'); D.tick()
    assert any("out of credit (402)" in x for x in logs) and not any("not logged in" in x for x in logs), logs


def test_resident_prompt_says_where_the_sandbox_runs():
    """QA2 2026-10-30: both agents called a server-sandbox project 「在你电脑的沙箱里」; the prompt only said `lab`."""
    import yaml
    from gameanything import projects
    e, T = new_project(); root = T.root
    f = root / "config" / "project.yaml"; c = yaml.safe_load(f.read_text(encoding="utf-8"))
    c.update(build_mode="lab", setup={"mode": "sandbox", "where": "server"}); f.write_text(yaml.safe_dump(c, allow_unicode=True), encoding="utf-8")
    t = agentd._where_text(root)
    assert "服务器" in t and "not on her computer" in t
    c.update(setup={"mode": "sandbox", "where": "this_computer"}); f.write_text(yaml.safe_dump(c, allow_unicode=True), encoding="utf-8")
    assert "her own computer" in agentd._where_text(root)
    c.update(build_mode="native"); f.write_text(yaml.safe_dump(c, allow_unicode=True), encoding="utf-8")
    assert "her own copy of the game" in agentd._where_text(root)


def test_skill_tells_agents_how_to_write_to_her():
    """QA2 2026-10-30: half-width punctuation in Chinese replies; plan items said 「她要求加的」 to her; card files left in her folder."""
    from gameanything import shipped
    for f in ("core.md", "references/resident-prompt.md"):
        t = (shipped.SKILL / f).read_text(encoding="utf-8")
        assert "full-width punctuation" in t and "你要求加的" in t, f
    core = (shipped.SKILL / "core.md").read_text(encoding="utf-8")
    assert '`F=$(mktemp)`' in core and "$TMPDIR/x.yaml" not in core, "a new file per card (hotfix 2026-10-30)"


def test_go_card_launch_notes_match_where_the_sandbox_runs():
    """A server-sandbox project: a go card whose launch_notes say the sandbox is on her computer is refused (it was posted, QA2 2026-10-30)."""
    import yaml
    from gameanything import cli
    e, T = new_project(); root = T.root
    f = root / "config" / "project.yaml"; c = yaml.safe_load(f.read_text(encoding="utf-8"))
    c.update(build_mode="lab", setup={"mode": "sandbox", "where": "server"}); f.write_text(yaml.safe_dump(c, allow_unicode=True), encoding="utf-8")
    card = {"kind": "go", "key": "go", "title": "开工", "milestone": "m1", "items": ["做第一版"],
            "launch_notes": ["游戏将在你的电脑本地沙盒（Docker Engine）中运行"],
            "en": {"launch_notes": ["The game runs in a local Docker sandbox on your computer"]}}
    cf = root.parent / "go.yaml"; cf.write_text(yaml.safe_dump(card, allow_unicode=True), encoding="utf-8")
    with pytest.raises(SystemExit) as x: cli.main(["chat", "card", "--project", str(root), "--file", str(cf)])
    assert "服务器" in str(x.value)
    card["launch_notes"] = ["游戏在服务器上的沙箱里运行，不动你电脑上的游戏"]; card["en"]["launch_notes"] = ["The game runs in a sandbox on the server"]
    cf.write_text(yaml.safe_dump(card, allow_unicode=True), encoding="utf-8")
    assert cli.main(["chat", "card", "--project", str(root), "--file", str(cf)]) == 0
