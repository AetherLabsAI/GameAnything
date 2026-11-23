"""Auto builds (builds.py, `gameanything agentd run --builds auto`): a build_start request starts ONE builder per project without a coordinator, the
builder reports through notes, the resident gets the result-card prompt; no seat -> queued + one note; a restart -> interrupted note; Codex
parity (sandbox dirs, network, no paid keys). No real agent and no real lab: the spawner starts a sleeping Python process, the lab is a fake."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from gameanything import agent_providers, agentd, builds, cli, keys, projects
from gameanything.conversation import Thread


class Spawner:
    def __init__(self): self.calls = []; self.procs = []

    def __call__(self, cmd, cwd, env, log):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        self.calls.append({"cmd": cmd, "cwd": Path(cwd), "env": env, "pid": p.pid}); self.procs.append(p); return p

    def builders(self): return [c for c in self.calls if c["env"].get("GAMEANYTHING_ROLE") == "builder"]

    def residents(self): return [c for c in self.calls if c["env"].get("GAMEANYTHING_ROLE") != "builder"]

    def end(self, call):
        p = next(p for p in self.procs if p.pid == call["pid"]); p.terminate(); p.wait(10)

    def stop_all(self):
        for p in self.procs:
            if p.poll() is None: p.kill(); p.wait(10)


@pytest.fixture
def spawner():
    s = Spawner(); yield s; s.stop_all()


class FakeLab:
    """The lab broker: seats free or not, leases of other people."""
    def __init__(self, free=True, ready=(True, "", True), others=()):
        self.free, self._ready, self.others = free, ready, list(others); self.acquired = []; self.released = []; self.beats = []; self.mine = None

    def ready(self, game): return self._ready

    def acquire(self, user, project, game):
        self.acquired.append((user, project, game))
        if self.mine is None: self.mine = {"id": "L1", "user": user, "project": project, "game": game}
        self.mine.update(state="active", sandbox="mclab-x", seat=2) if self.free else self.mine.update(state="queued", queue_position=3)
        return dict(self.mine)

    def release(self, project, user): self.released.append((project, user)); self.mine = None

    def heartbeat(self, project, user): self.beats.append(project)

    def leases(self, project): return [l for l in self.others if l["project"] == project]

    def lease_str(self, l): return f"{l['user']}/{l['project']}/{l['sandbox']}:{l['seat']}"

    # `gameanything lab env up` (labup.py): env_next = the next job's result (None = still running); env = what `env status` says now
    env_next = {"state": "ok", "did": []}; env = {"state": "ok"}

    def env_up_start(self, lease, why, out):
        self.__dict__.setdefault("env_calls", []).append((lease, why)); return {"pid": 0, "at": time.time()}

    def env_up_result(self, job): return self.env_next

    def env_up_stop(self, job): self.__dict__.setdefault("env_stopped", []).append(job)

    def env_status(self, lease): self.__dict__.setdefault("env_asked", []).append(lease); return self.env


class Clock:
    def __init__(self): self.t = time.time()
    def __call__(self): return self.t


def project(mode="lab"):
    e = projects.create("建一座桥", "feature", game="minecraft", build_mode=mode); T = Thread(Path(e["path"]))
    T.append({"from": "agent", "type": "text", "text": "你好", "source": "terminal"})
    return e, T


def go(T, key="go-m1", decision="start"):
    g = T.card({"kind": "go", "key": key, "title": "开工做第 1 版", "milestone": "m1", "items": ["桥"]})
    if decision: T.answer(g["id"], {"decision": decision})
    (T.dir / ".agent_cursor").write_text(T.events()[-1]["id"], encoding="utf-8")     # her answer is not new words here
    return g


def request(T, kind="build_start", **det):
    d = {"go_key": "go-m1", "milestone": "m1", "build_mode": "lab", "playtest_rounds": 2, "items": ["桥"], **det}
    return agentd.write_request(T.root, kind, "她点了开工", d)


def daemon(spawner, lab, tmp_path, clock=None, **kw):
    return agentd.Agentd(claude="/bin/false", spawn=spawner, quiet=True, requests=tmp_path / "req", lab=lab, clock=clock or time.time, **kw)


def notes(T, frm=None):
    out = []
    for f in agentd.inbox(T) + sorted((T.dir / ".agentd_inbox" / "done").glob("*.json")) if (T.dir / ".agentd_inbox").is_dir() else []:
        d = json.loads(f.read_text(encoding="utf-8"))
        if frm is None or d.get("from") == frm: out.append(d["text"])
    return out


def rec(T, m="m1"): return json.loads(builds.run_file(T.root, m).read_text(encoding="utf-8"))


@pytest.fixture
def req_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GAMEANYTHING_PARENT_REQUESTS", str(tmp_path / "req")); monkeypatch.setenv("M2W_LAB_USER", "tester"); return tmp_path / "req"


# ---------------------------------------------------------------- end to end
def test_request_starts_one_builder_then_the_resident_gets_the_result_prompt(spawner, tmp_path, req_dir, monkeypatch):
    monkeypatch.setenv("MESHY_API_KEY", "paid-secret-123456")
    e, T = project(); go(T); lab = FakeLab()
    D = daemon(spawner, lab, tmp_path)
    f = request(T); assert f.exists()
    D.tick()
    (b,) = spawner.builders()
    assert b["cwd"] == T.root and b["env"]["GAMEANYTHING_LEASE"] == f"tester/{e['id']}/mclab-x:2"
    assert b["env"]["MC_N"] == "2" and b["env"]["GAMEANYTHING_GEN_OFF"] == "1" and "MESHY_API_KEY" not in b["env"] and b["env"]["GAMEANYTHING_SESSION"] == f"builder:{e['id']}"
    cmd = b["cmd"]; deny = cmd[cmd.index("--disallowedTools") + 1: cmd.index("--append-system-prompt")]
    assert "Bash(*mclab_rt*)" not in deny and "Bash(*python* *gen_*.py*)" in deny and "Bash(*pkill*)" in deny and "Bash(*docker run*)" in deny
    system = cmd[cmd.index("--append-system-prompt") + 1]
    assert "Role: builder" in system and "m1" in system and "at most **2** playtest rounds" in system.replace("At most", "at most") and "{{" not in system
    r = rec(T); assert r["state"] == "running" and r["lease"].endswith(":2") and r["go_card"] and r["playtest_rounds"] == 2
    assert f.exists(), "the request file stays where it was (visibility for a coordinator)"
    assert lab.acquired == [("tester", e["id"], "minecraft")]
    # one build per project: more scans, and even a second build_start, start nothing new while it runs
    go(T, "go-m1b"); request(T, go_key="go-m1b"); D.tick(); D.tick()
    assert len(spawner.builders()) == 1
    # her change while it builds: more rounds
    agentd.write_request(T.root, "build_change", "她想多试玩两轮", {"milestone": "m1", "change": "playtest_rounds: 2 -> 4"}); D.tick()
    assert rec(T)["playtest_rounds"] == 4 and "playtest_rounds: 2 -> 4" in (T.root / "5_build" / "m1" / "build_changes.yaml").read_text(encoding="utf-8")
    # the builder reports (it may not use the chat), then exits with the build delivered
    monkeypatch.setenv("GAMEANYTHING_ROLE", "builder")
    with pytest.raises(SystemExit): cli.main(["chat", "say", "--project", str(T.root), "--text", "hi"])
    assert cli.main(["agentd", "notify", "--project", str(T.root), "--from", "builder", "--text", "做好了：m1，build check 通过"]) == 0
    monkeypatch.delenv("GAMEANYTHING_ROLE")
    monkeypatch.setattr("gameanything.delivery.check", lambda root, only=None, probe=True: [{"m": "m1", "ok": True, "problems": [], "warnings": []}])
    spawner.end(b); D.tick()
    r = rec(T); assert r["state"] == "done" and r["delivered"] and lab.released == [(e["id"], lab.acquired[0][0])]
    (res,) = [c for c in spawner.residents() if "做好了" in c["cmd"][2]]
    assert "Builder note" in res["cmd"][2] and "gameanything build check" in res["cmd"][2]
    assert notes(T, "agentd-build") == [], "the builder said it itself: agentd adds no second note"
    st = "\n".join(agentd.status_lines()); assert "build m1: done" in st
    # the second request (another go card) starts the next builder now that the first is over
    D.tick(); assert len(spawner.builders()) == 2


def test_agentd_reports_the_end_when_the_builder_did_not(spawner, tmp_path, req_dir):
    _, T = project(); go(T); D = daemon(spawner, FakeLab(), tmp_path); request(T); D.tick()
    (b,) = spawner.builders(); spawner.end(b); D.tick()
    assert rec(T)["state"] == "ended"
    (n,) = notes(T, "agentd-build"); assert "还没交付好" in n and "不要发 result 卡" in n


def test_no_seat_waits_in_the_queue_with_one_note(spawner, tmp_path, req_dir):
    _, T = project(); go(T); lab = FakeLab(free=False); clock = Clock()
    D = daemon(spawner, lab, tmp_path, clock); request(T); D.tick()
    assert spawner.builders() == [] and rec(T)["state"] == "waiting_seat"
    (n,) = notes(T, "agentd-build"); assert "排在第 3 位" in n and "自动开始" in n
    D.tick(); assert len(lab.acquired) == 1, "no spinning: the broker is asked again only after SEAT_RETRY_SECS"
    clock.t += builds.SEAT_RETRY_SECS + 1; D.tick(); assert len(lab.acquired) == 2 and len(notes(T, "agentd-build")) == 1
    lab.free = True; clock.t += builds.SEAT_RETRY_SECS + 1; D.tick()
    assert len(spawner.builders()) == 1 and rec(T)["state"] == "running"


def test_no_lab_here_is_said_plainly_and_kept(spawner, tmp_path, req_dir):
    _, T = project(); go(T); clock = Clock()
    D = daemon(spawner, FakeLab(ready=(False, "这台电脑没有配好服务器沙箱（gamebench 实验室）", False)), tmp_path, clock); request(T); D.tick()
    assert spawner.builders() == [] and rec(T)["state"] == "blocked"
    (n,) = notes(T, "agentd-build"); assert "没有配好服务器沙箱" in n and "请求留着" in n
    clock.t += builds.BLOCKED_RETRY_SECS + 1; D.tick(); assert len(notes(T, "agentd-build")) == 1, "the same reason is said once"


def test_native_mode_needs_no_seat(spawner, tmp_path, req_dir):
    _, T = project("native"); go(T); lab = FakeLab(); D = daemon(spawner, lab, tmp_path); request(T, build_mode="native"); D.tick()
    (b,) = spawner.builders(); assert lab.acquired == [] and "GAMEANYTHING_LEASE" not in b["env"] and rec(T)["build_mode"] == "native"


def test_refused_without_start_and_each_go_card_builds_once(spawner, tmp_path, req_dir):
    _, T = project(); go(T, decision=None); D = daemon(spawner, FakeLab(), tmp_path); request(T); D.tick()
    assert spawner.builders() == [] and "还没有在开工卡上点「开工」" in notes(T, "agentd-build")[0]
    go(T); request(T); D.tick(); (b,) = spawner.builders(); spawner.end(b); D.tick()
    request(T); D.tick(); assert len(spawner.builders()) == 1 and any("已经开过一次工" in n for n in notes(T, "agentd-build"))


def test_a_build_run_by_someone_else_is_left_alone(spawner, tmp_path, req_dir):
    e, T = project(); go(T)
    lab = FakeLab(others=[{"id": "X", "user": "wenyi", "project": e["id"], "state": "active", "sandbox": "mclab-x", "seat": 2}])
    D = daemon(spawner, lab, tmp_path); f = request(T); D.tick(); D.tick()
    assert spawner.builders() == [] and lab.acquired == [] and notes(T, "agentd-build") == []
    assert builds._read(builds.index_file(T.root))["requests"][f.name]["state"] == "elsewhere"
    lab.others = []; D.tick(); assert spawner.builders() == [], "never started later either"


def test_requests_from_before_auto_builds_and_coordinator_mode(spawner, tmp_path, req_dir):
    _, T = project(); go(T)
    request(T)                                                     # written before agentd ever ran with auto builds
    time.sleep(1.1)
    D = daemon(spawner, FakeLab(), tmp_path); D.tick(); assert spawner.builders() == []
    _, T2 = project(); go(T2)
    C = daemon(spawner, FakeLab(), tmp_path, builds="coordinator"); request(T2); C.tick()
    assert C.builds is None and spawner.builders() == [] and not builds.run_file(T2.root, "m1").exists()
    with pytest.raises(ValueError): daemon(spawner, FakeLab(), tmp_path, builds="sometimes")


def test_restart_reports_an_interrupted_build_and_never_reruns(spawner, tmp_path, req_dir):
    e, T = project(); go(T); lab = FakeLab(); D = daemon(spawner, lab, tmp_path); request(T); D.tick()
    (b,) = spawner.builders(); spawner.end(b)                    # the daemon "restarts": a new one finds the builder gone
    D2 = daemon(spawner, lab, tmp_path); D2.tick()
    r = rec(T); assert r["state"] == "interrupted" and lab.released
    (n,) = notes(T, "agentd-build"); assert "中断" in n and "不会自动重新开始" in n
    D2.tick(); assert len(spawner.builders()) == 1


def test_a_live_builder_is_adopted_after_a_restart(spawner, tmp_path, req_dir):
    _, T = project(); go(T); lab = FakeLab(); D = daemon(spawner, lab, tmp_path); request(T); D.tick()
    (b,) = spawner.builders()
    D2 = daemon(spawner, lab, tmp_path); D2.tick(); assert rec(T)["state"] == "running" and len(spawner.builders()) == 1
    spawner.end(b); D2.tick(); assert rec(T)["state"] == "ended", "seen alive by this daemon: a normal end, not an interruption"


# ---------------------------------------------------------------- Codex parity and the paid-key guard
def test_codex_builder_and_resident_commands(tmp_path):
    p = agent_providers.provider("codex", binary="codex")
    req, lab_runs = tmp_path / "req", tmp_path / "runs"
    b = p.command("go", "SYS", None, False, tmp_path / "proj", role="builder", add_dirs=[req, lab_runs], network=True, shell_set={"GAMEANYTHING_KEYS_FILE": "/k"})
    assert b[b.index("--sandbox") + 1] == "workspace-write" and b[b.index("--cd") + 1] == str(tmp_path / "proj") and "--ignore-rules" in b
    assert [b[i + 1] for i, x in enumerate(b) if x == "--add-dir"] == [str(req), str(lab_runs)]
    assert "sandbox_workspace_write.network_access=true" in b and "shell_environment_policy.ignore_default_excludes=false" in b
    assert 'shell_environment_policy.set={GAMEANYTHING_KEYS_FILE="/k"}' in b and "--dangerously-bypass-approvals-and-sandbox" not in b
    assert "<builder-system-prompt>" in b[-1]
    off = [b[i + 1] for i, x in enumerate(b) if x == "--disable"]; assert "image_generation" in off and "apps" in off, "codex's own paid image tool is off"
    r = p.command("again", "SYS", "thread-1", True, tmp_path, add_dirs=[req])
    assert r[:3] == ["codex", "exec", "resume"] and 'sandbox_mode="workspace-write"' in r and f"sandbox_workspace_write.writable_roots={json.dumps([str(req)])}" in r
    assert "sandbox_workspace_write.network_access=true" not in r, "residents get no network" and r[-2] == "thread-1"
    c = agent_providers.provider("claude-code", binary="claude").command("go", "SYS", "s", False, tmp_path, role="builder", add_dirs=[req])
    assert c[c.index("--add-dir") + 1] == str(req)
    with pytest.raises(ValueError): p.command("go", "SYS", None, False, tmp_path, role="boss")


def test_resident_codex_run_can_write_the_requests_dir(spawner, tmp_path):
    _, T = project(); T.user_text("你好")
    D = agentd.Agentd(provider="codex", agent="codex", spawn=spawner, quiet=True, requests=tmp_path / "req"); D.tick()
    cmd = spawner.calls[0]["cmd"]; assert cmd[cmd.index("--add-dir") + 1] == str(tmp_path / "req")


def test_paid_keys_are_stripped_from_every_run():
    env = {"PATH": "/bin", "MESHY_API_KEY": "m", "OPENROUTER_API_KEY": "o", "OPENAI_API_KEY": "img", "HF_TOKEN": "h", "AWS_SECRET_ACCESS_KEY": "a",
           "ANTHROPIC_API_KEY": "claude-own", "CLAUDE_CODE_OAUTH_TOKEN": "t", "CODEX_API_KEY": "codex-own", "CODEX_HOME": "/c", "GAMEANYTHING_KEYS_FILE": "/k"}
    c = agent_providers.agent_env(env, "claude-code")
    assert c == {"PATH": "/bin", "ANTHROPIC_API_KEY": "claude-own", "CLAUDE_CODE_OAUTH_TOKEN": "t", "CODEX_HOME": "/c", "GAMEANYTHING_KEYS_FILE": "/k", "GAMEANYTHING_GEN_OFF": "1", "M2W_GEN_OFF": "1"}
    x = agent_providers.agent_env(env, "codex")
    assert x == {"PATH": "/bin", "CODEX_API_KEY": "codex-own", "CODEX_HOME": "/c", "GAMEANYTHING_KEYS_FILE": "/k", "GAMEANYTHING_GEN_OFF": "1", "M2W_GEN_OFF": "1"}
    assert "AWS_SECRET_ACCESS_KEY" in agent_providers.agent_env({**env, "CLAUDE_CODE_USE_BEDROCK": "1"}, "claude-code")


def test_gen_off_refuses_keys_but_still_reports_them(monkeypatch, tmp_path):
    f = tmp_path / "k.env"; f.write_text("OPENROUTER_API_KEY=from-file\n", encoding="utf-8"); monkeypatch.setenv("GAMEANYTHING_KEYS_FILE", str(f))
    monkeypatch.setenv("GAMEANYTHING_GEN_OFF", "1")
    with pytest.raises(keys.MissingKey, match="gameanything gen request"): keys.get("OPENROUTER_API_KEY")
    assert keys.available("OPENROUTER_API_KEY")
    monkeypatch.delenv("GAMEANYTHING_GEN_OFF"); assert keys.get("OPENROUTER_API_KEY") == "from-file"


def test_estimate_codex_api_with_a_bare_model_name():
    from gameanything.estimate import estimate
    r = estimate("small", "codex", "gpt-5.5", "api")
    assert r["estimate"]["account"] == "api" and r["estimate"]["cost_usd"] and r["estimate"]["model"] == "openai/gpt-5.5" and "$" in r["sentence_zh"]
    assert estimate("small", "claude-code", "sonnet", "api")["estimate"]["model"] == "anthropic/claude-sonnet"


# ---------------------------------------------------------------- the lab environment (gameanything lab env up) and resuming an environment block
NEEDS_HER = {"state": "needs_her", "why": "Steam in mclab-x needs her", "why_zh": "沙箱 mclab-x 里的 Steam 需要她登录一次：打开这个沙箱的画面（viewer port 6440）"}


def test_env_up_runs_for_the_lease_before_the_builder(spawner, tmp_path, req_dir):
    e, T = project(); go(T); lab = FakeLab(); D = daemon(spawner, lab, tmp_path); request(T); D.tick()
    ((lease, why),) = lab.env_calls
    assert lease == f"tester/{e['id']}/mclab-x:2" and "开工" in why and "Steam" in why and "never a game" in why, "her consent is recorded"
    (b,) = spawner.builders(); assert rec(T)["env"]["state"] == "ok" and rec(T)["state"] == "running"


def test_steam_needs_her_keeps_the_request_and_starts_when_she_logged_in(spawner, tmp_path, req_dir):
    e, T = project(); go(T); lab = FakeLab(); lab.env_next = NEEDS_HER; clock = Clock()
    D = daemon(spawner, lab, tmp_path, clock); f = request(T); D.tick()
    r = rec(T); assert spawner.builders() == [] and r["state"] == "blocked" and "needs_her" in r["why"] and lab.released and r["lease"] is None
    (n,) = notes(T, "agentd-build"); assert "需要她登录" in n and "6440" in n and "开工卡不算用掉" in n and "不要替她输入密码" in n
    D.tick(); clock.t += 60; D.tick(); assert len(lab.env_calls) == 1, "no spinning: env up again only after ENV_RETRY_SECS"
    clock.t += builds.ENV_RETRY_SECS; D.tick(); assert len(lab.env_calls) == 2 and len(notes(T, "agentd-build")) == 1, "said once"
    lab.env_next = {"state": "ok", "did": ["steam"]}; clock.t += builds.ENV_RETRY_SECS + 1; D.tick()
    (b,) = spawner.builders(); assert rec(T)["state"] == "running" and rec(T)["request"] == f.name
    idx = builds._read(builds.index_file(T.root)); assert len(idx["go_used"]) == 1 and idx["requests"][f.name]["state"] == "taken"


def test_a_slow_env_up_waits_as_preparing_and_a_stuck_one_is_stopped(spawner, tmp_path, req_dir):
    _, T = project(); go(T); lab = FakeLab(); lab.env_next = None; clock = Clock()
    D = daemon(spawner, lab, tmp_path, clock); request(T); D.tick(); D.tick()
    assert rec(T)["state"] == "preparing" and spawner.builders() == [] and len(lab.env_calls) == 1
    st = "\n".join(builds.status(T.root)); assert "build m1: preparing" in st
    lab.env_next = {"state": "ok"}; D.tick(); assert len(spawner.builders()) == 1 and rec(T)["state"] == "running" and rec(T)["lease"].endswith(":2")
    _, T2 = project(); go(T2); lab2 = FakeLab(); lab2.env_next = None; D2 = daemon(spawner, lab2, tmp_path, clock); request(T2); D2.tick()
    clock.t = time.time() + builds.ENV_UP_MAX_SECS + 5; D2.tick()
    assert lab2.env_stopped and rec(T2)["state"] == "blocked" and "over" in rec(T2)["why"]


def test_a_builder_blocked_on_the_environment_is_resumed_and_the_go_card_is_not_spent_twice(spawner, tmp_path, req_dir, monkeypatch):
    e, T = project(); go(T); lab = FakeLab(); clock = Clock(); D = daemon(spawner, lab, tmp_path, clock); f = request(T); D.tick()
    (b,) = spawner.builders(); first_log = rec(T)["log"]
    monkeypatch.setenv("GAMEANYTHING_ROLE", "builder")
    assert cli.main(["build", "status", "--project", str(T.root), "--m", "m1", "--blocked", "Steam 没开，gameanything lab env up 退出码 4"]) == 0
    assert cli.main(["agentd", "notify", "--project", str(T.root), "--from", "builder", "--text", "卡住了：沙箱环境，Steam 没开"]) == 0
    monkeypatch.delenv("GAMEANYTHING_ROLE")
    lab.env = NEEDS_HER; spawner.end(b); D.tick()
    r = rec(T); assert r["state"] == "blocked" and r["resume_logs"] == [first_log] and "Steam 没开" in r["blocked_why"] and lab.released
    assert any("需要她登录" in n for n in notes(T, "agentd-build")), "agentd tells her how to unblock it, although the builder sent its own note"
    # the resident asks again with the SAME go card while it waits: merged into it, tried at once, never "已经开过一次工"
    lab.env_next = NEEDS_HER; request(T); D.tick()
    assert not any("已经开过一次工" in n for n in notes(T, "agentd-build")) and len(spawner.builders()) == 1
    idx = builds._read(builds.index_file(T.root)); assert [v["state"] for v in idx["requests"].values()].count("merged") == 1
    lab.env_next = {"state": "ok", "did": ["steam"]}; clock.t += builds.ENV_RETRY_SECS + 1; D.tick()
    b1, b2 = spawner.builders(); prompt = " ".join(map(str, b2["cmd"]))
    assert "RESUME (1)" in prompt and first_log in prompt and rec(T)["state"] == "running" and rec(T)["request"] == f.name
    from gameanything import buildwatch
    assert "blocked" not in buildwatch.read_status(T.root, "m1"), "the new builder's first status clears the old block"
    idx = builds._read(builds.index_file(T.root)); assert len(idx["go_used"]) == 1
    # delivered after the resume: done, one go card, nothing left waiting
    monkeypatch.setattr("gameanything.delivery.check", lambda root, only=None, probe=True: [{"m": "m1", "ok": True, "problems": [], "warnings": []}])
    spawner.end(b2); D.tick(); assert rec(T)["state"] == "done"
    D.tick(); assert len(spawner.builders()) == 2


def test_the_m8_case_builder_ended_rc0_with_steam_gone_is_resumable(spawner, tmp_path, req_dir):
    _, T = project(); go(T); lab = FakeLab(); clock = Clock(); D = daemon(spawner, lab, tmp_path, clock); request(T); D.tick()
    (b,) = spawner.builders()
    lab.env = {"state": "failed", "why": "Steam is not running in mclab-x (`gameanything lab env up` starts it)", "why_zh": "沙箱里的 Steam 没有开"}
    spawner.end(b); D.tick()
    r = rec(T); assert r["state"] == "blocked" and lab.env_asked and "Steam is not running" in r["why"]
    (n,) = notes(T, "agentd-build"); assert "不算结束" in n and "不要发 result 卡" in n
    clock.t += builds.ENV_RETRY_SECS + 1; D.tick(); assert len(spawner.builders()) == 2


def test_resumes_are_capped_and_an_ok_environment_ends_the_build_as_before(spawner, tmp_path, req_dir, monkeypatch):
    _, T = project(); go(T); lab = FakeLab(); lab.env = {"state": "down", "why": "pod gone"}; clock = Clock()
    D = daemon(spawner, lab, tmp_path, clock); request(T); D.tick()
    for i in range(builds.MAX_RESUMES):
        spawner.end(spawner.builders()[-1]); D.tick(); assert rec(T)["state"] == "blocked"
        clock.t += builds.ENV_RETRY_SECS + 1; D.tick(); assert rec(T)["state"] == "running"
    spawner.end(spawner.builders()[-1]); D.tick(); assert rec(T)["state"] == "ended" and len(rec(T)["resume_logs"]) == builds.MAX_RESUMES


def test_a_coordinator_repairing_the_environment_under_its_own_lease_gets_the_build_back(spawner, tmp_path, req_dir):
    """2026-10-27: the build was blocked on the environment, the coordinator took the project's lease to repair it, agentd marked the
    build `elsewhere` and never started it again. Now it stays blocked while that lease is held and goes on once it is released."""
    e, T = project(); go(T); lab = FakeLab(); lab.env_next = NEEDS_HER; clock = Clock()
    D = daemon(spawner, lab, tmp_path, clock); request(T); D.tick(); assert rec(T)["state"] == "blocked"
    lab.others = [{"id": "X", "user": "wenyi", "project": e["id"], "state": "active", "sandbox": "mclab-x", "seat": 2}]
    for _ in range(3):
        clock.t += builds.ENV_RETRY_SECS + 1; D.tick()
        r = rec(T); assert r["state"] == "blocked" and "foreign lease" in r["why"] and spawner.builders() == [] and len(lab.acquired) == 1
    lab.others = []; lab.env_next = {"state": "ok", "did": ["steam"]}
    clock.t += builds.SEAT_RETRY_SECS + 1; D.tick()
    assert rec(T)["state"] == "running" and len(spawner.builders()) == 1 and len(lab.acquired) == 2


def test_a_build_the_coordinator_finished_under_its_own_lease_is_not_run_again(spawner, tmp_path, req_dir):
    from gameanything import buildwatch
    e, T = project(); go(T); lab = FakeLab(); lab.env_next = NEEDS_HER; clock = Clock()
    D = daemon(spawner, lab, tmp_path, clock); request(T); D.tick()
    lab.others = [{"id": "X", "user": "wenyi", "project": e["id"], "state": "active", "sandbox": "mclab-x", "seat": 2}]
    clock.t += builds.ENV_RETRY_SECS + 1; D.tick(); assert rec(T)["state"] == "blocked"
    buildwatch.write_status(T.root, "m1", 2, 2, "交付", None, True)
    lab.others = []; clock.t += builds.SEAT_RETRY_SECS + 1; D.tick()
    assert rec(T)["state"] == "elsewhere" and "finished" in rec(T)["why"] and spawner.builders() == []


def test_resume_and_takeover_by_hand(spawner, tmp_path, req_dir, capsys):
    e, T = project(); go(T); lab = FakeLab(); lab.env_next = NEEDS_HER; clock = Clock()
    D = daemon(spawner, lab, tmp_path, clock); request(T); D.tick(); assert rec(T)["state"] == "blocked"
    # an older agentd let go of it (`elsewhere`): resume hands it back, tried at the next scan without waiting for retry_at
    r = rec(T); r.update(state="elsewhere", why="lease wenyi/x/mclab-x:2 not taken by agentd", ended="2026-10-27T00:55:00")
    builds._write(builds.run_file(T.root, "m1"), r)
    assert cli.main(["build", "takeover", "--project", str(T.root), "--m", "m1"]) == 0 and rec(T)["state"] == "elsewhere"
    assert cli.main(["build", "resume", "--project", str(T.root), "--m", "m1"]) == 0
    assert rec(T)["state"] == "blocked" and "ended" not in rec(T) and "next scan" in capsys.readouterr().out
    lab.env_next = {"state": "ok", "did": []}; D.tick()
    assert rec(T)["state"] == "running" and len(spawner.builders()) == 1
    with pytest.raises(SystemExit, match="正在跑"): cli.main(["build", "resume", "--project", str(T.root), "--m", "m1"])
    with pytest.raises(SystemExit, match="不存在"): cli.main(["build", "resume", "--project", str(T.root), "--m", "m7"])
    # takeover: agentd leaves a waiting build alone for good
    _, T2 = project(); go(T2); lab.env_next = NEEDS_HER; request(T2); D.tick(); assert rec(T2)["state"] == "blocked"
    assert cli.main(["build", "takeover", "--project", str(T2.root), "--m", "m1"]) == 0
    clock.t += builds.ENV_RETRY_SECS + 1; D.tick(); assert rec(T2)["state"] == "elsewhere" and len(spawner.builders()) == 1


def test_the_real_env_up_job_runs_in_the_background_and_returns_its_result(tmp_path):
    lab = builds.Lab()
    job = lab.env_up_start("not-a-lease", "test", tmp_path / "env.json")
    for _ in range(300):
        res = lab.env_up_result(job)
        if res is not None: break
        time.sleep(0.1)
    assert res["state"] == "refused" and res["code"] == 3 and "malformed" in res["why"]
    assert lab.env_up_result({"pid": 0, "out": str(tmp_path / "none.json")})["state"] == "failed"
