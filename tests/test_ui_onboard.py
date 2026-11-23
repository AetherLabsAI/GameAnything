"""First run (ui/onboard.py, static/onboard.js): `gameanything ui` with no project starts and serves the welcome page; its examples fall back from
settings to the user's own play videos to the bundled stills; the wizard's create API for every kind and game; the per-game check's shape;
the flow stepper per kind; the coach-marks flag; and (node) that every text the new pages show has English."""
import json
import re
import shutil
import os
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml
from conftest import her_clicks
from gameanything import buildmode, cli, games as registry, projects
from gameanything.ui import onboard

STATIC = Path(onboard.__file__).parent / "static"
KINDS = list(projects.KINDS); GAMES = list(projects.GAMES)


# ---------------------------------------------------------------- a real server, no project yet
@pytest.fixture
def server(monkeypatch):
    from gameanything.ui import serve
    monkeypatch.setattr(onboard, "docker_ok", lambda: True)            # no docker call in tests
    monkeypatch.setattr(onboard, "machine", lambda: {"system": "linux", "backend": "docker", "kit": True, "docker": True, "pool": None,
                                                   "scripts": {"stardew", "minecraft", "cities_skylines", "slay_the_spire", "overcooked2", "valheim"}, "headless": False})
    box, ready = {}, threading.Event()

    def up(srv): box["srv"] = srv; ready.set()
    th = threading.Thread(target=serve, args=(None,), kwargs={"port": 18800, "ready": up}, daemon=True); th.start()
    assert ready.wait(20), "the UI did not start"
    port = box["srv"].server_port
    yield f"http://127.0.0.1:{port}"
    box["srv"].shutdown(); box["srv"].server_close()


def _get(url, raw=False, headers=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=20) as r:
            body = r.read(); return r.status, (body if raw else json.loads(body)), r.headers
    except urllib.error.HTTPError as e:
        body = e.read(); return e.code, (body if raw else json.loads(body or b"{}")), e.headers


