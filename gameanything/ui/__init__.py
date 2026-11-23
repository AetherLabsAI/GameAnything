"""Local browser UI (the user's confirmation points): `gameanything ui --project <dir>`.

A small stdlib HTTP server bound to 127.0.0.1. `/` is the conversation shell (static/shell.html + shell.js: sidebar, the project conversation
with cards, and the workspace iframe); the workspace pages are the single-page app at /app (or `/?embed=1`; static/app.html: 素材, 这一天,
人物, 方案, 试玩, 带回家, hash routes). The conversation is conversation/thread.jsonl (see ../conversation.py; /api/thread, /api/thread/answer,
/api/agent, /conv/<file>); the user's words are copied to feedback/answers.md by `gameanything chat read`; the older one-purpose pages stay at /tag-old (people tagging; /tag opens the workspace screen #people/tag), /looks-old and /play-old. It serves the project's derived
images and writes only inside the project: 3_remember/people.yaml (names, roles, groups, persona choices, merges), 3_remember/tags.yaml
(who is in which box of which photo), 4_design/art/ (look recipes, review), 5_build/<m>/play/ (play feedback), conversation/ (the thread, attachments, frames), feedback/ (board and
plan reviews, requests to the agent, ui_edits.jsonl: one line per save, so the user's edits stay on record as feedback) and
0_inbox/ (uploaded files). Every people save keeps the previous people.yaml under 3_remember/.history/. Nothing leaves the machine unless the user turned on a backup.
Above one project (manage.py): the project list and switching (/api/projects*), export / import jobs (/api/export*, /api/import*, /exports/<zip> with Range;
import zips arrive through the same chunked upload with X-Upload-Target: import), and the backup settings and scheduler (/api/backup*; enabling needs the page's Origin and an ack).
First run (onboard.py): with no project yet the server still starts and the shell shows the welcome page (/api/welcome, its examples at
/example/<i>/image|video and /examples/<still>.svg) and the new-project wizard (/api/onboard/games: the per-game check from native.doctor());
only the routes in NO_PROJECT_* answer then. In a project, /api/shell carries `flow` (the stepper) and `coach_seen` (config/ui.yaml, /api/coach).
Every tab is bound to its own project (Local below): pages live at /p/<project id>/ and every request under that prefix is answered for
that project, so two tabs on one server never mix (the hub's mechanism). The server's "current" project is only where "/" redirects to
(and what an unprefixed script call such as curl /api/thread answers for); opening a project in one tab never changes another tab.
"""
import hmac
import io
import json
import mimetypes
import os
import shutil
import re
import secrets
import socketserver
import sys
import threading
from datetime import datetime
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import yaml

from .. import layout, projects, status
from ..conversation import CardError, Thread
from ..translate import Tr, localize
from . import onboard, screens
from .home import home_state
from .i18n import T, err, lang_of, scrub_paths
from .manage import Current, Manager
from .upload import ALLOWED as UPLOAD_ALLOWED, Inbox, UploadError

STATIC = Path(__file__).parent / "static"
BACKUP_EVERY = 300      # seconds
MAX_JSON = 64 << 20     # largest JSON body a POST may send (a play comment carries one PNG frame)
MAX_FRAME = 12 << 20    # largest decoded PNG frame a play comment may carry
MILESTONE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
LOOK_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,79}(@[A-Za-z0-9_-]{1,40})?$")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff",
                    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                                               "img-src 'self' data: blob:; media-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' ws: wss:; "
                                               "frame-src 'self'; frame-ancestors 'self'; object-src 'none'; base-uri 'self'; form-action 'self'"}
def decode_png(data_url) -> bytes:
    """A play frame: a PNG data URL -> its bytes (PNG magic and MAX_FRAME checked)."""
    import base64, binascii
    pre = "data:image/png;base64,"
    if not isinstance(data_url, str) or not data_url.startswith(pre) or len(data_url) > (MAX_FRAME * 4) // 3 + len(pre) + 8: raise ValueError("画面格式不对")
    try: b = base64.b64decode(data_url[len(pre):], validate=True)
    except (binascii.Error, ValueError): raise ValueError("画面格式不对")
    if not b.startswith(PNG_MAGIC) or len(b) > MAX_FRAME: raise ValueError("画面格式不对")
    return b
HEADER = """# 人物名单（GameAnything）。最初由 synthesize 按外观归并生成；之后由你在 `gameanything ui` 里编辑（名字、分组、要不要做成游戏角色）。
# 你在界面里的每次保存都记在 feedback/ui_edits.jsonl；上一版保存在 3_remember/.history/。
# role_guess / basis / confidence 是推测；name、role、confirmed_by: user 是你确认过的。
"""


# what answers while no project is open (the welcome page and the wizard); anything else says {no_project: true}
NO_PROJECT_GET = {"/", "/shell.js", "/i18n.js", "/manage.js", "/tag.js", "/onboard.js", "/app.css", "/app.js", "/fonts/inter-latin-wght-normal.woff2",
                  "/api/shell", "/api/welcome", "/api/projects", "/api/settings", "/api/onboard/games", "/api/import"}
# POSTs that put HER decision in the ledger (decisions.py): only from the page itself. They need the page's Origin and the per-server decision
# cookie the server sets on the page it serves to a browser (an HttpOnly SameSite=Strict cookie, in memory only, new at every start), so a
# script on this machine (an agent's curl) is refused (QA 2026-10-30: a POST without Origin confirmed the mapping in her name).
DECISION_POST = {"/api/board_review", "/api/plan_review", "/api/adaptation_review", "/api/gameplay_review", "/api/feature_review",
                 "/api/thread/answer", "/api/save"}
DECISION_REFUSED = "这一步要她自己在页面上点：请刷新页面再点一次（页面以外的请求不算她的确认）"
NO_PROJECT_POST = {"/api/projects/new", "/api/projects/open", "/api/settings", "/api/import/start"}
PREFIX = re.compile(r"^/p/([A-Za-z0-9_.-]+)(/.*)?$")
# the page's own fetch / XHR calls to "/..." go to window.M2W_BASE + "/..." (the project the page is bound to: /p/<id>); the hub uses it too
BASE_PATCH = ("(function(){function fx(u){var B=window.M2W_BASE;return B&&typeof u===\"string\"&&u.charAt(0)===\"/\"&&u.charAt(1)!==\"/\"&&"
              "u.indexOf(B+\"/\")!==0?B+u:u}var f=window.fetch;window.fetch=function(u,o){return f.call(window,fx(u),o)};"
              "var op=XMLHttpRequest.prototype.open;XMLHttpRequest.prototype.open=function(m,u){var a=[].slice.call(arguments);a[1]=fx(u);return op.apply(this,a)}})();")


