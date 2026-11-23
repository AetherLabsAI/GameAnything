"""Her preference profile (gameanything/profile.py, `gameanything profile …`) and the pages that show the loop: the 我的偏好 page (#prefs, /api/profile:
see / edit / switch off / delete / add, links back to the feedback records, owner only under the hub) and the 「反馈和改进」 panel of the
开发状态 page (/api/feedback); both render in node in zh and en with no missing English."""
import json
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from gameanything import cli, feedback as F, profile as P, projects
from gameanything.conversation import Thread
from gameanything.ui import screens

STATIC = Path(screens.__file__).parent / "static"


@pytest.fixture
def study_on(isolated):
    """The 「反馈和改进」 panel exists in study mode only (study.py); the 我的偏好 page in both. tests/test_study.py has the panel off."""
    from gameanything import study
    study.set_global(True, by="test")


@pytest.fixture
def proj():
    root = Path(projects.create("无人生还", "adaptation", lang="zh", game="minecraft")["path"])
    (root / "4_design").mkdir(exist_ok=True)
    (root / "4_design" / "world_plan.yaml").write_text("world_plan:\n  milestones:\n    m1: {status: built, at: '2026-10-26T18:00:00'}\n    m2: {status: built, at: '2026-10-26T21:00:00'}\n", encoding="utf-8")
    for m in ("m1", "m2"): (root / "5_build" / m / "play").mkdir(parents=True)
    return root


def records(root):
    for text, m, t, at in (("这里有点简陋", "m1", 308.1, "2026-10-26T19:09:32"), ("这里这个客厅还是太简陋了", "m2", 330, "2026-10-26T22:04:00")):
        ev = Thread(root).user_text(text, [{"kind": "video", "m": m, "t": t}])
        T = Thread(root); lines = [json.dumps({**e, "at": at} if e["id"] == ev["id"] else e, ensure_ascii=False) for e in T.events()]
        T.log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    F.capture(root, Thread(root).events())
    F.set_fields(root, "f1", interpretation="客厅太简陋", target="客厅"); F.set_fields(root, "f2", interpretation="客厅还是太简陋", target="客厅")


# ---------------------------------------------------------------- store
def test_store_add_edit_toggle_remove_and_privacy():
    e = P.add("wenyi", "场景要丰富、精致", kind="sparse_plain", modes="adaptation,memory", sources=["adaptation-3:f1"], by="retrospective")
    assert e["id"] == "p1" and e["status"] == "candidate" and e["on"] is False and e["confidence"] == "low"
    assert e["modes"] == ["adaptation", "memory"] and e["from"] == [{"project": "adaptation-3", "record": "f1"}]
    assert P.applicable("wenyi", "adaptation") == []                                  # a candidate is off until she switches it on
    P.toggle("wenyi", "p1", True); assert [x["id"] for x in P.applicable("wenyi", "adaptation", "minecraft", "x")] == ["p1"]
    assert P.applicable("wenyi", "gameplay") == []                                    # mode filter
    mine = P.add("wenyi", "镜头不要抖", by="her"); assert mine["on"] and mine["status"] == "confirmed" and mine["confidence"] == "high"
    P.update("wenyi", "p1", text="场景要丰富", sources=["my-san-diego-memory:f3", "adaptation-3:f1"])
    assert len(P.load("wenyi")["entries"][0]["from"]) == 2
    with pytest.raises(P.ProfileError, match="modes"): P.add("wenyi", "x", modes="weird")
    with pytest.raises(P.ProfileError, match="空"): P.update("wenyi", "p1", text="  ")
    P.mark_used("wenyi", ["p1"]); assert P.load("wenyi")["entries"][0]["used"] == 1
    P.remove("wenyi", "p2"); assert [x["id"] for x in P.load("wenyi")["entries"]] == ["p1"]
    f = P.path("wenyi"); assert f.parent.name == "profiles" and f.parent.parent == projects.home()           # outside every project
    assert P.path("../evil") .parent == f.parent and P.load("nobody") == {"entries": []}


