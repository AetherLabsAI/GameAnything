"""Her preference profile: personal taste learned from her feedback (docs/feedback-loop.md section 4). Private and per user:
<project list folder>/profiles/<owner>.yaml (owner = config/project.yaml `owner:`, `local` without one), never inside a project or a repo,
never shared with another user. The 我的偏好 page (#prefs) shows and edits it; `gameanything profile …` is the agents' side; feedback.brief
retrieves the entries that are on and apply to a project.

    load(owner) / save(owner, d)                       {entries: [...]}
    add(owner, text, …) / update(owner, pid, …) / toggle / remove      the edits
    applicable(owner, kind, game, project)             entries on, whose filters match, by confidence then last use
    mark_used(owner, ids)                              a brief showed them (last_used, used)
"""
import os
import re
from datetime import datetime
from pathlib import Path

import yaml
from . import clock

CONF = ("low", "medium", "high")
STATUS = ("candidate", "confirmed")
BY = ("retrospective", "resident", "her")
MODES = ("memory", "adaptation", "feature", "gameplay")
HEADER = "# 她的偏好（私人，只在这台电脑上；网页「我的偏好」可以看、改、关掉每一条；docs/feedback-loop.md 第 4 节）\n"


class ProfileError(ValueError):
    pass


def now() -> str: return datetime.now().isoformat(timespec="seconds")


def _safe(owner) -> str:
    o = re.sub(r"[^\w.-]", "_", str(owner or "local")).strip("._") or "local"
    return o


def path(owner) -> Path:
    from . import projects
    return projects.home() / "profiles" / f"{_safe(owner)}.yaml"


def owner_of(root) -> str:
    from . import projects
    return (projects.config_of(Path(root)) or {}).get("owner") or "local"


def load(owner) -> dict:
    try: d = yaml.safe_load(path(owner).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError): d = None
    es = d.get("entries") if isinstance(d, dict) else None
    return {"entries": [e for e in es if isinstance(e, dict)] if isinstance(es, list) else []}


