"""The development status (gameanything/devstatus.py, `gameanything status …`, 5_build/STATUS.yaml): the schema and its normalization, init's
seeds (go card, world plan, her unhandled words), the edits (items, regressions, issues, recheck, feedback, decisions), the warning in
`gameanything build deliver`, the result card, the 开发状态 page's data and its API (single user and hub roles)."""
import json
from pathlib import Path

import pytest
import yaml

from gameanything import cli, delivery, devstatus as S, projects
from gameanything.conversation import Thread, check_card
from gameanything.ui import screens

PLAN = """world_plan:
  milestones:
    m1: {name: 第一版, status: built, what: "做：茶餐厅、奶茶、菠萝包"}
    m2: {name: 第二版, status: building}
"""


@pytest.fixture
def proj():
    root = Path(projects.create("香港美食", "feature", lang="zh")["path"])
    (root / "4_design").mkdir(exist_ok=True); (root / "4_design" / "world_plan.yaml").write_text(PLAN, encoding="utf-8")
    return root


def go(root, items=("三道菜都能做完", "奶茶颜色对", {"text": "菠萝包"})):
    return Thread(root).card({"kind": "go", "title": "第二版", "milestone": "m2", "items": list(items)})


def run(*a): return cli.main(["status", *a])


def test_missing_and_bad_files(proj):
    d, P = S.load(proj); assert d == S.empty() and P == [] and not S.exists(proj)
    S.path(proj).parent.mkdir(parents=True, exist_ok=True)
    S.path(proj).write_text("items: [\n", encoding="utf-8")
    d, P = S.load(proj); assert d["items"] == [] and P and "读不了" in P[0]
    with pytest.raises(S.StatusError, match="先把 STATUS.yaml 修好"): S.set_item(proj, None, "done", "x")         # never overwritten blindly
    S.path(proj).write_text(yaml.safe_dump({"items": [{"text": "a", "state": "weird"}, "b", 3, {"id": "r1", "text": "c", "state": "done"}],
                                            "known_issues": "not a list", "recheck": ["开局能走通"]}, allow_unicode=True), encoding="utf-8")
    d, P = S.load(proj)
    assert [x["id"] for x in d["items"]] == ["r1", "r2", "r1"] and d["items"][1] == {"id": "r2", "text": "b"}
    assert d["recheck"] == [{"id": "c1", "text": "开局能走通"}] and d["known_issues"] == []
    assert any("weird" in p for p in P) and any("第 3 项" in p for p in P) and any("id 重复" in p for p in P) and any("known_issues 应该是列表" in p for p in P)


def test_init_seeds_from_go_card_and_feedback(proj, capsys):
    T = Thread(proj)
    T.user_text("开工前说的话")                                         # before the go card: not open feedback
    ev = go(proj)
    T.user_text("奶茶太浅了"); T.user_text("页面操作", auto=True); T.agent_text("好的")
    assert run("init", "--project", str(proj)) == 0
    d, P = S.load(proj)
    assert P == [] and [x["text"] for x in d["items"]] == ["三道菜都能做完", "奶茶颜色对", "菠萝包"]
    assert [x["id"] for x in d["items"]] == ["r1", "r2", "r3"] and {x["state"] for x in d["items"]} == {"todo"}
    assert d["items"][0]["source"] == f"go:{ev['id']}" and d["build"] == "m1"
    assert [f["text"] for f in d["open_feedback"]] == ["奶茶太浅了"] and d["open_feedback"][0]["state"] == "open"
    assert "3 条要求" in capsys.readouterr().out
    # again: kept as is; --force merges new seeds and keeps the states
    S.set_item(proj, "r1", "done", build="m2", by="playtester")
    assert S.init(proj)["created"] is False
    go(proj, ["三道菜都能做完", "加一道丝袜奶茶"])
    r = S.init(proj, force=True); d, _ = S.load(proj)
    assert r["added"] == 1 and d["items"][0]["state"] == "done" and d["items"][-1] == {**d["items"][-1], "id": "r4", "text": "加一道丝袜奶茶", "state": "todo"}


def test_init_without_go_card_uses_the_world_plan(proj):
    S.init(proj); d, _ = S.load(proj)
    assert [x["text"] for x in d["items"]] == ["茶餐厅", "奶茶", "菠萝包"]          # m2 has nothing written yet: the newest milestone that has
    assert {x["source"] for x in d["items"]} == {"plan:m1"}