def test_cli(proj, capsys):
    assert cli.main(["profile", "add", "--project", str(proj), "--text", "场景要丰富", "--kind", "sparse_plain", "--from", "x:f1"]) == 0
    assert cli.main(["profile", "on", "--project", str(proj), "--id", "p1"]) == 0
    assert cli.main(["profile", "show", "--project", str(proj)]) == 0
    out = capsys.readouterr().out; assert "p1 [开·candidate·low] 场景要丰富" in out and "x:f1" in out
    assert P.owner_of(proj) == "local" and P.load("local")["entries"][0]["on"]


# ---------------------------------------------------------------- page data
@pytest.mark.usefixtures("study_on")
def test_page_data(proj):
    records(proj)
    P.add(P.owner_of(proj), "场景要丰富", text_en="Rich scenes", kind="sparse_plain", sources=[f"{F.project_id(proj)}:f1", "other-project:f9"], by="her")
    st = screens.profile_state(proj)
    e = st["entries"][0]; assert e["shown"] == "场景要丰富" and e["from"][0]["here"] and e["from"][0]["words"] == "这里有点简陋" and e["from"][1]["words"] == ""
    assert screens.profile_state(proj, "en")["entries"][0]["shown"] == "Rich scenes"
    fb = screens.feedback_state(proj)
    assert fb["exists"] and [r["id"] for r in fb["records"]] == ["f2", "f1"] and fb["records"][0]["repeat_of"] == ["f1"] and fb["records"][0]["repeat_strict"]
    assert fb["metrics"]["rfr_strict"]["k"] == 1 and fb["profile_on"] == 1 and fb["kinds"]["sparse_plain"] == "场景简陋 / 空 / 不精致"
    assert screens.feedback_state(proj, "en")["kinds"]["sparse_plain"].startswith("bare")
    with pytest.raises(ValueError): screens.save_profile(proj, {"op": "weird"})
    assert screens.save_profile(proj, {"op": "toggle", "id": "p1", "on": False})["entry"]["on"] is False


# ---------------------------------------------------------------- API (single user) and the hub (owner only)
@pytest.fixture
def ui(proj):
    from gameanything.ui import serve
    box, ready = {}, threading.Event()
    def up(srv): box["srv"] = srv; ready.set()
    threading.Thread(target=serve, args=(proj,), kwargs={"port": 0, "ready": up}, daemon=True).start()
    assert ready.wait(20)
    yield f"http://127.0.0.1:{box['srv'].server_port}"
    box["srv"].shutdown(); box["srv"].server_close()


def _req(url, body=None, origin=None):
    h = {"Content-Type": "application/json", **({"Origin": origin} if origin else {})}
    r = urllib.request.Request(url, json.dumps(body).encode() if body is not None else None, h)
    try:
        with urllib.request.urlopen(r, timeout=20) as x: return x.status, json.loads(x.read())
    except urllib.error.HTTPError as e: return e.code, None


@pytest.mark.usefixtures("study_on")
def test_api(ui, proj):
    records(proj)
    st, d = _req(ui + "/api/feedback"); assert st == 200 and len(d["records"]) == 2
    st, d = _req(ui + "/api/profile"); assert st == 200 and d["entries"] == []
    st, d = _req(ui + "/api/profile", {"op": "add", "text": "镜头不要抖"}, ui); assert st == 200 and d["entry"]["by"] == "her" and d["entry"]["on"]
    st, d = _req(ui + "/api/profile", {"op": "set", "id": "p1", "text": "镜头要稳", "modes": ["adaptation"]}, ui); assert st == 200 and d["entry"]["modes"] == ["adaptation"]
    st, d = _req(ui + "/api/profile", {"op": "toggle", "id": "p1", "on": False}, ui); assert st == 200 and not d["entry"]["on"]
    st, _ = _req(ui + "/api/profile", {"op": "remove", "id": "p9"}, ui); assert st == 400
    st, _ = _req(ui + "/api/profile", {"op": "remove", "id": "p1"}, ui); assert st == 200 and P.load("local")["entries"] == []


