"""Auto builds: `gameanything agentd run --builds auto` (env GAMEANYTHING_BUILDS; the default) runs build requests itself, no coordinator session needed.

A resident run writes a build_start request (`gameanything agentd request --kind build_start`, <requests dir>/<project>-<time>.json, kept there for a
coordinator to see). Every scan agentd (builds.Builds.scan, one project at a time):
  - checks the request: details.milestone, the go card (details.go_key) is a `go` card she pressed 开工 on, that go card has not started an
    auto build before; refused -> a note to the resident with the reason in plain Chinese (it tells her);
  - skips a NEW request whose build is already run by someone else: a lab lease of the project that agentd did not take (the coordinator's
    `gameanything lab acquire`), or a 5_build/<m>/build_status.yaml (`gameanything build status`) that is not done and changed in the last FOREIGN_FRESH_SECS.
    Such a request is left to whoever runs that build (state `elsewhere`), never started later;
  - a build agentd already took that waits (`blocked`, `waiting_seat`) while the project has a lease agentd did not take (the coordinator
    repairing the environment): stays `blocked`, asked again every SEAT_RETRY_SECS, and goes on once that lease is released (unless
    build_status.yaml says someone else finished it meanwhile -> `elsewhere`). `gameanything build resume --project P --m mN` hands a waiting /
    `elsewhere` build back at once; `gameanything build takeover` makes it the coordinator's for good;
  - lab mode: takes a seat from the lab broker (gamebench hosting/broker.py, user = the project owner or $M2W_LAB_USER); no seat free ->
    `waiting_seat`, one note to the resident (her place in the queue), asked again every SEAT_RETRY_SECS; no lab here / the pool cannot run
    the game -> `blocked`, one note with the reason, looked at again every BLOCKED_RETRY_SECS. Native mode needs no seat;
  - lab mode with a seat: `gameanything lab env up` for that lease first (labup.py, in the background: pod, X display + viewer, on a Steam sandbox
    the Steam client logged on; her 开工 on the go card covers starting Steam in that sandbox, never a game). state `preparing` while it
    runs; Steam needs her login -> `blocked`, the lease released, one note telling her how to log in (the viewer port), tried again every
    ENV_RETRY_SECS; any other failure -> `blocked`, tried again the same way. The go card stays this request's: it is not used up;
  - starts ONE headless builder run per project (the same provider as the residents, the owner's login, paid keys stripped:
    agent_providers.agent_env) with core.md + the mode doc + roles/builder.md as its system prompt, GAMEANYTHING_LEASE / MC_N of the seat in its env;
  - while it runs: lease heartbeat, rounds from build_status.yaml, build_change requests appended to 5_build/<m>/build_changes.yaml (the
    builder reads it every round; a higher playtest_rounds raises the limit), stopped after wall_hours (+10 %);
  - when it ends in lab mode without a delivered build, and either the builder said the environment is gone (`gameanything build status --blocked
    REASON`) or `gameanything lab env status` of its lease now says so (the m8 case: Steam gone after a pod restart, builder ended rc 0 with a
    「卡住了」 note): the build is NOT over. It goes back to `blocked` (lease released), env up is retried every ENV_RETRY_SECS and the
    builder is started again with a resume note pointing at the previous log (at most MAX_RESUMES times). A new build_start of the same go
    card while a build waits (the resident asking again) is merged into it and retried at once, never refused as a used card;
  - when it ends: the lease is released, build_status.yaml done, and unless the builder sent its own note in its last minutes, agentd tells
    the resident the outcome (`gameanything build check` passed -> post the result card; else what is missing).
A build that was running when agentd restarted and whose process is gone is reported to the resident as interrupted (delivered ones as
done) and never re-run. Requests from before auto builds were first switched on (<data>/agentd-builds.json `since`) are never run.
Files: 5_build/<m>/.build_run.json (the build: state, pid, started, rounds, lease, log), conversation/.agentd_builds.json (what was decided
for each request; the go cards used). `--builds coordinator`: the old behaviour (requests only wait for a coordinator).
"""
import json
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

from . import clock
from . import agent_providers, envcompat, osdirs, projects, shipped, users
from .conversation import now

MODES = ("auto", "coordinator")
KINDS = ("build_start", "build_change")
ACTIVE = ("waiting_seat", "blocked", "preparing", "running")
SEAT_RETRY_SECS = 60
BLOCKED_RETRY_SECS = 600
ENV_RETRY_SECS = 300                          # env up again (Steam login, pod back) after this
ENV_UP_MAX_SECS = 15 * 60                     # an env up job running longer is stopped (exact pid) and counts as failed
MAX_RESUMES = 3                               # a builder restarted after an environment block at most this often per request
HEARTBEAT_SECS = 20 * 60
FOREIGN_FRESH_SECS = 2 * 3600
OWN_NOTE_SECS = 15 * 60                      # the builder's own note this close to its end: agentd adds none
WALL_HOURS = 5
ROLE = shipped.SKILL / "roles" / "builder.md"
CACHES = (".nuget", ".dotnet", ".gradle", ".m2", ".cache", ".local/share/NuGet")    # toolchain caches a build writes (Codex add-dir)


def mode(env=None) -> str:
    m = ((env if env is not None else os.environ).get("GAMEANYTHING_BUILDS") or "auto").strip().lower()
    if m not in MODES: raise ValueError(f"GAMEANYTHING_BUILDS / --builds 应该是 {' / '.join(MODES)}")
    return m


def _read(p: Path):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError): return None


def _write(p: Path, d):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True); tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8"); os.replace(tmp, p)


def _ts(s) -> float:
    try: return clock.epoch(s)
    except (TypeError, ValueError): return 0.0


def run_file(root, m) -> Path: return Path(root) / "5_build" / m / ".build_run.json"


def index_file(root) -> Path: return Path(root) / "conversation" / ".agentd_builds.json"


def records(root) -> list:
    """[(milestone, record)] of every auto build of the project (5_build/*/.build_run.json). With isolation on only the records agentd
    wrote itself (5_build is the agent's folder: a record it made up, with another pid or lease, is not one)."""
    from . import isolation
    B = Path(root) / "5_build"
    return [(f.parent.name, r) for f in sorted(B.glob("*/.build_run.json")) if isolation.trusted(f) for r in [_read(f)] if isinstance(r, dict)] if B.is_dir() else []


def current(root):
    """(milestone, record) of the project's build that is waiting or running, else (None, None)."""
    for m, r in records(root):
        if r.get("state") in ACTIVE: return m, r
    return None, None


