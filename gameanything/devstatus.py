"""A project's development status: <project>/5_build/STATUS.yaml (skills/gameanything/references/dev-status.md).

Where the project is: each of her requirements (from go cards, the world plan, her feedback) with its state, who verified it and the
evidence; known issues; regressions; the recheck list every round re-verifies; her comments not handled / answered yet; decisions.
Builders and playtesters update it through `gameanything status …`; the resident answers "where are we" from it; the 开发状态 page shows it
(read only); `gameanything build deliver` warns from it; `gameanything status card` makes the result card from it.

    load(root) -> (data, problems)    normalized (every list a list of dicts, unknown states kept but reported); never raises on a bad file
    save(root, data)                  atomic write with the header comment
    init(root, force=False)           seed items from the latest go card, the newest world_plan milestone and her unhandled words
    set_item / add_issue / add_regression / recheck / feedback / decide     the edits behind the CLI
    deliver_warnings(root, m)         what `gameanything build deliver` warns about
    summary(data) / result_card(root, m)
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path

import yaml

STATES = ("done", "partial", "todo", "broken", "regressed")
BAD = ("broken", "regressed")
BY = ("builder", "playtester")
SEVERITY = ("low", "medium", "high")
RESULTS = ("pass", "fail")
FB_STATES = ("open", "answered", "handled")
LISTS = ("items", "known_issues", "regressions", "recheck", "open_feedback", "decisions")
PREFIX = {"items": "r", "known_issues": "k", "regressions": "g", "recheck": "c"}
HEADER = ("# 开发状态（gameanything status 写的；格式见 skills/gameanything/references/dev-status.md）。网页「开发状态」页按这个文件显示。\n"
          "# items 她的每条要求 · known_issues 已知问题 · regressions 回归 · recheck 每轮复查 · open_feedback 她还没处理的话 · decisions 决定\n")


class StatusError(ValueError):
    pass


def path(root) -> Path:
    return Path(root) / "5_build" / "STATUS.yaml"


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _s(v) -> str:
    return "" if v is None else str(v)


# ---------------------------------------------------------------- read / write
def empty() -> dict:
    return {"build": None, "updated": None, **{k: [] for k in LISTS}}


def normalize(d) -> tuple:
    """-> (data, problems). Lists of mappings only; ids filled in (r1, k1, …); unknown enum values kept and reported."""
    P = []
    if d is None: return empty(), []
    if not isinstance(d, dict): return empty(), [f"STATUS.yaml 应该是一个映射，现在是 {type(d).__name__}"]
    out = {**empty(), **{k: v for k, v in d.items() if k not in LISTS}}
    for k in LISTS:
        v = d.get(k)
        if v is None: continue
        if not isinstance(v, list): P.append(f"{k} 应该是列表"); continue
        rows = []
        for i, x in enumerate(v):
            if isinstance(x, str) and k in ("items", "recheck", "decisions", "known_issues"): x = {"text": x}
            if not isinstance(x, dict): P.append(f"{k} 第 {i + 1} 项应该是一个映射"); continue
            x = dict(x)
            if k in PREFIX and x.get("id") in (None, ""): x["id"] = f"{PREFIX[k]}{i + 1}"
            if "id" in x: x["id"] = _s(x["id"])
            rows.append(x)
        ids = [x.get("id") for x in rows if x.get("id")]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup: P.append(f"{k} 的 id 重复：{', '.join(dup)}")
        out[k] = rows
    for x in out["items"]:
        if x.get("state") not in STATES: P.append(f"items {x['id']}: state {x.get('state')!r} 不是 {' / '.join(STATES)}")
        if x.get("verified_by") not in (None, "", *BY): P.append(f"items {x['id']}: verified_by {x.get('verified_by')!r} 不是 builder / playtester")
        if not _s(x.get("text")).strip(): P.append(f"items {x['id']}: 没有 text")
        if x.get("state") == "regressed" and not any(g.get("item") == x["id"] and not g.get("fixed_in") for g in out["regressions"]):
            P.append(f"items {x['id']}: regressed，但 regressions 里没有对应的一条")
    for x in out["known_issues"]:
        if x.get("severity") not in (None, "", *SEVERITY): P.append(f"known_issues {x['id']}: severity {x.get('severity')!r} 不是 low / medium / high")
    for x in out["recheck"]:
        if x.get("last_result") not in (None, "", *RESULTS): P.append(f"recheck {x['id']}: last_result {x.get('last_result')!r} 不是 pass / fail")
    for x in out["open_feedback"]:
        if x.get("state") not in (None, "", *FB_STATES): P.append(f"open_feedback {x.get('event')}: state {x.get('state')!r} 不是 open / answered / handled")
    return out, P


def load(root) -> tuple:
    """-> (data, problems); data is empty() when there is no file (problems then empty too: `exists(root)` tells them apart)."""
    f = path(root)
    try: d = yaml.safe_load(f.read_text(encoding="utf-8"))
    except FileNotFoundError: return empty(), []
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e: return empty(), [f"STATUS.yaml 读不了：{str(e).splitlines()[0] if str(e) else type(e).__name__}"]
    return normalize(d)


def exists(root) -> bool:
    return path(root).is_file()


def save(root, d: dict):
    d = {**d, "updated": now()}
    order = ["build", "updated", *LISTS]
    d = {**{k: d.get(k) for k in order}, **{k: v for k, v in d.items() if k not in order}}
    f = path(root); f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name("." + f.name + ".tmp")
    tmp.write_text(HEADER + yaml.safe_dump(d, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
    os.replace(tmp, f)
    return f


def _edit(root, fn):
    """Load (refusing a file that does not parse: never overwrite her project's file blindly), apply fn(data), save."""
    d, P = load(root)
    if P and any("读不了" in p or "应该是一个映射" in p for p in P): raise StatusError("；".join(P) + "：先把 STATUS.yaml 修好")
    r = fn(d); save(root, d); return r


def _next_id(rows, prefix) -> str:
    n = max([int(m.group(1)) for x in rows for m in [re.match(rf"^{prefix}(\d+)$", _s(x.get("id")))] if m] or [0])
    return f"{prefix}{n + 1}"


def _by_id(rows, i):
    return next((x for x in rows if x.get("id") == i), None)


# ---------------------------------------------------------------- init
def _latest_go(root):
    """(event, card) of the newest go card in the thread, or (None, None)."""
    from .conversation import Thread
    evs = Thread(root).events()
    for e in reversed(evs):
        if e.get("type") == "card" and (e.get("card") or {}).get("kind") == "go": return e, e["card"]
    return None, None


def _milestones(root) -> dict:
    try: d = yaml.safe_load((Path(root) / "4_design" / "world_plan.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError): return {}
    wp = d.get("world_plan") if isinstance(d, dict) else None
    ms = wp.get("milestones") if isinstance(wp, dict) else None
    return {str(k): v for k, v in ms.items() if isinstance(v, dict)} if isinstance(ms, dict) else {}


def _item_text(x) -> str:
    if isinstance(x, str): return x.strip()
    if isinstance(x, dict): return _s(x.get("text") or x.get("title") or x.get("what")).strip()
    return ""


def _plan_items(v: dict) -> list:
    if v.get("steps"): return [t for t in (_item_text(s) for s in v["steps"]) if t]
    what = _s(v.get("what")); body = what.split("：", 1)[1] if "：" in what else what
    return [p.strip(" 。;；") for p in re.split(r"[、+＋;；]", body) if p.strip(" 。;；")]


def unhandled_feedback(root, since_event=None) -> list:
    """Her own words in the chat (not page actions) after `since_event` (default: the newest go card) -> [{event, text, at, state: open}]."""
    from .conversation import Thread
    evs = Thread(root).events()
    if since_event is None:
        e, _ = _latest_go(root); since_event = e["id"] if e else None
    ids = [e.get("id") for e in evs]
    after = evs[ids.index(since_event) + 1:] if since_event in ids else evs
    return [{"event": e["id"], "text": _s(e.get("text")).strip(), "at": e.get("at"), "state": "open"} for e in after
            if e.get("from") == "user" and e.get("type") == "text" and not e.get("auto") and _s(e.get("text")).strip()]


def seeds(root) -> tuple:
    """-> (items, open_feedback, build) that init would write."""
    ev, go = _latest_go(root); ms = _milestones(root)
    m_new = next((m for m in reversed(list(ms)) if _plan_items(ms[m])), None)      # the newest milestone that says what it does
    items, seen = [], set()
    def put(text, source):
        t = text.strip()
        if t and t not in seen: seen.add(t); items.append({"text": t, "source": source, "state": "todo"})
    for x in (go or {}).get("items") or []: put(_item_text(x), f"go:{ev['id']}")
    if m_new and not go: [put(t, f"plan:{m_new}") for t in _plan_items(ms[m_new])]
    fb = unhandled_feedback(root, ev["id"] if ev else None)
    built = [m for m, v in ms.items() if v.get("status") in ("built", "accepted")]
    return items, fb, built[-1] if built else None


def init(root, force=False) -> dict:
    """Write STATUS.yaml from the seeds. An existing file is kept (-> {"created": False}) unless force: then the seeded items are merged in
    (an item with the same text keeps its state, evidence and id) and the other lists are kept."""
    if exists(root) and not force: return {"created": False, "file": str(path(root)), "added": 0}
    items, fb, build = seeds(root)
    d, P = load(root) if exists(root) else (empty(), [])
    if P and any("读不了" in p for p in P): raise StatusError("；".join(P))
    have = {_s(x.get("text")).strip() for x in d["items"]}; n = 0
    for x in items:
        if x["text"] in have: continue
        d["items"].append({"id": _next_id(d["items"], "r"), **x, "since": None, "verified_by": None, "evidence": None}); n += 1
    ev_have = {x.get("event") for x in d["open_feedback"]}
    d["open_feedback"] += [x for x in fb if x["event"] not in ev_have]
    if build and not d.get("build"): d["build"] = build
    save(root, d)
    return {"created": True, "file": str(path(root)), "added": n, "feedback": len(fb)}


# ---------------------------------------------------------------- edits
def set_item(root, iid, state=None, text=None, build=None, by=None, evidence=None, text_en=None, source=None) -> dict:
    """Change (or, with text, create) an item. done -> broken / regressed records a regression (broke_in = build)."""
    if state is not None and state not in STATES: raise StatusError(f"--state 要是 {' / '.join(STATES)}")
    if by is not None and by not in BY: raise StatusError("--by 要是 builder / playtester")
    def fn(d):
        x = _by_id(d["items"], iid) if iid else None
        if x is None:
            if not text: raise StatusError(f"没有条目 {iid}：新建一条要给 --text")
            x = {"id": iid or _next_id(d["items"], "r"), "text": text, "source": source, "state": "todo", "since": None, "verified_by": None, "evidence": None}
            d["items"].append(x)
        note = None
        old = x.get("state")
        if text: x["text"] = text
        if text_en: x["text_en"] = text_en
        if source: x["source"] = source
        if state:
            st = "regressed" if state == "broken" and old in ("done", "regressed") else state
            if st != old or build: x["since"] = build or x.get("since")
            x["state"] = st
            if st == "regressed" and old == "done":
                g = {"id": _next_id(d["regressions"], "g"), "item": x["id"], "what": x["text"], "broke_in": build, "cause": None, "fixed_in": None}
                d["regressions"].append(g); note = f"记了一条回归 {g['id']}（{x['id']} 以前做到了）：用 add-regression --id {g['id']} --cause … 补原因"
            if st == "done":
                for g in d["regressions"]:
                    if g.get("item") == x["id"] and not g.get("fixed_in") and build: g["fixed_in"] = build
        if by: x["verified_by"] = by
        if evidence: x["evidence"] = evidence
        if build: d["build"] = _later(d.get("build"), build)
        return {"item": dict(x), "note": note}
    r = _edit(root, fn)
    if state:                                                        # her feedback records linked to this item follow it (feedback.py)
        from . import feedback
        r["records"] = feedback.on_item(root, r["item"]["id"], r["item"].get("state"), build, by, evidence)
    return r


def _later(a, b):
    """The later of two build labels (m3 < m3b < m10); b when a is empty."""
    if not a: return b
    k = lambda s: [int(t) if t.isdigit() else t for t in re.findall(r"\d+|\D+", str(s))]
    try: return b if k(b) >= k(a) else a
    except TypeError: return b


def add_issue(root, text=None, severity="medium", since=None, plan=None, iid=None, fixed=False) -> dict:
    if severity not in SEVERITY: raise StatusError("--severity 要是 low / medium / high")
    def fn(d):
        if iid:
            x = _by_id(d["known_issues"], iid)
            if x is None: raise StatusError(f"没有已知问题 {iid}")
            if fixed: d["known_issues"].remove(x); return {"removed": x}
            for k, v in (("text", text), ("plan", plan), ("since", since)):
                if v: x[k] = v
            x["severity"] = severity or x.get("severity"); return {"issue": dict(x)}
        if not text: raise StatusError("--text 不能是空的")
        x = {"id": _next_id(d["known_issues"], "k"), "text": text, "severity": severity, "since": since, "plan": plan}
        d["known_issues"].append(x); return {"issue": dict(x)}
    return _edit(root, fn)


def add_regression(root, what=None, broke_in=None, cause=None, fixed_in=None, item=None, iid=None) -> dict:
    def fn(d):
        if iid:
            x = _by_id(d["regressions"], iid)
            if x is None: raise StatusError(f"没有回归 {iid}")
        else:
            if not what or not broke_in: raise StatusError("新的回归要 --what 和 --broke-in")
            x = {"id": _next_id(d["regressions"], "g"), "item": None, "what": what, "broke_in": broke_in, "cause": None, "fixed_in": None}
            d["regressions"].append(x)
        for k, v in (("what", what), ("broke_in", broke_in), ("cause", cause), ("fixed_in", fixed_in), ("item", item)):
            if v: x[k] = v
        it = _by_id(d["items"], x.get("item")) if x.get("item") else None
        if it is not None:
            if x.get("fixed_in"):
                if it.get("state") == "regressed": it["state"] = "done"; it["since"] = x["fixed_in"]
            elif it.get("state") != "regressed": it["state"] = "regressed"; it["since"] = x.get("broke_in")
        return {"regression": dict(x)}
    return _edit(root, fn)


def recheck(root, build=None, add=(), passed=(), failed=(), note=None, by="playtester") -> dict:
    """Add checklist lines; record pass / fail for this build. -> {todo: the lines not rechecked in `build` yet, ...}."""
    if by not in BY: raise StatusError("--by 要是 builder / playtester")
    def fn(d):
        b = build or d.get("build")
        for t in add or ():
            if t and not any(_s(x.get("text")) == t for x in d["recheck"]):
                d["recheck"].append({"id": _next_id(d["recheck"], "c"), "text": t, "last_build": None, "last_result": None})
        for ids, res in ((passed, "pass"), (failed, "fail")):
            for i in ids or ():
                x = _by_id(d["recheck"], i)
                if x is None: raise StatusError(f"复查清单里没有 {i}")
                if not b: raise StatusError("要 --build（哪一版复查的）")
                x.update({"last_build": b, "last_result": res, "at": now(), "by": by})
                if res == "fail" and note: x["note"] = note
                elif res == "pass": x.pop("note", None)
        if b and (passed or failed): d["build"] = _later(d.get("build"), b)
        return {"build": b, "todo": [dict(x) for x in d["recheck"] if not b or x.get("last_build") != b],
                "failed": [dict(x) for x in d["recheck"] if b and x.get("last_build") == b and x.get("last_result") == "fail"]}
    return _edit(root, fn)


def feedback(root, event, state=None, text=None, add=False) -> dict:
    if state is not None and state not in FB_STATES: raise StatusError("--state 要是 open / answered / handled")
    def fn(d):
        x = next((f for f in d["open_feedback"] if f.get("event") == event), None)
        if x is None:
            if not add: raise StatusError(f"open_feedback 里没有 {event}（新加一条用 --add-event）")
            tx, at = text, now()
            if not tx:
                from .conversation import Thread
                e = next((e for e in Thread(root).events() if e.get("id") == event), None)
                if e is None: raise StatusError(f"对话里没有事件 {event}")
                tx = _s(e.get("text")).strip(); at = e.get("at")
            x = {"event": event, "text": tx, "at": at, "state": "open"}; d["open_feedback"].append(x)
        if state: x["state"] = state
        return {"feedback": dict(x)}
    return _edit(root, fn)


def decide(root, text, event=None) -> dict:
    if not text: raise StatusError("--text 不能是空的")
    def fn(d):
        x = {"at": now(), "text": text, **({"event": event} if event else {})}; d["decisions"].append(x); return {"decision": x}
    return _edit(root, fn)


# ---------------------------------------------------------------- summaries
def counts(d: dict) -> dict:
    c = {s: 0 for s in STATES}
    for x in d["items"]: c[x.get("state")] = c.get(x.get("state"), 0) + 1
    return {**c, "total": len(d["items"]), "issues": len(d["known_issues"]),
            "regressions_open": sum(1 for g in d["regressions"] if not g.get("fixed_in")),
            "feedback_open": sum(1 for f in d["open_feedback"] if (f.get("state") or "open") == "open"),
            "recheck_total": len(d["recheck"]),
            "recheck_done": sum(1 for x in d["recheck"] if d.get("build") and x.get("last_build") == d.get("build"))}


def deliver_warnings(root, m) -> list:
    """What `gameanything build deliver` warns about (Chinese, one line each)."""
    if not exists(root): return ["没有 5_build/STATUS.yaml：先 gameanything status init，再按这一版的结果更新（dev-status.md）"]
    d, P = load(root); out = [f"STATUS.yaml：{p}" for p in P]
    bad = [x for x in d["items"] if x.get("state") in BAD]
    if bad: out.append("STATUS 里还有坏的条目：" + "；".join(f"{x['id']} {x.get('state')}「{_s(x.get('text'))[:30]}」" for x in bad))
    reg = [g for g in d["regressions"] if not g.get("fixed_in")]
    if reg: out.append(f"{len(reg)} 条回归还没修好：" + "；".join(f"{g['id']}「{_s(g.get('what'))[:30]}」" for g in reg))
    todo = [x for x in d["recheck"] if x.get("last_build") != m]
    if todo: out.append(f"这一版（{m}）的复查还没做完：{len(todo)}/{len(d['recheck'])} 条没复查（gameanything status recheck --build {m} --pass …）")
    fails = [x for x in d["recheck"] if x.get("last_build") == m and x.get("last_result") == "fail"]
    if fails: out.append("复查没通过：" + "；".join(f"{x['id']}「{_s(x.get('text'))[:30]}」" for x in fails))
    unver = [x for x in d["items"] if x.get("state") == "done" and x.get("verified_by") != "playtester"]
    if unver: out.append(f"{len(unver)} 条 done 只有 builder 自己说的，没有试玩独立确认：" + ", ".join(x["id"] for x in unver))
    return out


STATE_ZH = {"done": "做到了", "partial": "部分", "todo": "还没做", "broken": "坏了", "regressed": "回归"}


def show_text(root) -> str:
    d, P = load(root)
    if not exists(root): return f"[status] {path(root)} 还没有：gameanything status init --project {root}"
    c = counts(d)
    L = [f"[status] {path(root)}  build {d.get('build') or '?'}  更新于 {d.get('updated') or '?'}",
         f"  要求 {c['total']} 条：做到 {c['done']} · 部分 {c['partial']} · 还没做 {c['todo']} · 坏了 {c['broken']} · 回归 {c['regressed']}"]
    L += [f"  ! {p}" for p in P]
    for x in d["items"]:
        L.append(f"  [{STATE_ZH.get(x.get('state'), x.get('state'))}] {x['id']} {_s(x.get('text'))}" + (f"  （{x.get('since')}" + (f"，{x['verified_by']} 验证" if x.get("verified_by") else "") + "）" if x.get("since") else "")
                 + (f"\n        证据：{x['evidence']}" if x.get("evidence") else ""))
    if d["known_issues"]:
        L.append("  已知问题："); L += [f"    {x['id']} [{x.get('severity') or '?'}] {_s(x.get('text'))}" + (f"（计划：{x['plan']}）" if x.get("plan") else "") for x in d["known_issues"]]
    if d["regressions"]:
        L.append("  回归："); L += [f"    {g['id']} {_s(g.get('what'))}：{g.get('broke_in') or '?'} 坏的" + (f"，原因 {g['cause']}" if g.get("cause") else "")
                                  + (f"，{g['fixed_in']} 修好" if g.get("fixed_in") else "，还没修") for g in d["regressions"]]
    if d["recheck"]:
        L.append(f"  每轮复查（{c['recheck_done']}/{c['recheck_total']} 在 {d.get('build') or '?'} 复查过）：")
        L += [f"    {x['id']} {_s(x.get('text'))}  [{x.get('last_build') or '没复查过'}{' ' + x['last_result'] if x.get('last_result') else ''}]" for x in d["recheck"]]
    op = [f for f in d["open_feedback"] if (f.get("state") or "open") == "open"]
    if op: L.append("  她还没处理的话："); L += [f"    {f.get('event')} 「{_s(f.get('text'))[:60]}」" for f in op]
    if d["decisions"]: L.append("  决定："); L += [f"    {_s(x.get('at'))[:10]} {_s(x.get('text'))}" for x in d["decisions"]]
    return "\n".join(L)


def result_card(root, m, title=None, image=None) -> dict:
    """A `result` card from STATUS (stats from the items, issues and regressions); the resident adds the picture and posts it."""
    d, _ = load(root); c = counts(d)
    stats = [f"要求 {c['total']} 条：做到 {c['done']}" + (f" · 部分 {c['partial']}" if c["partial"] else "") + (f" · 还没做 {c['todo']}" if c["todo"] else "")
             + (f" · 坏了 {c['broken']}" if c["broken"] else "")]
    stats_en = [f"{c['total']} requirements: {c['done']} done" + (f" · {c['partial']} partly" if c["partial"] else "") + (f" · {c['todo']} to do" if c["todo"] else "")
                + (f" · {c['broken']} broken" if c["broken"] else "")]
    if c["regressed"] or c["regressions_open"]:
        stats.append(f"回归 {c['regressions_open']} 条没修好"); stats_en.append(f"{c['regressions_open']} regression(s) open")
    if c["issues"]: stats.append(f"已知问题 {c['issues']} 条"); stats_en.append(f"{c['issues']} known issue(s)")
    if c["recheck_total"]:
        n = sum(1 for x in d["recheck"] if x.get("last_build") == m and x.get("last_result") == "pass")
        stats.append(f"复查 {n}/{c['recheck_total']} 通过"); stats_en.append(f"recheck {n}/{c['recheck_total']} passed")
    first_pair = None
    try:                                                             # her earlier comments re-shot at the same anchor (feedback.py, verify.yaml)
        from . import feedback
        tv = feedback.to_verify(root, m) if feedback.uses(root, m, "verify") else []
        if tv:
            pr = [r for r in tv if (r.get("verification") or {}).get("m") == m and (r.get("verification") or {}).get("pair")]
            stats.append(f"你的 {len(tv)} 条意见：同一画面复拍 {len(pr)} 条"); stats_en.append(f"{len(tv)} of your comments: {len(pr)} re-shot at the same view")
            first_pair = pr[0]["verification"]["pair"] if pr else None
    except Exception: pass
    try:                                                             # what built it (builds.py .build_run.json: agent + model)
        from . import builds, live
        br = json.loads(builds.run_file(root, m).read_text(encoding="utf-8"))
        if br.get("provider"):
            who = live.run_label(br); stats.append(f"构建用的：{who}"); stats_en.append(f"Built with: {who}")
    except (OSError, ValueError, ImportError): pass
    card = {"kind": "result", "title": title or f"{m} 的结果", "milestone": m, "stats": stats, "open": f"#play/{m}", "en": {"stats": stats_en}}
    if image: card["image"] = image
    elif first_pair: card["image"] = "/media/" + first_pair
    return card
