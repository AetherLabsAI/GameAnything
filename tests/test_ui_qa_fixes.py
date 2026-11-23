"""The page fixes from the QA of 2026-10-29 (UI side): what the server tells the pages, and the static pages themselves (no browser here; the
screenshots at 390 / 1280 / 1440 px were checked by hand with headless Chromium)."""
import json
import re
from pathlib import Path

import pytest
import yaml

from gameanything import conversation, decisions, demo, layout, models, translate
from gameanything.conversation import CardError, Thread, en_fields, merge_en
from gameanything.ui import i18n, screens
from gameanything.ui.upload import ALLOWED

STATIC = Path(screens.__file__).parent / "static"
read = lambda n: (STATIC / n).read_text(encoding="utf-8")


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "proj"
    for d in ("config", layout.REMEMBER, layout.FEEDBACK, layout.DESIGN, "conversation", "0_inbox", "1_ingest"): (r / d).mkdir(parents=True, exist_ok=True)
    (r / "config" / "project.yaml").write_text("title: 测试\nkind: memory\ngame: stardew\n", encoding="utf-8")
    return r


def _y(p, data): Path(p).write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


# ---------------------------------------------------------------- round names (i18n.round_name)
def test_round_name_numerals_and_name_en():
    assert i18n.round_name("第一版：婚礼仪式", "zh") == "第 1 版 · 婚礼仪式"
    assert i18n.round_name("第十二期", "zh") == "第 12 版"
    assert i18n.round_name("第 2 版 · 婚后", "en") == "Round 2 · After the wedding"
    assert i18n.round_name("第二十一版", "en") == "Round 21"
    assert i18n.round_name("第一版：婚礼仪式", "en", name_en="Round 1: The ceremony") == "Round 1 · The ceremony"
    assert i18n.round_name("第一版：婚礼仪式", "en", name_en="The big day") == "The big day"
    assert i18n.round_name("第一版：婚礼仪式", "zh", name_en="The big day") == "第 1 版 · 婚礼仪式"      # zh never takes name_en
    assert i18n.cn_number("十") == 10 and i18n.cn_number("两") == 2 and i18n.cn_number("一百") is None


def test_sidebar_round_uses_name_en_and_plan_confirmation(root):
    _y(root / layout.DESIGN / "world_plan.yaml", {"world_plan": {"milestones": {"m1": {"name": "第一版：婚礼仪式", "name_en": "Round 1: The ceremony", "status": "next"}}}})
    decisions.start(root)                                          # a new project: only her page clicks count
    r = screens.Data(root).rounds("en")[0]
    assert r["name"] == "Round 1 · The ceremony" and r["sub"] == "Plan written, waiting for you to confirm it"
    _y(root / layout.FEEDBACK / "plan_review.yaml", {"milestone": "m1", "state": "confirmed"})   # an agent wrote it: not hers
    assert screens.Data(root).rounds("zh")[0]["sub"] == "方案写好了，等你确认"
    decisions.record(root, "plan:m1", "confirmed")
    assert screens.Data(root).rounds("zh")[0]["sub"] == "方案定了，等你点开工"


# ---------------------------------------------------------------- chat: the length cap, *_en cards, the same card twice
def test_message_cap(root):
    T = Thread(root)
    T.user_text("x" * conversation.MSG_MAX)
    with pytest.raises(CardError) as e: T.user_text("x" * (conversation.MSG_MAX + 1))
    assert "最多 20000" in str(e.value)
    assert i18n.err(str(e.value), "en").startswith("Message too long (20001 characters): at most 20000")
    assert f"MSG_MAX = {conversation.MSG_MAX};" in read("shell.js")            # the page's counter uses the same cap


def test_title_en_cards_show_english(root):
    T = Thread(root)
    ev = T.card({"kind": "options", "key": "k", "title": "选一个", "title_en": "Pick one",
                 "items": [{"key": "A", "title": "海边", "title_en": "Seaside"}, {"key": "B", "title": "山里"}]})
    assert ev["card_en"] == {"title": "Pick one", "items": [{"title": "Seaside"}, {}]}
    en = translate.localize(T.events(), root, "en")[-1]["card"]
    assert en["title"] == "Pick one" and en["items"][0]["title"] == "Seaside" and en["items"][1]["title"] == "山里" and en["items"][0]["key"] == "A"
    assert translate.localize(T.events(), root, "zh")[-1]["card"]["title"] == "选一个"


