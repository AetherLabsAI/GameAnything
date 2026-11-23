"""The lab (镜像 / sandbox mode) on the user's OWN Linux machine with a plain Docker engine (lab images phase 2,
2026-10-24). The images are the private ghcr.io/aetherlabsai/m2w-lab-{base,java,dotnet,steam}; the drivers are gamebench's
agent/modlab/stardew/sdlab_docker.py and agent/modlab/minecraft/mclab_docker.py (sdlab_rt.py / mclab_rt.py hand over to them by
themselves on plain Docker, so builder briefs are the same as on the maintainer's lab server). Settings: gamebench hosting/lab/labenv.py reads
~/.config/m2w/lab.env (or $M2W_LAB_HOME/lab.env, $M2W_LAB_CONFIG).

    status(env)        {config, gamebench, docker_login, images: {kind: ref | None}, games: {game: {ready, folder, image, why}}, pool}
    ready_games(env)   the gameanything game ids the plain lab can run on this machine now (buildmode: the "docker" backend's lab games)
    local_pool(env)    the local broker pool file (<M2W_LAB_HOME>/labs/pool.yaml) when a lab config exists, else None
    setup(argv)        `gameanything lab setup`: docker login ghcr.io (PAT with read:packages), pull the images, write lab.env, point it at the
                       game folders, write the local seat pool. Never prints the token. The pulled lab images run as the caller's
                       uid (gamebench seat.py --user). `--image GAME`: pull_images()
    pull_images(games) `--image GAME`: pull the published runtime-only image (sandbox.published_ref), else build_images(games): the
                       lab/images/ chain built locally, always for the user's own uid (sandbox.chain_argvs)

A game is ready when: a lab config file exists, the gamebench checkout has its plain driver, its folder is set and looks right
(Stardew: the Linux build with Stardew Valley.dll; Minecraft: a portablemc/launcher folder with versions/), and its image is on
this machine or pullable (logged in to ghcr.io).
"""
import getpass
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REGISTRY = "ghcr.io/aetherlabsai"
# gameanything game id -> (image kind, lab.env variable, gamebench driver, lab-doctor game id, pool game)
DRIVERS = {
    "stardew": ("dotnet", "M2W_LAB_GAME_STARDEW", "agent/modlab/stardew/sdlab_docker.py", "stardew", "stardew_valley"),
    "minecraft": ("java", "M2W_LAB_GAME_MINECRAFT", "agent/modlab/minecraft/mclab_docker.py", "minecraft", "minecraft"),
}
KINDS = ("base", "dotnet", "java")


def _env(env):
    return dict(os.environ if env is None else env)


def gamebench(env=None):
    from . import buildmode
    return buildmode.gamebench(env)


def labenv(env=None):
    """gamebench's hosting/lab/labenv.py as a module, or None (no gamebench checkout)."""
    g = gamebench(env)
    p = g / "hosting" / "lab" / "labenv.py" if g else None
    if not p or not p.is_file(): return None
    spec = importlib.util.spec_from_file_location("_m2w_labenv", p); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def config(env=None):
    """(values, config file) of the lab config, or (None, None) when there is no config file (the maintainer's lab server: none, docker-rt)."""
    e = _env(env); le = labenv(e)
    if not le: return None, None
    cfg = le.config_path(e)
    if not cfg or not Path(cfg).is_file(): return None, None
    try: return le.resolve(e)[0], Path(cfg)
    except SystemExit: return None, Path(cfg)


def local_pool(env=None):
    v, _ = config(env)
    if not v: return None
    return Path(v.get("M2W_LAB_POOL") or Path(v["M2W_LAB_HOME"]) / "labs" / "pool.yaml")


def _docker(env=None):
    from . import buildmode
    return buildmode.docker_bin(env)


