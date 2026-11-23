"""Paid generation, card-checked: the resident agent only QUEUES a request; the supervisor (agentd) checks it and runs it.

    gameanything gen request --project P --tool fal:image --inputs 4_design/gen/x.yaml --permission <card> --go <card>
                                                         (the unified interface, gameanything/gen: agentd runs the adapter in-process)
    gameanything gen request --project P --tool meshy3d --permission <card key or id> --go <card key or id> [--arg A ...]
                                                         (old projects: queue 4_design/tools/gen_meshy3d.py; runs nothing)
    gameanything gen status --project P                           (the queue and the runs of this project)

An adapter request (--tool <adapter>:<capability>) is checked more than a script: besides both cards, the permission card's `to` must
name the provider, every picture sent must be listed in its `files` globs, and the estimate (gen.estimate of exactly these jobs) must
fit the go card's money (cost_usd, estimate.cost_usd[1] or the permission card's cost_usd) and max_images. The run uses the owner's key
from users.gen_env, never os.environ, writes files + index.yaml + privacy_ledger.yaml entries, and keeps a progress card current.

A request is <project>/conversation/.gen_queue/<id>.json. agentd (no LLM) picks it up, at most one run per project at a time, in the
background, and runs it ONLY when
  - the script is an existing gen_<tool>.py directly inside the project's 4_design/tools/ (resolved; no path tricks),
  - the user's latest answer on the permission card is decision "yes" and on the go card decision "start" (in conversation/thread.jsonl),
  - this go card has not been used before (conversation/.gen_runs.json records every go card that started a run: once only).
The script runs with the PROJECT OWNER's env (users.gen_env: on a hub the owner's own key file, never the supervisor's keys), its output
goes to <log root>/<date>/gen/, and the outcome (or the reason a request was refused, in plain Chinese) goes to the project's agent as a
note (agentd.notify), which tells the user. The queue file then moves to .gen_queue/done|failed|rejected/. No secret is ever logged or sent:
output lines are redacted with the run env's key values.
"""
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from . import envcompat, gen, keys, osdirs, users
from .conversation import Thread, now

TOOL_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
GEN_MAX_SECS = 3 * 3600
POLL_SECS = 5.0                                 # how often an adapter asks a queued provider task whether it is done
HOST = socket.gethostname()
REPO = Path(__file__).resolve().parent.parent


class GenError(ValueError):
    pass


def _read(p: Path):
    try: return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError): return None


def _write(p: Path, d):
    p.parent.mkdir(parents=True, exist_ok=True); tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8"); os.replace(tmp, p)


def queue_dir(root) -> Path: return Path(root) / "conversation" / ".gen_queue"


def runs_file(root) -> Path: return Path(root) / "conversation" / ".gen_runs.json"


def script_of(tool: str) -> str: return f"4_design/tools/gen_{tool}.py"


def pending(root) -> list:
    d = queue_dir(root)
    return sorted(d.glob("*.json")) if d.is_dir() else []


# ---------------------------------------------------------------- the resident's side: queue only
def request(root, tool: str, permission: str, go: str, args=(), session=None, spec=None) -> Path:
    """Queue a run of 4_design/tools/gen_<tool>.py, or (tool = adapter:capability, spec = the inputs) of a gen adapter.
    Checks only the shape here; agentd checks the cards when it runs it."""
    tool = str(tool or "").strip()
    if gen.is_adapter_tool(tool): return _request_adapter(root, tool, permission, go, spec or {}, session)
    if tool.startswith("gen_"): tool = tool[4:]
    if tool.endswith(".py"): tool = tool[:-3]
    if not TOOL_RE.match(tool): raise GenError("tool 应该是脚本名里 gen_ 后面的部分，例如 meshy3d（只能用小写字母、数字和 _）")
    if not str(permission or "").strip() or not str(go or "").strip(): raise GenError("需要 --permission 和 --go（两张卡的 key 或 id）")
    root = Path(root).resolve()
    if not (root / "conversation").is_dir(): raise GenError(f"{root} 不是一个项目文件夹（没有 conversation/）")
    rid = f"{datetime.now():%Y%m%dT%H%M%S}_{secrets.token_hex(3)}"
    f = queue_dir(root) / f"{rid}.json"
    _write(f, {"id": rid, "tool": tool, "script": script_of(tool), "args": [str(a) for a in args or []],
               "permission": str(permission).strip(), "go": str(go).strip(),
               "session": session or os.environ.get("GAMEANYTHING_SESSION"), "at": now()})
    return f


