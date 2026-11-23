"""`gameanything ui` with two tabs on one server: every tab is bound to its own project (/p/<id>/), so opening another project in one tab never
changes what the other tab's conversation or workspace shows (2026-10-24: the chat showed 红楼梦 while the workspace showed 香港美食)."""
import json
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from gameanything import projects
from gameanything.conversation import Thread
from gameanything.ui import BASE_PATCH

STATIC = Path(__file__).resolve().parents[1] / "gameanything" / "ui" / "static"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None


OPEN = urllib.request.build_opener(NoRedirect)


@pytest.fixture
def two():
    """Two projects of different kinds, each with its own words in its conversation; the server starts on A."""
    a = projects.create("红楼梦", "adaptation", lang="zh"); b = projects.create("香港美食", "feature", lang="zh")
    Thread(Path(a["path"])).user_text("A 的话：红楼梦", []); Thread(Path(b["path"])).user_text("B 的话：香港美食", [])
    from gameanything.ui import serve
    box, ready = {}, threading.Event()

    def up(srv): box["srv"] = srv; ready.set()
    threading.Thread(target=serve, args=(Path(a["path"]),), kwargs={"port": 0, "ready": up}, daemon=True).start()
    assert ready.wait(20), "the UI did not start"
    url = f"http://127.0.0.1:{box['srv'].server_port}"
    yield url, a, b
    box["srv"].shutdown(); box["srv"].server_close()


def req(url, data=None, headers=None, raw=False):
    h = {"Content-Type": "application/json", **(headers or {})}
    r = urllib.request.Request(url, json.dumps(data).encode() if data is not None else None, h)
    try:
        with OPEN.open(r, timeout=20) as resp: body = resp.read(); return resp.status, (body if raw else json.loads(body)), resp.headers
    except urllib.error.HTTPError as e:
        body = e.read(); return e.code, (body if raw or not body.startswith((b"{", b"[")) else json.loads(body)), e.headers


def texts(r): return [e.get("text") for e in r["events"] if e.get("text")]


def test_two_tabs_never_mix(two):
    url, a, b = two; A, B = f"{url}/p/{a['id']}", f"{url}/p/{b['id']}"; org = {"Origin": url}
    # "/" goes to the default project's own address; the page there knows it (and prefixes its calls)
    st, _, h = req(url + "/", raw=True); assert st == 302 and h["Location"] == f"/p/{a['id']}/"
    st, _, h = req(A, raw=True); assert st == 302 and h["Location"] == f"/p/{a['id']}/"
    st, html, _ = req(A + "/", raw=True); assert st == 200 and f'window.M2W_BASE="/p/{a["id"]}"'.encode() in html and BASE_PATCH.encode() in html
    st, html, _ = req(A + "/?embed=1", raw=True); assert st == 200 and b"app.js" in html and f'"/p/{a["id"]}"'.encode() in html
    # tab A polls its conversation, then tab B opens 香港美食 (the old single "current project" flipped here for every tab)
    st, ta, _ = req(A + "/api/thread"); assert st == 200 and any("红楼梦" in x for x in texts(ta))
    last = ta["events"][-1]["id"]
    st, r, _ = req(B + "/api/projects/open", {"id": b["id"]}, org); assert st == 200 and r["go"] == f"/p/{b['id']}/"
    for _ in range(2):                                                    # tab A keeps polling with its cursor: nothing of B comes in
        st, r, _ = req(A + f"/api/thread?after={last}"); assert st == 200 and r["events"] == []
    st, r, _ = req(A + "/api/thread"); assert texts(r) == texts(ta) and not any("香港" in x for x in texts(r))
    st, r, _ = req(B + "/api/thread"); assert any("香港美食" in x for x in texts(r)) and not any("红楼梦" in x for x in texts(r))
    # the shell and the workspace screens of each tab stay on that tab's project
    sa, sb = req(A + "/api/shell")[1], req(B + "/api/shell")[1]
    assert (sa["project_id"], sa["kind"]) == (a["id"], "adaptation") and (sb["project_id"], sb["kind"]) == (b["id"], "feature")
    assert [p["id"] for p in sa["projects"] if p["current"]] == [a["id"]] and [p["id"] for p in sb["projects"] if p["current"]] == [b["id"]]
    assert req(A + "/api/adaptation")[0] == 200 and req(B + "/api/feature")[0] == 200
    # writing from tab A lands in A only
    st, r, _ = req(A + "/api/thread", {"text": "从 A 标签页说的"}, org); assert st == 200 and r["ok"]
    assert "从 A 标签页说的" in texts(req(A + "/api/thread")[1]) and "从 A 标签页说的" not in texts(req(B + "/api/thread")[1])
    assert "从 A 标签页说的" in Thread(Path(a["path"])).events()[-1].get("text", "")
    # pictures / downloads / the workspace frame linked without the prefix: the page they came from decides (Referer)
    st, r, _ = req(url + "/api/shell", headers={"Referer": B + "/?embed=1"}); assert r["project_id"] == b["id"]
    st, r, _ = req(url + "/api/shell", headers={"Referer": A + "/"}); assert r["project_id"] == a["id"]
    st, _, h = req(url + "/?embed=1", headers={"Referer": A + "/"}, raw=True); assert st == 302 and h["Location"] == f"/p/{a['id']}/?embed=1"
    # an old address redirects inside the tab's project; a project that is not on the list is not served
    st, _, h = req(A + "/people", raw=True); assert st == 302 and h["Location"] == f"/p/{a['id']}/#people"
    assert req(url + "/p/no-such/api/shell", raw=True)[0] == 404
    # the server's default only moved for "/" and unprefixed scripts
    st, _, h = req(url + "/", raw=True); assert h["Location"] == f"/p/{b['id']}/"
    assert req(url + "/api/shell")[1]["project_id"] == b["id"]


