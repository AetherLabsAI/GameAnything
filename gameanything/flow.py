"""The flow of a project as a state machine: one source of truth for the browser's stepper (ui/onboard.py) and for the agents.

    gameanything flow next  --project P [--json]          where the project is, what is done, the exact action(s) for the agent, the step doc,
                                                 what blocks, what to tell her
    gameanything flow check --project P [--step S] [--json]   pass / fail of each exit criterion of a step (default: the step to work on)

Per kind an ordered list of steps. A step has: id, label, the stepper group it belongs to (`ui`), who acts (agent / user / coordinator),
the step doc (skills/gameanything/steps/<kind>/<id>.md), what it needs, and its exit criteria, computed from the project files and the
conversation events ({id, ok, why, who, level, recheck}). A step is done when every `fail`-level criterion passes; `warn` ones are only
reported. As before, a later step that is done marks every earlier one done (a project never shows as going backwards), so `current`
is the step after the last done one. An earlier step whose file-based (`recheck`) agent criteria fail is a `gap` (e.g. a video in the
work but no keyframes yet), only after her last confirmation: the agent fixes the first gap before the current step (`todo`).

Rounds (all kinds): 4_design/world_plan.yaml milestones are the versions. Once a version is built, the project loops: the steps from
ROUND_START[kind] on (plan → go → build → feedback → next_round) are judged for the round's milestone only (cards after the previous
version's result card, plan_review.yaml of that milestone, its own 5_build/<m>/), and everything before them stays done. After a
result, the agent asks what next (an options card), writes the next milestone, and the round starts again: never 「都完成了」 unless the
project's last step (memory / feature: 带回家, final accepted) is done.
"""
import json
import re
from pathlib import Path

import yaml

from . import layout, projects, shipped
from . import osdirs

SKILL = shipped.SKILL                    # the checkout's skills/gameanything, or the installed copy (shipped.py)
OPT_IN = {"adaptation", "memory", "feature", "gameplay"}   # kinds whose resident runs are built from core + mode + the current step (agentd.py)
CARD_IMAGE_KINDS = ("questions", "candidates", "result")   # cards that show pictures (cards.md: options cards do not)
KIND_DOCS = {k: f"modes/{k}.md" for k in ("memory", "feature", "adaptation", "gameplay")}     # the mode layer of the prompt
LONG_DOCS = {"memory": "references/memory-project-flow.md", "feature": "references/feature-flow.md",       # the long flow docs (read on demand)
             "adaptation": "references/adaptation-flow.md", "gameplay": "references/gameplay-flow.md"}
ROUND_START = {"adaptation": "questions", "memory": "design", "feature": "plan", "gameplay": "go"}       # where a later version starts again
DONE_MS, OPEN_MS = ("built", "accepted"), ("next", "building")


def _y(p: Path, default=None):
    """The YAML of a file, else `default`; a file of another shape than `default` (a list where a mapping belongs, a string) also reads
    as `default`: filecheck.py names the file, the flow never crashes on it (QA2 2026-10-30: world_plan.yaml as a list)."""
    try: d = yaml.safe_load(Path(p).read_text(encoding="utf-8")) or default
    except (OSError, yaml.YAMLError, UnicodeDecodeError): return default
    if isinstance(default, (dict, list)) and not isinstance(d, type(default)): return default
    return d


def opted_in(kind) -> bool: return kind in OPT_IN


# ---------------------------------------------------------------- facts: everything the criteria look at, read once
def facts(root, signals=None) -> dict:
    """signals (tests, the UI) replace onboard._signals(root); without them the go signals are recomputed from build go cards only."""
    from .conversation import Thread
    from .ui import onboard
    root = Path(root); cfg = projects.config_of(root)
    kind = cfg.get("kind") if cfg.get("kind") in onboard.FLOWS else "memory"
    evs = Thread(root).events()
    s = dict(signals if signals is not None else onboard._signals(root))
    wp = (_y(root / layout.DESIGN / "world_plan.yaml", {}) or {})
    wp = (wp.get("world_plan") if isinstance(wp, dict) else None) or {}
    F = {"root": root, "cfg": cfg, "kind": kind, "s": s, "events": evs, "idx": {e.get("id"): i for i, e in enumerate(evs)},
         "cards": [e for e in evs if e.get("type") == "card" and isinstance(e.get("card"), dict)],
         "answers": {e.get("card_id"): e for e in evs if e.get("type") == "answer"},
         "plan": wp if isinstance(wp, dict) else {}, "plan_review": _y(root / layout.FEEDBACK / "plan_review.yaml", {}) or {}}
    F["all_cards"] = F["cards"]
    bg = F["build_gos"] = _live([e for e in F["cards"] if build_go(F, e)])
    if signals is None:                                   # a preview / art go card is not the build's go card (onboard counts any go card)
        st = [str(_dv(v).get("status")) for v in _milestones(F).values() if isinstance(v, dict)]
        s["go_waiting"] = any(e["id"] not in F["answers"] for e in bg)
        s["started"] = any(_decision(F, e) == "start" for e in bg) or any(x in ("building", "built", "accepted") for x in st)
    F["round"] = _round(F)
    if F["round"]["prev"]: _scope_round(F)
    s["plan_ok"] = bool(s.get("plan_ok")) or bool(plan_approvals(F))
    if kind == "adaptation":
        from . import visuals
        R = root / layout.REMEMBER
        A = _y(R / "adaptation.yaml", {})
        F.update(A=A if isinstance(A, dict) else {}, A_raw=(R / "adaptation.yaml").exists(),
                 review=_y(root / layout.FEEDBACK / "adaptation_review.yaml", {}) or {}, videos=visuals.videos(root),
                 keyframes=visuals.index(root), people=visuals.people_index(root))
    return F


def _dv(v) -> dict: return v if isinstance(v, dict) else {}


def _milestones(F) -> dict:
    ms = (F.get("plan") or {}).get("milestones")
    return ms if isinstance(ms, dict) else {}


def _decision(F, e): return ((F["answers"].get(e["id"]) or {}).get("answer") or {}).get("decision")


def _live(evs) -> list:
    """Cards still in force: a card resent with the same key replaces the older one (Thread.cards)."""
    last = {}
    for e in evs:
        k = e["card"].get("key")
        if k: last[k] = e["id"]
    return [e for e in evs if not e["card"].get("key") or last[e["card"]["key"]] == e["id"]]


GEN_GO_KEY = re.compile(r"(^|[_\-])(art|gen|preview|previews|draw|redraw|meshy|image|images|img|pic|pics|3d|portraits?|looks)([_\-]|$)", re.I)
GEN_GO_TITLE = re.compile(r"^(重画|再画|画|生成|再重做 \d|重做 \d)|预览图|效果图|生图|卡图|Meshy|3D 模型|3D 菜品", re.I)


def _gen_go_keys(F) -> set:
    """Go cards named by a paid-generation request (gameanything gen request --go …): those are drawing go cards, not the build's."""
    out = set()
    q = F["root"] / "conversation" / ".gen_queue"
    for f in (q.rglob("*.json") if q.is_dir() else []):
        try: out.add(str(json.loads(f.read_text(encoding="utf-8")).get("go") or ""))
        except (OSError, ValueError, AttributeError): pass
    try:
        runs = json.loads((F["root"] / "conversation" / ".gen_runs.json").read_text(encoding="utf-8"))
        for r in (runs.values() if isinstance(runs, dict) else runs if isinstance(runs, list) else []):
            if isinstance(r, dict) and r.get("go"): out.add(str(r["go"]))
    except (OSError, ValueError): pass
    return out - {""}


def build_go(F, e) -> bool:
    """A go card that starts the build of a version (not a go card for drawing previews / art / 3D models)."""
    c = e["card"]
    if c.get("kind") != "go": return False
    if e.get("flow_step") in ("preview", "perceive"): return False
    if "gen_go" not in F: F["gen_go"] = _gen_go_keys(F)
    if (c.get("key") and str(c["key"]) in F["gen_go"]) or e["id"] in F["gen_go"]: return False
    if GEN_GO_KEY.search(str(c.get("key") or "")): return False
    return e.get("flow_step") in ("go", "build") or not GEN_GO_TITLE.search(str(c.get("title") or ""))


# ---------------------------------------------------------------- rounds: one version (milestone) at a time
def _result_for(F, m) -> int:
    """Index of the first result card of milestone m (its open #play/<m>, milestone, or a /build/<m>/ picture); -1 = none."""
    for e in F["all_cards"]:
        c = e["card"]
        if c.get("kind") != "result": continue
        o = str(c.get("open") or "")
        if c.get("milestone") == m or o == f"#play/{m}" or o.startswith(f"#play/{m}/") or any(f"/build/{m}/" in u for u in _imgs(c)):
            return F["idx"][e["id"]]
    return -1


def _round(F) -> dict:
    """{m, prev, cut, n, after}: the milestone this round is about (the open one, else the last built), the version before it, the index
    of that version's result card (cards after it belong to this round), and whether a later version is already planned."""
    ms = _milestones(F); st = {m: str(_dv(v).get("status") or "") if isinstance(v, dict) else "" for m, v in ms.items()}
    keys = [m for m in ms if m != "final"]
    at = {m: str((ms[m] or {}).get("at") or "") if isinstance(ms[m], dict) else "" for m in keys}
    done = sorted((m for m in keys if st[m] in DONE_MS), key=lambda m: at[m] or "0")      # by date when written (stable: file order otherwise)
    R = next((m for m in keys if st[m] in OPEN_MS), None)
    if R: M, prev = R, (done[-1] if done else None)
    elif done: M, prev = done[-1], (done[-2] if len(done) > 1 else None)
    else: M, prev = (keys[0] if keys else None), None
    cut = -1
    if prev:
        cut = _result_for(F, prev)
        if cut < 0:                                   # no result card names the version before: the last result card before this one's
            mine = _result_for(F, M)
            rs = [F["idx"][e["id"]] for e in F["all_cards"] if e["card"].get("kind") == "result" and (mine < 0 or F["idx"][e["id"]] < mine)]
            cut = max(rs, default=-1)
    after = any(st[m] in OPEN_MS for m in keys[keys.index(M) + 1:]) if M in keys else False
    after = after or st.get("final") in OPEN_MS + DONE_MS
    return {"m": M, "prev": prev, "cut": cut, "n": len(done) + (1 if R else 0) or 1, "after": after, "status": st.get(M) if M else None}


