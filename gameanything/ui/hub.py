"""`gameanything hub`: one server, one port, several users.

    /login, POST /api/login, POST /api/logout      username + password; an HttpOnly, SameSite=Strict, signed session cookie (users.py)
    /  (static/hub.html + hub.js)                  the user's project list: their own, shared with them, everyone else's (read-only or 可申请)
    /api/hub, /api/hub/new, /api/members           the list, a new project of one's own, the owner changing members
    /api/access/request {project, role, note}      a permission card in the OWNER's project thread; the owner's answer sets `members`
    /api/me/claude[/disconnect|/test], /api/me/password      「我的 agent」 (a Claude subscription token or API key in the user's own env file,
    /api/me/agent {agent}, /api/me/codex[/disconnect]  never sent back; a test call like agentd's; which CLI runs their projects: Claude Code
                                                   or Codex, and a Codex OpenAI key) and changing one's own password
    /api/me/genkeys[/remove] {key, value}          「素材生成 API keys」 (fal, Meshy, OpenAI, OpenRouter) in her env file: set / remove / status
    /api/me/opencode {token, model}[/disconnect], /api/me/gemini {token}[/disconnect], /api/me/dsh {token}[/disconnect], /api/me/model {agent, model}
                                                   OpenCode (a model provider's key, e.g. OpenRouter, + provider/model), Gemini CLI (a Gemini API key)
                                                   and DeepSeek Harness (a DeepSeek API key)
    /api/me/codex/login[/cancel]                   「用 ChatGPT 登录 Codex」: POST starts `codex login --device-auth` for her own CODEX_HOME (one
                                                   at a time), GET polls {state, url, code}, cancel kills that login process (users.py)
    /api/admin/users, /api/admin/user/{add,passwd,remove,admin}    「用户管理」 (admins): add, reset a password, remove (projects stay), admin
    /p/<project id>/<path>                         the usual UI of that project (ui/__init__.py's handler), bound to it for this one request

Every request under /p/<id>/ checks the session user's role on that project (users.role_of): GET needs view; POSTs need what POST_NEED
says (default edit); deleting the project and changing members only the owner. The pages are the single-user pages: the hub puts
window.M2W_HUB {base, user, role} and window.M2W_BASE into them, and a few lines there (ui/__init__.py BASE_PATCH) prefix the page's own fetch / XHR calls with /p/<id>. Pictures, videos and
downloads the page links without the prefix are found through the Referer (the page they were linked from).

Isolation is app-level only: everyone on the server is root. The hub binds 127.0.0.1 unless --host says otherwise. Behind an https
reverse proxy set GAMEANYTHING_HUB_TRUST_PROXY=1 so the Origin check believes its X-Forwarded-Host / -Proto (otherwise the Origin's
host must equal the Host header, http or https). Import uploads live in each user's own folder under random names and are deleted
after the import; export zips need edit, carry a random part in their name and are deleted after EXPORT_TTL.
"""
import json
import os
import re
import secrets
import threading
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from .. import buildmode, projects, transfer, users
from ..native import quiet, ready
from ..conversation import CardError
from . import BASE_PATCH, DECISION_REFUSED, STATIC, Project, _Server, handler
from .i18n import err, scrub_paths
from .manage import Current, Manager
from .upload import Inbox

REQ = threading.local()                       # .user: the session user of the request this thread serves
COOKIE = "m2w_hub"
STATIC_JS = {"/i18n.js", "/shell.js", "/manage.js", "/onboard.js", "/tag.js", "/app.js", "/hub.js"}
HUB_LEVEL = {"/api/logout", "/api/access/request", "/api/hub", "/api/hub/new", "/api/members"}    # also reachable under /p/<id>/ (the patched fetch)
ACCOUNT_GET = {"/api/me/claude", "/api/me/codex/login", "/api/admin/users", "/api/me/genkeys"}
ACCOUNT_POST = {"/api/me/password", "/api/me/claude", "/api/me/claude/disconnect", "/api/me/claude/test",
                "/api/me/agent", "/api/me/codex", "/api/me/codex/disconnect", "/api/me/codex/login", "/api/me/codex/login/cancel",
                "/api/me/opencode", "/api/me/opencode/disconnect", "/api/me/gemini", "/api/me/gemini/disconnect", "/api/me/model",
                "/api/me/dsh", "/api/me/dsh/disconnect",
                "/api/admin/user/add", "/api/admin/user/passwd", "/api/admin/user/remove", "/api/admin/user/admin",
                "/api/me/genkeys", "/api/me/genkeys/remove"}
