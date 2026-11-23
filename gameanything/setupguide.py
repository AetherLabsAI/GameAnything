"""The setting a project works in and the guide an agent reads for it (decided 2026-10-29).

A setting is a system and a mode: linux / mac / windows x sandbox / native, plus server-sandbox for the hub (several users on one
server, where the server's system decides). Each setting has ONE guide, the single source of truth for its notes (prerequisites,
settings to change, checks, resources, the per-game table, pitfalls, what to tell the user):

    skills/gameanything/references/setups/<system>-<mode>.md     and  server-sandbox.md

    gameanything setup guide [--project P] [--mode sandbox|native] [--system S] [--hub] [--json] [--no-record]
        detects the computer (sandbox.detect, hub-aware), picks the mode (--mode, else the project's build_mode: lab = sandbox,
        else the recommended one for the project's game on this computer, sandbox.sources), prints the guide's path, its checklist
        and the project game's verdict, and records `setup: {system, arch, mode, where, guide, host, guide_read_at}` in the
        project's config/project.yaml. flow.py's go step needs that record (c_setup) before the first build or game launch.
    gameanything setup tables [--write]
        the per-game tables inside the guides, generated from sandbox.sources() (between the setup-games markers);
        without --write: exit 1 and list the guides whose table is out of date (tests/test_setupguide.py runs the same check)

The guides are written for an agent: read the whole file the command names, then follow its checklist.
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

from . import games as registry, layout, osdirs, projects, sandbox, shipped

MODES = ("sandbox", "native")
OF_BUILD_MODE = {"lab": "sandbox", "native": "native"}      # config/project.yaml build_mode -> the guide's mode
GUIDES = tuple(f"{s}-{m}" for s in sandbox.SYSTEMS for m in MODES) + ("server-sandbox",)
DIR = shipped.SKILL / "references" / "setups"
BEGIN, END = "<!-- setup-games:begin (gameanything setup tables --write) -->", "<!-- setup-games:end -->"
SYS_EN = {"linux": "Linux", "mac": "Mac", "windows": "Windows"}


def guide_name(system, mode, where="this_computer") -> str:
    if mode not in MODES: raise ValueError(f"mode must be one of {', '.join(MODES)}")
    if where == "server" and mode == "sandbox": return "server-sandbox"
    if system not in sandbox.SYSTEMS: raise ValueError(f"system must be one of {', '.join(sandbox.SYSTEMS)}")
    return f"{system}-{mode}"


def guide_path(name, root=None) -> Path:
    if name == "server-sandbox" and root is None:          # the hub's guide is internal (internal/setups/), not in the skill
        from . import internal_docs
        return internal_docs.SERVER_GUIDE
    return Path(root or DIR) / f"{name}.md"


def checklist(name, root=None) -> list:
    """The bullets of the guide's `## Checklist` section (top-level `- ` lines), the short form the command prints."""
    try: t = guide_path(name, root).read_text(encoding="utf-8")
    except OSError: return []
    m = re.search(r"(?ms)^## Checklist\s*\n(.*?)(?=^## |\Z)", t)
    return [ln[2:].strip() for ln in (m.group(1).splitlines() if m else []) if ln.startswith("- ")]


# ---------------------------------------------------------------- the verdict of one game in one setting
def _first(s: str) -> str:
    """The first sentence of a sandbox.py reason (the tables keep one line per game)."""
    s = (s or "").strip()
    i = s.find(". ")
    return s[:i + 1] if i > 0 else s


def _verified(game, system) -> str:
    v = [x for x in (registry.games().get(game) or {}).get("verified") or [] if isinstance(x, dict)]
    d = sorted(str(x.get("date")) for x in v if x.get("system") == system and x.get("result") == "pass")
    return d[-1] if d else ""


