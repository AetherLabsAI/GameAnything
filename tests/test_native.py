"""Native mode (D19): game folders on each system, backups, installs, Cities' mod switches. Uses fake game folders only."""
import zipfile
from pathlib import Path

import pytest

from gameanything.native import cgs, games, steam


def _steam(home: Path, sys_: str, appid: int, installdir: str) -> Path:
    root = steam.candidates(sys_, home, {})[0] if sys_ != "windows" else home / "Steam"
    (root / "steamapps").mkdir(parents=True, exist_ok=True)
    (root / "steamapps" / "libraryfolders.vdf").write_text(f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{root}"\n\t}}\n}}\n', encoding="utf-8")
    (root / "steamapps" / f"appmanifest_{appid}.acf").write_text(f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"installdir"\t\t"{installdir}"\n}}\n', encoding="utf-8")
    d = root / "steamapps" / "common" / installdir; d.mkdir(parents=True)
    return d


def _env(tmp, sys_):
    e = {"GAMEANYTHING_DATA": str(tmp / "m2w")}
    if sys_ == "windows": e.update(APPDATA=str(tmp / "home/AppData/Roaming"), LOCALAPPDATA=str(tmp / "home/AppData/Local"),
                                   GAMEANYTHING_STEAM_DIR=str(tmp / "home/Steam"))
    return e


@pytest.fixture(autouse=True)
def _not_running(monkeypatch):
    monkeypatch.setattr(games.Game, "running", lambda self: False)


def test_vdf_and_hash():
    d = steam.parse_vdf('"a"\n{\n\t"b"\t\t"C:\\\\Steam"\n\t"c" { "d" "1" }\n}')
    assert d == {"a": {"b": "C:\\Steam", "c": {"d": "1"}}}
    # the key the game itself wrote on Linux for this folder
    assert cgs.mod_key("/home/player/.local/share/Colossal Order/Cities_Skylines/Addons/Mods/WCHello") == "WCHello595075863.enabled"


def test_cgs_switch_off_leaves_her_file_as_it_was(tmp_path):
    """restore (her file back, without the mod's key) + uninstall (switch off) must not change her file: off = no key."""
    f = tmp_path / "userGameState.cgs"; mod = "/h/.local/share/Colossal Order/Cities_Skylines/Addons/Mods/M2WSmoke"
    assert cgs.enable(f, [mod], on=False) and not f.exists()                   # nothing there: nothing created
    cgs.write(f, {"_version": 4, "bool": {"Other123.enabled": True, "x": False}, "int": {"n": 3}}); before = f.read_bytes()
    (k,) = cgs.enable(f, [mod]); assert cgs.read(f)["bool"][k] is True and f.read_bytes() != before
    cgs.enable(f, [mod], on=False); assert f.read_bytes() == before            # the key is gone again, the rest unchanged
    t = f.stat().st_mtime_ns; cgs.enable(f, [mod], on=False); assert f.stat().st_mtime_ns == t   # no key: the file is not rewritten


@pytest.mark.parametrize("sys_", ["mac", "windows", "linux"])
def test_stardew_paths(tmp_path, sys_):
    home = tmp_path / "home"; d = _steam(home, sys_, 413150, "Stardew Valley")
    exe = d / "Contents" / "MacOS" if sys_ == "mac" else d
    exe.mkdir(parents=True, exist_ok=True); (exe / "Stardew Valley.dll").touch()
    g = games.get("stardew", sys_=sys_, home=home, env=_env(tmp_path, sys_))
    assert g.game_dir() == exe and g.mods_dir() == exe / "Mods" and not g.loader()["ok"]
    (exe / "StardewModdingAPI.dll").touch(); assert g.loader()["ok"]
    assert g.saves_dir() == (tmp_path / "home/AppData/Roaming/StardewValley/Saves" if sys_ == "windows" else home / ".config/StardewValley/Saves")
    # Windows: Steam's Play starts the plain game (the SMAPI installer leaves Steam alone), so launch starts SMAPI itself
    assert g.launch_url() == "steam://rungameid/413150"
    (exe / "StardewModdingAPI.exe").touch()
    if sys_ == "windows":
        assert g.launch_url() == f"script:{exe / 'StardewModdingAPI.exe'}" and "StardewModdingAPI.exe\" %command%" in g.launch_hint()
    else: assert g.launch_url() == "steam://rungameid/413150" and g.launch_option() is None


@pytest.mark.parametrize("sys_", ["mac", "windows", "linux"])
def test_cities_paths(tmp_path, sys_):
    home = tmp_path / "home"; d = _steam(home, sys_, 255710, "Cities_Skylines")
    m = d / ("Cities.app/Contents/Resources/Data/Managed" if sys_ == "mac" else "Cities_Data/Managed"); m.mkdir(parents=True); (m / "ICities.dll").touch()
    g = games.get("cities_skylines", sys_=sys_, home=home, env=_env(tmp_path, sys_))
    assert g.game_dir() == d and g.managed_dir() == m
    want = {"mac": home / "Library/Application Support/Colossal Order/Cities_Skylines",
            "windows": tmp_path / "home/AppData/Local/Colossal Order/Cities_Skylines",
            "linux": home / ".local/share/Colossal Order/Cities_Skylines"}[sys_]
    assert g.mods_dir() == want / "Addons" / "Mods" and g.cgs_file() == want / "userGameState.cgs"


def test_minecraft_paths(tmp_path):
    home = tmp_path / "home"; g = games.get("minecraft", sys_="mac", home=home, env=_env(tmp_path, "mac"))
    g.MAC_APPS = (tmp_path / "Applications",)
    assert not g.installed()
    mc = home / "Library/Application Support/minecraft"; (mc / "versions/fabric-loader-0.19.5-26.3").mkdir(parents=True)
    assert g.installed() and g.loader()["ok"] and g.mods_dir() == mc / "mods" and g.launch_url() is None


def test_minecraft_running_by_game_dir(tmp_path, monkeypatch):
    """A Minecraft client is a java process with `--gameDir <folder>`: only one started on THIS folder counts (spaces in the path too)."""
    import subprocess
    home = tmp_path / "my home"; mc = home / ".minecraft"
    ps = ("1 /usr/bin/java -cp x net.fabricmc.loader.impl.launch.knot.KnotClient --username A --gameDir /lab/instance --assetsDir /a\n"
          "2 [java] <defunct>\n")
    monkeypatch.setattr(games.shutil, "which", lambda n: "/bin/" + n)
    monkeypatch.setattr(games, "_run", lambda args, timeout=20: subprocess.CompletedProcess(args, 0, ps, ""))
    g = games.get("minecraft", sys_="linux", home=home, env=_env(tmp_path, "linux"))
    assert g.running() is False
    ps += f"3 /opt/jdk/bin/java -Xmx2G KnotClient --gameDir {mc} --assetsDir {mc}/assets\n"
    assert g.running() is True
    ps = f"3 java KnotClient --version 26.3 --gameDir {mc}\n"
    assert g.running() is True
    assert games.get("minecraft", sys_="windows", home=home, env=_env(tmp_path, "windows")).running() is None

