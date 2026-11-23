"""Where a project's builds run (design of 2026-10-24): `build_mode` in config/project.yaml, chosen in the new-project wizard
(「在哪里做」) and changeable later in the project's menu (the hub: edit role or the owner).

    lab      the server's docker sandbox (镜像): the gamebench labs. Needs Linux, a gamebench checkout, that engine answering, and
             docker-rt (the maintainer's cluster pods behind /tmp/docker-rt.sock): the launch scripts hosting/launch_rt/
             and, when a broker pool file is configured ($GAMEANYTHING_LAB_POOL / $M2W_LAB_POOL, or settings.yaml lab_pool), a sandbox that runs the game;
             plain local Docker (an outside user's Linux machine, labdocker.py): gamebench's plain driver (hosting/lab/seat.py), a lab
             config (~/.config/m2w/lab.env, `gameanything lab setup`), and per game its folder + image (pulled or pullable) and, when the local
             pool (<M2W_LAB_HOME>/labs/pool.yaml) exists, a seat for it there.
             the user's own sandbox (2026-10-30, labsandbox.py): Linux with a local Docker engine and NO gamebench lab: the published
             images and `gameanything lab sandbox`, one container per game, no seats. Every game with a sandbox image (sandbox.IMAGES).
    native   the user's own copy of the game (D19, native/): saves backed up first, only the Mods folder changes, never docker

    options(game, ...)     the two choices for one game on this computer: each ok or greyed with the reason, a note, and the recommended one
    mode_of(root)          the project's chosen mode, or None (a project from before 2026-10-24: the automatic rule auto_mode(), native.doctor())
    effective(root)        (mode, "project" | "auto")
    set_mode(ref, mode)    edits only the `build_mode:` line;  migrate(mode)  writes it into every registered project that has none (opt-in)

Texts are the Chinese source keys the page translates (i18n.js); every one is in TEXTS.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import yaml

from . import games as registry, layout, osdirs, projects

MODES = ("lab", "native")
# from each game.yaml's `lab:` (the game registry, games/): pool_name, steam, script
POOL_NAME = registry.lab_pool_names()       # gameanything game id -> the broker pool's game name (the rest are the same)
STEAM = registry.lab_steam()                # run on the shared Steam sandbox (the pool's `steam: true` adds to this)
SCRIPT = registry.lab_scripts()             # gameanything game id -> its gamebench launch script name (the rest are the same)
DOCKER_FALLBACK = ("/opt/docker-rt/bin/docker", "/usr/local/bin/docker", "/usr/bin/docker")
RT_SOCK = "/tmp/docker-rt.sock"
LOCAL_SOCK = "/var/run/docker.sock"
LAUNCH = {"docker-rt": "launch_rt", "docker": "launch"}    # the gamebench launch scripts of each backend (the broker / guards: launch_rt only)

NAME = {"native": "我的电脑（本机）", "lab": "沙箱（镜像）"}
WHY = {   # the one-line reason under the recommended choice
    "not_linux": "这台电脑是 {s}：直接装进你自己的游戏",
    "no_docker": "这台电脑上的沙箱还不能用：直接装进你自己的游戏",
    "no_adapter": "这个游戏还没有本机适配：在沙箱里做",
    "lab_cant": "沙箱跑不了这个游戏：直接装进你自己的游戏",
    "hub": "多人共用的服务器：在沙箱里做，不占你的电脑",
    "headless": "这是一台没有屏幕的服务器：在沙箱里做",
    "not_installed": "这台电脑上没装这个游戏：在沙箱里做",
    "hands_off": "长时间在后台跑、不用你看着：在沙箱里做",
    "play": "游戏装在这台电脑上，你可以自己玩：直接装进你的游戏",
    "none": "两种都还不能用：可以先建项目、做设计，构建前再选",
}
GREY = {  # why a choice cannot work here
    "lab_os": "沙箱需要 Linux 和 Docker，这台电脑是 {s}",
    "lab_kit": "这台电脑上的沙箱还没配好",
    "lab_docker": "这台电脑上的 Docker 没有回应",
    "lab_no_docker": "这台电脑上还没装 Docker：装好 Docker Engine 就能用沙箱",
    "lab_game": "沙箱还不能跑这个游戏",
    "lab_script": "这台机器没配好这个游戏的沙箱",
    "no_adapter": "这个游戏还没有本机适配",
}
NOTE = {
    "native": "先备份你的存档，只改 Mods 文件夹",
    "native_missing": "先备份你的存档，只改 Mods 文件夹；这台电脑上还没找到这个游戏，构建前要装好",
    "lab": "在沙箱（Docker 容器）里构建和试玩，不动你电脑上的游戏",
    "lab_steam": "在沙箱（Docker 容器）里构建和试玩；沙箱运行时会占用你的 Steam 账号（同一时间只能在一处玩）",
}
TEXTS = set(NAME.values()) | set(WHY.values()) | set(GREY.values()) | set(NOTE.values())
SYS_NAME = {"linux": "Linux", "mac": "macOS", "windows": "Windows"}


# ---------------------------------------------------------------- what this computer has
def docker_bin(env=None):
    """The docker client: $GAMEANYTHING_DOCKER, then PATH, then /opt/docker-rt/bin/docker (this server's docker-rt; not always on PATH)."""
    env = os.environ if env is None else env
    if env.get("GAMEANYTHING_DOCKER") and Path(env["GAMEANYTHING_DOCKER"]).is_file(): return env["GAMEANYTHING_DOCKER"]
    w = shutil.which("docker", path=env.get("PATH"))
    if w: return w
    return next((p for p in DOCKER_FALLBACK if os.access(p, os.X_OK)), None)


def backend(env=None):
    """Which engine the docker client talks to: "docker-rt" (DOCKER_HOST unix:///tmp/docker-rt…, or its socket is here: the cluster shim
    routes to it), "docker" (a local engine: DOCKER_HOST set otherwise, or /var/run/docker.sock), or None."""
    env = os.environ if env is None else env
    h = env.get("DOCKER_HOST") or ""
    if h.startswith("unix:///tmp/docker-rt"): return "docker-rt"
    if h: return "docker"
    if os.path.exists(RT_SOCK): return "docker-rt"
    return "docker" if os.path.exists(LOCAL_SOCK) else None


def gamebench_path(env=None):
    """Where the gamebench checkout is configured (maintainers' lab servers only, internal/README.md): $GAMEANYTHING_GAMEBENCH, $WC_CODE, or
    settings.yaml `gamebench`; None when none is (every user's machine). No built-in path since 2026-11-01."""
    env = os.environ if env is None else env
    v = env.get("GAMEANYTHING_GAMEBENCH") or env.get("WC_CODE") or projects.settings().get("gamebench")
    return Path(v).expanduser() if v else None


def gamebench(env=None):
    """The configured gamebench checkout when it is there (has hosting/), else None."""
    p = gamebench_path(env)
    return p if p and (p / "hosting").is_dir() else None


def pool_path(env=None):
    """The lab broker's pool.yaml as configured: $GAMEANYTHING_LAB_POOL, $M2W_LAB_POOL, or settings.yaml `lab_pool`; None when none is."""
    env = os.environ if env is None else env
    v = env.get("GAMEANYTHING_LAB_POOL") or env.get("M2W_LAB_POOL") or projects.settings().get("lab_pool")
    return Path(v).expanduser() if v else None


def lab_kit(env=None, backend_=None) -> bool:
    """A gamebench lab is set up for this backend: docker-rt = the launch scripts hosting/launch_rt; plain Docker = the seat driver
    hosting/lab/seat.py and a lab config file (labdocker.config(): `gameanything lab setup` writes ~/.config/m2w/lab.env)."""
    g = gamebench(env); b = backend_ or backend(env)
    if not (g and b): return False
    if b == "docker":
        from . import labdocker
        return (g / "hosting" / "lab" / "seat.py").is_file() and labdocker.config(env)[1] is not None
    return (g / "hosting" / LAUNCH[b]).is_dir()


def own_sandbox(env=None, backend_=None, sys_=None) -> bool:
    """The user's own sandbox (labsandbox.py) is the lab here: Linux, a local Docker engine (not docker-rt), a docker client, and no
    gamebench lab set up (lab_kit). Docker answering is checked separately (docker_ok)."""
    if (sys_ or osdirs.system()) != "linux": return False
    b = backend_ or backend(env)
    return b == "docker" and bool(docker_bin(env)) and not lab_kit(env, b)


def own_sandbox_games() -> set:
    from . import sandbox
    return {g for g in sandbox.IMAGES if sandbox.facts(g)["offered"] and registry.lab_supported(g)}


def docker_ok(env=None) -> bool:
    """The docker client exists and its daemon answers (DOCKER_HOST / the docker context are respected: the client reads them)."""
    d = docker_bin(env)
    if not d: return False
    try: return subprocess.run([d, "version", "--format", "{{.Server.Version}}"], capture_output=True, timeout=6,
                               env=dict(os.environ if env is None else env)).returncode == 0
    except (OSError, subprocess.SubprocessError): return False


def pool(path=None, env=None):
    """The lab broker's pool (gamebench hosting/broker.py), or None when there is none (other installs: no seat broker). Without a
    configured pool file (pool_path): the local pool of a plain-Docker lab config (labdocker.local_pool()), if any."""
    env = os.environ if env is None else env
    p = path or pool_path(env)
    if not p:
        from . import labdocker
        p = labdocker.local_pool(env)
    if not p: return None
    p = Path(p)
    try: d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError, UnicodeDecodeError): return None
    return d if isinstance(d, dict) else None


