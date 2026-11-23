"""Reference pictures of PUBLIC places from the web, only after her yes (skills/gameanything/references/landmark-references.md).

    gameanything refs fetch  --project P --place "Geisel Library" --url IMG --query "Geisel Library UCSD exterior" --consent websearch-geisel
                    [--page PAGE] [--license "CC BY-SA 4.0"] [--author A] [--side front]
    gameanything refs status --project P            the refs, their sources and the queue
    gameanything refs check  --project P            the problems `gameanything flow check` reports too (exit 1 when there are any)

The agent searches with its own web tools (Claude: WebSearch / WebFetch, Codex: web_search="live"); it never downloads a picture itself.
`gameanything refs fetch` saves one picture into 2_perceive/landmark_refs/<place>/ and records it in that folder's sources.yaml
({file, url, page, query, license, author, side, source: web, consent, fetched, sha256}). Before anything is downloaded:
  - consent: a `permission` card (decision yes) or an `options` card (picked `yes`) whose key starts with `websearch`, answered by her;
  - query hygiene: the query and the place may not contain a name the project knows (3_remember/people.yaml, board.yaml, config/vocab.txt,
    the owner's login / display name), an e-mail address or a path;
  - the URL is http(s) to a public address (every redirect too), the answer is an image (jpeg / png / gif / webp), at most MAX_BYTES.
Inside a resident / builder run (GAMEANYTHING_GEN_OFF is set) the command only QUEUES the request (conversation/.refs_queue/) and waits for agentd,
which checks it again and downloads it on the host: a Codex resident's sandbox has no network, and the checks run outside the model's
reach. Outside a run (the operator) it downloads directly, with the same checks.
"""
import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml

from . import layout
from .conversation import Thread, now

REFS_DIR = f"{layout.PERCEIVE}/landmark_refs"
CONSENT_PREFIX = "websearch"
YES_KEYS = ("yes", "search", "ok")
MAX_BYTES = 15 * 1024 * 1024
TIMEOUT = 20
WAIT_SECS = 60
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp")
# reference pictures saved before this rule existed (2026-10-26; older sources.yaml formats, her OK given in the chat) are not
# re-judged: residents must not delete refs a build still uses. Only pictures saved after it need a websearch consent card.
RULE_SINCE = 1793041200.0                                              # 2026-10-26T19:00:00Z
UA = "gameanything-refs/1 (reference pictures of a public place for a private project)"


class RefsError(ValueError):
    pass


def refs_dir(root) -> Path: return Path(root) / REFS_DIR


def queue_dir(root) -> Path: return Path(root) / "conversation" / ".refs_queue"


