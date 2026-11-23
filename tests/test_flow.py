"""The flow state machine (flow.py): adaptation steps and their exit criteria, `gameanything flow next / check`, the stepper shape, the layered
resident prompt and the corrective re-run in agentd, the chat guard, keyframes / people from videos, both languages on the pages, and a
simulated user walking a new adaptation project from gather to the plan. No real agent, no model call."""
import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import yaml
from conftest import her_clicks

from gameanything import adaptation_tr, agentd, cli, flow, projects, visuals
from gameanything.conversation import Thread
from gameanything.ui import onboard, screens

TEXT = """第二章
They came up over a steep hill and down a zigzag track to Sticklehaven.
"I haven't even seen my employer yet," said Vera.
第三章
In the wide hall drinks stood ready.
"""


# ---------------------------------------------------------------- helpers
def project(video=False):
    e = projects.create("无人生还", "adaptation", game="minecraft", lang="zh"); root = Path(e["path"]); return e, root, Thread(root)


def put_inbox(root):
    (root / "0_inbox").mkdir(exist_ok=True); (root / "0_inbox" / "book.txt").write_text(TEXT, encoding="utf-8")
    (root / "feedback").mkdir(exist_ok=True)
    (root / "feedback" / "ingest_request.yaml").write_text("state: pending\nfiles: [{path: book.txt}]\n", encoding="utf-8")


def ingest(root, video=None):
    d = root / "1_ingest" / "derived" / "docs" / "book"; d.mkdir(parents=True, exist_ok=True); (d / "text.txt").write_text(TEXT, encoding="utf-8")
    items = [{"id": "document_book", "kind": "document", "file": str(root / "0_inbox" / "book.txt"), "included": True,
              "derived": {"pages": [{"n": 1, "text": "1_ingest/derived/docs/book/text.txt"}]}}]
    if video: items.append({"id": "video_trailer", "kind": "video", "file": str(video), "included": True, "duration": 3.0, "derived": {}})
    (root / "1_ingest" / "pack.yaml").write_text(yaml.safe_dump({"items": items}, allow_unicode=True), encoding="utf-8")
    f = root / "feedback" / "ingest_request.yaml"; f.write_text(f.read_text(encoding="utf-8").replace("pending", "done"), encoding="utf-8")


def set_source(root):
    f = root / "config" / "project.yaml"; c = yaml.safe_load(f.read_text(encoding="utf-8"))
    c.update(source="And Then There Were None, 1939（她自己的文件）", source_license="copyrighted（私人自用，短引文）")
    f.write_text(yaml.safe_dump(c, allow_unicode=True), encoding="utf-8")


ADAPT = {"work": {"title": "无人生还", "title_en": "And Then There Were None", "type": "novel", "units": ["第二章", "第三章"]},
         "scenes": [{"id": "s02-01", "unit": "第二章", "title": "斯蒂克尔港", "title_en": "Sticklehaven", "place": "p-harbour", "what": "众人下到港口",
                     "what_en": "They come down to the harbour", "characters": ["薇拉"],
                     "quotes": [{"text": "They came up over a steep hill and down a zigzag track to Sticklehaven.", "text_zh": "他们翻过陡坡到斯蒂克尔港。", "where": "第二章"}]},
                    {"id": "s03-01", "unit": "第三章", "title": "大厅", "title_en": "The hall", "place": "宅子", "what": "酒水备好", "what_en": "Drinks are ready",
                     "characters": ["薇拉"], "quotes": [{"text": "In the wide hall drinks stood ready.", "where": "第三章"}]}],
         "places": [{"id": "p-harbour", "name": "斯蒂克尔港", "name_en": "Sticklehaven", "aliases": ["港口"], "described": [], "not_described": ["码头长度"],
                     "not_described_en": ["Length of the quay"]},
                    {"id": "p-house", "name": "宅子", "name_en": "The house", "aliases": []}],
         "characters": [{"name": "薇拉", "name_en": "Vera", "role": "家庭女教师", "role_en": "governess",
                         "lines": [{"text": "I haven't even seen my employer yet,", "text_zh": "我连雇主都还没见过，", "where": "第二章"}]}]}


