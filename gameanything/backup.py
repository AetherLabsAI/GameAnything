"""Optional automatic backup (D16), default OFF, switched on only by the user.

    <project>/config/backup.yaml          enabled, target {kind: folder, path} | {kind: hf, repo}, include_raw, raw_paths, every_minutes, consent
    <project>/config/.backup_manifest.json  what the last successful backup holds: path -> sha256 / size / mtime (and removed files, for the record)
    <project>/privacy_ledger.yaml         every run is appended under `backups:` (purpose: backup; `requests:` stays model requests only)

Incremental: only new or changed files are copied / uploaded; nothing on the target is ever deleted (files removed here are only noted in the
manifest). Folder target: <path>/<project-id>/..., each file written to a temp name and renamed. Hugging Face target: a PRIVATE dataset repo
(created private when missing, refused when it is not private), one commit per batch of changed files. The game itself (*.xnb, Content (unpacked),
decompiled sources) is never copied. The token comes from $HF_TOKEN, the system keyring (macOS Keychain or Secret Service, osdirs.py), or a 0600 file; it is never printed or put on a command line.
"""
import hashlib
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

import yaml

from . import clock
from . import layout, osdirs, projects
from .transfer import CHUNK, walk

CONF, MANIFEST, LOCK = "config/backup.yaml", "config/.backup_manifest.json", "config/.backup.lock"
DEFAULTS = {"enabled": False, "target": None, "include_raw": False, "raw_paths": [], "every_minutes": 30, "project_id": None, "consent": None}
RIDE_ALONG = {layout.LEDGER, "conversation/.agent_seen", "conversation/.agent_cursor", "conversation/.agent_read_at", "conversation/.agent_noticed", "conversation/.agent_owner.json", "conversation/.lock"}    # copied with other changes, never a reason to run alone
HF_BATCH_FILES, HF_BATCH_BYTES = 200, 2 << 30
FREE_MARGIN = 256 << 20
HEADER = ("# Automatic backup (gameanything backup ...). Default off. It is switched on only by you: in the browser (consent dialog) or `gameanything backup enable` in a terminal.\n"
          "# `consent` records who agreed, when, and to what; a file edited by hand without a matching consent is ignored.\n")


class BackupError(Exception):
    pass


def stamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- config
def load_cfg(root: Path) -> dict:
    try: raw = yaml.safe_load((Path(root) / CONF).read_text(encoding="utf-8")) or {}
    except (FileNotFoundError, yaml.YAMLError): raw = {}
    return {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}