def test_items_regressions_issues(proj):
    S.init(proj)
    S.set_item(proj, None, text="新要求：音乐", state="todo")                    # a new item without id gets the next one
    d, _ = S.load(proj); new = d["items"][-1]; assert new["text"] == "新要求：音乐" and new["id"] == f"r{len(d['items'])}"
    with pytest.raises(S.StatusError, match="--text"): S.set_item(proj, "r99", "done")
    with pytest.raises(S.StatusError, match="--state"): S.set_item(proj, "r1", "finished")
    with pytest.raises(S.StatusError, match="--by"): S.set_item(proj, "r1", "done", by="critic")
    S.set_item(proj, "r1", "done", build="m2", by="builder", evidence="m2 第 1 轮 01:00")
    r = S.set_item(proj, "r1", "broken", build="m3", by="playtester")              # done -> broken = a regression
    d, P = S.load(proj); x = d["items"][0]
    assert x["state"] == "regressed" and x["since"] == "m3" and x["verified_by"] == "playtester" and x["evidence"] == "m2 第 1 轮 01:00"
    assert d["regressions"] == [{"id": "g1", "item": "r1", "what": x["text"], "broke_in": "m3", "cause": None, "fixed_in": None}] and "g1" in r["note"]
    assert P == [] and d["build"] == "m3"
    S.add_regression(proj, cause="换了 UI 库", iid="g1")
    S.add_regression(proj, what="菜单按钮没反应", broke_in="m3", item="r2")         # by hand: the item becomes regressed
    d, _ = S.load(proj); assert d["regressions"][0]["cause"] == "换了 UI 库" and d["items"][1]["state"] == "regressed"
    S.set_item(proj, "r1", "done", build="m4", by="playtester")                     # fixed: the open regression gets fixed_in
    S.add_regression(proj, fixed_in="m4", iid="g2")
    d, P = S.load(proj)
    assert [g["fixed_in"] for g in d["regressions"]] == ["m4", "m4"] and d["items"][1]["state"] == "done" and P == []
    with pytest.raises(S.StatusError): S.add_regression(proj, what="x")
    S.add_issue(proj, "开场镜头抖", "low", "m3", "m4 修"); S.add_issue(proj, "偶尔卡死", "high")
    d, _ = S.load(proj); assert [k["id"] for k in d["known_issues"]] == ["k1", "k2"]
    S.add_issue(proj, iid="k1", fixed=True); d, _ = S.load(proj); assert [k["id"] for k in d["known_issues"]] == ["k2"]
    with pytest.raises(S.StatusError): S.add_issue(proj, "x", "urgent")


def test_recheck_feedback_decisions(proj):
    T = Thread(proj); go(proj); e = T.user_text("能不能加音乐")
    S.init(proj)
    r = S.recheck(proj, add=["开局能走通", "菜单能点"]); assert [x["id"] for x in r["todo"]] == ["c1", "c2"]
    with pytest.raises(S.StatusError, match="没有 c9"): S.recheck(proj, passed=["c9"], build="m2")
    r = S.recheck(proj, build="m2", passed=["c1"], failed=["c2"], note="点了没反应")
    assert [x["id"] for x in r["todo"]] == [] and [x["id"] for x in r["failed"]] == ["c2"]
    d, _ = S.load(proj); assert d["recheck"][1]["note"] == "点了没反应" and d["recheck"][0]["by"] == "playtester" and d["build"] == "m2"
    assert [x["id"] for x in S.recheck(proj, build="m3")["todo"]] == ["c1", "c2"]                 # a new round: all to do again
    S.feedback(proj, e["id"], "answered"); d, _ = S.load(proj); assert d["open_feedback"][0]["state"] == "answered"
    later = T.user_text("还有菠萝油")
    with pytest.raises(S.StatusError, match="--add-event"): S.feedback(proj, later["id"], "open")
    S.feedback(proj, later["id"], add=True); d, _ = S.load(proj); assert d["open_feedback"][-1]["text"] == "还有菠萝油"
    with pytest.raises(S.StatusError, match="没有事件"): S.feedback(proj, "e_nope", add=True)
    S.decide(proj, "只做三道菜", event=e["id"]); d, _ = S.load(proj); assert d["decisions"][0]["text"] == "只做三道菜"