def baseline() -> str:
    """When auto builds were first switched on in this data folder: older requests belong to whoever handled them then."""
    f = projects.data_dir() / "agentd-builds.json"; d = _read(f) or {}
    if not d.get("since"): d = {"since": now(), "note": "requests older than `since` are never run by agentd (they were for the coordinator)"}; _write(f, d)
    return d["since"]


def _m_ok(m) -> bool: return isinstance(m, str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,40}", m))


def _rounds(d: dict, text=""):
    """playtest_rounds from a request's details (an int, or the change text 'playtest_rounds: 1 -> 3'), else None."""
    v = (d or {}).get("playtest_rounds")
    if isinstance(v, int) and 0 <= v <= 50: return v
    if isinstance(v, str) and v.isdigit(): return int(v)
    m = re.search(r"playtest_rounds\D*?(\d+)(?:\s*(?:->|→|到|to)\s*(\d+))?", f"{(d or {}).get('change') or ''} {text}")
    return int(m.group(2) or m.group(1)) if m else None


# ---------------------------------------------------------------- the lab broker (gamebench hosting/broker.py), or no lab
class Lab:
    """Seats for lab builds. ready(game) -> (ok, why, pooled); pooled False = a lab without a seat broker (the lab tools run unguarded)."""

    def __init__(self, env=None):
        self.env = os.environ if env is None else env; self._b = None

    def broker(self):
        if self._b is None:
            from . import lab
            g = lab.gamebench()
            if g is None or not (g / "hosting" / "broker.py").is_file(): return None
            h = g / "hosting"
            if str(h) not in sys.path: sys.path.insert(0, str(h))
            import broker
            self._b = broker
        return self._b

    def ready(self, game):
        from . import buildmode, games as registry
        if osdirs.system() != "linux": return False, "服务器沙箱只在 Linux 服务器上有，这台电脑是别的系统", False
        if buildmode.own_sandbox(self.env):          # the user's own sandbox (labsandbox.py): no seats, the builder starts it itself
            if not buildmode.docker_ok(self.env): return False, "这台电脑上的 Docker 没有回应", False
            if game not in buildmode.own_sandbox_games(): return False, "沙箱还不能做这个游戏", False
            return True, "", False
        if not buildmode.lab_kit(self.env): return False, "这台电脑没有配好服务器沙箱（gamebench 实验室）", False
        if not registry.lab_supported(game): return False, "服务器沙箱还不能做这个游戏", False
        pool = buildmode.pool(env=self.env)
        if not buildmode.lab_runs(game, pool, buildmode.lab_scripts(self.env) if pool is None else None):
            return False, "服务器沙箱跑不了这个游戏（沙箱池里没有能跑它的位置）", False
        return True, "", pool is not None and self.broker() is not None

    def pool_game(self, game):
        from . import buildmode
        return buildmode.POOL_NAME.get(game, game)

    def acquire(self, user, project, game):
        b = self.broker()
        try: return b.acquire(user, project, self.pool_game(game))
        except b.BrokerError as e: raise ValueError(str(e))

    def release(self, project, user):
        b = self.broker()
        try: b.release(project, user)
        except b.BrokerError: pass

    def heartbeat(self, project, user):
        b = self.broker()
        try: b.heartbeat(project, user)
        except b.BrokerError: pass

    def leases(self, project) -> list:
        b = self.broker()
        if b is None: return []
        try: doc = b.read()
        except Exception: return []
        return [l for l in (doc or {}).get("leases") or [] if l.get("project") == project and l.get("state") in ("active", "queued")]

    def lease_str(self, l) -> str:
        return f"{l['user']}/{l['project']}/{l['sandbox']}:{l['seat']}"

    # `gameanything lab env up` for a lease, as a background job (it may wait minutes for Steam): agentd's scan never blocks on it
    def env_up_start(self, lease, why, out) -> dict:
        import subprocess
        out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in self.env.items() if k not in (*envcompat.names("INSTANCE", "ROLE"), "M2W_LAB_ADMIN")}
        pkg = str(Path(__file__).resolve().parent.parent); env["PYTHONPATH"] = pkg + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        with open(out, "wb") as o, open(out.with_suffix(".log"), "ab") as err:
            p = subprocess.Popen([sys.executable, "-m", "gameanything", "lab", "env", "up", "--lease", lease, "--json", "--why", why],
                                 stdin=subprocess.DEVNULL, stdout=o, stderr=err, env=env, start_new_session=True)
        self.jobs = getattr(self, "jobs", {}); self.jobs[p.pid] = p
        return {"pid": p.pid, "pid_start": osdirs.pid_start(p.pid), "out": str(out), "at": datetime.now().timestamp()}

    def env_up_result(self, job):
        """None while the job runs, else its result dict (labup.run)."""
        p = getattr(self, "jobs", {}).get(job.get("pid"))
        if p is not None:
            if p.poll() is None: return None
            self.jobs.pop(job["pid"], None)
        elif osdirs.pid_alive(job.get("pid"), job.get("pid_start")): return None
        try: d = json.loads(Path(job["out"]).read_text(encoding="utf-8").strip().splitlines()[-1])
        except (OSError, ValueError, IndexError): d = None
        return d if isinstance(d, dict) and d.get("state") else {"state": "failed", "why": f"env up ended without a result (see {job.get('out')})", "why_zh": ""}

    def env_up_stop(self, job):
        if osdirs.pid_alive(job.get("pid"), job.get("pid_start")): osdirs.stop_group(job["pid"])

    def env_status(self, lease) -> dict:
        from . import labup
        try: return labup.run(lease, start=False, env=self.env)
        except Exception as e: return {"state": "failed", "why": f"{type(e).__name__}: {e}", "why_zh": ""}


# ---------------------------------------------------------------- the coordinator's hand: `gameanything build resume | takeover`
def resume(root, m) -> dict:
    """Hand a build back to agentd: a `blocked` / `waiting_seat` one is tried again at the next scan, one marked `elsewhere` (an older
    agentd let go of it when the coordinator took a lease to repair the environment) waits again as `blocked`. Release your own lab
    lease first (`gameanything lab release`): agentd waits while the project has a lease it did not take."""
    f = run_file(root, m); r = _read(f)
    if not isinstance(r, dict): raise ValueError(f"5_build/{m}/.build_run.json 不存在：agentd 没有接过这一期的构建")
    if r.get("state") in ("running", "preparing"): raise ValueError(f"{m} 的构建正在{'跑' if r['state'] == 'running' else '准备环境'}，不用交还")
    if r.get("state") not in ("blocked", "waiting_seat", "elsewhere"):
        raise ValueError(f"{m} 的构建已经是 {r.get('state')}（结束了），不能再交还；要再做一期请发新的开工卡")
    om, other = current(root)
    if other is not None and om != m: raise ValueError(f"这个项目已经有一个在等 / 在跑的构建（{om}，{other.get('state')}）")
    prev = r.get("state")
    r.update(state="blocked", why=f"handed back ({prev}): try again now", retry_at=0, resumed_by_hand=now()); r.pop("ended", None)
    _write(f, r); return r


