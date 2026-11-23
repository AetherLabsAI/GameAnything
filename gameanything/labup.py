"""`gameanything lab env up|status [--lease L] [--timeout S] [--json]`: the BASE environment of a lab seat, checked against its lease (added
2026-10-26, after the m8 build stopped because Steam was not running in wc-cities after a pod restart).

    status   what is up / down for the lease's sandbox (read only)
    up       make the base environment up: the pod's X display and viewer (re-runs the pod's entrypoint with LAUNCH_GAME=0, or just the
             missing x11vnc / websockify / viewer.py), and on a Steam sandbox (pool kind `steam`, e.g. wc-cities) the Steam client running
             and logged on: started in the background with the sandbox's /scripts/steam-then-game.sh `sleep infinity`, then waited for its
             "[Logged On" line (at most --timeout seconds, each docker exec short); only a line newer than the running client's start
             counts (connection_log.txt survives a pod restart, and an OOM-killed client's old "[Logged On" stays its last line)

It NEVER starts or stops a game, never stops or logs out Steam, never types a password or a Steam Guard code: a Steam client that does
not log on by itself (no saved login, Steam Guard, a sign-in window) is the state `needs_her` (exit 4): she logs in through the viewer.
It never creates, starts or removes a pod: a sandbox that is not running is `down` (exit 5; the coordinator recreates it with gamebench
hosting/launch_rt/<game>.sh). Plain Docker (gamebench hosting/lab/seat.py, sandbox "local"): each lab run starts its own container
with the game's lab tool (`... up`), so there is nothing to prepare beyond a Docker engine that answers; Steam seats there: unsupported.

The lease (GAMEANYTHING_LEASE "<user>/<project>/<sandbox>:<seat>") must be an active lease of the broker (gamebench hosting/lab_guard.py, exit 3
otherwise). Residents may not run it (agentd's resident runs; builders and coordinators may); agentd's auto builds run `up` before the
builder starts (builds.py) and builders run it themselves when the sandbox lost its environment mid-build (roles/builder.md).

Exit codes: 0 ok, 1 failed (something could not be brought up; try again later), 2 usage, 3 refused (lease), 4 needs_her (Steam
login), 5 down (the pod is not running), 6 unsupported.
"""
import json
import os
import re
import subprocess
import sys
import time
from . import osdirs

CODES = {"ok": 0, "failed": 1, "usage": 2, "refused": 3, "needs_her": 4, "down": 5, "unsupported": 6}
STEAM_START = "/scripts/steam-then-game.sh"
STEAM_OUT = "/tmp/wc-logs/steam-then-game.out"
CONN_LOG = "/home/player/.steam/debian-installation/logs/connection_log.txt"
LOGIN_WINDOWS = "Sign in to Steam|Steam Sign In|Steam Guard|Steam - Login"
STEAM_TIMEOUT = 240
EXEC_TIMEOUT = 60
X_WAIT = 60
POLL = 5


class EnvError(Exception):
    pass


