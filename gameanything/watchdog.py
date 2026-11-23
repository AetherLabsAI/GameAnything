"""The setup watchdog: no blind waits during an account login, a game download or a launch in a sandbox (2026-10-29). Stdlib only (the
sandbox tools import it inside the image).

Every wait loop calls `Watchdog.tick()` every few seconds. A tick:

  1. snapshots the sandbox FROM INSIDE (never from host-cached files: JuiceFS served stale copies, HICCUPS steam #4 / mcdl #5): the
     visible windows with their sizes, the processes (exe, state, argv), the relevant log tails, a few single values grepped from config
     files (never a whole config: Steam's config.vdf holds login tokens), the app manifests and folder sizes. One `python3 -c` exec
     (SNAPSHOT_PY), the same code in a docker exec from the host (DockerBox) and inside the sandbox (LocalBox);
  2. turns it into facts (facts()) and matches them against the table of KNOWN situations (hiccups.py);
  3. acts: a safe automatic action (ACTIONS: exact scripts, never a click on a licence), a line for the user in their language, or a
     stop with a question (`stop` in the result: the caller exits and asks);
  4. when the state has not changed for `stall_s` (~60 s): saves the snapshot (redacted) and a screenshot read through the exec (none
     while a sign-in window is open: what the user types is never captured), and when no known situation matches, tells the user
     what it sees with the screenshot path;
  5. never stays silent longer than `heartbeat_s` (~110 s): a progress line with the phase's normal duration (hiccups.PHASES).

Security: no snapshot contains a password, a token or a whole login file. microsoft.json (the refresh token), Steam's
config.vdf / loginusers.vdf / registry.vdf are never read (only a grep for one setting); every text is passed through redact()
before it is saved or printed.

    w = Watchdog(box, "steam", "install", lang="zh", say=print, ctx={"app": 413150, "install_requested_at": t}, evidence=Path(...))
    while True:
        r = w.tick()
        if r["stop"]: ...ask the user...; break
        if r["facts"].get("app_installed"): break
        time.sleep(5)
"""
import calendar
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import hiccups

STEAM_ROOT = "~/.steam/debian-installation"
NETWORK_FS = ("fuse", "fuse.juicefs", "juicefs", "nfs", "nfs4", "cifs", "smb3", "9p", "fuse.sshfs", "virtiofs", "fakeowner")
SECRET_FILES = re.compile(r"(microsoft\.json|config\.vdf|loginusers\.vdf|registry\.vdf|ssfn\w*|\.ssh|launcher_accounts\w*\.json|"
                          r"accounts?\.json)$", re.I)

# ---------------------------------------------------------------- what to read, per flow (paths inside the sandbox)
SPECS = {
    "steam": {"logs": {"bootstrap": "{root}/logs/bootstrap_log.txt", "steamui_login": "{root}/logs/steamui_login.txt",
                       "webhelper": "{root}/logs/webhelper.txt", "connection": "{root}/logs/connection_log.txt",
                       "content": "{root}/logs/content_log.txt", "steam_out": "/sandbox/logs/steam.log",
                       "console": "{root}/logs/console-linux.txt"},
              "greps": {"shader_bg": ["{root}/config/config.vdf", r'"EnableShaderBackgroundProcessing"\s+"(\d)"'],
                        "webhelper_shm_flag": ["{root}/ubuntu12_64/steamwebhelper_sniper_wrap.sh", r"--disable-dev-shm-usage"]},
              "shm": True,
              "exists": {"client": "{root}/ubuntu12_32/steam", "login_cache": "{root}/config/loginusers.vdf"},
              "fs_of": "{root}/steamapps"},
    "microsoft": {"logs": {"mc_login_log": "/sandbox/logs/mc-login.log"},
                  "jsons": {"mc_login": "/sandbox/account/LOGIN.json", "mc_result": "/sandbox/account/minecraft.json"},
                  "exists": {"mc_token": "/sandbox/account/microsoft.json"}},
    "minecraft": {"logs": {"mc_game": "/sandbox/game/logs/latest.log", "mc_download_log": "/sandbox/logs/mc-download.log"},
                  "jsons": {"mc_result": "/sandbox/account/minecraft.json"},
                  "dirs": {"mc_saves": "/sandbox/game/saves"}},
    # the EA App under Wine ({root} = GA_EA_HOME, default /sandbox/ea; the prefix is {root}/pfx). A "*" picks the newest match.
    # Never read: the EA App's cookies / tokens (AppData/Local/Electronic Arts/EA Desktop/*.ini, Cookies, the QtWebEngine profile).
    "ea": {"logs": {"ea_installer": "{root}/pfx/drive_c/users/*/AppData/Local/Temp/EA_app_*.log",
                    "ea_desktop": "{root}/pfx/drive_c/ProgramData/EA Desktop/Logs/EADesktop.log",
                    "ea_out": "{root}/logs/ea-app.log"},
           # whole-file greps (the last match): the app's own state machine and its sign-in page
           "greps": {"ea_fsm": ["{root}/pfx/drive_c/ProgramData/EA Desktop/Logs/EADesktop.log", r"\[(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)[.\d]*Z\][^\n]*?DesktopFSM\[(\w+)\]"],
                     "ea_login_page": ["{root}/pfx/drive_c/ProgramData/EA Desktop/Logs/EADesktop.log", r"(Login page load \w+)"],
                     # the game's status the app sends its UI: who sells it (STEAM = linked from Steam) and installing / installed
                     "ea_game_status": ["{root}/pfx/drive_c/ProgramData/EA Desktop/Logs/EADesktopVerbose.log", r'"gameStatus":(\{[^{}]*\})'],
                     # the game's "Terms of play" dialog logs one impression per agreement link it shows
                     "ea_terms_shown": ["{root}/pfx/drive_c/ProgramData/EA Desktop/Logs/EADesktopVerbose.log", r'"impressionId": "(eula-link)"'],
                     "ea_installed_ids": ["{root}/pfx/drive_c/ProgramData/EA Desktop/Logs/EADesktopVerbose.log", r"Returning \[(\d+)\] installedOfferIds"]},
           # no screenshot while the app waits for a sign-in (the "EA" window then shows the login form)
           "private": {"ea_fsm": "awaitingAuthentication"},
           "exists": {"ea_app": "{root}/pfx/drive_c/Program Files/Electronic Arts/EA Desktop/*/EA Desktop/EALauncher.exe",
                      "ts4_exe": "{root}/pfx/drive_c/Program Files/EA Games/The Sims 4/Game/Bin/TS4_x64.exe"},
           "du": {"ts4": "{root}/pfx/drive_c/Program Files/EA Games/The Sims 4"},
           "fs_of": "{root}/pfx/drive_c"},
}

