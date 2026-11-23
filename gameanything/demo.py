"""`gameanything demo export`: a read-only, clickable copy of the browser UI on one project, as a folder of static files (docs/demo.md).

The UI server runs in this process on the project (agentd never starts, the project list is a throwaway one), every GET the pages make is
saved as a file, and the pages get ui/static/demo.js, which answers their GETs from those files and refuses every write with a small
"This is a demo" toast. Nothing in the project is changed. The folder works from any static host and from any sub-path (/hlm/ ...):

    index.html  app.html  *.js  app.css  fonts/        the real pages (index.html = the conversation shell, app.html = the workspace)
    demo-data/<lang>/api/<name>[@<query>].json          what /api/<name>?<query> answered, per language (demo_key())
    build/... media/... conv/... art/...                 the pictures and videos the answers point at (videos re-encoded: H.264, <= 720p)

The export shows what is in the project, as it is: clean a COPY of the project first (names, dates, costs, paths) and read the warnings
scan() prints at the end."""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

API = ["/api/shell", "/api/thread", "/api/day", "/api/gather", "/api/board", "/api/adaptation", "/api/feature", "/api/gameplay",
       "/api/plan", "/api/devstatus", "/api/now", "/api/feedback", "/api/looks", "/api/state", "/api/play", "/api/balance",
       "/api/models", "/api/profile"]             # the last two are reduced to what a read-only visitor may see (for_demo)
STATIC_FILES = ["i18n.js", "manage.js", "onboard.js", "shell.js", "tag.js", "app.js", "app.css", "demo.js", "fonts/inter-latin-wght-normal.woff2"]
ASSET_PREFIXES = ("/build/", "/media/", "/conv/", "/art/", "/examples/", "/kind_still/", "/crop?")
MEDIA_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".mp4", ".webm", ".mov", ".mp3", ".ogg", ".wav", ".m4a"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv"}
DAY = re.compile(r"^(\d{1,2} 月 \d{1,2} 日|(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2})( · )?")   # "10 月 22 日 · " on a round
ISO_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?([+-]\d{2}:?\d{2}|Z)?)?$")


def demo_key(path: str, query: str = "") -> str:
    """/api/play + "m=m6" -> api/play@m=m6.json (the same as demoKey() in demo.js; `after`, the thread's poll cursor, is left out)."""
    ps = sorted([(k, v) for k, v in parse_qsl(query or "", keep_blank_values=True) if k != "after"], key=lambda kv: kv[0])
    s = path.lstrip("/") + ("@" + "&".join(f"{k}={v}" for k, v in ps) if ps else "")
    return re.sub(r"[^A-Za-z0-9._=@&/-]", "_", s) + ".json"


def asset_path(url: str) -> str:
    """/build/m1/play/a b.png -> build/m1/play/a b.png; a query becomes part of the file name (the same as map() in demo.js)."""
    u = urlparse(url)
    return unquote(u.path).lstrip("/") + ("@" + re.sub(r"[^A-Za-z0-9._=&-]", "_", u.query) if u.query else "")


# ---------------------------------------------------------------- what the answers become in a demo
def strip_times(x):
    """Every value that is a date / clock time becomes "" (the pages then show no time at all)."""
    if isinstance(x, dict): return {k: strip_times(v) for k, v in x.items()}
    if isinstance(x, list): return [strip_times(v) for v in x]
    if isinstance(x, str) and ISO_TIME.match(x.strip()): return ""
    return x


