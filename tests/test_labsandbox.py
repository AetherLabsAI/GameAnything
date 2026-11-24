"""`gameanything lab sandbox` (labsandbox.py, sandbox.sandbox_argv): the user's own sandbox on plain Docker, no gamebench, no seats
(2026-10-30, docs/sandbox-hiccups.md #27). A fake docker client: only argv lists, nothing runs."""
import argparse
import json
from pathlib import Path

import pytest

from gameanything import buildmode, builds, labsandbox, sandbox


def test_sandbox_argv_writes_every_option_the_plain_docker_test_needed(monkeypatch):
    monkeypatch.setattr(sandbox, "host_apparmor", lambda root="/": 3)
    monkeypatch.setattr(sandbox, "PLATFORM", "linux/amd64")                        # an x86 computer (this test may run on a Mac)
    a = sandbox.sandbox_argv("valheim", "My Wedding!", gpu=True, image_uid=1000, uid=(1004, 1004), project_dir="/p")
    j = " ".join(a)
    assert a[:7] == ["docker", "run", "-d", "--platform", sandbox.PLATFORM, "--name", "ga-valheim"] and a[-1] == "gameanything-lab-valheim"
    assert "org.gameanything.project=My Wedding!" in a and a[a.index("-p") + 1] == "127.0.0.1:6080:6080"
    assert a[a.index("--user") + 1] == "1004:1004" and a[a.index("--memory") + 1] == "8g" and "--gpus" in a
    assert "type=volume,src=ga-valheim-my-wedding,dst=/sandbox" in a                                  # the project's own volume
    assert "apparmor=gameanything-steam" in j and "seccomp-steam.json" in j and a[a.index("--shm-size") + 1] == "1g"
    assert "ga-steam-home:/sandbox/home" in a                                                         # pulled image, another uid
    assert "type=volume,src=ga-steam-games,dst=/game,volume-subpath=common/Valheim,readonly" in a      # #27: the game read-only
    assert "/p:/project:ro" in a and "--privileged" not in a and "--cap-add" not in a
    t = sandbox.sandbox_argv("terraria", "p", image_uid=1000, uid=(1004, 1004), apparmor=False)
    assert not any("dst=/game," in x for x in t) and "GA_GAME=/sandbox/home/.steam/debian-installation/steamapps/common/tModLoader" in t
    assert t[t.index("--memory") + 1] == "4g"                                                           # a 2D game
    s = sandbox.sandbox_argv("slay_the_spire", "p", uid=None, apparmor=False)
    assert "type=volume,src=ga-steam-games,dst=/workshop,volume-subpath=workshop/content/646570,readonly" in s
    assert "ga-steam-home:/home/player" in s and "--user" not in s                                   # root / an image built for her
    h = sandbox.sandbox_argv("valheim", "p", image_uid=1000, uid=(1004, 1004), apparmor=False, steam_home_dir="/home/player")
    assert "ga-steam-home:/home/player" in h and h[len(h) - 1 - h[::-1].index("-e") + 1] == "HOME=/home/player"   # the last HOME wins
    f = sandbox.sandbox_argv("stardew", "p", source="folder", game_dir="/g", saves_dir="/s", uid=None)
    assert "/g:/game:ro" in f and "/s:/saves:ro" in f and not any("ga-steam" in x for x in f) and "--shm-size" not in f
    e = sandbox.sandbox_argv("sims4", "p", uid=None)
    assert "type=volume,src=ga-ea,dst=/sandbox/ea" in e and not any("ga-steam" in x for x in e)
    m = sandbox.sandbox_argv("minecraft", "p", uid=None)
    assert "type=volume,src=ga-mc-account,dst=/sandbox/account" in m and "GA_GAME=/sandbox/minecraft" in m
    with pytest.raises(ValueError): sandbox.sandbox_argv("sims4", "p", source="steam")
    with pytest.raises(ValueError): sandbox.sandbox_argv("stardew", "p", source="folder")
    with pytest.raises(ValueError): sandbox.sandbox_argv("nms", "p")
    assert set(sandbox.TOOLS) == set(sandbox.IMAGES) and set(sandbox.STEAM_FOLDER) <= set(sandbox.IMAGES)


