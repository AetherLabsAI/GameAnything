"""First-run and orientation data for the browser UI: the welcome page's examples, the new-project wizard's per-game check, the flow
stepper at the top of the workspace, and whether this project's coach marks were seen.

    examples()            2-3 example works for the welcome page: settings `examples`, else finished play videos in the user's own projects,
                          else the small bundled stills (static/examples/*.svg)
    game_checks()         one row per game of projects.GAMES: found on this computer? mod loader? build mode? and the 「在哪里做」 choices
                          (buildmode.options: lab / native, recommended, greyed with the reason), from native.doctor()
    flow_state(root)      where a project is, per kind (素材 → 这一天 → 方案 → …): each step done / current / todo, and the one next action
    coach_seen / set_coach_seen   config/ui.yaml `coach_seen` (the page also remembers it per browser)

Read-only except config/ui.yaml. Texts are the Chinese source keys the page translates (i18n.js); {vars} come in `vars`.
"""
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml

from .. import buildmode, games as registry, layout, projects

STATIC = Path(__file__).parent / "static"
IMG = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def _y(p: Path, default=None):
    """The YAML of a file, else `default`; a file of another shape than `default` (a list where a mapping belongs, a string) also reads
    as `default`: filecheck.py names the file, the flow never crashes on it (QA2 2026-10-30: world_plan.yaml as a list)."""
    try: d = yaml.safe_load(p.read_text(encoding="utf-8")) or default
    except (FileNotFoundError, NotADirectoryError, yaml.YAMLError, UnicodeDecodeError): return default
    if isinstance(default, (dict, list)) and not isinstance(d, type(default)): return default
    return d


# ---------------------------------------------------------------- examples on the welcome page
BUNDLED = [   # small vector stills shipped in static/examples/ (no large files in git)
    {"title": "婚礼那天，在星露谷里重新走一遍", "image": "/examples/memory.svg", "kind": "memory", "game": "stardew"},
    {"title": "小说里的城堡，一块一块建进 Minecraft", "image": "/examples/adaptation.svg", "kind": "adaptation", "game": "minecraft"},
    {"title": "读博五年，变成一套卡牌玩法", "image": "/examples/gameplay.svg", "kind": "gameplay", "game": "slay_the_spire"},
]
KIND_STILL = {k: f"/examples/{k}.svg" for k in projects.KINDS}
STILL_EXT = (".jpg", ".jpeg", ".png", ".webp")


def kind_still_file(kind: str):
    """A fixed picture for a project kind the owner put in <project list folder>/kind_stills/<kind>.jpg|png|webp (kept out of the repo:
    it may show the owner's own projects); None = the bundled drawing."""
    if kind not in projects.KINDS: return None
    return next((f for e in STILL_EXT for f in [projects.home() / "kind_stills" / f"{kind}{e}"] if f.is_file()), None)


def kind_stills() -> dict:
    """kind -> the picture the wizard shows: the fixed file when there is one, else the bundled drawing. Never changes by itself."""
    return {k: f"/kind_still/{k}" if kind_still_file(k) else KIND_STILL[k] for k in projects.KINDS}


def _settings_examples() -> list:
    out = []
    for e in projects.settings().get("examples") or []:
        img = Path(str(e.get("image") or "")).expanduser()
        if not img.is_file(): continue                                    # a missing file is skipped, never an error on the page
        vid = Path(str(e.get("video"))).expanduser() if e.get("video") else None
        out.append({"title": str(e.get("title") or ""), "image_path": img, "video_path": vid if vid and vid.is_file() else None,
                    "kind": e.get("kind") if e.get("kind") in projects.KINDS else "memory",
                    "game": e.get("game") if e.get("game") in projects.GAMES else "stardew", "source": "settings"})
    return out


