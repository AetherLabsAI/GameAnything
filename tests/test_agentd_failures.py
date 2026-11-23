"""QA 2026-10-29 (backend): agentd retries what it says it retries, tells her WHY a run failed (login, usage limit, an agent CLI that cannot
work here, a crash, a loop), backs off instead of burning a run per message, and Codex's sandbox problem is detected, never worked around."""
import json
import time
from pathlib import Path

import pytest

from gameanything import activity, agent_providers as ap, agentd, models
from test_agentd import Clock, Spawner, daemon, new_project, statuses


@pytest.fixture
def spawner():
    s = Spawner(); yield s; s.stop_all()


def run_log(T) -> Path:
    return Path(json.loads(agentd.run_path(T).read_text(encoding="utf-8"))["log"])


def fail_with(T, spawner, text):
    """The current run writes `text` to its log, then ends without answering."""
    with open(run_log(T), "a", encoding="utf-8") as f: f.write(text + "\n")
    spawner.end()


# ---------------------------------------------------------------- retries that the log promises really happen
def test_first_greeting_of_a_new_project_is_retried(spawner):
    _, T = new_project()
    clk = Clock(); D = daemon(spawner, clk); D.tick()
    assert len(spawner.calls) == 1 and "just created" in spawner.calls[0]["cmd"][2]
    spawner.end(); D.tick()                                                   # ended without a word
    assert len(spawner.calls) == 1
    clk.t += agentd.RETRY_AFTER[0] + 1; D.tick()
    assert len(spawner.calls) == 2 and "just created" in spawner.calls[1]["cmd"][2], "the greeting is retried as logged"
    spawner.end(); D.tick(); clk.t += agentd.RETRY_AFTER[1] + 1; D.tick(); assert len(spawner.calls) == 3
    spawner.end(); D.tick(); clk.t += 1000; D.tick(); D.tick()
    assert len(spawner.calls) == 3 and agentd.FAILED[0] in statuses(T), "after the retries: she is told, no endless runs"
    D2 = daemon(spawner, clk); D2.tick(); assert len(spawner.calls) == 3, "a restarted daemon does not start over"


def test_a_failed_corrective_run_is_retried_with_its_instruction(spawner, monkeypatch):
    _, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"})
    agentd._write(T.dir / ".agentd_correct.json", {"at": agentd.now(), "key": "correct-x", "step": "spec", "missing": [{"id": "spec_card", "why": "发卡"}]})
    clk = Clock(); D = daemon(spawner, clk); D.tick()
    assert len(spawner.calls) == 1 and "Corrective run" in spawner.calls[0]["cmd"][2]
    assert (T.dir / ".agentd_correct.json").exists(), "not deleted when the run starts"
    spawner.end(); D.tick(); clk.t += agentd.RETRY_AFTER[0] + 1; D.tick()
    assert len(spawner.calls) == 2 and "Corrective run" in spawner.calls[1]["cmd"][2]
    T.agent_text("好了"); spawner.end(); D.tick()
    assert not (T.dir / ".agentd_correct.json").exists()


# ---------------------------------------------------------------- the reason, for every kind of run
def test_login_failure_of_a_greeting_run_is_said(spawner):
    _, T = new_project()
    D = daemon(spawner); D.tick()
    fail_with(T, spawner, '{"type":"result","is_error":true,"result":"Not logged in · Please run /login"}'); D.tick()
    assert agentd.AUTH_FAILED[0] in statuses(T), "the notice is posted for a greeting run too, not only for her words"
    assert agentd.failed(T)["reason"] == "auth"


def test_backoff_no_run_per_message_after_a_login_failure(spawner):
    _, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"}); T.user_text("你好")
    clk = Clock(); D = daemon(spawner, clk); D.tick()
    fail_with(T, spawner, '{"type":"result","is_error":true,"result":"Not logged in"}'); D.tick()
    assert statuses(T).count(agentd.AUTH_FAILED[0]) == 1
    for w in ("在吗", "还在吗"):
        T.user_text(w); D.tick()
    assert len(spawner.calls) == 1, "no run for every new message while the login is broken"
    waits = [s for s in statuses(T) if s.startswith("这句话先记下了")]
    assert len(waits) == 2 and "登录" in waits[0], "each held message gets one line with the reason"
    assert T.online()["phase"] == "paused" and T.online()["failed"]["reason"] == "auth" and T.online()["backoff"]["kind"] == "auth"
    clk.t += agentd.BACKOFF_SECS["auth"] + 1; D.tick()
    assert len(spawner.calls) == 2, "after the backoff: one try for the words that waited"
    fail_with(T, spawner, '{"type":"result","is_error":true,"result":"Not logged in"}'); D.tick()
    clk.t += agentd.BACKOFF_SECS["auth"] + 1; D.tick(); D.tick()
    assert len(spawner.calls) == 2, "the same words are not tried again after every backoff"
    assert statuses(T).count(agentd.AUTH_FAILED[0]) == 2
    T.user_text("登录好了"); D.tick()
    assert len(spawner.calls) == 3, "her next words start a run"