class FakeDocker:
    def __init__(self, containers=None, downloaded=True, image=True, steam_root=""):
        self.bin = "docker"; self.calls = []; self.c = containers or {}; self.downloaded = downloaded; self.image = image
        self.steam_root = steam_root

    def run(self, args, timeout=600, check=False):
        self.calls.append(args)
        if args[0] == "version": return 0, "29.0\n", ""
        if args[0] == "inspect" and "{{.Image}}" in args: return (0, getattr(self, "box_image", "sha256:img") + "\n", "") if self.c.get(args[-1]) else (1, "", "")
        if args[:2] == ["image", "inspect"] and "{{.Id}}" in args: return 0, getattr(self, "tag_image", "sha256:img") + "\n", ""
        if args[:2] == ["image", "inspect"] and any("RepoDigests" in x for x in args):
            return (0, getattr(self, "digests", "[]|sha256:img") + "\n", "") if self.image else (1, "", "")
        if args[0] == "inspect":
            c = self.c.get(args[-1])
            return (0, f"{'true' if c['running'] else 'false'}|{c['project']}|{c.get('mounted', '0')}\n", "") if c else (1, "", "no such")
        if args[:2] == ["image", "inspect"]: return (0, "[]", "") if self.image else (1, "", "")
        if args[0] == "run" and "readlink" in args: return (0, self.steam_root + "\n", "") if self.steam_root else (1, "", "")
        if args[0] == "run" and "--entrypoint" in args: return (0 if self.downloaded else 1), "", ""
        if args[0] == "run": self.c[args[args.index("--name") + 1]] = {"running": True, "project": "x"}; return 0, "id\n", ""
        if args[0] == "exec" and "doctor" in args: return 0, json.dumps({"game_build": "linux"}) + "\n", ""
        if args[0] in ("rm", "stop"): self.c.pop(args[-1], None) if args[0] == "rm" else None; return 0, "", ""
        return 0, "", ""

    def stream(self, args): self.calls.append(args); return 0


def _project(tmp_path, game="valheim"):
    p = tmp_path / "proj"; (p / "config").mkdir(parents=True)
    (p / "config" / "project.yaml").write_text(f"title: T\ngame: {game}\nbuild_mode: lab\n", encoding="utf-8")
    return p


def _args(p, **kw):
    d = dict(project=str(p), source=None, folder=None, saves=None, gpu=None, memory=None, port=None, steam_home=None, replace=False)
    d.update(kw); return argparse.Namespace(**d)


@pytest.fixture
def host(monkeypatch):
    monkeypatch.setattr(sandbox, "host_apparmor", lambda root="/": 3)
    monkeypatch.setattr(labsandbox, "apparmor_ready", lambda abi=None: True)
    monkeypatch.setattr(labsandbox, "gpu_available", lambda: True)
    monkeypatch.setattr(sandbox, "image_player_uid", lambda image, docker="docker": 1000)
    monkeypatch.setattr(sandbox, "player_uid", lambda: (1004, 1004))


def test_up_starts_without_the_game_until_steam_downloaded_it(tmp_path, host):
    p = _project(tmp_path); d = FakeDocker(downloaded=False)
    r = labsandbox.up(_args(p, source="steam"), d, say=lambda *x: None, sleep=lambda s: None)
    run = next(c for c in d.calls if c[0] == "run" and "--entrypoint" not in c)
    assert r["code"] == 0 and not any("dst=/game," in x for x in run) and "org.gameanything.game-mounted=0" in run
    assert "--gpus" in run and any("login steam" in n and "--install" in n for n in r["next"])
    assert "source: steam" in (p / "config" / "project.yaml").read_text(encoding="utf-8") and "build_mode: lab" in (p / "config" / "project.yaml").read_text(encoding="utf-8")
    d.c["ga-valheim"] = {"running": True, "project": "proj", "mounted": "0"}; d.downloaded = True; d.calls.clear()
    r = labsandbox.up(_args(p), d, say=lambda *x: None, sleep=lambda s: None)            # downloaded now: re-created with /game
    run = next(c for c in d.calls if c[0] == "run" and "--entrypoint" not in c)
    assert r["code"] == 0 and ["rm", "ga-valheim"] in d.calls and any("dst=/game," in x for x in run) and r["game_mounted"]