def verdict(game, mode, m) -> dict:
    """{game, mode, verdict: recommended | available | not available, source, why, image, verified, warnings} of one game in one setting
    (m: a machine dict from sandbox.detect() or sandbox.machine()). Derived from sandbox.sources(): the guides' tables and the command
    say the same thing as the new-project wizard."""
    src = sandbox.sources(game, m)
    out = {"game": game, "mode": mode, "verdict": "not available", "source": None, "why": "", "image": game in sandbox.IMAGES,
           "verified": _verified(game, m.get("system")) if mode == "native" else "",
           "warnings": [w["en"] for w in src.get("warnings") or []]}
    if src.get("ask_system"):
        out["why"] = "The system was not detected: ask the user (Linux, Mac or Windows) and run again with --system"; return out
    opts = [o for o in src.get("options") or [] if o["source"] != "native"]
    usable = [o for o in opts if o["available"]]
    if mode == "sandbox":
        if not src["offered"]: out["why"] = src.get("reason_en", ""); return out
        if not usable: out["why"] = _first(opts[0]["reason_en"]) if opts else ""; return out
        rec = next((o for o in usable if o["recommended"]), None)
        o = rec or usable[0]
        out.update(verdict="recommended" if rec else "available", source=o["source"], why=_first(o["reason_en"]))
        return out
    if game not in registry.native_classes():
        out["why"] = "No native adapter for this game yet"; return out
    if not src["offered"]:
        out.update(verdict="recommended", why="Not in the sandbox wizard: native mode is the way for this game")
    elif src.get("recommended") == "native":
        out.update(verdict="recommended", why=_first(sandbox.NATIVE_MAC[1]))
    elif not usable:
        out.update(verdict="recommended", why="The sandbox cannot run here yet (Docker): native mode works now")
    else:
        out.update(verdict="available", why=f"The sandbox is recommended on {SYS_EN.get(m.get('system'), m.get('system'))}; "
                                             "native installs into the user's own game (saves backed up first, only the Mods folder changes)")
    return out


def table_machine(name) -> dict:
    """The machine a guide's table is for: Docker running, 32 GB; a Mac with Apple silicon (the common case); the hub's server is Linux."""
    if name == "server-sandbox": return sandbox.machine("linux", where="server")
    system = name.split("-")[0]
    return sandbox.machine(system, arch="arm64" if system == "mac" else "x86_64")


def table(name) -> str:
    """The markdown table of every game in one guide's setting (registry order)."""
    mode = "sandbox" if name.endswith("-sandbox") else "native"
    m = table_machine(name)
    if mode == "sandbox":
        L = ["| Game | Verdict | Game source | Runtime image | Why |", "|---|---|---|---|---|"]
    else:
        L = ["| Game | Verdict | Verified on this system | Why |", "|---|---|---|---|"]
    for gid, spec in registry.games().items():
        v = verdict(gid, mode, m)
        why = v["why"].replace("|", "/")
        if mode == "sandbox":
            arm = m.get("arch") == "arm64"           # Apple silicon: no published arm64 image, the chain is built there (FEX)
            img = ((f"built on this Mac for arm64 (FEX); {sandbox.FEX_TESTED.get(gid, 'not tested yet')}") if arm else
                   ("published, smoke mod tested on plain Docker (2026-10-30)" if gid in sandbox.IMAGE_TESTED else
                    "published, built only") if gid in sandbox.PUBLISHED else
                   "recipe only, not published" if v["image"] else "not built yet")
            src = {"mount": "the server's copy, mounted read-only" if name == "server-sandbox" else "own folder, mounted read-only",
                   "steam": "Steam download in the sandbox", "ea": "EA App download in the sandbox",
                   "microsoft": "Microsoft account download (files only)"}.get(v["source"], "-")
            L.append(f"| {spec.title} (`{gid}`) | {v['verdict']} | {src} | {img if v['verdict'] != 'not available' else '-'} | {why} |")
        else:
            L.append(f"| {spec.title} (`{gid}`) | {v['verdict']} | {v['verified'] or 'not yet verified'} | {why} |")
    return "\n".join(L)


def tables(write=False, root=None) -> list:
    """Refresh (write=True) or check the generated table of every guide. -> the guide names that were / are out of date."""
    out = []
    for name in GUIDES:
        f = guide_path(name, root)
        if name == "server-sandbox" and not f.is_file(): continue      # the hub's guide is in internal/: not in a public clone
        t = f.read_text(encoding="utf-8") if f.is_file() else ""
        if BEGIN not in t or END not in t: out.append(name); continue
        head, rest = t.split(BEGIN, 1); _, tail = rest.split(END, 1)
        new = f"{head}{BEGIN}\n{table(name)}\n{END}{tail}"
        if new != t:
            out.append(name)
            if write: f.write_text(new, encoding="utf-8")
    return out


