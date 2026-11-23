"""The gate: how an isolated agent run (isolation.py) writes what it must not forge (docs/agent-isolation.md, "The request channel").

    agent (ga-<user>)  --  gameanything chat say ... -->  cli.main sees client mode, sends the command line here
    agentd (service)   --  unix socket <agent root>/gate/agent.sock (root:ga-agents 0660)
                           1. SO_PEERCRED: the caller's pid and uid (the kernel's, not the caller's word)
                           2. the run: the caller is a descendant of a live agentd run (resident or builder) of the account's project
                           3. the command: an allowed one (ALLOW), with allowed flags only; --project and --session are the run's,
                              files the agent names are sent as bytes (never read by the service account)
                           4. runs it as the service account (GAMEANYTHING_GATE_FORWARDED=1, session / instance / role of the run),
                              which writes conversation/ and stamps `from: agent`, `via: gate`, `run: <run id>`
    <-- {code, stdout, stderr}

What never comes through: `chat say --user` (her words), `--force`, `--session`, another project, `agentd run`, card answers,
decisions, a lease that is not the run's. Card answers and decisions come only from the page server (decisions.py signs them).
"""
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import isolation

MAX_REQ = 32 << 20
MAX_SECS = 4 * 3600
FILE_FLAGS = {"--file", "--chapters", "--attach"}          # their values are files: sent as bytes by the client
# (command, subcommand) -> allowed flags; roles that may use it (None = every role)
ALLOW = {
    ("chat", "claim"): ({"--project"}, ("resident",)),
    ("chat", "wait"): ({"--project", "--listen", "--timeout"}, ("resident",)),
    ("chat", "read"): ({"--project"}, ("resident",)),
    ("chat", "idle"): ({"--project"}, ("resident",)),
    ("chat", "release"): ({"--project"}, ("resident",)),
    ("chat", "say"): ({"--project", "--text", "--text-en", "--attach"}, ("resident",)),
    ("chat", "card"): ({"--project", "--file", "--text", "--text-en"}, ("resident",)),
    ("chat", "progress"): ({"--project", "--key", "--milestone", "--title", "--steps", "--title-en", "--steps-en"}, ("resident",)),
    ("agentd", "request"): ({"--project", "--kind", "--text", "--details"}, ("resident", "builder")),
    ("agentd", "notify"): ({"--project", "--text", "--from"}, ("builder",)),
    ("gen", "request"): ({"--project", "--tool", "--permission", "--permission-key", "--go", "--go-key", "--arg", "--inputs", "--prompt",
                          "--image", "--name", "--n", "--out", "--model", "--option", "--redo"}, ("resident", "builder")),
    ("refs", "fetch"): ({"--project", "--place", "--url", "--query", "--consent", "--page", "--license", "--author", "--side", "--wait"},
                        ("resident", "builder")),
    ("build", "status"): ({"--project", "--m", "--round", "--max", "--step", "--step-en", "--started", "--done", "--blocked"}, ("resident", "builder")),
    ("build", "deliver"): ({"--project", "--m", "--name", "--what", "--chapters"}, ("builder", "resident")),
    ("lessons", "add"): ({"--game", "--role", "--symptom", "--cause", "--fix", "--evidence", "--confidence", "--local", "--general", "--project"},
                         ("builder", "resident")),
    ("lessons", "show"): ({"--game", "--role", "--json"}, ("builder", "resident")),
    ("lab", "env"): ({"--json", "--why"}, ("builder",)),
    ("lab", "heartbeat"): (set(), ("builder",)),
    ("lab", "run"): (None, ("builder",)),                  # a lab tool of the allowlist (lab_tools()), with the run's lease
}
FORWARD = {c for c, _ in ALLOW}
BOOL_FLAGS = {"--listen", "--done", "--redo", "--json", "--local", "--general"}
MULTI_FLAGS = {"--attach", "--steps", "--steps-en"}
PROJECT_PATH_FLAGS = {"--inputs", "--image"}


def _value(flag, v):
    """A value the service account would open: only a file the agent sent (@gate:N), or a plain path inside the project."""
    if flag in FILE_FLAGS and not v.startswith("@gate:"): raise GateError(f"{flag} takes a file the gate received")
    if flag == "--details" and v.startswith("@") and not v.startswith("@@gate:"): raise GateError("--details @file: the gate reads only files it received")
    if flag in PROJECT_PATH_FLAGS and (v.startswith(("/", "~", "\\")) or ".." in v.replace("\\", "/").split("/")):
        raise GateError(f"{flag} takes a path inside the project")