def test_english_card_keeps_the_pictures(root):
    """card_en naming only the words (the public demo's EN lost 27 pictures: a shallow merge replaced the items)."""
    base = {"kind": "candidates", "title": "挑一张", "items": [{"key": "a", "title": "甲", "url": "/media/a.png"}, {"key": "b", "title": "乙", "url": "/media/b.png"}]}
    m = merge_en(base, {"title": "Pick", "items": [{"key": "b", "title": "B"}, {"key": "a", "title": "A"}]})
    assert [(i["title"], i["url"]) for i in m["items"]] == [("A", "/media/a.png"), ("B", "/media/b.png")]
    m = merge_en(base, {"items": [{"title": "A"}, {"title": "B"}]})                       # no keys: by position
    assert m["items"][1] == {"key": "b", "title": "B", "url": "/media/b.png"} and m["title"] == "挑一张"
    assert en_fields({"kind": "progress", "now_en": "x", "steps": []}) is None             # fields a kind reads itself stay


def test_same_open_card_is_not_duplicated(root):
    T = Thread(root)
    card = {"kind": "task", "key": "tag", "title": "标出照片里的人", "body": "请在人物页标一下", "open": "#people/tag"}
    a = T.card(dict(card)); b = T.card(dict(card))
    assert a["id"] == b["id"] and sum(e["type"] == "card" for e in T.events()) == 1
    c = T.card({**card, "body": "也标一下阿杰"})                                         # changed: the newer one supersedes
    assert c["id"] != a["id"] and list(T.cards()) == [c["id"]]
    T.answer(c["id"], {"done": True})
    d = T.card({**card, "body": "也标一下阿杰"})                                         # answered: the same card again is a new one
    assert d["id"] != c["id"]


def test_page_hides_superseded_unanswered_cards():
    js = read("shell.js")
    assert 'e.card.kind === "progress" || !answered.has(prev)' in js
    assert "for (const [id, s] of [...slots]) if (!cards.has(id))" in js


# ---------------------------------------------------------------- 素材: files already in pack.yaml are not "new"
def test_gather_counts_ingested_inbox_files(root):
    from gameanything.ui.upload import Inbox
    inbox = root / "0_inbox"
    (inbox / "a.jpg").write_bytes(b"x" * 10); (inbox / "b.jpg").write_bytes(b"y" * 7); (inbox / "c.jpg").write_bytes(b"z" * 3)
    _y(root / "1_ingest" / "pack.yaml", {"source_folder": str(inbox), "items": [
        {"id": "photo_a", "kind": "photo", "file": str(inbox / "a.jpg"), "bytes": 10},
        {"id": "photo_b", "kind": "photo", "file": "/elsewhere/moved/b.jpg", "bytes": 7}]})     # a moved project: name + size
    g = screens.gather(root, Inbox(root, 1 << 30), 1 << 30)
    st = {f["path"]: f["ingested"] for f in g["inbox"]["files"]}
    assert st == {"a.jpg": True, "b.jpg": True, "c.jpg": False} and g["inbox"]["new"] == 1 and g["inbox"]["ingested"] == 2


# ---------------------------------------------------------------- 人物: everyone the project knows
def test_people_page_lists_people_without_looks(root):
    from gameanything.ui import Project
    _y(root / layout.REMEMBER / "people.yaml", {"people": [{"id": "p1", "name": "小林", "persona": "高个子"}, {"id": "p2", "name": "阿杰", "role": "新郎"}]})
    st = Project(root).looks_state()
    ppl = {p["id"]: p for p in st["people"]}
    assert set(ppl) == {"p1", "p2"} and ppl["p1"]["no_look"] and ppl["p1"]["persona"] == {"note": "高个子"} and ppl["p2"]["role"] == "新郎"
    assert screens.day(root)["people"] == len(st["people"])


