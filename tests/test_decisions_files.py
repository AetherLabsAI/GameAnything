"""QA 2026-10-29: an agent wrote her confirmation itself (decisions.py), malformed agent files broke the pages while flow check passed
(filecheck.py), the board confirm always failed, and the 这一天 page kept asking to confirm after she had."""
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from gameanything import decisions, filecheck, flow, projects
from gameanything.conversation import Thread
from gameanything.ui import home, screens


def wy(root, rel, d):
    p = Path(root) / rel; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")


class Proj:
    """What the save handlers need of the UI's Project."""
    def __init__(self, root): self.root = Path(root); self.lock = threading.Lock(); self.told = []; self.ui = []
    def tell(self, text, en=None, ctx=None, auto=False): self.told.append((text, en, auto))
    def feedback_ui(self, e): self.ui.append(e)


def gameplay_project():
    e = projects.create("夜班护士", "gameplay", game="slay_the_spire"); root = Path(e["path"])
    wy(root, "3_remember/gameplay.yaml", {"title": "夜班", "mapping": [{"id": "m1", "experience": "熬夜", "mechanic": "能量", "kind": "resource"}],
                                         "core": {"fantasy": "护士", "character": {"name": "小林", "hp": 70}}})
    return root


# ---------------------------------------------------------------- her confirmations are hers
def test_an_agent_written_confirmation_does_not_advance_the_flow():
    root = gameplay_project()
    assert decisions.strict(root), "a new project is under the ledger rule"
    wy(root, "feedback/gameplay_review.yaml", {"mapping": {"state": "confirmed"}, "items": {}})     # what OpenCode did
    assert not flow.facts(root)["s"]["mapping_ok"], "the file alone is not her decision"
    c = flow.check(root); ud = next(x for x in c["criteria"] if x["id"] == "user_decisions")
    assert not c["ok"] and not ud["ok"] and "gameplay_review.yaml" in ud["why"] and "不要替她写确认文件" in ud["why"]
    assert any("不是她在页面上点的" in a for a in flow.next_step(root)["actions"]), "flow next tells the agent first"
    assert screens.gameplay_state(root)["review"]["mapping"]["state"] == "draft", "her confirm button is there again"
    # she confirms on the page: now it counts, and the agent gets the 「确认了…」 line
    p = Proj(root); r = screens.save_gameplay(p, {"rev": screens.gameplay_rev(root), "stage": "mapping", "state": "confirmed", "items": {}})
    assert r["ok"] and flow.facts(root)["s"]["mapping_ok"] and decisions.forged(root) == []
    assert any(t.startswith("确认了机制映射") and auto for t, _, auto in p.told)


def test_a_ledger_line_typed_by_hand_does_not_count():
    root = gameplay_project()
    wy(root, "feedback/gameplay_review.yaml", {"mapping": {"state": "confirmed"}})
    with open(decisions.ledger(root), "a", encoding="utf-8") as f:
        f.write(json.dumps({"what": "gameplay:mapping", "state": "confirmed", "at": "2026-10-29T10:00:00", "via": "ui", "sig": "0" * 32}) + "\n")
    assert not decisions.confirmed(root, "gameplay:mapping") and decisions.forged(root)


def test_plan_board_spec_and_card_approval_are_recorded():
    e = projects.create("Fishing", "feature", game="overcooked2"); root = Path(e["path"])
    wy(root, "4_design/world_plan.yaml", {"world_plan": {"status": "confirmed", "milestones": {"m1": {"status": "next"}}}})
    assert not flow.facts(root)["s"]["plan_ok"], "the agent's own 'status: confirmed' is not her 「就按这个做」"
    T = Thread(root)
    card = T.card({"kind": "options", "key": "plan", "title": "方案", "items": [{"key": "ok", "title": "就按这个做"}, {"key": "no", "title": "再想想"}]})
    T.answer(card["id"], {"picked": ["ok"]})
    assert decisions.confirmed(root, "plan:m1") and flow.facts(root)["s"]["plan_ok"]
    wy(root, "feedback/feature_review.yaml", {"state": "confirmed"}); assert ("spec", "feedback/feature_review.yaml") in decisions.forged(root)


# legacy projects (never had a ledger) and a deleted ledger: test_decisions_ledger.py


def test_import_resigns_her_decisions(monkeypatch, tmp_path):
    root = gameplay_project(); decisions.record(root, "gameplay:mapping", "confirmed")
    monkeypatch.setenv("GAMEANYTHING_DECISION_KEYS", str(tmp_path / "other-install"))        # another GameAnything: other server keys
    assert not decisions.confirmed(root, "gameplay:mapping")
    assert decisions.resign(root) and decisions.confirmed(root, "gameplay:mapping")