def _request_adapter(root, tool, permission, go, spec, session):
    if not str(permission or "").strip() or not str(go or "").strip(): raise GenError("需要 --permission 和 --go（两张卡的 key 或 id）")
    root = Path(root).resolve()
    if not (root / "conversation").is_dir(): raise GenError(f"{root} 不是一个项目文件夹（没有 conversation/）")
    try: norm = gen.normalize(root, tool, spec)
    except gen.GenSpecError as e: raise GenError(str(e)) from None
    rid = f"{datetime.now():%Y%m%dT%H%M%S}_{secrets.token_hex(3)}"
    f = queue_dir(root) / f"{rid}.json"
    _write(f, {"id": rid, "tool": norm["tool"], "adapter": True, "spec": norm, "estimate": gen.estimate(norm["tool"], model=norm["model"], jobs=norm["jobs"])["estimate"],
               "permission": str(permission).strip(), "go": str(go).strip(), "session": session or os.environ.get("GAMEANYTHING_SESSION"), "at": now()})
    return f


def from_old_request(d: dict):
    """An old parent request {kind: gen_request_ready, path, details: {script, args, permission_key, go_key}} -> (root, tool, perm, go, args)."""
    det = d.get("details") or {}
    s = str(det.get("script") or "")
    m = re.match(r"^(?:\./)?4_design/tools/gen_([a-z0-9][a-z0-9_]*)\.py$", s)
    if not m: raise GenError(f"script 应该是 4_design/tools/gen_<名字>.py（收到的是 {s or '空'}）")
    return Path(d.get("path") or ""), m.group(1), det.get("permission_key") or det.get("permission"), det.get("go_key") or det.get("go"), det.get("args") or []


# ---------------------------------------------------------------- the checks
def _card_ids(T: Thread, ref: str):
    """The current card named by this key or event id (the latest card of a key; superseded ones do not count) -> (id, card) or (None, None)."""
    cs = T.cards()
    if ref in cs: return ref, cs[ref]
    for cid, c in cs.items():
        if c["card"].get("key") == ref: return cid, c
    return None, None


def _decision(c) -> str:
    ans = [a for a in c["answers"] if a.get("from") == "user"]
    return ((ans[-1].get("answer") or {}).get("decision")) if ans else None


def used(root) -> dict: return _read(runs_file(root)) or {}


def _cards(P, req):
    """Both cards answered (yes / start), the go card not used before. -> (permission card id, its card, go card id, its card)."""
    T = Thread(P)
    pid, pc = _card_ids(T, str(req.get("permission") or ""))
    if not pc or pc["card"].get("kind") != "permission": raise GenError(f"找不到许可卡 {req.get('permission')}")
    if _decision(pc) != "yes": raise GenError("用户还没有在许可卡上点「同意」，所以没有开始画")
    gid, gc = _card_ids(T, str(req.get("go") or ""))
    if not gc or gc["card"].get("kind") != "go": raise GenError(f"找不到开工卡 {req.get('go')}")
    if _decision(gc) != "start": raise GenError("用户还没有在开工卡上点「开工」，所以没有开始画")
    u = used(P).get(gid)
    if u: raise GenError(f"这张开工卡已经用过一次了（{u.get('started')}，{u.get('state')}）。要再画，请发一张新的开工卡，用户点了开工再提交")
    return pid, pc["card"], gid, gc["card"]


