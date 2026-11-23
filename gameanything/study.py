"""Study mode: the switch between the feedback loop as a product and the feedback loop as an experiment (docs/feedback-loop.md 0).

The rule (2026-10-27): everything that exists only to collect data for the paper is behind a switch that is OFF by default, is turned
on only while we run a study, and never changes what she experiences.

    OFF (default)  every version gets the full loop (records, confirm cards, same-anchor verification, the profile, the retrospective, the
                   critic). No blind condition, no `condition` event, no LLM-judge card or run, no label sheets / agreement, nothing is
                   written to feedback/metrics.jsonl, the 「反馈和改进」 metrics panel is hidden.
    ON             the evaluation runs as docs/feedback-loop.md section 7 describes (conditions, judge behind her permission card, the log).

The value is read fresh on every call (config/project.yaml `study:`, else the global default `study:` in <home>/settings.yaml), so agentd,
the builder and the resident pick up a change at once, also in builds that are already running.

    on(root) / state(root)          is study mode on for this project, and where the value comes from (project | global)
    set_project(root, value, by)    true | false | None (follow the global default); logs the boundary
    set_global(value, by)           the default for every project without its own value; logs the boundary in each project it changes
A change is logged as a `study` event in feedback/metrics.jsonl ({on, scope, by}): when it turns on (the first line of a study period)
and when it turns off (the last line: where the study data stops). Nothing else is written there while it is off.
"""
import json
import re
from datetime import datetime
from pathlib import Path

from . import layout, projects

KEY = "study"


def now() -> str: return datetime.now().isoformat(timespec="seconds")


def project_value(root):
    """config/project.yaml `study:` (True / False), or None when the project has no value of its own."""
    v = projects.config_of(root).get(KEY) if root else None
    return v if isinstance(v, bool) else None


def global_default() -> bool:
    return bool(projects.settings().get(KEY))


def on(root) -> bool:
    """Is study mode on for this project? Never raises (a broken config = off)."""
    try:
        v = project_value(root)
        return global_default() if v is None else v
    except Exception: return False


def state(root) -> dict:
    v = project_value(root)
    return {"on": global_default() if v is None else v, "source": "global" if v is None else "project", "global": global_default()}


def _boundary(root, value: bool, scope: str, by: str):
    """The `study` event that opens (on) or closes (off) a study period in this project's metrics log (written in both cases: it is the
    boundary of the study data, not study data itself)."""
    try:
        f = Path(root) / layout.FEEDBACK / "metrics.jsonl"
        if not value and not f.is_file(): return                     # never studied: nothing to close
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a", encoding="utf-8") as h:
            h.write(json.dumps({"at": now(), "ev": "study", "on": value, "scope": scope, "by": by}, ensure_ascii=False) + "\n")
    except OSError: pass


def _write(root, value):
    f = Path(root) / layout.CONFIG / "project.yaml"; t = f.read_text(encoding="utf-8") if f.exists() else ""
    if value is None: t = re.sub(r"(?m)^study:.*\n?", "", t)
    else:
        line = f"study: {'true' if value else 'false'}"
        if re.search(r"(?m)^study:.*$", t): t = re.sub(r"(?m)^study:.*$", line, t, count=1)
        else: t = (t.rstrip("\n") + "\n" if t else "") + line + "\n"
    f.parent.mkdir(parents=True, exist_ok=True); f.write_text(t, encoding="utf-8")


def set_project(root, value, by="cli") -> dict:
    """Study mode for one project: True / False, or None = follow the global default. -> state(root)."""
    if value is not None and not isinstance(value, bool): raise ValueError("study 要是 on / off / default")
    before = on(root); _write(root, value); after = on(root)
    if before != after: _boundary(root, after, "project", by)
    return state(root)


def set_global(value: bool, by="cli") -> list:
    """The global default (settings.yaml `study:`). Every registered project that follows it and changes gets the boundary event.
    -> [(project id, on)] of the projects whose state changed."""
    if not isinstance(value, bool): raise ValueError("study 要是 on / off")
    roots = [(e["id"], Path(e["path"])) for e in projects.load() if Path(e["path"]).is_dir()]
    before = {i: on(r) for i, r in roots}
    projects.save_settings({KEY: value})
    out = []
    for i, r in roots:
        a = on(r)
        if a != before[i]: _boundary(r, a, "global", by); out.append((i, a))
    return out


def text(root) -> str:
    s = state(root)
    return f"study={'on' if s['on'] else 'off'}" + (" (the global default)" if s["source"] == "global" else "") + f"; global default={'on' if s['global'] else 'off'}"
