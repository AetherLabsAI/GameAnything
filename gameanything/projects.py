"""The local project list (D16): <config>/projects.yaml, <config> = osdirs.config_home() (~/.config/gameanything; %APPDATA% on Windows), or $GAMEANYTHING_HOME.

    - {id, title, path, kind: memory|feature|adaptation|gameplay, game: an id of the game registry (games/, `gameanything game list`), created, last_opened}

config/project.yaml of a project: title, kind, game, lang, owner (the hub), build_mode: lab | native (where builds run, buildmode.py; missing =
the automatic rule of before 2026-10-24), study: true | false (study mode, study.py; missing = the global default, off).

`gameanything ui` opens the last-opened project when no --project is given; the browser's sidebar lists these. A project is always a plain folder
(layout.py); this file only remembers where they are. Removing a project moves its folder to <data>/.trash/ and never deletes it.
<data> = $GAMEANYTHING_DATA, else the folder that holds `projects/` when the project lives in one, else osdirs.data_home().
"""
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import yaml

from . import games as registry, layout, osdirs

KINDS = ("memory", "feature", "adaptation", "gameplay")
# the game a project targets (config/project.yaml `game`); a project without one is a Stardew project (the first ones were)
# {id: title} from the game registry (gameanything/games/: one package per game, plus pip-installed plugins; registry.refresh() updates it)
GAMES = registry.titles()
DEFAULT_GAME = {"gameplay": "slay_the_spire"}          # the game a new project of this kind starts with (the dialog preselects it)
SKELETON = (layout.INBOX, layout.CONFIG, layout.INGEST, layout.PERCEIVE, layout.REMEMBER, layout.DESIGN, layout.FEEDBACK, "conversation")


def home() -> Path:
    return Path(os.environ.get("GAMEANYTHING_HOME") or osdirs.config_home())


SETTINGS = {"max_active_projects": 3,          # how many projects agent sessions work on at once (D20); the rest wait in a queue
            "record_builds": True,            # record each build: the game screen (video) + snapshots of the mod code, for review and promo videos
            "keys_file": None,                # the user's KEY=value file (e.g. a .env) that model calls read their key from (keys.py); never copied
            "study": False,                   # study mode for every project without its own `study:` (study.py, docs/feedback-loop.md 0); off by default
            "examples": [],                   # the welcome page's examples: [{title, image, video?, kind, game}] (local files); empty = found / bundled ones
            "gamebench": None,                # maintainers only (internal/README.md): the gamebench checkout of a lab server ($GAMEANYTHING_GAMEBENCH wins)
            "lab_pool": None}                 # maintainers only: the lab broker's pool.yaml, leases.json next to it ($GAMEANYTHING_LAB_POOL wins)                   # the welcome page's examples: [{title, image, video?, kind, game}] (local files); empty = found / bundled ones


def _examples(v) -> list:
    """Keep the well-formed entries of a settings `examples` list: a title and an image path are needed; video, kind and game are optional."""
    out = []
    for e in v if isinstance(v, list) else []:
        if not isinstance(e, dict) or not isinstance(e.get("title"), str) or not isinstance(e.get("image"), str) or not e["image"]: continue
        x = {"title": e["title"], "image": e["image"]}
        if isinstance(e.get("video"), str) and e["video"]: x["video"] = e["video"]
        x["kind"] = e.get("kind") if e.get("kind") in KINDS else "memory"
        x["game"] = e.get("game") if e.get("game") in GAMES else "stardew"
        out.append(x)
    return out[:6]


def settings() -> dict:
    """<home>/settings.yaml merged over SETTINGS; values out of range fall back to the default."""
    try: d = yaml.safe_load((home() / "settings.yaml").read_text(encoding="utf-8")) or {}
    except (FileNotFoundError, yaml.YAMLError): d = {}
    out = dict(SETTINGS)
    try: n = int(d.get("max_active_projects", out["max_active_projects"]))
    except (TypeError, ValueError): n = out["max_active_projects"]
    out["max_active_projects"] = n if 1 <= n <= 10 else SETTINGS["max_active_projects"]
    rb = d.get("record_builds", SETTINGS["record_builds"]); out["record_builds"] = rb if isinstance(rb, bool) else SETTINGS["record_builds"]
    kf = d.get("keys_file"); out["keys_file"] = kf if isinstance(kf, str) and kf else None
    sv = d.get("study", SETTINGS["study"]); out["study"] = sv if isinstance(sv, bool) else SETTINGS["study"]
    out["examples"] = _examples(d.get("examples"))
    for k in ("gamebench", "lab_pool"): out[k] = d[k] if isinstance(d.get(k), str) and d[k] else None
    return out


