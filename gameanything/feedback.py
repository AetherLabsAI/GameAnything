"""Her feedback as structured records: the inner loop of docs/feedback-loop.md (records, confirmation, same-anchor verification) and the
data of its metrics. One project's records are <project>/feedback/records.yaml; the metrics log is <project>/feedback/metrics.jsonl.

    load(root) / save(root, recs)          the record list (atomic write under feedback/.records.lock)
    log_event(root, ev, **fields)          one line of feedback/metrics.jsonl (the evaluation's raw data, docs/feedback-loop.md 7.5)
    capture(root, events)                  `gameanything chat read`: a `new` record for each of her anchored words (video moment, region, picture, verdict)
    add / set_fields / confirm / link / verdict / accept     the resident's edits behind `gameanything feedback …`
    on_item(root, item, state, build, by, evidence)          STATUS item changed (devstatus.set_item): linked records follow (fixed / in_progress)
    verify / pairs / on_deliver / unverified                 same-anchor verification (before / after pairs, 5_build/<m>/play/verify.yaml)
    card(root, what, …)                    the confirm card (uncertain readings) and the verify card (her ok on before / after)
    heuristic_label(words) / targets(root) the zero-cost keyword labeller (kind, class) and the project's scene / place names
    repeats(recs, order) / metrics(root)   repeat detection and every metric of the 开发状态 panel and the paper
    backfill(root)                         records rebuilt from an existing project's thread, build feedback, play.yaml and STATUS.yaml
    brief(root, role, budget)              what a build starts with (budgeted, logged as a `retrieval`); the outer loop's retrieval seam
    retro_input / critic_input             what the retrospective and the critic see (the steps themselves: retro.py)
    assign / condition / uses              the blind per-version evaluation condition (docs 7.6, 7.8); study mode only
    datacheck(root)                        every datum the evaluation needs and whether this project records it (docs 7.5); study mode only

Study mode (study.py, docs/feedback-loop.md 0) is off by default: then every version runs the full loop (C4, nothing withheld), no condition
is assigned and log_event writes nothing to feedback/metrics.jsonl. The records, cards, verification, profile, retrospective and critic run
the same in both states.

Her words (`words`) are copied verbatim from the thread event and never edited; frames and pictures stay in her project (paths only).
"""
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import yaml

from . import layout, osdirs

CLASSES = ("bug", "taste", "request", "question")
STATES = ("new", "interpreted", "confirming", "answered", "dropped", "open", "in_progress", "fixed", "verifying", "closed", "reopened")
TERMINAL = ("answered", "dropped", "closed")
SCOPES = ("project", "user", "game", "mode", "craft", "system")
MODALITIES = ("text", "video_moment", "image", "image_region")
SOURCES = ("chat", "playtest", "picture", "card", "verdict", "backfill")
METHODS = ("reshoot", "chapter_offset", "listed")
CONDITIONS = ("C0", "C1", "C2", "C3", "C4")
# the complaint taxonomy (docs/feedback-loop.md 7.2): kind -> (default scope, zh, en)
KINDS = {
    "sparse_plain": ("user", "场景简陋 / 空 / 不精致", "bare, plain or crude scene"),
    "not_like_reference": ("craft", "不像真实地方 / 参考图", "not like the real place / reference"),
    "mood": ("user", "氛围不到位", "the feeling / genre is missing"),
    "color_light": ("user", "颜色 / 光线", "colour and light"),
    "clipping": ("craft", "穿模", "clipping"),
    "unreadable_object": ("craft", "看不出是什么", "cannot tell what it is"),
    "layout_scale": ("craft", "位置 / 比例 / 布局", "position, scale or layout"),
    "model_quality": ("craft", "模型 / 贴图坏了", "broken model or texture"),
    "missing_content": ("project", "少了东西", "something missing"),
    "npc_life": ("craft", "人物不动 / 太少", "people static or too few"),
    "camera": ("mode", "录像镜头", "the video camera"),
    "text_language": ("project", "游戏里的文字", "in-game text"),
    "ui_delivery": ("system", "网页 / 卡片 / 汇报的问题", "the product: page, cards, reports"),
    "game_error": ("game", "游戏报错", "game error"),
    "other": ("project", "其他", "other"),
}
# keyword rules of the heuristic labeller, in priority order: (kind, class, patterns). The first rule with a hit gives the primary kind.
RULES = [
    ("other", "question", ["我发现", "原来是"]),                       # her own clarification of an earlier comment, not a new one
    ("ui_delivery", "bug", ["卡片", "看不到图", "图呢", "bug", "试玩页", "播报", "汇报"]),
    ("game_error", "bug", ["报错", "崩溃", "闪退", "crash"]),
    ("clipping", "bug", ["穿模", "陷进", "埋在", "重叠"]),
    ("model_quality", "bug", ["缝隙", "三角", "建模有问题", "贴图", "糊成"]),
    ("camera", "taste", ["镜头", "录歪", "没录到", "闪过去", "太快", "视角", "录像", "抖"]),
    ("text_language", "request", ["英文", "中文", "文字", "大字", "招牌", "门牌", "地名"]),
    ("sparse_plain", "taste", ["简陋", "空荡", "太空", "这么空", "光秃秃", "不够精美", "不够好看", "丑", "难看", "粗糙", "生硬", "稀疏", "单调", "精致", "丰富"]),
    ("npc_life", "taste", ["不走动", "站着不动", "人都", "人也", "人物"]),
    ("layout_scale", "bug", ["跑到", "位置", "摆正", "比例", "布局", "俯视", "朝北"]),
    ("not_like_reference", "taste", ["不像", "参考图不一样", "不是这样", "不对", "照着做", "上网搜", "搜一下", "搜到"]),
    ("mood", "taste", ["氛围", "阴森", "悬疑", "恐怖", "繁华", "商圈", "感觉"]),
    ("color_light", "taste", ["颜色", "灰蒙蒙", "暗淡", "鲜亮", "灰暗", "太暗", "偏暗", "光线", "灰白"]),
    ("unreadable_object", "question", ["是什么", "是啥", "什么东西", "啥地方"]),
    ("missing_content", "request", ["呢？", "呢?", "在哪", "缺少", "还缺", "再加", "还没做", "加上", "没有海"]),
]
REPEAT_MARK = re.compile(r"还是|又|仍然|依然|\bstill\b|\bagain\b", re.I)
# generic scene words -> canonical target (used when the project's own place names do not match)
LEXICON = {"客厅": "客厅", "起居室": "客厅", "餐厅": "餐厅", "走廊": "走廊", "楼上": "走廊", "卧室": "卧室", "客房": "卧室", "房子": "房子", "宅邸": "房子",
           "大宅": "房子", "海景": "海边", "海边": "海边", "沙滩": "海边", "港口": "港口", "码头": "港口", "航母": "航母", "图书馆": "图书馆", "喷泉": "喷泉",
           "溜冰场": "溜冰场", "海狮": "海狮", "海豹": "海狮"}
HEADER = ("# 她的反馈记录（gameanything feedback 写的；格式见 docs/feedback-loop.md 1.1）。words 是她的原话，永远不改；interpretation 是 agent 的理解。\n")


class FeedbackError(ValueError):
    pass


def now() -> str: return datetime.now().isoformat(timespec="seconds")
def path(root) -> Path: return Path(root) / layout.FEEDBACK / "records.yaml"
def log_path(root) -> Path: return Path(root) / layout.FEEDBACK / "metrics.jsonl"
def _s(v) -> str: return "" if v is None else str(v)


# ---------------------------------------------------------------- store
def load(root) -> list:
    """The records (a list of dicts; never raises: a missing or broken file is [])."""
    try: d = yaml.safe_load(path(root).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError): return []
    d = d.get("records") if isinstance(d, dict) else d
    return [x for x in d if isinstance(x, dict)] if isinstance(d, list) else []


def save(root, recs: list) -> Path:
    f = path(root); f.parent.mkdir(parents=True, exist_ok=True); tmp = f.with_name("." + f.name + ".tmp")
    tmp.write_text(HEADER + yaml.safe_dump({"records": recs}, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
    os.replace(tmp, f); return f


def _edit(root, fn):
    """Load, fn(records) under the lock file, save. A records.yaml that exists but does not parse is never overwritten."""
    f = path(root); f.parent.mkdir(parents=True, exist_ok=True)
    with open(f.parent / ".records.lock", "a", encoding="utf-8") as lk:
        osdirs.lock(lk)
        if f.exists():
            try: yaml.safe_load(f.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, yaml.YAMLError) as e: raise FeedbackError(f"records.yaml 读不了（{e}）：先把它修好")
        recs = load(root); r = fn(recs); save(root, recs)
    return r


def log_event(root, ev: str, **fields):
    """Append one metrics event; never fails the caller (the log is evidence, not state). Only in study mode: the log is the study's data,
    nothing the product reads (records.yaml keeps every record's own history)."""
    from . import study
    if not study.on(root): return
    try:
        f = log_path(root); f.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"at": fields.pop("at", None) or now(), "ev": ev, **fields}, ensure_ascii=False, default=str) + "\n"
        with open(f, "a", encoding="utf-8") as h: h.write(line)
    except OSError: pass


def events(root, ev=None) -> list:
    try: lines = log_path(root).read_text(encoding="utf-8").splitlines()
    except OSError: return []
    out = []
    for ln in lines:
        try: x = json.loads(ln)
        except ValueError: continue
        if isinstance(x, dict) and (ev is None or x.get("ev") == ev): out.append(x)
    return out


def _next_id(recs) -> str:
    n = max([int(m.group(1)) for r in recs for m in [re.match(r"^f(\d+)$", _s(r.get("id")))] if m] or [0])
    return f"f{n + 1}"