def test_minecraft_install_needs_a_mod_jar(tmp_path):
    """gradlew build leaves the mod jar and a *-sources.jar (same fabric.mod.json, no classes) in build/libs; Fabric loads no folders."""
    home = tmp_path / "home"; g = games.get("minecraft", sys_="linux", home=home, env=_env(tmp_path, "linux"))
    (home / ".minecraft/versions/fabric-loader-0.19.5-26.3").mkdir(parents=True)
    libs = tmp_path / "build" / "libs"; libs.mkdir(parents=True)
    with zipfile.ZipFile(libs / "hello-1.0.0-sources.jar", "w") as z: z.writestr("fabric.mod.json", "{}"); z.writestr("org/Hello.java", "class Hello {}")
    with zipfile.ZipFile(libs / "hello-1.0.0.jar", "w") as z: z.writestr("fabric.mod.json", "{}"); z.writestr("org/Hello.class", b"\xca\xfe")
    with zipfile.ZipFile(libs / "plain.jar", "w") as z: z.writestr("org/Hello.class", b"\xca\xfe")
    (libs / "broken.jar").write_bytes(b"not a zip")
    for bad, why in ((libs, ".jar"), (libs / "hello-1.0.0-sources.jar", "sources"), (libs / "plain.jar", "fabric.mod.json"), (libs / "broken.jar", "zip")):
        with pytest.raises(games.NativeError, match=why): g.install(bad)
    assert not (home / ".minecraft/mods").exists() or not any((home / ".minecraft/mods").iterdir())
    assert g.install(libs / "hello-1.0.0.jar")["path"] == str(home / ".minecraft/mods/hello-1.0.0.jar")


def test_install_backup_restore_cities(tmp_path):
    home = tmp_path / "home"; d = _steam(home, "mac", 255710, "Cities_Skylines")
    m = d / "Cities.app/Contents/Resources/Data/Managed"; m.mkdir(parents=True); (m / "ICities.dll").touch()
    g = games.get("cities_skylines", sys_="mac", home=home, env=_env(tmp_path, "mac"))
    saves = g.saves_dir(); saves.mkdir(parents=True); (saves / "city.crp").write_text("v1", encoding="utf-8")
    src = tmp_path / "build" / "Memory2World"; (src / "Source").mkdir(parents=True); (src / "Source/Mod.cs").write_text("// v1", encoding="utf-8")
    with pytest.raises(games.NativeError, match="build"): g.install(src)       # the macOS game cannot compile source
    (src / "Memory2World.dll").write_bytes(b"MZ")

    r = g.install(src)
    dst = g.mods_dir() / "Memory2World"
    assert (dst / "Source/Mod.cs").read_text(encoding="utf-8") == "// v1" and r["backup"]
    assert cgs.read(g.cgs_file())["bool"][cgs.mod_key(str(dst))] is True
    # nothing changed in the saves: no second backup; the old mod goes to the trash, not deleted
    (src / "Source/Mod.cs").write_text("// v2", encoding="utf-8"); r2 = g.install(src)
    assert r2["backup"] is None and Path(r2["replaced_to_trash"], "Source/Mod.cs").read_text(encoding="utf-8") == "// v1"

    (saves / "city.crp").write_text("broken", encoding="utf-8")
    out = g.restore(g.backups()[0]["stamp"])
    assert (saves / "city.crp").read_text(encoding="utf-8") == "v1" and out["moved_to_trash"]
    assert g.uninstall("Memory2World")["moved_to_trash"] and not dst.exists()
    assert cgs.mod_key(str(dst)) not in cgs.read(g.cgs_file())["bool"]                # switched off = the key removed
    with pytest.raises(games.NativeError): g.uninstall("SomeoneElsesMod")


def test_refuses_while_running(tmp_path, monkeypatch):
    home = tmp_path / "home"; g = games.get("stardew", sys_="mac", home=home, env=_env(tmp_path, "mac"))
    g.saves_dir().mkdir(parents=True); stamp = g.backup()["stamp"]
    monkeypatch.setattr(games.Game, "running", lambda self: True)
    with pytest.raises(games.NativeError): g.restore(stamp)


def test_install_needs_loader(tmp_path):
    home = tmp_path / "home"; d = _steam(home, "mac", 413150, "Stardew Valley")
    exe = d / "Contents/MacOS"; exe.mkdir(parents=True); (exe / "Stardew Valley.dll").touch()
    g = games.get("stardew", sys_="mac", home=home, env=_env(tmp_path, "mac"))
    (tmp_path / "Mod").mkdir()
    with pytest.raises(games.NativeError, match="SMAPI"): g.install(tmp_path / "Mod")


def test_stardew_install_needs_manifest(tmp_path):
    """dotnet build's bin/Release/net6.0 has the DLL but no manifest.json (ModBuildConfig deploy off): SMAPI would skip it in silence."""
    home = tmp_path / "home"; d = _steam(home, "linux", 413150, "Stardew Valley")
    for f in ("Stardew Valley.dll", "StardewModdingAPI.dll"): (d / f).touch()
    g = games.get("stardew", sys_="linux", home=home, env=_env(tmp_path, "linux"))
    out = tmp_path / "bin" / "net6.0"; out.mkdir(parents=True); (out / "Hello.dll").touch()
    with pytest.raises(games.NativeError, match="manifest.json"): g.install(out, "Hello")
    with pytest.raises(games.NativeError, match="manifest.json"): g.install(out / "Hello.dll", "Hello")
    assert not (d / "Mods" / "Hello").exists()
    (out / "manifest.json").write_text("{}", encoding="utf-8")
    assert g.install(out, "Hello")["path"] == str(d / "Mods" / "Hello")


# ---------------------------------------------------------------- The Sims 4
def _s4(tmp, sys_, docs=None, folder="The Sims 4", **env):
    """A fake Sims 4 user folder under <docs>/Electronic Arts/<folder> -> (adapter, user folder)."""
    home = tmp / "home"; docs = docs or home / "Documents"; u = docs / "Electronic Arts" / folder; u.mkdir(parents=True)
    e = {**_env(tmp, sys_), "USERPROFILE": str(home), **{k: str(v) for k, v in env.items()}}
    return games.get("sims4", sys_=sys_, home=home, env=e), u


@pytest.mark.parametrize("sys_", ["mac", "windows"])
def test_sims4_user_folder(tmp_path, sys_):
    g = games.get("sims4", sys_=sys_, home=tmp_path / "home", env=_env(tmp_path, sys_))
    assert not g.installed() and g.user_dir() == tmp_path / "home/Documents/Electronic Arts/The Sims 4"      # not created yet: where it will be
    g, u = _s4(tmp_path, sys_)
    assert g.installed() and g.user_dir() == u and g.mods_dir() == u / "Mods" and g.saves_dir() == u / "saves"
    g.MAC_EA_APP = tmp_path / "no EA app.app"
    assert g.launch_url() is None                                                                        # no Steam install, no EA app
    if sys_ == "mac":                                                                                    # 2026-10-31: the EA App, then PLAY
        g.MAC_EA_APP = tmp_path / "EA app.app"; g.MAC_EA_APP.mkdir()
        assert g.launch_url() == str(g.MAC_EA_APP) and not g.launch_needs_game_pid


