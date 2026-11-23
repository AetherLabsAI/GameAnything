"""The LLM judge that labels her feedback records for the evaluation (docs/feedback-loop.md 7.4), and the agreement between labellers.

Her words go to a model only after she said yes on the project's `permission` card (key CONSENT_KEY), and every judge run is a
privacy_ledger.yaml `requests:` entry, like perceive. The judge runs the way perceive's agent-native mode does: no paid key, no script
calling an API. `emit` writes self-contained request files; the agent CLI on her own login (the resident, or a fresh sub-agent it starts)
answers each one into its output file; `collect` validates the answers and stores them next to the other labels (record.labels.judge,
.judge_b for the second prompt order) with the model, the rubric and the prompt version. Nothing here sends anything anywhere.

    consent_card(root) / consent(root)          the permission card she answers, and whether she said yes (on the current card of the key)
    emit(root, model, frames=False)             requests (two prompt orders; record labels + repeat pairs) -> feedback/labels/judge/<run>/
    collect(root, run=None)                     validate the answers, store labels, ledger entry, `judge` metrics event
    agreement(roots, a, b, field) / alpha(...)  Cohen's kappa + confusion matrix (two labellers), Krippendorff's alpha (nominal, any number)

All of it is study-only (study.py): with study mode off there is no card, no consent, no run (every call refuses with STUDY_OFF).
"""
import json
import random
from datetime import datetime
from pathlib import Path

import yaml

from . import feedback as F, layout

CONSENT_KEY = "feedback-judge"
RUBRIC_VERSION = "taxonomy-7.2-v1"     # the kind table of docs 7.2 with one positive and one negative example per kind
PROMPT_VERSION = 1                      # bump when the prompt text changes; labels keep the version they were made with
ORDERS = ("a", "b")                     # a: taxonomy and records as listed; b: both reversed (prompt-order robustness, 7.4)
WHO = {"a": "judge", "b": "judge_b"}
BATCH = 40

# one positive and one negative example per kind (abstracted; the negative is a near miss that belongs to another kind)
EXAMPLES = {
    "sparse_plain": ("这里有点简陋，空荡荡的", "颜色太灰了（color_light）"),
    "not_like_reference": ("跟我给你的参考图不一样，一点都不像那个地方", "这里太空了（sparse_plain）"),
    "mood": ("没有那种悬疑恐怖的感觉", "房间里东西太少（sparse_plain）"),
    "color_light": ("整体画面灰蒙蒙的，不鲜亮", "没有恐怖的氛围（mood）"),
    "clipping": ("人物穿模了，陷进桌子里", "桌子位置不对（layout_scale）"),
    "unreadable_object": ("后面那片白色的是什么？", "那个建筑呢？（missing_content）"),
    "layout_scale": ("喷泉怎么跑到水池里了；比例不对", "喷泉的模型有缝隙（model_quality）"),
    "model_quality": ("招牌全是缝隙和三角面", "招牌是中文要改英文（text_language）"),
    "missing_content": ("海狮呢？标志性的建筑呢？", "这是什么东西？（unreadable_object）"),
    "npc_life": ("为什么人都站着不动", "人穿进墙里了（clipping）"),
    "camera": ("镜头太抖，那里没录到正面", "画面太暗（color_light）"),
    "text_language": ("游戏里的字要改成英文", "卡片里看不到图（ui_delivery）"),
    "ui_delivery": ("卡片里看不到图；网页上找不到那个按钮", "游戏报错了（game_error）"),
    "game_error": ("游戏界面又报错了，崩溃了", "网页打不开（ui_delivery）"),
    "other": ("我有一个可以生成 3D 模型的 API", "这里太简陋（sparse_plain）"),
}

PROMPT = """# Labelling request {run} / order {order} / part {part}  (rubric {rubric}, prompt v{pv})

You label pieces of feedback that ONE user gave on versions of a game world built for her. You are a careful annotator for a research
study. Label each record independently, from its words (and the scene / chapter / picture given with it); do not guess from other records.

For each record return:
- class: bug (something is broken) | taste (it works but does not look / feel right to her) | request (add or change something) |
  question (she asks; a question that exposed a defect still has the defect's kind)
- kind: exactly ONE row of the taxonomy below: the change she wants belongs to that row (the primary one if she says several things)
- target: the place, room or object her words are about, written as one of the PLACES below when one fits, else a short noun from her
  words, else null. A different room of the same house is a different target.
- explanation: one short sentence (English) saying why.

Taxonomy (kind: meaning; + an example that IS this kind; - a near miss that is NOT):
{taxonomy}

PLACES of this project: {places}

Records (JSON, one per line; `words` are her words verbatim, `chapter` the part of the video she was watching, `frame` a picture of the
moment she pointed at when given):
{records}

Answer by writing ONE JSON object per record, one per line (JSON Lines, no code fence, no other text), with exactly the keys
{{"id", "class", "kind", "target", "explanation"}}, to:
{out}
Use the Write tool. Write nothing else anywhere. Do not open any other file of the project{frame_rule}.
"""