def image_present(ref, env=None):
    d = _docker(env)
    if not d: return False
    try: return subprocess.run([d, "image", "inspect", "--format", "{{.Id}}", ref], capture_output=True, timeout=10, env=_env(env)).returncode == 0
    except (OSError, subprocess.SubprocessError): return False


def image_for(kind, v, env=None):
    """The image a seat of this kind would use (same rule as gamebench hosting/lab/seat.py image()) and whether it is here."""
    want = (v or {}).get(f"M2W_LAB_IMAGE_{kind.upper()}") or ""
    if want: return want, image_present(want, env)
    for ref in (f"m2w-lab-{kind}:local", f"{REGISTRY}/m2w-lab-{kind}:latest"):
        if image_present(ref, env): return ref, True
    return f"{REGISTRY}/m2w-lab-{kind}:latest", False


def docker_login(env=None) -> bool:
    """docker has credentials for ghcr.io (~/.docker/config.json or $DOCKER_CONFIG): the private images can be pulled."""
    e = _env(env)
    p = Path(e.get("DOCKER_CONFIG") or Path(e.get("HOME") or Path.home()) / ".docker") / "config.json"
    try: d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError): return False
    keys = list((d.get("auths") or {})) + list((d.get("credHelpers") or {}))
    return any("ghcr.io" in k for k in keys)


def folder_ok(game, path) -> bool:
    p = Path(path).expanduser() if path else None
    if not p or not p.is_dir(): return False
    if game == "stardew": return (p / "Stardew Valley.dll").exists() or (p / "StardewValley.dll").exists()
    if game == "minecraft": return (p / "main" / "versions").is_dir() or (p / "versions").is_dir()
    return False


def status(env=None) -> dict:
    e = _env(env); g = gamebench(e); v, cfg = config(e)
    login = docker_login(e)
    out = {"config": str(cfg) if cfg else None, "gamebench": str(g) if g else None, "docker_login": login, "images": {}, "games": {},
           "pool": None}
    if v:
        p = local_pool(e); out["pool"] = str(p) if p and p.is_file() else None
    for game, (kind, var, drv, _, _) in DRIVERS.items():
        folder = (v or {}).get(var)
        img, here = image_for(kind, v, e) if v else (None, False)
        out["images"][kind] = img if here else None
        why = ("no_config" if not v else "no_driver" if not (g and (g / drv).is_file()) else "no_folder" if not folder_ok(game, folder)
               else "no_image" if not (here or login) else "")
        out["games"][game] = {"ready": not why, "why": why, "folder": folder, "image": img, "image_here": here}
    return out


def ready_games(env=None) -> set:
    return {g for g, s in status(env)["games"].items() if s["ready"]}


# ---------------------------------------------------------------- `gameanything lab setup`
WHY_TEXT = {"no_config": "no lab config (lab.env)", "no_driver": "the gamebench checkout has no plain-Docker driver for it (git pull gamebench)",
            "no_folder": "game folder not set or not the right build", "no_image": "image not here and not logged in to ghcr.io"}