def test_sims4_onedrive_and_localised(tmp_path):
    od = tmp_path / "home/OneDrive/Documents"
    g, u = _s4(tmp_path, "windows", docs=od)                                    # found through %USERPROFILE%\OneDrive without the env var
    assert g.user_dir() == u
    od2 = tmp_path / "other/OneDrive - Firma/文档"
    g, u = _s4(tmp_path / "x", "windows", docs=od2, OneDriveCommercial=tmp_path / "other/OneDrive - Firma")
    assert g.user_dir() == u
    # a localised folder name (the game's language): found by what is inside; "The Sims 4" is preferred when both exist
    g, u = _s4(tmp_path / "y", "mac", folder="Les Sims 4"); (u / "Options.ini").write_text("[options]\n", encoding="utf-8")
    assert g.user_dir() == u and g.mods_dir() == u / "Mods"
    (u.parent / "The Sims 4").mkdir(); assert g.user_dir() == u                 # an empty "The Sims 4" does not hide the real one
    (u.parent / "The Sims 4" / "Mods").mkdir(); assert g.user_dir() == u.parent / "The Sims 4"
    # the pin wins
    g.env["GAMEANYTHING_SIMS4_DIR"] = str(tmp_path / "pinned"); assert g.user_dir() == tmp_path / "pinned"


def test_sims4_linux_proton_prefix(tmp_path):
    home = tmp_path / "home"; root = home / ".steam/steam"; (root / "steamapps").mkdir(parents=True)
    g = games.get("sims4", sys_="linux", home=home, env=_env(tmp_path, "linux"))
    assert not g.installed()
    u = root / "steamapps/compatdata/1222670/pfx/drive_c/users/steamuser/Documents/Electronic Arts/The Sims 4"; u.mkdir(parents=True)
    assert g.installed() and g.user_dir() == u


def test_sims4_linux_plain_wine_prefix(tmp_path):
    """Linux without Steam: the EA app installed into a Wine prefix ($WINEPREFIX, else ~/.wine); Wine names the user after $USER."""
    home = tmp_path / "home"; pfx = tmp_path / "pfx"
    g = games.get("sims4", sys_="linux", home=home, env={**_env(tmp_path, "linux"), "WINEPREFIX": str(pfx), "USER": "player"})
    assert not g.installed() and g.game_dir() is None
    u = pfx / "drive_c/users/player/Documents/Electronic Arts/The Sims 4"; (u / "Mods").mkdir(parents=True)
    gd = pfx / "drive_c/Program Files/EA Games/The Sims 4"; gd.mkdir(parents=True)
    assert g.installed() and g.user_dir() == u and g.game_dir() == gd and g.launch_url() is None
    d = games.get("sims4", sys_="linux", home=home, env={**_env(tmp_path, "linux"), "USER": "player"})
    (home / ".wine/drive_c/users/player/Documents/Electronic Arts/The Sims 4").mkdir(parents=True)
    assert d.user_dir() == home / ".wine/drive_c/users/player/Documents/Electronic Arts/The Sims 4"


def test_sims4_game_dir_and_launch(tmp_path):
    home = tmp_path / "home"; d = _steam(home, "mac", 1222670, "The Sims 4")
    g, _ = _s4(tmp_path, "mac"); assert g.game_dir() == d and g.launch_url() == "steam://rungameid/1222670"
    gw, _ = _s4(tmp_path / "w", "windows", ProgramFiles=tmp_path / "w/PF"); ea = tmp_path / "w/PF/EA Games/The Sims 4"; ea.mkdir(parents=True)
    assert gw.game_dir() == ea and gw.launch_url() is None


OPTIONS = "[options]\r\nmodsdisabled = 1\r\nlastsavedgame = 星光\r\n\r\n[video]\r\nscriptmodsenabled = 0\r\nwidth = 1920\r\n"


def test_sims4_options_switch_keeps_the_rest(tmp_path):
    g, u = _s4(tmp_path, "windows"); (u / "Options.ini").write_bytes(OPTIONS.encode("utf-8"))
    lo = g.loader(); assert not lo["ok"] and "Options.ini" in lo["detail"] and "脚本模组" in lo["detail"]
    r = g.set_switches(); assert r["options"].startswith("set")
    assert (u / "Options.ini").read_bytes() == OPTIONS.replace("modsdisabled = 1", "modsdisabled = 0").replace("scriptmodsenabled = 0", "scriptmodsenabled = 1").encode("utf-8")
    assert g.loader()["ok"]
    b = (u / "Options.ini").read_bytes(); assert g.set_switches()["options"] == "ok" and (u / "Options.ini").read_bytes() == b
    # a missing key is added under [options], in the file's own line ending; LF files stay LF
    (u / "Options.ini").write_bytes(b"[options]\nwidth = 5\n"); g.set_switches()
    got = (u / "Options.ini").read_bytes(); assert b"\r" not in got and got.startswith(b"[options]\n") and got.endswith(b"width = 5\n")
    assert {b"modsdisabled = 0", b"scriptmodsenabled = 1"} <= set(got.split(b"\n"))
    (u / "Options.ini").unlink(); assert "no Options.ini" in g.set_switches()["options"] and not (u / "Options.ini").exists()


def test_sims4_resource_cfg(tmp_path):
    g, u = _s4(tmp_path, "windows"); assert g.ensure_resource_cfg() and not g.ensure_resource_cfg()
    t = (u / "Mods/Resource.cfg").read_bytes().decode("ascii")
    assert t.startswith("Priority 500\r\nPackedFile *.package\r\n") and "PackedFile */*/*/*/*/*.package\r\n" in t
    g2, u2 = _s4(tmp_path / "m", "mac"); g2.ensure_resource_cfg(); assert b"\r" not in (u2 / "Mods/Resource.cfg").read_bytes()
    (u2 / "Mods/Resource.cfg").write_text("Priority 1\n", encoding="utf-8"); assert not g2.ensure_resource_cfg()      # hers stays


def _mod(p: Path, scripts=("N.ts4script",), packages=("N.package",)):
    import zipfile
    p.mkdir(parents=True, exist_ok=True)
    for s in scripts:
        (p / s).parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(p / s, "w") as z: z.writestr("m/__init__.pyc", b"x")
    for k in packages: (p / k).parent.mkdir(parents=True, exist_ok=True); (p / k).write_bytes(b"DBPF")
    return p


def test_sims4_depth_rules(tmp_path):
    g, _ = _s4(tmp_path, "mac")
    g.check_installable(_mod(tmp_path / "ok"))
    g.check_installable(_mod(tmp_path / "pk4", scripts=(), packages=("a/b/c/d/N.package",)))              # Mods/<name>/a/b/c/d = 5 folders
    with pytest.raises(games.NativeError, match="一层"): g.check_installable(_mod(tmp_path / "deep", scripts=("sub/N.ts4script",), packages=()))
    with pytest.raises(games.NativeError, match="5 层"): g.check_installable(_mod(tmp_path / "pk5", scripts=(), packages=("a/b/c/d/e/N.package",)))
    with pytest.raises(games.NativeError, match="没有"): g.check_installable(_mod(tmp_path / "none", scripts=(), packages=()))
    (tmp_path / "bad").mkdir(); (tmp_path / "bad/N.ts4script").write_bytes(b"not a zip")
    with pytest.raises(games.NativeError, match="zip"): g.check_installable(tmp_path / "bad")