def _scope_round(F):
    """A later version: cards, plan confirmation, start, build and delivery are this milestone's only."""
    R = F["round"]; M, cut = R["m"], R["cut"]; s = F["s"]; root = F["root"]
    F["cards"] = [e for e in F["all_cards"] if F["idx"][e["id"]] > cut]
    pr = F["plan_review"]; v = _milestones(F).get(M) or {}
    known = set(_milestones(F))                    # a go card for another known version (an old one resent) is not this version's
    bg = F["build_gos"] = _live([e for e in F["cards"] if build_go(F, e) and (e["card"].get("milestone") == M or e["card"].get("milestone") not in known)])
    B = root / "5_build" / str(M)
    from . import decisions
    s.update(plan=True, plan_ok=decisions.confirmed(root, f"plan:{M}", (pr.get("milestone") == M and pr.get("state") == "confirmed")
                                                    or bool(isinstance(v, dict) and v.get("confirmed"))),
             started=R["status"] in ("building", "built", "accepted") or any(_decision(F, e) == "start" for e in bg),
             go_waiting=any(e["id"] not in F["answers"] for e in bg), live=R["status"] == "building",
             play=(B / "play" / "play.yaml").is_file(), balance=(B / "balance" / "report.yaml").is_file(), accepted=R["status"] == "accepted")


# ---------------------------------------------------------------- her plan approval on a card (the adaptation-3 case)
APPROVE_KEYS = {"ok", "yes", "go", "approve", "approved", "accept", "agree", "as_is", "confirm", "confirmed", "plan_ok", "do"}
APPROVE_WORDS = re.compile(r"按这个做|就按这个|照这个做|照着做|同意|没问题|就这样|确认方案|可以开工")
PLAN_STEPS = ("plan", "design", "confirm_plan")


def plan_card(e) -> bool:
    c = e["card"]
    return (e.get("flow_step") in PLAN_STEPS or str(c.get("key") or "").startswith("plan") or str(c.get("open") or "").startswith("#plan")
            or "方案" in str(c.get("title") or ""))


def approves(card, answer) -> bool:
    """Does this answer approve the plan? options: she picked an item like 「按这个做」 (key ok / yes / …); understanding: 「都对」."""
    a = answer or {}; k = (card or {}).get("kind")
    if k == "options":
        items = {str(i.get("key")): i for i in card.get("items") or [] if isinstance(i, dict)}
        return any(str(p).lower() in APPROVE_KEYS or APPROVE_WORDS.search(str((items.get(str(p)) or {}).get("title") or "")) for p in a.get("picked") or [])
    if k == "understanding": return bool(a.get("ok")) and not a.get("edits")
    return False


def plan_approvals(F) -> list:
    """Plan cards (options / understanding) she answered with an approval (in this round's cards)."""
    return [e for e in F["cards"] if e["card"].get("kind") in ("options", "understanding") and plan_card(e)
            and e["id"] in F["answers"] and approves(e["card"], F["answers"][e["id"]].get("answer"))]


def record_answer(root, ev, answer) -> bool:
    """Called when she answers a card (conversation.Thread.answer): an approval of the plan on an options / understanding card is
    recorded in feedback/plan_review.yaml like 「就按这个做」 on the 方案 page (milestone = the one the 方案 page shows). -> written?"""
    if not (isinstance(ev, dict) and isinstance(ev.get("card"), dict) and plan_card(ev) and approves(ev["card"], answer)): return False
    from datetime import datetime
    root = Path(root); f = root / layout.FEEDBACK / "plan_review.yaml"
    ms = ((_y(root / layout.DESIGN / "world_plan.yaml", {}) or {}).get("world_plan") or {}).get("milestones") or {}
    ms = ms if isinstance(ms, dict) else {}
    pick = next((m for m, v in ms.items() if _dv(v).get("status") == "next"), None) or next((m for m, v in ms.items() if _dv(v).get("status") == "building"), None)
    old = _y(f, {}) or {}
    from . import decisions
    if old.get("state") == "confirmed" and old.get("milestone") == pick:
        if not decisions.confirmed(root, f"plan:{pick}"): decisions.record(root, f"plan:{pick}", "confirmed", via=f"card {ev.get('id')}")
        return False
    rv = {"milestone": pick, "state": "confirmed", "at": datetime.now().isoformat(timespec="seconds"), "items": {}, "persistence": old.get("persistence"),
          "note": "", "via": f"card {ev.get('id')}"}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# 你在“方案”页里的选择（gameanything ui）。这一份来自你在对话卡片上的回答（via）：同意方案 = 就按这个做。\n"
                 + yaml.safe_dump(rv, allow_unicode=True, sort_keys=False), encoding="utf-8")
    decisions.record(root, f"plan:{pick}", "confirmed", via=f"card {ev.get('id')}")      # her answer on the card, as the server saw it
    return True


def _match(F, step, kinds, keys=(), opens=(), pred=None) -> list:
    """Card events of `kinds` that belong to `step`: sent while the step was the one to work on (`flow_step`, stamped by gameanything chat card),
    or with a key / open route the step doc prescribes, or (older cards) that `pred` recognises."""
    out = []
    for e in F["cards"]:
        c = e["card"]
        if c.get("kind") not in kinds: continue
        k, o = str(c.get("key") or ""), str(c.get("open") or "")
        if e.get("flow_step") == step or (keys and k.startswith(tuple(keys))) or (opens and o.startswith(tuple(opens))) or (pred and pred(c)):
            out.append(e)
    return out


def _answered(F, evs) -> bool: return any(e["id"] in F["answers"] for e in evs)


def _C(cid, ok, why, who="agent", level="fail", recheck=False) -> dict:
    return {"id": cid, "ok": bool(ok), "why": "" if ok else why, "who": who, "level": level, "recheck": recheck}


def _imgs(c) -> list:
    out = [c.get("image")] + [i.get("image") or i.get("url") for i in c.get("items") or [] if isinstance(i, dict)]
    return [str(u) for u in out if u]


def _image_card(F, step, prefix) -> list:
    return [e for e in F["cards"] if e["card"].get("kind") in CARD_IMAGE_KINDS and any(u.startswith(prefix) for u in _imgs(e["card"]))]


# ---------------------------------------------------------------- adaptation checks (also used by the tests)
def _q(x):
    """A quote: a string, or {text, where, text_zh/text_en/zh/en, grounding}."""
    return x if isinstance(x, dict) else {"text": x} if isinstance(x, str) else {}


def _unreadable(rel, path) -> list:
    """Why a page file reads as nothing: missing or empty, or (it is there) its YAML error / shape (QA2 2026-10-30: a syntax error was
    reported as 「不存在或是空的」)."""
    if path and Path(path).is_file():
        from . import filecheck
        d, err = filecheck._load(Path(path))
        if err: return [f"{rel} 读不出来：{err}"]
        if d is not None and not isinstance(d, dict): return [f"{rel} 整个文件应该是对象（key: value），现在是{filecheck._kind(d)}"]
    return [f"{rel} 不存在或是空的"]


def _not_list(v, name) -> list:
    from . import filecheck
    return [] if v is None or isinstance(v, list) else [f"{name} 应该是列表（- 开头的一条条），现在是{filecheck._kind(v)}"]


def check_adaptation(A, path=None) -> list:
    """Problems of 3_remember/adaptation.yaml (scenes and places); [] = valid. path: the file (to name a syntax error)."""
    P = []
    if not isinstance(A, dict) or not A: return _unreadable("3_remember/adaptation.yaml", path)
    w = A.get("work") or {}
    if not (isinstance(w.get("units"), list) and w["units"]): P.append("work.units 要列出这次抽取的章节 / 集")
    sc = A.get("scenes"); bad = _not_list(sc, "scenes")
    if bad: P += bad; sc = []
    elif not sc: P.append("scenes 是空的")
    ids = set()
    for i, s in enumerate(sc or [], 1):
        if not isinstance(s, dict): P.append(f"scenes 第 {i} 项不是对象"); continue
        for f in ("id", "title", "place"):
            if not s.get(f): P.append(f"场景 {s.get('id') or i} 缺少 {f}")
        if s.get("id") in ids: P.append(f"场景 id 重复：{s.get('id')}")
        ids.add(s.get("id"))
        for q in s.get("quotes") or []:
            q = _q(q)
            if not q.get("text") or not q.get("where"): P.append(f"场景 {s.get('id')} 的引文要有 text 和 where（出处）"); break
    pl = A.get("places"); bad = _not_list(pl, "places")
    if bad: P += bad; pl = []
    elif not pl and not A.get("buildables"): P.append("places 是空的")
    for i, p in enumerate(pl or [], 1):
        if not isinstance(p, dict) or not p.get("id") or not p.get("name"): P.append(f"地点第 {i} 项要有 id 和 name")
    return P


def check_registry(A) -> list:
    """The place registry across units: ids / names / aliases unique, every scene's place (and buildable's) is in it."""
    P, seen = [], {}
    for p in (A or {}).get("places") or []:
        if not isinstance(p, dict): continue
        for n in [p.get("id"), p.get("name"), *(p.get("aliases") or [])]:
            if not n: continue
            if n in seen and seen[n] != p.get("id"): P.append(f"「{n}」同时属于地点 {seen[n]} 和 {p.get('id')}：合并成一处，另一个名字写进 aliases")
            seen[str(n)] = p.get("id")
    if not seen: return P
    for s in (A or {}).get("scenes") or []:
        if isinstance(s, dict) and s.get("place") and str(s["place"]) not in seen:
            P.append(f"场景 {s.get('id')} 的地点「{s['place']}」不在地点表里（加进 places，或写成已有地点的 id / 别名）")
    for b in (A or {}).get("buildables") or []:
        if isinstance(b, dict) and b.get("place") and str(b["place"]) not in seen: P.append(f"可建造元素「{b.get('name')}」的地点「{b['place']}」不在地点表里")
    return P[:12]


