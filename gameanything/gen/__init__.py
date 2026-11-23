"""One card-checked interface for paid (and local) asset generation, instead of a gen_<tool>.py per project.

    gameanything gen list [--project P]                         adapters, capabilities, models, whether the key is there (never the value)
    gameanything gen estimate --tool fal:image --n 4            the go card's estimate (cost_usd range, wall_h, price source)
    gameanything gen request --project P --tool meshy:image-to-3d --inputs 4_design/gen/ucsd3d.yaml --permission K --go K
                                                       (a resident: queue only; agentd checks both cards, then runs it in-process)

A tool is <adapter>:<capability>. Capabilities: image, edit (variants / edits of reference pictures), image-to-3d, text-to-3d, sfx,
music, voice, video. Adapters: fal, meshy, openai, openrouter (paid, the project owner's key: users.gen_env), comfy (local).

The inputs file (yaml / json, inside the project) — or --prompt / --image / --name for one job:
    model: fal-ai/nano-banana-2        # optional: the adapter's default otherwise (must be in its price table)
    out: targets                       # under 4_design/ (default art/gen, art/3d, audio/gen, video/gen by capability)
    options: {aspect_ratio: "16:9"}    # for every job; a job's own options win
    redo: false                        # true: draw again even when the output exists
    jobs:
      - {name: m_harbor_A, prompt: "...", images: [2_perceive/landmark_refs/harbor/1.jpg], n: 1, options: {}}
Outputs: <project>/4_design/<out>/<name>.<ext> (3D: <out>/<name>/model.glb ...), <out>/index.yaml (adapter, model, files + sha256,
what was sent, cards, cost), and one privacy_ledger.yaml `requests:` entry per call (or a `local:` line for ComfyUI).
"""
import fnmatch
import re
import time
from datetime import datetime
from pathlib import Path

import yaml

from .base import CAPS, DEFAULT_OUT, KIND, NEEDS_IMAGES, NEEDS_PROMPT, AdapterError, Ctx
from .comfy import Comfy
from .fal import Fal
from .meshy import Meshy
from .openai_image import OpenAIImage
from .openrouter import OpenRouter

ADAPTERS = {a.name: a for a in (Fal(), Meshy(), OpenAIImage(), OpenRouter(), Comfy())}
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,79}$")
MAX_JOBS = 100
MAX_N = 8
MAX_PROMPT = 4000
WALL_MIN = {"image": (0.2, 1.5), "3d": (2, 8), "audio": (0.2, 2), "video": (2, 10)}      # minutes per call (rough, for the go card)
NO_SEND = ("conversation", "config", "0_inbox")                                          # never sent: the chat, settings, raw uploads


class GenSpecError(ValueError):
    pass


def is_adapter_tool(tool) -> bool: return ":" in str(tool or "")


def parse_tool(tool):
    a, _, c = str(tool or "").strip().partition(":")
    if a not in ADAPTERS: raise GenSpecError(f"没有这个生成工具 {a!r}（有：{', '.join(ADAPTERS)}）/ unknown adapter {a!r}")
    ad = ADAPTERS[a]
    if c not in ad.caps: raise GenSpecError(f"{a} 不能做 {c!r}（能做：{', '.join(ad.caps)}）/ {a} cannot do {c!r}")
    return ad, c


# ---------------------------------------------------------------- the inputs: shape and paths
def _inside(root: Path, rel, what) -> str:
    rel = str(rel or "").strip().replace("\\", "/")
    if not rel or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel): raise GenSpecError(f"{what} 应该是项目里的相对路径（收到 {rel or '空'}）")
    p = (root / rel).resolve()
    try: parts = p.relative_to(root).parts
    except ValueError: raise GenSpecError(f"{what} {rel} 不在项目文件夹里") from None
    if not parts or parts[0] in NO_SEND or any(x.startswith(".") for x in parts): raise GenSpecError(f"{what} {rel} 不能发送（对话、设置、隐藏文件和原始上传都不发）")
    if not p.is_file(): raise GenSpecError(f"找不到 {what} {rel}")
    return "/".join(parts)