# the role a POST under /p/<id>/ needs; anything not listed needs edit. 「评论」 only adds words: the chat, and notes on the play video
# (Project.kind_ok refuses its verdicts); every review page saves a decision (confirm / choices / verdicts), so those need edit, as cards do.
POST_NEED = {"/api/thread": "comment", "/api/play_feedback": "comment",
             "/api/review": "edit", "/api/board_review": "edit", "/api/plan_review": "edit", "/api/adaptation_review": "edit",
             "/api/gameplay_review": "edit", "/api/feature_review": "edit", "/api/thread/answer": "edit", "/api/next_round": "edit",
             "/api/coach": "view", "/api/projects/open": "view", "/api/projects/new": "view", "/api/import/start": "view",
             "/api/projects/remove": "owner", "/api/settings": "admin", "/api/profile": "owner", "/api/models": "owner",
             "/api/backup/preview": "owner", "/api/backup/enable": "owner", "/api/backup/disable": "owner", "/api/backup/run": "owner"}
# GETs under /p/<id>/ that need more than view: global settings and the backup panel (where her data goes), export zips (the whole project)
GET_NEED = {"/api/settings": "owner", "/api/backup": "owner", "/api/export": "edit"}
EXPORT_TTL = 3600                                  # an export zip in the hub lives this long (seconds), then it is deleted
DUMMY_HASH = users.hash_password("no such user, same work")
# wrong passwords: FAIL_MAX per (user name, IP) in FAIL_WINDOW, and a softer FAIL_MAX_IP per IP (so one mistyped name never locks out
# everyone behind the same address)
FAILS = {}; FAILS_LOCK = threading.Lock(); FAIL_MAX, FAIL_MAX_IP, FAIL_WINDOW = 8, 40, 300
TESTS = {}; TEST_GAP, TEST_MAX, TEST_WINDOW = 15, 6, 600      # 「测试连接」: per user, one at a time, 15 s apart, 6 per 10 minutes
REMOVED = {"zh": "已移除用户", "en": "Removed user"}
PATCH = BASE_PATCH + ("(function(){var H=window.M2W_HUB;var c=document.documentElement.classList;c.add(\"m2w-hub\");c.add(\"m2w-role-\"+H.role)})();")


def need_for(path, headers) -> str:
    if path == "/api/upload": return "view" if headers.get("X-Upload-Target") == "import" else "edit"
    return POST_NEED.get(path, "edit")


def get_need(path, query="") -> str:
    if path.startswith("/exports/"): return "edit"
    if path == "/api/upload" and "target=import" in query: return "view"          # her own import folder (HubManager.imports)
    return GET_NEED.get(path, "view")


def _fails_add(*keys):
    t = time.time()
    with FAILS_LOCK:
        for k in keys: FAILS.setdefault(k, []).append(t)


def _fails_ok(name, ip) -> bool:
    """Fewer than FAIL_MAX wrong passwords for this name from this IP, and fewer than FAIL_MAX_IP from this IP in all."""
    t0 = time.time()
    with FAILS_LOCK:
        for k in [k for k in FAILS if not [x for x in FAILS[k] if t0 - x < FAIL_WINDOW]]: FAILS.pop(k, None)
        n = lambda k: sum(1 for x in FAILS.get(k, []) if t0 - x < FAIL_WINDOW)
        return n(("user", name, ip)) < FAIL_MAX and n(("ip", ip)) < FAIL_MAX_IP


class RandomInbox(Inbox):
    """An import drop folder whose finished uploads get a random name (never the client's), so no one can name another's zip."""
    def _final(self, rel):
        return self.dir / f"{secrets.token_hex(12)}.zip"


def _entry(e) -> dict:
    return {"id": e["id"], "title": e["title"], "kind": e.get("kind") or "memory", "game": e.get("game") or "stardew", "last_opened": e.get("last_opened")}