def get(recs, rid):
    r = next((x for x in recs if x.get("id") == rid), None)
    if r is None: raise FeedbackError(f"没有记录 {rid}")
    return r


def _state(root, r, to, by, at=None):
    old = r.get("state")
    if old == to: return
    r["state"] = to; r.setdefault("history", []).append({"at": at or now(), "state": to, "by": by})
    log_event(root, "record_state", id=r["id"], at=at, **{"from": old, "to": to, "by": by}, **({"backfill": True} if by == "backfill" else {}))


def put_label(r, who, cls=None, kind=None, scope=None, target=None, **extra):
    """Keep every labeller's labels next to each other (r["labels"][who]): heuristic, resident, judge (+ model / prompt version), human:<name>.
    The record's own class / kind / scope stay the live ones the system uses; the paper can compute every metric per labeller (relabel)."""
    L = r.setdefault("labels", {}); d = {k: v for k, v in (("class", cls), ("kind", kind), ("scope", scope), ("target", target)) if v is not None}
    L[who] = {**d, **{k: v for k, v in extra.items() if v is not None}, "at": extra.get("at") or now()}


def relabel(recs, who) -> list:
    """Copies of the records with class / kind / target taken from labeller `who` (records it did not label keep the live ones, marked)."""
    out = []
    for r in recs:
        x = dict(r); lb = (r.get("labels") or {}).get(who)
        if lb:
            for k in ("class", "kind"):
                if lb.get(k): x[k] = lb[k]
            if lb.get("target"): x["anchor"] = {**(r.get("anchor") or {}), "target": lb["target"]}
        else: x["_unlabelled"] = True
        out.append(x)
    return out


def project_id(root) -> str:
    from . import projects
    try:
        for e in projects.load():
            if Path(e.get("path", "")).resolve() == Path(root).resolve(): return e["id"]
    except Exception: pass
    return Path(root).name


# ---------------------------------------------------------------- versions, chapters, targets
def _y(p):
    try: return yaml.safe_load(Path(p).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError): return None


def versions(root, evs=None) -> list:
    """Delivered versions in delivery order: [{m, at}]. Time = the first `result` card of m, else world_plan `at`, else play.yaml's mtime."""
    from .conversation import Thread
    root = Path(root); evs = Thread(root).events() if evs is None else evs
    wp = _y(root / layout.DESIGN / "world_plan.yaml"); ms = ((wp or {}).get("world_plan") or {}).get("milestones") if isinstance(wp, dict) else None
    ms = ms if isinstance(ms, dict) else {}
    B = root / "5_build"
    play = sorted(d.name for d in B.iterdir() if d.is_dir() and (d / "play").is_dir()) if B.is_dir() else []
    keys = list(dict.fromkeys([str(k) for k in ms] + play)); card_at = {}
    for e in evs:
        c = e.get("card") or {}
        if e.get("type") == "card" and c.get("kind") == "result" and c.get("milestone"):
            k = _ms_key(str(c["milestone"]), keys, ms)
            if k: card_at.setdefault(k, e.get("at"))
    names = [str(m) for m, v in ms.items() if isinstance(v, dict) and (v.get("status") in ("built", "accepted") or str(m) in play or str(m) in card_at)]
    names += [m for m in play + list(card_at) if m not in names]
    out = []
    for i, m in enumerate(names):
        v = ms.get(m) if isinstance(ms.get(m), dict) else {}
        at = card_at.get(m) or _s(v.get("at")) or None
        if not at and (B / m / "play" / "play.yaml").is_file(): at = datetime.fromtimestamp((B / m / "play" / "play.yaml").stat().st_mtime).isoformat(timespec="seconds")
        out.append({"m": m, "at": at, "_i": i})
    out.sort(key=lambda x: (x["at"] or "9999", x["_i"]))
    return [{"m": x["m"], "at": x["at"]} for x in out]


def _ms_key(label, keys, ms):
    """A result card's `milestone` -> a milestone id: the id itself, a world_plan `name`, or 「第 3 期…」 / 「第 7 版…」 by its first number
    (期 -> a p-milestone, 版 -> an m-milestone when both exist). None for labels that name no milestone (「雕像 A」)."""
    if label in keys: return label
    for k, v in ms.items():
        if isinstance(v, dict) and _s(v.get("name")).strip() == label.strip(): return str(k)
    n = re.search(r"\d+", label)
    if not n or not re.search(r"第\s*\d+\s*[期版轮]|^[A-Za-z]+\d", label): return None
    c = [k for k in keys if re.fullmatch(r"[A-Za-z]+" + n.group(0), k)]
    if len(c) > 1: c = [k for k in c if k.startswith("p" if "期" in label else "m")] or c
    return c[0] if c else None


def version_at(vers, at) -> str:
    """The newest version delivered at or before `at` (what she was looking at), or None."""
    m = None
    for v in vers:
        if v["at"] and at and v["at"] <= at: m = v["m"]
    return m


def chapter_at(root, m, t):
    """The play.yaml chapter of version m that contains second t: {moment, title, t} or None."""
    from .delivery import load_play
    if t is None: return None
    ch = load_play(Path(root) / "5_build" / str(m) / "play").get("chapters") or []
    cur = None
    for c in ch:
        if c["t"] <= float(t): cur = c
    return {"moment": cur["moment"], "title": cur["title"], "t": cur["t"]} if cur else None


def targets(root) -> list:
    """[(alias, canonical)] longest alias first: the project's places (adaptation), board moments (memory), chapter titles, the lexicon."""
    root = Path(root); out = {}
    def put(alias, canon):
        a = _s(alias).strip()
        if len(a) >= 2 and a not in out: out[a] = canon
    ad = _y(root / layout.REMEMBER / "adaptation.yaml") or {}
    for p in (ad.get("places") or []) if isinstance(ad, dict) else []:
        if isinstance(p, dict) and p.get("name"):
            nm = _s(p["name"]); put(nm, nm)
            for part in re.split(r"[与和(（)）:：,，、\s]+", nm): put(part, nm)
    bd = (_y(root / layout.REMEMBER / "board.yaml") or {}).get("experience_board", {}) if isinstance(_y(root / layout.REMEMBER / "board.yaml"), dict) else {}
    for mo in bd.get("moments") or []:
        if not isinstance(mo, dict): continue
        nm = _s(mo.get("title")).split("：")[0].split(":")[0].strip()
        put(nm, nm)
        for w in re.findall(r"[A-Za-z][A-Za-z]+(?: [A-Z][a-z]+)*", nm): put(w, nm)
    canon = {_s(mo.get("id")): _s(mo.get("title")).split("：")[0].split(":")[0].strip() for mo in bd.get("moments") or [] if isinstance(mo, dict)}
    B = root / "5_build"
    for f in sorted(B.glob("*/play/play.yaml")) if B.is_dir() else []:           # chapter titles: 「沿海开车 Coast drive」 -> its board moment
        d = _y(f)
        for c in (d.get("chapters") or []) if isinstance(d, dict) and isinstance(d.get("chapters"), list) else []:
            if not isinstance(c, dict) or c.get("moment") in (None, "full"): continue
            ti = _s(c.get("title")).strip()
            cn = canon.get(_s(c.get("moment"))) or find_target(ti, sorted(out.items(), key=lambda kv: -len(kv[0]))) or ti   # 「客厅 · 留声机的指控」 -> 客厅
            put(ti, cn)
            for part in re.split(r"[\s·]+", ti):
                if not part.isascii(): put(part, cn)
    for k, v in LEXICON.items():
        hit = next((c for a, c in out.items() if k in a), None)          # 客厅 inside 「客厅(风暴夜的起居室)」: map to the project's place
        put(k, hit or v)
    return sorted(out.items(), key=lambda kv: -len(kv[0]))


def chapter_target(root, ch, tg):
    """The target of a video moment whose words name none: its play.yaml chapter (a board moment / scene, not the one `full` chapter)."""
    if not ch or ch.get("moment") in (None, "", "full"): return None
    bd = _y(Path(root) / layout.REMEMBER / "board.yaml")
    for mo in ((bd or {}).get("experience_board") or {}).get("moments") or [] if isinstance(bd, dict) else []:
        if isinstance(mo, dict) and mo.get("id") == ch["moment"]: return _s(mo.get("title")).split("：")[0].split(":")[0].strip() or None
    return find_target(ch.get("title"), tg) or _s(ch.get("title")) or None


def find_target(text, tg) -> str:
    """The canonical target named in `text` (the earliest alias; ties: the longest), or None."""
    best = None
    for a, c in tg:
        i = _s(text).find(a) if not a.isascii() else _s(text).lower().find(a.lower())
        if i >= 0 and (best is None or i < best[0]): best = (i, c)
    return best[1] if best else None


# ---------------------------------------------------------------- heuristic labels
LOGISTICS = re.compile(r"^(怎么样了|进度|好了吗|还没好吗|在吗|开始|开工|可以|继续|重启|退出了|开了|游戏开好了|先给我看|我先看一下|你可以开工)")


def heuristic_label(words) -> dict:
    """{kind, class, marker}: the first keyword rule with a hit (RULES); kind `other` when none. A reproducible baseline labeller (no model)."""
    w = _s(words)
    for kind, cls, pats in RULES:
        if any(p.lower() in w.lower() for p in pats):
            if kind != "unreadable_object" and cls != "bug" and re.search(r"[？?]$", w.strip()) and not re.search(r"为什么|能不能|呢", w): cls = "question"
            return {"kind": kind, "class": cls, "marker": bool(REPEAT_MARK.search(w))}
    return {"kind": "other", "class": "question" if re.search(r"[？?吗]", w) else "request", "marker": bool(REPEAT_MARK.search(w))}


