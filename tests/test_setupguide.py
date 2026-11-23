"""The setting guides (setupguide.py, skills/gameanything/references/setups/): one guide per system x mode (+ the hub), the command that
picks it for the detected computer and records it in the project, the flow criterion that makes the agent read it before the first build
or launch, and the per-game tables kept equal to sandbox.sources(). No docker, no game, no network."""
import json
import re
from pathlib import Path

import pytest
import yaml
from conftest import her_clicks

from gameanything import cli, flow, projects, sandbox, setupguide
from gameanything import games as registry
from gameanything.conversation import Thread

ROOT = Path(__file__).resolve().parents[1]
GB = 2 ** 30
DOCKER_INFO = ("info", "--format", "{{.MemTotal}}")


class FakeProbe(sandbox.Probe):
    def __init__(self, platform, machine, env=None, runs=None, files=None, docker=True):
        self._p, self._m, self._e, self._runs, self._files, self._docker = platform, machine, env or {}, runs or {}, files or {}, docker

    def platform(self): return self._p
    def machine(self): return self._m
    def env(self): return dict(self._e)
    def run(self, argv, timeout=6): return self._runs.get(tuple(argv[1:]) if argv[0] == "/usr/bin/docker" else tuple(argv))
    def which(self, name): return "/usr/bin/docker" if name == "docker" and self._docker else None
    def read(self, path): return self._files.get(path)
    def windows_memory(self): return 16 * GB


LINUX = lambda: FakeProbe("linux", "x86_64", env={"DISPLAY": ":0"}, runs={DOCKER_INFO: str(31 * GB)}, files={"/proc/version": "Linux version 6.8"})
MAC = lambda: FakeProbe("darwin", "arm64", runs={DOCKER_INFO: str(8 * GB), ("sysctl", "-n", "hw.memsize"): str(16 * GB)})
WIN = lambda: FakeProbe("win32", "AMD64", env={"PROCESSOR_ARCHITECTURE": "AMD64"}, runs={DOCKER_INFO: str(16 * GB)})
WSL = lambda: FakeProbe("linux", "x86_64", runs={DOCKER_INFO: str(16 * GB)}, files={"/proc/version": "Linux version 5.15-microsoft-standard-WSL2"})


def proj(game="stardew", kind="memory", mode=None, owner=None):
    e = projects.create("t", kind, game=game, build_mode=mode, owner=owner); return Path(e["path"])


# ---------------------------------------------------------------- the guides
def test_a_guide_for_every_system_and_mode_and_the_hub():
    names = {f"{s}-{m}" for s in sandbox.SYSTEMS for m in setupguide.MODES} | {"server-sandbox"}
    assert set(setupguide.GUIDES) == names
    for n in names:
        if n == "server-sandbox" and not setupguide.guide_path(n).is_file(): continue   # internal/: maintainers' checkouts only
        t = setupguide.guide_path(n).read_text(encoding="utf-8")
        for h in ("## Checklist", "## Prerequisites", "## Settings to change", "## How to check", "## Resources", "## Games in this setting",
                  "## Known pitfalls", "## Tell the user before launching"):
            assert h in t, (n, h)
        assert setupguide.BEGIN in t and setupguide.END in t, n
        assert len(setupguide.checklist(n)) >= 4, n
    for n in ("mac-sandbox", "windows-sandbox"):                      # not tested on a real machine yet: the guide says so
        assert "not yet verified" in setupguide.guide_path(n).read_text(encoding="utf-8").lower(), n
    assert "Rosetta" in setupguide.guide_path("mac-sandbox").read_text(encoding="utf-8")
    w = setupguide.guide_path("windows-sandbox").read_text(encoding="utf-8")
    assert ".wslconfig" in w and "uid" in w and "GPU" in w
    assert "mac-native.md" in (ROOT / "docs/native-mac-checklist.md").read_text(encoding="utf-8")
    assert all(f"setups/{n}.md" in (ROOT / "docs/install.md").read_text(encoding="utf-8") for n in names - {"server-sandbox"})
    # the hub's guide is internal (maintainers only, 2026-10-30): not in the skill the user's agent gets, not linked from the user's docs
    assert setupguide.guide_path("server-sandbox") == ROOT / "internal" / "setups" / "server-sandbox.md"
    assert not (ROOT / "skills" / "gameanything" / "references" / "setups" / "server-sandbox.md").exists()
    assert "server-sandbox" not in (ROOT / "docs/install.md").read_text(encoding="utf-8")


