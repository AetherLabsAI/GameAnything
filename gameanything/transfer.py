"""Export and import of a whole project (D16): one ZIP64 file = the project folder + m2w_export.json (format, title, kind, file list with sha256 and size).

Everything is streamed in 1 MB pieces (never a whole file in memory). `export` can add original material folders under raw/. `import` checks every
sha256 before the project appears, refuses to overwrite a folder, rejects absolute paths / `..` / symlinks, and registers the project.
Never packed: caches, partial files, the machine-local backup settings, and the game itself (see `skip`).
"""
import hashlib
import json
import os
import shutil
import stat
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from . import __version__, projects

FORMAT = 1
MANIFEST = "m2w_export.json"
CHUNK = 1 << 20
SKIP_DIRS = {"__pycache__", ".tmp"}
SKIP_NAMES = {".ui.log", ".backup_manifest.json", "backup.yaml", ".backup.lock"}       # backup settings belong to a machine: an import never arrives with backup on
GAME_DIRS = {"decompiled", "sd-sources", "sd-source", "game_sources"}                   # the game itself: never leaves the machine
STORED = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".mp4", ".mov", ".m4v", ".mp3", ".ogg", ".wav", ".flac", ".zip", ".gz", ".docx", ".pdf"}


class TransferError(Exception):
    pass


def skip(parts, is_dir=False) -> bool:
    """True for a relative path (tuple of names) that is a cache, a partial file, machine-local state, or part of the game."""
    dirs, name = (parts, None) if is_dir else (parts[:-1], parts[-1])
    if any(p in SKIP_DIRS or p in GAME_DIRS or p.startswith("Content (unpacked") for p in dirs): return True
    return name is not None and (name in SKIP_NAMES or name.endswith((".part", ".m2wpart")) or name.lower().endswith(".xnb"))


def walk(root: Path, exclude=()):
    """-> (files [(rel, abs, size, mtime_ns)], empty dirs [rel], skipped count). Symlinks are neither followed nor packed."""
    root = Path(root); files, dirs, skipped = [], [], 0
    ex = {Path(e).resolve() for e in exclude}
    for dp, dn, fn in os.walk(root):
        d = Path(dp); keep = []
        for x in dn:
            if (d / x).is_symlink() or skip((d / x).relative_to(root).parts, True): skipped += 1
            else: keep.append(x)
        dn[:] = sorted(keep)
        if not keep and not fn and d != root: dirs.append("/".join(d.relative_to(root).parts))
        for f in sorted(fn):
            p = d / f
            if p.is_symlink() or skip(p.relative_to(root).parts) or p.resolve() in ex or not p.is_file(): skipped += 1; continue
            st = p.stat(); files.append(("/".join(p.relative_to(root).parts), p, st.st_size, st.st_mtime_ns))
    return files, dirs, skipped


def _zinfo(name, mtime_ns, method):
    t = datetime.fromtimestamp(min(max(mtime_ns / 1e9, 315532800), 4102444800)).timetuple()[:6]
    zi = zipfile.ZipInfo(name, t); zi.compress_type = method; zi.external_attr = 0o644 << 16
    return zi


def export_project(project: Path, out: Path, raw=(), progress=None) -> dict:
    """Write the zip (to out.part, then rename). progress(done_bytes, total_bytes, done_files, total_files). -> {path, bytes, files, skipped}."""
    project = Path(project).resolve(); out = Path(out).resolve()
    if not project.is_dir(): raise TransferError(f"不是项目文件夹：{project}")
    if project in out.parents: raise TransferError("导出文件不能放在项目文件夹里面")
    parts = [("project", project)] + [(f"raw/{Path(r).resolve().name}", Path(r).resolve()) for r in raw]
    if len({a for a, _ in parts}) != len(parts): raise TransferError("原始素材文件夹重名")
    for _, r in parts[1:]:
        if not r.is_dir(): raise TransferError(f"找不到原始素材文件夹：{r}")
    listing = []; skipped = 0
    for prefix, base in parts:
        fs, ds, sk = walk(base, exclude=[out, out.with_name(out.name + ".part")]); skipped += sk
        listing += [(prefix, f) for f in fs] + [(prefix, (d, None, 0, 0)) for d in ds]
    total = sum(f[2] for _, f in listing); nfiles = sum(1 for _, f in listing if f[1] is not None)
    cfg = projects.config_of(project); entries = []; nb = 0
    out.parent.mkdir(parents=True, exist_ok=True); tmp = out.with_name(out.name + ".part")
    try:
        with zipfile.ZipFile(tmp, "w", allowZip64=True) as zf:
            for prefix, (rel, ap, size, mt) in listing:
                if ap is None: zf.writestr(f"{prefix}/{rel}/", b""); continue                  # an empty folder
                name = f"{prefix}/{rel}"; h = hashlib.sha256(); n = 0
                zi = _zinfo(name, mt, zipfile.ZIP_STORED if Path(rel).suffix.lower() in STORED else zipfile.ZIP_DEFLATED)
                with open(ap, "rb") as src, zf.open(zi, "w", force_zip64=True) as dst:
                    while True:
                        b = src.read(CHUNK)
                        if not b: break
                        h.update(b); dst.write(b); n += len(b); nb += len(b)
                        if progress: progress(nb, max(total, nb), len(entries), nfiles)
                entries.append({"path": name, "sha256": h.hexdigest(), "size": n, "mtime_ns": mt})
            man = {"format": FORMAT, "title": cfg.get("title") or project.name, "kind": cfg.get("kind") or "memory", "lang": cfg.get("lang"),
                   "created": datetime.now().isoformat(timespec="seconds"), "tool_version": __version__, "source_name": project.name,
                   "raw": [a for a, _ in parts[1:]], "files": entries}
            zf.writestr(MANIFEST, json.dumps(man, ensure_ascii=False, indent=1).encode())
        os.replace(tmp, out)
    except BaseException:
        tmp.unlink(missing_ok=True); raise
    if progress: progress(nb, nb, len(entries), nfiles)
    return {"path": str(out), "bytes": out.stat().st_size, "files": len(entries), "skipped": skipped}