def takeover(root, m) -> dict:
    """The coordinator runs this build themselves from now on: agentd leaves the request alone for good (state `elsewhere`)."""
    f = run_file(root, m); r = _read(f)
    if not isinstance(r, dict): raise ValueError(f"5_build/{m}/.build_run.json 不存在：agentd 没有接过这一期的构建")
    if r.get("state") in ("running", "preparing"): raise ValueError(f"{m} 的构建 agentd 正在{'跑' if r['state'] == 'running' else '准备环境'}：先停掉它")
    if r.get("state") not in ACTIVE + ("elsewhere",): raise ValueError(f"{m} 的构建已经是 {r.get('state')}（结束了）")
    r.update(state="elsewhere", why="taken over by hand (`gameanything build takeover`)", ended=now()); _write(f, r); return r


# ---------------------------------------------------------------- the daemon side
class Builds:
    def __init__(self, D, lab=None, env=None):
        self.D = D; self.lab = lab if lab is not None else Lab(env); self.procs = {}; self.said = {}
        self.watched = set()               # projects whose builder this daemon has seen alive (its end is then normal, not an interruption)
        self.since = baseline()

    # ---- helpers
    def log(self, msg): self.D.log(msg)

    def note(self, root, text, key=None):
        """A note for the resident (starts its run). key: say this only once (until the key changes)."""
        from . import agentd
        if key is not None and self.said.get(str(root)) == key: return
        if key is not None: self.said[str(root)] = key
        agentd.notify(root, text, sender="agentd-build")

    def _index(self, root) -> dict:
        d = _read(index_file(root)) or {}; d.setdefault("requests", {}); d.setdefault("go_used", {}); return d

    def _mark(self, root, req_name, **kw):
        d = self._index(root); d["requests"][req_name] = {**(d["requests"].get(req_name) or {}), **kw, "at": now()}; _write(index_file(root), d)

    def _save(self, root, m, r):
        _write(run_file(root, m), r)
        from . import isolation
        if isolation.enabled():                          # the agent's folder: the record stays agentd's (read-only for the account)
            try: os.chmod(run_file(root, m), 0o640)
            except OSError: pass

    def pending(self, e) -> list:
        """[(file, request)] of this project's build_start / build_change requests agentd has not decided on, oldest first."""
        d = self.D.requests
        if not d.is_dir(): return []
        since = _ts(self.since); seen = self._index(e["path"])["requests"]; out = []
        for f in sorted(d.glob(f"{e['id']}-*.json")):
            if f.name in seen: continue
            r = _read(f)
            if not isinstance(r, dict) or r.get("kind") not in KINDS or r.get("project") != e["id"]: continue
            if _ts(r.get("at")) < since: continue
            out.append((f, r))
        return sorted(out, key=lambda x: _ts(x[1].get("at")))

    def user_of(self, root) -> str:
        return users.owner_of(root) or os.environ.get("M2W_LAB_USER") or os.environ.get("USER") or "m2w"

    # ---- one scan, one project
    def scan(self, e, T):
        root = Path(e["path"]); m, r = current(root)
        if r is not None:
            if r.get("state") == "running": return self._watch(e, T, m, r)
            if r.get("state") == "preparing": return self._prepare(e, T, m, r)
            self._merge_again(e, T, m, r)
            if self.D.clock() < float(r.get("retry_at") or 0): return
            return self._try_start(e, T, m, r)
        for f, req in self.pending(e):
            if req["kind"] == "build_change":
                self._mark(root, f.name, state="no_build", milestone=(req.get("details") or {}).get("milestone"))
                self.note(root, "她要改的地方（build_change）没有交给构建：现在没有正在进行的构建。已经做好的版本要再改，就是新的一期："
                          "先把改动记进开发状态，再发 go 卡，她点了开工再发 build_start。请用简单的中文告诉她。")
                self.log(f"{e['id']}: build_change {f.name} with no build running: told the resident"); continue
            self._new(e, T, f, req); return

    def _merge_again(self, e, T, m, r):
        """A build_start of the same go card while this build waits (blocked / no seat): the resident asks again (she fixed the Steam
        login, ...). Not a second build and not a refusal: it is this build, tried again now."""
        from . import genrun
        root = Path(e["path"])
        for f, req in self.pending(e):
            if req["kind"] != "build_start": continue
            gid, _ = genrun._card_ids(T, str((req.get("details") or {}).get("go_key") or (req.get("details") or {}).get("go") or ""))
            if not gid or gid != r.get("go_card"): continue
            self._mark(root, f.name, state="merged", milestone=m, into=r.get("request"))
            r["retry_at"] = 0; self.said.pop(str(root), None); self._save(root, m, r)
            self.log(f"{e['id']}: build_start {f.name} (same go card {gid}) merged into the waiting build {m}: trying again now")

    def _refuse(self, root, f, req, why):
        self._mark(root, f.name, state="refused", why=why)
        self.note(root, f"构建请求没有开始（{f.name}）：{why}。请用简单的中文告诉她还差什么。")
        self.log(f"{Path(root).name}: build request {f.name} refused: {why}")

    def _new(self, e, T, f, req):
        from . import buildmode, genrun
        root = Path(e["path"]); det = req.get("details") or {}
        m = det.get("milestone")
        if not _m_ok(m): return self._refuse(root, f, req, "请求里没有写 milestone（例如 m1）")
        gid, gc = genrun._card_ids(T, str(det.get("go_key") or det.get("go") or ""))
        if not gc or gc["card"].get("kind") != "go": return self._refuse(root, f, req, f"找不到开工卡 {det.get('go_key') or '（请求里没有 go_key）'}")
        if genrun._decision(gc) != "start": return self._refuse(root, f, req, "她还没有在开工卡上点「开工」")
        used = self._index(root)["go_used"].get(gid)
        if used: return self._refuse(root, f, req, f"这张开工卡已经开过一次工了（{used.get('at')}）。要再做一期，请发一张新的开工卡")
        why = self.elsewhere(e, m)
        if why:
            self._mark(root, f.name, state="elsewhere", milestone=m, why=why)
            self.log(f"{e['id']}: build request {f.name} left alone: {why}"); return
        bm = det.get("build_mode") if det.get("build_mode") in buildmode.MODES else buildmode.effective(root)[0]
        d = self._index(root); d["go_used"][gid] = {"at": now(), "request": f.name, "milestone": m}; _write(index_file(root), d)
        self._mark(root, f.name, state="taken", milestone=m)
        rn = go_runner(gc)                         # an older go card with runners: ignored, builds use only the project's build model
        if rn: self.log(f"{e['id']}: build {m}: go card {gid} carries runner {rn.get('id')} ({rn['agent']} {rn.get('model') or 'default'}): ignored, builds use the project's build model")
        r = {"state": "blocked", "milestone": m, "request": f.name, "request_path": str(f), "kind": req["kind"], "go_card": gid, **({"card_runner": rn} if rn else {}),
             "build_mode": bm, "game": projects.game_of(root), "details": det, "text": req.get("text"),
             "playtest_rounds": _rounds(det) or 6, "wall_hours": float(det.get("wall_hours") or WALL_HOURS),
             "rounds": 0, "queued": now(), "host": agentd_host()}
        self._save(root, m, r)
        self.log(f"{e['id']}: build request {f.name} taken: {m}, {bm}, go card {gid}")
        return self._try_start(e, T, m, r)

    def elsewhere(self, e, m) -> str:
        """Why this project's build runs somewhere else (a coordinator by hand), or ''. Asked only before agentd takes a request (it then
        holds no lease of the project): any lease of the project is someone else's; so is a fresh build_status.yaml that is not done."""
        from . import buildwatch
        for l in self.lab.leases(e["id"]):
            return f"实验室里已经有这个项目的座位（{l.get('user')}，{l.get('state')}，不是后台拿的）"
        try: s = buildwatch.read_status(Path(e["path"]), m)
        except ValueError: s = {}
        if s and not s.get("done") and (datetime.now().timestamp() - _ts(s.get("updated"))) < FOREIGN_FRESH_SECS:
            return f"5_build/{m}/build_status.yaml 显示有人正在构建（{s.get('updated')}）"
        return ""

    def _done_elsewhere(self, root, m, r) -> str:
        """The build was finished by someone else while it waited on their lease (a coordinator ran it): build_status.yaml done, written
        after agentd first saw that lease (whole seconds; a done status of an earlier build of the same milestone is older)."""
        from . import buildwatch
        try: s = buildwatch.read_status(Path(root), m)
        except ValueError: return ""
        if s and s.get("done") and _ts(s.get("updated")) >= _ts(r.get("foreign_since")):
            return f"5_build/{m}/build_status.yaml done ({s.get('updated')}) while agentd's build waited: someone else finished it"
        return ""

    def model_block(self, root) -> tuple:
        """(build model {agent, model}, why it cannot run or ''): builds run ONLY on the project's build model (models.py), never another one."""
        from . import models
        b = models.effective(root, "build", (self.D.provider.name, self.D.provider.model))
        if b["agent"] in models.usable(root, daemon=(self.D.provider.name, self.D.provider.model)): return b, ""
        return b, models.label(b["agent"], b["model"])

    def _try_start(self, e, T, m, r):
        from . import buildmode
        root = Path(e["path"]); lease = None
        b, who = self.model_block(root)
        if who:                                   # not another model in its place: she chose this one (and its cost)
            why = f"build model {b['agent']}:{b['model'] or 'default'} cannot run: the owner has no login / key for it"
            first = r.get("why") != why
            r.update(state="blocked", why=why, retry_at=self.D.clock() + BLOCKED_RETRY_SECS); self._save(root, m, r)
            self.note(root, f"构建（{m}）没有开始：项目的构建模型是 {who}，但项目所有者还不能用它（没有登录或 key）。不会换成别的模型替她跑。"
                      "请用简单的中文告诉她：在「我的 agent」里登录 / 填 key，或者点输入框旁的「构建」换一个能用的模型；好了以后几分钟内会自动开始"
                      "（也可以再发一次同一张开工卡的 build_start，马上再试）。", key=f"model:{m}:{b['agent']}:{b['model']}")
            if first: self.log(f"{e['id']}: build {m} blocked: {why} (no fallback to another model)")
            return
        chosen = buildmode.mode_of(root)
        if chosen and chosen != r["build_mode"] and r.get("state") != "waiting_seat":     # she switched 「在哪里做」 while it waited
            self.log(f"{e['id']}: build {m}: build mode now {chosen} (was {r['build_mode']})"); r["build_mode"] = chosen
        if r["build_mode"] == "lab":
            ok, why, pooled = self.lab.ready(r["game"])
            if not ok:
                r.update(state="blocked", why=why, retry_at=self.D.clock() + BLOCKED_RETRY_SECS); self._save(root, m, r)
                self.note(root, f"构建（{m}）现在没法开始：{why}。请求留着，条件好了会自动开始；也可以请她在项目菜单「在哪里做」换成「我的电脑（本机）」。"
                          "请用简单的中文告诉她。", key=f"blocked:{m}:{why}")
                return
            if pooled:
                user = self.user_of(root)
                foreign = [] if r.get("lease_id") else [l for l in self.lab.leases(e["id"]) if not l.get("id") or l.get("id") not in (r.get("our_leases") or [])]
                if foreign:                                    # we hold no lease now, yet the project has one: a coordinator repairs the
                    who = self.lab.lease_str(foreign[0]) if foreign[0].get("sandbox") else foreign[0].get("user")    # environment (or runs it)
                    first = not str(r.get("why") or "").startswith("foreign lease")
                    r.update(state="blocked", why=f"foreign lease {who}: waiting until it is released (`gameanything build takeover` if it is not ours any more)",
                             retry_at=self.D.clock() + SEAT_RETRY_SECS, foreign_since=r.get("foreign_since") or now()); self._save(root, m, r)
                    if first: self.log(f"{e['id']}: build {m} waits: the project has a lab lease agentd did not take ({who}); tried again once it is released")
                    return
                done_by = self._done_elsewhere(root, m, r) if r.get("foreign_since") else ""
                if done_by:
                    r.update(state="elsewhere", why=done_by, ended=now()); self._save(root, m, r)
                    self.log(f"{e['id']}: build {m} left alone: {done_by}"); return
                r.pop("foreign_since", None)
                try: l = self.lab.acquire(user, e["id"], r["game"])
                except ValueError as x:
                    r.update(state="blocked", why=str(x), retry_at=self.D.clock() + BLOCKED_RETRY_SECS); self._save(root, m, r)
                    self.note(root, f"构建（{m}）暂时拿不到服务器沙箱的位置：{x}。请求留着，过一会儿会再试。请用简单的中文告诉她（不用说技术细节）。",
                              key=f"blocked:{m}:{x}")
                    return
                r.update(lease_id=l.get("id"), lease_user=user)
                if l.get("state") != "active":
                    r.update(state="waiting_seat", why=f"queue #{l.get('queue_position')}", retry_at=self.D.clock() + SEAT_RETRY_SECS); self._save(root, m, r)
                    self.note(root, f"服务器沙箱的位置现在都占着，这个项目的构建（{m}）排在第 {l.get('queue_position') or '?'} 位；空出来会自动开始。"
                              "请用简单的中文告诉她：已经排上了，不用她做什么。", key=f"seat:{m}")
                    return
                lease = l
                if hasattr(self.lab, "env_up_start") and not self._env_up(e, root, m, r, lease): return
        try: self._start(e, T, m, r, lease)
        except (OSError, ValueError) as x:
            if lease: self.lab.release(e["id"], r.get("lease_user"))
            r.update(state="failed", why=f"{type(x).__name__}: {x}", ended=now()); self._save(root, m, r)
            self.note(root, f"构建（{m}）没能启动（{type(x).__name__}）。请告诉她这次没开始，会请人看一下。")
            self.log(f"{e['id']}: builder for {m} could not start: {x}")

    # ---- the lab environment (labup.py) before a builder starts
    def _env_up(self, e, root, m, r, lease) -> bool:
        """Start `gameanything lab env up` for the lease; True when it is already done and ok (fakes answer at once), else the build waits as
        `preparing` (_prepare polls the job) or `blocked`."""
        L = self.lab.lease_str(lease)
        why = (f"auto build {m} of {e['id']}, request {r.get('request')}, go card {r.get('go_card')}: she pressed 开工 for this build in this "
               "sandbox, which covers starting Steam there (never a game)")
        out = self.D.log_dir() / "agentd-builds" / f"{e['id']}-{m}-env-{datetime.now():%H%M%S}.json"
        job = dict(self.lab.env_up_start(L, why, out), at=self.D.clock())
        r.update(state="preparing", why="env up", retry_at=None, env_job=job, lease=L,
                 lease_obj={k: lease.get(k) for k in ("id", "user", "project", "sandbox", "seat")})
        self._save(root, m, r)
        self.log(f"{e['id']}: build {m}: lab env up for {L} (consent: her 开工 on go card {r.get('go_card')} covers starting Steam in this sandbox)")
        return self._env_done(e, root, m, r, self.lab.env_up_result(job))

    def _prepare(self, e, T, m, r):
        root = Path(e["path"]); job = r.get("env_job") or {}
        res = self.lab.env_up_result(job) if job else {"state": "failed", "why": "no env up job"}
        if res is None:
            if self.D.clock() - float(job.get("at") or 0) <= ENV_UP_MAX_SECS: return
            self.lab.env_up_stop(job); res = {"state": "failed", "why": f"env up ran over {ENV_UP_MAX_SECS // 60} min", "why_zh": ""}
        if self._env_done(e, root, m, r, res):
            lease = dict(r.get("lease_obj") or {})
            try: self._start(e, T, m, r, lease)
            except (OSError, ValueError) as x:
                self.lab.release(e["id"], r.get("lease_user"))
                r.update(state="failed", why=f"{type(x).__name__}: {x}", ended=now()); self._save(root, m, r)
                self.note(root, f"构建（{m}）没能启动（{type(x).__name__}）。请告诉她这次没开始，会请人看一下。")
                self.log(f"{e['id']}: builder for {m} could not start: {x}")

    def _env_done(self, e, root, m, r, res) -> bool:
        if res is None: return False
        r.pop("env_job", None)
        r["env"] = {"state": res.get("state"), "why": res.get("why"), "did": res.get("did") or [], "at": now()}
        if res.get("state") == "ok":
            self.log(f"{e['id']}: build {m}: lab env up ok for {r.get('lease')}" + (f" (started: {', '.join(res['did'])})" if res.get("did") else ""))
            return True
        self.lab.release(e["id"], r.get("lease_user"))
        r.update(state="blocked", why=f"env {res.get('state')}: {res.get('why')}", retry_at=self.D.clock() + ENV_RETRY_SECS, lease=None, lease_id=None, lease_obj=None,
                 our_leases=[*(r.get("our_leases") or []), r.get("lease_id")][-10:])
        self._save(root, m, r)
        self.log(f"{e['id']}: build {m}: lab env up {res.get('state')}: {res.get('why')}; the request waits, env up again in {ENV_RETRY_SECS // 60} min")
        self._env_note(root, m, res, resumed=bool(r.get("resume_logs")))
        return False

    def _env_note(self, root, m, res, resumed=False):
        what = "接着做" if resumed else "开始"
        if res.get("state") == "needs_her":
            self.note(root, f"构建（{m}）在等她：{res.get('why_zh') or '沙箱里的 Steam 需要她登录一次'}。请求留着，这张开工卡不算用掉；"
                      f"她登录好以后，几分钟内构建会自动{what}（也可以再发一次同一张开工卡的 build_start，马上再试）。"
                      "请用简单的中文告诉她怎么做（不用说技术细节），不要替她输入密码或验证码。", key=f"env:{m}:needs_her")
        else:
            self.note(root, f"构建（{m}）的服务器沙箱环境还没准备好（{res.get('why_zh') or '沙箱环境没起来'}）。请求留着，这张开工卡不算用掉，"
                      f"每隔几分钟会自动再试，好了就{what}。请用简单的中文告诉她：在等沙箱，不用她做什么。", key=f"env:{m}:{res.get('state')}")

    def add_dirs(self, root, r) -> list:
        """Where a builder writes outside the project (Codex: --add-dir; Claude: --add-dir for Read / Edit)."""
        from . import lab, lessons
        game = r.get("game"); out = [self.D.requests, lessons.local_dir(), *lessons.write_dirs(game)]
        if r.get("build_mode") == "lab":
            g = lab.gamebench()
            if g: out += [g, g.parent / "modlab", g.parent / "runs"]
            out += [Path(os.environ[k]) for k in ("WC_RT_LAB_ROOT", "CSLAB_RUNS_HOST", "M2W_LAB_HOME") if os.environ.get(k)]
        else:
            try:
                from . import native
                info = next((g for g in native.doctor(game).get("games") or [] if g.get("game") == game), {})
                out += [Path(v) for k in ("user_dir", "mods_dir", "saves_dir") for v in [info.get(k)] if v]
                out.append(projects.data_dir() / "backups")
            except Exception: pass
        out += [Path.home() / c for c in CACHES]
        out += [Path(p) for p in (os.environ.get("GAMEANYTHING_BUILDER_WRITE_DIRS") or "").split(os.pathsep) if p]
        seen, res = set(), []
        for d in out:
            try: d = Path(d).expanduser().resolve()
            except (OSError, RuntimeError): continue
            if str(d) in seen or not d.is_dir() or d == Path(root).resolve(): continue
            seen.add(str(d)); res.append(d)
        return res

    def system_prompt(self, e, root, r) -> str:
        from . import agentd, flow
        kind = projects.config_of(root).get("kind") or e.get("kind") or "memory"
        doc = agentd.SKILL / flow.KIND_DOCS.get(kind, "references/memory-project-flow.md")
        parts = ["# You are the BUILDER of this project (not the resident)\n\nThe resident's core rules follow for context: their hard rules bind "
                 "you too, but their 「Every run」 chat steps do NOT. You never use `gameanything chat` (it refuses you); you report only with "
                 "`gameanything agentd notify --from builder`. Your own role is the last part (roles/builder.md).",
                 agentd.CORE.read_text(encoding="utf-8"),
                 f"## Mode doc ({doc.relative_to(agentd.SKILL).as_posix()})\n\n" + (doc.read_text(encoding="utf-8") if doc.is_file() else ""),
                 ROLE.read_text(encoding="utf-8")]
        from . import internal_docs                 # a gamebench lab (seats) or the hub only: internal/, never the user's flow
        extra = internal_docs.addendum(root, getattr(self.lab, "env", None), role="builder")
        if extra: parts.append(extra.strip())
        t = agentd._fill("\n\n".join(parts), e, root, f"builder:{e['id']}", self.D.requests)
        vals = {"milestone": r["milestone"], "playtest_rounds": r["playtest_rounds"], "wall_hours": f"{r['wall_hours']:g}",
                "build_mode": r["build_mode"], "lease": r.get("lease") or self.no_lease(r), "go_card": r.get("go_card")}
        for k, v in vals.items(): t = t.replace("{{" + k + "}}", str(v))
        return t

    def no_lease(self, r) -> str:
        from . import buildmode
        if r.get("build_mode") == "lab" and buildmode.own_sandbox(getattr(self.lab, "env", None)):
            return "none: your own sandbox on her Linux machine, `gameanything lab sandbox` (step 3)"
        return "(none: native mode or a lab without a seat broker)"

    def user_prompt(self, r) -> str:
        return ("Start the build now. The build request the resident wrote (JSON):\n\n" + json.dumps(
            {"text": r.get("text"), "milestone": r["milestone"], "build_mode": r["build_mode"], "playtest_rounds": r["playtest_rounds"],
             "wall_hours": r["wall_hours"], "details": r.get("details") or {}}, ensure_ascii=False, indent=1)
            + f"\n\nChanges she asks for while you build are appended to 5_build/{r['milestone']}/build_changes.yaml: read it at the start of every round."
            + self.retro_note(r) + self.resume_note(r))

    def retro_note(self, r) -> str:
        """The retrospective of the versions before this one (docs/feedback-loop.md 2.1) is the builder's first step (roles/builder.md)."""
        ms = [m for m in r.get("retro_todo") or [] if m != r["milestone"]]
        if not ms or r.get("resume_logs"): return ""
        return ("\n\nFIRST, before the build: the retrospective of " + ", ".join(ms) + " (roles/builder.md 「Before the first round」 step 0): for each, "
                "`gameanything feedback retro --project \"$P\" --m <m> --emit`, answer the request it names in a fresh context, then `--collect`.")

    def resume_note(self, r) -> str:
        logs = r.get("resume_logs") or []
        if not logs: return ""
        return (f"\n\nRESUME ({len(logs)}): this build was started before and stopped because the lab environment was gone "
                f"({r.get('blocked_why') or 'see the log'}). `gameanything lab env up` has brought it back for your lease. The previous builder's log "
                f"(JSON lines, read its last part to see where it stopped): {logs[-1]}"
                + (f" (older: {', '.join(logs[:-1])})" if len(logs) > 1 else "")
                + f". Also read 5_build/{r['milestone']}/build_status.yaml and `gameanything status show`. Continue from there: do not redo finished work, "
                "re-check in the game what was only done offline. Do NOT send the start note again; send a short note that the build goes on.")

    def _start(self, e, T, m, r, lease):
        from . import agentd, buildwatch
        root = Path(e["path"]); run_id = uuid.uuid4().hex[:12]
        if lease: r["lease"] = self.lab.lease_str(lease)
        prov = self.D.provider_for(root, "build"); prov_name = prov.name     # only the project's build model (a go card runner is ignored)
        env = agentd.clean_env(extra={"GAMEANYTHING_SESSION": f"builder:{e['id']}", "GAMEANYTHING_INSTANCE": run_id, "GAMEANYTHING_PARENT_REQUESTS": str(self.D.requests),
                                      "GAMEANYTHING_BIN": agentd.m2w_bin(), "GAMEANYTHING_ROLE": "builder", "GAMEANYTHING_BUILD_M": m})
        if lease:
            env["GAMEANYTHING_LEASE"] = env["M2W_LEASE"] = r["lease"]       # M2W_LEASE: the lab tools (gamebench, in-sandbox guards) read the old name
            if isinstance(lease.get("seat"), int): env["MC_N"] = str(lease["seat"])
        env = prov.clean_env(env)
        env, blk = users.run_env(root, env, prov_name)
        if blk: raise ValueError(f"项目所有者的账号还不能跑构建：{blk}")
        env = agent_providers.agent_env(env, prov)
        env["PATH"] = str(Path(agentd.m2w_bin()).parent) + os.pathsep + env.get("PATH", "")
        try:                                             # the version's evaluation condition (docs/feedback-loop.md 7.8): fixed once, blind to her
            from . import feedback
            r["condition"] = feedback.assign(root, m)
            from . import retro
            r["retro_todo"] = retro.retro_todo(root, before=m)[-2:]        # the newest versions she gave feedback on, not looked back on yet
        except Exception: r.setdefault("condition", None)
        sid = prov.new_session_id()
        dirs = self.add_dirs(root, r)
        run_tmp = agent_providers.run_tmpdir(e["id"], run_id); env = agent_providers.with_run_tmp(env, run_tmp)   # its own TMPDIR (hotfix 2026-10-30)
        run_as = None
        from . import isolation
        if isolation.enabled():                          # docs/agent-isolation.md: the builder runs as the owner's account, the lab through the gate
            try: env, run_as = isolation.run_env(root, env, run_id, tmp=run_tmp)
            except (isolation.IsolationError, OSError) as x: agent_providers.drop_run_tmp(run_tmp); raise ValueError(f"agent account: {x}")
            dirs = []; self.D.ensure_gate()
        cmd, env = prov.launch(self.user_prompt(r), self.system_prompt(e, root, r), sid, False, root, None, role="builder", add_dirs=dirs,
                               network=True, shell_set={k: env[k] for k in ("GAMEANYTHING_KEYS_FILE",) if env.get(k)}, env=env)
        if run_as: isolation.after_launch(env, run_as)
        logf = self.D.log_dir() / "agentd-builds" / f"{e['id']}-{m}-{datetime.now():%H%M%S}-{run_id}.jsonl"; logf.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(logf, "ab") as lf: p = self.D.spawn(cmd, root, env, lf, **({"run_as": run_as} if run_as else {}))
        except BaseException: agent_providers.drop_run_tmp(run_tmp); raise
        self.procs[str(root)] = p
        r.update(state="running", why=None, retry_at=None, env_job=None, run_id=run_id, pid=p.pid, pid_start=osdirs.pid_start(p.pid), host=agentd_host(),
                 started=now(), log=str(logf), provider=prov.name, model=prov.model, agent_session=sid, heartbeat_at=self.D.clock(), add_dirs=[str(d) for d in dirs],
                 tmpdir=str(run_tmp), **({"account": run_as["account"]} if run_as else {}))
        self._save(root, m, r)
        try:
            from . import feedback
            feedback.log_event(root, "build_start", m=m, run_id=run_id, provider=prov.name, model=getattr(prov, "model", None), build_mode=r["build_mode"],
                               playtest_rounds=r["playtest_rounds"], wall_hours=r["wall_hours"], condition=r.get("condition"), go_card=r.get("go_card"),
                               resumed=len(r.get("resume_logs") or []), log=r.get("log"))
        except Exception: pass
        try: buildwatch.write_status(root, m, round_=0, max_rounds=r["playtest_rounds"], step="构建 agent 开始工作", step_en="The builder started", started=r["started"])
        except (OSError, ValueError): pass
        self._live("build", e, T, m, r)
        self.log(f"{e['id']}: builder {run_id} started for {m} ({r['build_mode']}{', lease ' + r['lease'] if lease else ''}, {prov.name} {prov.model or '(default model)'}, pid {p.pid}, log {logf.name})")

    def _alive(self, root, r):
        p = self.procs.get(str(root))
        if p is not None and p.pid == r.get("pid"):
            rc = p.poll()
            if rc is None: return True, None
            self.procs.pop(str(root), None); return False, rc
        if r.get("host") != agentd_host(): return True, None                 # another machine's build: not ours to judge
        return osdirs.pid_alive(r.get("pid"), r.get("pid_start")), None

    def _watch(self, e, T, m, r):
        from . import buildwatch
        root = Path(e["path"]); alive, rc = self._alive(root, r)
        if alive:
            self.watched.add(str(root)); changed = False
            try: s = buildwatch.read_status(root, m)
            except ValueError: s = {}
            if isinstance(s.get("round"), int) and s["round"] != r.get("rounds"): r["rounds"] = s["round"]; changed = True
            if r.get("lease_id") and self.D.clock() - float(r.get("heartbeat_at") or 0) > HEARTBEAT_SECS:
                self.lab.heartbeat(e["id"], r.get("lease_user")); r["heartbeat_at"] = self.D.clock(); changed = True
            for f, req in self.pending(e):
                if req["kind"] == "build_change": self._change(root, m, r, f, req); changed = True
            if self.D.clock() - _ts(r.get("started")) > r["wall_hours"] * 3600 * 1.1:
                self.log(f"{e['id']}: builder {r.get('run_id')} over {r['wall_hours']:g} h, stopping it"); osdirs.stop_group(r["pid"])
                r["stopped"] = "wall_hours"; changed = True
            if changed: self._save(root, m, r)
            self._live("build", e, T, m, r)
            return
        self._end(e, T, m, r, rc, adopted=rc is None and str(root) not in self.watched)

    def _live(self, what, *a, **kw):
        """agentd's own report of the build in her chat (live.py); never stops the build's own bookkeeping."""
        L = getattr(self.D, "live", None)
        if L is None: return
        try: getattr(L, what)(*a, **kw)
        except Exception as x: self.log(f"{a[0].get('id') if a and isinstance(a[0], dict) else '?'}: live {what} failed ({type(x).__name__}: {x})")

    def _change(self, root, m, r, f, req):
        import yaml
        det = req.get("details") or {}
        cf = Path(root) / "5_build" / m / "build_changes.yaml"
        try: cur = yaml.safe_load(cf.read_text(encoding="utf-8")) or []
        except (OSError, yaml.YAMLError): cur = []
        cur = cur if isinstance(cur, list) else []
        cur.append({"at": req.get("at") or now(), "text": req.get("text"), "change": det.get("change"), "details": det})
        n = _rounds(det, req.get("text") or "")
        if n and n > int(r.get("playtest_rounds") or 0):
            r["playtest_rounds"] = n; cur[-1]["playtest_rounds"] = n
            try:
                from . import buildwatch
                buildwatch.write_status(root, m, max_rounds=n)
            except (OSError, ValueError): pass
        cf.parent.mkdir(parents=True, exist_ok=True)
        cf.write_text("# her changes while the build runs (agentd appends; the builder reads this every round)\n"
                      + yaml.safe_dump(cur, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self._mark(root, f.name, state="passed_to_builder", milestone=m)
        self.log(f"{Path(root).name}: build_change {f.name} passed to the builder of {m}" + (f" (playtest_rounds {n})" if n else ""))

    def _end(self, e, T, m, r, rc, adopted):
        from . import buildwatch, delivery
        root = Path(e["path"]); agent_providers.drop_run_tmp(r.get("tmpdir"))       # the run is over (a resumed one gets a new folder)
        try: chk = delivery.check(root, only=m)
        except Exception: chk = []
        ok = bool(chk) and all(c.get("ok") for c in chk) and not any(c.get("skip") for c in chk)
        if not ok and not adopted and not r.get("stopped") and self._resume_later(e, root, m, r, rc): return
        if r.get("lease_id"): self.lab.release(e["id"], r.get("lease_user"))
        state = "done" if ok else ("interrupted" if adopted else ("stopped" if r.get("stopped") else "ended"))
        r.update(state=state, ended=now(), rc=rc, delivered=ok); self._save(root, m, r); self.watched.discard(str(root))
        try:                                             # the evaluation's raw data (docs/feedback-loop.md 7.5): wall time, rounds, tokens / cost
            from . import feedback
            feedback.log_event(root, "build_end", m=m, run_id=r.get("run_id"), rc=rc, state=state, delivered=ok, rounds=r.get("rounds"),
                               wall_s=round(_ts(r.get("ended")) - _ts(r.get("started"))) if r.get("started") else None, **feedback.run_usage(r.get("log")))
        except Exception: pass
        try: buildwatch.write_status(root, m, done=True, step="构建结束" if ok else "构建停了", step_en="Build finished" if ok else "Build stopped")
        except (OSError, ValueError): pass
        self.log(f"{e['id']}: builder {r.get('run_id')} for {m} ended rc={rc}: {state}")
        problems = "；".join(p for c in chk for p in c.get("problems") or [])[:300] or "没有 5_build/" + m + "/play/"
        self._live("build_end", e, T, m, r, state, ok, problems)
        from . import activity
        pause = activity.scan_log(r.get("log"), r.get("provider") or "claude-code") if not ok else None
        if pause:                                        # the builder stopped on a usage limit / login: say so, not just 「退出了」
            r["paused"] = pause; self._save(root, m, r)
        if adopted and not ok:
            self.note(root, f"构建（{m}）在后台重启时中断了，结果不确定（不会自动重新开始）。日志：{r.get('log')}。`gameanything build check` 现在说：{problems}。"
                      "请用简单的中文告诉她这次构建中断了；要接着做需要她再点一次开工（新的开工卡）。")
            return
        if self._builder_noted(T, r): return
        if ok:
            self.note(root, f"构建做好了（{m}，`gameanything build check` 已经通过）。请照 build 这一步：gameanything status card 生成 result 卡、补图，发给她。")
        else:
            why = "到了时间上限被停下" if r.get("stopped") else f"构建 agent 结束了（退出码 {rc}），没有报告"
            if pause and pause.get("kind") == "limit":
                why = "停在了 agent 的用量上限（" + (f"大约 {activity.hhmm(pause['resets'])} 恢复" if pause.get("resets") else "要等额度恢复") + "）"
            elif pause: why = "停在了 agent 的登录失效（需要重新登录）"
            self.note(root, f"构建（{m}）{why}，还没交付好：{problems}。请用简单的中文告诉她现在的情况（做到哪了看 gameanything status show），"
                      "不要发 result 卡；要接着做需要一张新的开工卡。")

    def _resume_later(self, e, root, m, r, rc) -> bool:
        """A lab builder that ended because the environment was gone: back to `blocked`, resumed when env up works again. True = handled."""
        from . import buildwatch
        if r.get("build_mode") != "lab": return False
        try: said = (buildwatch.read_status(root, m).get("blocked") or {})
        except ValueError: said = {}
        said = said if isinstance(said, dict) else {"reason": str(said)}
        env = self.lab.env_status(r["lease"]) if r.get("lease") and hasattr(self.lab, "env_status") else {}
        bad = (env or {}).get("state") in ("needs_her", "down", "failed")
        if not (said or bad): return False
        n = len(r.get("resume_logs") or [])
        why = said.get("reason") or (env or {}).get("why") or ""
        if n >= MAX_RESUMES:
            self.log(f"{e['id']}: builder for {m} blocked again ({why}) after {n} resumes: not resumed"); return False
        if r.get("lease_id"): self.lab.release(e["id"], r.get("lease_user"))
        r["our_leases"] = [*(r.get("our_leases") or []), r.get("lease_id")][-10:]
        r.update(state="blocked", why=f"environment: {why}", blocked_why=why, rc=rc, retry_at=self.D.clock() + (ENV_RETRY_SECS if bad else 0),
                 resume_logs=[*(r.get("resume_logs") or []), r.get("log")], lease=None, lease_id=None, lease_obj=None, pid=None, ended_run=now())
        self._save(root, m, r); self.watched.discard(str(root)); self.procs.pop(str(root), None)
        try: buildwatch.write_status(root, m, step="等服务器沙箱环境（好了会自动接着做）", step_en="Waiting for the lab environment (resumes by itself)")
        except (OSError, ValueError): pass
        self.log(f"{e['id']}: builder {r.get('run_id')} for {m} ended rc={rc} blocked on the environment ({why}; env {(env or {}).get('state') or '-'}):"
                 f" kept, resume {n + 1}/{MAX_RESUMES} when env up works")
        if (env or {}).get("state") == "needs_her": self._env_note(root, m, env, resumed=True)
        else:
            self.note(root, f"构建（{m}）停在了服务器沙箱环境上（{why[:120] or '沙箱环境没了'}）。不算结束：请求留着，这张开工卡不算用掉；"
                      "环境好了会自动接着做（agentd 每隔几分钟再准备一次环境）。请用简单的中文告诉她：在等沙箱，不用她做什么，不要发 result 卡。",
                      key=f"resume:{m}:{n}")
        return True

    def _builder_noted(self, T, r) -> bool:
        """The builder sent its own note in its last OWN_NOTE_SECS (its 「做好了」 / blocked): agentd adds none."""
        end = datetime.now().timestamp(); box = T.dir / ".agentd_inbox"
        for f in sorted(box.glob("*.json")) + sorted((box / "done").glob("*.json")):
            d = _read(f) or {}
            if d.get("from") == "builder" and _ts(d.get("at")) >= _ts(r.get("started")) and end - _ts(d.get("at")) <= OWN_NOTE_SECS: return True
        return False


def go_runner(gc):
    """The runner an OLDER go card was started with ({agent, model, id}; models.runner_choice), or None (no runners: every card since
    2026-10-28). Only logged: builds run on the project's build model whatever the card says."""
    from . import models
    if not gc: return None
    rs = [x for x in (gc["card"].get("runners") or []) if isinstance(x, dict)]
    ans = [a for a in gc.get("answers") or [] if a.get("from") == "user"]
    rid = ((ans[-1].get("answer") or {}).get("runner")) if ans else None
    R = next((x for x in rs if x.get("id") == rid), None) or next((x for x in rs if x.get("build_default")), None) or next((x for x in rs if x.get("recommended")), None)
    c = models.runner_choice(R) if R else None
    return {**c, "id": R.get("id")} if c else None


def agentd_host():
    from . import agentd
    return agentd.HOST


# ---------------------------------------------------------------- what `gameanything agentd status` shows
def status(root) -> list:
    out = []
    for m, r in records(root):
        if r.get("state") not in ACTIVE and _ts(r.get("ended")) < datetime.now().timestamp() - 24 * 3600: continue
        out.append(f"build {m}: {r.get('state')}" + (f" since {r.get('started')}" if r.get("state") == "running" else "")
                   + (f", round {r.get('rounds')}/{r.get('playtest_rounds')}" if r.get("state") == "running" else "")
                   + (f", lease {r.get('lease')}" if r.get("lease") else "") + (f" ({r.get('why')})" if r.get("why") else ""))
    return out
