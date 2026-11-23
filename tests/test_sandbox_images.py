"""The sandbox images' tools (lab/images/*: galab.py, ga-ksp, ga-mc, ga-sts) and the Minecraft pieces they share with native mode
(gameanything/native/mcversion.py, `gameanything native build --game minecraft`). No game, no Docker: fake folders."""
import argparse
import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from gameanything.native import games, mcversion

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "lab" / "images"
# The tools run inside the Linux images; a few tests need Linux / POSIX behaviour on the test machine itself.
on_windows = os.name == "nt"
exec_bits = pytest.mark.skipif(on_windows, reason="Windows has no executable bits (and no bash): the images are built on Linux / macOS")
links = pytest.mark.skipif(on_windows, reason="the tool makes symlinks (Windows without Developer Mode: WinError 1314)")


def _load(path: Path, name: str):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader); m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(IMAGES / "common"))
    try: loader.exec_module(m)
    finally: sys.path.remove(str(IMAGES / "common"))
    return m


# ---------------------------------------------------------------- the image files
TOOLS = [("stardew", "ga-sdv"), ("ksp", "ga-ksp"), ("minecraft", "ga-mc"), ("sts", "ga-sts"), ("terraria", "ga-terraria"),
         ("valheim", "ga-valheim"), ("overcooked2", "ga-oc2"), ("cities", "ga-cities"), ("civ6", "ga-civ6"), ("sims4", "ga-sims4")]