PAIR_PROMPT = """# Repeat-pair request {run} / order {order}  (rubric {rubric}, prompt v{pv})

Each line below is a PAIR of feedback records the same user gave on two versions of the same game world (`first` on an earlier
version, `second` on a later one). For each pair answer: is the second the same complaint as the first, on the same thing?
- same_kind: yes | no: the change she wants in both belongs to the same row of this taxonomy: {kinds}
- same_target: yes | no | unknown: the same place, room or object (a different room of the same house is a different target)
- answer: yes (same complaint, same thing) | partly (same complaint, other thing; or same thing, related complaint) | no
- reason: one short sentence (English).

Pairs (JSON, one per line):
{pairs}

Answer with ONE JSON object per pair, one per line, keys {{"first", "second", "same_kind", "same_target", "answer", "reason"}}, to:
{out}
Use the Write tool. Write nothing else anywhere.
"""


class JudgeError(ValueError):
    pass


STUDY_OFF = "研究模式没开（gameanything project set-study <项目> on）：模型标注只在做研究时用，不发许可卡，也不跑"


def _need_study(root):
    from . import study
    if not study.on(root): raise JudgeError(STUDY_OFF)


def now() -> str: return datetime.now().isoformat(timespec="seconds")
def base(root) -> Path: return Path(root) / layout.FEEDBACK / "labels" / "judge"


# ---------------------------------------------------------------- consent (her permission card, per project)
def consent_card(root, frames=False) -> dict:
    """The permission card the resident sends once per project. Key CONSENT_KEY; what is sent, what is not, to whom. frames: also the
    frames she pointed at (the with-frame ablation of 7.4; `files` lists them, emit(frames=True) needs it). Study mode only."""
    _need_study(root)
    c = _card(root)
    if frames:
        c["will_send"].insert(1, "你在录像上指出的那一帧截图"); c["will_not_send"][0] = "你的照片（录像截图以外的）"
        c["en"]["will_send"].insert(1, "the video frame you pointed at"); c["en"]["will_not_send"][0] = "your photos (other than those frames)"
        c["files"] = ["feedback/frames/*", "conversation/files/*"]
    return c


def _card(root) -> dict:
    n = len(F.load(root))
    return {"kind": "permission", "key": CONSENT_KEY,
            "title": "让模型给你的意见分类（只做研究统计：同一件事你要说几遍）",
            "will_send": [f"你在这个项目里说的 {n} 条意见原话（以后的新意见也一样）", "每条意见对应的场景名 / 录像章节名",
                          "用途：按「哪一类问题」打标签（场景简陋 / 穿模 / 看不出是什么…），标签只存在这个项目里，不改变我们怎么改你的游戏"],
            "will_not_send": ["你的照片和录像截图", "你的名字和别的项目", "原始文件"],
            "to": "你自己的 Claude Code 会话（平时跟你聊天的同一个账号，不用额外的 API 钥匙）",
            "en": {"title": "Let the model sort your comments by kind (research statistics only: how often you must say the same thing)",
                   "will_send": [f"your {n} comments in this project, verbatim (and new ones later)", "the scene / video chapter each one is about",
                                 "purpose: a kind label (bare scene, clipping, cannot tell what it is, …), stored only in this project; it does not change how we fix your game"],
                   "will_not_send": ["your photos and video frames", "your name and other projects", "original files"],
                   "to": "your own Claude Code session (the login you chat with; no extra API key)"}}


def consent(root):
    """(yes?, card id, why): her answer on the current card of CONSENT_KEY. No card / not answered / no / study mode off -> no judge."""
    from . import study
    if not study.on(root): return False, None, STUDY_OFF
    from .conversation import Thread
    from .genrun import _card_ids, _decision
    cid, c = _card_ids(Thread(root), CONSENT_KEY)
    if not c: return False, None, f"还没有发许可卡（key {CONSENT_KEY}）：gameanything feedback judge --project P --card"
    if c["card"].get("kind") != "permission": return False, cid, f"{CONSENT_KEY} 不是一张 permission 卡"
    d = _decision(c)
    if d != "yes": return False, cid, "她还没有在许可卡上点「同意」" if d is None else "她没有同意：这个项目不用模型标注"
    return True, cid, ""


