"""The supervisor (gameanything agentd), process-based chat ownership, the page's status line (phase) and the background build banner.
No real agent is started: the spawner is replaced by one that starts a sleeping Python process (a real pid the liveness checks can see)."""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from gameanything import agent_providers, agentd, cli, conversation, dispatch, osdirs, projects
from gameanything.conversation import Owned, Thread, phase
from gameanything.ui import screens

STATIC = Path(screens.__file__).parent / "static"


# ---------------------------------------------------------------- helpers
class Spawner:
    """Records each run the daemon starts; each run is a real waiting process (so pid checks work), ended by the test: it exits 0 when its
    stdin closes (terminate() would be exit code 1 on Windows, which agentd rightly reads as a crash)."""
    def __init__(self): self.calls = []; self.procs = []

    def __call__(self, cmd, cwd, env, log):
        p = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT)
        self.calls.append({"cmd": cmd, "cwd": Path(cwd), "env": env}); self.procs.append(p); return p

    def end(self, i=-1):
        p = self.procs[i]; p.stdin.close(); p.wait(10)

    def stop_all(self):
        for p in self.procs:
            if p.poll() is None: p.kill(); p.wait(10)


@pytest.fixture
def spawner():
    s = Spawner(); yield s; s.stop_all()


class Clock:
    def __init__(self): self.t = time.time()
    def __call__(self): return self.t


def new_project(title="测试项目"):
    e = projects.create(title, "feature", game="overcooked2"); return e, Thread(Path(e["path"]))


def daemon(spawner, clock=None, **kw):
    return agentd.Agentd(claude="/bin/false", spawn=spawner, clock=clock or time.time, quiet=True, **kw)


def dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"]); p.wait(10); return p.pid


def statuses(T): return [e["text"] for e in T.events() if e["type"] == "status"]


# ---------------------------------------------------------------- owner liveness
def test_owner_live_by_process():
    _, T = new_project()
    me = os.getpid()
    T._write_owner({"session": "agentd:x", "instance": "r1", "host": socket.gethostname(), "proc": me, "proc_start": osdirs.pid_start(me),
                    "since": conversation.now(), "last_seen": "2000-01-01T00:00:00"})
    assert T.owner_live(), "a running process owns the chat, however old last_seen is"
    T._write_owner({**T.owner(), "proc": dead_pid()})
    assert not T.owner_live(), "a dead run frees the chat at once"
    if osdirs.pid_start(me) is not None:                                   # Linux: a reused pid (other start time) is not the owner
        T._write_owner({**T.owner(), "proc": me, "proc_start": "1"})
        assert not T.owner_live()


def test_owner_live_other_host_and_interactive():
    _, T = new_project()
    fresh = conversation.now(); old = (datetime.now() - timedelta(seconds=conversation.OWNER_STALE_SECS + 5)).isoformat(timespec="seconds")
    T._write_owner({"session": "s", "host": "another-machine", "proc": 1, "since": fresh, "last_seen": fresh})
    assert T.owner_live(), "another host: its pid means nothing here, the timestamp decides"
    T._write_owner({**T.owner(), "last_seen": old})
    assert not T.owner_live()
    T._write_owner({"session": "s", "host": socket.gethostname(), "since": fresh, "last_seen": fresh})       # an interactive session (no proc)
    assert T.owner_live()
    T._write_owner({**T.owner(), "last_seen": old})
    assert not T.owner_live(), "an interactive owner unseen for 90 s is gone (was 10 minutes)"
    assert conversation.OWNER_STALE_SECS <= 120


