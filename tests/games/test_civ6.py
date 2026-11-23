"""Sid Meier's Civilization VI (civ6): the game package against fake folders (no game, no network; Linux, Windows and macOS paths).
The .modinfo checks, staging (nothing to compile), install -> Mods.sqlite switch -> uninstall, backup / restore byte-identical,
refusing while the game runs, `native check` and reload."""
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from gameanything import games as registry, native, projects
from gameanything.games import testing, tools
from gameanything.games.civ6 import adapter as cadapter
from gameanything.native import NativeError, checks

SMOKE = Path(registry.get("civ6").smoke_dir())
SMOKE_ID = "9707163e-1706-47cf-a4e6-fbd180b40f10"
MARKER = {"linux": ["Civ6", "steamassets/base/"], "windows": ["Base/Binaries/Win64Steam/CivilizationVI.exe"], "mac": ["Civ6.app/"]}
USER = {"linux": ".local/share/aspyr-media/Sid Meier's Civilization VI", "windows": "Documents/My Games/Sid Meier's Civilization VI",
        "mac": "Library/Application Support/Sid Meier's Civilization VI/Sid Meier's Civilization VI"}     # macOS: nested (her Mac, 2026-10-29)


def _db(p: Path, rows=()):
    """The relevant part of a current Civ VI Mods.sqlite: enabled state belongs to the selected mod group."""
    with closing(sqlite3.connect(str(p))) as c, c:
        c.execute("CREATE TABLE Mods (ModRowId INTEGER PRIMARY KEY AUTOINCREMENT, ModId TEXT NOT NULL)")
        c.execute("CREATE TABLE ModGroups (ModGroupRowId INTEGER PRIMARY KEY AUTOINCREMENT, Name TEXT NOT NULL, Selected BOOLEAN DEFAULT 0)")
        c.execute("CREATE TABLE ModGroupItems (ModGroupRowId INTEGER NOT NULL, ModRowId INTEGER NOT NULL, Disabled BOOLEAN DEFAULT 0, PRIMARY KEY (ModGroupRowId, ModRowId))")
        group = c.execute("INSERT INTO ModGroups (Name, Selected) VALUES ('default', 1)").lastrowid
        for mid, dis in rows:
            mod = c.execute("INSERT INTO Mods (ModId) VALUES (?)", (mid,)).lastrowid
            c.execute("INSERT INTO ModGroupItems VALUES (?, ?, ?)", (group, mod, dis))
    return p


def _game(tmp_path, sys_="linux", db_rows=None):
    env = testing.fake_steam_app(tmp_path, 289070, "Sid Meier's Civilization VI", files=MARKER[sys_])
    home = tmp_path / "home"
    if sys_ == "linux": env["XDG_DATA_HOME"] = str(tmp_path / "elsewhere")      # the Aspyr build ignores it: always ~/.local/share
    u = home / USER[sys_]
    (u / "Saves" / "Single" / "auto").mkdir(parents=True); (u / "Mods").mkdir()
    (u / "Saves" / "Single" / "Test.Civ6Save").write_bytes(b"save-1"); (u / "Saves" / "Single" / "auto" / "AutoSave_0001.Civ6Save").write_bytes(b"auto-1")
    if db_rows is not None: _db(u / "Mods.sqlite", db_rows)
    return testing.make("civ6", tmp_path, env=env, sys_=sys_), u


def _mod(tmp_path, name="MyMod", files=None, modinfo=None):
    d = tmp_path / "src" / name; d.mkdir(parents=True)
    files = {"UI/My.lua": "print('x')", "UI/My.xml": "<Context/>"} if files is None else files
    for rel, text in files.items(): (d / rel).parent.mkdir(parents=True, exist_ok=True); (d / rel).write_text(text, encoding="utf-8")
    listed = "".join(f"<File>{r}</File>" for r in files)
    (d / f"{name}.modinfo").write_text(modinfo if modinfo is not None else
        f'<Mod id="11111111-2222-3333-4444-555555555555" version="1"><Properties><Name>{name}</Name><CompatibleVersions>2.0</CompatibleVersions></Properties>'
        f'<InGameActions><AddUserInterfaces id="a"><File>UI/My.xml</File></AddUserInterfaces></InGameActions><Files>{listed}</Files></Mod>', encoding="utf-8")
    return d


