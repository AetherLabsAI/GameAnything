"""`gameanything game list | new | check`: list the registered games, scaffold a new game package, validate one (games/__init__.py).

    rows()                        one dict per game (id, title, engine, loader, steam app, adapter kind, lab, source, verified)
    markdown()                    the table of docs/games.md (between its <!-- games:begin --> / <!-- games:end --> markers)
    new(id, title, loader, ...)   gameanything/games/<id>/ (game.yaml, adapter.py, smoke/) + tests/games/test_<id>.py in this
                                  checkout, or with plugin=DIR a pip-installable plugin (pyproject.toml with the entry point)
    check(id, build=False)        -> {ok, items: [{level: error|warning|ok|info, text}]}: required fields, the adapter loads, smoke
                                  mod there (and no game files in it), tests and docs row there, what this computer has (native
                                  doctor); build=True also builds the smoke mod and runs `native check` on it when the game is here
"""
import re
from pathlib import Path

import yaml

from . import HERE, ID_RE, LOADER_TYPES, REQUIRED, SYSTEMS, GameSpec, adapter_class, games, get, load_spec

REPO = HERE.parent.parent                      # the checkout (pyproject.toml, tests/, docs/) when GameAnything runs from one
DOCS = REPO / "docs" / "games.md"
BEGIN, END = "<!-- games:begin (gameanything game list --markdown) -->", "<!-- games:end -->"
TOOLCHAINS = ("dotnet", "java", "python37", "none", None)
# never in a smoke mod: game files, binaries, packed game assets (a smoke mod is source only; the game's files stay hers)
BINARY = {".exe", ".dll", ".so", ".dylib", ".pdb", ".jar", ".tmod", ".pak", ".assets", ".xnb", ".bundle", ".ts4script", ".package", ".zip", ".7z"}


# ---------------------------------------------------------------- list
def _kind(s: GameSpec) -> str:
    a = s.get("adapter") or ""
    return "game.yaml only" if not a else "adapter.py" if not a.split(":")[0].count(".") else "code (native/games.py)" if a.startswith(("gameanything.native", "memory2world.native")) else a


def rows() -> list:
    out = []
    for gid, s in games().items():
        lab = s.get("lab") if isinstance(s.get("lab"), dict) else {}
        ver = [f"{v.get('system')} {v.get('date')}" for v in (s.get("verified") or []) if isinstance(v, dict)]
        out.append({"id": gid, "title": s.title, "engine": s.get("engine") or "", "loader": (s.get("loader") or {}).get("name") or "",
                    "loader_type": (s.get("loader") or {}).get("type") or "", "steam_appid": s.get("steam_appid"), "adapter": _kind(s),
                    "lab": "yes" if lab.get("supported", True) is not False else "no", "source": s.source, "verified": ver, "path": str(s.path)})
    return out


def markdown(builtin_only=True) -> str:
    h = "| id | Game | Engine | Mod loader | Steam app | Adapter | Lab | Verified on real games |\n|---|---|---|---|---|---|---|---|\n"
    body = "".join(f"| `{r['id']}` | {r['title']} | {r['engine']} | {r['loader']} | {r['steam_appid'] or '-'} | {r['adapter']} | {r['lab']} | "
                   f"{', '.join(r['verified']) or 'not yet'} |\n" for r in rows() if not builtin_only or r["source"] == "builtin")
    return h + body


def docs_in_sync(text: str = None) -> bool:
    t = (DOCS.read_text(encoding="utf-8") if text is None else text).replace("\r\n", "\n")     # a Windows checkout may have CRLF
    if BEGIN not in t or END not in t: return False
    return t[t.index(BEGIN) + len(BEGIN):t.index(END)].strip() == markdown().strip()


def write_docs():
    t = DOCS.read_text(encoding="utf-8")
    i, j = t.index(BEGIN) + len(BEGIN), t.index(END)
    DOCS.write_text(t[:i] + "\n" + markdown() + t[j:], encoding="utf-8")