def check_characters(A) -> list:
    P = []
    cs = (A or {}).get("characters")
    if not (isinstance(cs, list) and cs): return ["characters 是空的：抽出主要人物（name、role、looks、lines，带出处）"]
    for i, c in enumerate(cs, 1):
        if isinstance(c, str): P.append(f"人物「{c}」只有名字：要有 role 和 looks / lines"); continue
        n = c.get("name") or i
        if not c.get("role"): P.append(f"人物「{n}」缺少 role（在作品里是谁）")
        if not (c.get("looks") or c.get("lines")): P.append(f"人物「{n}」没有 looks 也没有 lines")
        for q in list(c.get("looks") or []) + list(c.get("lines") or []):
            q = _q(q)
            if q and not (q.get("where") or q.get("grounding")): P.append(f"人物「{n}」的外貌 / 台词要有出处 where（或 grounding: invented）"); break
    return P[:12]


EN_FIELDS = {"scenes": ("title", "what"), "places": ("name",), "characters": ("name", "role")}
CJK = re.compile(r"[一-鿿]")


def missing_translations(A, groups=("scenes", "places")) -> list:
    """Fields the pages show whose other-language sibling is missing: Chinese without *_en, or English without *_zh."""
    out = []
    for g in groups:
        for x in (A or {}).get(g) or []:
            if not isinstance(x, dict): continue
            for f in EN_FIELDS[g]:
                v = x.get(f)
                if isinstance(v, str) and v.strip():
                    other = f"{f}_en" if CJK.search(v) else f"{f}_zh"
                    if not str(x.get(other) or "").strip(): out.append(f"{g}.{x.get('id') or x.get('name')}.{other}")
    return out


def _corpus(root: Path) -> str:
    txt = []
    for it in (_y(layout.pack(root), {}) or {}).get("items") or []:
        d = it.get("derived") or {}
        for pg in d.get("pages") or []:
            try: txt.append((root / pg["text"]).read_text(encoding="utf-8", errors="replace"))
            except (OSError, KeyError, TypeError): pass
        if d.get("transcript"):
            txt += [str(s.get("text") or "") for s in (_y(root / d["transcript"], {}) or {}).get("segments") or []]
    return _norm("\n".join(txt))


def _norm(s: str) -> str: return re.sub(r"[\s“”‘’\"'「」『』]+", "", s or "")


def bad_quotes(root: Path, A) -> list:
    """Quotes that are not word for word in the work (whitespace and quote marks ignored); [] when there is no text to check against."""
    corpus = _corpus(Path(root))
    if not corpus: return []
    qs = []
    for s in (A or {}).get("scenes") or []: qs += [_q(q) for q in (s.get("quotes") or []) if isinstance(s, dict)]
    for p in (A or {}).get("places") or []:
        if isinstance(p, dict): qs += [_q(q) for q in p.get("described") or []] + [{"text": b.get("quote"), "where": "build"} for b in p.get("build") or [] if isinstance(b, dict) and b.get("quote")]
    for c in (A or {}).get("characters") or []:
        if isinstance(c, dict): qs += [_q(q) for q in list(c.get("looks") or []) + list(c.get("lines") or []) if _q(q).get("grounding") != "invented"]
    return [q["text"] for q in qs if q.get("text") and _norm(q["text"]) not in corpus][:8]


def _units_card_problems(c) -> list:
    if c.get("kind") == "options":
        its = c.get("items") or []
        P = [] if len(its) >= 2 else ["至少列出两个可选的章节 / 集"]
        if not any(i.get("recommended") for i in its if isinstance(i, dict)): P.append("没有默认：给建议的几章写 recommended: true")
        extra = sorted({str(k) for i in its if isinstance(i, dict) for k in set(i) - OPTION_KEYS})
        if extra:             # e.g. `description` instead of `desc` (an OpenCode / Kimi run, 2026-10-26: four resends on the old message)
            P.append(f"选项里有卡片不认识的字段 {', '.join(extra)}：每一项只用 {' / '.join(sorted(OPTION_KEYS))}（说明写在 desc，英文写在 en: {{title, desc}}；如果是 desc 里的「: 」把 yaml 拆开了，desc 用引号括起来）")
        elif any(not isinstance(i.get("desc", ""), str) for i in its if isinstance(i, dict)):
            P.append("有一项的 desc 被 yaml 拆坏了（desc 里有「: 」或「，」后跟冒号）：desc 用引号括起来")
        return P
    its = c.get("items") or []
    return [] if its and all(i.get("hint") for i in its if isinstance(i, dict)) else ["每个问题要带 hint（默认答案）"]


def _requests_for(F, kind) -> list:
    from . import agentd, isolation
    try: pid = projects.find(F["root"])["id"]
    except (KeyError, OSError, ValueError): pid = F["root"].name
    d = agentd.requests_dir(); out = []; pat = f"{pid}-*.json"
    if isolation.client_mode(): d, pat = Path(F["root"]) / "conversation" / ".requests", "*.json"    # an agent account: its own copies
    try: there = d.is_dir()
    except OSError: there = False
    if there:
        for f in d.rglob(pat):
            try: r = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError): continue
            if isinstance(r, dict) and r.get("kind") == kind: out.append(r)
    return out


# ---------------------------------------------------------------- the adaptation steps
OPTION_KEYS = {"key", "title", "desc", "recommended", "cost", "image", "en"}
UNIT_WORDS = ("章", "回", "集", "chapter", "Chapter", "episode", "Episode")


def _has_video(F): return bool(F.get("videos"))


def c_gather(F): return [_C("material", F["s"]["items"] or F["s"]["inbox"], "她还没有放进作品（作品页）", "user")]


def c_ingest(F):
    s = F["s"]
    return [_C("ingested", s["items"] and not s["ingest_requested"],
               "收件箱里有文件还没整理：gameanything ingest \"$P/0_inbox\" --project \"$P\"，然后把 feedback/ingest_request.yaml 的 state 改成 done")]


def c_copyright(F):
    cfg = F["cfg"]
    return [_C("source", str(cfg.get("source") or "").strip(), "config/project.yaml 缺 source（底本是哪一版，译本也算）", recheck=True),
            _C("source_license", str(cfg.get("source_license") or "").strip(),
               "config/project.yaml 缺 source_license（public domain / copyrighted…）；先在对话里说清版权，不清楚底本就发 questions 卡问她", recheck=True)]


def c_choose_units(F):
    cs = _match(F, "choose_units", ("options", "questions"), keys=("units",), pred=lambda c: any(w in str(c.get("title") or "") for w in UNIT_WORDS))
    last = cs[-1]["card"] if cs else {}
    return [_C("units_card", cs, "发一张 options（或 questions）卡：列出可选的章节 / 集，标出默认（recommended: true），key: units"),
            _C("units_card_valid", not cs or not _units_card_problems(last), "选章节卡的问题：" + "；".join(_units_card_problems(last)) if cs else ""),
            _C("units_answered", _answered(F, cs), "等她在选章节卡上选（不要没等她就开始抽取）", "user")]


def c_extract(F):
    A = F["A"]; P = check_adaptation(A, F["root"] / layout.REMEMBER / "adaptation.yaml"); out = [_C("adaptation_yaml", not P, "；".join(P[:6]), recheck=True)]
    if not P:
        bq = bad_quotes(F["root"], A)
        out.append(_C("quotes_verbatim", not bq, "这些引文在原文里找不到（逐字，不许改写；找不到就删掉）：" + " | ".join(x[:40] for x in bq)))
        en = missing_translations(A, ("scenes", "places"))
        out.append(_C("english", not en, f"{len(en)} 处没有英文（*_en），英文界面会显示中文：例如 {', '.join(en[:3])}", level="warn"))
    if _has_video(F):
        vids = {v["id"] for v in F["videos"]}; have = {k for k, v in (F["keyframes"].get("videos") or {}).items() if v.get("shots")}
        kd = F["root"] / "2_perceive" / "keyframes"           # keyframes made by hand (one folder per video) count too
        dirs = [d for d in kd.iterdir() if d.is_dir() and any(d.glob("*.jpg"))] if kd.is_dir() else []
        out.append(_C("keyframes", vids <= have or len(dirs) >= len(vids), "作品里有视频，但还没有关键画面：gameanything visuals --project \"$P\"", recheck=True))
        fr = [s for s in A.get("scenes") or [] if isinstance(s, dict) and s.get("frames")]
        ok = fr and all((F["root"] / str((_q(f) or {}).get("file") or "")).is_file() for s in fr for f in s["frames"])
        out.append(_C("scene_frames", ok, "把关键画面连到场景：场景加 frames: [{file: 2_perceive/keyframes/…/kNNN.jpg, t: 秒}]（按 index.yaml 里每个镜头的 said 对台词）", recheck=True))
        out.append(_C("frames_card", _image_card(F, "extract", "/media/2_perceive/keyframes"),
                      "发一张能显示图片的卡（questions 每题带 image，或 candidates media: image）给她看场景对应的画面"))
    out.append(_C("review_card", _match(F, "extract", ("task",), keys=("scenes",), opens=("#home", "#scenes")),
                  "发一张 task 卡请她去「场景」页逐条看（open: \"#home\"，key: scenes-review）"))
    return out


def c_registry(F):
    P = check_registry(F["A"]) if F["A"] else ["还没有 adaptation.yaml"]
    return [_C("registry", not P, "；".join(P[:5]), recheck=True)]


def c_confirm_scenes(F):
    from . import decisions
    return [_C("scenes_confirmed", decisions.confirmed(F["root"], "scenes", F["review"].get("state") == "confirmed"), "等她在「场景」页点「确认场景和地点」；她写了「要改」的条目先照改", "user")]


def c_characters(F):
    A = F["A"]; P = check_characters(A); out = [_C("characters", not P, "；".join(P[:6]), recheck=True)]
    if not P:
        en = missing_translations(A, ("characters",))
        out.append(_C("english", not en, f"{len(en)} 处人物信息没有英文（name_en / role_en）", level="warn"))
    if _has_video(F):
        cl = F["people"].get("clusters")
        pd = F["root"] / "2_perceive" / "people"
        if cl is None and pd.is_dir() and any(pd.rglob("*.jpg")): cl = [str(f) for f in pd.rglob("*.jpg")]   # crops made by hand
        out.append(_C("people", cl is not None, "作品里有视频，但还没找人物画面：gameanything visuals --project \"$P\"", recheck=True))
        has = [c for c in A.get("characters") or [] if isinstance(c, dict) and (c.get("image") or c.get("frames"))]
        out.append(_C("character_images", not cl or has, "把人物画面连到角色：角色加 image: 2_perceive/people/cNN/001.jpg（和 frames），按台词和场景对应", recheck=True))
        if cl: out.append(_C("people_card", _image_card(F, "characters", "/media/2_perceive/people"),
                             "发一张能显示图片的卡（questions 每题带 image）问她这些画面里是谁"))
    out.append(_C("characters_card", _match(F, "characters", ("task",), keys=("characters",), opens=("#people", "#characters")),
                  "发一张 task 卡请她去「角色」页逐条看（open: \"#people\"，key: characters-review）"))
    return out


