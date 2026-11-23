"""Per-project models (models.py): config/project.yaml chat_model / build_model, the CLI, /api/models (the chat page's chips; only the owner
changes them), agentd running the chat on the project's choice (same agent: the session is resumed with the new model; another agent: a
new session seeded with the recent thread), builds on her go card runner / the build model, the model on the live and result cards, and
the chips rendering in node in zh and en with no missing English."""
import json
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from gameanything import agentd, builds, cli, devstatus, live, models, projects, users
from gameanything.conversation import Thread
from test_builds import req_dir  # noqa: F401,F811  (fixture: the requests folder + lab user of the build tests)

STATIC = Path(models.__file__).parent / "ui" / "static"


class Spawner:
    def __init__(self): self.calls = []; self.procs = []

    def __call__(self, cmd, cwd, env, log):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        self.calls.append({"cmd": cmd, "cwd": Path(cwd), "env": env}); self.procs.append(p); return p

    def stop_all(self):
        for p in self.procs:
            if p.poll() is None: p.kill(); p.wait(10)


@pytest.fixture
def spawner():
    s = Spawner(); yield s; s.stop_all()


@pytest.fixture
def codex_cli(tmp_path, monkeypatch):
    """A codex binary on this machine (no hub: the installed CLIs are the ones a project may use)."""
    f = tmp_path / "bin" / "codex"; f.parent.mkdir(); f.write_text("#!/bin/sh\n", encoding="utf-8"); f.chmod(0o755)
    monkeypatch.setenv("GAMEANYTHING_CODEX", str(f)); return f


def proj(title="Garden"):
    return Path(projects.create(title, "feature")["path"])


def opt(cmd, flag):
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


# ---------------------------------------------------------------- the setting and its CLI
def test_defaults_set_validate_and_cli(codex_cli, capsys):
    root = proj()
    st = models.state(root)
    assert st["chat"] == {"agent": "claude-code", "model": "", "source": "daemon", "agent_name": "Claude Code", "model_shown": "sonnet", "warn": ""}
    assert st["build"]["agent"] == "claude-code" and st["can_edit"] and not st["hub"]
    ids = {g["id"]: [m["id"] for m in g["models"]] for g in st["agents"]}
    assert ids["claude-code"] == ["sonnet", "opus", "haiku", "fable"] and "codex" in ids and ids["codex"][0] == ""
    assert all(m["hint"] for g in st["agents"] for m in g["models"])
    models.set_choice(root, "chat", "claude", "Opus")
    assert projects.config_of(root)["chat_model"] == {"agent": "claude-code", "model": "opus"}
    assert models.effective(root, "chat")["source"] == "project" and models.effective(root, "build")["source"] == "daemon"
    for bad in (("claude-code", "gpt-6"), ("codex", "Bad Model!"), ("aider", "x"), ("gemini", "x")):
        with pytest.raises(models.ModelError): models.set_choice(root, "build", *bad)
    assert cli.main(["project", "set-model", root.name, "build", "codex:gpt-6.1-sol"]) == 0
    out = capsys.readouterr().out
    assert "chat_model=claude-code:opus" in out and "build_model=codex:gpt-6.1-sol" in out
    assert cli.main(["project", "set-model", root.name, "--list"]) == 0
    assert "sonnet, opus, haiku" in capsys.readouterr().out
    assert cli.main(["project", "set-model", root.name, "chat", "default"]) == 0
    assert "chat_model" not in projects.config_of(root) and "chat_model=claude-code (not chosen: daemon default)" in capsys.readouterr().out
    with pytest.raises(SystemExit): cli.main(["project", "set-model", root.name, "chat", "claude-code:gpt-x"])


def test_codex_models_are_a_fixed_list(tmp_path, monkeypatch):
    """Not models_cache.json: other Codex sessions rewrite it, the menu changed under her (QA 2026-10-29)."""
    h = tmp_path / "codexhome"; h.mkdir(); monkeypatch.setenv("CODEX_HOME", str(h))
    assert [m["id"] for m in models.codex_models()] == ["", *models.CODEX_MODELS]
    (h / "models_cache.json").write_text(json.dumps({"models": [{"slug": "gpt-9-astra", "priority": 1, "visibility": "list"}]}), encoding="utf-8")
    ms = models.codex_models()
    assert [m["id"] for m in ms] == ["", *models.CODEX_MODELS]
    assert ms[2]["hint"] == "最强，适合最难的任务；用的额度最多"