def test_no_internal_hosts_in_the_guides():
    for n in setupguide.GUIDES:
        if n == "server-sandbox" and not setupguide.guide_path(n).is_file(): continue   # internal/: maintainers' checkouts only
        t = setupguide.guide_path(n).read_text(encoding="utf-8")
        assert not re.search(r"wc-cities|mclab|docker-rt|/workspace/\w|hosting/", t), n


# ---------------------------------------------------------------- the per-game tables = sandbox.sources()
def _rows(name):
    t = setupguide.guide_path(name).read_text(encoding="utf-8")
    body = t.split(setupguide.BEGIN, 1)[1].split(setupguide.END, 1)[0]
    out = {}
    for ln in body.strip().splitlines()[2:]:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        out[re.search(r"`([^`]+)`", cells[0]).group(1)] = cells
    return out


def test_tables_are_up_to_date():
    assert setupguide.tables() == [], "run: gameanything setup tables --write"


@pytest.mark.parametrize("name", setupguide.GUIDES)
def test_tables_agree_with_the_wizard_rules(name):
    if not setupguide.guide_path(name).is_file(): pytest.skip("the hub's guide is in internal/: maintainers' checkouts only")
    rows = _rows(name); m = setupguide.table_machine(name)
    assert list(rows) == list(registry.games())
    for g, cells in rows.items():
        src = sandbox.sources(g, m); verdict = cells[1]
        if name.endswith("-sandbox"):
            rec = src.get("recommended")
            assert (verdict == "recommended") == (rec not in (None, "native")), (name, g)
            usable = any(o["available"] for o in src.get("options") or [] if o["source"] != "native")
            assert (verdict == "not available") == (not src["offered"] or not usable), (name, g)
        else:
            assert (verdict == "recommended") == (src.get("recommended") == "native" or not src["offered"]), (name, g)
    if name == "mac-sandbox":    # her decisions, spelled out: 10-29 (3D, Minecraft), 10-30 (native only), 10-31 (the 2D Steam games, FEX)
        avail = {g for g, r in rows.items() if r[1] != "not available"}
        assert avail == sandbox.FEX_GAMES and "graphics card" in rows["minecraft"][-1]
        assert all("FEX" in rows[g][-1] and "arm64" in rows[g][3] for g in avail)
    if name == "mac-native":
        assert rows["minecraft"][1] == rows["ksp"][1] == rows["stardew"][1] == "recommended"
        assert rows["stardew"][2] == "2026-10-25"                        # verified on a real Mac (game.yaml verified:)


def test_tables_check_finds_drift(tmp_path):
    for n in setupguide.GUIDES:
        if setupguide.guide_path(n).is_file(): (tmp_path / f"{n}.md").write_text(setupguide.guide_path(n).read_text(encoding="utf-8"), encoding="utf-8")
    f = tmp_path / "linux-sandbox.md"; f.write_text(f.read_text(encoding="utf-8").replace("| recommended |", "| available |", 1), encoding="utf-8")
    assert setupguide.tables(root=tmp_path) == ["linux-sandbox"]
    assert setupguide.tables(write=True, root=tmp_path) == ["linux-sandbox"] and setupguide.tables(root=tmp_path) == []


# ---------------------------------------------------------------- the command picks the guide for the detected computer
@pytest.mark.parametrize("probe,game,mode,guide", [
    (LINUX, "stardew", None, "linux-sandbox"),
    (LINUX, "stardew", "native", "linux-native"),
    (WSL, "minecraft", None, "linux-sandbox"),
    (MAC, "stardew", None, "mac-native"),                  # 2026-10-30: a Mac is native only (2D too: the Steam client crashes)
    (MAC, "minecraft", None, "mac-native"),                # needs a GPU: native first on a Mac
    (MAC, "ksp", None, "mac-native"),
    (MAC, "minecraft", "lab", "mac-sandbox"),              # her choice in the project wins
    (WIN, "valheim", None, "windows-sandbox"),
    (WIN, "sims4", "native", "windows-native"),
    (LINUX, "nms", None, "linux-native"),                  # not in the sandbox wizard
])
def test_the_command_picks_the_guide(probe, game, mode, guide):
    root = proj(game, mode=mode)
    inf = setupguide.info(root, probe=probe(), hub=False)
    assert inf["guide_name"] == guide and Path(inf["guide"]).is_file() and inf["checklist"] == setupguide.checklist(guide)
    assert inf["mode_from"] == ("project" if mode else "recommended") and inf["verdict"]["game"] == game
    if probe is MAC: assert any("emulated" in w or "ARM" in w for w in inf["verdict"]["warnings"])