def chars_confirmed(review: dict) -> bool:
    """「确认人物」: state_characters confirmed; a project confirmed under the old combined rule (no state_characters yet) counts too."""
    if review.get("state_characters") == "confirmed": return True
    return review.get("state") == "confirmed" and "state_characters" not in review


def her_chars_confirmed(root, review: dict) -> bool:
    """chars_confirmed, and she did it on the page (decisions.py): 「确认人物」, or the old combined 「确认场景和地点」."""
    from . import decisions
    if not chars_confirmed(review): return False
    return decisions.confirmed(root, "characters") or ("state_characters" not in review and decisions.confirmed(root, "scenes"))


def c_confirm_characters(F):
    return [_C("characters_confirmed", her_chars_confirmed(F["root"], F["review"]), "等她在「角色」页点「确认人物」", "user")]


def c_questions(F):
    cs = _match(F, "questions", ("questions",), keys=("plan-questions", "questions"))
    bad = [i for c in cs[-1:] for i in c["card"].get("items") or [] if isinstance(i, dict) and not i.get("hint")]
    return [_C("questions_card", cs, "发一张 questions 卡：按影响排序（比例、方位、游戏里没有的东西怎么对应、季节、用哪个名字），每题带原文证据和默认（hint），key: plan-questions"),
            _C("questions_defaults", not cs or not bad, "每个问题都要有 hint（默认答案）"),
            _C("questions_answered", _answered(F, cs), "等她回答（可以只答一部分，没答的按默认）", "user")]


def _plan_items(F) -> bool:
    """The 方案 page lists the items of the version it shows (status next, else building): 5_build/<m>/plan.yaml `items`, or the
    builder's package/BRIEF.md. Without them the page says the items are not written yet, so she has nothing to confirm."""
    ms = (F.get("plan") or {}).get("milestones") or {}
    ms = ms if isinstance(ms, dict) else {}
    m = next((k for k, v in ms.items() if _dv(v).get("status") == "next"), None) or next((k for k, v in ms.items() if _dv(v).get("status") == "building"), None)
    if not m: return bool(ms)                        # every version built: nothing waits on the 方案 page
    d = F["root"] / "5_build" / str(m)
    return bool((_y(d / "plan.yaml", {}) or {}).get("items")) or (d / "package" / "BRIEF.md").is_file()


PLAN_ITEMS_WHY = ("写 5_build/<这一版>/plan.yaml：items 逐条列出这一版要做的事（每条 n、title、title_en、desc、desc_en，可选 quote、quote_en）。"
                  "「方案」页只显示这份清单，没写就是空的：写好之前不要请她去看方案")


def c_plan(F):
    wp = F.get("plan") or {}
    cs = _match(F, "plan", ("understanding", "task"), keys=("plan",), opens=("#plan",))
    return [_C("world_plan", wp.get("places") or wp.get("milestones"), "写 4_design/world_plan.yaml：places（原文有的 / 发明的）和 milestones（每一版做哪几处）"),
            _C("plan_items", _plan_items(F), PLAN_ITEMS_WHY, recheck=True),
            _C("plan_card", cs, "发一张 understanding 卡复述方案要点，或 task 卡请她去「方案」页（open: \"#plan\"）"),
            _C("plan_confirmed", F["s"]["plan_ok"], "等她在「方案」页点「就按这个做」", "user")]


def c_preview(F):
    perm = _match(F, "preview", ("permission",), keys=("preview",))
    no = any((F["answers"].get(e["id"]) or {}).get("answer", {}).get("decision") == "no" for e in perm)
    cand = _match(F, "preview", ("candidates",), keys=("preview",))
    if no: return [_C("preview_declined", True, "")]
    return [_C("permission_card", perm, "发 permission 卡（发什么、发给谁）和预览的 go 卡；她同意后 gameanything gen request 排队，不要自己跑 gen_*.py"),
            _C("permission_yes", any((F["answers"].get(e["id"]) or {}).get("answer", {}).get("decision") == "yes" for e in perm), "等她在许可卡上点同意", "user"),
            _C("candidates_card", cand, "图画好后（后台会发通知给你）发 candidates 卡（media: image）让她挑"),
            _C("picked", _answered(F, cand), "等她在候选卡上挑", "user")]


SETUP_READ = "；读完后跑 gameanything setup guide --project \"$P\" --read <指南最后打印的 token>（只跑命令不算读过）"
SETUP_WHY = {"never": "开工和开游戏之前：跑 gameanything setup guide --project \"$P\"，它会把那份 setting 指南（references/setups/<系统>-<方式>.md）整份打印出来，从头读完，"
                      "照里面的 checklist 做；开工卡和开游戏前要告诉她的事照指南的「Tell the user before launching」说" + SETUP_READ,
             "mode": "构建方式（build_mode）换过了：重跑 gameanything setup guide --project \"$P\"，读新的那份 setting 指南" + SETUP_READ,
             "machine": "项目换了电脑（系统和记录的不一样）：重跑 gameanything setup guide --project \"$P\"，读这台电脑的 setting 指南" + SETUP_READ}


def c_setup(F):
    """The setting guide was read for this project's setting (config/project.yaml setup.guide_read_at, written by `gameanything setup guide`),
    before the first build or game launch. Not reopened: a round whose build already started, or a project whose versions are all built."""
    from . import setupguide
    s = F["s"]; ms = _milestones(F)
    done = s["started"] or (bool(ms) and not any(str(_dv(v).get("status")) in ("next", "building") for v in ms.values() if isinstance(v, dict)))
    why = "" if done else setupguide.stale(F["cfg"])
    return [_C("setup_guide", not why, SETUP_WHY.get(why, SETUP_WHY["never"]))]


def c_go(F):
    """The go card of the build (not a drawing go card): with an estimate (of the project's build model: builds run on it only, the card
    names it); she pressed 开工. Once she started, the card is history. An older card with runners and their estimates still counts."""
    s = F["s"]; gs = F.get("build_gos") or []
    last = gs[-1]["card"] if gs else {}
    ok = s["started"] or bool(gs and (last.get("estimate") or any(isinstance(r, dict) and r.get("estimate") for r in last.get("runners") or [])))
    why = ("上一张开工卡缺 estimate：重发一张（同一个 key）" if gs else "发 go 卡") + "：做什么（milestone、items）、多久、多少钱（gameanything estimate --project \"$P\" --size … --yaml，按项目的构建模型估）"
    return [*c_setup(F), _C("go_card", ok, why), _C("go_started", s["started"], "等她在开工卡上点开工", "user")]


def _built(F) -> bool:
    s = F["s"]; return bool(s["live"] or s["play"] or s["accepted"] or s.get("balance") or (F["round"]["prev"] and F["round"]["status"] in ("building", "built", "accepted")))


def _build_requests(F) -> list:
    rs = _requests_for(F, "build_start"); M = F["round"]["m"]
    if F["round"]["prev"] and M: rs = [r for r in rs if (r.get("details") or {}).get("milestone") in (M, None)]
    return rs


def c_build(F):
    s = F["s"]
    return [_C("build_request", _built(F) or _build_requests(F), "她点了开工：gameanything agentd request --project \"$P\" --kind build_start --text … --details "
               "'{\"go_key\": …, \"milestone\": …, \"build_mode\": …, \"runner\": …, \"items\": […], \"status\": \"5_build/STATUS.yaml\"}'"),
            _C("delivered", s["play"] or (F["kind"] == "gameplay" and s.get("balance")), "构建由后台跑；做好后会有通知", "coordinator"),
            _C("result_card", any(e["card"].get("kind") == "result" for e in F["cards"]),
               "这一版做好了（后台的「做好了」通知，或 5_build/<m>/play/ 已有录像）：gameanything build check --project \"$P\" --m <m> 通过，再用 gameanything status card 生成 result 卡发出（再发 task 卡请她去试玩页）")]


def _after_result(F) -> list:
    """Options cards after this round's last result card: what she wants next."""
    rs = [F["idx"][e["id"]] for e in F["cards"] if e["card"].get("kind") == "result"]
    if not rs: return []
    first = _result_for(F, F["round"]["m"]) if F["round"]["m"] else -1        # the version's first result card (it may be re-sent later)
    at = first if first > F["round"]["cut"] else max(rs)
    return [e for e in F["cards"] if e["card"].get("kind") == "options" and F["idx"][e["id"]] > at and e["card"].get("key") != "native-launch"]


def c_feedback(F):
    s = F["s"]
    if s["accepted"] or s["final"]: return [_C("accepted", True, "", "user")]
    nc = _after_result(F)              # she may also just say what she wants: then you write the next milestone and the round moves on
    if F["round"].get("status") not in DONE_MS: nc = []    # a version not built yet has no feedback: the last version's 下一步 card opened it
    return [_C("next_card", nc, "成果卡和试玩 task 卡之后，发一张 options 卡问她下一版做什么（key: next-round；几种做法写清代价、标出建议；memory / feature 加一项「带回家」）"),
            _C("next_answered", _answered(F, nc), "等她看录像、在「下一步」卡上选（她直接说了想做什么：照她说的写下一版的里程碑）", "user")]


def c_next_round(F):
    return [_C("next_milestone", F["round"]["after"],
               "照她选的写下一版：4_design/world_plan.yaml 加一个里程碑（status: next，name、what、what_en）；然后按下一版的步骤走（先写方案给她确认）。"
               "她选「带回家」：把 final 写成 status: next")]


def c_keep(F):
    return [_C("final", F["s"]["final"], "带回家（收尾那一期 final）：先备份她的存档，再装进她自己的游戏，说清存档里多了什么、怎么卸载；她试过后定稿", "user")]