def test_up_on_a_mac_found_problems(tmp_path, host, monkeypatch):
    """Her Mac 2026-10-30 (Docker Desktop): Slay the Spire's first `up` failed on the missing Workshop subpath, and a `docker run` that
    failed (port taken by Cursor) left a "Created" container that the next `up` only re-started with the old port."""
    p = _project(tmp_path, "slay_the_spire"); d = FakeDocker(downloaded=False)
    r = labsandbox.up(_args(p, source="steam"), d, say=lambda *x: None, sleep=lambda s: None)
    run = next(c for c in d.calls if c[0] == "run" and "--entrypoint" not in c)
    assert r["code"] == 0 and not any("dst=/workshop," in x for x in run) and not any("dst=/game," in x for x in run)

    class PortTaken(FakeDocker):
        def run(self, args, timeout=600, check=False):
            if args[0] == "run" and "--entrypoint" not in args and "readlink" not in args:
                self.calls.append(args); self.c["ga-sts"] = {"running": False, "project": "proj"}
                return 125, "", "Bind for 127.0.0.1:6080 failed: port is already allocated"
            return super().run(args, timeout, check)
    p2 = _project(tmp_path / "b", "slay_the_spire"); d = PortTaken(downloaded=False)
    r = labsandbox.up(_args(p2, source="steam"), d, say=lambda *x: None, sleep=lambda s: None)
    assert r["code"] != 0 and "--port" in r["why"] and "another program" in r["why"]
    assert ["rm", "ga-sts"] in d.calls and "ga-sts" not in d.c                          # no half-made container left behind

def test_up_refuses_another_projects_sandbox_and_restarts_a_stopped_one(tmp_path, host):
    p = _project(tmp_path)
    d = FakeDocker({"ga-valheim": {"running": True, "project": "other"}})
    r = labsandbox.up(_args(p, source="steam"), d, say=lambda *x: None, sleep=lambda s: None)
    assert r["code"] == labsandbox.NEEDS_USER and "other" in r["why"] and not any(c[0] == "run" for c in d.calls)
    d = FakeDocker({"ga-valheim": {"running": False, "project": "proj", "mounted": "1"}})
    r = labsandbox.up(_args(p, source="steam"), d, say=lambda *x: None, sleep=lambda s: None)
    assert r["code"] == 0 and ["start", "ga-valheim"] in d.calls and not any(c[0] == "run" and "--entrypoint" not in c for c in d.calls)


def test_up_asks_for_the_apparmor_step_and_a_gpu(tmp_path, host, monkeypatch):
    monkeypatch.setattr(labsandbox, "apparmor_ready", lambda abi=None: False)
    r = labsandbox.up(_args(_project(tmp_path), source="steam"), FakeDocker(), say=lambda *x: None, sleep=lambda s: None)
    assert r["code"] == labsandbox.NEEDS_USER and "sudo apparmor_parser" in r["why"]
    monkeypatch.setattr(labsandbox, "gpu_available", lambda: False)
    r = labsandbox.up(_args(_project(tmp_path / "mc", "minecraft")), FakeDocker(), say=lambda *x: None, sleep=lambda s: None)
    assert r["code"] == labsandbox.NEEDS_USER and "GPU" in r["why"]                      # Minecraft 26.x: gpu required
    r = labsandbox.up(_args(_project(tmp_path / "f"), source="folder"), FakeDocker(), say=lambda *x: None, sleep=lambda s: None)
    assert r["code"] == labsandbox.USAGE
    assert "Docker Engine 26" in labsandbox.explain_run_error("unknown option volume-subpath", "valheim")
    assert "--gpu off" in labsandbox.explain_run_error("could not select device driver nvidia", "valheim")


