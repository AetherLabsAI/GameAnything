"""galab: what the GameAnything sandbox tools (ga-ksp, ga-mc, ga-sts in lab/images/<game>/) share. Stdlib only.

The images have NO game files. The user's own game folder is mounted READ-ONLY at /game (and their saves at /saves when the game keeps
them elsewhere); everything the sandbox writes goes to the writable volume /sandbox, so the user's folders are never changed.

A game tool subclasses Lab and fills in: game_build() (which build is mounted), make_layer() (the sandbox's own copy in /sandbox/game),
game_argv() / game_env() / game_cwd() (how to start it), ready() (the game is up: a log line and a window) and the logs. Lab gives it the
common commands:

    doctor [--json]       what is mounted (game build, read-only or not), the layer, the display (Xorg on the GPU / Xvfb), the game
    layer [--force]       the sandbox's own copy of the game (the game tool's make_layer)
    up                    the screen (Xorg on an NVIDIA GPU when the sandbox has one, else Xvfb), x11vnc, the noVNC viewer on 6080, a silent sound card
    run [--timeout S]     start the game in the background and wait until it is up
    shot FILE             a PNG of the screen
    rec start|stop        record the screen to /sandbox/rec/<time>.mkv (MJPEG: cheap here; encode the final video on the host)
    log [-n N]            the end of the game's log
    stop / down           stop the game (and a recording); down also stops the screen and the viewer

Every process is started in its own session with a pid file and stopped by that exact pid (its process group).
"""
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

GAME = Path(os.environ.get("GA_GAME", "/game"))
SAVES_IN = Path(os.environ.get("GA_SAVES", "/saves"))
SANDBOX = Path(os.environ.get("GA_SANDBOX", "/sandbox"))
LAYER = SANDBOX / "game"
LOGS = SANDBOX / "logs"
RUN = SANDBOX / "run"
VENDOR = Path(os.environ.get("GA_VENDOR", "/opt/gameanything/vendor"))
DISPLAY = os.environ.get("DISPLAY", ":99")
SCREEN = os.environ.get("SCREEN", "1280x720x24")
VIEWER_PORT = int(os.environ.get("NOVNC_PORT", "6080"))
VNC_PORT = int(os.environ.get("VNC_PORT", "5900"))
VIEWER_BIND = os.environ.get("VIEWER_BIND", "0.0.0.0")
X_SERVER = os.environ.get("GA_X", "auto")                 # auto (Xorg when an NVIDIA GPU is there) | xorg | xvfb
NVIDIA_XORG = Path("/usr/lib/x86_64-linux-gnu/nvidia/xorg")
XORG_CONF = """Section "ServerFlags"
    Option "AutoAddDevices" "false"
    Option "AutoEnableDevices" "false"
    Option "AutoAddGPU" "false"
    Option "DontVTSwitch" "true"
EndSection
Section "Files"
    ModulePath "{nvidia}"
    ModulePath "/usr/lib/xorg/modules"
EndSection
Section "Device"
    Identifier "gpu0"
    Driver     "nvidia"
    BusID      "{busid}"
    Option     "AllowEmptyInitialConfiguration" "True"
    Option     "ProbeAllGpus" "False"
    Option     "ConnectedMonitor" "DFP-0"
EndSection
Section "Screen"
    Identifier   "screen0"
    Device       "gpu0"
    DefaultDepth 24
    Option       "AllowEmptyInitialConfiguration" "True"
    SubSection "Display"
        Depth   24
        Virtual {w} {h}
    EndSubSection
EndSection
Section "ServerLayout"
    Identifier "layout0"
    Screen     0 "screen0"
EndSection
"""


def x86(argv):
    """argv under FEX-Emu when this image has it (arm64, Apple silicon: lab/images/common/install-steam-fex.sh), else argv as it is.
    The games are x86 programs; GameAnything and the mod builds stay native."""
    if not shutil.which("ga-x86"): return list(argv)
    return ["ga-x86", "/bin/bash" if argv[0] == "bash" else argv[0], *argv[1:]]



