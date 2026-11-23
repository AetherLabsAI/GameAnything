"""Are the files the pages read well-formed? (QA 2026-10-29: people.yaml appended with `cat >>`, core.character written as a string,
gameplay resources as a string, plan items without `n`: the pages dropped the connection while `flow check` was green.)

    problems(root) -> [(file, what is wrong)]     one YAML document each, the shapes the UI reads (ui/screens.py, ui/__init__.py)

`gameanything flow next` lists them as the first thing to fix and `flow check` fails with them (flow.c_files); a page whose data cannot be
read answers with a JSON error naming the file (ui/__init__.py) instead of dropping the connection.
"""
import re
from pathlib import Path

import yaml

from . import layout


def _load(p: Path):
    """-> (data, error): the one YAML document of a file; a second document, a duplicate top-level key or a syntax error is an error."""
    try: text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError: return None, "不是 UTF-8 文本"
    try: docs = [d for d in yaml.safe_load_all(text)]
    except yaml.YAMLError as x:
        m = getattr(x, "problem_mark", None)
        return None, f"YAML 语法错误（第 {m.line + 1} 行）：{getattr(x, 'problem', '') or x}" if m else f"YAML 语法错误：{x}"
    docs = [d for d in docs if d is not None]
    if len(docs) > 1: return None, "文件里有不止一份 YAML（--- 分开的几段，多半是 cat >> 追加的）：合成一份"
    keys = [m.group(1) for m in re.finditer(r"(?m)^([A-Za-z_][\w-]*):", text)]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup: return None, f"顶层的 {', '.join(dup)} 出现了不止一次（多半是追加写进去的）：合成一个"
    return (docs[0] if docs else None), None


def _list_of_dicts(v, where, need=()) -> list:
    if v is None: return []
    if not isinstance(v, list): return [f"{where} 应该是列表（- 开头的一条条），现在是{_kind(v)}"]
    out = []
    for i, x in enumerate(v, 1):
        if not isinstance(x, dict): out.append(f"{where} 第 {i} 条应该是带字段的对象（key: value），现在是{_kind(x)}"); continue
        for f in need:
            if x.get(f) in (None, ""): out.append(f"{where} 第 {i} 条缺少 {f}")
    return out


def _kind(v) -> str:
    return {str: "一段文字", int: "数字", float: "数字", bool: "是/否", list: "列表", dict: "对象"}.get(type(v), type(v).__name__)


def _dict(v, where) -> list:
    return [] if v is None or isinstance(v, dict) else [f"{where} 应该是对象（key: value），现在是{_kind(v)}"]


def _people(d):
    out = _dict(d, "整个文件")
    if out: return out
    out += _list_of_dicts(d.get("people"), "people", ("id",))
    out += _list_of_dicts(d.get("groups"), "groups")
    return out


def _board(d):
    out = _dict(d, "整个文件")
    if out: return out
    b = d.get("experience_board")
    out += _dict(b, "experience_board")
    if isinstance(b, dict):
        out += _list_of_dicts(b.get("moments"), "experience_board.moments", ("id",))
        out += _list_of_dicts(b.get("skeleton"), "experience_board.skeleton", ("id",))
    return out


def _gameplay(d):
    out = _dict(d, "整个文件")
    if out: return out
    out += _list_of_dicts(d.get("mapping"), "mapping")
    c = d.get("core"); out += _dict(c, "core")
    if isinstance(c, dict):
        out += _dict(c.get("character"), "core.character")
        out += _list_of_dicts(c.get("resources"), "core.resources", ("name",))
        for i, x in enumerate(c.get("resources") if isinstance(c.get("resources"), list) else [], 1):
            if isinstance(x, dict) and not any(x.get(k) for k in ("meaning", "desc", "description")):
                out.append(f"core.resources 第 {i} 条缺少 meaning（它代表她经历里的什么；另写 gain / spend）")
        out += _list_of_dicts(c.get("archetypes"), "core.archetypes")
        if c.get("loop") is not None and not isinstance(c.get("loop"), (list, str)): out.append("core.loop 应该是列表或一段文字")
    C = d.get("content"); out += _dict(C, "content")
    if isinstance(C, dict):
        for k in ("cards", "relics", "enemies", "events", "bosses"): out += _list_of_dicts(C.get(k), f"content.{k}")
    out += _dict(d.get("scope"), "scope")
    return out