@exec_bits
@pytest.mark.parametrize("game,tool", TOOLS)
def test_image_files(game, tool):
    d = IMAGES / game
    df = (d / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG RUNTIME=gameanything-lab-" in df and f"lab/images/{game}/install.sh" in df and "USER player" in df and "PLAYER_UID" in df
    assert "x86_64 only" in df and "Rosetta" in df
    inst = (d / "install.sh").read_text(encoding="utf-8")
    assert "lab/images/common/layers.sh" in inst and "ga_need base" in inst and f"/usr/local/bin/{tool}" in inst
    assert "install-gameanything.sh" in inst
    r = subprocess.run(["bash", "-n", str(d / "install.sh")], capture_output=True, text=True); assert r.returncode == 0, r.stderr
    for f in (d / "install.sh", d / tool): assert f.stat().st_mode & 0o111, f"{f} not executable"
    r = subprocess.run([sys.executable, str(d / tool), "--help"], capture_output=True, text=True); assert r.returncode == 0, r.stderr


@exec_bits
@pytest.mark.parametrize("layer,script", [("base", "install-system.sh"), ("steam", "install-steam.sh"), ("dotnet", "install-dotnet.sh"),
                                          ("java", "install-java.sh"), ("wine", "install-wine.sh")])
def test_layer_files(layer, script):
    df = (IMAGES / layer / "Dockerfile").read_text(encoding="utf-8")
    assert f"lab/images/common/{script}" in df and "USER player" not in df       # the layers stay root: the game layer installs on them
    assert ("ARG UBUNTU=ubuntu:24.04@sha256:" in df) if layer == "base" else ("ARG BASE=gameanything-lab-" in df)
    s = IMAGES / "common" / script
    assert s.stat().st_mode & 0o111 and subprocess.run(["bash", "-n", str(s)]).returncode == 0
    assert f"/opt/gameanything/layers/{layer}" in s.read_text(encoding="utf-8")   # the marker layers.sh ga_need looks for


def test_install_scripts_set_their_own_umask():
    """An image server built with umask 077 (2026-10-30): /opt/gameanything, /game and galab.py's folder came out root-only and
    ga-steam / ga-sdv crashed for every player. Each install script sets umask 022 itself, before it makes anything."""
    scripts = sorted(IMAGES.glob("common/install-*.sh")) + sorted(IMAGES.glob("*/install.sh"))
    assert len(scripts) > 10
    for s in scripts:
        lines = s.read_text(encoding="utf-8").splitlines()
        i = lines.index("set -euo pipefail")
        assert any(l.startswith("umask 022") for l in lines[i + 1:i + 4]), s
        assert not any(l.startswith(("mkdir", "install ", "cp ", "echo ")) for l in lines[:i]), s


def _instructions(dockerfile: Path):
    """(instruction, rest) of a Dockerfile, continuation lines joined, comments dropped."""
    out, cur = [], ""
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        if not cur and (not line.strip() or line.lstrip().startswith("#")): continue
        cur += line.rstrip("\\").strip() + " " if line.endswith("\\") else line.strip()
        if not line.endswith("\\"):
            word, _, rest = cur.partition(" "); out.append((word.upper(), rest.strip())); cur = ""
    return out


@pytest.mark.parametrize("dockerfile", sorted(IMAGES.glob("*/Dockerfile")), ids=lambda p: p.parent.name)
def test_dockerfiles_cannot_leave_unreadable_paths(dockerfile):
    """docker-rt's kaniko runs every RUN under umask 077 (2026-10-30) and a checkout made with umask 077 COPYs 600 files: no
    instruction may leave a path the player (any uid) cannot read. Each RUN sets umask 022 first and ends with ga-readable (before
    the staging folder goes); each COPY either sets --chmod or stages into a folder that RUN removes."""
    staged = {"/tmp/ga-layer/": "rm -rf /tmp/ga-layer", "/opt/gameanything/src": "rm -rf /opt/gameanything/src"}
    pending = set()
    ins = _instructions(dockerfile)
    assert any(w == "RUN" for w, _ in ins)
    for word, rest in ins:
        if word in ("COPY", "ADD"):
            args = rest.split(); dest = args[-1]
            if any(a.startswith("--chmod=") for a in args): continue
            assert dest in staged, f"{dockerfile}: {word} {rest} lands outside a staging folder without --chmod"
            pending.add(dest)
            if dest == "/tmp/ga-layer/": assert "lab/images/common/ga-readable" in args, f"{dockerfile}: ga-readable not staged"
        elif word == "RUN":
            assert rest.startswith("umask 022 && "), f"{dockerfile}: RUN without umask 022: {rest[:80]}"
            assert "ga-readable" in rest, f"{dockerfile}: RUN without ga-readable"
            tail = rest[rest.rindex("ga-readable"):]
            assert "bash " not in tail and "install" not in tail, f"{dockerfile}: something runs after ga-readable"
            for dest in list(pending):
                assert rest.endswith(staged[dest]), f"{dockerfile}: {dest} not removed by the RUN after it"
                pending.discard(dest)
    assert not pending, f"{dockerfile}: staged but never removed: {pending}"


@exec_bits
def test_ga_readable_fixes_a_umask_077_tree(tmp_path):
    tool = IMAGES / "common" / "ga-readable"
    assert tool.stat().st_mode & 0o111
    src = tool.read_text(encoding="utf-8")
    for p in ("/opt/gameanything", "/usr/local/lib/gameanything", "/game", "/saves", "/sandbox", "/home/player"):
        assert p in src.split("ROOTS=${GA_READABLE_ROOTS:-", 1)[1].split("}", 1)[0].split(), p
    a = tmp_path / "opt"; (a / "lib-src" / "gameanything").mkdir(parents=True); (a / "private").mkdir()
    (a / "lib-src" / "gameanything" / "watchdog.py").write_text("x"); (a / "APT_SNAPSHOT").write_text("x")
    (a / "run").write_text("#!/bin/sh\n"); (a / "private" / "key").write_text("k"); (a / "dangling").symlink_to("/nonexistent")
    sb = tmp_path / "sandbox"; sb.mkdir(); sb.chmod(0o1777)
    for f in [a / "lib-src" / "gameanything" / "watchdog.py", a / "APT_SNAPSHOT", a / "private" / "key"]: f.chmod(0o600)
    (a / "run").chmod(0o744)
    for d in [a / "lib-src" / "gameanything", a / "lib-src", a]: d.chmod(0o700)
    acc = [tmp_path / "passwd", tmp_path / "group"]                  # never the host's own /etc/passwd (the tests may run as root)
    for f in acc: f.write_text("player:x:1000:\n"); f.chmod(0o664)    # a package that adds a system group rewrites it 664
    env = {"PATH": "/usr/bin:/bin", "GA_READABLE_ROOTS": f"{a} {sb} {tmp_path / 'missing'}", "GA_READABLE_PRIVATE": str(a / "private" / "key"),
           "GA_ACCOUNT_FILES": " ".join(map(str, acc + [tmp_path / "no-such-file"]))}
    r = subprocess.run(["sh", str(tool)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert "6 entries" in r.stdout, r.stdout
    mode = lambda p: p.stat().st_mode & 0o7777
    assert mode(a) == mode(a / "lib-src") == mode(a / "lib-src" / "gameanything") == 0o755 and mode(a / "run") == 0o755
    assert mode(a / "lib-src" / "gameanything" / "watchdog.py") == mode(a / "APT_SNAPSHOT") == 0o644
    assert mode(a / "private" / "key") == 0o600 and mode(sb) == 0o1777                  # PRIVATE kept; the 1777 volume untouched
    assert all(mode(f) == 0o666 for f in acc)                                            # galab.ensure_account can add a --user uid
    assert 'GA_ACCOUNT_FILES:-/etc/passwd /etc/group' in src
    r = subprocess.run(["sh", str(tool)], capture_output=True, text=True, env=env)
    assert "0 entries" in r.stdout                                                        # nothing left to touch: no layer bloat


def test_store_tools_survive_an_unreadable_watchdog_folder():
    for t in ("ga-steam", "ga-ea"):
        src = (IMAGES / "common" / t).read_text(encoding="utf-8")
        loop = src[src.index('for _p in (HERE.parent.parent.parent'):src.index("from gameanything import watchdog")]
        assert "except OSError" in loop, t


def test_pinned_downloads_have_a_sha256():
    """Every download of the images is pinned by checksum (the apt packages by the snapshot day)."""
    for f in [IMAGES / "common" / "install-wine.sh", IMAGES / "stardew" / "install.sh", IMAGES / "valheim" / "install.sh", IMAGES / "overcooked2" / "install.sh"]:
        t = f.read_text(encoding="utf-8")
        assert "sha256sum -c" in t and __import__("re").search(r"SHA(?:256)?[=:-]+[0-9a-f]{64}", t), f
    assert "APT_SNAPSHOT=20" in (IMAGES / "base" / "Dockerfile").read_text(encoding="utf-8")


@links
def test_galab_busid_and_copy(tmp_path):
    galab = _load(IMAGES / "common" / "galab.py", "galab")
    assert galab.busid("00000000:C4:00.0") == "PCI:196:0:0" and galab.busid("87:00.0") == "PCI:135:0:0"
    with pytest.raises(ValueError): galab.busid("")
    src = tmp_path / "game"; (src / "Data").mkdir(parents=True); (src / "Data/a").write_text("x"); (src / "small.cfg").write_text("y")
    (src / "skip.log").write_text("z"); (src / ".ga-ro-test-1").write_text("")
    copied, linked = galab.copy_entries(src, tmp_path / "layer", link=("Data",), skip=lambda n: n.endswith(".log"))
    lay = tmp_path / "layer"
    assert (copied, linked) == (1, 1) and (lay / "Data").is_symlink() and (lay / "small.cfg").read_text() == "y"
    assert not (lay / "skip.log").exists() and not (lay / ".ga-ro-test-1").exists()
    assert galab.read_only(tmp_path) is False and not list(tmp_path.glob(".ga-ro-test-*"))


def test_ksp_tool(tmp_path):
    k = _load(IMAGES / "ksp" / "ga-ksp", "ga_ksp")
    g = tmp_path / "ksp"; (g / "KSP_Data/Managed").mkdir(parents=True)
    assert k.ksp_build(g) == "none"
    (g / "KSP.x86_64").write_text(""); (g / "KSP_Data/Managed/Assembly-CSharp.dll").write_text("")
    assert k.ksp_build(g) == "linux"
    (g / "KSP_x64.exe").write_text(""); assert k.ksp_build(g) == "windows"
    s = k.windowed("FULLSCREEN = True\nSCREEN_RESOLUTION_WIDTH = 2560\nOTHER = 1\n")
    assert "FULLSCREEN = False" in s and "SCREEN_RESOLUTION_WIDTH = 1280" in s and "OTHER = 1" in s and "SHOW_WHATSNEW_DIALOG = False" in s


def test_sts_tool(tmp_path):
    s = _load(IMAGES / "sts" / "ga-sts", "ga_sts")
    g = tmp_path / "sts"; g.mkdir(); assert s.sts_build(g) == "none"
    (g / "desktop-1.0.jar").write_text(""); (g / "jre/bin").mkdir(parents=True); (g / "jre/bin/java").write_text("")
    assert s.sts_build(g) == "linux"
    (g / "SlayTheSpire.exe").write_text(""); assert s.sts_build(g) == "windows"
    j = tmp_path / "m.jar"
    with zipfile.ZipFile(j, "w") as z: z.writestr("ModTheSpire.json", '{"modid": "m2wsmoke"}')
    assert s.modid(j) == "m2wsmoke" and s.modid(tmp_path / "none.jar") is None


def test_mc_tool():
    m = _load(IMAGES / "minecraft" / "ga-mc", "ga_mc")
    assert m.offline_uuid("Player") == "a01e3843-e521-3998-958a-f459800e4d11"          # what an offline server gives "Player"
    o = m.set_options("fullscreen:true\nfov:0.5\n")
    assert "fullscreen:false" in o and "fov:0.5" in o and "onboardAccessibility:false" in o
    assert "launcher_accounts.json" not in m.COPIED and "mods" not in m.COPIED


# ---------------------------------------------------------------- mcversion: the launcher's version files
def _jar(p: Path, entries=None):
    p.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(p, "w") as z:
        for n, b in (entries or {"README": "x"}).items(): z.writestr(n, b)


def _mc(root: Path):
    """A .minecraft with the game version 26.3 and its Fabric profile (the files the official launcher + Fabric installer write)."""
    base = {"id": "26.3", "type": "release", "mainClass": "net.minecraft.client.main.Main", "assetIndex": {"id": "34"},
            "javaVersion": {"component": "java-runtime-epsilon", "majorVersion": 25},
            "arguments": {"game": ["--username", "${auth_player_name}", "--gameDir", "${game_directory}",
                                   {"rules": [{"action": "allow", "features": {"has_custom_resolution": True}}], "value": ["--width", "${resolution_width}"]},
                                   {"rules": [{"action": "allow", "features": {"is_demo_user": True}}], "value": "--demo"}],
                          "jvm": [{"rules": [{"action": "allow", "os": {"name": "osx"}}], "value": ["-XstartOnFirstThread"]}, "-cp", "${classpath}"]},
            "libraries": [{"name": "org.ow2.asm:asm:9.6", "downloads": {"artifact": {"path": "org/ow2/asm/asm/9.6/asm-9.6.jar"}}},
                          {"name": "org.lwjgl:lwjgl:3.4.3:natives-linux", "rules": [{"action": "allow", "os": {"name": "linux"}}]},
                          {"name": "org.lwjgl:lwjgl:3.4.3:natives-windows", "rules": [{"action": "allow", "os": {"name": "windows"}}]}]}
    fab = {"id": "fabric-loader-0.19.5-26.3", "inheritsFrom": "26.3", "mainClass": "net.fabricmc.loader.impl.launch.knot.KnotClient",
           "arguments": {"game": [], "jvm": ["-DFabricMcEmu= net.minecraft.client.main.Main "]},
           "libraries": [{"name": "org.ow2.asm:asm:9.10.1", "url": "https://maven.fabricmc.net/"},
                         {"name": "net.fabricmc:fabric-loader:0.19.5", "url": "https://maven.fabricmc.net/"}]}
    for v in (base, fab):
        d = root / "versions" / v["id"]; d.mkdir(parents=True); (d / f"{v['id']}.json").write_text(json.dumps(v), encoding="utf-8")
    _jar(root / "versions/26.3/26.3.jar", {"net/minecraft/client/Minecraft.class": b"\xca\xfe"})
    for p in ("org/ow2/asm/asm/9.10.1/asm-9.10.1.jar", "net/fabricmc/fabric-loader/0.19.5/fabric-loader-0.19.5.jar",
              "org/ow2/asm/asm/9.6/asm-9.6.jar", "org/lwjgl/lwjgl/3.4.3/lwjgl-3.4.3-natives-linux.jar"):
        _jar(root / "libraries" / p)
    return root


def test_mcversion_merge_classpath_arguments(tmp_path):
    root = _mc(tmp_path / ".minecraft")
    (root / "versions/fabric-0.18.0-old").mkdir(); (root / "versions/fabric-0.18.0-old/fabric-0.18.0-old.json").write_text("{}")
    assert mcversion.newest_fabric(root) == "fabric-loader-0.19.5-26.3" and mcversion.newest_fabric(tmp_path / "none") is None
    v = mcversion.load(root, "fabric-loader-0.19.5-26.3")
    assert v["mainClass"].endswith("KnotClient") and v["jar_version"] == "26.3" and mcversion.java_major(v) == 25
    cp = [p.relative_to(root).as_posix() for p in mcversion.classpath(root, v, "linux")]
    assert cp == ["libraries/org/ow2/asm/asm/9.10.1/asm-9.10.1.jar", "libraries/net/fabricmc/fabric-loader/0.19.5/fabric-loader-0.19.5.jar",
                  "libraries/org/lwjgl/lwjgl/3.4.3/lwjgl-3.4.3-natives-linux.jar", "versions/26.3/26.3.jar"]        # Fabric's newer ASM wins
    assert any("natives-windows" in str(p) for p in mcversion.classpath(root, v, "windows"))
    jvm, main, game = mcversion.arguments(v, {"auth_player_name": "P", "game_directory": "/g", "classpath": "CP", "resolution_width": 1280},
                                          "linux", features={"has_custom_resolution": True})
    assert jvm == ["-cp", "CP", "-DFabricMcEmu= net.minecraft.client.main.Main "] and main.endswith("KnotClient")
    assert game == ["--username", "P", "--gameDir", "/g", "--width", "1280"]
    assert mcversion.arguments(v, {}, "mac")[0][0] == "-XstartOnFirstThread"
    assert mcversion.lib_path({"name": "a.b:c:1.0:natives-linux"}) == "a/b/c/1.0/c-1.0-natives-linux.jar"


def test_minecraft_native_build(tmp_path, monkeypatch):
    home = tmp_path / "home"; root = _mc(home / ".minecraft")
    _jar(root / "mods/fabric-api-0.162.0+26.3.jar", {"META-INF/jars/fabric-lifecycle-events-v1-2.6.jar": b"inner", "fabric.mod.json": "{}"})
    jdk = tmp_path / "jdk/bin"; jdk.mkdir(parents=True); (jdk / "java").write_text(""); (jdk / "javac").write_text("")
    monkeypatch.setattr(games, "java", lambda sys_=None: {"ok": True, "path": str(jdk / "java"), "version": 25})
    monkeypatch.setattr(games.Game, "running", lambda self: False)
    g = games.get("minecraft", sys_="linux", home=home, env={"GAMEANYTHING_DATA": str(tmp_path / "data")})
    src = tmp_path / "我的 mod"; (src / "src/main/java/m").mkdir(parents=True); (src / "src/main/java/m/A.java").write_text("package m; class A {}")
    (src / "src/main/resources/assets/m").mkdir(parents=True); (src / "src/main/resources/assets/m/lang.json").write_text("{}")
    (src / "src/main/resources/fabric.mod.json").write_text('{"schemaVersion": 1, "id": "mymod", "version": "1.2.0"}')
    calls = []
    def run(args, **kw):
        calls.append((args, kw)); out = Path(args[args.index("-d") + 1]); (out / "m").mkdir(parents=True); (out / "m/A.class").write_bytes(b"\xca\xfe")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(games.subprocess, "run", run)
    b = g.build(src)
    args, kw = calls[0]
    assert args[:3] == [str(jdk / "javac"), "--release", "25"] and kw["cwd"] == str(src)
    cp = [Path(x).as_posix() for x in args[args.index("-cp") + 1].split(os.pathsep)]      # javac runs here: ";" and "\\" on Windows
    assert cp[-1].endswith("/fabric-lifecycle-events-v1-2.6.jar") and any(x.endswith("/mods/fabric-api-0.162.0+26.3.jar") for x in cp)
    assert any(x.endswith("versions/26.3/26.3.jar") for x in cp) and any(x.endswith("/fabric-loader-0.19.5.jar") for x in cp)
    assert b["modid"] == "mymod" and Path(b["jar"]).name == "mymod-1.2.0.jar" and b["version"] == "fabric-loader-0.19.5-26.3"
    with zipfile.ZipFile(b["jar"]) as z: assert {"fabric.mod.json", "m/A.class", "assets/m/lang.json", "META-INF/MANIFEST.MF"} <= set(z.namelist())
    g.check_installable(Path(b["jar"]))
    assert g.install(Path(b["jar"]))["path"] == str(root / "mods/mymod-1.2.0.jar")
    with pytest.raises(games.NativeError, match="fabric.mod.json"): g.build(tmp_path / "empty")
    (root / "libraries/org/ow2/asm/asm/9.10.1/asm-9.10.1.jar").unlink()
    with pytest.raises(games.NativeError, match="缺 1 个文件"): g.build(src)


def test_mc_fetches_the_linux_natives_a_windows_minecraft_lacks(tmp_path):
    """A Windows or Mac launcher downloads only its own system's native jars: the sandbox fetches the Linux ones (public, sha1-checked)."""
    import hashlib, io
    m = _load(IMAGES / "minecraft" / "ga-mc", "ga_mc2")
    root = _mc(tmp_path / ".minecraft")
    nat = root / "libraries/org/lwjgl/lwjgl/3.4.3/lwjgl-3.4.3-natives-linux.jar"; nat.unlink()
    v = mcversion.load(root, "fabric-loader-0.19.5-26.3")
    for lib in v["libraries"]:
        if lib["name"].endswith("natives-linux"):
            lib["downloads"] = {"artifact": {"path": "org/lwjgl/lwjgl/3.4.3/lwjgl-3.4.3-natives-linux.jar", "url": "https://libraries.minecraft.net/x.jar",
                                             "sha1": hashlib.sha1(b"native").hexdigest()}}
    urls = []
    def opener(url, timeout=None): urls.append(url); return io.BytesIO(b"native")
    dest = tmp_path / "extra"
    assert m.fetch_missing(root, v, dest, opener) == ["org/lwjgl/lwjgl/3.4.3/lwjgl-3.4.3-natives-linux.jar"] and urls == ["https://libraries.minecraft.net/x.jar"]
    cp = mcversion.classpath(root, v, "linux", extra_roots=[dest])
    assert all(p.is_file() for p in cp) and dest / "org/lwjgl/lwjgl/3.4.3/lwjgl-3.4.3-natives-linux.jar" in cp
    assert m.fetch_missing(root, v, dest, opener) == [] and len(urls) == 1                     # once
    (dest / "org/lwjgl/lwjgl/3.4.3/lwjgl-3.4.3-natives-linux.jar").unlink()
    with pytest.raises(SystemExit, match="sha1"): m.fetch_missing(root, v, dest, lambda url, timeout=None: io.BytesIO(b"tampered"))


def test_galab_windows_in_tree():
    galab = _load(IMAGES / "common" / "galab.py", "galab2")
    t = ('     0xc00017 "Minecraft* 26.3 - Singleplayer": ("java" "com.mojang.minecraft")  1280x720+0+0  +0+0\n'
         '     0xc00012 "Minecraft - RenderPearl OpenGL Hidden Utility Window": ("java" "com.mojang.minecraft")  320x480+480+120\n'
         '     0xc0000d (has no name): ()  1x1+-10+-10  +-10+-10\n')
    m = _load(IMAGES / "minecraft" / "ga-mc", "ga_mc3")
    assert galab.windows_in_tree(t, m.Mc.window) == [str(0xc00017)] and galab.windows_in_tree(t, "^Kerbal") == []


def test_new_game_tools_read_the_build(tmp_path):
    """The tools of the six games added 2026-10-29 tell the Linux build from the others (fake folders, nothing runs)."""
    t = _load(IMAGES / "terraria" / "ga-terraria", "ga_terraria")
    g = tmp_path / "tml"; g.mkdir(); assert t.tml_build(g) == "none"
    (g / "tModLoader.dll").write_text(""); (g / "start-tModLoader.sh").write_text(""); assert t.tml_build(g) == "linux"
    for mod, exe in (("valheim", "valheim.x86_64"), ("overcooked2", "Overcooked2.x86_64")):
        m = _load(IMAGES / mod / ("ga-valheim" if mod == "valheim" else "ga-oc2"), f"ga_{mod}")
        d = tmp_path / mod; d.mkdir(); assert m.unity_build(d, exe) == "none"
        (d / exe).write_text(""); (d / f"{exe.rsplit('.', 1)[0]}_Data" / "Managed").mkdir(parents=True); assert m.unity_build(d, exe) == "linux"
        w = tmp_path / f"{mod}-win"; w.mkdir(); (w / f"{exe.rsplit('.', 1)[0]}.exe").write_text(""); assert m.unity_build(w, exe) == "windows"
        assert "BepInEx" in m.SKIPPED and "run_bepinex.sh" in m.SKIPPED          # the user's own loader never comes along
    c = _load(IMAGES / "cities" / "ga-cities", "ga_cities")
    d = tmp_path / "cs"; (d / "Cities_Data" / "Managed").mkdir(parents=True); (d / "Cities.x64").write_text("")
    assert c.cities_build(d) == "none"
    (d / "Cities_Data" / "Managed" / "ICities.dll").write_text(""); assert c.cities_build(d) == "linux"
    v = _load(IMAGES / "civ6" / "ga-civ6", "ga_civ6")
    d = tmp_path / "civ"; (d / "steamassets").mkdir(parents=True); assert v.civ6_build(d) == "none"
    (d / "Civ6").write_text(""); assert v.civ6_build(d) == "linux"
    s = _load(IMAGES / "sims4" / "ga-sims4", "ga_sims4")
    assert s.EXE.as_posix() == "Game/Bin/TS4_x64.exe" and s.PREFIX_GAME.parts[-3:] == ("Program Files", "EA Games", "The Sims 4")


def test_terraria_watches_the_game_not_the_start_script(tmp_path, monkeypatch):
    """start-tModLoader.sh (2026 Steam build) starts LaunchUtils/ScriptCaller.sh with & and returns: ga-terraria run said "the game
    exited" while tModLoader started (plain Docker test, 2026-10-30). ScriptCaller.sh ends in exec dotnet, so its pid is the game's."""
    t = _load(IMAGES / "terraria" / "ga-terraria", "ga_terraria")
    lay = tmp_path / "game"; lay.mkdir(); (lay / "start-tModLoader.sh").write_text("")
    monkeypatch.setattr(t, "LAYER", lay)
    assert t.Terraria().game_argv()[1] == str(lay / "start-tModLoader.sh")          # an older folder without LaunchUtils
    (lay / "LaunchUtils").mkdir(); (lay / "LaunchUtils" / "ScriptCaller.sh").write_text("")
    argv = t.Terraria().game_argv()
    assert argv[:2] == ["bash", str(lay / "LaunchUtils" / "ScriptCaller.sh")] and argv[2:] == ["-tmlsavedirectory", str(t.SAVES)]


def test_terraria_layer_skips_the_first_start_screens(tmp_path):
    """A fresh save folder opened on "Select language" and then the first-launch Welcome: run waited 420 s (plain Docker test, 2026-10-30)."""
    t = _load(IMAGES / "terraria" / "ga-terraria", "ga_terraria")
    game = tmp_path / "game"; game.mkdir()
    pv = "ProductVersion".encode("utf-16-le") + b"\x00\x00" + "1.4.4.9+2026.08.3.0|2026.08|stable|Stable|c9545cf".encode("utf-16-le") + b"\x00\x00"
    (game / "tModLoader.dll").write_bytes(b"MZ\x00" * 50 + pv + b"\x00" * 20)
    assert t.tml_version(game / "tModLoader.dll") == "2026.8.3.0" and t.tml_version(tmp_path / "missing.dll") is None
    saves = tmp_path / "saves"; saves.mkdir()
    assert t.seed_config(saves, game) == {"Language": "en-US", "LastLaunchedTModLoaderVersion": "2026.8.3.0"}
    assert json.loads((saves / "config.json").read_text())["Language"] == "en-US"
    (saves / "config.json").write_text('{"Language": "de-DE"}')
    assert t.seed_config(saves, game) is None and "de-DE" in (saves / "config.json").read_text()     # never over the game's own
    other = tmp_path / "s2"; other.mkdir()
    assert t.seed_config(other, tmp_path / "nogame") == {"Language": "en-US"}                         # no version: only the language


def test_sims4_run_stops_on_the_ea_sign_in_window(monkeypatch):
    """The EA App came up on its sign-in window (session expired): run waited 180 s, then "the game exited" (2026-10-30)."""
    s = _load(IMAGES / "sims4" / "ga-sims4", "ga_sims4_login")
    states = []
    def fake_run(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, stdout="log line\n" + json.dumps(states.pop(0) if len(states) > 1 else states[0]) + "\n")
    monkeypatch.setattr(s.subprocess, "run", fake_run)
    lab = s.Sims4()
    states[:] = [{"login_window": True}] * 3 + [{"signed_in": True}]          # a brief sign-in window, then signed in by itself
    assert lab.wait_signed_in(pause=0) is True
    states[:] = [{"login_window": True}]                                     # stays on it: stop, ask the user to sign in
    assert lab.wait_signed_in(pause=0) is False
    states[:] = [{"fsm": "starting"}]                                        # no window, never signed in: old behaviour, try anyway
    assert lab.wait_signed_in(polls=3, pause=0) is True


def test_sims4_run_closes_a_launcher_left_on_its_activate_window_and_tries_once_more(monkeypatch, tmp_path):
    """Hiccups #54 (2026-10-31): right after she signed in, the EA App had not loaded the library; TS4_Launcher_x64.exe stayed on its own
    「Sign in with your EA Account to activate」 window, TS4_x64.exe never came and run said "the game exited". Closing the launcher and
    running a minute later worked: run now does that once, and only when the launcher alone is left."""
    s = _load(IMAGES / "sims4" / "ga-sims4", "ga_sims4_launcher")
    procs = {"TS4_Launcher_x64.exe": [4321]}
    monkeypatch.setattr(s.galab, "pids_by_comm", lambda name, proc=None: list(procs.get(name, [])))
    killed, slept, runs = [], [], []
    monkeypatch.setattr(s.os, "kill", lambda pid, sig: (killed.append(pid), procs.pop("TS4_Launcher_x64.exe", None)))
    monkeypatch.setattr(s.time, "sleep", lambda secs: slept.append(secs))
    monkeypatch.setattr(s.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=""))
    monkeypatch.setattr(s, "game_dir", lambda: tmp_path)
    def fake_lab_run(self, a):
        runs.append(1)
        if len(runs) == 1: sys.exit(1)                                      # the first try: "the game exited"
        return 0
    monkeypatch.setattr(s.galab.Lab, "cmd_run", fake_lab_run)
    lab = s.Sims4(); lab.x_up = lambda: True; lab.wait_signed_in = lambda *a, **k: True; lab.say = lambda *a: None
    assert lab.cmd_run(None) == 0 and runs == [1, 1] and killed == [4321] and slept == [lab.library_wait]
    runs.clear(); killed.clear(); procs.clear()                              # no launcher left: the failure stands, no second try
    with pytest.raises(SystemExit): lab.cmd_run(None)
    assert runs == [1] and killed == []
    runs.clear(); procs.update({"TS4_Launcher_x64.exe": [4321], "TS4_x64.exe": [999]})   # the game itself runs: not this case
    with pytest.raises(SystemExit): lab.cmd_run(None)
    assert runs == [1] and killed == []


@exec_bits
def test_bepinex_install_sets_the_executable(tmp_path):
    galab = _load(IMAGES / "common" / "galab.py", "galab")
    v = tmp_path / "vendor"; v.mkdir()
    with zipfile.ZipFile(v / "BepInEx_linux_x64_5.4.23.5.zip", "w") as z:
        z.writestr("run_bepinex.sh", '#!/bin/sh\nexecutable_name=""\nenabled="1"\n'); z.writestr("BepInEx/core/BepInEx.dll", "")
    lay = tmp_path / "layer"; lay.mkdir()
    assert galab.bepinex_install(lay, "valheim.x86_64", vendor=v) == "5.4.23.5"
    assert 'executable_name="valheim.x86_64"' in (lay / "run_bepinex.sh").read_text() and (lay / "BepInEx" / "plugins").is_dir()
    assert (lay / "run_bepinex.sh").stat().st_mode & 0o111
    with pytest.raises(FileNotFoundError): galab.bepinex_install(lay, "x", vendor=tmp_path / "none")


def test_ga_ea_uses_the_wine_layer(tmp_path, monkeypatch):
    """In the Sims 4 image Wine, mono, gecko and DXVK come from the wine layer; only EA's installer is downloaded (into the volume)."""
    baked = tmp_path / "opt"; (baked / "wine" / "bin").mkdir(parents=True); (baked / "wine" / "bin" / "wine").write_text("")
    (baked / "dxvk" / "x64").mkdir(parents=True)
    monkeypatch.setenv("GA_EA_BAKED", str(baked)); monkeypatch.setenv("GA_EA_HOME", str(tmp_path / "ea"))
    ea = _load(IMAGES / "common" / "ga-ea", "ga_ea_baked")
    assert ea.WINE_DIR == baked / "wine" and ea.DXVK_DIR == baked / "dxvk"
    monkeypatch.setenv("GA_EA_BAKED", str(tmp_path / "nothing"))
    ea2 = _load(IMAGES / "common" / "ga-ea", "ga_ea_plain")
    assert ea2.WINE_DIR == tmp_path / "ea" / "wine"


def test_sdv_names_out_of_memory(tmp_path, monkeypatch):
    """Plain Docker --memory 700m, 2026-10-29: SMAPI was killed a few seconds after start ("exited (code 137)"); ga-sdv now reads the
    cgroup's oom_kill counter and limit and says what happened and what to do."""
    m = _load(IMAGES / "stardew" / "ga-sdv", "ga_sdv_oom")
    cg = tmp_path / "cg"; cg.mkdir()
    (cg / "memory.events").write_text("low 0\nhigh 0\nmax 884\noom 1\noom_kill 2\noom_group_kill 0\n")
    (cg / "memory.max").write_text("734003200\n")
    real = m.Path
    monkeypatch.setattr(m, "Path", lambda p, *a: real(str(p).replace("/sys/fs/cgroup", str(cg)), *a))
    assert m.oom_kills() == (2, 734003200)
    (cg / "memory.max").write_text("max\n"); (cg / "memory.events").unlink()
    assert m.oom_kills() == (0, None)


@links
def test_mc_layer_takes_fabric_api_from_the_game_folder_when_the_worlds_folder_has_none(tmp_path, monkeypatch, capsys):
    """Plain Docker test, 2026-10-29: game files at /game (with mods/fabric-api), a world at /saves without mods. The layer took mods
    only from /saves, so Fabric API was missing and the smoke mod failed to compile ("package net.fabricmc.fabric.api... does not
    exist"). It now falls back to /game/mods, and says so plainly when neither has it."""
    m = _load(IMAGES / "minecraft" / "ga-mc", "ga_mc_layer")
    game = _mc(tmp_path / "game"); _jar(game / "mods/fabric-api-0.162.0+26.3.jar")
    saves = tmp_path / "saves"; (saves / "saves/New World").mkdir(parents=True); (saves / "saves/New World/level.dat").write_bytes(b"x")
    layer = tmp_path / "layer"
    for k, v in {"GAME": game, "LAYER": layer, "SAVES_IN": saves}.items(): monkeypatch.setattr(m, k, v)
    monkeypatch.setattr(m, "fetch_missing", lambda root, v: [])
    monkeypatch.setattr(m, "find_java", lambda root, v: "/usr/bin/java")
    lab = m.Mc(); lab.args_version = None
    r = lab.make_layer()
    assert r["worlds"] == ["New World"] and r["mods"] == ["fabric-api-0.162.0+26.3.jar"]
    import shutil
    shutil.rmtree(layer); (game / "mods/fabric-api-0.162.0+26.3.jar").unlink()
    assert lab.make_layer()["mods"] == [] and "no Fabric API jar" in capsys.readouterr().out


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc; and ga-sdv's pid check is os.kill(pid, 0): on Windows signal 0 "
                    "is CTRL_C_EVENT, a Ctrl+C to the whole console (it stopped pytest). The tools run only in the Linux sandbox")
def test_pid_files_from_before_a_container_restart_are_stale(tmp_path, monkeypatch):
    """Plain Docker, 2026-10-29: `docker stop` + `docker start` of a sandbox: the pid files live on the volume (/sandbox/run), the old
    Xvfb pid now belonged to another process, so Xvfb counted as running and the screen never came up ("no X display :99")."""
    import os, time
    for path, name in ((IMAGES / "stardew" / "ga-sdv", "ga_sdv_pid"), (IMAGES / "common" / "galab.py", "galab_pid")):
        m = _load(path, name)
        monkeypatch.setattr(m, "RUN", tmp_path)
        (tmp_path / "xvfb.pid").write_text(str(os.getpid()))                  # a live process
        pa = m.pid_alive if hasattr(m, "pid_alive") else m.Lab.pid_alive
        monkeypatch.setattr(m, "container_started", lambda: 0)
        assert pa("xvfb") == os.getpid()
        monkeypatch.setattr(m, "container_started", lambda: time.time() + 60)   # the container started after the file was written
        assert pa("xvfb") is None
    assert _load(IMAGES / "common" / "galab.py", "galab_cs").container_started() > 0      # real /proc here


def test_cities_sees_the_menu_of_the_2026_build():
    """The Linux build of 2026 logs no "MainMenu": ga-cities waited 420 s with the game at its menu (plain Docker test, 2026-10-30)."""
    c = _load(IMAGES / "cities" / "ga-cities", "ga_cities").Cities()
    log = ("Title: Terms-of-use-2019-04-05\nSaving /home/player/.local/share/Colossal Order/Cities_Skylines/userGameState.cgs  "
           "[Settings - Internal]\n")
    assert c.ready(log) and not c.ready("Title: Terms-of-use-2019-04-05\n")
    assert not c.ready("Loading /home/player/.local/share/Colossal Order/Cities_Skylines/userGameState.cgs  [Settings - Internal]\n")
    assert c.ready("[M2W-smoke] waiting: menu True, loading False\n") and c.ready("Loading level MainMenu\n")


@links
def test_galab_finds_stray_game_processes(tmp_path):
    """`stop` also ends a game process outside the started group, found by its executable in the layer (Cities, 2026-10-30)."""
    galab = _load(IMAGES / "common" / "galab.py", "galab")
    lay = tmp_path / "game"; lay.mkdir(); (lay / "Cities.x64").write_text("")
    proc = tmp_path / "proc"
    for pid, exe in ((101, lay / "Cities.x64"), (102, Path("/usr/bin/steam")), (103, tmp_path / "game2" / "x")):
        (proc / str(pid)).mkdir(parents=True); (proc / str(pid) / "exe").symlink_to(exe)
    (proc / "self").mkdir(); (proc / "104").mkdir()          # not a pid / no exe link (a kernel thread)
    assert galab.stray_game_pids(lay, proc) == [101]


def test_galab_adds_the_account_of_another_uid(tmp_path):
    """--user 1004 on a pulled image (uid 1000 inside): no passwd line, Civ VI segfaulted (2026-10-30). galab adds one, once."""
    galab = _load(IMAGES / "common" / "galab.py", "galab")
    pw = tmp_path / "passwd"; pw.write_text("root:x:0:0:root:/root:/bin/bash\nplayer:x:1000:1000::/home/player:/bin/bash\n")
    gr = tmp_path / "group"; gr.write_text("root:x:0:\nplayer:x:1000:\n")
    assert galab.ensure_account(pw, gr, uid=1000, gid=1000, home="/home/player") is False
    assert galab.ensure_account(pw, gr, uid=1004, gid=1004, home="/sandbox/home") is True
    assert "player1004:x:1004:1004::/sandbox/home:/bin/bash" in pw.read_text() and "player1004:x:1004:" in gr.read_text()
    assert galab.ensure_account(pw, gr, uid=1004, gid=1004, home="/sandbox/home") is False      # once
    ro = tmp_path / "ro"; ro.write_text(pw.read_text()); ro.chmod(0o444)
    if os.access(ro, os.W_OK): return                                                         # running as root: no read-only file
    assert galab.ensure_account(ro, gr, uid=1005, gid=1004) is False
    assert "chmod 666 /etc/passwd /etc/group" in (IMAGES / "common" / "install-system.sh").read_text()


def test_civ6_screen_holds_the_2k_agreement(monkeypatch):
    """On a 1280x720 screen Civ VI's first-start 2K agreement had its Agree button outside the window (2026-10-30)."""
    monkeypatch.delenv("SCREEN", raising=False)
    src = (IMAGES / "civ6" / "ga-civ6").read_text(encoding="utf-8")
    assert src.index('os.environ.setdefault("SCREEN", "1600x900x24")') < src.index("import galab")    # before galab reads it
    _load(IMAGES / "civ6" / "ga-civ6", "ga_civ6")
    assert os.environ["SCREEN"] == "1600x900x24"
    # in the image the base's ENV SCREEN=1280x720x24 wins over that default: the civ6 image sets its own (20261030c still ran 1280x720)
    assert re.search(r"^ENV .*\bSCREEN=1600x900x24\b", (IMAGES / "civ6" / "Dockerfile").read_text(encoding="utf-8"), re.M)


def test_galab_follows_a_game_that_restarts_itself(tmp_path):
    """The Sims 4: `wine TS4_x64.exe` exits (170) and the EA App starts TS4_x64.exe again; run said "the game exited" (2026-10-30)."""
    galab = _load(IMAGES / "common" / "galab.py", "galab")
    proc = tmp_path / "proc"
    for pid, comm in ((201, "wineserver"), (305, "TS4_x64.exe"), (306, "Steam")):
        (proc / str(pid)).mkdir(parents=True); (proc / str(pid) / "comm").write_text(comm + "\n")
    (proc / "self").mkdir()
    assert galab.pids_by_comm("TS4_x64.exe", proc) == [305] and galab.pids_by_comm("nothing", proc) == []
    s4 = _load(IMAGES / "sims4" / "ga-sims4", "ga_sims4").Sims4
    assert s4.relaunch_name == "TS4_x64.exe"
    tree = '     0x1c00007 "The Sims\u2122 4": ("TS4_x64.exe" "TS4_x64.exe")  1024x576+0+0  +0+0\n     0x1a00003 "EA": ()  819x461+102+57\n'
    assert galab.windows_in_tree(tree, s4.window) == [str(0x1c00007)]            # the real title has a ™ (it waited 420 s)


def test_sandbox_hiccups_live_under_docs():
    # the plain-Docker tester's log moved from the repository root (cleaned 2026-10-29) to docs/; nothing points at the old place
    assert (ROOT / "docs/sandbox-hiccups.md").is_file() and not (ROOT / "HICCUPS.md").exists()
    for rel in ("docs/sandbox-images.md", "docs/cross-platform.md", "skills/gameanything/references/setups/linux-sandbox.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "sandbox-hiccups.md" in text and "HICCUPS.md" not in text, rel


def test_xorg_output_fits_the_screen():
    """Valheim E2E 2026-10-30: on the GPU the output's preferred mode was 1024x576 on a 1280x720 screen and the pointer never reached
    the lower part (the builder could not click 「新建角色」); 1600x900 (Civ VI) is not in the driver's list: added from gtf."""
    galab = _load(IMAGES / "common" / "galab.py", "galab_fit")
    xr = ("Screen 0: minimum 8 x 8, current 1280 x 720, maximum 2560 x 1600\nDVI-D-0 connected primary 1024x576+0+0 (normal) 700mm x 400mm\n"
          "   1024x576      59.96*+  59.95\n   1280x720      60.00    59.99\n   960x720       85.00\n")
    calls = []
    def run(argv):
        calls.append(argv)
        out = xr if argv == ["xrandr"] else ('  # 1600x900 @ 60.00 Hz (GTF)\n  Modeline "1600x900_60.00"  119.00  1600 1696 1864 2128  900 901 904 932  -HSync +Vsync\n'
                                              if argv[0] == "gtf" else "")
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")
    assert galab.fit_output(1280, 720, run) == "1280x720" and calls[-1] == ["xrandr", "--output", "DVI-D-0", "--mode", "1280x720"]
    calls.clear()
    assert galab.fit_output(1600, 900, run) == "1600x900_60.00"
    assert ["xrandr", "--newmode", "1600x900_60.00", "119.00", "1600", "1696", "1864", "2128", "900", "901", "904", "932", "-HSync", "+Vsync"] in calls
    assert ["xrandr", "--addmode", "DVI-D-0", "1600x900_60.00"] in calls and calls[-1][-1] == "1600x900_60.00"
    assert galab.fit_output(1280, 720, lambda a: subprocess.CompletedProcess(a, 1, stdout="", stderr="")) is None   # no xrandr answer


def test_rec_records_the_games_sound():
    """Valheim E2E 2026-10-30 (sandbox-hiccups.md #47): `ga-valheim rec` gave a video with no sound. The games played into the null sink
    `rec` (PULSE_SINK=rec), but the recorder grabbed only the screen: no pulse input at all. Now every tool's `rec start` (galab.rec_argv,
    and ga-sdv's own copy) also reads `rec.monitor` into a PCM track; the EA App (which starts TS4_x64.exe again itself) gets the socket."""
    galab = _load(IMAGES / "common" / "galab.py", "galab_rec")
    a = galab.rec_argv("/sandbox/rec/x.mkv", 15, (1280, 720))
    assert ["-f", "pulse", "-i", "rec.monitor"] == a[a.index("pulse") - 1:a.index("pulse") + 3] and "pcm_s16le" in a and a[-1] == "/sandbox/rec/x.mkv"
    assert a.index("x11grab") < a.index("pulse") < a.index("-c:v")                      # two inputs, then the codecs
    v = galab.rec_argv("/x.mkv", 15, (1280, 720), audio=False)
    assert "pulse" not in v and "-c:a" not in v and "x11grab" in v
    assert "--load=module-null-sink sink_name=rec" in galab.PULSE_ARGV and any("auth-anonymous=1" in x for x in galab.PULSE_ARGV)
    src = (IMAGES / "common" / "galab.py").read_text(encoding="utf-8")
    body = src[src.index("    def cmd_rec(self, a):"):src.index("    def cmd_log(self, a):")]
    assert "rec_argv(" in body and "XDG_RUNTIME_DIR" in body
    assert '"PULSE_SINK": "rec"' in src[src.index("    def cmd_run(self, a):"):]                   # every game, whatever its game_env
    sdv = (IMAGES / "stardew" / "ga-sdv").read_text(encoding="utf-8")
    rec = sdv[sdv.index("def rec(a):"):sdv.index("def console(a):")]
    assert '"-f", "pulse", "-i", "rec.monitor"' in rec and "pcm_s16le" in rec and "auth-anonymous=1" in sdv and '"PULSE_SINK": "rec"' in sdv
    for g, t in TOOLS:                                                                    # nobody else builds its own recorder
        if t != "ga-sdv": assert "x11grab" not in (IMAGES / g / t).read_text(encoding="utf-8"), t
    ea = (IMAGES / "common" / "ga-ea").read_text(encoding="utf-8")
    assert 'e.setdefault("PULSE_SERVER", "unix:/tmp/ga-xdg/pulse/native")' in ea and galab.PULSE_DIR.as_posix() == "/tmp/ga-xdg"


def test_valheim_names_steam_cloud_saves(tmp_path):
    """sandbox-hiccups.md #46: the builder's test character and world were Cloud saves, synced to the user's real Steam account."""
    v = _load(IMAGES / "valheim" / "ga-valheim", "ga_valheim_cloud")
    remote = tmp_path / ".steam" / "debian-installation" / "userdata" / "123" / v.APPID / "remote"
    (remote / "characters").mkdir(parents=True); (remote / "worlds").mkdir()
    old = remote / "characters" / "hers.fch"; old.write_text(""); os.utime(old, (1000, 1000))
    new = remote / "worlds" / "test.fwl"; new.write_text("")
    local = tmp_path / ".config" / "unity3d" / "IronGate" / "Valheim" / "characters_local"; local.mkdir(parents=True)
    (local / "local.fch").write_text("")
    assert v.cloud_saves(tmp_path, since=2000) == [str(new.resolve())]                  # hers (older) and local ones are not named
    assert len(v.cloud_saves(tmp_path)) == 2 and v.cloud_saves(tmp_path / "none") == []
    role = (ROOT / "skills" / "gameanything" / "roles" / "builder.md").read_text(encoding="utf-8")
    assert "Never write test saves to Steam Cloud" in role and "Move to local" in role and "no tick to untick" in role and "_backup_auto" in role and "没有上\n   Steam 云" in role


def test_base_has_cjk_fonts():
    """sandbox-hiccups.md #45: a mod's Chinese banner drew as boxes (only wqy-zenhei, a .ttc, was there)."""
    t = (IMAGES / "common" / "install-system.sh").read_text(encoding="utf-8")
    assert "fonts-noto-cjk" in t and "fonts-droid-fallback" in t and "fonts-noto-cjk-extra" not in t


def test_stardew_image_carries_content_patcher_source_pinned():
    """Content Patcher's built mod is only on Nexus (login): the image carries the source of its release tag, sha256-pinned, its NuGet
    packages restored offline, and the .NET 10 SDK its C# 14 needs; the license row and VERSIONS line name it."""
    t = (IMAGES / "stardew" / "install.sh").read_text(encoding="utf-8")
    assert "CP_VERSION=${CP_VERSION:-2.9.1}" in t
    assert "CP_SHA256=${CP_SHA256:-e54844cd296cf86b5b97f456b63cedaafcd2f0e362b630d8fb32215b95828bff}" in t
    assert "codeload.github.com/Pathoschild/StardewMods/tar.gz/refs/tags/content-patcher/${CP_VERSION}" in t
    assert 'echo "${CP_SHA256}  $CP-src.tar.gz" | sha256sum -c -' in t
    assert 'NUGET_PACKAGES="$CP-nuget"' in t and "dotnet restore ContentPatcher/ContentPatcher.csproj" in t
    assert "dotnet-sdk-10.0" in t and "Content Patcher %s (MIT)" in t and ">> /opt/gameanything/vendor/VERSIONS" in t
    assert t.index('$CP-src.tar.gz" | sha256sum -c -') < t.index("dotnet restore")      # nothing from the tarball runs before its check
    doc = (ROOT / "docs" / "sandbox-images.md").read_text(encoding="utf-8")
    row = next(l for l in doc.splitlines() if l.startswith("| Content Patcher"))
    assert "2.9.1" in row and "MIT" in row and "sha256" in row


def _cp_vendor(tmp_path, ver="2.9.1"):
    import tarfile
    vendor = tmp_path / "vendor"; (vendor / f"ContentPatcher-{ver}-nuget" / "pathoschild.stardew.modbuildconfig").mkdir(parents=True)
    src = tmp_path / "tarsrc" / f"StardewMods-content-patcher-{ver}"
    for f in ("ContentPatcher/ContentPatcher.csproj", "Common/Common.projitems", "Directory.Build.props", "Directory.Packages.props", "LICENSE",
              "LookupAnything/skip.cs"):
        (src / f).parent.mkdir(parents=True, exist_ok=True); (src / f).write_text("x")
    with tarfile.open(vendor / f"ContentPatcher-{ver}-src.tar.gz", "w:gz") as z: z.add(src, arcname=src.name)
    return vendor


def _fake_dotnet(tmp_path, ver="2.9.1", fail=False):
    """A `dotnet` that records its call and, like ModBuildConfig with EnableModZip, writes '<ModZipPath>/ContentPatcher <ver>.zip'."""
    calls = tmp_path / "dotnet-calls.jsonl"; exe = tmp_path / "fake-dotnet"
    exe.write_text(f"""#!{sys.executable}
import json, os, sys, zipfile
from pathlib import Path
open({str(calls)!r}, "a").write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd(), "nuget": os.environ.get("NUGET_PACKAGES"),
                                          "src": sorted(p.name for p in Path.cwd().iterdir())}}) + "\\n")
if {fail!r}: print("error CS0305: nope"); sys.exit(1)
zp = Path(next(a.split("=", 1)[1] for a in sys.argv if a.startswith("-p:ModZipPath="))); zp.mkdir(parents=True)
with zipfile.ZipFile(zp / "ContentPatcher {ver}.zip", "w") as z:
    z.writestr("ContentPatcher/ContentPatcher.dll", "dll")
    z.writestr("ContentPatcher/manifest.json", json.dumps({{"Name": "Content Patcher", "Version": {ver!r}, "UniqueID": "Pathoschild.ContentPatcher"}}))
""")
    exe.chmod(0o755)
    return exe, calls


def _sdv(tmp_path, monkeypatch, name):
    m = _load(IMAGES / "stardew" / "ga-sdv", name)
    sb = tmp_path / "sandbox"
    for k, v in {"SANDBOX": sb, "LAYER": sb / "game", "LOGS": sb / "logs", "RUN": sb / "run", "VENDOR": _cp_vendor(tmp_path)}.items():
        monkeypatch.setattr(m, k, v)
    (sb / "game" / "Mods").mkdir(parents=True)
    return m


@pytest.mark.skipif(on_windows, reason="the sandbox tool runs on Linux (tar --wildcards, an executable fake dotnet)")
def test_sdv_layer_builds_content_patcher_offline_once(tmp_path, monkeypatch, capsys):
    m = _sdv(tmp_path, monkeypatch, "ga_sdv_cp")
    exe, calls = _fake_dotnet(tmp_path); monkeypatch.setenv("GA_DOTNET", str(exe))
    lay = m.LAYER
    assert m.install_cp(lay)[0] == "2.9.1" and m.cp_installed(lay) == "2.9.1"
    assert (lay / "Mods/ContentPatcher/ContentPatcher.dll").is_file() and not list((lay / "Mods").glob(".ga-new-*"))
    c = [json.loads(l) for l in calls.read_text().splitlines()]
    assert len(c) == 1
    a = c[0]["argv"]
    assert a[:2] == ["build", "ContentPatcher/ContentPatcher.csproj"] and f"-p:GamePath={lay}" in a and "-p:EnableModDeploy=false" in a
    assert "-p:UseSharedCompilation=false" in a and "-nodeReuse:false" in a                   # nothing left running after the layer
    assert "global.json" in c[0]["src"] and "LookupAnything" not in c[0]["src"]           # only what Content Patcher's build reads
    cfg = Path(a[a.index("--configfile") + 1]).name
    assert cfg == "NuGet.Config" and c[0]["nuget"].startswith(str(m.SANDBOX))         # the image's folder is a source, never written
    assert not (m.SANDBOX / "tmp" / "content-patcher").exists()                         # cleaned up
    # the same version already there: no build
    ver, msg = m.install_cp(lay); assert ver == "2.9.1" and "already installed" in msg and len(calls.read_text().splitlines()) == 1
    # an existing layer gets it through `ga-sdv layer` (no --force) and records it; doctor reports it
    (lay / ".ga-layer.json").write_text(json.dumps({"smapi": "SMAPI-4.5.2-installer.zip"}))
    assert m.ensure_cp() == "2.9.1" and json.loads((lay / ".ga-layer.json").read_text())["content_patcher"] == "2.9.1"
    monkeypatch.setattr(m, "GAME", tmp_path / "nogame"); capsys.readouterr()
    m.doctor(argparse.Namespace(json=True)); d = json.loads(capsys.readouterr().out)
    assert d["content_patcher"] == "2.9.1" and d["content_patcher_vendor"] == "2.9.1"


@pytest.mark.skipif(on_windows, reason="the sandbox tool runs on Linux (tar --wildcards, an executable fake dotnet)")
def test_sdv_content_patcher_failure_is_not_fatal(tmp_path, monkeypatch):
    m = _sdv(tmp_path, monkeypatch, "ga_sdv_cp_fail")
    exe, _ = _fake_dotnet(tmp_path, fail=True); monkeypatch.setenv("GA_DOTNET", str(exe))
    (m.LAYER / "Mods/OtherMod").mkdir()
    ver, msg = m.install_cp(m.LAYER)
    assert ver is None and "dotnet build failed (exit 1)" in msg and "SMAPI C# mods work" in msg and "nexusmods.com/stardewvalley/mods/1915" in msg
    assert "CS0305" in (m.LOGS / "content-patcher-build.log").read_text() and sorted(p.name for p in (m.LAYER / "Mods").iterdir()) == ["OtherMod"]
    # a different (older) version is replaced; an image without the source says so
    (m.LAYER / "Mods/ContentPatcher").mkdir(); (m.LAYER / "Mods/ContentPatcher/ContentPatcher.dll").write_text("old")
    (m.LAYER / "Mods/ContentPatcher/manifest.json").write_text('{"Version": "2.8.0"}')
    (tmp_path / "ok").mkdir(); exe, _ = _fake_dotnet(tmp_path / "ok"); monkeypatch.setenv("GA_DOTNET", str(exe))
    assert m.install_cp(m.LAYER)[0] == "2.9.1" and m.cp_installed(m.LAYER) == "2.9.1"
    monkeypatch.setattr(m, "VENDOR", tmp_path / "empty")
    ver, msg = m.install_cp(m.LAYER); assert ver is None and "no Content Patcher source" in msg


def test_skill_points_stardew_content_at_content_patcher():
    sk = ROOT / "skills" / "gameanything"
    b = (sk / "roles" / "builder.md").read_text(encoding="utf-8")
    assert "Content Patcher content pack" in b and "Pathoschild.ContentPatcher" in b and "2.9.1" in b and "only for logic" in b
    for g in ("linux-native", "mac-native", "windows-native", "linux-sandbox", "mac-sandbox", "windows-sandbox"):
        assert "Content Patcher" in (sk / "references" / "setups" / f"{g}.md").read_text(encoding="utf-8"), g