# ---------------------------------------------------------------- agentd: the chat runs on the project's choice
def _session(root, provider="claude-code", sid="sess-1"):
    T = Thread(root); T.dir.mkdir(parents=True, exist_ok=True)
    (T.dir / ".agent_session").write_text(json.dumps({"id": sid, "provider": provider, "created": datetime.now().isoformat(timespec="seconds"), "runs": 1}), encoding="utf-8")
    return T


def test_same_agent_new_model_keeps_the_session(spawner):
    root = proj(); T = _session(root)
    T.user_text("我们之前说到湖边的长椅"); models.set_choice(root, "chat", "claude-code", "opus")
    d = agentd.Agentd(claude="/bin/false", spawn=spawner, quiet=True); d.tick()
    cmd = spawner.calls[-1]["cmd"]
    assert opt(cmd, "--model") == "opus" and opt(cmd, "--resume") == "sess-1" and cmd[0] == "/bin/false"
    run = json.loads(agentd.run_path(T).read_text(encoding="utf-8"))
    assert run["agent_provider"] == "claude-code" and run["agent_model"] == "opus" and run["resume"] and not run["switched_from"]
    assert json.loads((T.dir / ".agent_session").read_text(encoding="utf-8"))["model"] == "opus"


def test_another_agent_starts_a_new_session_seeded_with_the_thread(spawner, codex_cli):
    root = proj(); T = _session(root)
    T.user_text("婚礼那天下了雨"); T.agent_text("记下了：雨天，湖边。"); T.user_text("再加一把伞")
    models.set_choice(root, "chat", "codex", "gpt-6.1-sol")
    agentd.Agentd(claude="/bin/false", spawn=spawner, quiet=True).tick()
    cmd = spawner.calls[-1]["cmd"]
    assert cmd[0] == str(codex_cli) and "resume" not in cmd and opt(cmd, "--model") == "gpt-6.1-sol"
    prompt = cmd[-1]
    assert "switched this project's chat from Claude to Codex" in prompt and "婚礼那天下了雨" in prompt and "agent: 记下了：雨天，湖边。" in prompt
    run = json.loads(agentd.run_path(T).read_text(encoding="utf-8"))
    assert run["agent_provider"] == "codex" and run["switched_from"] == "claude-code" and not run["resume"]
    assert agentd.seed_text(Thread(proj("Empty")), "codex", "claude-code") == ""


def test_hub_only_the_owners_logins_and_the_choice_beats_the_users_agent(spawner, monkeypatch):
    home = Path.home()
    for n in ("alice", "bob"):
        u = users.add_user(n, f"{n}-pass-1234", False, n.title(), home / n / "m2w", home / n / ".claude-m2w")
        d = Path(u["claude_config_dir"]); d.mkdir(parents=True); (d / ".credentials.json").write_text("{}", encoding="utf-8")
    root = Path(projects.create("A", "feature", owner="alice")["path"])
    st = models.state(root); assert [g["id"] for g in st["agents"]] == ["claude-code"] and st["chat"]["source"] == "daemon"
    with pytest.raises(models.ModelError, match="还不能用 Codex"): models.set_choice(root, "chat", "codex", "")
    users.connect_codex("alice", "sk-proj-" + "a" * 40)
    assert [g["id"] for g in models.state(root)["agents"]] == ["claude-code", "codex"]
    models.set_choice(root, "chat", "codex", "")                   # her user setting stays Claude Code; this project runs Codex
    assert users.agent_of(users.get_user("alice")) == "claude-code"
    Thread(root).user_text("hi", author="alice")
    agentd.Agentd(claude="/bin/false", spawn=spawner, quiet=True).tick()
    c = spawner.calls[-1]
    assert Path(c["cmd"][0]).name.startswith("codex") and "--model" not in c["cmd"] and c["env"]["CODEX_API_KEY"].startswith("sk-proj-")
    with pytest.raises(models.ModelError, match="还不能用 OpenCode"):
        models.set_choice(root, "build", "opencode", "openrouter/z-ai/glm-5.3")       # not usable: no OpenCode key