def write_adaptation(root, A=None):
    (root / "3_remember").mkdir(exist_ok=True)
    (root / "3_remember" / "adaptation.yaml").write_text(yaml.safe_dump(A or ADAPT, allow_unicode=True, sort_keys=False), encoding="utf-8")


def agent_card(root, T, card):
    return T.card(card, flow_step=cli._flow_step(root))


UNITS = {"kind": "options", "key": "units", "title": "先改编哪几章？", "multi": True,
         "items": [{"key": "ch2", "title": "第二章", "desc": "到港口", "recommended": True}, {"key": "ch3", "title": "第三章", "desc": "晚宴"}]}


class Proj:
    """What screens.save_adaptation needs of the UI's project object."""
    def __init__(self, root): self.root = root; self.lock = threading.Lock(); self.T = Thread(root)
    def feedback_ui(self, d): pass
    def tell(self, text, en=None, ctx=None, auto=False): self.T.user_text(text, ctx, auto=auto, text_en=en)


def confirm(root, **kw):
    return screens.save_adaptation(Proj(root), {"rev": screens.adaptation_rev(root), "items": {}, **kw})


def nxt(root): return flow.next_step(root)


# ---------------------------------------------------------------- the simulated user: gather -> plan
def test_simulated_user_from_new_project_to_plan():
    e, root, T = project()
    n = nxt(root); assert n["todo"] == "gather" and n["waiting_for"] == "user"
    assert onboard.flow_state(root)["current"] == "gather"

    put_inbox(root)                                                     # she drops the novel and clicks 整理新文件
    n = nxt(root); assert n["todo"] == "ingest" and n["actions"]
    assert onboard.flow_state(root)["next"]["hint"] == "agent 正在整理你的素材"

    ingest(root)                                                        # the agent ran gameanything ingest
    n = nxt(root); assert n["todo"] == "copyright" and any("source_license" in a for a in n["actions"])

    set_source(root)
    n = nxt(root); assert n["todo"] == "choose_units" and n["card_required"] == ["units_card"]
    assert onboard.flow_state(root)["next"]["hint"] == "agent 会在对话里问你先改编哪几章"

    T.agent_text("你想先改编哪几章？")                                    # the 2026-10-26 mistake: a plain-text question
    assert nxt(root)["todo"] == "choose_units" and nxt(root)["card_required"] == ["units_card"]

    ev = agent_card(root, T, UNITS); assert ev["flow_step"] == "choose_units"
    n = nxt(root); assert n["todo"] == "choose_units" and n["waiting_for"] == "user" and not n["card_required"]
    assert onboard.flow_state(root)["next"]["label"] == "在对话里选先改编哪几章"

    T.answer(ev["id"], {"picked": ["ch2", "ch3"]})
    n = nxt(root); assert n["todo"] == "extract"
    assert onboard.flow_state(root)["next"]["hint"] == "agent 正在从作品里抽取场景和地点"

    write_adaptation(root)
    n = nxt(root); assert n["todo"] == "extract" and n["card_required"] == ["review_card"]
    agent_card(root, T, {"kind": "task", "key": "scenes-review", "title": "看看场景", "body": "去场景页", "open": "#home"})
    n = nxt(root); assert n["todo"] == "confirm_scenes" and n["waiting_for"] == "user"
    st = onboard.flow_state(root); assert st["current"] == "scenes" and st["next"]["label"] == "确认场景" and st["next"]["route"] == "home"

    assert confirm(root, state="confirmed")["state_characters"] == "draft"          # 「确认场景和地点」 does not confirm the characters
    n = nxt(root); assert n["todo"] == "characters" and n["card_required"] == ["characters_card"]
    st = onboard.flow_state(root); assert st["current"] == "characters" and [s["key"] for s in st["steps"]][2] == "characters"
    assert st["steps"][1]["state"] == "done"

    agent_card(root, T, {"kind": "task", "key": "characters-review", "title": "看看人物", "body": "去角色页", "open": "#people"})
    n = nxt(root); assert n["todo"] == "confirm_characters" and n["waiting_for"] == "user"
    st = onboard.flow_state(root); assert st["next"] == {"label": "确认人物", "route": "people", "wait": False, "hint": ""}

    assert confirm(root, state_characters="confirmed")["state_characters"] == "confirmed"
    assert any("确认了人物" in x.get("text", "") for x in T.events())
    n = nxt(root); assert n["todo"] == "questions" and n["card_required"] == ["questions_card"]
    assert onboard.flow_state(root)["current"] == "plan"

    q = agent_card(root, T, {"kind": "questions", "key": "plan-questions", "title": "几个问题", "items": [{"n": 1, "text": "岛多大？", "hint": "默认 200 格"}]})
    assert nxt(root)["waiting_for"] == "user"
    T.answer(q["id"], {"answers": {}})
    n = nxt(root); assert n["todo"] == "plan" and n["card_required"] == ["plan_card"] and any("world_plan" in a for a in n["actions"])

    (root / "4_design").mkdir(exist_ok=True)
    (root / "4_design" / "world_plan.yaml").write_text(yaml.safe_dump({"world_plan": {"title": "x", "places": [{"id": "p-harbour", "name": "港口"}],
                                                                                     "milestones": {"m1": {"status": "next", "what": "港口"}}}}, allow_unicode=True), encoding="utf-8")
    n = nxt(root); assert n["todo"] == "plan" and n["card_required"] == ["plan_card"]
    assert any("5_build/<这一版>/plan.yaml" in a for a in n["actions"])      # the 方案 page would be empty: items first
    (root / "5_build" / "m1").mkdir(parents=True)
    (root / "5_build" / "m1" / "plan.yaml").write_text(yaml.safe_dump({"items": [{"n": 1, "title": "港口", "desc": "小码头"}]}, allow_unicode=True), encoding="utf-8")
    n = nxt(root); assert not any("plan.yaml" in a for a in n["actions"] if "5_build" in a)
    agent_card(root, T, {"kind": "understanding", "key": "plan", "title": "方案要点", "points": [{"id": "a", "text": "先做港口"}]})
    n = nxt(root); assert n["todo"] == "plan" and n["waiting_for"] == "user"
    assert onboard.flow_state(root)["next"]["label"] == "确认方案"
    (root / "feedback" / "plan_review.yaml").write_text("state: confirmed\nmilestone: m1\n", encoding="utf-8")
    her_clicks(root)                                     # stands for her click on the page
    assert nxt(root)["todo"] == "preview"


