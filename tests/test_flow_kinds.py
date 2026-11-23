"""Phase 2 of the flow state machine: memory / feature / gameplay as real steps with exit criteria. A simulated user walks a new project of
each kind from the first step to the build_start request (and on into the next version), asserting the step to work on and the action
due at each step; agentd's corrective re-run fires when a required card is missing. No real agent, no model call."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from conftest import her_clicks

from gameanything import agentd, cli, flow, projects, sandbox, setupguide
from gameanything.conversation import Thread
from gameanything.ui import onboard


# ---------------------------------------------------------------- helpers
def nxt(root): return flow.next_step(root)


def card(root, T, c, en=True):
    """A card as the agent sends it (`gameanything chat card` stamps the flow step); en=False: a card without English."""
    c = dict(c)
    if en: c.setdefault("en", {"title": "x"})
    return T.card(c, flow_step=cli._flow_step(root))


def wy(root, rel, data):
    f = Path(root) / rel; f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if str(rel).startswith("feedback/"): her_clicks(root)            # her review written here stands for her click on the page (decisions.py)
    return f


def inbox(root, name="a.jpg"):
    (root / "0_inbox").mkdir(exist_ok=True); (root / "0_inbox" / name).write_bytes(b"x")
    wy(root, "feedback/ingest_request.yaml", {"state": "pending", "files": [{"path": name}]})


def ingest(root, kind="photo", n=2):
    wy(root, "1_ingest/pack.yaml", {"items": [{"id": f"{kind}_{i}", "kind": kind, "file": f"0_inbox/a{i}." + ("jpg" if kind == "photo" else "txt"), "included": True} for i in range(n)]})
    wy(root, "feedback/ingest_request.yaml", {"state": "done"})


def plan(root, ms):
    wy(root, "4_design/world_plan.yaml", {"world_plan": {"title": "x", "milestones": ms}})


def picture(root, rel="4_design/previews/a.png"):
    f = root / rel; f.parent.mkdir(parents=True, exist_ok=True); f.write_bytes(b"\x89PNG"); return "/media/" + rel


EST = {"wall_h": [1, 2], "cost_usd": None, "account": "subscription"}
GO = {"kind": "go", "key": "m1-go", "milestone": "m1", "title": "第 1 版", "items": ["花拱门"], "estimate": EST,
      "runners": [{"id": "claude-code:sonnet", "harness": "Claude Code", "model": "Sonnet", "estimate": EST}]}


def press_start(root, T, go):
    T.answer(go["id"], {"decision": "start", "runner": "claude-code:sonnet"})


def build_request(root, m="m1"):
    agentd.write_request(root, "build_start", "开工", {"milestone": m, "go_key": f"{m}-go"})


def deliver(root, m="m1", status="built"):
    ms = (yaml.safe_load((root / "4_design" / "world_plan.yaml").read_text(encoding="utf-8")) or {})["world_plan"]["milestones"]
    ms[m]["status"] = status; plan(root, ms)
    wy(root, f"5_build/{m}/play/play.yaml", {"milestone": m, "video": "video.mp4"})


def result(root, T, m="m1"):
    return card(root, T, {"kind": "result", "milestone": m, "title": f"{m} 做好了", "open": f"#play/{m}"})


NEXT = {"kind": "options", "key": "next-round", "title": "下一版做什么？", "items": [{"key": "fix", "title": "修三处", "recommended": True},
                                                                                    {"key": "keep", "title": "带回家"}]}


def stepper(root): return onboard.flow_state(root)


def read_setup(root):
    """What `gameanything setup guide --project P` records (on a Linux computer with Docker)."""
    setupguide.record(root, setupguide.info(root, machine=sandbox.machine("linux")))


# ---------------------------------------------------------------- memory: new project -> build_start -> the next version
def test_memory_simulated_user_to_build_and_next_version():
    e = projects.create("婚礼", "memory", game="stardew"); root = Path(e["path"]); T = Thread(root)
    n = nxt(root); assert n["todo"] == "gather" and n["waiting_for"] == "user" and n["opted_in"]
    assert stepper(root)["current"] == "gather"

    inbox(root)
    n = nxt(root); assert n["todo"] == "ingest" and any("gameanything ingest" in a for a in n["actions"])
    assert stepper(root)["next"]["hint"] == "agent 正在整理你的素材"

    ingest(root)                                                            # photos: the model may look only after a yes
    n = nxt(root); assert n["todo"] == "perceive" and n["card_required"] == ["permission_card"]
    p = card(root, T, {"kind": "permission", "key": "perceive", "title": "让模型看你的照片", "will_send": ["缩小的照片"], "will_not_send": ["原图"], "to": "模型"})
    n = nxt(root); assert n["waiting_for"] == "user" and not n["actions"] and n["later"]       # gameanything perceive is due only after her yes
    assert stepper(root)["next"]["label"] == "在对话里点同意"
    T.answer(p["id"], {"decision": "yes"})
    n = nxt(root); assert n["todo"] == "perceive" and any("gameanything perceive" in a for a in n["actions"]) and not n["card_required"]
    wy(root, "2_perceive/cards/photo_0.json", {"caption": "x"})

    n = nxt(root); assert n["todo"] == "people" and n["card_required"] == ["people_card"]
    t = card(root, T, {"kind": "task", "key": "people-tag", "title": "给照片里的人起名字", "body": "去标", "open": "#people/tag"})
    assert stepper(root)["next"] == {"label": "标记照片里的人", "route": "people", "wait": False, "hint": ""}
    T.answer(t["id"], {"done": True})

    n = nxt(root); assert n["todo"] == "board" and n["card_required"] == ["board_card"] and any("board.yaml" in a for a in n["actions"])
    wy(root, "3_remember/board.yaml", {"experience_board": {"moments": [{"id": "m1", "title": "仪式"}]}})
    card(root, T, {"kind": "task", "key": "board-review", "title": "确认这一天", "body": "去看", "open": "#board"})
    n = nxt(root); assert n["todo"] == "confirm_day" and n["waiting_for"] == "user"
    assert stepper(root)["next"] == {"label": "确认这一天", "route": "board", "wait": False, "hint": ""}

    wy(root, "feedback/board_review.yaml", {"state": "confirmed"})
    n = nxt(root); assert n["todo"] == "design" and n["card_required"] == ["plan_card"]
    assert stepper(root)["current"] == "plan" and stepper(root)["steps"][1]["state"] == "done"
    plan(root, {"m1": {"status": "next", "name": "第 1 版", "what": "仪式"}})
    assert nxt(root)["todo"] == "design"                                 # no items for the 方案 page yet
    wy(root, "5_build/m1/plan.yaml", {"items": [{"n": 1, "title": "仪式"}]})
    pc = card(root, T, {"kind": "options", "key": "plan", "title": "文字方案：第一版做什么？", "items": [{"key": "ok", "title": "按这个做"}, {"key": "change", "title": "我想改"}]})
    n = nxt(root); assert n["todo"] == "confirm_plan" and n["waiting_for"] == "user"
    T.answer(pc["id"], {"picked": ["ok"]})                                 # approval on an options card is recorded like 「就按这个做」
    rv = yaml.safe_load((root / "feedback" / "plan_review.yaml").read_text(encoding="utf-8"))
    assert rv["state"] == "confirmed" and rv["milestone"] == "m1" and rv["via"] == f"card {pc['id']}"

    n = nxt(root); assert n["todo"] == "preview" and n["card_required"] == ["permission_card"]
    perm = card(root, T, {"kind": "permission", "key": "preview-permission", "title": "画预览图", "will_send": ["文字"], "will_not_send": ["照片"], "to": "生图模型"})
    pgo = card(root, T, {**GO, "key": "preview-go", "title": "画 6 张预览图"})            # the drawing go card is not the build's
    st = stepper(root); assert st["current"] == "preview" and st["next"]["label"] != "在对话里点开工"
    T.answer(perm["id"], {"decision": "yes"}); press_start(root, T, pgo)
    n = nxt(root); assert n["todo"] == "preview" and n["card_required"] == ["candidates_card"]
    cand = card(root, T, {"kind": "candidates", "key": "preview-hall", "title": "大厅", "media": "image",
                          "items": [{"key": "A", "title": "A", "url": picture(root)}]})
    T.answer(cand["id"], {"picked": ["A"]})

    n = nxt(root); assert n["todo"] == "go" and n["card_required"] == ["go_card"]
    assert any("setup guide" in a for a in n["actions"]); read_setup(root)      # the setting guide first (setupguide.py)
    assert stepper(root)["next"]["hint"] == "agent 会在对话里给你一张开工卡"     # the pressed drawing go card did not start the build
    go = card(root, T, GO)
    n = nxt(root); assert n["todo"] == "go" and n["waiting_for"] == "user" and not n["actions"]
    assert not any("build_start" in a for a in n["actions"])                   # never due before she pressed 开工
    assert stepper(root)["next"]["label"] == "在对话里点开工"
    press_start(root, T, go)
    n = nxt(root); assert n["todo"] == "build" and any("build_start" in a for a in n["actions"])
    assert stepper(root)["current"] == "play"
    build_request(root)
    n = nxt(root); assert n["todo"] == "build" and n["waiting_for"] == "coordinator" and not n["actions"]

    deliver(root)
    n = nxt(root); assert n["card_required"] == ["result_card"]
    result(root, T)
    n = nxt(root); assert n["todo"] == "feedback" and n["card_required"] == ["next_card"]
    assert stepper(root)["next"]["label"] == "看试玩录像"
    nc = card(root, T, NEXT)
    assert nxt(root)["waiting_for"] == "user" and stepper(root)["next"]["label"] == "在对话里选下一版做什么"
    T.answer(nc["id"], {"picked": ["fix"]})
    n = nxt(root); assert n["todo"] == "next_round" and "status: next" in n["actions"][0]
    assert stepper(root)["next"]["label"] != "都完成了"

    ms = yaml.safe_load((root / "4_design" / "world_plan.yaml").read_text(encoding="utf-8"))["world_plan"]["milestones"]
    plan(root, {**ms, "m2": {"status": "next", "name": "第 2 版", "what": "修三处"}})   # version 2: back to design, earlier steps stay done
    wy(root, "5_build/m2/plan.yaml", {"items": [{"n": 1, "title": "修三处"}]})
    n = nxt(root); assert n["todo"] == "design" and n["round"] == {"n": 2, "milestone": "m2", "after": "m1"} and n["card_required"] == ["plan_card"]
    st = stepper(root); assert st["current"] == "plan" and [s["state"] for s in st["steps"]][:2] == ["done", "done"]
    fb = {r["id"]: r for r in flow.state(root)["steps"]}["feedback"]      # m1's 下一步 card opened m2; it is not m2's feedback
    assert not fb["strict"]
    u = card(root, T, {"kind": "understanding", "key": "plan", "title": "第 2 版方案", "points": [{"id": "a", "text": "修三处"}]})
    assert nxt(root)["todo"] == "confirm_plan"                             # plan_review of m1 does not confirm m2
    T.answer(u["id"], {"ok": True})
    assert yaml.safe_load((root / "feedback" / "plan_review.yaml").read_text(encoding="utf-8"))["milestone"] == "m2"
    n = nxt(root); assert n["todo"] == "preview"


def test_memory_without_photos_skips_perceive_and_people_and_old_projects_never_go_back():
    e = projects.create("回忆", "memory"); root = Path(e["path"])
    inbox(root, "notes.txt"); ingest(root, kind="document", n=1)
    assert nxt(root)["todo"] == "board"
    # an old project: confirmed before the flow knew these steps; later versions built -> nothing before them is reopened
    wy(root, "feedback/board_review.yaml", {"state": "confirmed"})
    plan(root, {"m1": {"status": "built"}, "m2": {"status": "built"}}); wy(root, "5_build/m2/play/play.yaml", {"milestone": "m2"})
    n = nxt(root); assert n["gaps"] == [] and set(n["done"]) >= {"gather", "board", "confirm_day", "design", "confirm_plan", "go"}
    assert n["todo"] == "build" and n["card_required"] == ["result_card"]


# ---------------------------------------------------------------- feature
def test_feature_simulated_user_to_build():
    e = projects.create("香港美食", "feature", game="overcooked2"); root = Path(e["path"]); T = Thread(root)
    assert nxt(root)["todo"] == "gather" and stepper(root)["next"]["label"] == "在对话里说你想加什么"
    T.user_text("想加一个茶餐厅关卡")
    n = nxt(root); assert n["todo"] == "questions" and n["card_required"] == ["questions_card"]   # no inbox: ingest is skipped
    q = card(root, T, {"kind": "questions", "key": "feature-questions", "title": "问 2 件事", "items": [{"n": 1, "text": "放在哪", "hint": "新关卡"}]})
    assert stepper(root)["next"]["label"] == "在对话里回答几个问题"
    T.answer(q["id"], {"answers": {"1": "新关卡"}})
    n = nxt(root); assert n["todo"] == "spec" and n["card_required"] == ["spec_card"] and any("feature.yaml" in a for a in n["actions"])
    wy(root, "3_remember/feature.yaml", {"title": "茶餐厅", "goal": "做菠萝包", "items": [{"id": "f1", "what": "菠萝包"}]})
    assert any("done_when" in a for a in nxt(root)["actions"])
    wy(root, "3_remember/feature.yaml", {"title": "茶餐厅", "goal": "做菠萝包", "items": [{"id": "f1", "what": "菠萝包", "how": "烤箱", "done_when": "能上菜"}]})
    card(root, T, {"kind": "understanding", "key": "spec", "title": "需求", "points": [{"id": "f1", "text": "菠萝包"}], "open": "#spec"})
    n = nxt(root); assert n["todo"] == "confirm_spec" and stepper(root)["next"]["label"] == "确认需求"
    wy(root, "feedback/feature_review.yaml", {"state": "confirmed"})
    n = nxt(root); assert n["todo"] == "plan" and stepper(root)["current"] == "plan"
    plan(root, {"m1": {"status": "next", "name": "第一版"}})
    pc = card(root, T, {"kind": "understanding", "key": "plan", "title": "第一版方案", "points": [{"id": "a", "text": "菠萝包"}]})
    T.answer(pc["id"], {"ok": True})
    n = nxt(root); assert n["todo"] == "go" and n["card_required"] == ["go_card"]
    art = card(root, T, {**GO, "key": "hk_art_go", "title": "用 Meshy 做 3 个 3D 菜品"})      # a Meshy go card: not the build's
    assert nxt(root)["card_required"] == ["go_card"] and stepper(root)["next"]["hint"] == "agent 会在对话里给你一张开工卡"
    press_start(root, T, art); assert nxt(root)["todo"] == "go"
    go = card(root, T, GO); press_start(root, T, go)
    n = nxt(root); assert n["todo"] == "build" and any("build_start" in a for a in n["actions"])
    build_request(root); assert nxt(root)["waiting_for"] == "coordinator"


# ---------------------------------------------------------------- gameplay
def test_gameplay_simulated_user_to_build():
    e = projects.create("PhD", "gameplay"); root = Path(e["path"]); T = Thread(root)
    assert nxt(root)["todo"] == "gather"
    T.user_text("读博五年")
    n = nxt(root); assert n["todo"] == "questions" and n["card_required"] == ["questions_card"]
    q = card(root, T, {"kind": "questions", "key": "gameplay-questions", "title": "问几件事", "items": [{"n": 1, "text": "每天做什么", "hint": "读论文"}]})
    T.answer(q["id"], {"answers": {}})
    n = nxt(root); assert n["todo"] == "mapping" and n["card_required"] == ["mapping_card"]
    wy(root, "3_remember/gameplay.yaml", {"mapping": [{"id": "m1", "experience": "失败的实验", "mechanic": "Insight"}], "core": {"loop": ["读论文"], "archetypes": [{"name": "A"}]}})
    n = nxt(root); assert any("流派" in a for a in n["actions"] if a.startswith("(提醒)"))     # fewer than 3 archetypes: a warning
    card(root, T, {"kind": "task", "key": "mechanics-review", "title": "去机制映射", "body": "逐条看", "open": "#mechanics"})
    n = nxt(root); assert n["todo"] == "confirm_mapping" and stepper(root)["next"]["label"] == "确认机制映射"
    wy(root, "feedback/gameplay_review.yaml", {"mapping": {"state": "confirmed"}})
    n = nxt(root); assert n["todo"] == "scope" and n["card_required"] == ["scope_card"] and stepper(root)["current"] == "content"
    sc = card(root, T, {"kind": "understanding", "key": "scope", "title": "第一版范围", "points": [{"id": "a", "text": "30 张卡"}]})
    assert stepper(root)["next"]["label"] == "在对话里确认第一版范围"
    T.answer(sc["id"], {"ok": True})
    G = yaml.safe_load((root / "3_remember" / "gameplay.yaml").read_text(encoding="utf-8"))
    wy(root, "3_remember/gameplay.yaml", {**G, "scope": {"cards": [25, 35]}})
    n = nxt(root); assert n["todo"] == "content" and n["card_required"] == ["content_card"]
    wy(root, "3_remember/gameplay.yaml", {**G, "scope": {"cards": [25, 35]}, "content": {"cards": [{"id": "rp", "name": "Read Papers", "text": "获得 2 Insight"}]}})
    card(root, T, {"kind": "task", "key": "content-review", "title": "去内容页", "body": "逐张看", "open": "#content"})
    assert nxt(root)["todo"] == "confirm_content"
    wy(root, "feedback/gameplay_review.yaml", {"mapping": {"state": "confirmed"}, "content": {"state": "confirmed"}})
    n = nxt(root); assert n["todo"] == "go" and any("world_plan" in a for a in n["actions"]) and n["card_required"] == ["go_card"]
    plan(root, {"m1": {"status": "next", "name": "第一版"}}); (root / "4_design" / "BRIEF.md").write_text("brief", encoding="utf-8")
    go = card(root, T, GO); press_start(root, T, go)
    n = nxt(root); assert n["todo"] == "build" and any("build_start" in a for a in n["actions"]) and stepper(root)["current"] == "balance"
    build_request(root); deliver(root); wy(root, "5_build/m1/balance/report.yaml", {"win_rate": 0.4})
    assert nxt(root)["card_required"] == ["result_card"] and stepper(root)["next"]["label"] == "看平衡和试玩"


# ---------------------------------------------------------------- warnings, docs, the CLI on every kind
def test_card_without_english_is_a_warning():
    e = projects.create("回忆", "memory"); root = Path(e["path"]); T = Thread(root); inbox(root); ingest(root)
    card(root, T, {"kind": "permission", "key": "perceive", "title": "看照片", "will_send": ["照片"], "will_not_send": ["原图"], "to": "模型"}, en=False)
    c = {x["id"]: x for x in flow.check(root, "perceive")["criteria"]}
    assert not c["card_english"]["ok"] and c["card_english"]["level"] == "warn" and "en:" in c["card_english"]["why"]


def test_every_step_of_every_kind_has_a_short_doc():
    for kind in ("memory", "feature", "gameplay", "adaptation"):
        for st in flow.steps_of(kind):
            p = flow.doc_path(kind, st["id"]); assert p.is_file(), p
            assert 400 <= len(p.read_text(encoding="utf-8")) <= 1500, p
            assert st["ui"] in {k for k, _, _ in flow.ui_groups(kind)}, (kind, st["id"])
        assert len((flow.SKILL / flow.KIND_DOCS[kind]).read_text(encoding="utf-8")) <= 4000
    assert "websearch" in (flow.SKILL / "steps" / "memory" / "design.md").read_text(encoding="utf-8")
    core = (flow.SKILL / "core.md").read_text(encoding="utf-8")
    assert "LAST command (nothing after it)" in core and "only after it passed" in core and "en:" in core and len(core) <= 3200   # Codex acceptance run lessons (+ her confirmations, QA 2026-10-29)


def test_stepper_texts_have_english_and_flow_next_works_for_every_kind(capsys):
    for kind in ("memory", "feature", "gameplay"):
        e = projects.create(f"x {kind}", kind); root = Path(e["path"])
        assert cli.main(["flow", "next", "--project", str(root), "--json"]) == 0
        n = json.loads(capsys.readouterr().out); assert n["kind"] == kind and n["todo"] == "gather" and Path(n["step"]["doc"]).is_file()
        f = onboard.flow_state(root); assert {f["next"]["label"], f["next"]["hint"]} <= onboard.TEXTS | {""}


# ---------------------------------------------------------------- agentd: layered prompts and corrective re-runs per kind
class Spawner:
    def __init__(self): self.calls = []; self.procs = []

    def __call__(self, cmd, cwd, env, log):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        self.calls.append({"cmd": cmd}); self.procs.append(p); return p

    def end(self):
        p = self.procs[-1]; p.terminate(); p.wait(10)


@pytest.fixture
def spawner():
    s = Spawner(); yield s
    for p in s.procs:
        if p.poll() is None: p.kill(); p.wait(10)


def _system(cmd): return cmd[cmd.index("--append-system-prompt") + 1]


@pytest.mark.parametrize("kind,setup,step,card_id", [
    ("memory", lambda root, T: (inbox(root), ingest(root)), "perceive", "permission_card"),
    ("feature", lambda root, T: None, "questions", "questions_card"),
    ("gameplay", lambda root, T: None, "questions", "questions_card"),
])
def test_layered_prompt_and_corrective_run_per_kind(spawner, kind, setup, step, card_id):
    e = projects.create(f"p {kind}", kind); root = Path(e["path"]); T = Thread(root); setup(root, T)
    T.user_text("开始吧"); D = agentd.Agentd(claude="/bin/false", spawn=spawner, quiet=True); D.tick()
    sysp = _system(spawner.calls[0]["cmd"]); old = agentd.PROMPT.read_text(encoding="utf-8")
    assert f"Step {step}" in sysp and f"Mode: {kind}" in sysp and "GameAnything resident agent (core)" in sysp and old[:200] not in sysp
    assert len(sysp) < len(agentd.render_prompt(e, root, "s", D.requests)) and "{{" not in sysp
    r = json.loads((T.dir / ".agentd_run.json").read_text(encoding="utf-8")); assert r["flow_step"] == step and card_id in r["flow_missing"]
    T.read(); T.agent_text("你想先说说吗？")                                 # text only: the step's card is missing
    spawner.end(); D.tick()
    assert len(spawner.calls) == 2 and "Corrective run" in spawner.calls[1]["cmd"][2] and card_id in spawner.calls[1]["cmd"][2]
    assert "corrections 1" in "\n".join(agentd.status_lines()) and "prompt_chars" in "\n".join(agentd.status_lines())
    T.agent_text("还是文字"); spawner.end(); D.tick(); D.tick()
    assert len(spawner.calls) == 2                                          # capped


def test_no_correction_after_the_go_card_until_she_presses_start(spawner):
    e = projects.create("p", "feature"); root = Path(e["path"]); T = Thread(root)
    T.user_text("加一个关卡")
    q = card(root, T, {"kind": "questions", "key": "feature-questions", "title": "q", "items": [{"n": 1, "text": "x", "hint": "y"}]}); T.answer(q["id"], {"answers": {}})
    wy(root, "3_remember/feature.yaml", {"title": "t", "goal": "g", "items": [{"id": "f1", "what": "w", "how": "h", "done_when": "d"}]})
    card(root, T, {"kind": "understanding", "key": "spec", "title": "s", "points": [{"id": "a", "text": "b"}]}); wy(root, "feedback/feature_review.yaml", {"state": "confirmed"})
    plan(root, {"m1": {"status": "next"}}); wy(root, "feedback/plan_review.yaml", {"state": "confirmed", "milestone": "m1"})
    card(root, T, {"kind": "understanding", "key": "plan", "title": "p", "points": [{"id": "a", "text": "b"}]})
    assert nxt(root)["todo"] == "go"
    T.user_text("好"); D = agentd.Agentd(claude="/bin/false", spawn=spawner, quiet=True); D.tick()
    T.read(); read_setup(root); card(root, T, GO); spawner.end(); D.tick()
    assert len(spawner.calls) == 1                                          # the go card is out; build_start waits for her 开工


def test_a_run_that_skips_the_setting_guide_is_corrected(spawner):
    e = projects.create("p", "feature"); root = Path(e["path"]); T = Thread(root)
    T.user_text("加一个关卡")
    q = card(root, T, {"kind": "questions", "key": "feature-questions", "title": "q", "items": [{"n": 1, "text": "x", "hint": "y"}]}); T.answer(q["id"], {"answers": {}})
    wy(root, "3_remember/feature.yaml", {"title": "t", "goal": "g", "items": [{"id": "f1", "what": "w", "how": "h", "done_when": "d"}]})
    card(root, T, {"kind": "understanding", "key": "spec", "title": "s", "points": [{"id": "a", "text": "b"}]}); wy(root, "feedback/feature_review.yaml", {"state": "confirmed"})
    plan(root, {"m1": {"status": "next"}}); wy(root, "feedback/plan_review.yaml", {"state": "confirmed", "milestone": "m1"})
    card(root, T, {"kind": "understanding", "key": "plan", "title": "p", "points": [{"id": "a", "text": "b"}]})
    T.user_text("好"); D = agentd.Agentd(claude="/bin/false", spawn=spawner, quiet=True); D.tick()
    T.read(); card(root, T, GO); spawner.end(); D.tick()                   # a go card without `gameanything setup guide`
    assert len(spawner.calls) == 2 and "setup_guide" in spawner.calls[1]["cmd"][2]


def test_plan_approval_on_an_options_card_from_an_old_thread_counts():
    """adaptation-3: 「文字方案：第一版做什么?」 options card (no key, no flow step) answered 「按这个做」 before the recording existed."""
    e = projects.create("无人生还", "adaptation", game="minecraft"); root = Path(e["path"]); T = Thread(root)
    c = T.append({"from": "agent", "type": "card", "text": "", "card": {"kind": "options", "title": "文字方案:第一版做什么?(看一眼,同意就选「按这个做」)",
                                                                      "items": [{"key": "ok", "title": "按这个做"}, {"key": "change", "title": "我想改"}]}})
    F = flow.facts(root); assert not F["s"]["plan_ok"]
    T.append({"from": "user", "type": "answer", "card_id": c["id"], "answer": {"picked": ["ok"]}})      # no record_answer: an old answer
    assert flow.facts(root)["s"]["plan_ok"] and not (root / "feedback" / "plan_review.yaml").exists()
    assert not flow.approves({"kind": "options", "items": [{"key": "change", "title": "我想改"}]}, {"picked": ["change"]})
    assert not flow.approves({"kind": "understanding"}, {"ok": True, "edits": {"a": "x"}})