def is_complaint(r) -> bool:
    """A record that asks for a change or exposed a defect (docs 7.2)."""
    return r.get("class") in ("bug", "taste", "request") or (r.get("class") == "question" and r.get("kind") not in (None, "", "other"))


# ---------------------------------------------------------------- records from the channels
def anchor_of(root, ev, vers=None) -> tuple:
    """(modality, source, milestone, anchor) of a thread event, from its context; modality None when it carries no anchor."""
    vers = versions(root) if vers is None else vers
    a, mod, src, m = {}, None, "chat", None
    for c in ev.get("context") or []:
        k = c.get("kind")
        if k == "video":
            m = _s(c.get("m")) or m; t = c.get("t")
            a["video"] = {"m": m, "t": float(t) if t is not None else None}
            ch = chapter_at(root, m, t)
            if ch: a["chapter"] = ch
            if c.get("frame"): a["frame"] = c["frame"]
            mod, src = "video_moment", "playtest"
        elif k == "region":
            m = _s(c.get("m")) or m
            a["image"] = f"5_build/{m}/play/{c.get('file')}" if c.get("file") and not _s(c.get("file")).startswith("5_build/") else c.get("file")
            if c.get("box"): a["region"] = [float(x) for x in c["box"]]
            mod, src = "image_region", "playtest"
        elif k == "file":
            p = _s(c.get("path"))
            if Path(p).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif", ".bmp"):
                a.setdefault("image", p); mod = mod or "image"; src = "picture" if src == "chat" else src
        elif k in ("moment", "check", "person"):
            a[k if k != "person" else "person"] = c.get("id")
            if mod is None: mod, src = "text", "verdict"
    if m is None: m = version_at(vers, ev.get("at"))
    return mod, src, m, a


def _new(root, recs, words, event=None, at=None, source="chat", milestone=None, modality="text", anchor=None, labels=None, by="resident", tg=None):
    lb = labels or {}
    r = {"id": _next_id(recs), "project": project_id(root), "created": at or now(), "event": event, "source": source,
         "milestone": milestone, "modality": modality, "anchor": anchor or {}, "words": words,
         "interpretation": None, "certainty": None, "class": lb.get("class"), "kind": lb.get("kind"),
         "scope": lb.get("scope") or (KINDS.get(lb.get("kind")) or (None,))[0], "status_item": None, "state": None,
         "repeat_of": [], "labelled_by": lb.get("labelled_by")}
    if lb.get("marker"): r["marker"] = True
    if lb.get("labelled_by") and (lb.get("class") or lb.get("kind")): put_label(r, lb["labelled_by"], lb.get("class"), lb.get("kind"), r["scope"], at=at or now())
    tg = tg if tg is not None else targets(root)
    tgt = (anchor or {}).get("target") or find_target(words, tg) or chapter_target(root, (anchor or {}).get("chapter"), tg)
    if tgt: r["anchor"]["target"] = tgt
    recs.append(r); _state(root, r, "new", by, at=at)
    log_event(root, "record_created", at=at, id=r["id"], m=milestone, source=source, modality=modality, cls=r["class"], kind=r["kind"],
              **({"backfill": True} if source == "backfill" else {}))
    return r


def capture(root, evs) -> list:
    """`gameanything chat read`: a `new` record for each of her (non-auto) words that carry an anchor and have no record yet. -> the new records."""
    want = [e for e in evs if e.get("from") == "user" and e.get("type") == "text" and not e.get("auto")]
    if not want: return []
    vers = versions(root); tg = targets(root)
    todo = []
    for e in want:
        mod, src, m, a = anchor_of(root, e, vers)
        if mod and (_s(e.get("text")).strip() or a.get("image")): todo.append((e, mod, src, m, a))
    if not todo: return []
    def fn(recs):
        have = {r.get("event") for r in recs}; out = []
        for e, mod, src, m, a in todo:
            if e["id"] in have: continue
            w = _s(e.get("text")).strip(); lb = heuristic_label(w) if w else {"kind": "other", "class": "question"}
            lb = {**lb, "scope": KINDS[lb["kind"]][0], "labelled_by": "heuristic"}          # a first guess; the resident's `feedback set` replaces it
            r = _new(root, recs, w, e["id"], e.get("at"), src, m, mod, a, labels=lb, by="chat-read", tg=tg)
            out.append(dict(r))
        return out
    return _edit(root, fn)


def add(root, words=None, event=None, milestone=None, interpretation=None, cls=None, kind=None, scope=None, certainty=None, target=None, by="resident") -> dict:
    """A record from a thread event (her words are taken from it) or, with no event, from `words` (her words in the terminal)."""
    from .conversation import Thread
    e = None
    if event:
        e = next((x for x in Thread(root).events() if x.get("id") == event), None)
        if e is None: raise FeedbackError(f"对话里没有事件 {event}")
        if e.get("from") != "user": raise FeedbackError(f"{event} 不是她说的话")
    w = words if words is not None else _s((e or {}).get("text")).strip()
    if not w: raise FeedbackError("没有她的原话：给 --event（对话事件）或 --words")
    if e is not None and words is not None and words not in _s(e.get("text")):
        raise FeedbackError("--words 必须是这条消息里她的原话的一段（一条消息说了两件事时分成两条记录，原文照抄）")
    mod, src, m, a = anchor_of(root, e) if e else (None, "chat", None, {})
    if target: a["target"] = target
    _check_labels(cls, kind, scope, certainty)
    def fn(recs):
        r = _new(root, recs, w, event, (e or {}).get("at"), src if mod else "chat", milestone or m, mod or "text", a, by=by,
                 labels={"class": cls, "kind": kind, "scope": scope, "labelled_by": "resident" if (cls or kind) else None})
        _apply(root, recs, r, interpretation, None, cls, kind, scope, certainty, by)
        return dict(r)
    return _edit(root, fn)


def _check_labels(cls, kind, scope, certainty):
    if cls is not None and cls not in CLASSES: raise FeedbackError(f"--class 要是 {' / '.join(CLASSES)}")
    if kind is not None and kind not in KINDS: raise FeedbackError(f"--kind 要是 {' / '.join(KINDS)}")
    if scope is not None and scope not in SCOPES: raise FeedbackError(f"--scope 要是 {' / '.join(SCOPES)}")
    if certainty is not None and certainty not in ("high", "low"): raise FeedbackError("--certainty 要是 high / low")


def _apply(root, recs, r, interpretation, interpretation_en, cls, kind, scope, certainty, by):
    if interpretation: r["interpretation"] = interpretation
    if interpretation_en: r["interpretation_en"] = interpretation_en
    if cls: r["class"] = cls
    if kind: r["kind"] = kind; r["scope"] = scope or r.get("scope") or KINDS[kind][0]
    if scope: r["scope"] = scope
    if certainty: r["certainty"] = certainty
    if cls or kind or scope or certainty:
        r["labelled_by"] = "resident" if by not in ("judge", "human", "heuristic") else by
        put_label(r, r["labelled_by"], r.get("class"), r.get("kind"), r.get("scope"), (r.get("anchor") or {}).get("target"), certainty=r.get("certainty"))
        log_event(root, "record_labels", id=r["id"], cls=r.get("class"), kind=r.get("kind"), scope=r.get("scope"), certainty=r.get("certainty"), labelled_by=r["labelled_by"])
    if r.get("state") in ("new", "reopened") and r.get("interpretation") and r.get("class"):
        _state(root, r, "confirming" if r.get("certainty") == "low" else "interpreted", by)
    if is_complaint(r) and r.get("kind") and r.get("milestone"): _mark_repeat(root, recs, r)


def _mark_repeat(root, recs, r):
    """r's earlier records of the same kind (and target) on an earlier version: r is a repeat; a fixed / closed earlier one reopens."""
    order = {v["m"]: i for i, v in enumerate(versions(root))}
    me = order.get(r["milestone"])
    if me is None or r.get("kind") == "other": return
    tgt = (r.get("anchor") or {}).get("target")
    olds = [x for x in recs if x is not r and is_complaint(x) and x.get("kind") == r["kind"] and order.get(x.get("milestone"), 1e9) < me
            and (not tgt or not (x.get("anchor") or {}).get("target") or (x.get("anchor") or {}).get("target") == tgt)]
    r["repeat_of"] = [x["id"] for x in olds]
    for x in olds:
        if x.get("state") in ("fixed", "verifying", "closed"): _state(root, x, "reopened", "repeat")


def set_fields(root, rid, interpretation=None, interpretation_en=None, cls=None, kind=None, scope=None, certainty=None, target=None, state=None, by="resident") -> dict:
    _check_labels(cls, kind, scope, certainty)
    if state is not None and state not in STATES: raise FeedbackError(f"--state 要是 {' / '.join(STATES)}")
    def fn(recs):
        r = get(recs, rid)
        if target: r.setdefault("anchor", {})["target"] = target
        _apply(root, recs, r, interpretation, interpretation_en, cls, kind, scope, certainty, by)
        if state: _state(root, r, state, by)
        return dict(r)
    return _edit(root, fn)