def _consent_files(root) -> bool:
    from .conversation import Thread
    from .genrun import _card_ids
    _, c = _card_ids(Thread(root), CONSENT_KEY)
    return bool(c and c["card"].get("files"))


# ---------------------------------------------------------------- requests
def _taxonomy(order):
    ks = list(F.KINDS) if order == "a" else list(F.KINDS)[::-1]
    return "\n".join(f"- {k}: {F.KINDS[k][2]}  (+ 「{EXAMPLES[k][0]}」  - 「{EXAMPLES[k][1]}」)" for k in ks)


def _places(root):
    seen = []
    for _, c in F.targets(root):
        if c not in seen: seen.append(c)
    return ", ".join(seen) or "(none known)"


def _item(r, frames):
    a = r.get("anchor") or {}
    d = {"id": r["id"], "words": r.get("words"), "version": r.get("milestone"), "chapter": (a.get("chapter") or {}).get("title")}
    if frames and (a.get("frame") or a.get("image")): d["frame"] = a.get("frame") or a.get("image")
    return d


def pair_candidates(recs, order_of) -> list:
    """Loose-repeat pairs (same live kind, earlier version) the judge checks: (first, second)."""
    rp = F.repeats(recs, order_of); out = []
    for rid, v in rp.items():
        for o in v.get("loose") or []: out.append((o, rid))
    return out


