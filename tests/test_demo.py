"""`gameanything demo export` (gameanything/demo.py) and the demo mode of the page (ui/static/demo.js): a static, read-only copy of the UI on
one project. The export never writes into the project or the real project list; the page in demo mode answers GETs from files and refuses
writes; a page served by `gameanything ui` is exactly as before (no demo.js, no GA_DEMO)."""
import hashlib
import json
import shutil
import subprocess
import threading
import urllib.request
from pathlib import Path

import pytest

from gameanything import demo, projects
from gameanything.conversation import Thread

STATIC = Path(__file__).resolve().parents[1] / "gameanything" / "ui" / "static"


def _png(p: Path, size=(64, 40), color=(200, 50, 50)):
    from PIL import Image
    p.parent.mkdir(parents=True, exist_ok=True); Image.new("RGB", size, color).save(p)


@pytest.fixture
def proj():
    e = projects.create("红楼梦", "adaptation", lang="zh"); root = Path(e["path"])
    _png(root / "4_design" / "targets" / "a.png", (1280, 840), (90, 160, 90))
    T = Thread(root)
    T.user_text("我想要一个宏大的园子")
    T.agent_text("收到，先画两张预览图。")
    T.card({"kind": "candidates", "key": "k1", "media": "image", "title": "挑一张",
            "items": [{"key": "A", "title": "A", "url": "/media/4_design/targets/a.png"}]})
    return root


def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha1(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}


def test_keys_match_the_page():
    assert demo.demo_key("/api/shell") == "api/shell.json"
    assert demo.demo_key("/api/play", "m=m6") == "api/play@m=m6.json"
    assert demo.demo_key("/api/thread", "after=e_1") == "api/thread.json"                      # the poll cursor is not part of the key
    assert demo.demo_key("/api/x", "b=2&a=1") == "api/x@a=1&b=2.json"
    assert demo.asset_path("/build/m1/play/a%20b.png") == "build/m1/play/a b.png"
    assert demo.asset_path("/build/m5/r.png?v=12") == "build/m5/r.png@v=12"


def test_for_demo_hides_what_needs_a_server():
    sh = demo.for_demo("shell", {"projects": [{"id": "a", "current": True, "last_opened": "2026-10-01T10:00:00"}, {"id": "b", "current": False}],
                                 "footer": {"requests": 3, "image_cost_usd": 2.5}, "backup": {"state": "ok"}, "hub": {"role": "owner"},
                                 "rounds": [{"m": "m2", "sub": "10 月 22 日 · 等你看录像"}, {"m": "m1", "sub": "5 条意见"}],
                                 "flow": {"next": {"wait": True, "hint": "agent 正在准备下一版", "route": "chat"}}})
    assert [p["id"] for p in sh["projects"]] == ["a"] and sh["footer"]["image_cost_usd"] is None and "hub" not in sh
    assert [r["m"] for r in sh["rounds"]] == ["m1", "m2"] and sh["rounds"][1]["sub"] == "等你看录像" and sh["flow"]["next"]["hint"] is None
    th = demo.for_demo("thread", {"events": [{"id": "e1", "session": "s", "source": "terminal", "auto": True}], "agent": {"online": True}, "build": [1]})
    assert th["events"] == [{"id": "e1", "auto": True}] and th["agent"]["online"] is False and th["build"] == []
    assert demo.strip_times({"at": "2026-10-21T05:47:20", "x": ["2026-10-21", "第 2 版"], "t": 4.5}) == {"at": "", "x": ["", "第 2 版"], "t": 4.5}