def test_other_commands_stay_in_the_project(tmp_path, host):
    p = _project(tmp_path); d = FakeDocker({"ga-valheim": {"running": True, "project": "proj"}})
    assert labsandbox.in_project(p, p / "5_build" / "m1" / "mod") == "/project/5_build/m1/mod" and labsandbox.in_project(p, "/etc") is None
    r = labsandbox.other("build", [str(p / "5_build" / "m1" / "mod")], d, p, "proj", "valheim", "ga-valheim", print)
    assert ["exec", "ga-valheim", "gameanything", "native", "build", "--game", "valheim", "--install", "/project/5_build/m1/mod"] in d.calls
    assert labsandbox.other("build", ["/tmp/elsewhere"], d, p, "proj", "valheim", "ga-valheim", print)["code"] == labsandbox.USAGE
    labsandbox.other("tool", ["layer"], d, p, "proj", "valheim", "ga-valheim", print)
    assert ["exec", "ga-valheim", "ga-valheim", "layer"] in d.calls
    labsandbox.other("input", ["click", "10", "20"], d, p, "proj", "valheim", "ga-valheim", print)
    assert ["exec", "-e", "DISPLAY=:99", "ga-valheim", "xdotool", "mousemove", "10", "20", "click", "1"] in d.calls
    assert labsandbox.other("input", ["click", "10"], d, p, "proj", "valheim", "ga-valheim", print)["code"] == labsandbox.USAGE
    name, r = labsandbox.running(FakeDocker({"ga-valheim": {"running": True, "project": "other"}}), "valheim", "proj")
    assert name is None and r["code"] == labsandbox.NEEDS_USER


def test_own_sandbox_is_the_lab_without_gamebench(tmp_path, monkeypatch):
    """A Linux user who cloned only GameAnything: no gamebench, a local Docker engine -> the sandbox choice is on, every game with an
    image, no seat (pooled False)."""
    env = {"GAMEANYTHING_GAMEBENCH": str(tmp_path / "none"), "PATH": "/usr/bin:/bin", "DOCKER_HOST": "unix:///var/run/docker.sock"}
    monkeypatch.setattr(buildmode, "docker_bin", lambda env=None: "/usr/bin/docker")
    monkeypatch.setattr(buildmode, "docker_ok", lambda env=None: True)
    monkeypatch.setattr(buildmode.osdirs, "system", lambda: "linux")
    assert buildmode.own_sandbox(env) and not buildmode.lab_kit(env)
    m = buildmode.machine(env, sys_="linux")
    assert m["own"] and m["kit"] and m["docker"] and m["pool"] is None and "valheim" in m["scripts"] and "nms" not in m["scripts"]
    o = buildmode.options("valheim", m, {"installed": False})
    assert next(x for x in o["options"] if x["mode"] == "lab")["ok"]
    assert builds.Lab(env).ready("sims4") == (True, "", False) and builds.Lab(env).ready("nms")[0] is False
    assert not buildmode.own_sandbox({**env, "DOCKER_HOST": "unix:///tmp/docker-rt.sock"})          # the maintainer's docker-rt
    assert not buildmode.own_sandbox(env, sys_="mac")


def test_fetch_copies_only_from_sandbox_into_the_project(tmp_path, host):
    """The builder may not use raw docker; a recording (`tool -- rec stop` -> /sandbox/rec/*.mkv) comes out only through fetch."""
    p = _project(tmp_path); d = FakeDocker({"ga-valheim": {"running": True, "project": "proj"}})
    r = labsandbox.other("fetch", ["/sandbox/rec/a.mkv", str(p / "5_build" / "m1" / "a.mkv")], d, p, "proj", "valheim", "ga-valheim", print)
    assert r["code"] == 0 and d.calls[-1] == ["cp", "ga-valheim:/sandbox/rec/a.mkv", str((p / "5_build" / "m1" / "a.mkv").resolve())]
    for bad in (["/etc/passwd", str(p / "x")], ["/sandbox/../etc/passwd", str(p / "x")], ["/sandbox/a", "/tmp/outside"]):
        assert labsandbox.other("fetch", bad, d, p, "proj", "valheim", "ga-valheim", print)["code"] == labsandbox.USAGE


