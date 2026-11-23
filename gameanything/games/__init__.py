"""The game registry: every game gameanything can make content for is a game package, so anyone can bring their favourite game in
(skills/gameanything/references/add-a-game.md, CONTRIBUTING.md "Adding a game").

    gameanything/games/<id>/game.yaml   what the game is: id, title, Steam app id, engine, mod loader, folders per system, saves, logs,
                                        process names, window titles, launch, build toolchain, lab support, the wizard's description
    gameanything/games/<id>/adapter.py  optional code hooks: a native.games.Game subclass (the built-in games point `adapter:` at their
                                        class in native/games.py instead)
    gameanything/games/<id>/smoke/      a smallest mod that proves the round trip (loaded -> a log line + something on screen)
    tests/games/test_<id>.py            fake-folder tests (no game needed; CI runs them on Linux, Windows and macOS)

A pip-installable plugin adds a game without a fork: an entry point in the group `gameanything.games` that names a module (or
package) whose folder holds game.yaml (the old group name `memory2world.games` still works), e.g. in the plugin's pyproject.toml

    [project.entry-points."gameanything.games"]
    mygame = "m2w_mygame"            # m2w_mygame/game.yaml (+ adapter.py, smoke/)

`gameanything game list | new <id> | check <id>` (games/tools.py) list, scaffold and validate packages.

    games()          {id: GameSpec}, built-in first (by `order`), then plugins; a broken plugin is skipped and recorded in errors()
    get(id)          one spec;  adapter_class(spec)  its native adapter class (native.games.Game subclass)
    titles()         {id: title} (projects.GAMES);  native_classes()  {id: adapter class} (native.games.GAMES)
    lab_*(), loader_fix(), window_how(), no_reload(), ui_info()   the per-game tables other modules used to hard-code
    refresh()        discover again (a plugin installed while running, tests) and update those tables in place
"""
import importlib
import importlib.util
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
GROUP = "gameanything.games"
OLD_GROUPS = ("memory2world.games",)       # the group's name before the rename: plugins registered there still load
ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
SYSTEMS = ("windows", "mac", "linux")
LOADER_TYPES = ("bepinex", "smapi", "tmodloader", "fabric", "modthespire", "script", "builtin", "other")
REQUIRED = ("id", "title", "engine", "loader", "folders", "saves", "logs", "process_names", "launch", "toolchain", "smoke", "desc")

_CACHE = None
_ERRORS = []


class GameSpec(dict):
    """game.yaml as a dict, plus where it came from: path (the package folder), source ("builtin" or "plugin:<entry point>")."""
    def __init__(self, data: dict, path: Path, source: str):
        super().__init__(data); self.path = Path(path); self.source = source

    @property
    def id(self): return self["id"]

    @property
    def title(self): return self["title"]

    def smoke_dir(self):
        s = self.get("smoke")
        return (self.path / s).resolve() if isinstance(s, str) and s else None


def load_spec(folder: Path, source="builtin") -> GameSpec:
    """Read <folder>/game.yaml (no validation beyond being a mapping with an id; `gameanything game check` validates)."""
    f = Path(folder) / "game.yaml"
    d = yaml.safe_load(f.read_text(encoding="utf-8"))
    if not isinstance(d, dict) or not isinstance(d.get("id"), str): raise ValueError(f"{f}: not a game.yaml (needs at least `id:`)")
    return GameSpec(d, Path(folder), source)


def _builtin() -> list:
    out = []
    for f in sorted(HERE.glob("*/game.yaml")):
        if f.parent.name.startswith("_"): continue                      # _templates/
        try: out.append(load_spec(f.parent))
        except (OSError, ValueError, yaml.YAMLError) as e: _ERRORS.append({"source": str(f), "error": str(e)})
    return sorted(out, key=lambda s: (s.get("order", 1000), s.id))


