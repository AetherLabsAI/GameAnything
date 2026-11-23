"""The game registry (gameanything/games/): built-in packages, plugins through the `gameanything.games` entry point group (a real
dist-info on sys.path, and monkeypatched entry points), `gameanything game new` (every loader type, in a checkout and as a plugin), `gameanything game
check`, docs/games.md in sync, package data, and the page side (useGames in node)."""
import fnmatch
import json
import shutil
from pathlib import Path

import pytest
import yaml

from gameanything import buildmode, cli, games as registry, native, projects
from gameanything.games import testing, tools
from gameanything.native import games as ng, checks, quiet
from gameanything.ui import onboard

ROOT = Path(__file__).resolve().parents[1]
BEFORE = {"stardew": "Stardew Valley", "minecraft": "Minecraft", "cities_skylines": "Cities: Skylines", "slay_the_spire": "Slay the Spire",
          "overcooked2": "Overcooked! 2", "sims4": "The Sims 4", "valheim": "Valheim"}          # projects.GAMES before the registry
CLASSES = {"stardew": ng.Stardew, "minecraft": ng.Minecraft, "cities_skylines": ng.CitiesSkylines, "sims4": ng.Sims4,
           "slay_the_spire": ng.SlayTheSpire, "overcooked2": ng.Overcooked2, "valheim": ng.Valheim}


@pytest.fixture
def clean_registry():
    yield
    registry.refresh()                                       # whatever a test registered goes away again


# ---------------------------------------------------------------- built-in packages: the 7 games migrated without changes
def test_builtin_games_unchanged():
    g = registry.games()
    assert list(g)[:7] == list(BEFORE) and {k: projects.GAMES[k] for k in BEFORE} == BEFORE
    assert all(native.GAMES[k] is c for k, c in CLASSES.items())                            # the same code adapters
    assert buildmode.POOL_NAME == {"stardew": "stardew_valley"} and buildmode.SCRIPT == {"stardew": "stardew_valley", "cities_skylines": "cities"}
    assert buildmode.STEAM == {"cities_skylines", "overcooked2", "valheim", "terraria", "civ6"}
    old = lambda tbl: set(tbl) & set(BEFORE)                    # the migrated games only: every new package adds its own rows
    assert old(onboard.LOADER_FIX) == {"stardew", "minecraft"} and old(quiet.WINDOW_HOW) == {"stardew", "cities_skylines", "overcooked2", "valheim"}
    assert old(checks.NO_RELOAD) == {"stardew", "slay_the_spire", "minecraft", "sims4"}
    assert {"terraria"} <= set(onboard.LOADER_FIX) & set(quiet.WINDOW_HOW) & set(checks.NO_RELOAD)
    assert registry.errors() == []
    for gid, s in g.items():
        assert s.source == "builtin" and s.path.name == gid and s.path.parent == registry.HERE
        cls = native.GAMES[gid]
        if gid in CLASSES: assert cls.steam_appid == s.get("steam_appid") and cls.pin_var == s["pin_var"], gid   # yaml documents the code


@pytest.mark.parametrize("gid", list(BEFORE) + ["terraria"])
def test_every_builtin_package_checks_clean(gid):
    r = tools.check(gid)
    assert r["ok"], [i for i in r["items"] if i["level"] == "error"]


def test_docs_table_in_sync_and_cli(capsys):
    assert tools.docs_in_sync(), "docs/games.md is out of date: gameanything game list --write-docs"
    assert cli.main(["game", "list"]) == 0 and "terraria" in capsys.readouterr().out
    assert cli.main(["game", "list", "--json"]) == 0
    d = json.loads(capsys.readouterr().out); assert [r["id"] for r in d["games"]] == list(registry.games()) and d["errors"] == []
    assert cli.main(["game", "check", "terraria"]) == 0 and "[game] ok" in capsys.readouterr().out
    assert cli.main(["game", "check", "nope"]) == 1


def test_package_data_covers_game_packages():
    """A pip install (not -e) carries every game package's game.yaml, smoke mod and the scaffold templates (pyproject package-data)."""
    import re
    txt = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    pats = re.findall(r'"([^"]+)"', re.search(r"(?ms)^\[tool\.setuptools\.package-data\]\s*\ngameanything = \[(.*?)\]", txt).group(1))
    base = ROOT / "gameanything"
    for f in (base / "games").rglob("*"):
        if not f.is_file() or f.suffix == ".py" or "__pycache__" in f.parts: continue
        rel = f.relative_to(base).as_posix()
        assert any(fnmatch.fnmatch(rel, p) for p in pats), f"{rel} is not in pyproject's package-data"