def set_key(path: Path, key: str, value: str):
    """KEY=value in a lab.env: replaces the KEY= line (or a commented `# KEY=` line), else appends it. Other lines are kept."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    new = f"{key}={value}"
    for i, l in enumerate(lines):
        s = l.strip().lstrip("#").strip()
        if s.startswith("export "): s = s[7:].strip()
        if s.split("=", 1)[0].strip() == key and "=" in s:
            lines[i] = new; break
    else:
        lines.append(new)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ask(prompt, default, yes):
    if yes or not sys.stdin.isatty(): return default
    a = input(f"{prompt} [{default}]: ").strip()
    return a or default


def _yn(prompt, yes, default=True):
    if yes or not sys.stdin.isatty(): return default
    a = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not a else a.startswith("y")


def _doctor(g, env):
    try:
        r = subprocess.run([sys.executable, str(g / "hosting" / "lab" / "lab-doctor"), "--json", "--game", "stardew", "--game", "minecraft"],
                           capture_output=True, text=True, encoding="utf-8", timeout=180, env=env)
        return json.loads(r.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"checks": [], "docker": False, "render_mode": "software"}


def build_images(games, say=print, env=None, run=None, steam=False) -> int:
    """Build the runtime-only sandbox images LOCALLY (the fallback; the default is pull_images): for each game the shared layers of
    sandbox.CHAINS (base, steam / java / wine, dotnet) and then its own layer, always for the user's own uid (sandbox.chain_argvs):
    private mounted files (a Minecraft world's 0600 level.dat) stay readable. Nobody passes PLAYER_UID by hand. steam: kept for old
    callers (the Steam layer is in every image of a game that can come from Steam)."""
    from . import sandbox
    e = _env(env)
    d = _docker(e) or "docker"
    run = run or (lambda argv: subprocess.run(argv, env=e).returncode)
    for game in games:
        if game not in sandbox.IMAGES:
            print(f"[lab setup] no sandbox image for {game!r} yet (images: {', '.join(sandbox.IMAGES)})", file=sys.stderr); return 2
        if not sandbox.dockerfile(game).is_file():
            print(f"[lab setup] {sandbox.dockerfile(game)} is missing: building an image needs a GameAnything checkout (git clone)", file=sys.stderr)
            return 2
        if sandbox.PLATFORM == "linux/arm64" and game not in sandbox.ARM_IMAGES:
            print(f"[lab setup] {game}: no sandbox on an ARM computer (Apple silicon): only {', '.join(sorted(sandbox.ARM_IMAGES))} run "
                  "there (Steam and the game under FEX); use native mode", file=sys.stderr); return 2
        u = sandbox.player_uid()
        who = f"uid {u[0]} (yours)" if u else "uid 1000 (none of yours needed: Windows shares its drives readable to every uid; root reads all)"
        arm = " for arm64 (Apple silicon: Steam and the game under FEX, experimental)" if sandbox.PLATFORM == "linux/arm64" else ""
        say(f"building {sandbox.image_tag(game)} locally ({' -> '.join(sandbox.CHAINS[game])} -> {game}){arm} for {who}")
        for argv in sandbox.chain_argvs(game, docker=d):
            if run(argv) != 0:
                print(f"[lab setup] docker build of {game} failed at {argv[argv.index('-t') + 1]} (see above)", file=sys.stderr); return 1
    return 0


IMAGE_SPACE_GB = 15        # one game's chain of layers is 2-5 GB; a build needs room for its cache and the unpacked layers too


def image_store(docker="docker", env=None, info=None, usage=None):
    """(folder, free GB) where Docker keeps images on THIS computer, or (None, None) when it cannot be told (Docker Desktop: in its VM).
    Docker Engine 29 with the containerd image store keeps them in /var/lib/containerd, which is often on the root disk even when
    /var/lib/docker is a big separate disk (plain Docker test 2026-10-29: the shared root disk filled up during `--image` builds)."""
    import shutil
    if info is None:
        try: info = subprocess.run([docker, "info", "--format", "{{.DockerRootDir}}|{{json .DriverStatus}}"], capture_output=True, text=True,
                                   encoding="utf-8", timeout=15, env=env).stdout.strip()
        except (OSError, subprocess.SubprocessError): return None, None
    root, _, status = info.partition("|")
    path = "/var/lib/containerd" if "io.containerd.snapshotter" in status else root
    if not path or not Path(path).exists(): return None, None
    try: free = (usage or shutil.disk_usage)(path).free
    except OSError: return None, None
    return path, round(free / 2 ** 30, 1)


def pull_images(games, say=print, env=None, run=None, build=False, fallback=True) -> int:
    """`gameanything lab setup --image GAME`: pull the published image (sandbox.published_ref, by digest) and tag it as
    gameanything-lab-<game>; when the pull fails (not logged in to ghcr.io, offline) build it locally instead (build_images), unless
    fallback=False. build=True skips the pull. A pulled image is built for uid 1000: run_argv starts it with --user <your uid>."""
    from . import sandbox
    e = _env(env)
    d = _docker(e) or "docker"
    run = run or (lambda argv: subprocess.run(argv, env=e).returncode)
    for game in games:
        if game not in sandbox.IMAGES:
            print(f"[lab setup] no sandbox image for {game!r} yet (images: {', '.join(sandbox.IMAGES)})", file=sys.stderr); return 2
        if not build and sandbox.PLATFORM == "linux/arm64":
            say("ARM computer (Apple silicon): there are no published arm64 images, building it here (about 15 minutes the first time)")
        elif not build:
            pull, tag = sandbox.pull_argvs(game, docker=d)
            say(f"pulling {pull[-1]}")
            if run(pull) == 0 and run(tag) == 0:
                say(f"{sandbox.image_tag(game)} = {pull[-1]} (built for uid 1000; started with your uid, no rebuild needed)"); continue
            hint = ("not logged in to ghcr.io? The images are private for now: docker login ghcr.io -u <GitHub user> with a classic PAT "
                    "that has only read:packages")
            if not fallback:
                print(f"[lab setup] pull of {game} failed: {hint}", file=sys.stderr); return 1
            say(f"pull failed ({hint}); building it locally instead")
        r = build_images([game], say=say, env=e, run=run)
        if r: return r
    return 0


def _login(a, env, d, say) -> int:
    """docker login ghcr.io with --github-user and the PAT (stdin with --pat-stdin, else asked hidden). -> 0, or 1 with the reason printed."""
    user = a.github_user or (None if a.yes else _ask("GitHub user (for ghcr.io)", os.environ.get("USER", ""), False))
    pat = sys.stdin.readline().strip() if a.pat_stdin else (getpass.getpass("GitHub PAT (classic, only read:packages; hidden): ").strip()
                                                           if sys.stdin.isatty() and not a.yes else "")
    if not (user and pat):
        print("[lab setup] not logged in to ghcr.io: create a classic PAT with read:packages (https://github.com/settings/tokens), then\n"
              "  echo <PAT> | docker login ghcr.io -u <github user> --password-stdin   (or: gameanything lab setup --github-user U --pat-stdin)",
              file=sys.stderr); return 1
    r = subprocess.run([d, "login", "ghcr.io", "-u", user, "--password-stdin"], input=pat + "\n", capture_output=True, text=True, encoding="utf-8", env=env)
    pat = None
    if r.returncode != 0:
        print(f"[lab setup] docker login ghcr.io failed: {(r.stderr or r.stdout).strip()[-300:]}\n  (needs read access to the m2w-lab packages: ask the maintainer)", file=sys.stderr); return 1
    say("ghcr.io: logged in")
    return 0


def setup(argv) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="gameanything lab setup", description="Set up the lab (镜像 mode) on THIS Linux machine with plain Docker: "
                                 "ghcr.io login, images, ~/.config/m2w/lab.env, game folders, the local seat pool. Safe to run again.")
    ap.add_argument("--yes", "-y", action="store_true", help="no questions: take what lab-doctor finds")
    ap.add_argument("--github-user", default=None, help="GitHub user for `docker login ghcr.io` (the PAT is read hidden, or from stdin with --pat-stdin)")
    ap.add_argument("--pat-stdin", action="store_true", help="read the PAT (classic, read:packages only) from stdin; it is passed to docker, never printed or stored by GameAnything")
    ap.add_argument("--home", default=None, help="the lab's data folder M2W_LAB_HOME (default ~/m2w-lab; 40+ GB free)")
    ap.add_argument("--stardew", default=None, help="your Stardew Valley folder (the Linux build)")
    ap.add_argument("--minecraft", default=None, help="your Minecraft folder (portablemc main/ work/, or ~/.minecraft)")
    ap.add_argument("--no-pull", action="store_true", help="do not pull images (you built them: docker/lab/build.sh)")
    ap.add_argument("--image", action="append", default=[], metavar="GAME",
                    help="get this game's runtime-only sandbox image: pull the published one (ghcr.io/aetherlabsai/gameanything-lab-<game>, "
                         "private for now: docker login ghcr.io first), else build it locally from lab/images/ for your own uid; repeatable. "
                         "Games: stardew, minecraft, ksp, slay_the_spire, terraria, valheim, overcooked2, cities_skylines, civ6, sims4. "
                         "Works with Docker Desktop on Windows and Mac too (x86_64 images: Rosetta on Apple silicon)")
    ap.add_argument("--build", action="store_true", help="with --image: build locally (base -> runtime layers -> the game) instead of pulling")
    ap.add_argument("--steam", action="store_true", help="with --image: kept for old scripts; the Steam layer is in every image of a game "
                    "that can come from Steam (docs/sandbox-images.md, 'Steam inside the sandbox')")
    ap.add_argument("--json", action="store_true", help="print the final status as JSON")
    a = ap.parse_args(argv)
    if a.image:
        where, free = image_store(_docker(_env(None)) or "docker")
        if free is not None and free < IMAGE_SPACE_GB:
            print(f"[lab setup] only {free:g} GB free where Docker keeps images ({where}); a sandbox image needs about {IMAGE_SPACE_GB} GB. "
                  f"Free some space there first (docker image prune, or move Docker's image store to a bigger disk). Nothing was pulled or built.",
                  file=sys.stderr); return 1
        say0 = (lambda *x: None) if a.json else (lambda *x: print("[lab setup]", *x, flush=True))
        env0 = _env(None)
        if (a.github_user or a.pat_stdin) and not a.build and not docker_login(env0):
            # her Mac 2026-10-30: `--image X --github-user U --pat-stdin` pulled before the login further down, so it never logged in
            r = _login(a, env0, _docker(env0) or "docker", say0)
            if r: return r
        r = pull_images(a.image, build=a.build, say=say0)
        if r or not (a.stardew or a.minecraft or a.github_user or a.home): return r    # only the images were asked for
    from . import buildmode, osdirs
    env = dict(os.environ)
    say = (lambda *x: None) if a.json else (lambda *x: print("[lab setup]", *x, flush=True))
    if osdirs.system() != "linux":
        print("[lab setup] the lab needs Linux + Docker; on this computer use native mode (gameanything native doctor)", file=sys.stderr); return 1
    g = gamebench(env)
    if not g:
        print("[lab setup] no gamebench checkout (the internal lab repo: ask the maintainers for access); clone it, "
              "then export GAMEANYTHING_GAMEBENCH=<that folder>", file=sys.stderr); return 1
    if not labenv(env):     # a checkout of a branch without the lab (seen 2026-10-29: main and wenyi have no hosting/lab; wenyi-west1 has it)
        print(f"[lab setup] {g} has no hosting/lab/labenv.py: check out a gamebench branch with the lab (git -C {g} log --oneline -1 "
              "-- hosting/lab shows whether this one has it)", file=sys.stderr); return 1
    if not buildmode.docker_ok(env):
        print("[lab setup] Docker does not answer: install Docker Engine (sudo apt install docker.io), add yourself to the docker group "
              "(sudo usermod -aG docker $USER, log in again), then run this again", file=sys.stderr); return 1
    say(f"gamebench {g}; Docker ok")
    d = _docker(env)
    # 1. registry login (the images are private)
    if docker_login(env): say("ghcr.io: logged in")
    elif a.no_pull: say("ghcr.io: not logged in (--no-pull: using images built here)")
    else:
        r = _login(a, env, d, say)
        if r: return r
    # 2. lab.env
    le = labenv(env); cfg = le.config_path(env)
    if not cfg or not Path(cfg).is_file():
        cfg = Path(cfg or Path(env.get("HOME") or Path.home()) / ".config" / "m2w" / "lab.env").expanduser()
        home = a.home or _ask("lab data folder (40+ GB free)", str(Path.home() / "m2w-lab"), a.yes)
        ex = g / "config" / "lab.env.example"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(ex.read_text(encoding="utf-8") if ex.is_file() else "", encoding="utf-8")
        set_key(cfg, "M2W_LAB_HOME", home)
        say(f"wrote {cfg}")
    else:
        if a.home: set_key(cfg, "M2W_LAB_HOME", a.home)
        say(f"lab config {cfg}")
    env["M2W_LAB_CONFIG"] = str(cfg)
    # 3. game folders: given, else what lab-doctor finds
    doc = _doctor(g, env)
    found = {c["name"]: (c.get("data") or {}).get("path") for c in doc.get("checks", []) if c.get("area") == "games" and c.get("status") == "ok"}
    v = le.resolve(env)[0]
    for game, (kind, var, _, dgame, _) in DRIVERS.items():
        given = getattr(a, game)
        cur = v.get(var) if folder_ok(game, v.get(var)) else None
        pick = given or cur or found.get(dgame)
        if pick and not given and pick != cur:
            pick = pick if _yn(f"use {pick} for {game}?", a.yes) else None
        if not pick and not a.yes: pick = _ask(f"{game} folder (empty: skip)", "", False) or None
        if pick:
            if not folder_ok(game, pick): say(f"{game}: {pick} does not look right ({'need the Linux build with Stardew Valley.dll' if game == 'stardew' else 'need main/versions or versions/'}); written anyway")
            set_key(cfg, var, str(Path(pick).expanduser())); say(f"{game}: {pick}")
        else:
            say(f"{game}: no folder (skip; set {var} in {cfg} later)" + (" - Minecraft: docs/lab-acceptance.md step 4b" if game == "minecraft" else ""))
    v = le.resolve(env)[0]
    # 4. images
    if not a.no_pull:
        kinds = ["base"] + [DRIVERS[gm][0] for gm in DRIVERS if folder_ok(gm, v.get(DRIVERS[gm][1]))]
        for kind in dict.fromkeys(kinds):
            ref, here = image_for(kind, v, env)
            if here: say(f"image {ref}: here"); continue
            say(f"pulling {ref} (a few GB) ...")
            r = subprocess.run([d, "pull", ref], capture_output=True, text=True, encoding="utf-8", env=env)
            if r.returncode != 0:
                print(f"[lab setup] pull {ref} failed: {(r.stderr or r.stdout).strip()[-300:]}", file=sys.stderr); return 1
    # 5. the local seat pool (one sandbox "local" = this machine)
    games = [DRIVERS[gm][4] for gm in DRIVERS if folder_ok(gm, v.get(DRIVERS[gm][1]))]
    r = subprocess.run([sys.executable, str(g / "hosting" / "lab" / "seat.py"), "pool", "--write", "--force", *sum((["--game", x] for x in games), [])],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    if r.returncode != 0:
        print(f"[lab setup] writing the seat pool failed: {(r.stderr or r.stdout).strip()[-300:]}", file=sys.stderr); return 1
    say(r.stdout.splitlines()[0] if r.stdout else "pool written")
    st = status(env)
    if a.json: print(osdirs.json_text(st, indent=1))
    else:
        for game, s in st["games"].items():
            say(f"{game}: " + ("READY" if s["ready"] else f"not ready: {WHY_TEXT.get(s['why'], s['why'])}"))
        if any(s["ready"] for s in st["games"].values()):
            say("next: gameanything project new --title ... --game stardew --mode lab   (or `gameanything ui`: 在哪里做 = 服务器沙箱（镜像）)")
    return 0 if any(s["ready"] for s in st["games"].values()) else 1
