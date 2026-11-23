"""Data for the single-page app (ui/static/app.html): the sidebar, 这一天, 素材, 确认这一天 and 方案; adaptation (场景 / 角色), gameplay (机制映射 / 内容 / 平衡) and feature (需求) pages.

Everything is read from the project files on each request (no state of its own). The two review screens write only into
feedback/ (board_review.yaml, plan_review.yaml): board.yaml and world_plan.yaml are the agent's files, it applies the user's edits.
"""
import re
from datetime import datetime
from pathlib import Path

import yaml

from .. import delivery, layout, projects
from .. import decisions
from ..translate import Tr
from .home import MILESTONE_NAMES, home_state
from .i18n import T, round_name, short_date
from .upload import ALLOWED

IMPORTANCE = ("must_preserve", "important", "optional", "skip")
CHOICES = ("do", "hold", "change")
PERSISTENCE = ("once", "replay", "stay")
CJK = re.compile(r"[一-鿿]")


def _y(p: Path, default=None):
    """The YAML of a file, else `default`; a file of another shape than `default` (a list where a mapping belongs) also reads as
    `default` (QA2 2026-10-30: a bad file blanked the whole workspace; filecheck.py names it)."""
    try:
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or default
    except (FileNotFoundError, NotADirectoryError, yaml.YAMLError, UnicodeDecodeError):
        return default
    if isinstance(default, (dict, list)) and not isinstance(d, type(default)): return default
    return d


def _dd(v) -> dict: return v if isinstance(v, dict) else {}
def _ll(v) -> list: return v if isinstance(v, list) else []


def _bad(root, name) -> list:
    """The problems of 3_remember/<name> (filecheck.py): the page names the file instead of saying there is nothing yet."""
    from .. import filecheck
    try: return filecheck.problems_of(root, f"{layout.REMEMBER}/{name}")
    except Exception: return []


def refs_of(m) -> list:
    """The pack items of a board moment: `source_refs`, or `items` (what steps/memory/board.md says; QA2 2026-10-30: the photos never showed)."""
    m = _dd(m); out = []
    for k in ("source_refs", "items"):
        for r in _ll(m.get(k)):
            if isinstance(r, str) and r not in out: out.append(r)
    return out


def _mt(p: Path) -> str:
    return str(p.stat().st_mtime_ns) if p.exists() else "-"


def _date(s, lang="zh") -> str:
    try:
        return short_date(datetime.fromisoformat(str(s)[:10]), lang)
    except ValueError:
        return ""


def _short(s: str, n=24) -> str:
    return s if len(s) <= n else s[:n - 1] + "…"