# ---------------------------------------------------------------- models: Fable through another agent
def test_fable_warning_for_other_agents():
    assert models.warning("claude-code", "fable") and models.warning("opencode", "anthropic/claude-fable-5-1")
    assert models.warning("opencode", "openrouter/anthropic/claude-fable-5.1") and not models.warning("opencode", "openrouter/moonshotai/kimi-k2.6")
    pat = models.expensive()[0]["pattern"]
    assert re.search(pat, "anthropic/claude-fable-5-1") and not re.search(pat, "sonnet")


# ---------------------------------------------------------------- the public demo
def test_demo_exports_models_and_profile_without_private_data():
    assert "/api/models" in demo.API and "/api/profile" in demo.API
    m = demo.for_demo("models", {"can_edit": True, "agents": [{"id": "x"}], "chat": {"agent": "claude-code", "agent_name": "Claude Code", "model_shown": "sonnet", "source": "u"}, "build": {}})
    assert m["can_edit"] is False and m["agents"] == [] and m["chat"] == {"agent": "claude-code", "agent_name": "Claude Code", "model_shown": "sonnet"}
    p = demo.for_demo("profile", {"owner": "alice", "project": "x", "entries": [{"text": "她喜欢暖色"}], "kinds": {"a": "b"}})
    assert p["entries"] == [] and p["owner"] == "" and p["kinds"] == {"a": "b"}


# ---------------------------------------------------------------- 内容: archetype ids
def test_gameplay_archetypes_keep_their_id(root):
    _y(root / layout.REMEMBER / "gameplay.yaml", {"core": {"archetypes": [{"id": "steady", "name": "稳健护理", "idea": "x"}, {"name": "急救"}]}})
    a = screens.gameplay_state(root)["core"]["archetypes"]
    assert [(x["id"], x["name"]) for x in a] == [("steady", "稳健护理"), ("", "急救")]
    js = read("app.js")
    assert "C[key].map(c => c.archetype)" in js and "gpArchName(a)" in js                   # chips = the values the cards use, named when known


# ---------------------------------------------------------------- static pages: phones, routing, the wizard, errors
def test_phone_layouts_exist():
    sh = read("shell.html")
    assert "@media (max-width: 760px)" in sh and 'id="mbar"' in sh and 'id="mscrim"' in sh and "body.m-ws .app > .chat" in sh
    assert "@container (max-width: 860px)" in sh                                       # 1280 px: tab names were cut to one letter
    assert "@media (max-width:700px)" in read("app.css") and "@media (max-width:600px)" in read("hub.html")
    js = read("shell.js")
    assert "function mview(" in js and "function renderMbar(" in js and 'matchMedia("(max-width: 760px)")' in js


def test_workspace_follows_the_address_bar():
    js = read("shell.js")
    assert 'window.addEventListener("hashchange"' in js and "history.pushState(null" in js and "L.replace(L.href.split(\"#\")[0]" in js
    assert "ws(location.hash.slice(1) || startRoute(), { initial: true })" in js


def test_wizard_checks_files_like_the_upload():
    js = read("onboard.js")
    fb = json.loads(re.search(r"const UPLOAD_FALLBACK = (\[[^\]]*\]);", js).group(1))
    assert fb == sorted(ALLOWED)                                                         # the same list as upload.py
    assert "function fileProblem(" in js and "S.rejected" in js


def test_shell_api_names_upload_types(root, monkeypatch):
    src = (Path(screens.__file__).parent / "__init__.py").read_text(encoding="utf-8")
    assert src.count('"upload_allowed": sorted(UPLOAD_ALLOWED)') == 2                     # with and without a project open


def test_error_page_lists_bad_files():
    js = read("app.js")
    assert "err.files = (j && Array.isArray(j.files))" in js and "function errHtml(" in js and 'class="errfiles"' in js


def test_play_page_claims_only_what_play_yaml_says():
    js = read("app.js")
    assert 'span class="tag">${t("独立回放 · 真实键盘输入")}' not in js
    assert "P.independent_replay && t(\"独立回放\")" in js and "P.real_input && t(\"真实键盘输入\")" in js


def test_new_page_strings_have_english():
    """Every Chinese string the changed pages pass to t() has an English entry (i18n.js EN)."""
    en = read("i18n.js")
    for f in ("shell.js", "onboard.js"):
        for s in set(re.findall(r'\bt\("([^"\n]*[一-鿿][^"\n]*)"', read(f))):
            assert f'"{s}":' in en, (f, s)