def test_sims4_install_uninstall_backup(tmp_path):
    g, u = _s4(tmp_path, "windows"); (u / "Options.ini").write_bytes(OPTIONS.encode("utf-8"))
    (u / "saves").mkdir(); (u / "saves/slot1.save").write_text("v1", encoding="utf-8")
    src = _mod(tmp_path / "build/Hello", ("Hello.ts4script",), ("Hello.package",))
    r = g.install(src, "Hello"); dst = u / "Mods/Hello"
    assert r["backup"] and r["options"].startswith("set") and r["resource_cfg"] == "created"
    assert (dst / "Hello.ts4script").is_file() and g.loader()["ok"] and (u / "Mods/Resource.cfg").is_file()
    assert g.mods()["Hello"]["path"] == str(dst)
    bk = g.backups()[0]; names = {i["in_backup"] for i in bk["items"]}
    assert names == {"saves", "files/Options.ini"}                      # Resource.cfg did not exist yet
    (u / "Options.ini").write_text("changed", encoding="utf-8"); (u / "saves/slot1.save").write_text("v2", encoding="utf-8")
    g.restore(bk["stamp"]); assert (u / "Options.ini").read_bytes() == OPTIONS.encode("utf-8") and (u / "saves/slot1.save").read_text(encoding="utf-8") == "v1"
    g.set_switches()
    assert g.uninstall("Hello")["moved_to_trash"] and not dst.exists() and g.loader()["ok"]          # the switches stay on
    with pytest.raises(games.NativeError): g.uninstall("Other")
    with pytest.raises(games.NativeError, match="一层"): g.install(_mod(tmp_path / "bad", ("a/b.ts4script",), ()), "Bad")


def test_sims4_logs_and_process(tmp_path):
    import os
    g, u = _s4(tmp_path, "windows"); (u / "Mods/Hello").mkdir(parents=True)
    for n, t in (("lastException.txt", 1), ("lastException_2.txt", 5), ("lastUIException.txt", 3)):
        (u / n).write_text("x", encoding="utf-8"); os.utime(u / n, (t, t))
    (u / "Mods/Hello/Hello.log").write_text("hi", encoding="utf-8")
    assert {f.name for f in g.log_files()} == {"lastException_2.txt", "lastUIException.txt", "Hello.log"} and g.log().name == "Hello.log"
    assert dict(g.process_names) == {"windows": ("TS4_x64.exe",), "mac": ("The Sims 4",), "linux": ("TS4_x64.exe",)}


def test_sims4_package_only_build_roundtrip(tmp_path, monkeypatch):
    from gameanything.native import s4pkg
    monkeypatch.setattr(games, "python37", lambda *a, **k: None)                    # package-only needs no Python 3.7
    g, _ = _s4(tmp_path, "mac"); src = tmp_path / "Hello"
    (src / "package/tuning").mkdir(parents=True)
    (src / "package/strings.json").write_text('{"hello_name": "你好 Hello"}', encoding="utf-8")
    (src / "package/tuning/Hello_Buff.xml").write_text('<?xml version="1.0"?>\n<I c="Buff" i="buff" m="buffs.buff" n="Hello_Buff">\n<T n="buff_name">{{str:hello_name}}</T>\n</I>\n', encoding="utf-8")
    (src / "package/raw").mkdir(); (src / "package/raw/00B2D882_00000000_00000000000000AB.png").write_bytes(b"\x89PNG" * 100)
    b = g.build(src); pk = Path(b["staged"]) / "Hello.package"
    assert b["modules"] == 0 and b["resources"] == 3 and Path(b["staged"]).parts[-3:] == ("Hello", "mod", "Hello") and not (Path(b["staged"]) / "Hello.ts4script").exists()
    with s4pkg.Package(str(pk)) as p:
        kinds = {e[0] for e in p.entries}
        assert kinds == {s4pkg.types()["buff"], s4pkg.STBL_TYPE, 0x00B2D882}
        buff = p.get(s4pkg.types()["buff"], 0, s4pkg.fnv64("Hello_Buff", high_bit=True)).decode("utf-8")
        assert 'n="Hello_Buff"' in buff and f's="{s4pkg.fnv64("Hello_Buff", high_bit=True)}"' in buff and "0x%08X" % s4pkg.fnv32("hello_name") in buff
        st = next(e for e in p.entries if e[0] == s4pkg.STBL_TYPE); d = p.read(st)
        assert d[:4] == b"STBL" and "你好 Hello".encode("utf-8") in d
        assert p.get(0x00B2D882, 0, 0xAB) == b"\x89PNG" * 100
    g.check_installable(Path(b["staged"])); assert g.install(b["staged"], "Hello")["name"] == "Hello"
    (src / "package/tuning/Hello_Buff.xml").write_text('<I i="nope" n="x"/>', encoding="utf-8")
    with pytest.raises(games.NativeError, match="打包失败"): g.build(src)