def slug(place: str) -> str:
    """A folder name for the place that works on Windows / macOS / Linux (letters of any script kept)."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", str(place or "").strip())
    s = re.sub(r"\s+", "-", s).strip(".- ")[:60].strip(".- ")
    if not s or s.upper() in ("CON", "PRN", "AUX", "NUL") or re.fullmatch(r"(?i)(COM|LPT)\d", s): raise RefsError("place 应该是地点的名字")
    return s


def _y(p: Path, default=None):
    try: return yaml.safe_load(Path(p).read_text(encoding="utf-8")) or default
    except (OSError, yaml.YAMLError, UnicodeDecodeError): return default


def _write_json(p: Path, d):
    p.parent.mkdir(parents=True, exist_ok=True); tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8"); os.replace(tmp, p)


def _read_json(p: Path):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError): return None


# ---------------------------------------------------------------- consent
def _yes(card: dict, answer: dict) -> bool:
    if card.get("kind") == "permission": return answer.get("decision") == "yes"
    if card.get("kind") == "options":
        return any(str(k).lower().startswith(YES_KEYS) for k in answer.get("picked") or [])
    return False


def consents(root) -> dict:
    """{card event id: {key, card, yes}} for every websearch consent card in the thread (superseded ones too: a yes stays a yes for the
    pictures fetched under it); `yes` = her LATEST answer on that card says yes."""
    out = {}
    for e in Thread(root).events():
        if e.get("type") == "card" and isinstance(e.get("card"), dict):
            c = e["card"]
            if c.get("kind") in ("permission", "options") and str(c.get("key") or "").startswith(CONSENT_PREFIX):
                out[e["id"]] = {"key": c.get("key"), "card": c, "yes": False}
        elif e.get("type") == "answer" and e.get("from") == "user" and e.get("card_id") in out:
            o = out[e["card_id"]]; o["yes"] = _yes(o["card"], e.get("answer") or {})
    return out


def consent_for(root, ref: str):
    """The card named by `ref` (event id or key; a key = its latest card) -> its event id, if she said yes; else RefsError."""
    cs = consents(root); ref = str(ref or "").strip()
    if not ref: raise RefsError("需要 --consent：她点了同意的 websearch 许可卡的 key 或 id")
    cid = ref if ref in cs else next((i for i in reversed(list(cs)) if cs[i]["key"] == ref), None)
    if not cid:
        raise RefsError(f"找不到许可卡 {ref}（要一张 key 以 {CONSENT_PREFIX} 开头的 permission / options 卡）。先发卡问她要不要上网搜这个地方的参考图")
    if not cs[cid]["yes"]: raise RefsError("她还没有在上网搜图的许可卡上点同意，所以不能下载")
    return cid


# ---------------------------------------------------------------- query hygiene
def private_terms(root) -> set:
    """Names a query may not contain: the project's people (lessons.project_names) and the owner's login / display name."""
    from . import lessons, users
    out = set(lessons.project_names(root))
    try:
        o = users.owner_of(root)
        if o: out |= {o, users.display(o)}
    except (OSError, ValueError, KeyError): pass
    return {n for n in out if isinstance(n, str) and len(n.strip()) >= 2}


def query_problems(root, *texts) -> list:
    from . import lessons
    names = sorted(private_terms(root), key=len, reverse=True); out = []
    for t in texts:
        t = str(t or "")
        low = t.lower()
        for rx, what in lessons.PRIVATE_RES:
            if rx.search(t) and what not in out: out.append(what)
        for n in names:
            if n.lower() in low and f"名字 {n}" not in out: out.append(f"名字 {n}")
    return out


def check_query(root, place, query):
    if not str(query or "").strip(): raise RefsError("需要 --query：你搜索时用的词（只写公共地点的名字，比如 Geisel Library UCSD）")
    P = query_problems(root, place, query)
    if P: raise RefsError("搜索词 / 地点里有私人信息（" + "、".join(P) + "）：只能搜公共地点本身，不能带人名、邮箱或路径")


# ---------------------------------------------------------------- the URL and the download
def _public_host(host: str, resolve=socket.getaddrinfo) -> bool:
    try: addrs = {a[4][0] for a in resolve(host, None)}
    except (OSError, UnicodeError): return False
    try: return bool(addrs) and all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addrs)
    except ValueError: return False


def check_url(url: str, resolve=None):
    u = urllib.parse.urlsplit(str(url or "").strip())
    if u.scheme not in ("http", "https") or not u.hostname: raise RefsError(f"--url 应该是图片的 http(s) 网址，收到：{url}")
    if u.username or u.password: raise RefsError("网址里不能带用户名 / 密码")
    if resolve is not False and not _public_host(u.hostname, *(() if resolve is None else (resolve,))):
        raise RefsError(f"{u.hostname} 不是公网地址（本机、内网的地址不能用）")


class _Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, resolve=None): self.resolve = resolve
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl, self.resolve)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _kind(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff": return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n": return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"): return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP": return ".webp"
    return ""


def download(url: str, opener=None, resolve=None) -> tuple:
    """-> (bytes, extension). Every hop is checked (public address, http(s)); only an image, at most MAX_BYTES."""
    check_url(url, resolve)
    op = opener or urllib.request.build_opener(_Redirects(resolve))
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/*"})
    try:
        with op.open(req, timeout=TIMEOUT) as r:
            ct = str(r.headers.get("Content-Type") or "").lower()
            data = r.read(MAX_BYTES + 1)
    except RefsError: raise
    except (urllib.error.URLError, OSError, ValueError) as e: raise RefsError(f"下载失败：{type(e).__name__} {getattr(e, 'reason', '') or e}")
    if len(data) > MAX_BYTES: raise RefsError(f"图片太大（超过 {MAX_BYTES // 1024 // 1024} MB）")
    ext = _kind(data)
    if not ext: raise RefsError(f"这个网址给的不是图片（{ct or '没有类型'}）：要图片本身的网址，不是网页")
    return data, ext


# ---------------------------------------------------------------- the index
def index_of(folder: Path) -> dict:
    d = _y(Path(folder) / "sources.yaml", {}) or {}
    if isinstance(d, list): d = {"refs": d}
    if not isinstance(d, dict): d = {}
    if not isinstance(d.get("refs"), list): d["refs"] = []
    return d


def save(root, req: dict, data: bytes, ext: str, consent_id: str) -> dict:
    """Write the picture and its sources.yaml entry; the same picture twice is kept once. -> the entry."""
    folder = refs_dir(root) / slug(req["place"]); folder.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(data).hexdigest(); idx = index_of(folder)
    for r in idx["refs"]:
        if isinstance(r, dict) and r.get("sha256") == sha: return {**r, "duplicate": True}
    n = 1 + sum(1 for r in idx["refs"] if isinstance(r, dict))
    name = f"web-{n:02d}-{sha[:8]}{ext}"
    (folder / name).write_bytes(data)
    ent = {"file": name, "source": "web", "url": req["url"], "page": req.get("page") or None, "query": req["query"],
           "license": req.get("license") or "unknown", "author": req.get("author") or None, "side": req.get("side") or None,
           "consent": consent_id, "fetched": now(), "sha256": sha, "bytes": len(data)}
    ent = {k: v for k, v in ent.items() if v is not None}
    idx.setdefault("place", req["place"]); idx["refs"].append(ent)
    (folder / "sources.yaml").write_text(yaml.safe_dump(idx, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return ent


def check_request(root, req: dict) -> str:
    """Everything but the download; -> the consent card id."""
    slug(req.get("place"))
    check_query(root, req.get("place"), req.get("query"))
    check_url(req.get("url"), False)
    for f in ("page", "license", "author", "side"):
        if req.get(f) is not None and not isinstance(req[f], str): raise RefsError(f"{f} 应该是字符串")
    return consent_for(root, req.get("consent"))


def fetch_now(root, req: dict, opener=None, resolve=None) -> dict:
    cid = check_request(root, req)
    data, ext = download(req["url"], opener, resolve)
    return save(root, req, data, ext, cid)


# ---------------------------------------------------------------- the queue (a run asks; agentd downloads)
def in_run(env=None) -> bool:
    return bool((os.environ if env is None else env).get("GAMEANYTHING_GEN_OFF"))


def request(root, place, url, query, consent, page=None, license=None, author=None, side=None) -> Path:
    root = Path(root).resolve()
    if not (root / "conversation").is_dir(): raise RefsError(f"{root} 不是一个项目文件夹（没有 conversation/）")
    req = {"place": str(place or "").strip(), "url": str(url or "").strip(), "query": str(query or "").strip(), "consent": str(consent or "").strip(),
           "page": page, "license": license, "author": author, "side": side}
    check_request(root, req)                         # fast feedback; agentd checks it all again before it downloads
    rid = f"{datetime.now():%Y%m%dT%H%M%S}_{secrets.token_hex(3)}"
    f = queue_dir(root) / f"{rid}.json"
    _write_json(f, {"id": rid, **{k: v for k, v in req.items() if v}, "session": os.environ.get("GAMEANYTHING_SESSION"), "at": now()})
    return f


def pending(root) -> list:
    d = queue_dir(root)
    return sorted(d.glob("*.json")) if d.is_dir() else []


def result_of(qf: Path):
    for st in ("done", "failed", "rejected"):
        p = qf.parent / st / qf.name
        if p.exists(): return st, _read_json(p) or {}
    return None, None


def process(root, qf: Path, opener=None, resolve=None, notify=None) -> tuple:
    """agentd: check one queued request again and download it on the host. The file moves to done / failed / rejected with the outcome;
    when the asking run stopped waiting (<id>.notify), the outcome also goes to the project's agent as a note."""
    root = Path(root).resolve(); req = _read_json(qf)
    if not isinstance(req, dict):
        qf.rename(qf.with_suffix(".bad")); return "bad", {}
    try:
        try: cid = check_request(root, req)
        except RefsError as e: state, out = "rejected", {"why": str(e)}
        else:
            try:
                data, ext = download(req["url"], opener, resolve); ent = save(root, req, data, ext, cid)
                state, out = "done", {"entry": ent, "folder": f"{REFS_DIR}/{slug(req['place'])}"}
            except RefsError as e: state, out = "failed", {"why": str(e)}
    except Exception as e: state, out = "failed", {"why": f"{type(e).__name__}: {e}"}
    res = {**req, "state": state, **out, "ended": now()}
    _write_json(qf.parent / state / qf.name, res); qf.unlink(missing_ok=True)
    mark = qf.with_suffix(".notify")
    if mark.exists():
        mark.unlink(missing_ok=True)
        if notify: notify(root, outcome_text(res))
    return state, res


