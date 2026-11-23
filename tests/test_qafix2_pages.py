"""QA2 2026-10-30 (the cross-harness retests): flow check / next crashed on a world_plan.yaml of the wrong shape, the shell page went blank
on a bad file, the 这一天 moment photos never showed, a YAML syntax error was reported as a missing file, looks without `text` were hidden,
and the 人物 page had no one on it after she declined photo detection."""
from pathlib import Path

import pytest
import yaml

from gameanything import filecheck, flow, projects
from gameanything.ui import screens

KINDS = (("memory", "stardew"), ("gameplay", "slay_the_spire"), ("adaptation", "stardew"), ("feature", "stardew"))
BAD = ("- a\n- b\n", "oops\n", "world_plan:\n  milestones: oops\n", "world_plan: [1, 2]\n", "world_plan:\n  milestones:\n    m1: oops\n")


def wy(root, rel, d):
    p = Path(root) / rel; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(d if isinstance(d, str) else yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")


@pytest.mark.parametrize("kind,game", KINDS)
def test_flow_never_crashes_on_a_world_plan_of_the_wrong_shape(kind, game):
    root = Path(projects.create("t " + kind, kind, game=game)["path"])
    for txt in BAD:
        wy(root, "4_design/world_plan.yaml", txt)
        c = flow.check(root); n = flow.next_step(root)                # no traceback
        fv = next(x for x in c["criteria"] if x["id"] == "files_valid")
        assert not fv["ok"] and "world_plan.yaml" in fv["why"], txt
        assert any("world_plan.yaml" in a for a in n["actions"]), txt


@pytest.mark.parametrize("kind,game", KINDS)
def test_flow_never_crashes_on_any_page_file_of_the_wrong_shape(kind, game):
    root = Path(projects.create("t " + kind, kind, game=game)["path"])
    rels = [rel for rel, _ in filecheck.CHECKS if not rel.endswith("project.yaml")] + [f"feedback/{n}" for n in filecheck.REVIEWS]
    for txt in ("- a\n- b\n", "oops\n", "k: [unclosed\n"):
        for rel in rels: wy(root, rel, txt)
        flow.check(root); flow.next_step(root)
        listed = {f for f, _ in filecheck.problems(root)}
        assert "4_design/world_plan.yaml" in listed and "3_remember/board.yaml" in listed, (txt, listed)


def _pack(root, ids):
    wy(root, "1_ingest/pack.yaml", {"items": [{"id": i, "kind": "photo", "derived": {"image": f"1_ingest/derived/images/{i}.jpg",
                                                                                     "thumb": f"1_ingest/derived/thumbs/{i}.jpg"}} for i in ids]})


def test_moment_photos_show_with_items_as_the_board_doc_says():
    root = Path(projects.create("婚礼", "memory")["path"])
    _pack(root, ["p1", "p2"])
    wy(root, "3_remember/board.yaml", {"experience_board": {"title": "婚礼", "skeleton": [{"id": "s", "what": "上午"}],
           "moments": [{"id": "m1", "title": "接亲", "items": ["p1"], "importance": "must_preserve", "segment": "s"},
                       {"id": "m2", "title": "仪式", "source_refs": ["p2"], "importance": "important", "segment": "s"}]}})
    b = {m["id"]: m for m in screens.board_state(root)["moments"]}
    assert b["m1"]["img"] and "p1" in b["m1"]["img"], "items: (the doc's field) shows the photo"
    assert b["m2"]["img"] and "p2" in b["m2"]["img"], "source_refs: still works"
    assert "p1" in (screens.shell(root)["cover"] or "")


@pytest.mark.parametrize("rel", ["3_remember/people.yaml", "3_remember/board.yaml", "4_design/world_plan.yaml", "config/project.yaml"])
def test_shell_survives_a_file_of_the_wrong_shape(rel):
    root = Path(projects.create("婚礼", "memory")["path"])
    for txt in ("- a\n", "oops\n", "experience_board: [1]\nworld_plan: 3\npeople: 4\n"):
        wy(root, rel, txt)
        s = screens.shell(root)                                    # no traceback: the sidebar stays
        assert s["kind"] == "memory" and isinstance(s["rounds"], list), (rel, txt)
        screens.plan_state(root)


@pytest.fixture
def ui():
    import threading
    from gameanything.ui import serve
    root = Path(projects.create("我们的婚礼", "memory")["path"])
    box, ready = {}, threading.Event()
    th = threading.Thread(target=serve, args=(root,), kwargs={"port": 18911, "ready": lambda s: (box.setdefault("srv", s), ready.set())}, daemon=True)
    th.start(); assert ready.wait(20)
    yield f"http://127.0.0.1:{box['srv'].server_port}", root
    box["srv"].shutdown(); box["srv"].server_close()


def _get(url):
    import json, urllib.error, urllib.request
    try:
        with urllib.request.urlopen(url, timeout=20) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")


def test_api_shell_stays_up_and_names_the_bad_files(ui, monkeypatch):
    url, root = ui
    (root / "3_remember" / "people.yaml").write_text("people:\n- id: p1\n  name: [unclosed\n", encoding="utf-8")
    st, d = _get(url + "/api/shell")
    assert st == 200 and d["kind"] == "memory" and any(x["file"] == "3_remember/people.yaml" for x in d["bad_files"])
    def boom(*a, **k): raise KeyError("x")
    monkeypatch.setattr(screens, "shell", boom)                    # whatever else breaks: the shell still comes up
    st, d = _get(url + "/api/shell")
    assert st == 200 and d["kind"] == "memory" and d["rounds"] == [] and d["title"] and d["bad_files"]


def test_the_shell_page_shows_the_bad_file_list():
    js = (Path(screens.__file__).parent / "static" / "shell.js").read_text(encoding="utf-8")
    assert "bad_files" in js and "renderBadFiles" in js
    i18n = (Path(screens.__file__).parent / "static" / "i18n.js").read_text(encoding="utf-8")
    assert "这些文件有问题，有的页面可能显示不全：" in i18n


@pytest.mark.parametrize("kind,game,rel,fn", [("gameplay", "slay_the_spire", "3_remember/gameplay.yaml", "gameplay_state"),
                                               ("adaptation", "stardew", "3_remember/adaptation.yaml", "adaptation_state"),
                                               ("feature", "stardew", "3_remember/feature.yaml", "feature_state")])
def test_a_syntax_error_names_the_file_instead_of_an_empty_page(kind, game, rel, fn):
    root = Path(projects.create("t", kind, game=game)["path"])
    wy(root, rel, "title: x\nmapping: [unclosed\n")
    st = getattr(screens, fn)(root)
    assert st["bad"] and st["bad"][0]["file"] == rel and "语法" in st["bad"][0]["problem"]
    js = (Path(screens.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
    for screen in ("SCREENS.mechanics", "SCREENS.content", "SCREENS.scenes", "SCREENS.characters", "SCREENS.spec"):
        body = js[js.index(screen + " = "):][:400]
        assert "badPage(" in body, screen


def test_looks_without_text_are_shown_and_flagged():
    root = Path(projects.create("t", "adaptation")["path"])
    wy(root, "3_remember/adaptation.yaml", {"work": {"title": "白雪"}, "scenes": [], "places": [],
        "characters": [{"id": "q", "name": "王后", "looks": [{"text_zh": "黑发高个（发明的）", "where": "invented"}, {"text_en": "a red cloak"},
                                                            {"text": "原文", "where": "ch1"}], "lines": [{"zh": "魔镜"}]}]})
    ch = screens.adaptation_state(root)["characters"][0]
    assert [x["text"] for x in ch["looks"]] == ["黑发高个（发明的）", "a red cloak", "原文"] and ch["lines"][0]["text"] == "魔镜"
    assert screens.adaptation_state(root, "en")["characters"][0]["looks"][1]["text"] == "a red cloak"
    msgs = [m for f, m in filecheck.problems(root) if f.endswith("adaptation.yaml")]
    assert any("looks" in m and "text" in m for m in msgs), msgs


def _go(milestone, **kw):
    return {"kind": "go", "title": "开工", "milestone": milestone, "items": ["地图"], "eta_hours": 1, **kw}


def test_a_go_card_milestone_is_the_version_id_not_its_name():
    from gameanything.conversation import CardError, Thread
    root = Path(projects.create("婚礼", "memory")["path"])
    T = Thread(root)
    with pytest.raises(CardError, match="m1"):
        T.card(_go("第一版"))
    assert T.card(_go("m1"))["card"]["milestone"] == "m1"
    assert T.card(_go("preview", key="preview-go"), flow_step="preview")              # a preview go card is not a version
    ex = yaml.safe_load((Path(screens.__file__).parents[2] / "skills/gameanything/references/card-examples/go.yaml").read_text(encoding="utf-8"))
    assert str(ex["milestone"]).isascii(), "the example the agents copy uses an id"


def test_go_card_build_row_reads_flow_step_from_the_event_and_items_are_text():
    js = (Path(screens.__file__).parent / "static" / "shell.js").read_text(encoding="utf-8")
    assert "const isBuildGo = (k, ev)" in js and "isBuildGo(k, c.ev)" in js
    assert "JSON.stringify(x)" not in js and "goItem(" in js


def test_checker_wording_for_a_syntax_error_and_a_string_list():
    root = Path(projects.create("t", "adaptation")["path"])
    wy(root, "3_remember/adaptation.yaml", "work: {title: x\nscenes: [\n")
    P = flow.check_adaptation(flow._y(root / "3_remember/adaptation.yaml", {}), root / "3_remember/adaptation.yaml")
    assert P and "不存在" not in P[0] and "语法" in P[0], P
    P = flow.check_adaptation({"work": {"units": ["ch1"]}, "scenes": "oops", "places": "x"})
    assert len([p for p in P if "scenes" in p or "场景" in p]) == 1 and len([p for p in P if "places" in p or "地点" in p]) == 1, P
    f = root / "3_remember/feature.yaml"; f.write_text("title: [x\n", encoding="utf-8")
    P = flow.check_feature(flow._y(f, {}), f)
    assert "不存在" not in P[0] and "语法" in P[0], P
    assert flow.check_adaptation({}, root / "nope.yaml") == ["3_remember/adaptation.yaml 不存在或是空的"]


def test_gameplay_resources_with_desc_fill_the_meaning_column():
    root = Path(projects.create("t", "gameplay", game="slay_the_spire")["path"])
    wy(root, "3_remember/gameplay.yaml", {"mapping": [{"id": "m1", "experience": "a", "mechanic": "b"}],
        "core": {"fantasy": "x", "resources": [{"name": "精力", "desc": "每回合出牌"}, {"name": "专注"}]}})
    rs = screens.gameplay_state(root)["core"]["resources"]
    assert rs[0]["meaning"] == "每回合出牌"
    msgs = [m for f, m in filecheck.problems(root) if f.endswith("gameplay.yaml")]
    assert any("core.resources 第 2 条" in m and "meaning" in m for m in msgs) and not any("第 1 条" in m for m in msgs), msgs


def _post(url, body):
    import json, urllib.error, urllib.request
    rq = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                headers={"Content-Type": "application/json", "Origin": url.split("/api/")[0]})
    try:
        with urllib.request.urlopen(rq, timeout=20) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")


def test_people_page_can_add_a_person_by_hand(ui):
    """She declined photo detection: nobody on the 人物 page and no way to add one (QA2 2026-10-30)."""
    url, root = ui
    st, d = _get(url + "/api/looks"); assert st == 200 and d["people"] == []
    st, r = _post(url + "/api/people/add", {"name": "小林", "role": "新娘"}); assert st == 200 and r["ok"], r
    st, r = _post(url + "/api/people/add", {"name": "Mochi"}); assert st == 200 and r["ok"]
    st, r = _post(url + "/api/people/add", {"name": "小林"}); assert st == 400, "the same name twice"
    st, r = _post(url + "/api/people/add", {"name": "  "}); assert st == 400
    st, d = _get(url + "/api/looks")
    assert [(p["person_name"], p["role"] or "") for p in d["people"]] == [("小林", "新娘"), ("Mochi", "")]
    ppl = yaml.safe_load((root / "3_remember" / "people.yaml").read_text(encoding="utf-8"))["people"]
    assert [p["source"] for p in ppl] == ["user", "user"] and len({p["id"] for p in ppl}) == 2 and all(p["id"].isascii() for p in ppl)
    assert not filecheck.problems(root)
    from gameanything.conversation import Thread
    assert any("小林" in (e.get("text") or "") for e in Thread(root).events()), "the agent hears about it"
    js = (Path(screens.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
    assert "/api/people/add" in js
