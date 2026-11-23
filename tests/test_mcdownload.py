"""Minecraft download for the sandbox (gameanything/native/mcdownload.py) and the Microsoft device-code sign-in (msauth.py), offline with fakes."""
import hashlib
import json
import os
import stat

import pytest

from gameanything.native import mcdownload, mcversion, msauth

from _portable import needs_symlinks


def sha1(b): return hashlib.sha1(b).hexdigest()


def fake_web(tamper=None):
    """A tiny Mojang + Fabric + Modrinth: url -> bytes, and a counter of requests."""
    client, lib, obj, java, fl, api = b"client-jar", b"lwjgl", b"sound", b"#!java", b"fabric-loader", b"fabric-api-jar"
    idx = json.dumps({"objects": {"a/b.ogg": {"hash": sha1(obj), "size": len(obj)}}}).encode()
    rman = json.dumps({"files": {"bin": {"type": "directory"}, "bin/java": {"type": "file", "executable": True,
                       "downloads": {"raw": {"url": "https://rt/java", "sha1": sha1(java)}}}, "lib/link": {"type": "link", "target": "../bin/java"}}}).encode()
    v = json.dumps({"id": "26.3", "mainClass": "net.minecraft.client.main.Main", "javaVersion": {"component": "java-runtime-x", "majorVersion": 25},
                    "downloads": {"client": {"url": "https://m/client.jar", "sha1": sha1(client)}},
                    "assetIndex": {"id": "30", "url": "https://m/30.json", "sha1": sha1(idx)},
                    "libraries": [{"name": "org.lwjgl:lwjgl:3.3.3", "downloads": {"artifact": {"path": "org/lwjgl/lwjgl/3.3.3/lwjgl-3.3.3.jar",
                                   "url": "https://lib/lwjgl.jar", "sha1": sha1(lib)}}},
                                  {"name": "x:win-only:1", "rules": [{"action": "allow", "os": {"name": "windows"}}],
                                   "downloads": {"artifact": {"path": "x/w.jar", "url": "https://lib/w.jar", "sha1": sha1(b"win")}}}]}).encode()
    man = json.dumps({"versions": [{"id": "26.3", "url": "https://m/26.3.json", "sha1": sha1(v)}]}).encode()
    rwin = json.dumps({"files": {"bin": {"type": "directory"}, "bin/java.exe": {"type": "file", "downloads": {"raw": {"url": "https://rt/java.exe",
                       "sha1": sha1(b"MZjava")}}}}}).encode()                  # Mojang's Windows runtimes have no links
    allr = json.dumps({"linux": {"java-runtime-x": [{"manifest": {"url": "https://rt/man.json", "sha1": sha1(rman)}, "version": {"name": "25"}}]},
                       "windows-x64": {"java-runtime-x": [{"manifest": {"url": "https://rt/win.json", "sha1": sha1(rwin)}, "version": {"name": "25"}}]}}).encode()
    fv = json.dumps({"id": "fabric-loader-0.19.5-26.3", "inheritsFrom": "26.3", "mainClass": "net.fabricmc.loader.impl.launch.knot.KnotClient",
                     "libraries": [{"name": "net.fabricmc:fabric-loader:0.19.5", "url": "https://maven.fabricmc.net/"},       # no hash: the maven's .sha1
                                   {"name": "org.ow2.asm:asm:9.10.1", "url": "https://maven.fabricmc.net/", "sha1": sha1(b"asm")}]}).encode()
    mr = json.dumps([{"version_number": "0.162.0+26.3", "files": [{"primary": True, "filename": "fabric-api-0.162.0+26.3.jar",
                      "url": "https://cdn/api.jar", "hashes": {"sha512": hashlib.sha512(api).hexdigest()}}]}]).encode()
    web = {mcdownload.MANIFEST: man, "https://m/26.3.json": v, "https://m/client.jar": client, "https://lib/lwjgl.jar": lib,
           "https://m/30.json": idx, f"{mcdownload.ASSETS}/{sha1(obj)[:2]}/{sha1(obj)}": obj, mcdownload.RUNTIMES: allr,
           "https://rt/man.json": rman, "https://rt/java": java,
           mcdownload.FABRIC_META.format(game="26.3", loader="0.19.5"): fv,
           "https://maven.fabricmc.net/net/fabricmc/fabric-loader/0.19.5/fabric-loader-0.19.5.jar": fl, "https://cdn/api.jar": api,
           "https://maven.fabricmc.net/net/fabricmc/fabric-loader/0.19.5/fabric-loader-0.19.5.jar.sha1": sha1(fl).encode(),
           "https://maven.fabricmc.net/org/ow2/asm/asm/9.10.1/asm-9.10.1.jar": b"asm",
           "https://lib/w.jar": b"win", "https://rt/win.json": rwin, "https://rt/java.exe": b"MZjava"}
    web[mcdownload.MODRINTH.format(g="%5B%2226.3%22%5D")] = mr
    if tamper: web[tamper] = b"tampered"
    calls = []

    def get(url):
        calls.append(url)
        return web[url]
    return get, calls