def for_demo(name: str, obj, rounds=None):
    """What has no meaning (or no business) in a public read-only copy: other projects, costs, backups, the agent's online state, accounts,
    the feedback study and the private preference profile."""
    if not isinstance(obj, dict): return obj
    if name == "shell":
        obj = {**obj, "projects": [{**p, "last_opened": None} for p in obj.get("projects") or [] if p.get("current")],
               "footer": {**(obj.get("footer") or {}), "image_cost_usd": None}, "backup": {"state": "off"}, "coach_seen": True}
        obj.pop("hub", None)
        rs = [{**r, "sub": DAY.sub("", r.get("sub") or "")} for r in obj.get("rounds") or [] if isinstance(r, dict)]
        if all(re.fullmatch(r"m\d+", str(r.get("m") or "")) for r in rs): rs.sort(key=lambda r: int(r["m"][1:]))   # the dated ones came first
        obj["rounds"] = rs or obj.get("rounds")
        fl = obj.get("flow")
        if isinstance(fl, dict) and isinstance(fl.get("next"), dict) and fl["next"].get("wait"):     # nobody is working on a demo
            obj["flow"] = {**fl, "next": {**fl["next"], "hint": None}}
        gi = obj.get("game_info")
        if isinstance(gi, dict) and isinstance(gi.get("games"), dict):          # only this project's game, not the whole catalogue
            g = gi["games"].get(obj.get("game_id")) or {}
            obj["game_info"] = {**gi, "games": {obj.get("game_id"): g} if g else {},
                                "texts": {k: v for k, v in (gi.get("texts") or {}).items() if k in (g.get("desc"), g.get("title"))}}
    elif name == "thread":
        obj = {**obj, "agent": {"online": False, "busy": False, "queued": None, "owner": None, "sessions": [], "run": None, "agentd": {"alive": False},
                                "calling": None, "failed": None, "phase": None}, "build": []}
        for e in obj.get("events") or []:
            for k in ("session", "source", "author", "author_name"): e.pop(k, None)
    elif name == "day" and rounds:                 # the "watch version N" todo, named like the version list (not the built-in fallback names)
        def todo(t):
            m = str(t.get("href") or "").rpartition("/")[2]
            return {**t, "text": (t.get("text") or "") if m not in rounds else f"{rounds[m][1]}{rounds[m][0]}{rounds[m][2]}"}
        obj = {**obj, "todo": [todo(t) for t in obj.get("todo") or [] if isinstance(t, dict)]}
    elif name == "now":
        obj = {"build": None, "resident": None, "paused": None, "agentd": False}
    elif name == "feedback":
        obj = {"study": False, "exists": False, "profile_on": 0}
    elif name == "models":                         # which agent and model made it, read only; nothing about the owner's accounts
        obj = {"can_edit": False, "hub": False, "agents": [], "expensive": [],
               **{r: {k: (obj.get(r) or {}).get(k) for k in ("agent", "agent_name", "model_shown")} for r in ("chat", "build")}}
    elif name == "profile":                        # the owner's private preference profile: never in a public copy
        obj = {**{k: v for k, v in obj.items() if k in ("kinds", "games")}, "owner": "", "project": "", "entries": []}
    return obj


def urls_in(x, base=None, out=None):
    """The addresses of pictures / videos an answer points at: absolute ones (/build/...), and file names a page puts under /media/ or under
    the answer's `base` (the play page) - those are candidates, kept only when the server has them."""
    out = set() if out is None else out
    if isinstance(x, dict):
        b = x.get("base") if isinstance(x.get("base"), str) else base
        for v in x.values(): urls_in(v, b, out)
    elif isinstance(x, list):
        for v in x: urls_in(v, base, out)
    elif isinstance(x, str) and 1 < len(x) < 400 and "\n" not in x:
        if x.endswith("/"): pass
        elif x.startswith(ASSET_PREFIXES): out.add(x)
        elif not x.startswith(("/", "http:", "https:", "data:")) and Path(x.split("?")[0]).suffix.lower() in MEDIA_EXT:
            out.add("?" + "/media/" + x)
            if base: out.add("?" + base.rstrip("/") + "/" + x)
    return out


# ---------------------------------------------------------------- videos
def tool(name: str, ffmpeg: str | None) -> str:
    if ffmpeg:
        p = Path(ffmpeg)
        return str(p if name == "ffmpeg" else p.with_name(p.name.replace("ffmpeg", name)))
    w = os.environ.get("GAMEANYTHING_FFMPEG")
    if w: return tool(name, w)
    found = shutil.which(name)
    if not found: raise SystemExit(f"{name} not found: install ffmpeg or pass --ffmpeg")
    return found


def parse_cover(specs) -> list:
    """"1280x840:4,773,88,66" -> (1280, 840, 4, 773, 88, 66): a box painted black on every picture / video of exactly that size."""
    out = []
    for sp in specs or []:
        m = re.fullmatch(r"(\d+)x(\d+):(\d+),(\d+),(\d+),(\d+)", sp.strip())
        if not m: raise SystemExit(f"--cover {sp!r}: expected WxH:x,y,w,h")
        out.append(tuple(int(g) for g in m.groups()))
    return out


def cover_picture(p: Path, covers) -> bool:
    if not covers or p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp") and not re.search(r"\.(png|jpe?g|webp)@", p.name, re.I): return False
    from PIL import Image, ImageDraw
    try: im = Image.open(p); im.load()
    except Exception: return False
    hits = [c for c in covers if im.size == (c[0], c[1])]
    if not hits: return False
    fmt = im.format; im = im.convert("RGB") if im.mode not in ("RGB", "RGBA") else im; d = ImageDraw.Draw(im)
    for c in hits: d.rectangle([c[2], c[3], c[2] + c[4] - 1, c[3] + c[5] - 1], fill=(0, 0, 0))
    im.save(p, format=fmt); return True