# ---------------------------------------------------------------- the snapshot, run INSIDE the sandbox (python3 -c, stdlib only)
# Input: the env var GA_WD (JSON). No literal process pattern appears in this source, so it can never match itself in a process list
# (docker-rt's exec wrappers repeat the whole command line: HICCUPS mcdl #8); processes are matched per argv element afterwards.
SNAPSHOT_PY = r'''
import glob, json, os, re, subprocess, time
a = json.loads(os.environ.get("GA_WD") or "{}")
root = os.path.expanduser(os.environ.get("GA_STEAM_ROOT") or a.get("root") or "~/.steam/debian-installation")
disp = a.get("display") or os.environ.get("DISPLAY") or ":99"
secret = re.compile(a.get("secret") or "$^", re.I)
def P(s):
    p = os.path.expanduser(s.replace("{root}", root))
    if "*" in p:                                       # the newest match (EA's log names carry a date)
        m = sorted(glob.glob(p), key=lambda x: os.path.getmtime(x) if os.path.exists(x) else 0)
        return m[-1] if m else p
    return p
def run(argv, t=10):
    try: return subprocess.run(argv, capture_output=True, text=True, timeout=t, env=dict(os.environ, DISPLAY=disp)).stdout
    except Exception: return ""
def tail(p, n=60, b=12000):
    try:
        with open(p, "rb") as f:
            f.seek(0, 2); z = f.tell(); f.seek(max(0, z - b)); t = f.read().decode("utf-8", "replace")
        return "\n".join(t.splitlines()[-n:])
    except OSError: return None
out = {"at": int(time.time()), "root": root, "windows": [], "procs": [], "logs": {}, "greps": {}, "jsons": {}, "exists": {}, "dirs": {},
       "manifests": {}, "sizes": {}, "fs": None, "ns_mount_ok": None, "screenshot": None, "screenshot_skipped": None}
for w in run(["xdotool", "search", "--onlyvisible", "--name", "."]).split()[:60]:
    n = run(["xdotool", "getwindowname", w]).strip().replace("\u00a0", " ")     # EA titles use a no-break space
    if not n: continue
    g = re.search(r"Geometry: (\d+)x(\d+)", run(["xdotool", "getwindowgeometry", w]))
    out["windows"].append({"title": n[:120], "w": int(g.group(1)) if g else 0, "h": int(g.group(2)) if g else 0})
me = {os.getpid(), os.getppid()}
try: pids = os.listdir("/proc")
except OSError: pids = []                              # no /proc: not Linux (the tests run this on macOS / Windows too)
for d in pids:
    if not d.isdigit() or int(d) in me: continue
    try:
        exe = os.readlink(f"/proc/{d}/exe")
    except OSError: exe = ""
    try:
        raw = open(f"/proc/{d}/stat").read()
        comm = raw[raw.find("(") + 1:raw.rfind(")")]
        st = raw.rsplit(")", 1)[1].split()
        argv = open(f"/proc/{d}/cmdline", "rb").read().split(b"\0")[:6]
    except (OSError, IndexError): continue
    out["procs"].append({"pid": int(d), "state": st[0], "start": int(st[19]) if len(st) > 19 else 0, "exe": exe[:200], "comm": comm[:32],
                         "argv": [x.decode("utf-8", "replace")[:160] for x in argv if x]})
for k, p in (a.get("logs") or {}).items():
    if secret.search(P(p)): continue
    t = tail(P(p))
    if t is not None: out["logs"][k] = t
for k, (p, rx) in (a.get("greps") or {}).items():
    try: m = re.findall(rx, open(P(p), encoding="utf-8", errors="replace").read())
    except OSError: m = None
    out["greps"][k] = (m[-1] if m else "") if m is not None else None
for k, p in (a.get("jsons") or {}).items():
    if secret.search(P(p)): continue
    try: out["jsons"][k] = json.load(open(P(p), encoding="utf-8"))
    except (OSError, ValueError): out["jsons"][k] = None
for k, p in (a.get("exists") or {}).items(): out["exists"][k] = os.path.exists(P(p))
for k, p in (a.get("dirs") or {}).items():
    try: out["dirs"][k] = len(os.listdir(P(p)))
    except OSError: out["dirs"][k] = None
for k, p in (a.get("du") or {}).items():
    q = P(p)
    s = run(["du", "-sb", q], 60).split() if os.path.exists(q) else []
    out["sizes"][k] = int(s[0]) if s and s[0].isdigit() else None
apps = os.path.join(root, "steamapps")
for app in a.get("apps") or []:
    m = os.path.join(apps, f"appmanifest_{app}.acf")
    try: txt = open(m, encoding="utf-8", errors="replace").read()
    except OSError: txt = None
    out["manifests"][str(app)] = txt
    inst = re.search(r'"installdir"\s+"([^"]*)"', txt or "")
    for key, p in (("downloading", os.path.join(apps, "downloading", str(app))), ("common", os.path.join(apps, "common", inst.group(1)) if inst else "")):
        if p and os.path.exists(p):
            s = run(["du", "-skL", p], 25).split()
            out["sizes"][f"{key}_{app}"] = int(s[0]) if s and s[0].isdigit() else None
if a.get("fs_of"):
    p = os.path.realpath(P(a["fs_of"])); best = ("", None)
    try:
        for line in open("/proc/mounts"):
            f = line.split()
            if len(f) > 2 and (p == f[1] or p.startswith(f[1].rstrip("/") + "/")) and len(f[1]) >= len(best[0]): best = (f[1], f[2])
    except OSError: pass
    out["fs"] = best[1]
try:                                                   # cgroup v2: processes the kernel killed for memory in THIS sandbox, its limit
    out["oom_kills"] = int(next((l.split()[1] for l in open("/sys/fs/cgroup/memory.events").read().splitlines() if l.startswith("oom_kill ")), "0"))
    v = open("/sys/fs/cgroup/memory.max").read().strip(); out["mem_limit"] = None if v == "max" else int(v)
except (OSError, ValueError): out["oom_kills"], out["mem_limit"] = None, None
if a.get("shm"):                                       # /dev/shm size: 64 MB (Docker / k8s default) is too small for steamwebhelper
    try: v = os.statvfs("/dev/shm"); out["shm_mb"] = v.f_blocks * v.f_frsize // (1 << 20)
    except (OSError, AttributeError): out["shm_mb"] = None
if a.get("probe_ns"):
    try: out["ns_mount_ok"] = subprocess.run(["unshare", "--user", "--map-root-user", "--mount", "true"], capture_output=True, timeout=10).returncode == 0
    except Exception: out["ns_mount_ok"] = None
if a.get("shot"):
    login = out["logs"].get("steamui_login") or ""
    states = re.findall(r"\[ (\w+) \]", login)
    titles = " | ".join(w["title"] for w in out["windows"])
    # a private state's log that cannot be read counts as private: the sign-in window may be open (2026-10-31, the wrong EA root)
    priv = any(k in out["greps"] and (out["greps"][k] is None or re.search(rx, str(out["greps"][k] or "")))
               for k, rx in (a.get("private") or {}).items())
    if priv or (states and states[-1] == "WaitingForCredentials") or re.search(r"Sign in|Steam Guard|Friends List|Login", titles):
        out["screenshot_skipped"] = "private"
    else:
        os.makedirs(os.path.dirname(a["shot"]), exist_ok=True)
        size = re.search(r"dimensions:\s+(\d+x\d+)", run(["xdpyinfo"]))
        r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-video_size", size.group(1) if size else "1280x720",
                            "-i", disp, "-frames:v", "1", a["shot"]], capture_output=True, timeout=30)
        out["screenshot"] = a["shot"] if r.returncode == 0 else None
print(json.dumps(out))
'''