def confirm(root, rid, outcome, interpretation=None, event=None, card=None) -> dict:
    """Her answer on the confirm card: `confirmed` (the reading was right) or `corrected` (with the new reading; the old one stays in history)."""
    if outcome not in ("confirmed", "corrected"): raise FeedbackError("--as 要是 confirmed / corrected")
    if outcome == "corrected" and not interpretation: raise FeedbackError("corrected 要给 --interpretation（改正后的理解）")
    def fn(recs):
        r = get(recs, rid); old = r.get("interpretation")
        r["confirm"] = {"card": card or (r.get("confirm") or {}).get("card"), "state": outcome, "at": now(), "event": event}
        if outcome == "corrected": r.setdefault("history", []).append({"at": now(), "interpretation_was": old, "by": "her"}); r["interpretation"] = interpretation
        if r.get("state") in ("new", "confirming"): _state(root, r, "interpreted", "her")
        log_event(root, "confirm", id=rid, card=r["confirm"]["card"], outcome=outcome)
        return dict(r)
    return _edit(root, fn)


def link(root, rid, item=None, new_item=None, text_en=None) -> dict:
    """The STATUS item the record became (an existing id, or a new one from --new-item with source feedback:<event>)."""
    from . import devstatus
    if not item and not new_item: raise FeedbackError("要 --item rN 或 --new-item \"…\"")
    recs = load(root); r = get(recs, rid)
    if new_item: item = devstatus.set_item(root, None, "todo", new_item, source=f"feedback:{r.get('event')}" if r.get("event") else f"feedback:{rid}", text_en=text_en)["item"]["id"]
    else:
        d, _ = devstatus.load(root)
        if not any(x.get("id") == item for x in d["items"]): raise FeedbackError(f"STATUS 里没有条目 {item}")
    def fn(recs):
        r = get(recs, rid); r["status_item"] = item
        if r.get("state") in ("new", "interpreted", "reopened"): _state(root, r, "open", "resident")
        return dict(r)
    return _edit(root, fn)


def on_item(root, item, state, build=None, by=None, evidence=None):
    """devstatus.set_item changed item `item`: linked records follow (done -> fixed with the resolution; partial -> in_progress). Never raises."""
    if not path(root).exists(): return []
    try:
        def fn(recs):
            out = []
            for r in recs:
                if r.get("status_item") != item or r.get("state") in TERMINAL: continue
                if state == "done" and r.get("state") not in ("fixed", "verifying"):
                    r["resolution"] = {"m": build, "what": evidence, "by": by, "at": now()}; _state(root, r, "fixed", by or "builder"); out.append(r["id"])
                elif state == "partial" and r.get("state") in ("open", "reopened", "interpreted"): _state(root, r, "in_progress", by or "builder"); out.append(r["id"])
                elif state in ("broken", "regressed") and r.get("state") in ("fixed", "verifying"): _state(root, r, "reopened", by or "playtester"); out.append(r["id"])
            return out
        return _edit(root, fn)
    except (FeedbackError, OSError): return []


def verdict(root, rid, ok, event=None) -> dict:
    """Her word on the before / after pair: ok closes the record, not ok reopens it."""
    def fn(recs):
        r = get(recs, rid); m = (r.get("verification") or {}).get("m") or (r.get("resolution") or {}).get("m")
        r["her_verdict"] = {"verdict": "ok" if ok else "not_ok", "at": now(), "event": event, "m": m}
        _state(root, r, "closed" if ok else "reopened", "her")
        log_event(root, "verdict", id=rid, m=m, verdict=r["her_verdict"]["verdict"])
        return dict(r)
    return _edit(root, fn)


def accept(root, m, how="explicit"):
    log_event(root, "accepted", m=m, how=how); return {"m": m, "how": how}


# ---------------------------------------------------------------- evaluation conditions (docs 7.6, 7.8): blind, alternating, per version
SCHEDULE = "abba-C1C4-v1"            # the assignment rule; a new rule gets a new name (old assignments keep theirs)
ARMS = ("C1", "C4")
USES = {"profile": ("C2", "C3", "C4"), "critic": ("C3", "C4"), "verify": ("C4",), "brief_kinds": ("C4",), "lessons": ("C1", "C2", "C3", "C4")}


def scheduled(project, index) -> str:
    """The arm of a project's index-th version (0-based, in the order versions get their first build) under SCHEDULE: blocks A B B A
    (A A B B … would confound with learning), the first arm per project from sha256(project id + schedule) so half the projects start
    with each. Pure function: the assignment can be recomputed from the project id and the version order."""
    import hashlib
    flip = int(hashlib.sha256(f"{project}:{SCHEDULE}".encode()).hexdigest(), 16) % 2
    a, b = ARMS if not flip else ARMS[::-1]
    return a if index % 4 in (0, 3) else b


def assignments(root) -> dict:
    """{m: the condition event that fixed version m's condition} (the first one per version wins; later ones are ignored)."""
    out = {}
    for e in events(root, "condition"):
        if e.get("m") and e.get("name") in CONDITIONS: out.setdefault(str(e["m"]), e)
    return out


def assign(root, m) -> str:
    """Version m's condition, fixed once and logged (`condition` event {m, name, how, schedule, index, seed_of}): an earlier assignment of m,
    else a project-wide manual setting (`feedback condition --set C4`, for a project outside the study), else the blind schedule. Called by
    agentd at build start and by the builder's brief (a build agentd did not start), so every built version is assigned exactly once;
    everything else only peeks (deliver, the result card, the critic, datacheck) and never assigns. Study mode off: C4, nothing logged."""
    from . import study
    if not study.on(root): return "C4"
    m = str(m); got = assignments(root)
    if m in got: return got[m]["name"]
    man = [e for e in events(root, "condition") if not e.get("m") and e.get("name") in CONDITIONS]
    if man: name, how, idx = man[-1]["name"], "manual_project", None
    else: idx = len(got); name, how = scheduled(project_id(root), idx), "schedule"
    log_event(root, "condition", m=m, name=name, how=how, schedule=SCHEDULE if how == "schedule" else None, index=idx, project=project_id(root))
    return name


def condition(root, name=None, m=None):
    """Set (name; with m: only that version, before it is assigned) or read the condition. Read with m = assign(root, m); without m = the
    project-wide manual setting, else C4. For the coordinator and the code only: never shown to her (UI, chat, cards). Study mode off: C4
    (setting one is refused)."""
    from . import study
    if not study.on(root):
        if name: raise FeedbackError("研究模式没开（gameanything project set-study <项目> on）：不分条件，每一版都跑完整的流程")
        return "C4"
    if name:
        if name not in CONDITIONS: raise FeedbackError(f"条件要是 {' / '.join(CONDITIONS)}")
        if m and str(m) in assignments(root): raise FeedbackError(f"{m} 的条件已经定了（{assignments(root)[str(m)]['name']}）：一个版本只定一次")
        log_event(root, "condition", name=name, m=str(m) if m else None, how="manual"); return name
    if m: return assign(root, m)
    c = [e for e in events(root, "condition") if not e.get("m") and e.get("name") in CONDITIONS]
    return c[-1]["name"] if c else "C4"


def peek(root, m) -> str:
    """Version m's condition WITHOUT assigning one: its assignment, else the project-wide manual setting, else C4 (what every version
    built before the schedule existed ran under). Only build start (agentd) and the builder's brief assign (assign). Study mode off: C4,
    whatever was assigned while it was on (nothing is withheld from her)."""
    from . import study
    if not study.on(root): return "C4"
    got = assignments(root).get(str(m)) if m else None
    return got["name"] if got else condition(root)


def uses(root, m, part) -> bool:
    """Does version m's condition include this part of the loop (profile / critic / verify / brief_kinds / lessons)? Never assigns."""
    return peek(root, m) in USES[part]


# ---------------------------------------------------------------- verification at the same anchor
def _rel(root, p) -> str:
    p = Path(p); root = Path(root).resolve()
    try: return (p if p.is_absolute() else (root / p)).resolve().relative_to(root).as_posix()
    except ValueError: raise FeedbackError(f"{p} 不在项目里：复拍的画面放进 5_build/<m>/play/verify/")


def _before(r):
    a = r.get("anchor") or {}
    return a.get("frame") or a.get("image")


def to_verify(root, m, recs=None) -> list:
    """The records fixed in version m (resolution.m == m) whose anchor has a picture: they need a same-anchor pair."""
    recs = load(root) if recs is None else recs
    return [r for r in recs if (r.get("resolution") or {}).get("m") == m and r.get("state") in ("fixed", "verifying", "closed") and is_complaint(r)]


def verify(root, rid, m, after=None, method="reshoot") -> dict:
    """Register the after picture of a record in version m (the builder re-shot the anchor) and make the pair."""
    if method not in METHODS: raise FeedbackError(f"--method 要是 {' / '.join(METHODS)}")
    rel = _rel(root, after) if after else None
    if rel and not (Path(root) / rel).is_file(): raise FeedbackError(f"没有这个文件：{rel}")
    def fn(recs):
        r = get(recs, rid); v = {"m": m, "before": _before(r), "after": rel, "method": method if rel else "listed", "at": now()}
        if rel and v["before"]:
            try: v["pair"] = make_pair(root, v["before"], rel, Path(root) / "5_build" / m / "play" / "verify" / f"{rid}_pair.png", (r.get("anchor") or {}).get("region"), m)
            except Exception as x: v["pair_error"] = f"{type(x).__name__}: {x}"
        r["verification"] = v
        if rel and r.get("state") == "fixed": _state(root, r, "verifying", "builder")
        log_event(root, "verify", id=rid, m=m, method=v["method"])
        return dict(r)
    return _edit(root, fn)