def encode(src: Path, dst: Path, ffmpeg: str | None, max_mb: float = 30, height: int = 720, covers=(), preset: str = "slow"):
    """H.264 + AAC, at most `height` lines, sized to stay under max_mb (two passes at the bitrate that fits), playable while it loads."""
    pr = json.loads(subprocess.run([tool("ffprobe", ffmpeg), "-v", "error", "-show_entries", "format=duration,bit_rate:stream=codec_type,codec_name,bit_rate,width,height", "-of", "json", str(src)],
                                   capture_output=True, text=True, encoding="utf-8", check=True).stdout)
    dur = float(pr["format"]["duration"]); audio = any(s.get("codec_type") == "audio" for s in pr.get("streams", []))
    vs = [s for s in pr.get("streams", []) if s.get("codec_type") == "video"]
    h = max([s.get("height") or 0 for s in vs] or [0]); w = max([s.get("width") or 0 for s in vs] or [0])
    au = [s for s in pr.get("streams", []) if s.get("codec_type") == "audio"]
    copy_audio = bool(au) and au[0].get("codec_name") == "aac"           # kept as it is: re-encoding some recordings' AAC hangs this ffmpeg
    a_k = (int(au[0].get("bit_rate") or 128000) // 1000 if copy_audio else 64) if audio else 0
    src_k = int(pr["format"].get("bit_rate") or 0) // 1000 or 2500                 # never bigger than the source
    v_k = int(max(150, min(2500, src_k * 0.8, max_mb * 8192 * 0.94 / dur - a_k)))
    f = [f"drawbox=x={c[2]}:y={c[3]}:w={c[4]}:h={c[5]}:color=black:t=fill" for c in covers if (c[0], c[1]) == (w, h)]
    f += [f"scale=-2:{height}"] if h > height else []
    vf = ["-vf", ",".join(f)] if f else []
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        log = str(Path(td) / "pass"); tmp = Path(td) / "out.mp4"
        base = [tool("ffmpeg", ffmpeg), "-nostdin", "-v", "error", "-y", "-i", str(src), *vf, "-c:v", "libx264", "-preset", preset, "-threads", str(min(8, os.cpu_count() or 1)), "-b:v", f"{v_k}k",
                "-pix_fmt", "yuv420p", "-passlogfile", log]
        subprocess.run([*base, "-pass", "1", "-an", "-f", "mp4", os.devnull], check=True)
        subprocess.run([*base, "-pass", "2", *((["-c:a", "copy"] if copy_audio else ["-af", "aresample=async=1", "-c:a", "aac", "-b:a", f"{a_k}k", "-ac", "2"]) if audio else ["-an"]), "-movflags", "+faststart", str(tmp)], check=True)
        shutil.move(str(tmp), str(dst))
    return dst.stat().st_size


# ---------------------------------------------------------------- the server, in this process
class _Session:
    """The UI server on the project, on a free local port, with a throwaway project list (GAMEANYTHING_HOME / _DATA) and agentd off."""
    def __init__(self, project: Path):
        self.project = project.resolve(); self.tmp = tempfile.TemporaryDirectory(prefix="ga-demo-")
        self.env = {k: os.environ.get(k) for k in ("GAMEANYTHING_HOME", "GAMEANYTHING_DATA", "GAMEANYTHING_NO_AGENTD", "M2W_NO_AGENTD")}

    def __enter__(self):
        os.environ.update(GAMEANYTHING_HOME=str(Path(self.tmp.name) / "home"), GAMEANYTHING_DATA=str(Path(self.tmp.name) / "data"),
                          GAMEANYTHING_NO_AGENTD="1", M2W_NO_AGENTD="1")
        from . import projects
        from .ui import Project, _Server, handler
        from .ui.manage import Current, Manager
        projects.touch(self.project)
        cur = Current(Project(self.project)); mgr = Manager(cur, lambda r: Project(r), 2 ** 30)
        class Quiet(_Server):
            def handle_error(self, request, client_address): pass       # the existence checks hang up after the first byte
        self.srv = Quiet(("127.0.0.1", 0), handler(cur, mgr)); threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_port}"
        return self

    def __exit__(self, *a):
        self.srv.shutdown(); self.srv.server_close()
        for k, v in self.env.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        self.tmp.cleanup()

    def get(self, path: str, lang: str = "zh", rng: str | None = None):
        h = {"X-Lang": lang, **({"Range": rng} if rng else {})}
        try:
            r = urllib.request.urlopen(urllib.request.Request(self.base + path, headers=h), timeout=120)
            return r.status, r.headers, r
        except urllib.error.HTTPError as e:
            return e.code, e.headers, None


