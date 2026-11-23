"""Agent experience memory ("lessons"): what builders and playtesters learned, in three layers (skills/gameanything/references/lessons.md).

    game     <game package>/LESSONS.md           sections `## 开发` (builder) and `## 试玩` (playtester); committed
             (a game with no package yet: docs/lessons/games/<id>.md, moved into the package when it lands)
    role     skills/gameanything/references/lessons/<role>.md   game-independent; committed
    local    <project list folder>/lessons/<game>.md | general.md   this machine / account only; never committed

An installed copy of GameAnything (a wheel in site-packages, shipped.py) reads the game and role files it ships but never writes into the package:
new game / role lessons go to <project list folder>/lessons/_shared/{games,roles}/<id>.md (the same layers, read together with the
shipped ones), and confirm / drop / merge of a shipped entry is refused there (review those in a checkout).

One entry is a markdown block:

    ### terraria-003
    - date: 2026-10-25
    - game: terraria
    - role: builder
    - 现象: …
    - 原因: …
    - 做法: …
    - 证据: m2 第 1 轮 14:05
    - 可信度: tried once
    - status: candidate

    parse(text) / render(entry)       a file <-> its chunks (raw lines and entries); unknown lines are kept as they are
    show(game, role)                  the merged view: confirmed first, then candidates (game, role, local layer order)
    add(...)                          append a candidate, or fold it into a similar entry (more evidence, `verified repeatedly`)
    candidates() / confirm / drop / merge     `gameanything lessons review`
"""
import difflib
import re
from datetime import date
from pathlib import Path

from . import shipped

ROLES = ("builder", "playtester")
SECTION = {"builder": "开发", "playtester": "试玩"}
STATUSES = ("candidate", "confirmed")
CONF = ("tried once", "verified repeatedly")
FIELDS = ("date", "game", "role", "现象", "原因", "做法", "证据", "可信度", "status")       # the order an entry is written in
ALIAS = {"symptom": "现象", "cause": "原因", "fix": "做法", "evidence": "证据", "confidence": "可信度", "state": "status",
         "日期": "date", "游戏": "game", "角色": "role", "状态": "status"}
CONF_ALIAS = {"试过一次": "tried once", "once": "tried once", "多次验证": "verified repeatedly", "repeated": "verified repeatedly",
              "verified": "verified repeatedly"}
SIMILAR = 0.72                     # symptom + cause similarity at or above which a new lesson is folded into an old one
REPO = shipped.ROOT               # the checkout, or the copy of skills/ and docs/lessons/ inside an installed package (shipped.py)
ROLE_DIR = shipped.SKILL / "references" / "lessons"
GENERAL = "any"                    # the `game` of a game-independent lesson

HEAD_RE = re.compile(r"^###\s+(\S+)\s*$")
FIELD_RE = re.compile(r"^-\s*([^:：]+?)\s*[:：]\s?(.*)$")


class LessonError(ValueError):
    pass


# ---------------------------------------------------------------- where the files are
def local_dir() -> Path:
    from . import projects
    return projects.home() / "lessons"


def shared_dir() -> Path:
    """An installed copy's own game / role lessons (the shipped files are read-only there)."""
    return local_dir() / "_shared"


def writable(layer: str, f: Path) -> Path:
    """Where a write to the game / role file f goes: f itself, or (f inside an installed package) its copy under shared_dir()."""
    f = Path(f)
    if layer == "local" or not shipped.read_only(f): return f
    if layer == "role": return shared_dir() / "roles" / f.name
    return shared_dir() / "games" / f"{f.parent.name if f.name == 'LESSONS.md' else f.stem}.md"


def write_dirs(game=None) -> list:
    """The folders a builder writes lessons into (builds.add_dirs): the role folder and this game's, as writable() places them."""
    out = [writable("role", role_file(ROLES[0])).parent, writable("game", game_file(game or GENERAL)).parent]
    for d in out:
        if d.is_relative_to(shared_dir()):                     # (the data dir: made here, so that the builder may write to it)
            try: d.mkdir(parents=True, exist_ok=True)
            except OSError: pass
    return out


def game_file(game: str) -> Path:
    """<game package>/LESSONS.md; a game id with no package (or no game): docs/lessons/games/<id>.md in the checkout."""
    from . import games as registry
    try: return registry.get(game).path / "LESSONS.md"
    except KeyError: return REPO / "docs" / "lessons" / "games" / f"{game}.md"


def role_file(role: str) -> Path:
    return ROLE_DIR / f"{role}.md"


def local_file(game: str = None) -> Path:
    return local_dir() / f"{game or 'general'}.md"