def make_pair(root, before, after, out: Path, region=None, m=""):
    """before | after side by side at one height, the region box drawn on both; -> project-relative path of the pair."""
    from PIL import Image, ImageDraw
    root = Path(root); H = 480
    def load_img(p):
        im = Image.open(root / p).convert("RGB"); return im.resize((max(1, round(im.width * H / im.height)), H))
    a, b = load_img(before), load_img(after)
    gap = 12; im = Image.new("RGB", (a.width + b.width + gap, H + 28), (245, 245, 245))
    im.paste(a, (0, 28)); im.paste(b, (a.width + gap, 28))
    d = ImageDraw.Draw(im); d.text((6, 7), "before", fill=(90, 90, 90)); d.text((a.width + gap + 6, 7), f"after {m}".strip(), fill=(20, 110, 60))
    if region and len(region) == 4:
        for x0, w in ((0, a.width), (a.width + gap, b.width)):
            d.rectangle([x0 + region[0] * w, 28 + region[1] * H, x0 + region[2] * w, 28 + region[3] * H], outline=(230, 60, 40), width=3)
    out.parent.mkdir(parents=True, exist_ok=True); im.save(out)
    return out.resolve().relative_to(root.resolve()).as_posix()


def frame_at(video: Path, t: float, out: Path) -> bool:
    """The first frame at or after t seconds of a video (PyAV) saved as PNG. -> written?"""
    try:
        import av
        with av.open(str(video)) as c:
            s = c.streams.video[0]
            c.seek(int(max(0.0, t) / s.time_base), stream=s, any_frame=False, backward=True)
            for f in c.decode(s):
                if f.time is not None and f.time + 1e-3 < t: continue
                out.parent.mkdir(parents=True, exist_ok=True); f.to_image().save(out); return True
    except Exception: return False
    return False


def _offset_t(root, r, m):
    """chapter_offset: the anchor's chapter (not `full`) in the new version's play.yaml -> the mapped second, or None."""
    from .delivery import load_play, find_video
    a = r.get("anchor") or {}; ch = a.get("chapter") or {}; v = a.get("video") or {}
    if not ch or ch.get("moment") in (None, "", "full") or v.get("t") is None: return None, None
    play = Path(root) / "5_build" / m / "play"; d = load_play(play); chs = d.get("chapters") or []
    i = next((k for k, c in enumerate(chs) if c["moment"] == ch["moment"]), None)
    vid = find_video(play, d.get("video"))
    if i is None or not vid: return None, None
    end = chs[i + 1]["t"] if i + 1 < len(chs) else None
    t = chs[i]["t"] + max(0.0, float(v["t"]) - float(ch.get("t") or 0))
    if end is not None: t = min(t, max(chs[i]["t"], end - 0.5))
    return t, play / vid