# ---------------------------------------------------------------- the export
def export(project: Path, out: Path, langs=("zh", "en"), ffmpeg: str | None = None, max_mb: float = 30, keep_times: bool = False,
           home: str = "../", log=print, cover=(), placeholder=(), preset: str = "slow") -> dict:
    """placeholder: globs of exported paths (e.g. "media/1_ingest/*") whose pictures / videos are replaced by a neutral placeholder -
    someone's own photos, footage with a real person in it."""
    covers = parse_cover(cover); hide = list(placeholder or [])
    project = Path(project).resolve(); out = Path(out).resolve()
    if out == project or project in out.parents: raise SystemExit("--out must be outside the project folder")
    if out.exists() and any(out.iterdir()) and not (out / "demo-data").is_dir(): raise SystemExit(f"{out} is not empty and is not a demo folder")
    out.mkdir(parents=True, exist_ok=True)
    stats = {"api": 0, "files": 0, "videos": 0, "bytes": 0, "missing": []}
    before = {p for p in out.rglob("*") if p.is_file()}; keep = set()
    with _Session(project) as S:
        assets = set(); as_is = set()              # the chat shows a video note's frame by its project path as it is (relative to the page)
        for lang in langs:
            ms = []; rounds = {}
            for path in API:
                st, _, r = S.get(path, lang)
                if st != 200: continue
                obj = json.loads(r.read())
                if path == "/api/play": ms = [m if isinstance(m, str) else m.get("m") or m.get("id") for m in obj.get("milestones") or []]
                if path == "/api/shell":
                    rounds = {r["m"]: (r.get("name") or r["m"], *(("看", "的试玩录像") if lang == "zh" else ("Watch ", "'s playthrough")))
                              for r in obj.get("rounds") or [] if isinstance(r, dict) and r.get("m")}
                keep.add(save(out, lang, path, "", obj, keep_times, rounds)); stats["api"] += 1; urls_in(obj, out=assets)
                if path == "/api/thread": as_is |= {u[len("?/media/"):] for u in urls_in(obj) if u.startswith("?/media/")}
            for m in ms:
                for path in ("/api/play", "/api/balance"):
                    st, _, r = S.get(f"{path}?m={m}", lang)
                    if st != 200: continue
                    obj = json.loads(r.read()); keep.add(save(out, lang, path, f"m={m}", obj, keep_times)); stats["api"] += 1; urls_in(obj, out=assets)
        for u in sorted(assets):
            maybe = u.startswith("?"); u = u.lstrip("?")
            if any(fnmatch.fnmatchcase(asset_path(u), g) for g in hide):          # never read: a stand-in, even where the file is missing
                dst = out / asset_path(u); stand_in(dst, Path(urlparse(u).path).suffix.lower() in VIDEO_EXT, ffmpeg)
                stats["hidden"] = stats.get("hidden", 0) + 1; stats["files"] += 1; keep.add(dst); continue
            st, h, r = S.get(u, rng="bytes=0-0")
            if st not in (200, 206):
                if not maybe: stats["missing"].append(u)
                continue
            if r: r.close()
            dst = out / asset_path(u); size = _total(h)
            if Path(urlparse(u).path).suffix.lower() in VIDEO_EXT:
                side = dst.with_name("." + dst.name + ".src")
                sig = f"{size} {sorted(covers)}"
                if dst.exists() and side.exists() and side.read_text(encoding="utf-8") == sig:
                    log(f"[demo] video (kept) {u}")
                else:
                    with tempfile.TemporaryDirectory() as td:
                        raw = Path(td) / ("src" + Path(dst.name).suffix); _download(S, u, raw)
                        n = encode(raw, dst, ffmpeg, max_mb, covers=covers, preset=preset)
                        side.write_text(sig, encoding="utf-8"); log(f"[demo] video {u}: {size / 1e6:.0f} MB -> {n / 1e6:.1f} MB")
                stats["videos"] += 1; keep.add(side)
            else:
                _download(S, u, dst)
                if cover_picture(dst, covers): stats["covered"] = stats.get("covered", 0) + 1
            stats["files"] += 1; stats["bytes"] += dst.stat().st_size if dst.exists() else 0; keep.add(dst)
        for x in sorted(as_is):
            src = out / "media" / x
            if src.is_file(): d = out / x; d.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(src, d); keep.add(d)
        for name, src in (("index.html", "/"), ("app.html", "/app")):
            st, _, r = S.get(src, langs[0]); html = r.read().decode("utf-8")
            (out / name).write_text(page(html, langs, home), encoding="utf-8"); keep.add(out / name)
    static = Path(__file__).parent / "ui" / "static"
    for f in STATIC_FILES:
        d = out / f; d.parent.mkdir(parents=True, exist_ok=True)
        if f.endswith(".css"): d.write_text((static / f).read_text(encoding="utf-8").replace("url(/fonts/", "url(fonts/"), encoding="utf-8")
        else: shutil.copyfile(static / f, d)
        keep.add(d)
    for p in before - keep: p.unlink()                                  # what an earlier export wrote and this one no longer shows
    stats["warnings"] = scan(out)
    return stats