# ---------------------------------------------------------------- where the snapshot runs
class LocalBox:
    """Inside the sandbox itself (ga-steam, ga-mc)."""
    def py(self, source, env, timeout=90):
        try: r = subprocess.run([sys.executable or "python3", "-c", source], capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout, env={**os.environ, **env}, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired: return 124, ""
        return r.returncode, r.stdout

    def sh(self, script, timeout=90):
        try: r = subprocess.run(["sh", "-c", script], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                                stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired: return 124, ""
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    def read(self, path) -> bytes:
        try: return Path(path).read_bytes()
        except OSError: return b""


class DockerBox:
    """A sandbox container seen from the host: every read goes through `docker exec` (labup.Engine: plain Docker or docker-rt)."""
    def __init__(self, name, engine=None):
        if engine is None:
            from .labup import Engine
            engine = Engine()
        self.name, self.engine = name, engine

    def _exec(self, args, timeout, text=True):
        if not self.engine.docker: return 127, "" if text else b""
        enc = {"encoding": "utf-8", "errors": "replace"} if text else {}
        try: r = subprocess.run([self.engine.docker, "exec", *args], capture_output=True, text=text, timeout=timeout,
                                stdin=subprocess.DEVNULL, env=self.engine.env, **enc)
        except subprocess.TimeoutExpired: return 124, "" if text else b""
        except OSError: return 127, "" if text else b""
        return r.returncode, r.stdout if not text or r.returncode == 0 else (r.stdout or "") + (r.stderr or "")

    def py(self, source, env, timeout=90):
        e = sum((["-e", f"{k}={v}"] for k, v in env.items()), [])
        return self._exec([*e, self.name, "python3", "-c", source], timeout)

    def sh(self, script, timeout=90): return self._exec([self.name, "sh", "-c", script], timeout)

    def read(self, path) -> bytes: return self._exec([self.name, "cat", path], 60, text=False)[1] or b""

    def state(self): return self.engine.state(self.name)


def collect(box, flow, apps=(), shot=None, probe_ns=False, display=None, root=None) -> dict:
    """One snapshot of the sandbox for a flow ("steam" | "microsoft" | "minecraft"). Returns {} with "error" when the exec failed."""
    spec = {k: dict(v) if isinstance(v, dict) else v for k, v in SPECS[flow].items()}
    if flow == "microsoft": spec.setdefault("jsons", {}); spec["logs"] = {**spec["logs"], **SPECS["minecraft"]["logs"]}
    arg = {**spec, "apps": [int(x) for x in apps], "shot": shot or "", "probe_ns": bool(probe_ns), "secret": SECRET_FILES.pattern,
           **({"display": display} if display else {}), **({"root": root} if root else {})}
    rc, out = box.py(SNAPSHOT_PY, {"GA_WD": json.dumps(arg)})
    try: return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError, AttributeError): return {"error": f"snapshot failed (rc {rc}): {redact(str(out))[-200:]}"}


# ---------------------------------------------------------------- facts
def acf(text) -> dict:
    """appmanifest_*.acf -> its flat top-level keys (StateFlags, BytesDownloaded, ...)."""
    d, depth = {}, 0
    for raw in (text or "").splitlines():
        s = raw.strip()
        if s == "{": depth += 1; continue
        if s == "}": depth -= 1; continue
        t = re.findall(r'"([^"]*)"', s)
        if len(t) == 2 and depth == 1: d[t[0]] = t[1]
    return d


def _int(v, default=0):
    try: return int(v)
    except (TypeError, ValueError): return default


def _argv_has(argv, tool, *words):
    """argv element-wise: an element that is the tool (or ends with /tool) directly followed by words (no self-matching)."""
    for i, x in enumerate(argv or []):
        if x == tool or x.endswith("/" + tool):
            if list(argv[i + 1:i + 1 + len(words)]) == list(words): return True
    return False


def _last_state(text):
    m = re.findall(r"\[ (\w+) \]", text or "")
    return m[-1] if m else None


def _logged_on(conn):
    for line in reversed((conn or "").splitlines()):
        if "[Logged On" in line: return True
        if "[Logged Off" in line or "[Logging Off" in line: return False
    return False


def _bootstrap(text):
    """(stage, pct) from the client bootstrap log: downloading N of M KB, extracting, installing, or None when it is done / absent."""
    for line in reversed((text or "").splitlines()[-30:]):
        m = re.search(r"Downloading update \((\d[\d,]*) of (\d[\d,]*) KB\)", line)
        if m:
            n, t = int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))
            return ("downloading", round(100 * n / t) if t else 0) if n < t else ("extracting", 100)
        if re.search(r"Extracting package", line): return "extracting", 100
        if re.search(r"Installing update", line): return "installing", 100
        if re.search(r"Update complete|Startup - updater built|Verification complete|Shutdown", line): return None, None
    return None, None