# ---------------------------------------------------------------- the project's setting
def _gamebench_lab(env=None) -> bool:
    """A gamebench lab is set up here (the maintainer's servers: seats, a broker): its server guide, not the user's own sandbox."""
    from . import buildmode
    try: return buildmode.lab_kit(env)
    except Exception: return False


def is_hub(root=None, env=None) -> bool:
    """The hub (several users on one server): a run started for a hub user (GAMEANYTHING_USER) or a project with an owner."""
    import os
    env = os.environ if env is None else env
    if env.get("GAMEANYTHING_USER"): return True
    return bool(root and isinstance(projects.config_of(root).get("owner"), str) and projects.config_of(root).get("owner"))


def pick_mode(game, m, cfg, override=None):
    """(mode, from): --mode, else the project's build_mode, else the recommended one for the game on this computer."""
    if override:
        if override not in MODES: raise ValueError(f"mode must be one of {', '.join(MODES)}")
        return override, "flag"
    bm = OF_BUILD_MODE.get((cfg or {}).get("build_mode"))
    if bm: return bm, "project"
    if m.get("where") == "server": return "sandbox", "recommended"
    src = sandbox.sources(game, m)
    if not src["offered"] or src.get("recommended") == "native": return "native", "recommended"
    return "sandbox", "recommended"           # Docker missing / not running: still the recommended way; the guide says how to get Docker


def info(root=None, mode=None, system=None, hub=None, probe=None, env=None, machine=None) -> dict:
    """Everything `setup guide` prints. root: a project folder (or None); system: the user's own choice when detection failed (or, on
    the hub, the system of the user's own computer for native mode); machine: a ready machine dict (tests)."""
    cfg = projects.config_of(root) if root else {}
    game = (cfg.get("game") if cfg.get("game") in registry.games() else "stardew") if root else None
    hub = is_hub(root, env) if hub is None else hub
    m = machine or sandbox.detect(env=env, hub=hub, probe=probe)
    if system:
        if system not in sandbox.SYSTEMS: raise ValueError(f"system must be one of {', '.join(sandbox.SYSTEMS)}")
        if m.get("system") != system:
            m = sandbox.machine(system, arch=m.get("arch") or "x86_64", docker=m.get("docker") or "missing", memory_gb=m.get("memory_gb"),
                                where=m.get("where", "this_computer"))
    md, mfrom = pick_mode(game or "stardew", m, cfg, mode) if game or mode else ("sandbox", "default")
    out = {"project": str(root) if root else None, "game": game, "machine": m, "hub": hub, "mode": md, "mode_from": mfrom,
           "guide": None, "guide_name": None, "checklist": [], "verdict": None, "alternative": None, "ask_system": False}
    where = m.get("where", "this_computer")
    if where == "server" and md == "native" and not system:
        out.update(ask_system=True, why="Native mode on the hub means the user's own computer: ask which system it runs (Linux, Mac or "
                                         "Windows) and run again with --system")
        return out
    sysname = m.get("system")
    if sysname not in sandbox.SYSTEMS and not (where == "server" and md == "sandbox"):
        out.update(ask_system=True, why="The system was not detected: ask the user (Linux, Mac or Windows) and run again with --system")
        return out
    # a server only shared by its users (the hub) or set up as a gamebench lab gets the server guide; a Linux server that is the user's
    # own (no display, no gamebench: `gameanything lab sandbox`, buildmode.own_sandbox) gets linux-sandbox like her own computer
    shared = hub or (sysname == "linux" and _gamebench_lab(env))
    out["shared_server"] = where == "server" and shared
    name = guide_name(sysname, md, "server" if where == "server" and md == "sandbox" and shared else "this_computer")
    out.update(guide=str(guide_path(name)), guide_name=name, checklist=checklist(name))
    if game:
        vm = m if not (where == "server" and md == "native") else sandbox.machine(sysname)
        out["verdict"] = verdict(game, md, vm)
    other = "native" if md == "sandbox" else "sandbox"
    if sysname in sandbox.SYSTEMS and where != "server":
        out["alternative"] = {"mode": other, "guide": str(guide_path(guide_name(sysname, other)))}
    return out