def _post(url, data):
    req = urllib.request.Request(url, json.dumps(data).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")


def test_cli_ui_without_a_project_starts_the_server(monkeypatch):
    got = {}
    monkeypatch.setattr("gameanything.ui.serve", lambda root, *a, **k: got.setdefault("root", root))
    assert cli.main(["ui", "--port", "18799"]) == 0 and got["root"] is None          # no "pass --project" exit any more


def test_no_project_server_and_welcome(server):
    st, html, h = _get(server + "/", raw=True)
    assert st == 200 and b"/onboard.js" in html and h["Content-Type"].startswith("text/html")
    st, js, h = _get(server + "/onboard.js", raw=True); assert st == 200 and h["Content-Type"].startswith("text/javascript")
    assert _get(server + "/api/shell")[1]["no_project"] is True
    st, W, _ = _get(server + "/api/welcome")
    assert st == 200 and W["has_projects"] is False and W["open"] is False and W["kinds"] == KINDS and set(W["games"]) == set(GAMES)
    assert [x["source"] for x in W["examples"]] == ["bundled"] * 3 and all(x["video"] is None for x in W["examples"])
    for x in W["examples"]:                                                           # the bundled stills are served, small, and real SVG
        st, svg, h = _get(server + x["image"], raw=True)
        assert st == 200 and h["Content-Type"] == "image/svg+xml" and svg.lstrip().startswith(b"<svg") and len(svg) < 8000
    assert _get(server + "/examples/../onboard.py", raw=True)[0] == 404 or _get(server + "/examples/..%2Fonboard.py", raw=True)[0] == 404
    # everything that needs a project says so, it never crashes the handler
    for u in ("/api/thread", "/api/gather", "/api/day", "/app", "/api/play"):
        st, r, _ = _get(server + u); assert st == 409 and r["no_project"] is True
    st, r = _post(server + "/api/thread", {"text": "hi"}); assert st == 409 and r["no_project"] is True
    st, r = _post(server + "/api/coach", {"seen": True}); assert st == 409
    st, r, _ = _get(server + "/api/onboard/games"); assert st == 200 and r["mode"] in ("lab", "native") and len(r["games"]) == len(GAMES)


def test_wizard_create_every_kind_and_game(server):
    n = 0
    for k in KINDS:
        for g in GAMES:
            st, r = _post(server + "/api/projects/new", {"title": f"{k} {g}", "kind": k, "game": g, "lang": "zh"})
            assert st == 200 and r["ok"], r; n += 1
            e = projects.find(r["id"]); cfg = yaml.safe_load((Path(e["path"]) / "config" / "project.yaml").read_text(encoding="utf-8"))
            assert cfg == {"title": f"{k} {g}", "kind": k, "game": g, "lang": "zh", "id": r["id"], "decisions": "strict"}
            sh = _get(server + "/api/shell")[1]                                      # the server switched to the new project at once
            assert sh["project_id"] == r["id"] and sh["kind"] == k and sh["game_id"] == g and sh["coach_seen"] is False
            assert sh["flow"]["kind"] == k and sh["flow"]["current"] == "gather" and sh["flow"]["steps"][0]["state"] == "current"
            assert (Path(e["path"]) / "conversation" / "thread.jsonl").read_text(encoding="utf-8") == ""   # nothing said: agentd greets it
    assert len(projects.load()) == n == len(KINDS) * len(GAMES)
    W = _get(server + "/api/welcome")[1]; assert W["has_projects"] and W["open"] and len(W["projects"]) == len(KINDS) * len(GAMES)
    for bad in ({"title": "", "kind": "memory"}, {"title": "x", "kind": "novel"}, {"title": "x", "kind": "memory", "game": "doom"}):
        st, r = _post(server + "/api/projects/new", bad); assert st == 400 and not r["ok"]
    # coach marks: per project on the server
    st, r = _post(server + "/api/coach", {"seen": True}); assert st == 200 and r["coach_seen"] is True
    assert _get(server + "/api/shell")[1]["coach_seen"] is True


def test_removing_the_last_project_goes_back_to_the_welcome_page(server):
    r = _post(server + "/api/projects/new", {"title": "only", "kind": "memory"})[1]
    req = urllib.request.Request(server + "/api/projects/remove", json.dumps({"id": r["id"]}).encode(), {"Content-Type": "application/json", "Origin": server})
    with urllib.request.urlopen(req, timeout=20) as resp: out = json.loads(resp.read())
    assert out["ok"] and out["welcome"] is True and Path(out["trash"]).is_dir()
    assert _get(server + "/api/shell")[1]["no_project"] is True


# ---------------------------------------------------------------- examples: settings -> the user's own plays -> bundled
def _play(root: Path, m="m1", video=True, img="result/compare.jpg"):
    d = root / "5_build" / m / "play"; (d / Path(img).parent).mkdir(parents=True, exist_ok=True)
    (d / "play.yaml").write_text(f"milestone: {m}\nvideo: video.mp4\n", encoding="utf-8"); (d / img).write_bytes(b"\xff\xd8jpg")
    if video: (d / "video.mp4").write_bytes(b"\x00" * 4096)


def test_examples_fallback(tmp_path):
    assert [x["source"] for x in onboard.examples()] == ["bundled"] * 3                                  # nothing at all
    e1 = projects.create("Wedding", "memory"); e2 = projects.create("Castle", "adaptation", game="minecraft")
    projects.create("Empty", "feature")
    _play(Path(e1["path"])); _play(Path(e2["path"]), video=False, img="scenes/s1.png")
    ex = onboard.examples()
    assert [(x["title"], x["source"], bool(x["video_path"])) for x in ex] == [("Wedding", "project", True), ("Castle", "project", False)]
    pub = onboard.public(ex)
    assert pub[0]["image"] == "/example/0/image" and pub[0]["video"] == "/example/0/video" and pub[1]["video"] is None and pub[1]["game_name"] == "Minecraft"
    # settings win; an entry whose image is missing is skipped, a malformed one never reaches the page
    img = tmp_path / "still.png"; img.write_bytes(b"png"); vid = tmp_path / "v.mp4"; vid.write_bytes(b"mp4")
    projects.save_settings({"examples": [{"title": "Mine", "image": str(img), "video": str(vid), "kind": "gameplay", "game": "slay_the_spire"},
                                         {"title": "Gone", "image": str(tmp_path / "nope.png")}, {"image": 3}, "junk"]})
    assert [e["title"] for e in projects.settings()["examples"]] == ["Mine", "Gone"]
    ex = onboard.examples()
    assert [(x["title"], x["source"], x["kind"], x["video_path"]) for x in ex] == [("Mine", "settings", "gameplay", vid)]
    with pytest.raises(ValueError): projects.save_settings({"examples": "x"})


def test_example_files_are_served_with_range(server):
    e = projects.create("Wedding", "memory"); _play(Path(e["path"]))
    W = _get(server + "/api/welcome")[1]; x = W["examples"][0]
    assert x["source"] == "project" and x["video"]
    st, body, h = _get(server + x["video"], raw=True, headers={"Range": "bytes=0-99"})
    assert st == 206 and len(body) == 100 and h["Content-Range"] == "bytes 0-99/4096"
    assert _get(server + x["image"], raw=True)[0] == 200
    assert _get(server + "/example/9/image", raw=True)[0] == 404 and _get(server + "/example/0/secret", raw=True)[0] == 404


# ---------------------------------------------------------------- the wizard's game check
def _doctor(mode, games):
    return {"system": "linux" if mode == "lab" else "mac", "mode": mode, "games": games}


def _g(gid, installed, loader_ok=True, tool_ok=True):
    return {"game": gid, "installed": installed, "loader": {"ok": loader_ok, "name": "SMAPI"} if installed else None,
            "toolchain": {"ok": tool_ok, "name": ".NET SDK 6+", "setup": "https://dotnet.microsoft.com/download"}}


def _shape(r):
    assert set(r) >= {"system", "mode", "lab_ok", "games"} and [g["id"] for g in r["games"]] == GAMES
    for g in r["games"]:
        assert set(g) == {"id", "title", "ready", "modes", "checks"} and isinstance(g["ready"], bool)
        M = g["modes"]; assert M["recommended"] in ("lab", "native", None) and [o["mode"] for o in M["options"]] == ["native", "lab"]
        assert M["why"] in buildmode.TEXTS and all(o["name"] in buildmode.TEXTS and (o["ok"] or o["why"] in buildmode.TEXTS) for o in M["options"])
        assert M["recommended"] is None or next(o for o in M["options"] if o["mode"] == M["recommended"])["ok"]
        assert [c["key"] for c in g["checks"]] == ["found", "loader", "mode"]
        for c in g["checks"]:
            assert set(c) == {"key", "ok", "optional", "text", "fix", "vars"} and c["ok"] in (True, False, None)
            assert c["text"] in GAME_TEXTS and (not c["fix"] or c["fix"] in GAME_TEXTS)
    return {g["id"]: g for g in r["games"]}


GAME_TEXTS = None


@pytest.fixture(autouse=True)
def _texts():
    global GAME_TEXTS
    src = Path(onboard.__file__).read_text(encoding="utf-8")
    GAME_TEXTS = set(re.findall(r'"([^"]*[一-鿿][^"]*)"', src[src.index("LOADER_FIX"):src.index("# ---------------------------------------------------------------- the flow stepper")]))
    GAME_TEXTS |= set(registry.loader_fix().values())                          # the loader fixes come from each game.yaml (the registry)


def test_game_checks_lab_mode():
    """Linux with a working lab: the rows follow each game's recommended mode (buildmode.options)."""
    games = [_g("stardew", False), _g("minecraft", True, loader_ok=False), _g("cities_skylines", True)]
    G = _shape(onboard.game_checks(doctor=_doctor("lab", games), lab_ok=True))
    assert G["stardew"]["modes"]["recommended"] == "lab" and G["stardew"]["ready"]                # not installed here: the sandbox
    assert G["stardew"]["checks"][0]["ok"] is False and G["stardew"]["checks"][0]["optional"] is True and G["stardew"]["checks"][0]["fix"]
    assert G["minecraft"]["modes"]["recommended"] == "native" and not G["minecraft"]["ready"]       # installed, she can play it: her game, loader missing
    assert G["minecraft"]["checks"][1]["ok"] is False and "fabricmc.net" in G["minecraft"]["checks"][1]["fix"]
    assert G["slay_the_spire"]["checks"][0]["ok"] is None and G["slay_the_spire"]["modes"]["recommended"] == "lab" and G["slay_the_spire"]["ready"]
    assert G["sims4"]["modes"]["recommended"] is None             # no adapter in this doctor and no lab for it (no launch script, no pool): neither
    H = _shape(onboard.game_checks(doctor=_doctor("lab", games), lab_ok=True, hub=True))
    assert all(H[g]["modes"]["recommended"] == "lab" for g in ("stardew", "minecraft", "cities_skylines", "slay_the_spire")) and H["minecraft"]["ready"]
    G = _shape(onboard.game_checks(doctor=_doctor("lab", games), lab_ok=False))
    assert G["stardew"]["modes"]["recommended"] == "native" and not G["stardew"]["ready"]
    assert G["slay_the_spire"]["modes"]["recommended"] is None and not G["slay_the_spire"]["ready"]
    assert G["slay_the_spire"]["checks"][2]["fix"] == "启动 Docker 之后点“重新检查”"


def test_game_checks_native_mode():
    games = [_g("stardew", True), _g("minecraft", True, loader_ok=False), _g("cities_skylines", True, tool_ok=False)]
    G = _shape(onboard.game_checks(doctor=_doctor("native", games)))
    assert G["stardew"]["ready"] and G["stardew"]["checks"][2]["ok"] is True and G["stardew"]["modes"]["recommended"] == "native"
    assert not G["minecraft"]["ready"] and G["minecraft"]["checks"][1]["optional"] is False
    assert not G["cities_skylines"]["ready"] and G["cities_skylines"]["checks"][2]["fix"] == "还需要装 {t}：{u}"
    assert G["cities_skylines"]["checks"][2]["vars"]["u"].startswith("https://")
    assert not G["slay_the_spire"]["ready"] and G["slay_the_spire"]["modes"]["recommended"] is None      # macOS, no adapter: neither works yet
    assert G["slay_the_spire"]["checks"][2]["text"] == "构建方式：这台电脑上两种都还不能用"


def test_game_checks_real_doctor(monkeypatch):
    monkeypatch.setattr(onboard, "docker_ok", lambda: False)
    _shape(onboard.game_checks(force=True))


# ---------------------------------------------------------------- the flow stepper
def _sig(**kw):
    base = {"items": 0, "inbox": 0, "ingest_requested": False, "said": False, "board": False, "board_ok": False, "scenes": False, "scenes_ok": False,
            "spec": False, "spec_ok": False, "mapping": False, "mapping_ok": False, "content": False, "content_ok": False, "plan": False, "plan_ok": False,
            "looks": 0, "looks_unseen": 0, "previews": 0, "go_waiting": False, "started": False, "live": False, "play": False, "balance": False,
            "accepted": False, "final": False}
    return {**base, **kw}


def _flow(tmp_path, kind, **kw):
    r = tmp_path / kind; (r / "config").mkdir(parents=True, exist_ok=True)
    (r / "config" / "project.yaml").write_text(f"title: x\nkind: {kind}\n", encoding="utf-8")
    f = onboard.flow_state(r, _sig(**kw))
    return f["current"], f["next"]["label"], f["next"]["route"], [s["state"] for s in f["steps"]]


def test_flow_memory(tmp_path):
    assert _flow(tmp_path, "memory")[:3] == ("gather", "放进素材", "gather")
    assert _flow(tmp_path, "memory", inbox=3)[:3] == ("day", "把素材交给 agent 整理", "gather")
    assert _flow(tmp_path, "memory", inbox=3, ingest_requested=True)[1:3] == ("去对话里看看", "chat")
    assert _flow(tmp_path, "memory", items=5)[:3] == ("day", "去对话里看看", "chat")                    # the agent is shaping the day
    assert _flow(tmp_path, "memory", items=5, board=True)[:3] == ("day", "确认这一天", "board")
    assert _flow(tmp_path, "memory", items=5, board_ok=True, plan=True)[:3] == ("plan", "确认方案", "plan")
    assert _flow(tmp_path, "memory", items=5, board_ok=True, plan_ok=True, looks=3, looks_unseen=2)[:3] == ("preview", "看形象预览", "people")
    assert _flow(tmp_path, "memory", plan_ok=True, looks=3, go_waiting=True)[:3] == ("go", "在对话里点开工", "chat")
    cur, label, route, states = _flow(tmp_path, "memory", started=True, live=True)
    assert cur == "play" and label == "去对话里看看" and states == ["done"] * 4 + ["run", "current", "todo"]   # a later step marks the earlier done
    assert _flow(tmp_path, "memory", started=True, play=True)[:3] == ("play", "看试玩录像", "play")
    # a version accepted: the project loops into the next version (the agent asks what next) instead of jumping to 带回家
    assert _flow(tmp_path, "memory", accepted=True)[:3] == ("play", "去对话里看看", "chat")
    cur, label, route, states = _flow(tmp_path, "memory", final=True)
    assert cur is None and label == "都完成了" and route is None and states == ["done"] * 7


def test_flow_feature_adaptation_gameplay(tmp_path):
    assert _flow(tmp_path, "feature")[:3] == ("gather", "在对话里说你想加什么", "chat")
    assert _flow(tmp_path, "feature", said=True)[:3] == ("spec", "去对话里看看", "chat")                 # words in the chat count as material
    assert _flow(tmp_path, "feature", said=True, spec=True)[:3] == ("spec", "确认需求", "spec")
    assert len(_flow(tmp_path, "feature")[3]) == 6
    assert _flow(tmp_path, "adaptation")[:3] == ("gather", "放进作品", "gather")
    # adaptation runs on the flow state machine (flow.py; file-based cases in test_flow.py): with only the signals and no files, the
    # agent's next step after the work is ingested is the copyright note (config source / source_license), shown as a wait in 场景
    assert _flow(tmp_path, "adaptation", items=2, scenes=True)[:3] == ("scenes", "去对话里看看", "chat")
    assert _flow(tmp_path, "adaptation", inbox=2)[:3] == ("scenes", "把素材交给 agent 整理", "gather")
    cur, label, route, states = _flow(tmp_path, "adaptation", accepted=True)          # accepted: next version, not 「都完成了」
    assert (cur, label, route) == ("play", "去对话里看看", "chat") and states == ["done"] * 6 + ["current"]
    assert _flow(tmp_path, "gameplay")[:3] == ("gather", "说说你的经历", "gather")
    assert _flow(tmp_path, "gameplay", said=True, mapping=True)[:3] == ("mechanics", "确认机制映射", "mechanics")
    assert _flow(tmp_path, "gameplay", mapping_ok=True, content=True)[:3] == ("content", "确认内容", "content")
    assert _flow(tmp_path, "gameplay", content_ok=True, started=True, balance=True)[:3] == ("balance", "看平衡和试玩", "balance")
    assert _flow(tmp_path, "gameplay", content_ok=True, started=True, play=True)[:3] == ("balance", "看试玩录像", "play")


def test_flow_signals_from_files(tmp_path):
    """The same states read from real project files (what /api/shell does)."""
    e = projects.create("Day", "memory"); r = Path(e["path"])
    assert onboard.flow_state(r)["current"] == "gather"
    (r / "0_inbox" / "a.jpg").write_bytes(b"x"); (r / "0_inbox" / ".part").write_bytes(b"x")
    assert onboard.flow_state(r)["next"]["label"] == "把素材交给 agent 整理"
    (r / "1_ingest").mkdir(exist_ok=True); (r / "1_ingest" / "pack.yaml").write_text("items:\n- {id: a, kind: photo}\n", encoding="utf-8")
    (r / "3_remember" / "board.yaml").write_text("experience_board:\n  moments:\n  - {id: m1, title: 仪式}\n", encoding="utf-8")
    assert onboard.flow_state(r)["next"]["route"] == "board"
    (r / "feedback" / "board_review.yaml").write_text("state: confirmed\n", encoding="utf-8")
    her_clicks(r)                                     # stands for her click on the page
    (r / "4_design" / "world_plan.yaml").write_text("world_plan:\n  milestones:\n    m1: {status: next}\n", encoding="utf-8")
    assert onboard.flow_state(r)["next"] == {"label": "确认方案", "route": "plan", "wait": False, "hint": ""}
    (r / "feedback" / "plan_review.yaml").write_text("state: confirmed\n", encoding="utf-8")
    her_clicks(r)                                     # stands for her click on the page
    (r / "4_design" / "art").mkdir(); (r / "4_design" / "art" / "looks.yaml").write_text("p1: {upper: abigail}\n", encoding="utf-8")
    (r / "4_design" / "art" / "review.yaml").write_text("p1: {status: ok}\n", encoding="utf-8")
    from gameanything.conversation import Thread
    T = Thread(r); assert onboard.flow_state(r)["next"]["hint"] == "agent 会在对话里给你一张开工卡"
    ev = T.card({"kind": "go", "title": "开工", "milestone": "m1", "items": ["第一期"]})
    f = onboard.flow_state(r); assert f["current"] == "go" and f["next"]["label"] == "在对话里点开工"
    T.answer(ev["id"], {"decision": "start"}); assert onboard.flow_state(r)["current"] == "play"
    (r / "4_design" / "world_plan.yaml").write_text("world_plan:\n  milestones:\n    m1: {status: building}\n", encoding="utf-8")
    f = onboard.flow_state(r); assert [s["state"] for s in f["steps"]][4] == "run" and f["current"] == "play"
    p = r / "5_build" / "m1" / "play"; p.mkdir(parents=True); (p / "play.yaml").write_text("milestone: m1\n", encoding="utf-8")
    assert onboard.flow_state(r)["next"]["route"] == "play"


def test_coach_seen_roundtrip(tmp_path):
    r = tmp_path / "p"; (r / "config").mkdir(parents=True)
    assert onboard.coach_seen(r) is False
    assert onboard.set_coach_seen(r)["coach_seen"] is True and onboard.coach_seen(r) is True
    assert "coach_seen" in yaml.safe_load((r / "config" / "ui.yaml").read_text(encoding="utf-8"))
    assert onboard.set_coach_seen(r, False)["coach_seen"] is False and onboard.coach_seen(r) is False


# ---------------------------------------------------------------- the pages (node, no browser)
NODE_PRELUDE = ("globalThis.window={addEventListener(){},parent:null};globalThis.document={documentElement:{dataset:{},getAttribute(){return null},setAttribute(){}},"
                "addEventListener(){},querySelectorAll(){return[]}};globalThis.localStorage={getItem(){return null},setItem(){}};\n")


def _node(script: str):
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:   # a script file: -e hits the argv size limit
        f.write(script)
    try: out = subprocess.run(["node", f.name], capture_output=True, text=True, encoding="utf-8")
    finally: os.unlink(f.name)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_i18n_coverage():
    """Every Chinese text the shell, the workspace and the first-run pages show has English: t("…") literals in every page script, every
    Chinese string in onboard.js (its dictionaries included), and every text onboard.py sends (flow steps, the game check, bundled titles)."""
    src = {f: (STATIC / f).read_text(encoding="utf-8") for f in ("i18n.js", "manage.js", "onboard.js", "shell.js", "app.js", "tag.js", "hub.js")}
    keys = set()
    for f in ("shell.js", "manage.js", "app.js", "tag.js", "onboard.js", "hub.js"):
        keys |= {json.loads(f'"{m}"') for m in re.findall(r'\bt\(\s*"((?:[^"\\]|\\.)*)"', src[f])}
    for f in ("onboard.js", "hub.js"):                                       # every Chinese string, their dictionaries included
        body = re.sub(r"/\*.*?\*/|(?:^|\s)//[^\n]*", "", src[f], flags=re.S)          # comments are not shown
        keys |= {json.loads(f'"{m}"') for m in re.findall(r'"((?:[^"\\]|\\.)*)"', body)}
    pkg = registry.texts()                                                    # a game package's texts bring their own English (game.yaml *_en)
    assert all(pkg.values()), [k for k, v in pkg.items() if not v]
    keys |= onboard.TEXTS | {x["title"] for x in onboard.BUNDLED} | (GAME_TEXTS - set(pkg)) | buildmode.TEXTS
    keys = sorted(k for k in keys if re.search(r"[一-鿿]", k))
    miss = _node(NODE_PRELUDE + src["i18n.js"] + f"\nconsole.log(JSON.stringify({json.dumps(keys, ensure_ascii=False)}.filter(k => !(k in EN))))")
    assert miss == []
    # no developer words left in what the page shows
    shown = [k for k in keys if re.search(r"Claude Code|\bm2w [a-z]+|--project|协调者", k)]
    assert shown == []


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_pages_logic_in_node():
    """The stepper, the empty page's 下一步, the welcome page and the coach texts, rendered with a fake DOM (strings only)."""
    js = "".join((STATIC / f).read_text(encoding="utf-8") for f in ("i18n.js", "manage.js", "onboard.js"))
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    nxt = app[app.index("function nextStep(here) {"):]; nxt = nxt[:nxt.index("\n}\n") + 3]
    flow = {"kind": "memory", "current": "day", "next": {"label": "确认这一天", "route": "board", "wait": False, "hint": ""},
            "steps": [{"key": k, "label": lb, "route": r, "state": st} for (k, lb, r), st in zip(onboard.FLOWS["memory"], ["done", "current"] + ["todo"] * 5)]}
    wait = {**flow, "next": {"label": "去对话里看看", "route": "chat", "wait": True, "hint": "agent 正在写方案"}}
    W = {"projects": [], "open": False, "examples": onboard.public([dict(x, source="bundled") for x in onboard.BUNDLED])}
    MAC = buildmode.options("cities_skylines", {"system": "mac", "docker": False, "kit": False, "pool": None, "headless": False}, {"installed": True})
    probe = NODE_PRELUDE + """
const el = () => ({ innerHTML: "", hidden: true, onclick: null, classList: { add() {}, remove() {}, toggle() {} }, querySelectorAll() { return []; }, querySelector() { return el(); } });
const FLOW = el(); globalThis.$ = (s, r) => s === "#flow" ? FLOW : el(); globalThis.$$ = () => [];
globalThis.esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
globalThis.icon = n => `<svg data-i="${n}"></svg>`; globalThis.toast = () => {}; globalThis.ws = () => {};
""" + js + "\n" + nxt + f"""
var SH = {{ kind: "memory", flow: {json.dumps(flow, ensure_ascii=False)} }}; var EMBED = true;
const tabs = () => KIND_TABS[SH.kind] || [["gather", "upload", "素材"], ["home", "day", "这一天"], ["people", "people", "人物"], ["plan", "plan", "方案"], ["play", "play", "试玩"], ["keep", "home", "带回家"]];
const out = {{}};
renderFlow(); out.flow = FLOW.innerHTML; out.next = nextStep("home"); out.nextHere = nextStep("board");
SH.flow = {json.dumps(wait, ensure_ascii=False)}; renderFlow(); out.flowWait = FLOW.innerHTML; out.nextWait = nextStep("plan");
M2W.lang = "en"; SH.flow = {json.dumps(flow, ensure_ascii=False)}; renderFlow(); out.flowEn = FLOW.innerHTML;
M2W.lang = "zh"; const wl = el(); paintWelcome(wl, {json.dumps(W, ensure_ascii=False)}); out.welcome = wl.innerHTML;
out.coach = {{}}; for (const k of ["memory", "feature", "adaptation", "gameplay"]) {{ SH.kind = M2W.kind = k; out.coach[k] = coachSteps().map(s => s.body); }}
const MM = {json.dumps(MAC, ensure_ascii=False)}; out.modes = MM.options.map(o => modeOptHtml(o, MM, o.mode === MM.recommended)).join("");
M2W.lang = "en"; out.modesEn = MM.options.map(o => modeOptHtml(o, MM, false)).join(""); M2W.lang = "zh";
console.log(JSON.stringify(out));"""
    o = _node(probe)
    assert o["flow"].count('class="btn sm fnext') == 1 and "下一步：确认这一天" in o["flow"] and o["flow"].count('class="fs ') == 7
    assert 'class="fs done"' in o["flow"] and 'class="fs current"' in o["flow"]
    assert o["next"].count("btn sm") == 1 and 'href="#board"' in o["next"]
    assert "data-chat" in o["nextHere"] and "去对话里看看" in o["nextHere"]                       # the next step is this very page: say where to go
    assert "agent 正在写方案" in o["flowWait"] and "data-chat" in o["nextWait"] and o["nextWait"].count("btn sm") == 1
    assert "Next: Confirm the day" in o["flowEn"] and "Materials" in o["flowEn"]
    assert "开始第一个项目" in o["welcome"] and o["welcome"].count('class="wl-card"') == 3 and "怎么进行" in o["welcome"] and "示意图" in o["welcome"]
    assert all(len(v) == 7 for v in o["coach"].values())          # new project + the four kinds, then the five page tips
    assert all("新项目" in v[0] and "回忆项目" in v[1] and "玩法项目" in v[1] for v in o["coach"].values())
    # 「在哪里做」 on a Mac: her own game recommended with the reason, the sandbox greyed with why
    assert o["modes"].count('class="opt md') == 2 and o["modes"].count(" off") == 1 and "我的电脑（本机）" in o["modes"] and "建议" in o["modes"]
    assert "这台电脑是 macOS：直接装进你自己的游戏" in o["modes"] and "沙箱需要 Linux 和 Docker，这台电脑是 macOS" in o["modes"]
    assert "先备份你的存档，只改 Mods 文件夹" in o["modes"] and 'data-mode="lab" aria-disabled="true"' in o["modes"]
    assert "My computer (native)" in o["modesEn"] and "The sandbox needs Linux and Docker; this computer runs macOS" in o["modesEn"]
    assert "机制映射" in o["coach"]["gameplay"][2] and "需求" in o["coach"]["feature"][2] and "这一天" in o["coach"]["memory"][2]


def test_coach_seen_is_per_person_and_kind(tmp_path, monkeypatch):
    from gameanything.ui import onboard
    monkeypatch.setenv("GAMEANYTHING_HOME", str(tmp_path / "home"))
    a, b = tmp_path / "a", tmp_path / "b"; a.mkdir(); b.mkdir()
    assert not onboard.coach_seen(a, "memory", "wenyi")
    onboard.set_coach_seen(a, True, "memory", "wenyi")
    assert onboard.coach_seen(b, "memory", "wenyi")             # another project of the same kind: not again
    assert not onboard.coach_seen(b, "feature", "wenyi") and not onboard.coach_seen(b, "memory", "carol")