def play_example(root: Path):
    """The newest finished play of one project: {image_path, video_path} (a result picture, else a scene shot; the video when there is one)."""
    B = Path(root) / "5_build"
    plays = sorted((p.parent for p in B.glob("*/play/play.yaml")), key=lambda d: (d / "play.yaml").stat().st_mtime, reverse=True) if B.is_dir() else []
    for d in plays:
        imgs = [f for sub in ("result", "scenes") for f in sorted((d / sub).glob("*")) if f.suffix.lower() in IMG and f.is_file()]
        if not imgs: continue
        v = (_y(d / "play.yaml", {}) or {}).get("video") or "video.mp4"
        vid = (d / str(v)) if isinstance(v, str) else None
        ok = vid and vid.is_file() and str(vid.resolve()).startswith(str(d.resolve()))
        return {"image_path": imgs[0], "video_path": vid if ok else None}
    return None


KIND_GAME = {"memory": "stardew", "adaptation": "minecraft", "feature": "overcooked2", "gameplay": "slay_the_spire"}   # the showcase game of each kind


def _project_examples(keep=None) -> list:
    """keep(root) -> bool: which projects may show (the hub: only the requesting user's own); None = every registered project."""
    out, kinds = [], set()
    es = sorted(projects.load(), key=lambda e: e.get("last_opened") or "", reverse=True)
    for e in es:
        root = Path(e["path"])
        if not root.is_dir() or (keep is not None and not keep(root)): continue
        x = play_example(root)
        if not x: continue
        out.append({"title": e.get("title") or root.name, "kind": e.get("kind") or "memory", "game": e.get("game") or "stardew", "source": "project", **x})
    out.sort(key=lambda x: (x["video_path"] is None,))                    # with a video first, then one per kind where possible
    pick = []
    for k, g in KIND_GAME.items():                                         # each kind's picture comes from its showcase game first
        x = next((x for x in out if x["kind"] == k and x["game"] == g), None)
        if x: pick.append(x); kinds.add(k)
    for x in out:
        if x["kind"] not in kinds: pick.append(x); kinds.add(x["kind"])
    pick += [x for x in out if x not in pick]
    return pick[:3]


def examples(keep=None) -> list:
    """-> [{title, kind, game, source, image_path | image, video_path?}]: the first source that has any (the curated settings list, the
    projects keep() allows, the bundled stills)."""
    return _settings_examples()[:3] or _project_examples(keep) or [dict(x, source="bundled") for x in BUNDLED]


def public(exs: list) -> list:
    """What the page gets: URLs only (/example/<i>/image|video for files, /examples/... for the bundled stills)."""
    return [{"title": x["title"], "kind": x["kind"], "game": x["game"], "game_name": projects.GAMES.get(x["game"], ""), "source": x["source"],
             "image": x.get("image") or f"/example/{i}/image", "video": f"/example/{i}/video" if x.get("video_path") else None}
            for i, x in enumerate(exs)]


def bundled_file(name: str) -> Path:
    p = (STATIC / "examples" / name).resolve()
    if p.parent != (STATIC / "examples").resolve() or not p.is_file(): raise FileNotFoundError(name)
    return p


# ---------------------------------------------------------------- the wizard's game check
_LOCK = threading.Lock(); _CACHE = {}          # {hub: (at, value)}
CACHE_SECS = 60
LOADER_FIX = registry.loader_fix()             # {game id: how to install its mod loader}: game.yaml `loader.fix` (English: loader.fix_en)


def docker_ok() -> bool:
    """The lab's docker engine answers (docker-rt or a local one; buildmode.docker_ok)."""
    return buildmode.docker_ok()


def machine() -> dict:
    """buildmode.machine(), asking docker only when a gamebench lab is set up here."""
    m = buildmode.machine(docker=False)
    if m["kit"]: m["docker"] = docker_ok()
    return m


def _row(key, ok, text, fix="", optional=False, **vars):
    return {"key": key, "ok": ok, "optional": optional, "text": text, "fix": fix, "vars": vars}