MARKS = 3


def marks(root, name) -> list:
    """The read marks spread through the printed guide (after about 1/4, 1/2 and 3/4 of it, never at its end): `--read m1-m2-m3`
    proves the guide's content reached the agent, not only that the command ran (QA 2026-10-29: Gemini could not open the file, the
    step passed anyway; QA 2026-10-30: `setup guide | tail -3` found a token printed on the last line)."""
    import hashlib
    try: t = guide_path(name).read_text(encoding="utf-8")
    except OSError: t = ""
    return [hashlib.sha256(f"{Path(root).resolve()}|{name}|{i}|{t}".encode("utf-8")).hexdigest()[:6] for i in range(MARKS)]


def token(root, name) -> str:
    """What `--read` expects: the read marks in order, joined with "-"."""
    return "-".join(marks(root, name))


def marked(root, name, body: str) -> str:
    """The guide text with the read marks put in at blank lines near 1/4, 1/2 and 3/4 of it."""
    lines = body.rstrip().splitlines(); ms = marks(root, name); n = len(lines)
    blank = [i for i, ln in enumerate(lines) if not ln.strip()]
    at = []
    for k in range(MARKS):
        want = n * (k + 1) // (MARKS + 1)
        i = min(blank, key=lambda b: abs(b - want)) if blank else want
        while i in at or (at and i < at[-1]): i += 1
        at.append(min(i, max(n - 1, 0)))
    out = []
    for i, ln in enumerate(lines):
        out.append(ln)
        for k, a in enumerate(at):
            if a == i: out += ["", f"> (read mark {k + 1} of {MARKS}: {ms[k]})", ""]
    return "\n".join(out)


def record(root, inf, read=True) -> dict:
    """Write `setup:` into config/project.yaml (only that block; the other lines and comments stay). read=False: the guide was only shown
    (`guide_shown_at`); a read recorded before for the same guide stays."""
    m = inf["machine"]; now_ = datetime.now().isoformat(timespec="seconds")
    old = recorded(projects.config_of(root))
    rec = {"system": m.get("system"), "arch": m.get("arch"), "mode": inf["mode"], "where": m.get("where", "this_computer"),
           "guide": inf["guide_name"], "host": osdirs.system(), "guide_shown_at": now_}
    if read: rec["guide_read_at"] = now_
    elif old.get("guide_read_at") and old.get("guide") == inf["guide_name"] and old.get("mode") == inf["mode"]: rec["guide_read_at"] = old["guide_read_at"]
    f = Path(root) / layout.CONFIG / "project.yaml"; t = f.read_text(encoding="utf-8") if f.exists() else ""
    t = re.sub(r"(?m)^setup:.*(?:\n[ \t]+.*)*\n?", "", t)
    t = (t.rstrip("\n") + "\n" if t.strip() else "") + yaml.safe_dump({"setup": rec}, allow_unicode=True, sort_keys=False)
    f.parent.mkdir(parents=True, exist_ok=True); f.write_text(t, encoding="utf-8")
    return rec


def recorded(cfg) -> dict:
    s = (cfg or {}).get("setup"); return s if isinstance(s, dict) else {}


def stale(cfg) -> str:
    """'' when the recorded setting still holds; else why the guide must be read again (never read, the mode or the computer changed)."""
    s = recorded(cfg)
    if not s.get("guide_read_at"): return "never"
    bm = OF_BUILD_MODE.get(cfg.get("build_mode"))
    if bm and s.get("mode") != bm: return "mode"
    if s.get("host") and s.get("host") != osdirs.system(): return "machine"
    return ""