def known_in_log(tool, text):
    """The words of a KNOWN situation (gameanything/hiccups.py) that the game log shows, in the user's language, or None. Only when the
    image has GameAnything (it always has, in its venv; a bare checkout of this file without it: no check)."""
    flow = {"ga-mc": "minecraft"}.get(tool)
    if not flow or not text: return None
    try:
        from gameanything import watchdog
    except Exception: return None
    hits = watchdog.known_in_log(flow, "launch", {"mc_game": text})
    lang = os.environ.get("GAMEANYTHING_LANG", "en")
    return watchdog.say_of(hits[0], lang, {})[lang if lang in ("zh", "en") else "en"] if hits else None


def size():
    w, h = SCREEN.split("x")[:2]
    return int(w), int(h)


def fit_output(w, h, run=None):
    """Xorg on the GPU: the virtual output's preferred mode is SMALLER than the screen (1024x576 on an L40S for a 1280x720 screen), so
    the game drew 1280x720 but the pointer stayed inside 1024x576: clicks on the lower part never arrived (Valheim E2E and Civ VI's
    2K agreement, plain-Docker test 2026-10-30). Set the output's mode to the screen; a size the driver does not list (1600x900) is
    added from `gtf`. -> the mode set, or None."""
    run = run or (lambda argv: subprocess.run(argv, capture_output=True, text=True, env={**os.environ, "DISPLAY": DISPLAY}))
    r = run(["xrandr"]); out = r.stdout if r.returncode == 0 else ""
    m = re.search(r"^(\S+) connected", out, re.M)
    if not m: return None
    o, mode = m.group(1), f"{w}x{h}"
    if not re.search(rf"^\s+{mode}\s", out, re.M):
        g = run(["gtf", str(w), str(h), "60"])
        ml = re.search(r'Modeline\s+"([^"]+)"\s+(.+)', g.stdout if g.returncode == 0 else "")
        if not ml: return None
        mode = ml.group(1)
        run(["xrandr", "--newmode", mode, *ml.group(2).split()]); run(["xrandr", "--addmode", o, mode])
    return mode if run(["xrandr", "--output", o, "--mode", mode]).returncode == 0 else None


PULSE_DIR = Path("/tmp/ga-xdg")          # XDG_RUNTIME_DIR of the sandbox's PulseAudio (its socket: pulse/native)
PULSE_ARGV = ["pulseaudio", "-n", "--daemonize=no", "--exit-idle-time=-1", "--load=module-null-sink sink_name=rec",
              "--load=module-native-protocol-unix auth-anonymous=1", "--load=module-always-sink"]
# ^ the games play into the null sink `rec` (PULSE_SINK=rec); the recorder reads its monitor. auth-anonymous: the socket's folder is the
#   player's own 0700 /tmp/ga-xdg, and a `docker exec` with another HOME has no matching cookie (ffmpeg then got no sound)


def rec_argv(out, fps, wh, audio=True):
    """ffmpeg for `rec start`: the screen (x11grab, MJPEG) AND the game's sound (the `rec` sink's monitor, PCM) into one .mkv.
    Without the pulse input the recording had no audio track at all (Valheim E2E, sandbox-hiccups.md #47). audio=False: video only."""
    a = ["ffmpeg", "-loglevel", "error", "-y", "-thread_queue_size", "512", "-f", "x11grab", "-framerate", str(fps), "-video_size", "%dx%d" % tuple(wh),
         "-i", DISPLAY]
    if audio: a += ["-thread_queue_size", "512", "-f", "pulse", "-i", "rec.monitor"]
    return a + ["-c:v", "mjpeg", "-q:v", "4"] + (["-c:a", "pcm_s16le"] if audio else []) + [str(out)]


def pulse_up() -> bool:
    return (PULSE_DIR / "pulse" / "native").exists()


def busid(nvidia_smi_line: str) -> str:
    """'00000000:87:00.0' (nvidia-smi, hex) -> 'PCI:135:0:0' (xorg.conf, decimal)."""
    m = re.match(r"^(?:[0-9A-Fa-f]+:)?([0-9A-Fa-f]+):([0-9A-Fa-f]+)\.([0-9A-Fa-f]+)$", nvidia_smi_line.strip())
    if not m: raise ValueError(f"not a PCI bus id: {nvidia_smi_line!r}")
    return "PCI:%d:%d:%d" % tuple(int(x, 16) for x in m.groups())


