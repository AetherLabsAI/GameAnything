"""Keep a build's progress card current while it runs: which playtest round it is in, out of how many, and how long it has run.

    gameanything build watch --project P --session S --key K --milestone M --trial <gamebench trial dir> \
        --steps "done:…" "current:构建（{round_text} · {time_text}）" "…" --steps-en "done:…" "current:Build ({round_en} · {time_en})" "…"

Reads only the trial folder: result.json (status, started, playtest.max_rounds) and playtest/round_N/. Every minute, when the round or
the hour changes, it posts the progress card again (same key, so the page shows one card); it exits when the build is no longer running.
Placeholders in --steps: {round} {max_rounds} {round_text} {time_text}; in --steps-en: {round_en} {time_en}.
"""
import json
import time
from datetime import datetime
from pathlib import Path


def state(trial: Path, max_rounds: int, wall_min: int) -> dict:
    try: r = json.loads((trial / "result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError): r = {}
    rounds = len(list((trial / "playtest").glob("round_*"))) if (trial / "playtest").is_dir() else 0
    mx = (r.get("playtest") or {}).get("max_rounds") or max_rounds
    try: el = ((datetime.fromisoformat(r["finished"]) if r.get("finished") else datetime.now()) - datetime.fromisoformat(r["started"])).total_seconds() / 60
    except (KeyError, TypeError, ValueError): el = 0
    h, m = int(el // 60), int(el % 60); wh = wall_min / 60
    wall = f"{wh:g}"
    return {"status": r.get("status", "running"), "round": rounds, "max_rounds": mx,
            "round_text": f"试玩第 {rounds} 轮（最多 {mx} 轮）" if rounds else f"还没开始试玩（最多 {mx} 轮）",
            "round_en": f"playtest round {rounds} of at most {mx}" if rounds else f"no playtest yet (at most {mx} rounds)",
            "time_text": f"已跑 {h} 小时 {m} 分（最多 {wall} 小时）", "time_en": f"{h} h {m} min so far (at most {wall} h)", "hour": h,
            "plain": (f"正在第 {rounds} 轮试玩评审（最多 {mx} 轮）" if rounds else f"还没开始试玩评审（最多 {mx} 轮）") + f"，已经跑了 {h} 小时 {m} 分，最多跑 {wall} 小时",
            "plain_en": (f"in playtest review round {rounds} (at most {mx})" if rounds else f"no playtest review yet (at most {mx} rounds)") + f"; running for {h} h {m} min, at most {wall} h",
            "meter": {"round": rounds, "max_rounds": mx, "elapsed_min": round(el), "wall_min": wall_min, "done": r.get("status") not in (None, "running")}}


def _steps(xs):
    out = []
    for x in xs:
        st, _, tx = x.partition(":")
        out.append({"state": st, "text": tx} if st in ("done", "current", "todo") and tx else {"state": "todo", "text": x})
    return out


def post(T, session, key, milestone, title, steps, title_en=None, steps_en=None, meter=None):
    """The same progress card `gameanything chat progress` posts (same key = the page shows one card)."""
    st = _steps(steps); en = {}
    if steps_en: en["steps"] = [{"state": a["state"], "text": b["text"]} for a, b in zip(st, _steps(steps_en))]
    if title_en: en["title"] = title_en
    return T.card({"kind": "progress", "title": title, "milestone": milestone or key, "key": key, "steps": st, **({"meter": meter} if meter else {})},
                  card_en=en or None, session=session)


def watch(T, session, key, milestone, trial: Path, steps, steps_en, max_rounds=6, wall_min=300, every=60, title="构建中", title_en="Building", runner=None):
    last = None
    while True:
        s = state(trial, max_rounds, wall_min)
        sig = (s["round"], s["meter"]["elapsed_min"] // 10, s["status"])        # every new round, every 10 minutes, and at the end
        latest = next((e for e in reversed(T.events()) if e.get("type") == "card" and (e.get("card") or {}).get("key") == key), None)
        if last is not None and latest and not latest["card"].get("meter"): return s     # the agent already posted the next stage: do not overwrite it
        if sig != last:
            post(T, session, key, milestone, title, [x.format(**s) for x in steps], title_en, [x.format(**s) for x in steps_en],
                 {**s["meter"], **({"runner": runner} if runner else {})})
            last = sig
        if s["status"] != "running": return s
        time.sleep(every)


# ---- 5_build/<m>/build_status.yaml: what the page's "building" banner shows while a builder runs (the coordinator writes it: gameanything build status)
def status_file(root: Path, m: str) -> Path:
    if not m or "/" in m or "\\" in m or m.startswith("."): raise ValueError(f"milestone 不对：{m!r}")
    return Path(root) / "5_build" / m / "build_status.yaml"


def read_status(root: Path, m: str) -> dict:
    import yaml
    try: d = yaml.safe_load(status_file(root, m).read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, yaml.YAMLError): return {}
    return d if isinstance(d, dict) else {}


def write_status(root: Path, m: str, round_=None, max_rounds=None, step=None, started=None, done=False, step_en=None, blocked=None):
    """Merge into build_status.yaml {round, max_rounds, step, step_en, started, updated, done, blocked}; -> (file, data). Values not given
    are kept, except `blocked` ({reason, at}: the builder stopped because the lab environment is gone, builds.py resumes it): any write
    with a new round / step / done and no blocked= clears it."""
    import yaml
    for n, v in (("round", round_), ("max", max_rounds)):
        if v is not None and not (isinstance(v, int) and 0 <= v <= 100): raise ValueError(f"--{n} 应该是 0 到 100 的整数")
    if round_ is not None and max_rounds is not None and round_ > max_rounds: raise ValueError("--round 不能大于 --max")
    if started:
        try: datetime.fromisoformat(started)
        except ValueError: raise ValueError(f"--started 应该是 ISO 时间，例如 2026-10-23T19:25:00，收到：{started}")
    f = status_file(root, m); d = read_status(root, m)
    now_ = datetime.now().isoformat(timespec="seconds")
    if d.get("done") and not done: d = {}                                   # a new build of the same milestone
    for k, v in (("round", round_), ("max_rounds", max_rounds), ("step", step), ("step_en", step_en), ("started", started)):
        if v is not None: d[k] = v
    if blocked: d["blocked"] = {"reason": str(blocked)[:500], "at": now_}
    elif round_ is not None or step is not None or done: d.pop("blocked", None)
    d.setdefault("started", now_); d["updated"] = now_; d["done"] = bool(done)
    f.parent.mkdir(parents=True, exist_ok=True); tmp = f.with_name(".build_status.yaml.tmp")
    tmp.write_text("# the page's \"building\" banner (gameanything build status)\n" + yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
    import os; os.replace(tmp, f)
    return f, d