# ---------------------------------------------------------------- plugins
def _plugin_pkg(where: Path, gid="fakegame", title="Fake Game", adapter=None) -> Path:
    pkg = where / f"m2w_{gid}"; (pkg / "smoke" / "M2WSmoke").mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "smoke" / "M2WSmoke" / "main.lua").write_text('print("[M2W-smoke] loaded")\n', encoding="utf-8")
    d = {"id": gid, "title": title, "engine": "custom", "steam_appid": 4242, "loader": {"name": "Fake loader", "type": "script"},
         "folders": {"game": {"marker": "fake.exe"}, "user": {"windows": "{appdata}/Fake", "linux": "{xdg_data}/Fake", "mac": "{home}/Library/Fake"},
                     "mods": "{game}/mods"},
         "saves": ["{user}/saves"], "logs": ["{user}/log.txt"], "process_names": {"linux": ["fake"], "windows": ["fake.exe"], "mac": ["Fake"]},
         "launch": {"url": "steam://rungameid/4242"}, "toolchain": {"kind": "none"}, "smoke": "smoke/M2WSmoke", "lab": {"supported": False},
         "desc": "一个测试用的游戏", "desc_en": "A game for tests", "tests": ["tests/test_fakegame.py"]}
    if adapter: d["adapter"] = adapter
    (pkg / "game.yaml").write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    return pkg