class HubManager(Manager):
    """The project-level manager of one project in the hub: the list, opening, creating, removing and importing act for the session user."""
    multi_user = True                                           # 「在哪里做」: the lab is recommended where both work

    def __init__(self, cur, make, upload_max, hub):
        self._imports = {}; self._imports_lock = threading.Lock()
        super().__init__(cur, make, upload_max); self.hub = hub

    @property
    def imports(self):
        """The session user's own import folder (<their data>/imports/.u-<name>): an upload id or a zip of someone else's is never in it."""
        u = REQ.user or {}; name = u.get("name") or "-"
        with self._imports_lock:
            if name not in self._imports:
                base = Path(u.get("data_root") or projects.data_dir()) / "imports" / f".u-{name}"
                self._imports[name] = RandomInbox(None, self.upload_max_, base, {"zip"})
            return self._imports[name]

    @imports.setter
    def imports(self, v): self.upload_max_ = v.max                   # Manager.__init__'s shared folder is never used in the hub

    def examples(self):
        """The welcome page's examples: the curated settings list, else only the session user's OWN projects, else the bundled stills."""
        from . import onboard
        return onboard.examples(keep=lambda root: users.role_of(REQ.user, root) == "owner")

    def welcome(self, lang="zh"):
        r = super().welcome(lang); self.exs = None; return r          # never keep one user's list for the next one

    def example_file(self, i: int, what: str) -> Path:
        exs = self.examples(); x = exs[i] if 0 <= i < len(exs) else {}
        p = x.get("image_path") if what == "image" else x.get("video_path") if what == "video" else None
        if not p or not Path(p).is_file(): raise FileNotFoundError(f"{i}/{what}")
        return Path(p)

    def _job(self, kind, fn):
        j = super()._job(kind, fn); j["by"] = (REQ.user or {}).get("name"); return j

    def job(self, jid, lang="zh"):
        j = self.jobs.get(jid)
        if not j or (j["kind"] == "import" and j.get("by") != (REQ.user or {}).get("name")): raise KeyError(jid)
        return {k: v for k, v in super().job(jid, lang).items() if k not in ("path", "raw", "by")}     # no server paths for the page

    def _sweep_exports(self):
        """Export zips older than EXPORT_TTL are deleted."""
        t0 = time.time()
        for f in self.exports.glob("*.zip") if self.exports.is_dir() else []:
            try:
                if t0 - f.stat().st_mtime > EXPORT_TTL: f.unlink()
            except OSError: pass

    def export_name(self, e):
        return f"{e['id']}-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_urlsafe(18)}.zip"        # not guessable from the time

    def export_start(self, d):
        self._sweep_exports(); return super().export_start(d)

    def role(self): return users.role_of(REQ.user, self.cur.root)
    def viewer(self): return (REQ.user or {}).get("name") or "local"

    def project_list(self, lang="zh"):
        cur = str(self.cur.root) if self.cur.root else None; out = []
        for e in projects.load():
            root = Path(e["path"])
            if not root.is_dir() or not users.role_of(REQ.user, root): continue
            out.append({**_entry(e), "current": str(root.resolve()) == cur, "exists": True})
        out.sort(key=lambda e: e["last_opened"] or "", reverse=True); out.sort(key=lambda e: not e["current"])
        return out

    def shell_extra(self, lang="zh"):
        return {**super().shell_extra(lang), "hub": self.hub.info(REQ.user, self.cur.root, lang)}

    def open(self, d):
        e = projects.find(str(d.get("id") or ""))
        if not users.role_of(REQ.user, Path(e["path"])): raise users.HubError("没有权限打开这个项目")
        return {"ok": True, "id": e["id"], "go": f"/p/{e['id']}/"}

    def new(self, d):
        e = users.create_project(REQ.user, str(d.get("title") or ""), str(d.get("kind") or "memory"),
                                 lang=d.get("lang") if d.get("lang") in ("zh", "en") else "en", game=str(d.get("game") or "stardew"),
                                 build_mode=d.get("mode") or None)
        return {"ok": True, "id": e["id"], "go": f"/p/{e['id']}/"}

    def remove(self, d):
        e = projects.find(str(d.get("id") or ""))
        if users.role_of(REQ.user, Path(e["path"])) != "owner": raise users.HubError("只有项目的所有者能删除项目")
        dst = projects.remove(e["id"]); self.hub.forget(e["path"])
        return {"ok": True, "trash": str(dst) if dst else None, "welcome": False, "go": "/"}

    def set_game(self, d):
        e = projects.set_game(self.entry()["id"], str(d.get("game") or ""))           # only the project this page is bound to
        self.cur.p = self.make(Path(e["path"])); return {"ok": True, "id": e["id"], "game": e["game"]}

    def set_mode(self, d):
        e = buildmode.set_mode(self.entry()["id"], str(d.get("mode") or ""))             # only the project this page is bound to (POST needs edit)
        return {"ok": True, "id": e["id"], "build_mode": buildmode.mode_of(Path(e["path"]))}

    def set_launch(self, d):
        e = quiet.set_policy(self.entry()["id"], str(d.get("mode") or ""), d.get("window") or None, d.get("minutes"), d.get("drive") or None,
                             d.get("front") or None, d.get("hands") or None)      # only the project this page is bound to
        return {"ok": True, "id": e["id"], "native_launch": quiet.policy(Path(e["path"])), "native_ready": ready.summary(Path(e["path"]))}

    def coach(self, d):
        if not users.at_least(self.role(), "edit"): return {"ok": True}                 # a reader's clicks never write into the owner's project
        return super().coach(d)

    def settings(self, d=None):
        if d is not None and not (REQ.user or {}).get("admin"): raise users.HubError("只有管理员能改全局设置")
        return super().settings(d)

    def export_file(self, name):
        if not name.startswith(self.entry()["id"] + "-"): raise FileNotFoundError(name)     # only this project's exports (the GET needs edit)
        self._sweep_exports(); return super().export_file(name)

    def import_start(self, d):
        """Like the single-user import, from the user's OWN upload folder into their own data folder, owned by them (members of the exported
        copy are dropped); the uploaded zip is deleted once the import is over."""
        rel = str(d.get("path") or ""); base = self.imports.dir.resolve(); f = (base / rel).resolve()
        if f.parent != base or not f.is_file(): raise ValueError("找不到上传的文件")
        user = REQ.user
        if any(j["state"] == "running" and j["kind"] == "import" and j.get("by") == user["name"] for j in self.jobs.values()): raise ValueError("正在导入：等它完成")
        into = Path(user.get("data_root") or projects.data_dir()) / "projects"

        def fn(prog):
            try:
                r = transfer.import_project(f, into, None, unique=True, progress=prog)
                users.set_owner(r["path"], user["name"]); users._write_cfg_key(r["path"], "members", None)
                return {k: v for k, v in r.items() if k not in ("path", "raw")}
            finally:
                try: f.unlink()
                except OSError: pass
        return {"ok": True, "job": self._job("import", fn)}