def _safe(name: str) -> PurePosixPath:
    if not name or "\x00" in name or "\\" in name or name.startswith("/") or ":" in name.split("/")[0]:
        raise TransferError(f"文件里有不安全的路径：{name!r}")
    p = PurePosixPath(name)
    if any(x in ("..", ".", "") for x in name.split("/")): raise TransferError(f"文件里有不安全的路径：{name!r}")
    return p


def read_manifest(zpath: Path) -> dict:
    try:
        with zipfile.ZipFile(zpath) as zf: man = json.loads(zf.read(MANIFEST))
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as e:
        raise TransferError(f"不是 GameAnything 导出的文件：{e}")
    if not isinstance(man, dict) or not isinstance(man.get("files"), list): raise TransferError("不是 GameAnything 导出的文件：清单不对")
    if man.get("format", 0) > FORMAT: raise TransferError(f"导出文件的格式版本（{man['format']}）比这个工具新：请先升级 GameAnything")
    return man


def import_project(zpath: Path, into: Path = None, name: str = None, unique: bool = False, progress=None) -> dict:
    """Verify and extract. The project folder is `<into>/<name>` (default: <data>/projects, the exported folder's name); an existing folder is refused
    (unique=True picks `<name>-2` instead). Raw material goes next to it in `<name>_raw/`. -> {path, raw, id, title, kind, files, bytes}."""
    zpath = Path(zpath); man = read_manifest(zpath)
    into = Path(into).expanduser() if into else projects.data_dir() / "projects"
    base = name or man.get("source_name") or projects.slug(man.get("title"))
    if "/" in base or "\\" in base or base in (".", "..") or base.startswith("."): raise TransferError("名字不合法")
    dest = into / base
    if dest.exists():
        if not unique: raise TransferError(f"{dest} 已经存在，不会覆盖：换个名字，例如 --name {base}-2")
        i = 2
        while (into / f"{base}-{i}").exists(): i += 1
        base = f"{base}-{i}"; dest = into / base
    rawdest = into / f"{base}_raw"
    if rawdest.exists(): raise TransferError(f"{rawdest} 已经存在，不会覆盖")
    byname = {}
    for e in man["files"]:
        p = _safe(e["path"])
        if p.parts[0] not in ("project", "raw") or len(p.parts) < 2: raise TransferError(f"文件里有不认识的路径：{e['path']}")
        byname[e["path"]] = e
    stage = into / f".{base}.importing"
    if stage.exists(): raise TransferError(f"上一次导入没有完成：{stage}（确认没人在用后，把它挪走再试）")
    total = sum(e["size"] for e in man["files"]); nb = 0; got = set()
    stage.mkdir(parents=True)
    try:
        with zipfile.ZipFile(zpath) as zf:
            for zi in zf.infolist():
                if zi.filename == MANIFEST: continue
                p = _safe(zi.filename.rstrip("/"))
                if stat.S_ISLNK(zi.external_attr >> 16): raise TransferError(f"导出文件里有符号链接，拒绝导入：{zi.filename}")
                if p.parts[0] not in ("project", "raw"): raise TransferError(f"文件里有不认识的路径：{zi.filename}")
                tgt = stage.joinpath(*p.parts)
                if zi.is_dir(): tgt.mkdir(parents=True, exist_ok=True); continue
                e = byname.get(zi.filename)
                if e is None: raise TransferError(f"清单里没有这个文件：{zi.filename}")
                if zi.filename in got: raise TransferError(f"文件重复：{zi.filename}")
                tgt.parent.mkdir(parents=True, exist_ok=True); h = hashlib.sha256(); n = 0
                with zf.open(zi) as src, open(tgt, "wb") as dst:
                    while True:
                        b = src.read(CHUNK)
                        if not b: break
                        h.update(b); dst.write(b); n += len(b); nb += len(b)
                        if progress: progress(nb, max(total, nb), len(got), len(byname))
                if h.hexdigest() != e["sha256"] or n != e["size"]: raise TransferError(f"校验失败（内容和清单不一致）：{zi.filename}")
                if e.get("mtime_ns"): os.utime(tgt, ns=(e["mtime_ns"], e["mtime_ns"]))
                got.add(zi.filename)
        missing = set(byname) - got
        if missing: raise TransferError(f"导出文件缺少 {len(missing)} 个文件，例如 {sorted(missing)[0]}")
        (stage / "project").mkdir(exist_ok=True)
        os.replace(stage / "project", dest)
        raws = stage / "raw"
        if raws.is_dir() and any(raws.iterdir()): os.replace(raws, rawdest)
        else: rawdest = None
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)                       # only our own half-written staging folder
        raise
    shutil.rmtree(stage, ignore_errors=True)
    from . import decisions
    if decisions.strict(dest): decisions.resign(dest)        # her decisions in the backup, signed again with this server's key (the CLI's import: they do not count)
    e = projects.register(dest, man.get("title"), man.get("kind"))
    return {"path": str(dest), "raw": str(rawdest) if rawdest else None, "id": e["id"], "title": e["title"], "kind": e["kind"], "files": len(got), "bytes": nb}