# ---------------------------------------------------------------- per-step criteria
def test_copyright_and_units_card_validity():
    e, root, T = project(); put_inbox(root); ingest(root)
    c = flow.check(root, "copyright"); assert not c["ok"] and {x["id"] for x in c["criteria"] if not x["ok"]} == {"source", "source_license"}
    set_source(root); assert flow.check(root, "copyright")["ok"]
    bad = {**UNITS, "items": [{"key": "ch2", "title": "第二章", "desc": "换船登岛", "管家夫妇迎接": None}, {"key": "ch3", "title": "第三章"}]}
    agent_card(root, T, bad)                                            # the broken yaml of adaptation-3 and no default
    c = {x["id"]: x for x in flow.check(root, "choose_units")["criteria"]}
    assert c["units_card"]["ok"] and not c["units_card_valid"]["ok"] and "默认" in c["units_card_valid"]["why"] and "desc" in c["units_card_valid"]["why"]
    assert "管家夫妇迎接" in c["units_card_valid"]["why"]
    agent_card(root, T, {**UNITS, "items": [{"key": "ch2", "title": "第二章", "description": "换船", "recommended": True}, {"key": "ch3", "title": "第三章"}]})
    why = {x["id"]: x for x in flow.check(root, "choose_units")["criteria"]}["units_card_valid"]["why"]
    assert "description" in why and "desc" in why, "a field the card does not know is named, not called broken yaml"