def pairs(root, m, auto=True) -> list:
    """Every record to verify in version m: the builder's re-shot pair, else (auto) a chapter-offset frame of the new video, else listed.
    Writes 5_build/<m>/play/verify.yaml. -> [{id, words, before, after, pair, method}]."""
    root = Path(root); out = []
    for r in to_verify(root, m):
        v = r.get("verification") or {}
        if v.get("m") == m and v.get("after"):
            if not v.get("pair") and v.get("before"): r = verify(root, r["id"], m, v["after"], v.get("method") or "reshoot"); v = r["verification"]
        elif auto and _before(r):
            t, vid = _offset_t(root, r, m)
            f = root / "5_build" / m / "play" / "verify" / f"{r['id']}_after.png"
            if t is not None and frame_at(vid, t, f): r = verify(root, r["id"], m, f, "chapter_offset"); v = r["verification"]
            else: v = {"m": m, "before": _before(r), "after": None, "method": "listed"}
        else: v = {"m": m, "before": _before(r), "after": None, "method": "listed"}
        out.append({"id": r["id"], "words": r.get("words"), "interpretation": r.get("interpretation"), "before": v.get("before"), "after": v.get("after"),
                    "pair": v.get("pair"), "method": v.get("method") or "listed", "anchor": r.get("anchor") or {}})
    if out:
        f = root / "5_build" / m / "play" / "verify.yaml"; f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("# 同一画面复拍（gameanything feedback pairs / build deliver 写的；docs/feedback-loop.md 1.6）：她在上一版指出的地方，这一版同一个画面的改前 / 改后\n"
                     + yaml.safe_dump({"milestone": m, "pairs": out}, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
    return out


def unverified(root, m) -> list:
    """Records fixed in m without an after picture (what `build check` / `deliver` warn about); none when m's condition has no verification."""
    if not uses(root, m, "verify"): return []
    return [r for r in to_verify(root, m) if not ((r.get("verification") or {}).get("m") == m and (r.get("verification") or {}).get("after"))]


def on_deliver(root, m) -> list:
    """`gameanything build deliver`: make the pairs, log `delivered`; -> [(mark, line)] for its report (the builder's, never hers). Never raises."""
    try:
        lines = []
        if uses(root, m, "critic"):
            c = _y(Path(root) / "5_build" / str(m) / "critic.yaml")
            if not (isinstance(c, dict) and c.get("collected")):
                lines.append(("warn", f"交付前的预评还没做：gameanything feedback critic --project <P> --m {m} --emit，答完 --collect（p ≥ 0.5 的修一轮再交付）"))
        if not uses(root, m, "verify"):                 # this version's condition has no same-anchor step: logged, nothing said (blind)
            log_event(root, "delivered", m=m, records_to_verify=len(to_verify(root, m)), pairs=None, verify_step=False); return lines
        ps = pairs(root, m)
        by = {k: sum(1 for p in ps if p["method"] == k) for k in METHODS}
        log_event(root, "delivered", m=m, records_to_verify=len(ps), pairs=by, verify_step=True)
        if not ps: return lines
        lines.append(("ok", f"同一画面复拍：{len(ps) - by['listed']}/{len(ps)} 条她的意见有改前 / 改后（5_build/{m}/play/verify.yaml）"))
        if by["listed"]:
            ids = ", ".join(p["id"] for p in ps if p["method"] == "listed")
            lines.append(("warn", f"{by['listed']} 条她的意见没有在同一个画面复拍：{ids}（把镜头放回原来的位置截图，gameanything feedback verify --project <P> --id … --m {m} --after …）"))
        return lines
    except Exception as x: return [("warn", f"同一画面复拍没做成：{type(x).__name__}: {x}")]


# ---------------------------------------------------------------- cards
def _url(root, p):
    p = _s(p)
    if p.startswith("conversation/files/"): return "/conv/" + p[len("conversation/files/"):]
    return "/media/" + p if p else None


def card(root, what, m=None, ids=None) -> dict:
    """what = confirm: a questions card for uncertain readings (the anchor frame as the picture); verify: her ok on each before / after pair."""
    recs = load(root)
    if what == "confirm":
        rs = [get(recs, i) for i in ids] if ids else [r for r in recs if r.get("state") == "confirming"]
        if not rs: raise FeedbackError("没有要确认的记录（certainty low 的 confirming 记录，或给 --ids）")
        items, items_en = [], []
        for n, r in enumerate(rs, 1):
            it = {"n": n, "text": f"你说「{r['words']}」，我理解成：{r.get('interpretation') or '（还没写理解）'}。对吗？不对的话是指什么？"}
            u = _url(root, _before(r))
            if u and (u.startswith("/conv/") or layout.media_file(root, u)): it["image"] = u
            items.append(it); items_en.append({"n": n, "text": f"You said “{r['words']}”; I read it as: {r.get('interpretation_en') or r.get('interpretation') or '-'}. Right? If not, what do you mean?"})
        key = "fbc-" + "-".join(r["id"] for r in rs)
        return {"kind": "questions", "key": key, "title": "我理解得对吗？（改之前先确认）", "items": items,
                "en": {"title": "Did I understand you? (before anything changes)", "items": items_en}}
    if what == "verify":
        if not m: raise FeedbackError("verify 卡要 --m")
        ps = [p for p in pairs(root, m, auto=False) if p.get("pair")]
        if not ps: raise FeedbackError(f"{m} 还没有改前 / 改后的对比图（gameanything feedback pairs --m {m}）")
        items = [{"n": i, "text": f"「{p['words']}」：左边是改之前，右边是这一版同一个画面。这样可以了吗？", "image": "/media/" + p["pair"]} for i, p in enumerate(ps, 1)]
        en = [{"n": i, "text": f"“{p['words']}”: left before, right this version at the same view. Is it right now?"} for i, p in enumerate(ps, 1)]
        return {"kind": "questions", "key": f"verify-{m}", "title": f"你上一版指出的地方，{m} 改好了吗？", "items": items,
                "en": {"title": f"The places you pointed at: fixed in {m}?", "items": en}}
    raise FeedbackError("what 要是 confirm / verify")


# ---------------------------------------------------------------- repeats and metrics
def repeats(recs, order, key=None) -> dict:
    """{id: {"strict": [...], "loose": [...]}} for every complaint: earlier complaints of the same kind (strict: and the same target).
    `key(r)` = the unit a record belongs to (default its version, `milestone`); `order` = unit -> position."""
    key = key or (lambda r: r.get("milestone"))
    out = {}
    cs = [r for r in recs if is_complaint(r) and r.get("kind") and r.get("kind") != "other" and order.get(key(r)) is not None]
    for r in cs:
        i = order[key(r)]; tg = (r.get("anchor") or {}).get("target")
        older = [x for x in cs if x is not r and x["kind"] == r["kind"] and order[key(x)] < i]
        out[r["id"]] = {"loose": [x["id"] for x in older], "strict": [x["id"] for x in older if tg and (x.get("anchor") or {}).get("target") == tg]}
    return out


def deliveries(root, evs=None) -> list:
    """Every delivery in time order: each `result` card of a version is one ([{d: "p3#2", m, at}]); a version re-delivered three times
    (SD 第 3 期 · 电影版 2 / 3 / 4) counts three times. Versions with no result card count once, at their version time."""
    from .conversation import Thread
    root = Path(root); evs = Thread(root).events() if evs is None else evs; vers = versions(root, evs)
    wp = _y(root / layout.DESIGN / "world_plan.yaml"); ms = ((wp or {}).get("world_plan") or {}).get("milestones") if isinstance(wp, dict) else None
    ms = ms if isinstance(ms, dict) else {}; keys = [v["m"] for v in vers]; out = []; n = {}
    for e in evs:
        c = e.get("card") or {}
        if e.get("type") == "card" and c.get("kind") == "result" and c.get("milestone"):
            k = _ms_key(str(c["milestone"]), keys, ms)
            if k: n[k] = n.get(k, 0) + 1; out.append({"d": f"{k}#{n[k]}", "m": k, "at": e.get("at")})
    out += [{"d": f"{v['m']}#1", "m": v["m"], "at": v["at"]} for v in vers if v["m"] not in n]
    return sorted(out, key=lambda x: x["at"] or "9999")


def delivery_of(r, dels):
    """The delivery a record is about: the newest delivery of its version at or before it (else the version's first delivery)."""
    mine = [d for d in dels if d["m"] == r.get("milestone")]
    if not mine: return None
    before = [d for d in mine if d["at"] and r.get("created") and d["at"] <= r["created"]]
    return (before[-1] if before else mine[0])["d"]


def _rate(k, n): return {"k": k, "n": n, "rate": (k / n) if n else None}


def metrics(root, recs=None) -> dict:
    """Every metric of docs/feedback-loop.md 7.3 that the records and the log can give now."""
    root = Path(root); recs = load(root) if recs is None else recs
    vers = versions(root); order = {v["m"]: i for i, v in enumerate(vers)}
    C = [r for r in recs if is_complaint(r)]
    first = min((order[r["milestone"]] for r in C if r.get("milestone") in order), default=None)
    rp = repeats(recs, order)
    elig = [r for r in C if r.get("milestone") in order and first is not None and order[r["milestone"]] > first]
    rs = sum(1 for r in elig if rp.get(r["id"], {}).get("strict")); rl = sum(1 for r in elig if rp.get(r["id"], {}).get("loose"))
    per = []
    for v in vers:
        cv = [r for r in C if r.get("milestone") == v["m"]]
        if not cv and not any(r.get("milestone") == v["m"] for r in recs): continue
        per.append({"m": v["m"], "at": v["at"], "complaints": len(cv), "by_class": {c: sum(1 for r in cv if r.get("class") == c) for c in CLASSES},
                    "repeats_strict": sum(1 for r in cv if rp.get(r["id"], {}).get("strict")), "repeats_loose": sum(1 for r in cv if rp.get(r["id"], {}).get("loose"))})
    cnt = lambda key, keys: {k: sum(1 for r in recs if r.get(key) == k) for k in keys}
    acc = [e for e in events(root, "accepted")]
    rounds = None
    if acc and vers:
        am = acc[0].get("m"); rounds = {"accepted": am, "rounds": order[am] + 1 if am in order else None}
    fixed = [r for r in recs if r.get("resolution")]
    ver = [r for r in fixed if (r.get("verification") or {}).get("after")]
    dels = deliveries(root); dorder = {d["d"]: i for i, d in enumerate(dels)}; dk = {r.get("id"): delivery_of(r, dels) for r in recs}
    drp = repeats(recs, dorder, lambda r: dk.get(r.get("id")))
    dfirst = min((dorder[dk[r["id"]]] for r in C if dk.get(r.get("id")) in dorder), default=None)
    delig = [r for r in C if dk.get(r.get("id")) in dorder and dfirst is not None and dorder[dk[r["id"]]] > dfirst]
    by_del = {"deliveries": len(dels), "rfr_strict": _rate(sum(1 for r in delig if drp.get(r["id"], {}).get("strict")), len(delig)),
              "rfr_loose": _rate(sum(1 for r in delig if drp.get(r["id"], {}).get("loose")), len(delig))}
    hv = [r.get("her_verdict", {}).get("verdict") for r in recs if r.get("her_verdict")]
    conf = [(r.get("confirm") or {}).get("state") for r in recs if r.get("confirm")]
    return {"records": len(recs), "complaints": len(C), "by_class": cnt("class", CLASSES), "by_state": cnt("state", STATES),
            "by_kind": {k: n for k in KINDS for n in [sum(1 for r in C if r.get("kind") == k)] if n},
            "by_modality": cnt("modality", MODALITIES), "versions": per,
            "rfr_strict": _rate(rs, len(elig)), "rfr_loose": _rate(rl, len(elig)), "by_delivery": by_del, "rounds_to_accept": rounds,
            "verification": {"fixed": len(fixed), "paired": len(ver), "by_method": {k: sum(1 for r in ver if r["verification"].get("method") == k) for k in METHODS},
                             "her_ok": hv.count("ok"), "her_not_ok": hv.count("not_ok")},
            "interpretation": {"confirmed": conf.count("confirmed"), "corrected": conf.count("corrected")},
            "rule_hits": rule_hits(root, recs, order), "repeats": rp}          # never the condition: she must not see it (blind, docs 7.8)


def rule_hits(root, recs, order) -> dict:
    """M4: retrieved entries whose kind was complained about before, and the share with no complaint of that kind on the build's version."""
    C = [r for r in recs if is_complaint(r) and r.get("milestone") in order]
    latest = max(order.values()) if order else -1
    ret = app = hit = 0
    for e in events(root, "retrieval"):
        m = e.get("m"); i = order.get(m)
        for x in e.get("entries") or []:
            ret += 1; k = x.get("kind")
            if not k or k == "other" or i is None: continue
            if not any(r["kind"] == k and order[r["milestone"]] < i for r in C): continue
            if i == latest and not any(r.get("milestone") == m for r in recs): continue      # her feedback on that version is not in yet
            app += 1; hit += not any(r["kind"] == k and r["milestone"] == m for r in C)
    return {"retrieved": ret, "applicable": app, "hits": hit, "rate": (hit / app) if app else None}


# ---------------------------------------------------------------- backfill
TIME_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")


def backup(root, why="backfill") -> Path:
    """A copy of feedback/ before a bulk write (feedback/backups/<why>-<time>/; frames/ and older backups are not copied: nothing bulk writes them)."""
    src = Path(root) / layout.FEEDBACK; dst = src / "backups" / f"{why}-{datetime.now():%Y%m%dT%H%M%S}"
    if not src.is_dir(): return None
    shutil.copytree(src, dst, ignore=lambda d, names: [n for n in names if Path(d) == src and n in ("frames", "backups")] + [n for n in names if n.endswith(".lock")])
    return dst


def backfill(root, dry_run=False, make_backup=True) -> dict:
    """Records rebuilt from an existing project's history: her words in the thread (anchored ones always; plain text when the keyword
    labeller sees a complaint), labels from heuristic_label, links to STATUS items (feedback:<event> sources, m:ss times in item texts),
    resolution from the item's state, repeats. Safe on a LIVE project: merge-only and idempotent. An event that already has a record (made by
    `chat read`, the resident or an earlier backfill) is never recorded again and existing records are never changed (her confirmations,
    verdicts, the resident's readings stay as they are); feedback/ is backed up first. -> counts."""
    from .conversation import Thread
    from . import devstatus
    root = Path(root); evs = Thread(root).events(); vers = versions(root, evs); tg = targets(root)
    st, _ = devstatus.load(root)
    cand, skipped = [], []
    for e in evs:
        if e.get("from") != "user" or e.get("type") != "text" or e.get("auto"): continue
        w = _s(e.get("text")).strip()
        mod, src, m, a = anchor_of(root, e, vers)
        lb = heuristic_label(w)
        if not w or (not mod and (lb["kind"] == "other" or LOGISTICS.match(w))) or w.startswith("（来自"): skipped.append(e["id"]); continue
        cand.append((e, w, mod, src, m, a, lb))
    have0 = {r.get("event") for r in load(root) if r.get("event")}
    todo0 = [c for c in cand if c[0]["id"] not in have0]
    if dry_run: return {"would_add": len(todo0), "existing": len(load(root)), "already_recorded": len(cand) - len(todo0), "skipped_not_feedback": len(skipped)}
    bk = backup(root) if make_backup and todo0 and path(root).parent.is_dir() else None
    run = f"bf{datetime.now():%Y%m%dT%H%M%S}"
    def fn(recs):
        have = {r.get("event") for r in recs if r.get("event")}; new = []
        for e, w, mod, src, m, a, lb in cand:
            if e["id"] in have: continue
            lb = {**lb, "scope": KINDS[lb["kind"]][0], "labelled_by": "heuristic"}
            r = _new(root, recs, w, e["id"], e.get("at"), "backfill", m, mod or "text", dict(a), labels=lb, by="backfill", tg=tg)
            r["backfill_channel"] = src; r["backfill_run"] = run; new.append(r); have.add(e["id"])
        _link_status(root, new, st, tg)
        order = {v["m"]: i for i, v in enumerate(vers)}; rp = repeats(recs, order)
        for r in new: r["repeat_of"] = rp.get(r["id"], {}).get("strict") or []
        return [r["id"] for r in new]
    added = _edit(root, fn) if todo0 else []
    log_event(root, "backfill", run=run, added=len(added), ids=added, already_recorded=len(cand) - len(added), skipped_not_feedback=len(skipped),
              backup=bk.relative_to(root).as_posix() if bk else None)
    recs = load(root); m = metrics(root, recs)
    return {"added": len(added), "ids": added, "already_recorded": len(cand) - len(added), "records": len(recs), "skipped_not_feedback": len(skipped),
            "backup": str(bk) if bk else None, "by_class": m["by_class"], "by_kind": m["by_kind"], "by_modality": m["by_modality"],
            "complaints": m["complaints"], "rfr_strict": m["rfr_strict"], "rfr_loose": m["rfr_loose"], "versions": m["versions"], "by_delivery": m["by_delivery"],
            "linked": sum(1 for r in recs if r.get("status_item")), "fixed": sum(1 for r in recs if r.get("state") == "fixed")}


def _link_status(root, recs, st, tg):
    by_ev = {r.get("event"): r for r in recs}
    for it in st["items"]:
        src = _s(it.get("source")); hit = []
        if src.startswith("feedback:") and src[9:] in by_ev: hit.append(by_ev[src[9:]])
        for mm, ss in TIME_RE.findall(_s(it.get("text"))):
            t = int(mm) * 60 + int(ss)
            c = [r for r in recs if (r.get("anchor") or {}).get("video", {}).get("t") is not None and abs(r["anchor"]["video"]["t"] - t) <= 2]
            if it.get("since"): c = [r for r in c if _s(r.get("milestone")) != _s(it["since"]) or len(c) == 1]
            hit += [r for r in c if r not in hit]
        for r in hit:
            if r.get("status_item"): continue
            r["status_item"] = it["id"]
            if not (r.get("anchor") or {}).get("target"):
                t_ = find_target(it.get("text"), tg)
                if t_: r["anchor"]["target"] = t_
            s = it.get("state")
            if s == "done": r["resolution"] = {"m": it.get("since"), "what": it.get("evidence"), "by": it.get("verified_by")}; _state(root, r, "fixed", "backfill", at=r["created"])
            elif s == "partial": _state(root, r, "in_progress", "backfill", at=r["created"])
            else: _state(root, r, "open", "backfill", at=r["created"])


# ---------------------------------------------------------------- labelling sheets (LLM judge / human check, docs 7.4)
def _need_study(root, what):
    from . import study
    if not study.on(root): raise FeedbackError(f"研究模式没开（gameanything project set-study <项目> on）：{what}只在做研究时用")


def label_export(root, out=None) -> Path:
    _need_study(root, "标注表")
    recs = load(root); f = Path(out) if out else Path(root) / layout.FEEDBACK / "labels" / f"{datetime.now():%Y-%m-%d}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "w", encoding="utf-8") as h:
        for r in recs:
            h.write(json.dumps({"id": r["id"], "words": r.get("words"), "milestone": r.get("milestone"), "target": (r.get("anchor") or {}).get("target"),
                                "chapter": ((r.get("anchor") or {}).get("chapter") or {}).get("title"), "class": None, "kind": None, "labeller": None},
                               ensure_ascii=False) + "\n")
    return f


def label_import(root, f, labeller="judge", name=None, apply=False) -> int:
    """Merge a labelling sheet (one JSON line per record: id, class, kind, target, scope?, explanation?) as labeller `judge` or `human`
    (`name`: who, e.g. human:anna). The labels are kept next to the others (r["labels"]); the live class / kind change only with apply."""
    _need_study(root, "标注表")
    if labeller not in ("judge", "human"): raise FeedbackError("--labeller 要是 judge / human")
    who = f"{labeller}:{name}" if name else labeller
    rows = [json.loads(x) for x in Path(f).read_text(encoding="utf-8").splitlines() if x.strip()]
    def fn(recs):
        n = 0
        for x in rows:
            r = next((y for y in recs if y.get("id") == x.get("id")), None)
            if r is None or not (x.get("class") or x.get("kind")): continue
            _check_labels(x.get("class"), x.get("kind"), x.get("scope"), None)
            put_label(r, who, x.get("class"), x.get("kind"), x.get("scope"), x.get("target"), explanation=x.get("explanation"), sheet=Path(f).name)
            log_event(root, "record_labels", id=r["id"], cls=x.get("class"), kind=x.get("kind"), scope=x.get("scope"), target=x.get("target"), labelled_by=who, live=bool(apply))
            if apply:
                _apply(root, recs, r, None, None, x.get("class"), x.get("kind"), x.get("scope"), None, labeller)
                if x.get("target"): r.setdefault("anchor", {})["target"] = x["target"]
            n += 1
        return n
    return _edit(root, fn)


# ---------------------------------------------------------------- retrieval (outer loop seam)
def brief(root, role="builder", budget=12, m=None, log=True) -> dict:
    """What a build starts with, within `budget` entries (docs 2.3): her applicable preferences, this project's repeat-prone kinds, the anchors
    to re-shoot, matching confirmed lessons. Obeys the evaluation condition; logs a `retrieval` event. -> {lines, entries}."""
    from . import lessons as L, profile, projects
    root = Path(root); cfg = projects.config_of(root) or {}
    game = projects.game_of(root); kind = cfg.get("kind") or "memory"
    m = m or os.environ.get("GAMEANYTHING_BUILD_M") or None; cond = condition(root, m=m)
    recs = load(root)
    lines, entries = [], []
    def room(): return len(entries) < budget
    if cond in ("C2", "C3", "C4"):
        for p in profile.applicable(profile.owner_of(root), kind, game, project_id(root))[:4]:
            if not room(): break
            lines.append(f"[她的偏好 {p['id']}] {p['text']}"); entries.append({"type": "preference", "id": p["id"], "kind": p.get("kind")})
    if cond == "C4":
        C = [r for r in recs if is_complaint(r) and r.get("kind") not in (None, "other")]
        byk = {}
        for r in C: byk.setdefault(r["kind"], []).append(r)
        for k, rs in sorted(byk.items(), key=lambda kv: -len(kv[1]))[:3]:
            if not room(): break
            tg = sorted({(r.get("anchor") or {}).get("target") for r in rs if (r.get("anchor") or {}).get("target")})
            lines.append(f"[她已经说过 {len(rs)} 次] {KINDS[k][1]}" + (f"（{'、'.join(tg[:4])}）" if tg else "") + f"：{'；'.join('「' + _s(r['words'])[:40] + '」' for r in rs[-2:])}")
            entries.append({"type": "kind", "id": k, "kind": k})
        todo = [r for r in recs if r.get("state") in ("open", "in_progress", "reopened", "fixed") and _before(r)]
        if todo and room():
            lines.append(f"[同一画面复拍] 这一版做完要在这些地方复拍改后的画面：{', '.join(r['id'] + (' ' + _s((r.get('anchor') or {}).get('target')) if (r.get('anchor') or {}).get('target') else '') for r in todo[:8])}"
                         f"（gameanything feedback pairs --project \"$P\" --m <m> --todo）")
            entries.append({"type": "verify", "id": ",".join(r["id"] for r in todo[:8]), "kind": None})
    if cond != "C0":
        open_kinds = {r.get("kind") for r in recs if r.get("state") not in TERMINAL}
        for e in L.show(game, role if role in L.ROLES else "builder"):
            if not room(): break
            if e.get("status") != "confirmed": continue
            k = heuristic_label(_s(e.get("现象")) + " " + _s(e.get("做法")))["kind"]
            if cond == "C4" and k not in open_kinds: continue
            lines.append(f"[经验 {e.get('id')}] {_s(e.get('现象'))} → {_s(e.get('做法'))}"); entries.append({"type": "lesson", "id": e.get("id"), "kind": k})
    if log:
        log_event(root, "retrieval", m=m, role=role, condition=cond, budget=budget, n=len(entries), chars=sum(len(x) for x in lines), entries=entries)
        if any(x["type"] == "preference" for x in entries):
            try: profile.mark_used(profile.owner_of(root), [x["id"] for x in entries if x["type"] == "preference"])
            except Exception: pass
    return {"lines": lines, "entries": entries, "condition": cond}


def retro_input(root, m) -> dict:
    """Seam for the retrospective step (docs 2.1): version m's resolved records, their pairs, the repeats and the build's retrievals."""
    recs = load(root); order = {v["m"]: i for i, v in enumerate(versions(root))}; rp = repeats(recs, order)
    return {"m": m, "resolved": [r for r in recs if (r.get("resolution") or {}).get("m") == m],
            "repeats": [r for r in recs if r.get("milestone") == m and rp.get(r["id"], {}).get("loose")],
            "retrievals": [e for e in events(root, "retrieval") if e.get("m") == m]}


def critic_input(root, m) -> dict:
    """Seam for the critic (docs 2.4): what it may see before version m is delivered (nothing she said about m itself)."""
    from . import profile, projects
    order = {v["m"]: i for i, v in enumerate(versions(root))}; i = order.get(m, len(order))
    recs = [r for r in load(root) if order.get(r.get("milestone"), -1) < i]
    cfg = projects.config_of(root) or {}
    return {"m": m, "records": [{k: r.get(k) for k in ("id", "kind", "class", "words", "milestone", "anchor")} for r in recs if is_complaint(r)],
            "preferences": profile.applicable(profile.owner_of(root), cfg.get("kind") or "memory", projects.game_of(root), project_id(root))}


def match_predictions(root, m, preds=None, theta=0.5) -> dict:
    """M7: a critic's predictions for version m (5_build/<m>/critic.yaml) against her complaints on m (retro.match: loose / strict, Brier)."""
    from . import retro
    return retro.match(root, m, theta, preds)


# ---------------------------------------------------------------- run usage (builds.py logs it at the end of a build)
def run_usage(log_file) -> dict:
    """Tokens / cost / turns of an agent run from its stream log (Claude Code `result` events; Codex `turn.completed` usage). Best effort."""
    u = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}; out = {}
    try: lines = Path(log_file).read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, TypeError): return {}
    seen = False
    models = []
    for ln in lines:
        if '"model"' in ln and '"init"' in ln:
            try: x = json.loads(ln)
            except ValueError: x = {}
            if x.get("type") == "system" and x.get("subtype") == "init" and x.get("model") and x["model"] not in models: models.append(x["model"])
        if '"usage"' not in ln: continue
        try: e = json.loads(ln)
        except ValueError: continue
        if e.get("type") in ("result", "turn.completed") and isinstance(e.get("usage"), dict):
            seen = True
            for k in u: u[k] += int(e["usage"].get(k) or (e["usage"].get("cached_input_tokens") if k == "cache_read_input_tokens" else 0) or 0)
            if e.get("total_cost_usd") is not None: out["cost_usd"] = round(out.get("cost_usd", 0) + float(e["total_cost_usd"]), 4)
            if e.get("num_turns") is not None: out["num_turns"] = out.get("num_turns", 0) + int(e["num_turns"])
            if e.get("duration_ms") is not None: out["duration_ms"] = out.get("duration_ms", 0) + int(e["duration_ms"])
    if models: out["models"] = models
    return {"usage": u, **out} if seen else ({"models": models} if models else {})


