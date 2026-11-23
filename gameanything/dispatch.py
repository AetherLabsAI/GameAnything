"""Automatic claiming (D20): one running agent session watches every registered project, so a new project never waits for the user
to say "continue".

`gameanything chat wait --all --session S` calls `scan()` every second:
- a project S owns: its owner record is kept fresh; new user words wake S. After `IDLE_RELEASE_SECS` with no event in the
  conversation S stops refreshing it, the owner goes stale and the slot frees (a later message claims it again).
- a project with no live owner and new user words: S claims it when fewer than `max_active_projects` projects have a live owner
  (projects.settings(), default 3, set in the browser), posts a status line and wakes; otherwise the project is marked queued
  (`conversation/.agent_queued`) and the page says so. Queued projects are taken oldest message first when a slot frees.
- a project another live session owns: left alone.
Nothing here starts an agent. The default is the supervisor `gameanything agentd` (agentd.py), which starts one headless run per project; while it is
alive, `wait --unowned` stays quiet (scan_unowned returns nothing) so a parent session that still runs the old watcher never doubles it.
"""
import json
import time
from pathlib import Path

from . import projects, users
from .conversation import Thread, now

IDLE_RELEASE_SECS = 2 * 3600


def _age(ts) -> float:
    return Thread._age(ts)


def _last_event_at(T: Thread):
    evs = T.events()
    return evs[-1]["at"] if evs else None


def _queued_path(T: Thread) -> Path:
    return T.dir / ".agent_queued"


def queued(T: Thread):
    """The page's "queued" note, or None (only while no live owner and the mark is recent)."""
    try: q = json.loads(_queued_path(T).read_text(encoding="utf-8"))
    except (OSError, ValueError): return None
    return q if _age(q.get("at")) <= 120 and not T.owner_live() else None


def scan(session: str) -> list:
    """One pass over the registered projects -> [(entry, Thread)] that have new user words for `session` (claimed if needed)."""
    cap = projects.settings()["max_active_projects"]
    rows = []
    for e in projects.load():
        root = Path(e["path"])
        if not (root / "conversation").is_dir() or not users.default_login_may_run(root): continue
        T = Thread(root); o = T.owner(); live = T.owner_live(o)
        rows.append((e, T, o, live, T.unread()))
    active = sum(1 for _, _, _, live, _ in rows if live)
    ready = []
    waiting = sorted((r for r in rows if not r[3] and r[4]), key=lambda r: r[4][0]["at"])      # unowned projects with new words, oldest first
    for e, T, o, live, new in rows:
        if live and T.is_mine(o, session):
            if new: ready.append((e, T))
            if new or _age(_last_event_at(T)) <= IDLE_RELEASE_SECS: T.touch_owner(session)        # idle long enough: let it go stale
            T.mark_waiting()
    for e, T, o, live, new in waiting:
        if active < cap:
            T.claim(session); active += 1
            _queued_path(T).unlink(missing_ok=True)
            T.append({"from": "system", "type": "status", "text": "agent 接上了这个项目", "text_en": "An agent picked up this project", "session": session})
            ready.append((e, T))
        else:
            _queued_path(T).write_text(json.dumps({"at": now(), "active": active, "cap": cap}), encoding="utf-8")
    return ready


def wait_all(session: str, timeout: float) -> list:
    """Block until some project has new user words for `session` -> [(entry, Thread)]; [] on timeout."""
    end = time.time() + timeout
    while True:
        ready = scan(session)
        if ready:
            for _, T in ready:
                new = T.unread()
                if new: T.notice(new[-1]["id"])
            return ready
        if time.time() >= end: return []
        time.sleep(1)


def scan_unowned() -> list:
    """Projects whose user has new words but no live agent owns them -> [(entry, Thread)], oldest message first. Claims NOTHING: used by a
    parent session that starts one resident sub-agent per project (the sub-agent claims). Respects `max_active_projects` like scan()."""
    cap = projects.settings()["max_active_projects"]
    rows = []
    from . import agentd
    if agentd.daemon_state()["alive"]: return []                 # the supervisor calls the agents
    for e in projects.load():
        root = Path(e["path"])
        if not (root / "conversation").is_dir() or not users.default_login_may_run(root): continue      # another hub user's project: agentd only
        T = Thread(root); live = T.owner_live()
        new = [] if live else T.unread()
        if not live and not new and T.owner() is None:            # a brand-new project: no agent has ever owned it, nobody has written yet
            new = [{"at": e.get("created") or now(), "id": "new-project"}]
        rows.append((e, T, live, new))
    active = sum(1 for r in rows if r[2])
    out = []
    for e, T, live, new in sorted((r for r in rows if not r[2] and r[3]), key=lambda r: r[3][0]["at"]):
        if active + len(out) < cap: out.append((e, T)); _queued_path(T).unlink(missing_ok=True)
        else: _queued_path(T).write_text(json.dumps({"at": now(), "active": active, "cap": cap}), encoding="utf-8")
    return out


def _tell_calling(T):
    """The user sees at once that an agent is on its way (starting a resident sub-agent takes about a minute): the page's status line
    says so for this message; the line in the thread is posted at most once per 10 minutes."""
    f = T.dir / ".agent_calling"; fresh = f.exists() and time.time() - f.stat().st_mtime < 600
    new = T.unread(); T.set_calling(new[-1]["id"] if new else None)
    if fresh: return
    T.append({"from": "system", "type": "status", "text": "收到，正在为这个项目叫一个 agent，大约一分钟内回复你",
              "text_en": "Got it - an agent is being called for this project, it will reply within about a minute"})


def wait_unowned(timeout: float, ignore=()) -> list:
    """Block until scan_unowned() finds a project (not in `ignore`, e.g. ones a sub-agent was just started for) -> [(entry, Thread)]; [] on timeout."""
    end = time.time() + timeout
    while True:
        ready = [(e, T) for e, T in scan_unowned() if e["path"] not in ignore]
        for e, T in ready: _tell_calling(T)
        if ready or time.time() >= end: return ready
        time.sleep(2)