def test_real_entry_point_plugin(tmp_path, monkeypatch, clean_registry):
    """A plugin found the way pip installs it: <site>/m2w_fakegame/ + a dist-info whose entry_points.txt names it."""
    site = tmp_path / "site"; _plugin_pkg(site)
    di = site / "m2w_fakegame-0.1.dist-info"; di.mkdir()
    (di / "METADATA").write_text("Metadata-Version: 2.1\nName: m2w-fakegame\nVersion: 0.1\n", encoding="utf-8")
    (di / "entry_points.txt").write_text("[gameanything.games]\nfakegame = m2w_fakegame\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(site))
    registry.refresh()
    s = registry.get("fakegame")
    assert s.source == "plugin:fakegame" and s.path == site / "m2w_fakegame"
    assert projects.GAMES["fakegame"] == "Fake Game" and list(projects.GAMES)[-1] == "fakegame"         # after the built-in ones
    g = native.get("fakegame", sys_="linux", home=tmp_path / "home", env={"GAMEANYTHING_DATA": str(tmp_path / "d"), "GAMEANYTHING_STEAM_DIR": str(tmp_path / "none")})
    assert isinstance(g, ng.DeclarativeGame) and not g.installed() and g.saves_dir() == tmp_path / "home" / ".local" / "share" / "Fake" / "saves"
    assert not buildmode.lab_runs("fakegame", None, {"fakegame"})                                     # lab.supported: false
    assert registry.ui_info()["games"]["fakegame"]["desc_en"] == "A game for tests"
    r = tools.check("fakegame")
    assert r["ok"], r["items"] and any("plugin's own repository" in i["text"] for i in r["items"])
    # a project for it, the wizard row, doctor
    p = projects.create("插件游戏", game="fakegame", dir=tmp_path / "proj")
    assert projects.game_of(p["path"]) == "fakegame"
    assert any(x["id"] == "fakegame" for x in onboard.game_checks(force=True, doctor=native.doctor())["games"])


def test_declarative_round_trip(tmp_path, monkeypatch, clean_registry):
    """A game.yaml-only game: found in a fake Steam library, backup -> install (a folder) -> uninstall -> restore."""
    pkg = _plugin_pkg(tmp_path)
    ep = type("EP", (), {"name": "fakegame", "value": "m2w_fakegame", "load": lambda self: str(pkg)})()
    monkeypatch.setattr(registry, "_entry_points", lambda: [ep]); registry.refresh()
    for sys_ in ("linux", "windows", "mac"):
        root = tmp_path / sys_
        env = testing.fake_steam_app(root, 4242, "Fake Game", files=["fake.exe"])
        g = testing.make("fakegame", root, env=env, sys_=sys_)
        assert g.installed() and g.mods_dir() == root / "steam" / "steamapps" / "common" / "Fake Game" / "mods"
        g.saves_dir().mkdir(parents=True); (g.saves_dir() / "slot1").write_bytes(b"save")
        mod = root / "M2WSmoke"; mod.mkdir(); (mod / "main.lua").write_text("x", encoding="utf-8")
        r = g.install(mod); assert r["backup"] and (g.mods_dir() / "M2WSmoke" / "main.lua").is_file()
        (g.saves_dir() / "slot1").write_bytes(b"changed")
        g.uninstall("M2WSmoke"); g.restore(g.backups()[0]["stamp"])
        assert (g.saves_dir() / "slot1").read_bytes() == b"save"
        assert checks.check(g, mod)["ok"]                                                             # the generic check: installable


def test_broken_and_duplicate_plugins_never_break_m2w(tmp_path, monkeypatch, clean_registry):
    def boom(): raise ImportError("no such module")
    eps = [type("EP", (), {"name": "broken", "value": "x", "load": lambda self: boom()})(),
           type("EP", (), {"name": "dup", "value": "y", "load": lambda self: {"id": "stardew", "title": "Fake Stardew"}})(),
           type("EP", (), {"name": "badid", "value": "z", "load": lambda self: {"id": "Bad Id", "title": "x"}})(),
           type("EP", (), {"name": "badadapter", "value": "w", "load": lambda self: str(_plugin_pkg(tmp_path, "badad", adapter="nosuch.module:X"))})()]
    monkeypatch.setattr(registry, "_entry_points", lambda: eps); registry.refresh()
    assert projects.GAMES["stardew"] == "Stardew Valley" and "Bad Id" not in projects.GAMES and "badad" not in native.GAMES
    src = {e["source"] for e in registry.errors()}
    assert {"plugin:broken", "plugin:dup", "plugin:badid", "plugin:badadapter"} <= src, registry.errors()
    assert cli.main(["game", "list"]) == 0


# ---------------------------------------------------------------- scaffold and check
@pytest.mark.parametrize("loader", registry.LOADER_TYPES)
def test_new_in_a_checkout(tmp_path, loader):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='gameanything'\n", encoding="utf-8")
    r = tools.new("my_game", "My Game", loader=loader, engine="unity-mono", steam_appid=123, root=tmp_path)
    pkg = Path(r["package"])
    assert pkg == tmp_path / "gameanything" / "games" / "my_game" and (tmp_path / "tests" / "games" / "test_my_game.py").is_file()
    s = registry.load_spec(pkg)
    assert s["id"] == "my_game" and s["loader"]["type"] == loader and s["steam_appid"] == 123 and s["adapter"] == "adapter:MyGame"
    assert (pkg / "smoke" / "M2WSmoke").is_dir() and not any("{{" in f.name for f in pkg.rglob("*"))
    for f in (pkg / "smoke").rglob("*"):
        if f.is_file(): assert "{{" not in f.read_text(encoding="utf-8"), f
    compile((pkg / "adapter.py").read_text(encoding="utf-8"), "adapter.py", "exec")
    r = tools.check_folder(pkg)                                       # a fresh package is not done yet: its TODOs are errors
    assert not r["ok"] and any("TODO" in i["text"] for i in r["items"] if i["level"] == "error")
    with pytest.raises(ValueError, match="已经有了|已存在"): tools.new("my_game", "x", root=tmp_path) if "my_game" in registry.games() else tools.new("my_game", "x", root=tmp_path)


def test_new_refuses_bad_input(tmp_path):
    with pytest.raises(ValueError, match="id"): tools.new("Bad-Id", "x", root=tmp_path)
    with pytest.raises(ValueError, match="loader"): tools.new("okid", "x", loader="nope", root=tmp_path)
    with pytest.raises(ValueError, match="已经有了"): tools.new("terraria", "x", root=tmp_path)
    with pytest.raises(ValueError, match="--plugin"): tools.new("okid", "x", root=tmp_path)            # not a checkout


def test_new_plugin_then_fill_then_check(tmp_path, monkeypatch, clean_registry, capsys):
    assert cli.main(["game", "new", "fakegame", "--title", "Fake Game", "--loader", "tmodloader", "--plugin", str(tmp_path / "plug")]) == 0
    plug = tmp_path / "plug"; pkg = plug / "m2w_fakegame"
    assert '[project.entry-points."gameanything.games"]\nfakegame = "m2w_fakegame"' in (plug / "pyproject.toml").read_text(encoding="utf-8")
    assert (pkg / "smoke" / "M2WSmoke" / "M2WSmoke.csproj").is_file() and (plug / "tests" / "test_fakegame.py").is_file()
    # the author fills game.yaml: replace every TODO with a value
    shutil.copy2(_plugin_pkg(tmp_path / "filled") / "game.yaml", pkg / "game.yaml")
    d = yaml.safe_load((pkg / "game.yaml").read_text(encoding="utf-8")); d["loader"]["type"] = "tmodloader"; d["adapter"] = "adapter:Fakegame"
    (pkg / "game.yaml").write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["game", "check", "--path", str(pkg)]) == 0, capsys.readouterr().out
    # a game file in the smoke mod is an error (never ship game files)
    (pkg / "smoke" / "M2WSmoke" / "Assembly-CSharp.dll").write_bytes(b"MZ")
    r = tools.check_folder(pkg)
    assert not r["ok"] and any("binary" in i["text"] for i in r["items"])