def check(root, req: dict):
    """-> (script path, args, go card id) or GenError with the reason in plain Chinese (for the agent to tell the user)."""
    P = Path(root).resolve(); tools = (P / "4_design" / "tools").resolve()
    tool = str(req.get("tool") or "")
    if not TOOL_RE.match(tool): raise GenError(f"工具名 {tool!r} 不对（只能用小写字母、数字和 _）")
    s = (P / script_of(tool)).resolve()
    if s.parent != tools or not s.name.startswith("gen_") or s.suffix != ".py": raise GenError("脚本必须在这个项目的 4_design/tools/ 里面")
    if not s.is_file(): raise GenError(f"找不到脚本 4_design/tools/{s.name}，请先写好它")
    _, _, gid, _ = _cards(P, req)
    args = [str(a) for a in req.get("args") or []]
    if not args or Path(args[0]).expanduser().resolve() != P: args = [str(P), *args]       # the project path goes first exactly once
    return s, args, gid


def _money(c):
    """The most money a card allows (cost_usd, else estimate.cost_usd[1]), or None."""
    if isinstance(c.get("cost_usd"), (int, float)) and not isinstance(c.get("cost_usd"), bool): return float(c["cost_usd"])
    e = c.get("estimate") or {}
    cu = e.get("cost_usd") if isinstance(e, dict) else None
    return float(cu[1]) if isinstance(cu, list) and len(cu) == 2 and isinstance(cu[1], (int, float)) else None


SLACK = 1.10                                     # the go card's money may be passed by the estimate by at most 10 % (rounding on the card)


def check_adapter(root, req: dict):
    """-> (normalized spec, permission card id, go card id, estimate, budget) or GenError (plain Chinese, for the agent to tell her).
    The cards say what is sent to whom (permission: `to` names the provider, `files` covers every picture) and how much (go)."""
    P = Path(root).resolve()
    try:
        spec = gen.normalize(P, req.get("tool"), req.get("spec") or {})       # re-checked now: files may have moved since queueing
        ad, cap = gen.parse_tool(spec["tool"])
        est = gen.estimate(spec["tool"], model=spec["model"], jobs=spec["jobs"])
    except gen.GenSpecError as e: raise GenError(str(e)) from None
    pid, pc, gid, gc = _cards(P, req)
    if not ad.local:
        to = str(pc.get("to") or "").lower()
        if not any(w in to for w in ad.vendor):
            raise GenError(f"许可卡上写的是发给「{pc.get('to')}」，这次要发给 {ad.title}：请发一张写明发给 {ad.title} 的许可卡")
        sent = sorted({x for j in spec["jobs"] for x in j["images"]})
        if sent:
            pats = pc.get("files") or []
            if not pats: raise GenError(f"这次要把 {len(sent)} 张图发给 {ad.title}，但许可卡上没有列出会发哪些图（files）：请在许可卡的 files 里写明")
            miss = [x for x in sent if not gen.covered(x, pats)]
            if miss: raise GenError(f"这些图不在许可卡的 files 里，不能发：{', '.join(miss[:5])}" + (" …" if len(miss) > 5 else ""))
    budget = _money(gc)
    if budget is None: budget = _money(pc)
    hi = est["cost_usd_max"]
    if hi > 0 and budget is None: raise GenError(f"开工卡上没有写大约多少钱（cost_usd 或 estimate）：这次估计最多 ${hi:g}（gameanything gen estimate）")
    if hi > 0 and hi > budget * SLACK + 0.01: raise GenError(f"这次估计最多 ${hi:g}，超过了开工卡上写的 ${budget:g}：请发一张写对花费的新开工卡")
    mx = gc.get("max_images")
    if isinstance(mx, (int, float)) and est["outputs"] > mx: raise GenError(f"这次要生成 {est['outputs']} 个，超过了开工卡上写的最多 {mx:g} 个")
    return spec, pid, gid, est, budget


# ---------------------------------------------------------------- running
def popen(cmd, cwd, env, log, run_as=None):
    kw = {"creationflags": 0x00000200} if os.name == "nt" else {"start_new_session": True}
    if run_as:                                           # isolation on: the project's own script runs as its account, never as the service
        from . import isolation
        kw.update(isolation.spawn_kwargs(run_as)); env = {**env, "HOME": run_as.get("home") or env.get("HOME", "")}
    return subprocess.Popen(cmd, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **kw)