def _write(p: Path, header: str, data):
    p.parent.mkdir(exist_ok=True); p.write_text(header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")


class Data:
    """Read-side helpers over one project root."""

    def __init__(self, root: Path, lang="zh"):
        self.root = root; self.B = root / "5_build"; self.tr = Tr(root, lang)    # tr: the project's English for its own content (translate.py)
        self.rem = root / layout.REMEMBER; self.art = root / layout.DESIGN / "art"
        self.pack = _y(layout.pack(root), {}); self.pack["items"] = [it for it in _ll(self.pack.get("items")) if isinstance(it, dict) and it.get("id")]
        self.items = {it["id"]: it for it in self.pack["items"]}
        self.board = _dd(_y(self.rem / "board.yaml", {}).get("experience_board"))
        if "moments" in self.board: self.board["moments"] = [m for m in _ll(self.board["moments"]) if isinstance(m, dict)]
        self.plan = _dd(_y(root / layout.DESIGN / "world_plan.yaml", {}).get("world_plan"))
        if "milestones" in self.plan: self.plan["milestones"] = _dd(self.plan["milestones"])
        self.cfg = _y(root / layout.CONFIG / "project.yaml", {})
        self.people = [p for p in _ll(_y(self.rem / "people.yaml", {}).get("people")) if isinstance(p, dict)]

    # ---- images ----
    def image(self, ref, full=False):
        """URL of the picture of a source item (photo; video / document: its first frame / page), or None."""
        it = self.items.get(ref); d = (it or {}).get("derived") or {}
        p = d.get("image") if full and it["kind"] == "photo" else d.get("thumb") or d.get("image")
        return "/media/" + p if p else None

    def moment_image(self, m, full=False):
        refs = refs_of(m)
        ordered = sorted(refs, key=lambda r: {"photo": 0, "video": 1}.get((self.items.get(r) or {}).get("kind"), 2))
        for r in ordered:
            u = self.image(r, full)
            if u: return u
        return None

    def cover(self):
        """The hero photo: config/project.yaml `cover: <item id>`, else the first photo of the first must-preserve moment."""
        c = self.cfg.get("cover")
        if c and self.image(c, True): return self.image(c, True), self.image(c)
        for m in self.board.get("moments", []):
            if m.get("importance") == "must_preserve":
                for r in refs_of(m):
                    if (self.items.get(r) or {}).get("kind") == "photo" and self.image(r): return self.image(r, True), self.image(r)
        first = next((i for i in self.items.values() if i["kind"] == "photo" and self.image(i["id"])), None)
        return (self.image(first["id"], True), self.image(first["id"])) if first else (None, None)

    def place(self):
        for m in self.board.get("moments", []):
            pid = m.get("place")
            for pl in (_y(self.rem / "motifs.yaml", {}) or {}).get("places", []):
                if pl.get("id") == pid:
                    w = pl.get("what", ""); mm = re.search(r"请柬：([^）)]+)", w)
                    return self.tr(mm.group(1).strip() if mm else re.split(r"[（(]", w)[0])
        return ""

    # ---- rounds (world_plan milestones + 5_build/<m>/play) ----
    def milestones(self):
        return self.plan.get("milestones") or {}

    def round_name(self, m, v, lang="zh"):
        v = v if isinstance(v, dict) else {}
        return round_name(v.get("name") or MILESTONE_NAMES.get(m) or m, lang, self.tr, v.get("name_en"))

    def play_builds(self):
        """Build folders the 试玩 page can show (play/ has a play.yaml or a video), oldest first (by `at`, else the folder's time, then name)."""
        ms = self.milestones()
        return sorted(delivery.play_folders(self.B), key=lambda m: (str((ms.get(m) or {}).get("at") or self.folder_at(m)), m))

    def folder_at(self, m) -> str:
        """The play folder's modification time (ISO), for builds that world_plan.yaml does not know."""
        try: return datetime.fromtimestamp((self.B / m / "play").stat().st_mtime).isoformat(timespec="seconds")
        except OSError: return ""

    def play(self, m, lang="zh"):
        """5_build/<m>/play/play.yaml as the page reads it (delivery.load_play: normalized; synthesized for a folder with only a video)."""
        if not m or "/" in m or "\\" in m or m.startswith("."): return {}
        return delivery.load_play(self.B / m / "play", T(lang, "完整录像"))

    def review_count(self, m):
        play = self.B / m / "play"; r = _y(play / "user_review.yaml", {}) or {}
        return (sum(1 for e in (r.get("moments") or {}).values() if e.get("status") == "change") + len(r.get("notes") or [])
                + sum(1 for e in (r.get("checks") or {}).values() if e.get("verdict"))
                + sum(1 for e in (r.get("sounds") or {}).values() if e.get("status") == "change"))

    def plan_ok(self, m, v=None) -> bool:
        """Did SHE confirm this milestone's plan (「就按这个做」 on the 方案 page, or her approval on a plan card)? The same rule as the flow
        (flow._scope_round): plan_review.yaml for this milestone, or world_plan's `confirmed`, counted only through her decision record."""
        pr = _y(self.root / layout.FEEDBACK / "plan_review.yaml", {}) or {}
        claimed = (isinstance(pr, dict) and pr.get("milestone") == m and pr.get("state") == "confirmed") or bool(isinstance(v, dict) and v.get("confirmed"))
        return decisions.confirmed(self.root, f"plan:{m}", claimed)

    def rounds(self, lang="zh"):
        out = []; ms = self.milestones(); folders = delivery.play_folders(self.B)
        for i, (m, v) in enumerate(ms.items()):
            v = v if isinstance(v, dict) else {}; st = v.get("status", "planned"); play = m in folders
            state = "live" if st == "building" else "done" if st in ("built", "accepted") else "planned"
            sub = [_date(v.get("at"), lang)] if v.get("at") else []
            if state == "live": sub.append(T(lang, "进行中"))
            elif state == "planned": sub = [(T(lang, "方案定了，等你点开工") if self.plan_ok(m, v) else T(lang, "方案写好了，等你确认")) if st == "next" else T(lang, "计划中")]
            elif st == "accepted": sub.append(T(lang, "已定稿"))
            else:
                n = self.review_count(m)
                sub.append(T(lang, "{n} 条意见", n) if n else T(lang, "等你看录像") if play else T(lang, "做好了"))
            name = self.round_name(m, v, lang)
            out.append({"m": m, "name": name, "title": name.split(" · ", 1)[-1], "state": state, "status": st, "sub": " · ".join(s for s in sub if s),
                        "play": play, "at": str(v.get("at") or ""), "order": i})
        for m in folders:                     # delivered as a folder only (no world_plan milestone): still listed, by the folder's time
            if m in ms: continue
            out.append({"m": m, "name": m, "title": m, "state": "done", "status": "unregistered", "sub": T(lang, "做好了") + " · " + T(lang, "还没登记"),
                        "play": True, "at": self.folder_at(m), "order": len(out)})
        live = [r for r in out if r["state"] == "live"]; planned = [r for r in out if r["state"] == "planned"]
        done = sorted((r for r in out if r["state"] == "done"), key=lambda r: (r["at"], r["order"]), reverse=True)
        return live + done + planned

    def scene_map(self):
        """moment id -> {m, url}: the newest delivered game screenshot of each moment, over all play builds."""
        out = {}
        for m in self.play_builds():
            idx = _y(self.B / m / "play" / "scenes" / "index.yaml", []) or []
            for e in idx:
                mid = e.get("moment") or e.get("source_time"); f = e.get("file", "")
                f = f if f.startswith("scenes/") else "scenes/" + f
                if mid and (self.B / m / "play" / f).exists(): out[mid] = {"m": m, "url": f"/build/{m}/{f}"}
        return out


def default_lang(root: Path) -> str:
    """config/project.yaml `lang` (zh | en), else zh: the language the UI starts in before the user picks one."""
    v = (_y(root / layout.CONFIG / "project.yaml", {}) or {}).get("lang")
    return v if v in ("zh", "en") else "zh"


def shell(root: Path, lang="zh") -> dict:
    d = Data(root, lang); led = layout.ledger_requests(_y(root / layout.LEDGER, {}))
    pk = d.pack.get("items", [])
    hero, thumb = d.cover(); rounds = d.rounds(lang)
    looks = _y(d.art / "looks.yaml", {}); review = _y(d.art / "review.yaml", {})
    unseen = [k for k in looks if _dd(review.get(k)).get("status") in (None, "todo")]
    live = next((r for r in rounds if r["state"] == "live"), None)
    return {"title": d.tr(d.board.get("title") or d.cfg.get("title") or root.name), "date": str(d.board.get("date") or "")[:10], "cover": thumb,
            "game": projects.GAMES[projects.game_of(root)], "game_id": projects.game_of(root), "kind": d.cfg.get("kind") or "memory", "items": len(pk), "persistent": d.tr(str(d.plan.get("persistent") or "").strip()), "people_new": len(unseen), "rounds": rounds,
            "status": {"text": T(lang, "{t} · 进行中", t=live["title"]) if live else T(lang, "现在没有在进行的版本"), "live": bool(live)}, "lang": default_lang(root),
            "footer": {"requests": len(led), "image_cost_usd": round(sum(r.get("cost_usd") or 0 for r in led), 2)}}



def shell_min(root: Path, lang="zh") -> dict:
    """What the sidebar needs when shell() could not read the project's files: the title and kind from config/project.yaml, no rounds."""
    cfg = projects.config_of(root)
    return {"title": str(cfg.get("title") or root.name), "date": "", "cover": None, "game": projects.GAMES[projects.game_of(root)],
            "game_id": projects.game_of(root), "kind": cfg.get("kind") or "memory", "items": 0, "persistent": "", "people_new": 0, "rounds": [],
            "status": {"text": T(lang, "现在没有在进行的版本"), "live": False}, "lang": default_lang(root), "footer": {"requests": 0, "image_cost_usd": 0}}

def _since_min(at) -> float:
    """Minutes from `at` (ISO, naive = local time, or with an offset) until now; None when it does not parse."""
    try: t = datetime.fromisoformat(str(at))
    except ValueError: return None
    return ((datetime.now(t.tzinfo) if t.tzinfo else datetime.now()) - t).total_seconds() / 60


def build_banner(root: Path, lang="zh", evs=None) -> list:
    """The page's "background build" banner, one row per milestone whose world_plan status is `building` (shown even when no agent is
    online): {m, name, round, max_rounds, step, started, updated, elapsed_min}. Sources: 5_build/<m>/build_status.yaml (the coordinator's
    `gameanything build status`) first, then the newest progress card of that milestone (its current step and meter). A finished status hides it."""
    from ..buildwatch import read_status
    d = Data(root, lang); out = []
    evs = evs if evs is not None else []
    for m, v in d.milestones().items():
        v = v or {}
        if v.get("status") != "building": continue
        try: st = read_status(root, m)
        except ValueError: st = {}
        if st.get("done"): continue
        name = d.round_name(m, v, lang); tok = re.compile(rf"(^|[_\-.]){re.escape(m)}([_\-.]|$)")
        card_ev = next((e for e in reversed(evs) if e.get("type") == "card" and (e.get("card") or {}).get("kind") == "progress"
                        and (tok.search(str(e["card"].get("key") or "")) or str(e["card"].get("milestone") or "") in (m, v.get("name") or "\0", name))), None)
        card = dict((card_ev or {}).get("card") or {})
        if lang == "en" and card_ev and isinstance(card_ev.get("card_en"), dict):
            from ..conversation import merge_en
            card = merge_en(card, card_ev["card_en"])
        meter = card.get("meter") or {}
        cur = next((x.get("text") for x in card.get("steps") or [] if x.get("state") == "current"), None)
        step = (st.get("step_en") if lang == "en" else None) or st.get("step") or cur
        started = st.get("started") or v.get("started")
        el = _since_min(started) if started else None
        if el is None and meter.get("elapsed_min") is not None and card_ev:
            el = meter["elapsed_min"] + max(0, _since_min(card_ev["at"]) or 0) if not meter.get("done") else meter["elapsed_min"]
        out.append({"m": m, "name": name, "round": st.get("round", meter.get("round")), "max_rounds": st.get("max_rounds", meter.get("max_rounds")),
                    "step": step, "started": str(started) if started else None, "updated": str(st.get("updated") or (card_ev or {}).get("at") or "") or None,
                    "elapsed_min": round(el) if el is not None and el >= 0 else None})
    return out


def _steps_of(v: dict, tr=lambda s: s):
    """Steps of a running round: the plan's own `steps` if the agent wrote them, else its `what` split into the items it lists."""
    if v.get("steps"):
        return [{"text": tr(s), "state": "todo"} if isinstance(s, str) else {"text": tr(s.get("text", "")), "state": s.get("state", "todo")} for s in v["steps"]], True
    what = str(v.get("what") or "")
    body = what.split("：", 1)[1] if "：" in what else what
    parts = [p.strip(" 。;；") for p in re.split(r"[、+＋]", body)]
    return [{"text": tr(p), "state": "todo"} for p in parts if p], False


def day(root: Path, lang="zh") -> dict:
    d = Data(root, lang); sh = shell(root, lang); hero, _ = d.cover(); ms = d.milestones(); H = home_state(root, lang)
    builds = d.play_builds(); scenes = d.scene_map(); names = {r["m"]: r["name"] for r in sh["rounds"]}
    reviews = {m: _y(d.B / m / "play" / "user_review.yaml", {}) or {} for m in builds}
    requests = {m: _y(d.B / m / "play" / "next_round_request.yaml", None) for m in builds}
    plays = {m: d.play(m, lang) for m in builds}
    checks = {m: _y(d.B / m / "play" / "checks.yaml", []) or [] for m in builds}
    last = builds[-1] if builds else None

    # a running round's brief quotes the user's words: a comment found there has been handed over even without a request file
    brief = "".join((d.B / r["m"] / "package" / f).read_text(encoding="utf-8") if (d.B / r["m"] / "package" / f).exists() else ""
                    for r in sh["rounds"] if r["state"] == "live" for f in ("BRIEF.md", "FEEDBACK_LIST.md"))

    def commented(mid):
        """-> (has comment, handed to the next round) for a moment, over all play builds."""
        has = handed = False
        for m in builds:
            r = reviews[m]; ch = plays[m].get("chapters") or []; e = (r.get("moments") or {}).get(mid) or {}
            hit = e.get("status") == "change"; texts = [e.get("note")] if hit else []
            for n in r.get("notes") or []:
                inside = n.get("t") is not None and any(c["moment"] == mid and c["t"] <= n["t"] < (ch[i + 1]["t"] if i + 1 < len(ch) else 1e9) for i, c in enumerate(ch))
                if n.get("moment") == mid or inside: hit = True; texts.append(n.get("note"))
            if hit:
                has = True; handed = handed or bool(requests[m]) or any(t and t.strip()[:20] in brief for t in texts)
        return has, handed

    moments = []
    for m in d.board.get("moments", []):
        if m.get("importance") == "skip": continue
        mid = m["id"]; has, handed = commented(mid)
        bad = [c for c in checks.get(last, []) if c.get("moment") == mid and c.get("verdict") in ("partial", "no")] if last else []
        sc = scenes.get(mid)
        if has: st, edit = T(lang, "你的意见已交给下一版" if handed else "你留了意见，还没交给下一版"), True
        elif bad: st, edit = T(lang, "检查里还有 {n} 项没做到", len(bad)), True
        elif sc: st, edit = T(lang, "{name}里能玩", name=names.get(sc["m"], sc["m"]).split(" · ")[0]), False
        else: st, edit = T(lang, "还没做"), False
        moments.append({"id": mid, "title": d.tr(m.get("title", mid)), "real": d.moment_image(m), "game": sc["url"] if sc else None, "status": st, "edit": edit,
                        "play": sc["m"] if sc else None})
    skipped = [d.tr(m.get("title", m["id"])) for m in d.board.get("moments", []) if m.get("importance") == "skip"]
    running = next((r for r in sh["rounds"] if r["state"] == "live"), None); rd = None
    if running:
        v = ms.get(running["m"]) or {}; steps, real = _steps_of(v, d.tr)
        rd = {"m": running["m"], "name": running["title"], "at": _date(v.get("at"), lang), "steps": steps, "steps_real": real,
              "progress": v.get("progress") if isinstance(v.get("progress"), (int, float)) and 0 <= v["progress"] <= 1 else None,
              "eta_hours": v.get("eta_hours"), "cost_usd": v.get("cost_usd")}
    todo = []
    for t in H["todo"]:
        h = t.get("href") or ""
        h = "#board" if not h else "#people" if h in ("/people", "/looks") else "#play/" + h.split("m=")[1] if "m=" in h else "#play"
        todo.append({"text": t["text"], "href": h})
    looks = _y(d.art / "looks.yaml", {}) or {}; review = _y(d.art / "review.yaml", {}) or {}
    byid = {p["id"]: p for p in d.people}; faces = []
    for k in looks:
        if (review.get(k) or {}).get("status") in (None, "todo"):
            base = k.partition("@")[0]; f = d.art / "portraits" / f"{base}_neutral.png"
            if f.exists() and len(faces) < 5: faces.append({"url": f"/art/portraits/{f.name}", "name": d.tr((byid.get(base) or {}).get("name") or base)})
    return {"title": sh["title"], "date": sh["date"], "place": d.place(), "hero": hero, "game": sh["game"], "items": len(d.items), "people": len(d.people),
            "moment_total": len(d.board.get("moments", [])), "todo": todo, "more_todo": H["more_todo"], "faces": faces, "round": rd,
            "moments": moments, "skipped": skipped, "board_status": d.board.get("status")}


# ---------------------------------------------------------------- 素材
def ingested(pack: dict) -> dict:
    """What 1_ingest/pack.yaml already holds, to tell the inbox files that are in the material from new ones: {paths: inbox-relative
    paths (items whose file lies under the pack's source_folder), name_bytes: {(file name, size)} (a project folder that was moved or
    copied: the absolute paths no longer match)}. A file is never hashed here (videos can be many GB)."""
    src = str((pack or {}).get("source_folder") or "").rstrip("/\\")
    paths, nb = set(), set()
    for it in (pack or {}).get("items") or []:
        if not isinstance(it, dict) or not it.get("file"): continue
        f = str(it["file"]).replace("\\", "/")
        if src and f.startswith(src.replace("\\", "/") + "/"): paths.add(f[len(src) + 1:])
        nb.add((f.rsplit("/", 1)[-1], it.get("bytes")))
    return {"paths": paths, "name_bytes": nb}


def gather(root: Path, inbox, max_bytes: int, lang="zh") -> dict:
    d = Data(root, lang); its = list(d.items.values()); S = d.pack.get("summary", {})
    cnt = lambda k: sum(1 for i in its if i["kind"] == k)
    with_time = [i for i in its if (i.get("capture_time") or {}).get("value")]
    low = [i for i in with_time if i["capture_time"].get("trust") == "low"]
    videos = [i for i in its if i["kind"] == "video"]
    steps = []
    if with_time: steps.append(T(lang, "读取拍摄时间（{n} 份有，{k} 份不太可靠）", n=len(with_time), k=len(low)) if low else T(lang, "读取拍摄时间（{n} 份有）", n=len(with_time)))
    if S.get("near_duplicate_groups"): steps.append(T(lang, "去掉重复的照片（{n} 组，每组留最大的一张）", n=len(S["near_duplicate_groups"])))
    fr = [i for i in videos if (i.get("derived") or {}).get("frames")]
    if fr: steps.append(T(lang, "视频抽出关键画面（{n} 段）", n=len(fr)))
    tr = [i for i in videos if (i.get("derived") or {}).get("transcript")]
    if tr: steps.append(T(lang, "语音转成文字（{n} 段，本机识别）", n=len(tr)))
    ps = [i for i in its if (i.get("derived") or {}).get("persons")]
    if ps: steps.append(T(lang, "框出照片里的人（{n} 张）", n=len(ps)))
    hero, thumb = d.cover(); pick = [thumb] if thumb else []
    for m in d.board.get("moments", []):
        u = d.moment_image(m)
        if u and u not in pick: pick.append(u)
    files = inbox.files(); req = _y(root / layout.FEEDBACK / "ingest_request.yaml", None)
    asked = {f["path"] for f in (req or {}).get("files", []) if isinstance(f, dict)}
    done = ingested(d.pack)
    for f in files:
        f["asked"] = f["path"] in asked
        f["ingested"] = f["path"] in done["paths"] or (f["path"].rsplit("/", 1)[-1], f["bytes"]) in done["name_bytes"]
    return {"items": len(its), "photo": cnt("photo"), "video": cnt("video"), "document": cnt("document"), "bytes": sum(i.get("bytes") or 0 for i in its),
            "transcribed": len(tr), "people": len(d.people), "steps": steps, "thumbs": pick[:4],
            "inbox": {"files": files, "bytes": sum(f["bytes"] for f in files), "request": {"state": req.get("state"), "at": req.get("at")} if req else None,
                      "new": sum(1 for f in files if not f["asked"] and not f["ingested"]),
                      "ingested": sum(1 for f in files if f["ingested"])},
            "max_bytes": max_bytes, "allowed": sorted(ALLOWED)}


def _hers(root, what, state):
    """A review state as the page shows it: a 'confirmed' she did not make on the page (an agent wrote it; decisions.py) is a draft, so her
    confirm button is there again."""
    return "draft" if state == "confirmed" and not decisions.confirmed(root, what) else state


# ---------------------------------------------------------------- 确认这一天
def board_rev(root: Path) -> str:
    return _mt(root / layout.REMEMBER / "board.yaml") + ";" + _mt(root / layout.FEEDBACK / "board_review.yaml")


def board_state(root: Path, lang="zh") -> dict:
    d = Data(root, lang); tr = d.tr; b = d.board; rv = _y(root / layout.FEEDBACK / "board_review.yaml", {}) or {}
    fresh = rv.get("base_revision") == b.get("revision")         # once the agent applied the review (a newer revision), board.yaml is the truth
    mine = (rv.get("moments") or {}) if fresh else {}
    order = [i for i in rv.get("order", []) if any(m["id"] == i for m in b.get("moments", []))] if fresh else []
    byid = {m["id"]: m for m in b.get("moments", [])}
    order += [i for i in byid if i not in order]
    seg_names = {}
    for s in b.get("skeleton", []):
        seg_names[s["id"]] = tr(re.split(r"[：:（(]", s.get("what", s["id"]))[0].strip() or s["id"])
    ms = []
    for i in order:
        m = byid[i]; e = mine.get(i) or {}
        ms.append({"id": i, "title": tr(m.get("title", i)), "what": tr((m.get("what_happened") or "").strip()), "gaps": tr(m.get("gaps") or ""),
                   "base": m.get("importance"), "importance": e.get("importance") or m.get("importance"),
                   "segment": e.get("segment") or m.get("segment"), "base_segment": m.get("segment"), "img": d.moment_image(m)})
    return {"rev": board_rev(root), "title": tr(b.get("title") or d.cfg.get("title") or root.name), "status": b.get("status"), "revision": b.get("revision"),
            "segments": [{"id": k, "label": v} for k, v in seg_names.items()], "moments": ms,
            "importances": [x for x in IMPORTANCE if x != "optional" or any(m.get("importance") == "optional" for m in b.get("moments", []))],
            "review": {"state": _hers(root, "board", rv.get("state")), "at": rv.get("at"), "note": rv.get("note", "")} if rv else None}


def save_board(proj, data):
    root = proj.root
    with proj.lock:
        if data.get("rev") != board_rev(root):
            return {"ok": False, "stale": True, "error": "这个页面打开后，回忆板或你的修改在别处变过了：请刷新页面再改（刷新前没保存的改动会丢）"}
        d = Data(root); byid = {m["id"]: m for m in d.board.get("moments", [])}
        segl = [s["id"] for s in d.board.get("skeleton", []) if isinstance(s, dict) and s.get("id")]; segs = set(segl)
        order = data.get("order") or []; mine = data.get("moments") or {}
        if sorted(order) != sorted(byid): raise ValueError("时刻列表和回忆板对不上，请刷新页面")
        out, changes = {}, []
        for i in order:
            e = mine.get(i) or {}; imp = e.get("importance"); seg = e.get("segment")
            # tolerant (QA 2026-10-29: 「确认这一天」 always failed when the agent wrote moments without importance / segment): a missing or
            # unknown value falls back to the moment's own, then to "important" / the first segment of the day (none when the board has no skeleton)
            if imp not in IMPORTANCE: imp = byid[i].get("importance") if byid[i].get("importance") in IMPORTANCE else "important"
            if seg not in segs: seg = byid[i].get("segment") if byid[i].get("segment") in segs else (segl[0] if segl else None)
            out[i] = {"importance": imp, "segment": seg}
            if imp != byid[i].get("importance"): changes.append(f"{byid[i].get('title', i)}：重要程度 {byid[i].get('importance')} → {imp}")
            if seg != byid[i].get("segment"): changes.append(f"{byid[i].get('title', i)}：移到 {seg}")
        if order != list(byid): changes.append("时刻的顺序有调整")
        state = "confirmed" if data.get("state") == "confirmed" else "draft"
        prev = _y(root / layout.FEEDBACK / "board_review.yaml", {}) or {}
        rv = {"state": state, "at": datetime.now().isoformat(timespec="seconds"), "base_revision": d.board.get("revision"),
              "note": str(data.get("note") or ""), "changes": changes, "order": order, "moments": out}
        _write(root / layout.FEEDBACK / "board_review.yaml",
               "# 你在“确认这一天”页里的修改（gameanything ui）。agent 会把它应用到 3_remember/board.yaml；board.yaml 本身不由界面改。\n"
               "# state: confirmed = 你点了“确认这一天”，draft = 草稿；order = 时刻的顺序；moments = 每个时刻的重要程度和所在分段。\n", rv)
        proj.feedback_ui({"type": "board_review", "state": state, "changes": len(changes), "note": rv["note"]})
        was = _hers(root, "board", prev.get("state")); decisions.record(root, "board", state, via="ui board")   # her decision, as the server saw it (decisions.py)
        # to the thread: the note when it changed; a plain line when the user confirms the day
        if rv["note"].strip() and rv["note"].strip() != str(prev.get("note") or "").strip(): proj.tell(rv["note"].strip())
        if state == "confirmed" and was != "confirmed":
            n = len(changes); tail = ("：" + "；".join(changes[:3]) + ("……" if n > 3 else "")) if n else ""
            proj.tell(f"确认了这一天（回忆板改了 {n} 处{tail}）" if n else "确认了这一天（回忆板没有改动）",
                      f"Confirmed the day ({n} change{'s' if n != 1 else ''} to the memory board)", None, auto=True)
        return {"ok": True, "rev": board_rev(root), "at": rv["at"], "state": state, "changes": changes}


# ---------------------------------------------------------------- 方案
def plan_rev(root: Path) -> str:
    return _mt(root / layout.DESIGN / "world_plan.yaml") + ";" + _mt(root / layout.FEEDBACK / "plan_review.yaml")


def brief_items(path: Path):
    """The items of a round's BRIEF.md (`## 4. The items`): [{n, title, desc, quote}]. The brief is the agent's own text."""
    try:
        t = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    m = re.search(r"^## 4\..*?\n(.*?)(?=^## \d+\.)", t, re.S | re.M)
    if not m: return []
    out = []
    for blk in re.split(r"(?m)^(?=\*\*\d+\.\s)", m.group(1)):
        h = re.match(r"\*\*(\d+)\.\s+(.*?)\*\*", blk, re.S)
        if not h: continue
        title = h.group(2).strip().rstrip(".。"); body = blk[h.end():]
        do = re.search(r"^- (?:\*\*)?Do:?(?:\*\*)?:?\s*(.+)$", body, re.M) or re.search(r"^- (?!Source)(.+)$", body, re.M)
        src = re.search(r"^- Source:\s*(.+)$", body, re.M)
        q = next((x for x in re.findall(r"[“\"]([^”\"]{4,})[”\"]", src.group(1) if src else "") if CJK.search(x)), "")
        desc = (do.group(1) if do else "").strip(); desc = re.sub(r"[`*]", "", desc)
        out.append({"n": int(h.group(1)), "title": re.sub(r"[`*]", "", title), "desc": _short(desc, 220), "quote": _short(q, 90)})
    return out


def plan_state(root: Path, lang="zh") -> dict:
    d = Data(root, lang); ms = d.milestones(); tr = d.tr
    # a field in the UI language: the agent's own <f>_en / <f>_zh sibling first, else the project's translation store (translate.py)
    pl = lambda x, f: str(x.get(f"{f}_{lang}")) if isinstance(x, dict) and x.get(f"{f}_{lang}") else tr(str((x or {}).get(f) or ""))
    pitem = lambda x, i=0: {"n": int(x["n"]) if str(x.get("n", "")).isdigit() else i + 1, "title": pl(x, "title"), "desc": pl(x, "desc"), "quote": pl(x, "quote")}
    pitems = lambda xs: [pitem(x, i) for i, x in enumerate(xs if isinstance(xs, list) else []) if isinstance(x, dict)]   # a broken item: flow check names it
    pick = next((m for m, v in ms.items() if (v or {}).get("status") == "next"), None) or next((m for m, v in ms.items() if (v or {}).get("status") == "building"), None)
    rv = _y(root / layout.FEEDBACK / "plan_review.yaml", None)
    base = {"rev": plan_rev(root), "round": None, "items": [], "source": None, "review": None, "persistence": list(PERSISTENCE)}
    def _hist_items(m):
        zh_ = (_y(d.B / m / "plan.yaml", {}) or {}).get("items")
        if zh_: return pitems(zh_)
        return [{**i, "title": tr(i["title"]), "desc": tr(i["desc"]), "quote": tr(i["quote"])} for i in brief_items(d.B / m / "package" / "BRIEF.md")]
    base["history"] = [{"m": m, "name": d.round_name(m, v, lang), "status": (v or {}).get("status"), "what": pl(v or {}, "what"),
                        "eta_hours": (v or {}).get("eta_hours"), "cost_usd": (v or {}).get("cost_usd"), "items": _hist_items(m)} for m, v in ms.items()]
    if not pick: return base
    v = ms[pick] or {}
    zh = (_y(d.B / pick / "plan.yaml", {}) or {}).get("items")      # 5_build/<m>/plan.yaml: the plan in the user's language, written with the brief
    if zh: items = pitems(zh)
    else: items = [{**i, "title": tr(i["title"]), "desc": tr(i["desc"]), "quote": tr(i["quote"])} for i in brief_items(d.B / pick / "package" / "BRIEF.md")]     # quote = the user's words: only mapped when the agent added a line for it
    src = "plan" if zh else "brief"
    if not items:
        src = "request"
        for m in reversed(d.play_builds()):
            req = _y(d.B / m / "play" / "next_round_request.yaml", None)
            if req and req.get("items"):
                items = [{"n": i + 1, "title": tr(x.get("what", "")), "desc": "", "quote": _short(x.get("note", ""), 90)} for i, x in enumerate(req["items"])]; break
    if not items: src = None
    cur = rv if rv and rv.get("milestone") == pick else None
    return {**base, "round": {"m": pick, "name": d.round_name(pick, v, lang), "title": d.round_name(pick, v, lang).split(" · ", 1)[-1], "status": v.get("status"), "what": pl(v, "what"),
                              "eta_hours": v.get("eta_hours"), "cost_usd": v.get("cost_usd"), "max_images": v.get("max_images")},
            "items": items, "source": src, "review": ({**cur, "state": _hers(root, f"plan:{pick}", cur.get("state"))} if cur else cur)}


def save_plan(proj, data):
    root = proj.root
    with proj.lock:
        if data.get("rev") != plan_rev(root):
            return {"ok": False, "stale": True, "error": "方案在别处变过了：请刷新页面再选"}
        st = plan_state(root)
        if not st["round"] or st["round"]["m"] != data.get("m"): raise ValueError("现在没有这一版的方案，请刷新页面")
        nums = {str(i["n"]): i["title"] for i in st["items"]}; items = {}
        for k, e in (data.get("items") or {}).items():
            if k not in nums or e.get("choice") not in CHOICES: raise ValueError(f"条目 {k} 不合法")
            items[k] = {"title": nums[k], "choice": e["choice"], **({"note": str(e["note"])} if e.get("note") else {})}
        pers = data.get("persistence")
        if pers is not None and pers not in PERSISTENCE: raise ValueError("留存选项不合法")
        state = "confirmed" if data.get("state") == "confirmed" else "draft"
        prev_rv = _y(root / layout.FEEDBACK / "plan_review.yaml", None)
        rv = {"milestone": data["m"], "state": state, "at": datetime.now().isoformat(timespec="seconds"), "items": items,
              "persistence": pers, "note": str(data.get("note") or "")}
        _write(root / layout.FEEDBACK / "plan_review.yaml",
               "# 你在“方案”页里的选择（gameanything ui）。choice：do 照着做 / hold 先放着 / change 要改（note 写怎么改）；persistence：做完之后留在存档里的程度\n"
               "# （once 只发生一次 / replay 之后可以重温 / stay 留在世界里）。state: confirmed = 你点了“就按这个做”，draft = 草稿。world_plan.yaml 本身不由界面改。\n", rv)
        proj.feedback_ui({"type": "plan_review", "m": data["m"], "state": state, "items": len(items)})
        was = _hers(root, f"plan:{data['m']}", (prev_rv or {}).get("state") if (prev_rv or {}).get("milestone") == data["m"] else None)
        decisions.record(root, f"plan:{data['m']}", state, via="ui plan")
        prev = prev_rv or {}; pit = prev.get("items") or {}
        if rv["note"].strip() and rv["note"].strip() != str(prev.get("note") or "").strip(): proj.tell(rv["note"].strip())
        for k, e in items.items():                                    # per-item words, verbatim, once each
            if e.get("note", "").strip() and e["note"].strip() != str((pit.get(k) or {}).get("note") or "").strip():
                proj.tell(e["note"].strip(), ctx=[{"kind": "plan", "id": k, "label": e["title"]}])
        if state == "confirmed" and was != "confirmed":
            c = {x: sum(1 for e in items.values() if e["choice"] == x) for x in CHOICES}; n = re.sub(r"\D", "", str(data["m"])) or data["m"]
            proj.tell(f"确认了第 {n} 版的方案：照着做 {c.get('do', 0)} 条，先放着 {c.get('hold', 0)} 条，要改 {c.get('change', 0)} 条",
                      f"Confirmed the plan for round {n}: {c.get('do', 0)} to do, {c.get('hold', 0)} on hold, {c.get('change', 0)} to change", None, auto=True)
        return {"ok": True, "rev": plan_rev(root), "at": rv["at"], "state": state}


# ---- adaptation projects (kind: adaptation): 3_remember/adaptation.yaml, written by the agent; the user's review in feedback/adaptation_review.yaml ----
GROUNDING = {"explicit": "explicit", "grounded": "explicit", "implied": "implied", "invented": "invented"}
REVIEW_CHOICES = ("keep", "skip", "change")


def adaptation_rev(root: Path) -> str:
    return _mt(root / layout.REMEMBER / "adaptation.yaml") + ";" + _mt(root / layout.FEEDBACK / "adaptation_review.yaml")


def _L(x: dict, f: str, lang="zh") -> str:
    """A shown field in the UI language: `<f>_<lang>` when the agent wrote it, else `<f>`, else the other language's sibling.
    adaptation.yaml keeps the base field in the work's language of display (Chinese, usually) and optional *_en / *_zh siblings."""
    if not isinstance(x, dict): return str(x or "")
    other = "zh" if lang == "en" else "en"
    for k in (f"{f}_{lang}", f, f"{f}_{other}"):
        v = x.get(k)
        if isinstance(v, str) and v.strip(): return v
    return ""


def _Ls(x: dict, f: str, lang="zh") -> list:
    """A list field (aliases, not_described, characters of a scene) in the UI language: `<f>_<lang>` when it is there."""
    v = x.get(f"{f}_{lang}") if isinstance(x, dict) else None
    return [str(a) for a in (v if isinstance(v, list) and v else (x.get(f) if isinstance(x, dict) else None) or [])]


def _quotes(xs, lang="zh"):
    """Quotes are strings or {text, where, text_zh / text_en (older: zh / en)}; -> [{text, where, tr}]. `text` is always the original
    (word for word); `tr` is its translation into the UI language when the agent wrote one and the original is in the other language."""
    out = []
    other = "zh" if lang == "en" else "en"
    for q in xs if isinstance(xs, list) else []:
        # without `text` (an invented look written only as text_zh, QA2 2026-10-30): the UI language's, else the other one's; filecheck flags it
        if isinstance(q, dict) and not q.get("text"):
            alt = next((q[k] for k in (f"text_{lang}", lang, f"text_{other}", other) if isinstance(q.get(k), str) and q[k].strip()), None)
            if alt: q = {**q, "text": alt}
        if isinstance(q, dict) and q.get("text"):
            t = str(q["text"]); tr = q.get(f"text_{lang}") or q.get(lang) or ""
            out.append({"text": t, "where": str(q.get("where") or ""), "tr": str(tr) if tr and str(tr) != t else ""})
        elif isinstance(q, str) and q.strip(): out.append({"text": q, "where": "", "tr": ""})
    return out


def adaptation_state(root: Path, lang="zh") -> dict:
    """The scenes, places and characters the agent extracted from the work, plus the user's review. Accepts the extraction format of the
    2026-10-21 spike (buildables listed separately, `status: grounded|invented`) as well as places with their own `build` list.
    Shown text follows the UI language (`lang`): *_en / *_zh siblings, falling back to the other language."""
    from ..flow import chars_confirmed, her_chars_confirmed
    A = _y(root / layout.REMEMBER / "adaptation.yaml", {}) or {}
    rv = _y(root / layout.FEEDBACK / "adaptation_review.yaml", {}) or {}
    places, by_name = [], {}
    for i, p in enumerate(A.get("places") or []):
        pid = str(p.get("id") or f"p{i + 1}")
        e = {"id": pid, "name": _L(p, "name", lang) or pid, "aliases": _Ls(p, "aliases", lang), "described": _quotes(p.get("described"), lang),
             "not_described": _Ls(p, "not_described", lang), "build": [], "note": _L(p, "note", lang)}
        if isinstance(p.get(f"described_{lang}"), list):          # a parallel list of translations of the described quotes
            for q, t in zip(e["described"], p[f"described_{lang}"]):
                if isinstance(t, str) and t != q["text"]: q["tr"] = t
        places.append(e)
        for n in [str(p.get("name") or ""), *[str(a) for a in p.get("aliases") or []], e["name"], *e["aliases"]]: by_name.setdefault(n, e)
    def add_build(b, place):
        g = GROUNDING.get(str(b.get("grounding") or b.get("status") or "").lower(), "invented")
        q = b.get("quote")
        place["build"].append({"name": _L(b, "name", lang), "kind": str(b.get("kind") or ""), "grounding": g,
                               "quote": str(q) if q else "", "note": _L(b, "note", lang)})
    for p, src in zip(places, A.get("places") or []):
        for b in src.get("build") or []: add_build(b, p)
    for b in A.get("buildables") or []:
        p = by_name.get(str(b.get("place") or ""))
        if p is None:
            p = {"id": f"p{len(places) + 1}", "name": str(b.get("place") or "?"), "aliases": [], "described": [], "not_described": [], "build": [], "note": ""}
            places.append(p); by_name[p["name"]] = p
        add_build(b, p)
    cnames = {}                                                    # a character's name in the scene chips follows the UI language too
    for c in A.get("characters") or []:
        if isinstance(c, dict) and c.get("name"):
            for n in [c["name"], *(c.get("aliases") or [])]: cnames[str(n)] = _L(c, "name", lang)
    scenes = []
    for i, s in enumerate(A.get("scenes") or []):
        sid = str(s.get("id") or f"s{i + 1}")
        scenes.append({"id": sid, "unit": _L(s, "unit", lang) or str(s.get("chapter") or A.get("chapter") or ""), "title": _L(s, "title", lang) or str(s.get("place") or sid),
                       "place": str(s.get("place") or ""), "what": _L(s, "what", lang), "characters": [cnames.get(str(c), str(c)) for c in s.get("characters") or []],
                       "character_ids": [str(c) for c in s.get("characters") or []],
                       "time": _L(s, "time", lang) or str(s.get("time_weather") or ""), "quotes": _quotes(s.get("quotes"), lang),
                       "frames": [{"file": str(f.get("file") if isinstance(f, dict) else f), "t": (f.get("t") if isinstance(f, dict) else None)}
                                  for f in (s.get("frames") or []) if f]})
    chars = []
    for i, c in enumerate(A.get("characters") or []):
        if isinstance(c, str): c = {"name": c}
        name = str(c.get("name") or f"c{i + 1}")
        chars.append({"id": str(c.get("id") or name), "name": _L(c, "name", lang) or name, "aliases": _Ls(c, "aliases", lang), "role": _L(c, "role", lang),
                      "looks": _quotes(c.get("looks"), lang), "lines": _quotes(c.get("lines"), lang), "image": str(c.get("image") or ""),
                      "frames": [{"file": str(f.get("file") if isinstance(f, dict) else f), "t": (f.get("t") if isinstance(f, dict) else None)}
                                 for f in (c.get("frames") or []) if f],
                      "scenes": [s["id"] for s in scenes if name in s["character_ids"]]})
    counts = {g: sum(1 for p in places for b in p["build"] if b["grounding"] == g) for g in ("explicit", "implied", "invented")}
    w = A.get("work") or {}
    return {"rev": adaptation_rev(root), "exists": bool(A), "bad": _bad(root, "adaptation.yaml"), "work": {k: _L(w, k, lang) for k in ("title", "type", "source", "source_license")},
            "units": _Ls(w, "units", lang), "scenes": scenes, "places": places, "characters": chars, "counts": counts,
            "review": {"state": _hers(root, "scenes", rv.get("state")),
                       "state_characters": "confirmed" if her_chars_confirmed(root, rv) else ("draft" if chars_confirmed(rv) else (rv.get("state_characters") or "draft")),
                       "at": rv.get("at"), "at_characters": rv.get("at_characters") or (rv.get("at") if chars_confirmed(rv) else None),
                       "items": rv.get("items") or {}, "note": rv.get("note") or ""}}


def save_adaptation(proj, data):
    """The user's choices on the 场景 / 角色 pages: per scene / place / character keep|skip|change + a note. Notes go into the thread verbatim
    (once each); confirming tells the agent with one auto line. adaptation.yaml itself is the agent's file and is never edited here."""
    root = proj.root
    with proj.lock:
        if data.get("rev") != adaptation_rev(root):
            return {"ok": False, "stale": True, "error": "场景表在别处变过了：请刷新页面再改"}
        st = adaptation_state(root)
        known = {f"scene:{s['id']}": s["title"] for s in st["scenes"]} | {f"place:{p['id']}": p["name"] for p in st["places"]} \
            | {f"char:{c['id']}": c["name"] for c in st["characters"]}
        prev = _y(root / layout.FEEDBACK / "adaptation_review.yaml", {}) or {}; pit = prev.get("items") or {}
        items = dict(pit)
        for k, e in (data.get("items") or {}).items():
            if k not in known: raise ValueError(f"不认识的条目 {k}")
            ch = e.get("choice") or "keep"
            if ch not in REVIEW_CHOICES: raise ValueError(f"条目 {k} 的选择不合法")
            items[k] = {"label": known[k], "choice": ch, **({"note": str(e["note"])} if str(e.get("note") or "").strip() else {})}
        # what stays from before: only what SHE confirmed (an agent's 'confirmed' becomes draft, and no 「确认了…」 goes out in her name)
        state = "confirmed" if data.get("state") == "confirmed" else (_hers(root, "scenes", prev.get("state")) or "draft")
        from ..flow import chars_confirmed, her_chars_confirmed
        cst = "confirmed" if data.get("state_characters") == "confirmed" or her_chars_confirmed(root, prev) else "draft"   # 「确认人物」 (its own button since 2026-10-26)
        at = datetime.now().isoformat(timespec="seconds")
        rv = {"state": state, "state_characters": cst, "at": at, "at_characters": at if cst == "confirmed" and not chars_confirmed(prev) else prev.get("at_characters", prev.get("at") if cst == "confirmed" else None),
              "items": items, "note": str(data.get("note", prev.get("note") or ""))}
        _write(root / layout.FEEDBACK / "adaptation_review.yaml",
               "# 你在“场景”“角色”页里的选择（gameanything ui）。键：scene:<id> / place:<id> / char:<id>；choice：keep 保留 / skip 先不做 / change 要改（note 写怎么改）。\n"
               "# state: confirmed = 你点了“确认场景和地点”；state_characters: confirmed = 你在“角色”页点了“确认人物”。adaptation.yaml 本身不由界面改。\n", rv)
        proj.feedback_ui({"type": "adaptation_review", "state": state, "state_characters": cst, "items": len(items)})
        was = _hers(root, "scenes", prev.get("state")); was_c = her_chars_confirmed(root, prev)
        if data.get("state") == "confirmed": decisions.record(root, "scenes", "confirmed", via="ui scenes")
        if data.get("state_characters") == "confirmed": decisions.record(root, "characters", "confirmed", via="ui characters")
        kinds = {"scene": "场景", "place": "地点", "char": "角色"}
        for k, e in items.items():
            n = str(e.get("note") or "").strip()
            if n and n != str((pit.get(k) or {}).get("note") or "").strip():
                proj.tell(n, ctx=[{"kind": "adaptation", "id": k, "label": f"{kinds[k.split(':')[0]]} · {e['label']}"}])
        if str(rv["note"]).strip() and str(rv["note"]).strip() != str(prev.get("note") or "").strip(): proj.tell(str(rv["note"]).strip())
        def counts(prefixes):
            ks = [k for k in known if k.split(":")[0] in prefixes]
            c = {x: sum(1 for k in ks if (items.get(k) or {}).get("choice") == x) for x in REVIEW_CHOICES}
            return len(ks), len(ks) - c["skip"] - c["change"], c["skip"], c["change"]
        if state == "confirmed" and was != "confirmed":
            n, keep, skip, ch = counts(("scene", "place"))
            proj.tell(f"确认了场景和地点（共 {n} 条）：保留 {keep} 条，先不做 {skip} 条，要改 {ch} 条",
                      f"Confirmed the scenes and places ({n}): {keep} kept, {skip} not now, {ch} to change", None, auto=True)
        if cst == "confirmed" and not was_c:
            n, keep, skip, ch = counts(("char",))
            proj.tell(f"确认了人物（共 {n} 个）：保留 {keep} 个，先不做 {skip} 个，要改 {ch} 个",
                      f"Confirmed the characters ({n}): {keep} kept, {skip} not now, {ch} to change", None, auto=True)
        return {"ok": True, "rev": adaptation_rev(root), "at": rv["at"], "state": state, "state_characters": cst}


# ---- gameplay projects (kind: gameplay): an experience turned into a game system. 3_remember/gameplay.yaml (mapping, core, content) is the
# agent's file; the user's per-item review is feedback/gameplay_review.yaml; balance numbers come from 5_build/<m>/balance/report.yaml ----
GP_KINDS = ("resource", "card", "relic", "enemy", "event", "boss", "rule")
GP_CHOICES = ("keep", "change", "drop")
GP_GROUPS = (("card", "cards"), ("relic", "relics"), ("enemy", "enemies"), ("event", "events"), ("boss", "bosses"))
GP_STAGES = ("mapping", "content")


def gameplay_rev(root: Path) -> str:
    return _mt(root / layout.REMEMBER / "gameplay.yaml") + ";" + _mt(root / layout.FEEDBACK / "gameplay_review.yaml")


def _s(v) -> str:
    return "" if v is None else str(v)


def _art(root: Path, p) -> str:
    """`art` -> a /media URL when /media may serve it (layout.media_file), else ""."""
    p = _s(p).strip().removeprefix("/media/")
    return "/media/" + p if p and layout.media_file(root, p) else ""


def _moves(xs) -> list:
    out = []
    for m in xs or []:
        if isinstance(m, dict): out.append(": ".join(x for x in (_s(m.get("name")), _s(m.get("effect") or m.get("intent") or m.get("text"))) if x))
        elif _s(m).strip(): out.append(_s(m))
    return out


def _as_list(v) -> list:
    """Agent-written list entries: dicts as they are; a plain line becomes {name: line} (a resources string was dropped silently before)."""
    if isinstance(v, str): v = [x.strip() for x in re.split(r"[、,，;；\n]", v) if x.strip()]
    return [x if isinstance(x, dict) else {"name": _s(x)} for x in (v if isinstance(v, list) else [])]


def gameplay_state(root: Path, lang="zh") -> dict:
    """The experience -> mechanic mapping, the core loop and the content list the agent wrote, plus the user's review."""
    G = _y(root / layout.REMEMBER / "gameplay.yaml", {}) or {}
    rv = _y(root / layout.FEEDBACK / "gameplay_review.yaml", {}) or {}
    G = G if isinstance(G, dict) else {}; rv = rv if isinstance(rv, dict) else {}
    mapping = []
    for i, r in enumerate(_as_list(G.get("mapping"))):
        k = _s(r.get("kind")).lower()
        mapping.append({"id": _s(r.get("id") or f"m{i + 1}"), "experience": _s(r.get("experience")), "mechanic": _s(r.get("mechanic")),
                        "kind": k if k in GP_KINDS else "rule", "note": _s(r.get("note"))})
    c = G.get("core") or {}
    c = c if isinstance(c, dict) else {"fantasy": _s(c)}
    ch = c.get("character") or {}
    if not isinstance(ch, dict): ch = {"note": _s(ch)}                    # written as one line (QA 2026-10-29): shown, and flow check names it
    core = {"fantasy": _s(c.get("fantasy")), "loop": [_s(x) for x in c.get("loop")] if isinstance(c.get("loop"), list) else _s(c.get("loop")),
            "character": {k: _s(ch.get(k)) for k in ("name", "hp", "gold", "start", "note")} if ch else None,
            "resources": [{"name": _s(x.get("name")), "meaning": _s(x.get("meaning") or x.get("desc") or x.get("description")), "gain": _s(x.get("gain") or x.get("gained")),
                           "spend": _s(x.get("spend") or x.get("spent"))} for x in _as_list(c.get("resources"))],
            "archetypes": [{"id": _s(x.get("id") or x.get("key")), "name": _s(x.get("name")), "idea": _s(x.get("idea")), "key_cards": [_s(k) for k in x.get("key_cards") or []]}
                           for x in c.get("archetypes") or [] if isinstance(x, dict)]}
    C = G.get("content") or {}
    content = {}
    for kind, key in GP_GROUPS:
        out = []
        for i, x in enumerate(C.get(key) or []):
            if not isinstance(x, dict): continue
            e = {"id": _s(x.get("id") or f"{kind}{i + 1}"), "name": _s(x.get("name") or x.get("title") or x.get("id")), "art": _art(root, x.get("art")),
                 "art_ref": _s(x.get("art")), "note": _s(x.get("note"))}
            if kind == "card":
                e |= {k: _s(x.get(k)) for k in ("type", "cost", "rarity", "text", "upgrade", "archetype")}; e["type"] = e["type"].lower()
            elif kind == "relic": e |= {k: _s(x.get(k)) for k in ("rarity", "text", "archetype")}
            elif kind in ("enemy", "boss"): e |= {"hp": _s(x.get("hp")), "moves": _moves(x.get("moves")), "mechanic": _s(x.get("mechanic")), "act": _s(x.get("act"))}
            else: e |= {"text": _s(x.get("text")), "options": [{"label": _s(o.get("label")), "effect": _s(o.get("effect"))} if isinstance(o, dict)
                                                               else {"label": _s(o), "effect": ""} for o in x.get("options") or []]}
            out.append(e)
        content[key] = out
    sc = G.get("scope") or {}
    scope = {k: [int(v) for v in (sc[k] if isinstance(sc[k], list) else [sc[k], sc[k]])][:2] for k in ("cards", "relics", "events", "enemies", "bosses", "acts")
             if k in sc and all(str(v).isdigit() for v in (sc[k] if isinstance(sc[k], list) else [sc[k]]))}
    st = {s: (rv.get(s) or {}) for s in GP_STAGES}
    tr = Tr(root, lang)                                  # agent-written: English from the project's translation store when the page is in EN
    mapping, core, content = tr.deep(mapping), tr.deep(core), tr.deep(content)
    return {"rev": gameplay_rev(root), "exists": bool(G), "bad": _bad(root, "gameplay.yaml"), "title": tr(_s(G.get("title"))), "game": projects.GAMES[projects.game_of(root)],
            "mapping": mapping, "core": core, "content": content, "scope": scope, "has_content": any(content.values()),
            "review": {"items": rv.get("items") or {}, "note": rv.get("note") or "", **{s: {"state": _hers(root, f"gameplay:{s}", st[s].get("state")), "at": st[s].get("at")} for s in GP_STAGES}}}


def save_gameplay(proj, data):
    """The user's choices on the 机制映射 / 内容 pages: per row / card / relic / enemy / event / boss keep|change|drop + a note, and the
    confirm of a stage (mapping | content). Notes go into the thread verbatim (once each); gameplay.yaml itself is never edited here."""
    root = proj.root
    with proj.lock:
        if data.get("rev") != gameplay_rev(root):
            return {"ok": False, "stale": True, "error": "机制映射或内容在别处变过了：请刷新页面再改"}
        st = gameplay_state(root)
        known = {f"map:{r['id']}": r["experience"] or r["mechanic"] or r["id"] for r in st["mapping"]}
        for kind, key in GP_GROUPS: known |= {f"{kind}:{x['id']}": x["name"] for x in st["content"][key]}
        prev = _y(root / layout.FEEDBACK / "gameplay_review.yaml", {}) or {}; pit = prev.get("items") or {}
        items = dict(pit)
        for k, e in (data.get("items") or {}).items():
            if k not in known: raise ValueError(f"不认识的条目 {k}")
            ch = e.get("choice") or "keep"
            if ch not in GP_CHOICES: raise ValueError(f"条目 {k} 的选择不合法")
            items[k] = {"label": known[k], "choice": ch, **({"note": str(e["note"])} if str(e.get("note") or "").strip() else {})}
        stage = data.get("stage")
        if stage is not None and stage not in GP_STAGES: raise ValueError("stage 应该是 mapping 或 content")
        at = datetime.now().isoformat(timespec="seconds")
        rv = {s: (prev.get(s) if isinstance(prev.get(s), dict) and _hers(root, f"gameplay:{s}", prev[s].get("state")) == prev[s].get("state") else None)
              or {"state": "draft"} for s in GP_STAGES} | {"at": at, "items": items, "note": str(data.get("note", prev.get("note") or ""))}
        if stage and data.get("state") == "confirmed": rv[stage] = {"state": "confirmed", "at": at}
        _write(root / layout.FEEDBACK / "gameplay_review.yaml",
               "# 你在“机制映射”“内容”页里的选择（gameanything ui）。键：map:<id> / card:<id> / relic:<id> / enemy:<id> / event:<id> / boss:<id>；\n"
               "# choice：keep 保留 / change 要改（note 写怎么改）/ drop 不要。mapping / content 的 state: confirmed = 你点了确认。gameplay.yaml 本身不由界面改。\n", rv)
        proj.feedback_ui({"type": "gameplay_review", "stage": stage, "state": data.get("state"), "items": len(items)})
        was = _hers(root, f"gameplay:{stage}", (prev.get(stage) or {}).get("state")) if stage else None
        if stage and data.get("state") == "confirmed": decisions.record(root, f"gameplay:{stage}", "confirmed", via=f"ui gameplay {stage}")
        kinds = {"map": "映射", "card": "卡牌", "relic": "遗物", "enemy": "敌人", "event": "事件", "boss": "Boss"}
        for k, e in items.items():
            n = str(e.get("note") or "").strip()
            if n and n != str((pit.get(k) or {}).get("note") or "").strip():
                proj.tell(n, ctx=[{"kind": "gameplay", "id": k, "label": f"{kinds[k.split(':')[0]]} · {e['label']}"}])
        if str(rv["note"]).strip() and str(rv["note"]).strip() != str(prev.get("note") or "").strip(): proj.tell(str(rv["note"]).strip())
        if stage and data.get("state") == "confirmed" and was != "confirmed":
            ks = [k for k in known if (k.startswith("map:") if stage == "mapping" else not k.startswith("map:"))]
            c = {x: sum(1 for k in ks if (items.get(k) or {}).get("choice", "keep") == x) for x in GP_CHOICES}
            what, what_en = ("机制映射", "the mechanics mapping") if stage == "mapping" else ("内容表", "the content list")
            proj.tell(f"确认了{what}（共 {len(ks)} 条）：保留 {c['keep']} 条，要改 {c['change']} 条，不要 {c['drop']} 条",
                      f"Confirmed {what_en} ({len(ks)} items): {c['keep']} kept, {c['change']} to change, {c['drop']} dropped", None, auto=True)
        return {"ok": True, "rev": gameplay_rev(root), "at": at, "review": {s: rv[s] for s in GP_STAGES}}


# ---- feature projects (kind: feature): 3_remember/feature.yaml is the requirement sheet the agent writes; the user's review is feedback/feature_review.yaml ----
FT_CHOICES = ("keep", "change", "drop")


def feature_rev(root: Path) -> str:
    return _mt(root / layout.REMEMBER / "feature.yaml") + ";" + _mt(root / layout.FEEDBACK / "feature_review.yaml")


def feature_state(root: Path, lang="zh") -> dict:
    """The requirement sheet (title, goal, items, open questions) the agent wrote, plus the user's review of each item."""
    F = _y(root / layout.REMEMBER / "feature.yaml", {}) or {}
    if not isinstance(F, dict): F = {}
    rv = _y(root / layout.FEEDBACK / "feature_review.yaml", {}) or {}
    items = []
    for i, x in enumerate(F.get("items") or []):
        if not isinstance(x, dict): continue
        st = _s(x.get("status")).lower()
        items.append({"id": _s(x.get("id") or f"i{i + 1}"), "what": _s(x.get("what")), "how": _s(x.get("how")), "done_when": _s(x.get("done_when")),
                      "saves": _s(x.get("saves")), "status": st if st in ("open", "confirmed") else "open"})
    qs = F.get("open_questions") or []
    tr = Tr(root, lang)                                  # agent-written sheet: English from the project's translation store when the page is in EN
    items = [{**x, **{k: tr(x[k]) for k in ("what", "how", "done_when", "saves")}} for x in items]
    return {"rev": feature_rev(root), "exists": bool(F), "bad": _bad(root, "feature.yaml"), "title": tr(_s(F.get("title"))), "goal": tr(_s(F.get("goal"))),
            "game": projects.GAMES[projects.game_of(root)], "items": items,
            "open_questions": [tr(_s(q)) for q in (qs if isinstance(qs, list) else [qs]) if _s(q).strip()], "updated": _s(F.get("updated")),
            "review": {"items": rv.get("items") or {}, "note": rv.get("note") or "", "state": _hers(root, "spec", rv.get("state")), "at": rv.get("at")}}


def save_feature(proj, data):
    """The user's choices on the 需求 page: per item keep|change|drop + a note, and the confirm of the whole sheet. Notes go into the
    thread verbatim (once each); confirming tells the agent with one auto line. feature.yaml itself is the agent's file and is never edited here."""
    root = proj.root
    with proj.lock:
        if data.get("rev") != feature_rev(root):
            return {"ok": False, "stale": True, "error": "需求单在别处变过了：请刷新页面再改"}
        st = feature_state(root)
        known = {f"item:{x['id']}": x["what"] or x["id"] for x in st["items"]}
        prev = _y(root / layout.FEEDBACK / "feature_review.yaml", {}) or {}; pit = prev.get("items") or {}
        items = dict(pit)
        for k, e in (data.get("items") or {}).items():
            if k not in known: raise ValueError(f"不认识的条目 {k}")
            ch = e.get("choice") or "keep"
            if ch not in FT_CHOICES: raise ValueError(f"条目 {k} 的选择不合法")
            items[k] = {"label": known[k], "choice": ch, **({"note": str(e["note"])} if str(e.get("note") or "").strip() else {})}
        state = "confirmed" if data.get("state") == "confirmed" else (_hers(root, "spec", prev.get("state")) or "draft")   # only hers stays
        from ..flow import chars_confirmed
        cst = "confirmed" if data.get("state_characters") == "confirmed" or chars_confirmed(prev) else "draft"   # 「确认人物」 (its own button since 2026-10-26)
        at = datetime.now().isoformat(timespec="seconds")
        rv = {"state": state, "state_characters": cst, "at": at, "at_characters": at if cst == "confirmed" and not chars_confirmed(prev) else prev.get("at_characters", prev.get("at") if cst == "confirmed" else None),
              "items": items, "note": str(data.get("note", prev.get("note") or ""))}
        _write(root / layout.FEEDBACK / "feature_review.yaml",
               "# 你在“需求”页里的选择（gameanything ui）。键：item:<id>；choice：keep 保留 / change 要改（note 写怎么改）/ drop 不要。\n"
               "# state: confirmed = 你点了“确认需求”。feature.yaml 本身不由界面改。\n", rv)
        proj.feedback_ui({"type": "feature_review", "state": state, "items": len(items)})
        was = _hers(root, "spec", prev.get("state"))
        if data.get("state") == "confirmed": decisions.record(root, "spec", "confirmed", via="ui spec")
        for k, e in items.items():
            n = str(e.get("note") or "").strip()
            if n and n != str((pit.get(k) or {}).get("note") or "").strip() and k in known:
                proj.tell(n, ctx=[{"kind": "feature", "id": k, "label": f"需求 · {e['label']}"}])
        if str(rv["note"]).strip() and str(rv["note"]).strip() != str(prev.get("note") or "").strip(): proj.tell(str(rv["note"]).strip())
        if state == "confirmed" and was != "confirmed":
            c = {x: sum(1 for k in known if (items.get(k) or {}).get("choice", "keep") == x) for x in FT_CHOICES}
            proj.tell(f"确认了需求单（共 {len(known)} 条）：保留 {c['keep']} 条，要改 {c['change']} 条，不要 {c['drop']} 条",
                      f"Confirmed the requirements ({len(known)} items): {c['keep']} kept, {c['change']} to change, {c['drop']} dropped", None, auto=True)
        return {"ok": True, "rev": feature_rev(root), "at": rv["at"], "state": state}


def _num(v):
    try: return float(v)
    except (TypeError, ValueError): return None


def _rows(x) -> list:
    """{id: {...}} or [{id, ...}] -> [{id, ...}]."""
    if isinstance(x, dict): return [{"id": str(k), **(v if isinstance(v, dict) else {})} for k, v in x.items()]
    return [dict(v, id=str(v.get("id") or v.get("name") or i)) for i, v in enumerate(x or []) if isinstance(v, dict)]


def balance_state(root: Path, m=None, lang="zh") -> dict:
    """5_build/<m>/balance/report.yaml (written by the lab's simulator), newest round first; names joined from gameplay.yaml."""
    d = Data(root, lang); ms = d.milestones()
    have = [f.parent.parent.name for f in d.B.glob("*/balance/report.yaml")] if d.B.exists() else []
    have = sorted(have, key=lambda x: (str((ms.get(x) or {}).get("at") or ""), x))
    names = {r["m"]: r["name"] for r in d.rounds(lang)}
    rounds = [{"m": x, "name": names.get(x) or x} for x in reversed(have)]
    m = m if m in have else (have[-1] if have else None)
    if not m: return {"m": None, "rounds": []}
    R = _y(d.B / m / "balance" / "report.yaml", {}) or {}   # cards/enemies or sts-sim's per_card/per_enemy
    C = (_y(root / layout.REMEMBER / "gameplay.yaml", {}) or {}).get("content") or {}
    nm = {kind: {str(x.get("id")): str(x.get("name") or x.get("id")) for x in C.get(key) or [] if isinstance(x, dict)} for kind, key in GP_GROUPS}
    cards = [{"id": r["id"], "name": nm["card"].get(r["id"], r["id"]), "picked": _num(r.get("picked")), "played": _num(r.get("played")),
              "win_rate": _num(r.get("win_rate_when_in_deck"))} for r in _rows(R.get("cards") or R.get("per_card"))]
    enemies = [{"id": r["id"], "name": nm["enemy"].get(r["id"]) or nm["boss"].get(r["id"]) or r["id"], "avg_turns": _num(r.get("avg_turns")),
                "avg_damage_taken": _num(r.get("avg_damage_taken"))} for r in _rows(R.get("enemies") or R.get("per_enemy"))]
    b = R.get("boss") or {}
    bid = str(b.get("id") or "")
    boss = {"id": bid, "name": nm["boss"].get(bid) or str(b.get("name") or bid), "avg_turns": _num(b.get("avg_turns")), "win_rate": _num(b.get("win_rate"))} if b else None
    notes = R.get("notes") or []
    return {"m": m, "rounds": rounds, "runs": _num(R.get("runs")), "win_rate": _num(R.get("win_rate")), "at": str(R.get("at") or ""),
            "cards": cards, "enemies": enemies, "boss": boss, "notes": [str(n) for n in (notes if isinstance(notes, list) else [notes])]}


def devstatus_state(root: Path, lang="zh") -> dict:
    """The 开发状态 page (read only for her): 5_build/STATUS.yaml as the page draws it (devstatus.py). Agent-written texts are shown in
    English from `text_en` or the project's i18n store; her own words (open_feedback) never are."""
    from .. import devstatus as S
    tr = Tr(root, lang); d, P = S.load(root); b = d.get("build")
    loc = lambda x, k="text": _s(x.get(k + "_en")) if lang == "en" and x.get(k + "_en") else tr(_s(x.get(k)))
    order = {s: i for i, s in enumerate(("regressed", "broken", "partial", "todo", "done"))}
    items = [{"id": x["id"], "text": loc(x), "state": x.get("state") if x.get("state") in S.STATES else "todo", "since": _s(x.get("since")),
              "verified_by": x.get("verified_by") if x.get("verified_by") in S.BY else None, "evidence": tr(_s(x.get("evidence")))}
             for x in d["items"]]
    items.sort(key=lambda x: order.get(x["state"], 9))
    sev = {"high": 0, "medium": 1, "low": 2}
    issues = sorted([{"id": x.get("id"), "text": loc(x), "severity": x.get("severity") if x.get("severity") in S.SEVERITY else "medium",
                      "since": _s(x.get("since")), "plan": loc(x, "plan")} for x in d["known_issues"]], key=lambda x: sev[x["severity"]])
    regs = [{"id": g.get("id"), "item": _s(g.get("item")), "what": loc(g, "what"), "broke_in": tr(_s(g.get("broke_in"))), "cause": loc(g, "cause"),
             "fixed_in": tr(_s(g.get("fixed_in")))} for g in d["regressions"]]
    regs.sort(key=lambda g: bool(g["fixed_in"]))
    rc = [{"id": x.get("id"), "text": loc(x), "last_build": _s(x.get("last_build")), "last_result": x.get("last_result") if x.get("last_result") in S.RESULTS else None,
           "this_round": bool(b) and x.get("last_build") == b, "note": tr(_s(x.get("note")))} for x in d["recheck"]]
    fb = [{"event": _s(f.get("event")), "text": _s(f.get("text")), "at": _s(f.get("at")), "state": f.get("state") if f.get("state") in S.FB_STATES else "open"}
          for f in d["open_feedback"]]
    fb.sort(key=lambda f: (f["state"] != "open", f["at"]))
    dec = [{"at": _s(x.get("at")), "text": loc(x), "event": _s(x.get("event"))} for x in d["decisions"]]
    return {"exists": S.exists(root), "build": _s(b), "updated": _s(d.get("updated")), "counts": S.counts(d), "items": items, "known_issues": issues,
            "regressions": regs, "recheck": rc, "open_feedback": fb, "decisions": dec, "problems": P,
            "game": projects.GAMES[projects.game_of(root)], "kind": (projects.config_of(root) or {}).get("kind") or "memory"}


def _fb_url(p) -> str:
    p = _s(p)
    if not p: return ""
    return "/conv/" + p[len("conversation/files/"):] if p.startswith("conversation/files/") else "/media/" + p


def feedback_state(root: Path, lang="zh", owner=False) -> dict:
    """The 「反馈和改进」 panel of the 开发状态 page: her feedback records (feedback.py) and the loop's metrics. Her words are shown as written;
    the agent's reading in English from interpretation_en when the page is in EN. The panel is part of the study (study.py): with study mode
    off only {study: false, profile_on} (the page shows the 我的偏好 link); `study_badge` (on, and the viewer is the owner) marks the page."""
    from .. import feedback as F, profile, study
    root = Path(root)
    try: n_prof = len([e for e in profile.load(profile.owner_of(root))["entries"] if e.get("on")])
    except Exception: n_prof = 0
    if not study.on(root): return {"study": False, "exists": F.path(root).is_file(), "profile_on": n_prof}
    recs = F.load(root); m = F.metrics(root, recs); rp = m.pop("repeats", {})
    tr = Tr(root, lang); en = lang == "en"
    out = []
    for r in reversed(recs):
        a = r.get("anchor") or {}; v = a.get("video") or {}; ver = r.get("verification") or {}
        out.append({"id": r.get("id"), "words": _s(r.get("words")), "event": _s(r.get("event")),
                    "interpretation": _s(r.get("interpretation_en")) if en and r.get("interpretation_en") else tr(_s(r.get("interpretation"))),
                    "class": r.get("class") if r.get("class") in F.CLASSES else None, "kind": r.get("kind") if r.get("kind") in F.KINDS else "other",
                    "state": r.get("state") if r.get("state") in F.STATES else "new", "milestone": _s(r.get("milestone")), "t": v.get("t"),
                    "target": _s(a.get("target")), "frame": _fb_url(a.get("frame") or a.get("image")), "region": a.get("region"),
                    "status_item": _s(r.get("status_item")), "repeat_of": rp.get(r.get("id"), {}).get("loose") or [],
                    "repeat_strict": bool(rp.get(r.get("id"), {}).get("strict")), "pair": _fb_url(ver.get("pair")), "method": _s(ver.get("method")),
                    "verdict": (r.get("her_verdict") or {}).get("verdict"), "certainty": r.get("certainty"), "labelled_by": _s(r.get("labelled_by"))})
    return {"study": True, "study_badge": bool(owner), "exists": F.path(root).is_file(), "records": out, "metrics": m, "profile_on": n_prof,
            "kinds": {k: (v[2] if en else v[1]) for k, v in F.KINDS.items()}}


def profile_state(root: Path, lang="zh") -> dict:
    """The 我的偏好 page: the owner's preference profile (profile.py), each entry with its sources resolved to the feedback records."""
    from .. import feedback as F, profile
    owner = profile.owner_of(root); d = profile.load(owner); here = F.project_id(root); cache = {}
    def rec(pid, rid):
        if pid not in cache:
            try: cache[pid] = {r.get("id"): r for r in F.load(Path(projects.find(pid)["path"]) if pid != here else root)}
            except (KeyError, OSError): cache[pid] = {}
        return cache[pid].get(rid) or {}
    en = lang == "en"; kinds = {k: (v[2] if en else v[1]) for k, v in F.KINDS.items()}
    entries = []
    for e in d["entries"]:
        src = [{"project": _s(x.get("project")), "record": _s(x.get("record")), "here": _s(x.get("project")) == here,
                "words": _s(rec(_s(x.get("project")), _s(x.get("record"))).get("words"))} for x in e.get("from") or []]
        entries.append({**{k: e.get(k) for k in ("id", "text", "text_en", "kind", "modes", "games", "projects", "confidence", "status", "on", "last_used", "used", "hits", "by", "created")},
                        "shown": _s(e.get("text_en")) if en and e.get("text_en") else _s(e.get("text")), "from": src})
    return {"owner": owner, "project": here, "entries": entries, "kinds": kinds, "games": projects.GAMES}


def save_profile(root: Path, d: dict) -> dict:
    """POST /api/profile from the 我的偏好 page: op add | set | toggle | remove (her own edits: `by: her`)."""
    from .. import profile
    owner = profile.owner_of(root); op = d.get("op")
    s_ = lambda k: d.get(k) if d.get(k) is None else str(d.get(k))
    if op == "add": e = profile.add(owner, s_("text"), s_("text_en"), s_("kind") or None, d.get("modes"), d.get("games"), d.get("projects"), by="her")
    elif op == "set": e = profile.update(owner, s_("id"), by="her", text=s_("text"), text_en=s_("text_en"), modes=d.get("modes"), games=d.get("games"), projects=d.get("projects"),
                                         status="confirmed" if d.get("confirm") else None)
    elif op == "toggle": e = profile.toggle(owner, s_("id"), bool(d.get("on")), by="her")      # her switch on a candidate confirms it
    elif op == "remove": e = profile.remove(owner, s_("id"))
    else: raise ValueError("op 要是 add / set / toggle / remove")
    return {"ok": True, "entry": e}