class GateError(Exception):
    pass


# ---------------------------------------------------------------- the client (an agent's `gameanything ...`)
def wanted(argv) -> bool:
    return bool(argv) and argv[0] in FORWARD and (argv[0], argv[1] if len(argv) > 1 else "") in ALLOW


def _pack(d) -> bytes:
    b = json.dumps(d).encode(); return struct.pack(">I", len(b)) + b


def _unpack(sock):
    h = _recv(sock, 4)
    if not h: return None
    n = struct.unpack(">I", h)[0]
    if n > MAX_REQ: raise GateError("request too large")
    return json.loads(_recv(sock, n).decode())


def _recv(sock, n):
    buf = b""
    while len(buf) < n:
        c = sock.recv(min(1 << 20, n - len(buf)))
        if not c: break
        buf += c
    return buf


def _client_files(argv):
    """argv with the values of FILE_FLAGS (and --details @file) replaced by @gate:N; -> (argv, files) — the agent's own read of the file."""
    out, files, i, cur = [], [], 0, None
    def add(p):
        files.append({"name": os.path.basename(p), "orig": os.path.abspath(p), "data": base64.b64encode(Path(p).read_bytes()).decode()})
        return f"@gate:{len(files) - 1}"
    while i < len(argv):
        t = argv[i]
        if t.startswith("--"):
            flag, eq, val = t.partition("=")
            cur = flag if flag in FILE_FLAGS else None
            if flag == "--details" and eq and val.startswith("@"): out.append(f"--details=@{add(val[1:])}"); cur = None; i += 1; continue
            if flag == "--details" and not eq and i + 1 < len(argv) and argv[i + 1].startswith("@"):
                out += ["--details", "@" + add(argv[i + 1][1:])]; i += 2; continue
            if cur and eq: out.append(f"{flag}={add(val)}"); cur = None if flag != "--attach" else cur; i += 1; continue
            out.append(t); i += 1; continue
        if cur: out.append(add(t)); cur = cur if cur == "--attach" else None
        else: out.append(t)
        i += 1
    return out, files


def call(argv, stdin=None) -> int:
    """Send one command to the gate and print what it printed. -> its exit code."""
    argv, files = _client_files(list(argv))
    if argv[:2] == ["chat", "say"] and not any(a == "--text" or a.startswith("--text=") for a in argv) and stdin is None:
        stdin = sys.stdin.read() if not sys.stdin.isatty() else ""
    p = isolation.gate_path()
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try: s.connect(str(p))
    except OSError as e:
        print(f"[gameanything] 这个命令要经过后台（agentd）的门：{p} 连不上（{e.strerror}）。后台没在运行时，对话和请求都写不进去。", file=sys.stderr)
        return 75
    try:
        s.sendall(_pack({"argv": argv, "stdin": stdin, "files": files, "cwd": os.getcwd()}))
        r = _unpack(s) or {"error": "the gate closed the connection"}
    finally: s.close()
    if r.get("error"):
        print(f"[gameanything] 门拒绝了这个命令：{r['error']}", file=sys.stderr); return 77
    if r.get("stdout"): sys.stdout.write(r["stdout"])
    if r.get("stderr"): sys.stderr.write(r["stderr"])
    return int(r.get("code") or 0)


def maybe_forward(argv):
    """cli.main in client mode: -> exit code of the forwarded command, or None (the command runs here, as the agent)."""
    if not wanted(argv): return None
    return call(argv)