def all_files() -> list:
    """[(layer, path)] of every lessons file that exists: each registered game's, the role files, the local ones."""
    from . import games as registry
    gs = registry.games()
    out = [("game", s.path / "LESSONS.md") for s in gs.values()]
    out += [("game", f) for f in sorted((REPO / "docs" / "lessons" / "games").glob("*.md")) if f.stem not in gs]    # games without a package yet
    out += [("role", role_file(r)) for r in ROLES]
    sd = shared_dir()
    out += [("game", f) for f in sorted((sd / "games").glob("*.md"))] + [("role", f) for f in sorted((sd / "roles").glob("*.md"))]
    if local_dir().is_dir(): out += [("local", f) for f in sorted(local_dir().glob("*.md"))]
    return [(k, f) for k, f in out if f.is_file()]


# ---------------------------------------------------------------- parse / render
def _key(k: str) -> str:
    k = k.strip().strip("*`").strip()
    return ALIAS.get(k.lower(), ALIAS.get(k, k.lower() if k.isascii() else k))


def norm_conf(v: str) -> str:
    v = str(v or "").strip()
    return CONF_ALIAS.get(v, CONF_ALIAS.get(v.lower(), v.lower() if v.lower() in CONF else v))


def parse(text: str) -> list:
    """-> chunks: {"raw": [lines]} or {"entry": {id, fields..., "_section": the `## ` heading above it, "_extra": [unparsed lines]}}."""
    out, cur, section, last = [], None, None, None
    raw = []
    def flush_raw():
        if raw: out.append({"raw": list(raw)}); raw.clear()
    for line in text.replace("\r\n", "\n").split("\n"):
        h = HEAD_RE.match(line)
        if h:
            flush_raw(); cur = {"id": h.group(1), "_section": section, "_extra": []}; out.append({"entry": cur}); last = None; continue
        if line.startswith("## ") or line.startswith("# "):         # a heading always starts a raw chunk of its own
            flush_raw(); cur = None
            if line.startswith("## "): section = line[3:].strip()
            raw.append(line); continue
        if cur is None: raw.append(line); continue
        f = FIELD_RE.match(line)
        if f:
            last = _key(f.group(1)); cur[last] = f.group(2).strip(); continue
        if line.startswith("  ") and line.strip() and last:
            cur[last] = (cur[last] + "\n" + line.strip()).strip(); continue
        if not line.strip():
            cur.setdefault("_blank", 0); cur["_blank"] += 1; continue
        cur["_extra"].append(line)
    flush_raw()
    for c in out:                                                   # blank lines after an entry stay with the entry (one is written back)
        if "entry" in c: c["entry"].pop("_blank", None)
    if out and "raw" in out[-1] and out[-1]["raw"] == [""]: out.pop()
    return out


def entries(text: str) -> list:
    return [c["entry"] for c in parse(text) if "entry" in c]


def render(e: dict) -> list:
    lines = [f"### {e['id']}"]
    keys = [k for k in FIELDS if e.get(k) not in (None, "")] + [k for k in e if not k.startswith("_") and k not in FIELDS and k != "id" and e[k] not in (None, "")]
    for k in keys:
        v = str(e[k]).split("\n")
        lines.append(f"- {k}: {v[0]}"); lines += ["  " + x for x in v[1:]]
    return lines + list(e.get("_extra") or []) + [""]


def unparse(chunks: list) -> str:
    lines = []
    for c in chunks: lines += c["raw"] if "raw" in c else render(c["entry"])
    while lines and lines[-1] == "": lines.pop()
    return "\n".join(lines) + "\n"


def read(f: Path) -> list:
    try: return parse(Path(f).read_text(encoding="utf-8"))
    except FileNotFoundError: return []


def write(f: Path, chunks: list):
    f = Path(f); f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name("." + f.name + ".tmp"); tmp.write_text(unparse(chunks), encoding="utf-8"); tmp.replace(f)


def problems(text: str) -> list:
    """What is wrong with a lessons file's entries (English, one line each); [] = fine. `gameanything game check` reports them."""
    out, seen = [], set()
    for e in entries(text):
        i = e["id"]
        if i in seen: out.append(f"{i}: the id is used twice")
        seen.add(i)
        for k in ("现象", "做法"):
            if not e.get(k): out.append(f"{i}: no {k}")
        if e.get("role") and e["role"] not in ROLES: out.append(f"{i}: role {e['role']!r} is not builder / playtester")
        if e.get("status") and e["status"] not in STATUSES: out.append(f"{i}: status {e['status']!r} is not candidate / confirmed")
        if e.get("可信度") and norm_conf(e["可信度"]) not in CONF: out.append(f"{i}: 可信度 {e['可信度']!r} is not tried once / verified repeatedly")
    return out