def test_extract_registry_quotes_and_english():
    e, root, T = project(); put_inbox(root); ingest(root); set_source(root)
    A = json.loads(json.dumps(ADAPT))
    A["scenes"][0]["quotes"][0]["text"] = "A quote that is not in the book."
    A["scenes"][1]["place"] = "不存在的地方"; A["places"][1]["aliases"] = ["港口"]
    del A["scenes"][1]["title_en"]
    write_adaptation(root, A)
    c = {x["id"]: x for x in flow.check(root, "extract")["criteria"]}
    assert not c["quotes_verbatim"]["ok"] and "not in the book" in c["quotes_verbatim"]["why"]
    assert not c["english"]["ok"] and c["english"]["level"] == "warn" and "title_en" in c["english"]["why"]
    r = flow.check(root, "registry"); assert not r["ok"]
    assert "不存在的地方" in r["criteria"][0]["why"] and "「港口」同时属于" in r["criteria"][0]["why"]
    assert flow.check_adaptation({}) and flow.check_adaptation({"work": {"units": ["一"]}, "scenes": [{"id": "s"}], "places": []})


def test_video_needs_keyframes_and_linked_frames():
    e, root, T = project(); put_inbox(root); ingest(root, video=root / "0_inbox" / "trailer.mp4"); set_source(root)
    T.answer(agent_card(root, T, UNITS)["id"], {"picked": ["ch2"]}); write_adaptation(root)
    agent_card(root, T, {"kind": "task", "key": "scenes-review", "title": "看看", "body": "去", "open": "#home"})
    c = {x["id"]: x for x in flow.check(root, "extract")["criteria"]}
    assert not c["keyframes"]["ok"] and "gameanything visuals" in c["keyframes"]["why"] and not c["scene_frames"]["ok"] and not c["frames_card"]["ok"]
    assert nxt(root)["todo"] == "extract"
    k = root / visuals.KEY_DIR / "video_trailer"; k.mkdir(parents=True); (k / "k001.jpg").write_bytes(b"x")
    (root / visuals.KEY_DIR / "index.yaml").write_text(yaml.safe_dump({"videos": {"video_trailer": {"shots": [{"n": 1, "frames": [{"file": "2_perceive/keyframes/video_trailer/k001.jpg", "t": 1}]}]}}}), encoding="utf-8")
    A = json.loads(json.dumps(ADAPT)); A["scenes"][0]["frames"] = [{"file": "2_perceive/keyframes/video_trailer/k001.jpg", "t": 1.0}]; write_adaptation(root, A)
    agent_card(root, T, {"kind": "questions", "title": "这是哪一场？", "items": [{"n": 1, "text": "哪一场", "hint": "港口", "image": "/media/2_perceive/keyframes/video_trailer/k001.jpg"}]})
    assert flow.check(root, "extract")["ok"]
    assert screens.adaptation_state(root)["scenes"][0]["frames"][0]["file"].endswith("k001.jpg")
    # her confirmation before the frames existed does not hide the gap: the scenes are not confirmed yet, so extract is fixed first
    c = {x["id"]: x for x in flow.check(root, "characters")["criteria"]}
    assert not c["people"]["ok"]