def facts(snap, ctx=None) -> dict:
    """The facts the KNOWN detectors use, from one snapshot (pure: the tests feed recorded snapshots). ctx: app (the appid being
    installed or launched), install_requested_at, game, viewer, now, consent (licence consents of the project)."""
    ctx = ctx or {}
    s = snap or {}
    now = ctx.get("now") or s.get("at") or time.time()
    logs = s.get("logs") or {}
    procs = s.get("procs") or []
    wins = s.get("windows") or []
    exes = [p.get("exe") or "" for p in procs if p.get("state") != "Z"]
    titles = [w.get("title", "") for w in wins]
    f = {"error": s.get("error"), "window_titles": titles, "windows": [f"{w.get('title')} {w.get('w')}x{w.get('h')}" for w in wins],
         "game": ctx.get("game") or "", "viewer": ctx.get("viewer") or "http://localhost:6080/vnc.html"}
    # Steam
    f["steam_running"] = any(e.endswith("ubuntu12_32/steam") for e in exes)
    f["webhelper"] = any(e.endswith("ubuntu12_64/steamwebhelper") for e in exes)
    f["zenity"] = any(e.endswith("/zenity") for e in exes)
    f["fossilize"] = sum(1 for e in exes if "fossilize_replay" in e)
    f["installer_dialog"] = any(t == "Steam installer" for t in titles)
    f["updater_window"] = any(w.get("title") == "Steam" and 0 < (w.get("w") or 0) < 500 for w in wins)
    f["friends_window"] = any(re.match(r"^Friends List", t) for t in titles)
    f["login_state"] = _last_state(logs.get("steamui_login"))
    f["logged_on"] = _logged_on(logs.get("connection"))
    f["desktop_login_window"] = bool(re.search(r"DesktopLoginWindow .*'Sign in", logs.get("webhelper") or ""))
    f["login_window"] = bool(f["webhelper"] and not f["logged_on"] and (f["login_state"] == "WaitingForCredentials" or f["desktop_login_window"]
                                                                        or any(t.startswith("Sign in") for t in titles)))
    f["logon_failure_noise"] = "Received logon failure response" in (logs.get("steamui_login") or "") or \
        "Failed to poll auth session" in (logs.get("steamui_login") or "")
    f["bootstrap_stage"], f["bootstrap_pct"] = _bootstrap(logs.get("bootstrap")) if f["steam_running"] or logs.get("bootstrap") else (None, None)
    if f["logged_on"] or f["login_window"]: f["bootstrap_stage"], f["bootstrap_pct"] = None, None
    f["installer_cancelled"] = "Installation cancelled" in (logs.get("steam_out") or "")[-2000:]
    f["ns_mount_ok"] = s.get("ns_mount_ok")
    # Docker Desktop on Apple silicon: the 32-bit client runs under qemu-i386 and crashes after its self-update (her Mac 2026-10-30)
    f["qemu_segv"] = bool(re.search(r"qemu: uncaught target signal 11", (s.get("logs") or {}).get("console") or ""))
    f["oom_new"] = (s.get("oom_kills") or 0) > ctx.get("oom_base", s.get("oom_kills") or 0)   # killed for memory since this watch began
    f["mem_limit_gb"] = f"{s['mem_limit'] / 2 ** 30:.1f}" if s.get("mem_limit") else "?"
    f["library_fs"] = s.get("fs")
    f["network_disk"] = bool(s.get("fs") and (s["fs"] in NETWORK_FS or s["fs"].startswith("fuse")))
    f["shm_mb"] = s.get("shm_mb")
    f["small_shm"] = bool(s.get("shm_mb") is not None and s["shm_mb"] < 256)
    wf = (s.get("greps") or {}).get("webhelper_shm_flag")
    f["webhelper_shm_flag"] = None if wf is None else bool(wf)      # None: the client is not installed yet (no wrapper script)
    sb = (s.get("greps") or {}).get("shader_bg")
    f["shader_precache"] = None if sb is None else sb != "0"           # missing key = Steam's default: on
    content = (logs.get("content") or "").splitlines()
    zero = 0
    for line in reversed([x for x in content if "Current download rate" in x]):
        if re.search(r"Current download rate: 0\.000 Mbps", line): zero += 1
        else: break
    f["rate_zero_minutes"] = zero                                       # Steam writes this line about once a minute
    running = {}
    for line in content:
        m = re.search(r"AppID (\d+) state changed : (.*)", line)
        if m: running[int(m.group(1))] = "App Running" in m.group(2)
    f["steam_thinks_running"] = sorted(a for a, r in running.items() if r)
    game_procs = [p for p in procs if p.get("state") != "Z" and "/steamapps/common/" in (p.get("exe") or "")]
    f["game_running"] = bool(game_procs)
    f["ghost_running"] = bool(f["steam_thinks_running"]) and not f["game_running"]
    f["app_no_license"] = bool(re.search(r"No licenses|No subscription|missing license", (logs.get("content") or "")[-4000:], re.I)) and \
        (not ctx.get("app") or str(ctx.get("app")) in (logs.get("content") or "")[-4000:])
    # the app being installed / launched
    app = ctx.get("app")
    eula = hiccups.EULAS.get(int(app)) if app else None
    f.update(eula_known=bool(eula), publisher=(eula or {}).get("publisher", ""), agreement=(eula or {}).get("agreement", ""),
             url=(eula or {}).get("url", ""))
    req = ctx.get("install_requested_at")
    f["install_requested_s"] = int(now - req) if req else -1
    man = (s.get("manifests") or {}).get(str(app)) if app else None
    a = acf(man) if man else {}
    flags = _int(a.get("StateFlags"))
    f["app_manifest"] = bool(man)
    f["app_flags"] = flags
    f["app_installed"] = bool(man) and flags == 4
    f["app_downloading"] = bool(man) and bool(flags & 1024)
    f["app_bytes_dl"] = _int(a.get("BytesDownloaded"))
    f["app_bytes_total"] = _int(a.get("BytesToDownload"))
    f["app_staged"] = _int(a.get("BytesStaged"))
    f["app_size"] = _int(a.get("SizeOnDisk"))
    sizes = s.get("sizes") or {}
    f["app_du_kb"] = (sizes.get(f"downloading_{app}") or 0) + (sizes.get(f"common_{app}") or 0) if app else 0
    total = f["app_bytes_total"]
    f["app_download_complete"] = bool(total) and f["app_bytes_dl"] >= total
    want = f["app_size"] or total
    f["app_files_complete"] = bool(want) and (sizes.get(f"common_{app}") or 0) * 1024 >= 0.98 * want and not f["app_installed"]
    f["app_pct"] = round(100 * f["app_bytes_dl"] / total) if total else 0
    # Microsoft / Minecraft
    js = s.get("jsons") or {}
    lg = js.get("mc_login") or {}
    f["mc_code"], f["mc_url"] = lg.get("code") or "", lg.get("url") or ""
    f["mc_code_expired"] = bool(lg) and _int(lg.get("expires_at")) < now
    logins = sorted((p for p in procs if p.get("state") != "Z" and _argv_has(p.get("argv"), "ga-mc", "account", "login")),
                    key=lambda p: p.get("start", 0))
    f["mc_login_procs"] = len(logins)
    f["mc_login_pids"] = [p["pid"] for p in logins]
    f["mc_older_login_pids"] = " ".join(str(p["pid"]) for p in logins[:-1])
    f["mc_signed_in"] = bool((s.get("exists") or {}).get("mc_token"))
    res = js.get("mc_result")
    f["mc_checked"] = isinstance(res, dict)
    f["mc_owns_java"] = bool(isinstance(res, dict) and res.get("owns_java"))
    g = logs.get("mc_game") or ""
    f["mc_world_missing"] = bool(re.search(r"Could not find a world|Failed to Quick Play", g))
    f["mc_saves"] = (s.get("dirs") or {}).get("mc_saves")
    ea_facts(f, s, procs, titles, logs, ctx)
    f["last_log"] = _last_line(logs)
    return f