class Hub:
    def __init__(self, upload_max=20 * 2 ** 30, content=None):
        self.upload_max, self.content = upload_max, content; self.cache = {}; self.lock = threading.Lock()

    def make(self, root): return Project(Path(root), self.content, self.upload_max)

    def bound(self, root):
        """(Current, HubManager) of a project folder, made once and kept (its upload locks, export jobs and backup scheduler live there)."""
        k = str(Path(root).resolve())
        with self.lock:
            if k not in self.cache:
                cur = Current(self.make(Path(root))); self.cache[k] = (cur, HubManager(cur, self.make, self.upload_max, self))
            return self.cache[k]

    def forget(self, root):
        with self.lock: self.cache.pop(str(Path(root).resolve()), None)

    def info(self, user, root, lang="zh") -> dict:
        role = users.role_of(user, root); o = users.owner_of(root); req = users.latest_request(root, user["name"]) if role != "owner" else None
        gone = bool(o) and not users.get_user(o)
        return {"user": user["name"], "display": user.get("display") or user["name"], "admin": bool(user.get("admin")), "role": role,
                "owner": o, "owner_name": REMOVED.get(lang, REMOVED["zh"]) if gone else users.display(o), "owner_removed": gone, "private": users.private(root),
                "can": {"chat": users.at_least(role, "comment"), "cards": users.at_least(role, "edit"), "edit": users.at_least(role, "edit"),
                        "owner": role == "owner", "admin": bool(user.get("admin"))},
                "request": {k: req.get(k) for k in ("role", "state", "at")} if req else None}

    def overview(self, user) -> dict:
        us = users.load_users(); out = []
        for e in projects.load():
            root = Path(e["path"])
            if not root.is_dir(): continue
            role = users.role_of(user, root); o = users.owner_of(root)
            ent = _entry(e) if role else {**_entry(e), "title": "", "title_hidden": True}       # a private project of someone else: no title
            x = {**ent, "owner": o, "owner_name": (us.get(o) or {}).get("display") or o, "owner_removed": bool(o) and o not in us,
                 "role": role, "private": users.private(root),
                 "section": "mine" if role == "owner" else "shared" if users.members_of(root).get(user["name"]) else "others"}
            if role == "owner":
                x["members"] = [{"name": n, "display": (us.get(n) or {}).get("display") or n, "role": r, "removed": n not in us}
                                for n, r in users.members_of(root).items()]
                x["pending"] = sum(1 for r in users.requests_of(root) if r.get("state") == "pending")
            else:
                r = users.latest_request(root, user["name"]); x["request"] = {k: r.get(k) for k in ("role", "state", "at")} if r else None
            out.append(x)
        out.sort(key=lambda x: x["last_opened"] or "", reverse=True)
        return {"user": {"name": user["name"], "display": user.get("display") or user["name"], "admin": bool(user.get("admin")),
                         "claude_login": users.agent_login(user, daemon_agent()), "claude": users.claude_status(user),
                         "agent": users.agent_status(user, daemon_agent())},
                "projects": out, "users": [{"name": n, "display": u.get("display") or n} for n, u in us.items()],
                "kinds": list(projects.KINDS), "games": projects.GAMES, "default_game": projects.DEFAULT_GAME}