def _act(label, route): return {"label": label, "route": route, "wait": False, "hint": ""}
def _wait(hint): return {"label": "去对话里看看", "route": "chat", "wait": True, "hint": hint}


def _pending_card(F, crit_id, crit) -> bool:
    c = {x["id"]: x for x in crit}
    return c.get(crit_id, {}).get("ok") is False


def _st(id_, label, ui, actor, crit, ui_next, needs, tell, anchor=True) -> dict:
    """anchor=False: a check-only step (registry) that can pass with nothing done; it never marks the steps before it done."""
    return {"id": id_, "label": label, "ui": ui, "actor": actor, "crit": crit, "ui_next": ui_next, "needs": needs, "tell": tell, "anchor": anchor}


def tail(ui) -> list:
    """build → feedback → next_round: the end of every version, in the stepper group `ui` (试玩, or 平衡/试玩 for gameplay)."""
    def see(F):
        s = F["s"]
        if ui == "balance" and s.get("balance"): return _act("看平衡和试玩", "balance")
        return _act("看试玩录像", "play") if s["play"] else None
    return [
        _st("build", "构建", ui, "coordinator", c_build, lambda F, c: see(F) or _wait("正在后台构建，做好后在这里看录像"),
            ["她点了开工：发 build_start 请求", "构建由后台跑；做好后 gameanything build check 通过再发 result 卡 + task 卡"],
            lambda F: "这一版做好了，成果卡马上发到对话里。" if F["s"]["play"] else "正在后台构建，做好后对话里会有成果卡。"),
        _st("feedback", "试玩和意见", ui, "user", c_feedback,
            lambda F, c: _act("在对话里选下一版做什么", "chat") if c[0]["ok"] and len(c) > 1 and not c[1]["ok"] else see(F) or _act("看试玩录像", "play"),
            ["她看录像、提意见；意见进 5_build/STATUS.yaml", "发「下一步」options 卡（key: next-round）"], "录像做好了，去「试玩」页看，有意见直接说；下一版做什么在对话里的卡片上选。"),
        _st("next_round", "下一版", ui, "agent", c_next_round, lambda F, c: _wait("agent 正在准备下一版"),
            ["照她选的在 world_plan.yaml 加下一版的里程碑（status: next）", "然后从下一版的方案开始"], "好，我按你选的准备下一版，先写方案给你看。"),
    ]


ADAPTATION = [
    _st("gather", "放进作品", "gather", "user", c_gather, lambda F, c: _act("放进作品", "gather"),
        ["请她在「作品」页放进要改编的作品（文字、字幕、截图、视频）"], "请在「作品」页放进要改编的作品，放好后点「整理新文件」。"),
    _st("ingest", "整理作品", "scenes", "agent", c_ingest,
        lambda F, c: _wait("agent 正在整理你的素材") if F["s"]["ingest_requested"] else _act("把素材交给 agent 整理", "gather"),
        ["gameanything ingest 整理收件箱（本机处理，不发给模型）"], "作品整理好了，下一步先说清版权。"),
    _st("copyright", "版权和底本", "scenes", "agent", c_copyright, lambda F, c: _wait("agent 会先和你确认底本和版权"),
        ["在对话里说清版权（公有领域才逐字引用）", "把 source、source_license 写进 config/project.yaml"], "先确认底本和版权，再选章节。"),
    _st("choose_units", "选章节", "scenes", "agent", c_choose_units,
        lambda F, c: _act("在对话里选先改编哪几章", "chat") if c[0]["ok"] and not c[2]["ok"] else _wait("agent 会在对话里问你先改编哪几章"),
        ["发选章节卡（options / questions，带默认）", "等她选"], "请在对话里的卡片上选先改编哪几章（默认已勾好）。"),
    _st("extract", "抽取场景", "scenes", "agent", c_extract, lambda F, c: _wait("agent 正在从作品里抽取场景和地点"),
        ["写 3_remember/adaptation.yaml（场景、地点、可建造元素，逐字引文，中英文都写）", "有视频：gameanything visuals，场景连上关键画面，发带图的卡",
         "发 task 卡请她看「场景」页"], "场景和地点抽好了，请到「场景」页逐条选保留 / 先不做 / 要改。"),
    _st("registry", "地点登记表", "scenes", "agent", c_registry, lambda F, c: _wait("agent 正在从作品里抽取场景和地点"),
        ["地点表：别名、后文正名合并成一处，每个场景的地点都在表里"], "地点表核对好了。", anchor=False),
    _st("confirm_scenes", "确认场景", "scenes", "user", c_confirm_scenes, lambda F, c: _act("确认场景", "home"),
        ["等她确认场景；她写的「要改」先照改"], "请在「场景」页看完后点「确认场景和地点」。"),
    _st("characters", "整理人物", "characters", "agent", c_characters, lambda F, c: _wait("agent 正在整理人物"),
        ["characters：role、looks、lines（带出处），中英文", "有视频：人物连上画面（image / frames），发带图的卡问她是谁", "发 task 卡请她看「角色」页"],
        "人物整理好了，请到「角色」页逐个看，最后点「确认人物」。"),
    _st("confirm_characters", "确认人物", "characters", "user", c_confirm_characters, lambda F, c: _act("确认人物", "people"),
        ["等她确认人物；她写的「要改」先照改"], "请在「角色」页看完后点「确认人物」。"),
    _st("questions", "问关键问题", "plan", "agent", c_questions,
        lambda F, c: _act("在对话里回答几个问题", "chat") if c[0]["ok"] and not c[2]["ok"] else _wait("agent 会先问你几个问题，再写方案"),
        ["发 questions 卡：按影响排序，每题带原文证据和默认"], "请回答卡片上的几个问题（不答的按默认）。"),
    _st("plan", "文字方案", "plan", "agent", c_plan, lambda F, c: _act("确认方案", "plan") if F["s"]["plan"] else _wait("agent 正在写方案"),
        ["写 4_design/world_plan.yaml（发明的单独列出）", "发 understanding / task 卡", "等她确认"], "方案写好了，请到「方案」页看，没问题就点「就按这个做」。"),
    _st("preview", "预览图", "preview", "agent", c_preview,
        lambda F, c: _act("在对话里看预览", "chat") if F["s"]["previews"] or (c[2]["ok"] if len(c) > 2 else False) else _wait("agent 正在出预览图"),
        ["permission 卡 + 预览 go 卡 → gameanything gen request", "画好后发 candidates 卡"], "预览图在对话里，挑你喜欢的。"),
    _st("go", "开工", "go", "agent", c_go, lambda F, c: _act("在对话里点开工", "chat") if F["s"]["go_waiting"] else _wait("agent 会在对话里给你一张开工卡"),
        ["gameanything setup guide --project \"$P\" + 读它给的 setting 指南", "发 go 卡（estimate：按构建模型估）", "等她点开工"], "开工卡在对话里，看过花费和时间后点开工。"),
    *tail("play"),
]
ADAPTATION_UI = [("gather", "作品", "gather"), ("scenes", "场景", "home"), ("characters", "人物", "people"), ("plan", "方案", "plan"),
                 ("preview", "预览", "chat"), ("go", "开工", "chat"), ("play", "试玩", "play")]




# ---------------------------------------------------------------- memory / feature / gameplay: shared criteria
PHOTO_WORDS = re.compile(r"照片|看图|看看|图片|photo", re.I)
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif")


def _photos(F) -> int:
    its = (_y(layout.pack(F["root"]), {}) or {}).get("items") or []
    return sum(1 for i in its if isinstance(i, dict) and (i.get("kind") == "photo" or str(i.get("file") or "").lower().endswith(IMG_EXT)) and i.get("included", True))


def c_ingest_any(F):
    """Ingest is the agent's only when files sit in the inbox (feature / gameplay may start from her words alone)."""
    s = F["s"]
    if not s["inbox"] and not s["items"]: return [_C("ingested", True, "")]
    return c_ingest(F)


def c_said_or_material(F):
    s = F["s"]; return [_C("material", s["items"] or s["inbox"] or s["said"], "她还没说要什么（对话里说，或放进素材）", "user")]


def _questions(F, step, key, why):
    cs = _match(F, step, ("questions",), keys=(key, "questions"))
    bad = [i for c in cs[-1:] for i in c["card"].get("items") or [] if isinstance(i, dict) and not i.get("hint")]
    return [_C("questions_card", cs, why), _C("questions_defaults", not cs or not bad, "每个问题都要有 hint（默认答案）", level="warn"),
            _C("questions_answered", _answered(F, cs), "等她回答（可以只答一部分）", "user")]


def _task(F, step, keys, opens): return _match(F, step, ("task",), keys=keys, opens=opens)


def _plan_criteria(F, step, ui_open="#plan"):
    wp = F.get("plan") or {}
    cs = _match(F, step, ("understanding", "options", "task"), keys=("plan",), opens=(ui_open,))
    return [_C("world_plan", wp.get("milestones") or wp.get("places") or F["s"]["plan"],
               "写 4_design/world_plan.yaml：milestones（这一版 m<n>: {status: next, name, what, what_en}），每条写出处（她的话 / 素材 / 发明）", recheck=True),
            _C("plan_items", _plan_items(F), PLAN_ITEMS_WHY, recheck=True),
            _C("plan_card", cs, "发一张 understanding 卡复述方案要点（key: plan），或 task 卡请她去「方案」页（open: \"#plan\"）")]


def c_confirm_plan(F):
    return [_C("plan_confirmed", F["s"]["plan_ok"], "等她在「方案」页点「就按这个做」（或在方案卡上同意）", "user")]


def c_preview_memory(F):
    """Preview pictures after the plan (permission + go → gameanything gen request → candidates), and the looks (形象) she checks on 人物."""
    s = F["s"]
    if s["looks"] and not s["looks_unseen"]: return [_C("looks_seen", True, "")]
    out = c_preview(F)
    if len(out) == 1: return out                                  # she declined the preview pictures
    if s["looks_unseen"]:
        out += [_C("looks_card", _task(F, "preview", ("looks", "people"), ("#people",)), "发 task 卡请她去「人物」看形象（open: \"#people\"）"),
                _C("looks_seen", False, "等她在「人物」页看完每个形象", "user")]
    return out


