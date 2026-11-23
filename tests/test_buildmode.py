"""Where a project's builds run (buildmode.py, approved 2026-10-24): the recommendation table on Linux / macOS / Windows, with and without a
working lab, the game installed or not, no native adapter, a game no sandbox runs; lab availability (gamebench launch scripts per engine, the
broker pool); the project setting (wizard API, the project menu, CLI new --mode / set-mode / migrate-mode, native doctor --project) and that a
project without build_mode keeps the old automatic rule."""
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from gameanything import agentd, buildmode, cli, native, projects
from gameanything.ui import onboard

INST = {"installed": True}
MISSING = {"installed": False}


LAB_GAMES = {"stardew", "minecraft", "cities_skylines", "slay_the_spire", "overcooked2", "valheim", "terraria", "civ6"}   # games with a launch script (no sims4)


def M(system="linux", docker=True, kit=True, pool=None, headless=False, scripts=LAB_GAMES):
    return {"system": system, "backend": "docker-rt" if system == "linux" else None, "kit": kit, "docker": docker, "pool": pool,
            "scripts": scripts, "headless": headless}


def rec(game, m, info, **kw):
    o = buildmode.options(game, m, info, **kw)
    by = {x["mode"]: x for x in o["options"]}
    assert [x["mode"] for x in o["options"]] == ["native", "lab"] and o["why"] in buildmode.TEXTS
    for x in o["options"]: assert (x["ok"] and not x["why"] and x["note"] in buildmode.TEXTS) or (not x["ok"] and x["why"] in buildmode.TEXTS)
    return o["recommended"], o["why"], by


# ---------------------------------------------------------------- the recommendation table
@pytest.mark.parametrize("system,name", [("mac", "macOS"), ("windows", "Windows")])
@pytest.mark.parametrize("docker", [True, False])
def test_mac_and_windows_native_lab_greyed(system, name, docker):
    for info in (INST, MISSING):
        r, why, by = rec("stardew", M(system, docker=docker), info)
        assert r == "native" and why == buildmode.WHY["not_linux"]
        assert not by["lab"]["ok"] and by["lab"]["why"] == buildmode.GREY["lab_os"] and by["lab"]["vars"] == {"s": name}
        assert by["native"]["note"] == (buildmode.NOTE["native"] if info is INST else buildmode.NOTE["native_missing"])
    r, why, by = rec("slay_the_spire", M(system, docker=docker), None)          # no adapter, no lab here: neither
    assert r is None and why == buildmode.WHY["none"] and by["native"]["why"] == "这个游戏还没有本机适配"


def test_linux_without_a_lab():
    for m, grey in ((M(docker=False), "lab_docker"), (M(kit=False, docker=False), "lab_kit"), (M(kit=False, docker=True), "lab_kit")):
        r, why, by = rec("minecraft", m, INST)
        assert r == "native" and why == buildmode.WHY["no_docker"] and by["lab"]["why"] == buildmode.GREY[grey]
    assert buildmode.GREY["lab_kit"] == "这台电脑上的沙箱还没配好"     # a bare Docker Desktop is not a lab


def test_linux_with_a_lab():
    r, why, _ = rec("stardew", M(), INST); assert (r, why) == ("native", buildmode.WHY["play"])              # installed, a desktop: play it yourself
    r, why, _ = rec("stardew", M(), INST, prefer="hands_off"); assert (r, why) == ("lab", buildmode.WHY["hands_off"])
    r, why, _ = rec("stardew", M(), MISSING); assert (r, why) == ("lab", buildmode.WHY["not_installed"])
    r, why, _ = rec("stardew", M(), INST, hub=True); assert (r, why) == ("lab", buildmode.WHY["hub"])         # a multi-user hub
    r, why, _ = rec("stardew", M(headless=True), INST); assert (r, why) == ("lab", buildmode.WHY["headless"])  # a server without a screen
    r, why, by = rec("slay_the_spire", M(), None)
    assert (r, why) == ("lab", buildmode.WHY["no_adapter"]) and not by["native"]["ok"] and by["native"]["why"] == "这个游戏还没有本机适配"