def test_claim_for_a_run_and_release(monkeypatch):
    _, T = new_project()
    me = os.getpid()
    o, _ = T.claim("agentd:p", proc=me, inst="run1")
    assert o["proc"] == me and o["instance"] == "run1"
    monkeypatch.setenv("GAMEANYTHING_INSTANCE", "run1")                               # the run itself claims: it is the same owner, the pid stays
    o, took = T.claim("agentd:p")
    assert not took and T.owner()["proc"] == me
    monkeypatch.setenv("GAMEANYTHING_INSTANCE", "someone-else")
    with pytest.raises(Owned): T.claim("interactive")
    with pytest.raises(Owned): T.guard("interactive")
    monkeypatch.setenv("GAMEANYTHING_INSTANCE", "run1")
    assert T.release("agentd:p") and not T.owner_live()
    monkeypatch.setenv("GAMEANYTHING_INSTANCE", "someone-else")
    assert T.guard("interactive") == "interactive" and T.owner()["session"] == "interactive"   # a released chat is taken without --force


def test_default_session_from_env(monkeypatch):
    monkeypatch.setenv("GAMEANYTHING_SESSION", "agentd:abc")
    assert conversation.default_session() == "agentd:abc"


# ---------------------------------------------------------------- the daemon's decisions
def test_new_words_start_one_run(spawner, monkeypatch):
    monkeypatch.setattr(agentd, "MAX_CORRECTIONS", 0); monkeypatch.setattr(agentd, "MAX_CONTINUE", 0)   # the run lifecycle only (flow re-runs: test_flow*.py)
    e, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "你好", "source": "terminal"})          # not brand new: only her words start a run
    D = daemon(spawner)
    D.tick(); assert spawner.calls == []
    u = T.user_text("你好，帮我看看")
    D.tick()
    assert len(spawner.calls) == 1
    c = spawner.calls[0]
    assert c["cwd"] == T.root.resolve() or c["cwd"] == T.root
    assert c["env"]["GAMEANYTHING_SESSION"] == f"agentd:{e['id']}" and "CLAUDE_CODE_SESSION_ID" not in c["env"]
    cmd = c["cmd"]
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk" and "--session-id" in cmd and "--resume" not in cmd
    assert "--append-system-prompt" in cmd and T.root.as_posix() in cmd[cmd.index("--append-system-prompt") + 1].replace("\\", "/")
    assert agentd.CALLING[0] in statuses(T), "the user sees at once that an agent is coming"
    assert T.calling()["event"] == u["id"]
    run = agentd.active_run(T); assert run and run["pid"] == spawner.procs[0].pid
    assert T.owner_live() and T.owner()["proc"] == run["pid"]
    info = T.online(); assert info["phase"] == "calling" and info["run"]
    # one run per project: more words while it runs start nothing
    T.user_text("还有一件事")
    D.tick(); D.tick(); assert len(spawner.calls) == 1
    # the run reads and answers, then ends
    T.read(); assert T.online()["phase"] == "working"
    T.agent_text("好的，看了", session=f"agentd:{e['id']}")
    spawner.end(); D.tick()
    r = json.loads(agentd.run_path(T).read_text(encoding="utf-8"))
    assert r["ended"] and r["answered"] and not T.owner_live()
    assert T.online()["phase"] is None
    # the next words resume the same Claude session
    T.user_text("第二句")
    D.tick()
    assert len(spawner.calls) == 2
    cmd2 = spawner.calls[1]["cmd"]; sid = cmd[cmd.index("--session-id") + 1]
    assert cmd2[cmd2.index("--resume") + 1] == sid
    assert json.loads((T.dir / ".agent_session").read_text(encoding="utf-8"))["runs"] == 2
    assert statuses(T).count(agentd.CALLING[0]) == 1, "the calling line is not repeated for every message (the status line shows it)"


def test_brand_new_project_is_greeted(spawner):
    _, T = new_project()
    D = daemon(spawner); D.tick()
    assert len(spawner.calls) == 1 and "just created" in spawner.calls[0]["cmd"][2]
    assert T.online()["phase"] == "working"


def test_a_live_interactive_owner_is_left_alone(spawner):
    _, T = new_project()
    T.claim("wenyi-main"); T.user_text("在吗")
    D = daemon(spawner); D.tick()
    assert spawner.calls == [] and T.online()["phase"] == "sent"