def _english(F, step) -> list:
    """A warn on any card of this step without English (`en:`)."""
    no = [e for e in F["cards"] if e.get("flow_step") == step and e["card"].get("kind") != "progress" and not e.get("card_en")]
    return [_C("card_english", False, f"{len(no)} 张卡没有英文（卡片 yaml 里写 en: {{title: …}}）：{', '.join(str(e['card'].get('title') or '')[:20] for e in no[:3])}",
               level="warn")] if no else []


# ---------------------------------------------------------------- memory
def c_perceive(F):
    if not _photos(F): return [_C("no_photos", True, "")]
    perm = _match(F, "perceive", ("permission",), keys=("perceive",), pred=lambda c: bool(PHOTO_WORDS.search(str(c.get("title") or ""))))
    if any(_decision(F, e) == "no" for e in perm[-1:]): return [_C("perceive_declined", True, "")]
    cd = layout.cards(F["root"]); seen = cd.is_dir() and any(cd.glob("*.json"))
    return [_C("permission_card", perm or seen, "发 permission 卡（key: perceive）：会发缩小的照片和文字给模型看，不发原图 / 视频，发给谁"),
            _C("permission_yes", seen or any(_decision(F, e) == "yes" for e in perm), "等她在许可卡上点同意", "user"),
            _C("perceived", seen, "她同意后：gameanything perceive --project \"$P\" --emit，逐个写看图卡，再 gameanything perceive --project \"$P\" --collect；记进 privacy_ledger.yaml", recheck=True)]


def c_people(F):
    R = F["root"] / layout.REMEMBER
    if not _photos(F): return [_C("no_photos", True, "")]
    people = (_y(R / "people.yaml", {}) or {}).get("people") or []
    from . import decisions
    people = people if isinstance(people, list) else []
    tagged = decisions.confirmed(F["root"], "people", (R / "tags.yaml").is_file() or any(isinstance(p, dict) and p.get("confirmed_by") == "user" for p in people))
    cs = _task(F, "people", ("people",), ("#people",))
    done = tagged or any(((F["answers"].get(e["id"]) or {}).get("answer") or {}).get("done") for e in cs)
    return [_C("people_card", cs or done, "发 task 卡请她去「人物 → 标记照片里的人」（open: \"#people/tag\"，key: people-tag）：说为什么要做、大概多久"),
            _C("people_tagged", done, "等她标好人、点「做好了」（拿不准的人用 questions 卡问）", "user")]


def c_board(F):
    s = F["s"]
    return [_C("board", s["board"], "整理这一天：3_remember/board.yaml 的 experience_board.moments（时刻、段落、原话，每条有出处）", recheck=True),
            _C("board_questions", _match(F, "board", ("questions",), keys=("board", "questions")) or s["board_ok"],
               "只有她知道的事（谁、什么时候、为什么重要）用 questions 卡问", level="warn"),
            _C("board_card", _task(F, "board", ("board",), ("#board",)), "发 task 卡请她去「这一天」确认时刻和顺序（open: \"#board\"，key: board-review）")]


def c_confirm_day(F): return [_C("day_confirmed", F["s"]["board_ok"], "等她在「这一天」页点确认", "user")]


def _day_next(F, c):
    s = F["s"]
    if not s["items"] and s["inbox"]: return _wait("agent 正在整理你的素材") if s["ingest_requested"] else _act("把素材交给 agent 整理", "gather")
    return _act("确认这一天", "board") if s["board"] else _wait("agent 正在把素材整理成这一天")


def _crit_ok(c, cid) -> bool: return any(x["id"] == cid and x["ok"] for x in c)


def _card_wait(c, label, hint, ok_i=0, user_i=1):
    """A step that sent its card and waits for her: an action in the chat; otherwise the agent is at it."""
    return _act(label, "chat") if c[ok_i]["ok"] and len(c) > user_i and not c[user_i]["ok"] else None


MEMORY = [
    _st("gather", "放进素材", "gather", "user", lambda F: [_C("material", F["s"]["items"] or F["s"]["inbox"], "她还没有放进素材（素材页）", "user")],
        lambda F, c: _act("放进素材", "gather"),
        ["请她在「素材」页放进照片、视频、文字"], "请在「素材」页放进这一天的照片、视频和文字，放好后点「整理新文件」。"),
    _st("ingest", "整理素材", "day", "agent", c_ingest, _day_next, ["gameanything ingest 整理收件箱（本机处理，不发给模型）"], "素材整理好了。", anchor=False),
    _st("perceive", "看图", "day", "agent", c_perceive, lambda F, c: _card_wait(c, "在对话里点同意", "") or _day_next(F, c),
        ["发 permission 卡（看图要发什么）", "她同意后 gameanything perceive --emit / --collect"], "想请模型看看你的照片，写出每张里有什么：许可卡在对话里。", anchor=False),
    _st("people", "标记人物", "day", "agent", c_people, lambda F, c: _act("标记照片里的人", "people") if c[0]["ok"] and not c[-1]["ok"] else _day_next(F, c),
        ["发 task 卡请她去「人物 → 标记照片里的人」", "等她标好"], "请到「人物」页给照片里的人起名字、分组，做好后点「做好了」。", anchor=False),
    _st("board", "整理这一天", "day", "agent", c_board, _day_next,
        ["写 3_remember/board.yaml（时刻、顺序、原话）", "只有她知道的用 questions 卡问", "发 task 卡请她确认「这一天」"], "这一天整理好了，请到「这一天」页看时刻和顺序，确认一下。"),
    _st("confirm_day", "确认这一天", "day", "user", c_confirm_day, lambda F, c: _act("确认这一天", "board"),
        ["等她确认这一天；她改的先照改"], "请在「这一天」页看完后点确认。"),
    _st("design", "写方案", "plan", "agent", lambda F: _plan_criteria(F, "design"),
        lambda F, c: _act("确认方案", "plan") if F["s"]["plan"] else _wait("agent 正在写方案"),
        ["设计上的选择用 options 卡问（扮演谁、地点、留下什么）", "写 4_design/world_plan.yaml", "发 understanding / task 卡"], "方案写好了，请到「方案」页看，没问题就点「就按这个做」。"),
    _st("confirm_plan", "确认方案", "plan", "user", c_confirm_plan, lambda F, c: _act("确认方案", "plan"),
        ["等她确认方案"], "请在「方案」页看完后点「就按这个做」。"),
    _st("preview", "预览图和形象", "preview", "agent", c_preview_memory,
        lambda F, c: _act("看形象预览", "people") if F["s"]["looks_unseen"] else _act("在对话里看预览", "chat") if F["s"]["previews"] or _crit_ok(c, "candidates_card")
        else _wait("agent 正在出预览图"),
        ["permission 卡 + 预览 go 卡 → gameanything gen request", "画好后发 candidates 卡", "形象：task 卡请她去「人物」"], "预览图在对话里，挑你喜欢的。"),
    _st("go", "开工", "go", "agent", c_go, lambda F, c: _act("在对话里点开工", "chat") if F["s"]["go_waiting"] else _wait("agent 会在对话里给你一张开工卡"),
        ["gameanything setup guide --project \"$P\" + 读它给的 setting 指南", "发 go 卡（estimate：按构建模型估；每条写出自她哪句话）", "等她点开工"], "开工卡在对话里，看过花费和时间后点开工。"),
    *tail("play"),
    _st("keep", "带回家", "keep", "user", c_keep, lambda F, c: _act("装进你的游戏", "keep"),
        ["收尾那一期：先备份存档，再装进她的游戏"], "最后一步：先备份你的存档，再装进你自己的游戏。"),
]


# ---------------------------------------------------------------- feature
def check_feature(D, path=None) -> list:
    if not isinstance(D, dict) or not D: return _unreadable("3_remember/feature.yaml", path)
    P = [] if D.get("title") and D.get("goal") else ["要有 title 和 goal（一句话说清做什么）"]
    its = D.get("items")
    if not (isinstance(its, list) and its): return P + ["items 是空的"]
    for i, x in enumerate(its, 1):
        if not isinstance(x, dict): P.append(f"第 {i} 条不是对象"); continue
        miss = [f for f in ("id", "what", "how", "done_when") if not x.get(f)]
        if miss: P.append(f"条目 {x.get('id') or i} 缺少 {', '.join(miss)}")
    return P[:8]


def c_feature_questions(F):
    return _questions(F, "questions", "feature", "发一张 questions 卡问清楚：放在哪、怎么用、素材从哪来、怎样算做好（每题带 hint 默认答案，key: feature-questions）")


def c_spec(F):
    P = check_feature(_y(F["root"] / layout.REMEMBER / "feature.yaml", {}), F["root"] / layout.REMEMBER / "feature.yaml")
    cs = _match(F, "spec", ("understanding", "task"), keys=("spec", "feature"), opens=("#spec",))
    return [_C("feature_yaml", not P, "；".join(P), recheck=True),
            _C("spec_card", cs, "发 understanding 卡复述需求（做什么、怎么用、怎样算做好、存档里多什么），或 task 卡请她去「需求」页（open: \"#spec\"）")]


def c_confirm_spec(F): return [_C("spec_confirmed", F["s"]["spec_ok"], "等她在「需求」页点「确认需求」；她标了「要改 / 不要」的先改", "user")]


def _spec_next(F, c):
    s = F["s"]
    if not s["items"] and s["inbox"]: return _wait("agent 正在整理你的素材") if s["ingest_requested"] else _act("把素材交给 agent 整理", "gather")
    return _act("确认需求", "spec") if s["spec"] else _wait("agent 会先问你几个问题，再写需求单")