def test_linux_without_docker_says_install_docker_and_the_builder_is_told_its_lab(tmp_path, monkeypatch):
    m = {"system": "linux", "backend": None, "kit": False, "docker": False, "pool": None, "scripts": set(), "headless": False, "docker_client": False}
    lab = next(x for x in buildmode.options("valheim", m, {"installed": False})["options"] if x["mode"] == "lab")
    assert not lab["ok"] and "Docker Engine" in lab["why"] and lab["why"] in buildmode.TEXTS
    assert lab["why"] in (Path(buildmode.__file__).parent / "ui" / "static" / "i18n.js").read_text(encoding="utf-8")
    m.update(backend="docker", docker_client=True)                                      # Docker there, a gamebench lab missing
    assert next(x for x in buildmode.options("valheim", m, {"installed": False})["options"] if x["mode"] == "lab")["why"] == buildmode.GREY["lab_kit"]
    class B: lab = builds.Lab({})
    monkeypatch.setattr(buildmode, "own_sandbox", lambda env=None, *a, **k: True)
    assert "gameanything lab sandbox" in builds.Builds.no_lease(B(), {"build_mode": "lab"})
    assert "native" in builds.Builds.no_lease(B(), {"build_mode": "native"})
    role = (Path(builds.ROLE)).read_text(encoding="utf-8")
    assert "her own sandbox" in role and "`gameanything lab sandbox` and the game's sandbox tool" in role and "fetch --project" in role
    for internal_only in ("GAMEANYTHING_LEASE", "lab env up", "lab acquire", "wc-cities", "broker"):  # the gamebench lab: internal/, not the role
        assert internal_only not in role, internal_only


def test_gamebench_and_hub_guidance_is_internal(monkeypatch, tmp_path):
    """Maintainers' setups (the gamebench labs, the hub) are kept out of the user's flow (2026-10-30): internal/ is not in the skill and
    is appended to the prompts only where it applies."""
    from gameanything import internal_docs, setupguide, shipped
    root = Path(shipped.CHECKOUT)
    have = internal_docs.GAMEBENCH.is_file()                     # internal/ is not in the public repository (2026-11-01): only in maintainers' checkouts
    if have: assert "GAMEANYTHING_LEASE" in internal_docs.GAMEBENCH.read_text(encoding="utf-8")
    assert "internal" not in shipped.BUNDLED and not any(b.startswith("internal") for b in shipped.BUNDLED)
    skill = "\n".join(f.read_text(encoding="utf-8") for f in (root / "skills" / "gameanything").rglob("*.md") if "lessons" not in f.parts)   # lessons cite where an incident happened
    for word in ("wc-cities", "launch_rt", "lab acquire", "mclab-hlm", "hosting/modlab"):
        assert word not in skill, word
    monkeypatch.setattr(buildmode, "lab_kit", lambda env=None, backend_=None: False)
    monkeypatch.setattr(setupguide, "is_hub", lambda root=None, env=None: False)
    assert internal_docs.addendum(tmp_path) == ""                                        # a user's machine
    monkeypatch.setattr(buildmode, "lab_kit", lambda env=None, backend_=None: True)
    if have: assert "seat lab" in internal_docs.addendum(tmp_path)                       # a gamebench lab
    else: assert internal_docs.addendum(tmp_path) == ""                                  # a public clone: nothing to append