def _win_exes(procs) -> list:
    """The Windows programs running under Wine: the .exe name of argv[0] (lower case), zombies left out."""
    out = []
    for p in procs:
        if p.get("state") == "Z": continue
        a0 = ((p.get("argv") or [""])[0] or "")
        m = re.search(r"([^\\/]+\.exe)$", a0, re.I)
        if m: out.append(m.group(1).lower())
    return out


EA_SIGNED_IN = ("authenticated",)        # DesktopFSM states seen 10-29: awaitingMainAppReady -> mainAppReady -> awaitingAuthentication -> authenticated


def ea_facts(f, s, procs, titles, logs, ctx=None):
    """The EA App (Windows, under Wine) facts, from the snapshot of the "ea" flow (seen 2026-10-29, HICCUPS ea)."""
    exes = _win_exes(procs)
    inst = logs.get("ea_installer") or ""
    desk = logs.get("ea_desktop") or ""
    ex = s.get("exists") or {}
    f["ea_installer_running"] = "eaappinstaller.exe" in exes
    f["ea_installer_window"] = "EA app installer" in titles
    f["ea_installer_applying"] = "Apply begin" in inst and "Apply complete" not in inst
    m = re.findall(r"Apply complete, result: (0x[0-9a-fA-F]+)", inst)
    f["ea_installer_result"] = m[-1] if m else None
    f["ea_installer_failed"] = bool(m and m[-1] != "0x0") or "INST-14-1603" in inst
    # the first page = EA's User Agreement ("LET'S GO" accepts): the installer window is up and nothing was planned yet
    f["ea_installer_eula"] = f["ea_installer_window"] and "Plan begin" not in inst and "Apply begin" not in inst
    if f["ea_installer_eula"]:
        e = hiccups.EULAS["ea"]; f.update(publisher=e["publisher"], agreement=e["agreement"], url=e["url"])
    f["ts4_exe"] = bool(ex.get("ts4_exe"))
    f["ts4_running"] = "ts4_x64.exe" in exes
    f["ts4_bytes"] = (s.get("sizes") or {}).get("ts4") or 0
    f["ea_app_installed"] = bool(ex.get("ea_app"))
    f["ea_app_running"] = "eadesktop.exe" in exes
    f["ea_app_window"] = "EA" in titles
    g = s.get("greps") or {}
    fsm = g.get("ea_fsm")                                          # [UTC time, the app's DesktopFSM state] (EADesktop.log, appended per start)
    f["ea_fsm"] = fsm[1] if isinstance(fsm, list) and len(fsm) == 2 else None
    f["ea_fsm_at"] = calendar.timegm(time.strptime(fsm[0], "%Y-%m-%dT%H:%M:%S")) if f["ea_fsm"] else 0
    # after a (re)start only lines written since then count: the log keeps the last run's "authenticated"
    if f["ea_fsm"] and (ctx or {}).get("ea_started_at") and f["ea_fsm_at"] < ctx["ea_started_at"] - 5: f["ea_fsm"] = "starting"
    f["ea_login_page"] = g.get("ea_login_page") or None
    # the sign-in form: the app waits for authentication and its page loaded (the "EA" window is then 520x648)
    f["ea_login_window"] = f["ea_app_running"] and f["ea_fsm"] == "awaitingAuthentication"
    f["ea_login_page_failed"] = f["ea_app_running"] and f["ea_fsm"] == "awaitingAuthentication" and f["ea_login_page"] == "Login page load failed"
    f["ea_signed_in"] = f["ea_app_running"] and f["ea_fsm"] in EA_SIGNED_IN    # a positive state only (awaitingMainAppReady is not)
    try: gs = json.loads(g.get("ea_game_status") or "{}")
    except ValueError: gs = {}
    f["ea_game_source"] = gs.get("externalSource") or None          # "STEAM": owned through a linked Steam account
    # owned ONLY through another store: real entitlement data, never a click outcome. externalSource alone is NOT enough (10-29: her
    # account is linked to Steam, externalSource was STEAM, yet managedBy was EA and the EA App downloaded the game itself); it
    # counts only when the app also says another store manages the game.
    f["ea_game_managed_by"] = gs.get("managedBy") or None
    f["ea_external_owned"] = bool(f["ea_game_source"]) and f["ea_game_managed_by"] not in (None, "EA") and not gs.get("installed")
    f["ea_steam_owned"] = f["ea_external_owned"] and f["ea_game_source"] == "STEAM"
    f["ea_store_name"] = {"STEAM": "Steam", "EPIC": "Epic Games"}.get(f["ea_game_source"] or "", (f["ea_game_source"] or "").title())
    # a browser opened by Wine (winebrowser) after a click: most likely a MISCLICK on a link (HICCUPS ea #11), never evidence
    f["ea_browser_opened"] = sum(1 for p in procs if "winebrowser" in (p.get("comm") or "").lower() or
                                 any("winebrowser" in x.lower() for x in (p.get("argv") or [])[:1]))
    f["ea_game_installing"] = bool(gs.get("installing") or gs.get("updating"))
    f["ea_game_installed"] = bool(gs.get("installed")) or (f.get("ts4_exe") is True and not f["ea_game_installing"])
    f["ea_terms_of_play"] = bool(g.get("ea_terms_shown")) and not f["ea_game_installing"] and not gs.get("installed")
    if f["ea_login_window"]: f["login_window"] = True              # no screenshot, no "unknown" picture while it is open
    f["wine_mono_dialog"] = "Wine Mono Installer" in titles or "Wine Gecko Installer" in titles


def _last_line(logs) -> str:
    for k in ("steam_out", "bootstrap", "content", "steamui_login", "mc_login_log", "mc_download_log", "mc_game", "ea_desktop", "ea_installer"):
        t = [x for x in (logs.get(k) or "").splitlines() if x.strip()]
        if t: return redact(t[-1])[:200]
    return "-"