def stand_in(dst: Path, video: bool, ffmpeg: str | None):
    """A neutral grey picture (or a 3-second video of it) in place of something that must not be shown."""
    from PIL import Image, ImageDraw
    dst.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (640, 400), (236, 236, 240)); d = ImageDraw.Draw(im)
    d.rectangle([270, 150, 370, 230], outline=(170, 170, 180), width=4); d.ellipse([300, 170, 322, 192], outline=(170, 170, 180), width=4)
    d.line([276, 224, 310, 196, 334, 214, 350, 200, 366, 224], fill=(170, 170, 180), width=4)
    d.text((228, 250), "not shown in this demo", fill=(120, 120, 130))
    if not video:
        fmt = {".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP", ".gif": "GIF"}.get(Path(re.sub(r"@.*$", "", dst.name)).suffix.lower(), "PNG")
        im.save(dst, format=fmt); return
    with tempfile.TemporaryDirectory() as td:
        png = Path(td) / "p.png"; im.save(png)
        subprocess.run([tool("ffmpeg", ffmpeg), "-v", "error", "-y", "-loop", "1", "-i", str(png), "-t", "3", "-r", "10", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(dst)], check=True)


def _total(h) -> int:
    cr = h.get("Content-Range") or ""
    return int(cr.rsplit("/", 1)[1]) if "/" in cr else int(h.get("Content-Length") or 0)


def _download(S, u: str, dst: Path):
    st, _, r = S.get(u)
    if st != 200: raise RuntimeError(f"{u}: {st}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "wb") as f: shutil.copyfileobj(r, f, 1 << 20)


def save(out: Path, lang: str, path: str, query: str, obj, keep_times: bool, rounds=None):
    name = path.rsplit("/", 1)[-1]; obj = for_demo(name, obj, rounds)
    if not keep_times: obj = strip_times(obj)
    p = out / "demo-data" / lang / demo_key(path, query); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def page(html: str, langs, home: str) -> str:
    """The server's page, made to work from the demo folder: demo.js first, the page's own files by relative address."""
    cfg = json.dumps({"langs": list(langs), "app": "app.html?embed=1", "home": home})
    html = html.replace("<head>", f'<head>\n<script>window.GA_DEMO={cfg};</script>\n<script src="demo.js"></script>', 1)
    html = re.sub(r'(src|href)="/(?!/)', r'\1="', html)
    return html.replace("url(/fonts/", "url(fonts/")


# ---------------------------------------------------------------- what to look at before publishing
SCAN = [("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")), ("path", re.compile(r"(/root/|/home/|/Users/|C:\\\\|/tmp/|/mnt/|/opt/)")),
        ("money", re.compile(r"(\$\s?\d|\d\s?USD|美元|美金)")), ("date", re.compile(r"20\d\d-\d\d-\d\d|\d{1,2}:\d\d:\d\d")),
        ("key", re.compile(r"(sk-[A-Za-z0-9]{8,}|hf_[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}|api[_-]?key)", re.I)),
        ("url", re.compile(r"(127\.0\.0\.1|localhost|:\d{4,5}/)"))]


def scan(out: Path) -> list:
    """Strings in the exported answers that often should not be public (e-mail addresses, file paths, money, dates, keys, local addresses):
    printed, never changed - the project copy is where to fix them."""
    hits = []
    for p in sorted((out / "demo-data").rglob("*.json")):
        def walk(x, where):
            if isinstance(x, dict):
                for k, v in x.items(): walk(v, where + "." + str(k))
            elif isinstance(x, list):
                for i, v in enumerate(x): walk(v, f"{where}[{i}]")
            elif isinstance(x, str):
                for kind, rx in SCAN:
                    m = rx.search(x)
                    if m: hits.append({"file": str(p.relative_to(out)), "at": where, "kind": kind, "text": x[max(0, m.start() - 30): m.end() + 30]})
        walk(json.loads(p.read_text(encoding="utf-8")), "")
    return hits