def gpu_bus():
    """The first NVIDIA GPU's bus id, or None (no GPU in this sandbox, or its X driver was not passed in)."""
    if not shutil.which("nvidia-smi") or not (NVIDIA_XORG / "nvidia_drv.so").is_file(): return None
    r = subprocess.run(["nvidia-smi", "--query-gpu=pci.bus_id", "--format=csv,noheader"], capture_output=True, text=True)
    line = r.stdout.strip().splitlines()[0] if r.returncode == 0 and r.stdout.strip() else ""
    try: return busid(line)
    except ValueError: return None


def windows_in_tree(tree: str, pattern: str) -> list:
    """The ids of the windows whose name matches pattern in `xwininfo -root -tree` output (one per line: 0x.. "name": ...)."""
    out = []
    for l in tree.splitlines():
        m = re.match(r'^\s*(0x[0-9a-fA-F]+) "(.*)":', l)
        if m and re.search(pattern, m.group(2)): out.append(str(int(m.group(1), 16)))
    return out


def ensure_account(passwd: Path = Path("/etc/passwd"), group: Path = Path("/etc/group"), uid=None, gid=None, home=None) -> bool:
    """A pulled image run with --user <uid> (sandbox.run_user_args) has no /etc/passwd line for that uid: getpwuid() fails and Civ VI
    (Aspyr: its user folder comes from the account's home) dies with a segfault (plain Docker test, 2026-10-30). The base layer leaves
    /etc/passwd and /etc/group writable inside the container; add the missing lines (home = $HOME). True when a line was added."""
    uid = os.getuid() if uid is None else uid; gid = os.getgid() if gid is None else gid
    home = home or os.environ.get("HOME") or "/sandbox/home"
    added = False
    for f, line, key in ((passwd, f"player{uid}:x:{uid}:{gid}::{home}:/bin/bash\n", uid), (group, f"player{gid}:x:{gid}:\n", gid)):
        try:
            rows = f.read_text().splitlines()
            if any(r.split(":")[2:3] == [str(key)] for r in rows): continue
            with open(f, "a") as fh: fh.write(line)
            added = True
        except OSError: pass                 # not writable (an older image): the games that do not ask still run
    return added


def pids_by_comm(name: str, proc: Path = Path("/proc")) -> list:
    """Pids whose process name (/proc/N/comm, 15 characters at most) is name: a game that re-starts itself under another parent."""
    out = []
    for d in proc.iterdir() if proc.is_dir() else ():
        if not d.name.isdigit(): continue
        try:
            if (d / "comm").read_text().strip() == name[:15]: out.append(int(d.name))
        except OSError: continue
    return sorted(out)


def stray_game_pids(layer: Path, proc: Path = Path("/proc")) -> list:
    """Pids whose executable lies in the sandbox's game layer: only this sandbox's own copy of the game runs from there."""
    out, root = [], str(Path(layer).resolve())
    for d in proc.iterdir() if proc.is_dir() else ():
        if not d.name.isdigit() or int(d.name) == os.getpid(): continue
        try: exe = os.readlink(d / "exe")
        except OSError: continue
        if exe == root or exe.startswith(root + "/"): out.append(int(d.name))
    return sorted(out)


def read_only(d: Path) -> bool:
    """True when nothing can be created in d (the mount is :ro). Never leaves a file behind."""
    t = d / f".ga-ro-test-{os.getpid()}"
    try: fd = os.open(t, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError: return True
    os.close(fd); t.unlink(); return False


def writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True); t = d / f".ga-write-test-{os.getpid()}"; t.write_text("x"); t.unlink(); return True
    except OSError: return False


def copy_entries(src: Path, dst: Path, link=(), skip=lambda name: False, rename=None):
    """dst/<name> for every entry of src: a symlink into src for the names in `link` (big and read-only), a copy otherwise
    (symlinks kept as links), nothing for skip(name). -> (copied, linked)."""
    dst.mkdir(parents=True, exist_ok=True); copied = linked = 0
    for e in sorted(os.scandir(src), key=lambda e: e.name):
        n = e.name
        if skip(n) or n.startswith(".ga-"): continue
        s = Path(e.path); d = dst / ((rename or {}).get(n, n))
        if n in link: os.symlink(s, d); linked += 1; continue
        if e.is_dir(follow_symlinks=False): shutil.copytree(s, d, symlinks=True)
        else: shutil.copy2(s, d, follow_symlinks=False)
        copied += 1
    return copied, linked