def game_checks(force=False, doctor=None, lab_ok=None, hub=False, m=None) -> dict:
    """{system, mode (the automatic rule of old projects), lab_ok, backend, games: [{id, title, ready, modes, checks: [{key: found|loader|mode,
    ok: true|false|null, optional, text, fix, vars}]}]}. modes = buildmode.options(): the wizard step "where" (two choices), the recommended one
    first-picked. The rows follow the recommended mode: in the lab the game on this computer is only needed to take the result home
    (optional); natively it is what builds use. hub: a multi-user server (the lab is recommended where both work)."""
    with _LOCK:
        c = _CACHE.get(bool(hub))
        if not force and doctor is None and m is None and c and time.time() - c[0] < CACHE_SECS: return c[1]
    from .. import native
    d = doctor or native.doctor()
    if m is None and doctor is not None:          # a given doctor (tests, other callers): its system; the lab works when lab_ok says so
        m = {"system": d["system"], "backend": None, "kit": True, "docker": bool(lab_ok if lab_ok is not None else d["mode"] == "lab"),
             "pool": None, "scripts": set(projects.GAMES) - {"sims4"}, "headless": False}   # as if every game but sims4 had a launch script
    m = m or machine()
    info = {g["game"]: g for g in d["games"]}
    games = []
    for gid, title in projects.GAMES.items():
        g = info.get(gid); rows = []
        md = buildmode.options(gid, m, g, hub=hub); rec = md["recommended"]; lab = rec == "lab"
        if g is None:
            rows.append(_row("found", None, "还不能自动查找 {g}", optional=True, g=title))
        elif g["installed"]:
            rows.append(_row("found", True, "在这台电脑上找到了 {g}", optional=lab, g=title))
        else:
            rows.append(_row("found", False, "这台电脑上没找到 {g}", "在 Steam（或游戏自己的启动器）里装好它；装在别处的话，在对话里告诉 agent 游戏文件夹在哪", optional=lab, g=title))
        lo = (g or {}).get("loader")
        if g is None or not g["installed"]: rows.append(_row("loader", None, "找到游戏之后再查 mod 加载器", optional=True))
        elif lo and lo.get("ok"): rows.append(_row("loader", True, "mod 加载器 {n} 已装好", optional=lab, n=lo.get("name") or ""))
        else: rows.append(_row("loader", False, "还没装 mod 加载器 {n}", LOADER_FIX.get(gid, ""), optional=lab, n=(lo or {}).get("name") or ""))
        if lab:
            rows.append(_row("mode", True, "构建方式：沙箱（镜像）")); ready = True
        elif rec is None:
            lab_opt = md["options"][1]
            fix = "启动 Docker 之后点“重新检查”" if lab_opt["why"] == buildmode.GREY["lab_docker"] else "可以先建项目、做设计，构建前再说"
            rows.append(_row("mode", False, "构建方式：这台电脑上两种都还不能用", fix)); ready = False
        else:
            tc = g.get("toolchain") or {}
            ok = bool(g["installed"] and (lo or {}).get("ok") and tc.get("ok", True))
            fix = "" if ok or not g["installed"] or not (lo or {}).get("ok") else "还需要装 {t}：{u}"
            rows.append(_row("mode", ok, "构建方式：用你自己的游戏（先备份存档，只改 Mods 文件夹）", fix, t=tc.get("name") or "", u=tc.get("setup") or ""))
            ready = ok
        games.append({"id": gid, "title": title, "ready": ready, "modes": md, "checks": rows})
    v = {"system": d["system"], "mode": d["mode"], "lab_ok": bool(m.get("kit", True) and m["docker"]) if m["system"] == "linux" else None,
         "backend": m.get("backend"), "hub": bool(hub), "games": games, "game_info": registry.ui_info(), "at": datetime.now().isoformat(timespec="seconds")}
    if doctor is None:
        with _LOCK: _CACHE[bool(hub)] = (time.time(), v)
    return v