def test_deliver_warns_from_status(proj, monkeypatch):
    monkeypatch.setattr(delivery, "probe_video", lambda f: (True, "fake video"))
    play = proj / "5_build" / "m2" / "play"; play.mkdir(parents=True); (play / "video.mp4").write_bytes(b"\0" * 64)
    r = delivery.deliver(proj, "m2", "第二版")
    assert r["ok"] and any(k == "warn" and "STATUS.yaml" in t and "init" in t for k, t in r["lines"])        # no STATUS: say so, still delivered
    go(proj); S.init(proj); S.recheck(proj, add=["开局能走通"])
    S.set_item(proj, "r1", "done", build="m1", by="builder"); S.set_item(proj, "r1", "broken", build="m2", by="playtester")
    W = S.deliver_warnings(proj, "m2")
    assert any("坏的条目" in w and "r1" in w for w in W) and any("回归" in w for w in W) and any("复查还没做完" in w for w in W)
    r = delivery.deliver(proj, "m2")
    assert r["ok"] and sum(1 for k, t in r["lines"] if k == "warn" and ("复查" in t or "回归" in t or "坏的" in t)) >= 3
    S.set_item(proj, "r1", "done", build="m2", by="playtester"); S.recheck(proj, build="m2", passed=["c1"])
    for i in ("r2", "r3"): S.set_item(proj, i, "done", build="m2", by="playtester")
    assert S.deliver_warnings(proj, "m2") == []
    S.set_item(proj, "r2", "done", build="m2", by="builder")
    assert any("没有试玩独立确认" in w for w in S.deliver_warnings(proj, "m2"))


def test_show_and_result_card(proj, capsys):
    assert run("show", "--project", str(proj)) == 0 and "还没有" in capsys.readouterr().out
    go(proj); S.init(proj); S.set_item(proj, "r1", "done", build="m2", by="playtester"); S.set_item(proj, "r2", "partial", build="m2")
    S.add_issue(proj, "镜头抖", "low"); S.recheck(proj, add=["开局能走通"]); S.recheck(proj, build="m2", passed=["c1"])
    assert run("show", "--project", str(proj)) == 0
    out = capsys.readouterr().out
    assert "要求 3 条：做到 1 · 部分 1 · 还没做 1" in out and "镜头抖" in out and "1/1 在 m2 复查过" in out
    assert run("show", "--project", str(proj), "--json") == 0
    j = json.loads(capsys.readouterr().out); assert j["exists"] and j["counts"]["done"] == 1 and j["counts"]["recheck_done"] == 1
    c = S.result_card(proj, "m2", image="/build/m2/a.png")
    assert c["stats"][0] == "要求 3 条：做到 1 · 部分 1 · 还没做 1" and "已知问题 1 条" in c["stats"] and "复查 1/1 通过" in c["stats"]
    en = c.pop("en"); check_card(c); check_card({**c, **en})                          # a valid result card in both languages
    out_f = proj / "card.yaml"
    assert run("card", "--project", str(proj), "--m", "m2", "--out", str(out_f)) == 0
    assert yaml.safe_load(out_f.read_text(encoding="utf-8"))["kind"] == "result"
    # the README command without a subcommand still works
    assert run("--project", str(proj)) == 0 and (proj / "README.md").is_file()


def test_cli_edits(proj, capsys):
    go(proj); assert run("init", "--project", str(proj)) == 0
    assert run("set-item", "--project", str(proj), "--id", "r1", "--state", "done", "--build", "m2", "--by", "builder", "--evidence", "m2 r1 01:00") == 0
    assert run("set-item", "--project", str(proj), "--id", "r1", "--state", "broken", "--build", "m3", "--by", "playtester") == 0
    assert "回归 g1" in capsys.readouterr().out
    assert run("add-regression", "--project", str(proj), "--id", "g1", "--cause", "改了配方表") == 0
    assert run("add-issue", "--project", str(proj), "--text", "镜头抖", "--severity", "low", "--since", "m3") == 0
    assert run("recheck", "--project", str(proj), "--add", "开局能走通") == 0
    assert run("recheck", "--project", str(proj), "--build", "m3", "--fail", "c1", "--note", "卡在第一关") == 0
    assert "1 条没通过" in capsys.readouterr().out
    assert run("decide", "--project", str(proj), "--text", "第四道菜放下一版") == 0
    with pytest.raises(SystemExit): run("set-item", "--project", str(proj), "--id", "r1", "--state", "nope")
    with pytest.raises(SystemExit): run("feedback", "--project", str(proj))
    d, P = S.load(proj)
    assert P == [] and d["items"][0]["state"] == "regressed" and d["regressions"][0]["cause"] == "改了配方表" and d["recheck"][0]["last_result"] == "fail"