def test_gap_is_fixed_first_but_never_reopens_what_she_confirmed():
    e, root, T = project(); put_inbox(root); ingest(root); set_source(root)
    T.answer(agent_card(root, T, UNITS)["id"], {"picked": ["ch2"]}); write_adaptation(root)
    agent_card(root, T, {"kind": "task", "key": "scenes-review", "title": "看看", "body": "去", "open": "#home"})
    assert nxt(root)["todo"] == "confirm_scenes"
    f = root / "config" / "project.yaml"; c = yaml.safe_load(f.read_text(encoding="utf-8")); c.pop("source_license"); f.write_text(yaml.safe_dump(c), encoding="utf-8")
    n = nxt(root); assert n["todo"] == "copyright" and n["gaps"] == ["copyright"] and n["current"] == "confirm_scenes"
    confirm(root, state="confirmed")                                   # she confirmed: earlier steps are not reopened
    n = nxt(root); assert n["gaps"] == [] and n["todo"] == "characters"


def test_old_combined_confirmation_counts_for_characters():
    e, root, T = project(); write_adaptation(root)
    (root / "feedback").mkdir(exist_ok=True)
    (root / "feedback" / "adaptation_review.yaml").write_text("state: confirmed\nat: '2026-10-21T10:00:00'\nitems: {}\n", encoding="utf-8")
    her_clicks(root)                                     # stands for her click on the page
    assert flow.chars_confirmed(yaml.safe_load((root / "feedback" / "adaptation_review.yaml").read_text(encoding="utf-8")))
    s = screens.adaptation_state(root); assert s["review"]["state_characters"] == "confirmed"
    r = confirm(root, items={"char:薇拉": {"choice": "change", "note": "头发是黑色"}})
    assert r["state_characters"] == "confirmed"                         # saving again keeps the old project's characters confirmed


# ---------------------------------------------------------------- both languages on the pages
def test_pages_follow_the_ui_language_with_fallback():
    e, root, T = project(); A = json.loads(json.dumps(ADAPT)); del A["scenes"][1]["what_en"]; write_adaptation(root, A)
    zh, en = screens.adaptation_state(root, "zh"), screens.adaptation_state(root, "en")
    assert zh["scenes"][0]["title"] == "斯蒂克尔港" and en["scenes"][0]["title"] == "Sticklehaven"
    assert en["scenes"][1]["what"] == "酒水备好"                         # no English: the Chinese stays
    assert en["scenes"][0]["characters"] == ["Vera"] and zh["scenes"][0]["characters"] == ["薇拉"]
    assert en["places"][0]["not_described"] == ["Length of the quay"] and en["characters"][0]["role"] == "governess"
    assert en["work"]["title"] == "And Then There Were None" and en["characters"][0]["scenes"] == ["s02-01", "s03-01"]
    q0 = zh["scenes"][0]["quotes"][0]; assert q0["text"].startswith("They came") and q0["tr"] == "他们翻过陡坡到斯蒂克尔港。"
    assert en["scenes"][0]["quotes"][0]["tr"] == ""                     # the original is English: no translation line in EN
    (root / "4_design").mkdir(exist_ok=True)
    (root / "4_design" / "world_plan.yaml").write_text(yaml.safe_dump({"world_plan": {"milestones": {"m1": {"status": "next", "what": "港口", "what_en": "The harbour"}}}},
                                                                       allow_unicode=True), encoding="utf-8")
    (root / "5_build" / "m1").mkdir(parents=True)
    (root / "5_build" / "m1" / "plan.yaml").write_text(yaml.safe_dump({"items": [{"n": 1, "title": "码头", "title_en": "The quay", "desc": "木头"}]}, allow_unicode=True), encoding="utf-8")
    p = screens.plan_state(root, "en"); assert p["round"]["what"] == "The harbour" and p["items"][0]["title"] == "The quay" and p["items"][0]["desc"] == "木头"
    assert screens.plan_state(root, "zh")["items"][0]["title"] == "码头"