def save_cfg(root: Path, cfg: dict):
    f = Path(root) / CONF; f.parent.mkdir(parents=True, exist_ok=True); tmp = f.with_name(".backup.yaml.tmp")
    tmp.write_text(HEADER + yaml.safe_dump({k: cfg.get(k) for k in DEFAULTS}, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
    os.replace(tmp, f)


def target_text(t) -> str:
    if not t: return ""
    return f"folder: {t['path']}" if t.get("kind") == "folder" else f"hf: {t['repo']} (dataset)"


def fingerprint(cfg: dict) -> str:
    return hashlib.sha256(json.dumps([cfg.get("target"), bool(cfg.get("include_raw")), list(cfg.get("raw_paths") or [])], sort_keys=True).encode()).hexdigest()[:16]


def consent_ok(cfg: dict) -> bool:
    c = cfg.get("consent") or {}
    return bool(cfg.get("enabled") and cfg.get("target") and c.get("by") == "user" and c.get("fingerprint") == fingerprint(cfg))


def check_target(root: Path, cfg: dict):
    t = cfg.get("target") or {}
    if t.get("kind") == "folder":
        if not t.get("path"): raise BackupError("要先选一个备份文件夹")
        if Path(t["path"]).expanduser().exists() and not Path(t["path"]).expanduser().is_dir(): raise BackupError("备份位置不是文件夹")
        dst = Path(t["path"]).expanduser().resolve() / (cfg.get("project_id") or projects.slug(Path(root).name))
        r = Path(root).resolve()
        if dst == r or r in dst.parents or dst in r.parents: raise BackupError("备份文件夹不能在项目文件夹里面，也不能包含项目文件夹")
    elif t.get("kind") == "hf":
        repo = t.get("repo") or ""
        if repo.count("/") != 1 or not all(repo.split("/")): raise BackupError("数据集名字应该是 所有者/名字")
    else:
        raise BackupError("备份目标不合法")


# ---------------------------------------------------------------- what would be copied
USER_MUSIC = ("config/music/user_originals/", "config/music/songs/")


def scan(root: Path, cfg: dict) -> dict:
    """key (path on the target, below <project-id>/) -> {abs, size, mtime_ns}; the game and caches are left out (transfer.skip)."""
    out = {}; root = Path(root)
    fs, _, _ = walk(root)
    for rel, ap, size, mt in fs: out[rel] = {"abs": ap, "size": size, "mtime_ns": mt}
    if (cfg.get("target") or {}).get("kind") == "hf":           # songs the user brought (D9) never go to someone else's server
        out = {k: v for k, v in out.items() if not k.startswith(USER_MUSIC) and not Path(k).name.startswith("user_songs")}
    if cfg.get("include_raw"):
        for r in cfg.get("raw_paths") or []:
            r = Path(r).expanduser().resolve()
            if not r.is_dir(): continue
            for rel, ap, size, mt in walk(r)[0]: out[f"_raw/{r.name}/{rel}"] = {"abs": ap, "size": size, "mtime_ns": mt}
    return out


def load_manifest(root: Path) -> dict:
    try: return json.loads((Path(root) / MANIFEST).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError): return {}


def save_manifest(root: Path, m: dict):
    f = Path(root) / MANIFEST; tmp = f.with_name(".backup_manifest.json.tmp")
    tmp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8"); os.replace(tmp, f)


def changes(root: Path, cfg: dict, cur: dict = None, man: dict = None):
    """-> (changed keys, removed keys). A different target than the manifest's counts as everything changed."""
    cur = scan(root, cfg) if cur is None else cur; man = load_manifest(root) if man is None else man
    old = man.get("files", {}) if man.get("target") == target_text(cfg.get("target")) else {}
    ch = [k for k, v in cur.items() if k not in old or old[k]["size"] != v["size"] or old[k]["mtime_ns"] != v["mtime_ns"]]
    return ch, [k for k in old if k not in cur]


def plan(root: Path, cfg: dict) -> dict:
    """What a backup with this config would copy (for the consent dialog): totals and a per-folder breakdown."""
    cur = scan(root, cfg); top = {}
    for k, v in cur.items():
        p = k.split("/"); g = "/".join(p[:2]) + "/" if p[0] == "_raw" else p[0] + "/" if len(p) > 1 else "."
        n, b = top.get(g, (0, 0)); top[g] = (n + 1, b + v["size"])
    return {"files": len(cur), "bytes": sum(v["size"] for v in cur.values()),
            "folders": [{"name": g, "files": n, "bytes": b} for g, (n, b) in sorted(top.items())]}


# ---------------------------------------------------------------- token
def token_file() -> Path:
    return projects.home() / "hf_token"


def token_source() -> str:
    """Where a token would come from: env | keyring | file | '' (none). Never returns the token."""
    if os.environ.get("HF_TOKEN"): return "env"
    if osdirs.secret_get("huggingface", "token"): return "keyring"
    return "file" if token_file().is_file() else ""


def get_token() -> str:
    t = os.environ.get("HF_TOKEN")
    if t: return t.strip()
    t = osdirs.secret_get("huggingface", "token")
    if t: return t
    f = token_file()
    if f.is_file():
        if osdirs.system() != "windows" and f.stat().st_mode & 0o077:      # Windows has no mode bits (always 0o666); the profile folder's ACL protects it
            raise BackupError(f"{f} 的权限太宽：先运行 chmod 600 {f}")
        return f.read_text(encoding="utf-8").strip()
    raise BackupError("没有找到 Hugging Face 的 token：设置环境变量 HF_TOKEN，或运行 gameanything backup token set")


def set_token(tok: str) -> str:
    """Store in the system keyring (macOS Keychain, Linux Secret Service) when there is one, else in a 0600 file; -> 'keyring' | 'file'."""
    tok = tok.strip()
    if not tok: raise BackupError("token 是空的")
    if osdirs.secret_set("huggingface", "token", tok, "GameAnything Hugging Face token"): return "keyring"
    f = token_file(); f.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as h: h.write(tok + "\n")
    os.chmod(f, 0o600); return "file"


def _scrub(msg, tok):
    return str(msg).replace(tok, "***") if tok else str(msg)


# ---------------------------------------------------------------- targets
def _sha_copy(src: Path, dst: Path):
    """Copy via a temp name + rename, hashing on the way; -> (sha256, bytes)."""
    dst.parent.mkdir(parents=True, exist_ok=True); tmp = dst.with_name(dst.name + ".m2wpart"); h = hashlib.sha256(); n = 0
    with open(src, "rb") as a, open(tmp, "wb") as b:
        while True:
            buf = a.read(CHUNK)
            if not buf: break
            h.update(buf); b.write(buf); n += len(buf)
        b.flush(); os.fsync(b.fileno())
    os.utime(tmp, ns=(src.stat().st_atime_ns, src.stat().st_mtime_ns)); os.replace(tmp, dst)
    return h.hexdigest(), n


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""): h.update(b)
    return h.hexdigest()


def _api(token):
    from huggingface_hub import HfApi
    return HfApi(token=token)


def hf_private_repo(api, repo: str):
    """The dataset repo, created private when missing; refuses a repo that is not private."""
    from huggingface_hub.errors import RepositoryNotFoundError
    try: info = api.repo_info(repo, repo_type="dataset")
    except RepositoryNotFoundError:
        api.create_repo(repo, repo_type="dataset", private=True); info = api.repo_info(repo, repo_type="dataset")
    if getattr(info, "private", None) is not True: raise BackupError(f"数据集 {repo} 不是私有的（private）：拒绝备份。先在 Hugging Face 上把它设成私有")
    return info


def _upload_hf(root, cfg, items, cur, tok, api, put):
    from huggingface_hub import CommitOperationAdd
    api = api or _api(tok); repo = cfg["target"]["repo"]; pid = cfg["project_id"]
    hf_private_repo(api, repo)
    batch, size = [], 0

    def flush():
        nonlocal batch, size
        if not batch: return
        api.create_commit(repo_id=repo, repo_type="dataset", operations=[CommitOperationAdd(path_in_repo=f"{pid}/{k}", path_or_fileobj=str(cur[k]["abs"])) for k in batch],
                          commit_message=f"gameanything backup {stamp()}: {len(batch)} file(s)")
        for k in batch: put(k, sha[k])
        batch, size = [], 0
    sha = {}
    for k in items:
        sha[k] = _sha(cur[k]["abs"]); batch.append(k); size += cur[k]["size"]
        if len(batch) >= HF_BATCH_FILES or size >= HF_BATCH_BYTES: flush()
    flush()


def _copy_folder(root, cfg, items, cur, put):
    dst = Path(cfg["target"]["path"]).expanduser().resolve() / cfg["project_id"]
    dst.mkdir(parents=True, exist_ok=True)
    need = sum(cur[k]["size"] for k in items)
    if shutil.disk_usage(dst).free < need + FREE_MARGIN: raise BackupError("备份位置的空间不够")
    for k in items:
        sha, _ = _sha_copy(cur[k]["abs"], dst / k); put(k, sha)


# ---------------------------------------------------------------- ledger
def ledger_add(root: Path, entry: dict):
    f = Path(root) / layout.LEDGER
    try: d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except FileNotFoundError: d = {}
    d.setdefault("note", "every request that sent memory content to a model API (written by gameanything perceive); backups are listed separately under `backups`")
    d.setdefault("requests", []); d.setdefault("backups", []).append(entry)
    tmp = f.with_name(f".{f.name}.tmp"); tmp.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False, width=140), encoding="utf-8"); os.replace(tmp, f)


