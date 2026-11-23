"""QA2 2026-10-30: the units card says 「默认已勾好」 so the recommended items start ticked; an answered card shows the titles, not the
keys (「ch1 + ch2 + ch3」); a task card's `open:` must be a page this kind of project has; 「两个时刻」."""
import json
import re
import shutil

import pytest

from gameanything import cli, projects
from gameanything.conversation import CardError, Thread
from test_card_keys import run_shell, thread

UNITS = {"kind": "options", "key": "units", "title": "先改编哪几章？（可多选，默认已勾好）", "multi": True,
         "items": [{"key": "ch1", "title": "第一章 出发", "recommended": True}, {"key": "ch2", "title": "第二章 抵达", "recommended": True},
                   {"key": "ch3", "title": "第三章 晚宴"}]}
node = pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")


@node
def test_recommended_items_start_ticked():
    T = thread(); T.card(UNITS)
    html = run_shell("zh", [T.events()])["kids"][0]["html"]
    on = re.findall(r'class="opt on [^"]*" data-k="([^"]+)"', html)
    assert on == ["ch1", "ch2"], html


@node
def test_answered_card_shows_titles():
    T = thread(); c = T.card(UNITS); T.answer(c["id"], {"picked": ["ch1", "ch3"]})
    html = run_shell("zh", [T.events()])["kids"][0]["html"]
    assert "第一章 出发 + 第三章 晚宴" in html and "ch1 + ch3" not in html


def test_task_card_open_must_fit_the_kind():
    e = projects.create("改编", kind="adaptation"); T = Thread(projects.resolve(e["id"]))
    task = {"kind": "task", "key": "t1", "title": "确认角色", "body": "去看看", "open": "#people"}
    assert T.card(task)["card"]["open"] == "#characters", "the adaptation's own page, not the memory people page"
    assert T.card({**task, "key": "t0", "open": "#home"})["card"]["open"] == "#scenes"
    with pytest.raises(CardError) as x: T.card({**task, "key": "t2", "open": "#nowhere"})
    assert "#scenes" in str(x.value)
    m = projects.create("回忆", kind="memory"); M = Thread(projects.resolve(m["id"]))
    assert M.card({**task, "open": "#people/tag"})["card"]["open"] == "#people/tag"
    with pytest.raises(CardError): M.card({**task, "key": "t3", "open": "#scenes"})


@node
def test_two_moments_reads_right():
    import json, subprocess
    js = (projects.Path(cli.__file__).parent / "ui" / "static" / "app.js").read_text(encoding="utf-8")
    head = "\n".join(l for l in js.splitlines()[:30] if l.startswith(("const CN", "const cn")))
    out = subprocess.run(["node", "-"], input=head + "\nconsole.log(JSON.stringify([2, 3, 12, 22].map(cnCount)))", capture_output=True, text=True,
                         check=True, encoding="utf-8").stdout
    assert json.loads(out) == ["两", "三", "十二", "二十二"]
    assert "cnCount(D.moments.length)" in js


def test_composer_attach_without_a_project_says_what_to_do():
    """QA2 2026-10-30: a file put into the chat box on the welcome page went to /api/upload with no project: 409."""
    js = (projects.Path(cli.__file__).parent / "ui" / "static" / "shell.js").read_text(encoding="utf-8")
    body = js[js.index("function attach(files)"):js.index("async function upload(")]
    assert "no_project" in body and "先建一个项目" in body
    i18n = (projects.Path(cli.__file__).parent / "ui" / "static" / "i18n.js").read_text(encoding="utf-8")
    assert "先建一个项目，再把文件放进来" in i18n


@node
def test_spec_page_none_reads_as_words():
    """需求 page: `saves: none` showed the raw word (fixed in 3ebb79e): the NONE pattern covers it."""
    import subprocess
    js = (projects.Path(cli.__file__).parent / "ui" / "static" / "app.js").read_text(encoding="utf-8")
    line = next(l for l in js.splitlines() if "const NONE =" in l).strip()
    out = subprocess.run(["node", "-"], input=line + "\nconsole.log(['none','None.','无','一个奖杯'].map(x => NONE.test(x)).join())",
                         capture_output=True, text=True, check=True, encoding="utf-8").stdout.strip()
    assert out == "true,true,true,false"


@node
def test_archetype_ids_show_as_names():
    """QA2 2026-10-30: the content page's archetype chips showed raw ids (steady); the card tiles too."""
    import subprocess
    js = (projects.Path(cli.__file__).parent / "ui" / "static" / "app.js").read_text(encoding="utf-8")
    line = next(l for l in js.splitlines() if l.startswith("const gpArchName ="))
    probe = ("let GP = {core: {archetypes: [{id: 'steady', name: '稳健护理'}, {id: '', name: 'Theory'}]}};\n" + line
             + "\nconsole.log(JSON.stringify(['steady', 'Steady', 'Theory', 'other'].map(gpArchName)))")
    out = subprocess.run(["node", "-"], input=probe, capture_output=True, text=True, check=True, encoding="utf-8").stdout
    assert out.strip() == '["稳健护理","稳健护理","Theory","other"]'
    tiles = js[js.index("function tileHtml"):js.index("SCREENS.content =")]
    assert "esc(x.archetype)" not in tiles


@node
def test_click_path_default_picked_reads_the_card_state():
    """Hotfix 2026-10-30 (f1afba6 regression): the click handlers call lastPicked/defaultPicked with the card STATE ({ev, answers}), the
    render path with {ev, card}; reading c.card.kind on the state threw 「Cannot read properties of undefined (reading 'kind')」 so no
    options/candidates card could be answered. Both shapes must work, for every caller."""
    T = thread(); o = T.card(UNITS)
    for n in "ab": (T.root / "4_design" / "art").mkdir(parents=True, exist_ok=True); (T.root / "4_design" / "art" / f"{n}.png").write_bytes(b"\x89PNG")
    cand = T.card({"kind": "candidates", "key": "pics", "title": "选一张", "media": "image",
                   "items": [{"key": "a", "title": "A", "url": "/art/a.png"}, {"key": "b", "title": "B", "url": "/art/b.png"}]})
    probe = (f"const S = cardState(), so = S.get({json.dumps(o['id'])}), sc = S.get({json.dumps(cand['id'])});"
             "console.log(JSON.stringify({opt_state: lastPicked(so), opt_def: defaultPicked(so), opt_render: defaultPicked({ ...so, card: so.ev.card }),"
             " cand_state: lastPicked(sc), cand_render: defaultPicked({ ...sc, card: sc.ev.card }), empty: defaultPicked({})}));")
    out = run_shell("zh", [T.events()], probe=probe)
    assert out == {"opt_state": ["ch1", "ch2"], "opt_def": ["ch1", "ch2"], "opt_render": ["ch1", "ch2"],
                   "cand_state": [], "cand_render": [], "empty": []}
    T.answer(o["id"], {"picked": ["ch3"]})
    out = run_shell("zh", [T.events()], probe=f"console.log(JSON.stringify(lastPicked(cardState().get({json.dumps(o['id'])}))));")
    assert out == ["ch3"]
