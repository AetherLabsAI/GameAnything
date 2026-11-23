"""The lab on the user's own Linux machine with plain Docker (labdocker.py, lab images phase 2): when buildmode counts it as available
(lab config + gamebench's plain driver + game folder + image here or pullable; the local seat pool), and `gameanything lab setup` (ghcr.io login
without printing the token, image pulls, lab.env, game folders, local pool). Fake gamebench, fake docker: no engine, no network."""
import io
import json
import os
import sys
from pathlib import Path

import pytest

from gameanything import buildmode, cli, labdocker

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="the plain-Docker lab is Linux only (fake docker is a shell script)")

FAKE_LABENV = '''
import os
from pathlib import Path
def config_path(env=None):
    env = os.environ if env is None else env
    if env.get("M2W_LAB_CONFIG"): return Path(env["M2W_LAB_CONFIG"])
    p = Path(env.get("HOME", "")) / ".config" / "m2w" / "lab.env"
    return p if p.is_file() else None
def resolve(env=None):
    env = os.environ if env is None else env
    v = {}
    p = config_path(env)
    if p and p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, x = line.split("=", 1); v[k.strip()] = x.strip()
    v.setdefault("M2W_LAB_HOME", str(Path(env.get("HOME", "")) / "m2w-lab"))
    return v, p
'''
FAKE_DOCTOR = '''#!/usr/bin/env python3
import json, os
print(json.dumps({"tool": "lab-doctor", "checks": [{"area": "games", "name": "stardew", "status": "ok", "data": {"path": os.environ["FAKE_SDV"]}}],
                  "docker": True, "render_mode": "software"}))
'''
FAKE_SEAT = '''#!/usr/bin/env python3
import os, sys
from pathlib import Path
home = [l.split("=", 1)[1] for l in Path(os.environ["M2W_LAB_CONFIG"]).read_text().splitlines() if l.startswith("M2W_LAB_HOME=")][0]
p = Path(home) / "labs" / "pool.yaml"; p.parent.mkdir(parents=True, exist_ok=True)
games = [sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--game"]
p.write_text('{"defaults": {}, "games": {"stardew_valley": {"mem_gb": 1.5}, "minecraft": {"mem_gb": 2.6, "gpu": true}}, '
             '"sandboxes": {"local": {"kind": "lab", "seats": 2, "gpu": false, "games": %s}}}' % repr(games).replace("'", '"'))
print("wrote", p)
'''
FAKE_DOCKER = '''#!/bin/sh
echo "$*" >> "$FAKE_LOG"
case "$1" in
  version) exit 0;;
  login) cat > /dev/null; mkdir -p "$HOME/.docker"; echo '{"auths": {"ghcr.io": {}}}' > "$HOME/.docker/config.json"; exit 0;;
  pull) echo "$2" >> "$FAKE_LOG.images"; exit 0;;
  image) grep -qx "$5" "$FAKE_LOG.images" 2>/dev/null && exit 0; exit 1;;
esac
exit 0
'''


@pytest.fixture
def m(tmp_path, monkeypatch):
    gb = tmp_path / "gamebench"
    for f in ("agent/modlab/stardew/sdlab_docker.py", "agent/modlab/minecraft/mclab_docker.py", "hosting/broker.py"):
        (gb / f).parent.mkdir(parents=True, exist_ok=True); (gb / f).write_text("", encoding="utf-8")
    (gb / "hosting" / "lab").mkdir(parents=True)
    (gb / "hosting" / "lab" / "labenv.py").write_text(FAKE_LABENV, encoding="utf-8")
    for n, body in (("lab-doctor", FAKE_DOCTOR), ("seat.py", FAKE_SEAT)): (gb / "hosting" / "lab" / n).write_text(body, encoding="utf-8")
    (gb / "config").mkdir(); (gb / "config" / "lab.env.example").write_text("# template\nM2W_LAB_HOME=$HOME/m2w-lab\n# M2W_LAB_GAME_STARDEW=\nM2W_LAB_GPU=auto\n", encoding="utf-8")
    sdv = tmp_path / "Stardew Valley"; sdv.mkdir(); (sdv / "Stardew Valley.dll").write_text("x", encoding="utf-8")
    d = tmp_path / "bin"; d.mkdir(); (d / "docker").write_text(FAKE_DOCKER, encoding="utf-8"); (d / "docker").chmod(0o755)
    log = tmp_path / "docker.log"
    for k, v in {"GAMEANYTHING_GAMEBENCH": str(gb), "GAMEANYTHING_DOCKER": str(d / "docker"), "FAKE_LOG": str(log), "FAKE_SDV": str(sdv),
                 "DOCKER_HOST": "unix:///run/docker.sock"}.items(): monkeypatch.setenv(k, v)
    for k in ("M2W_LAB_POOL", "M2W_LAB_CONFIG", "M2W_LAB_HOME", "DOCKER_CONFIG"): monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("GAMEANYTHING_LAB_POOL", raising=False)                    # no server pool configured (no built-in path since 2026-11-01)
    cfg = Path.home() / ".config" / "m2w" / "lab.env"
    return type("M", (), {"gb": gb, "sdv": sdv, "log": log, "cfg": cfg, "home": Path.home(), "tmp": tmp_path})