def test_check_reports_missing_fields(tmp_path, monkeypatch, clean_registry):
    pkg = _plugin_pkg(tmp_path); d = yaml.safe_load((pkg / "game.yaml").read_text(encoding="utf-8"))
    for k in ("saves", "desc_en"): d.pop(k)
    d["loader"]["type"] = "nope"; (pkg / "game.yaml").write_text(yaml.safe_dump(d), encoding="utf-8")
    errs = [i["text"] for i in tools.check_folder(pkg)["items"] if i["level"] == "error"]
    assert any("`saves`" in e for e in errs) and any("loader.type" in e for e in errs) and any("desc_en" in e for e in errs)


# ---------------------------------------------------------------- the pages
@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_pages_take_games_from_the_registry():
    from test_ui_onboard import NODE_PRELUDE, STATIC, _node
    js = "".join((STATIC / f).read_text(encoding="utf-8") for f in ("i18n.js", "manage.js"))
    info = json.dumps(registry.ui_info(), ensure_ascii=False)
    out = _node(NODE_PRELUDE + js + f"\nuseGames({info}); M2W.lang = 'en';\n"
                "console.log(JSON.stringify({names: GAME_NAME, desc: t(GAME_DESC.terraria), vh: t(GAME_DESC.valheim)}))")
    assert out["names"]["terraria"] == "Terraria" and list(out["names"])[:7] == list(BEFORE)
    assert out["desc"] == registry.get("terraria")["desc_en"] and out["vh"] == registry.get("valheim")["desc_en"]
    ob = (STATIC / "onboard.js").read_text(encoding="utf-8"); mg = (STATIC / "manage.js").read_text(encoding="utf-8")
    assert "const GAME_DESC" not in ob and "useGames(CHECKS.game_info)" in ob and 'opt("stardew"' not in mg   # no per-game copies in the pages


def test_terraria_user_folder_pin(tmp_path):
    """The sandbox image sets GAMEANYTHING_TERRARIA_USER_DIR=/sandbox/saves (ga-terraria's -tmlsavedirectory): `native build --install`
    must put the .tmod and enabled.json there, not in ~/.local/share/Terraria/tModLoader (plain Docker test, 2026-10-30)."""
    from gameanything.native import games
    home = tmp_path / "home"; home.mkdir()
    g = games.get("terraria", sys_="linux", home=home, env={})
    assert g.mods_dir() == home / ".local" / "share" / "Terraria" / "tModLoader" / "Mods"
    saves = tmp_path / "saves"
    g = games.get("terraria", sys_="linux", home=home, env={"GAMEANYTHING_TERRARIA_USER_DIR": str(saves)})
    assert g.user_dir() == saves and g.mods_dir() == saves / "Mods" and g.enabled_file() == saves / "Mods" / "enabled.json"


def test_an_installed_copy_without_tests_checks_clean(tmp_path, monkeypatch):
    from gameanything.games import tools
    monkeypatch.setattr(tools, "REPO", tmp_path); monkeypatch.setattr(tools, "DOCS", tmp_path / "docs" / "games.md")   # no tests/, no docs/
    r = tools.check("stardew")
    assert r["ok"], [i for i in r["items"] if i["level"] == "error"]
    assert any(i["level"] == "info" and "not in an installed copy" in str(i) for i in r["items"])