# ---------------------------------------------------------------- the flow stepper
FLOWS = {   # (key, label, the page it opens)
    "memory": [("gather", "素材", "gather"), ("day", "这一天", "home"), ("plan", "方案", "plan"), ("preview", "预览", "people"),
               ("go", "开工", "chat"), ("play", "试玩", "play"), ("keep", "带回家", "keep")],
    "feature": [("gather", "素材", "gather"), ("spec", "需求", "spec"), ("plan", "方案", "plan"), ("go", "开工", "chat"),
                ("play", "试玩", "play"), ("keep", "带回家", "keep")],
    "adaptation": [("gather", "作品", "gather"), ("scenes", "场景", "home"), ("plan", "方案", "plan"), ("preview", "预览", "chat"),
                   ("go", "开工", "chat"), ("play", "试玩", "play")],
    "gameplay": [("gather", "经历", "gather"), ("mechanics", "机制映射", "mechanics"), ("content", "内容", "content"), ("go", "开工", "chat"),
                 ("balance", "平衡/试玩", "balance")],
}
WAIT = "去对话里看看"
# every text flow_state can return (the i18n test checks each has English)
TEXTS = {WAIT, "放进素材", "放进作品", "说说你的经历", "在对话里说你想加什么", "把素材交给 agent 整理", "agent 正在整理你的素材",
         "确认这一天", "agent 正在把素材整理成这一天", "确认场景", "agent 正在从作品里抽取场景和地点", "确认需求", "agent 会先问你几个问题，再写需求单",
         "确认机制映射", "agent 正在画出机制映射", "确认内容", "agent 正在列卡牌、遗物和敌人", "确认方案", "agent 正在写方案",
         "看形象预览", "在对话里看预览", "agent 正在出预览图", "在对话里点开工", "agent 会在对话里给你一张开工卡", "看试玩录像", "看平衡和试玩",
         "正在后台构建，做好后在这里看录像", "装进你的游戏", "都完成了",
         # adaptation (flow.py): its own stepper groups and waits
         "人物", "agent 会先和你确认底本和版权", "在对话里选先改编哪几章", "agent 会在对话里问你先改编哪几章", "agent 正在整理人物", "确认人物",
         "在对话里回答几个问题", "agent 会先问你几个问题，再写方案",
         # memory / feature / gameplay steps and the loop into the next version (flow.py)
         "在对话里点同意", "标记照片里的人", "在对话里确认第一版范围", "在对话里选下一版做什么", "agent 正在准备下一版"} | {s[1] for f in FLOWS.values() for s in f}