def steam_running() -> bool:
    """A Steam client of this sandbox is running (its ubuntu12_32/steam binary). Games that call SteamAPI (Terraria / tModLoader,
    Valheim, Overcooked! 2, Cities: Skylines, Civilization VI) need it: `ga-steam start` (and log in once) first."""
    for d in os.listdir("/proc"):
        if not d.isdigit(): continue
        try: e = os.readlink(f"/proc/{d}/exe")
        except OSError: continue
        if e.endswith("/ubuntu12_32/steam"): return True
    return False


def bepinex_install(layer: Path, exe: str, vendor: Path = None) -> str:
    """The image's pinned BepInEx 5 (vendor BepInEx_linux_x64_*.zip, LGPL-2.1) unpacked into the layer, its run_bepinex.sh set to the
    game's executable. -> the BepInEx version. The user's own BepInEx and plugins are never copied (the layer starts clean)."""
    import zipfile
    zips = sorted((vendor or VENDOR).glob("BepInEx_linux_x64_*.zip"))
    if not zips: raise FileNotFoundError(f"no BepInEx_linux_x64_*.zip in {vendor or VENDOR}")
    with zipfile.ZipFile(zips[-1]) as z: z.extractall(layer)
    run = layer / "run_bepinex.sh"
    run.write_text(re.sub(r'^executable_name=".*"$', f'executable_name="{exe}"', run.read_text(), count=1, flags=re.M))
    run.chmod(0o755)
    (layer / "BepInEx" / "plugins").mkdir(parents=True, exist_ok=True)
    return zips[-1].stem.rsplit("_", 1)[-1]


def container_started():
    """When this container (its PID 1) started, in epoch seconds; 0 when unknown. A pid file older than that is from before a
    `docker stop` / `docker start` (or another container on the same volume): its pid number now belongs to some other process."""
    try:
        ticks = int(Path("/proc/1/stat").read_text().rsplit(")", 1)[1].split()[19])
        btime = int(next(l.split()[1] for l in Path("/proc/stat").read_text().splitlines() if l.startswith("btime ")))
        return btime + ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration): return 0