SIGNATURE = ("error", "steam_running", "webhelper", "windows", "login_state", "logged_on", "bootstrap_stage", "bootstrap_pct",
             "installer_dialog", "app_flags", "app_bytes_dl", "app_staged", "app_du_kb", "app_manifest", "mc_code", "mc_checked",
             "mc_world_missing", "fossilize", "rate_zero_minutes", "ea_installer_running", "ea_installer_applying", "ea_app_running", "ea_fsm",
             "ts4_bytes", "ea_game_installing", "ea_game_installed", "ea_browser_opened")


def signature(f) -> str:
    """What counts as 'the state changed' (a new log line alone does not: Steam keeps logging while it is stuck)."""
    return json.dumps({k: f.get(k) for k in SIGNATURE}, sort_keys=True, default=str)


# ---------------------------------------------------------------- the detectors
def _test(v, cond) -> bool:
    if not isinstance(cond, dict): return v == cond
    num = isinstance(v, (int, float)) and not isinstance(v, bool)
    for k, c in cond.items():
        if k == "re":
            items = v if isinstance(v, list) else [v]
            if not any(x is not None and re.search(c, str(x)) for x in items): return False
        elif k == "min":
            if not (num and v >= c): return False
        elif k == "max":
            if not (num and v <= c): return False
        elif k == "in":
            if v not in c: return False
        elif k == "not":
            if v == c: return False
        else: return False
    return bool(cond)


def match(f, flow, phase=None, stalled_s=0, known=None) -> list:
    """The KNOWN entries whose detector holds for these facts, in table order."""
    out = []
    for e in known if known is not None else hiccups.KNOWN:
        if flow not in e["flows"]: continue
        if phase and e.get("phases") and phase not in e["phases"]: continue
        if stalled_s < e.get("min_stall_s", 0): continue
        if all(_test(f.get(k), c) for k, c in e["when"].items()): out.append(e)
    return out


# ---------------------------------------------------------------- the safe automatic actions (exact scripts, run inside the sandbox)
ACTIONS = {
    # the Debian "Steam installer" zenity box: [Cancel] [Install], Install at the right of the bottom row; Return would be Cancel
    "click_installer_install": 'w=$(xdotool search --onlyvisible --name "^Steam installer$" | head -1); [ -n "$w" ] || exit 3; '
                               'eval "$(xdotool getwindowgeometry --shell "$w")"; xdotool windowactivate --sync "$w" 2>/dev/null; '
                               'xdotool mousemove $((X+WIDTH-50)) $((Y+HEIGHT-22)); sleep 0.3; xdotool click 1; sleep 3; '
                               'xdotool search --onlyvisible --name "^Steam installer$" >/dev/null && exit 4 || exit 0',
    "steam_start": "ga-steam start",
    "steam_restart": "ga-steam stop; ga-steam start",
    "steam_open_downloads": "ga-steam open downloads",
    "close_friends_window": 'for w in $(xdotool search --onlyvisible --name "^Friends List"); do xdotool windowunmap "$w"; done; true',
    "shader_precache_off": "ga-steam shader-off",
    "steam_webhelper_no_shm": "ga-steam shm-fix",
    "ea_restart": "ga-ea stop; ga-ea start",
    "ea_normalize_window": "ga-ea normalize",
    # agreement buttons, ONLY for a fresh click_for_me consent (Watchdog._accept_for_user); window-relative, seen 2026-10-29
    "ea_click_lets_go": 'w=$(xdotool search --onlyvisible --name "^EA.app installer$" | head -1); [ -n "$w" ] || exit 3; '
                        'eval "$(xdotool getwindowgeometry --shell "$w")"; xdotool mousemove $((X+240)) $((Y+401)); sleep 0.3; xdotool click 1',
    "ea_click_terms_download": 'w=$(xdotool search --onlyvisible --name "^EA$" | head -1); [ -n "$w" ] || exit 3; '
                               'eval "$(xdotool getwindowgeometry --shell "$w")"; [ "$WIDTH" = 1024 ] || exit 5; '
                               'xdotool mousemove $((X+585)) $((Y+495)); sleep 0.3; xdotool click 1',
    # Wine's first-start "Wine Mono Installer" / "Wine Gecko Installer" box: Return = its default button, Install
    "wine_mono_install": 'w=$(xdotool search --onlyvisible --name "^Wine (Mono|Gecko) Installer$" | head -1); [ -n "$w" ] || exit 3; '
                         'xdotool key --window "$w" Return',
    "mc_login_again": "ga-mc-login-start",                    # resolved by the caller (loginflow.MC_LOGIN_START)
    "mc_keep_newest_login": "for p in {mc_older_login_pids}; do kill $p; done; true",   # the exact pids of the older login processes
}


def redact(text) -> str:
    """No token, account name, Steam id or e-mail in anything saved or printed."""
    t = str(text)
    t = re.sub(r'"(refresh_token|access_token|device_code|id_token|Token|AccountName|PersonaName|password|RememberPassword)"(\s*:\s*|\s+)"[^"]*"',
               r'"\1"\2"[redacted]"', t, flags=re.I)
    t = re.sub(r"\[U:1:\d+\]", "[U:1:…]", t)
    t = re.sub(r"\b7656119\d{10}\b", "[steamid]", t)
    t = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email]", t)
    t = re.sub(r"\beyJ[\w-]{4,}\.[\w-]+\.[\w-]+", "[token]", t)
    t = re.sub(r"\b(?:M\.[A-Z0-9]+_|EwB)[\w!*.$/+=-]{16,}", "[token]", t)
    t = re.sub(r"[A-Za-z0-9+/_=-]{64,}", "[redacted]", t)
    return t


def fmt(words, values) -> str:
    class D(dict):
        def __missing__(self, k): return "?"
    try: return str(words).format_map(D(values))
    except (ValueError, IndexError): return str(words)


def say_of(e, lang, values) -> dict:
    return {"zh": fmt(e["say"]["zh"], values), "en": fmt(e["say"]["en"], values)}


def human_s(s, lang="en") -> str:
    s = int(s)
    if s < 90: return f"{s} 秒" if lang == "zh" else f"{s} s"
    return f"{round(s / 60)} 分钟" if lang == "zh" else f"{round(s / 60)} min"


# ---------------------------------------------------------------- licence consents (recorded only: the user still clicks Accept)
CLICK_FOR_ME_MAX_S = 900          # a "click it for me" is valid for this one dialog, for 15 minutes