# ---------------------------------------------------------------- logging completeness (docs 7.5): is every datum recorded?
def logging_since(root):
    """When this project's live logging began: the first metrics event that is not from a backfill (None: not yet)."""
    ts = [e.get("at") for e in events(root) if not e.get("backfill") and e.get("ev") not in ("backfill", "record_created", "record_state") and e.get("at")]
    live = [e.get("at") for e in events(root) if e.get("ev") in ("record_created", "record_state") and not e.get("backfill") and e.get("at")]
    return min(ts + live) if ts + live else None


def datacheck(root) -> dict:
    """Every datum the evaluation chapter needs (docs 7.3-7.6), per unit, and whether this project records it: rows {datum, unit, state,
    n, detail} with state ok | missing | partial | n/a (not applicable yet, or from before live logging began). Raw data only, no metric."""
    from . import judge, profile
    root = Path(root); recs = load(root); evs = events(root); since = logging_since(root)
    by = {}
    for e in evs: by.setdefault(e.get("ev"), []).append(e)
    rows = []
    def row(datum, unit, state, n=None, detail=""): rows.append({"datum": datum, "unit": unit, "state": state, "n": n, "detail": detail})
    def frac(datum, unit, good, total, detail=""):
        row(datum, unit, "n/a" if not total else ("ok" if good == total else ("missing" if good == 0 else "partial")), f"{good}/{total}", detail)
    # records
    need = ("created", "event", "words", "milestone", "modality", "source")
    frac("record fields (created, event, words, milestone, modality, source)", "record", sum(1 for r in recs if all(r.get(k) for k in need[:3]) and r.get("modality") and r.get("source")), len(recs))
    frac("record milestone (the version she was looking at)", "record", sum(1 for r in recs if r.get("milestone")), len(recs), "none = said before any delivered version")
    ids_state = {e.get("id") for e in by.get("record_state", [])}
    frac("state transitions (history + record_state events)", "record", sum(1 for r in recs if r.get("history") and r["id"] in ids_state), len(recs))
    frac("labels kept per labeller (record.labels)", "record", sum(1 for r in recs if r.get("labels")), len(recs), "older records: only the live labels")
    frac("live labels (class, kind, scope)", "record", sum(1 for r in recs if r.get("class") and r.get("kind") and r.get("scope")), len(recs))
    frac("resident's reading (interpretation, certainty) of live records", "record", sum(1 for r in recs if r.get("interpretation") and r.get("certainty")),
         sum(1 for r in recs if r.get("source") != "backfill"))
    low = [r for r in recs if r.get("certainty") == "low"]
    frac("her answer on uncertain readings (confirm)", "record", sum(1 for r in low if r.get("confirm", {}).get("state") in ("confirmed", "corrected")), len(low))
    fx = [r for r in recs if r.get("resolution")]
    frac("fix linked (status_item + resolution)", "record", sum(1 for r in fx if r.get("status_item")), len(fx))
    ok_, cid, why = judge.consent(root)
    if not ok_: row("LLM-judge labels (model, rubric, prompt version)", "record", "n/a", None, why)
    else: frac("LLM-judge labels (model, rubric, prompt version)", "record", sum(1 for r in recs if (r.get("labels") or {}).get("judge", {}).get("model")), len(recs), f"consent {cid}")
    hum = [k for k in judge.labellers([root]) if k.startswith("human")]
    row("human labels (export / import ready)", "record", "ok" if hum else "n/a", ", ".join(hum) or None, "label --human-sheet / --import --labeller human --name X")
    if by.get("judge"):
        led = _y(Path(root) / layout.LEDGER) or {}
        n = sum(1 for x in (led.get("requests") or []) if isinstance(x, dict) and x.get("purpose") == "feedback-judge")
        frac("judge runs in privacy_ledger.yaml", "judge run", min(n, len(by["judge"])), len(by["judge"]))
    # versions and deliveries
    vers = versions(root); dels = deliveries(root)
    frac("version time (delivery order)", "version", sum(1 for v in vers if v.get("at")), len(vers))
    row("deliveries (result cards per version)", "delivery", "ok" if dels else "n/a", len(dels))
    live_v = [v for v in vers if since and v.get("at") and v["at"] >= since] + [{"m": e["m"]} for e in by.get("build_start", []) if e.get("m") not in {v["m"] for v in vers}]
    live_m = list(dict.fromkeys(v["m"] for v in live_v))
    asg = assignments(root)
    def per(datum, ev, ok=lambda e: True, applies=lambda m: True, detail=""):
        ms = [m for m in live_m if applies(m)]
        good = sum(1 for m in ms if any(e.get("m") == m and ok(e) for e in by.get(ev, [])))
        frac(datum, "version", good, len(ms), detail or ("" if since else "no live logging yet"))
    frac("condition assigned, logged (blind)", "version", sum(1 for m in live_m if m in asg), len(live_m))
    per("build start (provider, model, condition, go card)", "build_start", lambda e: e.get("provider") and e.get("condition"))
    per("build end (wall time, rounds, tokens, cost)", "build_end", lambda e: e.get("wall_s") is not None and e.get("usage"))
    per("retrieval: which lessons / profile entries were in the brief", "retrieval")
    per("critic predictions (versions whose condition has the critic)", "critic", applies=lambda m: uses(root, m, "critic"))
    per("delivered event (pairs by method)", "delivered")
    from . import retro
    todo = set(retro.retro_todo(root))
    frac("retrospective applied (proposals with evidence)", "version", sum(1 for m in live_m if m not in todo and (retro.retro_dir(root, m) / "applied.yaml").is_file()),
         sum(1 for m in live_m if m in todo or (retro.retro_dir(root, m) / "applied.yaml").is_file()))
    vf = [r for r in recs if (r.get("verification") or {}).get("pair")]
    frac("her verdict on before / after pairs", "record", sum(1 for r in vf if r.get("her_verdict")), len(vf), "none yet = 'unconfirmed' in M5")
    row("accepted (rounds to acceptance)", "version", "ok" if by.get("accepted") else "n/a", len(by.get("accepted", [])), "logged when she accepts a version")
    prof = profile.load(profile.owner_of(root))["entries"]
    frac("profile entries with history (proposed / confirmed / switched)", "profile entry", sum(1 for e in prof if e.get("history")), len(prof))
    frac("profile entries linked to records (from)", "profile entry", sum(1 for e in prof if e.get("from")), len(prof))
    missing = [r for r in rows if r["state"] == "missing"]
    return {"project": project_id(root), "logging_since": since, "live_versions": live_m, "rows": rows, "missing": [r["datum"] for r in missing]}