# ---------------------------------------------------------------- text output
def text(inf, rec=None) -> str:
    m = inf["machine"]
    where = ("the hub's server" if inf.get("shared_server", True) else "this server (yours)") if m.get("where") == "server" else "this computer"
    chip = f", {'Apple silicon' if m.get('chip') == 'apple' else 'Intel'}" if m.get("system") == "mac" else ""
    L = [f"[setup] {where}: {SYS_EN.get(m.get('system'), m.get('system') or 'unknown system')} {m.get('arch') or ''}{chip}"
         + (", WSL" if m.get("wsl") else "") + f", Docker {m.get('docker')}"
         + (f", {m['memory_gb']:g} GB" if m.get("memory_gb") else "")
         + (f", GPU {len(m['gpus'])}× {m['gpus'][0]}" if m.get("gpus") else "")]
    L.append(f"[setup] mode: {inf['mode']} ({ {'flag': 'chosen with --mode', 'project': 'the project build_mode', 'recommended': 'recommended for this game here', 'default': 'the default'}[inf['mode_from']] })")
    if inf["ask_system"]:
        L.append(f"[setup] {inf['why']}"); return "\n".join(L)
    L.append(f"[setup] guide: {inf['guide']}")
    L.append("[setup] READ THE WHOLE GUIDE NOW, then follow its checklist:")
    L += [f"  - {c}" for c in inf["checklist"]]
    v = inf.get("verdict")
    if v:
        title = registry.titles().get(inf["game"], inf["game"])
        L.append(f"[setup] {title} in {inf['guide_name']}: {v['verdict']}" + (f" (source: {v['source']})" if v.get("source") else "")
                 + (f": {v['why']}" if v.get("why") else ""))
        L += [f"  warning: {w}" for w in v.get("warnings") or []]
    if inf.get("alternative"): L.append(f"[setup] the other mode: {inf['alternative']['mode']}: {inf['alternative']['guide']}")
    if rec: L.append(f"[setup] recorded in config/project.yaml setup: mode {rec['mode']}, guide {rec['guide']}, "
                     + (f"read at {rec['guide_read_at']}" if rec.get("guide_read_at") else "shown (not read yet: --read <the read marks in it>)"))
    return "\n".join(L)


def main(a) -> int:
    if a.what == "tables":
        out = tables(write=a.write)
        if a.write: print(f"[setup] tables refreshed: {', '.join(out) or 'all up to date'}"); return 0
        if out: print(f"[setup] out of date: {', '.join(out)} (gameanything setup tables --write)"); return 1
        print("[setup] every guide's table is up to date"); return 0
    root = projects.resolve(a.project) if a.project else None
    try: inf = info(root, mode=a.mode, system=a.system, hub=True if a.hub else None)
    except ValueError as e: print(f"[setup] {e}", file=sys.stderr); return 2
    if getattr(a, "read", None):                       # the agent read the whole guide: the read marks spread through it
        if not (root and inf["guide"]): print("[setup] --read needs --project and a guide", file=sys.stderr); return 2
        if a.read.strip() != token(root, inf["guide_name"]):
            print(f"[setup] those are not the {MARKS} read marks of {inf['guide_name']}.md (in order, joined with -): run `gameanything setup guide --project \"$P\"` and read the whole guide it prints", file=sys.stderr)
            return 2
        rec = record(root, inf, read=True); print(f"[setup] guide {inf['guide_name']} read; recorded at {rec['guide_read_at']}"); return 0
    rec = record(root, inf, read=False) if root and inf["guide"] and not a.no_record else None
    body = ""
    if root and inf["guide"] and not a.no_record:
        try: body = guide_path(inf["guide_name"]).read_text(encoding="utf-8")
        except OSError: body = ""
    shown = marked(root, inf["guide_name"], body) if body else ""
    how = (f"read it all? the guide has {MARKS} read marks in it (「read mark 1 of {MARKS}: ...」); then: "
           f"gameanything setup guide --project \"$P\" --read <mark1>-<mark2>-<mark3>")
    if a.json: print(osdirs.json_text({**inf, "recorded": rec, "guide_text": shown or None, "read_how": how if shown else None}, indent=1))
    else:
        print(text(inf, rec))
        if body:
            print(f"\n----- the guide {inf['guide_name']}.md (read all of it) -----\n{shown}\n----- end of the guide -----")
            print(f"[setup] {how}")
    return 3 if inf["ask_system"] else 0