def test_hub_owner_only(monkeypatch):
    from test_hub import Client, add
    from gameanything.ui.hub import serve
    add("alice", admin=True); add("bob")
    box, ready = {}, threading.Event()
    def up(srv): box["srv"] = srv; ready.set()
    threading.Thread(target=serve, kwargs={"port": 0, "ready": up}, daemon=True).start()
    assert ready.wait(20)
    base = f"http://127.0.0.1:{box['srv'].server_port}"
    try:
        a = Client(base).login("alice"); b = Client(base).login("bob")
        code, r, _ = a.post("/api/hub/new", {"title": "Alice Garden", "kind": "feature", "game": "stardew", "lang": "en"}); pid = r["id"]
        P.add("alice", "my taste", by="her")
        code, d, _ = a.get(f"/p/{pid}/api/profile"); assert code == 200 and d["owner"] == "alice" and d["entries"][0]["text"] == "my taste"
        assert a.post(f"/p/{pid}/api/profile", {"op": "add", "text": "second"})[0] == 200
        assert b.get(f"/p/{pid}/api/profile")[0] == 403                                  # bob views the project, never alice's taste
        assert b.post(f"/p/{pid}/api/profile", {"op": "add", "text": "x"})[0] == 403
        assert b.get(f"/p/{pid}/api/feedback")[0] == 200
    finally:
        box["srv"].shutdown(); box["srv"].server_close()


# ---------------------------------------------------------------- the pages in node
def _node(part, data, call, lang):
    js = ("globalThis.window={addEventListener(){},parent:{postMessage(){}}};globalThis.document={documentElement:{dataset:{},getAttribute(){return null},setAttribute(){}},"
          "addEventListener(){},querySelectorAll(){return[]}};globalThis.localStorage={getItem(){return null},setItem(){}};globalThis.location={origin:'x'};\n"
          + (STATIC / "i18n.js").read_text(encoding="utf-8")
          + f"\nM2W.lang={json.dumps(lang)};const SCREENS={{}};const EMBED=true;const esc=s=>String(s??'');const icon=()=>'';"
          "const screen={innerHTML:''};const $=()=>screen;const $$=()=>[];const topbar=(c,r='')=>c+r;const nextStep=()=>'';const post=async()=>({ok:true});const toast=()=>{};"
          f"const DATA={json.dumps(data, ensure_ascii=False)};const get=async u=>DATA[u];\n" + part
          + f"\n{call}.then(()=>console.log(JSON.stringify({{html:screen.innerHTML,miss:[...M2W.miss]}})));")
    r = subprocess.run(["node", "-"], input=js, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
@pytest.mark.usefixtures("study_on")
def test_pages_render_in_node(proj):
    records(proj)
    P.add(P.owner_of(proj), "场景要丰富、精致", kind="sparse_plain", sources=[f"{F.project_id(proj)}:f1"], by="retrospective")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    part = app[app.index("/* ------------------------------------------------------------ 开发状态"):app.index("/* ------------------------------------------------------------ 工作台")]
    out = {}
    for lang in ("zh", "en"):
        data = {"/api/devstatus": screens.devstatus_state(proj, lang), "/api/feedback": screens.feedback_state(proj, lang), "/api/profile": screens.profile_state(proj, lang),
                "/api/now": {}}
        out[lang] = (_node(part, data, "SCREENS.status([],()=>true)", lang), _node(part, data, "SCREENS.prefs([],()=>true)", lang))
    (zs, zp), (es, ep) = out["zh"], out["en"]
    for s in ("反馈和改进", "这里这个客厅还是太简陋了", "你以前说过（f1）", "agent 的理解", "客厅还是太简陋", "我的偏好", "1/1 · 100%"):
        assert s in zs["html"], s
    for s in ("我的偏好", "场景要丰富、精致", "关着", "候选：你打开以后才会用", "这里有点简陋", "打开", "删掉", "自己加一条"):
        assert s in zp["html"], s
    assert es["miss"] == [] and ep["miss"] == [], (es["miss"], ep["miss"])
    assert "Feedback and improvement" in es["html"] and "这里有点简陋" in es["html"] and "My preferences" in ep["html"]       # her words stay as written


def test_page_script_wiring():
    app, i18n = (STATIC / "app.js").read_text(encoding="utf-8"), (STATIC / "i18n.js").read_text(encoding="utf-8")
    assert "SCREENS.prefs = async" in app and '"/api/profile"' in app and '"/api/feedback"' in app and 'prefs: "status"' in i18n
