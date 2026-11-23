"""Download Minecraft: Java Edition + a Fabric profile into a .minecraft folder, from the official public sources. Stdlib only.

Used by the sandbox tool `ga-mc download` (lab/images/minecraft) for a user who has no .minecraft yet, after `ga-mc account login`
checked with their Microsoft account that they own the game (msauth). The files are the ones the official launcher downloads:

    piston-meta.mojang.com      version manifest -> <version>.json (sha1 from the manifest) -> client jar, libraries, asset index (sha1)
    resources.download.minecraft.net   the asset objects (each named by its sha1)
    piston-meta.mojang.com      Mojang's Java runtime for this version (java-runtime-*, every file sha1)
    meta.fabricmc.net           the Fabric loader profile (fabric-loader-<loader>-<game>.json); its libraries from maven.fabricmc.net (sha1)
    api.modrinth.com            Fabric API (sha512 from Modrinth) into mods/

Every file is checked against its official hash; a file already there with the right hash is kept, so a second run downloads nothing.
The layout is the official launcher's (versions/, libraries/, assets/, runtime/<component>/linux/<component>/), so ga-mc and
`gameanything native build --game minecraft` use it like any .minecraft.
"""
import hashlib
import json
import os
import ssl
import subprocess
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import mcversion

VERSION, FABRIC, FABRIC_API = "26.3", "0.19.5", "0.162.0+26.3"          # what the GameAnything Minecraft lab uses
MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
RUNTIMES = "https://piston-meta.mojang.com/v1/products/java-runtime/2ec0cc96c44e5a76b9c8b7c39df7210883d12871/all.json"
ASSETS = "https://resources.download.minecraft.net"
FABRIC_META = "https://meta.fabricmc.net/v2/versions/loader/{game}/{loader}/profile/json"
MODRINTH = "https://api.modrinth.com/v2/project/fabric-api/version?game_versions={g}&loaders=%5B%22fabric%22%5D"
UA = "GameAnything/1 (ga-mc download; +https://github.com/AetherLabsAI/GameAnything)"


class DownloadError(Exception):
    pass


def _windows_fetch(url, timeout) -> bytes:
    """Windows' own curl.exe (schannel): it still verifies the certificate, and Windows fetches a root it does not have yet, which
    Python's ssl never does (a real Windows 11 PC 2026-11-01: cdn.modrinth.com failed in Python, worked in curl.exe)."""
    exe = Path(os.environ.get("SystemRoot") or "C:\\Windows") / "System32" / "curl.exe"
    r = subprocess.run([str(exe), "-fsSL", "--max-time", str(timeout), "-A", UA, url], capture_output=True, timeout=timeout + 30)
    if r.returncode != 0: raise DownloadError(f"{url}: curl.exe failed ({r.returncode}): {r.stderr.decode(errors='replace').strip()[:200]}")
    return r.stdout


def fetch(url, timeout=120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r: return r.read()
        except OSError as e:
            if os.name == "nt" and isinstance(getattr(e, "reason", e), ssl.SSLCertVerificationError): return _windows_fetch(url, timeout)
            if i == 2: raise
            time.sleep(2 * (i + 1))


def _hash(data: bytes, algo: str) -> str:
    return hashlib.new(algo, data).hexdigest()


def _file_ok(p: Path, h: str, algo="sha1") -> bool:
    if not p.is_file(): return False
    d = hashlib.new(algo)
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): d.update(b)
    return d.hexdigest() == h


class Job:
    """Downloads with hash checks and counts what was fetched / kept."""

    def __init__(self, get=fetch, workers=8, log=print):
        self.get, self.workers, self.log = get, workers, log
        self.fetched = self.kept = self.bytes = 0

    def file(self, url, dest: Path, h=None, algo="sha1", mode=None) -> bytes | None:
        """dest from url, checked against h (no h: only when dest is missing). -> the bytes when fetched, else None."""
        if (h and _file_ok(dest, h, algo)) or (not h and dest.is_file()):
            self.kept += 1
            if mode: os.chmod(dest, mode)
            return None
        data = self.get(url)
        if h and _hash(data, algo) != h: raise DownloadError(f"{url}: {algo} does not match (expected {h})")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part"); tmp.write_bytes(data)
        if mode: os.chmod(tmp, mode)
        os.replace(tmp, dest)
        self.fetched += 1; self.bytes += len(data)
        return data

    def json(self, url, dest: Path, h=None, algo="sha1") -> dict:
        self.file(url, dest, h, algo)
        return json.loads(dest.read_text(encoding="utf-8"))

    def many(self, items, what):
        """items: (url, dest, sha1[, mode]) in parallel."""
        items = list(items); t = time.time()
        with ThreadPoolExecutor(self.workers) as ex: list(ex.map(lambda it: self.file(it[0], it[1], it[2], "sha1", *(it[3:] or [None])), items))
        self.log(f"{what}: {len(items)} files ({time.time() - t:.0f} s)")


def runtime_files(manifest: dict, base: Path):
    """Mojang's Java runtime manifest -> ((url, dest, sha1, mode) files, (dest, target) links, dirs)."""
    files, links, dirs = [], [], []
    for rel, f in (manifest.get("files") or {}).items():
        p = base / rel
        if f["type"] == "directory": dirs.append(p)
        elif f["type"] == "link": links.append((p, f["target"]))
        elif f["type"] == "file":
            raw = f["downloads"]["raw"]
            files.append((raw["url"], p, raw["sha1"], 0o755 if f.get("executable") else 0o644))
    return files, links, dirs