@needs_symlinks                    # Mojang's Linux Java runtime has links (it runs in the sandbox)
def test_download_layout_hashes_and_reuse(tmp_path):
    get, calls = fake_web()
    r = mcdownload.download(tmp_path, get=get, log=lambda m: None, workers=2)
    assert r["fabric_profile"] == "fabric-loader-0.19.5-26.3" and r["fabric_api"] == "fabric-api-0.162.0+26.3.jar"
    assert (tmp_path / "versions/26.3/26.3.jar").read_bytes() == b"client-jar"
    assert (tmp_path / "libraries/org/lwjgl/lwjgl/3.3.3/lwjgl-3.3.3.jar").is_file()
    assert not (tmp_path / "libraries/x/w.jar").exists()                       # a Windows-only library is skipped on Linux
    java = tmp_path / "runtime/java-runtime-x/linux/java-runtime-x/bin/java"
    assert java.read_bytes() == b"#!java" and java.stat().st_mode & stat.S_IXUSR and r["java"] == str(java)
    assert (tmp_path / "runtime/java-runtime-x/linux/java-runtime-x/lib/link").is_symlink()
    assert (tmp_path / "mods/fabric-api-0.162.0+26.3.jar").is_file()
    # ga-mc and native build read it like any .minecraft
    assert mcversion.newest_fabric(tmp_path) == "fabric-loader-0.19.5-26.3"
    v = mcversion.load(tmp_path, "fabric-loader-0.19.5-26.3")
    assert all(p.is_file() for p in mcversion.classpath(tmp_path, v, "linux"))
    # a second run fetches only the metadata again, no file
    calls.clear()
    r2 = mcdownload.download(tmp_path, get=get, log=lambda m: None, workers=2)
    assert r2["fetched"] == 0 and r2["kept"] == r["fetched"]
    assert not any(u in calls for u in ("https://m/client.jar", "https://lib/lwjgl.jar", "https://rt/java", "https://cdn/api.jar"))


@needs_symlinks                    # Mojang's Linux Java runtime has links (it runs in the sandbox)
@pytest.mark.parametrize("bad", ["https://maven.fabricmc.net/net/fabricmc/fabric-loader/0.19.5/fabric-loader-0.19.5.jar", "https://m/client.jar", "https://rt/java", "https://cdn/api.jar", "https://m/26.3.json"])
def test_download_refuses_a_wrong_hash(tmp_path, bad):
    get, _ = fake_web(tamper=bad)
    with pytest.raises(mcdownload.DownloadError, match="does not match"):
        mcdownload.download(tmp_path, get=get, log=lambda m: None, workers=1)