def _entry_points():
    from importlib import metadata
    out, seen = [], set()
    for g in (GROUP, *OLD_GROUPS):
        try: eps = list(metadata.entry_points(group=g))
        except TypeError:                                               # Python < 3.10 style (not supported, but never crash)
            eps = list(metadata.entry_points().get(g, []))
        for ep in eps:
            if (ep.name, ep.value) not in seen: seen.add((ep.name, ep.value)); out.append(ep)
    return out


def _plugin_spec(ep) -> GameSpec:
    """An entry point names a module / package whose folder holds game.yaml, or an object that is a folder path or a dict
    (game.yaml's content, with `path` = the folder its smoke / adapter paths are relative to)."""
    obj = ep.load()
    src = f"plugin:{ep.name}"
    if isinstance(obj, (str, Path)): return load_spec(Path(obj), src)
    if isinstance(obj, dict):
        d = dict(obj); p = Path(d.pop("path", ".")); return GameSpec(d, p, src)
    f = getattr(obj, "__file__", None)
    if f: return load_spec(Path(f).resolve().parent, src)
    raise ValueError(f"entry point {ep.name} = {ep.value}: not a module with game.yaml next to it, a folder or a dict")


def discover() -> dict:
    """Built-in packages, then every entry point of the group. A plugin cannot replace a built-in game (same id: skipped, recorded)."""
    _ERRORS.clear()
    out = {}
    for s in _builtin(): out[s.id] = s
    for ep in _entry_points():
        try: s = _plugin_spec(ep)
        except Exception as e:                                          # a broken plugin never breaks GameAnything
            _ERRORS.append({"source": f"plugin:{getattr(ep, 'name', '?')}", "error": f"{type(e).__name__}: {e}"}); continue
        if not ID_RE.match(s.id): _ERRORS.append({"source": s.source, "error": f"bad id {s.id!r}"}); continue
        if s.id in out: _ERRORS.append({"source": s.source, "error": f"{s.id} is already registered by {out[s.id].source}"}); continue
        out[s.id] = s
    return out


def games(refresh_=False) -> dict:
    global _CACHE
    if _CACHE is None or refresh_: _CACHE = discover()
    return _CACHE


def errors() -> list:
    games(); return list(_ERRORS)


def get(gid: str) -> GameSpec:
    g = games()
    if gid not in g: raise KeyError(gid)
    return g[gid]


# ---------------------------------------------------------------- adapters
def _module_from_file(spec: GameSpec, rel: str):
    """A module of the package folder by file name (a built-in package is importable as gameanything.games.<id>.<mod>; a plugin's
    adapter is part of its own importable package, so this is the fallback for a plain folder)."""
    f = spec.path / f"{rel}.py"
    if spec.source == "builtin" and spec.path.parent == HERE:
        return importlib.import_module(f"{__name__}.{spec.path.name}.{rel}")
    name = f"_m2w_game_{spec.id}_{rel}"
    if name in sys.modules: return sys.modules[name]
    ms = importlib.util.spec_from_file_location(name, f)
    if ms is None or ms.loader is None: raise ImportError(f"cannot load {f}")
    m = importlib.util.module_from_spec(ms); sys.modules[name] = m; ms.loader.exec_module(m)
    return m


def adapter_class(spec: GameSpec):
    """`adapter: package.module:Class` (absolute), `adapter: adapter:Class` (adapter.py of the package), or none: a DeclarativeGame
    made from game.yaml alone. The class gets `.spec`."""
    from ..native import games as ng
    a = spec.get("adapter")
    if not a: cls = ng.declarative(spec)
    else:
        mod, _, attr = str(a).partition(":")
        if not attr: raise ValueError(f"{spec.id}: adapter must be 'module:Class', got {a!r}")
        m = importlib.import_module(mod) if "." in mod else _module_from_file(spec, mod)
        cls = getattr(m, attr)
        if not (isinstance(cls, type) and issubclass(cls, ng.Game)): raise TypeError(f"{spec.id}: {a} is not a native.games.Game subclass")
        if issubclass(cls, ng.DeclarativeGame): cls.apply_spec(spec)          # game.yaml is the source of its identity fields
        else: cls.spec = spec                                                 # a code adapter keeps its own (`gameanything game check` compares)
    return cls