def test_answered_but_crashed_with_a_usage_limit_is_said(spawner):
    _, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"}); T.user_text("开始")
    D = daemon(spawner); D.tick(); T.read(); T.agent_text("收到，我先看看")
    reset = int(time.time()) + 3600
    fail_with(T, spawner, json.dumps({"type": "rate_limit_event", "rate_limit_info": {"status": "rejected", "resetsAt": reset, "rateLimitType": "five_hour"}}))
    D.tick()
    r = json.loads(agentd.run_path(T).read_text(encoding="utf-8"))
    assert r["answered"] and r["failure"] == "limit"
    assert any("用量到上限" in s for s in statuses(T)), "a run that answered and then stopped on a limit is not counted as a plain success"


def test_crash_reason_is_said_after_the_retries(spawner):
    _, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"}); T.user_text("你好")

    class Crash(Spawner):
        def __call__(self, cmd, cwd, env, log):
            import subprocess, sys
            p = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(3)"], stdout=log, stderr=log)
            self.calls.append({"cmd": cmd}); self.procs.append(p); return p
    sp = Crash(); clk = Clock(); D = daemon(sp, clk)
    for _ in range(1 + len(agentd.RETRY_AFTER)):
        D.tick(); sp.procs[-1].wait(10); D.tick(); clk.t += 100
    D.tick()
    assert len(sp.calls) == 1 + len(agentd.RETRY_AFTER)
    f = agentd.failed(T); assert f["reason"] == "crash" and "退出码 3" in f["text"]
    assert any("退出码 3" in s for s in statuses(T))