def test_package_is_valid():
    r = tools.check("civ6")
    assert r["ok"], [i for i in r["items"] if i["level"] == "error"]
    assert "civ6" in projects.GAMES and native.GAMES["civ6"] is cadapter.Civ6 and registry.get("civ6")["verified"][0]["system"] == "linux"
    assert registry.lab_supported("civ6") and registry.get("civ6")["lab"]["steam"] is True


@pytest.mark.parametrize("sys_", ["linux", "windows", "mac"])
def test_folders_on_each_system(tmp_path, sys_):
    g, u = _game(tmp_path, sys_)
    i = g.info()
    assert i["installed"] and Path(i["game_dir"]).name == "Sid Meier's Civilization VI"
    assert Path(i["user_dir"]) == u and Path(i["mods_dir"]) == u / "Mods" and Path(i["saves_dir"]) == u / "Saves"
    # macOS (her Mac, 2026-10-29) and Windows (a real Windows 11 PC, 2026-11-01): Logs/ sit under Firaxis Games, not next to Mods/
    logs = (tmp_path / "home" / "Library/Application Support/Sid Meier's Civilization VI/Firaxis Games/Sid Meier's Civilization VI/Logs" if sys_ == "mac" else
            Path(g._vars()["localappdata"]) / "Firaxis Games" / "Sid Meier's Civilization VI" / "Logs" if sys_ == "windows" else u / "Logs")
    assert g.log_files() == [logs / "Lua.log", logs / "Modding.log"]
    assert i["launch"] == "steam://rungameid/289070" and "single-player" in i["launch_hint"]


def test_marker_is_per_system(tmp_path):
    env = testing.fake_steam_app(tmp_path, 289070, "Sid Meier's Civilization VI", files=MARKER["windows"])
    assert testing.make("civ6", tmp_path, env=env, sys_="windows").installed()
    assert not testing.make("civ6", tmp_path, env=env, sys_="linux").installed()           # a Windows copy is not a Linux install


def test_smoke_mod_checks_and_builds(tmp_path):
    g, u = _game(tmp_path)
    it = {"errors": [], "warnings": [], "notes": []}; g.check_mod(SMOKE, it)
    assert not it["errors"] and not it["warnings"], it
    b = g.build(SMOKE)
    st = Path(b["staged"])
    assert st.name == "M2WSmoke" and (st / "M2WSmoke.modinfo").is_file() and b["mod_id"] == SMOKE_ID and not b["warnings"]
    assert st.is_relative_to(g.root / "build")
    mi = cadapter.read_modinfo(st)
    assert mi["actions"] == ["UpdateText", "UpdateText", "AddGameplayScripts"] and not mi["toplevel_text"]       # text through UpdateText
    assert {"Text/M2WSmoke_Text.xml", "Text/M2WSmoke_FrontEnd.xml"} <= set(mi["files"])
    text = (st / "Text" / "M2WSmoke_Text.xml").read_text(encoding="utf-8")
    assert "[M2W-smoke] loaded" in text and 'Tag="LOC_WORLD_TRACKER_CHOOSE_RESEARCH"' in text      # the World Tracker label (not only the HUD one)
    assert "[M2W-smoke]" in (st / "Text" / "M2WSmoke_FrontEnd.xml").read_text(encoding="utf-8")


def test_text_outside_an_action_is_flagged(tmp_path):
    g, _ = _game(tmp_path)
    d = _mod(tmp_path, "T", files={"Text/T.xml": "<GameData/>"}, modinfo=(
        '<Mod id="11111111-2222-3333-4444-555555555555"><Properties><CompatibleVersions>2.0</CompatibleVersions></Properties>'
        '<InGameActions><AddGameplayScripts id="s"><File>Text/T.xml</File></AddGameplayScripts></InGameActions>'
        '<LocalizedText><File>Text/T.xml</File></LocalizedText><Files><File>Text/T.xml</File></Files></Mod>'))
    it = {"errors": [], "warnings": [], "notes": []}; g.check_mod(d, it)
    assert any("UpdateText" in w and "Text/T.xml" in w for w in it["warnings"]), it


