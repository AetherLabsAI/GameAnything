"""Both languages for an adaptation project's own data (the 场景 / 地点 / 角色 / 方案 pages follow the UI language).

    gameanything adaptation translate --project P [--out todo.yaml]     list the shown fields that miss their other-language sibling
    gameanything adaptation translate --project P --apply done.yaml     merge the filled file into 3_remember/adaptation.yaml / 4_design/world_plan.yaml

The siblings live next to the field: title -> title_en (Chinese base) or title_zh (English base); quotes keep the original `text` and add
`text_zh` / `text_en`. The agent writes them itself while it extracts (it is a language model; no extra service). This tool never calls
a model: sending the work's text to a translation model would need a `permission` card and the paid-generation path (agentd), which
phase 1 does not add.
"""
import re
from pathlib import Path

import yaml

from . import layout

CJK = re.compile(r"[一-鿿]")
FIELDS = {"scenes": ("title", "what", "time"), "places": ("name", "note"), "characters": ("name", "role")}
PLAN_FIELDS = {"places": ("name", "text", "invent"), "milestones": ("what", "name")}


def _y(p: Path):
    try: return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError): return {}


def _other(v: str, f: str) -> str: return f"{f}_en" if CJK.search(v) else f"{f}_zh"


def missing(root) -> dict:
    """{path: source text} for every shown field without its sibling. path: <group>.<id>.<field> or plan.<group>.<id>.<field>."""
    root = Path(root); out = {}
    A = _y(root / layout.REMEMBER / "adaptation.yaml")
    for g, fs in FIELDS.items():
        for x in A.get(g) or []:
            if not isinstance(x, dict): continue
            for f in fs:
                v = x.get(f)
                if isinstance(v, str) and v.strip() and not x.get(_other(v, f)): out[f"{g}.{x.get('id') or x.get('name')}.{_other(v, f)}"] = v
            for qf in ("quotes", "looks", "lines", "described"):
                for i, q in enumerate(x.get(qf) or []):
                    if isinstance(q, dict) and isinstance(q.get("text"), str):
                        t = _other(q["text"], "text")
                        if not (q.get(t) or q.get(t[-2:])): out[f"{g}.{x.get('id') or x.get('name')}.{qf}.{i}.{t}"] = q["text"]
    wp = (_y(root / layout.DESIGN / "world_plan.yaml").get("world_plan") or {})
    for g, fs in PLAN_FIELDS.items():
        rows = wp.get(g) or []
        rows = [{"id": k, **v} for k, v in rows.items() if isinstance(v, dict)] if isinstance(rows, dict) else rows
        for x in rows:
            if not isinstance(x, dict): continue
            for f in fs:
                v = x.get(f)
                if isinstance(v, str) and v.strip() and not x.get(_other(v, f)): out[f"plan.{g}.{x.get('id')}.{_other(v, f)}"] = v
    return out


def _find(rows, key):
    if isinstance(rows, dict): return rows.get(key)
    return next((x for x in rows or [] if isinstance(x, dict) and str(x.get("id") or x.get("name")) == key), None)


def apply(root, part: dict) -> tuple:
    """Merge {path: translation} (blank values skipped). -> (written, skipped)."""
    root = Path(root); af, pf = root / layout.REMEMBER / "adaptation.yaml", root / layout.DESIGN / "world_plan.yaml"
    A, W = _y(af), _y(pf); n = s = 0
    for path, val in (part or {}).items():
        if not isinstance(val, str) or not val.strip(): s += 1; continue
        ps = str(path).split(".")
        if ps[0] == "plan":
            x = _find((W.get("world_plan") or {}).get(ps[1]), ps[2]); rest = ps[3:]
        else:
            x = _find(A.get(ps[0]), ps[1]); rest = ps[2:]
        if len(rest) == 3 and isinstance(x, dict):                       # <list field>.<index>.<text_xx>
            lst = x.get(rest[0]) or []; i = int(rest[1]) if rest[1].isdigit() else -1
            x = lst[i] if 0 <= i < len(lst) and isinstance(lst[i], dict) else None; rest = rest[2:]
        if not isinstance(x, dict) or len(rest) != 1: raise ValueError(f"不认识的位置：{path}")
        x[rest[0]] = val; n += 1
    if n:
        dump = lambda d: yaml.safe_dump(d, allow_unicode=True, sort_keys=False, width=200)
        if A: af.write_text(dump(A), encoding="utf-8")
        if W: pf.write_text(dump(W), encoding="utf-8")
    return n, s


def main(a) -> int:
    from . import projects
    root = projects.resolve(a.project)
    if a.apply:
        try: n, s = apply(root, yaml.safe_load(Path(a.apply).read_text(encoding="utf-8")) or {})
        except (ValueError, OSError, yaml.YAMLError) as e: print(f"[adaptation] {e}"); return 1
        print(f"[adaptation] 写入 {n} 处，跳过 {s} 处空白"); return 0
    m = missing(root)
    if a.out:
        Path(a.out).write_text("# 填上右边的译文（简体中文 <-> 英文），然后 gameanything adaptation translate --project P --apply 这个文件\n"
                               + yaml.safe_dump({k: "" for k in m}, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
    for k, v in list(m.items())[:40]: print(f"{k}\t{v[:60]}")
    print(f"[adaptation] 缺 {len(m)} 处另一种语言" + (f"，待填文件：{a.out}" if a.out else "") +
          "。自己写好（不调用模型），用 --apply 合并；要用翻译模型得先发 permission 卡（这一版不支持）。")
    return 0 if not m else 1