# ---------------------------------------------------------------- run
def run(root: Path, progress=None, api=None) -> dict:
    """One incremental backup -> {files, bytes, removed, at, ok, error}. Raises BackupError when it is off, has no consent, or is already running."""
    root = Path(root).resolve(); cfg = load_cfg(root)
    if not consent_ok(cfg): raise BackupError("备份没有开启（或开启记录对不上：请在界面里或用 gameanything backup enable 重新开启）")
    (root / "config").mkdir(exist_ok=True); lk = open(root / LOCK, "a", encoding="utf-8")
    try: osdirs.lock(lk, block=False)
    except OSError: raise BackupError("备份正在运行")
    tname = target_text(cfg["target"]); tok = None
    try:
        man = load_manifest(root)
        if man.get("target") != tname: man = {"version": 1, "target": tname, "files": {}, "removed": {}}
        cur = scan(root, cfg); ch, gone = changes(root, cfg, cur, man)
        if all(k in RIDE_ALONG for k in ch) and not gone: ch = []          # e.g. only the ledger changed (by the previous run): not worth a run
        res = {"at": stamp(), "ok": True, "files": 0, "bytes": 0, "removed": len(gone), "error": None}
        done = {"n": 0, "b": 0, "t": time.time()}

        def put(k, sha):
            man["files"][k] = {"sha256": sha, "size": cur[k]["size"], "mtime_ns": cur[k]["mtime_ns"]}; man["removed"].pop(k, None)
            done["n"] += 1; done["b"] += cur[k]["size"]
            if progress: progress(done["n"], len(ch))
            if time.time() - done["t"] > 20: save_manifest(root, man); done["t"] = time.time()
        try:
            check_target(root, cfg)
            if ch:
                if cfg["target"]["kind"] == "folder": _copy_folder(root, cfg, ch, cur, put)
                else:
                    tok = get_token(); _upload_hf(root, cfg, ch, cur, tok, api, put)
            for k in gone: man["removed"][k] = stamp(); man["files"].pop(k, None)
        except BackupError as e:
            res.update(ok=False, error=str(e))
        except Exception as e:
            res.update(ok=False, error=_scrub(f"{type(e).__name__}: {e}", tok)[:300])
        res.update(files=done["n"], bytes=done["b"])
        man["last_run"] = res; save_manifest(root, man)
        if ch or gone or not res["ok"]:
            ledger_add(root, {"at": res["at"], "purpose": "backup", "target": tname, "files": res["files"], "bytes": res["bytes"],
                              "status": "ok" if res["ok"] else "error", **({"error": res["error"]} if res["error"] else {})})
        return res
    finally:
        lk.close()