def outcome_text(res: dict) -> str:
    if res.get("state") == "done":
        e = res.get("entry") or {}
        return (f"参考图已保存：{res.get('folder')}/{e.get('file')}（{res.get('place')}，来源 {e.get('url')}，许可 {e.get('license')}）"
                + ("；这张以前就存过了" if e.get("duplicate") else ""))
    return f"参考图没有保存（{res.get('place')}，{res.get('url')}）：{res.get('why')}"


def wait(qf: Path, secs=WAIT_SECS, clock=time.time, sleep=time.sleep):
    """The run's side: wait for agentd's outcome; on a timeout leave <id>.notify so the outcome comes back as a note."""
    end = clock() + secs
    while clock() < end:
        st, res = result_of(qf)
        if st: return st, res
        sleep(0.5)
    qf.with_suffix(".notify").write_text(now(), encoding="utf-8")
    st, res = result_of(qf)                           # it may have finished just now
    if st: qf.with_suffix(".notify").unlink(missing_ok=True)
    return st, res


# ---------------------------------------------------------------- what `gameanything flow check` reports
def problems(root) -> list:
    """Problems of 2_perceive/landmark_refs: pictures without a sources.yaml entry, web refs without her yes on a websearch card, web refs
    without url / query / license. [] = fine (also when there is no landmark_refs folder)."""
    base = refs_dir(root)
    if not base.is_dir(): return []
    cs = None; out = []
    for folder in sorted(p for p in base.iterdir() if p.is_dir()):
        idx = index_of(folder); listed = set()
        for r in idx["refs"]:
            if not isinstance(r, dict): continue
            listed.add(str(r.get("file") or ""))
            where = f"{folder.name}/{r.get('file')}"
            if str(r.get("source") or "web") != "web": continue           # source: user = a picture she gave
            f0 = folder / str(r.get("file") or "")
            if f0.is_file() and f0.stat().st_mtime < RULE_SINCE: continue    # saved before the rule
            miss = [k for k in ("url", "query", "license") if not str(r.get(k) or "").strip()]
            if miss: out.append(f"{where} 的 sources.yaml 缺 {' / '.join(miss)}")
            if cs is None: cs = consents(root)
            c = cs.get(str(r.get("consent") or ""))
            if not (c and c["yes"]): out.append(f"{where} 是网上的图，但没有她同意上网搜图的许可卡（consent）：删掉它，或先发 websearch 许可卡")
        for f in sorted(folder.iterdir()):
            if f.is_file() and f.suffix.lower() in IMAGE_EXT and f.name not in listed and f.stat().st_mtime >= RULE_SINCE:
                out.append(f"{folder.name}/{f.name} 没有登记在 sources.yaml 里（网图只能用 gameanything refs fetch 下载；她给的图写 source: user）")
    return out