def save(owner, d) -> Path:
    f = path(owner); f.parent.mkdir(parents=True, exist_ok=True); tmp = f.with_name(f".{f.name}.{os.getpid()}.tmp")
    tmp.write_text(HEADER + yaml.safe_dump(d, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
    try: os.chmod(tmp, 0o600)
    except OSError: pass
    os.replace(tmp, f); return f


def _list(v) -> list:
    if v is None: return []
    if isinstance(v, str): v = [x for x in re.split(r"[,\s]+", v) if x]
    return [str(x) for x in v if str(x).strip()]


def _next(es) -> str:
    n = max([int(m.group(1)) for e in es for m in [re.match(r"^p(\d+)$", str(e.get("id") or ""))] if m] or [0])
    return f"p{n + 1}"


def _check(confidence, status, by, modes):
    if confidence is not None and confidence not in CONF: raise ProfileError(f"confidence 要是 {' / '.join(CONF)}")
    if status is not None and status not in STATUS: raise ProfileError(f"status 要是 {' / '.join(STATUS)}")
    if by is not None and by not in BY: raise ProfileError(f"by 要是 {' / '.join(BY)}")
    bad = [m for m in _list(modes) if m not in MODES]
    if bad: raise ProfileError(f"modes 只能是 {' / '.join(MODES)}：{', '.join(bad)}")


def _from(v) -> list:
    """[{project, record}] from [{project, record}] or 'proj:f3' strings."""
    out = []
    for x in v or []:
        if isinstance(x, dict) and x.get("record"): out.append({"project": str(x.get("project") or ""), "record": str(x["record"])})
        elif isinstance(x, str) and x.strip():
            p, _, r = x.strip().rpartition(":"); out.append({"project": p, "record": r})
    return out


def add(owner, text, text_en=None, kind=None, modes=None, games=None, projects=None, sources=None, confidence=None, status=None, by="her", on=None) -> dict:
    text = str(text or "").strip()
    if not text: raise ProfileError("偏好不能是空的")
    by = by or "her"; _check(confidence, status, by, modes)
    d = load(owner)
    e = {"id": _next(d["entries"]), "text": text, **({"text_en": text_en.strip()} if text_en else {}), "kind": kind,
         "modes": _list(modes), "games": _list(games), "projects": _list(projects), "from": _from(sources),
         "confidence": confidence or ("high" if by == "her" else "low"), "status": status or ("confirmed" if by == "her" else "candidate"),
         "on": (by == "her") if on is None else bool(on), "created": now(), "updated": now(), "last_used": None, "used": 0, "hits": 0, "by": by,
         "history": [{"at": now(), "op": "add", "by": by, "status": None}]}
    e["history"][0]["status"] = e["status"]
    d["entries"].append(e); save(owner, d); return e


def _get(d, pid):
    e = next((x for x in d["entries"] if x.get("id") == pid), None)
    if e is None: raise ProfileError(f"没有偏好 {pid}")
    return e


def _hist(e, op, by, **kw):
    """Every change of an entry with who made it (candidates proposed / confirmed / switched off: Table 6 of the paper)."""
    if not e.get("history"): e["history"] = [{"at": e.get("created"), "op": "add", "by": e.get("by"), "status": None, "seeded": True}]   # entries from before history
    e["history"].append({"at": now(), "op": op, "by": by, **{k: v for k, v in kw.items() if v is not None}})


def update(owner, pid, by=None, **kw) -> dict:
    _check(kw.get("confidence"), kw.get("status"), None, kw.get("modes"))
    d = load(owner); e = _get(d, pid); was = (e.get("status"), e.get("on"), len(e.get("from") or []))
    for k in ("text", "text_en", "kind", "confidence", "status"):
        if kw.get(k) is not None: e[k] = str(kw[k]).strip()
    for k in ("modes", "games", "projects"):
        if kw.get(k) is not None: e[k] = _list(kw[k])
    if kw.get("sources") is not None:
        have = {(x["project"], x["record"]) for x in e.get("from") or []}
        e["from"] = (e.get("from") or []) + [x for x in _from(kw["sources"]) if (x["project"], x["record"]) not in have]
    if kw.get("on") is not None: e["on"] = bool(kw["on"])
    if not str(e.get("text") or "").strip(): raise ProfileError("偏好不能是空的")
    if on_confirms := (kw.get("on") is True and by == "her" and e.get("status") == "candidate"): e["status"] = "confirmed"   # her switch on = her yes
    ops = [o for o, hit in (("confirm", on_confirms or (was[0] != "confirmed" and e.get("status") == "confirmed")), ("on" if e.get("on") else "off", was[1] != e.get("on")),
                            ("evidence", len(e.get("from") or []) != was[2])) if hit] or ["edit"]
    for o in ops: _hist(e, o, by or "agent", sources=len(e.get("from") or []) if o == "evidence" else None)
    e["updated"] = now(); save(owner, d); return e


def toggle(owner, pid, on: bool, by=None) -> dict: return update(owner, pid, by=by, on=on)


def remove(owner, pid) -> dict:
    d = load(owner); e = _get(d, pid); d["entries"].remove(e); save(owner, d); return e


RANK = {"high": 0, "medium": 1, "low": 2}


def applicable(owner, kind=None, game=None, project=None) -> list:
    """Entries that are on and whose filters (modes / games / projects; empty = everywhere) match; confidence, then the latest use first."""
    out = [e for e in load(owner)["entries"] if e.get("on") and (not e.get("modes") or kind in e["modes"])
           and (not e.get("games") or game in e["games"]) and (not e.get("projects") or project in e["projects"])]
    return sorted(out, key=lambda e: (RANK.get(e.get("confidence"), 3), -(clock.epoch(e["last_used"]) if e.get("last_used") else 0)))


def mark_used(owner, ids):
    d = load(owner); hit = False
    for e in d["entries"]:
        if e.get("id") in ids: e["last_used"] = now(); e["used"] = int(e.get("used") or 0) + 1; hit = True
    if hit: save(owner, d)
