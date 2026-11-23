"""The outer loop's two agent steps (docs/feedback-loop.md 2.1, 2.4): the retrospective after a delivered version and the critic before a
delivery. Both run like perceive's agent-native mode: `--emit` writes one self-contained request, an agent on her own login (the builder,
best in a fresh sub-agent context) answers it into the file the request names, `--collect` validates the answer, applies it and logs it.
No model is called from here and no paid key is used.

    retro_emit(root, m) / retro_collect(root, m)     proposals with evidence -> user: profile candidates (off until she turns them on on
                                                     the 我的偏好 page) · game / mode / craft: candidate lessons (the lessons guard applies)
                                                     · system: a request for the coordinator · project: nothing (the STATUS item is it)
    retro_todo(root, before=None)                    delivered versions without a retrospective
    critic_emit(root, m) / critic_collect(root, m)   "would she raise this again?" predictions -> 5_build/<m>/critic.yaml, a `critic` event;
                                                     obeys the version's blind condition (feedback.uses(root, m, "critic"))
    match(root, m, theta)                            predictions vs her complaints on m (loose: kind; strict: kind + target), Brier score
"""
from datetime import datetime
from pathlib import Path

import yaml

from . import feedback as F, layout

PROMPT_VERSION = 1
THETA = 0.5
RETRO_SCOPES = ("user", "game", "mode", "craft", "system", "project")


class RetroError(ValueError):
    pass


def now() -> str: return datetime.now().isoformat(timespec="seconds")
def retro_dir(root, m) -> Path: return Path(root) / layout.FEEDBACK / "retro" / str(m)
def critic_file(root, m) -> Path: return Path(root) / "5_build" / str(m) / "critic.yaml"
def critic_dir(root, m) -> Path: return Path(root) / "5_build" / str(m) / "critic"