# ---------------------------------------------------------------- Fable: on the menu, very expensive, the CLI alias
def test_fable_is_offered_with_a_warning(capsys):
    root = proj()
    fab = next(m for m in models.catalog("claude-code")["models"] if m["id"] == "fable")
    assert "额度用得最快" in fab["hint"] and "非常贵" in fab["warn"]
    assert not any(m.get("warn") for m in models.catalog("claude-code")["models"] if m["id"] != "fable")
    assert models.check("claude-code", "Fable") == "fable"                         # `claude --model fable` = claude-fable-5-1
    assert models.cli_model("claude-code", "anthropic/claude-fable") == "fable"
    assert models.warning("claude-code", "fable") and models.warning("claude-code", "claude-fable-5-1") and not models.warning("claude-code", "opus")
    assert cli.main(["project", "set-model", root.name, "build", "claude-code:fable"]) == 0
    out = capsys.readouterr().out
    assert "build_model=claude-code:fable" in out and "Fable 非常贵" in out
    st = models.state(root); assert st["build"]["warn"] and not st["chat"]["warn"]
    from gameanything import estimate as E
    sub = E.estimate("small", "claude-code", "fable")
    assert sub["estimate"]["model"] == "anthropic/claude-fable" and "Fable 非常贵" in sub["estimate"]["note"] and "Fable is very expensive" in sub["estimate_en"]["note"]
    api, opus = E.estimate("small", "claude-code", "fable", "api"), E.estimate("small", "claude-code", "opus", "api")
    assert api["estimate"]["cost_usd"][0] > opus["estimate"]["cost_usd"][0]


# ---------------------------------------------------------------- builds: only the build model
EST_SMALL = {"wall_h": [1.1, 2.0], "cost_usd": None, "account": "subscription", "agent": "claude-code", "model": "anthropic/claude-sonnet", "note": "s"}


def test_go_card_names_the_build_model_and_drops_runners(codex_cli):
    root = proj()
    rs = [{"id": "claude-code:anthropic/claude-sonnet", "harness": "Claude Code", "model": "anthropic/claude-sonnet", "recommended": True, "estimate": EST_SMALL},
          {"id": "claude-code:anthropic/claude-opus", "harness": "Claude Code", "model": "anthropic/claude-opus",
           "estimate": {**EST_SMALL, "model": "anthropic/claude-opus", "note": "o"}}]
    card = {"kind": "go", "milestone": "m1", "title": "Go", "items": ["x"], "runners": rs,
            "en": {"title": "Go", "runners": [{**r, "estimate": {**r["estimate"], "note": r["estimate"]["note"] + "-en"}} for r in rs]}}
    c, fix = models.stamp_build_model(root, card)                  # default: Claude Code + sonnet = the first runner's estimate
    assert "runners" not in c and "runners" not in c["en"] and not fix
    assert c["build_model"] == {"agent": "claude-code", "model": "", "label": "Claude Code · sonnet"}
    assert c["estimate"]["note"] == "s" and c["en"]["estimate"]["note"] == "s-en" and c["en"]["title"] == "Go"
    models.set_choice(root, "build", "claude-code", "opus")
    c, _ = models.stamp_build_model(root, card); assert c["estimate"]["note"] == "o" and c["build_model"]["label"] == "Claude Code · opus"
    models.set_choice(root, "build", "codex", "gpt-6.1-sol")       # no runner is it: estimated anew, same size (small)
    c, fix = models.stamp_build_model(root, card)
    assert c["estimate"]["agent"] == "codex" and c["estimate"]["model"] == "openai/gpt-6.1-sol" and c["estimate"]["wall_h"] == [1.1, 2.0] and not fix
    assert c["en"]["estimate"]["agent"] == "codex"
    c, fix = models.stamp_build_model(root, {"kind": "go", "milestone": "m1", "title": "Go", "items": ["x"], "estimate": {**EST_SMALL, "wall_h": [1, 2]}})
    assert c["estimate"]["wall_h"] == [1, 2] and "不是按项目的构建模型" in fix      # a size it cannot tell: kept, the resident is told
    c, fix = models.stamp_build_model(root, {"kind": "go", "milestone": "m1", "title": "Go", "items": ["x"], "estimate": {**EST_SMALL, "agent": "codex", "model": "openai/gpt-6.1-sol"}})
    assert not fix and c["estimate"]["agent"] == "codex"           # already the build model's
    assert models.stamp_build_model(root, {"kind": "permission", "title": "x"}) == ({"kind": "permission", "title": "x"}, "")