def test_look_reads_only_inside_and_run_wants_steam(tmp_path, host):
    """E2E 2026-10-30: the builder used raw `docker exec` to read files (now `look`), and ran Valheim without Steam (a black screen)."""
    p = _project(tmp_path); d = FakeDocker({"ga-valheim": {"running": True, "project": "proj"}})
    r = labsandbox.other("look", ["/sandbox/game/BepInEx/LogOutput.log"], d, p, "proj", "valheim", "ga-valheim", print, n=50)
    assert r["code"] == 0 and d.calls[-1][:2] == ["exec", "ga-valheim"] and d.calls[-1][-2:] == ["/sandbox/game/BepInEx/LogOutput.log", "50"]
    for bad in ("/etc/shadow", "/sandbox/../etc/shadow", "/home/player/.steam/config/config.vdf"):
        assert labsandbox.other("look", [bad], d, p, "proj", "valheim", "ga-valheim", print)["code"] == labsandbox.USAGE
    class Steam(FakeDocker):
        up = False
        def run(self, args, timeout=600, check=False):
            if args[:2] == ["exec", "ga-valheim"] and "ga-steam status" in " ".join(args):    # indented over many lines, as ga-steam prints it
                self.calls.append(args); return 0, json.dumps({"running": self.up, "apps": [892970]}, indent=1) + "\n", ""
            return super().run(args, timeout, check)
    d = Steam({"ga-valheim": {"running": True, "project": "proj"}})
    r = labsandbox.other("tool", ["run"], d, p, "proj", "valheim", "ga-valheim", print, source="steam")
    assert r["code"] == labsandbox.FAILED and "lab login steam" in r["why"] and not any(c[-1:] == ["run"] for c in d.calls)
    assert labsandbox.other("tool", ["layer"], d, p, "proj", "valheim", "ga-valheim", print, source="steam")["code"] == 0   # only run needs it
    d = Steam({"ga-valheim": {"running": True, "project": "proj"}}); d.up = True      # 2026-10-31: refused while Steam was running
    assert labsandbox.other("tool", ["run"], d, p, "proj", "valheim", "ga-valheim", print, source="steam")["code"] == 0 and d.calls[-1][-1] == "run"


def test_up_mounts_steam_home_where_the_volume_was_set_up(tmp_path, host):
    """2026-10-31: Civ VI (pulled image, --user: /sandbox/home) after Valheim had set up the shared Steam volume at /home/player:
    Steam's links led nowhere and the login stopped on "~/.steam belongs to root"."""
    d = FakeDocker(steam_root="/home/player/.steam/debian-installation")
    r = labsandbox.up(_args(_project(tmp_path), source="steam"), d, say=lambda *x: None, sleep=lambda s: None)
    run = next(c for c in d.calls if c[0] == "run" and "--name" in c)
    assert r["code"] == 0 and "ga-steam-home:/home/player" in run and "HOME=/home/player" in run
    d = FakeDocker()                                                                    # a new volume: the image's default
    labsandbox.up(_args(_project(tmp_path / "b"), source="steam"), d, say=lambda *x: None, sleep=lambda s: None)
    run = next(c for c in d.calls if c[0] == "run" and "--name" in c)
    assert "ga-steam-home:/sandbox/home" in run and "HOME=/home/player" not in run
    a = sandbox.sandbox_argv("valheim", "p", source="steam", image_uid=1004, uid=(1004, 1004), steam_home_dir="/sandbox/home")
    assert "ga-steam-home:/sandbox/home" in a and "HOME=/sandbox/home" in a and "--user" not in a     # no --user: HOME set all the same