def lab_scripts(env=None, backend_=None) -> set:
    """The games the lab can start on this backend: docker-rt = the games with a launch script hosting/launch_rt/<x>.sh (without a broker
    pool these are the only games the lab is offered for: better no choice than one that fails at the first build); plain Docker =
    labdocker.ready_games() (driver, game folder and image ready on this machine)."""
    g = gamebench(env); b = backend_ or backend(env)
    if not (g and b): return set()
    if b == "docker":
        from . import labdocker
        return labdocker.ready_games(env)
    inv = {v: k for k, v in SCRIPT.items()}
    return {inv.get(f.stem, f.stem) for f in (g / "hosting" / LAUNCH[b]).glob("*.sh")}


def steam_game(game: str, pool_=None) -> bool:
    g = ((pool_ or {}).get("games") or {}).get(POOL_NAME.get(game, game)) or {}
    return game in STEAM or bool(isinstance(g, dict) and g.get("steam"))


def lab_runs(game: str, pool_, scripts=None) -> bool:
    """Some sandbox of the pool can run the game (the broker's rule: Steam games on a Steam sandbox, the others on a lab sandbox that lists
    them, with a GPU when the game needs one). No pool: only the games with a launch script for this backend (lab_scripts()). A game whose
    game.yaml says `lab: {supported: false}` has no lab driver: never."""
    if not registry.lab_supported(game): return False
    if pool_ is None: return game in (scripts or ())
    name = POOL_NAME.get(game, game); g = (pool_.get("games") or {}).get(name)
    if not isinstance(g, dict): return False
    for sb in (pool_.get("sandboxes") or {}).values():
        if not isinstance(sb, dict): continue
        if g.get("steam"):
            if sb.get("kind") == "steam": return True
        elif sb.get("kind") == "lab" and name in (sb.get("games") or []) and (sb.get("gpu") or not g.get("gpu")): return True
    return False