def test_translate_helper_lists_and_merges(capsys):
    e, root, T = project(); A = json.loads(json.dumps(ADAPT)); del A["scenes"][1]["what_en"]; write_adaptation(root, A)
    m = adaptation_tr.missing(root)
    assert "scenes.s03-01.what_en" in m and "scenes.s03-01.quotes.0.text_zh" in m
    out = root / "todo.yaml"
    assert cli.main(["adaptation", "translate", "--project", str(root), "--out", str(out)]) == 1 and "不调用模型" in capsys.readouterr().out
    part = {"scenes.s03-01.what_en": "Drinks are ready", "scenes.s03-01.quotes.0.text_zh": "宽敞的大厅里已备好酒水。", "scenes.s02-01.title_en": ""}
    assert adaptation_tr.apply(root, part) == (2, 1)
    assert screens.adaptation_state(root, "en")["scenes"][1]["what"] == "Drinks are ready"
    with pytest.raises(ValueError): adaptation_tr.apply(root, {"scenes.nope.title_en": "x"})


# ---------------------------------------------------------------- CLI, stepper shape, chat guard
def test_cli_next_and_check(capsys):
    e, root, T = project(); put_inbox(root); ingest(root); set_source(root)
    assert cli.main(["flow", "next", "--project", str(root), "--json"]) == 0
    n = json.loads(capsys.readouterr().out)
    assert n["todo"] == "choose_units" and Path(n["step"]["doc"]).as_posix().endswith("steps/adaptation/choose_units.md") and Path(n["step"]["doc"]).is_file()
    assert n["tell_user"] and n["card_required"] == ["units_card"]
    assert cli.main(["flow", "next", "--project", e["id"]]) == 0
    t = capsys.readouterr().out; assert "choose_units" in t and "gameanything chat card" in t and "告诉她" in t
    assert cli.main(["flow", "check", "--project", str(root)]) == 1
    t = capsys.readouterr().out; assert "不行 units_card" in t and "[她]" in t
    assert cli.main(["flow", "check", "--project", str(root), "--step", "copyright"]) == 0
    assert cli.main(["flow", "check", "--project", str(root), "--step", "nope"]) == 2


def test_every_step_has_a_short_doc_and_the_layers_fit():
    for st in flow.ADAPTATION:
        p = flow.doc_path("adaptation", st["id"]); assert p.is_file(), p
        assert len(p.read_text(encoding="utf-8")) <= 1500, p
    assert len(agentd.CORE.read_text(encoding="utf-8")) <= 3200          # + her confirmations rule (QA 2026-10-29)
    assert len((flow.SKILL / "modes" / "adaptation.md").read_text(encoding="utf-8")) <= 4000


def test_stepper_shape_unchanged(tmp_path):
    for kind in ("memory", "feature", "gameplay"):
        e = projects.create(f"x {kind}", kind); f = onboard.flow_state(Path(e["path"]))
        assert set(f) == {"kind", "steps", "current", "next"} and set(f["next"]) == {"label", "route", "wait", "hint"}
        assert [(s["key"], s["label"], s["route"]) for s in f["steps"]] == onboard.FLOWS[kind]
        assert all(set(s) == {"key", "label", "route", "state"} for s in f["steps"])
    e, root, T = project(); f = onboard.flow_state(root)
    assert [s["key"] for s in f["steps"]] == ["gather", "scenes", "characters", "plan", "preview", "go", "play"]
    assert f["steps"][2]["route"] == "people" and set(f["next"]) == {"label", "route", "wait", "hint"}
    texts = {flow_step["label"] for flow_step in f["steps"]} | {f["next"]["label"], f["next"]["hint"]}
    assert texts <= onboard.TEXTS | {""}