def status_lines(root) -> list:
    out = []
    base = refs_dir(root)
    for folder in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
        refs = [r for r in index_of(folder)["refs"] if isinstance(r, dict)]
        out.append(f"{folder.name}: {len(refs)} 张")
        out += [f"  {r.get('file')}  {r.get('source', 'web')}  {r.get('license', '')}  {r.get('url', '')}" for r in refs]
    out += [f"排队中：{q.name} {(_read_json(q) or {}).get('place')}" for q in pending(root)]
    return out or ["还没有参考图"]


# ---------------------------------------------------------------- CLI
def main(a) -> int:
    from . import agentd, projects
    root = projects.resolve(a.project)
    if a.what == "status": print("\n".join(status_lines(root))); return 0
    if a.what == "check":
        P = problems(root); print("\n".join(P) if P else "参考图没有问题"); return 1 if P else 0
    req = {"place": a.place, "url": a.url, "query": a.query, "consent": a.consent, "page": a.page, "license": a.license, "author": a.author, "side": a.side}
    try:
        if not in_run():
            e = fetch_now(root, {k: (str(v).strip() if isinstance(v, str) else v) for k, v in req.items()})
            print(outcome_text({"state": "done", "place": a.place, "url": a.url, "entry": e, "folder": f"{REFS_DIR}/{slug(a.place)}"})); return 0
        qf = request(root, **req)
    except RefsError as e: print(f"[refs] {e}"); return 2
    if not agentd.daemon_state().get("alive"):
        print(f"[refs] 已排队（{qf.name}），但后台（agentd）现在没有运行：它启动后会下载，并留言告诉你"); qf.with_suffix(".notify").write_text(now(), encoding="utf-8"); return 0
    st, res = wait(qf, a.wait)
    if not st: print(f"[refs] 已排队（{qf.name}），后台还在下载；下好后会留言告诉你"); return 0
    print(f"[refs] {outcome_text(res)}"); return 0 if st == "done" else 2
