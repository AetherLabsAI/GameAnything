"""A card sent again under a key that was used before (adaptation-3, 2026-10-27: the resident sent the next round's 5 questions as
`plan-questions`, the key of the 4 questions answered the day before, and the page repainted them in the old card's place far up in
yesterday's history, so she never saw them). The new card is the live one, at the bottom; the old one stays where it was, read-only, with
its own answers and 「已更新，见下方」. The server (Thread.cards) and the page (shell.js cardState / render) must agree."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from gameanything import projects
from gameanything.conversation import CardError, Thread

STATIC = Path(__file__).resolve().parents[1] / "gameanything" / "ui" / "static"
Q1 = {"kind": "questions", "key": "plan-questions", "title": "第一版的问题", "items": [{"n": i, "text": f"旧问题{i}"} for i in range(1, 5)]}
Q2 = {"kind": "questions", "key": "plan-questions", "title": "下一版的问题", "items": [{"n": i, "text": f"新问题{i}"} for i in range(1, 6)]}


def thread():
    e = projects.create("改编三", "adaptation", game="stardew"); return Thread(Path(e["path"]))


def test_new_card_under_an_old_key_is_the_live_one_and_starts_unanswered():
    T = thread()
    q1 = T.card(Q1); T.answer(q1["id"], {"answers": {"1": "旧回答一"}})
    assert T.cards()[q1["id"]]["answers"][0]["answer"]["answers"] == {"1": "旧回答一"}
    q2 = T.card(Q2)
    cs = T.cards()
    assert q1["id"] not in cs and cs[q2["id"]]["answers"] == [] and cs[q2["id"]]["card"]["title"] == "下一版的问题"
    with pytest.raises(CardError, match="已经更新"): T.answer(q1["id"], {"answers": {"2": "晚到的旧回答"}})
    with pytest.raises(CardError, match="找不到"): T.answer("nope", {"answers": {"1": "x"}})
    T.answer(q2["id"], {"answers": {"5": "新回答五"}})
    assert [a["answer"]["answers"] for a in T.cards()[q2["id"]]["answers"]] == [{"5": "新回答五"}]
    # a progress card under one key is still updated in place (only the newest one counts)
    p1 = T.card({"kind": "progress", "key": "prog-m4", "milestone": "m4", "steps": [{"text": "构建", "state": "current"}]})
    p2 = T.card({"kind": "progress", "key": "prog-m4", "milestone": "m4", "steps": [{"text": "构建", "state": "done"}]})
    assert p1["id"] not in T.cards() and p2["id"] in T.cards()


# A tiny fake DOM, enough for shell.js's thread state + render(): elements keep their innerHTML as a string and their children in order.
FAKE_DOM = r"""
globalThis.window = globalThis; globalThis.addEventListener = () => {};
class CL { constructor(e) { this.e = e; } get s() { return new Set(this.e.className.split(/\s+/).filter(Boolean)); }
  add(c) { const s = this.s; s.add(c); this.e.className = [...s].join(" "); } remove(c) { const s = this.s; s.delete(c); this.e.className = [...s].join(" "); }
  contains(c) { return this.s.has(c); } toggle(c, on) { on = on === undefined ? !this.contains(c) : on; on ? this.add(c) : this.remove(c); return on; } }
class El { constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.className = ""; this._h = ""; this.style = {}; this.parent = null;
    this.classList = new CL(this); this.scrollTop = 0; this.scrollHeight = 0; this.clientHeight = 0; this.textContent = ""; }
  append(...xs) { for (const x of xs) { if (x.parent) x.remove(); x.parent = this; this.children.push(x); } }
  remove() { if (this.parent) { this.parent.children.splice(this.parent.children.indexOf(this), 1); this.parent = null; } }
  set innerHTML(h) { this._h = h; this.children = []; } get innerHTML() { return this._h; }
  get lastElementChild() { return this.children[this.children.length - 1] || null; }
  addEventListener() {} removeEventListener() {} }
const TH = new El("div");
globalThis.document = { documentElement: { dataset: {}, getAttribute() { return null; }, setAttribute() {} }, addEventListener() {},
  querySelectorAll() { return []; }, querySelector() { return null; }, createElement: t => new El(t), hidden: false };