def _y(p):
    try: return yaml.safe_load(Path(p).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e: raise RetroError(f"{Path(p).name} 读不了：{e}")


def _dump(x) -> str: return yaml.safe_dump(x, allow_unicode=True, sort_keys=False, width=160)


def _rec(r, keep=("id", "words", "milestone", "class", "kind", "scope", "state", "interpretation", "status_item", "repeat_of")):
    d = {k: r.get(k) for k in keep if r.get(k) not in (None, [], "")}
    a = r.get("anchor") or {}
    if a.get("target"): d["target"] = a["target"]
    if (a.get("chapter") or {}).get("title"): d["chapter"] = a["chapter"]["title"]
    return d


# ---------------------------------------------------------------- retrospective (2.1)
RETRO_PROMPT = """# Retrospective of version {m} (project {pid}, game {game}, kind {kind}; prompt v{pv})

You look back at one delivered version of a game world built for one user, to turn what happened into experience at the right scope.
Use ONLY the data below. Every proposal needs evidence: the record ids it comes from.

Rules:
- Every record listed under REPEATS (she said the same kind of thing again on this version) must get a proposal: why the earlier fix
  did not hold and what to do differently (at the record's scope).
- A resolved record whose fix generalises (it does not depend on her own content) may get a proposal at its scope.
- scope `user` = her personal taste: write it as a preference about her ("场景要…"); it goes to HER private profile only, as a candidate
  she confirms herself. If an entry of her profile below already says it, use `merge_into: <its id>` instead of new text.
- scope `game` / `mode` / `craft` = shared experience other projects read: abstracted, NO personal content (no names of her people, no
  photo or file names, no project paths, no quotes of her words, no places that identify her). Give symptom, cause, fix.
- scope `system` = a bug of the product itself (pages, cards, reports): a short issue for the developers, never prompt text.
- scope `project` = only this project: no proposal needed (the STATUS item already holds it); skip it.
- Never invent evidence. Fewer, better proposals beat many.

DATA (YAML):
{data}

Answer by writing ONE YAML document to:
{out}
with exactly this shape (no other text):
proposals:
- scope: user | game | mode | craft | system
  kind: <a kind of the taxonomy: {kinds}>
  evidence: [f3, f7]              # record ids from the data
  why: repeat | generalises | system_bug
  text: "…"                       # user: the preference (zh); system: the issue; game / mode / craft: one-line summary
  text_en: "…"
  merge_into: p1                  # user only, optional: an existing profile entry that already says it
  symptom: "…"                    # game / mode / craft
  cause: "…"
  fix: "…"
  mode: adaptation                # mode only: the project kind it is about
Use the Write tool. Write nothing else anywhere.
"""


def retro_input(root, m) -> dict:
    """What the retrospective sees: version m's resolved records with their fix and pair, her complaints on m, the repeats on m, the
    retrievals of m's build, her verdicts, her applicable profile entries."""
    from . import profile, projects
    root = Path(root); recs = F.load(root); order = {v["m"]: i for i, v in enumerate(F.versions(root))}; rp = F.repeats(recs, order)
    cfg = projects.config_of(root) or {}; byid = {r["id"]: r for r in recs}
    res = [{**_rec(r), "fix": (r.get("resolution") or {}).get("what"), "pair": (r.get("verification") or {}).get("pair"),
            "her_verdict": (r.get("her_verdict") or {}).get("verdict")} for r in recs if (r.get("resolution") or {}).get("m") == m]
    on_m = [r for r in recs if r.get("milestone") == m and F.is_complaint(r)]
    reps = [{**_rec(r), "earlier": [{**_rec(byid[x]), "fix": (byid[x].get("resolution") or {}).get("what")} for x in rp.get(r["id"], {}).get("loose") or [] if x in byid]}
            for r in on_m if rp.get(r["id"], {}).get("loose")]
    prof = [{k: e.get(k) for k in ("id", "text", "kind", "status", "on")} for e in profile.load(profile.owner_of(root))["entries"]]
    return {"m": m, "project": F.project_id(root), "game": projects.game_of(root), "kind": cfg.get("kind") or "memory",
            "resolved": res, "complaints_on_this_version": [_rec(r) for r in on_m if not rp.get(r["id"], {}).get("loose")], "repeats": reps,
            "retrievals": [{k: e.get(k) for k in ("role", "entries", "n")} for e in F.events(root, "retrieval") if e.get("m") == m],
            "her_profile": prof}


def retro_emit(root, m) -> dict:
    root = Path(root).resolve(); d = retro_dir(root, m); d.mkdir(parents=True, exist_ok=True)
    data = retro_input(root, m)
    if not (data["resolved"] or data["repeats"] or data["complaints_on_this_version"]): raise RetroError(f"{m} 没有可以回顾的记录")
    out = d / "proposals.yaml"; req = d / "request.md"
    req.write_text(RETRO_PROMPT.format(m=m, pid=data["project"], game=data["game"], kind=data["kind"], pv=PROMPT_VERSION, data=_dump(data),
                                       out=out, kinds=", ".join(F.KINDS)), encoding="utf-8")
    F.log_event(root, "retro_emit", m=m, prompt_version=PROMPT_VERSION, resolved=len(data["resolved"]), repeats=len(data["repeats"]),
                condition=F.assignments(root).get(str(m), {}).get("name"))
    return {"m": m, "request": str(req), "out": str(out), "repeats": len(data["repeats"]), "resolved": len(data["resolved"])}


def retro_collect(root, m, model=None) -> dict:
    """Validate proposals.yaml and apply each proposal; -> {applied: [...], refused: [...], uncovered_repeats: [...]}. Written to
    feedback/retro/<m>/applied.yaml and a `retro` metrics event (the raw data of Table 6)."""
    from . import agentd, lessons, profile, projects
    root = Path(root).resolve(); d = retro_dir(root, m); f = d / "proposals.yaml"
    if not f.is_file(): raise RetroError(f"还没有 {f.relative_to(root)}（先 --emit，答完再 --collect）")
    if (d / "applied.yaml").is_file(): raise RetroError(f"{m} 的回顾已经收过了（{(d / 'applied.yaml').relative_to(root)}）")
    doc = _y(f) or {}; props = doc.get("proposals") if isinstance(doc, dict) else None
    if not isinstance(props, list): raise RetroError("proposals.yaml 要有 proposals: 列表")
    recs = {r["id"]: r for r in F.load(root)}; pid = F.project_id(root); owner = profile.owner_of(root)
    game = projects.game_of(root); kind = (projects.config_of(root) or {}).get("kind") or "memory"
    applied, refused = [], []
    for i, p in enumerate(props, 1):
        if not isinstance(p, dict): refused.append({"n": i, "why": "不是一个对象"}); continue
        sc, k, ev = p.get("scope"), p.get("kind"), [str(x) for x in p.get("evidence") or []]
        row = {"n": i, "scope": sc, "kind": k, "evidence": ev, "why": p.get("why")}
        bad = [x for x in ev if x not in recs]
        if sc not in RETRO_SCOPES: refused.append({**row, "refused": f"scope {sc!r}"}); continue
        if k not in F.KINDS: refused.append({**row, "refused": f"kind {k!r}"}); continue
        if not ev or bad: refused.append({**row, "refused": "没有证据" if not ev else f"不认识的记录 {bad}"}); continue
        try:
            if sc == "project": row["result"] = "project: no change (the STATUS item holds it)"
            elif sc == "user":
                into = p.get("merge_into")
                srcs = [f"{pid}:{x}" for x in ev]
                if into:
                    e = profile.update(owner, str(into), sources=srcs); row["result"] = f"profile:{e['id']} (evidence added)"
                else:
                    if not str(p.get("text") or "").strip(): raise RetroError("user 提议要有 text")
                    e = profile.add(owner, p["text"], p.get("text_en"), k, sources=srcs, by="retrospective")
                    row["result"] = f"profile:{e['id']} (candidate, off)"
            elif sc == "system":
                txt = str(p.get("text") or "").strip()
                if not txt: raise RetroError("system 提议要有 text")
                rq = agentd.write_request(root, "other", f"[system issue from the retrospective of {m}] {txt}",
                                          details={"type": "system_issue", "m": m, "kind": k, "records": ev, "text_en": p.get("text_en")})
                row["result"] = f"request:{Path(rq).name}"
            else:
                g = game if sc == "game" else None
                sym = str(p.get("symptom") or p.get("text") or "").strip()
                if sc == "mode": sym = f"[{p.get('mode') or kind}] {sym}"
                r = lessons.add(g, "builder", sym, p.get("cause") or "", p.get("fix") or "", evidence=f"retrospective {m}: {len(ev)} feedback record(s) of kind {k}",
                                general=sc != "game", project=root)
                row["result"] = f"lesson:{r['id']} ({r['action']})"
            applied.append(row)
        except (RetroError, lessons.LessonError, profile.ProfileError, ValueError) as x:
            refused.append({**row, "refused": str(x)})
    reps = {r["id"] for r in retro_input(root, m)["repeats"]}
    covered = {x for a in applied for x in a["evidence"]}
    out = {"m": m, "at": now(), "model": model, "prompt_version": PROMPT_VERSION, "applied": applied, "refused": refused,
           "uncovered_repeats": sorted(reps - covered)}
    (d / "applied.yaml").write_text(_dump(out), encoding="utf-8")
    F.log_event(root, "retro", m=m, model=model, prompt_version=PROMPT_VERSION, condition=F.assignments(root).get(str(m), {}).get("name"),
                proposals=[{k: a.get(k) for k in ("scope", "kind", "evidence", "why", "result", "refused")} for a in applied + refused],
                repeats=sorted(reps), uncovered_repeats=out["uncovered_repeats"])
    return out


def retro_todo(root, before=None) -> list:
    """Delivered versions (before `before`, if given) that have records to look back on and no applied retrospective yet."""
    vs = [v["m"] for v in F.versions(root)]
    if before in vs: vs = vs[:vs.index(before)]
    recs = F.load(root); out = []
    for m in vs:
        if (retro_dir(root, m) / "applied.yaml").is_file(): continue
        if any((r.get("resolution") or {}).get("m") == m or (r.get("milestone") == m and F.is_complaint(r)) for r in recs): out.append(m)
    return out


# ---------------------------------------------------------------- critic (2.4)
CRITIC_PROMPT = """# Critic for version {m} before it is delivered (project {pid}, game {game}, kind {kind}; prompt v{pv})

You are a strict critic who knows this user well. Before she sees version {m}, predict what she would complain about, judging from:
her preference profile, what she said about earlier versions (her words verbatim), and the craft checklist. Look at every frame listed
below (Read each file). For each problem you would expect her to raise, give the kind (one row of the taxonomy), the place / object
(target), the frame and the second of the video when you can, your probability p (0-1) that she raises it on this version, and one
sentence. Include low-p ones too (they are needed for calibration). Do not fix anything; only predict.

Taxonomy kinds: {kinds}

DATA (YAML):
{data}

FRAMES of the new version (chapter, second, file):
{frames}

Answer by writing ONE YAML document to:
{out}
with exactly this shape (no other text):
predictions:
- kind: sparse_plain
  target: 客厅                    # or null
  chapter: drawing                # the chapter moment id, or null
  t: 312.0                        # second in the video, or null
  frame: 5_build/{m}/critic/frames/drawing.png    # or null
  p: 0.7
  text: "客厅还是只有几件家具，她两次说过简陋"
Use the Write tool. Write nothing else anywhere.
"""


def frames(root, m, n_full=6) -> list:
    """A frame per chapter (its middle) of version m's video, else n_full frames over the whole video: [{chapter, t, file}] (written once)."""
    from .delivery import load_play, find_video
    root = Path(root); play = root / "5_build" / str(m) / "play"; d = load_play(play); vid = find_video(play, d.get("video"))
    if not vid: return []
    try:
        import av
        with av.open(str(play / vid)) as c: dur = float(c.duration / 1e6) if c.duration else None
    except Exception: dur = None
    chs = [c for c in d.get("chapters") or [] if c.get("moment") not in (None, "full")]
    pts = []
    if chs:
        for i, c in enumerate(chs):
            end = chs[i + 1]["t"] if i + 1 < len(chs) else (dur or c["t"] + 10)
            pts.append((c["moment"], c["t"] + max(0.0, (end - c["t"]) / 2)))
    elif dur: pts = [(f"full{i + 1}", dur * (i + 0.5) / n_full) for i in range(n_full)]
    out = []
    for name, t in pts:
        f = critic_dir(root, m) / "frames" / f"{name}.png"
        if f.is_file() or F.frame_at(play / vid, t, f): out.append({"chapter": name, "t": round(t, 1), "file": f.relative_to(root).as_posix()})
    return out


def critic_input(root, m) -> dict:
    """Everything the critic sees: F.critic_input (her complaints before m, her applicable preferences) + the recheck checklist."""
    from . import devstatus, projects
    root = Path(root); base = F.critic_input(root, m)
    try: st, _ = devstatus.load(root); chk = [x.get("text") for x in st.get("recheck") or [] if x.get("text")]
    except Exception: chk = []
    cfg = projects.config_of(root) or {}
    return {"m": m, "project": F.project_id(root), "game": projects.game_of(root), "kind": cfg.get("kind") or "memory",
            "her_earlier_complaints": [_rec(r) for r in base["records"]],
            "her_preferences": [{k: e.get(k) for k in ("id", "text", "kind")} for e in base["preferences"]], "craft_checklist": chk}


def critic_emit(root, m) -> dict:
    """The critic request of version m, or {skip: True} when m's condition has no critic (said to the builder only as 「不用」)."""
    root = Path(root).resolve()
    if not F.uses(root, m, "critic"):
        F.log_event(root, "critic_skip", m=m); return {"skip": True, "m": m}
    data = critic_input(root, m); fr = frames(root, m)
    d = critic_dir(root, m); d.mkdir(parents=True, exist_ok=True); req = d / "request.md"; out = critic_file(root, m)
    req.write_text(CRITIC_PROMPT.format(m=m, pid=data["project"], game=data["game"], kind=data["kind"], pv=PROMPT_VERSION, kinds=", ".join(F.KINDS),
                                        data=_dump(data), frames="\n".join(f"- {x['chapter']}  {x['t']}s  {root / x['file']}" for x in fr) or "(no video yet)",
                                        out=out), encoding="utf-8")
    F.log_event(root, "critic_emit", m=m, prompt_version=PROMPT_VERSION, frames=len(fr), records=len(data["her_earlier_complaints"]),
                preferences=[p["id"] for p in data["her_preferences"]])
    return {"skip": False, "m": m, "request": str(req), "out": str(out), "frames": len(fr)}


def critic_collect(root, m, model=None) -> dict:
    """Validate 5_build/<m>/critic.yaml, log every prediction (`critic` event); -> {predictions, high: the ones with p >= THETA}."""
    root = Path(root).resolve(); f = critic_file(root, m)
    if not f.is_file(): raise RetroError(f"还没有 {f.relative_to(root)}（先 --emit，答完再 --collect）")
    doc = _y(f) or {}; ps = doc.get("predictions") if isinstance(doc, dict) else None
    if not isinstance(ps, list): raise RetroError("critic.yaml 要有 predictions: 列表")
    good, bad = [], []
    for i, p in enumerate(ps, 1):
        try: pv = float(p.get("p"))
        except (TypeError, ValueError, AttributeError): bad.append(f"第 {i} 条没有 p"); continue
        if p.get("kind") not in F.KINDS or not 0 <= pv <= 1: bad.append(f"第 {i} 条的 kind / p 不对"); continue
        good.append({"kind": p["kind"], "target": p.get("target"), "chapter": p.get("chapter"), "t": p.get("t"), "frame": p.get("frame"), "p": pv, "text": p.get("text")})
    if bad and not good: raise RetroError("；".join(bad[:5]))
    n = sum(1 for e in F.events(root, "critic") if e.get("m") == m)
    doc.update({"m": m, "collected": now(), "model": model, "prompt_version": PROMPT_VERSION, "predictions": good})
    f.write_text("# 交付前的预评（gameanything feedback critic 写的；docs/feedback-loop.md 2.4）\n" + _dump(doc), encoding="utf-8")
    F.log_event(root, "critic", m=m, model=model, prompt_version=PROMPT_VERSION, theta=THETA, collect=n + 1,
                predictions=[{k: p.get(k) for k in ("kind", "target", "chapter", "t", "p")} for p in good])
    return {"m": m, "predictions": good, "high": [p for p in good if p["p"] >= THETA], "problems": bad}


def match(root, m, theta=THETA, preds=None) -> dict:
    """M7 for version m: predictions with p >= theta vs her complaints on m. Loose = same kind; strict = same kind and the same target
    (or chapter). Brier score over all predictions (outcome: a complaint of that kind, strict: and target, on m). Before her feedback on m
    is in, recall is meaningless: `her_records` says how many there are."""
    if preds is None:
        d = F._y(critic_file(root, m)) or {}; preds = (d.get("predictions") or []) if isinstance(d, dict) else []
    C = [r for r in F.load(root) if F.is_complaint(r) and r.get("milestone") == m]
    def hit(p, r, strict):
        if r.get("kind") != p.get("kind"): return False
        if not strict: return True
        a = r.get("anchor") or {}
        return bool((p.get("target") and a.get("target") == p.get("target")) or (p.get("chapter") and (a.get("chapter") or {}).get("moment") == p.get("chapter")))
    out = {"m": m, "theta": theta, "predictions": len(preds), "her_records": len(C)}
    for name, strict in (("loose", False), ("strict", True)):
        hi = [p for p in preds if float(p.get("p") or 0) >= theta]
        tp_p = sum(1 for p in hi if any(hit(p, r, strict) for r in C))
        tp_r = sum(1 for r in C if any(hit(p, r, strict) for p in hi))
        prec = tp_p / len(hi) if hi else None; rec = tp_r / len(C) if C else None
        f1 = 2 * prec * rec / (prec + rec) if prec and rec else (0.0 if prec == 0 or rec == 0 else None)
        brier = (sum((float(p.get("p") or 0) - (1.0 if any(hit(p, r, strict) for r in C) else 0.0)) ** 2 for p in preds) / len(preds)) if preds else None
        out[name] = {"precision": prec, "recall": rec, "f1": f1, "brier": brier, "tp_predictions": tp_p, "tp_records": tp_r, "high": len(hi)}
    return out
