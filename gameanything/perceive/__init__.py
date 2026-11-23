"""Stage B of the memory pipeline: one model call per item -> <project>/2_perceive/cards/<id>.json (an observation card).

Two ways to run it:
- agent-native (the user's Claude Code session does the looking): `--emit` writes one request per item to
  2_perceive/requests/<id>.md; the session (or its subagents) reads each request and writes the card JSON to
  2_perceive/agent_output/<id>.json; `--collect` validates them, writes 2_perceive/cards/<id>.json and records them in the ledger;
- headless: one `claude -p` per item (the default mode; needs the Claude Code CLI on PATH or $GAMEANYTHING_CLAUDE).

What leaves the machine: reduced copies of images (normalized images, at most 1600 px; video keyframes, at most 1280 px;
document page renders) and text (transcripts, document text). Never the original files. Every call is recorded in
<project>/privacy_ledger.yaml (what was sent, when, to which backend / model). Nothing is sent without the user's consent
(--yes, or an interactive confirmation after the list of what will be sent); --dry-run only prints that list.
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import yaml

from . import prompts, schemas
from .. import layout
from .backend import BACKENDS

PROMPT_VERSION = 1      # bump when prompts / schemas change; cards from another version are redone
MAX_VIDEO_FRAMES = 8


def build_request(it, project: Path, lang: str):
    """-> (prompt, files sent, text sources sent)"""
    d = it.get("derived") or {}
    ab = lambda p: str(project / p)
    if it["kind"] == "photo":
        return prompts.PHOTO.format(image=ab(d["image"]), lang=lang), [ab(d["image"])], []
    if it["kind"] == "video":
        fr = d.get("frames") or []
        if len(fr) > MAX_VIDEO_FRAMES:
            fr = [fr[round(i * (len(fr) - 1) / (MAX_VIDEO_FRAMES - 1))] for i in range(MAX_VIDEO_FRAMES)]
        txt = (project / d["transcript"]).with_suffix(".txt") if d.get("transcript") else None
        transcript = "\n" + txt.read_text(encoding="utf-8") if txt and txt.exists() else "(none: no audio, or not transcribed)"
        frames = "\n".join(f"  {f['t']:6.1f} -> {ab(f['file'])}" for f in fr)
        p = prompts.VIDEO.format(n=len(fr), duration=it.get("duration") or 0, frames=frames, transcript=transcript, lang=lang)
        return p, [ab(f["file"]) for f in fr], [str(txt)] if txt and txt.exists() else []
    if it["kind"] == "document":
        pages, files, texts = [], [], []
        for pg in d.get("pages") or []:
            t = (project / pg["text"]).read_text(encoding="utf-8") if pg.get("text") else ""
            pages.append(f"--- page {pg['n']}: image {ab(pg['image'])}" + (f"\n{t.strip()}" if t.strip() else "\n(no extractable text)") if pg.get("image")
                         else f"--- page {pg['n']}\n{t.strip()}")
            if pg.get("image"): files.append(ab(pg["image"]))
            if pg.get("text"): texts.append(ab(pg["text"]))
        return prompts.DOCUMENT.format(pages=len(pages), page_list="\n\n".join(pages), lang=lang), files, texts
    raise ValueError(f"no perceive prompt for kind {it['kind']}")


def ledger_append(project: Path, entries):
    f = project / layout.LEDGER
    old = yaml.safe_load(f.read_text(encoding="utf-8")) if f.exists() else None
    old = old or {"note": "every request that sent memory content to a model API (written by gameanything perceive)", "requests": []}
    old["requests"].extend(entries)
    f.write_text(yaml.safe_dump(old, allow_unicode=True, sort_keys=False, width=140), encoding="utf-8")


REQUEST = """# Observation request: {id} ({kind})

{prompt}

Answer by writing ONE JSON object (no comments, no code fence) that matches the JSON Schema below to:
{card}
Use the Write tool. Write nothing else anywhere.

