"""Feature projects (kind: feature): the 需求 page's data (3_remember/feature.yaml), the review write, and the page list in i18n.js."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from gameanything import layout
from gameanything.ui import screens

STATIC = Path(screens.__file__).parent / "static"
FULL = {"title": "香港美食", "goal": "做一个茶餐厅关卡", "game": "overcooked2", "updated": "2026-10-23",
        "items": [{"id": "f1", "what": "茶餐厅地图", "how": "进关卡就能玩", "done_when": "三道菜能做完", "saves": "none", "status": "confirmed"},
                  {"what": "港式奶茶", "status": "weird"}],
        "open_questions": ["有没有照片？", "", "主打哪几道菜"]}


class FakeProj:
    """Just what save_feature uses of the UI's project object."""
    def __init__(self, root):
        import threading
        self.root, self.lock, self.told, self.events = root, threading.RLock(), [], []
    def tell(self, text, en=None, ctx=None, auto=False): self.told.append((text, ctx, auto))
    def feedback_ui(self, ev): self.events.append(ev)


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "feature"
    (r / "config").mkdir(parents=True); (r / layout.REMEMBER).mkdir(); (r / layout.FEEDBACK).mkdir()
    (r / "config" / "project.yaml").write_text("title: 香港美食\nkind: feature\ngame: overcooked2\n", encoding="utf-8")
    return r


def _sheet(root, data):
    (root / layout.REMEMBER / "feature.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_loader_missing_and_empty(root):
    st = screens.feature_state(root)
    assert st["exists"] is False and st["items"] == [] and st["review"]["state"] is None
    (root / layout.REMEMBER / "feature.yaml").write_text("", encoding="utf-8")
    assert screens.feature_state(root)["exists"] is False
    (root / layout.REMEMBER / "feature.yaml").write_text("- not\n- a mapping\n", encoding="utf-8")
    assert screens.feature_state(root)["items"] == []


def test_loader_full(root):
    _sheet(root, FULL)
    st = screens.feature_state(root)
    assert st["exists"] and st["title"] == "香港美食" and st["goal"] == "做一个茶餐厅关卡" and st["game"]
    assert [i["id"] for i in st["items"]] == ["f1", "i2"]                       # a missing id becomes i<position>
    assert st["items"][0]["done_when"] == "三道菜能做完" and st["items"][0]["status"] == "confirmed"
    assert st["items"][1]["status"] == "open" and st["items"][1]["how"] == ""    # unknown status -> open, absent text -> ""
    assert st["open_questions"] == ["有没有照片？", "主打哪几道菜"]


def test_review_write(root):
    _sheet(root, FULL)
    p = FakeProj(root); rv = root / layout.FEEDBACK / "feature_review.yaml"
    st = screens.feature_state(root)
    r = screens.save_feature(p, {"rev": st["rev"], "items": {"item:f1": {"choice": "change", "note": "要大排档"}, "item:i2": {"choice": "drop"}}})
    assert r["ok"] and r["state"] == "draft"
    saved = yaml.safe_load(rv.read_text(encoding="utf-8"))
    assert saved["items"]["item:f1"] == {"label": "茶餐厅地图", "choice": "change", "note": "要大排档"} and saved["items"]["item:i2"]["choice"] == "drop"
    assert p.told == [("要大排档", [{"kind": "feature", "id": "item:f1", "label": "需求 · 茶餐厅地图"}], False)]
    # the same note again is not repeated; confirming sends one auto line with the counts
    r = screens.save_feature(p, {"rev": r["rev"], "items": {"item:f1": {"choice": "change", "note": "要大排档"}}, "state": "confirmed"})
    assert r["state"] == "confirmed" and len(p.told) == 2 and p.told[1][2] is True and "要改 1 条，不要 1 条" in p.told[1][0]
    assert screens.feature_state(root)["review"]["state"] == "confirmed"
    # a stale page, an unknown item and a bad choice are refused
    assert screens.save_feature(p, {"rev": "old", "items": {}})["stale"] is True
    with pytest.raises(ValueError): screens.save_feature(p, {"rev": r["rev"], "items": {"item:nope": {"choice": "keep"}}})
    with pytest.raises(ValueError): screens.save_feature(p, {"rev": r["rev"], "items": {"item:f1": {"choice": "skip"}}})
    assert yaml.safe_load((root / layout.REMEMBER / "feature.yaml").read_text(encoding="utf-8")) == FULL   # the agent's file is never edited


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_feature_tabs_and_words():
    js = (STATIC / "i18n.js").read_text(encoding="utf-8")
    probe = ("globalThis.window={addEventListener(){}};globalThis.document={documentElement:{dataset:{},getAttribute(){return null},setAttribute(){}},"
             "addEventListener(){},querySelectorAll(){return[]}};globalThis.localStorage={getItem(){return null},setItem(){}};globalThis.navigator={language:'zh'};\n"
             + js + "\nconsole.log(JSON.stringify({tabs:KIND_TABS.feature.map(x=>x[0]),names:KIND_TABS.feature.map(x=>x[2]),"
             "alias:['home','board','people','plan'].map(k=>tabOf('feature',k)),memory:tabOf('memory','board'),"
             "noEN:Object.entries(KIND_WORDS.feature).flatMap(([k,v])=>[k,v]).filter(s=>!(s in EN)&&!['素材','照片'].includes(s)),"
             "memoryWords:Object.values(KIND_WORDS.feature).filter(s=>/回忆|这一天|时刻|人物/.test(s))}))")
    out = json.loads(subprocess.run(["node", "-"], input=probe, capture_output=True, text=True, check=True, encoding="utf-8").stdout)
    assert out["tabs"] == ["gather", "spec", "plan", "play", "status", "keep"] and out["names"] == ["素材", "需求", "方案", "试玩", "开发状态", "带回家"]
    assert out["alias"] == ["spec", "spec", "spec", "plan"] and out["memory"] == "home"
    assert out["noEN"] == [] and out["memoryWords"] == []


def test_english_from_the_translation_store(root):
    """In EN the sheet (and a gameplay sheet) read the project's i18n store; ZH and untranslated strings stay as written."""
    from gameanything import translate
    _sheet(root, FULL)
    translate.add(root, {"香港美食": "Hong Kong Food", "茶餐厅地图": "A cha chaan teng map", "主打哪几道菜": "Which dishes lead?"})
    en, zh = screens.feature_state(root, "en"), screens.feature_state(root, "zh")
    assert en["title"] == "Hong Kong Food" and en["items"][0]["what"] == "A cha chaan teng map" and en["items"][0]["how"] == "进关卡就能玩"
    assert en["open_questions"][-1] == "Which dishes lead?" and zh["title"] == "香港美食" and zh["items"][0]["what"] == "茶餐厅地图"
    (root / layout.REMEMBER / "gameplay.yaml").write_text(yaml.safe_dump({"title": "香港美食", "mapping": [{"experience": "茶餐厅地图", "mechanic": "订单"}],
        "content": {"cards": [{"name": "Quick Test", "text": "主打哪几道菜", "art": "4_design/a.png"}]}}, allow_unicode=True), encoding="utf-8")
    g = screens.gameplay_state(root, "en")
    assert g["title"] == "Hong Kong Food" and g["mapping"][0]["experience"] == "A cha chaan teng map" and g["mapping"][0]["mechanic"] == "订单"
    assert g["content"]["cards"][0]["text"] == "Which dishes lead?" and screens.gameplay_state(root)["mapping"][0]["experience"] == "茶餐厅地图"
    assert "订单" in translate.missing(root) and "茶餐厅地图" not in translate.missing(root)