def hub_handler(hub: Hub):
    home_cur = Current(None)
    Base = handler(home_cur, Manager(home_cur, hub.make, hub.upload_max))

    class HubH(Base):
        base = None

        def own_hosts(self) -> set:
            """The host[:port] this page is served as: the Host header, and behind a reverse proxy the X-Forwarded-Host it sends (only when
            GAMEANYTHING_HUB_TRUST_PROXY=1 says one is in front)."""
            hs = {(self.headers.get("Host") or "").strip().lower()}
            if trust_proxy():
                fh = (self.headers.get("X-Forwarded-Host") or "").split(",")[0].strip().lower()
                if fh: hs.add(fh)
            hs.discard(""); return hs

        def origin_ok(self) -> bool:
            """A POST from this page: the Origin's host is the one the request was sent to (http or https; behind a trusted proxy its
            X-Forwarded-Proto must match too). No Origin: a script on this machine (the browser always sends one with a POST)."""
            o = self.headers.get("Origin")
            if o is None: return True
            u = urlparse(o)
            if u.scheme not in ("http", "https") or u.path not in ("", "/") or (u.netloc or "").lower() not in self.own_hosts(): return False
            fp = (self.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower() if trust_proxy() else ""
            return not fp or fp == u.scheme

        def decision_ok(self) -> bool:
            """Her decisions in the hub: the page's Origin (her login cookie, HttpOnly SameSite=Strict, already says it is her browser)."""
            if self.agent_peer(): return False
            return self.headers.get("Origin") is not None and self.origin_ok()

        def inject(self, html: bytes) -> bytes:
            if not self.base: return html
            info = {"base": self.base, "user": REQ.user["name"], "display": REQ.user.get("display") or REQ.user["name"], "role": users.role_of(REQ.user, self.proj.root)}
            s = json.dumps(info, ensure_ascii=False).replace("</", "<\\/")
            return html.replace(b"<head>", f"<head><script>window.M2W_HUB={s};window.M2W_BASE={json.dumps(self.base)};{PATCH}</script>".encode(), 1)

        def end_headers(self):
            self.send_header("Referrer-Policy", "same-origin")        # same-origin links always carry the page they came from (see dispatch)
            super().end_headers()

        def send_header(self, k, v):
            if k.lower() == "location" and self.base and str(v).startswith("/") and not str(v).startswith(self.base + "/"): v = self.base + v
            super().send_header(k, v)

        def cookie(self):
            c = SimpleCookie()
            try: c.load(self.headers.get("Cookie") or "")
            except Exception: return None
            return c[COOKIE].value if COOKIE in c else None

        def drain(self):
            """Read the request body we will not use (up to 1 MiB) before refusing it: closing a socket with unread data makes Windows
            send a reset, so the client would see ConnectionAbortedError instead of the error answer."""
            left = min(int(self.headers.get("Content-Length") or 0), 1 << 20)
            while left > 0:
                buf = self.rfile.read(min(1 << 16, left))
                if not buf: break
                left -= len(buf)

        def forbidden(self):
            """403 for a cross-site POST (the body read first: drain)."""
            self.drain()
            return self.send(403, b"forbidden", "text/plain")

        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 1 << 20: raise ValueError("too large")
            return json.loads(self.rfile.read(n) or b"{}")

        def redirect(self, to):
            self.send_response(302); self.send_header("Location", to); self.send_header("Content-Length", "0"); self.end_headers()

        def do_GET(self): self.dispatch("GET")
        def do_POST(self): self.dispatch("POST")

        def dispatch(self, method):
            self.base = None; self.proj, self.mgr = home_cur, Base.mgr; REQ.user = None; bound = None
            u = urlparse(self.path); path = u.path
            if method == "POST" and self.agent_peer(): return self.forbidden()       # isolation on: an agent account never logs in or decides
            try:
                if method == "GET" and path in STATIC_JS:
                    return self.send(200, (STATIC / path[1:]).read_bytes(), "text/javascript; charset=utf-8")
                if method == "GET" and path in ("/app.css", "/fonts/inter-latin-wght-normal.woff2"):
                    return self.send(200, (STATIC / path[1:]).read_bytes(), "text/css; charset=utf-8" if path.endswith(".css") else "font/woff2")
                if method == "GET" and path == "/login": return self.send(200, (STATIC / "hub.html").read_bytes(), "text/html; charset=utf-8")
                if method == "POST" and path == "/api/login": return self.login()
                user = users.session_user(self.cookie())
                if not user:
                    if method == "GET" and not path.startswith("/api/") and "/api/" not in path:
                        return self.redirect("/login" + (f"?next={quote(path)}" if path.startswith("/p/") else ""))
                    return self.fail(401, "请先登录", login=True)
                REQ.user = user
                m = re.match(r"^/p/([A-Za-z0-9_.-]+)(/.*)?$", path)
                if m and m.group(2) in HUB_LEVEL: path = m.group(2); m = None
                if m:
                    if m.group(2) is None: return self.redirect(f"/p/{m.group(1)}/" + (f"?{u.query}" if u.query else ""))
                    bound = self.project(method, user, m.group(1), m.group(2) + (f"?{u.query}" if u.query else "")); return
                if path == "/" and "embed" not in parse_qs(u.query) and method == "GET":
                    return self.send(200, (STATIC / "hub.html").read_bytes(), "text/html; charset=utf-8")
                if path == "/api/hub" and method == "GET": return self.json(hub.overview(user))
                if method == "POST" and path in HUB_LEVEL: return self.hub_post(user, path)
                if (method == "GET" and path in ACCOUNT_GET) or (method == "POST" and path in ACCOUNT_POST): return self.account(method, user, path)
                ref = urlparse(self.headers.get("Referer") or ""); rm = re.match(r"^/p/([A-Za-z0-9_.-]+)/", ref.path or "")
                if rm and ref.netloc.lower() in self.own_hosts():       # a picture / video / download / the workspace frame linked without the prefix
                    if method == "GET" and path in ("/", "/app"): return self.redirect(f"/p/{rm.group(1)}{path}" + (f"?{u.query}" if u.query else ""))
                    bound = self.project(method, user, rm.group(1), self.path); return
                return self.send(404, b"not found", "text/plain")
            finally:
                if bound is not None: bound.local.who = None; bound.local.role = None
                REQ.user = None

        # ---- login
        def login(self):
            if not self.origin_ok(): return self.forbidden()
            ip = self.client_address[0]
            try: d = self.body()
            except ValueError: return self.fail(400, "请求不对")
            name = str(d.get("name") or "").strip().lower()[:64]
            if not _fails_ok(name, ip): return self.fail(429, "试错太多次了，请过几分钟再试")
            u = users.get_user(name)
            if not users.check_password(str(d.get("password") or ""), u.get("password_hash") if u else DUMMY_HASH) or not u:     # same work for an unknown name
                _fails_add(("user", name, ip), ("ip", ip))
                time.sleep(0.4); return self.fail(401, "用户名或密码不对")
            self.with_session(name, {"ok": True, "user": name})

        def with_session(self, name, obj):
            """A JSON answer that also sets a fresh session cookie for this user."""
            c = users.make_session(name); body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
            self.send_header("Set-Cookie", f"{COOKIE}={c}; HttpOnly; SameSite=Strict; Path=/; Max-Age={users.SESSION_SECS}")
            self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)

        # ---- 「我的 Claude」, one's own password, 「用户管理」 (admins)
        def account(self, method, user, path):
            name = user["name"]
            if method == "POST" and not self.origin_ok(): return self.forbidden()
            try:
                d = self.body() if method == "POST" else {}
                if path == "/api/me/claude":
                    if method == "POST": users.connect_claude(name, str(d.get("kind") or ""), d.get("token"))
                    return self.json({"ok": True, "claude": users.claude_status(users.get_user(name)), "agent": users.agent_status(users.get_user(name), daemon_agent())})
                if path == "/api/me/claude/disconnect": return self.json({"ok": True, "claude": users.disconnect_claude(name), "agent": users.agent_status(users.get_user(name), daemon_agent())})
                if path == "/api/me/agent": return self.json({"ok": True, "agent": {**users.set_agent(name, d.get("agent")), "default": daemon_agent()}})
                if path == "/api/me/codex": users.connect_codex(name, d.get("token")); return self.json({"ok": True, "agent": users.agent_status(users.get_user(name), daemon_agent())})
                if path == "/api/me/codex/disconnect": users.disconnect_codex(name); return self.json({"ok": True, "agent": users.agent_status(users.get_user(name), daemon_agent())})
                if path == "/api/me/opencode": users.connect_opencode(name, d.get("token"), d.get("model") or None); return self.json({"ok": True, "agent": users.agent_status(users.get_user(name), daemon_agent())})
                if path == "/api/me/opencode/disconnect": users.disconnect_opencode(name); return self.json({"ok": True, "agent": users.agent_status(users.get_user(name), daemon_agent())})
                if path == "/api/me/gemini": users.connect_gemini(name, d.get("token")); return self.json({"ok": True, "agent": users.agent_status(users.get_user(name), daemon_agent())})
                if path == "/api/me/gemini/disconnect": users.disconnect_gemini(name); return self.json({"ok": True, "agent": users.agent_status(users.get_user(name), daemon_agent())})
                if path == "/api/me/dsh": users.connect_dsh(name, d.get("token"), d.get("model") or None); return self.json({"ok": True, "agent": users.agent_status(users.get_user(name), daemon_agent())})
                if path == "/api/me/dsh/disconnect": users.disconnect_dsh(name); return self.json({"ok": True, "agent": users.agent_status(users.get_user(name), daemon_agent())})
                if path == "/api/me/model": return self.json({"ok": True, "agent": users.set_model(name, str(d.get("agent") or ""), d.get("model"))})
                if path == "/api/me/codex/login":                  # her own account only: the session user, never a name from the request
                    lg = users.codex_login_start(name) if method == "POST" else users.codex_login_status(name)
                    return self.json({"ok": True, "login": lg, "agent": users.agent_status(users.get_user(name), daemon_agent())})
                if path == "/api/me/codex/login/cancel":
                    return self.json({"ok": True, "login": users.codex_login_cancel(name), "agent": users.agent_status(users.get_user(name), daemon_agent())})
                if path == "/api/me/claude/test": return self.claude_test(name)
                if path == "/api/me/genkeys":                      # 「素材生成 API keys」: set / status, never a value back
                    ks = users.set_gen_key(name, str(d.get("key") or ""), d.get("value")) if method == "POST" else users.gen_keys_status(users.get_user(name))
                    return self.json({"ok": True, "keys": ks})
                if path == "/api/me/genkeys/remove": return self.json({"ok": True, "keys": users.remove_gen_key(name, str(d.get("key") or ""))})
                if path == "/api/me/password":
                    if not self.pw_attempt_ok(name): return self.fail(429, "试错太多次了，请过几分钟再试")
                    if not users.check_password(str(d.get("old") or ""), user.get("password_hash")):
                        self.pw_failed(name); return self.fail(400, "原密码不对")
                    users.set_password(name, str(d.get("new") or ""))     # every other session of this user ends (the hash is in the signature)
                    return self.with_session(name, {"ok": True})
                if not user.get("admin"): return self.fail(403, "只有管理员能管理用户")
                if path == "/api/admin/users": return self.json({"ok": True, **admin_list(name)})
                who = str(d.get("name") or "").strip().lower()
                if path == "/api/admin/user/add":
                    pw = str(d.get("password") or "") or users.new_password()
                    users.add_user(who, pw, bool(d.get("admin")), str(d.get("display") or "").strip()[:60] or None)
                    return self.json({"ok": True, "name": who, **({"password": pw} if not d.get("password") else {})})
                if not users.get_user(who): raise users.HubError(f"没有用户 {who}")
                if path == "/api/admin/user/passwd":
                    pw = str(d.get("password") or "") or users.new_password(); users.set_password(who, pw)
                    if who == name: return self.with_session(name, {"ok": True, "name": who, **({"password": pw} if not d.get("password") else {})})
                    return self.json({"ok": True, "name": who, **({"password": pw} if not d.get("password") else {})})
                if path == "/api/admin/user/remove":
                    if who == name: raise users.HubError("不能移除你自己")
                    users.remove_user(who); return self.json({"ok": True})
                if path == "/api/admin/user/admin":
                    users.set_admin(who, bool(d.get("admin"))); return self.json({"ok": True})
            except (users.HubError, ValueError, OSError) as x: return self.fail(400, users.redact(str(x)))
            return self.send(404, b"not found", "text/plain")

        def pw_attempt_ok(self, name):
            return _fails_ok(name, self.client_address[0])

        def pw_failed(self, name):
            _fails_add(("user", name, self.client_address[0]), ("ip", self.client_address[0])); time.sleep(0.4)

        def claude_test(self, name):
            t0 = time.time()
            with FAILS_LOCK:
                st = TESTS.setdefault(name, {"at": [], "busy": False}); st["at"] = [x for x in st["at"] if t0 - x < TEST_WINDOW]
                if st["busy"]: return self.fail(429, "上一次测试还没结束")
                wait = max(TEST_GAP - (t0 - st["at"][-1]) if st["at"] else 0, (TEST_WINDOW - (t0 - st["at"][0])) if len(st["at"]) >= TEST_MAX else 0)
                if wait > 0: return self.fail(429, f"测试太频繁了，请过 {int(wait) + 1} 秒再试")
                st["busy"] = True; st["at"].append(t0)
            try: r = users.try_claude(name, agent=users.agent_of(users.get_user(name), daemon_agent()))
            finally:
                with FAILS_LOCK: st["busy"] = False
            r = {**r, "text": err(r["text"], self.lang())}
            return self.json({"ok": True, "test": r, "claude": users.claude_status(users.get_user(name)), "agent": users.agent_status(users.get_user(name), daemon_agent())})

        # ---- hub-level POSTs
        def hub_post(self, user, path):
            if not self.origin_ok(): return self.forbidden()
            try:
                d = self.body()
                if path == "/api/logout":
                    users.end_session(self.cookie()); body = b'{"ok": true}'
                    self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
                    self.send_header("Set-Cookie", f"{COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"); self.end_headers(); self.wfile.write(body); return
                if path == "/api/hub/new":
                    e = users.create_project(user, str(d.get("title") or ""), str(d.get("kind") or "memory"),
                                             lang=d.get("lang") if d.get("lang") in ("zh", "en") else "en", game=str(d.get("game") or "stardew"),
                                             build_mode=d.get("mode") or None)
                    return self.json({"ok": True, "id": e["id"], "go": f"/p/{e['id']}/"})
                e = projects.find(str(d.get("project") or "")); root = Path(e["path"])
                if path == "/api/access/request":
                    r = users.request_access(root, user, str(d.get("role") or ""), d.get("note") or "")
                    return self.json({"ok": True, "request": {k: r[k] for k in ("id", "role", "state", "at")}})
                if path == "/api/members":
                    if users.role_of(user, root) != "owner": return self.fail(403, "只有项目的所有者能改成员")
                    who = str(d.get("user") or "")
                    if not users.get_user(who): raise users.HubError(f"没有用户 {who}")
                    users.set_member(root, who, d.get("role") or None); return self.json({"ok": True, "members": users.members_of(root)})
            except KeyError: return self.fail(404, "找不到这个项目")
            except (users.HubError, CardError, ValueError, OSError) as x: return self.fail(400, str(x))
            return self.send(404, b"not found", "text/plain")

        # ---- one project, bound for this request
        def project(self, method, user, pid, rest):
            try: e = projects.find(pid)
            except KeyError: self.send(404, b"not found", "text/plain"); return None
            root = Path(e["path"])
            if not root.is_dir(): self.send(404, b"not found", "text/plain"); return None
            role = users.role_of(user, root)
            if not role:
                if method != "GET": self.drain()
                self.fail(403, "这个项目没有共享给你：可以在项目列表里申请权限", need="view", role=None); return None
            cur, mgr = hub.bound(root)
            self.proj, self.mgr, self.base = cur, mgr, f"/p/{pid}"
            cur.p.local.who = {"author": user["name"], "author_name": user.get("display") or user["name"]}; cur.p.local.role = role
            self.path = rest; p = urlparse(rest).path
            if method == "GET":
                need = get_need(p, urlparse(rest).query)
                if need != "view" and not (user.get("admin") and p == "/api/settings") and not users.at_least(role, need):
                    self.fail(403, "只有项目的所有者能做这一步" if need == "owner" else "你没有编辑权限：申请编辑权限后才能做这一步", need=need, role=role); return cur.p
                Base.do_GET(self); return cur.p
            need = need_for(p, self.headers)
            if not (user.get("admin") if need == "admin" else users.at_least(role, need)):
                msg = {"comment": "你现在只能看：申请评论或编辑权限后才能在这里说话", "edit": "你没有编辑权限：申请编辑权限后才能做这一步",
                       "owner": "只有项目的所有者能做这一步", "admin": "只有管理员能改全局设置"}.get(need, "没有权限")
                self.drain(); self.fail(403, msg, need=need, role=role); return cur.p
            if p == "/api/thread/answer": self.answer(cur, root, user, role); return cur.p
            Base.do_POST(self); return cur.p

        def answer(self, cur, root, user, role):
            if not self.decision_ok(): self.drain(); return self.fail(403, DECISION_REFUSED, need="reload")
            try:
                d = self.body(); cid = d.get("card_id")
                if users.access_card(root, cid):                  # an access request: only the owner decides; the answer sets members
                    if role != "owner": return self.fail(403, "只有项目的所有者能决定权限申请")
                    with cur.lock: ev = users.decide(root, cid, d.get("answer"), user)
                    r = {"ok": True, "event": ev}
                else: r = cur.answer(d)
            except (CardError, users.HubError, ValueError) as x: return self.fail(400, str(x))
            self.json(r)

        def fail(self, code, msg, **extra):
            self.json({"ok": False, "error": scrub_paths(err(msg, self.lang())), **extra}, code)
    return HubH