globalThis.goModelHtml = () => ""; globalThis.MODELS = null;      // defined outside the thread part (go cards render)
globalThis.localStorage = { getItem() { return null; }, setItem() {} }; globalThis.navigator = { language: "zh" };
"""


def run_shell(lang, batches, probe=None):
    """Feed the event batches to render() like poll() does; -> the thread's children [{id, cls, html}] and pending().
    `probe`: JS that runs after the renders instead, and prints its own JSON."""
    sh = (STATIC / "shell.js").read_text(encoding="utf-8")
    part = sh[sh.index("/* ------------------------------------------------------------ thread state */"):sh.index("\nlet busy = false;")]
    js = (FAKE_DOM + (STATIC / "i18n.js").read_text(encoding="utf-8")
          + f"\nM2W.lang = {json.dumps(lang)};\n"
          + "const esc = s => String(s ?? '').replace(/[&<>\"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));\n"
          + "const $ = (s, r) => s === '#thread' ? TH : null, $$ = () => [], icon = () => '', hhmm = fmtHM, at = u => u, SH = null, AGENT = {};\n"
          + "const daemonUp = () => false, renderSide = () => {}, ws = () => {}, toast = () => {}, post = async () => ({}), poll = async () => {};\n"
          + part
          + f"\nfor (const b of {json.dumps(batches, ensure_ascii=False)}) {{ EV = EV.concat(b); render(b); firstLoad = false; }}\n"
          + (probe or "console.log(JSON.stringify({kids: TH.children.filter(x => x.dataset.id).map(x => ({id: x.dataset.id, cls: x.className, html: x.innerHTML})), pending: pending()}));") + " process.exit(0);")   # exit: the first render follows late images with a 5 s interval
    r = subprocess.run(["node", "-"], input=js, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
@pytest.mark.parametrize("lang,note", [("zh", "已更新，见下方"), ("en", "Updated, see below")])
def test_page_shows_the_new_card_at_the_bottom_and_keeps_the_old_one_read_only(lang, note):
    T = thread()
    q1 = T.card(Q1); T.answer(q1["id"], {"answers": {"1": "旧回答一"}}); T.agent_text("我先看看下一版要做什么")
    day1 = T.events()
    q2 = T.card(Q2)
    p1 = T.card({"kind": "progress", "key": "prog-m4", "milestone": "m4", "steps": [{"text": "构建", "state": "current"}]})
    T.agent_text("构建开始了")
    p2 = T.card({"kind": "progress", "key": "prog-m4", "milestone": "m4", "steps": [{"text": "构建", "state": "done"}]})
    later = T.events()[len(day1):]
    for batches in ([day1, later], [day1 + later]):                  # live (two polls), and opening the page afterwards (one render)
        out = run_shell(lang, batches)
        ids = [k["id"] for k in out["kids"]]
        assert ids == [q1["id"], q2["id"], p2["id"]], "the old card stays in place, the new one and the newest progress card at the bottom"
        old, new = out["kids"][0], out["kids"][1]
        assert "old" in old["cls"].split() and note in old["html"] and "旧回答一" in old["html"] and "旧问题4" in old["html"]
        assert f'data-newer="{q2["id"]}"' in old["html"]
        assert "old" not in new["cls"].split() and note not in new["html"] and "新问题5" in new["html"] and "旧回答一" not in new["html"]
        assert new["html"].count("<textarea") == 5 and 'data-act="submit"' in new["html"]
        assert out["pending"] == 1, "only the new questions wait for her"
    assert p1["id"] not in ids


def test_superseded_cards_are_read_only_in_css_and_click_handler():
    css = (STATIC / "shell.html").read_text(encoding="utf-8"); js = (STATIC / "shell.js").read_text(encoding="utf-8")
    assert ".msg.old .card textarea" in css and ".msg.old .card [data-act]" in css
    assert "if (c.newer && !tg.dataset.open && !tg.dataset.ws) return;" in js
    assert 'EV.find(x => x.type === "card" && x.card.key === k)' not in js, "a card under an old key must not take the first card's place"
    assert '"已更新，见下方": "Updated, see below"' in (STATIC / "i18n.js").read_text(encoding="utf-8")