def test_queue_at_the_cap(spawner):
    projects.save_settings({"max_active_projects": 1})
    _, A = new_project("甲"); _, B = new_project("乙")
    for T in (A, B): T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"})
    A.user_text("先说的"); time.sleep(1.1); B.user_text("后说的")
    D = daemon(spawner); D.tick()
    assert len(spawner.calls) == 1 and spawner.calls[0]["cwd"] in (A.root, A.root.resolve()), "oldest message first"
    q = dispatch.queued(B)
    assert q and q["active"] == 1 and q["cap"] == 1 and q["projects"] == ["甲"]
    assert B.online()["phase"] == "queued"
    A.agent_text("好"); spawner.end(); D.tick()                                # A's run ends: B gets the slot
    assert len(spawner.calls) == 2 and spawner.calls[1]["cwd"] in (B.root, B.root.resolve())
    assert dispatch.queued(B) is None


def test_no_answer_is_retried_then_reported(spawner):
    _, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"})
    u = T.user_text("你好")
    clk = Clock(); D = daemon(spawner, clk)
    D.tick(); assert len(spawner.calls) == 1
    for n, wait in enumerate(agentd.RETRY_AFTER, 2):
        spawner.end(); D.tick()                                                # ended without a word
        assert len(spawner.calls) == n - 1, "no retry before the back-off"
        clk.t += wait + 1; D.tick()
        assert len(spawner.calls) == n
    spawner.end(); D.tick(); clk.t += 1000; D.tick()
    assert len(spawner.calls) == 1 + len(agentd.RETRY_AFTER), "gives up after the retries"
    assert agentd.failed(T)["event"] == u["id"] and agentd.FAILED[0] in statuses(T)
    assert T.online()["phase"] == "failed"
    T.user_text("再试一次"); D.tick()
    assert len(spawner.calls) == 2 + len(agentd.RETRY_AFTER), "new words: a new try"


def test_daemon_adopts_runs_of_an_earlier_daemon(spawner, monkeypatch):
    monkeypatch.setattr(agentd, "MAX_CORRECTIONS", 0); monkeypatch.setattr(agentd, "MAX_CONTINUE", 0)   # the run lifecycle only (flow re-runs: test_flow*.py)
    _, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"}); T.user_text("你好")
    daemon(spawner).tick(); assert len(spawner.calls) == 1
    D2 = daemon(spawner); D2.tick()                                            # a restarted daemon: the run still owns the chat
    assert len(spawner.calls) == 1
    T.read(); T.agent_text("好"); spawner.end(); D2.tick()
    assert json.loads(agentd.run_path(T).read_text(encoding="utf-8"))["answered"] and not T.owner_live()


def test_heartbeat_and_old_watcher(spawner):
    _, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"}); T.user_text("你好")
    assert not agentd.daemon_state()["alive"]
    assert [x for x, _ in dispatch.scan_unowned()], "without agentd the parent's watcher still sees the project"
    daemon(spawner).tick()
    assert agentd.daemon_state()["alive"] and T.online()["agentd"]["alive"]
    assert dispatch.scan_unowned() == [], "with agentd alive the old --unowned watcher stays quiet"
    hb = json.loads(agentd.heartbeat_path().read_text(encoding="utf-8")); assert hb["runs"] and hb["pid"] == os.getpid()


def test_down_when_nobody_will_come():
    _, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"}); T.user_text("有人吗")
    assert T.online()["phase"] == "down"