def test_up_gives_new_store_volumes_to_her_uid(tmp_path, host, monkeypatch):
    """2026-10-31: the own sandbox of The Sims 4 (pulled uid-1000 image, --user 1004): the new `ga-ea` volume was root's and the EA App
    download failed on /sandbox/ea/dl. Store volumes are checked (and chowned when not hers) before the sandbox starts."""
    monkeypatch.setattr(sandbox, "player_uid", lambda: (1004, 1004))
    d = FakeDocker()
    r = labsandbox.up(_args(_project(tmp_path, "sims4"), source="ea"), d, say=lambda *x: None, sleep=lambda s: None)
    own = [c for c in d.calls if c[0] == "run" and "ga-ea:/v" in c]
    assert r["code"] == 0 and len(own) == 1 and "chown -R 1004:1004 /v" in own[0][-1]
    assert d.calls.index(own[0]) < d.calls.index(next(c for c in d.calls if c[0] == "run" and "--name" in c))
    home = [c for c in d.calls if c[0] == "run" and "ga-sims4-proj:/sandbox" in c]                 # HOME=/sandbox/home: hers too (sound)
    assert len(home) == 1 and "chown 1004:1004 /sandbox/home" in home[0][-1]
    d = FakeDocker()
    labsandbox.up(_args(_project(tmp_path / "s"), source="steam"), d, say=lambda *x: None, sleep=lambda s: None)
    assert {v for c in d.calls if c[0] == "run" for v in ("ga-steam-home", "ga-steam-games") if f"{v}:/v" in c} == {"ga-steam-home", "ga-steam-games"}
    assert not any(c[0] == "run" and any(x.endswith(":/sandbox") for x in c) and "--rm" in c for c in d.calls)   # HOME is the Steam volume
    monkeypatch.setattr(sandbox, "player_uid", lambda: (1000, 1000))                    # her uid = the image's: no --user, nothing to give
    d = FakeDocker()
    labsandbox.up(_args(_project(tmp_path / "t", "sims4"), source="ea"), d, say=lambda *x: None, sleep=lambda s: None)
    assert not any("ga-ea:/v" in c for c in d.calls)


def test_no_picture_while_a_sign_in_window_is_open(tmp_path, host):
    """2026-10-31: a screenshot of The Sims 4 caught the launcher's own 「Sign in with your EA Account to activate」 window (empty fields)
    right after she signed in; ga-ea did not call it a sign-in window. shot / tool shot / rec start refuse while one may be open."""
    p = _project(tmp_path, "sims4")
    class Box(FakeDocker):
        st = {}
        def run(self, args, timeout=600, check=False):
            if args[0] == "exec" and " status --json" in args[-1]: self.calls.append(args); return 0, json.dumps(self.st, indent=1), ""
            return super().run(args, timeout, check)
    d = Box({"ga-sims4": {"running": True, "project": "proj"}})
    d.st = {"login_window": False, "windows": [{"title": "EA"}, {"title": "DisplayName field missing from registry."}]}
    for what, rest in (("shot", [str(tmp_path / "a.png")]), ("tool", ["shot", "/sandbox/a.png"]), ("tool", ["rec", "start"])):
        r = labsandbox.other(what, rest, d, p, "proj", "sims4", "ga-sims4", print, source="ea")
        assert r["code"] == labsandbox.NEEDS_USER and "registry" in r["why"], (what, rest)
    assert not any(c[0] == "exec" and ("shot" in c or "x11grab" in " ".join(c)) for c in d.calls if "status" not in c[-1])
    d.st = {"login_window": True, "windows": [{"title": "EA"}]}
    assert labsandbox.other("shot", [str(tmp_path / "a.png")], d, p, "proj", "sims4", "ga-sims4", print, source="ea")["code"] == labsandbox.NEEDS_USER
    d.st = {"login_window": False, "windows": [{"title": "EA"}, {"title": "The Sims\u2122 4"}]}
    assert labsandbox.other("shot", [str(tmp_path / "a.png")], d, p, "proj", "sims4", "ga-sims4", print, source="ea")["code"] == 0
    assert labsandbox.other("tool", ["rec", "stop"], d, p, "proj", "sims4", "ga-sims4", print, source="ea")["code"] == 0   # stop: always
    d = Box({"ga-valheim": {"running": True, "project": "proj"}}); d.st = {"running": True, "login_window": True}
    r = labsandbox.other("shot", [str(tmp_path / "v.png")], d, _project(tmp_path / "v"), "proj", "valheim", "ga-valheim", print, source="steam")
    assert r["code"] == labsandbox.NEEDS_USER and "Steam" in r["why"]