def record_consent(path, appid, by="user", note="", click_for_me=False, words="", now=None, project=None) -> dict:
    """Write that the user said yes to the publisher agreement of appid. A plain yes never makes the watchdog click (the user clicks
    Accept). click_for_me=True (2026-10-29 rule, Wenyi): the user said, in the moment and for THIS dialog, "agree, click it for me"
    (e.g. 「同意，帮我点」, kept in `words`); then the watchdog may click it once, within CLICK_FOR_ME_MAX_S."""
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    d = consents(p)
    key = int(appid) if str(appid).isdigit() else str(appid)
    e = hiccups.EULAS.get(key, {})
    t = now if now is not None else time.time()
    d[str(key)] = {"game": e.get("game"), "publisher": e.get("publisher"), "agreement": e.get("agreement"), "url": e.get("url"),
                   "by": by, "note": note, "at": time.strftime("%Y-%m-%d %H:%M", time.localtime(t)), "at_ts": int(t),
                   "click_for_me": bool(click_for_me), "words": words}
    if project: d[str(key)]["project"] = project          # a lab-lease project name (e.g. steam-dl), recorded in the user's file
    p.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    return d[str(key)]


def click_for_me_ok(c, now) -> bool:
    """A consent that allows the agent to click: click_for_me, the user's words, and fresh."""
    return bool(c and c.get("click_for_me") and (c.get("words") or "").strip() and 0 <= now - (c.get("at_ts") or 0) <= CLICK_FOR_ME_MAX_S)


def consents(path) -> dict:
    try: return json.loads(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, ValueError): return {}


# ---------------------------------------------------------------- the watchdog
class Watchdog:
    """See the module doc. say(line) gets the user's language; emit(event) gets every event with both languages (--json)."""

    def __init__(self, box, flow, phase, lang="en", say=None, emit=None, ctx=None, evidence=None, stall_s=60, heartbeat_s=110,
                 clock=time.time, known=None, actions=None, apps=(), display=None, consent=None, probe_ns=False, root=None):
        self.box, self.flow, self.phase, self.lang = box, flow, phase, lang if lang in ("zh", "en") else "en"
        self.say_fn, self.emit_fn = say or (lambda m: print(m, flush=True)), emit or (lambda e: None)
        self.ctx = dict(ctx or {}); self.evidence = Path(evidence) if evidence else None
        self.stall_s, self.heartbeat_s, self.clock = stall_s, heartbeat_s, clock
        self.known = known if known is not None else hiccups.KNOWN
        self.actions = dict(ACTIONS, **(actions or {}))
        self.apps = list(apps) or ([self.ctx["app"]] if self.ctx.get("app") else [])
        self.display, self.consent, self.probe_ns, self.root = display, consent or {}, probe_ns, root
        t = self.clock()
        self.t0 = self.phase_t0 = self.last_change = self.last_said = t
        self.last_sig, self.active, self.done_once, self.unknown_at, self.stall_saved = None, {}, set(), 0, None
        self.last_private = False
        self.events = []

    # -- output
    def _out(self, kind, words, **kw):
        ev = {"kind": kind, "phase": self.phase, "at": int(self.clock()), "zh": words["zh"], "en": words["en"], **kw}
        self.events.append(ev); self.emit_fn(ev)
        if kind != "quiet": self.say_fn(words[self.lang]); self.last_said = self.clock()
        return ev

    def progress(self, words, **kw): return self._out("progress", words, **kw)

    def set_phase(self, phase):
        if phase != self.phase: self.phase, self.phase_t0 = phase, self.clock()

    # -- one tick
    def tick(self, snap=None) -> dict:
        now = self.clock()
        if snap is None: snap = collect(self.box, self.flow, self.apps, probe_ns=self.probe_ns, display=self.display, root=self.root)
        self.ctx.setdefault("oom_base", snap.get("oom_kills") or 0)       # the sandbox's count when the watch began
        f = facts(snap, {**self.ctx, "now": now})
        sig = signature(f)
        if sig != self.last_sig: self.last_sig, self.last_change, self.stall_saved = sig, now, None
        stalled = now - self.last_change
        ms = match(f, self.flow, self.phase, stalled, self.known)
        stop, acted = None, []
        ids = {e["id"] for e in ms}
        for gone in [i for i in self.active if i not in ids]: self.active.pop(gone)
        for e in ms:
            st = self.active.setdefault(e["id"], {"first": now, "told": False, "tries": 0, "escalated": False})
            vals = {**f, **self.ctx}
            if e["kind"] == "ignore": continue
            if e.get("once") and e["id"] in self.done_once: continue
            if e.get("license"):
                c = self.consent.get(str(e.get("consent_key") or self.ctx.get("app")))
                if click_for_me_ok(c, now) and e.get("accept_action") and not st.get("clicked"):
                    st["clicked"] = True                 # the user asked, for this dialog, just now: click once, logged with a picture
                    acted.append(self._accept_for_user(e, c, f, vals)); st["told"] = True
                    continue
                if c and not st["told"]:                 # a plain (or stale) yes: the user still clicks Accept herself; keep waiting
                    btn = e.get("button") or "Accept"
                    w = {"zh": f"你 {c.get('at')} 同意过这份协议：请在查看器里自己点 {btn}，我在等。",
                         "en": f"You agreed to this on {c.get('at')}: please click {btn} yourself in the viewer; I am waiting."}
                    self._out("known", {"zh": say_of(e, "zh", vals)["zh"] + " " + w["zh"], "en": say_of(e, "en", vals)["en"] + " " + w["en"]},
                              id=e["id"], license=True, consent=c)
                    st["told"] = True
                elif not c:
                    stop = self._out("needs_user", say_of(e, self.lang, vals), id=e["id"], license=True, publisher=f.get("publisher"),
                                     url=f.get("url"))
                continue                                  # otherwise a licence is never clicked, with or without a plain yes
            if e["kind"] == "ask":
                stop = self._out("needs_user", say_of(e, self.lang, vals), id=e["id"]); continue
            if e["kind"] == "auto" and st["tries"] < e.get("tries", 1):
                st["tries"] += 1
                acted.append(self._act(e, e["action"], say_of(e, self.lang, vals), vals))
                st["told"] = True
            elif e["kind"] == "tell" and not st["told"]:
                self._out("known", say_of(e, self.lang, vals), id=e["id"]); st["told"] = True
            if e.get("once"): self.done_once.add(e["id"])
            mw = e.get("max_wait_s", 0)
            if mw and now - st["first"] >= mw and not st["escalated"]:
                st["escalated"] = True
                th = e.get("then")
                if th and th.get("kind") == "auto": acted.append(self._act(e, th["action"], say_of(th, self.lang, vals), vals, then=True))
                elif th: self._out("known", say_of(th, self.lang, vals), id=e["id"], then=True)
                else:
                    self._out("stuck", {"zh": f"「{e['id']}」已经 {human_s(now - st['first'], 'zh')} 了，比正常久：请在查看器里看一眼，告诉我你看到了什么。",
                                        "en": f"'{e['id']}' has lasted {human_s(now - st['first'])}, longer than normal: please look at the "
                                              "viewer and tell me what you see."}, id=e["id"])
        real = [e for e in ms if e["kind"] != "ignore"]
        shot = None
        if stalled >= self.stall_s and self.stall_saved != sig:
            self.stall_saved = sig
            shot = self._save_stall(snap, f)
            if not real:
                self.unknown_at = now
                private = self.last_private
                v = {"stalled": int(stalled), "windows": ", ".join(f["windows"]) or "-", "last_log": f["last_log"]}
                self._out("unknown", {k: fmt(hiccups.UNKNOWN_SAY[k], {**v, "shot": shot or (hiccups.SHOT_PRIVATE[k] if private else "-")})
                                      for k in ("zh", "en")}, screenshot=shot)
        if now - self.last_said >= self.heartbeat_s and not stop:
            self.heartbeat(now)
        return {"facts": f, "matched": [e["id"] for e in ms], "stalled_s": int(stalled), "stop": stop, "acted": acted, "screenshot": shot}

    def heartbeat(self, now=None):
        now = now or self.clock()
        ph = hiccups.PHASES.get(self.phase) or {"zh": self.phase, "en": self.phase, "normal_zh": "-", "normal_en": "-"}
        self._out("heartbeat", {"zh": fmt(hiccups.HEARTBEAT_SAY["zh"], {"phase": ph["zh"], "elapsed": human_s(now - self.phase_t0, "zh"), "normal": ph["normal_zh"]}),
                                "en": fmt(hiccups.HEARTBEAT_SAY["en"], {"phase": ph["en"], "elapsed": human_s(now - self.phase_t0), "normal": ph["normal_en"]})})

    def _act(self, e, name, words, vals, then=False) -> dict:
        if e.get("license"): raise RuntimeError("a licence is never accepted automatically")      # validate() keeps this out of the table
        script = fmt(self.actions[name], vals)
        rc, out = self.box.sh(script)
        self._out("action", words, id=e["id"], action=name, rc=rc, then=then)
        return {"id": e["id"], "action": name, "rc": rc}

    def _accept_for_user(self, e, c, f, vals) -> dict:
        """Click an agreement's accept button because the user said "click it for me" for it (fresh click_for_me consent). Logged: a
        screenshot of the dialog first (an agreement dialog holds no personal data) and the consent record."""
        shot = None
        if self.evidence and self.box:
            ts = time.strftime("%H%M%S", time.localtime(self.clock()))
            self.evidence.mkdir(parents=True, exist_ok=True)
            s2 = collect(self.box, self.flow, self.apps, shot=f"/sandbox/logs/watchdog/accept-{ts}.png", display=self.display, root=self.root)
            data = self.box.read(s2["screenshot"]) if s2.get("screenshot") else b""
            if data: shot = str(self.evidence / f"accept-{e['id']}-{ts}.png"); Path(shot).write_bytes(data)
            (self.evidence / f"accept-{e['id']}-{ts}.json").write_text(json.dumps({"entry": e["id"], "consent": c, "screenshot": shot},
                                                                                  indent=1, ensure_ascii=False), encoding="utf-8")
        rc, _ = self.box.sh(fmt(self.actions[e["accept_action"]], vals))
        btn = e.get("button") or "Accept"
        self._out("action", {"zh": f"你刚才说「{c.get('words')}」：我替你点了 {btn}（{f.get('publisher') or c.get('publisher')} 的协议）。",
                             "en": f"You just said \"{c.get('words')}\": I clicked {btn} for you ({f.get('publisher') or c.get('publisher')}'s agreement)."},
                  id=e["id"], action=e["accept_action"], rc=rc, license=True, consent=c, screenshot=shot)
        return {"id": e["id"], "action": e["accept_action"], "rc": rc, "click_for_me": True}

    def _save_stall(self, snap, f):
        """The redacted snapshot and (when allowed) a screenshot read through the exec, into the evidence folder. -> the screenshot path."""
        self.last_private = bool(f.get("login_window") or f.get("friends_window"))
        if not self.evidence: return None
        ts = time.strftime("%H%M%S", time.localtime(self.clock()))
        self.evidence.mkdir(parents=True, exist_ok=True)
        shot = None
        if not self.last_private:                      # never a picture of a sign-in window or of the friends list
            inside = f"/sandbox/logs/watchdog/{ts}.png"
            s2 = collect(self.box, self.flow, self.apps, shot=inside, display=self.display, root=self.root) if self.box else {}
            if s2.get("screenshot"):
                data = self.box.read(s2["screenshot"])
                if data:
                    shot = str(self.evidence / f"stall-{ts}.png"); Path(shot).write_bytes(data)
            elif s2.get("screenshot_skipped") == "private": self.last_private = True
        (self.evidence / f"stall-{ts}.json").write_text(redact(json.dumps({"phase": self.phase, "facts": {k: v for k, v in f.items()},
                                                                           "snapshot": snap}, indent=1, default=str)), encoding="utf-8")
        return shot