def test_steam_games_note_the_busy_account():
    for g in ("cities_skylines", "overcooked2", "valheim", "terraria", "civ6"):
        _, _, by = rec(g, M(), MISSING); assert by["lab"]["note"] == buildmode.NOTE["lab_steam"] and "Steam" in by["lab"]["note"]
    _, _, by = rec("minecraft", M(), MISSING); assert by["lab"]["note"] == buildmode.NOTE["lab"]


POOL = {"games": {"minecraft": {"mem_gb": 2.6, "gpu": True}, "stardew_valley": {"mem_gb": 1.5}, "slay_the_spire": {"mem_gb": 1.5},
                  "cities_skylines": {"steam": True}, "overcooked2": {"steam": True}},
        "sandboxes": {"wc-cities": {"kind": "steam", "gpu": True}, "sd": {"kind": "lab", "gpu": False, "games": ["stardew_valley", "slay_the_spire"]},
                      "ext": {"kind": "external", "games": ["minecraft"]}}}


def test_lab_follows_the_broker_pool():
    assert buildmode.lab_runs("stardew", POOL) and buildmode.lab_runs("slay_the_spire", POOL) and buildmode.lab_runs("cities_skylines", POOL)
    assert not buildmode.lab_runs("minecraft", POOL)                          # needs a GPU lab sandbox; only an external one lists it
    assert not buildmode.lab_runs("sims4", POOL)                              # not in the pool
    r, why, by = rec("sims4", M(pool=POOL), INST)
    assert (r, why) == ("native", buildmode.WHY["lab_cant"]) and by["lab"]["why"] == "沙箱还不能跑这个游戏"
    no_steam = {**POOL, "sandboxes": {k: v for k, v in POOL["sandboxes"].items() if k != "wc-cities"}}
    assert not buildmode.lab_runs("overcooked2", no_steam)
    r, _, by = rec("overcooked2", M(pool=no_steam), None); assert r is None and not by["lab"]["ok"]
    assert not buildmode.lab_runs("minecraft", None)                          # no pool file and no launch scripts: nothing
    assert buildmode.lab_runs("minecraft", None, {"minecraft"}) and not buildmode.lab_runs("sims4", None, {"minecraft"})
    r, _, by = rec("sims4", M(pool=None, scripts={"minecraft"}), INST); assert by["lab"]["why"] == "这台机器没配好这个游戏的沙箱"