def _feature(d):
    out = _dict(d, "整个文件")
    return out or _list_of_dicts(d.get("items"), "items", ("id",))


def _adaptation(d):
    out = _dict(d, "整个文件")
    if out: return out
    for k in ("scenes", "places", "characters"): out += _list_of_dicts(d.get(k), k)
    for i, c in enumerate(d.get("characters") if isinstance(d.get("characters"), list) else [], 1):
        for f in ("looks", "lines"):
            v = c.get(f) if isinstance(c, dict) else None
            if v is None: continue
            if not isinstance(v, list): out.append(f"characters 第 {i} 条的 {f} 应该是列表"); continue
            if any(isinstance(q, dict) and not q.get("text") for q in v):
                out.append(f"characters 第 {i} 条的 {f} 有条目缺少 text（原文那一句；发明的也写在 text 里，另写 where: invented；译文放 text_en / text_zh）")
    return out


def _world_plan(d):
    out = _dict(d, "整个文件")
    if out: return out
    w = d.get("world_plan"); out += _dict(w, "world_plan")
    if isinstance(w, dict):
        ms = w.get("milestones"); out += _dict(ms, "world_plan.milestones")
        if isinstance(ms, dict):
            out += [f"world_plan.milestones.{m} 应该是对象（status: …）" for m, v in ms.items() if v is not None and not isinstance(v, dict)]
    return out


def _plan_items(d):
    out = _dict(d, "整个文件")
    if out: return out
    out += _list_of_dicts(d.get("items"), "items", ("n", "title"))
    for i, x in enumerate(d.get("items") or [], 1):
        if isinstance(x, dict) and x.get("n") not in (None, "") and not str(x.get("n")).isdigit(): out.append(f"items 第 {i} 条的 n 应该是数字（1, 2, 3…）")
    return out


def _mapping(d): return _dict(d, "整个文件")


CHECKS = [(f"{layout.REMEMBER}/people.yaml", _people), (f"{layout.REMEMBER}/board.yaml", _board), (f"{layout.REMEMBER}/gameplay.yaml", _gameplay),
          (f"{layout.REMEMBER}/feature.yaml", _feature), (f"{layout.REMEMBER}/adaptation.yaml", _adaptation), (f"{layout.REMEMBER}/tags.yaml", _mapping),
          (f"{layout.DESIGN}/world_plan.yaml", _world_plan), (f"{layout.DESIGN}/art/looks.yaml", _mapping), (f"{layout.DESIGN}/art/review.yaml", _mapping),
          (f"{layout.CONFIG}/project.yaml", _mapping)]
REVIEWS = ("board_review.yaml", "plan_review.yaml", "adaptation_review.yaml", "feature_review.yaml", "gameplay_review.yaml")


def problems_of(root, rel) -> list:
    """[{file, problem}] of one file the pages read (rel: as in CHECKS), for a page that shows it instead of 「还没有…」 (QA2 2026-10-30)."""
    return [{"file": f, "problem": m} for f, m in problems(root) if f == rel]


def problems(root) -> list:
    """[(file relative to the project, what is wrong)] for every file the pages read."""
    root = Path(root); out = []
    files = list(CHECKS) + [(f"{layout.FEEDBACK}/{n}", _mapping) for n in REVIEWS]
    B = root / "5_build"
    if B.is_dir(): files += [(f"5_build/{p.parent.name}/plan.yaml", _plan_items) for p in sorted(B.glob("*/plan.yaml"))]
    for rel, fn in files:
        p = root / rel
        if not p.is_file(): continue
        d, err = _load(p)
        if err: out.append((rel, err)); continue
        try: out += [(rel, m) for m in fn(d)]
        except Exception as x: out.append((rel, f"读不懂（{type(x).__name__}）"))
    return out


def text(P, n=6) -> str:
    return "；".join(f"{f}: {m}" for f, m in P[:n]) + (f"（还有 {len(P) - n} 处）" if len(P) > n else "")