def headless(env=None, sys_=None) -> bool:
    """Linux without a display: a server nobody plays on."""
    env = os.environ if env is None else env
    return (sys_ or osdirs.system()) == "linux" and not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


def machine(env=None, sys_=None, docker=None, pool_=False, kit=None) -> dict:
    """{system, backend, kit, docker, pool, scripts, headless, own}: what options() needs, looked up once (docker answers within 6 s).
    kit: a gamebench lab is set up for this backend, or (own) the user's own sandbox stands in for it; docker: its engine answers.
    Only looked up on Linux."""
    sys_ = sys_ or osdirs.system(); lin = sys_ == "linux"
    b = backend(env) if lin else None
    own = kit is None and lin and own_sandbox(env, b, sys_)
    kit = (lin and (lab_kit(env, b) or own)) if kit is None else bool(kit)
    pl = (None if own else pool(env=env) if lin else None) if pool_ is False else pool_
    scripts = own_sandbox_games() if own else lab_scripts(env, b) if kit else set()
    if b == "docker" and pl is not None:     # plain Docker: the local pool's seats count only for games that are ready here
        scripts = {g for g in scripts if lab_runs(g, pl)}; pl = None
    return {"system": sys_, "backend": b, "kit": kit, "docker": (kit and docker_ok(env)) if docker is None else bool(docker),
            "pool": pl, "scripts": scripts, "headless": headless(env, sys_), "own": bool(own),
            "docker_client": bool(lin and docker_bin(env))}


# ---------------------------------------------------------------- the choice for one game
def _opt(mode, ok, why_key=None, note_key=None, **vars):
    return {"mode": mode, "name": NAME[mode], "ok": ok, "why": GREY[why_key] if why_key else "", "note": NOTE[note_key] if note_key else "", "vars": vars}