def test_switch_game_and_remove_stay_in_their_tab(two):
    url, a, b = two; A, B = f"{url}/p/{a['id']}", f"{url}/p/{b['id']}"; org = {"Origin": url}
    req(B + "/api/projects/open", {"id": b["id"]}, org)
    st, r, _ = req(A + "/api/projects/game", {"id": a["id"], "game": "minecraft"}, org); assert st == 200 and r["game"] == "minecraft"
    assert req(A + "/api/shell")[1]["project_id"] == a["id"] and req(B + "/api/shell")[1]["project_id"] == b["id"]
    st, r, _ = req(B + "/api/projects/remove", {"id": b["id"]}, org); assert st == 200 and r["go"] == "/" and not r["welcome"]
    assert req(A + "/api/shell")[1]["project_id"] == a["id"] and req(B + "/api/shell", raw=True)[0] == 404
    st, _, h = req(url + "/", raw=True); assert h["Location"] == f"/p/{a['id']}/"            # the default moved to the one left
    # a new project from the welcome wizard: its own address
    st, r, _ = req(A + "/api/projects/new", {"title": "第三个", "kind": "memory"}, org); assert st == 200 and r["go"] == f"/p/{r['id']}/"
    assert req(url + r["go"] + "api/shell")[1]["project_id"] == r["id"] and req(A + "/api/shell")[1]["project_id"] == a["id"]


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_page_urls_use_the_bound_project():
    probe = """
const calls = []; globalThis.window = globalThis;
window.fetch = (u, o) => calls.push(u); globalThis.XMLHttpRequest = function () {}; XMLHttpRequest.prototype.open = function (m, u) { calls.push(m + " " + u); };
""" + BASE_PATCH + """
fetch("/api/thread");                                    // no project bound (the welcome page): unchanged
window.M2W_BASE = "/p/a"; fetch("/api/thread"); fetch("/p/a/api/shell"); fetch("//x/y"); new XMLHttpRequest().open("POST", "/api/upload");
window.M2W_BASE = "/p/b"; fetch("/api/feature");
console.log(JSON.stringify(calls));"""
    out = json.loads(subprocess.run(["node", "-"], input=probe, capture_output=True, text=True, encoding="utf-8", check=True).stdout)
    assert out == ["/api/thread", "/p/a/api/thread", "/p/a/api/shell", "//x/y", "POST /p/a/api/upload", "/p/b/api/feature"]
    sh, ob = (STATIC / "shell.js").read_text(encoding="utf-8"), (STATIC / "onboard.js").read_text(encoding="utf-8")
    assert 'f.src = BASE + "/?embed=1#"' in sh and "GAMEANYTHING_HUB.base" not in sh + ob     # the workspace frame and the wizard follow GAMEANYTHING_BASE
    for f in ("shell.js", "app.js", "onboard.js", "manage.js"):
        assert subprocess.run(["node", "--check", str(STATIC / f)]).returncode == 0


def test_divider_drag_never_turns_off_the_workspace_iframe():
    """Dragging the conversation/workspace divider must not set pointer-events:none on the workspace iframe: Chrome then stops scrolling
    the workspace with the mouse wheel after the drag (2026-10-26, 「右边工作区滚不动了」). A cover over .ws keeps the pointer in the shell
    instead, and the drag ends on pointercancel / lostpointercapture too, so the page can't stay in the dragging state."""
    import re
    css = (STATIC / "shell.html").read_text(encoding="utf-8")
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if "iframe" in sel:
            assert "pointer-events" not in body, f"pointer-events on the workspace iframe: {sel.strip()} {{{body}}}"
    assert re.search(r"\.dragging \.ws::after\s*\{[^}]*position:absolute[^}]*inset:0", css), "no cover over the workspace while dragging"
    assert re.search(r"\.ws\s*\{[^}]*position:relative", css)
    js = (STATIC / "shell.js").read_text(encoding="utf-8")
    drag = js[js.index("draggable divider"):js.index("dblclick")]
    for ev in ("pointerup", "pointercancel", "lostpointercapture"):
        assert ev in drag, f"the divider drag does not end on {ev}"