def native_classes() -> dict:
    out = {}
    for gid, s in games().items():
        try: out[gid] = adapter_class(s)
        except Exception as e:
            _ERRORS.append({"source": s.source, "error": f"{gid}: adapter: {type(e).__name__}: {e}"})
    return out


# ---------------------------------------------------------------- the tables other modules read
def titles() -> dict: return {gid: s.title for gid, s in games().items()}


def _lab(s) -> dict: return s.get("lab") if isinstance(s.get("lab"), dict) else {}


def lab_supported(gid: str) -> bool:
    """False only when game.yaml says `lab: {supported: false}` (no gamebench lab for it): the wizard never offers the sandbox then."""
    s = games().get(gid)
    return True if s is None else _lab(s).get("supported", True) is not False


def lab_pool_names() -> dict: return {gid: _lab(s)["pool_name"] for gid, s in games().items() if _lab(s).get("pool_name") not in (None, gid)}
def lab_scripts() -> dict: return {gid: _lab(s)["script"] for gid, s in games().items() if _lab(s).get("script") not in (None, gid)}
def lab_steam() -> set: return {gid for gid, s in games().items() if _lab(s).get("steam") is True}


def _text(s, *keys):
    v = s
    for k in keys: v = v.get(k) if isinstance(v, dict) else None
    return v if isinstance(v, str) and v else None


def loader_fix() -> dict: return {gid: t for gid, s in games().items() if (t := _text(s, "loader", "fix"))}
def window_how() -> dict: return {gid: t for gid, s in games().items() if (t := _text(s, "window", "how"))}
def no_reload() -> dict: return {gid: t for gid, s in games().items() if (t := _text(s, "reload", "none"))}


def texts() -> dict:
    """{Chinese text: English} of every page-visible text a game package brings (desc, loader fix): the page adds them to its EN table."""
    out = {}
    for s in games().values():
        for keys in (("desc",), ("loader", "fix")):
            zh, en = _text(s, *keys), _text(s, *keys[:-1], keys[-1] + "_en") if len(keys) > 1 else _text(s, "desc_en")
            if zh: out[zh] = en
    return out


def ui_info() -> dict:
    """What the pages need per game: {id: {title, desc, desc_en}} plus `_texts` {zh: en} (i18n of the packages' texts)."""
    out = {gid: {"title": s.title, "desc": _text(s, "desc") or "", "desc_en": _text(s, "desc_en") or ""} for gid, s in games().items()}
    return {"games": out, "texts": {k: v for k, v in texts().items() if v}}


def refresh() -> dict:
    """Discover again and update, in place, every table derived from the registry in modules already imported."""
    g = games(True)
    mods = sys.modules
    if (p := mods.get("gameanything.projects")): p.GAMES.clear(); p.GAMES.update(titles())
    if (n := mods.get("gameanything.native.games")): n.GAMES.clear(); n.GAMES.update(native_classes())
    if (b := mods.get("gameanything.buildmode")):
        b.POOL_NAME.clear(); b.POOL_NAME.update(lab_pool_names()); b.SCRIPT.clear(); b.SCRIPT.update(lab_scripts())
        b.STEAM.clear(); b.STEAM.update(lab_steam())
    if (o := mods.get("gameanything.ui.onboard")): o.LOADER_FIX.clear(); o.LOADER_FIX.update(loader_fix())
    if (q := mods.get("gameanything.native.quiet")): q.WINDOW_HOW.clear(); q.WINDOW_HOW.update(window_how())
    if (c := mods.get("gameanything.native.checks")): c.NO_RELOAD.clear(); c.NO_RELOAD.update(no_reload())
    return g