def test_lab_scripts_follow_the_launch_folder(tmp_path):
    gb = tmp_path / "gamebench"
    for d, names in (("launch_rt", ["minecraft", "stardew_valley", "cities"]), ("launch", ["sims4", "slay_the_spire"])):
        (gb / "hosting" / d).mkdir(parents=True)
        for n in names: (gb / "hosting" / d / f"{n}.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    env = {"GAMEANYTHING_GAMEBENCH": str(gb)}
    assert buildmode.lab_scripts(env, "docker-rt") == {"minecraft", "stardew", "cities_skylines"}
    assert buildmode.lab_scripts(env, "docker") == set()            # plain Docker: not the launch folder, the ready games (test_labdocker.py)
    assert buildmode.lab_scripts({"GAMEANYTHING_GAMEBENCH": str(tmp_path / "none")}, "docker") == set()


def test_machine_lookup(tmp_path, monkeypatch):
    gb = tmp_path / "gamebench"; (gb / "hosting" / "launch_rt").mkdir(parents=True)
    pool_f = tmp_path / "pool.yaml"; pool_f.write_text(yaml.safe_dump(POOL), encoding="utf-8")
    env = {"GAMEANYTHING_GAMEBENCH": str(gb), "M2W_LAB_POOL": str(pool_f), "DOCKER_HOST": "unix:///tmp/docker-rt.sock", "PATH": ""}
    assert buildmode.backend(env) == "docker-rt" and buildmode.lab_kit(env) and buildmode.pool(env=env)["games"]["overcooked2"]["steam"]
    assert buildmode.backend({**env, "DOCKER_HOST": "unix:///run/docker.sock"}) == "docker"
    assert not buildmode.lab_kit({**env, "DOCKER_HOST": "unix:///run/docker.sock"})            # plain Docker needs the seat driver + a lab config
    (gb / "hosting" / "launch").mkdir(); assert not buildmode.lab_kit({**env, "DOCKER_HOST": "unix:///run/docker.sock"})   # (test_labdocker.py)
    assert not buildmode.lab_kit({**env, "GAMEANYTHING_GAMEBENCH": str(tmp_path / "none")})               # Docker Desktop without gamebench: not a lab
    assert buildmode.pool(env={"M2W_LAB_POOL": str(tmp_path / "missing.yaml")}) is None           # no pool file: no hard failure
    m = buildmode.machine(env, sys_="linux", docker=True); assert m["kit"] and m["docker"] and m["backend"] == "docker-rt" and m["headless"]
    m = buildmode.machine({**env, "DISPLAY": ":0"}, sys_="mac"); assert not m["kit"] and not m["docker"] and m["pool"] is None and not m["headless"]
    fake = tmp_path / "bin" / "docker"; fake.parent.mkdir(); fake.write_text("#!/bin/sh\n", encoding="utf-8"); fake.chmod(0o755)
    assert buildmode.docker_bin({"GAMEANYTHING_DOCKER": str(fake), "PATH": ""}) == str(fake)
    monkeypatch.setattr(buildmode, "DOCKER_FALLBACK", (str(fake),)); assert buildmode.docker_bin({"PATH": ""}) == str(fake)   # /opt/docker-rt/bin off PATH
    monkeypatch.setattr(buildmode, "DOCKER_FALLBACK", ()); assert buildmode.docker_bin({"PATH": ""}) is None and not buildmode.docker_ok({"PATH": ""})


def test_new_adapters_show_up_by_themselves(monkeypatch):
    """all_options() covers every game of projects.GAMES; a game gets the native choice as soon as native.GAMES has an adapter."""
    d = {"system": "mac", "mode": "native", "games": [{"game": "stardew", "installed": True}, {"game": "slay_the_spire", "installed": False}]}
    o = buildmode.all_options(M("mac"), doctor=d)
    assert list(o) == list(projects.GAMES) and o["slay_the_spire"]["recommended"] == "native" and o["overcooked2"]["recommended"] is None


def test_cli_game_choices_follow_the_adapters(capsys):
    for g in native.GAMES:                                                     # the CLI's --game choices are native.GAMES, new adapters included
        assert cli.main(["native", "doctor", "--game", g, "--json"]) == 0
        assert [x["game"] for x in json.loads(capsys.readouterr().out)["games"]] == [g]


# ---------------------------------------------------------------- the project setting
def test_old_projects_keep_the_automatic_rule(tmp_path, monkeypatch):
    e = projects.create("Old one", "memory"); root = Path(e["path"])
    assert "build_mode" not in yaml.safe_load((root / "config" / "project.yaml").read_text(encoding="utf-8"))
    monkeypatch.setattr(buildmode, "docker_bin", lambda env=None: "/usr/bin/docker")
    monkeypatch.setattr(buildmode, "lab_kit", lambda env=None, backend_=None: True)              # this server: docker-rt + gamebench
    assert buildmode.mode_of(root) is None and buildmode.effective(root, sys_="linux") == ("lab", "auto")
    assert buildmode.effective(root, sys_="mac") == ("native", "auto")
    monkeypatch.setattr(buildmode, "lab_kit", lambda env=None, backend_=None: False)             # a CI runner: docker, no gamebench
    assert buildmode.effective(root, sys_="linux") == ("native", "auto")
    monkeypatch.setattr(buildmode, "lab_kit", lambda env=None, backend_=None: True)
    monkeypatch.setattr(buildmode, "docker_bin", lambda env=None: None)
    assert buildmode.effective(root, sys_="linux") == ("native", "auto")
    d = native.doctor(project=root); assert d["mode_source"] == "auto" and d["mode"] == d["auto_mode"] and d["project"]["build_mode"] is None
    buildmode.set_mode(e["id"], "lab")
    d = native.doctor(project=root); assert (d["mode"], d["mode_source"]) == ("lab", "project") and "this project chose" in d["mode_why"]
    t = (root / "config" / "project.yaml").read_text(encoding="utf-8")
    buildmode.set_mode(e["id"], "native"); t2 = (root / "config" / "project.yaml").read_text(encoding="utf-8")
    assert t2 == t.replace("build_mode: lab", "build_mode: native") and buildmode.mode_of(root) == "native"   # only that line changes
    with pytest.raises(ValueError): buildmode.set_mode(e["id"], "cloud")
    with pytest.raises(ValueError): projects.create("Bad", "memory", build_mode="cloud")


def test_cli_new_set_mode_migrate_doctor(capsys):
    assert cli.main(["project", "new", "--title", "Lab one", "--mode", "lab"]) == 0
    assert "build_mode=lab" in capsys.readouterr().out
    assert cli.main(["project", "new", "--title", "Plain one"]) == 0; capsys.readouterr()
    assert cli.main(["project", "new", "--title", "Mine", "--mode", "native", "--game", "minecraft"]) == 0; capsys.readouterr()
    ids = {e["title"]: e["id"] for e in projects.load()}
    cfg = lambda t: projects.config_of(Path(projects.find(ids[t])["path"]))
    assert cfg("Lab one")["build_mode"] == "lab" and "build_mode" not in cfg("Plain one") and cfg("Mine")["build_mode"] == "native"
    with pytest.raises(SystemExit): cli.main(["project", "new", "--title", "x", "--mode", "cloud"])
    assert cli.main(["project", "set-mode", ids["Lab one"], "native"]) == 0
    assert "build_mode=native" in capsys.readouterr().out and cfg("Lab one")["build_mode"] == "native"
    assert cli.main(["project", "set-mode", ids["Plain one"], "--show"]) == 0
    out = capsys.readouterr().out; assert "not chosen" in out and "native " in out and "lab " in out and "build_mode" not in cfg("Plain one")
    assert cli.main(["native", "doctor", "--project", ids["Mine"]]) == 0
    out = capsys.readouterr().out; assert "mode native (chosen by the project)" in out
    from gameanything import osdirs
    assert ("[native] lab: backend" in out) == (osdirs.system() == "linux") and "gamebench kit" not in out
    assert cli.main(["native", "doctor", "--project", ids["Plain one"], "--json"]) == 0
    d = json.loads(capsys.readouterr().out); assert d["mode_source"] == "auto" and set(d["lab"]) == {"backend", "gamebench", "kit", "pool"}
    # migration: opt-in, only projects without one, dry run writes nothing
    assert cli.main(["project", "migrate-mode", "--dry-run"]) == 0
    assert ids["Plain one"] in capsys.readouterr().out and "build_mode" not in cfg("Plain one")
    assert cli.main(["project", "migrate-mode"]) == 0
    out = capsys.readouterr().out; assert ids["Plain one"] in out and ids["Mine"] not in out
    assert cfg("Plain one")["build_mode"] == "lab" and cfg("Mine")["build_mode"] == "native" and cfg("Lab one")["build_mode"] == "native"
    assert cli.main(["project", "migrate-mode"]) == 0 and "already has" in capsys.readouterr().out


def test_resident_prompt_says_the_mode(tmp_path):
    e = projects.create("P", "memory", build_mode="native"); root = Path(e["path"])
    t = agentd.render_prompt(e, root, "agentd:p", tmp_path / "req")
    assert "build mode `native`" in t and "{{build_mode}}" not in t and "{{project_id}}" not in t and "never docker" in t
    e2 = projects.create("Q", "memory"); t2 = agentd.render_prompt(e2, Path(e2["path"]), "agentd:q", tmp_path / "req")
    assert "(not chosen yet: the automatic rule)" in t2


# ---------------------------------------------------------------- the wizard API and the project menu
@pytest.fixture
def server(monkeypatch):
    from gameanything.ui import serve
    monkeypatch.setattr(onboard, "machine", lambda: M())
    box, ready = {}, threading.Event()

    def up(srv): box["srv"] = srv; ready.set()
    threading.Thread(target=serve, args=(None,), kwargs={"port": 0, "ready": up}, daemon=True).start()
    assert ready.wait(20)
    yield f"http://127.0.0.1:{box['srv'].server_port}"
    box["srv"].shutdown(); box["srv"].server_close()


def _req(url, data=None):
    r = urllib.request.Request(url, json.dumps(data).encode() if data is not None else None, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=20) as resp: return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")


def test_wizard_api_and_project_menu(server):
    st, G = _req(server + "/api/onboard/games?force=1"); assert st == 200
    g = {x["id"]: x for x in G["games"]}
    assert set(g) == set(projects.GAMES) and g["slay_the_spire"]["modes"]["recommended"] == "lab" and not G["hub"]
    assert g["stardew"]["modes"]["recommended"] == "lab"                     # not installed on the test machine: the sandbox
    st, r = _req(server + "/api/projects/new", {"title": "Wiz", "kind": "memory", "game": "stardew", "mode": "native"}); assert st == 200 and r["ok"]
    root = Path(projects.find(r["id"])["path"]); assert buildmode.mode_of(root) == "native"
    sh = _req(server + "/api/shell")[1]; assert (sh["build_mode"], sh["build_mode_source"]) == ("native", "project")
    st, r2 = _req(server + "/api/projects/mode", {"id": r["id"], "mode": "lab"}); assert st == 200 and r2["build_mode"] == "lab"
    assert buildmode.mode_of(root) == "lab" and _req(server + "/api/shell")[1]["build_mode"] == "lab"
    st, bad = _req(server + "/api/projects/mode", {"mode": "cloud"}); assert st == 400 and not bad["ok"]
    st, bad = _req(server + "/api/projects/new", {"title": "x", "kind": "memory", "mode": "cloud"}); assert st == 400
    st, r3 = _req(server + "/api/projects/new", {"title": "No choice", "kind": "memory"}); assert st == 200
    sh = _req(server + "/api/shell")[1]; assert sh["build_mode_source"] == "auto" and buildmode.mode_of(Path(projects.find(r3["id"])["path"])) is None


def test_lab_paths_come_only_from_the_environment_or_settings(tmp_path, monkeypatch):
    for k in ("GAMEANYTHING_GAMEBENCH", "WC_CODE", "GAMEANYTHING_LAB_POOL", "M2W_LAB_POOL"): monkeypatch.delenv(k, raising=False)
    assert buildmode.gamebench_path() is None and buildmode.pool_path() is None and buildmode.gamebench() is None    # a user's machine
    gb = tmp_path / "gb"; (gb / "hosting").mkdir(parents=True); pool_f = tmp_path / "labs" / "pool.yaml"
    (projects.home() / "settings.yaml").write_text(f"gamebench: {gb}\nlab_pool: {pool_f}\n", encoding="utf-8")
    assert buildmode.gamebench() == gb and buildmode.pool_path() == pool_f                                            # a lab server's settings
    monkeypatch.setenv("GAMEANYTHING_LAB_POOL", str(tmp_path / "other.yaml"))
    assert buildmode.pool_path() == tmp_path / "other.yaml"                                                           # the environment wins