def test_sims4_script_build_needs_python37(tmp_path, monkeypatch):
    monkeypatch.setattr(games, "python37", lambda *a, **k: None)
    g, _ = _s4(tmp_path, "windows"); src = tmp_path / "Scripted"
    (src / "scripts/m").mkdir(parents=True); (src / "scripts/m/__init__.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(games.NativeError, match="Python 3.7") as e: g.build(src)
    assert "python.org" in str(e.value) and "pyenv" in str(e.value)
    assert not g.toolchain()["ok"] and "python.org" in g.toolchain()["setup"]
    with pytest.raises(games.NativeError, match="没有可以构建"): g.build(tmp_path)


def test_sims4_script_build_with_python37(tmp_path):
    """Only where a real 3.7 exists (the bytecode must be the game's): skipped otherwise."""
    py = games.python37()
    if py is None: pytest.skip("no Python 3.7 here")
    import zipfile
    g, _ = _s4(tmp_path, "mac"); src = tmp_path / "Scripted"
    (src / "scripts/m").mkdir(parents=True); (src / "scripts/m/__init__.py").write_text("x = 1  # 你好\n", encoding="utf-8")
    b = g.build(src)
    with zipfile.ZipFile(Path(b["staged"]) / "Scripted.ts4script") as z: assert z.namelist() == ["m/__init__.pyc"]
    assert b["modules"] == 1
    (src / "scripts/m/__init__.py").write_text("def (:\n", encoding="utf-8")
    with pytest.raises(games.NativeError, match="编译失败"): g.build(src)


def test_sims4_compile_helper_runs(tmp_path, monkeypatch):
    """The compile step through a subprocess, with the current interpreter standing in for 3.7 (the .pyc version is not checked here)."""
    import sys, zipfile
    monkeypatch.setattr(games, "python37", lambda *a, **k: [sys.executable])
    g, _ = _s4(tmp_path, "mac"); src = tmp_path / "S"
    (src / "scripts/m").mkdir(parents=True); (src / "scripts/m/__init__.py").write_text("x = '你好'\n", encoding="utf-8")
    b = g.build(src)
    with zipfile.ZipFile(Path(b["staged"]) / "S.ts4script") as z: assert z.namelist() == ["m/__init__.pyc"]
    (src / "scripts/m/bad.py").write_text("def (:\n", encoding="utf-8")
    with pytest.raises(games.NativeError, match="编译失败"): g.build(src)


# ---------------------------------------------------------------- Slay the Spire (ModTheSpire + BaseMod)
def _sts_jar(p: Path, modid="phd", extra=None):
    import json, zipfile
    p.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("ModTheSpire.json", json.dumps({"modid": modid, "name": "读博", "dependencies": ["basemod"]}, ensure_ascii=False))
        for n, b in (extra or {}).items(): z.writestr(n, b)
    return p


def _sts_game(home: Path, sys_: str) -> Path:
    d = _steam(home, sys_, 646570, "SlayTheSpire")
    gd = d / "SlayTheSpire.app/Contents/Resources" if sys_ == "mac" else d
    gd.mkdir(parents=True, exist_ok=True); (gd / "desktop-1.0.jar").write_bytes(b"PK")
    return gd


@pytest.mark.parametrize("sys_", ["mac", "windows", "linux"])
def test_sts_paths_and_loader(tmp_path, sys_):
    home = tmp_path / "home"; g = games.get("slay_the_spire", sys_=sys_, home=home, env=_env(tmp_path, sys_))
    assert not g.installed() and "SlayTheSpire" in str(g.saves_dir())          # not installed: where it would be, no crash
    gd = _sts_game(home, sys_)
    assert g.game_dir() == gd and g.mods_dir() == gd / "mods" and g.saves_dir() == gd / "saves"
    assert g.log() is None and g.log_files() == [gd / "sendToDevs/logs/SlayTheSpire.log"]
    assert g.launch_url() == "steam://run/646570" and "Play With Mods" in g.launch_hint()
    lo = g.loader(); assert not lo["ok"] and "1605060445" in lo["detail"] and "1605833019" in lo["detail"]
    ws = next(p for p in gd.parents if p.name == "steamapps") / "workshop/content/646570"
    (ws / "1605060445").mkdir(parents=True); (ws / "1605060445/ModTheSpire.jar").write_bytes(b"PK")
    assert not g.loader()["ok"] and "BaseMod" in g.loader()["detail"]
    (gd / "mods").mkdir(); (gd / "mods/BaseMod.jar").write_bytes(b"PK")       # BaseMod by hand, ModTheSpire from the Workshop
    lo = g.loader(); assert lo["ok"] and "1605060445" in lo["detail"] and str(gd / "mods/BaseMod.jar") in lo["detail"]
    (gd / "sendToDevs/logs").mkdir(parents=True); (gd / "sendToDevs/logs/SlayTheSpire.log").write_text("INFO basemod.BaseMod> 读博\n", encoding="utf-8")
    assert g.log() == gd / "sendToDevs/logs/SlayTheSpire.log"


def test_sts_pin_to_the_app_bundle(tmp_path):
    app = tmp_path / "游戏 文件夹/SlayTheSpire.app"; (app / "Contents/Resources").mkdir(parents=True); (app / "Contents/Resources/desktop-1.0.jar").write_bytes(b"PK")
    for pin in (app, app.parent):
        g = games.get("slay_the_spire", sys_="mac", home=tmp_path / "home", env={**_env(tmp_path, "mac"), "GAMEANYTHING_STS_DIR": str(pin)})
        assert g.game_dir() == app / "Contents/Resources"


def test_sts_install_backup_restore(tmp_path, monkeypatch):
    home = tmp_path / "home 小雨"; gd = _sts_game(home, "mac")
    (gd / "ModTheSpire.jar").write_bytes(b"PK"); (gd / "mods").mkdir(); (gd / "mods/BaseMod.jar").write_bytes(b"PK")
    (gd / "mods/someone-elses.jar").write_bytes(b"PK")
    (gd / "saves").mkdir(); (gd / "saves/IRONCLAD.autosave").write_text("v1", encoding="utf-8")
    (gd / "preferences").mkdir(); (gd / "preferences/STSUnlocks").write_text('{"解锁": 1}', encoding="utf-8")
    g = games.get("slay_the_spire", sys_="mac", home=home, env=_env(tmp_path, "mac"))
    jar = _sts_jar(tmp_path / "build 构建/phd.jar")
    with pytest.raises(games.NativeError, match=r"\.jar"): g.install(tmp_path / "build 构建")
    with pytest.raises(games.NativeError, match="ModTheSpire.json"): g.install(_bare_jar(tmp_path / "bare.jar"))
    r = g.install(jar, "读博 PhD")
    dst = gd / "mods/读博 PhD.jar"
    assert r["backup"] and dst.is_file() and r["path"] == str(dst) and g.mods()["读博 PhD.jar"]["path"] == str(dst)
    bk = g.backups()[0]; assert {i["in_backup"] for i in bk["items"]} == {"saves", "files/preferences"}
    assert g.install(jar, "读博 PhD")["backup"] is None                       # nothing changed since: no second backup
    (gd / "preferences/STSUnlocks").write_text("broken", encoding="utf-8")
    assert g.needs_backup()                                                   # unlocks count as saves
    g.restore(bk["stamp"]); assert (gd / "preferences/STSUnlocks").read_text(encoding="utf-8") == '{"解锁": 1}'
    monkeypatch.setattr(games.Game, "running", lambda self: True)
    with pytest.raises(games.NativeError, match="正在运行"): g.install(jar)
    with pytest.raises(games.NativeError, match="正在运行"): g.uninstall("读博 PhD")
    monkeypatch.setattr(games.Game, "running", lambda self: False)
    t = g.uninstall("读博 PhD")["moved_to_trash"]                             # the name without .jar works too
    assert t and Path(t).is_file() and ".trash" in t and not dst.exists()
    with pytest.raises(games.NativeError, match="不是 GameAnything 装的"): g.uninstall("someone-elses.jar")
    assert (gd / "mods/someone-elses.jar").is_file() and (gd / "mods/BaseMod.jar").is_file()


def _bare_jar(p: Path):
    import zipfile
    with zipfile.ZipFile(p, "w") as z: z.writestr("a.class", b"\xca\xfe")
    return p


def test_sts_running_check(monkeypatch):
    """The app's own launcher is not running (the base check, patched to False here); ModTheSpire's java is found by its jar, a shell
    whose command line names the jar is not."""
    import subprocess
    comm = {"11": "-bash\n", "22": "/Applications/x/jre/bin/java\n"}
    def run(args, timeout=20):
        if args[:2] == ["pgrep", "-f"]: return subprocess.CompletedProcess(args, 0, " ".join(comm) + "\n", "")
        if args[0] == "ps": return subprocess.CompletedProcess(args, 0, comm[args[-1]], "")
        return subprocess.CompletedProcess(args, 1, "", "")
    monkeypatch.setattr(games, "_run", run); monkeypatch.setattr(games.shutil, "which", lambda n: "/usr/bin/" + n)
    assert games.SlayTheSpire(sys_="mac", env={}).running() is True
    del comm["22"]; assert games.SlayTheSpire(sys_="linux", env={}).running() is False
    assert games.SlayTheSpire(sys_="windows", env={}).running() is None                 # ModTheSpire's java cannot be told apart on Windows


class _FakeRun:
    """Stands in for subprocess.run of javac / dotnet: records argv and writes what the tool would."""
    def __init__(self, make): self.calls = []; self.make = make
    def __call__(self, args, **kw):
        import subprocess
        self.calls.append((args, kw)); self.make(args, kw)
        return subprocess.CompletedProcess(args, 0, "ok", "")


def test_sts_build_makes_the_lab_jar(tmp_path, monkeypatch):
    import json, zipfile
    home = tmp_path / "home"; gd = _sts_game(home, "linux")
    (gd / "ModTheSpire.jar").write_bytes(b"PK"); (gd / "mods").mkdir(); (gd / "mods/BaseMod.jar").write_bytes(b"PK")
    g = games.get("slay_the_spire", sys_="linux", home=home, env=_env(tmp_path, "linux"))
    src = tmp_path / "读博 mod"; (src / "src/phd/cards").mkdir(parents=True); (src / "src/phd/cards/Idea.java").write_text("package phd.cards; class Idea {}", encoding="utf-8")
    (src / "resources/phd/localization/zhs").mkdir(parents=True)
    (src / "resources/ModTheSpire.json").write_text('﻿{"modid": "phd", "dependencies": ["basemod"]}', encoding="utf-8")
    (src / "resources/phd/localization/zhs/CardStrings.json").write_text('{"phd:Idea": {"NAME": "灵感"}}', encoding="utf-8")
    (src / "libs").mkdir()
    with zipfile.ZipFile(src / "libs/extra.jar", "w") as z: z.writestr("lib/X.class", b"\xca\xfe"); z.writestr("META-INF/MANIFEST.MF", b"x")
    monkeypatch.setattr(games.SlayTheSpire, "toolchain", lambda self: {"ok": True, "setup": ""})
    monkeypatch.setattr(games.SlayTheSpire, "_javac", lambda self: (Path("/jdk/bin/javac"), {"version": 25}))
    def make(args, kw):
        out = Path(args[args.index("-d") + 1]); (out / "phd/cards").mkdir(parents=True); (out / "phd/cards/Idea.class").write_bytes(b"\xca\xfe\x00\x00\x00\x34")
        srcs = Path(args[-1][1:]).read_text(encoding="utf-8").split()
        assert srcs == ['"src/phd/cards/Idea.java"'] and kw["cwd"] == str(src)
    fake = _FakeRun(make); monkeypatch.setattr(games.subprocess, "run", fake)
    b = g.build(src)
    args = fake.calls[0][0]
    assert args[:3] == [str(Path("/jdk/bin/javac")), "--release", "8"] and "UTF-8" in args
    cp = args[args.index("-cp") + 1]                                        # the linux game joins with ":" (a Windows host's paths have "C:" too)
    assert cp.startswith(":".join(str(x) for x in (gd / "desktop-1.0.jar", gd / "ModTheSpire.jar", gd / "mods/BaseMod.jar")) + ":") and cp.endswith("extra.jar")
    assert b["modid"] == "phd" and Path(b["jar"]).name == "phd.jar"
    with zipfile.ZipFile(b["jar"]) as z:
        names = set(z.namelist())
        assert {"META-INF/MANIFEST.MF", "ModTheSpire.json", "phd/cards/Idea.class", "phd/localization/zhs/CardStrings.json", "lib/X.class"} <= names
        assert json.loads(z.read("phd/localization/zhs/CardStrings.json").decode("utf-8"))["phd:Idea"]["NAME"] == "灵感"
    g.check_installable(Path(b["jar"]))
    with pytest.raises(games.NativeError, match="ModTheSpire.json"): g.build(tmp_path / "empty")


def test_sts_build_real_javac(tmp_path):
    """Only where a JDK 9+ is installed: compiles one class against fake game jars (no game API used)."""
    import zipfile
    home = tmp_path / "home"; gd = _sts_game(home, "linux")
    g = games.get("slay_the_spire", home=home, env=_env(tmp_path, games.osdirs.system()))
    if not g.toolchain()["ok"]: pytest.skip("no JDK 9+ here")
    g.env["GAMEANYTHING_STS_DIR"] = str(gd)
    for p in (gd / "desktop-1.0.jar", gd / "ModTheSpire.jar", gd / "mods/BaseMod.jar"):
        p.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(p, "w") as z: z.writestr("README", "x")
    src = tmp_path / "我的 mod"; (src / "src/m").mkdir(parents=True); (src / "src/m/A.java").write_text('package m; public class A { String s = "读博"; }', encoding="utf-8")
    (src / "ModTheSpire.json").write_text('{"modid": "m"}', encoding="utf-8")
    b = g.build(src)
    with zipfile.ZipFile(b["jar"]) as z: assert z.read("m/A.class")[6:8] == b"\x00\x34"            # Java 8 bytecode


# ---------------------------------------------------------------- Overcooked! 2 (BepInEx 5)
def _oc2_game(home: Path, sys_: str, bepinex=True) -> Path:
    d = _steam(home, sys_, 728880, "Overcooked! 2")
    m = d / ("Overcooked2.app/Contents/Resources/Data/Managed" if sys_ == "mac" else "Overcooked2_Data/Managed"); m.mkdir(parents=True)
    for n in ("Assembly-CSharp.dll", "UnityEngine.dll", "UnityEngine.CoreModule.dll", "mscorlib.dll"): (m / n).write_bytes(b"MZ")
    if bepinex:
        (d / "BepInEx/core").mkdir(parents=True); (d / "BepInEx/core/BepInEx.dll").write_bytes(b"MZ"); (d / "BepInEx/core/0Harmony.dll").write_bytes(b"MZ")
        (d / ("winhttp.dll" if sys_ == "windows" else "run_bepinex.sh")).write_bytes(b"x")
    return d


@pytest.mark.parametrize("sys_", ["mac", "windows", "linux"])
def test_doctor_does_not_look_for_processes_of_games_not_found(tmp_path, monkeypatch, sys_):
    # A real Windows 11 ARM64 PC with no game (2026-10-31): `native doctor` took 22 s, one `tasklist` per game and a 9.5 s PowerShell
    # process query for Terraria, so the new-project wizard's game list (/api/onboard/games) timed out.
    home = tmp_path / "home"; e = {**_env(tmp_path, sys_), "USERPROFILE": str(home)}
    def boom(): raise AssertionError("running() of a game that is not installed")
    for gid in games.GAMES:
        g = games.get(gid, sys_=sys_, home=home, env=e); monkeypatch.setattr(g, "running", boom)
        assert not g.installed() and g.info()["running"] is False, gid


def _pe(machine: int) -> bytes:
    return b"MZ" + bytes(0x3A) + (0x40).to_bytes(4, "little") + b"PE\0\0" + machine.to_bytes(2, "little") + bytes(64)


def test_oc2_windows_bepinex_must_match_the_32_bit_game(tmp_path):
    # A real Windows 11 PC (2026-11-01): Overcooked2.exe is 32-bit; the x64 BepInEx was "ok" in doctor but never loaded.
    home = tmp_path / "home"; e = {**_env(tmp_path, "windows"), "USERPROFILE": str(home)}
    g = games.get("overcooked2", sys_="windows", home=home, env=e)
    d = _oc2_game(home, "windows"); (d / "Overcooked2.exe").write_bytes(_pe(0x14C)); (d / "winhttp.dll").write_bytes(_pe(0x8664))
    lo = g.loader(); assert not lo["ok"] and "x64 BepInEx" in lo["detail"] and "BepInEx_win_x86" in lo["detail"]
    (d / "winhttp.dll").write_bytes(_pe(0x14C)); assert g.loader()["ok"]
    (d / "winhttp.dll").unlink(); assert "BepInEx_win_x86" in g.loader()["detail"]


@pytest.mark.parametrize("sys_", ["mac", "windows", "linux"])
def test_oc2_paths_and_loader(tmp_path, sys_):
    home = tmp_path / "home"; e = {**_env(tmp_path, sys_), "USERPROFILE": str(home)}
    g = games.get("overcooked2", sys_=sys_, home=home, env=e)
    assert not g.installed(); g.info()                                            # not installed: no crash
    d = _oc2_game(home, sys_, bepinex=False)
    assert g.game_dir() == d and g.mods_dir() == d / "BepInEx/plugins" and g.managed_dir().name == "Managed"
    lo = g.loader(); assert not lo["ok"] and "BepInEx" in lo["detail"] and ("Windows" in lo["detail"] if sys_ == "windows" else "unix" in lo["detail"])
    (d / "BepInEx/core").mkdir(parents=True); (d / "BepInEx/core/BepInEx.dll").write_bytes(b"MZ")
    assert not g.loader()["ok"] and ("winhttp.dll" if sys_ == "windows" else "run_bepinex.sh") in g.loader()["detail"]
    (d / ("winhttp.dll" if sys_ == "windows" else "run_bepinex.sh")).write_bytes(b"x")
    assert g.loader()["ok"] and "not run yet" in g.loader()["detail"]
    want = {"mac": home / "Library/Application Support/Team17/Overcooked2", "windows": home / "AppData/LocalLow/Team17/Overcooked2",
            "linux": home / ".config/unity3d/Team17/Overcooked2"}[sys_]
    assert g.saves_dir() == want
    assert ("run_bepinex.sh" in g.launch_hint()) == (sys_ != "windows") and g.launch_url() == "steam://rungameid/728880"
    # the plugin log wins over Unity's Player.log
    pl = g.log_files()[-1]; pl.parent.mkdir(parents=True, exist_ok=True); pl.write_text("unity", encoding="utf-8")
    assert g.log() == pl
    (d / "BepInEx/LogOutput.log").write_text("[Info   :   BepInEx] Loading [HkFood 1.0]", encoding="utf-8"); assert g.log() == d / "BepInEx/LogOutput.log"


def test_oc2_mac_old_unity_folder(tmp_path):
    home = tmp_path / "home"; old = home / "Library/Application Support/unity.Team17.Overcooked2"; old.mkdir(parents=True)
    assert games.get("overcooked2", sys_="mac", home=home, env=_env(tmp_path, "mac")).saves_dir() == old


def test_oc2_install_backup_restore(tmp_path, monkeypatch):
    home = tmp_path / "home 小雨"; d = _oc2_game(home, "linux")
    (d / "BepInEx/plugins").mkdir(); (d / "BepInEx/plugins/OtherPlugin.dll").write_bytes(b"MZ")
    g = games.get("overcooked2", sys_="linux", home=home, env=_env(tmp_path, "linux"))
    sv = g.saves_dir() / "76561199810022756"; sv.mkdir(parents=True); (sv / "CoopSlot_SaveFile_0.save").write_bytes(b"v1")
    src = tmp_path / "构建 out/HkFood"; (src / "models/菠萝包").mkdir(parents=True); (src / "HkFood.dll").write_bytes(b"MZ1")
    (src / "models/菠萝包/model.obj").write_text("v 0 0 0\n", encoding="utf-8")
    with pytest.raises(games.NativeError, match="dll"): g.install(src / "models")
    bad = tmp_path / "bad"; bad.mkdir(); (bad / "OC2Bridge.dll").write_bytes(b"MZ")
    with pytest.raises(games.NativeError, match="OC2Bridge"): g.install(bad)
    r = g.install(src); dst = d / "BepInEx/plugins/HkFood"
    assert r["backup"] and (dst / "models/菠萝包/model.obj").is_file() and (dst / "HkFood.dll").read_bytes() == b"MZ1"
    (g.saves_dir() / "Player.log").write_text("a new start", encoding="utf-8")
    assert not g.needs_backup()                                                  # Player.log is not a save
    (sv / "CoopSlot_SaveFile_0.save").write_bytes(b"broken")
    g.restore(g.backups()[0]["stamp"]); assert (sv / "CoopSlot_SaveFile_0.save").read_bytes() == b"v1"
    one = g.install(src / "HkFood.dll", "HkFood.dll"); assert Path(one["path"]).is_file()      # a single DLL works too
    monkeypatch.setattr(games.Game, "running", lambda self: True)
    with pytest.raises(games.NativeError, match="正在运行"): g.uninstall("HkFood")
    monkeypatch.setattr(games.Game, "running", lambda self: False)
    assert g.uninstall("HkFood")["moved_to_trash"] and g.uninstall("HkFood.dll")["moved_to_trash"] and not dst.exists()
    with pytest.raises(games.NativeError): g.uninstall("OtherPlugin.dll")
    assert (d / "BepInEx/plugins/OtherPlugin.dll").is_file()


def test_oc2_build_points_the_lab_csproj_at_this_copy(tmp_path, monkeypatch):
    home = tmp_path / "home"; d = _oc2_game(home, "mac")
    g = games.get("overcooked2", sys_="mac", home=home, env=_env(tmp_path, "mac"))
    src = tmp_path / "港式 oc2/mod"; src.mkdir(parents=True)
    (src / "HkFood.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><AssemblyName>HkFood</AssemblyName>'
                                       '<GameDir Condition="\'$(GameDir)\' == \'\'">/home/player/x</GameDir></PropertyGroup><ItemGroup>'
                                       '<Reference Include="UnityEngine"><HintPath>$(GameDir)/Overcooked2_Data/Managed/UnityEngine.dll</HintPath></Reference>'
                                       '<Reference Include="BepInEx"><HintPath>$(GameDir)/BepInEx/core/BepInEx.dll</HintPath></Reference></ItemGroup></Project>', encoding="utf-8")
    (src / "Plugin.cs").write_text('class Plugin { const string Dir = "/home/player/oc2lab/hkfood/"; }', encoding="utf-8")
    (src / "NuGet.config").write_text("<configuration/>", encoding="utf-8"); (src / "names.txt").write_text("菠萝包", encoding="utf-8")
    monkeypatch.setattr(games, "dotnet", lambda *a, **k: {"ok": True, "path": "/usr/local/share/dotnet/dotnet", "sdks": ["8.0.100"]})
    def make(args, kw):
        o = Path(args[args.index("-o") + 1]); o.mkdir(parents=True)
        import re
        asm = re.search(r"<AssemblyName>(\w+)</AssemblyName>", Path(args[2]).read_text(encoding="utf-8")).group(1)
        for n in (f"{asm}.dll", f"{asm}.pdb", "UnityEngine.dll", "UnityEngine.pdb", "Newtonsoft.Json.dll"): (o / n).write_bytes(b"MZ")
    fake = _FakeRun(make); monkeypatch.setattr(games.subprocess, "run", fake)
    b = g.build(src)
    args = fake.calls[0][0]; man = d / "Overcooked2.app/Contents/Resources/Data/Managed"
    assert f"-p:M2wManaged={man}" in args and f"-p:M2wBepInExCore={d / 'BepInEx/core'}" in args
    proj = Path(args[2]).read_text(encoding="utf-8")
    assert "$(M2wManaged)/UnityEngine.dll" in proj and "$(M2wBepInExCore)/BepInEx.dll" in proj and "Overcooked2_Data" not in proj
    st = Path(b["staged"]); assert st.name == "HkFood" and Path(b["dll"]) == st / "HkFood.dll"
    assert sorted(p.name for p in st.iterdir()) == ["HkFood.dll", "HkFood.pdb", "Newtonsoft.Json.dll", "names.txt"]   # never the game's DLLs or the lab's NuGet.config;
    #                                                                     the plugin's .pdb goes along (ScriptEngine reads symbols)
    assert not (Path(args[2]).parent / "NuGet.config").exists()
    assert len(b["warnings"]) == 1 and "/home/player/oc2lab/hkfood/" in b["warnings"][0]
    g.check_installable(st)
    # no csproj: a minimal one that references what this copy has
    (src / "HkFood.csproj").unlink(); fake.calls.clear(); g.build(src, "Hello")
    proj = Path(fake.calls[0][0][2]).read_text(encoding="utf-8")
    assert "<AssemblyName>Hello</AssemblyName>" in proj and "$(M2wManaged)/Assembly-CSharp.dll" in proj and "UnityEngine.UI.dll" not in proj


def test_smoke_mods_have_the_build_layout():
    import json
    from gameanything.worlds import overcooked2, slay_the_spire
    mj = json.loads((slay_the_spire.SMOKE / "resources/ModTheSpire.json").read_text(encoding="utf-8"))
    assert mj["modid"] == "m2wsmoke" and "basemod" in mj["dependencies"] and list((slay_the_spire.SMOKE / "src").rglob("*.java"))
    assert "[M2W-smoke] loaded" in (overcooked2.SMOKE / "Plugin.cs").read_text(encoding="utf-8")


def test_build_folders_are_per_game(tmp_path):
    """Her Mac 2026-10-30: the disk ignores case, so Slay the Spire's and Minecraft's `m2wsmoke` and Terraria's `M2WSmoke` were one build
    folder and each build moved the one before away. The folder is per game now."""
    env = {"GAMEANYTHING_DATA": str(tmp_path / "d")}
    a = games.get("slay_the_spire", sys_="mac", home=tmp_path, env=env).build_dir("m2wsmoke")
    b = games.get("minecraft", sys_="mac", home=tmp_path, env=env).build_dir("m2wsmoke")
    c = games.get("terraria", sys_="mac", home=tmp_path, env=env).build_dir("M2WSmoke")
    assert len({str(x).lower() for x in (a, b, c)}) == 3 and a.parent.name == "slay_the_spire" and b.parent.parent == a.parent.parent



def test_minecraft_on_a_mac_opens_the_launcher_and_checks_the_installation(tmp_path):
    """2026-10-30: `launch` opens the Minecraft Launcher on a Mac and after_launch presses PLAY, but only when the Launcher's last used
    installation is the Fabric one (launcher_profiles.json, lastUsed); after_launch runs before the game's java exists."""
    import json
    home = tmp_path / "home"; g = games.get("minecraft", sys_="mac", home=home, env=_env(tmp_path, "mac"))
    g.MAC_APPS = (tmp_path / "Applications",)
    assert g.launch_url() is None and not g.launch_needs_game_pid
    (tmp_path / "Applications/Minecraft.app").mkdir(parents=True)
    assert g.launch_url() == str(tmp_path / "Applications/Minecraft.app")
    mc = home / "Library/Application Support/minecraft"; mc.mkdir(parents=True)
    prof = {"profiles": {"a": {"name": "Latest release", "lastVersionId": "latest-release", "lastUsed": "2026-10-01T00:00:00.000Z"},
                         "b": {"name": "fabric-loader-26.3", "lastVersionId": "fabric-loader-0.20.1-26.3", "lastUsed": "2026-10-30T05:57:40.788Z"}}}
    (mc / "launcher_profiles.json").write_text(json.dumps(prof), encoding="utf-8")
    assert g.last_installation() == ("fabric-loader-26.3", "fabric-loader-0.20.1-26.3")
    prof["profiles"]["a"]["lastUsed"] = "2026-10-31T00:00:00.000Z"; (mc / "launcher_profiles.json").write_text(json.dumps(prof), encoding="utf-8")
    r = g.after_launch(tmp_path, [], sleep=lambda s: None)                   # the vanilla one was used last: PLAY is not pressed
    assert "not Fabric" in r["launcher"] and "Latest release" in r["launcher"]
    assert games.get("minecraft", sys_="linux", home=home, env=_env(tmp_path, "linux")).launch_url() is None



def test_sims4_refuses_a_script_module_another_mod_already_has(tmp_path):
    """Her Mac 2026-10-30: an old Mods/m2w_smoke/ (module m2w_smoke) shadowed the newly installed smoke mod with the same module."""
    g, u = _s4(tmp_path, "mac")
    old = u / "Mods" / "m2w_smoke"; old.mkdir(parents=True)
    with zipfile.ZipFile(old / "m2w_smoke.ts4script", "w") as z: z.writestr("m2w_smoke/__init__.pyc", b"x")
    new = tmp_path / "M2WSmoke"; new.mkdir()
    with zipfile.ZipFile(new / "M2WSmoke.ts4script", "w") as z: z.writestr("m2w_smoke/__init__.pyc", b"y")
    with pytest.raises(games.NativeError, match="m2w_smoke"): g.check_installable(new)
    other = tmp_path / "Other"; other.mkdir()
    with zipfile.ZipFile(other / "Other.ts4script", "w") as z: z.writestr("other_mod.pyc", b"z")
    g.check_installable(other)                                                     # a different module: fine
    again = tmp_path / "m2w_smoke"; again.mkdir()
    with zipfile.ZipFile(again / "m2w_smoke.ts4script", "w") as z: z.writestr("m2w_smoke/__init__.pyc", b"w")
    g.check_installable(again)                                                     # the same folder name: it replaces the old copy