FEATURE = [
    _st("gather", "说想加什么", "gather", "user", c_said_or_material, lambda F, c: _act("在对话里说你想加什么", "chat"),
        ["等她在对话里说想加什么（或放进素材）"], "在对话里说说你想在游戏里加什么。"),
    _st("ingest", "整理素材", "spec", "agent", c_ingest_any, _spec_next, ["收件箱有文件：gameanything ingest"], "素材整理好了。", anchor=False),
    _st("questions", "问清楚", "spec", "agent", c_feature_questions, lambda F, c: _card_wait(c, "在对话里回答几个问题", "", 0, 2) or _spec_next(F, c),
        ["发 questions 卡（放在哪、怎么用、素材从哪来），每题带默认"], "请回答卡片上的几个问题（不答的按默认）。"),
    _st("spec", "写需求单", "spec", "agent", c_spec, _spec_next,
        ["写 3_remember/feature.yaml（每条 what / how / done_when / saves）", "发 understanding 卡（链接 #spec）"], "需求单写好了，请到「需求」页逐条看，最后点「确认需求」。"),
    _st("confirm_spec", "确认需求", "spec", "user", c_confirm_spec, lambda F, c: _act("确认需求", "spec"), ["等她确认需求"], "请在「需求」页看完后点「确认需求」。"),
    _st("plan", "方案", "plan", "agent", lambda F: _plan_criteria(F, "plan"),
        lambda F, c: _act("确认方案", "plan") if F["s"]["plan"] else _wait("agent 正在写方案"),
        ["大功能先用 options 卡定做到多大", "world_plan.yaml 写这一版的里程碑", "发方案卡"], "方案写好了，请到「方案」页看，没问题就点「就按这个做」。"),
    _st("confirm_plan", "确认方案", "plan", "user", c_confirm_plan, lambda F, c: _act("确认方案", "plan"), ["等她确认方案"], "请在「方案」页看完后点「就按这个做」。"),
    _st("go", "开工", "go", "agent", c_go, lambda F, c: _act("在对话里点开工", "chat") if F["s"]["go_waiting"] else _wait("agent 会在对话里给你一张开工卡"),
        ["gameanything setup guide --project \"$P\" + 读它给的 setting 指南", "发 go 卡（estimate：按构建模型估）", "等她点开工"], "开工卡在对话里，看过花费和时间后点开工。"),
    *tail("play"),
    _st("keep", "带回家", "keep", "user", c_keep, lambda F, c: _act("装进你的游戏", "keep"), ["装进她自己的游戏试玩"], "装进你自己的游戏试一试。"),
]


# ---------------------------------------------------------------- gameplay
def _G(F): return _y(F["root"] / layout.REMEMBER / "gameplay.yaml", {}) or {}


def check_mapping(G) -> list:
    mp = (G or {}).get("mapping")
    if not (isinstance(mp, list) and mp): return ["mapping 是空的：每条 {id, experience, mechanic, kind}"]
    P = [f"映射 {m.get('id') or i} 缺少 experience / mechanic" for i, m in enumerate(mp, 1) if isinstance(m, dict) and not (m.get("experience") and m.get("mechanic"))]
    if not ((G.get("core") or {}).get("loop")): P.append("core.loop（核心循环）还没写")
    return P[:8]


def check_content(G) -> list:
    ct = (G or {}).get("content") or {}
    cards = ct.get("cards") if isinstance(ct, dict) else None
    if not (isinstance(cards, list) and cards): return ["content.cards 是空的"]
    return [f"卡 {c.get('id') or i} 缺少 name / text" for i, c in enumerate(cards, 1) if isinstance(c, dict) and not (c.get("name") and c.get("text"))][:8]


def c_gameplay_questions(F):
    return _questions(F, "questions", "gameplay", "先用一两句复述这段经历的核心张力，再发 questions 卡问只有她知道的（每天做什么、最难熬 / 最有成就感的、圈内梗、不要放进去的），每题带 hint，key: gameplay-questions")


def c_mapping(F):
    G = _G(F); P = check_mapping(G)
    arch = (G.get("core") or {}).get("archetypes") or []
    return [_C("mapping", not P, "；".join(P), recheck=True),
            _C("archetypes", len(arch) >= 3, "至少 3 个能各自打通的流派（core.archetypes：打法 + 关键卡）", level="warn"),
            _C("mapping_card", _task(F, "mapping", ("mechanics", "mapping"), ("#mechanics",)), "发 task 卡请她去「机制映射」页逐条选（open: \"#mechanics\"）")]


def c_confirm_mapping(F): return [_C("mapping_confirmed", F["s"]["mapping_ok"], "等她在「机制映射」页点「确认机制映射」", "user")]


def c_scope(F):
    cs = _match(F, "scope", ("understanding",), keys=("scope",))
    return [_C("scope_card", cs or F["s"]["content_ok"], "发 understanding 卡复述第一版范围（角色、卡数、遗物、事件、敌人、幕、Boss），key: scope"),
            _C("scope_answered", _answered(F, cs) or F["s"]["content_ok"], "等她确认范围", "user"),
            _C("scope_yaml", (_G(F).get("scope")) or F["s"]["content_ok"], "她确认后把范围写进 gameplay.yaml 的 scope", recheck=True)]


def c_content(F):
    P = check_content(_G(F))
    return [_C("content", not P, "；".join(P), recheck=True),
            _C("content_card", _task(F, "content", ("content",), ("#content",)), "发 task 卡请她去「内容」页逐张看（open: \"#content\"）")]


def c_confirm_content(F): return [_C("content_confirmed", F["s"]["content_ok"], "等她在「内容」页点「确认内容」", "user")]


def c_go_gameplay(F):
    ok = F["s"]["started"] or bool(_milestones(F))
    return [_C("milestone", ok, "4_design/world_plan.yaml 写这一版：world_plan: {title, game, milestones: {m1: {name: 第一版, status: next, what}}}"),
            _C("brief", F["s"]["started"] or (F["root"] / layout.DESIGN / "BRIEF.md").is_file(), "写 4_design/BRIEF.md（映射、范围、内容表、题材规则、平衡要求、她的原话）", level="warn"),
            *c_go(F)]


def _mech_next(F, c):
    s = F["s"]
    if not s["items"] and s["inbox"]: return _wait("agent 正在整理你的素材") if s["ingest_requested"] else _act("把素材交给 agent 整理", "gather")
    return _act("确认机制映射", "mechanics") if s["mapping"] else _wait("agent 正在画出机制映射")


def _content_next(F, c): return _act("确认内容", "content") if F["s"]["content"] else _wait("agent 正在列卡牌、遗物和敌人")


GAMEPLAY = [
    _st("gather", "说说经历", "gather", "user", c_said_or_material, lambda F, c: _act("说说你的经历", "gather"),
        ["请她在「经历」页放进文字 / 设计笔记，或在对话里讲"], "在「经历」页放进你的文字或设计笔记，或者直接在对话里讲讲。"),
    _st("ingest", "整理经历", "mechanics", "agent", c_ingest_any, _mech_next, ["收件箱有文件：gameanything ingest"], "材料整理好了。", anchor=False),
    _st("questions", "问关键问题", "mechanics", "agent", c_gameplay_questions, lambda F, c: _card_wait(c, "在对话里回答几个问题", "", 0, 2) or _mech_next(F, c),
        ["复述核心张力", "发 questions 卡，每题带默认"], "请回答卡片上的几个问题（可以只答一部分）。"),
    _st("mapping", "机制映射", "mechanics", "agent", c_mapping, _mech_next,
        ["写 gameplay.yaml 的 mapping + core（主题和机制同构，3–4 个流派）", "发 task 卡请她去「机制映射」页"], "机制映射写好了，请到「机制映射」页逐条选，最后点「确认机制映射」。"),
    _st("confirm_mapping", "确认机制映射", "mechanics", "user", c_confirm_mapping, lambda F, c: _act("确认机制映射", "mechanics"),
        ["等她确认映射"], "请在「机制映射」页看完后点「确认机制映射」。"),
    _st("scope", "第一版范围", "content", "agent", c_scope, lambda F, c: _card_wait(c, "在对话里确认第一版范围", "") or _content_next(F, c),
        ["发 understanding 卡复述第一版范围", "确认后写进 scope"], "第一版的范围在对话里的卡片上，不对直接改。"),
    _st("content", "内容表", "content", "agent", c_content, _content_next,
        ["写 content（卡、遗物、敌人、事件、Boss）", "发 task 卡请她去「内容」页"], "内容表写好了，请到「内容」页逐张看，最后点「确认内容」。"),
    _st("confirm_content", "确认内容", "content", "user", c_confirm_content, lambda F, c: _act("确认内容", "content"),
        ["等她确认内容"], "请在「内容」页看完后点「确认内容」。"),
    _st("go", "开工", "go", "agent", c_go_gameplay, lambda F, c: _act("在对话里点开工", "chat") if F["s"]["go_waiting"] else _wait("agent 会在对话里给你一张开工卡"),
        ["卡图要画：permission + 画图 go 卡 → gameanything gen request", "world_plan 里程碑 + BRIEF", "gameanything setup guide + 读 setting 指南", "发 go 卡（estimate：按构建模型估）"], "开工卡在对话里，看过花费和时间后点开工。"),
    *tail("balance"),
]
STEPS = {"adaptation": ADAPTATION, "memory": MEMORY, "feature": FEATURE, "gameplay": GAMEPLAY}


def steps_of(kind) -> list:
    """The machine steps of a kind (each in one stepper group, `ui`)."""
    return STEPS[kind]


def ui_groups(kind) -> list:
    from .ui import onboard
    return ADAPTATION_UI if kind == "adaptation" else onboard.FLOWS[kind]


def doc_path(kind, step_id) -> Path:
    return SKILL / "steps" / kind / f"{step_id}.md"


# ---------------------------------------------------------------- state
def state(root, signals=None, F=None) -> dict:
    """{kind, steps: [{id, label, ui, actor, done, strict, crit}], current, todo, gaps, hints, round, F}."""
    F = F or facts(root, signals); kind = F["kind"]; sts = steps_of(kind)
    rows = []
    for st in sts:
        cr = st["crit"](F)
        if st["actor"] == "agent": cr = cr + _english(F, st["id"])
        rows.append({**{k: st[k] for k in ("id", "label", "ui", "actor", "needs", "tell")}, "crit": cr,
                     "strict": all(c["ok"] for c in cr if c["level"] == "fail"), "_st": st})
    ids = [r["id"] for r in rows]
    # a later version: everything before the round's first step was done in an earlier version
    start = ids.index(ROUND_START[kind]) - 1 if F["round"]["prev"] and ROUND_START.get(kind) in ids else -1
    last = max([start] + [i for i, r in enumerate(rows) if r["strict"] and r["_st"].get("anchor", True)])
    cur = next((i for i in range(last + 1, len(rows)) if not rows[i]["strict"]), None)
    for i, r in enumerate(rows): r["done"] = i <= last or (cur is None or i < cur)
    # gaps only after her last confirmation: what she already confirmed is not reopened (an old project is not sent back to fix it)
    floor = max([start] + [i for i, r in enumerate(rows) if r["actor"] == "user" and r["strict"]])
    end = cur if cur is not None else len(rows)
    gaps = [r["id"] for r in rows[floor + 1:end]
            if not r["strict"] and any(not c["ok"] and c["recheck"] and c["who"] == "agent" and c["level"] == "fail" for c in r["crit"])]
    todo = gaps[0] if gaps else (rows[cur]["id"] if cur is not None else None)
    hints = [c["why"] for r in rows[floor + 1:end + 1] for c in r["crit"] if not c["ok"] and c["level"] == "warn" and c["who"] == "agent"]
    return {"kind": kind, "steps": rows, "current": rows[cur]["id"] if cur is not None else None, "todo": todo, "gaps": gaps, "hints": hints,
            "round": F["round"], "F": F}


