"""Paid generation without a coordinator (genrun.py + agentd): the resident queues, agentd checks both cards, runs once per go card with the
owner's env, and notes the outcome to the agent. The gen script is NEVER run: the spawner is replaced by a tiny `python -c print` process."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from gameanything import agentd, cli, genrun, projects, users
from gameanything.conversation import Thread

from _portable import CAN_SYMLINK

SECRET = "meshy-secret-value-123456"


# ---------------------------------------------------------------- helpers
class GenSpawn:
    """Stands in for the gen script: records the command and env, prints one line (and the key, to prove it is redacted)."""
    def __init__(self, rc=0): self.calls = []; self.rc = rc

    def __call__(self, cmd, cwd, env, log):
        self.calls.append({"cmd": cmd, "cwd": cwd, "env": env})
        code = f"import sys; print('made 2 models'); print('key {SECRET}'); sys.exit({self.rc})"
        return subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)


def project(title="三维菜", owner=None):
    e = projects.create(title, "feature", game="overcooked2", **({"owner": owner} if owner else {})); T = Thread(Path(e["path"]))
    tools = T.root / "4_design" / "tools"; tools.mkdir(parents=True, exist_ok=True)
    (tools / "gen_meshy3d.py").write_text("raise SystemExit('must never run in tests')\n", encoding="utf-8")
    return e, T


def cards(T, perm="yes", go="start"):
    p = T.card({"kind": "permission", "key": "perm-meshy", "title": "发给 Meshy？", "to": "Meshy", "will_send": ["2 张参考图"], "will_not_send": ["人脸"]})
    g = T.card({"kind": "go", "key": "go-meshy", "title": "开工做 2 个模型", "milestone": "m1", "items": ["鱼蛋", "烧卖"]})
    if perm: T.answer(p["id"], {"decision": perm})
    if go: T.answer(g["id"], {"decision": go})
    return p, g


def daemon(gs, spawn=None):
    def nospawn(*a, **k): raise AssertionError("no agent run in this test")
    return agentd.Agentd(claude="/bin/false", spawn=spawn or nospawn, quiet=True, gen_spawn=gs)


def notes(T): return [json.loads(f.read_text(encoding="utf-8"))["text"] for f in agentd.inbox(T)]


def run_once(T, gs=None):
    gs = gs or GenSpawn(); D = daemon(gs); D._gen(None, T); D.wait_gens(); return D, gs


# ---------------------------------------------------------------- the deny list (Claude Code: the pattern is a glob on the whole command)
def denied(cmd: str) -> bool:
    for rule in agentd.DENY:
        m = re.fullmatch(r"Bash\((.*)\)", rule, re.S); pat = "".join(".*" if ch == "*" else re.escape(ch) for ch in m.group(1))
        if re.fullmatch(pat, cmd, re.S): return True
    return False


@pytest.mark.parametrize("cmd", [
    'gameanything gen request --project "$PWD" --tool meshy3d --permission perm-meshy --go go-meshy',
    '/root/x/.venv/bin/m2w gen request --project /p --tool hkfood_v2 --permission p1 --go g1 --arg=--redo --arg yuk',
    'gameanything agentd request --project "$P" --kind gen_request_ready --text "两张卡都点了" --details \'{"script":"4_design/tools/gen_meshy3d.py","args":["g1"],"permission_key":"p","go_key":"g"}\'',
    'gameanything gen status --project "$P"', 'cat 4_design/tools/gen_meshy3d.py', 'ls 4_design/tools/',
])
def test_handoff_commands_are_allowed(cmd):
    assert not denied(cmd)


@pytest.mark.parametrize("cmd", [
    "python 4_design/tools/gen_x.py", "python3 4_design/tools/gen_meshy3d.py /p g1", "/root/x/.venv/bin/python /p/4_design/tools/gen_x.py /p",
    "cd 4_design/tools && python gen_x.py", "uv run 4_design/tools/gen_x.py", "py 4_design\\tools\\gen_x.py", "nohup python -u gen_x.py &",
    "chmod +x 4_design/tools/gen_x.py", "python /srv/lab/scripts/run-gen-request.py", "python -m gameanything.genrun",
    "docker run x",
])
def test_running_a_gen_script_is_denied(cmd):
    assert denied(cmd)


# ---------------------------------------------------------------- queue (the resident's side)
def test_request_queues_only(tmp_path):
    _, T = project()
    assert cli.main(["gen", "request", "--project", str(T.root), "--tool", "meshy3d", "--permission", "perm-meshy", "--go", "go-meshy", "--arg=--redo"]) == 0
    (q,) = genrun.pending(T.root); d = json.loads(q.read_text(encoding="utf-8"))
    assert d["script"] == "4_design/tools/gen_meshy3d.py" and d["args"] == ["--redo"] and d["go"] == "go-meshy"
    for bad in ("../x", "gen_a/../../b", "Meshy", ""):
        with pytest.raises(genrun.GenError): genrun.request(T.root, bad, "p", "g")
    with pytest.raises(genrun.GenError): genrun.request(T.root, "meshy3d", "", "g")


def test_old_gen_request_ready_goes_into_the_queue(tmp_path, monkeypatch):
    _, T = project(); monkeypatch.setenv("GAMEANYTHING_PARENT_REQUESTS", str(tmp_path / "req"))
    det = {"script": "4_design/tools/gen_meshy3d.py", "args": ["go-meshy"], "permission_key": "perm-meshy", "go_key": "go-meshy"}
    assert cli.main(["agentd", "request", "--project", str(T.root), "--kind", "gen_request_ready", "--text", "图可以画了", "--details", json.dumps(det)]) == 0
    assert not list((tmp_path / "req").glob("*.json")) and len(genrun.pending(T.root)) == 1
    # a file an older m2w wrote into the requests dir: agentd converts it
    (tmp_path / "req").mkdir(exist_ok=True)
    (tmp_path / "req" / "x-1.json").write_text(json.dumps({"kind": "gen_request_ready", "path": str(T.root), "text": "t", "details": det}), encoding="utf-8")
    (tmp_path / "req" / "x-2.json").write_text(json.dumps({"kind": "gen_request_ready", "path": str(T.root), "text": "t",
                                                           "details": {**det, "script": "../../evil/gen_x.py"}}), encoding="utf-8")
    (tmp_path / "req" / "x-3.json").write_text(json.dumps({"kind": "build_start", "path": str(T.root), "text": "t"}), encoding="utf-8")
    daemon(GenSpawn())._old_gen_requests()
    assert len(genrun.pending(T.root)) == 2 and [f.name for f in (tmp_path / "req").glob("*.json")] == ["x-3.json"]
    assert sorted(f.name for f in (tmp_path / "req" / "converted").glob("*.json")) == ["x-1.json", "x-2.json"]
    assert any("4_design/tools/gen_<名字>.py" in n for n in notes(T))


# ---------------------------------------------------------------- checks
@pytest.mark.parametrize("perm,go,why", [(None, "start", "许可卡"), ("no", "start", "许可卡"), ("yes", None, "开工卡"), ("yes", "wait", "开工卡")])
def test_both_cards_required(perm, go, why):
    _, T = project(); cards(T, perm, go); genrun.request(T.root, "meshy3d", "perm-meshy", "go-meshy")
    _, gs = run_once(T)
    assert gs.calls == [] and genrun.pending(T.root) == []
    (n,) = notes(T); assert "没有执行" in n and why in n
    assert len(list((genrun.queue_dir(T.root) / "rejected").glob("*.json"))) == 1


def test_latest_answer_counts_and_card_ids_work():
    _, T = project(); p, g = cards(T); T.answer(g["id"], {"decision": "wait"})            # pressed start, then changed her mind
    with pytest.raises(genrun.GenError, match="开工"): genrun.check(T.root, {"tool": "meshy3d", "permission": p["id"], "go": g["id"]})
    T.answer(g["id"], {"decision": "start"})
    s, args, gid = genrun.check(T.root, {"tool": "meshy3d", "permission": p["id"], "go": "go-meshy", "args": [str(T.root), "x"]})
    assert gid == g["id"] and args == [str(T.root), "x"] and s.name == "gen_meshy3d.py"


def test_script_must_stay_inside_tools(tmp_path):
    _, T = project(); cards(T)
    outside = T.root / "4_design" / "gen_evil.py"; outside.write_text("x", encoding="utf-8")
    (tmp_path / "gen_elsewhere.py").write_text("x", encoding="utf-8")
    if CAN_SYMLINK: (T.root / "4_design" / "tools" / "gen_link.py").symlink_to(tmp_path / "gen_elsewhere.py")
    for tool, msg in (("link", "4_design/tools") if CAN_SYMLINK else ("link", "找不到脚本"), ("missing", "找不到脚本"), ("../evil", "工具名")):
        with pytest.raises(genrun.GenError, match=msg): genrun.check(T.root, {"tool": tool, "permission": "perm-meshy", "go": "go-meshy"})
    q = genrun.queue_dir(T.root); q.mkdir(parents=True, exist_ok=True)
    (q / "evil.json").write_text(json.dumps({"id": "evil", "tool": "../evil", "permission": "perm-meshy", "go": "go-meshy"}), encoding="utf-8")
    _, gs = run_once(T); assert gs.calls == [] and "没有执行" in notes(T)[0]


# ---------------------------------------------------------------- running
def test_runs_once_per_go_card_and_notifies_done():
    _, T = project(); cards(T)
    genrun.request(T.root, "meshy3d", "perm-meshy", "go-meshy", ["--redo"])
    D, gs = run_once(T)
    (c,) = gs.calls
    assert c["cmd"][0] == sys.executable and c["cmd"][1] == str(T.root / "4_design" / "tools" / "gen_meshy3d.py") and c["cmd"][2:] == [str(T.root), "--redo"]
    (n,) = notes(T); assert "已完成" in n and "made 2 models" in n
    rec = genrun.used(T.root); (r,) = rec.values(); assert r["state"] == "done" and r["rc"] == 0
    assert "made 2 models" in Path(r["log"]).read_text(encoding="utf-8", errors="replace") and Path(r["log"]).is_relative_to(D.log_root)
    assert genrun.pending(T.root) == [] and len(list((genrun.queue_dir(T.root) / "done").glob("*.json"))) == 1
    # the same go card again: refused, nothing runs
    for f in agentd.inbox(T): f.unlink()
    genrun.request(T.root, "meshy3d", "perm-meshy", "go-meshy")
    _, gs2 = run_once(T); assert gs2.calls == []
    (n,) = notes(T); assert "已经用过一次" in n and "新的开工卡" in n


def test_failed_run_notifies_and_key_is_redacted(monkeypatch):
    monkeypatch.setenv("MESHY_API_KEY", SECRET)
    _, T = project(); cards(T); genrun.request(T.root, "meshy3d", "perm-meshy", "go-meshy")
    _, gs = run_once(T, GenSpawn(rc=3))
    (n,) = notes(T); assert "没有成功" in n and "退出码 3" in n and SECRET not in n
    (r,) = genrun.used(T.root).values(); assert r["state"] == "failed" and SECRET not in Path(r["log"]).read_text(encoding="utf-8", errors="replace")


def test_one_at_a_time_and_the_tick_starts_the_agent_after(monkeypatch):
    _, T = project(); cards(T)
    T.append({"from": "agent", "type": "text", "text": "好的", "source": "terminal"})
    genrun.request(T.root, "meshy3d", "perm-meshy", "go-meshy"); genrun.request(T.root, "meshy3d", "perm-meshy", "go-meshy")
    calls = []
    def spawn(cmd, cwd, env, log):
        calls.append(cmd); return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    gs = GenSpawn(); D = daemon(gs, spawn)
    try:
        D.tick(); D.tick()                       # the 2nd scan runs no 2nd gen while... the first is finished or running; never two at once
        D.wait_gens(); D.tick(); D.wait_gens(); D.tick()
        assert len(gs.calls) == 1, "the second request with the same go card is refused, not run"
        assert calls, "the outcome note starts an agent run"
    finally:
        r = agentd._read(agentd.run_path(T)) or {}
        if r.get("pid"): agentd._stop(r["pid"])


def test_owner_env_on_a_hub(monkeypatch):
    home = Path.home()
    monkeypatch.setenv("MESHY_API_KEY", "supervisor-meshy-key"); monkeypatch.setenv("ANTHROPIC_API_KEY", "supervisor-key")
    users.add_user("alice", "alice-pass-123", True, "Alice", home / "alice" / "m2w", home / ".claude")                 # default login
    envf = home / "bob.env"; envf.write_text("MESHY_API_KEY=bobs-own-meshy-key\n", encoding="utf-8")
    users.add_user("bob", "bob-pass-4567", False, "Bob", home / "bob" / "m2w", home / "bob" / ".claude-m2w", env_file=envf)   # no Claude login
    _, Ta = project("A", owner="alice"); _, Tb = project("B", owner="bob"); _, Tn = project("N")
    for T in (Ta, Tb, Tn): cards(T); genrun.request(T.root, "meshy3d", "perm-meshy", "go-meshy")
    ea = run_once(Ta)[1].calls[0]["env"]; eb = run_once(Tb)[1].calls[0]["env"]
    assert ea["MESHY_API_KEY"] == "supervisor-meshy-key" and ea["GAMEANYTHING_USER"] == "alice"
    assert eb["MESHY_API_KEY"] == "bobs-own-meshy-key" and eb["GAMEANYTHING_USER"] == "bob" and eb["GAMEANYTHING_KEYS_FILE"] == str(envf)
    assert "ANTHROPIC_API_KEY" not in eb, "the supervisor's keys never reach another user's run"
    _, gs = run_once(Tn); assert gs.calls == [] and "所有者" in notes(Tn)[0]


def test_interrupted_run_of_an_earlier_daemon_is_closed():
    _, T = project(); cards(T)
    p = subprocess.Popen([sys.executable, "-c", "pass"]); p.wait(10)
    genrun._record(T.root, "e_x", state="running", pid=p.pid, host=genrun.HOST, script="gen_meshy3d.py", log="/l")
    assert not genrun.busy_elsewhere(T.root)
    assert genrun.used(T.root)["e_x"]["state"] == "interrupted" and "中断" in notes(T)[0]