def test_page_data(proj):
    st = screens.devstatus_state(proj)
    assert st["exists"] is False and st["items"] == [] and st["counts"]["total"] == 0
    go(proj); e = Thread(proj).user_text("奶茶太浅"); S.init(proj)
    S.set_item(proj, "r1", "done", build="m1", by="builder"); S.set_item(proj, "r1", "broken", build="m2", by="playtester")
    S.set_item(proj, "r2", "done", build="m2", by="playtester", text_en="The milk tea colour is right")
    S.add_issue(proj, "偶尔卡死", "high"); S.add_issue(proj, "镜头抖", "low")
    S.recheck(proj, add=["开局能走通", "菜单能点"]); S.recheck(proj, build="m2", passed=["c1"])
    S.feedback(proj, e["id"], "handled"); Thread(proj).user_text("再加一道"); S.init(proj, force=True)
    st = screens.devstatus_state(proj)
    assert [x["state"] for x in st["items"]] == ["regressed", "todo", "done"]                      # the worst first
    assert [k["severity"] for k in st["known_issues"]] == ["high", "low"] and st["regressions"][0]["fixed_in"] == ""
    assert [x["this_round"] for x in st["recheck"]] == [True, False] and st["build"] == "m2"
    assert [(f["text"], f["state"]) for f in st["open_feedback"]] == [("再加一道", "open"), ("奶茶太浅", "handled")]      # open first
    en = screens.devstatus_state(proj, "en")
    assert "The milk tea colour is right" in [x["text"] for x in en["items"]] and en["open_feedback"][0]["text"] == "再加一道"   # her words as written


@pytest.fixture
def ui(proj):
    import threading
    from gameanything.ui import serve
    box, ready = {}, threading.Event()
    def up(srv): box["srv"] = srv; ready.set()
    threading.Thread(target=serve, args=(proj,), kwargs={"port": 0, "ready": up}, daemon=True).start()
    assert ready.wait(20), "the UI did not start"
    yield f"http://127.0.0.1:{box['srv'].server_port}"
    box["srv"].shutdown(); box["srv"].server_close()


def _get(url, headers=None):
    import urllib.error, urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=20) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, None


def test_api(ui, proj):
    st, d = _get(ui + "/api/devstatus"); assert st == 200 and d["exists"] is False
    go(proj); S.init(proj); S.set_item(proj, "r1", "done", build="m2", by="playtester")
    st, d = _get(ui + "/api/devstatus"); assert st == 200 and d["exists"] and d["counts"]["done"] == 1 and len(d["items"]) == 3
    st, d = _get(ui + "/api/devstatus", {"X-Lang": "en"}); assert st == 200 and d["items"][0]["text"]
    import urllib.error, urllib.request
    req = urllib.request.Request(ui + "/api/devstatus", b"{}", {"Content-Type": "application/json", "Origin": ui})
    with pytest.raises(urllib.error.HTTPError) as e: urllib.request.urlopen(req, timeout=20)
    assert e.value.code == 404                                                      # read only: no way to write it from the page


def test_hub_roles(monkeypatch):
    """Under gameanything hub, a viewer of the project reads the page; someone without access (a private project) gets 403."""
    import threading
    from test_hub import Client, add                                              # tests/test_hub.py's helpers (users with passwords, a cookie jar)
    from gameanything.ui.hub import serve
    from gameanything import users
    add("alice", admin=True); add("bob")
    box, ready = {}, threading.Event()
    def up(srv): box["srv"] = srv; ready.set()
    threading.Thread(target=serve, kwargs={"port": 0, "ready": up}, daemon=True).start()
    assert ready.wait(20)
    base = f"http://127.0.0.1:{box['srv'].server_port}"
    try:
        a = Client(base).login("alice"); b = Client(base).login("bob")
        code, r, _ = a.post("/api/hub/new", {"title": "Alice Garden", "kind": "feature", "game": "stardew", "lang": "en"}); pid = r["id"]
        root = Path(projects.find(pid)["path"]); go(root); S.init(root)
        assert a.get(f"/p/{pid}/api/devstatus")[0] == 200
        code, d, _ = b.get(f"/p/{pid}/api/devstatus"); assert code == 200 and len(d["items"]) == 3          # view role: reads it
        assert b.post(f"/p/{pid}/api/devstatus", {})[0] in (403, 404)
        cfg = root / "config" / "project.yaml"; c = yaml.safe_load(cfg.read_text(encoding="utf-8")); c["visibility"] = "private"
        cfg.write_text(yaml.safe_dump(c, allow_unicode=True), encoding="utf-8"); assert users.private(root)
        assert b.get(f"/p/{pid}/api/devstatus")[0] == 403
    finally:
        box["srv"].shutdown(); box["srv"].server_close()