def test_refuses_what_the_game_would_not_load(tmp_path):
    g, _ = _game(tmp_path)
    e = tmp_path / "empty"; e.mkdir()
    with pytest.raises(NativeError, match="modinfo"): g.check_installable(e)
    with pytest.raises(NativeError, match="UI/Gone.lua"):
        g.check_installable(_mod(tmp_path, "A", files={"UI/My.xml": "<Context/>"},
                                 modinfo='<Mod id="11111111-2222-3333-4444-555555555555"><InGameActions><X/></InGameActions><Files><File>UI/Gone.lua</File></Files></Mod>'))
    with pytest.raises(NativeError, match="GUID"):
        g.check_installable(_mod(tmp_path, "B", modinfo='<Mod id="not-a-guid"><InGameActions><X/></InGameActions></Mod>'))
    with pytest.raises(NativeError, match="Actions"):
        g.check_installable(_mod(tmp_path, "C", modinfo='<Mod id="11111111-2222-3333-4444-555555555555"><Properties/></Mod>'))
    with pytest.raises(NativeError, match="CompatibleVersions"):
        g.check_installable(_mod(tmp_path, "Compat", modinfo='<Mod id="11111111-2222-3333-4444-555555555555"><InGameActions><X/></InGameActions></Mod>'))
    with pytest.raises(NativeError, match="XML"): g.check_installable(_mod(tmp_path, "D", modinfo="<Mod id="))


def test_check_flags_bad_xml_case_and_unlisted_files(tmp_path):
    g, _ = _game(tmp_path)
    d = _mod(tmp_path, files={"UI/My.lua": "print('x')", "UI/My.xml": "<Context>"})
    (d / "UI" / "Extra.lua").write_text("print(1)", encoding="utf-8")
    (d / "UI" / "My.lua").rename(d / "UI" / "my.lua")
    it = {"errors": [], "warnings": [], "notes": []}; g.check_mod(d, it)
    assert any("UI/My.xml" in e and "XML" in e for e in it["errors"]), it
    assert any("UI/Extra.lua" in w for w in it["warnings"]) and any("UI/My.lua" in w and "大小写" in w for w in it["warnings"])


def test_check_refuses_a_second_mod_with_the_same_id(tmp_path):
    g, u = _game(tmp_path)
    shutil.copytree(_mod(tmp_path, "Hers"), u / "Mods" / "Hers")
    it = {"errors": [], "warnings": [], "notes": []}; g.check_mod(_mod(tmp_path, "Mine"), it)
    assert any("Hers" in e for e in it["errors"])


def test_install_switch_uninstall_and_restore(tmp_path):
    g, u = _game(tmp_path, db_rows=[("aaaaaaaa-0000-0000-0000-000000000000", 0)])
    before = {p: p.read_bytes() for p in [*(u / "Saves").rglob("*.Civ6Save"), u / "Mods.sqlite"]}
    r = g.install(g.build(SMOKE)["staged"])
    assert r["backup"] and (u / "Mods" / "M2WSmoke" / "M2WSmoke.modinfo").is_file() and "scanned" in r["switch"]     # not in the db yet
    assert r["pending"] and r["enabled"] is False and g.enable_state(SMOKE_ID) is None
    with closing(sqlite3.connect(str(u / "Mods.sqlite"))) as c, c: c.execute("INSERT INTO Mods (ModId) VALUES (?)", (SMOKE_ID,))  # the game scanned it, but did not add it to the selected group
    assert g.enable_state(SMOKE_ID) is False
    r2 = g.install(g.build(SMOKE)["staged"])
    assert r2["replaced_to_trash"] and g.enable_state(SMOKE_ID) is True and "enabled" in r2["switch"]
    assert g.enable_state("aaaaaaaa-0000-0000-0000-000000000000") is True                  # her other mod untouched
    for p in (u / "Saves").rglob("*.Civ6Save"): p.write_bytes(b"played")
    out = g.uninstall("M2WSmoke")
    assert out["moved_to_trash"] and not (u / "Mods" / "M2WSmoke").exists() and g.enable_state(SMOKE_ID) is False
    with pytest.raises(NativeError): g.uninstall("Hers")
    g.restore(g.backups()[0]["stamp"])
    assert {p: p.read_bytes() for p in before} == before


def test_refuses_while_running(tmp_path, monkeypatch):
    g, _ = _game(tmp_path)
    monkeypatch.setattr(cadapter.Civ6, "running", lambda self: True)
    for f in (lambda: g.install(SMOKE), lambda: g.uninstall("M2WSmoke"), lambda: g.restore("x")):
        with pytest.raises(NativeError, match="正在运行"): f()


def test_native_check_and_reload(tmp_path):
    g, _ = _game(tmp_path)
    assert checks.check(g, g.build(SMOKE)["staged"])["ok"]
    assert "civ6" in checks.NO_RELOAD and "重" in checks.NO_RELOAD["civ6"]