# ---------------------------------------------------------------- Gemini: quota is a usage limit, not a login problem
def test_gemini_quota_waits_for_the_reset(spawner, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    _, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"}); T.user_text("你好")
    D = agentd.Agentd(provider="gemini", agent="/bin/false", spawn=spawner, quiet=True); D.tick()
    fail_with(T, spawner, '{"type":"result","status":"error","error":{"type":"unknown","message":"[API Error: You have exhausted your daily quota on this model.]"}}')
    D.tick()
    st = statuses(T)
    assert any("Gemini 的用量到上限了" in s for s in st) and not any("API key 不对" in s for s in st)
    assert "not logged in" not in (D.log_dir() / "agentd.log").read_text(encoding="utf-8")


def test_gemini_reads_the_skill_but_cannot_write_it(tmp_path):
    from gameanything import shipped
    p = ap.provider("gemini", binary="gemini")
    cmd, _ = p.launch("go", "R", None, False, tmp_path, add_dirs=[tmp_path / "req"], env={"GAMEANYTHING_GEMINI_HOME": str(tmp_path / "gh")})
    inc = [cmd[i + 1] for i, x in enumerate(cmd) if x == "--include-directories"]
    assert str(shipped.SKILL.resolve()) in inc, "the step docs and setting guides are readable (no 'Path not in workspace')"
    pol = (tmp_path / "gh" / ".gemini" / "m2w" / "policy-resident.toml").read_text(encoding="utf-8")
    assert 'toolName = ["write_file", "replace"]' in pol and shipped.SKILL.resolve().as_posix().split("/")[-1] in pol


# ---------------------------------------------------------------- Codex: its sandbox cannot start in this container
BWRAP = "bwrap: Failed to make / slave: Permission denied"


def test_codex_bwrap_error_is_a_sandbox_problem_not_a_login(tmp_path):
    log = tmp_path / "c.jsonl"
    log.write_text(json.dumps({"type": "item.completed", "item": {"type": "command_execution", "aggregated_output": BWRAP, "exit_code": 1}}) + "\n"
                   + json.dumps({"type": "turn.failed", "error": {"message": "401 Unauthorized? no: " + BWRAP}}) + "\n", encoding="utf-8")
    c = ap.provider("codex", binary="codex")
    assert c.failure(log) == "sandbox" and not c.auth_failed(log)


def test_codex_probe_is_cached(monkeypatch, tmp_path):
    monkeypatch.delenv("GAMEANYTHING_CODEX_SANDBOX", raising=False)
    monkeypatch.setattr("sys.platform", "linux")
    exe = tmp_path / "codex"; exe.write_text("#!/bin/sh\n", encoding="utf-8"); exe.chmod(0o755)
    calls = []

    class R:
        returncode, stdout, stderr = 1, "", BWRAP + "\n"

    def run(cmd, **kw): calls.append(cmd); return R()
    p1 = ap.codex_sandbox_probe(str(exe), {}, run=run); p2 = ap.codex_sandbox_probe(str(exe), {}, run=run)
    assert not p1["ok"] and "bwrap" in p1["why"] and p2 == p1 and len(calls) == 1, "probed once, then cached"
    assert calls[0][1:] == ["sandbox", "--", "true"]
    R.returncode, R.stderr = 2, "error: unrecognized subcommand 'sandbox'"
    exe.write_text("#!/bin/sh\n# v2\n", encoding="utf-8"); import os; os.utime(exe, (time.time() + 5, time.time() + 5))
    assert ap.codex_sandbox_probe(str(exe), {}, run=run)["ok"], "an unknown failure (an older codex) never blocks Codex"


def test_codex_unavailable_no_run_clear_notice_and_marked_in_the_menu(spawner, monkeypatch):
    monkeypatch.setenv("GAMEANYTHING_CODEX_SANDBOX", "fail")
    _, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"}); T.user_text("你好")
    D = agentd.Agentd(provider="codex", agent="/bin/false", spawn=spawner, quiet=True); D.tick(); D.tick()
    assert spawner.calls == [], "no Codex run that can only fail"
    assert statuses(T).count(agentd.SANDBOX_FAILED[0]) == 1 and "沙盒" in agentd.SANDBOX_FAILED[0]
    assert agentd.failed(T)["reason"] == "sandbox"
    T.user_text("还是不行吗"); D.tick(); assert spawner.calls == []
    st = models.state(T.root, daemon=("codex", None))
    cx = next(a for a in st["agents"] if a["id"] == "codex"); assert cx["unavailable"] and "沙盒" in cx["unavailable"]
    with pytest.raises(models.ModelError): models.set_choice(T.root, "chat", "codex", "")


def test_codex_default_label_is_its_builtin_default_and_menu_is_stable(tmp_path, monkeypatch):
    h = tmp_path / "ch"; h.mkdir(); monkeypatch.setenv("CODEX_HOME", str(h))
    (h / "models_cache.json").write_text(json.dumps({"models": [{"slug": "gpt-x-weird", "visibility": "list", "priority": 1}]}), encoding="utf-8")
    m1 = models.codex_models()
    (h / "models_cache.json").write_text(json.dumps({"models": [{"slug": "other-session-model", "visibility": "list"}]}), encoding="utf-8")
    m2 = models.codex_models()
    assert [x["id"] for x in m1] == [x["id"] for x in m2], "another Codex session rewriting models_cache.json does not change the menu"
    assert "config.toml" not in m1[0]["hint"] and "内置" in m1[0]["hint"], "--ignore-user-config: the default is Codex's built-in one"


# ---------------------------------------------------------------- a model the CLI or the key refuses (harness check 2026-10-31)
def test_a_refused_model_is_said_once_and_waits_for_another_model(spawner):
    _, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"}); T.user_text("你好")
    clk = Clock(); D = daemon(spawner, clk, model="fable"); D.tick()
    fail_with(T, spawner, '{"type":"result","is_error":true,"result":"There\'s an issue with the selected model (fable). It may not exist or you may not have access to it."}')
    D.tick()
    assert agentd.failed(T)["reason"] == "model"
    assert sum("claude update" in s and "fable" in s for s in statuses(T)) == 1, "she is told once: update the CLI or pick another model"
    T.user_text("在吗"); D.tick(); clk.t += agentd.BACKOFF_SECS["auth"] + 1; T.user_text("还在吗"); D.tick()
    assert len(spawner.calls) == 1, "no retries and no run per message: the same model would be refused again"
    models.set_choice(T.root, "chat", "claude-code", "sonnet")
    T.user_text("换好了"); D.tick()
    assert len(spawner.calls) == 2 and spawner.calls[1]["cmd"][spawner.calls[1]["cmd"].index("--model") + 1] == "sonnet", "another model: a run at once"


def test_model_refusals_of_each_cli_are_model_failures_not_logins(tmp_path):
    cases = {"claude-code": ['{"type":"result","is_error":true,"result":"API Error: 400 {\\"error\\":{\\"message\\":\\"Claude Code 2.1.72 does not support this model; version 2.1.280 or newer is required.\\",\\"details\\":{\\"error_code\\":\\"claude_code_version_too_old\\"}}}"}'],
             "opencode": ['{"type":"error","error":{"name":"APIError","data":{"message":"The request is prohibited due to a violation of provider Terms Of Service.","statusCode":403}}}'],
             "codex": ['{"type":"turn.failed","error":{"message":"The \'gpt-nope-9\' model is not supported when using Codex with a ChatGPT account."}}'],
             "gemini": ['{"type":"result","status":"error","error":{"type":"Error","message":"[API Error: models/gemini-nope-9 is not found for API version v1beta, or is not supported for generateContent.]"}}']}
    for name, lines in cases.items():
        log = tmp_path / f"{name}.log"; log.write_text("\n".join(lines), encoding="utf-8")
        p = ap.provider(name, binary="-")
        assert p.failure(log) == "model" and not p.auth_failed(log), name
    assert "claude update" in agentd.model_notice("claude-code", "opus")[0] and "claude update" not in agentd.model_notice("opencode", "openrouter/x/y")[0]


# ---------------------------------------------------------------- a run going round in circles
def test_a_looping_run_is_stopped_and_she_is_told(spawner):
    _, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"}); T.user_text("你好")
    import subprocess, sys

    class Group(Spawner):                                                       # a real process group, as agentd.popen starts it
        def __call__(self, cmd, cwd, env, log):
            p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            self.calls.append({"cmd": cmd}); self.procs.append(p); return p
    spawner = Group()
    clk = Clock(); D = agentd.Agentd(provider="opencode", agent="/bin/false", spawn=spawner, quiet=True, clock=clk); D.tick()
    lines = []
    for i in range(activity.LOOP_WINDOW):
        cmd = "gameanything chat claim --project ." if i % 2 == 0 else "gameanything chat read --project ."
        lines.append(json.dumps({"type": "tool_use", "part": {"type": "tool", "tool": "bash", "callID": f"c{i}", "state": {"status": "completed", "input": {"command": cmd}}}}))
    with open(run_log(T), "a", encoding="utf-8") as f: f.write("\n".join(lines) + "\n")
    D.tick()                                                                    # the live check sees the loop and stops the run
    spawner.procs[-1].wait(10); D.tick(); clk.t += 1000; D.tick()
    assert len(spawner.calls) == 1, "a loop is not retried"
    r = json.loads(agentd.run_path(T).read_text(encoding="utf-8")); assert r["stopped"] == "loop" and r["failure"] == "loop"
    assert any("原地打转" in s for s in statuses(T)) and agentd.failed(T)["reason"] == "loop"
    spawner.stop_all()


# ---------------------------------------------------------------- the page's status says what is true
def test_online_ends_with_the_run_and_calling_expires(spawner):
    _, T = new_project()
    T.append({"from": "agent", "type": "text", "text": "hi", "source": "terminal"}); T.user_text("你好")
    D = daemon(spawner); D.tick()
    T.seen()                                                                    # the run looked at the chat (claim / read)
    assert T.online()["online"]
    spawner.end(); D.tick()                                                     # the run died after a few seconds without a word
    assert not T.online()["online"], "not 「agent 在线」 for 5 more minutes after a failed 10 s run"
    agentd.heartbeat_path().unlink()                                            # agentd stopped
    assert T.online()["phase"] == "down", "a stale 「正在叫 agent」 does not hide that nobody comes"


def test_shell_status_banner_and_server_down():
    js = (Path(agentd.__file__).parent / "ui" / "static" / "shell.js").read_text(encoding="utf-8")
    away = js[js.index("const away ="):js.index('$("#offline").innerHTML')]
    assert 'AGENT.phase !== "calling"' not in away, "the 后台调度没有运行 banner is not hidden while 「calling」"
    assert "server_down" in js and "连不上 GameAnything 服务" in js, "a failed poll turns 「agent 在线」 off"


def test_chinese_title_gets_a_sensible_ascii_id():
    from gameanything import projects
    a = projects.create("我们的婚礼", "memory"); b = projects.create("夜班护士", "adaptation"); c = projects.create("Our Wedding 2026", "memory")
    assert a["id"].startswith("memory-") and len(a["id"]) == len("memory-") + 6 and a["id"].isascii()
    assert b["id"].startswith("adaptation-") and b["id"] != "adaptation", "not just the kind"
    assert c["id"] == "our-wedding-2026"
    assert projects.title_id("我们的婚礼", "memory") == a["id"], "stable for the same title"