def secrets_of(env: dict) -> list:
    return sorted({v for k, v in (env or {}).items() if users.CRED_RE.match(k) and isinstance(v, str) and len(v) >= 8}, key=len, reverse=True)


def redact(text, env) -> str:
    s = str(text or "")
    for v in secrets_of(env): s = s.replace(v, "***")
    return users.SECRET_RE.sub("sk-ant-***", s)


def _record(root, gid, **kw):
    with open(Path(root) / "conversation" / ".lock", "a", encoding="utf-8") as lk:
        osdirs.lock(lk)
        d = used(root); d[gid] = {**(d.get(gid) or {}), **kw}; _write(runs_file(root), d)


def _finish_queue(qf: Path, req: dict, state: str, outcome: str):
    dest = qf.parent / state; dest.mkdir(parents=True, exist_ok=True)
    _write(dest / qf.name, {**req, "state": state, "outcome": outcome, "ended": now()})
    qf.unlink(missing_ok=True)


def _tail(log: Path, env, n=3) -> str:
    try: lines = [l for l in log.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    except OSError: return ""
    return redact(" | ".join(lines[-n:]), env)[-600:]


def _scrub_log(log: Path, env):
    """The script should never print a key; if it did, the key does not stay in the log."""
    try:
        t = log.read_text(encoding="utf-8", errors="replace"); r = redact(t, env)
        if r != t: log.write_text(r, encoding="utf-8")
    except OSError: pass


def env_for(root):
    """-> (env, None) or (None, why): the PROJECT OWNER's env (users.gen_env), the agent-session variables of the supervisor dropped."""
    from . import agentd
    env = envcompat.drop(agentd.clean_env(), "GEN_OFF")                 # (a daemon started from inside a run must not pass it on)
    return users.gen_env(root, env)


def note(root, text):
    from . import agentd
    return agentd.notify(root, text, sender="gen")


def reject(root, qf: Path, req: dict, why: str):
    _finish_queue(qf, req, "rejected", why)
    what = f"gameanything gen {req.get('tool')}" if req.get("adapter") else f"gen_{req.get('tool')}.py"
    note(root, f"付费生成的请求没有执行（{what}）：{why}。请用简单的中文告诉用户为什么还没开始、她需要做什么。")


def start(root, qf: Path, log_dir: Path, spawn=popen, log=print, max_secs=GEN_MAX_SECS, http=None):
    """Check one queued request; refuse it (note to the agent) or start it in a background thread. -> the thread or None."""
    root = Path(root).resolve(); req = _read(qf)
    if not isinstance(req, dict):
        qf.rename(qf.with_suffix(".bad")); log(f"{root.name}: gen request {qf.name} unreadable, set aside"); return None
    if req.get("adapter"): return start_adapter(root, qf, req, log_dir, log=log, max_secs=max_secs, http=http)
    try:
        s, args, gid = check(root, req)
        env, blk = env_for(root)
        if blk: raise GenError(f"项目所有者的账号还不能用来付费生成：{blk}")
    except GenError as e:
        reject(root, qf, req, str(e)); log(f"{root.name}: gen request {req.get('id')} rejected: {e}"); return None
    log_dir = Path(log_dir) / "gen"; log_dir.mkdir(parents=True, exist_ok=True)
    logf = log_dir / f"{root.name}-{req.get('id')}.log"
    cwd = REPO if (REPO / "pyproject.toml").exists() else root
    _record(root, gid, state="running", started=now(), request=req.get("id"), script=s.name, host=HOST, log=str(logf))
    req = {**req, "state": "running", "go_card": gid}; _write(qf, req)
    try:
        from . import isolation
        ra = isolation.run_as_for(root)
        if ra: cwd = root                                 # (the account cannot enter the service's checkout)
        with open(logf, "ab") as lf: p = spawn([sys.executable, str(s), *args], cwd, env, lf, **({"run_as": ra} if ra else {}))
    except OSError as e:
        why = f"没能启动脚本（{type(e).__name__}）"
        _record(root, gid, state="failed", ended=now(), outcome=why); _finish_queue(qf, req, "failed", why)
        note(root, f"付费生成没能开始（{s.name}）：{why}。请告诉用户，并说明会请人看一下。"); return None
    _record(root, gid, pid=p.pid, pid_start=osdirs.pid_start(p.pid))
    log(f"{root.name}: gen {req.get('id')} started {s.name} (go card {gid}, pid {p.pid}, log {logf})")

    def wait():
        try: rc = p.wait(timeout=max_secs)
        except subprocess.TimeoutExpired:
            osdirs.stop_group(p.pid); rc = "timeout"
        except Exception as e: rc = f"error {type(e).__name__}"
        _scrub_log(logf, env)
        tail = _tail(logf, env); ok = rc == 0
        state = "done" if ok else "failed"
        outcome = f"{'完成' if ok else '失败'}，退出码 {rc}" + (f"；最后的输出：{tail}" if tail else "")
        _record(root, gid, state=state, rc=rc, ended=now(), outcome=outcome)
        _finish_queue(qf, req, state, outcome)
        if ok:
            note(root, f"付费生成已完成：{s.name}（开工卡 {gid}）。{outcome}。日志：{logf}。请自己先看一遍结果，再发预览 / 候选卡给用户。")
        else:
            note(root, f"付费生成没有成功：{s.name}（开工卡 {gid}）。{outcome}。日志：{logf}。请用简单的中文告诉用户没画成，"
                       f"已经画好的部分照常发给她看；要重试需要一张新的开工卡。")
        log(f"{root.name}: gen {req.get('id')} {state} rc={rc}")

    t = threading.Thread(target=wait, name=f"gen-{root.name}", daemon=True); t.start(); return t


def _progress_card(root, rid, spec):
    """A progress card in her chat, one step per job (the old scripts' `gameanything chat progress`), kept current by the run."""
    T = Thread(root); key = f"gen-{rid}"; steps = [{"text": j["name"], "state": "todo"} for j in spec["jobs"]]
    title = f"正在生成（{spec['tool']}）"

    def upd(i=None, state=None):
        if i is not None: steps[i]["state"] = state
        try: T.card({"kind": "progress", "key": key, "milestone": "生成", "title": title, "steps": steps},
                    card_en={"title": f"Generating ({spec['tool']})", "milestone": "generation"}, session="gen")
        except Exception: pass                                        # the card is a courtesy; the run goes on without it
    if len(steps) > 1: upd()
    return upd if len(steps) > 1 else None


def start_adapter(root, qf, req, log_dir, log=print, max_secs=GEN_MAX_SECS, http=None):
    """An adapter request: checked (check_adapter), then run in-process in a thread with the owner's key (never os.environ)."""
    try:
        spec, pid, gid, est, budget = check_adapter(root, req)
        ad, cap = gen.parse_tool(spec["tool"])
        env, blk = env_for(root)
        if blk: raise GenError(f"项目所有者的账号还不能用来付费生成：{blk}")
        key = None
        if ad.key:
            key = keys.lookup(ad.key, env)
            if not key: raise GenError(f"项目所有者还没有设置 {ad.key}（{ad.title} 的 API key）：请她在「我的 agent」→「素材生成 API keys」里保存一次，"
                                       f"单机版也可以 gameanything gen key set {ad.key}")
    except GenError as e:
        reject(root, qf, req, str(e)); log(f"{root.name}: gen request {req.get('id')} rejected: {e}"); return None
    log_dir = Path(log_dir) / "gen"; log_dir.mkdir(parents=True, exist_ok=True)
    logf = log_dir / f"{root.name}-{req.get('id')}.log"
    renv = {**(env or {}), **({"GEN_API_KEY": key} if key else {})}                    # what redact() hides
    label = f"gameanything gen {spec['tool']}"
    _record(root, gid, state="running", started=now(), request=req.get("id"), script=label, host=HOST, log=str(logf), pid=os.getpid(),
            pid_start=osdirs.pid_start(os.getpid()), estimate_usd=est["cost_usd_max"])
    req = {**req, "state": "running", "go_card": gid}; _write(qf, req)
    log(f"{root.name}: gen {req.get('id')} started {label} ({len(spec['jobs'])} jobs, go card {gid}, log {logf})")
    lines = []

    def say(m):
        m = redact(m, renv); lines.append(m)
        try:
            with open(logf, "a", encoding="utf-8") as f: f.write(f"{now()} {m}\n")
        except OSError: pass

    def work():
        try:
            r = gen.run(root, spec, key, http=http, log=say, cards={"permission": pid, "go": gid}, request_id=req.get("id"),
                        budget_usd=budget, deadline=time.time() + max_secs, poll_secs=POLL_SECS, progress=_progress_card(root, req.get("id"), spec))
        except Exception as e:
            r = {"done": [], "skipped": [], "failed": [{"name": "*", "error": redact(f"{type(e).__name__}: {e}", renv)[:400]}], "files": [], "cost_usd": None}
        ok = not r["failed"]; state = "done" if ok else "failed"
        fails = "；".join(f"{f['name']}: {redact(f['error'], renv)[:160]}" for f in r["failed"][:4])
        outcome = (f"{'完成' if ok else '部分没成功' if r['done'] else '失败'}：做好 {len(r['done'])} 个" + (f"，已有跳过 {len(r['skipped'])} 个" if r["skipped"] else "")
                   + (f"，失败 {len(r['failed'])} 个（{fails}）" if r["failed"] else "") + (f"，花费约 ${r['cost_usd']:g}" if r.get("cost_usd") else ""))
        _record(root, gid, state=state, ended=now(), outcome=outcome, files=len(r["files"]))
        _finish_queue(qf, req, state, outcome)
        where = f"4_design/{spec['out']}/（index.yaml 里有每个文件和 sha256）"
        if ok: note(root, f"付费生成已完成：{label}（开工卡 {gid}）。{outcome}。文件在 {where}。日志：{logf}。请自己先看一遍结果，再发预览 / 候选卡给用户。")
        else: note(root, f"付费生成没有全部成功：{label}（开工卡 {gid}）。{outcome}。文件在 {where}。日志：{logf}。请用简单的中文告诉用户，"
                         f"已经做好的部分照常发给她看；要重试需要一张新的开工卡。")
        log(f"{root.name}: gen {req.get('id')} {state}")

    t = threading.Thread(target=work, name=f"gen-{root.name}", daemon=True); t.start(); return t


def busy_elsewhere(root) -> bool:
    """A run started by an earlier agentd that still runs (adopted: wait for it). One that died is closed with a note."""
    d = used(root); busy = False
    for gid, r in d.items():
        if r.get("state") != "running" or r.get("host") != HOST: continue
        if r.get("pid") and osdirs.pid_alive(r.get("pid"), r.get("pid_start")): busy = True; continue
        _record(root, gid, state="interrupted", ended=now(), outcome="后台重启时中断，结果不确定")
        for qf in pending(root):
            q = _read(qf) or {}
            if q.get("go_card") == gid: _finish_queue(qf, q, "failed", "interrupted")
        note(root, f"付费生成（{r.get('script')}，开工卡 {gid}）在后台重启时中断了，结果不确定。日志：{r.get('log')}。"
                   f"请看一下已经生成了哪些文件，告诉用户；要补画需要一张新的开工卡。")
    return busy


def status_lines(root) -> list:
    out = [f"queued: {q.name} {(_read(q) or {}).get('tool')}" for q in pending(root)]
    for gid, r in used(root).items(): out.append(f"go card {gid}: {r.get('state')} {r.get('script')} {r.get('started')} {r.get('outcome') or ''}".rstrip())
    return out or ["no paid generation requests"]