def test_docker_missing_still_points_to_the_sandbox_guide_with_native_as_the_other(monkeypatch):
    monkeypatch.setattr(setupguide, "_gamebench_lab", lambda env=None: False)     # a user's Linux computer, not a gamebench server
    inf = setupguide.info(proj("stardew"), probe=FakeProbe("linux", "x86_64", docker=False), hub=False)
    assert inf["guide_name"] == "linux-sandbox" and inf["verdict"]["verdict"] == "not available" and "Docker" in inf["verdict"]["why"]
    inf = setupguide.info(proj("stardew"), probe=FakeProbe("darwin", "arm64", docker=False), hub=False)     # a Mac: native only
    assert inf["guide_name"] == "mac-native"


def test_hub_and_failed_detection():
    root = proj("stardew", owner="alice")                               # a hub project: the server's system decides
    inf = setupguide.info(root, probe=LINUX())
    assert inf["hub"] and inf["guide_name"] == "server-sandbox" and inf["machine"]["where"] == "server"
    root = proj("minecraft", mode="native", owner="alice")               # native on the hub = her own computer: ask which
    inf = setupguide.info(root, probe=LINUX())
    assert inf["ask_system"] and inf["guide"] is None
    inf = setupguide.info(root, probe=LINUX(), system="mac")
    assert inf["guide_name"] == "mac-native" and inf["verdict"]["verdict"] == "recommended"
    inf = setupguide.info(proj(), probe=FakeProbe("sunos5", "sparc"), hub=False)
    assert inf["ask_system"] and inf["guide"] is None
    assert setupguide.info(proj(), probe=FakeProbe("sunos5", "sparc"), hub=False, system="windows")["guide_name"] == "windows-sandbox"