class Lab:
    name = "game"                     # the tool's name in messages (ga-ksp, ...)
    title = "the game"
    window = None                     # xdotool --name regex of the game window
    relaunch_name = None              # the game's process name when it re-starts itself (The Sims 4 via the EA App): followed by name
    mount_hint = "mount your game folder: -v <folder>:/game:ro"

    # ------------------------------------------------------------ to fill in
    def game_build(self) -> str: return "none"          # linux | windows | mac | java | none
    def build_hints(self) -> dict: return {}
    def make_layer(self) -> dict: raise NotImplementedError
    def layer_ok(self) -> bool: return (LAYER / ".ga-layer.json").is_file()
    def game_argv(self) -> list: raise NotImplementedError
    def game_env(self) -> dict: return {}
    def game_cwd(self) -> Path: return LAYER
    def log_file(self) -> Path: return LOGS / "game.log"
    def ready(self, text: str) -> bool: return True     # text = the game log so far; the window is checked as well
    def doctor_extra(self) -> dict: return {}
    def interesting(self, line: str) -> bool: return False

    # ------------------------------------------------------------ helpers
    def say(self, *a): print(f"[{self.name}]", *a, flush=True)

    def die(self, msg, code=1):
        print(f"[{self.name}] {msg}", file=sys.stderr, flush=True); sys.exit(code)

    @staticmethod
    def pid_alive(name):
        """The pid of our process `name` while it runs (a zombie counts as gone: docker exec'd children are not always reaped)."""
        try: pid = int((RUN / f"{name}.pid").read_text())
        except (OSError, ValueError): return None
        try:
            if (RUN / f"{name}.pid").stat().st_mtime < container_started() - 1: return None    # from before a restart (see container_started)
        except OSError: return None
        try: st = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except (OSError, IndexError): return None
        return None if st in ("Z", "X") else pid

    def start(self, name, argv, log, env=None, cwd=None):
        RUN.mkdir(parents=True, exist_ok=True); LOGS.mkdir(parents=True, exist_ok=True)
        if self.pid_alive(name): return self.pid_alive(name)
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=open(LOGS / log, "ab"), stderr=subprocess.STDOUT, start_new_session=True,
                             env={**os.environ, **(env or {})}, cwd=cwd)
        (RUN / f"{name}.pid").write_text(str(p.pid))
        return p.pid

    def stop_pid(self, name, sig=signal.SIGTERM, wait=10):
        pid = self.pid_alive(name)
        if pid:
            try: os.killpg(pid, sig)          # its own session (start_new_session): the group is exactly what we started
            except OSError:
                try: os.kill(pid, sig)
                except OSError: pass
            for _ in range(wait * 4):
                if not self.pid_alive(name): break
                time.sleep(0.25)
            if self.pid_alive(name):
                try: os.killpg(pid, signal.SIGKILL)
                except OSError: pass
        (RUN / f"{name}.pid").unlink(missing_ok=True)
        return pid

    @staticmethod
    def x_up():
        return subprocess.run(["xdpyinfo", "-display", DISPLAY], capture_output=True).returncode == 0

    def windows(self):
        if not self.window: return []
        env = {**os.environ, "DISPLAY": DISPLAY}
        r = subprocess.run(["xdotool", "search", "--name", self.window], capture_output=True, text=True, env=env)
        if r.stdout.split(): return r.stdout.split()
        # xdotool finds no window of some games (Minecraft 26.x, seen 2026-10-29): the X server's own window tree does
        t = subprocess.run(["xwininfo", "-root", "-tree"], capture_output=True, text=True, env=env).stdout
        return windows_in_tree(t, self.window)

    # ------------------------------------------------------------ commands
    def cmd_doctor(self, a):
        b = self.game_build()
        d = {"game": str(GAME), "game_build": b, "game_read_only": read_only(GAME) if GAME.is_dir() else None,
             "saves_mounted": SAVES_IN.is_dir() and any(SAVES_IN.iterdir()), "saves_read_only": read_only(SAVES_IN) if SAVES_IN.is_dir() and any(SAVES_IN.iterdir()) else None,
             "sandbox": str(SANDBOX), "sandbox_writable": writable(SANDBOX), "layer": self.layer_ok(),
             "display": bool(self.pid_alive("x")), "x_server": (RUN / "x.kind").read_text() if (RUN / "x.kind").exists() else None,
             "gpu": gpu_bus(), "viewer": bool(self.pid_alive("websockify")), "game_running": bool(self.pid_alive("game")), **self.doctor_extra()}
        owners = {p.stat().st_uid for p in (GAME, SAVES_IN) if p.is_dir() and any(p.iterdir())}
        if owners - {os.getuid(), 0}:              # her files can be private (a world's level.dat is 0600): the player must be their owner
            d["owner_uid"] = sorted(owners)
            d["uid_hint"] = (f"the mounted folders belong to uid {', '.join(map(str, sorted(owners)))}, the game runs as uid {os.getuid()}: "
                             f"rebuild it with `gameanything lab setup --image <game>` (it passes your uid: PLAYER_UID) or start it with "
                             f"--user $(id -u):$(id -g), so the game can read private files")
        h = {"none": self.mount_hint, **self.build_hints()}
        if b in h: d["hint"] = h[b]
        if a.json: print(json.dumps(d, indent=1)); return 0
        for k, v in d.items(): print(f"{k:18} {v}")
        return 0

    def cmd_layer(self, a):
        b = self.game_build()
        if b in ("none", "windows", "mac"):
            self.die(f"{GAME}: {b} build; " + {"none": self.mount_hint, **self.build_hints()}.get(b, ""), 3)
        if not writable(SANDBOX): self.die(f"{SANDBOX} is not writable: mount a volume there (-v ga-{self.name}:/sandbox)", 3)
        if self.layer_ok() and not a.force: self.say(f"layer {LAYER} already there (--force: build it again)"); return 0
        if self.pid_alive("game"): self.die(f"the game is running: {self.name} stop first")
        shutil.rmtree(LAYER, ignore_errors=True)
        t0 = time.time()
        info = self.make_layer()
        info = {"from": str(GAME), "made": time.strftime("%FT%TZ", time.gmtime()), **info, "seconds": round(time.time() - t0, 1)}
        LAYER.mkdir(parents=True, exist_ok=True)
        (LAYER / ".ga-layer.json").write_text(json.dumps(info, indent=1))
        self.say(f"layer {LAYER}: " + ", ".join(f"{k} {v}" for k, v in info.items() if k not in ("from", "made")))
        return 0

    def cmd_up(self, a=None):
        n = DISPLAY.lstrip(":")
        lock = Path(f"/tmp/.X{n}-lock")
        if not self.pid_alive("x") and lock.exists():
            lock.unlink(missing_ok=True); Path(f"/tmp/.X11-unix/X{n}").unlink(missing_ok=True)
        if not self.pid_alive("x"):
            bus = gpu_bus() if X_SERVER in ("auto", "xorg") else None
            if X_SERVER == "xorg" and not bus: self.die("GA_X=xorg but no NVIDIA GPU / X driver here (docker run --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all)")
            if bus:
                w, h = size(); RUN.mkdir(parents=True, exist_ok=True)
                conf = RUN / "xorg.conf"; conf.write_text(XORG_CONF.format(nvidia=NVIDIA_XORG, busid=bus, w=w, h=h))
                self.start("x", ["Xorg", DISPLAY, "-config", str(conf), "-noreset", "-novtswitch", "-sharevts", "-nolisten", "tcp", "-ac",
                                 "+extension", "GLX", "+extension", "RANDR", "+extension", "RENDER", "-logfile", str(LOGS / "xorg.log")], "xorg.out")
                (RUN / "x.kind").write_text(f"xorg (NVIDIA GPU {bus})")
            else:
                self.start("x", ["Xvfb", DISPLAY, "-screen", "0", SCREEN, "-nolisten", "tcp"], "xvfb.log")
                (RUN / "x.kind").write_text("xvfb (software OpenGL)")
        for _ in range(60):
            if self.x_up(): break
            time.sleep(0.5)
        else: self.die(f"no X display {DISPLAY}; see {LOGS}/xorg.log or xvfb.log")
        if (RUN / "x.kind").read_text().startswith("xorg"): fit_output(*size())      # the pointer reaches the whole screen
        self.start("x11vnc", ["x11vnc", "-display", DISPLAY, "-rfbport", str(VNC_PORT), "-localhost", "-forever", "-shared", "-nopw", "-noxdamage", "-quiet"], "x11vnc.log")
        self.start("websockify", ["websockify", "--web", "/usr/share/novnc", f"{VIEWER_BIND}:{VIEWER_PORT}", f"127.0.0.1:{VNC_PORT}"], "viewer.log")
        if shutil.which("pulseaudio") and not self.pid_alive("pulse"):        # a silent sound card: the game and the recorder find one
            os.makedirs(PULSE_DIR, mode=0o700, exist_ok=True)
            self.start("pulse", PULSE_ARGV, "pulse.log", env={"XDG_RUNTIME_DIR": str(PULSE_DIR)})
        self.say(f"display {DISPLAY} ({SCREEN}, {(RUN / 'x.kind').read_text()}); viewer http://<this sandbox>:{VIEWER_PORT}/vnc.html")
        return 0

    def cmd_run(self, a):
        if not self.layer_ok(): self.die(f"no layer yet: {self.name} layer")
        if self.pid_alive("game"): self.say("the game is already running"); return 0
        if not self.x_up(): self.cmd_up()
        log = self.log_file(); log.parent.mkdir(parents=True, exist_ok=True)
        if log.exists(): log.unlink()
        env = {"DISPLAY": DISPLAY, "XDG_RUNTIME_DIR": str(PULSE_DIR), "PULSE_SINK": "rec", **self.game_env()}
        self.start("game", x86(self.game_argv()), "game.out", env=env, cwd=str(self.game_cwd()))
        self.say(f"starting {self.title} ...")
        t0 = last_say = time.time()
        while time.time() - t0 < a.timeout:
            t = log.read_text(errors="replace") if log.exists() else ""
            known = known_in_log(self.name, t)
            if known:                         # a known situation the log alone shows (the watchdog's table): say it, do not wait blindly
                self.say(known); return 4
            if time.time() - last_say >= 60: self.say(f"still starting {self.title} ({round(time.time() - t0)} s)"); last_say = time.time()
            win = self.windows()
            if self.ready(t) and (win or not self.window):
                for w in win: subprocess.run(["xdotool", "windowmove", w, "0", "0"], capture_output=True, env={**os.environ, "DISPLAY": DISPLAY})
                break
            if not self.pid_alive("game") and self.relaunch_name:
                for _ in range(60):          # `wine TS4_x64.exe` exits (170) and the EA App starts the game again (2026-10-30)
                    p = pids_by_comm(self.relaunch_name)
                    if p: (RUN / "game.pid").write_text(str(p[0])); break
                    time.sleep(1)
            if not self.pid_alive("game"):
                print((t or (LOGS / "game.out").read_text(errors="replace"))[-3000:])
                self.die(f"the game exited; logs {log}, {LOGS / 'game.out'}")
            time.sleep(1)
        else: self.die(f"not up after {a.timeout} s; see {log} and {LOGS / 'game.out'}")
        t = log.read_text(errors="replace") if log.exists() else ""
        for l in t.splitlines():
            if self.interesting(l): print("  " + l[:220])
        self.say(f"game is up ({round(time.time() - t0)} s)")
        return 0

    def cmd_shot(self, a):
        out = Path(a.file); out.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-video_size", "%dx%d" % size(), "-i", DISPLAY,
                            "-frames:v", "1", str(out)], capture_output=True, text=True)
        if r.returncode != 0: self.die(f"screenshot failed: {r.stderr[-300:]}")
        self.say(f"screenshot {out}"); return 0

    def cmd_rec(self, a):
        d = SANDBOX / "rec"; d.mkdir(parents=True, exist_ok=True)
        if a.what == "start":
            if self.pid_alive("rec"): self.say("already recording"); return 0
            f = d / time.strftime("%Y%m%d-%H%M%S.mkv")
            audio = pulse_up()
            self.start("rec", rec_argv(f, a.fps, size(), audio), "rec.log", env={"XDG_RUNTIME_DIR": str(PULSE_DIR)})
            (RUN / "rec.file").write_text(str(f))
            self.say(f"recording {f}" + ("" if audio else " (no sound: PulseAudio is not running in this sandbox; `up` starts it)"))
        else:
            f = (RUN / "rec.file").read_text() if (RUN / "rec.file").exists() else "?"
            self.stop_pid("rec", signal.SIGINT)
            self.say(f"stopped: {f} (encode it on the host, e.g. ffmpeg -i <it> -c:v libx264 -crf 23 -pix_fmt yuv420p out.mp4)")
        return 0

    def cmd_log(self, a):
        p = self.log_file()
        if not p.exists(): self.die("no game log yet")
        print("\n".join(p.read_text(errors="replace").splitlines()[-a.n:])); return 0

    def cmd_stop(self, a):
        self.stop_pid("rec", signal.SIGINT)
        pid = self.stop_pid("game", wait=20)
        for p in stray_game_pids(LAYER):     # a game process in another group (Cities, 2026-10-30: it held the next start for 7 min)
            try: os.kill(p, signal.SIGKILL)
            except OSError: pass
        self.say(f"game stopped (pid {pid})" if pid else "the game was not running")
        if a.cmd == "down":
            for n in ("websockify", "x11vnc", "pulse", "x"): self.stop_pid(n)
            (RUN / "x.kind").unlink(missing_ok=True)
            self.say("screen and viewer stopped")
        return 0

    def parser(self, doc):
        ap = argparse.ArgumentParser(prog=self.name, description=doc.split("\n\n")[0])
        sub = ap.add_subparsers(dest="cmd", required=True)
        s = sub.add_parser("doctor"); s.add_argument("--json", action="store_true"); s.set_defaults(f=self.cmd_doctor)
        s = sub.add_parser("layer"); s.add_argument("--force", action="store_true"); s.set_defaults(f=self.cmd_layer)
        sub.add_parser("up").set_defaults(f=self.cmd_up)
        s = sub.add_parser("run"); s.add_argument("--timeout", type=int, default=420); s.set_defaults(f=self.cmd_run)
        s = sub.add_parser("shot"); s.add_argument("file"); s.set_defaults(f=self.cmd_shot)
        s = sub.add_parser("rec"); s.add_argument("what", choices=["start", "stop"]); s.add_argument("--fps", type=int, default=15); s.set_defaults(f=self.cmd_rec)
        s = sub.add_parser("log"); s.add_argument("-n", type=int, default=40); s.set_defaults(f=self.cmd_log)
        sub.add_parser("stop").set_defaults(f=self.cmd_stop); sub.add_parser("down").set_defaults(f=self.cmd_stop)
        return ap, sub

    def main(self, doc, argv=None):
        ap, _ = self.parser(doc)
        a = ap.parse_args(argv)
        ensure_account()
        return a.f(a)