def options(game: str, m: dict, native_info=None, hub=False, prefer=None) -> dict:
    """-> {game, recommended: lab|native|None, why, vars, options: [native, lab]}. m: machine(); native_info: the adapter's info()
    (None: no native adapter for this game); prefer: "play" (she wants to play it herself) | "hands_off" (long runs, unattended) | None."""
    s = m["system"]; sv = {"s": SYS_NAME.get(s, s)}
    has_native = native_info is not None; installed = bool(has_native and native_info.get("installed"))
    if s != "linux": lab = _opt("lab", False, "lab_os", **sv)
    elif not m.get("kit", True):           # no gamebench lab and no own sandbox: on Linux that is a missing Docker Engine
        lab = _opt("lab", False, "lab_no_docker" if m.get("backend") is None or not m.get("docker_client", True) else "lab_kit")
    elif not m["docker"]: lab = _opt("lab", False, "lab_docker")
    elif not lab_runs(game, m.get("pool"), m.get("scripts")): lab = _opt("lab", False, "lab_game" if m.get("pool") is not None else "lab_script")
    else: lab = _opt("lab", True, note_key="lab_steam" if steam_game(game, m.get("pool")) else "lab")
    nat = _opt("native", True, note_key="native" if installed else "native_missing") if has_native else _opt("native", False, "no_adapter")
    if lab["ok"] and nat["ok"]:
        why = ("hub" if hub else "headless" if m.get("headless") else "not_installed" if not installed else
               "hands_off" if prefer == "hands_off" else "play")
        rec = "native" if why == "play" else "lab"
    elif nat["ok"]: rec, why = "native", ("not_linux" if s != "linux" else "no_docker" if not (m.get("kit", True) and m["docker"]) else "lab_cant")
    elif lab["ok"]: rec, why = "lab", "no_adapter"
    else: rec, why = None, "none"
    return {"game": game, "recommended": rec, "why": WHY[why], "vars": sv, "options": [nat, lab]}


def all_options(m=None, doctor=None, hub=False, prefer=None) -> dict:
    """{game id: options()} for every game of projects.GAMES; new native adapters (native.GAMES) show up by themselves."""
    from . import native
    m = m or machine()
    d = doctor or native.doctor()
    info = {g["game"]: g for g in d["games"]}
    return {gid: options(gid, m, info.get(gid), hub, prefer) for gid in projects.GAMES}


# ---------------------------------------------------------------- the project's setting
def mode_of(root) -> str:
    v = projects.config_of(root).get("build_mode"); return v if v in MODES else None


def auto_mode(sys_=None, env=None) -> str:
    """Projects without build_mode: lab only where the lab is really usable — Linux with a docker client, a docker engine (backend())
    and a gamebench kit for it (lab_kit(): this server's docker-rt + gamebench); else native (e.g. a CI runner: docker but no gamebench)."""
    if (sys_ or osdirs.system()) != "linux" or not docker_bin(env): return "native"
    return "lab" if lab_kit(env) else "native"


def effective(root, sys_=None, env=None):
    m = mode_of(root) if root else None
    return (m, "project") if m else (auto_mode(sys_, env), "auto")


def _write_mode(root: Path, mode: str):
    f = Path(root) / layout.CONFIG / "project.yaml"; t = f.read_text(encoding="utf-8") if f.exists() else ""
    line = f"build_mode: {mode}"
    if re.search(r"(?m)^build_mode:.*$", t): t = re.sub(r"(?m)^build_mode:.*$", line, t, count=1)
    else: t = (t.rstrip("\n") + "\n" if t else "") + line + "\n"
    f.parent.mkdir(parents=True, exist_ok=True); f.write_text(t, encoding="utf-8")


def set_mode(ref, mode: str) -> dict:
    """Change where a project's builds run (any time; a build that already runs keeps going where it is). -> the project entry."""
    if mode not in MODES: raise ValueError("构建位置应该是 lab 或 native")
    e = projects.find(ref); _write_mode(Path(e["path"]), mode); return e


def migrate(mode: str = "lab", dry_run=False) -> list:
    """Write `build_mode: <mode>` into every registered project that has none (opt-in; nothing does this by itself). -> [(id, path)]."""
    if mode not in MODES: raise ValueError("构建位置应该是 lab 或 native")
    out = []
    for e in projects.load():
        root = Path(e["path"])
        if not (root / layout.CONFIG / "project.yaml").is_file() or mode_of(root): continue
        if not dry_run: _write_mode(root, mode)
        out.append((e["id"], str(root)))
    return out