# ---------------------------------------------------------------- new
_GAME_YAML = """# {title}: a gameanything game package. How to fill it: skills/gameanything/references/add-a-game.md
# Paths: one string, a list of candidates (the first that exists wins), or a per-system map {{windows, mac, linux}}; placeholders:
# {{home}} {{documents}} {{appdata}} {{localappdata}} {{xdg_data}} {{xdg_config}} {{game}} (the install) {{user}} (folders.user) {{mods}}
id: {id}
title: {title}
order: 1000
steam_appid: {appid}              # null when the game is not on Steam
engine: {engine}                  # unity-mono, unity-il2cpp, xna-fna, java, unreal, godot, custom, ...
adapter: {adapter}                # code hooks; remove the line to use game.yaml alone (no build, install of files / folders only)
pin_var: GAMEANYTHING_{ID}_DIR             # lets the user point GameAnything at the install folder
loader:
  name: TODO the mod loader's name and version line
  type: {loader}                  # {types}
  url: TODO where users get it (official page only)
  fix: TODO 一句话：怎么装 mod 加载器（中文，界面显示）
  fix_en: TODO one line, how to install the mod loader
  check: []                       # paths that exist once the loader is installed, e.g. ["{{game}}/BepInEx/core/BepInEx.dll"]
folders:
  game: {{marker: TODO a file only this game's install folder has}}
  user:
    windows: "TODO {{documents}}/My Games/..."
    linux: "TODO {{xdg_data}}/..."
    mac: "TODO {{home}}/Library/Application Support/..."
  mods: "{{user}}/Mods"
saves: ["{{user}}/Saves"]          # every folder with her saves: backed up before the first install, restorable byte for byte
extra_files: []                   # other files install / the game rewrites that belong in the backup (mod switch files, settings)
logs: ["{{user}}/TODO.log"]       # where "[M2W-smoke] loaded" shows up
process_names: {{linux: [TODO], windows: [TODO.exe], mac: [TODO]}}
window_titles: []
launch:
  url: {launch}
  hint: TODO what the user picks so the game starts with its mod loader (a launch option, a "Play with mods" entry), if anything
toolchain: {{kind: {toolchain}, major: {major}, purpose: TODO what it builds}}
smoke: smoke/{Name}
lab:
  supported: false                # true only when a gamebench lab can run it (pool_name, script, steam: true)
sandbox:
  offered: false                  # the user's own Docker sandbox: build linux | java | windows, three_d true|false, gpu none|recommended|required (gameanything/sandbox.py)
window:
  how: TODO 一句话：怎么让游戏以窗口模式运行（中文）
reload:
  none: TODO 一句话：为什么不能热重载 / 怎么重载（中文）。能热重载就删掉这一项，在 adapter.py 写 reload_mod
desc: TODO 一句话介绍（中文，向导里显示）：什么游戏，适合哪种项目，哪些已经能做
desc_en: TODO the same in English
tests: [{tests}]
verified: []                      # [{{system: linux, date: YYYY-MM-DD, result: pass, how: ...}}] after a real round trip
"""
_ADAPTER = '''"""{title}: the code hooks of its game package (game.yaml has the folders, saves, logs and launch)."""
import re
from pathlib import Path

from gameanything.native.games import DeclarativeGame, NativeError


class {cls}(DeclarativeGame):
    def build(self, src, name=None) -> dict:
        """Compile the mod in `src` with the toolchain of game.yaml into <data>/native/build/<name>/ (never into the game's folders)
        -> {{staged: the folder or file `install` copies, log, warnings}}."""
        raise NativeError("TODO: {title} 的本机构建还没写")

    def check_installable(self, src: Path):
        """Refuse what the loader would silently skip (wrong file type, missing manifest)."""
        if not Path(src).exists(): raise NativeError(f"找不到 {{src}}")

    def check_mod(self, src: Path, it: dict):
        """`gameanything native check`: add to it["errors"] / it["warnings"] / it["notes"] without opening the game."""
        try: self.check_installable(Path(src))
        except NativeError as e: it["errors"].append(str(e))
'''
_TEST = '''"""{title} ({id}): the game package against fake folders (no game, no network; Linux, Windows and macOS paths)."""
import pytest

from gameanything import games as registry
from gameanything.games import testing, tools


def test_package_checks():
    r = tools.check("{id}")
    assert not [i for i in r["items"] if i["level"] == "error"], r


@pytest.mark.parametrize("sys_", ["linux", "windows", "mac"])
def test_folders(tmp_path, sys_):
    s = registry.get("{id}")
    marker = (s.get("folders") or {{}}).get("game", {{}}).get("marker") or "TODO"
    env = testing.fake_steam_app(tmp_path, s.get("steam_appid") or 1, "{title}", files=[marker])
    g = testing.make(s, tmp_path, env=env, sys_=sys_)
    assert g.installed() and g.mods_dir() is not None and g.saves_dir() is not None
'''
_PYPROJECT = """[project]
name = "m2w-{dash}"
version = "0.1.0"
description = "{title} for gameanything (a game package plugin)"
requires-python = ">=3.10"
dependencies = ["gameanything"]

[project.entry-points."gameanything.games"]
{id} = "m2w_{id}"

[build-system]
requires = ["setuptools>=64"]
build-backend = "setuptools.build_meta"

[tool.setuptools.package-data]
m2w_{id} = ["game.yaml", "LESSONS.md", "smoke/**/*"]
"""