def emit(root, model, frames=False, ids=None, batch=BATCH) -> dict:
    """Write the requests of a new judge run (refused without her yes). -> {run, dir, requests: [paths], records, pairs}."""
    root = Path(root).resolve(); _need_study(root)
    ok, cid, why = consent(root)
    if not ok: raise JudgeError(why)
    if frames and not _consent_files(root): raise JudgeError("许可卡没有包括录像截图：要带截图，先发 --card --frames 的那张，她同意了再来")
    if not model: raise JudgeError("要 --model（回答这些请求的模型，写进标签和 privacy_ledger.yaml）")
    recs = [r for r in F.load(root) if not ids or r["id"] in ids]
    if not recs: raise JudgeError("没有要标注的记录")
    run = f"j{datetime.now():%Y%m%dT%H%M%S}"; d = base(root) / run; d.mkdir(parents=True, exist_ok=True)
    places = _places(root); reqs = []
    for order in ORDERS:
        rs = recs if order == "a" else recs[::-1]
        for i in range(0, len(rs), batch):
            part = i // batch + 1; out = d / f"out_{order}_{part}.jsonl"
            body = "\n".join(json.dumps(_item(r, frames), ensure_ascii=False) for r in rs[i:i + batch])
            rule = (": the frames are inside the project (Read them by the path given, relative to " + str(root) + ")") if frames else ""
            f = d / f"req_{order}_{part}.md"
            f.write_text(PROMPT.format(run=run, order=order, part=part, rubric=RUBRIC_VERSION, pv=PROMPT_VERSION, taxonomy=_taxonomy(order),
                                       places=places, records=body, out=out, frame_rule=rule), encoding="utf-8")
            reqs.append(f)
    order_of = {v["m"]: i for i, v in enumerate(F.versions(root))}
    prs = pair_candidates(F.load(root), order_of); byid = {r["id"]: r for r in F.load(root)}
    prs = [p for p in prs if not ids or (p[0] in ids and p[1] in ids)]
    if prs:
        for order in ORDERS:
            ps = prs if order == "a" else [(b, a) for a, b in prs][::-1]          # order b: the two records swapped, the list reversed
            lines = "\n".join(json.dumps({"first": {"id": a, "words": byid[a].get("words"), "version": byid[a].get("milestone")},
                                          "second": {"id": b, "words": byid[b].get("words"), "version": byid[b].get("milestone")}},
                                         ensure_ascii=False) for a, b in ps)
            f = d / f"pairs_{order}.md"
            f.write_text(PAIR_PROMPT.format(run=run, order=order, rubric=RUBRIC_VERSION, pv=PROMPT_VERSION, kinds=", ".join(F.KINDS),
                                            pairs=lines, out=d / f"pairs_out_{order}.jsonl"), encoding="utf-8")
            reqs.append(f)
    meta = {"run": run, "model": model, "rubric": RUBRIC_VERSION, "prompt_version": PROMPT_VERSION, "orders": list(ORDERS), "frames": bool(frames),
            "records": [r["id"] for r in recs], "pairs": [list(p) for p in prs], "consent_card": cid, "at": now(), "collected": None,
            "requests": [p.name for p in reqs]}
    (d / "run.yaml").write_text(yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8")
    F.log_event(root, "judge_emit", run=run, model=model, rubric=RUBRIC_VERSION, prompt_version=PROMPT_VERSION, n=len(recs), pairs=len(prs), frames=bool(frames))
    return {"run": run, "dir": str(d), "requests": [str(p) for p in reqs], "records": len(recs), "pairs": len(prs)}


def runs(root) -> list:
    b = base(root)
    return sorted(p.parent.name for p in b.glob("*/run.yaml")) if b.is_dir() else []


def _rows(f):
    out, bad = [], []
    if not f.is_file(): return out, bad
    for n, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        if not ln.strip(): continue
        try: x = json.loads(ln)
        except ValueError: bad.append(f"{f.name}:{n} 不是 JSON"); continue
        if isinstance(x, dict): out.append(x)
        else: bad.append(f"{f.name}:{n} 不是一个对象")
    return out, bad


def collect(root, run=None) -> dict:
    """Validate the answers of a judge run and store them (record.labels.judge / .judge_b, with model, rubric, prompt version, run, the
    explanation; the repeat-pair answers under labels.judge.pairs); one privacy_ledger.yaml entry; a `judge` metrics event. -> counts."""
    root = Path(root).resolve(); _need_study(root); run = run or (runs(root) or [None])[-1]
    if not run: raise JudgeError("还没有 judge 请求（先 --emit）")
    d = base(root) / run; meta = yaml.safe_load((d / "run.yaml").read_text(encoding="utf-8"))
    if meta.get("collected"): raise JudgeError(f"{run} 已经收过了（{meta['collected']}）")
    want = set(meta["records"]); got = {o: {} for o in ORDERS}; bad = []
    for o in ORDERS:
        for f in sorted(d.glob(f"out_{o}_*.jsonl")):
            rows, b = _rows(f); bad += b
            for x in rows:
                rid = x.get("id")
                if rid not in want: bad.append(f"{f.name}: 不认识的记录 {rid}"); continue
                if x.get("class") not in F.CLASSES or x.get("kind") not in F.KINDS: bad.append(f"{f.name}: {rid} 的 class / kind 不在表里"); continue
                got[o][rid] = x
    pairs = {o: _rows(d / f"pairs_out_{o}.jsonl")[0] for o in ORDERS}
    missing = {o: sorted(want - set(got[o])) for o in ORDERS}
    if not any(got.values()): raise JudgeError("没有可用的回答：" + ("；".join(bad[:5]) or "输出文件还是空的"))
    common = {"model": meta["model"], "rubric": meta["rubric"], "prompt_version": meta["prompt_version"], "run": run, "frames": meta.get("frames")}
    def fn(recs):
        n = 0
        for r in recs:
            for o in ORDERS:
                x = got[o].get(r["id"])
                if not x: continue
                F.put_label(r, WHO[o], x["class"], x["kind"], F.KINDS[x["kind"]][0], x.get("target") or None, explanation=x.get("explanation"), order=o, **common)
                n += 1
            pa = [p for p in pairs["a"] if p.get("second") == r["id"]] + [{**p, "first": p.get("second"), "second": p.get("first"), "order": "b"}
                                                                         for p in pairs["b"] if p.get("first") == r["id"]]
            if pa and (r.get("labels") or {}).get("judge") is not None:
                r["labels"]["judge"]["pairs"] = [{k: p.get(k) for k in ("first", "same_kind", "same_target", "answer", "reason", "order")} for p in pa]
        return n
    n = F._edit(root, fn)
    sent = {"at": now(), "purpose": "feedback-judge", "backend": "agent-cli-session", "model": meta["model"], "run": run,
            "consent_card": meta.get("consent_card"), "text": [f"her words of {len(want)} feedback records ({F.path(root).relative_to(root).as_posix()})"],
            "records": sorted(want), "images": sorted({(next((r for r in F.load(root) if r["id"] == i), {}).get("anchor") or {}).get("frame") or ""
                                                       for i in want} - {""}) if meta.get("frames") else []}
    from .perceive import ledger_append
    ledger_append(root, [sent])
    meta["collected"] = now(); meta["missing"] = missing; meta["problems"] = bad[:50]
    (d / "run.yaml").write_text(yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8")
    F.log_event(root, "judge", run=run, model=meta["model"], rubric=meta["rubric"], prompt_version=meta["prompt_version"],
                labelled={o: len(got[o]) for o in ORDERS}, pairs={o: len(pairs[o]) for o in ORDERS}, missing={o: len(v) for o, v in missing.items()},
                order_agreement=agreement([root], "judge", "judge_b")["kappa"])
    return {"run": run, "stored": n, "labelled": {o: len(got[o]) for o in ORDERS}, "missing": missing, "problems": bad,
            "pairs": {o: len(pairs[o]) for o in ORDERS}}


# ---------------------------------------------------------------- agreement (7.4 step 4)
def _value(r, who, field):
    x = (r.get("labels") or {}).get(who)
    if x is None and who == "live": x = {"class": r.get("class"), "kind": r.get("kind"), "target": (r.get("anchor") or {}).get("target")}
    return (x or {}).get(field)


def labellers(roots) -> list:
    """Every labeller name present in these projects' records (heuristic, resident, judge, judge_b, human:<name>, …)."""
    out = []
    for root in roots:
        for r in F.load(root):
            for k in (r.get("labels") or {}):
                if k not in out: out.append(k)
    return out


def agreement(roots, a="judge", b="human", field="kind", only_complaints=False) -> dict:
    """Cohen's kappa of labellers a and b on `field` over the records both labelled (pooled over projects), with the confusion matrix
    (rows a, columns b) and the raw agreement. `live` = the record's live labels. kappa None when n = 0 or the chance agreement is 1."""
    pairs = []
    for root in roots:
        for r in F.load(root):
            if only_complaints and not F.is_complaint(r): continue
            x, y = _value(r, a, field), _value(r, b, field)
            if x is not None and y is not None: pairs.append((str(x), str(y)))
    n = len(pairs)
    if not n: return {"a": a, "b": b, "field": field, "n": 0, "kappa": None, "observed": None, "confusion": {}}
    cats = sorted({v for p in pairs for v in p}); po = sum(1 for x, y in pairs if x == y) / n
    pa = {c: sum(1 for x, _ in pairs if x == c) / n for c in cats}; pb = {c: sum(1 for _, y in pairs if y == c) / n for c in cats}
    pe = sum(pa[c] * pb[c] for c in cats)
    conf = {c: {d: sum(1 for x, y in pairs if x == c and y == d) for d in cats} for c in cats}
    return {"a": a, "b": b, "field": field, "n": n, "observed": po, "kappa": None if pe >= 1 else (po - pe) / (1 - pe), "confusion": conf}


def alpha(roots, raters=None, field="kind") -> dict:
    """Krippendorff's alpha (nominal) over any number of labellers (default: judge and every human:<name>); units = records with >= 2 labels."""
    raters = raters or [k for k in labellers(roots) if k == "judge" or k.startswith("human")]
    units = []
    for root in roots:
        for r in F.load(root):
            vs = [str(v) for v in (_value(r, k, field) for k in raters) if v is not None]
            if len(vs) >= 2: units.append(vs)
    if not units: return {"raters": raters, "field": field, "units": 0, "alpha": None}
    from collections import Counter
    o = Counter()                                         # coincidence matrix
    for vs in units:
        m = len(vs)
        for i, x in enumerate(vs):
            for j, y in enumerate(vs):
                if i != j: o[(x, y)] += 1 / (m - 1)
    nc = Counter()
    for (x, _), v in o.items(): nc[x] += v
    N = sum(nc.values())
    do = sum(v for (x, y), v in o.items() if x != y)
    de = sum(nc[x] * nc[y] for x in nc for y in nc if x != y) / (N - 1) if N > 1 else 0
    return {"raters": raters, "field": field, "units": len(units), "alpha": None if not de else 1 - do / de}


def sample_sheet(root, out=None, seed=0) -> Path:
    """A blind sheet for a human labeller (7.4 step 3): ids and words only, shuffled with a fixed seed; import it back with
    `gameanything feedback label --import F --labeller human --name <who>`. Study mode only."""
    _need_study(root)
    recs = F.load(root); rng = random.Random(seed); rows = list(recs); rng.shuffle(rows)
    f = Path(out) if out else Path(root) / layout.FEEDBACK / "labels" / f"human-{datetime.now():%Y-%m-%d}-seed{seed}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "w", encoding="utf-8") as h:
        for r in rows:
            h.write(json.dumps({"id": r["id"], "words": r.get("words"), "chapter": ((r.get("anchor") or {}).get("chapter") or {}).get("title"),
                                "class": None, "kind": None, "target": None}, ensure_ascii=False) + "\n")
    return f