def load_inputs(root, path) -> dict:
    root = Path(root).resolve()
    rel = _inside(root, path, "--inputs")
    try: d = yaml.safe_load((root / rel).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e: raise GenSpecError(f"--inputs {rel} 读不了：{e}") from None
    if isinstance(d, list): d = {"jobs": d}
    if not isinstance(d, dict): raise GenSpecError("--inputs 应该是一个带 jobs: 的 yaml / json")
    return {**d, "inputs_file": rel}


def normalize(root, tool, spec: dict) -> dict:
    """-> the checked request spec {tool, model, out, redo, jobs: [{name, prompt, images, n, options}]}; GenSpecError otherwise."""
    root = Path(root).resolve(); ad, cap = parse_tool(tool); spec = dict(spec or {})
    model = spec.get("model") or None
    try: ad.model(cap, model)
    except AdapterError as e: raise GenSpecError(str(e)) from None
    kind = KIND[cap]
    out = str(spec.get("out") or DEFAULT_OUT[kind]).strip().replace("\\", "/").strip("/")
    outp = (root / "4_design" / out).resolve()
    try: outp.relative_to((root / "4_design").resolve())
    except ValueError: raise GenSpecError(f"out {out} 必须在 4_design/ 里面") from None
    if out in ("", ".") or any(x.startswith(".") for x in Path(out).parts) or out.split("/")[0] == "tools": raise GenSpecError(f"out {out!r} 不行：用 targets、art/... 或 3d 这样的子文件夹")
    common = spec.get("options") or {}
    if not isinstance(common, dict): raise GenSpecError("options 应该是 key: value")
    jobs = spec.get("jobs") or []
    if not isinstance(jobs, list) or not jobs: raise GenSpecError("没有要生成的东西（jobs 是空的；或者用 --prompt / --image）")
    if len(jobs) > MAX_JOBS: raise GenSpecError(f"一次最多 {MAX_JOBS} 个 job")
    seen, norm = set(), []
    for j in jobs:
        if not isinstance(j, dict): raise GenSpecError("每个 job 应该是 {name, prompt, images, n, options}")
        name = str(j.get("name") or "").strip()
        if not NAME_RE.match(name): raise GenSpecError(f"job 名字 {name!r} 不行（字母、数字、_ - .，不超过 80 个字符）")
        if name.lower() in seen: raise GenSpecError(f"job 名字 {name} 重复了")
        seen.add(name.lower())
        prompt = j.get("prompt")
        if prompt is not None and not isinstance(prompt, str): raise GenSpecError(f"{name}: prompt 应该是文字")
        if prompt and len(prompt) > MAX_PROMPT: raise GenSpecError(f"{name}: prompt 太长（最多 {MAX_PROMPT} 个字符）")
        if cap in NEEDS_PROMPT and not (prompt or "").strip(): raise GenSpecError(f"{name}: {cap} 需要 prompt")
        imgs = j.get("images") or []
        if isinstance(imgs, str): imgs = [imgs]
        imgs = [_inside(root, x, f"{name} 的图") for x in imgs]
        if cap in NEEDS_IMAGES and not imgs: raise GenSpecError(f"{name}: {cap} 需要至少一张图（images）")
        if cap == "image-to-3d" and len(imgs) > 1: raise GenSpecError(f"{name}: image-to-3d 一个 job 只用一张图")
        if ad.caps[cap].sends == "text" and imgs: raise GenSpecError(f"{name}: {tool} 只发文字；要用参考图请用 {ad.name}:edit")
        o = {**common, **(j.get("options") or {})}
        if o.get("workflow"): o["workflow"] = _inside(root, o["workflow"], f"{name} 的 workflow")
        n = j.get("n", spec.get("n", 1))
        if not (isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= MAX_N): raise GenSpecError(f"{name}: n 应该是 1 到 {MAX_N}")
        if KIND[cap] == "3d" and n != 1: raise GenSpecError(f"{name}: 3D 一个 job 只出一个模型（n 应该是 1）")
        norm.append({"name": name, "prompt": prompt, "images": imgs, "n": n, "options": o})
    return {"tool": f"{ad.name}:{cap}", "model": model or ad.caps[cap].default, "out": out, "redo": bool(spec.get("redo")), "jobs": norm,
            **({"inputs_file": spec["inputs_file"]} if spec.get("inputs_file") else {})}


# ---------------------------------------------------------------- what it may cost
def estimate(tool, n=1, model=None, options=None, jobs=None) -> dict:
    """The go card's estimate for n outputs (or for these normalized jobs). -> {estimate (card shape), cost_usd_max, price, ...}."""
    ad, cap = parse_tool(tool)
    try: m = ad.model(cap, model)
    except AdapterError as e: raise GenSpecError(str(e)) from None
    lo = hi = 0.0; calls = 0; outs = 0
    for j in jobs or [{"n": int(n or 1), "options": options or {}}]:
        p = ad.price(cap, m.id, j.get("options")); k = int(j.get("n") or 1)
        lo += p.lo * k; hi += p.hi * k; outs += k; calls += 1 if ad.name in ("fal", "openai") else k
    p = ad.price(cap, m.id, options)
    w = WALL_MIN[KIND[cap]]; wall = [round(w[0] * calls / 60, 2), round(max(w[1] * calls / 60, 0.05), 2)]
    lo, hi = round(lo, 2), round(max(hi, lo), 2)
    if hi > 0 and hi == lo: hi = round(hi + 0.01, 2)
    paid = not ad.local
    note_zh = (f"{ad.title} {m.id}，{outs} 个输出，每个约 ${p.lo:g}–{p.hi:g}（{p.source}）" + ("" if p.verified else "；价格没有核实过") if paid
               else f"{ad.title}：在这台电脑上跑，不花钱，不发送任何东西")
    note_en = (f"{ad.title} {m.id}, {outs} outputs, about ${p.lo:g}-{p.hi:g} each ({p.source})" + ("" if p.verified else "; price not verified") if paid
               else f"{ad.title}: runs on this computer, no cost, nothing is sent")
    est = {"wall_h": wall, "cost_usd": [lo, hi] if paid else [0, 0], "account": "api", "model": m.id, "note": note_zh}
    return {"tool": f"{ad.name}:{cap}", "model": m.id, "outputs": outs, "calls": calls, "estimate": est, "estimate_en": {**est, "note": note_en},
            "cost_usd_max": hi if paid else 0, "price": {"lo": p.lo, "hi": p.hi, "per": p.per, "source": p.source, "verified": p.verified},
            "to": ad.title, "key": ad.key, "sends": ad.caps[cap].sends}


# ---------------------------------------------------------------- the list
def listing(env=None, http=None) -> list:
    from .. import keys
    rows = []
    for ad in ADAPTERS.values():
        if ad.local:
            a = type(ad)(env) if isinstance(ad, Comfy) else ad
            ok, why = a.available(http)
            key = "no key needed" + ("" if ok else f"; {why}")
        else:
            ok = keys.available(ad.key, env); key = f"{ad.key}: {'yes' if ok else 'no'}"
        for c, cap in ad.caps.items():
            m = cap.models[cap.default]; p = m.price
            rows.append({"tool": f"{ad.name}:{c}", "ready": ok, "key": key, "model": m.id, "models": list(cap.models),
                         "price": f"${p.lo:g}-{p.hi:g}/{p.per}" + ("" if p.verified else " (unverified)"), "sends": cap.sends})
    return rows


# ---------------------------------------------------------------- running (agentd only: genrun.py calls this after both cards)
def _ledger(root: Path, entry: dict, local=False):
    from .. import layout, osdirs
    lk = root / "conversation" / ".ledger.lock"; lk.parent.mkdir(parents=True, exist_ok=True)
    with open(lk, "a", encoding="utf-8") as f:
        osdirs.lock(f)
        p = root / layout.LEDGER
        try: d = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else None
        except yaml.YAMLError: d = None; p.replace(p.with_name(p.name + f".broken-{int(time.time())}"))
        if isinstance(d, list): d = {"requests": d}
        d = d if isinstance(d, dict) else {}
        d.setdefault("requests", [])
        (d.setdefault("local", []) if local else d["requests"]).append(entry)
        tmp = p.with_name(f".{p.name}.tmp"); tmp.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8"); tmp.replace(p)


def _index(root: Path, outdir: Path, name: str, item: dict):
    f = outdir / "index.yaml"
    try: d = yaml.safe_load(f.read_text(encoding="utf-8")) if f.exists() else None
    except yaml.YAMLError: d = None
    d = d if isinstance(d, dict) else {}
    d.setdefault("generated_by", "gameanything gen (gameanything/gen): one entry per job, files with sha256")
    d.setdefault("items", {})[name] = item
    outdir.mkdir(parents=True, exist_ok=True)
    tmp = outdir / ".index.yaml.tmp"; tmp.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8"); tmp.replace(f)


def _exists(root, spec, kind, outdir, job):
    if kind == "3d": return (outdir / job["name"] / "model.glb").exists()
    return any(outdir.glob(f"{glob_escape(job['name'])}.*"))


def glob_escape(s): return re.sub(r"([*?\[])", r"[\1]", s)


def run(root, spec: dict, key, http=None, log=print, cards=None, request_id=None, budget_usd=None, poll_secs=5.0, deadline=None,
        progress=None, sleep=time.sleep) -> dict:
    """Run a normalized, card-checked request: every job in turn, files + index + ledger. -> {done, skipped, failed, cost_usd, files}.
    key: the API key value (None for a local adapter). budget_usd: stop before a job once the estimate of what was spent passes it."""
    from . import http as H
    root = Path(root).resolve(); ad, cap = parse_tool(spec["tool"]); kind = KIND[cap]; http = http or H.default()
    outdir = root / "4_design" / spec["out"]; cards = cards or {}
    done, skipped, failed, files, spent = [], [], [], [], 0.0
    for i, job in enumerate(spec["jobs"]):
        if not spec.get("redo") and _exists(root, spec, kind, outdir, job): skipped.append(job["name"]); progress and progress(i, "done"); continue
        p = ad.price(cap, spec["model"], job["options"])
        if budget_usd is not None and spent + p.lo * job["n"] > budget_usd + 1e-9:
            failed.append({"name": job["name"], "error": f"stopped: the go card's budget ${budget_usd:g} would be passed"}); continue
        progress and progress(i, "current")
        ctx = Ctx(root=root, out=outdir / job["name"] if kind == "3d" else outdir, key=key or "", http=http, log=log, poll_secs=poll_secs,
                  deadline=deadline or (time.time() + 3600), sleep=sleep)
        at = datetime.now().isoformat(timespec="seconds"); t0 = time.time()
        unbilled = False
        try:
            r = ad.run(ctx, cap, {**job, "model": spec["model"]}); err = None
        except Exception as e:                                     # one job failing does not stop the others
            r, err = None, f"{type(e).__name__}: {str(e)[:400]}"; unbilled = key_refused(e)
        cost = (r or {}).get("cost_usd")
        est = round(p.hi * job["n"], 4) if not ad.local else 0.0
        spent += cost if isinstance(cost, (int, float)) else (est if r else 0.0 if unbilled else p.lo * job["n"])   # a failed call may still be billed
        sent = {"text": [job["prompt"]] if job.get("prompt") else [], "images": job["images"]}
        entry = {"id": f"gen/{spec['out']}/{job['name']}", "at": at, "backend": ad.name, "model": spec["model"], "tool": spec["tool"],
                 "purpose": f"gameanything gen {spec['tool']} (permission card {cards.get('permission')}, go card {cards.get('go')})",
                 "card": cards.get("permission"), "go": cards.get("go"), "gen_request": request_id, "sent": sent,
                 "status": "ok" if r else f"error: {err}", "cost_usd": cost, "cost_estimate_usd": est,
                 **({"provider_request_id": r.get("request_id")} if r and r.get("request_id") else {}),
                 **({"meta": r["meta"]} if r and r.get("meta") else {})}
        if ad.local: _ledger(root, {"at": at, "what": f"gameanything gen {spec['tool']} {job['name']}", "sent": "nothing", "status": entry["status"]}, local=True)
        else: _ledger(root, entry)
        if not r:
            failed.append({"name": job["name"], "error": err}); log(f"gen {spec['tool']} {job['name']}: {err}"); progress and progress(i, "todo"); continue
        rel = [{"path": f.path.relative_to(root).as_posix(), "sha256": f.sha256, "bytes": f.bytes, "role": f.role} for f in r["files"]]
        _index(root, outdir, job["name"], {"adapter": ad.name, "capability": cap, "model": spec["model"], "made": at, "secs": round(time.time() - t0, 1),
                                           "prompt": job.get("prompt"), "images_sent": job["images"], "options": job["options"], "n": job["n"],
                                           "files": rel, "cost_usd": cost, "cost_estimate_usd": est, "provider_request_id": r.get("request_id"),
                                           "meta": r.get("meta") or {}, "permission_card": cards.get("permission"), "go_card": cards.get("go"),
                                           "gen_request": request_id})
        files += [x["path"] for x in rel]; done.append(job["name"]); log(f"gen {spec['tool']} {job['name']}: {len(rel)} files")
        progress and progress(i, "done")
    return {"done": done, "skipped": skipped, "failed": failed, "files": files, "cost_usd": round(spent, 3)}


def key_refused(e) -> bool:
    """The provider refused the key itself (401 / 403, or a 400 saying the key is invalid): nothing was started, nothing billed."""
    from .http import GenHTTPError
    if not isinstance(e, GenHTTPError): return False
    return e.status in (401, 403) or (e.status == 400 and bool(re.search(r"api[ _]?key", e.detail, re.I)))


def covered(path: str, patterns) -> bool:
    """A project-relative path matches one of the permission card's `files` globs (`2_perceive/landmark_refs/**` style)."""
    for pat in patterns or []:
        pat = str(pat).strip().replace("\\", "/").lstrip("./")
        if fnmatch.fnmatchcase(path, pat) or (pat.endswith("/**") and path.startswith(pat[:-2])) or path == pat.rstrip("/"): return True
        if pat.endswith("/") and path.startswith(pat): return True
    return False


__all__ = ["ADAPTERS", "CAPS", "GenSpecError", "AdapterError", "parse_tool", "is_adapter_tool", "normalize", "load_inputs", "estimate",
           "listing", "run", "covered"]