def _fill(t: str, v: dict) -> str:
    for k, x in v.items(): t = t.replace("{{" + k + "}}", x)
    return t


def new(gid: str, title: str, loader: str = "other", engine: str = "TODO", steam_appid=None, plugin=None, root: Path = None) -> dict:
    """-> {package, files}. Refuses an id that exists or a folder that is not empty."""
    if not ID_RE.match(gid): raise ValueError(f"id 要是小写字母开头的小写字母、数字、下划线（2–40 个）：{gid}")
    if loader not in LOADER_TYPES: raise ValueError(f"loader 要是其中之一：{', '.join(LOADER_TYPES)}")
    if gid in games(): raise ValueError(f"{gid} 已经有了（{games()[gid].path}）")
    root = Path(root) if root else REPO
    if plugin:
        base = Path(plugin).expanduser().resolve(); pkg = base / f"m2w_{gid}"; tests = base / "tests"
        adapter_ref = "adapter:" + _cls(gid); test_ref = f"tests/test_{gid}.py"
    else:
        if not (root / "pyproject.toml").is_file(): raise ValueError(f"{root} 不是 gameanything 的代码仓库：加 --plugin DIR 做成一个单独的插件")
        pkg = root / "gameanything" / "games" / gid; tests = root / "tests" / "games"; adapter_ref = "adapter:" + _cls(gid)
        test_ref = f"tests/games/test_{gid}.py"
    if pkg.exists() and any(pkg.iterdir()): raise ValueError(f"文件夹已存在：{pkg}")
    tc = {"bepinex": ("dotnet", 6), "smapi": ("dotnet", 6), "tmodloader": ("dotnet", 8), "fabric": ("java", 21), "modthespire": ("java", 11)}.get(loader, ("none", 0))
    v = {"id": gid, "ID": gid.upper(), "title": title, "Name": "M2WSmoke", "appid": str(steam_appid) if steam_appid else "null", "engine": engine,
         "adapter": adapter_ref, "loader": loader, "types": " | ".join(LOADER_TYPES), "launch": f"steam://rungameid/{steam_appid}" if steam_appid else "null",
         "toolchain": tc[0], "major": str(tc[1]), "tests": test_ref}
    files = []
    pkg.mkdir(parents=True, exist_ok=True)
    def w(p: Path, text: str):
        p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text, encoding="utf-8"); files.append(str(p))
    w(pkg / "__init__.py", f'"""{title}: a gameanything game package (game.yaml, adapter.py, smoke/)."""\n')
    w(pkg / "game.yaml", _GAME_YAML.format(**v))
    w(pkg / "adapter.py", _ADAPTER.format(title=title, cls=_cls(gid)))
    tpl = HERE / "_templates" / loader
    for f in sorted(tpl.rglob("*")):
        if f.is_file(): w(pkg / "smoke" / "M2WSmoke" / _fill(str(f.relative_to(tpl)), v), _fill(f.read_text(encoding="utf-8"), v))
    from ..lessons import game_template
    w(pkg / "LESSONS.md", game_template(title))                     # what builders / playtesters learn about it (lessons.md)
    w(tests / f"test_{gid}.py", _TEST.format(id=gid, title=title))
    if plugin: w(Path(plugin).expanduser().resolve() / "pyproject.toml", _PYPROJECT.format(id=gid, dash=gid.replace("_", "-"), title=title))
    return {"package": str(pkg), "files": files}


def _cls(gid: str) -> str:
    return "".join(p.capitalize() for p in gid.split("_")) or "Game"


# ---------------------------------------------------------------- check
def _per_os(v) -> dict:
    if isinstance(v, dict) and any(k in v for k in SYSTEMS): return {k: v.get(k) for k in SYSTEMS}
    return {k: v for k in SYSTEMS}


def _smoke_needs(loader: str) -> list:
    """(glob, what) the smoke mod of this loader type must have."""
    return {"bepinex": [("*.cs", "a C# plugin (*.cs)")], "smapi": [("manifest.json", "manifest.json"), ("*.cs", "*.cs")],
            "tmodloader": [("build.txt", "build.txt"), ("*.cs", "*.cs")], "fabric": [("fabric.mod.json", "fabric.mod.json")],
            "modthespire": [("ModTheSpire.json", "ModTheSpire.json")]}.get(loader, [("*", "at least one file")])