def test_env_and_command():
    env = agentd.clean_env({"CLAUDE_CODE_SESSION_ID": "x", "CLAUDECODE": "1", "CLAUDE_PID": "9", "CLAUDE_CODE_OAUTH_TOKEN": "t", "PATH": "/bin",
                            "GAMEANYTHING_INSTANCE": "parent", "HOME": "/root"}, {"GAMEANYTHING_SESSION": "agentd:p"})
    assert env == {"CLAUDE_CODE_OAUTH_TOKEN": "t", "PATH": "/bin", "HOME": "/root", "GAMEANYTHING_SESSION": "agentd:p"}
    cmd = agentd.command("claude", "sonnet", "go", "SYS", "abc", True)
    assert cmd[:3] == ["claude", "-p", "go"] and cmd[cmd.index("--resume") + 1] == "abc" and "stream-json" in cmd and "--verbose" in cmd
    assert cmd[cmd.index("--tools") + 1] == "Bash,Read,Write,Edit,Glob,Grep,WebSearch,WebFetch" and "--strict-mcp-config" in cmd


def test_codex_provider_command_session_and_environment(tmp_path):
    p = agent_providers.provider("codex", binary="codex")
    cmd = p.command("go", "SYS", None, False, tmp_path)
    assert cmd[:3] == ["codex", "exec", "--json"]
    assert "--ignore-user-config" in cmd
    assert cmd[cmd.index("--sandbox") + 1] == "workspace-write" and "--approve-for-me" not in cmd
    assert cmd[cmd.index("--cd") + 1] == str(tmp_path) and "SYS" in cmd[-1] and "go" in cmd[-1]
    resumed = p.command("again", "SYS", "thread-123", True, tmp_path)
    assert resumed[:4] == ["codex", "exec", "resume", "--json"] and "--ignore-user-config" in resumed
    assert "--skip-git-repo-check" in resumed and resumed[-2] == "thread-123"
    log = tmp_path / "codex.jsonl"
    log.write_text('{"type":"thread.started","thread_id":"thread-123"}\n', encoding="utf-8")
    assert p.session_id(log) == "thread-123"
    env = p.clean_env({"CODEX_THREAD_ID": "parent", "CODEX_HOME": "/login", "OPENAI_API_KEY": "secret", "PATH": "/bin"})
    assert env == {"CODEX_HOME": "/login", "OPENAI_API_KEY": "secret", "PATH": "/bin"}
    with pytest.raises(ValueError, match="USD budget"):
        p.command("go", "SYS", None, False, tmp_path, budget=1.0)


def test_codex_keeps_machine_settings_and_drops_operator_extras(tmp_path):
    home = tmp_path / "codexhome"; home.mkdir()
    (home / "config.toml").write_text('model = "gpt-x"\nsqlite_home = "/tmp/codex-sqlite"\nlog_dir = \'/var/log/cx\'  # here\n'
                                      '[projects."/a"]\nsqlite_home = "/nope"\n', encoding="utf-8")
    p = agent_providers.provider("codex", binary="codex")
    for resume in (False, True):
        cmd = p.command("go", "SYS", "t-1", resume, tmp_path, env={"CODEX_HOME": str(home)})
        assert 'sqlite_home="/tmp/codex-sqlite"' in cmd and "log_dir='/var/log/cx'" in cmd and 'sqlite_home="/nope"' not in cmd
        assert not any("gpt-x" in x for x in cmd)                       # only the machine keys, never the model or the rest
        assert "skills.include_instructions=false" in cmd and 'web_search="live"' in cmd and "goals" in cmd
        assert "AGENTS.md" in cmd[-1] and "agent_notes" in cmd[-1]        # the operator's own AGENTS.md does not apply to a run
    b = p.command("go", "SYS", None, False, tmp_path, role="builder", network=True, env={"CODEX_HOME": str(tmp_path / "none")})
    assert 'web_search="live"' in b and not any(x.startswith("sqlite_home") for x in b)


def test_codex_new_session_gets_its_own_age_and_count(spawner):
    _, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"})
    (T.dir / ".agent_session").write_text(json.dumps({"id": "old", "provider": "codex", "created": "2020-01-01T00:00:00", "runs": 9, "broken": True}), encoding="utf-8")
    T.user_text("你好"); D = agentd.Agentd(provider="codex", agent="codex", spawn=spawner, quiet=True); D.tick()
    assert "resume" not in spawner.calls[0]["cmd"][:3]
    run = json.loads(agentd.run_path(T).read_text(encoding="utf-8"))
    Path(run["log"]).write_text('{"type":"thread.started","thread_id":"fresh"}\n', encoding="utf-8")
    spawner.end(); D.tick()
    s = json.loads((T.dir / ".agent_session").read_text(encoding="utf-8"))
    assert s["id"] == "fresh" and s["runs"] == 1 and s["created"] != "2020-01-01T00:00:00"