# ---------------------------------------------------------------- templates
def game_template(title: str) -> str:
    return (f"# {title}：经验（lessons）\n\n"
            "做过的人留下的做法。格式和规则见 skills/gameanything/references/lessons.md：一条 = 一个 `### <id>` 小块，\n"
            "不写她的照片、人名、存档细节。`gameanything lessons add` 追加候选（candidate），协调员 `gameanything lessons review` 确认 / 合并 / 删除。\n\n"
            "## 开发\n\n## 试玩\n")


def role_template(role: str) -> str:
    return (f"# {role}：经验（和游戏无关）\n\n"
            "格式和规则见 skills/gameanything/references/lessons.md。只写对每个游戏都成立的做法；某个游戏的写进它游戏包里的 LESSONS.md。\n")


def local_template(game: str = None) -> str:
    return (f"# 本机经验：{game or '和游戏无关'}\n\n"
            "只对这台电脑 / 这个账号成立的做法。这个文件不进任何仓库。格式见 skills/gameanything/references/lessons.md。\n\n"
            + ("## 开发\n\n## 试玩\n" if game else ""))


# ---------------------------------------------------------------- privacy guard for the shared layers
PRIVATE_RES = [(re.compile(r"\b[\w.-]+\.(?:jpe?g|heic|png|webp|mp4|mov|m4a|wav)\b", re.I), "a photo / video / audio file name"),
               (re.compile(r"(?:^|[\\/\s])(?:0_inbox|1_ingest|2_perceive|3_remember|conversation)[\\/]"), "a path into a project's own materials"),
               (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "an e-mail address"),
               (re.compile(r"(?:/home/|/Users/|C:\\Users\\)([^/\\\s]+)", re.I), "a path with a user name")]