# ---------------------------------------------------------------- inside one process: a heartbeat for a long call (ga-mc download)
class Heartbeat:
    """with Heartbeat(say, "mc_download", "zh"): ... ; call .beat() on every progress line. Prints a progress line whenever nothing
    was said for `every` seconds."""

    def __init__(self, say, phase, lang="en", every=110, tick=5):
        self.say, self.phase, self.lang, self.every, self.tick = say, phase, lang if lang in ("zh", "en") else "en", every, tick
        self.t0 = self.last = time.time(); self._stop = threading.Event(); self._t = None

    def beat(self): self.last = time.time()

    def _run(self):
        while not self._stop.wait(self.tick):
            if time.time() - self.last >= self.every:
                ph = hiccups.PHASES.get(self.phase) or {"zh": self.phase, "en": self.phase, "normal_zh": "-", "normal_en": "-"}
                k = "_zh" if self.lang == "zh" else "_en"
                self.say(fmt(hiccups.HEARTBEAT_SAY[self.lang], {"phase": ph[self.lang], "elapsed": human_s(time.time() - self.t0, self.lang),
                                                                "normal": ph["normal" + k]}))
                self.last = time.time()

    def __enter__(self):
        self._t = threading.Thread(target=self._run, daemon=True); self._t.start(); return self

    def __exit__(self, *exc): self._stop.set()


def known_in_log(flow, phase, logs) -> list:
    """KNOWN entries that a log alone shows (galab's launch wait): logs {name: text} as in SPECS."""
    return [e for e in match(facts({"logs": logs}), flow, phase) if e["kind"] != "ignore"]