def check(gid: str, build: bool = False, game_kw: dict = None) -> dict:
    """Validate the package of one game. game_kw: passed to the adapter (tests: sys_, home, env)."""
    items = []
    def add(level, text): items.append({"level": level, "text": text})
    try: s = get(gid)
    except KeyError:
        return {"ok": False, "game": gid, "items": [{"level": "error", "text": f"no game package {gid} (gameanything game list)"}]}
    # ---- game.yaml
    for k in REQUIRED:
        if s.get(k) in (None, "", [], {}): add("error", f"game.yaml: `{k}` is missing")
    if not ID_RE.match(gid): add("error", f"id {gid!r}: lowercase letters, digits, _ (2-40, a letter first)")
    if s.source == "builtin" and s.path.name != gid: add("error", f"the folder is {s.path.name}, the id is {gid}: they must be the same")
    lo = s.get("loader") if isinstance(s.get("loader"), dict) else {}
    if lo.get("type") not in LOADER_TYPES: add("error", f"loader.type {lo.get('type')!r}: one of {', '.join(LOADER_TYPES)}")
    if lo and not lo.get("fix") and lo.get("type") not in ("builtin", "script"): add("warning", "loader.fix: one Chinese line on how to install the loader (the wizard shows it)")
    if lo.get("fix") and not lo.get("fix_en"): add("error", "loader.fix_en: the English of loader.fix")
    if s.get("desc") and not s.get("desc_en"): add("error", "desc_en: the English of desc (the wizard shows both languages)")
    if s.get("steam_appid") is not None and not isinstance(s.get("steam_appid"), int): add("error", "steam_appid: a number (or null)")
    if (s.get("toolchain") or {}).get("kind") not in TOOLCHAINS: add("error", "toolchain.kind: one of dotnet, java, python37, none")
    user = _per_os((s.get("folders") or {}).get("user"))
    for sy in SYSTEMS:
        if not user.get(sy): add("warning", f"folders.user has no {sy} path: the game cannot be found there (fine if it does not run there; say so in docs)")
    for k in ("saves", "logs"):
        if s.get(k) is not None and not isinstance(s.get(k), list): add("error", f"`{k}` must be a list")
    for k, v in (("game.yaml", yaml.safe_dump(dict(s), allow_unicode=True)),):
        if re.search(r"\bTODO\b", v): add("error", f"{k} still has TODO placeholders")
    if s.get("sandbox") is not None:                     # the user's own sandbox (gameanything/sandbox.py)
        from .. import sandbox
        try:
            if not isinstance(s.get("sandbox"), dict): raise ValueError("`sandbox` must be a mapping")
            sandbox.facts_of(s)
        except ValueError as e: add("error", f"sandbox: {e}")
    lab = s.get("lab") if isinstance(s.get("lab"), dict) else {}
    if lab.get("supported", True) is not False and s.source != "builtin": add("warning", "lab.supported is not false: a plugin game has no gamebench lab unless you add one")
    # ---- the adapter
    try: cls = adapter_class(s)
    except Exception as e:
        add("error", f"adapter {s.get('adapter')!r} does not load: {type(e).__name__}: {e}"); cls = None
    if cls is not None:
        add("ok", f"adapter: {cls.__module__}.{cls.__name__}")
        for attr in ("steam_appid", "pin_var"):
            if s.get(attr) is not None and getattr(cls, attr, None) != s.get(attr): add("warning", f"{attr}: game.yaml says {s.get(attr)!r}, the adapter {getattr(cls, attr, None)!r}")
        from ..native import games as ng
        if cls.build is ng.Game.build:
            add("warning", "the adapter has no build(): `gameanything native build` says it is not connected (fine for mods that need no compiling)")
    # ---- smoke mod
    sd = s.smoke_dir()
    if not sd or not sd.is_dir(): add("error", f"smoke mod folder {s.get('smoke')!r} is not there")
    else:
        fs = [f for f in sd.rglob("*") if f.is_file()]
        for g, what in _smoke_needs(lo.get("type")):
            if not any(f.match(g) for f in fs): add("error", f"smoke mod: no {what} in {sd}")
        bad = [f for f in fs if f.suffix.lower() in BINARY or f.stat().st_size > 2 * 2 ** 20]
        for f in bad: add("error", f"smoke mod: {f.relative_to(sd)} is a binary / big file: ship source only, never the game's files or a built mod")
        if not any(b"[M2W-smoke]" in f.read_bytes() for f in fs if f.stat().st_size < 2 ** 20): add("warning", "smoke mod: nothing logs \"[M2W-smoke] ...\" (the real test looks for it)")
        if not bad: add("ok", f"smoke mod: {sd} ({len(fs)} files)")
    # ---- LESSONS.md: what builders / playtesters learned about this game (skills/gameanything/references/lessons.md)
    lf = s.path / "LESSONS.md"
    if not lf.is_file(): add("warning", "no LESSONS.md: every game package ships one (sections ## 开发 / ## 试玩; `gameanything game new` writes an empty one)")
    else:
        from ..lessons import entries, problems
        t = lf.read_text(encoding="utf-8"); ps = problems(t)
        for x in ps: add("warning", f"LESSONS.md: {x}")
        if "## 开发" not in t or "## 试玩" not in t: add("warning", "LESSONS.md: needs the two sections ## 开发 (builder) and ## 试玩 (playtester)")
        if not ps: add("ok", f"LESSONS.md: {len(entries(t))} lesson(s)")
    # ---- tests and docs (a built-in game: in this checkout)
    tests = s.get("tests") or []
    if not tests: add("error", "tests: list the test files (fake folders, no game needed)")
    base = REPO if s.source == "builtin" else s.path.parent
    for t in tests:
        p = (base / t)
        if p.is_file(): add("ok", f"tests: {t}")
        elif s.source == "builtin" and not (REPO / "tests").is_dir():   # an installed copy ships no tests (2026-11-01: every built-in game said ERROR)
            add("info", f"tests: {t} (in the GameAnything repository, not in an installed copy)")
        elif s.source == "builtin" or (s.path.parent / t).exists(): add("error", f"tests: {t} is not there")
        else: add("info", f"tests: {t} (in the plugin's own repository)")
    if s.source == "builtin" and DOCS.is_file():
        if f"| `{gid}` |" not in DOCS.read_text(encoding="utf-8") or not docs_in_sync(): add("error", "docs/games.md is not up to date: run  gameanything game list --write-docs")
        else: add("ok", "docs/games.md lists it")
    # ---- this computer (native doctor)
    if cls is not None:
        try:
            g = cls(**(game_kw or {})); i = g.info()
            if i["installed"]:
                add("info", f"this computer ({g.sys}): found at {i['game_dir'] or i['user_dir']}; mods {i['mods_dir']}; saves {i['saves_dir']}")
                lo_ = i.get("loader") or {}
                add("info" if lo_.get("ok") else "warning", f"loader {lo_.get('name')}: {'ok' if lo_.get('ok') else 'MISSING'} ({lo_.get('detail')})")
            else:
                add("info", f"this computer ({g.sys}): {s.title} not found (looked in Steam app {s.get('steam_appid')}, ${i['pin_var']}); saves would be at {i['saves_dir']}")
            tc = i.get("toolchain") or {}
            add("info" if tc.get("ok") else "warning", f"toolchain {tc.get('name')}: {'ok' if tc.get('ok') else 'missing'} ({tc.get('detail')})")
            if build:
                if not (i["installed"] and (i.get("loader") or {}).get("ok") and tc.get("ok")): add("warning", "--build skipped: the game, its loader or the toolchain is not here")
                elif sd and sd.is_dir():
                    from ..native import checks
                    b = g.build(sd); add("ok", f"smoke mod built: {b['staged']}")
                    r = checks.check(g, b["staged"])
                    for m in r["mods"]:
                        for e in m["errors"]: add("error", f"native check: {e}")
                        for e in m["warnings"]: add("warning", f"native check: {e}")
                    if r["ok"]: add("ok", "native check of the smoke mod: ok")
        except Exception as e:                                          # noqa: BLE001 -- a broken adapter is a check result
            add("error", f"the adapter fails on this computer: {type(e).__name__}: {e}")
    return {"ok": not any(i["level"] == "error" for i in items), "game": gid, "source": s.source, "path": str(s.path), "items": items}


def check_folder(folder) -> dict:
    """`gameanything game check --path DIR`: a package folder that is not registered yet (a plugin before pip install)."""
    s = load_spec(Path(folder), "path")
    g = games(); old = g.get(s.id); g[s.id] = s
    try: return check(s.id)
    finally:
        if old is None: g.pop(s.id, None)
        else: g[s.id] = old