def test_sandbox_argv_on_apple_silicon(monkeypatch):
    """arm64 (2026-10-31): the locally built arm64 image, Steam's seccomp profile as on x86, no AppArmor (Docker Desktop has none),
    and more memory: Steam and the game under FEX took ~3 GB."""
    monkeypatch.setattr(sandbox, "PLATFORM", "linux/arm64")
    a = sandbox.sandbox_argv("slay_the_spire", "p", uid=(501, 20), image_uid=501, apparmor=False)
    assert a[a.index("--platform") + 1] == "linux/arm64" and a[a.index("--memory") + 1] == "5g"
    assert any("seccomp-steam.json" in x for x in a) and not any("apparmor=" in x for x in a) and "--user" not in a


def test_up_removes_the_old_image_when_the_sandbox_was_down(tmp_path, host, monkeypatch):
    """2026-11-02 (stardew 20261102a): the sandbox was down before `up`, so no container ran the old image and it stayed (4.6 GB)."""
    from gameanything import labdocker
    d = FakeDocker({})
    d.digests = '["ghcr.io/aetherlabsai/gameanything-lab-sims4@sha256:0000"]|sha256:0000'; d.tag_image = "sha256:0000"
    want = sandbox.PUBLISHED["sims4"].split("@", 1)[1]
    monkeypatch.setattr(labdocker, "pull_images", lambda games, say=print, fallback=True, **k: setattr(d, "tag_image", want) or 0)
    monkeypatch.setattr(labdocker, "image_store", lambda docker="docker": ("/var/lib/docker", 50))
    r = labsandbox.up(_args(_project(tmp_path, "sims4"), source="ea"), d, say=lambda *x: None, sleep=lambda s: None)
    assert r["code"] == 0 and ["image", "rm", "sha256:0000"] in d.calls and ["image", "rm", want] not in d.calls


def test_up_pulls_a_newer_published_image_and_recreates_the_sandbox(tmp_path, host, monkeypatch):
    """2026-10-31: `git pull` brought new digests (sims4 20261031a) but `up` kept starting the old local image."""
    from gameanything import labdocker
    pulled = []
    monkeypatch.setattr(labdocker, "pull_images", lambda games, say=print, fallback=True, **k: pulled.append((games, fallback)) or 0)
    monkeypatch.setattr(labdocker, "image_store", lambda docker="docker": ("/var/lib/docker", 50))
    want = sandbox.PUBLISHED["sims4"].split("@", 1)[1]
    d = FakeDocker({"ga-sims4": {"running": True, "project": "proj"}})
    d.digests = '["ghcr.io/aetherlabsai/gameanything-lab-sims4@sha256:0000"]|sha256:0000'
    d.box_image, d.tag_image = "sha256:0000", want                                      # after the pull the tag is the new image
    r = labsandbox.up(_args(_project(tmp_path, "sims4"), source="ea"), d, say=lambda *x: None, sleep=lambda s: None)
    assert r["code"] == 0 and pulled == [(["sims4"], False)] and any(c[0] == "rm" and c[-1] == "ga-sims4" for c in d.calls)
    assert any(c[0] == "run" and "--name" in c for c in d.calls) and ["image", "rm", "sha256:0000"] in d.calls
    for i, digests in enumerate((f'["gameanything-lab-sims4@{want}"]|sha256:x', "[]|sha256:built-here")):  # current, or built here: kept
        pulled.clear(); d = FakeDocker({"ga-sims4": {"running": True, "project": "proj"}}); d.digests = digests
        labsandbox.up(_args(_project(tmp_path / f"case{i}", "sims4"), source="ea"), d, say=lambda *x: None, sleep=lambda s: None)
        assert pulled == [] and not any(c[0] == "run" and "--name" in c for c in d.calls)