# ---------------------------------------------------------------- the policy (pure: tests call it directly)
def check_argv(argv, run) -> list:
    """-> the argv the service account runs (the run's --project, no --session), or raises GateError."""
    if not argv or len(argv) < 2: raise GateError("no command")
    key = (argv[0], argv[1])
    if key not in ALLOW: raise GateError(f"`{' '.join(key)}` is not a command an agent run may send")
    flags, roles = ALLOW[key]
    role = run.get("role") or "resident"
    if roles and role not in roles: raise GateError(f"`{' '.join(key)}` is not for a {role} run")
    if key == ("lab", "run"): return list(argv)
    rest = argv[2:]
    if key == ("lab", "env"):
        if not rest or rest[0] not in ("up", "status"): raise GateError("lab env: up | status")
        rest = rest[1:]
    out, i, cur = list(argv[:2]) + (argv[2:3] if key == ("lab", "env") else []), 0, None
    while i < len(rest):
        t = rest[i]
        if t.startswith("-") and t != "-":
            flag, eq, val = t.partition("=")
            if flag not in flags: raise GateError(f"flag {flag} is not allowed here")
            if flag in ("--project", "--from"):                # the run's project / sender is used
                i += 1 if eq else 2; cur = None; continue
            cur = flag if flag not in BOOL_FLAGS else None
            if eq: _value(flag, val); cur = cur if flag in MULTI_FLAGS else None
            out.append(t); i += 1; continue
        if cur: _value(cur, t); cur = cur if cur in MULTI_FLAGS else None
        out.append(t); i += 1
    if key == ("lessons", "show"): pass
    elif key[0] != "lab" or key == ("lab", "heartbeat"): out += ["--project", str(run["root"])]
    if key == ("agentd", "notify"): out += ["--from", "builder"]
    if key[0] == "lab":
        if not run.get("lease"): raise GateError("this run has no lab seat")
        if key == ("lab", "env"): out += ["--lease", str(run["lease"])]
    return out


def lab_tools() -> list:
    """The lab tools a builder may start through the gate: settings `agent_lab_tools`, else gamebench's launch_rt scripts and lab tools."""
    s = isolation._settings().get("agent_lab_tools")
    if isinstance(s, list): return [str(Path(x)) for x in s]
    from .lab import gamebench
    if gamebench() is None: return []
    g = gamebench() / "hosting"
    return sorted(str(p) for d in (g / "launch_rt", g / "lab") if d.is_dir() for p in d.iterdir() if p.is_file())