def test_download_for_windows(tmp_path, monkeypatch):
    # a native .minecraft on a Windows PC (2026-11-01): its own libraries and Mojang's windows-x64 runtime, laid out like the launcher's
    monkeypatch.setattr(mcversion, "_arch", lambda: "x86_64")
    get, _ = fake_web()
    r = mcdownload.download(tmp_path, get=get, log=lambda m: None, workers=2, os_name="windows")
    assert (tmp_path / "libraries/x/w.jar").read_bytes() == b"win"
    java = tmp_path / "runtime/java-runtime-x/windows-x64/java-runtime-x/bin/java.exe"
    assert java.read_bytes() == b"MZjava" and r["java"] == str(java)
    assert all(p.is_file() for p in mcversion.classpath(tmp_path, mcversion.load(tmp_path, r["fabric_profile"]), "windows"))
    assert mcdownload.runtime_platform("windows", "arm64") == "windows-arm64" and mcdownload.runtime_platform("linux") == "linux"


def test_os_version_range_rules():
    # 26.x's default-user-jvm: ZGC from Windows 10.0.17134, G1 before it. Both at once and the JVM refuses to start
    # ("Multiple garbage collectors selected", a real Windows 11 PC 2026-11-01)
    zgc = [{"action": "allow", "os": {"name": "osx"}}, {"action": "allow", "os": {"name": "linux"}},
           {"action": "allow", "os": {"name": "windows", "versionRange": {"min": "10.0.17134"}}}]
    g1 = [{"action": "allow", "os": {"name": "windows", "versionRange": {"max": "10.0.17134"}}}]
    for ver, z, g in (("10.0.26200", True, False), ("10.0.16299", False, True), (None, True, False)):
        assert (mcversion.allowed(zgc, "windows", os_version=ver), mcversion.allowed(g1, "windows", os_version=ver)) == (z, g), ver
    assert mcversion.allowed(zgc, "linux") and not mcversion.allowed(g1, "linux") and mcversion.allowed(zgc, "mac")
    assert mcversion.allowed([{"action": "allow", "os": {"name": "osx", "version": r"^10\.5\.\d$"}}], "mac", os_version="10.5.8")
    assert not mcversion.allowed([{"action": "allow", "os": {"name": "osx", "version": r"^10\.5\.\d$"}}], "mac", os_version="15.1")


def test_native_minecraft_cli_needs_her_sign_in(tmp_path, capsys):
    # `native minecraft`: the sandbox's account + download for her own computer; no download before the account owns the game
    from gameanything import cli
    assert cli.main(["native", "minecraft", "status", "--json"]) == 0
    s = json.loads(capsys.readouterr().out); assert s["signed_in"] is False and s["owns_java"] is False and not s["installed"]
    with pytest.raises(SystemExit, match="sign in first"): cli.main(["native", "minecraft", "download"])
    assert cli.main(["native", "minecraft", "logout"]) == 0


def test_download_unknown_version(tmp_path):
    get, _ = fake_web()
    with pytest.raises(mcdownload.DownloadError, match="not in Mojang"):
        mcdownload.download(tmp_path, version="1.0-nope", get=get, log=lambda m: None)


class FakeMs:
    """login.live.com, Xbox Live and Minecraft services; records requests."""
    def __init__(self, pending=2, owns=True, xerr=None):
        self.pending, self.owns, self.xerr, self.seen = pending, owns, xerr, []

    def __call__(self, method, url, data=None, form=False, headers=None, timeout=30):
        self.seen.append((url, data, headers))
        if url == msauth.DEVICE_URL: return 200, {"user_code": "ABCD1234", "device_code": "dev-secret", "verification_uri": "https://www.microsoft.com/link", "interval": 1, "expires_in": 900}
        if url == msauth.TOKEN_URL:
            if data["grant_type"] == "refresh_token": return 200, {"access_token": "ms-access-2", "refresh_token": "ms-refresh-2"}
            if self.pending: self.pending -= 1; return 400, {"error": "authorization_pending"}
            return 200, {"access_token": "ms-access", "refresh_token": "ms-refresh"}
        if url == msauth.XBL_URL:
            if data["Properties"]["RpsTicket"].startswith(("d=", "t=")): return 400, {}
            return 200, {"Token": "xbl", "DisplayClaims": {"xui": [{"uhs": "1234"}]}}
        if url == msauth.XSTS_URL: return (401, {"XErr": self.xerr}) if self.xerr else (200, {"Token": "xsts", "DisplayClaims": {"xui": [{"uhs": "1234"}]}})
        if url == msauth.MC_LOGIN_URL:
            assert data["identityToken"] == "XBL3.0 x=1234;xsts"
            return 200, {"access_token": "mc-access"}
        if url == msauth.ENTITLEMENTS_URL:
            return 200, {"items": [{"name": "product_minecraft"}, {"name": "game_minecraft"}] if self.owns else []}
        if url == msauth.PROFILE_URL: return (200, {"name": "Someone"}) if self.owns else (404, {})
        raise AssertionError(url)