JSON Schema:
{schema}
"""


def emit(project: Path, reqs, lang):
    R, C = layout.requests(project), layout.agent_output(project)
    R.mkdir(parents=True, exist_ok=True); C.mkdir(parents=True, exist_ok=True)
    for it, prompt, files, texts in reqs:
        (R / f"{it['id']}.md").write_text(REQUEST.format(id=it["id"], kind=it["kind"], prompt=prompt, card=C / f"{it['id']}.json",
                                                          schema=json.dumps(schemas.BY_KIND[it["kind"]], ensure_ascii=False, indent=1)), encoding="utf-8")
    print(f"[perceive] {len(reqs)} requests in {R}; cards go to {C}; then run --collect")


def quote_check(it, card, project: Path):
    """Quotes must be verbatim from the transcript (punctuation and spaces aside); -> the ones that are not."""
    import re
    tp = (it.get("derived") or {}).get("transcript")
    if it["kind"] != "video" or not tp or not (project / tp).exists(): return []
    norm = lambda x: re.sub(r"[\s,，。.!！?？、:：;；\"'“”‘’]", "", x)
    full = norm("".join(sg["text"] for sg in json.loads((project / tp).read_text(encoding="utf-8"))["segments"]))
    return [q["text"] for q in card.get("speech", {}).get("notable_quotes", []) if norm(q["text"]) not in full]


def collect(project: Path, items, lang, model):
    """Validate agent-written cards, wrap them like headless cards, record what was sent."""
    import jsonschema
    O = layout.cards(project); C = layout.agent_output(project); O.mkdir(parents=True, exist_ok=True)
    ok, bad, sent = 0, [], []
    for it in items:
        f = C / f"{it['id']}.json"
        if not f.exists(): continue
        try:
            card = json.loads(f.read_text(encoding="utf-8")); jsonschema.validate(card, schemas.BY_KIND[it["kind"]])
        except Exception as e:
            bad.append(f"{it['id']}: {str(e).splitlines()[0][:200]}"); continue
        nv = quote_check(it, card, project)
        if nv: bad.append(f"{it['id']}: quotes not verbatim from the transcript: {nv}"); continue
        _, files, texts = build_request(it, project, lang)
        at = datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")
        (O / f"{it['id']}.json").write_text(json.dumps(
            {"id": it["id"], "kind": it["kind"], "sha256": it["sha256"], "prompt_version": PROMPT_VERSION, "lang": lang,
             "backend": "claude-code-session", "model": model, "at": at, "card": card}, ensure_ascii=False, indent=1), encoding="utf-8")
        sent.append({"id": it["id"], "at": at, "backend": "claude-code-session", "model": model,
                     "images": [Path(x).relative_to(project).as_posix() for x in files], "text": [Path(t).relative_to(project).as_posix() for t in texts]})
        ok += 1
    if sent: ledger_append(project, sent)
    print(f"[perceive] collected {ok} cards" + (f"; {len(bad)} invalid (fix and collect again):" if bad else ""))
    for b in bad: print("  ", b)
    return bad


def perceive(project: Path, model: str, lang="English", backend="claude-code", jobs=4, only=(), yes=False, dry_run=False, mode="call"):
    project = project.resolve()
    pack = yaml.safe_load(open(layout.pack(project), encoding="utf-8"))
    O = layout.cards(project); O.mkdir(parents=True, exist_ok=True)
    todo, cached, excluded = [], 0, []
    for it in pack["items"]:
        if only and it["id"] not in only: continue
        if not it.get("included", True): excluded.append(it["id"]); continue
        if it["kind"] not in schemas.BY_KIND: continue
        f = O / f"{it['id']}.json"
        if f.exists():
            c = json.loads(f.read_text(encoding="utf-8"))
            if c.get("sha256") == it["sha256"] and c.get("prompt_version") == PROMPT_VERSION and c.get("lang") == lang: cached += 1; continue
        todo.append(it)
    if mode == "collect":
        return collect(project, todo, lang, model)
    reqs = [(it, *build_request(it, project, lang)) for it in todo]
    n_files = sum(len(r[2]) for r in reqs); n_text = sum(len(r[3]) for r in reqs)
    print(f"[perceive] {len(reqs)} items to look at ({cached} already done, {len(excluded)} excluded by the user: {', '.join(excluded) or '-'})")
    print(f"[perceive] would send to {backend} / {model}: {n_files} reduced images + {n_text} text files (transcripts, document text)")
    for it, _, files, texts in reqs:
        print(f"  {it['id']:<40} {it['kind']:<9} {len(files)} image(s)" + (f", {len(texts)} text" if texts else ""))
    if dry_run or not reqs:
        return
    if mode == "emit":
        return emit(project, reqs, lang)
    if not yes:
        if not sys.stdin.isatty(): sys.exit("[perceive] not sent: add --yes to confirm (nothing was sent)")
        if input("Send these to the model? [y/N] ").strip().lower() != "y": sys.exit("[perceive] cancelled, nothing was sent")
    be = BACKENDS[backend](model)
    total, fails = 0.0, []

    def one(r):
        it, prompt, files, texts = r
        card, meta = be.call(prompt, schemas.BY_KIND[it["kind"]], project)
        at = datetime.now().isoformat(timespec="seconds")
        (O / f"{it['id']}.json").write_text(json.dumps(
            {"id": it["id"], "kind": it["kind"], "sha256": it["sha256"], "prompt_version": PROMPT_VERSION, "lang": lang,
             "backend": be.name, "model": model, "at": at, **meta, "card": card}, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"id": it["id"], "at": at, "backend": be.name, "model": model,
                "images": [Path(f).relative_to(project).as_posix() for f in files], "text": [Path(t).relative_to(project).as_posix() for t in texts]}, meta

    sent = []
    with ThreadPoolExecutor(jobs) as ex:
        futs = {ex.submit(one, r): r for r in reqs}
        for fu in as_completed(futs):
            it, _, files, texts = futs[fu]; iid = it["id"]
            try:
                entry, meta = fu.result(); sent.append(entry); total += meta.get("cost_usd") or 0
                print(f"  done {iid} ({meta['seconds']}s, ${meta.get('cost_usd') or 0:.3f})", flush=True)
            except Exception as e:                        # the content may have been sent anyway: it goes in the ledger too
                fails.append(iid); print(f"  FAILED {iid}: {e}", flush=True)
                sent.append({"id": iid, "at": datetime.now().isoformat(timespec="seconds"), "backend": be.name, "model": model, "status": "failed",
                             "images": [Path(f).relative_to(project).as_posix() for f in files], "text": [Path(t).relative_to(project).as_posix() for t in texts]})
            if len(sent) % 5 == 0 and sent: ledger_append(project, sent); sent = []   # keep the ledger current during long runs
    if sent: ledger_append(project, sent)
    print(f"[perceive] {len(reqs) - len(fails)} cards written to {O}, cost ${total:.2f}" + (f"; failed: {', '.join(fails)}" if fails else ""))