def save_settings(d: dict) -> dict:
    cur = settings()
    if "max_active_projects" in d:
        n = int(d.get("max_active_projects", 0))
        if not 1 <= n <= 10: raise ValueError("同时进行的项目要在 1 到 10 之间")
        cur["max_active_projects"] = n
    if "record_builds" in d:
        if not isinstance(d["record_builds"], bool): raise ValueError("record_builds 应该是 true / false")
        cur["record_builds"] = d["record_builds"]
    if "study" in d:                                 # use study.set_global: it also logs where each project's study data starts / stops
        if not isinstance(d["study"], bool): raise ValueError("study 应该是 true / false")
        cur["study"] = d["study"]
    if "keys_file" in d:
        kf = d["keys_file"] or None
        if kf and not Path(kf).expanduser().is_file(): raise ValueError("key 文件不存在")
        cur["keys_file"] = str(Path(kf).expanduser().resolve()) if kf else None
    if "examples" in d:
        if not isinstance(d["examples"], list): raise ValueError("examples 应该是一个列表")
        cur["examples"] = _examples(d["examples"])
    home().mkdir(parents=True, exist_ok=True); (home() / "settings.yaml").write_text(yaml.safe_dump(cur, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return cur


def data_dir(project: Path = None) -> Path:
    if os.environ.get("GAMEANYTHING_DATA"): return Path(os.environ["GAMEANYTHING_DATA"])
    for p in ([Path(project).resolve()] if project else []) + [Path(e["path"]) for e in load()]:
        if p.parent.name == "projects": return p.parent.parent
    return osdirs.data_home()


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load() -> list:
    f = home() / "projects.yaml"
    try: return [e for e in (yaml.safe_load(f.read_text(encoding="utf-8")) or []) if isinstance(e, dict) and e.get("path")]
    except FileNotFoundError: return []


def save(entries: list):
    h = home(); h.mkdir(parents=True, exist_ok=True)
    tmp = h / f".projects.yaml.{os.getpid()}.tmp"           # one per process: several `gameanything ui` started together each save
    tmp.write_text("# GameAnything project list (gameanything project ...). Folders are never deleted from here.\n"
                   + yaml.safe_dump(entries, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
    os.replace(tmp, h / "projects.yaml")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower().replace("'", "")).strip("-")[:40] or "project"


def title_id(title: str, kind: str = "memory") -> str:
    """A sensible ASCII id for a new project: the slug of its title; a title without Latin letters or digits (a Chinese one, 「我们的婚礼」)
    is <kind>-<short hash of the title>, so two Chinese titles never both become "adaptation" (QA 2026-10-29)."""
    s = slug(title)
    if s != "project" and len(s) >= 2: return s
    import hashlib
    return f"{kind}-{hashlib.sha1(str(title).strip().encode('utf-8')).hexdigest()[:6]}"


def unique_id(base: str, entries: list) -> str:
    taken = {e["id"] for e in entries}; i, n = slug(base), 2
    while i in taken: i = f"{slug(base)}-{n}"; n += 1
    return i


def config_of(path: Path) -> dict:
    try: d = yaml.safe_load((Path(path) / layout.CONFIG / "project.yaml").read_text(encoding="utf-8")) or {}
    except (FileNotFoundError, NotADirectoryError, yaml.YAMLError, UnicodeDecodeError): return {}
    return d if isinstance(d, dict) else {}             # a list / a string: filecheck names the file, nothing crashes on it


def game_of(path: Path) -> str:
    g = config_of(path).get("game"); return g if g in GAMES else "stardew"


def register(path, title=None, kind=None) -> dict:
    """Add a project folder to the list (or refresh its entry); -> the entry. Title, kind and game default to config/project.yaml, then the folder name / memory / stardew."""
    path = Path(path).resolve(); es = load(); cfg = config_of(path)
    e = next((x for x in es if Path(x["path"]).resolve() == path), None)
    if e is None:
        e = {"id": unique_id(path.name, es), "title": "", "path": str(path), "kind": "memory", "created": now(), "last_opened": None}; es.append(e)
    e["title"] = title or cfg.get("title") or e["title"] or path.name
    e["kind"] = kind or (cfg.get("kind") if cfg.get("kind") in KINDS else None) or e.get("kind") or "memory"
    e["game"] = game_of(path)
    save(es); return e


def find(ref) -> dict:
    """An entry by id, or by folder path."""
    es = load(); ref = str(ref)
    for e in es:
        if e["id"] == ref: return e
    p = Path(ref).expanduser()
    if p.is_dir():
        for e in es:
            if Path(e["path"]).resolve() == p.resolve(): return e
    raise KeyError(ref)


def resolve(ref) -> Path:
    """--project value: a registered id, else a folder path."""
    p = Path(str(ref)).expanduser()
    if p.is_dir(): return p.resolve()
    try: return Path(find(ref)["path"])
    except KeyError: raise SystemExit(f"no such project: {ref} (not a folder, not in `gameanything project list`)")


def touch(path) -> dict:
    """Mark a project as just opened (registers it first when it is new to the list)."""
    e = register(path); es = load()
    for x in es:
        if x["id"] == e["id"]: x["last_opened"] = now(); e = x
    save(es); return e


def last_opened():
    es = [e for e in load() if e.get("last_opened") and Path(e["path"]).is_dir()]
    return Path(max(es, key=lambda e: e["last_opened"])["path"]) if es else None


def create(title: str, kind: str = "memory", dir: Path = None, lang: str = "en", game: str = "stardew", owner: str = None, data: Path = None,
           build_mode: str = None) -> dict:
    """Make the folder skeleton (layout.py) with config/project.yaml and register it. owner: the hub user it belongs to (users.py);
    data: the data folder whose projects/ it goes in (default data_dir(); a hub user's data_root); build_mode: lab | native (None: not written)."""
    title = (title or "").strip()
    if not title: raise ValueError("项目名不能为空")
    if kind not in KINDS: raise ValueError("项目类型不合法")
    if game not in GAMES: raise ValueError("游戏不合法")
    if build_mode not in (None, "lab", "native"): raise ValueError("构建位置应该是 lab 或 native")
    es = load(); base = title_id(title, kind); pid = unique_id(base, es)
    data = Path(data) if data else data_dir()
    if not dir:                                   # also skip names whose folder already exists (e.g. left behind by a removed project)
        n = 2
        while (data / "projects" / pid).exists() and any((data / "projects" / pid).iterdir()):
            pid = unique_id(f"{slug(base)}-{n}", es); n += 1
    root = Path(dir).expanduser() if dir else data / "projects" / pid
    if root.exists() and any(root.iterdir()): raise ValueError(f"文件夹已存在：{root}")
    for d in SKELETON: (root / d).mkdir(parents=True, exist_ok=True)
    (root / layout.CONFIG / "project.yaml").write_text(yaml.safe_dump({"title": title, "kind": kind, "game": game, "lang": lang, **({"owner": owner} if owner else {}), **({"build_mode": build_mode} if build_mode else {})}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (root / "conversation" / "thread.jsonl").touch()
    e = register(root, title, kind)
    from . import decisions
    decisions.start(root, e["id"])                # her confirmations count only when the UI server saw them (decisions.py)
    return touch(root)


def set_game(ref, game: str) -> dict:
    """Change the game of a project that has no build yet (5_build/ empty); edits only the `game:` line of config/project.yaml."""
    if game not in GAMES: raise ValueError("游戏不合法")
    e = find(ref); root = Path(e["path"]); B = root / "5_build"
    if B.is_dir() and any(B.iterdir()): raise ValueError("这个项目已经开始构建了，不能再换游戏")
    f = root / layout.CONFIG / "project.yaml"; t = f.read_text(encoding="utf-8") if f.exists() else ""
    line = f"game: {game}"
    if re.search(r"(?m)^game:.*$", t): t = re.sub(r"(?m)^game:.*$", line, t, count=1)
    else: t = (t.rstrip("\n") + "\n" if t else "") + line + "\n"
    f.parent.mkdir(parents=True, exist_ok=True); f.write_text(t, encoding="utf-8")
    return register(root)


def remove(ref) -> Path:
    """Unregister and move the folder to <data>/.trash/<id>-<timestamp>/; -> where it went. Never deletes."""
    e = find(ref); src = Path(e["path"]); dst = None
    if src.exists():
        dst = data_dir(src) / ".trash" / f"{e['id']}-{datetime.now():%Y%m%d-%H%M%S}"
        dst.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(src), str(dst))
    save([x for x in load() if x["id"] != e["id"]]); return dst