def test_not_configured_is_not_a_lab(m):
    assert labdocker.config()[1] is None and labdocker.ready_games() == set()
    assert not buildmode.lab_kit() and buildmode.backend() == "docker"
    s = labdocker.status(); assert s["config"] is None and s["games"]["stardew"]["why"] == "no_config"


def test_ready_needs_folder_and_an_image_or_a_login(m):
    m.cfg.parent.mkdir(parents=True); m.cfg.write_text(f"M2W_LAB_HOME={m.tmp / 'lab'}\nM2W_LAB_GAME_STARDEW={m.sdv}\n", encoding="utf-8")
    assert buildmode.lab_kit()                                                     # seat driver + a lab config
    s = labdocker.status()["games"]
    assert s["stardew"]["why"] == "no_image" and s["minecraft"]["why"] == "no_folder"
    (m.home / ".docker").mkdir(); (m.home / ".docker" / "config.json").write_text('{"auths": {"ghcr.io": {"auth": "x"}}}', encoding="utf-8")
    assert labdocker.ready_games() == {"stardew"}                                  # pullable
    (m.home / ".docker" / "config.json").unlink()
    Path(str(m.log) + ".images").write_text("m2w-lab-dotnet:local\n", encoding="utf-8")
    assert labdocker.ready_games() == {"stardew"}                                  # built here
    assert labdocker.status()["games"]["stardew"]["image"] == "m2w-lab-dotnet:local"
    mc = m.tmp / "mc"; (mc / "main" / "versions").mkdir(parents=True)
    labdocker.set_key(m.cfg, "M2W_LAB_GAME_MINECRAFT", str(mc))
    assert labdocker.status()["games"]["minecraft"]["why"] == "no_image"           # java image missing, no login
    labdocker.set_key(m.cfg, "M2W_LAB_GAME_STARDEW", str(m.tmp / "nothing"))
    assert labdocker.status()["games"]["stardew"]["why"] == "no_folder"


def test_buildmode_offers_the_lab_for_ready_games_with_a_seat(m):
    m.cfg.parent.mkdir(parents=True); m.cfg.write_text(f"M2W_LAB_HOME={m.tmp / 'lab'}\nM2W_LAB_GAME_STARDEW={m.sdv}\n", encoding="utf-8")
    Path(str(m.log) + ".images").write_text("m2w-lab-dotnet:local\n", encoding="utf-8")
    mach = buildmode.machine(sys_="linux", docker=True)
    assert mach["backend"] == "docker" and mach["kit"] and mach["scripts"] == {"stardew"} and mach["pool"] is None
    o = buildmode.options("stardew", mach, None)
    assert o["recommended"] == "lab" and {x["mode"]: x["ok"] for x in o["options"]} == {"native": False, "lab": True}
    assert not {x["mode"]: x["ok"] for x in buildmode.options("minecraft", mach, None)["options"]}["lab"]
    pool = m.tmp / "lab" / "labs" / "pool.yaml"; pool.parent.mkdir(parents=True)
    pool.write_text('{"games": {"stardew_valley": {"mem_gb": 1.5}}, "sandboxes": {"local": {"kind": "lab", "seats": 1, "games": []}}}', encoding="utf-8")
    assert buildmode.pool()["sandboxes"]["local"]["seats"] == 1                     # the local pool when the server has none
    assert buildmode.machine(sys_="linux", docker=True)["scripts"] == set()       # ready, but the local pool has no seat for it
    pool.write_text('{"games": {"stardew_valley": {"mem_gb": 1.5}}, "sandboxes": {"local": {"kind": "lab", "seats": 1, "games": ["stardew_valley"]}}}', encoding="utf-8")
    assert buildmode.machine(sys_="linux", docker=True)["scripts"] == {"stardew"}
    assert buildmode.auto_mode("linux") == "lab"