def test_chat_guard_warns_on_text_when_a_card_is_due(capsys):
    e, root, T = project(); put_inbox(root); ingest(root); set_source(root)
    assert cli.main(["chat", "say", "--project", str(root), "--session", "s1", "--text", "你想先选哪几章？"]) == 0
    err = capsys.readouterr().err; assert "要的是卡片" in err and "gameanything chat card" in err
    f = root / "units.yaml"; f.write_text(yaml.safe_dump(UNITS, allow_unicode=True), encoding="utf-8")
    assert cli.main(["chat", "card", "--project", str(root), "--session", "s1", "--file", str(f)]) == 0
    capsys.readouterr()
    assert [x for x in T.events() if x["type"] == "card"][-1]["flow_step"] == "choose_units"
    assert cli.main(["chat", "say", "--project", str(root), "--session", "s1", "--text", "卡片发好了"]) == 0
    assert "要的是卡片" not in capsys.readouterr().err
    m = projects.create("回忆", "memory"); capsys.readouterr()
    assert cli.main(["chat", "say", "--project", m["path"], "--session", "s1", "--text", "好"]) == 0 and "卡片" not in capsys.readouterr().err


# ---------------------------------------------------------------- agentd: layered prompt and the corrective re-run
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


def test_layered_prompt_is_core_mode_and_one_step(spawner, monkeypatch):
    from gameanything import internal_docs                    # a user's machine: no gamebench addendum (this test host has a lab)
    monkeypatch.setattr(internal_docs, "applies", lambda *a, **k: False)
    e, root, T = project(); put_inbox(root); ingest(root); set_source(root)
    T.user_text("开始吧"); D = agentd.Agentd(claude="/bin/false", spawn=spawner, quiet=True); D.tick()
    sysp = _system(spawner.calls[0]["cmd"])
    old = agentd.PROMPT.read_text(encoding="utf-8")
    assert "Step choose_units" in sysp and "Mode: adaptation" in sysp and "GameAnything resident agent (core)" in sysp
    assert "Step extract" not in sysp and old[:200] not in sysp and "{{" not in sysp and str(root) in sysp
    budget = sum(len(p.read_text(encoding="utf-8")) for p in (agentd.CORE, flow.SKILL / "modes" / "adaptation.md", flow.doc_path("adaptation", "choose_units")))
    assert len(sysp) <= budget + 2500 and len(sysp) < len(old)
    assert "开始吧" in spawner.calls[0]["cmd"][2]                        # her unread words are in the run's prompt
    r = json.loads((T.dir / ".agentd_run.json").read_text(encoding="utf-8")); assert r["flow_step"] == "choose_units" and r["flow_missing"] == ["units_card"]
    m = projects.create("回忆", "memory"); Thread(Path(m["path"])).user_text("hi"); spawner.end(); D.tick()
    assert all(old[:200] not in _system(c["cmd"]) for c in spawner.calls[1:])   # every kind runs on layered prompts now
    assert any("Mode: memory" in _system(c["cmd"]) for c in spawner.calls[1:])
    D2 = agentd.Agentd(claude="/bin/false", spawn=spawner, quiet=True, template=agentd.PROMPT.parent / "resident-prompt.md")
    assert D2.template == agentd.PROMPT                                       # resident-prompt.md stays the fallback template


def test_missing_card_starts_one_corrective_run(spawner):
    e, root, T = project(); put_inbox(root); ingest(root); set_source(root)
    T.user_text("开始吧"); D = agentd.Agentd(claude="/bin/false", spawn=spawner, quiet=True); D.tick(); assert len(spawner.calls) == 1
    T.read(); T.agent_text("你想先改编哪几章？")                          # the run answered in text only, no card
    spawner.end(); D.tick()
    assert len(spawner.calls) == 2 and "Corrective run" in spawner.calls[1]["cmd"][2] and "units_card" in spawner.calls[1]["cmd"][2]
    assert (T.dir / ".agentd_correct.json").exists(), "kept while the corrective run goes (a failed one is retried)"
    T.agent_text("还是文字"); spawner.end(); D.tick(); D.tick()
    assert not (T.dir / ".agentd_correct.json").exists()
    assert len(spawner.calls) == 2                                      # capped: no second correction
    log = (D.log_dir() / "agentd.log").read_text(encoding="utf-8"); assert "one corrective run" in log


