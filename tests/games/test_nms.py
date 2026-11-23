"""No Man's Sky (nms): the game package against fake folders (no game, no network; Linux under Proton, Windows and macOS paths).
Loose-file mods: GAMEDATA/MODS/<Mod>/ with EXML patches, the GCMODSETTINGS.MXML backup, a legacy DISABLEMODS.TXT moved aside
and put back, refusing .pak mods, backup / restore of the saves, refusing while the game runs, check and reload."""
from pathlib import Path

import pytest

from gameanything import games as registry, native, projects
from gameanything.games import testing, tools
from gameanything.games.nms import adapter as nadapter
from gameanything.native import NativeError, checks

SMOKE = Path(registry.get("nms").smoke_dir())


def _game(tmp_path, sys_="linux", disable=False):
    env = testing.fake_steam_app(tmp_path, 275850, "No Man's Sky", files=["Binaries/NMS.exe", "GAMEDATA/PCBANKS/"])
    home = tmp_path / "home"
    gd = tmp_path / "steam" / "steamapps" / "common" / "No Man's Sky"
    (gd / "Binaries" / "SETTINGS").mkdir(parents=True)
    (gd / "Binaries" / "SETTINGS" / "GCMODSETTINGS.MXML").write_text('<Data template="cGcModSettings" />', encoding="utf-8")
    if disable: (gd / "GAMEDATA" / "PCBANKS" / "DISABLEMODS.TXT").write_bytes(b"")
    if sys_ == "linux": u = tmp_path / "steam" / "steamapps" / "compatdata" / "275850" / "pfx" / "drive_c" / "users" / "steamuser" / "AppData" / "Roaming" / "HelloGames" / "NMS"
    elif sys_ == "windows": u = home / "AppData" / "Roaming" / "HelloGames" / "NMS"; env["APPDATA"] = str(home / "AppData" / "Roaming")
    else: u = home / "Library" / "Application Support" / "HelloGames" / "NMS"
    (u / "st_76561190000000000").mkdir(parents=True)
    (u / "st_76561190000000000" / "save.hg").write_bytes(b"save-1"); (u / "st_76561190000000000" / "mf_save.hg").write_bytes(b"meta-1")
    return testing.make("nms", tmp_path, env=env, sys_=sys_), gd, u


def test_package_is_valid():
    r = tools.check("nms")
    assert r["ok"], [i for i in r["items"] if i["level"] == "error"]
    s = registry.get("nms")
    assert "nms" in projects.GAMES and native.GAMES["nms"] is nadapter.Nms and s["lab"]["supported"] is False


@pytest.mark.parametrize("sys_", ["linux", "windows", "mac"])
def test_folders_on_each_system(tmp_path, sys_):
    g, gd, u = _game(tmp_path, sys_)
    i = g.info()
    assert i["installed"] and Path(i["game_dir"]) == gd
    assert Path(i["user_dir"]) == u and Path(i["saves_dir"]) == u and Path(i["mods_dir"]) == gd / "GAMEDATA" / "MODS"
    assert Path(i["mod_settings"]) == gd / "Binaries" / "SETTINGS" / "GCMODSETTINGS.MXML"
    assert i["launch"] == "steam://rungameid/275850" and "offline" in i["launch_hint"].lower()
    assert i["toolchain"]["ok"]                                      # nothing to compile


def test_smoke_mod_checks_and_builds(tmp_path):
    g, gd, _ = _game(tmp_path)
    it = {"errors": [], "warnings": [], "notes": []}; g.check_mod(SMOKE, it)
    assert not it["errors"] and not it["warnings"], it
    b = g.build(SMOKE)
    st = Path(b["staged"])
    assert st.name == "M2WSmoke" and st.is_relative_to(g.root / "build") and not st.is_relative_to(gd)
    assert nadapter.scan(st)["exml"] and not list(st.rglob("README*"))


def test_refuses_what_the_game_would_not_load(tmp_path):
    g, _, _ = _game(tmp_path)
    m = tmp_path / "Bad"; m.mkdir()
    with pytest.raises(NativeError, match="EXML"): g.check_installable(m)                 # empty
    (m / "OLD.pak").write_bytes(b"x")
    with pytest.raises(NativeError, match=r"\.pak"): g.check_installable(m)
    (m / "OLD.pak").unlink(); (m / "METADATA").mkdir(); (m / "METADATA" / "X.EXML").write_text("<Data>", encoding="utf-8")
    with pytest.raises(NativeError, match="XML"): g.check_installable(m)
    (m / "METADATA" / "X.EXML").write_text("<Root />", encoding="utf-8")
    with pytest.raises(NativeError, match="template"): g.check_installable(m)
    (m / "METADATA" / "X.EXML").write_text('<Data template="cGcX" />', encoding="utf-8"); (m / "Y.MXML").write_text("<Data/>", encoding="utf-8")
    it = {"errors": [], "warnings": [], "notes": []}; g.check_mod(m, it)
    assert not it["errors"] and any("Y.MXML" in w for w in it["warnings"])


def test_install_moves_disablemods_aside_and_back(tmp_path):
    g, gd, u = _game(tmp_path, disable=True)
    dm = gd / "GAMEDATA" / "PCBANKS" / "DISABLEMODS.TXT"
    r = g.install(g.build(SMOKE)["staged"])
    assert r["backup"] and (gd / "GAMEDATA" / "MODS" / "M2WSmoke").is_dir() and not dm.exists() and "DISABLEMODS" in r["switch"]
    assert (g.root / "nms-disablemods" / "GAMEDATA" / "PCBANKS" / "DISABLEMODS.TXT").is_file()      # moved, never deleted
    out = g.uninstall("M2WSmoke")
    assert out["moved_to_trash"] and not (gd / "GAMEDATA" / "MODS" / "M2WSmoke").exists() and dm.is_file()
    with pytest.raises(NativeError): g.uninstall("HerMod")


def test_backup_restore_byte_identical(tmp_path):
    g, gd, u = _game(tmp_path)
    files = [u / "st_76561190000000000" / "save.hg", u / "st_76561190000000000" / "mf_save.hg", gd / "Binaries" / "SETTINGS" / "GCMODSETTINGS.MXML"]
    before = {p: p.read_bytes() for p in files}
    g.install(g.build(SMOKE)["staged"])
    for p in files: p.write_bytes(b"changed by playing")
    g.restore(g.backups()[0]["stamp"])
    assert {p: p.read_bytes() for p in files} == before


def test_refuses_while_running(tmp_path, monkeypatch):
    g, _, _ = _game(tmp_path)
    monkeypatch.setattr(nadapter.Nms, "running", lambda self: True)
    for f in (lambda: g.install(SMOKE), lambda: g.uninstall("M2WSmoke"), lambda: g.restore("x")):
        with pytest.raises(NativeError, match="正在运行"): f()


def test_native_check_and_reload(tmp_path):
    g, _, _ = _game(tmp_path)
    r = checks.check(g, g.build(SMOKE)["staged"])
    assert r["ok"], r
    assert "nms" in checks.NO_RELOAD and "重" in checks.NO_RELOAD["nms"]