def stepper(root, signals=None) -> dict:
    """The browser stepper (same shape as ever): {kind, steps: [{key, label, route, state}], current: group key | None, next}."""
    S = state(root, signals); kind = S["kind"]; F = S["F"]; rows = S["steps"]
    groups = ui_groups(kind); cur = next((r for r in rows if r["id"] == S["current"]), None)
    out = []
    for key, label, route in groups:
        mine = [r for r in rows if r["ui"] == key]
        st = "done" if mine and all(r["done"] for r in mine) else "current" if cur and cur["ui"] == key else "todo"
        if key == "go" and F["s"].get("live"): st = "run"
        out.append({"key": key, "label": label, "route": route, "state": st})
    nxt = cur["_st"]["ui_next"](F, cur["crit"]) if cur else {"label": "都完成了", "route": None, "wait": False, "hint": ""}
    return {"kind": kind, "steps": out, "current": cur["ui"] if cur else None, "next": nxt}


def _public(r, kind) -> dict:
    return {"id": r["id"], "label": r["label"], "actor": r["actor"], "done": r["done"], "doc": str(doc_path(kind, r["id"])),
            "needs": r["needs"], "criteria": [{k: c[k] for k in ("id", "ok", "why", "who", "level")} for c in r["crit"]]}


def next_step(root, signals=None) -> dict:
    """What `gameanything flow next` prints: the step to work on (todo), what is done, what it needs, what blocks it, what to tell her."""
    S = state(root, signals); kind = S["kind"]; rows = S["steps"]
    by = {r["id"]: r for r in rows}
    todo = by.get(S["todo"]); cur = by.get(S["current"])
    rd = S["round"]
    out = {"project": str(S["F"]["root"]), "kind": kind, "opted_in": kind in OPT_IN, "current": S["current"], "todo": S["todo"], "gaps": S["gaps"],
           "round": {"n": rd["n"], "milestone": rd["m"], "after": rd["prev"]},
           "done": [r["id"] for r in rows if r["done"]], "n": len(rows),
           "index": [r["id"] for r in rows].index(S["todo"]) + 1 if todo else None}
    fix = [x["why"] for x in rules(S["F"]["root"]) if not x["ok"]]
    if not todo:
        out.update(step=None, waiting_for=None, actions=fix, later=[], blockers=[], card_required=[], while_waiting=[],
                   tell_user="都完成了（最后一期也定稿了）。她再说想做什么，就从下一版的方案开始。")
        return out
    pend = [c for c in todo["crit"] if not c["ok"]]
    agent = [c for c in pend if c["who"] == "agent"]
    out.update(step=_public(todo, kind), current_step=_public(cur, kind) if cur and cur is not todo else None,
               actions=fix + [c["why"] for c in expected_now(todo)] + [f"(提醒) {c['why']}" for c in agent if c["level"] == "warn"],
               later=[c["why"] for c in agent if c["level"] == "fail" and c not in expected_now(todo)],
               blockers=[f"{WHO.get(c['who'], c['who'])}：{c['why']}" for c in pend if c["who"] != "agent"],
               waiting_for=None if fix or expected_now(todo) else next((c["who"] for c in pend if c["level"] == "fail" and c["who"] != "agent"), pend[0]["who"] if pend else None),
               card_required=card_required(todo), tell_user=_tell(cur or todo, S["F"]),
               while_waiting=S["hints"] if not expected_now(todo) else [])
    return out


def _tell(row, F) -> str: return row["tell"](F) if callable(row["tell"]) else row["tell"]


def expected_now(row) -> list:
    """The agent criteria of a step that fail and can be done now: those before the first failing criterion of her / the coordinator
    (after the go card she must press 开工 before a build_start request is due; candidates wait for the drawing)."""
    out = []
    for c in row["crit"]:
        if c["ok"] or c["level"] != "fail": continue
        if c["who"] != "agent": break
        out.append(c)
    return out


def card_required(row) -> list:
    """Card criteria of the step that are due now (the chat guard and the corrective re-run use this)."""
    return [c["id"] for c in expected_now(row) if c["id"].endswith("_card")]


def c_web_refs(root) -> dict:
    """A rule of every step, every kind (landmark-references.md): a web picture in 2_perceive/landmark_refs needs her yes on a websearch
    card, and every picture there is listed in its sources.yaml (url, query, license). Not part of a step's exit: `check` fails with it."""
    from . import refs
    P = refs.problems(root)
    return _C("web_refs_consent", not P, "参考图：" + "；".join(P[:4]) + (f"（还有 {len(P) - 4} 处）" if len(P) > 4 else ""))


def c_files(root) -> dict:
    """A rule of every step: the files the pages read are well-formed (filecheck.py). A broken one is fixed before anything else."""
    from . import filecheck
    P = filecheck.problems(root)
    return _C("files_valid", not P, "这些文件页面读不了，先改好（用文件工具写成一份完整的 YAML，不要 cat >> 追加）：" + filecheck.text(P))


def c_decisions(root) -> dict:
    """A rule of every step: her confirmations are hers. A review file that says confirmed without her click on the page (decisions.py) is
    undone by the agent that wrote it, and she confirms herself."""
    from . import decisions
    P = decisions.forged(root); T = decisions.tampered(root)
    if T: return _C("user_decisions", False, f"她的确认记录被动过：{T}。她以前的确认现在都不算；不要再碰 conversation/ 里的记录，"
                    "请她自己在页面上把要确认的再点一次；永远不要替她写确认文件")
    return _C("user_decisions", not P, "这些「确认」不是她在页面上点的（是 agent 写的）："
              + "、".join(f for _, f in P[:4]) + "。把你写的 state: confirmed 改回 draft（或删掉那一行），请她自己在页面上确认；"
              "永远不要替她写确认文件")


def rules(root) -> list:
    """The rules of every step, every kind: web refs, well-formed files, her own confirmations."""
    return [c_web_refs(root), c_files(root), c_decisions(root)]


def check(root, step=None) -> dict:
    """{step, ok, criteria}: the exit criteria of `step` (default: the step to work on), plus the web refs rule (c_web_refs)."""
    S = state(root); by = {r["id"]: r for r in S["steps"]}
    sid = step or S["todo"] or S["current"]
    if sid not in by: raise ValueError(f"没有这一步：{sid}。这个项目的步骤：{' '.join(by)}")
    r = by[sid]; rs = rules(S["F"]["root"])
    return {"project": str(S["F"]["root"]), "kind": S["kind"], "step": sid, "ok": r["strict"] and all(x["ok"] for x in rs),
            "criteria": [{k: c[k] for k in ("id", "ok", "why", "who", "level")} for c in r["crit"] + rs]}


def agent_missing(root, step) -> list:
    """Agent criteria of `step` that fail and were due (expected_now): what a run working on that step should have done."""
    S = state(root); r = next((x for x in S["steps"] if x["id"] == step), None)
    if not r: return []
    # a broken file the pages read, or a confirmation of hers the agent wrote: fixed first (the corrective run says so)
    return [x for x in rules(root)[1:] if not x["ok"]] + expected_now(r)


# ---------------------------------------------------------------- text output
WHO = {"user": "她", "coordinator": "协调者", "agent": "你"}


def next_text(n: dict) -> str:
    L = [f"项目 {n['project']}（{n['kind']}）"]
    if not n.get("step"):
        L += [f"你现在要做的：{a}" for a in n.get("actions") or []]; L.append(n["tell_user"]); return "\n".join(L)
    s = n["step"]
    L.append(f"要做的这一步：{n['index']}/{n['n']} {s['id']}「{s['label']}」" + (f"（先补这一步；现在的步骤是 {n['current']}）" if n["gaps"] else ""))
    if n.get("round", {}).get("after"): L.append(f"第 {n['round']['n']} 版（{n['round']['milestone']}）：上一版 {n['round']['after']} 之前的步骤都算做过了")
    L.append("已完成：" + (" ".join(n["done"]) or "无"))
    if n["actions"]:
        L.append("你现在要做的："); L += [f"  - {a}" for a in n["actions"]]
    if n["blockers"]:
        L.append("在等：" if not n["actions"] else "然后在等："); L += [f"  - {b}" for b in n["blockers"]]
    if n.get("later"):
        L.append("她做完之后你再做（现在不要做）："); L += [f"  - {a}" for a in n["later"]]
    if n.get("while_waiting"):
        L.append("等她的时候可以先做："); L += [f"  - {h}" for h in n["while_waiting"]]
    if n.get("card_required"): L.append(f"这一步要发卡（{', '.join(n['card_required'])}）：用 gameanything chat card 发，不要只发文字")
    L.append(f"步骤文档：{s['doc']}")
    L.append(f"告诉她：{n['tell_user']}")
    return "\n".join(L)


def check_text(c: dict) -> str:
    L = [f"{c['step']}：{'通过' if c['ok'] else '没通过'}"]
    for x in c["criteria"]:
        mark = "OK  " if x["ok"] else ("注意" if x["level"] == "warn" else "不行")
        L.append(f"  {mark} {x['id']} [{WHO.get(x['who'], x['who'])}]" + (f"：{x['why']}" if x["why"] else ""))
    return "\n".join(L)


def main(a) -> int:
    root = projects.resolve(a.project)
    if a.what == "next":
        n = next_step(root)
        print(osdirs.json_text(n, indent=1) if a.json else next_text(n)); return 0
    try: c = check(root, a.step)
    except ValueError as e: print(f"[flow] {e}"); return 2
    print(osdirs.json_text(c, indent=1) if a.json else check_text(c)); return 0 if c["ok"] else 1