def test_device_code_sign_in_saves_only_a_private_refresh_token(tmp_path):
    ms = FakeMs()
    dc = msauth.device_code(ms)
    assert dc["user_code"] == "ABCD1234" and dc["verification_uri"].endswith("/link")
    tok = msauth.poll(dc, ms, sleep=lambda s: None)
    r = msauth.check_and_save(tmp_path, tok, ms, now=lambda: 1000)
    assert r["owns_java"] and r["has_profile"]
    saved = tmp_path / "microsoft.json"
    assert json.loads(saved.read_text(encoding="utf-8"))["refresh_token"] == "ms-refresh"
    assert os.name == "nt" or stat.S_IMODE(saved.stat().st_mode) == 0o600            # (Windows has no mode bits; this runs in the sandbox)
    res = (tmp_path / "minecraft.json").read_text(encoding="utf-8")
    assert "access" not in res and "refresh" not in res                                # the result file has no token
    st = msauth.status(tmp_path, now=lambda: 1000 + 7200)
    assert st["signed_in"] and st["owns_java"] and st["refresh_token_age_h"] == 2.0
    assert not any("ms-" in json.dumps(v) or "mc-access" in json.dumps(v) for v in st.values())
    # the scope / client id are the launcher's
    assert ms.seen[0][1]["client_id"] == msauth.CLIENT_ID and ms.seen[0][1]["scope"] == msauth.SCOPE


def test_recheck_uses_the_saved_token_without_a_sign_in(tmp_path):
    ms = FakeMs(pending=0)
    msauth.check_and_save(tmp_path, msauth.poll(msauth.device_code(ms), ms, sleep=lambda s: None), ms)
    ms.seen.clear()
    assert msauth.recheck(tmp_path, ms)["owns_java"]
    assert msauth.DEVICE_URL not in [u for u, *_ in ms.seen]
    assert json.loads((tmp_path / "microsoft.json").read_text())["refresh_token"] == "ms-refresh-2"
    msauth.logout(tmp_path)
    assert not msauth.status(tmp_path)["signed_in"]
    with pytest.raises(msauth.AuthError, match="not signed in"): msauth.recheck(tmp_path, ms)


def test_not_owned_and_xsts_errors(tmp_path):
    ms = FakeMs(pending=0, owns=False)
    r = msauth.check_and_save(tmp_path, msauth.poll(msauth.device_code(ms), ms, sleep=lambda s: None), ms)
    assert not r["owns_java"] and not r["has_profile"]
    ms = FakeMs(pending=0, xerr=2148916238)
    with pytest.raises(msauth.AuthError, match="child account"):
        msauth.check_and_save(tmp_path, msauth.poll(msauth.device_code(ms), ms, sleep=lambda s: None), ms)


def test_poll_expires():
    t = [0]
    def req(*a, **k): return 400, {"error": "authorization_pending"}
    def sleep(s): t[0] += s
    with pytest.raises(msauth.AuthError, match="expired"):
        msauth.poll({"device_code": "d", "interval": 5, "expires_in": 20}, req, sleep=sleep, now=lambda: t[0])