def test_codex_session_is_learned_from_jsonl_after_first_run(spawner):
    _, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"}); T.user_text("你好")
    D = agentd.Agentd(provider="codex", agent="codex", spawn=spawner, quiet=True)
    D.tick()
    cmd = spawner.calls[0]["cmd"]
    assert cmd[:3] == ["codex", "exec", "--json"] and "--session-id" not in cmd
    run = json.loads(agentd.run_path(T).read_text(encoding="utf-8"))
    Path(run["log"]).write_text('{"type":"thread.started","thread_id":"thread-abc"}\n', encoding="utf-8")
    spawner.end(); D.tick()
    session = json.loads((T.dir / ".agent_session").read_text(encoding="utf-8"))
    assert session["id"] == "thread-abc" and session["provider"] == "codex" and session["runs"] == 1


def test_prompt_template_is_filled():
    e, T = new_project("读博通关战")
    p = agentd.render_prompt(e, T.root, "agentd:x", Path("/req"))
    assert "{{" not in p.split("\n", 3)[3] and "读博通关战" in p and str(T.root) in p and "agentd:x" in p and str(Path("/req")) in p
    for must in ("simplified Chinese", "gameanything chat claim", "gameanything agentd request", "gameanything gen request", "build_start", "Never"):
        assert must in p


# ---------------------------------------------------------------- requests for the coordinator, notes for the agent
def test_parent_requests(monkeypatch, tmp_path, capsys):
    e, T = new_project()
    monkeypatch.setenv("GAMEANYTHING_PARENT_REQUESTS", str(tmp_path / "req")); monkeypatch.setenv("GAMEANYTHING_SESSION", f"agentd:{e['id']}")
    f = agentd.write_request(T.root, "build_start", "她点了开工", {"go_key": "g1", "milestone": "m2"})
    d = json.loads(f.read_text(encoding="utf-8"))
    assert f.parent == tmp_path / "req" and f.name.startswith(e["id"] + "-")
    assert d["project"] == e["id"] and d["kind"] == "build_start" and d["details"]["go_key"] == "g1" and d["session"] == f"agentd:{e['id']}"
    assert agentd.write_request(T.root, "build_start", "again") != f, "two requests in one second do not overwrite each other"
    for bad in (("launch", "x", None), ("question", " ", None), ("question", "x", ["not", "a", "dict"])):
        with pytest.raises(ValueError): agentd.write_request(T.root, *bad)
    assert cli.main(["agentd", "request", "--project", str(T.root), "--kind", "gen_request_ready", "--text", "图可以画了",
                     "--details", json.dumps({"script": "4_design/tools/gen_a.py", "permission_key": "p", "go_key": "g"})]) == 0
    assert len(list((tmp_path / "req").glob("*.json"))) == 2, "gen_request_ready goes into the project's gen queue, not to the coordinator"
    assert len(list((T.dir / ".gen_queue").glob("*.json"))) == 1
    with pytest.raises(SystemExit): cli.main(["agentd", "request", "--project", str(T.root), "--kind", "nope", "--text", "x"])


def test_coordinator_note_starts_a_run(spawner):
    _, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"})
    assert cli.main(["agentd", "notify", "--project", str(T.root), "--text", "预览图画好了，在 4_design/targets/m2/"]) == 0
    D = daemon(spawner); D.tick()
    assert len(spawner.calls) == 1 and "预览图画好了" in spawner.calls[0]["cmd"][2]
    assert len(agentd.inbox(T)) == 1, "the note stays until the run ended (a failed run is retried with it)"
    T.agent_text("好的"); spawner.end(); D.tick()
    assert agentd.inbox(T) == [] and list((T.dir / ".agentd_inbox" / "done").glob("*.json"))