def test_export_is_static_and_leaves_the_project_alone(proj, tmp_path, writes):
    before = _tree(proj); reg = projects.load()
    out = tmp_path / "site" / "hlm"
    with writes() as w:
        st = demo.export(proj, out, cover=["1280x840:4,773,88,66"], log=lambda *a: None)
    assert _tree(proj) == before and projects.load() == reg                         # nothing in the project, nothing in the project list
    assert not [p for p in w if str(proj.resolve()) in p]
    for f in ("index.html", "app.html", "demo.js", "shell.js", "app.js", "i18n.js", "app.css", "fonts/inter-latin-wght-normal.woff2"):
        assert (out / f).is_file(), f
    idx = (out / "index.html").read_text(encoding="utf-8")
    assert "window.GA_DEMO=" in idx and '<script src="demo.js">' in idx and 'src="/' not in idx and "url(/fonts/" not in idx
    for lang in ("zh", "en"):
        sh = json.loads((out / "demo-data" / lang / "api" / "shell.json").read_text(encoding="utf-8"))
        assert sh["title"] == "红楼梦" and len(sh["projects"]) == 1
        th = json.loads((out / "demo-data" / lang / "api" / "thread.json").read_text(encoding="utf-8"))
        assert [e["text"] for e in th["events"] if e["type"] == "text"][0] == "我想要一个宏大的园子"
        assert all(e["at"] == "" for e in th["events"])                            # times blanked
    pic = out / "media" / "4_design" / "targets" / "a.png"
    assert pic.is_file() and st["covered"] == 1
    from PIL import Image
    im = Image.open(pic).convert("RGB"); assert im.getpixel((30, 800)) == (0, 0, 0) and im.getpixel((300, 300)) == (90, 160, 90)
    (out / "stale.json").write_text("{}", encoding="utf-8")                          # a second export into the same folder drops what is gone
    demo.export(proj, out, log=lambda *a: None)
    assert not (out / "stale.json").exists() and (out / "index.html").is_file()


def test_placeholder_replaces_own_photos(proj, tmp_path):
    """--placeholder: a picture the answers point at is exported as a neutral stand-in, never as the file itself."""
    out = tmp_path / "site" / "x"
    st = demo.export(proj, out, placeholder=["media/4_design/*"], log=lambda *a: None)
    from PIL import Image
    pic = out / "media" / "4_design" / "targets" / "a.png"
    assert st["hidden"] == 1 and Image.open(pic).size == (640, 400) and Image.open(pic).convert("RGB").getpixel((5, 5)) == (236, 236, 240)


def test_day_todo_uses_the_version_names():
    day = demo.for_demo("day", {"todo": [{"text": "看第 2 期：别的项目的名字的试玩录像", "href": "#play/m2"}, {"text": "去确认", "href": "#board"}]},
                        {"m2": ("第 2 版", "看", "的试玩录像")})
    assert [t["text"] for t in day["todo"]] == ["看第 2 版的试玩录像", "去确认"]


def test_export_refuses_a_folder_inside_the_project_or_not_a_demo(proj, tmp_path):
    with pytest.raises(SystemExit): demo.export(proj, proj / "demo")
    other = tmp_path / "busy"; other.mkdir(); (other / "notes.txt").write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit): demo.export(proj, other)


def test_scan_flags_what_should_not_be_public(tmp_path):
    d = tmp_path / "demo-data" / "zh" / "api"; d.mkdir(parents=True)
    (d / "thread.json").write_text(json.dumps({"events": [{"text": "key 在 /root/x/env.sh，花了 $0.70，问 a@b.com"}]}), encoding="utf-8")
    kinds = {h["kind"] for h in demo.scan(tmp_path)}
    assert {"path", "money", "email"} <= kinds


def test_normal_pages_are_unchanged(proj):
    """`gameanything ui` serves the pages without demo.js; shell.js only takes the demo route when GA_DEMO is set."""
    from gameanything.ui import serve
    box, ready = {}, threading.Event()
    threading.Thread(target=serve, args=(proj,), kwargs={"port": 0, "ready": lambda s: (box.update(s=s), ready.set())}, daemon=True).start()
    assert ready.wait(20)
    try:
        url = f"http://127.0.0.1:{box['s'].server_port}"
        html = urllib.request.urlopen(url + "/").read().decode("utf-8")
        assert "demo.js" not in html and "GA_DEMO" not in html
    finally:
        box["s"].shutdown(); box["s"].server_close()
    js = (STATIC / "shell.js").read_text(encoding="utf-8")
    assert 'if (window.GA_DEMO) f.src = window.GA_DEMO.map("/?embed=1#" + route); else f.src = BASE + "/?embed=1#" + route;' in js