def datacheck_text(d) -> str:
    mark = {"ok": "✓", "partial": "~", "missing": "✗", "n/a": "·"}
    L = [f"[feedback] {d['project']}：评估要的数据（live logging since {d['logging_since'] or '—'}；live versions {', '.join(d['live_versions']) or '—'}）"]
    for r in d["rows"]:
        L.append(f"  {mark[r['state']]} {r['datum']} [{r['unit']}]" + (f" {r['n']}" if r["n"] is not None else "") + (f" — {r['detail']}" if r["detail"] else ""))
    L.append(f"  缺：{'；'.join(d['missing'])}" if d["missing"] else "  没有缺的")
    return "\n".join(L)


def show_text(root) -> str:
    recs = load(root)
    if not recs: return f"[feedback] {path(root)} 还没有记录"
    m = metrics(root, recs); L = [f"[feedback] {len(recs)} 条记录，{m['complaints']} 条意见；重复意见率（严格）"
                                    + (f"{m['rfr_strict']['k']}/{m['rfr_strict']['n']}" if m["rfr_strict"]["n"] else "—")]
    for r in recs:
        a = r.get("anchor") or {}; v = a.get("video") or {}
        where = (f"{r.get('milestone') or '?'} {int(v['t'] // 60)}:{int(v['t'] % 60):02d}" if v.get("t") is not None else _s(r.get("milestone") or "-"))
        L.append(f"  {r['id']} [{r.get('state')}] {r.get('class') or '?'}/{r.get('kind') or '?'} {where}" + (f" · {a['target']}" if a.get("target") else "")
                 + (f" → {r['status_item']}" if r.get("status_item") else "") + (f" · 重复 {','.join(r['repeat_of'])}" if r.get("repeat_of") else "")
                 + f"\n        「{_s(r.get('words'))[:70]}」" + (f"\n        理解：{r['interpretation']}" if r.get("interpretation") else ""))
    return "\n".join(L)