# ---------------------------------------------------------------- the docker client (a fake in the tests)
class Engine:
    """docker ps / docker exec through the docker client of this machine (docker-rt: DOCKER_HOST unix:///tmp/docker-rt.sock)."""

    def __init__(self, env=None, backend=None):
        from . import buildmode
        self.env = dict(os.environ if env is None else env)
        self.backend = backend or buildmode.backend(self.env)
        if self.backend == "docker-rt" and not self.env.get("DOCKER_HOST"): self.env["DOCKER_HOST"] = "unix://" + buildmode.RT_SOCK
        self.docker = buildmode.docker_bin(self.env)

    def _run(self, args, timeout):
        if not self.docker: raise EnvError("no docker client on this machine")
        try: r = subprocess.run([self.docker, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                                stdin=subprocess.DEVNULL, env=self.env)
        except subprocess.TimeoutExpired: return 124, ""
        except OSError as e: raise EnvError(f"docker: {e}")
        return r.returncode, (r.stdout or "") + (r.stderr or "" if r.returncode else "")

    def answers(self) -> bool:
        try: return self._run(["ps", "--format", "{{.Names}}"], 30)[0] == 0
        except EnvError: return False

    def state(self, name):
        """'up' | 'not running' | None (the engine does not answer). docker-rt ignores regex name filters: the whole list is read."""
        rc, out = self._run(["ps", "--format", "{{.Names}}|{{.Status}}"], 30)
        if rc != 0: return None
        for line in out.splitlines():
            n, _, st = line.partition("|")
            if n == name: return "up" if st.startswith("Up") else "not running"
        return "not running"

    def sh(self, name, script, timeout=EXEC_TIMEOUT, env=None):
        """(rc, output) of `sh -c script` in the container (stdin closed, never -i; short: docker-rt execs must stay under 2 min)."""
        e = sum((["-e", f"{k}={v}"] for k, v in (env or {}).items()), [])
        return self._run(["exec", *e, name, "sh", "-c", script], timeout)


# ---------------------------------------------------------------- what the pod has (one exec)
# The [x] brackets keep pgrep from matching this script's own command line (docker-rt's exec wrapper repeats it).
PROBE = r"""D=${DISPLAY:-:${DISPLAY_NUM:-99}}; V=${NOVNC_PORT:-6080}; P=${VNC_PORT:-5900}; W=${WS_PORT:-$((V+2))}
port() { python3 -c "import socket,sys;socket.create_connection(('127.0.0.1',int(sys.argv[1])),2)" "$1" >/dev/null 2>&1 && echo 1 || echo 0; }
echo "display=$D"; echo "viewer_port=$V"
xdpyinfo -display "$D" >/dev/null 2>&1 && echo x=1 || echo x=0
echo "vnc=$(port $P)"; echo "ws=$(port $W)"; echo "viewer=$(port $V)"
pgrep -f "[e]ntrypoint.sh" >/dev/null && echo entrypoint=1 || echo entrypoint=0
[ -n "${SEAT_DISPLAY:-}" ] && { xdpyinfo -display "$SEAT_DISPLAY" >/dev/null 2>&1 && echo seat_x=1 || echo seat_x=0; }
true"""

# Process patterns are anchored at the start of the command line: the probe's own `sh -c <script>` and docker-rt's exec wrappers
# (`sh -c '"$@"; rc=$?; ...' sh sh -c <script>`, `env K=V sh -c ...`) repeat the whole script, so an unanchored pattern, or the
# start script's path written out anywhere in it, matches the probe itself (2026-10-27: wrapper=1 with no Steam in the pod, so
# `up` waited instead of starting Steam). The real processes are `bash /scripts/steam-then-game.sh ...` and
# `/home/player/.steam/debian-installation/ubuntu12_32/steam ...`. The start script's path is put together at run time ($S).
STEAM_PROBE = r"""CL=""" + CONN_LOG + r"""; S=/scripts/steam-then-game; S=$S.sh
sp=$(pgrep -o -f "^[^ ]*ubuntu12_32/steam( |$)"); [ -n "$sp" ] && echo steam=1 || echo steam=0
pgrep -f "^([^ ]*/)?(env )?([^ ]*/)?(ba)?sh /scripts/steam-then-game[.]sh( |$)" >/dev/null && echo wrapper=1 || echo wrapper=0
[ -x "$S" ] && echo script=1 || echo script=0
echo "now=$(date -u +%s)"
[ -n "$sp" ] && echo "steam_up=$(ps -o etimes= -p "$sp" 2>/dev/null | tr -dc 0-9)"
L=$(grep -E "\[(Logged On|Logged Off|Log Off)" "$CL" 2>/dev/null | tail -1)
echo "last=$(printf %s "$L" | cut -c1-160)"
ts=$(printf %s "$L" | sed -E 's/^\[([0-9-]+ [0-9:]+)\].*/\1/'); echo "last_at=$(date -u -d "$ts" +%s 2>/dev/null || echo 0)"
F=$(grep -E "RecvMsgClientLogOnResponse\(\) : \[[^]]*\] '" "$CL" 2>/dev/null | grep -v "'OK'" | tail -1)
fts=$(printf %s "$F" | sed -E 's/^\[([0-9-]+ [0-9:]+)\].*/\1/'); echo "fail_at=$(date -u -d "$fts" +%s 2>/dev/null || echo 0)"
echo "fail=$(printf %s "$F" | sed -E "s/.*'([^']*)'.*/\1/" | cut -c1-60)"
w=$(DISPLAY=${DISPLAY:-:${DISPLAY_NUM:-99}} xdotool search --onlyvisible --name '""" + LOGIN_WINDOWS + r"""' 2>/dev/null | head -1)
[ -n "$w" ] && echo login_window=1 || echo login_window=0
true"""

ENTRYPOINT = ("D=${DISPLAY:-:${DISPLAY_NUM:-99}}; N=${D#:}; L=/tmp/.X$N-lock; "
              "if [ -e \"$L\" ] && ! kill -0 \"$(tr -dc 0-9 < \"$L\")\" 2>/dev/null; then rm -f \"$L\" \"/tmp/.X11-unix/X$N\"; fi; "   # a dead X's lock
              "mkdir -p /tmp/wc-logs; nohup /usr/local/bin/entrypoint.sh > /tmp/entrypoint.out 2>&1 < /dev/null &")
VNC = ("D=${DISPLAY:-:${DISPLAY_NUM:-99}}; x11vnc -display \"$D\" -rfbport \"${VNC_PORT:-5900}\" -localhost -forever -shared -nopw -noxdamage -quiet "
       "-bg -o /tmp/wc-logs/x11vnc.log >/dev/null 2>&1")
WS = ("V=${NOVNC_PORT:-6080}; W=${WS_PORT:-$((V+2))}; setsid nohup websockify \"127.0.0.1:$W\" \"localhost:${VNC_PORT:-5900}\" "
      "> /tmp/wc-logs/websockify.log 2>&1 < /dev/null &")
VIEWER = ("V=${NOVNC_PORT:-6080}; W=${WS_PORT:-$((V+2))}; XDG_RUNTIME_DIR=/tmp/xdg-runtime VIEWER_PORT=$V WS_UPSTREAM=\"ws://127.0.0.1:$W/websockify\" "
          "setsid nohup python3 /usr/local/bin/viewer.py > /tmp/wc-logs/viewer.log 2>&1 < /dev/null &")
STEAM = ("mkdir -p /tmp/wc-logs; cd /home/player && DISPLAY=${DISPLAY:-:${DISPLAY_NUM:-99}} setsid nohup " + STEAM_START
         + " sleep infinity > " + STEAM_OUT + " 2>&1 < /dev/null &")


def _kv(out) -> dict:
    d = {}
    for line in (out or "").splitlines():
        k, sep, v = line.partition("=")
        if sep and re.fullmatch(r"[a-z_]+", k): d[k] = v.strip()
    return d


def _int(v):
    try: return int(v)
    except (TypeError, ValueError): return 0


# ---------------------------------------------------------------- lease and pool
def parse_lease(s):
    try:
        user, project, rest = (s or "").strip().split("/", 2)
        sandbox, seat = rest.rsplit(":", 1)
    except ValueError: return None
    if not (user and project and sandbox and seat): return None
    return {"user": user, "project": project, "sandbox": sandbox, "seat": int(seat) if seat.isdigit() else seat}


def guard_check(seat, sandbox, lease):
    """(ok, message) from gamebench hosting/lab_guard.py (the broker's leases)."""
    from . import lab
    if lab.gamebench() is None: return False, lab.NO_GAMEBENCH
    h = lab.gamebench() / "hosting"
    if not (h / "lab_guard.py").is_file(): return False, f"no gamebench lab_guard.py at {h} (set GAMEANYTHING_GAMEBENCH)"
    if str(h) not in sys.path: sys.path.insert(0, str(h))
    import lab_guard
    try: ok, msg = lab_guard.decide(lab_guard.load(lab_guard.default_registry()), sandbox, seat, lease)
    except RuntimeError as e: ok, msg = False, str(e)
    if not ok and os.environ.get("M2W_LAB_ADMIN") == "1": return True, f"M2W_LAB_ADMIN=1, although: {msg}"
    return ok, msg


def sandbox_of(pool, name) -> dict:
    sb = dict(((pool or {}).get("sandboxes") or {}).get(name) or {})
    if sb: sb.setdefault("kind", "lab")
    return sb


# ---------------------------------------------------------------- the work
class Run:
    def __init__(self, lease, engine, pool, start, timeout, say, sleep, clock):
        self.lease, self.engine, self.pool, self.start, self.timeout = lease, engine, pool, start, timeout
        self.say, self.sleep, self.clock = say, sleep, clock
        self.checks, self.did = [], []

    def check(self, name, ok, detail=""):
        self.checks = [c for c in self.checks if c["name"] != name] + [{"name": name, "ok": bool(ok), "detail": detail}]

    def result(self, state, why="", why_zh="", **kw):
        l = self.lease or {}
        return {"state": state, "code": CODES[state], "ok": state == "ok", "lease": kw.pop("lease_str", None), "sandbox": l.get("sandbox"),
                "seat": l.get("seat"), "checks": self.checks, "did": self.did, "why": why, "why_zh": why_zh, **kw}


def run(lease_str, start=True, timeout=STEAM_TIMEOUT, engine=None, pool=None, guard=None, env=None, say=None, sleep=time.sleep, clock=time.time,
        why=""):
    """-> the result dict (state ok | failed | refused | needs_her | down | unsupported, checks, did, viewer_port, ...)."""
    from . import buildmode
    env = os.environ if env is None else env
    say = say or (lambda *_: None)
    lease = parse_lease(lease_str)
    R = Run(lease, engine, pool, start, timeout, say, sleep, clock)
    base = {"lease_str": lease_str}
    if not lease:
        return R.result("refused", f"GAMEANYTHING_LEASE is {'not set' if not lease_str else 'malformed: ' + str(lease_str)} (<user>/<project>/<sandbox>:<seat>)",
                        "没有有效的沙箱座位（GAMEANYTHING_LEASE）", **base)
    ok, msg = (guard or guard_check)(lease["seat"], lease["sandbox"], lease_str)
    if not ok: return R.result("refused", f"lease refused: {msg}", "这个座位不是这次构建的（租约对不上）", **base)
    pool = pool if pool is not None else buildmode.pool(env=env)
    sb = sandbox_of(pool, lease["sandbox"])
    if not sb: return R.result("unsupported", f"{lease['sandbox']} is not in the lab pool", "这个沙箱不在沙箱池里", **base)
    if sb["kind"] not in ("lab", "steam"):
        return R.result("unsupported", f"{lease['sandbox']} is a {sb['kind']} sandbox (never ours to prepare)", "这个沙箱不归我们管", **base)
    steam = sb["kind"] == "steam" or bool(sb.get("steam"))
    base.update(kind=sb["kind"], steam=steam, viewer_port=sb.get("viewer_port"))
    R.engine = engine = engine or Engine(env)
    back = getattr(engine, "backend", None) or buildmode.backend(env)
    base["backend"] = back
    if back == "docker":
        if steam:
            return R.result("unsupported", "Steam seats exist only on the maintainer's lab server (docker-rt); plain Docker has no Steam sandbox",
                            "这台电脑的沙箱（普通 Docker）不能跑 Steam 游戏", **base)
        if not engine.answers(): R.check("docker", False, "the Docker engine does not answer"); return R.result("failed", "Docker does not answer", "Docker 没有响应", **base)
        R.check("docker", True, "answers")
        R.check("seat", True, "plain Docker: the game's lab tool starts its own container with `... up` (gamebench hosting/lab/seat.py)")
        return R.result("ok", "", "", **base)
    if back != "docker-rt": return R.result("unsupported", "no lab backend here (no docker-rt socket, no Docker engine)", "这台电脑没有沙箱后端", **base)
    try: return _docker_rt(R, lease, sb, steam, base, why)
    except EnvError as e:
        return R.result("failed", str(e), "沙箱环境没能准备好", **base)


def _probe(R, name, seat_display=None):
    rc, out = R.engine.sh(name, PROBE, env={"SEAT_DISPLAY": seat_display} if seat_display else None)
    if rc != 0 and "x=" not in out: raise EnvError(f"docker exec {name} failed (rc {rc}): {out.strip()[-200:]}")
    return _kv(out)


def _docker_rt(R, lease, sb, steam, base, why):
    name = lease["sandbox"]
    st = R.engine.state(name)
    if st is None: R.check("pod", False, "docker-rt does not answer"); return R.result("failed", "docker-rt does not answer", "服务器沙箱的后台没有响应", **base)
    R.check("pod", st == "up", st)
    if st != "up":
        return R.result("down", f"sandbox {name} is not running (the coordinator recreates it: gamebench hosting/launch_rt/<game>.sh)",
                        f"沙箱 {name} 没有在运行，需要管理员重新开起来", **base)
    seat_display = f":{104 + lease['seat']}" if isinstance(lease["seat"], int) and lease["seat"] >= 2 else None
    p = _probe(R, name, seat_display)
    base.setdefault("display", p.get("display")); base["pod_viewer_port"] = p.get("viewer_port")
    if R.start and p.get("x") != "1":
        R.say(f"[lab env] {name}: X display {p.get('display')} is down: re-running the pod's entrypoint (LAUNCH_GAME=0, no game)")
        rc, out = R.engine.sh(name, ENTRYPOINT, env={"LAUNCH_GAME": "0"})
        if rc != 0: raise EnvError(f"could not re-run the entrypoint in {name}: {out.strip()[-200:]}")
        R.did.append("entrypoint")
        t0 = R.clock()
        while True:
            R.sleep(POLL); p = _probe(R, name, seat_display)
            if (p.get("x") == "1" and p.get("viewer") == "1") or R.clock() - t0 > X_WAIT: break
    if R.start and p.get("x") == "1":
        for k, cmd in (("vnc", VNC), ("ws", WS), ("viewer", VIEWER)):
            if p.get(k) != "1":
                R.say(f"[lab env] {name}: {k} is down: starting it again")
                R.engine.sh(name, cmd); R.did.append(k); R.sleep(2); p = _probe(R, name, seat_display)
    R.check("display", p.get("x") == "1", p.get("display") or "")
    viewer_ok = all(p.get(k) == "1" for k in ("vnc", "ws", "viewer"))
    R.check("viewer", viewer_ok, " ".join(f"{k} {'up' if p.get(k) == '1' else 'down'}" for k in ("vnc", "ws", "viewer")))
    if seat_display:
        R.check("seat_display", True, f"{seat_display} {'up' if p.get('seat_x') == '1' else 'down (the lab tool brings it up: lab-display.sh ' + str(lease['seat']) + ' up)'}")
    if p.get("x") != "1" or not viewer_ok:
        return R.result("failed", f"{name}: " + "; ".join(f"{c['name']} {c['detail']}" for c in R.checks if not c["ok"]),
                        "沙箱的画面（显示器 / 查看器）没有起来", **base)
    if not steam: return R.result("ok", "", "", **base)
    return _steam(R, name, base, why)


def _steam_probe(R, name):
    rc, out = R.engine.sh(name, STEAM_PROBE)
    d = _kv(out)
    if "steam" not in d: raise EnvError(f"docker exec {name} failed (rc {rc}): {out.strip()[-200:]}")
    return d


def _steam_since(s):
    """When the running Steam client started (pod clock, epoch s; 0 = unknown). A log-on line older than that is from an earlier
    client (connection_log.txt survives pod restarts: an OOM-killed client never writes its Log Off, so its old [Logged On stays last)."""
    up = s.get("steam_up")
    if s.get("steam") != "1" or up in (None, ""): return 0
    return max(_int(s.get("now")) - _int(up) - 2, 1)                   # 2 s: ps etimes vs the log's whole seconds


def _logged_on(s, since=0):
    """The client runs and the newest log-on line was written after `since` and after this client started."""
    return (s.get("steam") == "1" and "Logged On" in (s.get("last") or "")
            and _int(s.get("last_at")) >= max(since, _steam_since(s), 1))


def _last_line(s, since=0):
    last = s.get("last") or ""
    if not last: return "no log-on line"
    return last if _int(s.get("last_at")) >= max(since, _steam_since(s), 1) else f"no log-on since the start; last line from before: {last}"


def _steam(R, name, base, why):
    s = _steam_probe(R, name)
    view = f"viewer port {base.get('viewer_port') or base.get('pod_viewer_port')}"
    her = (f"Steam in {name} needs her: log in once through the sandbox viewer ({view}); the password / Steam Guard code is hers, "
           "nobody types it for her")
    her_zh = (f"沙箱 {name} 里的 Steam 需要她登录一次：打开这个沙箱的画面（{view}），在 Steam 窗口里登录"
              "（密码 / Steam 令牌验证码只有她自己输入）。登录好以后构建会自动开始")
    if _logged_on(s):
        R.check("steam", True, f"running, logged on ({s.get('last')})"); return R.result("ok", "", "", **base)
    if s.get("steam") == "1" and s.get("login_window") == "1":
        R.check("steam", False, "a Steam sign-in window is open"); return R.result("needs_her", her, her_zh, **base)
    if not R.start:
        R.check("steam", False, "running, not logged on" if s.get("steam") == "1" else "not running")
        return R.result("failed", f"Steam {'is not logged on' if s.get('steam') == '1' else 'is not running'} in {name} (`gameanything lab env up` starts it)",
                        "沙箱里的 Steam 没有开", **base)
    since = _int(s.get("now"))
    if s.get("steam") != "1" and s.get("wrapper") != "1":
        if s.get("script") != "1":
            R.check("steam", False, f"not running; no {STEAM_START} in the sandbox")
            return R.result("unsupported", f"{name} has no {STEAM_START}: start Steam by hand", "这个沙箱没有启动 Steam 的脚本", **base)
        R.say(f"[lab env] {name}: Steam is not running: starting it in the background ({STEAM_START} sleep infinity; no game)"
              + (f"; consent: {why}" if why else ""))
        rc, out = R.engine.sh(name, STEAM)
        # 124: the docker client timed out (docker-rt can keep an exec open while a child holds a stream); the start may well have
        # taken (Steam survived such a timeout by hand, 2026-10-27): the probes below tell, a client that never appears is `failed`.
        if rc == 124: R.say(f"[lab env] {name}: the start exec did not return in time; checking whether Steam came up anyway")
        elif rc != 0: raise EnvError(f"could not start Steam in {name}: {out.strip()[-200:]}")
        R.did.append("steam")
    else:                                                              # Steam (or its wrapper) runs already: only log-ons of
        since = 0                                                      # this client count (_steam_since), never restarted here
        R.say(f"[lab env] {name}: Steam {'is running' if s.get('steam') == '1' else 'start script is running (no client yet)'}"
              " but not logged on yet: waiting (never restarted here)")
    t0 = R.clock(); last_say = t0
    while True:
        R.sleep(POLL); s = _steam_probe(R, name)
        if _logged_on(s, since):
            R.check("steam", True, f"logged on ({s.get('last')})"); R.say(f"[lab env] {name}: Steam logged on")
            return R.result("ok", "", "", **base)
        if s.get("login_window") == "1" or (s.get("fail") and _int(s.get("fail_at")) >= max(since, _steam_since(s), 1)):
            R.check("steam", False, "sign-in window open" if s.get("login_window") == "1" else f"log-on refused: {s.get('fail')}")
            return R.result("needs_her", her, her_zh, **base)
        if R.clock() - t0 > R.timeout:
            R.check("steam", False, f"{'running' if s.get('steam') == '1' else 'not running'}, not logged on after {R.timeout:g} s ({_last_line(s, since)})")
            if s.get("steam") != "1":
                return R.result("failed", f"the Steam client did not stay up in {name} (see {STEAM_OUT} there)", "沙箱里的 Steam 没能开起来", **base)
            return R.result("needs_her", her, her_zh, **base)
        if R.clock() - last_say >= 30: R.say(f"[lab env] {name}: waiting for Steam to log on ... {int(R.clock() - t0)} s"); last_say = R.clock()


# ---------------------------------------------------------------- the command
def resident_run(env=None) -> bool:
    """An agentd run that is not a builder (a resident): may not touch the lab environment."""
    env = os.environ if env is None else env
    return bool(env.get("GAMEANYTHING_INSTANCE")) and env.get("GAMEANYTHING_ROLE") != "builder"


def main(argv) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="gameanything lab env", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["up", "status"])
    ap.add_argument("--lease", default=None, help="the seat: <user>/<project>/<sandbox>:<seat> (default $GAMEANYTHING_LEASE)")
    ap.add_argument("--timeout", type=float, default=STEAM_TIMEOUT, help=f"up: seconds to wait for Steam to log on (default {STEAM_TIMEOUT})")
    ap.add_argument("--why", default="", help="up: why Steam may be started (logged), e.g. 'build m8 of P, go card c12 (she pressed 开工)'")
    ap.add_argument("--json", action="store_true", help="print the result as JSON (one object)")
    a = ap.parse_args(argv)
    if resident_run():
        print("[lab env] 常驻 agent 不能动沙箱环境：构建 agent（builder）或管理员才可以。请把需要告诉她 / 交给构建。", file=sys.stderr); return CODES["refused"]
    lease = a.lease or os.environ.get("GAMEANYTHING_LEASE") or ""
    say = (lambda m: print(m, file=sys.stderr, flush=True)) if a.json else (lambda m: print(m, flush=True))
    r = run(lease, start=a.what == "up", timeout=a.timeout, say=say, why=a.why)
    if a.json: print(osdirs.json_text(r)); return r["code"]
    print(f"[lab env] {r.get('sandbox') or '?'} seat {r.get('seat')} ({r.get('backend') or '-'}, {r.get('kind') or '-'}): {r['state'].upper()}"
          + (f"  viewer port {r['viewer_port']}" if r.get("viewer_port") else ""))
    for c in r["checks"]: print(f"  {'ok  ' if c['ok'] else 'DOWN'} {c['name']}: {c['detail']}")
    if r["did"]: print(f"  started: {', '.join(r['did'])}")
    if r["why"]: print(f"  {r['why']}")
    return r["code"]
