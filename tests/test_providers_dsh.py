"""DeepSeek Harness (`dsh --profile headless`) as an agentd provider: command lines, sessions and resume, the per-run dsh home and patch
layer (isolation from the operator's ~/.dsh), the key moved out of the env, auth failures, residents vs builders, the hub's per-user
choice, the activity parser. Fake binaries only: nothing calls a model."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import pytest
import yaml

from gameanything import activity, agent_providers as ap, agentd, projects, users
from gameanything.conversation import Thread

SECRET_DS = "sk-" + "0123456789abcdef" * 2
SECRET_OR = "sk-or-v1-" + "0123456789abcdef" * 4


def project():
    e = projects.create("红发会", "feature", game="minecraft"); T = Thread(Path(e["path"]))
    T.append({"from": "agent", "type": "text", "text": "你好", "source": "terminal"})
    return e, T


def opt(cmd, flag):
    return [cmd[i + 1] for i, x in enumerate(cmd) if x == flag]


# the event lines `dsh --profile headless --json` prints (packages/bundle/headless/src/json-stream.ts, 0.2.1-rc.2)
OK_RUN = [{"type": "session", "sessionId": "session-1111", "cwd": "/p"},
          {"type": "status", "phase": "turn_start", "turn": 1}, {"type": "status", "phase": "step_start", "turn": 1, "step": 1},
          {"type": "tool_call", "callId": "c1", "tool": "bash", "input": {"command": "m2w chat say --project . --text hi"}},
          {"type": "tool_result", "callId": "c1", "status": "completed", "result": "ok"},
          {"type": "text", "text": "OK"},
          {"type": "status", "phase": "step_end", "turn": 1, "step": 1,
           "usage": {"inputTokens": 100, "outputTokens": 5, "cacheReadTokens": 40, "reasoningTokens": 2}},
          {"type": "status", "phase": "turn_end", "turn": 1, "reason": {"kind": "completed"}},
          {"type": "final", "sessionId": "session-1111", "reason": {"kind": "completed"}, "text": "OK"}]


def lines(evs): return "".join(json.dumps(e) + "\n" for e in evs)


def test_dsh_command_lines_resume_and_no_budget(tmp_path):
    p = ap.provider("dsh", binary="dsh", model="deepseek-flash")
    new = p.command("go", "SYS", None, False, tmp_path, add_dirs=[tmp_path], env={"GAMEANYTHING_DSH_HOME": str(tmp_path / "h")})
    assert new[:3] == ["dsh", "--profile", "headless"] and opt(new, "--patch") == [str(tmp_path / "h" / "gameanything" / "patch-resident.yml")]
    assert new.index("--patch") < new.index("--json"), "launcher flags before the app's own arguments"
    assert not {"--permission-mode", "--approval-policy", "--add-dir"} & set(new), "0.2.1-rc.x ends the run on an option it does not know"
    assert "--session-id" not in new and new[-1].startswith("<resident-system-prompt>") and "SYS" in new[-1] and new[-1].endswith("go")
    again = p.command("again", "SYS", "session-1111", True, tmp_path, role="builder")
    assert opt(again, "--session-id") == ["session-1111"] and again[-1].startswith("<builder-system-prompt>")
    with pytest.raises(ValueError, match="budget"): p.command("go", "SYS", None, False, tmp_path, budget=1.0)
    with pytest.raises(ValueError): p.command("go", "SYS", None, False, tmp_path, role="boss")
    assert ap.provider("dsh", binary="x").model == ap.DSH_DEFAULT_MODEL and ap.provider("deepseek", binary="x").name == "dsh"
    log = tmp_path / "ds.jsonl"; log.write_text(lines(OK_RUN), encoding="utf-8")
    assert p.session_id(log) == "session-1111" and ap.reply_text("dsh", log.read_text(encoding="utf-8")) == "OK"
    u = ap.usage("dsh", log); assert u["input"] == 100 and u["output"] == 5 and u["cache_read"] == 40 and u["steps"] == 1 and u["cost_usd"] is None
    assert not p.auth_failed(log) and ap.error_text("dsh", log.read_text(encoding="utf-8")) == ""
    # no key: the turn ends in an error, the runner writes `dsh: <code>: <message>` to stderr (the agentd log gets both streams)
    log.write_text(lines([OK_RUN[0], {"type": "final", "sessionId": "session-1111", "text": "",
                                      "reason": {"kind": "error", "error": {"code": "MISSING_CREDENTIAL", "message": "DEEPSEEK_API_KEY is not set"}}}])
                   + "dsh: MISSING_CREDENTIAL: DEEPSEEK_API_KEY is not set\n", encoding="utf-8")
    assert p.auth_failed(log) and ap.error_text("dsh", log.read_text(encoding="utf-8")) == "MISSING_CREDENTIAL: DEEPSEEK_API_KEY is not set"
    # what 0.2.1-rc.2 printed on 2026-10-27 with no key: the reason comes with turn_end, the final event has none
    rc2 = [OK_RUN[0], {"type": "status", "phase": "turn_end", "turn": 1, "reason": {"kind": "error", "error": {
               "message": "llm-deepseek: no API key for provider route \"deepseek-official\"; ... export DEEPSEEK_API_KEY in the launching environment",
               "code": "MISSING_CREDENTIAL"}}}, {"type": "final", "text": ""}]
    log.write_text(lines(rc2) + "dsh: MISSING_CREDENTIAL: llm-deepseek: no API key for provider route\n", encoding="utf-8")
    assert p.auth_failed(log) and ap.error_text("dsh", log.read_text(encoding="utf-8")).startswith("MISSING_CREDENTIAL: llm-deepseek: no API key")
    log.write_text(lines([{"type": "error", "message": "Session session-9 was not found"}]), encoding="utf-8")
    assert ap.error_text("dsh", log.read_text(encoding="utf-8")) == "Session session-9 was not found" and not p.auth_failed(log)


def test_dsh_launch_isolates_the_home_and_moves_the_key_out_of_the_env(tmp_path):
    home = tmp_path / "dshhome"; root = tmp_path / "proj"; root.mkdir()
    p = ap.provider("dsh", binary="dsh", model="deepseek-flash")
    env = {"PATH": "/bin", "GAMEANYTHING_DSH_HOME": str(home), "DEEPSEEK_API_KEY": SECRET_DS, "GAMEANYTHING_KEYS_FILE": "/k"}
    cmd, run = p.launch("go", "THE RULES", None, False, root, env=env)
    assert SECRET_DS not in json.dumps(run) and "DEEPSEEK_API_KEY" not in run, "no key in the agent's environment"
    kf = home / ".env"; assert kf.read_text(encoding="utf-8") == f"DEEPSEEK_API_KEY={SECRET_DS}\n"
    if os.name != "nt": assert kf.stat().st_mode & 0o077 == 0
    assert run["DSH_HOME"] == str(home) and run["DSH_AGENTS_HOME"] == str(home / "agents") and run["PWD"] == str(root)
    assert run["DSH_TELEMETRY_DISABLED"] == "1" and run["DSH_TELEMETRY_MODE"] == "DISABLED", "no session upload to DeepSeek's collector (D3)"
    assert run["DSH_PERMISSION_MODE"] == "danger-full-access", "the CLI itself does not run inside dsh's workspace-write sandbox (its uv cache)"
    assert "THE RULES" in cmd[-1], "the system prompt is the first block of the task (no prompt template: its {{ }} would be variables)"
    patch = yaml.safe_load(Path(opt(cmd, "--patch")[0]).read_text(encoding="utf-8"))
    rows = {r["id"]: r for r in patch}
    assert rows["agent-default-model"]["config"] == {"provider": "deepseek-official", "model": "deepseek-flash"}
    assert rows["agent-instructions"]["config"]["instructionFileCandidates"] == ["M2W-NO-CONTEXT-FILE.md"], "no AGENTS.md / CLAUDE.md of a parent folder"
    for k in ("skill-filesystem", "tool-skill", "tool-subagent", "mcp-resources"): assert rows[k]["disabled"] is True
    # the key is gone from the next run's env: the key file goes too
    p.launch("go", "THE RULES", None, False, root, env={"PATH": "/bin", "GAMEANYTHING_DSH_HOME": str(home)}); assert not kf.exists()
    # without a hub user's home: <data dir>/agent-homes/dsh, never the operator's ~/.dsh
    cmd, run = p.launch("go", "R", None, False, root, env={"PATH": "/bin"})
    assert run["DSH_HOME"] == str(projects.data_dir() / "agent-homes" / "dsh") and Path(run["DSH_HOME"]) != Path.home() / ".dsh"


def test_dsh_routes_an_openrouter_model_through_pi_ai(tmp_path):
    assert ap.dsh_route(None) == ("deepseek-official", "deepseek-v4-pro", "DEEPSEEK_API_KEY")
    assert ap.dsh_route("deepseek/deepseek-flash") == ("deepseek-official", "deepseek-flash", "DEEPSEEK_API_KEY")
    assert ap.dsh_route("openrouter/deepseek/deepseek-v4-pro") == ("openrouter", "deepseek/deepseek-v4-pro", "OPENROUTER_API_KEY")
    home = tmp_path / "h"; root = tmp_path / "p"; root.mkdir()
    p = ap.provider("dsh", binary="dsh", model="openrouter/deepseek/deepseek-v4-pro")
    env = ap.agent_env({"PATH": "/bin", "GAMEANYTHING_DSH_HOME": str(home), "OPENROUTER_API_KEY": SECRET_OR, "MESHY_API_KEY": "paid"}, p)
    assert env["OPENROUTER_API_KEY"] == SECRET_OR and "MESHY_API_KEY" not in env, "her model's key stays for the launch, paid keys go"
    cmd, run = p.launch("go", "R", None, False, root, env=env)
    assert SECRET_OR not in json.dumps(run) and (home / ".env").read_text(encoding="utf-8") == f"OPENROUTER_API_KEY={SECRET_OR}\n"
    rows = {r.get("id"): r for r in yaml.safe_load(Path(opt(cmd, "--patch")[0]).read_text(encoding="utf-8"))}
    assert rows["agent-default-model"]["config"] == {"provider": "openrouter", "model": "deepseek/deepseek-v4-pro"}
    assert rows["llm-pi-ai"]["config"] == {"providers": {"openrouter": {"apiKeyEnv": "OPENROUTER_API_KEY"}}}, "the key by reference only"
    # no DeepSeek key: web_search asks perplexity/sonar on OpenRouter with the same key, through GameAnything's own search plugin
    assert "tool-web" not in rows and rows["web"]["config"] == {"searchProvider": "openai-compatible", "fetchProvider": "http"}
    ins = next(r for r in yaml.safe_load(Path(opt(cmd, "--patch")[0]).read_text(encoding="utf-8")) if "insert" in r)["insert"]
    assert [r["id"] for r in ins] == ["web-search-openai-compatible"] and ins[0]["config"] == {
        "baseURL": "https://openrouter.ai/api/v1", "apiKeyEnv": "OPENROUTER_API_KEY", "model": "perplexity/sonar"}, "the key by reference only"
    plugin = Path(url2pathname(urlparse(ins[0]["name"]).path))
    assert ins[0]["name"].startswith("file:///") and plugin.is_file() and plugin.name == "index.js", "loaded from the install by file URL"
    # another search model: OpenRouter's web search server tool does the searching
    cmd, run = p.launch("go", "R", None, False, root, env={**env, "GAMEANYTHING_DSH_SEARCH_MODEL": "deepseek/deepseek-v4-flash"})
    ins = next(r for r in yaml.safe_load(Path(opt(cmd, "--patch")[0]).read_text(encoding="utf-8")) if "insert" in r)["insert"]
    assert ins[0]["config"]["model"] == "deepseek/deepseek-v4-flash" and ins[0]["config"]["body"] == {"tools": [{"type": "openrouter:web_search"}]}
    # a provider with no known search model: no web_search tool
    assert {"id": "tool-web", "config": {"search": False}} in ap.dsh_patch("groq/llama-4", deepseek_key=False)
    # with a DeepSeek key as well: DeepSeek's own web_search (dsh's default rows), both keys go to the key file
    cmd, run = p.launch("go", "R", None, False, root, env={"GAMEANYTHING_DSH_HOME": str(home), "OPENROUTER_API_KEY": SECRET_OR, "DEEPSEEK_API_KEY": SECRET_DS})
    patch = yaml.safe_load(Path(opt(cmd, "--patch")[0]).read_text(encoding="utf-8")); rows = {r.get("id"): r for r in patch}
    assert "tool-web" not in rows and "web" not in rows and not any("insert" in r for r in patch)
    assert set(l.split("=")[0] for l in (home / ".env").read_text(encoding="utf-8").splitlines()) == {"OPENROUTER_API_KEY", "DEEPSEEK_API_KEY"}
    log = tmp_path / "or.log"   # what pi-ai's openrouter route reports for a wrong key
    log.write_text(lines([OK_RUN[0], {"type": "status", "phase": "turn_end", "reason": {"kind": "error", "error": {"code": "INVALID_CREDENTIAL",
                                                                                                                       "message": "401 User not found."}}}]), encoding="utf-8")
    assert p.auth_failed(log)
    from gameanything.estimate import estimate
    assert estimate("small", "dsh", "openrouter/deepseek/deepseek-v4-pro")["estimate"]["model"] == "openrouter/deepseek/deepseek-v4-pro"


def test_hub_user_on_dsh_with_an_openrouter_key(hubusers, monkeypatch):
    users.set_agent("carol", "dsh")
    with pytest.raises(users.HubError, match="OpenRouter"): users.connect_dsh("carol", SECRET_DS, "openrouter/deepseek/deepseek-v4-pro")
    st = users.connect_dsh("carol", SECRET_OR, "openrouter/deepseek/deepseek-v4-pro")
    assert st["connected"] and st["key_name"] == "OPENROUTER_API_KEY" and st["model"] == "openrouter/deepseek/deepseek-v4-pro"
    u = users.get_user("carol"); assert f"OPENROUTER_API_KEY={SECRET_OR}" in Path(u["env_file"]).read_text(encoding="utf-8")
    users.set_model("carol", "dsh", "deepseek-flash")
    assert not users.dsh_status(users.get_user("carol"))["connected"], "a DeepSeek model needs the DeepSeek key"
    users.set_model("carol", "dsh", "openrouter/deepseek/deepseek-v4-pro")
    assert not users.disconnect_dsh("carol")["connected"] and "OPENROUTER_API_KEY" not in Path(u["env_file"]).read_text(encoding="utf-8")


def test_dsh_env_isolation_from_the_operator_and_paid_keys():
    env = {"PATH": "/bin", "DEEPSEEK_API_KEY": "ds", "OPENROUTER_API_KEY": "or", "MESHY_API_KEY": "paid", "DSH_HOME": "/op/.dsh",
           "DSH_PERMISSION_MODE": "danger-full-access", "GAMEANYTHING_DSH_HOME": "/m2w"}
    p = ap.provider("dsh", binary="-")
    e = ap.agent_env(p.clean_env(env), p)
    assert e == {"PATH": "/bin", "DEEPSEEK_API_KEY": "ds", "GAMEANYTHING_DSH_HOME": "/m2w", "GAMEANYTHING_GEN_OFF": "1",
                 "M2W_GEN_OFF": "1"}, \
        "the operator's DSH_* (home, a danger-full-access mode) and every other key stay out"


def test_dsh_activity_lines():
    acts = [a for e in OK_RUN for a in activity.translate("dsh", e, "/p")]
    kinds = [a["t"] for a in acts]
    assert "tool" in kinds and "tool_end" in kinds and "say" in kinds and kinds[-1] == "end" and acts[-1]["ok"] is True
    (err,) = activity.translate("dsh", {"type": "status", "phase": "turn_end", "reason": {"kind": "error", "error": {"code": "INVALID_CREDENTIAL", "message": "bad key"}}})
    assert err["t"] == "auth" and activity.translate("dsh", {"type": "final", "text": ""}) == [{"t": "end", "ok": None}]


# ---------------------------------------------------------------- agentd end to end with a fake dsh
FAKE = r'''
import json, os, sys
mode = os.environ.get("FAKE_MODE", "ok"); rec = os.environ["FAKE_REC"]
with open(rec, "a", encoding="utf-8") as f: f.write(json.dumps({"argv": sys.argv[1:], "env": dict(os.environ), "cwd": os.getcwd()}) + "\n")
sid = sys.argv[sys.argv.index("--session-id") + 1] if "--session-id" in sys.argv else "session-fake1"
print(json.dumps({"type": "session", "sessionId": sid, "cwd": os.getcwd()}))
if mode == "auth":
    print(json.dumps({"type": "final", "sessionId": sid, "text": "", "reason": {"kind": "error", "error": {"code": "INVALID_CREDENTIAL", "message": "Authentication Fails"}}}))
    sys.stderr.write("dsh: INVALID_CREDENTIAL: Authentication Fails\n"); sys.exit(1)
print(json.dumps({"type": "final", "sessionId": sid, "text": "OK", "reason": {"kind": "completed"}}))
'''


@pytest.fixture
def fake(tmp_path, monkeypatch):
    f = tmp_path / "fake_dsh.py"; f.write_text(FAKE, encoding="utf-8")
    rec = tmp_path / "rec.jsonl"; monkeypatch.setenv("FAKE_REC", str(rec))
    procs = []

    def spawn(cmd, cwd, env, log):
        p = agentd.popen([sys.executable, str(f), *cmd[1:]], cwd, env, log); procs.append(p); return p

    def calls(): return [json.loads(l) for l in rec.read_text(encoding="utf-8").splitlines()] if rec.exists() else []
    yield {"spawn": spawn, "calls": calls, "procs": procs}
    for p in procs:
        if p.poll() is None: p.kill(); p.wait(10)


def run_once(D, fake):
    D.tick(); p = fake["procs"][-1]; p.wait(30)
    return p


def test_agentd_runs_resumes_and_stops_on_auth_failure(fake, monkeypatch, tmp_path):
    monkeypatch.setenv("MESHY_API_KEY", "paid-meshy-secret"); monkeypatch.setenv("DEEPSEEK_API_KEY", SECRET_DS)
    (tmp_path / "req").mkdir()
    _, T = project(); T.user_text("你好")
    D = agentd.Agentd(provider="dsh", agent="fake-bin", spawn=fake["spawn"], quiet=True, requests=tmp_path / "req")
    run_once(D, fake)
    T.append({"from": "agent", "type": "text", "text": "收到", "session": f"agentd:{T.root.name}"}); D.tick()
    s = json.loads((T.dir / ".agent_session").read_text(encoding="utf-8"))
    assert s["provider"] == "dsh" and s["id"] == "session-fake1" and s["runs"] == 1
    c = fake["calls"]()[-1]
    assert "paid-meshy-secret" not in json.dumps(c["env"]) and SECRET_DS not in json.dumps(c["env"]) and c["env"]["GAMEANYTHING_GEN_OFF"] == "1"
    assert Path(c["cwd"]).resolve() == T.root.resolve(), "dsh takes the invocation directory as the workspace root"
    assert c["env"]["DSH_PERMISSION_MODE"] == "danger-full-access" and "--session-id" not in c["argv"]
    assert (Path(c["env"]["DSH_HOME"]) / ".env").read_text(encoding="utf-8").strip() == f"DEEPSEEK_API_KEY={SECRET_DS}"
    # the next words resume the same session
    T.user_text("再来"); run_once(D, fake)
    assert opt(fake["calls"]()[-1]["argv"], "--session-id") == ["session-fake1"]
    T.append({"from": "agent", "type": "text", "text": "好", "session": f"agentd:{T.root.name}"}); D.tick()
    # a key problem: one plain message, no retries
    monkeypatch.setenv("FAKE_MODE", "auth"); T.user_text("还在吗"); run_once(D, fake); n = len(fake["calls"]())
    D.tick()
    msgs = [e.get("text", "") for e in T.events() if e.get("type") == "status"]
    assert any("DeepSeek" in m for m in msgs), msgs
    assert json.loads((T.dir / ".agentd_failed").read_text(encoding="utf-8"))["reason"] == "auth"
    D.clock = lambda: time.time() + 3600; D.tick(); assert len(fake["calls"]()) == n, "no retry after an auth failure"


def test_builder_runs_with_the_builder_patch(monkeypatch, tmp_path):
    from tests.test_builds import FakeLab, Spawner, go, request
    monkeypatch.setenv("GAMEANYTHING_PARENT_REQUESTS", str(tmp_path / "req")); monkeypatch.setenv("M2W_LAB_USER", "tester")
    monkeypatch.setenv("DEEPSEEK_API_KEY", SECRET_DS)
    e = projects.create("建一座桥", "feature", game="minecraft", build_mode="lab"); T = Thread(Path(e["path"]))
    T.append({"from": "agent", "type": "text", "text": "你好", "source": "terminal"})
    sp = Spawner()
    try:
        go(T); D = agentd.Agentd(provider="dsh", agent="dsh", spawn=sp, quiet=True, requests=tmp_path / "req", lab=FakeLab())
        request(T); D.tick()
        (b,) = sp.builders(); env = b["env"]
        assert env["GAMEANYTHING_ROLE"] == "builder" and env["GAMEANYTHING_LEASE"] and env["GAMEANYTHING_GEN_OFF"] == "1" and SECRET_DS not in json.dumps(env)
        assert Path(opt(b["cmd"], "--patch")[0]).name == "patch-builder.yml" and b["cmd"][-1].startswith("<builder-system-prompt>")
        assert env["DSH_PERMISSION_MODE"] == "danger-full-access" and env["DSH_TELEMETRY_DISABLED"] == "1"
    finally: sp.stop_all()


# ---------------------------------------------------------------- the hub: her own choice, key and model
@pytest.fixture
def hubusers(monkeypatch):
    home = Path.home()
    users.add_user("carol", "carol-pass-89", False, "Carol", home / "carol" / "m2w", home / "carol" / ".claude-m2w")
    users.add_user("alice", "alice-pass-123", True, "Alice", home / "alice" / "m2w", home / "alice" / ".claude-m2w")
    d = home / "alice" / ".claude-m2w"; d.mkdir(parents=True); (d / ".credentials.json").write_text("{}", encoding="utf-8")


def test_hub_user_on_dsh_gets_her_own_home_key_and_model(hubusers, monkeypatch):
    from tests.test_builds import Spawner
    monkeypatch.setenv("DEEPSEEK_API_KEY", "supervisor-ds-xyz"); monkeypatch.setenv("ANTHROPIC_API_KEY", "supervisor-ant-xyz")
    pc = projects.create("C", "feature", owner="carol"); T = Thread(Path(pc["path"])); T.user_text("hi")
    users.set_agent("carol", "deepseek")
    assert users.get_user("carol")["agent"] == "dsh" and "no DEEPSEEK_API_KEY" in users.blocked(pc["path"], "claude-code")
    for bad, why in (("short", "看起来不是"), ("sk-ant-api03-" + "x" * 30, "DeepSeek"), ("sk-or-v1-" + "x" * 30, "DeepSeek"), ("AIza" + "x" * 30, "DeepSeek")):
        with pytest.raises(users.HubError, match=why): users.connect_dsh("carol", bad)
    st = users.connect_dsh("carol", SECRET_DS); assert st["connected"] and st["kind"] == "api_key" and st["last4"] == SECRET_DS[-4:]
    with pytest.raises(users.HubError, match="模型名不对"): users.set_model("carol", "dsh", "deepseek flash")
    users.set_model("carol", "dsh", "deepseek-flash")
    u = users.get_user("carol"); assert f"DEEPSEEK_API_KEY={SECRET_DS}" in Path(u["env_file"]).read_text(encoding="utf-8")
    assert users.blocked(pc["path"]) is None and users.model_for(pc["path"], "dsh") == "deepseek-flash"
    sp = Spawner()
    try:
        agentd.Agentd(claude="/bin/false", spawn=sp, quiet=True).tick()        # the daemon is on Claude Code; carol's choice wins
        c = sp.calls[-1]; env = c["env"]
        assert c["cmd"][1:3] == ["--profile", "headless"] and env["DSH_HOME"] == str(users.dsh_home(u)) and env["GAMEANYTHING_USER"] == "carol"
        assert "supervisor" not in json.dumps(env) and SECRET_DS not in json.dumps(env)
        assert (users.dsh_home(u) / ".env").read_text(encoding="utf-8").strip() == f"DEEPSEEK_API_KEY={SECRET_DS}"
        rows = {r["id"]: r for r in yaml.safe_load(Path(opt(c["cmd"], "--patch")[0]).read_text(encoding="utf-8"))}
        assert rows["agent-default-model"]["config"]["model"] == "deepseek-flash"
        run = json.loads(agentd.run_path(T).read_text(encoding="utf-8")); assert run["agent_provider"] == "dsh"
    finally: sp.stop_all()
    a = users.agent_status(users.get_user("carol"))
    assert a["agent"] == "dsh" and a["connected"] and a["dsh"]["model"] == "deepseek-flash" and SECRET_DS not in json.dumps(a)
    assert not users.disconnect_dsh("carol")["connected"]


def test_hub_connection_test_runs_dsh_with_her_env(hubusers, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "supervisor-ds-xyz")
    users.set_agent("carol", "dsh"); users.connect_dsh("carol", SECRET_DS)
    calls = []
    def run(cmd, **kw): calls.append({"cmd": cmd, **kw}); return subprocess.CompletedProcess(cmd, 0, lines(OK_RUN), "")
    r = users.try_claude("carol", run=run); assert r == {"ok": True, "text": "OK"}, r
    env = calls[-1]["env"]; assert "supervisor" not in json.dumps(env) and SECRET_DS not in json.dumps(env) and env["GAMEANYTHING_GEN_OFF"] == "1"
    assert env["DSH_HOME"] == str(users.dsh_home(users.get_user("carol")))
    bad = lines([{"type": "final", "text": "", "reason": {"kind": "error", "error": {"code": "INVALID_CREDENTIAL", "message": f"key {SECRET_DS} rejected"}}}])
    r = users.try_claude("carol", run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, bad, ""))
    assert not r["ok"] and SECRET_DS not in r["text"] and "***" in r["text"]


def test_estimate_for_dsh_has_time_but_no_unchecked_price():
    from gameanything.estimate import estimate
    r = estimate("small", "dsh")
    assert r["estimate"]["model"] == "deepseek/deepseek-v4-pro" and r["estimate"]["account"] == "api" and r["estimate"]["cost_usd"] is None
    assert estimate("small", "dsh", "deepseek-flash")["estimate"]["model"] == "deepseek/deepseek-flash"


# the search plugin itself (plugins/dsh-web-search-openai-compatible, loaded by dsh from the install), run by node against a local
# OpenAI-compatible stand-in. Its loading inside a real dsh 0.2.1-rc.2 run was checked by hand (docs/agent-providers.md).
PLUGIN = Path(__file__).resolve().parent.parent / "plugins" / "dsh-web-search-openai-compatible" / "index.js"
NODE_SEARCH = """
import { apply } from %s;
const [config, launched] = JSON.parse(process.argv[1]);
let provider;
const ctx = { web: { registerSearchProvider: (p) => { provider = p; } },
              get: (n) => n === "launchEnvironment" ? { get: (k) => launched[k] === undefined ? undefined : { value: launched[k] } } : undefined };