def test_cli_prints_records_and_keeps_the_rest_of_project_yaml(monkeypatch, capsys):
    root = proj("minecraft", mode="lab")
    f = root / "config" / "project.yaml"; f.write_text(f.read_text(encoding="utf-8") + "# her note\nnative_launch: ask\n", encoding="utf-8")
    real = sandbox.detect
    monkeypatch.setattr(sandbox, "detect", lambda env=None, hub=False, probe=None: real(probe=MAC(), hub=hub))
    assert cli.main(["setup", "guide", "--project", str(root), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["guide_name"] == "mac-sandbox" and out["recorded"]["mode"] == "sandbox" and out["recorded"]["system"] == "mac"
    assert cli.main(["setup", "guide", "--project", str(root), "--mode", "native"]) == 0
    txt = capsys.readouterr().out
    assert "mac-native.md" in txt and "READ THE WHOLE GUIDE" in txt and "Minecraft" in txt
    t = f.read_text(encoding="utf-8"); cfg = yaml.safe_load(t)
    assert t.count("setup:") == 1 and "# her note" in t and cfg["native_launch"] == "ask" and cfg["build_mode"] == "lab"
    assert cfg["setup"]["mode"] == "native" and cfg["setup"]["arch"] == "arm64" and cfg["setup"]["guide_shown_at"]
    assert cli.main(["setup", "guide", "--project", str(root), "--no-record", "--mode", "sandbox"]) == 0
    assert yaml.safe_load(f.read_text(encoding="utf-8"))["setup"]["mode"] == "native"
    assert cli.main(["setup", "tables"]) == 0


# ---------------------------------------------------------------- the flow criterion
def _feature_at_go(mode=None):
    root = proj("overcooked2", kind="feature", mode=mode); T = Thread(root)
    T.user_text("加一个关卡")
    q = T.card({"kind": "questions", "key": "feature-questions", "title": "q", "items": [{"n": 1, "text": "x", "hint": "y"}], "en": {"title": "q"}})
    T.answer(q["id"], {"answers": {}})
    (root / "3_remember").mkdir(exist_ok=True)
    (root / "3_remember" / "feature.yaml").write_text(yaml.safe_dump({"title": "t", "goal": "g", "items": [{"id": "f1", "what": "w", "how": "h", "done_when": "d"}]}), encoding="utf-8")
    T.card({"kind": "understanding", "key": "spec", "title": "s", "points": [{"id": "a", "text": "b"}], "en": {"title": "s"}})
    (root / "feedback" / "feature_review.yaml").write_text("state: confirmed\n", encoding="utf-8")
    her_clicks(root)                                     # stands for her click on the page
    (root / "4_design").mkdir(exist_ok=True)
    (root / "4_design" / "world_plan.yaml").write_text(yaml.safe_dump({"world_plan": {"milestones": {"m1": {"status": "next"}}}}), encoding="utf-8")
    (root / "feedback" / "plan_review.yaml").write_text("state: confirmed\nmilestone: m1\n", encoding="utf-8")
    her_clicks(root)                                     # stands for her click on the page
    T.card({"kind": "understanding", "key": "plan", "title": "p", "points": [{"id": "a", "text": "b"}], "en": {"title": "p"}})
    return root, T


def _setup(n): return next((c for c in n["step"]["criteria"] if c["id"] == "setup_guide"), None)


def test_flow_lists_the_setting_guide_until_it_is_read_and_again_when_the_mode_changes():
    root, T = _feature_at_go(mode="lab")
    n = flow.next_step(root)
    assert n["todo"] == "go" and not _setup(n)["ok"] and "setup guide" in n["actions"][0] and n["card_required"] == ["go_card"]
    setupguide.record(root, setupguide.info(root, machine=sandbox.machine("linux")))
    n = flow.next_step(root); assert _setup(n)["ok"] and not any("setup guide" in a for a in n["actions"])
    from gameanything import buildmode
    buildmode.set_mode(root, "native")                                  # she switched to native: read the native guide
    n = flow.next_step(root); assert not _setup(n)["ok"] and "build_mode" in n["actions"][0]
    setupguide.record(root, setupguide.info(root, machine=sandbox.machine("linux")))
    assert _setup(flow.next_step(root))["ok"] and yaml.safe_load((root / "config" / "project.yaml").read_text(encoding="utf-8"))["setup"]["guide"] == "linux-native"


def test_flow_asks_again_on_another_computer(monkeypatch):
    root, T = _feature_at_go()
    monkeypatch.setattr(setupguide.osdirs, "system", lambda: "linux")     # recorded on a Linux computer (whatever runs the test: on a
    setupguide.record(root, setupguide.info(root, machine=sandbox.machine("linux")))   # Mac the host was "mac" and nothing changed)
    assert _setup(flow.next_step(root))["ok"]
    monkeypatch.setattr(setupguide.osdirs, "system", lambda: "mac")
    n = flow.next_step(root); assert not _setup(n)["ok"] and "换了电脑" in n["actions"][0]


def test_every_kind_has_it_in_the_go_step():
    for kind in ("memory", "feature", "adaptation", "gameplay"):
        root = proj(kind=kind); F = flow.facts(root)
        go = next(s for s in flow.steps_of(kind) if s["id"] == "go")
        assert any(c["id"] == "setup_guide" for c in go["crit"](F)), kind
        assert "setup guide" in flow.doc_path(kind, "go").read_text(encoding="utf-8"), kind


def test_finished_and_running_projects_are_not_reopened():
    root = proj()                                                       # every version built: nothing waits for a build
    (root / "4_design").mkdir(exist_ok=True)
    (root / "4_design" / "world_plan.yaml").write_text(yaml.safe_dump({"world_plan": {"milestones": {"m1": {"status": "built"}, "final": {"status": "accepted"}}}}), encoding="utf-8")
    assert flow.c_setup(flow.facts(root))[0]["ok"]
    n = flow.next_step(root); assert not any("setup guide" in a for a in n["actions"])
    root, T = _feature_at_go()                                          # a round whose build she already started
    go = T.card({"kind": "go", "key": "m1-go", "milestone": "m1", "title": "v1", "items": ["a"], "estimate": {"wall_h": [1, 2], "cost_usd": None, "account": "subscription"}, "en": {"title": "v1"}})
    T.answer(go["id"], {"decision": "start"})
    n = flow.next_step(root); assert n["todo"] == "build" and "go" in n["done"]
    assert flow.c_setup(flow.facts(root))[0]["ok"]


def test_guide_counts_as_read_only_with_the_read_marks_spread_through_it(monkeypatch, capsys):
    """QA 2026-10-29: running the command recorded guide_read_at although Gemini could not open the guide file. QA 2026-10-30: the token
    was on the last line (`| tail -3` was enough) and in --json read_token: now 3 marks spread through the guide, none near its end."""
    import re
    root = proj("minecraft", mode="lab")
    real = sandbox.detect
    monkeypatch.setattr(sandbox, "detect", lambda env=None, hub=False, probe=None: real(probe=MAC(), hub=hub))
    assert cli.main(["setup", "guide", "--project", str(root)]) == 0
    out = capsys.readouterr().out
    body = setupguide.guide_path("mac-sandbox").read_text(encoding="utf-8")
    assert body.strip().splitlines()[-1] in out, "the whole guide is printed"
    lines = out.splitlines()
    at = [i for i, ln in enumerate(lines) if "read mark" in ln and re.search(r"read mark \d of 3: [0-9a-f]{6}", ln)]
    assert len(at) == 3
    assert all(len(lines) - i > 8 for i in at), "no mark in the last lines"
    tail = "\n".join(lines[-5:]); assert not re.search(r"[0-9a-f]{6}-[0-9a-f]{6}", tail)
    tk = "-".join(re.search(r"read mark \d of 3: ([0-9a-f]{6})", lines[i]).group(1) for i in at)
    s = yaml.safe_load((root / "config" / "project.yaml").read_text(encoding="utf-8"))["setup"]
    assert s.get("guide_shown_at") and not s.get("guide_read_at") and setupguide.stale(projects.config_of(root)) == "never"
    assert cli.main(["setup", "guide", "--project", str(root), "--read", "deadbeef"]) == 2
    assert cli.main(["setup", "guide", "--project", str(root), "--read", tk.split("-")[-1]]) == 2, "the last mark alone is not enough"
    assert cli.main(["setup", "guide", "--project", str(root), "--read", tk]) == 0
    assert setupguide.stale(projects.config_of(root)) == "" and tk == setupguide.token(root, "mac-sandbox")
    assert cli.main(["setup", "guide", "--project", str(root)]) == 0, "shown again: the read stays for the same guide"
    assert setupguide.stale(projects.config_of(root)) == ""
    capsys.readouterr()
    assert cli.main(["setup", "guide", "--project", str(root), "--json"]) == 0
    j = json.loads(capsys.readouterr().out)
    assert "read_token" not in j and tk not in json.dumps(j) and j["guide_text"].count("read mark") == 3


def test_a_single_users_headless_server_gets_the_linux_sandbox_guide(monkeypatch):
    """A Linux server with no display is `where: server`; when it is the user's own (no hub, no gamebench lab: `gameanything lab sandbox`)
    the guide is linux-sandbox, not the hub's server-sandbox with seats (plain-Docker E2E from a fresh clone, 2026-10-30)."""
    headless = lambda: FakeProbe("linux", "x86_64", env={})
    monkeypatch.setattr(setupguide, "_gamebench_lab", lambda env=None: False)
    inf = setupguide.info(proj("valheim", mode="lab"), probe=headless(), hub=False)
    assert inf["machine"]["where"] == "server" and inf["guide_name"] == "linux-sandbox" and not inf["shared_server"]
    assert "this server (yours)" in setupguide.text(inf)
    assert setupguide.info(proj("valheim", mode="lab", owner="alice"), probe=headless())["guide_name"] == "server-sandbox"   # the hub
    monkeypatch.setattr(setupguide, "_gamebench_lab", lambda env=None: True)                                                 # a gamebench lab
    inf = setupguide.info(proj("valheim", mode="lab"), probe=headless(), hub=False)
    assert inf["guide_name"] == "server-sandbox" and "the hub's server" in setupguide.text(inf)
