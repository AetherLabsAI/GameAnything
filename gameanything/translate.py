"""English for the project's own content (agent messages, cards, moment titles, names, checks, plan ...).

The translations are written by the agent session (never by a model call from this tool); the tool only stores and applies them:
    <project>/i18n/en.yaml          { "<Chinese source string>": "<English>" }, exact-string map
    thread events (agent only)      optional `text_en` and `card_en` (same shape as `card`) next to `text` / `card`
Applied when a page asks for lang=en; a string with no translation stays as it is. The user's own words (user text events, answers,
review notes, plan quotes) are never mapped. `missing` lists what the UI can show with no English yet; `add` merges a filled file.
"""
import re
from pathlib import Path

import yaml

CJK = re.compile(r"[一-鿿]")
SKIP_KEYS = {"id", "kind", "key", "url", "image", "open", "media", "multi", "n", "state", "file"}   # structure, not display text
HEADER = ("# English for this project's content (gameanything i18n). Key = the Chinese source string, exactly; value = the English shown when the UI is in EN.\n"
          "# The user's own words are never translated. Edit freely; `gameanything i18n missing` lists what is still untranslated.\n")
_cache = {}


def store_path(root, lang="en") -> Path:
    return Path(root) / "i18n" / f"{lang}.yaml"


def load(root, lang="en") -> dict:
    p = store_path(root, lang)
    try: mt = p.stat().st_mtime_ns
    except FileNotFoundError: return {}
    hit = _cache.get(p)
    if hit and hit[0] == mt: return hit[1]
    try: d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError: d = {}
    d = {str(k): v for k, v in d.items() if isinstance(v, str)} if isinstance(d, dict) else {}
    _cache[p] = (mt, d)
    return d


class Tr:
    """tr(s) -> the English of s when lang is en and the store has it, else s. tr.deep(obj) maps every string leaf of a dict / list."""

    def __init__(self, root, lang="zh"):
        self.on = lang == "en"; self.m = load(root, "en") if self.on else {}

    def __call__(self, s):
        return self.m.get(s, s) if self.on and isinstance(s, str) else s

    def deep(self, o):
        if not self.on: return o
        if isinstance(o, str): return self.m.get(o, o)
        if isinstance(o, list): return [self.deep(x) for x in o]
        if isinstance(o, dict): return {k: (v if k in SKIP_KEYS else self.deep(v)) for k, v in o.items()}
        return o


def localize(events, root, lang):
    """Thread events as the page should see them. Agent events: text_en / card_en (else the store); user events: only the context labels
    (moment / person titles) are mapped, never the words. The *_en fields themselves are not sent."""
    tr = Tr(root, lang); out = []
    for e in events:
        e = dict(e); te = e.pop("text_en", None); ce = e.pop("card_en", None)
        if tr.on:
            if e.get("from") in ("agent", "system"):
                if "text" in e: e["text"] = te or tr(e["text"])
                if isinstance(e.get("card"), dict):
                    from .conversation import en_fields, merge_en
                    if not isinstance(ce, dict): ce = en_fields(e["card"])          # an old card written with title_en … (no card_en saved)
                    # the English overlay over the card (deep: the pictures, urls and numbers it leaves out stay); words it leaves out: the store
                    e["card"] = merge_en(tr.deep(e["card"]), ce) if isinstance(ce, dict) else tr.deep(e["card"])
            else:
                if e.get("auto") and te: e["text"] = te                  # page-generated line, not the user's words
                if e.get("context"):
                    e["context"] = [{**c, "label": tr(c["label"])} if isinstance(c, dict) and c.get("label") else c for c in e["context"]]
        out.append(e)
    return out


# ---- completeness ----
def _scan(o, found, skip=()):
    if isinstance(o, str):
        if CJK.search(o): found.setdefault(o, None)
    elif isinstance(o, list):
        for x in o: _scan(x, found, skip)
    elif isinstance(o, dict):
        for k, v in o.items():
            if k not in skip and k not in SKIP_KEYS: _scan(v, found, skip)


def missing(root, lang="en") -> dict:
    """{Chinese source string: ""} for every content string the pages show in `lang` that has no translation yet (walks what the APIs return)."""
    from .conversation import Thread
    from .ui import Project, screens
    root = Path(root); found = {}; P = Project(root); th = Thread(root)
    sh = screens.shell(root, lang); _scan({k: sh[k] for k in ("title", "persistent", "rounds", "status")}, found)
    d = screens.day(root, lang); _scan(d, found)
    g = screens.gather(root, P.inbox, P.upload_max, lang); g.pop("inbox", None); _scan(g, found)
    b = screens.board_state(root, lang); _scan({"title": b["title"], "segments": b["segments"], "moments": b["moments"]}, found)
    pl = screens.plan_state(root, lang); _scan(pl, found, skip=("review", "quote"))
    fe = screens.feature_state(root, lang); _scan({k: fe[k] for k in ("title", "goal", "items", "open_questions")}, found)
    gp = screens.gameplay_state(root, lang); _scan({k: gp[k] for k in ("title", "mapping", "core", "content")}, found, skip=("art", "art_ref"))
    ds = screens.devstatus_state(root, lang); _scan({k: ds[k] for k in ("items", "known_issues", "regressions", "recheck", "decisions")}, found)
    lk = P.looks_state(lang); _scan(lk, found, skip=("review", "look", "bases"))
    for m in P.builds():
        s = P.play_state(m, lang); _scan({"play": {k: s["play"].get(k) for k in ("chapters", "checks", "sounds")}, "moment_titles": s["moment_titles"]}, found)
    for e in localize(th.events(), root, lang):
        if e.get("from") == "agent" and lang == "en":
            raw = next((x for x in th.events() if x["id"] == e["id"]), {})
            if not raw.get("text_en"): _scan(e.get("text"), found)
            if not raw.get("card_en"): _scan(e.get("card"), found)
        else:
            _scan([c.get("label") for c in e.get("context") or [] if isinstance(c, dict)], found)
    have = set(load(root, lang).values())
    return {k: "" for k in found if k not in have}


def add(root, part: dict, lang="en") -> tuple:
    """Merge {zh: en} into the store (existing keys are overwritten); blank values are skipped. -> (added, replaced, skipped)."""
    if not isinstance(part, dict): raise ValueError("the file must be a mapping {中文: English}")
    for k, v in part.items():
        if not isinstance(k, str) or not isinstance(v, str): raise ValueError(f"not a string-to-string mapping at: {k!r}")
    cur = dict(load(root, lang)); a = r = s = 0
    for k, v in part.items():
        if not v.strip(): s += 1; continue
        if k in cur: r += cur[k] != v
        else: a += 1
        cur[k] = v
    p = store_path(root, lang); p.parent.mkdir(exist_ok=True)
    tmp = p.with_suffix(".tmp"); tmp.write_text(HEADER + yaml.safe_dump(cur, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8"); tmp.replace(p)
    return a, r, s