def test_set_key_keeps_the_rest(m):
    f = m.tmp / "x.env"; f.write_text("# head\nA=1\n# M2W_LAB_GAME_STARDEW=$HOME/old\nB=2\n", encoding="utf-8")
    labdocker.set_key(f, "M2W_LAB_GAME_STARDEW", "/g/Stardew Valley"); labdocker.set_key(f, "A", "3"); labdocker.set_key(f, "C", "4")
    assert f.read_text(encoding="utf-8") == "# head\nA=3\nM2W_LAB_GAME_STARDEW=/g/Stardew Valley\nB=2\nC=4\n"


def test_setup_end_to_end_never_prints_the_token(m, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("ghp_SECRET123\n"))
    rc = labdocker.setup(["--yes", "--github-user", "bob", "--pat-stdin", "--home", str(m.tmp / "lab")])
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert "ghp_SECRET123" not in out.out + out.err + m.log.read_text(encoding="utf-8")
    calls = m.log.read_text(encoding="utf-8").splitlines()
    assert "login ghcr.io -u bob --password-stdin" in calls
    assert "pull ghcr.io/aetherlabsai/m2w-lab-base:latest" in calls and "pull ghcr.io/aetherlabsai/m2w-lab-dotnet:latest" in calls
    assert not any("m2w-lab-java" in c and c.startswith("pull") for c in calls)     # no Minecraft folder: no java image
    t = m.cfg.read_text(encoding="utf-8")
    assert f"M2W_LAB_GAME_STARDEW={m.sdv}" in t and f"M2W_LAB_HOME={m.tmp / 'lab'}" in t and "M2W_LAB_GPU=auto" in t
    pool = json.loads((m.tmp / "lab" / "labs" / "pool.yaml").read_text(encoding="utf-8"))
    assert pool["sandboxes"]["local"]["games"] == ["stardew_valley"]
    assert "stardew: READY" in out.out
    assert labdocker.ready_games() == {"stardew"} and buildmode.machine(sys_="linux", docker=True)["scripts"] == {"stardew"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert labdocker.setup(["--yes"]) == 0                                          # again: logged in, images here, nothing asked


def test_setup_without_a_token_says_how(m, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert labdocker.setup(["--yes"]) == 1
    assert "read:packages" in capsys.readouterr().err


def test_cli_lab_ready(m, capsys):
    assert cli.main(["lab", "ready", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["games"]["stardew"]["why"] == "no_config"


def test_setup_with_a_gamebench_branch_without_the_lab_says_so(m, capsys):
    """2026-10-29 on a plain Linux server: gamebench main has no hosting/lab, and setup crashed (AttributeError) instead of saying it."""
    (Path(os.environ["GAMEANYTHING_GAMEBENCH"]) / "hosting" / "lab" / "labenv.py").unlink()
    assert labdocker.setup(["--yes"]) == 1
    assert "no hosting/lab/labenv.py" in capsys.readouterr().err


def test_image_store_is_where_docker_really_keeps_images(tmp_path, monkeypatch, capsys):
    """Plain Docker test 2026-10-29: Engine 29's containerd image store is /var/lib/containerd (there on the root disk), not
    DockerRootDir; `lab setup --image` builds filled the shared root disk. Setup now refuses below IMAGE_SPACE_GB, before pulling or building."""
    class U: free = 5 * 2 ** 30
    root = tmp_path / "docker"; root.mkdir()
    assert labdocker.image_store(info=f"{root}|[[\"Backing Filesystem\",\"extfs\"]]", usage=lambda p: U) == (str(root), 5.0)
    p, _ = labdocker.image_store(info=f"{root}|[[\"driver-type\",\"io.containerd.snapshotter.v1\"]]", usage=lambda p: U)
    assert p in ("/var/lib/containerd", None)                         # that folder, when this machine has it
    assert labdocker.image_store(info=f"{tmp_path / 'nope'}|[]") == (None, None)  # Docker Desktop: inside its VM, not checked
    monkeypatch.setattr(labdocker, "image_store", lambda *a, **k: ("/var/lib/containerd", 4.3))
    called = []
    monkeypatch.setattr(labdocker, "pull_images", lambda *a, **k: called.append(a) or 0)
    assert labdocker.setup(["--image", "valheim", "--build"]) == 1 and called == []
    assert "only 4.3 GB free" in capsys.readouterr().err
