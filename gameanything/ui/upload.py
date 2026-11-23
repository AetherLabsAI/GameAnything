"""Chunked, resumable file upload into <project>/0_inbox (the browser's drop zone).

One file = one upload id. The page posts consecutive chunks (8 MB) with `Content-Range: bytes a-b/total`; the bytes are streamed to
0_inbox/.partial/<id>.part and moved to 0_inbox/<relative path> when complete. `GET /api/upload?id=` says how many bytes the server
already has, so an interrupted upload (reload, network) continues where it stopped. Nothing is held in memory beyond one 1 MB read,
and nothing is written outside the inbox: names are validated here (no absolute paths, no `..`, allowed extensions only).
The user's inbox files are never edited afterwards; ingest reads them like any other folder.
"""
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import yaml

from .. import layout

ALLOWED = {"jpg", "jpeg", "heic", "png", "webp", "mp4", "mov", "m4v", "pdf", "txt", "docx", "md", "epub",
           "mp3", "m4a", "wav", "ogg", "flac", "aac"}             # audio: songs and recordings the user brings (D9: only her own files)
MAX_PATH_PART = 200
READ = 1 << 20
ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
FREE_MARGIN = 512 << 20      # keep this much free on the disk after the upload


class UploadError(Exception):
    def __init__(self, msg, code=400, **extra):
        super().__init__(msg); self.code = code; self.extra = extra


def safe_rel(name: str, allowed=ALLOWED) -> str:
    """Validate a client-supplied relative path (folder uploads send `dir/sub/file.jpg`); returns it normalised."""
    if not name or "\x00" in name or "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise UploadError("文件名不合法")
    parts = name.split("/")
    for p in parts:
        if p in ("", ".", "..") or p.startswith(".") or len(p) > MAX_PATH_PART:
            raise UploadError("文件名不合法（不能含 .. 或以点开头的名字）")
    ext = parts[-1].rsplit(".", 1)[-1].lower() if "." in parts[-1] else ""
    if ext not in allowed:
        raise UploadError(f"不支持这种文件（{ext or '没有扩展名'}）：只收 " + " ".join(sorted(allowed)))
    return "/".join(parts)


class Inbox:
    def __init__(self, root: Path, max_bytes: int, dir: Path = None, allowed=ALLOWED):
        """The project's inbox, or (dir, allowed) for another drop folder, e.g. the zips of a project import."""
        self.dir = Path(dir) if dir else layout.inbox(root); self.max = max_bytes; self.part = self.dir / ".partial"; self.allowed = allowed

    def _ids(self, uid):
        if not ID_RE.match(uid or ""): raise UploadError("上传编号不合法")
        return self.part / f"{uid}.part", self.part / f"{uid}.json"

    def status(self, uid):
        part, meta = self._ids(uid)
        got = part.stat().st_size if part.exists() else 0
        m = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
        return {"ok": True, "id": uid, "received": got, "total": m.get("total"), "name": m.get("name")}

    def _final(self, rel):
        """Unused target path inside the inbox (a name clash gets ' (2)', never overwrites)."""
        base = (self.dir / rel).resolve()
        if self.dir.resolve() not in base.parents: raise UploadError("文件名不合法")
        n, p = 2, base
        while p.exists():
            p = base.with_name(f"{base.stem} ({n}){base.suffix}"); n += 1
        return p

    def put(self, uid, headers, rfile):
        """Append one chunk read from `rfile`; -> status dict (done=True once the last chunk is in)."""
        part, meta = self._ids(uid)
        m = re.match(r"^bytes (\d+)-(\d+)/(\d+)$", headers.get("Content-Range") or "")
        if not m: raise UploadError("缺少 Content-Range")
        a, b, total = map(int, m.groups())
        from urllib.parse import unquote
        rel = safe_rel(unquote(headers.get("X-File-Name") or ""), self.allowed)
        length = int(headers.get("Content-Length") or 0)
        if b < a or b >= total or length != b - a + 1: raise UploadError("Content-Range 和内容长度对不上")
        if total > self.max: raise UploadError(f"文件太大（{total / 2 ** 30:.1f} GB，上限 {self.max / 2 ** 30:.0f} GB）", 413)
        self.part.mkdir(parents=True, exist_ok=True)
        got = part.stat().st_size if part.exists() else 0
        if meta.exists():
            old = json.loads(meta.read_text(encoding="utf-8"))
            if old.get("total") != total or old.get("name") != rel: raise UploadError("这个上传编号已经用于另一个文件", 409)
        elif got: part.unlink(); got = 0
        if a != got: raise UploadError("接上的位置不对", 409, received=got)
        if shutil.disk_usage(self.dir).free < (total - got) + FREE_MARGIN: raise UploadError("磁盘空间不够", 507)
        meta.write_text(json.dumps({"name": rel, "total": total, "at": datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
        left = length
        with open(part, "ab") as f:
            while left:
                buf = rfile.read(min(READ, left))
                if not buf: break                                   # the browser dropped the connection: the next status() tells where to resume
                f.write(buf); left -= len(buf)
        got = part.stat().st_size
        if left: raise UploadError("传输中断，可以接着传", 400, received=got)
        if got < total: return {"ok": True, "id": uid, "received": got, "done": False}
        dst = self._final(rel); dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(part), dst); meta.unlink()
        return {"ok": True, "id": uid, "received": got, "done": True, "path": dst.relative_to(self.dir).as_posix()}

    def files(self):
        """What is waiting in the inbox: [{path, bytes}] (the partial uploads are not listed)."""
        if not self.dir.exists(): return []
        return [{"path": p.relative_to(self.dir).as_posix(), "bytes": p.stat().st_size}
                for p in sorted(self.dir.rglob("*")) if p.is_file() and ".partial" not in p.parts and p.name != "ingest_request.yaml"]

    def request_ingest(self, root: Path, note=""):
        """Ingest cannot add files to an existing pack without renumbering ids, so the agent does it: leave it a request."""
        fs = self.files()
        if not fs: raise UploadError("收件箱里还没有文件")
        req = {"state": "pending", "at": datetime.now().isoformat(timespec="seconds"), "note": note or "", "files": fs}
        fb = root / layout.FEEDBACK; fb.mkdir(exist_ok=True)
        (fb / "ingest_request.yaml").write_text("# 用户在“素材”页点了“整理新文件”：收件箱 0_inbox/ 里的这些文件等 agent 整理进素材（state: pending → started → done）\n"
                                                + yaml.safe_dump(req, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
        return req
