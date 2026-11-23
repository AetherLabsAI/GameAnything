"""OpenCode and Gemini CLI as agentd providers: command lines, sessions and resume, the per-run agent home (isolation from the operator's
own config), the paid-key guard, auth failures, residents vs builders, the hub's per-user choice. Fake binaries only: nothing calls a model."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from gameanything import agent_providers as ap, agentd, keys, projects, users
from gameanything.conversation import Thread

SECRET_OR = "sk-or-v1-" + "0123456789abcdef" * 4
SECRET_GEM = "AIza" + "SyFakeFakeFakeFakeFakeFakeFake1234"


def project():
    e = projects.create("红发会", "feature", game="minecraft"); T = Thread(Path(e["path"]))
    T.append({"from": "agent", "type": "text", "text": "你好", "source": "terminal"})
    return e, T


def opt(cmd, flag):
    return [cmd[i + 1] for i, x in enumerate(cmd) if x == flag]


# ---------------------------------------------------------------- OpenCode
def test_opencode_command_lines_resume_and_no_budget(tmp_path):
    p = ap.provider("opencode", binary="opencode", model="openrouter/moonshotai/kimi-k2.6")
    new = p.command("go", "SYS", None, False, tmp_path)
    assert new[:4] == ["opencode", "run", "--format", "json"] and opt(new, "--model") == ["openrouter/moonshotai/kimi-k2.6"]
    assert "--session" not in new and new[-1] == "go" and "SYS" not in new, "the system prompt goes into an instructions file, not argv"
    assert opt(new, "--dir") == [str(tmp_path)], "opencode would take the daemon's $PWD as the project"
    again = p.command("again", "SYS", "ses_abc", True, tmp_path)
    assert opt(again, "--session") == ["ses_abc"] and again[-1] == "again"
    with pytest.raises(ValueError, match="budget"): p.command("go", "SYS", None, False, tmp_path, budget=1.0)
    with pytest.raises(ValueError): p.command("go", "SYS", None, False, tmp_path, role="boss")
    assert ap.provider("opencode", binary="x").model == ap.OPENCODE_DEFAULT_MODEL
    log = tmp_path / "oc.jsonl"
    log.write_text('{"type":"step_start","sessionID":"ses_123","part":{}}\n{"type":"text","sessionID":"ses_123","part":{"text":"OK"}}\n'
                   '{"type":"step_finish","sessionID":"ses_123","part":{"cost":0.25,"tokens":{"input":100,"output":5,"reasoning":2,"cache":{"read":40}}}}\n',
                   encoding="utf-8")
    assert p.session_id(log) == "ses_123" and ap.reply_text("opencode", log.read_text(encoding="utf-8")) == "OK"
    u = ap.usage("opencode", log); assert u["cost_usd"] == 0.25 and u["input"] == 100 and u["output"] == 7 and u["cache_read"] == 40
    assert not p.auth_failed(log)
    # the event `opencode run` printed on 2026-10-26 for a wrong OpenRouter key
    log.write_text('{"type":"error","sessionID":"ses_1","error":{"name":"APIError","data":{"message":"User not found.","statusCode":401,'
                   '"isRetryable":false}}}\n', encoding="utf-8")
    assert p.auth_failed(log) and ap.error_text("opencode", log.read_text(encoding="utf-8")) == "User not found."


def test_opencode_launch_isolates_config_and_moves_the_key_out_of_the_env(tmp_path, monkeypatch):
    home = tmp_path / "ochome"; req = tmp_path / "req"; req.mkdir(); root = tmp_path / "proj"; root.mkdir()
    p = ap.provider("opencode", binary="opencode", model="openrouter/z-ai/glm-5.3")
    env = {"PATH": "/bin", "GAMEANYTHING_OPENCODE_HOME": str(home), "OPENROUTER_API_KEY": SECRET_OR, "XDG_CONFIG_HOME": "/op/cfg",
           "OPENCODE_CONFIG": "/op/opencode.json", "OPENCODE_PERMISSION": '{"*":"allow"}', "GAMEANYTHING_KEYS_FILE": "/k"}
    cmd, run = p.launch("go", "THE RULES", None, False, root, add_dirs=[req], env=env)
    assert cmd[1] == "run" and SECRET_OR not in json.dumps(run) and "OPENROUTER_API_KEY" not in run, "no key in the agent's environment"
    assert run["PWD"] == str(root)
    kf = home / "m2w" / "key-openrouter"; assert kf.read_text(encoding="utf-8") == SECRET_OR
    if os.name != "nt": assert kf.stat().st_mode & 0o077 == 0
    assert run["XDG_CONFIG_HOME"] == str(home / "config") and run["XDG_DATA_HOME"] == str(home / "data") and run["XDG_STATE_HOME"] == str(home / "state")
    assert run["GAMEANYTHING_SHELL_XDG_CONFIG_HOME"] == "/op/cfg", "the shell gets the operator's XDG folders back (the plugin)"
    assert "OPENCODE_CONFIG" not in run and "OPENCODE_PERMISSION" not in run
    for k in ("OPENCODE_DISABLE_PROJECT_CONFIG", "OPENCODE_DISABLE_CLAUDE_CODE", "OPENCODE_DISABLE_EXTERNAL_SKILLS", "OPENCODE_DISABLE_AUTOUPDATE"):
        assert run[k] == "1"
    cfg = json.loads(run["OPENCODE_CONFIG_CONTENT"])
    assert cfg["model"] == cfg["small_model"] == "openrouter/z-ai/glm-5.3" and cfg["mcp"] == {} and cfg["autoupdate"] is False
    assert cfg["provider"]["openrouter"]["options"]["apiKey"] == "{file:" + kf.as_posix() + "}"
    (sysf,) = cfg["instructions"]; assert Path(sysf).read_text(encoding="utf-8") == "THE RULES"
    perm = cfg["permission"]
    assert perm["*"] == "deny" and perm["task"] == "deny" and perm["skill"] == "deny" and perm["question"] == "deny"
    vals = lambda d: [x for v in d.values() for x in (vals(v) if isinstance(v, dict) else [v])]
    assert "ask" not in vals(perm), "`opencode run` has nobody to ask"
    assert perm["bash"]["*"] == "allow" and perm["bash"]["*docker run*"] == "deny" and perm["bash"]["*python* *gen_*.py*"] == "deny"
    assert perm["bash"]["*launch_rt/*"] == "deny" and perm["bash"]["*pkill*"] == "deny"
    ext = perm["external_directory"]; assert ext["*"] == "deny" and ext[req.resolve().as_posix() + "/*"] == "allow"
    assert not any(str(home) in k for k in ext), "the agent home (config, key file) is not open to the file tools"
    plugin = home / "config" / "opencode" / "plugins" / "m2w-shell-env.js"
    assert "shell.env" in plugin.read_text(encoding="utf-8") and "OPENCODE_CONFIG_CONTENT" in plugin.read_text(encoding="utf-8")
    # builder: the lab tools are allowed (they check GAMEANYTHING_LEASE); gen and raw docker are not
    _, b = p.launch("go", "B", None, False, root, role="builder", add_dirs=[req], network=True, env={**env, "OPENROUTER_API_KEY": SECRET_OR})
    assert cfg["agent"]["build"]["steps"] == ap.OPENCODE_RESIDENT_STEPS and "agent" not in json.loads(b["OPENCODE_CONFIG_CONTENT"])
    bp = json.loads(b["OPENCODE_CONFIG_CONTENT"])["permission"]["bash"]
    assert "*launch_rt/*" not in bp and bp["*docker run*"] == "deny" and bp["*genrun*"] == "deny"


def test_opencode_env_isolation_from_the_operator_and_paid_keys(tmp_path, monkeypatch):
    env = {"PATH": "/bin", "OPENROUTER_API_KEY": "or", "MESHY_API_KEY": "m", "OPENAI_API_KEY": "img", "GEMINI_API_KEY": "g", "HF_TOKEN": "h",
           "ANTHROPIC_API_KEY": "a", "OPENCODE": "1", "OPENCODE_PID": "7", "GAMEANYTHING_OPENCODE_HOME": "/h"}
    p = ap.provider("opencode", binary="-", model="openrouter/x/y")
    e = ap.agent_env(p.clean_env(env), p)
    assert e == {"PATH": "/bin", "OPENROUTER_API_KEY": "or", "GAMEANYTHING_OPENCODE_HOME": "/h", "GAMEANYTHING_GEN_OFF": "1", "M2W_GEN_OFF": "1"}
    e = ap.agent_env(env, ap.provider("opencode", binary="-", model="anthropic/claude-sonnet-4-5"))
    assert "ANTHROPIC_API_KEY" in e and "OPENROUTER_API_KEY" not in e, "only the key of the model's own provider stays"
    assert ap.opencode_key_names("openrouter/a/b") == ("OPENROUTER_API_KEY",) and ap.opencode_key_names("my-llm/x") == ("MY_LLM_API_KEY",)
    # on the operator's own machine (no hub home): the m2w home is under the data dir, the operator's opencode login file is copied once
    op_auth = Path(os.environ["XDG_DATA_HOME"]) / "opencode" / "auth.json"; op_auth.parent.mkdir(parents=True)
    op_auth.write_text('{"openrouter": {"type": "api", "key": "x"}}', encoding="utf-8")
    (Path(os.environ["XDG_CONFIG_HOME"]) / "opencode").mkdir(parents=True)
    (Path(os.environ["XDG_CONFIG_HOME"]) / "opencode" / "AGENTS.md").write_text("take notes in agent_notes/", encoding="utf-8")
    _, run = ap.provider("opencode", binary="-").launch("go", "S", None, False, tmp_path, env={"PATH": "/bin"})
    home = projects.data_dir() / "agent-homes" / "opencode"
    assert run["XDG_CONFIG_HOME"] == str(home / "config") and (home / "data" / "opencode" / "auth.json").is_file()
    assert not (home / "config" / "opencode" / "AGENTS.md").exists() and json.loads(run["OPENCODE_CONFIG_CONTENT"])["provider"] == {}


# ---------------------------------------------------------------- Gemini CLI
def test_gemini_command_lines_resume_settings_and_policy(tmp_path):
    home = tmp_path / "gh"; req = tmp_path / "req"; req.mkdir()
    p = ap.provider("gemini", binary="gemini", model="gemini-3.1-pro-preview")
    env = {"PATH": "/bin", "GAMEANYTHING_GEMINI_HOME": str(home), "GEMINI_API_KEY": SECRET_GEM, "GAMEANYTHING_KEYS_FILE": "/k", "GEMINI_SYSTEM_MD": "/op/sys.md",
           "GEMINI_CLI_SYSTEM_SETTINGS_PATH": "/op/settings.json"}
    cmd, run = p.launch("go", "THE RULES", None, False, tmp_path, add_dirs=[req], env=env)
    assert cmd[0] == "gemini" and opt(cmd, "--output-format") == ["stream-json"] and opt(cmd, "--approval-mode") == ["default"]
    assert opt(cmd, "--include-directories") == [str(req)] + [str(d) for d in ap.gemini_read_only()] and opt(cmd, "--model") == ["gemini-3.1-pro-preview"] and "--resume" not in cmd
    assert "--yolo" not in cmd and "-y" not in cmd and "--sandbox" not in cmd
    (prompt,) = opt(cmd, "--prompt"); assert "THE RULES" in prompt and prompt.endswith("go") and "GEMINI.md" in prompt
    assert run["GEMINI_CLI_HOME"] == str(home) and run["GEMINI_API_KEY"] == SECRET_GEM and run["GAMEANYTHING_USER_ENV_FILE"] == "/k"
    assert "GEMINI_SYSTEM_MD" not in run and "GEMINI_CLI_SYSTEM_SETTINGS_PATH" not in run
    s = json.loads((home / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    red = s["security"]["environmentVariableRedaction"]; assert red["enabled"] is True and "GEMINI_API_KEY" in red["blocked"]
    assert s["mcpServers"] == {} and s["skills"]["enabled"] is False and s["hooksConfig"]["enabled"] is False
    assert s["experimental"]["enableAgents"] is False and s["security"]["auth"]["selectedType"] == "gemini-api-key"
    assert s["context"]["fileName"] == ["M2W-NO-CONTEXT-FILE.md"], "no GEMINI.md of the operator or a parent folder is loaded"
    (pol,) = opt(cmd, "--policy"); pol = Path(pol).read_text(encoding="utf-8")
    assert "docker\\ run" in pol and "gen_" in pol and "launch_rt" in pol and 'mcpName = "*"' in pol and "run_shell_command" in pol
    again, _ = p.launch("again", "THE RULES", "uuid-1", True, tmp_path, role="builder", add_dirs=[req], network=True, env=env)
    assert opt(again, "--resume") == ["uuid-1"] and "builder-system-prompt" in opt(again, "--prompt")[0]
    assert "launch_rt" not in (home / ".gemini" / "m2w" / "policy-builder.toml").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="budget"): p.command("go", "S", None, False, tmp_path, budget=2.0)
    log = tmp_path / "g.jsonl"
    log.write_text('{"type":"init","session_id":"7f8810ee-f2f8","model":"gemini-3.1-pro-preview"}\n'
                   '{"type":"message","role":"assistant","content":"OK","delta":true}\n'
                   '{"type":"result","status":"success","stats":{"input_tokens":80,"output_tokens":40,"cached":3,"tool_calls":7}}\n', encoding="utf-8")
    assert p.session_id(log) == "7f8810ee-f2f8" and ap.reply_text("gemini", log.read_text(encoding="utf-8")) == "OK" and not p.auth_failed(log)
    assert ap.usage("gemini", log)["input"] == 80
    # what gemini 0.39 printed on 2026-10-26 for a wrong key, and with no auth at all
    log.write_text('{"type":"result","status":"error","error":{"type":"unknown","message":"[API Error: API key not valid. Please pass a valid API key.]"}}\n', encoding="utf-8")
    assert p.auth_failed(log)
    log.write_text("Please set an Auth method in your /x/.gemini/settings.json or specify one of the following environment variables", encoding="utf-8")
    assert p.auth_failed(log)
    log.write_text("Error authenticating: IneligibleTierError: This client is no longer supported for Gemini Code Assist for individuals.", encoding="utf-8")
    assert p.auth_failed(log), "the personal Google login this server had (2026-10-26)"
    log.write_text('{"type":"result","status":"error","error":{"message":"[API Error: 402 Your prepayment credits are depleted.]"}}\n', encoding="utf-8")
    assert p.auth_failed(log), "a valid key without credit: retrying cannot help"
    log.write_text('{"type":"result","status":"error","error":{"type":"unknown","message":"[API Error: You have exhausted your daily quota on this model.]"}}\n', encoding="utf-8")
    assert not p.auth_failed(log), "the free tier's daily quota is a usage limit, not a login problem (QA 2026-10-29)"
    from gameanything import activity
    pz = activity.scan_log(log, "gemini"); assert pz["kind"] == "limit" and pz["resets"] and pz["resets"] > time.time() + 60, "back at midnight Pacific, not in 15 s"
    log.write_text('Error when talking to Gemini API TerminalQuotaError: You have exhausted your daily quota on this model.\n'
                   '{"type":"result","status":"error","error":{"message":"You exceeded your current quota, please check your plan"}}\n', encoding="utf-8")
    assert not p.auth_failed(log) and activity.scan_log(log, "gemini")["kind"] == "limit"


def test_gemini_env_and_keys_file_alias(tmp_path, monkeypatch):
    env = {"PATH": "/bin", "GEMINI_API_KEY": "g", "GOOGLE_API_KEY": "op-google", "OPENROUTER_API_KEY": "or", "GEMINI_CLI_IDE_PID": "3",
           "GEMINI_CLI_HOME": "/op/home", "GAMEANYTHING_GEMINI_HOME": "/m2w"}
    p = ap.provider("gemini", binary="-")
    e = ap.agent_env(p.clean_env(env), p)
    assert e == {"PATH": "/bin", "GEMINI_API_KEY": "g", "GAMEANYTHING_GEMINI_HOME": "/m2w", "GAMEANYTHING_GEN_OFF": "1", "M2W_GEN_OFF": "1"}, "the operator's GOOGLE_API_KEY would win"
    assert "GOOGLE_API_KEY" in ap.agent_env({**env, "GOOGLE_GENAI_USE_VERTEXAI": "true"}, p)
    f = tmp_path / "u.env"; f.write_text("MESHY_API_KEY=from-user\n", encoding="utf-8")
    monkeypatch.delenv("GAMEANYTHING_KEYS_FILE", raising=False); monkeypatch.setenv("GAMEANYTHING_USER_ENV_FILE", str(f))
    assert keys.available("MESHY_API_KEY") and keys.get("MESHY_API_KEY") == "from-user"
    monkeypatch.setenv("GAMEANYTHING_USER_ENV_FILE", ""); assert not keys.available("MESHY_API_KEY"), "empty: the user has no keys file"


# ---------------------------------------------------------------- agentd end to end with fake binaries
FAKE = r'''
import json, os, sys
mode = os.environ.get("FAKE_MODE", "ok"); name = os.environ["FAKE_NAME"]
rec = os.environ["FAKE_REC"]
with open(rec, "a", encoding="utf-8") as f: f.write(json.dumps({"argv": sys.argv[1:], "env": dict(os.environ), "cwd": os.getcwd()}) + "\n")
if name == "opencode":
    if mode == "auth":
        print(json.dumps({"type": "error", "sessionID": "ses_x", "error": {"name": "APIError", "data": {"message": "User not found.", "statusCode": 401}}})); sys.exit(1)
    sid = sys.argv[sys.argv.index("--session") + 1] if "--session" in sys.argv else "ses_fake1"
    print(json.dumps({"type": "step_start", "sessionID": sid, "part": {}}))
    print(json.dumps({"type": "step_finish", "sessionID": sid, "part": {"cost": 0.01, "tokens": {"input": 1, "output": 1}}}))
else:
    if mode == "auth":
        print("Please set an Auth method in your settings.json or specify one of the following environment variables"); sys.exit(41)
    sid = sys.argv[sys.argv.index("--resume") + 1] if "--resume" in sys.argv else "gem-uuid-1"
    print(json.dumps({"type": "init", "session_id": sid, "model": "gemini-3.1-pro-preview"}))
    print(json.dumps({"type": "result", "status": "success", "stats": {}}))
'''


@pytest.fixture
def fake(tmp_path, monkeypatch):
    f = tmp_path / "fake_agent.py"; f.write_text(FAKE, encoding="utf-8")
    rec = tmp_path / "rec.jsonl"; monkeypatch.setenv("FAKE_REC", str(rec))
    procs = []

    def spawn(cmd, cwd, env, log):
        p = agentd.popen([sys.executable, str(f), *cmd[1:]], cwd, env, log); procs.append(p); return p

    def calls(): return [json.loads(l) for l in rec.read_text(encoding="utf-8").splitlines()] if rec.exists() else []
    yield {"spawn": spawn, "calls": calls, "procs": procs}
    for p in procs:
        if p.poll() is None: p.kill(); p.wait(10)


def run_once(D, T, fake):
    D.tick(); p = fake["procs"][-1]; p.wait(30)
    return p


@pytest.mark.parametrize("name", ["opencode", "gemini"])
def test_agentd_runs_resumes_and_stops_on_auth_failure(name, fake, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_NAME", name); monkeypatch.setenv("MESHY_API_KEY", "paid-meshy-secret")
    monkeypatch.setenv("OPENROUTER_API_KEY" if name == "opencode" else "GEMINI_API_KEY", SECRET_OR if name == "opencode" else SECRET_GEM)
    _, T = project(); T.user_text("你好")
    D = agentd.Agentd(provider=name, agent="fake-bin", spawn=fake["spawn"], quiet=True, requests=tmp_path / "req")
    run_once(D, T, fake)
    T.append({"from": "agent", "type": "text", "text": "收到", "session": f"agentd:{T.root.name}"}); D.tick()
    s = json.loads((T.dir / ".agent_session").read_text(encoding="utf-8"))
    assert s["provider"] == name and s["id"] == ("ses_fake1" if name == "opencode" else "gem-uuid-1") and s["runs"] == 1
    c = fake["calls"]()[-1]
    assert "paid-meshy-secret" not in json.dumps(c["env"]) and c["env"]["GAMEANYTHING_GEN_OFF"] == "1" and Path(c["cwd"]).resolve() == T.root.resolve()
    if name == "opencode":
        assert SECRET_OR not in json.dumps(c["env"]) and "--session" not in c["argv"]
        assert str(tmp_path / "req") in json.dumps(json.loads(c["env"]["OPENCODE_CONFIG_CONTENT"])["permission"]["external_directory"]) or \
            (tmp_path / "req").resolve().as_posix() in c["env"]["OPENCODE_CONFIG_CONTENT"]
    else:
        assert c["env"]["GEMINI_API_KEY"] == SECRET_GEM and opt(c["argv"], "--include-directories")[0] == str(tmp_path / "req")
    # the next words resume the same session
    T.user_text("再来"); run_once(D, T, fake)
    c2 = fake["calls"]()[-1]; flag = "--session" if name == "opencode" else "--resume"
    assert opt(c2["argv"], flag) == [s["id"]]
    T.append({"from": "agent", "type": "text", "text": "好", "session": f"agentd:{T.root.name}"}); D.tick()
    # a login problem: one plain message, no retries
    monkeypatch.setenv("FAKE_MODE", "auth"); T.user_text("还在吗"); run_once(D, T, fake); n = len(fake["calls"]())
    D.tick()
    msgs = [e.get("text", "") for e in T.events() if e.get("type") == "status"]
    assert any(("OpenCode" in m) if name == "opencode" else ("Gemini" in m) for m in msgs), msgs
    assert json.loads((T.dir / ".agentd_failed").read_text(encoding="utf-8"))["reason"] == "auth"
    D.clock = lambda: time.time() + 3600; D.tick(); assert len(fake["calls"]()) == n, "no retry after an auth failure"


@pytest.mark.parametrize("name", ["opencode", "gemini"])
def test_builder_runs_with_the_builder_rules(name, monkeypatch, tmp_path):
    from tests.test_builds import FakeLab, Spawner, go, request
    monkeypatch.setenv("GAMEANYTHING_PARENT_REQUESTS", str(tmp_path / "req")); monkeypatch.setenv("M2W_LAB_USER", "tester")
    monkeypatch.setenv("OPENROUTER_API_KEY", SECRET_OR); monkeypatch.setenv("GEMINI_API_KEY", SECRET_GEM)
    e = projects.create("建一座桥", "feature", game="minecraft", build_mode="lab"); T = Thread(Path(e["path"]))
    T.append({"from": "agent", "type": "text", "text": "你好", "source": "terminal"})
    sp = Spawner()
    try:
        go(T); D = agentd.Agentd(provider=name, agent=name, spawn=sp, quiet=True, requests=tmp_path / "req", lab=FakeLab())
        request(T); D.tick()
        (b,) = sp.builders(); env = b["env"]
        assert env["GAMEANYTHING_ROLE"] == "builder" and env["GAMEANYTHING_LEASE"] and env["GAMEANYTHING_GEN_OFF"] == "1"
        if name == "opencode":
            perm = json.loads(env["OPENCODE_CONFIG_CONTENT"])["permission"]
            assert "*launch_rt/*" not in perm["bash"] and perm["bash"]["*docker run*"] == "deny" and SECRET_OR not in json.dumps(env)
        else:
            pol = Path(opt(b["cmd"], "--policy")[0]); assert pol.name == "policy-builder.toml" and "launch_rt" not in pol.read_text(encoding="utf-8")
            assert "<builder-system-prompt>" in opt(b["cmd"], "--prompt")[0] and opt(b["cmd"], "--include-directories")
    finally: sp.stop_all()


# ---------------------------------------------------------------- the hub: her own choice, key and model
@pytest.fixture
def hubusers(monkeypatch):
    home = Path.home()
    users.add_user("carol", "carol-pass-89", False, "Carol", home / "carol" / "m2w", home / "carol" / ".claude-m2w")
    users.add_user("alice", "alice-pass-123", True, "Alice", home / "alice" / "m2w", home / "alice" / ".claude-m2w")
    d = home / "alice" / ".claude-m2w"; d.mkdir(parents=True); (d / ".credentials.json").write_text("{}", encoding="utf-8")


def test_hub_user_on_opencode_and_gemini_gets_her_own_home_key_and_model(hubusers, monkeypatch, tmp_path):
    from tests.test_builds import Spawner
    monkeypatch.setenv("OPENROUTER_API_KEY", "supervisor-or-xyz"); monkeypatch.setenv("GEMINI_API_KEY", "supervisor-gem-xyz")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "supervisor-ant-xyz")
    pc = projects.create("C", "feature", owner="carol"); T = Thread(Path(pc["path"])); T.user_text("hi")
    users.set_agent("carol", "opencode")
    assert "no OpenCode key" in users.blocked(pc["path"], "claude-code")
    for bad, why in (("short", "看起来不是"), ("sk-ant-oat01-" + "x" * 30, "订阅 token"), ("sk-proj-" + "x" * 30, "OpenRouter")):
        with pytest.raises(users.HubError, match=why): users.connect_opencode("carol", bad)
    with pytest.raises(users.HubError, match="provider/model"): users.connect_opencode("carol", SECRET_OR, "kimi")
    st = users.connect_opencode("carol", SECRET_OR, "openrouter/z-ai/glm-5.3")
    assert st["connected"] and st["kind"] == "api_key" and st["last4"] == SECRET_OR[-4:] and st["model"] == "openrouter/z-ai/glm-5.3"
    u = users.get_user("carol"); assert f"OPENROUTER_API_KEY={SECRET_OR}" in Path(u["env_file"]).read_text(encoding="utf-8")
    assert users.blocked(pc["path"]) is None and users.model_for(pc["path"], "opencode") == "openrouter/z-ai/glm-5.3"
    sp = Spawner()
    try:
        agentd.Agentd(claude="/bin/false", spawn=sp, quiet=True).tick()        # the daemon is on Claude Code; carol's choice wins
        c = sp.calls[-1]; env = c["env"]
        assert c["cmd"][1] == "run" and opt(c["cmd"], "--model") == ["openrouter/z-ai/glm-5.3"]
        assert env["GAMEANYTHING_OPENCODE_HOME"] == str(users.opencode_home(u)) and env["XDG_DATA_HOME"].startswith(str(users.opencode_home(u)))
        assert "supervisor" not in json.dumps(env) and SECRET_OR not in json.dumps(env) and env["GAMEANYTHING_USER"] == "carol"
        assert (users.opencode_home(u) / "m2w" / "key-openrouter").read_text(encoding="utf-8") == SECRET_OR
        run = json.loads(agentd.run_path(T).read_text(encoding="utf-8")); assert run["agent_provider"] == "opencode"
        sp.stop_all(); time.sleep(0.2); agentd.Agentd(claude="/bin/false", spawn=sp, quiet=True).tick()
        # Gemini
        users.set_agent("carol", "gemini"); assert "no Gemini login" in users.blocked(pc["path"])
        with pytest.raises(users.HubError, match="Gemini API key"): users.connect_gemini("carol", "sk-" + "x" * 30)
        st = users.connect_gemini("carol", SECRET_GEM); assert st["connected"] and st["kind"] == "api_key"
        users.set_model("carol", "gemini", "gemini-3.1-pro-preview"); T.user_text("hi again")
        agentd.Agentd(claude="/bin/false", spawn=sp, quiet=True).tick()
        c = sp.calls[-1]; env = c["env"]
        assert c["cmd"][1] == "--output-format" and opt(c["cmd"], "--model") == ["gemini-3.1-pro-preview"]
        assert env["GEMINI_CLI_HOME"] == str(users.gemini_home(u)) and env["GEMINI_API_KEY"] == SECRET_GEM and "supervisor" not in json.dumps(env)
        assert "OPENROUTER_API_KEY" not in env, "her OpenRouter key is not Gemini's own key: stripped"
    finally: sp.stop_all()
    a = users.agent_status(users.get_user("carol"))
    assert a["agent"] == "gemini" and a["opencode"]["connected"] and a["gemini"]["model"] == "gemini-3.1-pro-preview"
    assert SECRET_GEM not in json.dumps(a) and SECRET_OR not in json.dumps(a)
    assert not users.disconnect_gemini("carol")["connected"] and not users.disconnect_opencode("carol")["connected"]


@pytest.mark.parametrize("name", ["opencode", "gemini"])
def test_hub_connection_test_runs_the_agent_with_her_env(name, hubusers, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "supervisor-or-xyz")
    users.set_agent("carol", name)
    (users.connect_opencode("carol", SECRET_OR) if name == "opencode" else users.connect_gemini("carol", SECRET_GEM))
    calls = []
    out = (json.dumps({"type": "text", "sessionID": "s", "part": {"text": "OK"}}) if name == "opencode"
           else json.dumps({"type": "message", "role": "assistant", "content": "OK"}))
    def run(cmd, **kw): calls.append({"cmd": cmd, **kw}); return subprocess.CompletedProcess(cmd, 0, out + "\n", "")
    r = users.try_claude("carol", run=run); assert r == {"ok": True, "text": "OK"}, r
    env = calls[-1]["env"]; assert "supervisor" not in json.dumps(env) and env["GAMEANYTHING_GEN_OFF"] == "1"
    if name == "opencode": assert SECRET_OR not in json.dumps(env) and calls[-1]["cmd"][1] == "run"
    else: assert env["GEMINI_CLI_HOME"] == str(users.gemini_home(users.get_user("carol")))
    bad = (json.dumps({"type": "error", "error": {"data": {"message": f"key {SECRET_OR} User not found.", "statusCode": 401}}}) if name == "opencode"
           else json.dumps({"type": "result", "status": "error", "error": {"message": f"API key not valid {SECRET_GEM}"}}))
    r = users.try_claude("carol", run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, bad + "\n", ""))
    assert not r["ok"] and SECRET_OR not in r["text"] and SECRET_GEM not in r["text"] and "***" in r["text"]


def test_estimate_for_opencode_and_gemini():
    from gameanything.estimate import estimate
    r = estimate("small", "opencode", "openrouter/moonshotai/kimi-k2.6")
    assert r["estimate"]["account"] == "api" and r["estimate"]["cost_usd"] and "2026-10-26" in r["estimate"]["note"]
    assert estimate("small", "opencode", "openrouter/nobody/unknown")["estimate"]["cost_usd"] is None
    g = estimate("small", "gemini", "gemini-3.1-pro-preview", "api"); assert g["estimate"]["model"] == "google/gemini-3.1-pro-preview" and g["estimate"]["cost_usd"]