def _signals(root: Path) -> dict:
    from ..conversation import Thread
    R, D, F, B = root / layout.REMEMBER, root / layout.DESIGN, root / layout.FEEDBACK, root / "5_build"
    pk = _y(layout.pack(root), {}); pk = pk.get("items") if isinstance(pk, dict) else None
    items = len(pk) if isinstance(pk, list) else 0
    ib = layout.inbox(root)
    inbox = [f for f in ib.rglob("*") if f.is_file() and not any(p.startswith(".") for p in f.relative_to(ib).parts)] if ib.is_dir() else []
    req = _y(F / "ingest_request.yaml", None)
    evs = Thread(root).events()
    said = any(e.get("from") == "user" and e.get("type") == "text" and not e.get("auto") for e in evs)
    cards = {}
    for e in evs:
        if e.get("type") == "card" and (e.get("card") or {}).get("kind") == "go": cards[e["id"]] = None
        if e.get("type") == "answer" and e.get("card_id") in cards: cards[e["card_id"]] = (e.get("answer") or {}).get("decision")
    def dd(v): return v if isinstance(v, dict) else {}       # a file of the wrong shape (a list, a string) reads as empty: filecheck names it
    board = dd(dd(_y(R / "board.yaml", {})).get("experience_board"))
    plan = dd(dd(_y(D / "world_plan.yaml", {})).get("world_plan"))
    ms = dd(plan.get("milestones"))
    st = {m: dd(v).get("status") for m, v in ms.items()}
    def rv(n):
        v = _y(F / n, {}) or {}
        return v if isinstance(v, dict) else {}
    from .. import decisions
    ok = lambda what, claimed: decisions.confirmed(root, what, claimed)

    def plan_ok():
        pr = rv("plan_review.yaml")
        if pr.get("state") == "confirmed" and ok(f"plan:{pr.get('milestone')}", True): return True
        # the agent's own world_plan status: only with her decision on the milestone the plan is about (any, in a legacy project)
        if plan.get("status") != "confirmed": return False
        if not decisions.strict(root): return True
        pick = next((m for m, v in ms.items() if dd(v).get("status") in ("next", "building")), None)
        return bool(pick) and ok(f"plan:{pick}", True)
    gp = rv("gameplay_review.yaml"); G = _y(R / "gameplay.yaml", {}) or {}
    G = G if isinstance(G, dict) else {}
    looks = dd(_y(D / "art" / "looks.yaml", {})); lrev = dd(_y(D / "art" / "review.yaml", {}))
    previews = [f for f in (D / "previews").glob("*") if f.suffix.lower() in IMG] if (D / "previews").is_dir() else []
    return {
        "items": items, "inbox": len(inbox), "ingest_requested": bool(req) and (req or {}).get("state") != "done", "said": said,
        # her confirmations: the review file (or the agent's status) AND her decision as the UI server saw it (decisions.py; QA 2026-10-29)
        "board": bool(board.get("moments")),
        "board_ok": ok("board", board.get("status") == "confirmed" or rv("board_review.yaml").get("state") == "confirmed"),
        "scenes": bool(_y(R / "adaptation.yaml", {})), "scenes_ok": ok("scenes", rv("adaptation_review.yaml").get("state") == "confirmed"),
        "spec": bool(_y(R / "feature.yaml", {})), "spec_ok": ok("spec", rv("feature_review.yaml").get("state") == "confirmed"),
        "mapping": bool(G.get("mapping")), "mapping_ok": ok("gameplay:mapping", dd(gp.get("mapping")).get("state") == "confirmed"),
        "content": bool(G.get("content")), "content_ok": ok("gameplay:content", dd(gp.get("content")).get("state") == "confirmed"),
        "plan": any(s in ("next", "building") for s in st.values()) or bool(ms),
        "plan_ok": plan_ok(),
        "looks": len(looks), "looks_unseen": sum(1 for k in looks if dd(lrev.get(k)).get("status") in (None, "todo")), "previews": len(previews),
        "go_waiting": any(v is None for v in cards.values()),
        "started": any(v == "start" for v in cards.values()) or any(s in ("building", "built", "accepted") for s in st.values()),
        "live": any(s == "building" for s in st.values()),
        "play": any(B.glob("*/play/play.yaml")) if B.is_dir() else False,
        "balance": any(B.glob("*/balance/report.yaml")) if B.is_dir() else False,
        "accepted": any(s == "accepted" for s in st.values()), "final": st.get("final") == "accepted",
    }


def _done(key, kind, s) -> bool:
    return {"gather": bool(s["items"] or s["inbox"] or (kind in ("feature", "gameplay") and s["said"])),
            "day": s["board_ok"], "scenes": s["scenes_ok"], "spec": s["spec_ok"], "mechanics": s["mapping_ok"], "content": s["content_ok"],
            "plan": s["plan_ok"], "preview": bool((s["looks"] and not s["looks_unseen"]) or (kind != "memory" and s["previews"])),
            "go": s["started"], "play": s["accepted"] or s["final"], "balance": s["accepted"] or s["final"], "keep": s["final"]}[key]