# ---------------------------------------------------------------- the server (a thread of agentd)
def _ancestors(pid) -> list:
    out = []
    for _ in range(64):
        out.append(pid)
        try: ppid = int(open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace").read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError): break
        if ppid <= 1: break
        pid = ppid
    return out


class Gate:
    """lookup(pids) -> the run record {root, project, session, run_id, role, account, lease?, tmp?} whose process is one of `pids`, or None."""

    def __init__(self, lookup, log=print, path=None, runner=None):
        self.lookup, self.log = lookup, log
        self.path = Path(path or isolation.gate_path())
        self.runner = runner or self._run
        self.sock = None; self.stop = False

    def start(self):
        d = self.path.parent; d.mkdir(parents=True, exist_ok=True)
        g = isolation.group_gid()
        try:
            os.chown(d, isolation.service_uid(), g if g is not None else -1); os.chmod(d, 0o750 if g is not None else 0o711)
        except OSError: pass
        try: self.path.unlink()
        except FileNotFoundError: pass
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.bind(str(self.path))
        os.chmod(self.path, 0o660 if g is not None else 0o666)
        if g is not None: os.chown(self.path, isolation.service_uid(), g)
        s.listen(32); self.sock = s
        threading.Thread(target=self._loop, daemon=True, name="gate").start()
        self.log(f"gate listening on {self.path}")
        return self

    def close(self):
        self.stop = True
        try: self.sock.close()
        except Exception: pass

    def _loop(self):
        while not self.stop:
            try: c, _ = self.sock.accept()
            except OSError:
                if self.stop: return
                time.sleep(0.2); continue
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c):
        try:
            cred = c.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            pid, uid, gid = struct.unpack("3i", cred)
            try: req = _unpack(c)
            except (GateError, ValueError) as e: c.sendall(_pack({"error": str(e)})); return
            if not isinstance(req, dict): c.sendall(_pack({"error": "bad request"})); return
            try: resp = self.handle(pid, uid, req)
            except GateError as e:
                resp = {"error": str(e)}; self.log(f"gate refused uid {uid} pid {pid}: {e}")
            c.sendall(_pack(resp))
        except Exception as e:
            try: c.sendall(_pack({"error": f"{type(e).__name__}"}))
            except OSError: pass
            self.log(f"gate error: {type(e).__name__}: {e}")
        finally:
            try: c.close()
            except OSError: pass

    def handle(self, pid, uid, req) -> dict:
        acct = isolation.account_of_uid(uid)
        if not acct or uid == isolation.service_uid(): raise GateError("only agent accounts use the gate")
        run = self.lookup(_ancestors(pid))
        if not run: raise GateError("not inside a live agentd run")
        if run.get("account") != acct: raise GateError("this run belongs to another account")
        argv = check_argv([str(a) for a in req.get("argv") or []], run)
        tmp = Path(tempfile.mkdtemp(prefix="ga-gate-")); os.chmod(tmp, 0o700)
        try:
            argv = self._files(argv, req.get("files") or [], tmp, run)
            r = self.runner(argv, run, req.get("stdin"))
        finally: shutil.rmtree(tmp, ignore_errors=True)
        self.log(f"gate: {acct} {run.get('project')} {run.get('role')} {' '.join(argv[:2])} -> {r.get('code')}")
        return r

    def _files(self, argv, files, tmp, run):
        total = 0; paths = []
        for i, f in enumerate(files):
            data = base64.b64decode(str(f.get("data") or ""))
            total += len(data)
            if total > MAX_REQ: raise GateError("files too large")
            orig = str(f.get("orig") or "")
            try:
                from . import agent_providers
                other = agent_providers.run_tmp_project(orig)
            except Exception: other = None
            if other and other != run.get("project"): raise GateError("that file is in another project's run folder")
            name = os.path.basename(str(f.get("name") or f"file{i}")) or f"file{i}"
            d = tmp / str(i); d.mkdir(); p = d / name; p.write_bytes(data); paths.append(str(p))
        out = []
        for a in argv:
            for i, p in enumerate(paths):
                a = a.replace(f"@gate:{i}", p)
            out.append(a)
        return out

    def _run(self, argv, run, stdin):
        from . import users
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GAMEANYTHING_SESSION", "GAMEANYTHING_INSTANCE", "GAMEANYTHING_ROLE"))
               and not users.CRED_RE.match(k)}
        env.update({isolation.FORWARDED_ENV: "1", "GAMEANYTHING_SESSION": str(run.get("session") or ""), "GAMEANYTHING_INSTANCE": str(run.get("run_id") or ""),
                    "GAMEANYTHING_ROLE": "builder" if run.get("role") == "builder" else "resident", "GAMEANYTHING_GATE_RUN": str(run.get("run_id") or "")})
        if run.get("role") != "builder": env.pop("GAMEANYTHING_ROLE", None)
        if run.get("tmp"): env["GAMEANYTHING_RUN_TMP"] = str(run["tmp"])
        if run.get("lease"): env["GAMEANYTHING_LEASE"] = env["M2W_LEASE"] = str(run["lease"])
        if argv[:2] == ["lab", "run"]:
            tool = argv[2] if len(argv) > 2 else ""
            ok = {str(Path(x).resolve()) for x in lab_tools()}
            try: rt = str(Path(tool).resolve())
            except OSError: rt = ""
            if rt not in ok: raise GateError("not a lab tool of the allowlist")
            if not run.get("lease"): raise GateError("this run has no lab seat")
            cmd = [rt, *argv[3:]] if os.access(rt, os.X_OK) else [sys.executable if rt.endswith(".py") else "bash", rt, *argv[3:]]
        else:
            cmd = [sys.executable, "-m", "gameanything", *argv]
            code = str(Path(__file__).resolve().parents[1])            # this very code (a clone / a worktree), never the agent's folder:
            env["PYTHONPATH"] = code + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")   # cwd is an empty root-only folder
        timeout = MAX_SECS
        if argv[:2] == ["chat", "wait"]: timeout = 4000
        cwd = tempfile.mkdtemp(prefix="ga-gate-cwd-"); os.chmod(cwd, 0o700)
        try:
            p = subprocess.run(cmd, cwd=cwd, env=env, input=stdin if isinstance(stdin, str) else None, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=timeout)
            return {"code": p.returncode, "stdout": p.stdout[-200000:], "stderr": p.stderr[-50000:]}
        except subprocess.TimeoutExpired:
            return {"code": 124, "stdout": "", "stderr": "[gate] timed out"}
        finally: shutil.rmtree(cwd, ignore_errors=True)