NODE_PROBE = r"""
const out = {};
function boot(demoOn) {
  const calls = [];
  globalThis.location = { pathname: "/hlm/index.html", origin: "http://x" };
  const el = () => ({ classList: { add() {} }, appendChild() {}, style: {}, setAttribute() {}, getAttribute() { return null } });
  globalThis.document = { documentElement: el(), head: el(), body: el(), createElement: el, getElementById() { return null },
                          addEventListener() {}, querySelectorAll() { return [] } };
  globalThis.MutationObserver = class { observe() {} };
  globalThis.XMLHttpRequest = function () {}; XMLHttpRequest.prototype.open = function () {}; XMLHttpRequest.prototype.send = function () {};
  globalThis.Response = class { constructor(b) { this.b = b } json() { return Promise.resolve(JSON.parse(this.b)) } };
  globalThis.fetch = (u, o) => { calls.push([u, (o && o.method) || "GET"]); return Promise.resolve(new Response("{}")) };
  globalThis.toast = m => calls.push(["toast", m]);
  globalThis.window = globalThis;
  globalThis.GA_DEMO = demoOn ? { langs: ["zh", "en"], app: "app.html?embed=1" } : undefined;
  eval(require("fs").readFileSync(process.argv[2], "utf8"));
  return calls;
}
(async () => {
  let c = boot(true);
  await fetch("/api/play?m=m6", { headers: { "X-Lang": "en" } });
  await fetch("/api/thread", { headers: { "X-Lang": "zh" } });
  const r = await (await fetch("/api/thread/answer", { method: "POST", headers: {} })).json();
  out.on = { calls: c, refused: r, map: [GA_DEMO.map("/build/m1/play/video.mp4"), GA_DEMO.map("/?embed=1#play/m2"), GA_DEMO.map("/hlm/x.png"),
                                         GA_DEMO.map("http://e/x"), GA_DEMO.map("/build/m5/r.png?v=12")],
             keys: [GA_DEMO.key("/api/x", "?b=2&a=1&after=9"), GA_DEMO.key("/api/shell", "")] };
  c = boot(false);
  await fetch("/api/shell", {});
  out.off = { calls: c, demo: typeof GA_DEMO };
  console.log(JSON.stringify(out));
})();
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_demo_js_maps_reads_and_refuses_writes(tmp_path):
    subprocess.run(["node", "--check", str(STATIC / "demo.js")], check=True)
    probe = tmp_path / "probe.js"; probe.write_text(NODE_PROBE, encoding="utf-8")
    r = json.loads(subprocess.run(["node", str(probe), str(STATIC / "demo.js")], capture_output=True, text=True, check=True, encoding="utf-8").stdout)
    on = r["on"]
    assert on["calls"][0] == ["/hlm/demo-data/en/api/play@m=m6.json", "GET"]
    assert on["calls"][1] == ["/hlm/demo-data/zh/api/thread.json", "GET"]
    assert ["toast", "这是演示：只能看，不能修改"] in on["calls"] and not any(c[1] == "POST" for c in on["calls"] if c[0] != "toast")
    assert on["refused"]["ok"] is False and on["refused"]["demo"] is True
    assert on["map"] == ["/hlm/build/m1/play/video.mp4", "/hlm/app.html?embed=1#play/m2", None, None, "/hlm/build/m5/r.png@v=12"]
    assert on["keys"] == [demo.demo_key("/api/x", "b=2&a=1&after=9"), demo.demo_key("/api/shell")]
    assert r["off"]["calls"] == [["/api/shell", "GET"]] and r["off"]["demo"] == "undefined"      # without GA_DEMO the page is untouched