def project_names(project) -> set:
    """Names a project knows about its people: config/vocab.txt and the people of 3_remember/people.yaml / board.yaml (best effort)."""
    import yaml
    root = Path(project); out = set()
    try: out |= {w.strip() for w in (root / "config" / "vocab.txt").read_text(encoding="utf-8").replace(",", "\n").splitlines() if len(w.strip()) >= 2}
    except OSError: pass
    for f in (root / "3_remember" / "people.yaml", root / "3_remember" / "board.yaml"):
        try: d = yaml.safe_load(f.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError): continue
        def walk(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    if k in ("name", "display", "nickname") and isinstance(v, str) and len(v.strip()) >= 2: out.add(v.strip())
                    else: walk(v)
            elif isinstance(x, list):
                for v in x: walk(v)
        walk(d)
    return out


def private_hits(text: str, names=()) -> list:
    out = [what for rx, what in PRIVATE_RES if rx.search(text)]
    out += [f"the name {n!r} from the project" for n in names if n and n in text]
    return out


# ---------------------------------------------------------------- similarity
def _norm(s: str) -> str:
    return re.sub(r"[\s`'\"“”‘’，。、；：,.;:!?！？()（）\[\]【】<>-]+", " ", str(s or "").lower()).strip()


def similarity(a: dict, b: dict) -> float:
    """How alike two lessons are by symptom and cause (0..1). Character-level, so Chinese and English both work; a missing cause on
    either side weighs on the symptom alone."""
    r = lambda x, y: difflib.SequenceMatcher(None, _norm(x), _norm(y)).ratio() if _norm(x) and _norm(y) else None
    s, c = r(a.get("现象"), b.get("现象")), r(a.get("原因"), b.get("原因"))
    if s is None: return c or 0.0
    return s if c is None else 0.6 * s + 0.4 * c


# ---------------------------------------------------------------- show
def _layers(game=None, role=None) -> list:
    """[(layer, path, section filter)] to read for this game / role."""
    out = []
    if game and game != GENERAL: out.append(("game", game_file(game)))
    out += [("role", role_file(r)) for r in ([role] if role else ROLES)]
    out += [(k, w) for k, f in list(out) for w in [writable(k, f)] if w != f]          # an installed copy's own game / role lessons
    if game and game != GENERAL: out.append(("local", local_file(game)))
    out.append(("local", local_file(None)))
    return out


def collect(game=None, role=None) -> list:
    """Every entry for this game (or every game when None) and role, each with `_layer` and `_file`."""
    out = []
    files = _layers(game, role) if game else all_files()
    for layer, f in files:
        for e in entries(f.read_text(encoding="utf-8")) if f.is_file() else []:
            r = e.get("role") or {v: k for k, v in SECTION.items()}.get(e.get("_section"))
            if role and r and r != role: continue
            if game and layer != "role" and e.get("game") not in (None, "", game, GENERAL) and f != local_file(None): continue
            out.append({**e, "role": r or e.get("role"), "_layer": layer, "_file": str(f)})
    return out


def show(game=None, role=None) -> list:
    """The merged view: confirmed first (layer order game, role, local; then by date), then candidates."""
    order = {"game": 0, "role": 1, "local": 2}
    es = collect(game, role)
    return sorted(es, key=lambda e: (e.get("status") != "confirmed", order.get(e["_layer"], 3), str(e.get("date") or "")))


def show_text(game=None, role=None, lang="zh") -> str:
    es = show(game, role)
    head = f"[lessons] {game or '所有游戏'} · {role or 'builder + playtester'}：{len(es)} 条"
    if not es: return head + "\n  （还没有经验。一轮结束时用 gameanything lessons add 记下新坑和做法）"
    lines = [head]
    last = None
    for e in es:
        grp = "已确认" if e.get("status") == "confirmed" else "候选（试过，自己再验证）"
        if grp != last: lines.append(f"\n== {grp} =="); last = grp
        lines.append(f"### {e['id']}  [{e['_layer']}{' · ' + e['role'] if e.get('role') else ''} · {e.get('可信度') or '?'} · {e.get('date') or ''}]")
        for k in ("现象", "原因", "做法", "证据"):
            if e.get(k): lines.append(f"- {k}: " + str(e[k]).replace("\n", "\n    "))
    return "\n".join(lines)


# ---------------------------------------------------------------- add
def _next_id(prefix: str, chunks_by_file: list) -> str:
    n = 0
    for chunks in chunks_by_file:
        for c in chunks:
            m = re.match(rf"^{re.escape(prefix)}-(\d+)$", c["entry"]["id"]) if "entry" in c else None
            if m: n = max(n, int(m.group(1)))
    return f"{prefix}-{n + 1:03d}"


def target(game, role, local=False, general=False) -> tuple:
    """(path, id prefix, template text, section heading or None) of where a new lesson goes."""
    if role not in ROLES: raise LessonError(f"--role 要是 {' / '.join(ROLES)}")
    if local:
        g = None if general or not game or game == GENERAL else game
        return local_file(g), f"local-{g or 'general'}", local_template(g), SECTION[role] if g else None
    if general or not game or game == GENERAL:
        return writable("role", role_file(role)), role, role_template(role), None
    from . import games as registry
    try: title = registry.get(game).title
    except KeyError: title = game
    return writable("game", game_file(game)), game, game_template(title), SECTION[role]


def add(game, role, symptom, cause="", fix="", evidence="", local=False, general=False, confidence=None, force=False, project=None,
        today=None) -> dict:
    """Append a candidate. -> {action: added | merged, id, file, similar: [(id, score)]}. A lesson like an existing one in the same file
    (similarity >= SIMILAR) is folded into it: its evidence gets one more line and its confidence becomes `verified repeatedly`."""
    if not str(symptom or "").strip(): raise LessonError("--symptom 不能是空的")
    if not str(fix or "").strip(): raise LessonError("--fix 不能是空的：写下一个人能照做的做法")
    f, prefix, tpl, section = target(game, role, local, general)
    if not local:
        hits = private_hits(" ".join([symptom, cause or "", fix, evidence or ""]), project_names(project) if project else ())
        if hits: raise LessonError("共享的经验里不能有她的私人内容（" + "；".join(hits) + "）：改掉，或者用 --local 记在本机")
    chunks = read(f) if f.is_file() else parse(tpl)
    new = {"现象": str(symptom).strip(), "原因": str(cause or "").strip()}
    sims = sorted(((c["entry"]["id"], similarity(new, c["entry"])) for c in chunks if "entry" in c), key=lambda x: -x[1])
    if sims and sims[0][1] >= SIMILAR and not force:
        e = next(c["entry"] for c in chunks if "entry" in c and c["entry"]["id"] == sims[0][0])
        if evidence and evidence not in str(e.get("证据") or ""): e["证据"] = (str(e.get("证据") or "") + "\n" + evidence).strip()
        e["可信度"] = "verified repeatedly"
        if not e.get("原因") and cause: e["原因"] = cause
        write(f, chunks)
        return {"action": "merged", "id": e["id"], "file": str(f), "similar": sims[:3]}
    others = [read(x) for _, x in all_files() if x != f] + [chunks]
    e = {"id": _next_id(prefix, others), "date": (today or date.today()).isoformat(), "game": GENERAL if general or not game else game,
         "role": role, "现象": new["现象"], "原因": new["原因"], "做法": str(fix).strip(), "证据": str(evidence or "").strip(),
         "可信度": norm_conf(confidence) if confidence else "tried once", "status": "candidate", "_extra": []}
    if e["可信度"] not in CONF: raise LessonError("--confidence 要是 tried once / verified repeatedly")
    # into its section (before the next `## ` heading), else at the end (adding the section heading when it is missing)
    heading = lambda c, t=None: "raw" in c and c["raw"] and c["raw"][0].startswith("## ") and (t is None or c["raw"][0].strip() == f"## {t}")
    if section:
        idx = next((i for i, c in enumerate(chunks) if heading(c, section)), None)
        if idx is None: chunks.append({"raw": [f"## {section}", ""]}); idx = len(chunks) - 1
        j = idx + 1
        while j < len(chunks) and not heading(chunks[j]): j += 1
        chunks.insert(j, {"entry": e})
    else: chunks.append({"entry": e})
    _fix_gaps(chunks)
    write(f, chunks)
    return {"action": "added", "id": e["id"], "file": str(f), "similar": sims[:3]}


def _fix_gaps(chunks):
    """A heading right before an entry gets one blank line after it."""
    for i, c in enumerate(chunks[:-1]):
        if "raw" in c and "entry" in chunks[i + 1] and c["raw"] and c["raw"][-1] != "": c["raw"].append("")


# ---------------------------------------------------------------- review
def candidates() -> list:
    return [e for e in show() if e.get("status") != "confirmed"]


def _find(eid: str):
    for _, f in all_files():
        chunks = read(f)
        for i, c in enumerate(chunks):
            if "entry" in c and c["entry"]["id"] == eid:
                if shipped.read_only(f): raise LessonError(f"{eid} 是安装包里自带的经验（{f}），这里改不了：在 gameanything 的代码仓库里审")
                return f, chunks, i
    raise LessonError(f"找不到经验 {eid}（gameanything lessons review 列出候选）")


def confirm(eid: str) -> str:
    f, chunks, i = _find(eid)
    chunks[i]["entry"]["status"] = "confirmed"; write(f, chunks); return str(f)


def drop(eid: str) -> str:
    f, chunks, i = _find(eid)
    del chunks[i]; write(f, chunks); return str(f)


def merge(a: str, b: str) -> str:
    """Fold B into A: A keeps its texts (empty ones filled from B), evidence lines of both, confidence `verified repeatedly`; B is removed."""
    if a == b: raise LessonError("不能把一条并进它自己")
    fb, cb, ib = _find(b); eb = cb[ib]["entry"]
    fa, ca, ia = _find(a)
    if fa == fb: ca = cb                                            # same file: edit one copy
    ea = ca[ia]["entry"]
    for k in ("原因", "做法"):
        if not ea.get(k) and eb.get(k): ea[k] = eb[k]
    ev = [x for x in str(ea.get("证据") or "").split("\n") if x.strip()]
    ev += [x for x in str(eb.get("证据") or "").split("\n") if x.strip() and x not in ev]
    ea["证据"] = "\n".join(ev); ea["可信度"] = "verified repeatedly"
    if eb.get("status") == "confirmed": ea["status"] = "confirmed"
    if fa == fb:
        del ca[next(i for i, c in enumerate(ca) if "entry" in c and c["entry"] is eb)]; write(fa, ca)
    else:
        del cb[ib]; write(fb, cb); write(fa, ca)
    return str(fa)


def review_text() -> str:
    cs = candidates()
    lines = [f"[lessons review] {len(cs)} 条候选"]
    for e in cs:
        lines.append(f"\n### {e['id']}  [{e['_layer']} · {e.get('game') or '?'} · {e.get('role') or '?'} · {e.get('可信度') or '?'} · {e.get('date') or ''}]  {e['_file']}")
        for k in ("现象", "原因", "做法", "证据"):
            if e.get(k): lines.append(f"- {k}: " + str(e[k]).replace("\n", "\n    "))
        sim = [(o["id"], similarity(e, o)) for o in show() if o["id"] != e["id"]]
        sim = [x for x in sim if x[1] >= 0.5]
        if sim: lines.append("  像：" + ", ".join(f"{i} ({s:.2f})" for i, s in sorted(sim, key=lambda x: -x[1])[:3]) + "  → 考虑 --merge")
    lines.append("\n确认：gameanything lessons review --confirm ID   删掉：--drop ID   合并（B 并进 A）：--merge A B" if cs else "  没有要审的候选")
    return "\n".join(lines)