# ---------------------------------------------------------------- the page's status line
def _ev(i, frm, typ="text", src="ui", at=None): return {"id": f"e{i}", "from": frm, "type": typ, "source": src, "at": at or f"2026-10-23T10:00:{i:02d}"}


@pytest.mark.parametrize("info,evs,want", [
    ({}, [], None),
    ({"run": {"started": "x"}}, [], "working"),                                          # a brand-new project being greeted
    ({"agentd": {"alive": True}}, [_ev(1, "user")], "sent"),
    ({"owner_live": True}, [_ev(1, "user")], "sent"),
    ({}, [_ev(1, "user")], "down"),
    ({"run": {"started": "x"}}, [_ev(1, "user")], "calling"),
    ({"calling": {"event": "e1", "at": conversation.now()}, "agentd": {"alive": True}}, [_ev(1, "user")], "calling"),
    ({"calling": {"event": "e0", "at": "2026-10-23T09:00:00"}, "agentd": {"alive": True}}, [_ev(0, "user"), _ev(1, "user")], "sent"),   # an old call
    ({"calling": {"event": None, "at": conversation.now()}, "agentd": {"alive": True}}, [_ev(1, "user", at="2026-10-23T10:00:00")], "calling"),  # older file: only a time
    ({"calling": {"event": "e1", "at": "2026-10-23T09:00:00"}, "agentd": {"alive": True}}, [_ev(1, "user")], "sent"),   # a call never expired before (QA 2026-10-29)
    ({"calling": {"event": "e1", "at": conversation.now()}}, [_ev(1, "user")], "down"),                       # agentd stopped: not 「正在叫」
    ({"queued": {"active": 3, "cap": 3}, "agentd": {"alive": True}}, [_ev(1, "user")], "queued"),
    ({"cursor": "e1", "run": {"started": "x"}}, [_ev(1, "user")], "working"),
    ({"noticed": "e1"}, [_ev(1, "user")], "working"),
    ({"failed": {"event": "e1"}, "calling": {"event": "e1"}}, [_ev(1, "user")], "failed"),
    ({"failed": {"event": "e0"}, "agentd": {"alive": True}}, [_ev(0, "user"), _ev(1, "user")], "sent"),
    ({"agentd": {"alive": True}}, [_ev(1, "user"), _ev(2, "agent")], None),
    ({"run": {"started": "x"}}, [_ev(1, "user"), _ev(2, "agent")], "working"),         # still working after its reply
    ({"agentd": {"alive": True}}, [_ev(1, "user", src="terminal")], None),               # words typed in the terminal are already known
])
def test_phase(info, evs, want):
    assert phase(evs, info) == want


# ---------------------------------------------------------------- the background build banner
def _plan(root, ms):
    (root / "4_design").mkdir(exist_ok=True)
    (root / "4_design" / "world_plan.yaml").write_text(yaml.safe_dump({"world_plan": {"milestones": ms}}, allow_unicode=True), encoding="utf-8")