def test_cli_chat_card_stamps_the_build_model(tmp_path, capsys):
    root = proj(); models.set_choice(root, "build", "claude-code", "haiku")
    f = tmp_path / "go.yaml"
    f.write_text(yaml.safe_dump({"kind": "go", "key": "m1-go", "milestone": "m1", "title": "Go", "items": ["x"], "estimate": EST_SMALL,
                                 "runners": [{"id": "claude-code:anthropic/claude-sonnet", "harness": "Claude Code", "model": "anthropic/claude-sonnet", "recommended": True}]}), encoding="utf-8")
    T = Thread(root); T.claim("s1")
    assert cli.main(["chat", "card", "--project", str(root), "--session", "s1", "--file", str(f)]) == 0
    out = capsys.readouterr().out
    card = [e for e in T.events() if e.get("type") == "card"][-1]["card"]
    assert "runners" not in card and card["build_model"]["label"] == "Claude Code · haiku" and card["estimate"]["model"] == "anthropic/claude-haiku"
    assert "runners 去掉了" in out
    assert cli.main(["estimate", "--project", str(root), "--size", "small", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["estimate"]["model"] == "anthropic/claude-haiku"


def _lab_build(spawner, tmp_path, monkeypatch, build, answer):
    """A lab build of a project whose build model is `build` ("agent:model"), from an OLDER go card that carries a runner (Claude Code + opus)."""
    from test_builds import Clock, FakeLab, daemon, project, request
    orig = projects.create

    def create(*a, **k):
        x = orig(*a, **k); ag, _, mo = build.partition(":")                  # written as is: it may be one the owner cannot run
        users._write_cfg_key(Path(x["path"]), "build_model", {"agent": ag, "model": mo}); return x
    monkeypatch.setattr(projects, "create", create)
    e, T = project()
    g = T.card({"kind": "go", "key": "go-m1", "title": "开工", "milestone": "m1", "items": ["桥"],
                "runners": [{"id": "claude-code:anthropic/claude-opus", "harness": "Claude Code", "model": "anthropic/claude-opus"}]})
    T.answer(g["id"], answer); (T.dir / ".agent_cursor").write_text(T.events()[-1]["id"], encoding="utf-8")
    request(T); clock = Clock(); D = daemon(spawner, FakeLab(), tmp_path, clock=clock); D.tick()
    return T, D, clock


def _builders(spawner): return [c for c in spawner.calls if c["env"].get("GAMEANYTHING_ROLE") == "builder"]


def test_build_uses_only_the_build_model_even_with_an_old_runner(spawner, tmp_path, req_dir, codex_cli, monkeypatch):
    from test_builds import rec
    T, D, _ = _lab_build(spawner, tmp_path, monkeypatch, "codex:gpt-6-luna", {"decision": "start", "runner": "claude-code:anthropic/claude-opus"})
    (b,) = _builders(spawner)
    assert b["cmd"][0] == str(codex_cli) and opt(b["cmd"], "--model") == "gpt-6-luna"
    r = rec(T); assert r["provider"] == "codex" and r["model"] == "gpt-6-luna" and r["card_runner"]["model"] == "opus" and "runner" not in r


def test_build_is_blocked_when_the_owner_cannot_run_the_build_model(spawner, tmp_path, req_dir, codex_cli, monkeypatch):
    from test_builds import notes, rec
    monkeypatch.setattr(models, "_installed", lambda a: False)      # Codex is gone from this machine: no fallback to Claude Code
    T, D, clock = _lab_build(spawner, tmp_path, monkeypatch, "codex:", {"decision": "start"})
    assert not _builders(spawner)
    r = rec(T); assert r["state"] == "blocked" and "build model codex:default cannot run" in r["why"]
    (n,) = [x for x in notes(T) if "构建模型" in x]
    assert "Codex" in n and "不会换成别的模型" in n and "「构建」" in n
    clock.t += builds.BLOCKED_RETRY_SECS + 5; D.tick()
    assert len([x for x in notes(T) if "构建模型" in x]) == 1 and not _builders(spawner)     # still blocked, told once
    monkeypatch.setattr(models, "_installed", lambda a: True)       # Codex is back: it starts at the next try, on Codex
    clock.t += builds.BLOCKED_RETRY_SECS + 5; D.tick()
    (b,) = _builders(spawner); assert b["cmd"][0] == str(codex_cli) and rec(T)["provider"] == "codex"


def test_live_card_and_result_card_show_the_model(tmp_path):
    root = proj()
    r = {"provider": "claude-code", "model": "opus", "build_mode": "native", "started": datetime.now().isoformat(timespec="seconds"), "playtest_rounds": 3}
    assert live.run_label(r) == "Claude · opus" and live.run_label({"provider": "claude-code"}) == "Claude · sonnet"
    assert live.run_label({"provider": "codex"}) == "Codex"
    f = builds.run_file(root, "m1"); f.parent.mkdir(parents=True); f.write_text(json.dumps(r), encoding="utf-8")
    card = devstatus.result_card(root, "m1")
    assert "构建用的：Claude · opus" in card["stats"] and "Built with: Claude · opus" in card["en"]["stats"]


# ---------------------------------------------------------------- /api/models and the chips in node
def test_api_models_single_user(codex_cli):
    from gameanything.ui import serve
    root = proj(); box, ready = {}, threading.Event()
    threading.Thread(target=serve, args=(root,), kwargs={"port": 0, "ready": lambda s: (box.update(srv=s), ready.set())}, daemon=True).start()
    assert ready.wait(20)
    import urllib.request
    base = f"http://127.0.0.1:{box['srv'].server_port}"

    def call(method, path, data=None):
        req = urllib.request.Request(base + path, json.dumps(data).encode() if data is not None else None,
                                     {"Content-Type": "application/json", "Origin": base, "X-Lang": "en"}, method=method)
        try: resp = urllib.request.urlopen(req, timeout=20)
        except urllib.error.HTTPError as e: resp = e
        return resp.status if hasattr(resp, "status") else resp.code, json.loads(resp.read())
    try:
        code, st = call("GET", "/api/models"); assert code == 200 and st["can_edit"] and st["chat"]["model_shown"] == "sonnet"
        code, r = call("POST", "/api/models", {"role": "build", "agent": "codex", "model": "gpt-6-luna"})
        assert code == 200 and r["models"]["build"]["agent"] == "codex" and projects.config_of(root)["build_model"]["model"] == "gpt-6-luna"
        code, r = call("POST", "/api/models", {"role": "chat", "agent": "claude-code", "model": "gpt-x"})
        assert code == 400 and r["error"].startswith("Claude Code models are")
        code, r = call("POST", "/api/models", {"role": "build", "agent": "default"}); assert code == 200 and r["models"]["build"]["source"] == "daemon"
    finally:
        box["srv"].shutdown(); box["srv"].server_close()


def _chips_in_node(state, lang, role="chat", sel=None, go=None):
    shell = (STATIC / "shell.js").read_text(encoding="utf-8")
    part = shell[shell.index("/* ------------------------------------------------------------ models:"):shell.index("/* ------------------------------------------------------------ end models */")]
    js = ("globalThis.window={addEventListener(){}};globalThis.document={documentElement:{dataset:{},getAttribute(){return null},setAttribute(){}},"
          "addEventListener(){},querySelectorAll(){return[]}};globalThis.localStorage={getItem(){return null},setItem(){}};globalThis.location={origin:'x'};\n"
          + (STATIC / "i18n.js").read_text(encoding="utf-8")
          + f"\nM2W.lang={json.dumps(lang)};const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}}[c]));\n"
          + part + f"\nconst M={json.dumps(state, ensure_ascii=False)};"
          f"const GO={json.dumps(go, ensure_ascii=False)};"
          f"console.log(JSON.stringify({{chips:modelChipsHtml(M),menu:modelMenuHtml({json.dumps(role)},M,{json.dumps(sel)}),go:GO?goModelHtml(GO[0],GO[1],M):'',miss:[...M2W.miss]}}));")
    r = subprocess.run(["node", "-"], input=js, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_chips_and_menu_render_in_node(tmp_path, monkeypatch):
    for v in ("GAMEANYTHING_OPENCODE", "GAMEANYTHING_GEMINI", "GAMEANYTHING_CODEX"):
        f = tmp_path / v; f.write_text("", encoding="utf-8"); monkeypatch.setenv(v, str(f))
    root = proj(); models.set_choice(root, "build", "codex", "")
    st = models.state(root)
    assert [g["id"] for g in st["agents"]] == ["claude-code", "codex", "opencode", "gemini"]
    zh, en = _chips_in_node(st, "zh"), _chips_in_node(st, "en")
    assert "对话：Claude Code · sonnet ▾" in zh["chips"] and "构建：Codex · 默认 ▾" in zh["chips"]
    assert "Chat: Claude Code · sonnet ▾" in en["chips"] and "Build: Codex · Default ▾" in en["chips"]
    assert "更强，适合难的任务" in zh["menu"] and "Stronger, for hard tasks" in en["menu"] and "In use" in en["menu"]
    assert "openrouter/moonshotai/kimi-k2.6" in en["menu"] and "Or type another provider/model" in en["menu"]
    assert "mwarn" not in en["menu"]
    sw = _chips_in_node(st, "en", "chat", {"agent": "codex", "model": "gpt-6-luna"})
    assert "Switching to another agent starts a new session" in sw["menu"] and "Switch agent and save" in sw["menu"]
    bd = _chips_in_node(st, "en", "build", {"agent": "claude-code", "model": "opus"})
    assert "mwarn" not in bd["menu"] and "Model for builds" in bd["menu"]
    ro = _chips_in_node({**st, "can_edit": False}, "en")
    assert "▾" not in ro["chips"] and "Only the project&#39;s owner can change the models" in ro["chips"]
    assert en["miss"] == [] and sw["miss"] == [] and bd["miss"] == [] and ro["miss"] == []


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_fable_confirm_and_go_card_model_line_in_node():
    root = proj(); st = models.state(root)
    zh = _chips_in_node(st, "zh", "build", {"agent": "claude-code", "model": "fable"})
    en = _chips_in_node(st, "en", "build", {"agent": "claude-code", "model": "fable"})
    assert "非常贵" in zh["menu"] and "知道很贵，还是用它" in zh["menu"] and "很贵" in zh["menu"]
    assert "Fable is very expensive" in en["menu"] and "I know it is expensive, use it" in en["menu"] and "Very expensive" in en["menu"]
    assert "uses quota fastest" in en["menu"] and "Background builds use only this one" in en["menu"]
    plain = _chips_in_node(st, "en", "build", {"agent": "claude-code", "model": "opus"})
    assert "I know it is expensive" not in plain["menu"] and "Fable is very expensive" not in plain["menu"]
    card = {"kind": "go", "build_model": {"agent": "claude-code", "model": "", "label": "Claude Code · sonnet"}}
    live_ = _chips_in_node(st, "en", go=[card, True])
    assert "Claude Code · sonnet" in live_["go"] and "click “Build” next to the message box" in live_["go"] and "estimate again" not in live_["go"]
    models.set_choice(root, "build", "claude-code", "fable"); st = models.state(root)
    ch = _chips_in_node(st, "en", go=[card, True])
    assert "Claude Code · fable" in ch["go"] and "made for Claude Code · sonnet" in ch["go"] and "Fable is very expensive" in ch["go"]
    done = _chips_in_node(st, "zh", go=[card, False])              # answered: the model the card named, no pointer
    assert "Claude Code · sonnet" in done["go"] and "「构建」" not in done["go"]
    assert _chips_in_node(st, "en", go=[{"kind": "go"}, False])["go"] == ""
    assert all(x["miss"] == [] for x in (en, plain, live_, ch))


def test_page_wiring():
    shell, html, hub = ((STATIC / n).read_text(encoding="utf-8") for n in ("shell.js", "shell.html", "../hub.py"))
    assert 'id="mchips"' in html and 'get("/api/models")' in shell and 'post("/api/models"' in shell and "goModelHtml(k, ed && !c.newer, MODELS)" in shell
    assert 'data-act="runner"' not in shell and "runner: rn" not in shell        # the go card has no runner to pick any more
    assert '"/api/models": "owner"' in hub


def test_opencode_model_needs_its_providers_key():
    home = Path.home()
    users.add_user("dora", "dora-pass-1234", False, "Dora", home / "dora" / "m2w", home / "dora" / ".claude-m2w")
    root = Path(projects.create("D", "feature", owner="dora")["path"])
    users.connect_opencode("dora", "sk-or-v1-" + "b" * 40)
    models.set_choice(root, "chat", "opencode", "openrouter/z-ai/glm-5.3")
    assert models.effective(root, "chat") == {"agent": "opencode", "model": "openrouter/z-ai/glm-5.3", "source": "project"}
    with pytest.raises(models.ModelError, match="还没有 anthropic 的 key"): models.set_choice(root, "build", "opencode", "anthropic/claude-sonnet-5-5")
    with pytest.raises(models.ModelError, match="provider/model"): models.set_choice(root, "build", "opencode", "glm")
    st = models.state(root); oc = next(g for g in st["agents"] if g["id"] == "opencode")
    assert oc["free"] and oc["models"][0]["id"] == users.opencode_model(users.get_user("dora"))
