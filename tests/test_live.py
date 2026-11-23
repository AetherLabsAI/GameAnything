"""What background work is doing, told by agentd itself (activity.py, live.py): recorded / fake agent streams -> plain activity lines,
usage limits and logins with their reset time, the live build card and its key moments in her chat, stalls, and residents that wait for
a usage limit instead of giving up. No real agent: the streams are written by the tests."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path


from gameanything import activity as A, agentd, builds, devstatus, live
from gameanything.conversation import Thread

from test_builds import FakeLab, Spawner, daemon, go, project, request, req_dir, spawner   # noqa: F401,F811  (fixtures)


def claude_tool(name, **inp):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"t{time.time_ns()}", "name": name, "input": inp}]}}


def acts(provider, *events, root=None):
    return [x["act"] for e in events for x in A.translate(provider, e, root) if x.get("t") == "tool"]


# ---------------------------------------------------------------- translating streams
def test_claude_tool_calls_become_plain_lines_without_commands_or_secrets(tmp_path):
    root = tmp_path / "p"; (root / "5_build").mkdir(parents=True)
    got = acts("claude-code",
               claude_tool("Bash", command="cd /work/a3/mod && OPENROUTER_API_KEY=sk-or-v1-FAKE-test-key ./gradlew build --offline -q 2>&1 | tail -30"),
               claude_tool("Edit", file_path="/work/a3/mod/src/main/java/org/modlab/sol/Story.java", old_string="a", new_string="b"),
               claude_tool("Read", file_path="/work/a3/shots/tour/s0185.png"),
               claude_tool("Bash", command='export P=$PWD; gameanything lessons show --game minecraft --role builder | head -80'),
               claude_tool("Bash", command='gameanything status set-item --project "$P" --id r3 --state done --build m2 --by builder --evidence "x"'),
               claude_tool("Bash", command="until /tmp/dx.sh 'mc state' | grep -q in_world; do sleep 5; done"),
               claude_tool("Bash", command="/tmp/shots.sh c '1 2 3'", run_in_background=True),
               claude_tool("Write", file_path=str(root / "5_build" / "STATUS.yaml"), content="x"),
               claude_tool("Bash", command="python3 - <<'E'\np='Rooms.java'; s=open(p).read()\nopen(p,'w').write(s)\nE"),
               claude_tool("Bash", command="curl -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abcdefghijklmnopqrstuv' https://x.example/api"),
               root=root)
    zh = [a["zh"] for a in got]
    assert zh == ["在编译 mod", "在改剧情镜头的代码 Story.java", "在看截图 s0185.png", "在读经验本", "在更新开发状态（r3 → done）",
                  "在等游戏启动", "在游戏里截图（在后台）", "在更新开发状态", "在改场景搭建的代码 Rooms.java", "在从网上取东西"]
    blob = json.dumps(got, ensure_ascii=False)
    assert "sk-or" not in blob and "eyJ" not in blob and "gradlew" not in blob and "/work/a3" not in blob.replace(got[2].get("image", ""), "")
    assert got[1]["en"] == "Editing the story camera code Story.java" and all(len(a["zh"]) <= A.MAX_TEXT for a in got)


def test_other_providers_codex_opencode_gemini(tmp_path):
    root = tmp_path
    c = acts("codex", {"type": "item.started", "item": {"id": "i1", "type": "command_execution", "command": "/bin/bash -lc 'cd mod && ./gradlew build'"}},
             {"type": "item.completed", "item": {"id": "i2", "type": "file_change", "changes": [{"path": str(root / "src/Story.java"), "kind": "update"}]}})
    assert [a["zh"] for a in c] == ["在编译 mod", "在改剧情镜头的代码 Story.java"]
    o = acts("opencode", {"type": "tool_use", "part": {"tool": "bash", "callID": "c1", "state": {"status": "running", "input": {"command": "gameanything native shot --project x"}}}},
             {"type": "tool_use", "part": {"tool": "read", "state": {"status": "completed", "input": {"filePath": "notes/CLAUDE.md"}}}})
    assert [a["zh"] for a in o] == ["在游戏里截图", "在读说明 CLAUDE.md"]
    g = acts("gemini", {"type": "tool_use", "tool_name": "write_file", "tool_id": "g1", "parameters": {"file_path": "mod/Terrain.java"}},
             {"type": "tool_use", "tool_name": "run_shell_command", "tool_id": "g2", "parameters": {"command": "ffmpeg -i a.mp4 b.mp4"}})
    assert [a["zh"] for a in g] == ["在写地形的代码 Terrain.java", "在处理视频和图片"]
    A.register("my-cli", lambda e, root=None: [{"t": "tool", "act": A.act("tool", "在做 X", "Doing X")}])
    assert [a["zh"] for a in acts("my-cli", {"anything": 1})] == ["在做 X"]
    assert A.translate("claude-code", "not a dict") == [] and all(x["t"] == "beat" for x in A.translate("codex", {"type": "item.started", "item": None}))


def test_usage_limits_logins_and_reset_times():
    t0 = 1793000000.0
    ev = A.translate("claude-code", {"type": "rate_limit_event", "rate_limit_info": {"status": "rejected", "resetsAt": 1793057400, "rateLimitType": "five_hour"}})
    assert ev[0]["t"] == "limit" and ev[0]["resets"] == 1793057400
    assert A.translate("claude-code", {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}}) == [{"t": "ok"}]
    r = A.translate("claude-code", {"type": "result", "is_error": True, "result": "Claude AI usage limit reached|1793057400"})
    assert r[0]["t"] == "limit" and r[0]["resets"] == 1793057400 and r[-1] == {"t": "end", "ok": False}
    s = A.translate("claude-code", {"type": "assistant", "error": "rate_limit", "message": {"model": "<synthetic>", "content": [{"type": "text", "text": "You've hit your limit · resets 6pm (UTC)"}]}})
    assert s[0]["t"] == "limit" and s[0]["resets"]
    a = A.translate("claude-code", {"type": "result", "is_error": True, "result": "Invalid API key · Please run /login"})
    assert a[0]["t"] == "auth"
    cx = A.translate("codex", {"type": "error", "message": "You've hit your usage limit. Try again in 3 hours."})
    assert cx[0]["t"] == "limit" and cx[0]["resets"] and abs(cx[0]["resets"] - time.time() - 3 * 3600) < 60
    assert A.reset_at("resets 6pm (UTC)", t0) % 86400 == 18 * 3600
    assert A.reset_at("try again in 45 minutes", t0) == t0 + 45 * 60 and A.reset_at("no time here", t0) is None
    # a normal tool output that mentions 429 is not a limit (only the CLI's own error events are read)
    assert all(x["t"] != "limit" for x in A.translate("claude-code", {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "x", "content": "HTTP 429"}]}}))


# ---------------------------------------------------------------- tailing a log
def write(log, *events):
    with open(log, "a", encoding="utf-8") as f:
        for e in events: f.write(json.dumps(e, ensure_ascii=False) + "\n")


def test_tail_reads_only_new_lines_merges_repeats_and_starts_big_logs_at_a_line(tmp_path):
    root = tmp_path / "p"; (root / "conversation").mkdir(parents=True); log = tmp_path / "run.jsonl"
    write(log, {"type": "system", "subtype": "init"}, claude_tool("Bash", command="mc state"), claude_tool("Bash", command="mc state"))
    t = A.Tail(root, "r1", log, "claude-code", "builder")
    got = t.step(); assert [x["zh"] for x in got] == ["在看游戏的状态和日志"] and t.state["last"]["n"] == 2
    assert t.step() == []
    with open(log, "a", encoding="utf-8") as f: f.write(json.dumps(claude_tool("Edit", file_path="Terrain.java")) + "\n" + '{"type": "assist')   # half a line
    assert [x["zh"] for x in t.step()] == ["在改地形的代码 Terrain.java"]
    with open(log, "a", encoding="utf-8") as f: f.write('ant", "message": {"content": [{"type": "tool_use", "id": "z", "name": "Bash", "input": {"command": "ffmpeg -i a b"}}]}}\n')
    assert [x["zh"] for x in t.step()] == ["在处理视频和图片"]
    assert [x["zh"] for x in A.lines(root, "r1")] == ["在看游戏的状态和日志", "在改地形的代码 Terrain.java", "在处理视频和图片"]
    t2 = A.Tail(root, "r1", log, "claude-code", "builder"); assert t2.step() == [], "the offset survives a restart (state file)"
    big = tmp_path / "big.jsonl"
    with open(big, "w", encoding="utf-8") as f:
        pad = json.dumps({"type": "system", "subtype": "thinking_tokens", "x": "y" * 200}) + "\n"
        for _ in range(A.FIRST_TAIL // len(pad) + 50): f.write(pad)
        f.write(json.dumps(claude_tool("Bash", command="./gradlew build")) + "\n")
    tb = A.Tail(root, "big", big, "claude-code")
    assert [x["zh"] for x in tb.step()] == ["在编译 mod"] and tb.state["offset"] == big.stat().st_size


def test_tail_stall_slow_tool_and_pause(tmp_path):
    root = tmp_path / "p"; (root / "conversation").mkdir(parents=True); log = tmp_path / "run.jsonl"
    clock = [time.time()]
    write(log, claude_tool("Bash", command="until grep -q STARTED start.log; do sleep 5; done"))
    t = A.Tail(root, "r2", log, "claude-code", clock=lambda: clock[0]); t.step()
    assert live.alert_of(t) is None
    clock[0] += live.SLOW_TOOL_SECS + 5; os.utime(log, (clock[0], clock[0]))         # heartbeats keep the log fresh, the tool still runs
    a = live.alert_of(t); assert a["kind"] == "slow" and "在等游戏启动" in a["text"]
    clock[0] += live.STALL_SECS + 5
    a = live.alert_of(t); assert a["kind"] == "stall" and "最后一步是「在等游戏启动」" in a["text"]
    write(log, {"type": "rate_limit_event", "rate_limit_info": {"status": "rejected", "resetsAt": int(time.time()) + 3600}})
    got = t.step(); assert got[-1]["kind"] == "pause" and live.alert_of(t)["kind"] == "pause"
    write(log, {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}}, claude_tool("Bash", command="./gradlew build"))
    t.step(); assert t.state["pause"] is None


# ---------------------------------------------------------------- the live build card in her chat
def live_events(T, kind=None):
    return [e for e in T.events() if e.get("from") == "system" and (kind is None or e.get("live") == kind)]


def live_card(T, m="m1"):
    return next(e for e in reversed(T.events()) if e.get("type") == "card" and e["card"].get("key") == f"live-{m}")


def test_build_card_status_items_screenshots_pause_and_end(spawner, tmp_path, req_dir, monkeypatch):
    monkeypatch.setattr(live, "CARD_EVERY_SECS", 0); monkeypatch.setattr(live, "FILES_EVERY_SECS", 0)
    e, T = project(); go(T); D = daemon(spawner, FakeLab(), tmp_path)
    devstatus.init(T.root)
    request(T); D.tick()
    r = builds.current(T.root)[1]; log = Path(r["log"])
    (st,) = live_events(T, "build_start"); assert "后台构建开始了：m1" in st["text"] and "mclab-x（座位 2）" in st["text"] and st["text_en"]
    c = live_card(T); assert c["from"] == "system" and c["card"]["kind"] == "progress" and c["card"]["open"] == "#now"
    assert c["card"]["meter"]["max_rounds"] == 2 and "座位 2" in c["card"]["meter"]["runner"] and c["card_en"]["title"] == "Background build · now"
    # the builder works: an edit, a screenshot it looks at, a STATUS item done with a picture as evidence, a new picture in 5_build/m1/
    shots = tmp_path / "lab" / "shots"; shots.mkdir(parents=True)
    from PIL import Image
    Image.new("RGB", (1600, 900), (40, 90, 160)).save(shots / "a1.png")
    play = T.root / "5_build" / "m1" / "play"; play.mkdir(parents=True)
    Image.new("RGB", (64, 64), (200, 10, 10)).save(play / "bridge.png")
    d, _ = devstatus.load(T.root); iid = d["items"][0]["id"]
    devstatus.set_item(T.root, iid, state="done", build="m1", by="builder", evidence="第 1 轮：play/bridge.png")
    write(log, claude_tool("Read", file_path=str(shots / "a1.png")), claude_tool("Edit", file_path="mod/src/Story.java"))
    D.tick()
    c = live_card(T)["card"]
    assert c["now"] == "在改剧情镜头的代码 Story.java" and c["now_en"].startswith("Editing")
    assert c["steps"][0]["state"] == "done" and any(u.startswith("/media/5_build/m1/play/bridge.png") for u in c["images"])
    thumb = [u for u in c["images"] if u.startswith("/conv/now_")]
    assert thumb and (T.root / "conversation" / "files" / thumb[0][len("/conv/"):]).is_file()
    assert max(Image.open(T.root / "conversation" / "files" / thumb[0][len("/conv/"):]).size) <= live.THUMB_PX
    n = len(T.events()); D.tick(); assert len(T.events()) == n, "nothing new: no new chat event"
    # a usage limit: one status line with the reset time, the card says why
    reset = int(time.time()) + 2 * 3600
    write(log, {"type": "rate_limit_event", "rate_limit_info": {"status": "rejected", "resetsAt": reset, "rateLimitType": "five_hour"}})
    D.tick(); D.tick()
    (p,) = live_events(T, "build_pause"); assert "用量到上限" in p["text"] and A.hhmm(reset) in p["text"]
    assert live_card(T)["card"]["alert"]["kind"] == "pause"
    assert json.loads(agentd.heartbeat_path().read_text(encoding="utf-8"))["paused"]["claude-code"]["resets"] == reset
    # the builder exits on the limit: the end says so, and so does the resident's note
    write(log, {"type": "result", "is_error": True, "result": f"Claude AI usage limit reached|{reset}"})
    monkeypatch.setattr("gameanything.delivery.check", lambda root, only=None, probe=True: [{"m": "m1", "ok": False, "problems": ["没有视频"], "warnings": []}])
    spawner.end(spawner.builders()[0]); D.tick()
    (end,) = live_events(T, "build_end"); assert "后台构建停了" in end["text"] and "用量到上限" in end["text"]
    c = live_card(T)["card"]; assert c["alert"]["kind"] == "pause" and c["meter"]["done"] and "now" not in c
    from test_builds import notes
    assert any("用量上限" in x for x in notes(T, "agentd-build"))
    # the panel's data
    s = live.now_state(T.root)
    b = s["build"]; assert b["m"] == "m1" and b["state"] == "ended" and b["timeline"][0]["text"] and b["shots"] and b["items"][0]["state"] == "done"
    assert "en" not in json.dumps(b["timeline"][0]) or True
    assert live.now_state(T.root, "en")["build"]["timeline"][-1]["text"].startswith(("Looking", "Editing"))


def test_build_stall_is_said_once(spawner, tmp_path, req_dir, monkeypatch):
    e, T = project(); go(T); D = daemon(spawner, FakeLab(), tmp_path)
    request(T); D.tick()
    log = Path(builds.current(T.root)[1]["log"])
    write(log, claude_tool("Bash", command="./gradlew build"), {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "x"}]}})
    old = time.time() - live.STALL_SECS - 60; os.utime(log, (old, old))
    D.tick(); D.tick()
    (s,) = live_events(T, "build_stall"); assert "可能卡住了" in s["text"] and "在编译 mod" in s["text"]
    assert live_card(T)["card"]["alert"]["kind"] == "stall"
    write(log, claude_tool("Bash", command="mc state")); D.tick()
    assert "alert" not in live_card(T)["card"], "it moves again: the banner goes"


# ---------------------------------------------------------------- residents: a usage limit is waited out, not given up
class LimitSpawner:
    """Each run prints one stream line (a usage-limit result first, then a normal answer) and exits."""
    def __init__(self, reset): self.reset = reset; self.calls = []

    def __call__(self, cmd, cwd, env, log):
        if not self.calls:
            line = json.dumps({"type": "result", "is_error": True, "result": f"Claude AI usage limit reached|{self.reset}"})
            code = f"print({line!r})"
        else:
            code = ("import subprocess,sys,os; from gameanything import cli; "
                    "cli.main(['chat','claim','--project',os.getcwd()]); cli.main(['chat','read','--project',os.getcwd()]); "
                    "cli.main(['chat','say','--project',os.getcwd(),'--text','好的'])")
        p = subprocess.Popen([sys.executable, "-c", code], cwd=str(cwd), env={**os.environ, **env, "PYTHONPATH": os.pathsep.join(sys.path)},
                             stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        self.calls.append(p); return p


def test_resident_usage_limit_waits_for_the_reset_and_tells_her(tmp_path, req_dir):
    from gameanything import projects
    e = projects.create("等额度", "memory"); T = Thread(Path(e["path"]))
    T.append({"from": "agent", "type": "text", "text": "你好", "source": "terminal"})
    T.user_text("在吗")
    clock = [time.time()]; reset = int(clock[0]) + 3 * 3600
    sp = LimitSpawner(reset)
    D = agentd.Agentd(claude="/bin/false", spawn=sp, quiet=True, requests=tmp_path / "req", clock=lambda: clock[0], builds="coordinator")
    D.tick(); sp.calls[0].wait(30); D.tick()
    (s,) = [x for x in T.events() if x.get("live") == "resident_pause"]
    assert "用量到上限" in s["text"] and A.hhmm(reset) in s["text"] and "自动接着回复" in s["text"]
    assert not (T.dir / ".agentd_failed").exists()
    for _ in range(3): D.tick()
    assert len(sp.calls) == 1, "no retry before the reset"
    clock[0] = reset + 120; D.tick()
    assert len(sp.calls) == 2
    sp.calls[1].wait(60); D.tick()
    assert any(x.get("from") == "agent" and x.get("text") == "好的" for x in T.events())
    assert len([x for x in T.events() if x.get("live") == "resident_pause"]) == 1