def runtime_platform(os_name: str, arch: str = None) -> str:
    """The key of Mojang's java-runtime all.json (and the official launcher's runtime/<component>/<key>/ folder) for a system."""
    arm = (arch or mcversion._arch()) in ("arm64", "aarch64")
    if os_name == "windows": return "windows-arm64" if arm else "windows-x64"
    if os_name in ("mac", "osx"): return "mac-os-arm64" if arm else "mac-os"
    return "linux"


def download(root, version=VERSION, fabric=FABRIC, fabric_api=FABRIC_API, get=fetch, log=print, workers=8, os_name="linux") -> dict:
    """The game + Fabric into root (a .minecraft), with the libraries, natives and Java runtime of os_name (linux: the sandbox;
    windows: a native .minecraft, a real Windows 11 PC 2026-11-01). -> {version, fabric_profile, fetched, kept, bytes, seconds, java}."""
    root = Path(root); root.mkdir(parents=True, exist_ok=True); t0 = time.time()
    plat = runtime_platform(os_name)
    job = Job(get, workers, log)
    man = json.loads(get(MANIFEST))
    entry = next((v for v in man["versions"] if v["id"] == version), None)
    if not entry: raise DownloadError(f"Minecraft {version} is not in Mojang's version manifest")
    vdir = root / "versions" / version
    v = job.json(entry["url"], vdir / f"{version}.json", entry.get("sha1"))
    c = v["downloads"]["client"]
    job.file(c["url"], vdir / f"{version}.jar", c["sha1"])
    log(f"client {version}: ok")
    libs = []
    for lib in mcversion.libraries(v, os_name):
        url, sha1 = mcversion.lib_url(lib)
        if url: libs.append((url, root / "libraries" / mcversion.lib_path(lib), sha1))
    job.many(libs, "game libraries")
    ai = v["assetIndex"]
    idx = job.json(ai["url"], root / "assets" / "indexes" / f"{ai['id']}.json", ai["sha1"])
    objs = {o["hash"] for o in idx["objects"].values()}
    job.many(((f"{ASSETS}/{h[:2]}/{h}", root / "assets" / "objects" / h[:2] / h, h) for h in sorted(objs)), "assets")
    comp = (v.get("javaVersion") or {}).get("component")
    java = None
    if comp:
        allr = json.loads(get(RUNTIMES))
        cands = (allr.get(plat) or {}).get(comp) or []
        if not cands: raise DownloadError(f"Mojang has no {plat} Java runtime {comp}")
        m = cands[0]["manifest"]
        rman = job.json(m["url"], root / "runtime" / f"{comp}.manifest.json", m["sha1"])
        base = root / "runtime" / comp / plat / comp
        files, links, dirs = runtime_files(rman, base)
        for d in dirs: d.mkdir(parents=True, exist_ok=True)
        job.many(files, f"Java runtime {comp}")
        for p, target in links:
            if not p.is_symlink(): p.parent.mkdir(parents=True, exist_ok=True); p.unlink(missing_ok=True); p.symlink_to(target)
        (root / "runtime" / comp / plat / f"{comp}.version").write_text(json.dumps(cands[0].get("version") or {}), encoding="utf-8")
        home = base / "jre.bundle" / "Contents" / "Home" if (base / "jre.bundle").is_dir() else base     # macOS runtimes are a bundle
        java = str(home / "bin" / ("java.exe" if os_name == "windows" else "java"))
    fid = f"fabric-loader-{fabric}-{version}"
    fv = json.loads(get(FABRIC_META.format(game=urllib.parse.quote(version), loader=urllib.parse.quote(fabric))))
    if fv.get("id") != fid or fv.get("inheritsFrom") != version: raise DownloadError(f"Fabric meta answered {fv.get('id')} for {fid}")
    fdir = root / "versions" / fid; fdir.mkdir(parents=True, exist_ok=True)
    (fdir / f"{fid}.json").write_text(json.dumps(fv, indent=1), encoding="utf-8")
    flibs = []
    for lib in fv.get("libraries") or []:
        url, sha1 = mcversion.lib_url(lib)
        if not sha1:                  # the loader and intermediary entries carry no hash: the maven's own <jar>.sha1 next to it
            try: sha1 = get(url + ".sha1").decode().split()[0].lower()
            except (OSError, IndexError, KeyError) as e: raise DownloadError(f"Fabric library {lib.get('name')}: no sha1 ({e})")
            if len(sha1) != 40: raise DownloadError(f"Fabric library {lib.get('name')}: bad sha1 file")
        flibs.append((url, root / "libraries" / mcversion.lib_path(lib), sha1))
    job.many(flibs, f"Fabric {fabric} libraries")
    api = None
    if fabric_api:
        vs = json.loads(get(MODRINTH.format(g=urllib.parse.quote(json.dumps([version])))))
        hit = next((x for x in vs if x.get("version_number") == fabric_api), None)
        if not hit: raise DownloadError(f"Fabric API {fabric_api} is not on Modrinth for {version}")
        f = next((x for x in hit["files"] if x.get("primary")), hit["files"][0])
        job.file(f["url"], root / "mods" / f["filename"], f["hashes"]["sha512"], "sha512")
        api = f["filename"]; log(f"Fabric API {fabric_api}: ok")
    for n in ("saves", "resourcepacks"): (root / n).mkdir(exist_ok=True)
    res = {"version": version, "fabric_profile": fid, "fabric_api": api, "java": java, "fetched": job.fetched, "kept": job.kept,
           "bytes": job.bytes, "seconds": round(time.time() - t0, 1)}
    (root / ".ga-download.json").write_text(json.dumps({**res, "at": int(time.time())}, indent=1), encoding="utf-8")
    return res