def _next(key, kind, s) -> dict:
    act = lambda label, route: {"label": label, "route": route, "wait": False, "hint": ""}
    wait = lambda hint: {"label": WAIT, "route": "chat", "wait": True, "hint": hint}
    if key == "gather":
        return act({"adaptation": "放进作品", "gameplay": "说说你的经历"}.get(kind, "放进素材"), "gather") if kind != "feature" else act("在对话里说你想加什么", "chat")
    if not s["items"] and s["inbox"] and key in ("day", "scenes", "spec", "mechanics"):         # files sit in the inbox, not handed over yet
        return wait("agent 正在整理你的素材") if s["ingest_requested"] else act("把素材交给 agent 整理", "gather")
    if key == "day": return act("确认这一天", "board") if s["board"] else wait("agent 正在把素材整理成这一天")
    if key == "scenes": return act("确认场景", "home") if s["scenes"] else wait("agent 正在从作品里抽取场景和地点")
    if key == "spec": return act("确认需求", "spec") if s["spec"] else wait("agent 会先问你几个问题，再写需求单")
    if key == "mechanics": return act("确认机制映射", "mechanics") if s["mapping"] else wait("agent 正在画出机制映射")
    if key == "content": return act("确认内容", "content") if s["content"] else wait("agent 正在列卡牌、遗物和敌人")
    if key == "plan": return act("确认方案", "plan") if s["plan"] else wait("agent 正在写方案")
    if key == "preview":
        if kind == "memory" and s["looks_unseen"]: return act("看形象预览", "people")
        return act("在对话里看预览", "chat") if s["previews"] else wait("agent 正在出预览图")
    if key == "go": return act("在对话里点开工", "chat") if s["go_waiting"] else wait("agent 会在对话里给你一张开工卡")
    if key == "play": return act("看试玩录像", "play") if s["play"] else wait("正在后台构建，做好后在这里看录像")
    if key == "balance":
        return act("看平衡和试玩", "balance") if s["balance"] else act("看试玩录像", "play") if s["play"] else wait("正在后台构建，做好后在这里看录像")
    return act("装进你的游戏", "keep")


def flow_state(root: Path, signals: dict = None) -> dict:
    """{kind, steps: [{key, label, route, state: done | current | todo | run}], current: key | None, next: {label, route, wait, hint}}.
    A later step that is done marks every step before it done too (a project never shows as going backwards). The steps and what is
    done come from the flow state machine (flow.py), the same one the agents follow (`gameanything flow next`)."""
    from .. import flow
    return flow.stepper(Path(root), signals)


# ---------------------------------------------------------------- coach marks seen
# Shown by itself once per person and project kind: <project list folder>/ui-seen.yaml {who: {kind: when}} is shared by every
# `gameanything ui` port and the hub (a browser's localStorage is per port, so it can't be the record). The project's own
# config/ui.yaml `coach_seen` still counts (it was the record before). who = the hub user, or "local" for a plain `gameanything ui`.
def _ui_file(root: Path) -> Path: return Path(root) / layout.CONFIG / "ui.yaml"
def _seen_file() -> Path: return projects.home() / "ui-seen.yaml"


def coach_seen(root: Path, kind: str = "", who: str = "local") -> bool:
    if (_y(_ui_file(root), {}) or {}).get("coach_seen"): return True
    g = _y(_seen_file(), {}) or {}
    return bool(isinstance(g, dict) and isinstance(g.get(who), dict) and g[who].get(kind or "_"))


def set_coach_seen(root: Path, seen=True, kind: str = "", who: str = "local") -> dict:
    f = _ui_file(root); d = _y(f, {}) or {}
    if not isinstance(d, dict): d = {}
    now = datetime.now().isoformat(timespec="seconds")
    if seen: d["coach_seen"] = now
    else: d.pop("coach_seen", None)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# the browser UI's per-project state (gameanything ui): coach_seen = when the first-visit tips were finished or skipped\n"
                 + yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
    g = _y(_seen_file(), {}) or {}
    if not isinstance(g, dict): g = {}
    mine = g.get(who) if isinstance(g.get(who), dict) else {}
    if seen: mine[kind or "_"] = now
    else: mine.pop(kind or "_", None)
    g[who] = mine; sf = _seen_file(); sf.parent.mkdir(parents=True, exist_ok=True)
    tmp = sf.with_name(f".{sf.name}.{os.getpid()}"); tmp.write_text("# first-visit tips seen, per person and project kind (gameanything ui / hub)\n"
                 + yaml.safe_dump(g, allow_unicode=True, sort_keys=False), encoding="utf-8"); os.replace(tmp, sf)
    return {"ok": True, "coach_seen": bool(d.get("coach_seen"))}
