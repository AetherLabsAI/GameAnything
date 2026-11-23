"""`gameanything lab sandbox`: the user's own sandbox on THEIR OWN Linux machine with plain Docker Engine. No gamebench, no seats, no
broker (2026-10-30): one person, one machine, one container per game. The image is the published runtime-only image (`lab setup --image`);
the game comes from the user's own folder (read-only) or from the store inside the sandbox (Steam, EA App, Microsoft).

    gameanything lab sandbox up     --project P [--source steam|folder|ea|microsoft] [--folder DIR] [--saves DIR] [--gpu auto|on|off]
                                    [--memory 8g] [--port 6080] [--steam-home DIR] [--replace] [--json]
        pulls the image when it is missing, starts the sandbox (or starts it again), waits for its screen and prints the viewer.
        The choices are kept in the project's config/project.yaml (`sandbox:`), so later calls need only --project.
        A Steam game not downloaded yet: the sandbox starts without /game; after `gameanything lab login steam --project P --install`
        run `up` again (the sandbox is re-created with the game mounted read-only; the volumes keep everything).
    gameanything lab sandbox status --project P [--json]
    gameanything lab sandbox tool   --project P -- <args>        the game's own tool in the sandbox (ga-sdv, ga-valheim, ...): doctor,
                                                                 layer, run, shot, rec, log, stop
    gameanything lab sandbox build  --project P <mod folder>     gameanything native build --install in the sandbox (the project folder is
                                                                 mounted read-only at /project, so the mod folder must be inside it)
    gameanything lab sandbox shot   --project P FILE             a screenshot of the sandbox's screen, copied to FILE on this computer
    gameanything lab sandbox input  --project P key K | click X Y | move X Y | type TEXT
    gameanything lab sandbox look   --project P <path> [-n N]       read-only: a folder's listing or a file's last N lines (default 200),
                                                                 under /sandbox, /game, /project or /workshop (no raw docker exec)
    gameanything lab sandbox fetch  --project P <file in the sandbox> <file in the project>
                                                                 copies a file out (a recording from `tool -- rec stop`, a log): only
                                                                 from /sandbox, only into the project folder
    gameanything lab sandbox down   --project P                  stops the game (and Steam) and removes the container; volumes stay
                                                                 (logins, downloads, the project's layer and mods)

Containers: ga-<image> (the name `lab login` finds), labelled with the project; volumes: ga-<image>-<project id> (/sandbox) and the
store volumes shared by every project (sandbox.STORE_VOLUMES). The viewer is on 127.0.0.1 only: on a server, `ssh -L 6080:127.0.0.1:6080`.
Exit codes: 0 ok, 1 failed, 2 usage, 4 needs the user (a sudo step, a download, another project's sandbox), 5 not running.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

from . import buildmode, layout, projects, sandbox
from . import osdirs

OK, FAILED, USAGE, NEEDS_USER, DOWN = 0, 1, 2, 4, 5
MOUNT_LABEL = "org.gameanything.game-mounted"


class Docker:
    """The docker client (a fake in the tests): run(args) -> (rc, stdout, stderr)."""

    def __init__(self, bin_=None):
        self.bin = bin_ or buildmode.docker_bin()

    def run(self, args, timeout=600, check=False):
        if not self.bin: return 127, "", "no docker client on this machine (install Docker Engine: docs in linux-sandbox.md)"
        try: r = subprocess.run([self.bin, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired: return 124, "", f"docker {args[0]} timed out after {timeout} s"
        except OSError as e: return 127, "", str(e)
        return r.returncode, r.stdout, r.stderr

    def stream(self, args) -> int:
        """Run with the output going straight to the user (pulls, the game tool)."""
        if not self.bin: return 127
        return subprocess.run([self.bin, *args]).returncode


# ---------------------------------------------------------------- the project
def project(ref):
    root = projects.resolve(ref); cfg = projects.config_of(root)
    try: pid = projects.find(str(root))["id"]
    except KeyError: pid = projects.slug(root.name)
    game = cfg.get("game") or "stardew"
    if game not in sandbox.IMAGES: raise SystemExit(f"[sandbox] {game}: no sandbox image for this game (images: {', '.join(sandbox.IMAGES)})")
    s = cfg.get("sandbox") if isinstance(cfg.get("sandbox"), dict) else {}
    return root, pid, game, dict(s)


def save_choice(root, choice: dict):
    """Write the `sandbox:` block of config/project.yaml (only that block; the other lines and comments stay)."""
    p = Path(root) / layout.CONFIG / "project.yaml"
    t = p.read_text(encoding="utf-8") if p.is_file() else ""
    t = re.sub(r"(?m)^sandbox:.*(?:\n[ \t]+.*)*\n?", "", t)
    keep = {k: v for k, v in choice.items() if v not in (None, "")}
    t = (t.rstrip("\n") + "\n" if t.strip() else "") + yaml.safe_dump({"sandbox": keep}, allow_unicode=True, sort_keys=False)
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(t, encoding="utf-8")


# ---------------------------------------------------------------- what this machine has
def gpu_available() -> bool:
    """An NVIDIA GPU Docker can hand over: the driver (nvidia-smi) and the Container Toolkit (CDI spec or the nvidia runtime)."""
    if not shutil.which("nvidia-smi"): return False
    return Path("/etc/cdi/nvidia.yaml").is_file() or Path("/var/run/cdi/nvidia.yaml").is_file() or bool(shutil.which("nvidia-container-runtime"))


def apparmor_ready(abi=None) -> bool:
    """The Steam profile is installed (a user cannot read the kernel's profile list: the file in /etc/apparmor.d stands for it)."""
    return Path("/etc/apparmor.d", sandbox.APPARMOR_PROFILE).is_file()


def container(d, name) -> dict:
    """{exists, running, project, mounted} of a container (exists False when there is none)."""
    rc, out, _ = d.run(["inspect", "--format", "{{.State.Running}}|{{index .Config.Labels \"%s\"}}|{{index .Config.Labels \"%s\"}}"
                        % (sandbox.PROJECT_LABEL, MOUNT_LABEL), name], 30)
    if rc != 0: return {"exists": False, "running": False, "project": None, "mounted": False}
    run, proj, mounted = (out.strip().split("|") + ["", "", ""])[:3]
    return {"exists": True, "running": run == "true", "project": proj or None, "mounted": mounted == "1"}


def image_ok(d, game) -> bool:
    return image_state(d, game) != "missing"


def image_state(d, game) -> str:
    """missing | old | ok. old: the local image was pulled (it has registry digests) but is not the one sandbox.PUBLISHED pins now
    (2026-10-31: after `git pull` brought new digests, `up` kept starting the old Sims 4 image). An image built here (no registry
    digest) is hers: ok."""
    rc, out, _ = d.run(["image", "inspect", "--format", "{{json .RepoDigests}}|{{.Id}}", sandbox.image_tag(game)], 30)
    if rc != 0: return "missing"
    pub = sandbox.PUBLISHED.get(game) or ""
    if "@sha256:" not in pub: return "ok"
    want = pub.split("@", 1)[1]
    js, _, iid = (out or "").strip().partition("|")
    try: digests = json.loads(js) or []
    except ValueError: digests = []
    if not digests: return "ok"
    return "ok" if iid == want or any(str(x).endswith("@" + want) for x in digests) else "old"


def image_id(d, ref, container=False):
    rc, out, _ = d.run(["inspect" if container else "image", *([] if container else ["inspect"]), "--format",
                        "{{.Image}}" if container else "{{.Id}}", ref], 30)
    return out.strip() if rc == 0 else None


def steam_downloaded(d, game) -> bool:
    """The game's folder is in the Steam library volume (a volume subpath that does not exist makes `docker run` fail)."""
    v = sandbox.STORE_VOLUMES["steam"]["games"]; f = f"/v/common/{sandbox.STEAM_FOLDER[game]}"
    rc, _, _ = d.run(["run", "--rm", "--entrypoint", "test", "-v", f"{v}:/v:ro", sandbox.image_tag(game), "-d", f], 120)
    return rc == 0


def workshop_downloaded(d, game) -> bool:
    """The game's Workshop items are in the Steam library volume (Slay the Spire: ModTheSpire + BaseMod, mounted at /workshop)."""
    if game not in sandbox.WORKSHOP_APP: return True
    v = sandbox.STORE_VOLUMES["steam"]["games"]; f = f"/v/workshop/content/{sandbox.WORKSHOP_APP[game]}"
    rc, _, _ = d.run(["run", "--rm", "--entrypoint", "test", "-v", f"{v}:/v:ro", sandbox.image_tag(game), "-d", f], 120)
    return rc == 0


def steam_volume_home(d, game):
    """The HOME the shared Steam home volume was first used with (Steam's ~/.steam/root link points into it), None for a new volume.
    Every Steam game shares the volume, but its default mount differs (a pulled image run with --user: /sandbox/home; an image built
    for her uid: /home/player): mounted at the other HOME, Steam's links lead nowhere and login stops on "~/.steam belongs to root"
    (2026-10-31, Civ VI after Valheim). As root, read-only: the volume's HOME is 0750 for her uid, not the image's."""
    v = sandbox.STORE_VOLUMES["steam"]["home"]
    rc, out, _ = d.run(["run", "--rm", "--user", "0:0", "--entrypoint", "readlink", "-v", f"{v}:/v:ro", sandbox.image_tag(game), "/v/.steam/root"], 60)
    t = (out or "").strip(); tail = "/.steam/debian-installation"
    return t[:-len(tail)] if rc == 0 and t.endswith(tail) and t.startswith("/") and len(t) > len(tail) else None


def own_store_volumes(d, game, pid, src, argv, say=print) -> None:
    """Give the store volumes of `src` to her uid when the sandbox runs with --user (a pulled uid-1000 image on a machine where she is
    not uid 1000): a new named volume whose mount point is not in the image is made root's by Docker, one at a path that is (/sandbox/home)
    gets the image's uid 1000: either way she cannot write it (2026-10-31: `ga-ea` root's, the EA App download failed on /sandbox/ea/dl).
    One check per volume; chown -R only when its top is not hers (a new volume: empty or nearly). Also /sandbox/home when it is HOME."""
    if "--user" not in argv: return
    uid = argv[argv.index("--user") + 1]; u = uid.split(":")[0]
    vols = list(sandbox.STORE_VOLUMES.get(src, {}).values()) if src == "steam" else list(sandbox.STORE_VOLUMES.get(src, {}))
    for v in vols:
        rc, out, _ = d.run(["run", "--rm", "--user", "0:0", "--entrypoint", "sh", "-v", f"{v}:/v", sandbox.image_tag(game), "-c",
                            f'[ "$(stat -c %u /v)" = "{u}" ] && echo ok || {{ chown -R {uid} /v && echo given; }}'], 3600)
        if "given" in (out or ""): say(f"[sandbox] {v}: given to uid {u} (it was not writable for you)")
    if src != "steam" and [x for x in argv if x.startswith("HOME=")][-1:] == ["HOME=/sandbox/home"]:      # Steam: HOME is its volume
        # HOME in the project volume is the image's (uid 1000, 1777): PulseAudio refuses a HOME that is not hers ("Home directory not
        # accessible"), so EA / Microsoft / folder sandboxes had no sound at all and `rec` no audio track (2026-10-31, The Sims 4).
        # Mounted at /sandbox like the sandbox itself, so a new volume is still filled from the image first.
        d.run(["run", "--rm", "--user", "0:0", "--entrypoint", "sh", "-v", f"{sandbox.sandbox_volume(game, pid)}:/sandbox",
               sandbox.image_tag(game), "-c", f'[ "$(stat -c %u /sandbox/home)" = "{u}" ] || chown {uid} /sandbox/home'], 120)

def explain_run_error(err: str, game) -> str:
    e = err or ""
    if "apparmor" in e.lower():
        cmds = sandbox.apparmor_load_commands()
        return ("Steam's AppArmor profile is not loaded on this computer. Run once (needs sudo):\n  " +
                "\n  ".join(" ".join(c) for c in cmds)) if cmds else "AppArmor refused the sandbox: " + e.strip()[-300:]
    if "volume-subpath" in e or "subpath" in e:
        return "this Docker Engine cannot mount a volume subpath (Docker Engine 26 or newer is needed): " + e.strip()[-300:]
    if "nvidia" in e.lower() or "gpu" in e.lower() or "libEGL_nvidia" in e:
        return ("the GPU could not be handed to the sandbox (NVIDIA Container Toolkit; after a driver update: sudo nvidia-ctk cdi generate "
                "--output=/etc/cdi/nvidia.yaml). Or run without it: --gpu off. " + e.strip()[-300:])
    if "port is already allocated" in e or "address already in use" in e:
        return ("the viewer port is taken by another program on this computer (another sandbox, or an app such as an editor's port "
                "forwarding): pick a free one with --port (e.g. --port 6081; it is remembered), or `gameanything lab sandbox down` the other sandbox")
    return e.strip()[-600:] or "docker run failed"


# ---------------------------------------------------------------- up
def up(a, d=None, say=print, sleep=time.sleep) -> dict:
    d = d or Docker()
    root, pid, game, saved = project(a.project)
    choice = {"source": a.source or saved.get("source") or sandbox.default_source(game),
              "folder": str(Path(a.folder).expanduser().resolve()) if a.folder else saved.get("folder"),
              "saves": str(Path(a.saves).expanduser().resolve()) if a.saves else saved.get("saves"),
              "gpu": a.gpu or saved.get("gpu") or "auto", "memory": a.memory or saved.get("memory"),
              "port": a.port or saved.get("port") or 6080, "steam_home": a.steam_home or saved.get("steam_home")}
    src = choice["source"]
    if src == "folder" and not choice["folder"]: return result(USAGE, "source folder needs --folder <the game folder>")
    if src == "folder" and not Path(choice["folder"]).is_dir(): return result(USAGE, f"no such folder: {choice['folder']}")
    if src == "steam" and game not in sandbox.STEAM_FOLDER: return result(USAGE, f"{game} does not come from Steam: --source {sandbox.default_source(game)} or folder")
    save_choice(root, choice)
    if d.run(["version", "--format", "{{.Server.Version}}"], 20)[0] != 0:
        return result(FAILED, "Docker does not answer (sudo systemctl start docker; your user in the docker group: sudo usermod -aG docker $USER, then log in again)")
    name = sandbox.container_name(game); c = container(d, name)
    if c["exists"] and c["project"] not in (None, pid):
        if not a.replace:
            return result(NEEDS_USER, f"{name} is the sandbox of project {c['project']}: one sandbox per game at a time. "
                          f"`gameanything lab sandbox down --project {c['project']}` first (its volumes stay), or up --replace")
        stop_box(d, name, game); c = container(d, name)
    state = image_state(d, game)
    before = image_id(d, sandbox.image_tag(game)) if state == "old" else None      # the image the tag named before the pull
    if state != "ok":
        from . import labdocker
        where, free = labdocker.image_store(d.bin or "docker")
        if free is not None and free < 6:            # a whole image is 3-4 GB; layers shared with an image already here need less (#26)
            return result(NEEDS_USER, f"only {free:g} GB free where Docker keeps images ({where}): free some space (docker image prune) first")
        if free is not None and free < labdocker.IMAGE_SPACE_GB:
            say(f"[sandbox] {free:g} GB free where Docker keeps images ({where}): enough when the image shares layers with one here, tight otherwise")
        say(f"[sandbox] {'a newer published ' + game + ' image: pulling it' if state == 'old' else 'getting the ' + game + ' image'}"
            f" (gameanything lab setup --image {game}) ...")
        if labdocker.pull_images([game], say=say, fallback=state == "missing") != 0 or not image_ok(d, game):
            if state == "missing": return result(FAILED, f"no {game} image: gameanything lab setup --image {game}")
            say(f"[sandbox] the pull failed: keeping the {game} image you have")
    old = image_id(d, name, container=True) if c["exists"] else None
    if old and old != image_id(d, sandbox.image_tag(game)):
        say(f"[sandbox] {name} runs an older image: re-creating it with the new one (the volumes keep everything)")
        stop_box(d, name, game); c = container(d, name)
        d.run(["image", "rm", old], 60)              # the old image, unless another container still uses it (then docker refuses)
    if before and before != old and before != image_id(d, sandbox.image_tag(game)):
        d.run(["image", "rm", before], 60)           # the same when the sandbox was down before the pull (2026-11-02: f6727fe3 stayed, 4.6 GB)
    want_mount = src == "steam" and game not in sandbox.STEAM_IN_PLACE
    have_game = steam_downloaded(d, game) if want_mount else True
    if c["exists"] and want_mount and have_game and not c["mounted"]:
        say("[sandbox] the game is downloaded now: re-creating the sandbox with it mounted read-only (the volumes keep everything)")
        stop_box(d, name, game); c = container(d, name)
    if c["exists"] and not c["running"]:
        rc, _, err = d.run(["start", name], 120)
        if rc != 0: return result(FAILED, explain_run_error(err, game))
        say(f"[sandbox] {name} started again")
    elif not c["exists"]:
        if src == "steam" and sandbox.host_apparmor() is not None and not apparmor_ready():
            cmds = sandbox.apparmor_load_commands()
            return result(NEEDS_USER, "Steam in the sandbox needs its AppArmor profile, loaded once with sudo:\n  " + "\n  ".join(" ".join(x) for x in cmds))
        gpu = {"on": True, "off": False}.get(choice["gpu"], sandbox.facts(game)["three_d"] and gpu_available())
        if sandbox.facts(game)["gpu"] == "required" and not gpu:
            return result(NEEDS_USER, f"{game} needs an NVIDIA GPU with the NVIDIA Container Toolkit in the sandbox (it opens no window without one)")
        home = choice["steam_home"] or (steam_volume_home(d, game) if src == "steam" else None)
        if home and not choice["steam_home"]: say(f"[sandbox] the Steam volume was set up with HOME={home}: using it")
        argv = sandbox.sandbox_argv(game, pid, source=src, game_dir=choice["folder"], saves_dir=choice["saves"], project_dir=str(root), gpu=gpu,
                                    memory=choice["memory"], image_uid=sandbox.image_player_uid(sandbox.image_tag(game), d.bin or "docker"),
                                    docker=d.bin or "docker", port=int(choice["port"]), steam_home_dir=home)
        if want_mount and not have_game:            # not downloaded yet: no /game mount (its subpath does not exist)
            i = next(i for i, x in enumerate(argv) if x == "--mount" and "dst=/game," in argv[i + 1]); del argv[i:i + 2]
        if src == "steam" and game in sandbox.WORKSHOP_APP and not (have_game and workshop_downloaded(d, game)):
            # nor /workshop before the Workshop items are there (her Mac 2026-10-30: Slay the Spire's first `up` failed on the missing
            # workshop/content/646570 subpath); `lab login steam --install` fetches them, then `up` re-creates the sandbox with both
            i = next((i for i, x in enumerate(argv) if x == "--mount" and "dst=/workshop," in argv[i + 1]), None)
            if i is not None: del argv[i:i + 2]
        argv[3:3] = ["--label", f"{MOUNT_LABEL}={'1' if want_mount and have_game else '0'}"]
        own_store_volumes(d, game, pid, src, argv, say)
        rc, _, err = d.run(argv[1:], 300)
        if rc != 0:
            # a `docker run` that fails at the start (the port taken: Cursor on 6080 on her Mac, 2026-10-30) leaves the container "Created";
            # the next `up` would only `docker start` it, with the old port. It never ran: remove it (the volumes stay).
            d.run(["rm", name], 60)
            return result(FAILED, explain_run_error(err, game), argv=argv)
        say(f"[sandbox] {name} created for project {pid} (game from {src}{', GPU' if gpu else ''})")
    tool = sandbox.TOOLS[game]; up_ok = False
    for _ in range(30):
        rc, out, _ = d.run(["exec", name, tool, "doctor", "--json"], 60)
        if rc == 0 and out.strip():
            up_ok = True; break
        sleep(2)
    if not up_ok: return result(FAILED, f"{name} runs but its tool does not answer: docker logs {name}")
    port = int(choice["port"]); nxt = []
    if want_mount and not have_game: nxt.append(f"gameanything lab login steam --project {a.project} --install   (then `gameanything lab sandbox up --project {a.project}` again)")
    elif src in ("steam", "ea", "microsoft"): nxt.append(f"gameanything lab login {src} --project {a.project}")
    return result(OK, "the sandbox is up", container=name, project=pid, game=game, source=src, viewer=f"http://localhost:{port}/vnc.html",
                  tunnel=f"ssh -L {port}:127.0.0.1:{port} <this computer>", game_mounted=bool(want_mount and have_game) or not want_mount, next=nxt)


def stop_box(d, name, game):
    d.run(["exec", name, sandbox.TOOLS[game], "stop"], 60)
    if game in sandbox.STEAM_FOLDER: d.run(["exec", name, "sh", "-c", "command -v ga-steam >/dev/null && ga-steam stop || true"], 60)
    if game == "sims4": d.run(["exec", name, "sh", "-c", "ga-ea stop || true"], 60)
    d.run(["stop", "-t", "20", name], 60); d.run(["rm", name], 60)


def result(code, why, **kw) -> dict:
    return {"code": code, "ok": code == OK, "why": why, **kw}


# ---------------------------------------------------------------- the other commands
def running(d, game, pid):
    name = sandbox.container_name(game); c = container(d, name)
    if not c["running"]: return None, result(DOWN, f"no running sandbox for this project: gameanything lab sandbox up --project <P>")
    if c["project"] not in (None, pid): return None, result(NEEDS_USER, f"{name} is the sandbox of project {c['project']}, not this one")
    return name, None


def in_project(root, path) -> str:
    """A path inside the project folder as the sandbox sees it (/project/...), or None."""
    p = Path(path).expanduser().resolve()
    try: return "/project/" + p.relative_to(Path(root).resolve()).as_posix()
    except ValueError: return None


def main(argv) -> int:
    ap = argparse.ArgumentParser(prog="gameanything lab sandbox", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["up", "status", "tool", "build", "shot", "input", "look", "fetch", "down"])
    ap.add_argument("rest", nargs="*", help="tool: after --; build: the mod folder; shot: the file; input: key K | click X Y | ...")
    ap.add_argument("--project", required=True)
    ap.add_argument("--source", choices=["steam", "folder", "ea", "microsoft"]); ap.add_argument("--folder"); ap.add_argument("--saves")
    ap.add_argument("--gpu", choices=["auto", "on", "off"]); ap.add_argument("--memory"); ap.add_argument("--port", type=int)
    ap.add_argument("--steam-home", help="where the Steam home volume goes (keep the place it was made at: Steam stores absolute paths)")
    ap.add_argument("--replace", action="store_true", help="up: stop another project's sandbox of the same game first (its volumes stay)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("-n", type=int, default=200, help="look: the last N lines of a file")
    argv = list(argv); tail = []
    if "--" in argv: i = argv.index("--"); argv, tail = argv[:i], argv[i + 1:]      # tool -- <args of the game's tool>
    a = ap.parse_intermixed_args(argv)
    rest = a.rest + tail
    d = Docker()
    say = (lambda m: print(m, file=sys.stderr, flush=True)) if a.json else print
    if a.what == "up":
        r = up(a, d, say)
    else:
        root, pid, game, saved = project(a.project)
        name, r = running(d, game, pid) if a.what not in ("status", "down") else (sandbox.container_name(game), None)
        if a.what == "down":
            c = container(d, name)
            if c["exists"] and c["project"] not in (None, pid): r = result(NEEDS_USER, f"{name} is the sandbox of project {c['project']}, not this one")
            elif not c["exists"]: r = result(OK, "no sandbox to stop")
        if r is None: r = other(a.what, rest, d, root, pid, game, name, say, n=a.n, source=saved.get("source"))
    if a.json: print(osdirs.json_text(r))
    else:
        print(f"[sandbox] {r['why']}")
        for k in ("viewer", "tunnel"):
            if r.get(k): print(f"[sandbox] {k}: {r[k]}")
        for n in r.get("next") or []: print(f"[sandbox] next: {n}")
    return r["code"]


LOOK_ROOTS = ("/sandbox", "/game", "/project", "/workshop")


def steam_running(d, name) -> bool:
    """ga-steam status --json is indented over many lines (as loginflow.jsn reads it); 2026-10-31 the last line alone ("}") made
    every `tool -- run` of a Steam game refuse while Steam was running."""
    rc, out, _ = d.run(["exec", name, "sh", "-c", "ga-steam status --json 2>/dev/null"], 60)
    if rc != 0 and not out.strip(): return True              # no ga-steam: nothing to check
    try: v = json.loads(out.strip())
    except ValueError: v = None
    return bool(v.get("running")) if isinstance(v, dict) else False


def _status(d, name, cmd):
    rc, out, _ = d.run(["exec", name, "sh", "-c", f"{cmd} status --json 2>/dev/null"], 60)
    try: v = json.loads((out or "").strip())
    except ValueError: v = None
    return v if isinstance(v, dict) else {}


def signin_open(d, name, source):
    """Why no picture may be taken now, or "": a store's sign-in window is open (never a screenshot or recording of what she types).
    EA: also any window that is neither the EA App's nor the game's (2026-10-31: right after she signed in, The Sims 4's launcher showed
    its own 「Sign in with your EA Account to activate」 window, which ga-ea did not report as a sign-in window)."""
    if source == "steam":
        return "Steam's sign-in window is open" if _status(d, name, "ga-steam").get("login_window") else ""
    if source == "ea":
        st = _status(d, name, "ga-ea")
        if st.get("login_window"): return "the EA App's sign-in window is open"
        odd = [w.get("title", "") for w in st.get("windows") or [] if w.get("title") != "EA" and "Sims" not in (w.get("title") or "")]
        if odd: return f"a window that may ask her to sign in is open ({', '.join(odd)[:80]})"
    return ""


def other(what, rest, d, root, pid, game, name, say, n=200, source=None) -> dict:
    tool = sandbox.TOOLS[game]
    if what == "status":
        c = container(d, name)
        st = None
        if c["running"]:
            rc, out, _ = d.run(["exec", name, tool, "doctor", "--json"], 60)
            try: st = json.loads(out.strip().splitlines()[-1]) if rc == 0 and out.strip() else None
            except ValueError: st = None
        return result(OK if c["running"] else DOWN, "running" if c["running"] else ("stopped" if c["exists"] else "no sandbox"),
                      container=name, project=c["project"], ours=c["project"] in (None, pid), game_mounted=c["mounted"], doctor=st)
    if what == "tool":
        if not rest: return result(USAGE, f"tool needs the arguments of {tool} (doctor, layer, run, shot, rec, log, stop)")
        if rest[0] == "run" and (source or sandbox.default_source(game)) == "steam" and not steam_running(d, name):
            # 2026-10-30 E2E: the builder ran Valheim without Steam and looked at a black screen for minutes
            return result(FAILED, f"Steam is not running in the sandbox ({game} needs it): gameanything lab login steam --project {root} "
                          "(the saved login signs in by itself), then run again")
        if rest[0] == "shot" or rest[:2] == ["rec", "start"]:
            why = signin_open(d, name, source or sandbox.default_source(game))
            if why: return result(NEEDS_USER, f"no {rest[0]}: {why}; she signs in in the viewer (or closes it), then try again")
        return result(OK if d.stream(["exec", name, tool, *rest]) == 0 else FAILED, f"{tool} {' '.join(rest)} done")
    if what == "build":
        if len(rest) != 1: return result(USAGE, "build needs one mod folder (inside the project folder)")
        inside = in_project(root, rest[0])
        if not inside: return result(USAGE, f"{rest[0]} is not inside the project folder {root} (the sandbox sees only that, at /project)")
        rc = d.stream(["exec", name, "gameanything", "native", "build", "--game", game, "--install", inside])
        return result(OK if rc == 0 else FAILED, f"build of {inside} {'done' if rc == 0 else 'failed'}")
    if what == "shot":
        if len(rest) != 1: return result(USAGE, "shot needs the file to write on this computer")
        why = signin_open(d, name, source or sandbox.default_source(game))
        if why: return result(NEEDS_USER, f"no screenshot: {why}; she signs in in the viewer (or closes it), then try again")
        out = Path(rest[0]).expanduser().resolve(); tmp = f"/sandbox/shots/host-{int(time.time())}.png"
        rc, _, err = d.run(["exec", name, "sh", "-c", f"mkdir -p /sandbox/shots && {tool} shot {tmp}"], 60)
        if rc != 0: return result(FAILED, f"shot failed: {err.strip()[-300:]}")
        out.parent.mkdir(parents=True, exist_ok=True)
        rc, _, err = d.run(["cp", f"{name}:{tmp}", str(out)], 60); d.run(["exec", name, "rm", "-f", tmp], 30)
        return result(OK if rc == 0 else FAILED, f"screenshot {out}" if rc == 0 else f"copy failed: {err.strip()[-300:]}", file=str(out))
    if what == "input":
        x = {"key": 2, "click": 3, "move": 3, "type": 2}
        if not rest or rest[0] not in x or len(rest) != x[rest[0]]: return result(USAGE, "input key K | click X Y | move X Y | type TEXT")
        xd = {"key": ["key", rest[1:][0] if rest[1:] else ""], "type": ["type", "--delay", "40", rest[1] if len(rest) > 1 else ""],
              "move": ["mousemove", *rest[1:]], "click": ["mousemove", *rest[1:], "click", "1"]}[rest[0]]
        rc, _, err = d.run(["exec", "-e", "DISPLAY=:99", name, "xdotool", *xd], 30)
        return result(OK if rc == 0 else FAILED, f"input {rest[0]} {'sent' if rc == 0 else 'failed: ' + err.strip()[-200:]}")
    if what == "look":
        if len(rest) != 1: return result(USAGE, "look needs one path inside the sandbox")
        p = rest[0]
        if ".." in Path(p).parts or not any(p == r or p.startswith(r + "/") for r in LOOK_ROOTS):
            return result(USAGE, f"look reads only under {', '.join(LOOK_ROOTS)}")
        rc, out, err = d.run(["exec", name, "sh", "-c", 'if [ -d "$1" ]; then ls -la "$1"; else tail -n "$2" "$1"; fi', "look", p, str(max(1, n))], 60)
        if out: print(out, end="" if out.endswith("\n") else "\n")
        return result(OK if rc == 0 else FAILED, f"look {p}" + ("" if rc == 0 else f": {err.strip()[-200:]}"))
    if what == "fetch":
        if len(rest) != 2: return result(USAGE, "fetch needs the file in the sandbox and the file to write in the project")
        src, dst = rest[0], Path(rest[1]).expanduser().resolve()
        if not src.startswith("/sandbox/") or ".." in Path(src).parts: return result(USAGE, "fetch copies only files under /sandbox/")
        if not in_project(root, dst): return result(USAGE, f"{dst} is not inside the project folder {root}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        rc, _, err = d.run(["cp", f"{name}:{src}", str(dst)], 600)
        return result(OK if rc == 0 else FAILED, f"copied {src} -> {dst}" if rc == 0 else f"copy failed: {err.strip()[-300:]}", file=str(dst))
    if what == "down":
        stop_box(d, name, game)
        return result(OK, f"{name} stopped and removed; the volumes stay (logins, downloads, {sandbox.sandbox_volume(game, pid)})")
    return result(USAGE, what)