apply(ctx, config);
try { console.log(JSON.stringify({ id: provider.id, available: provider.available(), result: await provider.search({ query: "stardew 1.6" }) })); }
catch (e) { console.log(JSON.stringify({ error: e.message, code: e.code })); }
"""


@pytest.mark.skipif(not __import__("shutil").which("node"), reason="node is not installed")
def test_dsh_search_plugin_reads_every_source_shape_and_keeps_the_key_safe():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    seen, answers = [], []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            seen.append({"path": self.path, "auth": self.headers.get("authorization"), "x": self.headers.get("x-title"),
                         "body": json.loads(self.rfile.read(int(self.headers["content-length"])))})
            status, body = answers.pop(0)
            out = json.dumps(body).encode(); self.send_response(status)
            if status == 302: self.send_header("location", "http://127.0.0.1:1/elsewhere")
            self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(out))); self.end_headers(); self.wfile.write(out)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/api/v1/"

    def search(answer, config=None, launched=None):
        answers.append(answer)
        cfg = {"baseURL": base, "model": "perplexity/sonar", "apiKeyEnv": "OPENROUTER_API_KEY", **(config or {})}
        r = subprocess.run(["node", "--input-type=module", "-e", NODE_SEARCH % json.dumps(PLUGIN.as_uri()),
                            json.dumps([cfg, {"OPENROUTER_API_KEY": SECRET_OR} if launched is None else launched])],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    def done(**kw): return {"choices": [{"index": 0, "message": {"role": "assistant", "content": "The answer.", **kw.pop("msg", {})}}], **kw}

    try:
        a, b = "https://example.org/a", "https://example.org/b"
        # OpenRouter (every model, Perplexity's included): message.annotations url_citation; the key from $DSH_HOME/.env (launch environment)
        r = search((200, done(msg={"annotations": [{"type": "url_citation", "url_citation": {"url": a, "title": "A", "content": "snip"}},
                                                   {"type": "url_citation", "url_citation": {"url": a, "title": "A again"}}]})))
        assert r["id"] == "openai-compatible" and r["available"] and r["result"] == {
            "content": "The answer.", "sources": [{"url": a, "title": "A", "snippet": "snip"}], "truncated": False}
        q = seen[-1]; assert q["path"] == "/api/v1/chat/completions" and q["auth"] == f"Bearer {SECRET_OR}"
        assert q["body"]["model"] == "perplexity/sonar" and q["body"]["stream"] is False and "stardew 1.6" in q["body"]["messages"][-1]["content"]
        # Perplexity's search_results, GLM's web_search, plain citations
        r = search((200, done(search_results=[{"url": a, "title": "A", "snippet": "s", "date": "2026-10-01"}], citations=[a, b, "not a url"])))
        assert r["result"]["sources"] == [{"url": a, "title": "A", "snippet": "s", "publishedAt": "2026-10-01"}, {"url": b}]
        r = search((200, done(web_search=[{"link": b, "title": "B", "content": "c", "publish_date": "2026-09-30", "refer": "ref_1"}])))
        assert r["result"]["sources"] == [{"url": b, "title": "B", "snippet": "c", "publishedAt": "2026-09-30"}]
        # extra request fields (OpenRouter's server tool, Qwen's enable_search) and headers; they never replace model or messages
        r = search((200, done()), {"body": {"tools": [{"type": "openrouter:web_search"}], "model": "x", "messages": []}, "headers": {"X-Title": "m2w"}})
        q = seen[-1]; assert q["body"]["tools"] == [{"type": "openrouter:web_search"}] and q["body"]["model"] == "perplexity/sonar"
        assert len(q["body"]["messages"]) == 1 and q["x"] == "m2w" and r["result"] == {"content": "The answer.", "sources": [], "truncated": False}
        # a local server without a key: no Authorization header at all
        search((200, done()), {"apiKeyEnv": None}); assert seen[-1]["auth"] is None
        # errors: the endpoint's own message; nothing back; a redirect is refused (the key never follows it); a missing key
        r = search((401, {"error": {"message": "No auth credentials found", "code": 401}}))
        assert "HTTP 401: No auth credentials found" in r["error"] and r["code"] == "WEB_PROVIDER_ERROR"
        assert "neither an answer nor sources" in search((200, {"choices": [{"message": {"content": ""}}]}))["error"]
        n = len(seen); r = search((302, {})); assert "failed" in r["error"] and len(seen) == n + 1, "one request, the redirect not followed"
        r = search((200, done()), launched={}); answers.clear()
        assert r["code"] == "WEB_PROVIDER_CREDENTIAL_MISSING" and "OPENROUTER_API_KEY" in r["error"] and len(seen) == n + 1, "no request without its key"
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- GameAnything: per-project chips, model refusals, notices, isolation
def test_dsh_in_the_projects_chat_and_build_chips(hubusers):
    from tests.test_builds import Spawner
    from gameanything import models
    root = Path(projects.create("C", "feature", owner="carol")["path"])
    assert "dsh" not in [g["id"] for g in models.state(root)["agents"]], "offered only once she can run it"
    users.connect_dsh("carol", SECRET_OR, "openrouter/deepseek/deepseek-v4.1-flash")
    g = next(g for g in models.state(root)["agents"] if g["id"] == "dsh")
    assert g["name"] == "DeepSeek Harness" and g["free"] and [m["id"] for m in g["models"]] == ["openrouter/deepseek/deepseek-v4.1-flash"]
    assert g["placeholder"] == "openrouter/deepseek/deepseek-v4.1-flash" and g["models"][0]["hint"] == models.HINT_MINE
    with pytest.raises(models.ModelError, match="DeepSeek 的 key（DEEPSEEK_API_KEY）"):
        models.set_choice(root, "chat", "dsh", "deepseek-flash")              # DeepSeek's own API needs a DeepSeek key she does not have
    with pytest.raises(models.ModelError, match="模型名不对"): models.set_choice(root, "chat", "dsh", "deepseek flash")
    e = models.set_choice(root, "chat", "deepseek-harness", "openrouter/deepseek/deepseek-v4-pro")
    assert e == {"agent": "dsh", "model": "openrouter/deepseek/deepseek-v4-pro", "source": "project"}
    assert models.label("dsh", "") == "DeepSeek Harness · deepseek-v4-pro" and models.check("dsh", "", users.get_user("carol")) == ""
    assert models.runner_choice({"harness": "DeepSeek Harness", "model": "deepseek-flash"}) == {"agent": "dsh", "model": "deepseek-flash"}
    Thread(root).user_text("hi", author="carol"); sp = Spawner()
    try:
        agentd.Agentd(claude="/bin/false", spawn=sp, quiet=True).tick()
        c = sp.calls[-1]; rows = {r.get("id"): r for r in yaml.safe_load(Path(opt(c["cmd"], "--patch")[0]).read_text(encoding="utf-8"))}
        assert c["cmd"][1:3] == ["--profile", "headless"] and SECRET_OR not in json.dumps(c["env"]), "the project's choice runs, her key stays out"
        assert rows["agent-default-model"]["config"] == {"provider": "openrouter", "model": "deepseek/deepseek-v4-pro"}
        assert rows["web"]["config"]["searchProvider"] == "openai-compatible"
    finally: sp.stop_all()


def test_dsh_model_refused_and_key_notices(tmp_path):
    p = ap.provider("dsh", binary="dsh", model="openrouter/deepseek/no-such-model")
    log = tmp_path / "x.log"
    log.write_text(lines([OK_RUN[0], {"type": "status", "phase": "turn_end", "reason": {"kind": "error", "error": {
        "message": "400 deepseek/no-such-model is not a valid model ID"}}}]), encoding="utf-8")
    assert p.failure(log) == "model" and not p.auth_failed(log), "a wrong model name: one message and a backoff, not a retry"
    log.write_text(lines([OK_RUN[0], {"type": "error", "message": "Model Not Exist"}]), encoding="utf-8"); assert p.failure(log) == "model"
    log.write_text(lines([OK_RUN[0], {"type": "error", "message": "402 Insufficient credits"}]), encoding="utf-8")
    assert p.failure(log) == "auth" and p.out_of_credit(log)
    hub, single = agentd.auth_notice("dsh", hub=True), agentd.auth_notice("dsh", hub=False)
    assert "「我的 agent」" in hub[0] and "OPENROUTER_API_KEY" in single[0] and "DeepSeek Harness" in single[1]


@pytest.mark.skipif(os.name == "nt", reason="agent isolation needs POSIX accounts; on Windows the switch stays off (docs/agent-isolation.md)")
def test_isolation_hands_the_dsh_home_to_the_account(tmp_path, monkeypatch):
    from gameanything import isolation
    monkeypatch.setenv("GAMEANYTHING_AGENT_ROOT", str(tmp_path / "agents"))
    monkeypatch.setattr(isolation, "ensure_project", lambda root, account=None: [])
    monkeypatch.setattr(isolation, "ids", lambda account: (os.getuid(), os.getgid()))
    monkeypatch.setattr(isolation, "group_gid", lambda name=None: None)
    root = tmp_path / "proj"; root.mkdir()
    env, run_as = isolation.run_env(root, {"PATH": "/bin", "GAMEANYTHING_DSH_HOME": "/srv/service-owned/dsh"}, "r1", account="ga-carol")
    home = Path(run_as["home"])
    assert env["GAMEANYTHING_DSH_HOME"] == str(home / "dsh-home") and (home / "dsh-home").is_dir(), "the account's own dsh home"
    cmd, run = ap.provider("dsh", binary="dsh").launch("go", "R", None, False, root, env={**env, "DEEPSEEK_API_KEY": SECRET_DS})
    assert run["DSH_HOME"] == str(home / "dsh-home") and (home / "dsh-home" / ".env").is_file()
    isolation.after_launch(run, run_as)                     # chowns what launch wrote (here: to ourselves, which is a no-op)