def test_page_script_has_the_screen():
    static = Path(screens.__file__).parent / "static"
    app, shell, i18n = ((static / f).read_text(encoding="utf-8") for f in ("app.js", "shell.js", "i18n.js"))
    assert "SCREENS.status = async" in app and '"/api/devstatus"' in app and '["status", "status", "开发状态"]' in app
    assert '["status", "status", "开发状态"]' in shell and i18n.count('["status", "status", "开发状态"]') == 2 and '"开发状态": "Dev status"' in i18n
    assert 'id="i-status"' in (static / "app.html").read_text(encoding="utf-8") and 'id="i-status"' in (static / "shell.html").read_text(encoding="utf-8")


@pytest.mark.skipif(not __import__("shutil").which("node"), reason="node is not installed")
def test_page_renders_in_node(proj):
    """SCREENS.status with the real /api/devstatus data and a fake DOM: the html has every section, the state chips, and English in EN."""
    import subprocess
    go(proj); e = Thread(proj).user_text("奶茶太浅"); S.init(proj)
    S.set_item(proj, "r1", "done", build="m1", by="builder"); S.set_item(proj, "r1", "broken", build="m2", by="playtester")
    S.set_item(proj, "r2", "done", build="m2", by="playtester", evidence="m2 第 2 轮 03:12")
    S.add_issue(proj, "偶尔卡死", "high", "m2", "查日志"); S.recheck(proj, add=["开局能走通"]); S.recheck(proj, build="m2", passed=["c1"])
    S.decide(proj, "只做三道菜", event=e["id"])
    static = Path(screens.__file__).parent / "static"
    app = (static / "app.js").read_text(encoding="utf-8")
    part = app[app.index("/* ------------------------------------------------------------ 开发状态"):app.index("\nroute();          // last")]
    out = {}
    for lang in ("zh", "en"):
        data = json.dumps(screens.devstatus_state(proj, lang), ensure_ascii=False)
        js = ("globalThis.window={addEventListener(){},parent:{postMessage(){}}};globalThis.document={documentElement:{dataset:{},getAttribute(){return null},setAttribute(){}},"
              "addEventListener(){},querySelectorAll(){return[]}};globalThis.localStorage={getItem(){return null},setItem(){}};globalThis.location={origin:'x'};\n"
              + (static / "i18n.js").read_text(encoding="utf-8")
              + f"\nM2W.lang={json.dumps(lang)};const SCREENS={{}};const EMBED=true;const esc=s=>String(s??'');const icon=()=>'';"
              "const screen={innerHTML:''};const $=()=>screen;const $$=()=>[];const topbar=(c,r='')=>c+r;const nextStep=()=>'';"
              f"const get=async()=>({data});\n" + part
              + "\nSCREENS.status([],()=>true).then(()=>console.log(JSON.stringify({html:screen.innerHTML,miss:[...M2W.miss]})));")
        r = subprocess.run(["node", "-"], input=js, capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr
        out[lang] = json.loads(r.stdout)
    zh, en = out["zh"]["html"], out["en"]["html"]
    for s in ("开发状态", "你的要求", "以前好的，现在坏了", "回归", "已知问题", "每一版都要复查", "你说过的话", "定下来的事", "奶茶太浅", "在对话里看", "试玩 agent 验证过"):
        assert s in zh, s
    assert "ds-bad" in zh and "ds-ok" in zh and 'data-ev="' + e["id"] + '"' in zh
    assert out["en"]["miss"] == [] and "Your requests" in en and "Worked before, broken now" in en and "奶茶太浅" in en      # her words stay as written