def status(root: Path) -> dict:
    """For the sidebar and `gameanything backup status` (cheap: no scan)."""
    cfg = load_cfg(root); man = load_manifest(root)
    return {"enabled": consent_ok(cfg), "configured": bool(cfg.get("target")), "target": target_text(cfg.get("target")), "target_kind": (cfg.get("target") or {}).get("kind"),
            "include_raw": bool(cfg.get("include_raw")), "raw_paths": cfg.get("raw_paths") or [], "every_minutes": cfg.get("every_minutes"),
            "consent": cfg.get("consent"), "last": man.get("last_run") if man.get("target") == target_text(cfg.get("target")) else None,
            "held": len(man.get("files", {})) if man.get("target") == target_text(cfg.get("target")) else 0}


def due(root: Path) -> bool:
    cfg = load_cfg(root)
    if not consent_ok(cfg): return False
    last = (load_manifest(root).get("last_run") or {}).get("at")
    try: return not last or time.time() - clock.epoch(last) >= max(1, int(cfg["every_minutes"] or 30)) * 60
    except (ValueError, TypeError): return True


def enable(root: Path, target: dict, include_raw=False, raw_paths=(), every_minutes=30, via="ui") -> dict:
    """Switch the backup on. Call only after the person has seen what is copied and where and said yes (browser dialog / typed confirmation)."""
    root = Path(root).resolve(); cfg = load_cfg(root)
    if target.get("kind") == "folder": target = {"kind": "folder", "path": str(Path(target["path"]).expanduser().resolve())}
    elif target.get("kind") == "hf": target = {"kind": "hf", "repo": str(target.get("repo", "")).strip()}
    cfg.update(target=target, include_raw=bool(include_raw), raw_paths=[str(Path(r).expanduser().resolve()) for r in raw_paths] if include_raw else [],
               every_minutes=max(1, int(every_minutes or 30)), project_id=cfg.get("project_id") or projects.register(root)["id"])
    check_target(root, cfg)
    p = plan(root, cfg)
    cfg["consent"] = {"by": "user", "via": via, "at": stamp(), "to": target_text(target), "sends": f"{p['files']} files, {p['bytes']} bytes, as listed in the dialog",
                      "include_raw": cfg["include_raw"], "fingerprint": None}
    cfg["enabled"] = True; cfg["consent"]["fingerprint"] = fingerprint(cfg); save_cfg(root, cfg)
    return cfg


def disable(root: Path) -> dict:
    cfg = load_cfg(root); cfg["enabled"] = False; save_cfg(root, cfg); return cfg