def test_finished_step_with_an_agent_step_next_starts_a_continuation(spawner):
    e, root, T = project(); put_inbox(root); ingest(root)                  # ingest done; copyright is the agent's next step
    T.user_text("开始吧"); D = agentd.Agentd(claude="/bin/false", spawn=spawner, quiet=True); D.tick()
    assert json.loads((T.dir / ".agentd_run.json").read_text(encoding="utf-8"))["flow_step"] == "copyright"
    T.read(); set_source(root); T.agent_text("版权写好了"); spawner.end(); D.tick()          # the run did copyright and ended
    assert len(spawner.calls) == 2 and "Continuation run" in spawner.calls[1]["cmd"][2] and "units_card" in spawner.calls[1]["cmd"][2]
    assert "Step choose_units" in _system(spawner.calls[1]["cmd"])
    r = json.loads((T.dir / ".agentd_run.json").read_text(encoding="utf-8")); assert r["flow_step"] == "choose_units" and r["why"] == "correct"
    agent_card(root, T, UNITS); spawner.end(); D.tick(); D.tick()          # the card is out: she has to pick, nothing more starts
    assert len(spawner.calls) == 2
    assert "one continuation run" in (D.log_dir() / "agentd.log").read_text(encoding="utf-8")


def test_continuations_are_capped_per_message(spawner, monkeypatch):
    monkeypatch.setattr(agentd, "MAX_CONTINUE", 1)
    e, root, T = project(); put_inbox(root); ingest(root)
    T.user_text("开始吧"); D = agentd.Agentd(claude="/bin/false", spawn=spawner, quiet=True); D.tick()
    T.read(); set_source(root); T.agent_text("版权写好了"); spawner.end(); D.tick(); assert len(spawner.calls) == 2
    T.answer(agent_card(root, T, UNITS)["id"], {"picked": ["ch2"]}); T.read(); T.agent_text("好"); spawner.end(); D.tick(); D.tick()
    assert len(spawner.calls) == 2                                      # extract is due, but the one continuation for 开始吧 was used


def test_no_correction_when_the_card_was_sent_or_she_must_act(spawner):
    e, root, T = project(); put_inbox(root); ingest(root); set_source(root)
    T.user_text("开始吧"); D = agentd.Agentd(claude="/bin/false", spawn=spawner, quiet=True); D.tick()
    T.read(); agent_card(root, T, UNITS); spawner.end(); D.tick()
    assert len(spawner.calls) == 1                                      # the card went out: now she has to pick, nothing to correct


# ---------------------------------------------------------------- keyframes and people from a real (tiny) video
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")
def test_visuals_keyframes_and_people(tmp_path):
    e, root, T = project(); put_inbox(root)
    v = root / "0_inbox" / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=160x120:d=1.5", "-f", "lavfi", "-i", "color=c=blue:s=160x120:d=1.5",
                    "-filter_complex", "[0:v][1:v]concat=n=2:v=1[o]", "-map", "[o]", str(v)], check=True)
    ingest(root, video=v)
    k = visuals.keyframes(root)
    shots = k["videos"]["video_trailer"]["shots"]; assert len(shots) == 2 and shots[1]["start"] == pytest.approx(1.5, abs=0.2)
    assert all((root / f["file"]).is_file() for s in shots for f in s["frames"])
    box = lambda im: [(10, 10, 80, 100)]
    p = visuals.people(root, detect=("test", box))
    assert p["method"] == "test" and len(p["clusters"]) == 2 and (root / p["clusters"][0]["rep"]).is_file()   # red and blue: two looks
    visuals.note_ledger(root, "test"); led = yaml.safe_load((root / "privacy_ledger.yaml").read_text(encoding="utf-8"))
    assert led["local"][0]["sent"] == "nothing" and led["requests"] == []
    assert cli.main(["flow", "check", "--project", str(root), "--step", "extract"]) == 1   # keyframes made, but not linked to scenes yet