def test_skill_says_never_write_her_confirmations():
    from gameanything import shipped
    core = (shipped.SKILL / "core.md").read_text(encoding="utf-8")
    assert "Never write her confirmations yourself" in core


# ---------------------------------------------------------------- malformed files: flow check names them, pages answer with an error
def test_flow_check_names_malformed_files():
    root = gameplay_project()
    wy(root, "3_remember/gameplay.yaml", {"core": {"character": "小林，70 血", "resources": "能量、咖啡"}, "mapping": []})
    (root / "3_remember" / "people.yaml").write_text("people:\n- id: p1\n  name: 小林\n", encoding="utf-8")
    with open(root / "3_remember" / "people.yaml", "a", encoding="utf-8") as f: f.write("people:\n- id: p2\n")      # cat >>
    (root / "5_build" / "m1").mkdir(parents=True, exist_ok=True); wy(root, "5_build/m1/plan.yaml", {"items": [{"title": "地图"}, "第二条"]})
    P = dict(((f, m) for f, m in filecheck.problems(root)))
    files = [f for f, _ in filecheck.problems(root)]
    assert "3_remember/people.yaml" in files and "3_remember/gameplay.yaml" in files and "5_build/m1/plan.yaml" in files
    assert any("core.character" in m for f, m in filecheck.problems(root) if f.endswith("gameplay.yaml"))
    assert any("core.resources" in m for f, m in filecheck.problems(root) if f.endswith("gameplay.yaml"))
    c = flow.check(root); fv = next(x for x in c["criteria"] if x["id"] == "files_valid")
    assert not c["ok"] and not fv["ok"] and "people.yaml" in fv["why"]
    # the pages that read them do not crash
    g = screens.gameplay_state(root); assert g["core"]["character"]["note"].startswith("小林") and [r["name"] for r in g["core"]["resources"]] == ["能量", "咖啡"]
    wy(root, "4_design/world_plan.yaml", {"world_plan": {"milestones": {"m1": {"status": "next"}}}})
    assert [i["n"] for i in screens.plan_state(root)["items"]] == [1], "an item without n is numbered, a string item is skipped"


@pytest.fixture
def ui(monkeypatch):
    from gameanything.ui import serve
    e = projects.create("我们的婚礼", "memory"); root = Path(e["path"])
    box, ready = {}, threading.Event()
    th = threading.Thread(target=serve, args=(root,), kwargs={"port": 18871, "ready": lambda s: (box.setdefault("srv", s), ready.set())}, daemon=True)
    th.start(); assert ready.wait(20)
    yield f"http://127.0.0.1:{box['srv'].server_port}", root
    box["srv"].shutdown(); box["srv"].server_close()


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=20) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")


def test_ui_answers_with_the_bad_file_instead_of_dropping_the_connection(ui):
    url, root = ui
    (root / "3_remember" / "people.yaml").write_text("people:\n- id: p1\n  name: [unclosed\n", encoding="utf-8")
    for api in ("/api/day", "/api/state", "/api/home"):
        st, d = _get(url + api)
        assert st == 500 and d["ok"] is False and any(x["file"] == "3_remember/people.yaml" for x in d["files"]), (api, st, d)
        assert "people.yaml" in d["error"] and str(root) not in d["error"]


# ---------------------------------------------------------------- 确认这一天
def test_board_confirm_works_without_segments_and_home_stops_asking():
    e = projects.create("婚礼", "memory"); root = Path(e["path"])
    wy(root, "3_remember/board.yaml", {"experience_board": {"moments": [{"id": "m1", "title": "出门", "weight": 3}, {"id": "m2", "title": "仪式"}]}})
    st = screens.board_state(root)
    body = {"rev": st["rev"], "order": [m["id"] for m in st["moments"]], "state": "confirmed",
            "moments": {m["id"]: {"importance": m["importance"], "segment": m["segment"]} for m in st["moments"]}}
    p = Proj(root); r = screens.save_board(p, body)
    assert r["ok"] and r["state"] == "confirmed", "no 「重要程度或分段不合法」 for a board without skeleton / importance"
    rv = yaml.safe_load((root / "feedback" / "board_review.yaml").read_text(encoding="utf-8"))
    assert rv["moments"]["m1"]["importance"] == "important"
    assert flow.facts(root)["s"]["board_ok"]
    todo = [t["text"] for t in home.home_state(root)["todo"]]
    assert not any("确认回忆板" in t for t in todo), "after she confirmed, 这一天 stops asking"
    doc = (Path(flow.SKILL) / "steps" / "memory" / "board.md").read_text(encoding="utf-8")
    assert "segment" in doc and "importance" in doc and "skeleton" in doc