class Project:
    def __init__(self, root: Path, content: Path = None, upload_max: int = 20 * 2 ** 30):
        self.root = root.resolve(); self.lock = threading.Lock(); self.content = content
        self.inbox = Inbox(self.root, upload_max); self.upload_max = upload_max; self.up_locks = {}; self.up_guard = threading.Lock()
        self.thread = Thread(self.root); self.rem = self.root / layout.REMEMBER; self.art = self.root / layout.DESIGN / "art"
        self.local = threading.local()            # the hub (ui/hub.py) sets local.who = {author, author_name} for the request this thread serves

    def who(self) -> dict:
        return dict(getattr(self.local, "who", None) or {})

    def _yaml(self, p, default):
        return (yaml.safe_load(p.read_text(encoding="utf-8")) or default) if p.exists() else default

    def state(self):
        pack = self._yaml(layout.pack(self.root), {"items": []})
        board = self._yaml(self.rem / "board.yaml", {}).get("experience_board", {})
        ppl = self._yaml(self.rem / "people.yaml", {})
        tags = self._yaml(self.rem / "tags.yaml", {}).get("tags", [])
        photos = []
        for it in pack["items"]:
            if it["kind"] != "photo": continue
            d = it.get("derived") or {}
            det = json.loads((self.root / d["persons"]).read_text(encoding="utf-8")) if d.get("persons") and (self.root / d["persons"]).exists() else {}
            photos.append({"id": it["id"], "image": "/media/" + d["image"], "thumb": "/media/" + d["thumb"],
                           "boxes": det.get("boxes", []), "show_threshold": det.get("show_threshold", 0.75),
                           "third_party": False})
        segs = [{"id": s["id"], "label": f"{s.get('time', '')} {s.get('what', '')}".strip(), "items": s.get("items", [])}
                for s in board.get("skeleton", [])]
        cfg = status.project_config(self.root)
        return {"rev": self.rev(), "title": cfg.get("title") or self.root.name, "lang": cfg.get("lang", "en"), "segments": segs, "photos": photos,
                "people": ppl.get("people", []), "groups": ppl.get("groups", []), "tags": tags}

    def rev(self) -> str:
        """Version of the files the page edits; a page holding an older version may not overwrite newer edits."""
        return ";".join(str(int(f.stat().st_mtime_ns)) if f.exists() else "-" for f in (self.rem / "people.yaml", self.rem / "tags.yaml"))

    def save(self, data):
        with self.lock:
            if data.get("rev") != self.rev():
                return {"ok": False, "stale": True, "error": "这个页面打开后，文件被别处改过了：请刷新页面再改（刷新前没保存的改动会丢）"}
            pf = self.rem / "people.yaml"
            old = self._yaml(pf, {})
            if pf.exists():                                   # keep a previous version, at most one every BACKUP_EVERY (autosave is frequent)
                h = self.rem / ".history"; h.mkdir(exist_ok=True)
                last = max((f.stat().st_mtime for f in h.glob("people-*.yaml")), default=0)
                if datetime.now().timestamp() - last >= BACKUP_EVERY:
                    shutil.copy2(pf, h / f"people-{datetime.now():%Y%m%d-%H%M%S}.yaml")
            byid = {p["id"]: p for p in old.get("people", [])}
            people = []
            for p in data["people"]:                          # keep fields the UI does not edit (basis, looks, members ...)
                people.append({**byid.get(p["id"], {}), **p})
            merged = old.get("merged", []) + data.get("merged", [])
            out = {"people": people, "groups": data["groups"], **({"merged": merged} if merged else {}),
                   **({"crowds": old["crowds"]} if old.get("crowds") else {})}
            pf.write_text(HEADER + yaml.safe_dump(out, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
            (self.rem / "tags.yaml").write_text(
                "# 谁在哪张照片的哪个框里（gameanything ui）。box = [x0, y0, x1, y1]，0-1，左上角为原点；source: detector = 本地检测框，user = 你画的框\n"
                + yaml.safe_dump({"tags": data["tags"]}, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
            fb = self.root / layout.FEEDBACK; fb.mkdir(exist_ok=True)
            with open(fb / "ui_edits.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "people": len(people),
                                    "named": sum(1 for p in people if p.get("name")), "groups": len(data["groups"]),
                                    "tags": len(data["tags"]), "merged": data.get("merged", []), "note": data.get("note", "")},
                                   ensure_ascii=False) + "\n")
            from .. import decisions
            decisions.record(self.root, "people", "confirmed", via="ui people")      # she saved the people / tags page (decisions.py)
            status.write(self.root)
            return {"ok": True, "at": datetime.now().strftime("%H:%M:%S"), "rev": self.rev()}

    def add_person(self, d):
        """The 人物 page's 「加一个人」: someone she names by hand (she declined photo detection, or the photos miss them; QA2 2026-10-30).
        Appended to people.yaml with source: user (the agent keeps it), and the agent hears it in the chat."""
        name = str(d.get("name") or "").strip()[:60]; role = str(d.get("role") or "").strip()[:60]
        if not name: raise ValueError("请写一个名字")
        with self.lock:
            pf = self.rem / "people.yaml"
            try: old = yaml.safe_load(pf.read_text(encoding="utf-8")) if pf.exists() else {}
            except yaml.YAMLError: raise ValueError("3_remember/people.yaml 现在读不出来：请 agent 先改好它")
            old = old if isinstance(old, dict) else {}
            ppl = [p for p in (old.get("people") or []) if isinstance(p, dict)] if isinstance(old.get("people"), list) else []
            if any(str(p.get("name") or "").strip() == name for p in ppl): raise ValueError(f"已经有「{name}」了")
            ids = {str(p.get("id")) for p in ppl}; n = len(ppl) + 1
            while f"p_user{n}" in ids: n += 1
            ppl.append({"id": f"p_user{n}", "name": name, **({"role": role} if role else {}), "source": "user"})
            self.rem.mkdir(parents=True, exist_ok=True)
            pf.write_text(HEADER + yaml.safe_dump({**old, "people": ppl}, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
            self.tell(f"在「人物」页加了一个人：{name}" + (f"（{role}）" if role else ""), f"Added a person on the People page: {name}" + (f" ({role})" if role else ""), None, auto=True)
            return {"ok": True, "id": f"p_user{n}"}

    # ---- look review page (4_design/art) ----
    def looks_rev(self):
        f = self.art / "looks.yaml"; return str(int(f.stat().st_mtime_ns)) if f.exists() else "-"

    def looks_state(self, lang="zh"):
        from ..worlds.stardew.art import sprites
        tr = Tr(self.root, lang)
        looks = self._yaml(self.art / "looks.yaml", {}); ppl = {p["id"]: p for p in self._yaml(self.rem / "people.yaml", {}).get("people", []) if isinstance(p, dict) and p.get("id")}
        groups = self._yaml(self.rem / "people.yaml", {}).get("groups", []); review = self._yaml(self.art / "review.yaml", {})
        v = lambda f: f"?v={int(f.stat().st_mtime)}" if f.exists() else ""
        ppl = {k: p for k, p in ppl.items() if isinstance(p, dict)}
        looks = looks if isinstance(looks, dict) else {}; groups = [g for g in groups if isinstance(g, dict)] if isinstance(groups, list) else []
        def persona(p):                                  # a dict (npc / presence / note); an agent's one-line string is shown as its note
            pr = p.get("persona")
            if isinstance(pr, str): return {"note": tr(pr)} if pr.strip() else None
            if isinstance(pr, dict): return {**pr, "note": tr(pr.get("note"))} if pr.get("note") else pr
            return None
        out = []
        for pid, lk in looks.items():
            base, _, variant = pid.partition("@")                # "<person>@license" = that person's licence-day look
            p = ppl.get(base, {}); w = self.art / "walk" / f"{pid}.png"; ph = self.art / "portrait_inputs" / f"{pid}_photo.jpg"
            if variant and not ph.exists(): ph = self.art / "license_refs" / f"{base}_full.jpg"
            pts = sorted(self.art.glob(f"portraits/{base}_*.png"))
            order = ["neutral", "happy", "laugh", "touched", "surprised", "shy"]
            pts.sort(key=lambda f: order.index(f.stem[len(base) + 1:]) if f.stem[len(base) + 1:] in order else 99)
            pn = tr((p.get("name") or base).replace("（请柬署名）", ""))
            vl = {"license": T(lang, "领证那天")}.get(variant, variant)
            nm = pn + (f" ({vl})" if lang == "en" else f"（{vl}）") * bool(variant)
            face = next((f for f in (self.art / "portrait_inputs" / f"{pid}_photo.jpg", self.art / "license_refs" / f"{base}_head.jpg",
                                     self.art / "license_refs" / f"{base}_full.jpg") if f.exists()), None)
            out.append({"id": pid, "base": base, "variant": variant, "role": tr(p.get("role") or p.get("role_guess")), "person_name": pn,
                        "face": (f"/art/{face.relative_to(self.art).as_posix()}{v(face)}" if face else None), "name": nm, "persona": persona(p),
                        "groups": [tr(g["name"]) for g in groups if base in (g.get("members") or [])], "look": lk,
                        "walk": f"/art/walk/{pid}.png{v(w)}" if w.exists() else None, "photo": f"/art/portrait_inputs/{pid}_photo.jpg{v(ph)}" if ph.exists() else None,
                        "portraits": [{"expr": f.stem[len(base) + 1:], "url": f"/art/portraits/{f.name}{v(f)}"} for f in pts],
                        "review": review.get(pid, {"status": "todo"})})
        # everyone the project knows (people.yaml), also those without a game look yet: the same people as 这一天 counts (QA 2026-10-29)
        have = {o["base"] for o in out}
        for pid, p in ppl.items():
            if pid in have: continue
            face = next((f for f in (self.art / "portrait_inputs" / f"{pid}_photo.jpg", self.art / "license_refs" / f"{pid}_head.jpg") if f.exists()), None)
            pn = tr((p.get("name") or pid).replace("（请柬署名）", ""))
            out.append({"id": pid, "base": pid, "variant": "", "role": tr(p.get("role") or p.get("role_guess")), "person_name": pn, "name": pn,
                        "face": (f"/art/{face.relative_to(self.art).as_posix()}{v(face)}" if face else None), "persona": persona(p),
                        "groups": [tr(g["name"]) for g in groups if pid in (g.get("members") or [])], "look": None, "no_look": True,
                        "walk": None, "photo": None, "portraits": [], "review": {"status": "none"}})
        V = sprites.villagers()
        bases = {k: {"fit": x.get("fit", {}), "materials": sorted({(m if isinstance(m, str) else mm[0]) for c, m in x["colors"].items()
                                                                   for mm in ([m] if isinstance(m, str) else m)} if isinstance(x, dict) else set())}
                 for k, x in V.items()}
        return {"rev": self.looks_rev(), "people": out, "bases": bases, "accessories": ["glasses", "veil"],
                "groups": [{"id": g.get("id"), "name": tr(g["name"]), "members": g.get("members") or []} for g in groups]}

    def save_look(self, data):
        from ..worlds.stardew.art import sprites
        with self.lock:
            if data.get("rev") != self.looks_rev():
                return {"ok": False, "stale": True, "error": "外观配方在别处被改过了：请刷新页面再改"}
            f = self.art / "looks.yaml"; looks = self._yaml(f, {}); pid = data.get("id")
            if not isinstance(pid, str) or not LOOK_ID_RE.match(pid): raise ValueError("没有这个人")
            look = {k: v for k, v in data["look"].items() if v not in (None, "", [], {})}
            img = sprites.build(self.content, look)                       # build first: a bad recipe never gets saved
            looks[pid] = look
            f.write_text("# 行走图的外观配方（GameAnything；也可以在“形象确认”页里改）。upper/lower = 用哪个原版村民的上 / 下半身，cut = 帧内第几行切开，\n"
                         "# colors = 每种材质的颜色，contrast = 明暗反差，accessories = 配件。\n" + yaml.safe_dump(looks, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
            (self.art / "walk").mkdir(exist_ok=True); img.save(self.art / "walk" / f"{pid}.png")
            self.feedback({"type": "look_edit", "id": pid, "look": look})
            if str(data.get("note") or "").strip():
                self.tell(str(data["note"]).strip(), ctx=[{"kind": "person", "id": pid, "label": self.thread.lookup()["people"].get(pid) or pid}])
            return {"ok": True, "rev": self.looks_rev(), "walk": f"/art/walk/{pid}.png?v={int(datetime.now().timestamp() * 1000)}"}

    def review(self, data):
        with self.lock:
            f = self.art / "review.yaml"; r = self._yaml(f, {}); pid = data["id"]
            e = {"status": data.get("status", "todo"), "note": data.get("note", ""), "at": datetime.now().isoformat(timespec="seconds")}
            if data.get("portrait_request"): e["portrait_request"] = {"note": data.get("note", ""), "expressions": data.get("expressions") or ["neutral"], "state": "pending"}
            elif (r.get(pid) or {}).get("portrait_request", {}).get("state") == "pending": e["portrait_request"] = r[pid]["portrait_request"]
            old = r.get(pid) or {}; r[pid] = e
            f.write_text("# 形象确认的状态（gameanything ui）：todo 待看 / ok 满意 / change 要改；portrait_request 是请 GameAnything 重新生成头像的请求\n"
                         + yaml.safe_dump(r, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
            self.feedback({"type": "portrait_request" if data.get("portrait_request") else "review", "id": pid, **e})
            self._tell_look(pid, old, e, data.get("portrait_request"))
            return {"ok": True}

    def _tell_look(self, pid, old, e, redo):
        name = self.thread.lookup()["people"].get(pid) or pid; ctx = [{"kind": "person", "id": pid, "label": name}]; note = (e.get("note") or "").strip()
        if redo: self.tell(f"请求按意见重画《{name}》的头像", f"Asked for a redraw of {name}'s portrait", ctx, auto=True)
        elif e["status"] != old.get("status") and e["status"] in ("ok", "change"):
            zh, en = ("满意", "satisfied") if e["status"] == "ok" else ("要改", "needs changes")
            self.tell(f"把《{name}》的形象标成了{zh}", f"Marked {name}'s look as {en}", ctx, auto=True)
        if note and note != (old.get("note") or "").strip(): self.tell(note, ctx=ctx)

    # ---- conversation (conversation.py; the session reads the same files) ----
    def say(self, d):
        from ..conversation import check_length
        check_length(d.get("text"))                     # before anything is saved (a frame of the play video)
        ctx = []
        for c in d.get("context") or []:
            if not isinstance(c, dict) or c.get("kind") not in ("moment", "person", "video", "file"): raise CardError("context 里有不认识的东西")
            if c.get("kind") == "file" and not self.inside(c.get("path")): raise CardError("context 里的文件不在这个项目里")
            if c.get("kind") == "video" and c.get("m") not in (None, "") and not (isinstance(c.get("m"), str) and MILESTONE_RE.match(c["m"])): raise CardError("context 里有不认识的东西")
            c = {k: v for k, v in c.items() if k != "frame_data"} | ({"frame": self.thread.save_frame(c["frame_data"])} if c.get("frame_data") else {})
            ctx.append(c)
        for a in d.get("attachments") or []:                                  # chunked uploads: the path is inside 0_inbox
            p = (self.inbox.dir / str(a)).resolve()
            if self.inbox.dir.resolve() not in p.parents or not p.is_file(): raise CardError(f"找不到附件 {a}")
            ctx.append({"kind": "file", "path": f"{layout.INBOX}/{p.relative_to(self.inbox.dir.resolve()).as_posix()}"})
        with self.lock: ev = self.thread.user_text(d.get("text"), ctx, **self.who())
        return {"ok": True, "event": ev}

    def inside(self, rel) -> bool:
        """rel is a relative path of a file inside this project."""
        if not isinstance(rel, str) or not rel or rel.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", rel) or "\x00" in rel: return False
        p = (self.root / rel).resolve()
        return self.root in p.parents and p.is_file()

    def tell(self, text, en=None, ctx=None, auto=False):
        """Mirror a feedback POST into the thread so `gameanything chat wait` wakes (caller holds self.lock). A real note goes in verbatim; auto=True is a line
        built from a verdict (flagged, never copied to answers.md). Never fails the save itself."""
        try: self.thread.user_text(text, ctx or None, auto=auto, text_en=en, **self.who())
        except (CardError, OSError): pass

    def answer(self, d):
        with self.lock: return {"ok": True, "event": self.thread.answer(d.get("card_id"), d.get("answer"), **self.who())}

    def thread_state(self, after=None, lang="zh"):
        evs = self.thread.events()
        try: build = screens.build_banner(self.root, lang, evs)
        except Exception: build = []                        # a half-written world_plan.yaml never breaks the chat
        ids = [e["id"] for e in evs]; new = evs[ids.index(after) + 1:] if after in ids else evs        # one read of the log per poll
        return {"events": localize(new, self.root, lang), "agent": self.thread.online(evs), "build": build}

    def feedback_ui(self, entry):
        fb = self.root / layout.FEEDBACK; fb.mkdir(exist_ok=True)
        with open(fb / "ui_edits.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), **entry}, ensure_ascii=False) + "\n")

    def upload_lock(self, uid):
        with self.up_guard: return self.up_locks.setdefault(uid, threading.Lock())

    def feedback(self, entry):
        fb = self.root / layout.FEEDBACK; fb.mkdir(exist_ok=True)
        with open(fb / "art_feedback.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), **entry}, ensure_ascii=False) + "\n")

    # ---- play & check page (5_build/<milestone>/play) ----
    def builds(self):
        return screens.Data(self.root).play_builds()             # play.yaml or only a video; oldest first, the default is the newest

    def milestone(self, m) -> str:
        """A milestone id from the page: one of this project's play builds (5_build/<m>/play), never a path. -> m; ValueError otherwise."""
        m = m if isinstance(m, str) else ""
        if not MILESTONE_RE.match(m) or m not in self.builds(): raise ValueError("没有这一版")
        B = (self.root / "5_build").resolve(); D = (B / m / "play").resolve()
        if D.parent.parent != B or not D.is_dir(): raise ValueError("没有这一版")
        return m

    def kind_ok(self, k) -> bool:
        """The hub's 「评论」 role only adds words: notes on the video / a picture, never a verdict (hub.py sets local.role)."""
        return getattr(self.local, "role", None) != "comment" or k not in DECIDING_PLAY_KINDS

    def play_state(self, m, lang="zh"):
        if m: m = self.milestone(m)
        tr = Tr(self.root, lang); D = self.root / "5_build" / m / "play" if m else None
        d = screens.Data(self.root, lang)
        play = d.play(m, lang); board = self._yaml(self.rem / "board.yaml", {}).get("experience_board", {})
        mine = self._yaml(D / "user_review.yaml", {"moments": {}, "checks": {}, "sounds": {}, "notes": []}) if D else {"moments": {}, "checks": {}, "sounds": {}, "notes": []}
        req = self._yaml(D / "next_round_request.yaml", None) if D else None
        if tr.on:                                                        # the shown parts of play.yaml; scenes / references are not shown
            play = {**play, "chapters": [{**c, "title": tr(c.get("title"))} for c in play.get("chapters") or []],
                    "checks": [{**c, "item": tr(c.get("item")), "note": tr(c.get("note"))} for c in play.get("checks") or []],
                    "sounds": [{**c, "used_for": tr(c.get("used_for")), "note": tr(c.get("note"))} for c in play.get("sounds") or []]}
        return {"milestones": self.builds(), "m": m, "play": play, "base": f"/build/{m}/", "review": mine, "next_round": req,
                "moment_titles": {x["id"]: tr(x["title"]) for x in board.get("moments", [])},
                "game_by_moment": {k: v["url"] for k, v in d.scene_map().items()},     # newest delivered screenshot per moment (any build)
                "real_by_moment": {x["id"]: d.moment_image(x, True) for x in board.get("moments", [])}}

    def play_feedback(self, data):
        with self.lock:
            m = self.milestone(data.get("m")); D = self.root / "5_build" / m / "play"; f = D / "user_review.yaml"
            if not self.kind_ok(data.get("kind")): raise Denied("评论权限只能留言，不能下判断：申请编辑权限后才能标满意 / 要改")
            r = self._yaml(f, {"moments": {}, "checks": {}, "sounds": {}, "notes": []})
            at = datetime.now().isoformat(timespec="seconds"); k = data["kind"]
            e = {"at": at, **{x: data[x] for x in ("status", "note", "t", "box", "moment", "verdict", "id") if data.get(x) not in (None, "")}}
            if data.get("frame"):                                 # a frame grabbed from the video where the user commented
                png = decode_png(data["frame"])
                fr = self.root / layout.FEEDBACK / "frames"; fr.mkdir(parents=True, exist_ok=True)
                name = f"{m}_{at.replace(':', '')}.png"; out = (fr / name).resolve()
                if out.parent != fr.resolve(): raise ValueError("画面格式不对")
                out.write_bytes(png)
                e["frame"] = f"feedback/frames/{name}"
            prev = {}
            if k == "moment": prev = r["moments"].get(data["moment"]) or {}
            elif k == "check": prev = r["checks"].get(data["id"]) or {}
            elif k == "sound": prev = r["sounds"].get(data["id"]) or {}
            if k == "all_ok":                                     # "这一版可以了": every moment without a verdict -> ok, one thread line
                todo = [x for x in data.get("moments") or [] if not (r["moments"].get(x) or {}).get("status")]
                for x in todo: r["moments"][x] = {"at": at, "status": "ok"}
            elif k == "moment": r["moments"][data["moment"]] = e
            elif k == "check": r["checks"][data["id"]] = e
            elif k == "sound": r["sounds"][data["id"]] = e
            else: r["notes"].append({**e, "kind": k})
            f.write_text("# 你在“试玩检查”页里的意见（gameanything ui）。moments：每个时刻的满意 / 要改；checks：改判；sounds：试听；notes：录像某一刻 / 截图上的留言\n"
                         + yaml.safe_dump(r, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
            self.feedback_build({"m": m, "kind": k, **{x: v for x, v in e.items() if x != "frame"}, **({"id": data["id"]} if data.get("id") else {}),
                                 **({"frame": e["frame"]} if e.get("frame") else {})})
            self._tell_play(m, k, data, e, prev, len(todo) if k == "all_ok" else 0)
            return {"ok": True, "review": r}

    def _tell_play(self, m, k, data, e, prev, n_ok=0):
        n = re.sub(r"\D", "", m) or m; ver, ver_en = f"第 {n} 版", f"round {n}"
        note = (e.get("note") or "").strip(); changed = note != (prev.get("note") or "").strip()
        titles = self.thread.lookup()["moments"]; mo = data.get("moment"); ctx = []
        if mo: ctx.append({"kind": "moment", "id": mo, "label": titles.get(mo) or mo})
        title = titles.get(mo) or mo or ""
        if k == "all_ok":
            if n_ok: self.tell(f"在{ver}里把 {n_ok} 个时刻都标成了满意", f"Marked {n_ok} moments in {ver_en} as satisfied", ctx, auto=True)
        elif k in ("time", "box"):
            if k == "time" and e.get("t") is not None: ctx.append({"kind": "video", "m": m, "t": e["t"], **({"frame": e["frame"]} if e.get("frame") else {})})
            if k == "box" and e.get("box"): ctx.append({"kind": "region", "m": m, "file": data.get("id"), "box": e["box"], "label": str(data.get("id") or "").split("/")[-1]})
            if note: self.tell(note, ctx=ctx)
        elif k == "moment":
            st = e.get("status")
            if st in ("ok", "change") and st != prev.get("status"):
                zh, en = ("满意", "satisfied") if st == "ok" else ("要改", "needs changes")
                self.tell(f"在{ver}里把《{title}》标成了{zh}", f"Marked “{title}” in {ver_en} as {en}", ctx, auto=True)
            if note and changed: self.tell(note, ctx=ctx)
        elif k == "check":
            item = next((c for c in screens.Data(self.root).play(m).get("checks") or [] if c.get("id") == data.get("id")), {})
            label = item.get("item") or data.get("id"); cctx = ctx + [{"kind": "check", "id": data.get("id"), "label": label}]
            v = e.get("verdict")
            if v and v != prev.get("verdict"):
                zh, en = {"ok": ("做到了", "done"), "partial": ("部分做到", "partly done"), "no": ("没做到", "not done"), "unknown": ("没法确认", "can't tell")}.get(v, (v, v))
                self.tell(f"在{ver}里把检查《{label}》改判为“{zh}”", f"Changed the verdict of check “{label}” in {ver_en} to “{en}”", cctx, auto=True)
            if note and changed: self.tell(note, ctx=cctx)
        elif k == "sound":
            st = e.get("status"); f = str(data.get("id") or "").split("/")[-1]; sctx = [{"kind": "file", "path": f"5_build/{m}/play/{data.get('id')}"}]
            if st in ("ok", "change") and st != prev.get("status"):
                zh, en = ("没问题", "sounds fine") if st == "ok" else ("听着不对", "sounds wrong")
                self.tell(f"在{ver}里把声音 {f} 标成了{zh}", f"Marked sound {f} in {ver_en} as {en}", sctx, auto=True)
            if note and changed: self.tell(note, ctx=sctx)

    def next_round(self, data):
        with self.lock:
            m = self.milestone(data.get("m")); D = self.root / "5_build" / m / "play"
            req = {"state": "pending", "at": datetime.now().isoformat(timespec="seconds"), "from_milestone": m,
                   "items": data.get("items", []), "note": data.get("note", "")}
            (D / "next_round_request.yaml").write_text("# 用户点了“按这些意见改”：GameAnything 会把这些意见写成下一轮的修改要求（state: pending → started → done）\n"
                                                       + yaml.safe_dump(req, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
            self.feedback_build({"m": m, "kind": "next_round", "items": len(req["items"])})
            k_ = len(req["items"]); n = re.sub(r"\D", "", m) or m
            self.tell(f"把第 {n} 版的 {k_} 条意见交给下一版（按意见做下一版）", f"Handed the {k_} notes on round {n} to the next round", None, auto=True)
            return {"ok": True, "next_round": req}

    def feedback_build(self, entry):
        fb = self.root / layout.FEEDBACK; fb.mkdir(exist_ok=True)
        with open(fb / "build_feedback.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), **entry}, ensure_ascii=False) + "\n")

    def build_file(self, rel: str) -> Path:
        B = (self.root / "5_build").resolve(); m, _, rest = rel.partition("/")
        p = (B / m / "play" / rest).resolve()
        if not str(p).startswith(str(B / m / "play") + os.sep) or not p.is_file(): raise FileNotFoundError(rel)
        return p

    def art_file(self, rel: str) -> Path:
        p = (self.art / rel).resolve()
        if not str(p).startswith(str(self.art.resolve()) + os.sep) or not p.is_file(): raise FileNotFoundError(rel)
        return p

    def media(self, rel: str) -> Path:
        p = layout.media_file(self.root, rel)
        if p is None: raise FileNotFoundError(rel)
        return p

    def crop(self, item: str, box) -> bytes:
        from PIL import Image
        p = self.media(f"{layout.INGEST}/derived/images/{item}.jpg")
        im = Image.open(p); W, H = im.size
        x0, y0, x1, y1 = [float(v) for v in box]
        pad = 0.04
        c = im.crop((max(0, (x0 - pad) * W), max(0, (y0 - pad / 2) * H), min(W, (x1 + pad) * W), min(H, (y0 + (y1 - y0) * 0.45) * H)))
        c.thumbnail((160, 160)); b = io.BytesIO(); c.convert("RGB").save(b, "JPEG", quality=85)
        return b.getvalue()


class Denied(Exception):
    """A POST the session user's role may not make (answered 403)."""


DECIDING_PLAY_KINDS = {"all_ok", "moment", "check", "sound"}       # play_feedback kinds that decide (a verdict), not only add words


def handler(proj_, mgr_: Manager):
    """The request handler class for one (Current, Manager): the project and the manager are class attributes, so a subclass (the hub,
    ui/hub.py) can bind them per request."""
    class H(BaseHTTPRequestHandler):
        proj, mgr = proj_, mgr_

        def log_message(self, *a): pass

        def agent_peer(self) -> bool:
            """Isolation on: the client is a process of an agent account (the kernel's socket table, not a header). It may load pages and
            media (curl /media/... before a card), never decide, never POST (docs/agent-isolation.md)."""
            v = getattr(self, "_agent_peer", None)
            if v is None:
                from .. import isolation
                v = self._agent_peer = isolation.peer_is_agent(self.client_address, self.server.server_port)
            return v

        def origin_ok(self) -> bool:
            """A POST comes from this page (or from a script without an Origin, e.g. curl on this machine)."""
            return self.headers.get("Origin") in (None, f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}")

        def inject(self, html: bytes) -> bytes:
            return html

        # ---- her decisions: only from the page (DECISION_POST)
        def decide_cookie(self) -> str: return f"ga_decide_{self.server.server_port}"

        def decide_token(self) -> str:
            return self.server.__dict__.setdefault("ga_decide_token", secrets.token_urlsafe(32))       # memory only, per server start

        def browser_page(self) -> bool:
            """A page a browser loads as a page (its Sec-Fetch-Dest), not a script's GET: only then does it get the decision cookie."""
            if self.agent_peer(): return False
            return self.headers.get("Sec-Fetch-Dest") in ("document", "iframe") and self.headers.get("Sec-Fetch-Site") in (None, "none", "same-origin")

        def decision_ok(self) -> bool:
            """A decision POST from this page: its Origin AND the decision cookie of this server start."""
            if self.agent_peer(): return False
            if self.headers.get("Origin") is None or not self.origin_ok(): return False
            try: c = SimpleCookie(); c.load(self.headers.get("Cookie") or "")
            except CookieError: return False
            v = c.get(self.decide_cookie())
            return v is not None and hmac.compare_digest(v.value.encode(), self.decide_token().encode())

        def end_headers(self):
            for k, v in SECURITY_HEADERS.items(): self.send_header(k, v)
            if getattr(self, "_decide_cookie", False):
                self._decide_cookie = False
                self.send_header("Set-Cookie", f"{self.decide_cookie()}={self.decide_token()}; HttpOnly; SameSite=Strict; Path=/")
            super().end_headers()

        def send(self, code, body: bytes, ctype):
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)

        def send_file(self, p: Path, download=False):
            """With HTTP Range support (browsers need it to seek in a video, a download to resume); streamed in 1 MB pieces."""
            size = p.stat().st_size; ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            a, b, code = 0, size - 1, 200
            rng = self.headers.get("Range")
            if rng and rng.startswith("bytes=") and "," not in rng:
                x, _, y = rng[6:].partition("-")
                try:
                    if x == "": a = max(0, size - int(y)); b = size - 1                  # "bytes=-N": the last N bytes
                    else: a = int(x); b = min(int(y) if y else size - 1, size - 1)
                except ValueError:
                    a, b = size, -1
                if a > b or a >= size:
                    self.send_response(416); self.send_header("Content-Range", f"bytes */{size}"); self.send_header("Content-Length", "0"); self.end_headers(); return
                code = 206
            self.send_response(code)
            if code == 206: self.send_header("Content-Range", f"bytes {a}-{b}/{size}")
            self.send_header("Content-Type", ctype); self.send_header("Accept-Ranges", "bytes"); self.send_header("Content-Length", str(b - a + 1))
            if download: self.send_header("Content-Disposition", f'attachment; filename="{p.name}"')
            self.send_header("Cache-Control", "no-store"); self.end_headers()
            try:
                with open(p, "rb") as f:
                    f.seek(a); left = b - a + 1
                    while left:
                        buf = f.read(min(1 << 20, left))
                        if not buf: break
                        self.wfile.write(buf); left -= len(buf)
            except (BrokenPipeError, ConnectionResetError):
                pass                                                                    # the browser stopped watching / seeked elsewhere

        def page(self, name):
            html = (STATIC / name).read_bytes()
            if self.browser_page(): self._decide_cookie = True
            if name in ("shell.html", "app.html") and self.proj.root:          # the language the UI starts in, before the user picks one (localStorage m2w.lang)
                html = html.replace(b'data-default-lang="zh"', f'data-default-lang="{screens.default_lang(self.proj.root)}"'.encode())
            return self.send(200, self.inject(html), "text/html; charset=utf-8")

        def ui_version(self):
            return max(int(f.stat().st_mtime) for f in STATIC.iterdir() if f.suffix in (".js", ".html", ".css"))   # the page asks to reload when this changes

        def lang(self):
            return lang_of(self.headers, parse_qs(urlparse(self.path).query))

        def json(self, obj, code=200):
            self.send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json")

        def fail(self, code, msg, **extra):
            """An error answer for the page, in the page's language (never with an absolute server path in it)."""
            self.json({"ok": False, "error": scrub_paths(err(msg, self.lang())), **extra}, code)

        def do_GET(self):
            u = urlparse(self.path)
            try:
                if u.path.startswith("/examples/"):                               # the bundled example stills
                    p = onboard.bundled_file(unquote(u.path[len("/examples/"):]))
                    return self.send(200, p.read_bytes(), "image/svg+xml" if p.suffix == ".svg" else mimetypes.guess_type(p.name)[0] or "application/octet-stream")
                if u.path.startswith("/kind_still/"):                             # the wizard's fixed picture of a project kind
                    f = onboard.kind_still_file(unquote(u.path[len("/kind_still/"):]))
                    if not f: raise FileNotFoundError(u.path)
                    return self.send_file(f)
                if u.path.startswith("/example/"):                                # /example/<i>/image|video: a file the welcome page's examples list
                    i, _, what = u.path[len("/example/"):].partition("/")
                    return self.send_file(self.mgr.example_file(int(i), what))
                if u.path == "/api/welcome":
                    return self.json(self.mgr.welcome(self.lang()))
                if u.path == "/api/onboard/games":
                    return self.json(self.mgr.games("force" in parse_qs(u.query)))
                if self.proj.p is None and u.path not in NO_PROJECT_GET and not (u.path == "/api/upload" and parse_qs(u.query).get("target") == ["import"]):
                    return self.json({"ok": False, "no_project": True, "error": err("还没有打开的项目", self.lang())}, 409)
                if u.path == "/api/shell" and self.proj.p is None:
                    return self.json({"no_project": True, "projects": self.mgr.project_list(self.lang()), "ui_version": self.ui_version(),
                                      "upload_allowed": sorted(UPLOAD_ALLOWED)})
                if u.path == "/app" or (u.path == "/" and "embed" in parse_qs(u.query)):       # the pages themselves (the shell embeds them)
                    return self.page("app.html")
                if u.path == "/":
                    return self.page("shell.html")
                if u.path in ("/shell.js", "/i18n.js", "/manage.js", "/tag.js", "/onboard.js"):
                    return self.send(200, (STATIC / u.path[1:]).read_bytes(), "text/javascript; charset=utf-8")
                if u.path == "/api/thread":
                    return self.json(self.proj.thread_state(parse_qs(u.query).get("after", [None])[0], self.lang()))
                if u.path == "/api/agent":
                    return self.json(self.proj.thread.online())
                if u.path == "/api/models":                                      # the chat page's 「对话 / 构建」 model chips (models.py)
                    from .. import models
                    return self.json(models.state(self.proj.root, self.models_ok()))
                if u.path.startswith("/conv/"):
                    p = self.proj.thread.file_path(unquote(u.path[len("/conv/"):]))
                    return self.send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream")
                if u.path == "/fonts/inter-latin-wght-normal.woff2":
                    return self.send(200, (STATIC / u.path[1:]).read_bytes(), "font/woff2")
                if u.path in ("/app.css", "/app.js"):                     # not mimetypes: on Windows it reads the registry (often text/plain for .js)
                    return self.send(200, (STATIC / u.path[1:]).read_bytes(), ("text/css" if u.path.endswith(".css") else "text/javascript") + "; charset=utf-8")
                if u.path in ("/people", "/looks", "/play", "/home"):                  # the old addresses open the new screens
                    om = (parse_qs(u.query).get("m") or [""])[0] if u.path == "/play" else ""
                    self.send_response(302); self.send_header("Location", "/#" + u.path[1:] + (("/" + om) if MILESTONE_RE.match(om) else ""))
                    self.send_header("Content-Length", "0"); self.end_headers(); return
                if u.path == "/home-old":
                    return self.page("home.html")
                if u.path == "/api/shell":
                    try: flow = onboard.flow_state(self.proj.root)
                    except Exception: flow = None                                  # a half-written file never breaks the page
                    try: base = screens.shell(self.proj.root, self.lang())
                    except Exception as x:                                         # the sidebar and the chat stay up whatever file is broken (QA2 2026-10-30)
                        try: sys.stderr.write(f"[ui] /api/shell: {type(x).__name__}: {x}\n")
                        except Exception: pass
                        base = screens.shell_min(self.proj.root, self.lang())
                    bad = [{"file": f, "problem": m} for f, m in self.bad_files()[:8]]       # the page lists them (shell.js renderBadFiles)
                    return self.json({**base, **self.mgr.shell_extra(self.lang()), "flow": flow, "ui_version": self.ui_version(), "bad_files": bad,
                                      "upload_allowed": sorted(UPLOAD_ALLOWED)})                  # the wizard checks files before it uploads them
                if u.path == "/api/projects":
                    return self.json({"projects": self.mgr.project_list(self.lang())})
                if u.path == "/api/settings":
                    return self.json(self.mgr.settings())
                if u.path == "/api/export":
                    return self.json(self.mgr.job(parse_qs(u.query).get("id", [""])[0], self.lang()))
                if u.path == "/api/import":
                    return self.json(self.mgr.job(parse_qs(u.query).get("id", [""])[0], self.lang()))
                if u.path == "/api/backup":
                    return self.json(self.mgr.backup_panel(self.lang()))
                if u.path.startswith("/exports/"):
                    return self.send_file(self.mgr.export_file(u.path[len("/exports/"):]), download=True)
                if u.path == "/api/day":
                    return self.json(screens.day(self.proj.root, self.lang()))
                if u.path == "/api/gather":
                    return self.json(screens.gather(self.proj.root, self.proj.inbox, self.proj.upload_max, self.lang()))
                if u.path == "/api/board":
                    return self.json(screens.board_state(self.proj.root, self.lang()))
                if u.path == "/api/adaptation":
                    return self.json(screens.adaptation_state(self.proj.root, self.lang()))
                if u.path == "/api/feature":
                    return self.json(screens.feature_state(self.proj.root, self.lang()))
                if u.path == "/api/gameplay":
                    return self.json(screens.gameplay_state(self.proj.root, self.lang()))
                if u.path == "/api/balance":
                    return self.json(screens.balance_state(self.proj.root, parse_qs(u.query).get("m", [None])[0], self.lang()))
                if u.path == "/api/plan":
                    return self.json(screens.plan_state(self.proj.root, self.lang()))
                if u.path == "/api/now":                                         # 工作台: what the background build does right now (live.py)
                    from .. import live as _live
                    return self.json(_live.now_state(self.proj.root, self.lang()))
                if u.path == "/live" or u.path.startswith("/live/"):            # the game picture, only after her yes (liveview.py; view only)
                    from .. import liveview
                    liveview.serve(self, self.proj.root, u.path[len("/live"):]); return
                if u.path == "/api/devstatus":                                   # 开发状态 (5_build/STATUS.yaml), read only
                    return self.json(screens.devstatus_state(self.proj.root, self.lang()))
                if u.path == "/api/feedback":                                    # 开发状态's 「反馈和改进」: her feedback records + the loop's metrics (feedback.py)
                    return self.json(screens.feedback_state(self.proj.root, self.lang(), owner=self.profile_ok()))
                if u.path == "/api/profile":                                     # 我的偏好: the owner's private preference profile (profile.py)
                    if not self.profile_ok(): return self.fail(403, "只有项目的所有者能看自己的偏好")
                    return self.json(screens.profile_state(self.proj.root, self.lang()))
                if u.path == "/api/upload":
                    q = parse_qs(u.query)
                    return self.json((self.mgr.imports if q.get("target") == ["import"] else self.proj.inbox).status(q.get("id", [""])[0]))
                if u.path == "/api/home":
                    return self.send(200, json.dumps(home_state(self.proj.root, self.lang()), ensure_ascii=False).encode(), "application/json")
                if u.path == "/design4":
                    return self.send(200, (STATIC / "design4.html").read_bytes(), "text/html; charset=utf-8")
                if u.path == "/design3":
                    return self.send(200, (STATIC / "design3.html").read_bytes(), "text/html; charset=utf-8")
                if u.path == "/design":
                    return self.send(200, (STATIC / "design.html").read_bytes(), "text/html; charset=utf-8")
                if u.path in ("/tag", "/index.html"):                                  # the tagging tool is a workspace screen now
                    self.send_response(302); self.send_header("Location", "/#people/tag"); self.send_header("Content-Length", "0"); self.end_headers(); return
                if u.path == "/tag-old":
                    return self.page("index.html")
                if u.path == "/play-old":
                    return self.page("play.html")
                if u.path == "/api/play":
                    q = parse_qs(u.query); ms = self.proj.builds(); m = (q.get("m") or [ms[-1] if ms else ""])[0]
                    return self.send(200, json.dumps(self.proj.play_state(m, self.lang()), ensure_ascii=False).encode(), "application/json")
                if u.path.startswith("/build/"):
                    return self.send_file(self.proj.build_file(unquote(u.path[len("/build/"):])))
                if u.path == "/looks-old":
                    return self.page("looks.html")
                if u.path == "/api/looks":
                    return self.send(200, json.dumps(self.proj.looks_state(self.lang()), ensure_ascii=False).encode(), "application/json")
                if u.path.startswith("/art/"):
                    p = self.proj.art_file(unquote(u.path[len("/art/"):]))
                    return self.send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream")
                if u.path == "/api/state":
                    return self.send(200, json.dumps(self.proj.state(), ensure_ascii=False).encode(), "application/json")
                if u.path.startswith("/media/"):
                    p = self.proj.media(unquote(u.path[len("/media/"):]))
                    return self.send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream")
                if u.path == "/crop":
                    q = parse_qs(u.query)
                    return self.send(200, self.proj.crop(q["item"][0], q["box"][0].split(",")), "image/jpeg")
            except UploadError as e:
                return self.fail(e.code, str(e), **e.extra)
            except FileNotFoundError:
                return self.send(404, b"not found", "text/plain")
            except Exception as e:                                  # a page's data could not be read: say which file, never drop the connection
                bad = self.bad_files()
                if u.path.startswith("/api/") and (bad or not isinstance(e, (KeyError, ValueError))):
                    return self.data_error(e, bad)
                if isinstance(e, (KeyError, ValueError)): return self.send(404, b"not found", "text/plain")
                return self.data_error(e, bad)
            self.send(404, b"not found", "text/plain")

        def bad_files(self):
            from .. import filecheck
            try: return filecheck.problems(self.proj.root) if self.proj.root else []
            except Exception: return []

        def data_error(self, e, bad):
            """500 with a JSON the page can show: the files that are broken (filecheck.py), else what went wrong (no server paths)."""
            files = [{"file": f, "problem": m} for f, m in bad[:8]]
            msg = ("页面要的数据读不出来，这些文件有问题：" + "；".join(f"{x['file']}（{x['problem']}）" for x in files) + "。请 agent 改好这些文件（gameanything flow check 会列出来）"
                   if files else f"页面要的数据读不出来（{type(e).__name__}）。请 agent 跑 gameanything flow check 看一下")
            try: sys.stderr.write(f"[ui] {self.path}: {type(e).__name__}: {e}\n")
            except Exception: pass
            return self.fail(500, msg, files=files)

        def do_POST(self):
            path = urlparse(self.path).path
            if self.agent_peer():
                n = min(int(self.headers.get("Content-Length") or 0), 1 << 20)
                if n: self.rfile.read(n)
                return self.send(403, json.dumps({"error": "agent 的进程不能在页面上操作（只有她的浏览器能）"}, ensure_ascii=False).encode(), "application/json")
            # bound late (lambdas): with no project open there is no Project to bind to
            routes = {"/api/save": lambda d: self.proj.save(d), "/api/look": lambda d: self.proj.save_look(d), "/api/review": lambda d: self.proj.review(d), "/api/play_feedback": lambda d: self.proj.play_feedback(d),
                      "/api/next_round": lambda d: self.proj.next_round(d), "/api/board_review": lambda d: screens.save_board(self.proj, d),
                      "/api/plan_review": lambda d: screens.save_plan(self.proj, d), "/api/adaptation_review": lambda d: screens.save_adaptation(self.proj, d), "/api/gameplay_review": lambda d: screens.save_gameplay(self.proj, d), "/api/feature_review": lambda d: screens.save_feature(self.proj, d), "/api/ingest_request": lambda d: self.ingest_request(d),
                      "/api/thread": lambda d: self.proj.say(d), "/api/thread/answer": lambda d: self.proj.answer(d),
                      "/api/projects/open": self.mgr.open, "/api/projects/new": self.mgr.new, "/api/projects/game": self.mgr.set_game, "/api/projects/mode": self.mgr.set_mode, "/api/projects/launch": self.mgr.set_launch, "/api/projects/remove": self.mgr.remove, "/api/settings": self.mgr.settings, "/api/export/start": self.mgr.export_start, "/api/import/start": self.mgr.import_start,
                      "/api/backup/preview": self.mgr.backup_preview, "/api/backup/enable": self.mgr.backup_enable, "/api/backup/disable": self.mgr.backup_disable,
                      "/api/backup/run": self.mgr.backup_run, "/api/coach": self.mgr.coach, "/api/live": lambda d: self.live_switch(d),
                      "/api/profile": lambda d: self.profile_save(d), "/api/models": lambda d: self.models_save(d)}
            routes["/api/people/add"] = lambda d: self.proj.add_person(d)          # 人物 page: someone she names by hand
            if path != "/api/upload" and path not in routes: return self.send(404, b"not found", "text/plain")
            if self.proj.p is None and path not in NO_PROJECT_POST and not (path == "/api/upload" and self.headers.get("X-Upload-Target") == "import"):
                return self.fail(409, "还没有打开的项目", no_project=True)
            if not self.origin_ok():
                return self.send(403, b"forbidden", "text/plain")
            if path in ("/api/backup/enable", "/api/projects/remove") and self.headers.get("Origin") is None: return self.send(403, b"forbidden", "text/plain")     # only from the page, never a bare script
            if path in DECISION_POST and not self.decision_ok():
                return self.fail(403, DECISION_REFUSED, need="reload")
            if path == "/api/upload":                                    # a binary chunk, streamed to disk (never read whole)
                uid = self.headers.get("X-Upload-Id") or ""
                try:
                    with self.proj.upload_lock(uid) if self.proj.p else self.mgr.lock:
                        r = (self.mgr.imports if self.headers.get("X-Upload-Target") == "import" else self.proj.inbox).put(uid, self.headers, self.rfile)
                except UploadError as e:
                    left = min(int(self.headers.get("Content-Length") or 0), 16 << 20)    # read the rest of the body, or the browser sees a reset instead of the error
                    while left > 0:
                        buf = self.rfile.read(min(1 << 20, left))
                        if not buf: break
                        left -= len(buf)
                    return self.fail(e.code, str(e), **e.extra)
                return self.send(200, json.dumps(r).encode(), "application/json")
            n = int(self.headers.get("Content-Length", 0))
            if n > MAX_JSON: return self.send(413, b"too large", "text/plain")
            try:
                body = json.loads(self.rfile.read(n))
                r = routes[path](body)
            except UploadError as e:
                return self.fail(e.code, str(e))
            except Denied as e:
                return self.fail(403, str(e), need="edit")
            except (CardError, Exception) as e:
                return self.fail(400, str(e))
            if isinstance(r, dict) and r.get("error"): r = {**r, "error": err(r["error"], self.lang())}
            self.send(200, json.dumps(r).encode(), "application/json")

        def profile_ok(self) -> bool:
            """Her preference profile is hers alone: in the hub only the project's owner (the single-user UI has no other viewer)."""
            from .. import profile
            who = self.proj.who().get("author")
            return not who or who == profile.owner_of(self.proj.root)

        def profile_save(self, d):
            if not self.profile_ok(): raise CardError("只有项目的所有者能改自己的偏好")
            with self.proj.lock: return screens.save_profile(self.proj.root, d)

        def models_ok(self) -> bool:
            """Which agent / model a project runs on (and so whose quota it uses) is the owner's choice: in the hub only the owner."""
            from .. import users
            who = self.proj.who().get("author")
            return not who or who == users.owner_of(self.proj.root)

        def models_save(self, d):
            from .. import models
            if not self.models_ok(): raise CardError("只有项目的所有者能换模型")
            with self.proj.lock:
                try: models.set_choice(self.proj.root, str(d.get("role") or ""), d.get("agent"), d.get("model"), by=self.proj.who().get("author"))
                except models.ModelError as x: raise CardError(str(x))
                return {"ok": True, "models": models.state(self.proj.root, True)}

        def live_switch(self, d):
            """The 工作台's 「打开 / 关掉实时画面」: her word on watching the current build (liveview.py)."""
            from .. import builds, liveview
            m, r = builds.current(self.proj.root)
            if not r: raise CardError("现在没有正在进行的构建")
            who = self.proj.who().get("author")
            return {"ok": True, "live": liveview.set_consent(self.proj.root, m, bool(d.get("on")), who)}

        def ingest_request(self, d):
            with self.proj.lock:
                req = self.proj.inbox.request_ingest(self.proj.root, str(d.get("note") or ""))
                self.proj.feedback_ui({"type": "ingest_request", "files": len(req["files"])})
                n = len(req["files"]); self.proj.tell(f"请 agent 整理 {n} 个新文件", f"Asked the agent to sort {n} new files", None, auto=True)
                return {"ok": True, "request": {"state": req["state"], "at": req["at"]}}
    return H


class _Server(ThreadingHTTPServer):
    # Windows' SO_REUSEADDR lets a second server bind a port another one is listening on (both "work", requests go to either),
    # so a second `gameanything ui` would never move on to the next free port; elsewhere it only skips TIME_WAIT after a restart
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        """HTTPServer.server_bind also asks socket.getfqdn(host), a reverse DNS lookup that hangs for 30 s or more on some Macs (GitHub's
        macOS runners, 2026-10-25: `gameanything ui` did not listen within 20 s). The name is never used: skip it."""
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = str(self.server_address[0]), self.server_address[1]


class LocalManager(Manager):
    """The manager of one project of `gameanything ui`: opening / creating / removing a project never re-points a tab, it moves the default ("/")
    and answers {go: /p/<id>/} so the page that asked navigates to the project's own address."""
    def __init__(self, cur, make, upload_max, local):
        super().__init__(cur, make, upload_max); self.local = local

    def open(self, d):
        e = projects.find(str(d.get("id") or ""))
        if not Path(e["path"]).is_dir(): raise ValueError("找不到这个项目的文件夹")
        self.local.default = Path(e["path"]); projects.touch(e["path"]); return {"ok": True, "id": e["id"], "go": f"/p/{e['id']}/"}

    def new(self, d):
        e = projects.create(str(d.get("title") or ""), str(d.get("kind") or "memory"), lang=d.get("lang") if d.get("lang") in ("zh", "en") else "en",
                            game=str(d.get("game") or "stardew"), build_mode=d.get("mode") or None)
        self.local.default = Path(e["path"]); return {"ok": True, "id": e["id"], "go": f"/p/{e['id']}/"}

    def set_game(self, d):
        e = projects.set_game(str(d.get("id") or self.entry()["id"]), str(d.get("game") or ""))
        self.local.refresh(e["path"]); return {"ok": True, "id": e["id"], "game": e["game"]}

    def remove(self, d):
        e = projects.find(str(d.get("id") or "")); was = self.local.default is not None and str(Path(e["path"]).resolve()) == str(self.local.default.resolve())
        others = [x for x in self.project_list() if x["id"] != e["id"] and x["exists"]]
        dst = projects.remove(e["id"]); self.local.forget(e["path"])
        if was and others: o = projects.find(others[0]["id"]); self.local.default = Path(o["path"]); projects.touch(o["path"])
        elif was: self.local.default = None                          # the last one: back to the welcome page
        return {"ok": True, "trash": str(dst) if dst else None, "welcome": self.local.default is None, "go": "/"}


class Local:
    """`gameanything ui`: one (Current, LocalManager) per project folder, made the first time a tab asks for it and kept (upload locks, export jobs,
    the backup scheduler live there); `default` is the project "/" redirects to; `home` (no project) serves the welcome page."""
    def __init__(self, make, upload_max, first=None):
        self.make, self.upload_max = make, upload_max; self.cache = {}; self.lock = threading.Lock()
        self.home = Current(None); self.home_mgr = LocalManager(self.home, make, upload_max, self)
        self.default = Path(first) if first is not None else None

    def bound(self, root):
        k = str(Path(root).resolve())
        with self.lock:
            if k not in self.cache:
                cur = Current(self.make(Path(root))); self.cache[k] = (cur, LocalManager(cur, self.make, self.upload_max, self))
            return self.cache[k]

    def current(self):
        """What "/" and an unprefixed call answer for."""
        if self.default is not None and Path(self.default).is_dir(): return self.bound(self.default)
        return self.home, self.home_mgr

    def refresh(self, root):
        with self.lock: hit = self.cache.get(str(Path(root).resolve()))
        if hit: hit[0].p = self.make(Path(root))

    def forget(self, root):
        with self.lock: self.cache.pop(str(Path(root).resolve()), None)


def local_handler(local: Local):
    """The handler of `gameanything ui`: /p/<id>/<path> is <path> answered for that project; a picture / video / download / the workspace frame the
    page links without the prefix is found through the Referer (the page it came from); "/" goes to the default project's address."""
    Base = handler(local.home, local.home_mgr)

    class L(Base):
        base = None

        def end_headers(self):
            self.send_header("Referrer-Policy", "same-origin")        # same-origin links always carry the page they came from
            super().end_headers()

        def send_header(self, k, v):
            if k.lower() == "location" and self.base and str(v).startswith("/") and not str(v).startswith(self.base + "/"): v = self.base + v
            super().send_header(k, v)

        def inject(self, html: bytes) -> bytes:
            b = f"window.M2W_BASE={json.dumps(self.base)};" if self.base else ""      # without a project (the welcome page) the patch waits for one
            return html.replace(b"<head>", f"<head><script>{b}{BASE_PATCH}</script>".encode(), 1)

        def redirect(self, to):
            self.send_response(302); self.send_header("Location", to); self.send_header("Content-Length", "0"); self.end_headers()

        def do_GET(self): self.dispatch(Base.do_GET)
        def do_POST(self): self.dispatch(Base.do_POST)

        def bind(self, pid) -> bool:
            try: e = projects.find(pid)
            except KeyError: e = None
            if e is None or e["id"] != pid or not Path(e["path"]).is_dir(): self.send(404, b"not found", "text/plain"); return False
            self.proj, self.mgr = local.bound(e["path"]); self.base = f"/p/{pid}"; return True

        def dispatch(self, fn):
            self.base = None; self.proj, self.mgr = local.current()
            u = urlparse(self.path); q = f"?{u.query}" if u.query else ""
            m = PREFIX.match(u.path)
            if m:
                if m.group(2) is None: return self.redirect(f"/p/{m.group(1)}/{q}")
                if not self.bind(m.group(1)): return
                self.path = m.group(2) + q; return fn(self)
            ref = urlparse(self.headers.get("Referer") or ""); rm = re.match(r"^/p/([A-Za-z0-9_.-]+)/", ref.path or "")
            if rm and ref.netloc == self.headers.get("Host"):
                if self.command == "GET" and u.path in ("/", "/app"): return self.redirect(f"/p/{rm.group(1)}{u.path}{q}")
                if not self.bind(rm.group(1)): return
                return fn(self)
            if self.command == "GET" and u.path == "/" and "embed" not in parse_qs(u.query) and self.proj.p is not None:
                return self.redirect(f"/p/{self.mgr.entry()['id']}/")          # the page always runs under its project's own address
            return fn(self)
    return L


def serve(project, port=8765, content: Path = None, upload_max: int = 20 * 2 ** 30, ready=None):
    """project None: no project yet; the page opens on the welcome page and its new-project wizard. ready(server) is called once it listens."""
    if project is not None and not Path(project).is_dir(): raise SystemExit(f"{project} is not a folder")
    make = lambda root: Project(root, content, upload_max)
    if project is not None: projects.touch(Path(project))              # the first time a folder is opened it joins the project list
    from .. import decisions
    decisions.serve_signing()                         # this process alone signs her decisions (the key lives only in its memory)
    local = Local(make, upload_max, Path(project) if project is not None else None)
    for p in range(port, port + 30):                  # the default port may be taken by something else: use the next free one
        try:
            srv = _Server(("127.0.0.1", p), local_handler(local)); port = p; break
        except OSError:
            continue
    else:
        raise SystemExit(f"no free port in {port}-{port + 29}")
    print(f"[ui] {project or 'no project yet: the page starts with the welcome page'}\n[ui] open http://127.0.0.1:{port}/  (local only; Ctrl-C to stop)", flush=True)
    if ready: ready(srv)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