def test_build_banner_from_progress_card_and_status_file(capsys):
    _, T = new_project()
    assert screens.build_banner(T.root, "zh", T.events()) == []
    _plan(T.root, {"m1": {"name": "第一版", "status": "built"}, "m2": {"name": "第二版", "status": "building"}})
    T.card({"kind": "progress", "title": "构建中", "milestone": "第二版", "key": "feature_m2_build",
            "steps": [{"text": "准备实验室", "state": "done"}, {"text": "第 1 轮：做地图", "state": "current"}],
            "meter": {"round": 1, "max_rounds": 3, "elapsed_min": 30, "wall_min": 180}})
    b, = screens.build_banner(T.root, "zh", T.events())
    assert b["m"] == "m2" and b["round"] == 1 and b["max_rounds"] == 3 and b["step"] == "第 1 轮：做地图" and 29 <= b["elapsed_min"] <= 31
    started = (datetime.now() - timedelta(minutes=65)).isoformat(timespec="seconds")
    assert cli.main(["build", "status", "--project", str(T.root), "--m", "m2", "--round", "2", "--max", "3", "--step", "第 2 轮：试玩评审",
                     "--step-en", "Round 2: playtest review", "--started", started]) == 0
    d = yaml.safe_load((T.root / "5_build" / "m2" / "build_status.yaml").read_text(encoding="utf-8"))
    assert d["round"] == 2 and d["max_rounds"] == 3 and d["started"] == started and d["updated"] and d["done"] is False
    b, = screens.build_banner(T.root, "zh", T.events())
    assert (b["round"], b["max_rounds"], b["step"]) == (2, 3, "第 2 轮：试玩评审") and 64 <= b["elapsed_min"] <= 66
    assert screens.build_banner(T.root, "en", T.events())[0]["step"] == "Round 2: playtest review"
    assert cli.main(["build", "status", "--project", str(T.root), "--m", "m2", "--round", "3"]) == 0       # the rest is kept
    d = yaml.safe_load((T.root / "5_build" / "m2" / "build_status.yaml").read_text(encoding="utf-8"))
    assert d["round"] == 3 and d["step"] == "第 2 轮：试玩评审" and d["started"] == started
    assert cli.main(["build", "status", "--project", str(T.root), "--m", "m2", "--done"]) == 0
    assert screens.build_banner(T.root, "zh", T.events()) == [], "a finished build hides the banner"
    for bad in (["--m", "../x"], ["--m", "m2", "--round", "4", "--max", "3"], ["--m", "m2", "--started", "yesterday"]):
        with pytest.raises(SystemExit): cli.main(["build", "status", "--project", str(T.root), *bad])


def test_build_banner_in_the_thread_api(tmp_path):
    from gameanything.ui import Project
    _, T = new_project()
    _plan(T.root, {"m1": {"name": "第一版", "status": "building"}})
    T.user_text("开始了吗")
    st = Project(T.root).thread_state(None, "zh")
    assert st["build"][0]["m"] == "m1" and st["agent"]["phase"] == "down" and st["events"][-1]["text"] == "开始了吗"
    (T.root / "4_design" / "world_plan.yaml").write_text("world_plan: [broken", encoding="utf-8")
    assert Project(T.root).thread_state(None, "zh")["build"] == []


# ---------------------------------------------------------------- the page's words
@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_shell_words_have_english():
    """Every t("中文") literal in shell.js has an English entry (or is a kind word); the page logic parses."""
    js = (STATIC / "shell.js").read_text(encoding="utf-8")
    subprocess.run(["node", "--check", str(STATIC / "shell.js")], check=True)
    used = sorted({m for m in re.findall(r'\bt\("((?:[^"\\]|\\.)*)"', js) if re.search(r"[一-鿿]", m)})
    lines = [m for m in re.findall(r'\[(?:ring|dots), "([^"]+)"\]', js)]                          # the status line's words, passed to t() later
    probe = ("globalThis.window={addEventListener(){}};globalThis.document={documentElement:{dataset:{},getAttribute(){return null},setAttribute(){}},"
             "addEventListener(){},querySelectorAll(){return[]}};globalThis.localStorage={getItem(){return null},setItem(){}};globalThis.navigator={language:'zh'};\n"
             + (STATIC / "i18n.js").read_text(encoding="utf-8") + f"\nconsole.log(JSON.stringify({json.dumps(used + lines, ensure_ascii=False)}.filter(s=>!(s in EN))))")
    missing = json.loads(subprocess.run(["node", "-"], input=probe, capture_output=True, text=True, check=True, encoding="utf-8").stdout)
    assert len(lines) == 8 and missing == []                                                    # 7 states + the login-expired variant of "failed"