def trust_proxy() -> bool:
    """GAMEANYTHING_HUB_TRUST_PROXY=1: a reverse proxy (https) in front sets X-Forwarded-Host / -Proto, and those are believed."""
    return (os.environ.get("GAMEANYTHING_HUB_TRUST_PROXY") or os.environ.get("M2W_HUB_TRUST_PROXY") or "").strip().lower() in ("1", "true", "yes", "on")


def daemon_agent() -> str:
    """The agent CLI agentd runs projects with when a user chose none (its heartbeat, else $GAMEANYTHING_AGENT_PROVIDER, else claude-code)."""
    from .. import agentd
    p = (agentd._read(agentd.heartbeat_path()) or {}).get("provider") or os.environ.get("GAMEANYTHING_AGENT_PROVIDER") or "claude-code"
    return p if p in users.AGENTS else "claude-code"


def admin_list(me) -> dict:
    """「用户管理」: every user (no secrets, no paths) with their project count; owners no longer in users.yaml as removed."""
    us = users.load_users(); count = {}
    for e in projects.load():
        root = Path(e["path"])
        if root.is_dir(): o = users.owner_of(root); count[o] = count.get(o, 0) + 1
    rows = [{"name": n, "display": u.get("display") or n, "admin": bool(u.get("admin")), "created": u.get("created"), "me": n == me,
             "claude": users.agent_login({**u, "name": n}, daemon_agent()), "agent": users.agent_of(u, daemon_agent()), "projects": count.get(n, 0)} for n, u in us.items()]
    gone = [{"name": o, "projects": c} for o, c in count.items() if o and o not in us]
    return {"users": rows, "removed": gone, "admins": sum(1 for r in rows if r["admin"])}


def serve(port=8800, host="127.0.0.1", content: Path = None, upload_max: int = 20 * 2 ** 30, ready=None):
    if not users.enabled(): raise SystemExit(f"[hub] no users yet ({users.users_file()}): gameanything hub user add <name> --admin")
    hub = Hub(upload_max, content)
    from .. import decisions
    decisions.serve_signing()                         # this process alone signs her decisions (the key lives only in its memory)
    try: srv = _Server((host, port), hub_handler(hub))
    except OSError as e: raise SystemExit(f"[hub] cannot listen on {host}:{port}: {e}")
    shown = "127.0.0.1" if host in ("127.0.0.1", "localhost") else host
    print(f"[hub] users: {users.users_file()}\n[hub] open http://{shown}:{srv.server_port}/  "
          + ("(this machine only)" if host in ("127.0.0.1", "localhost") else "(reachable from the network: logins are app-level only, everyone on the server is root)")
          + "; Ctrl-C to stop", flush=True)
    if ready: ready(srv)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
