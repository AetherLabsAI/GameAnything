"""Project conversation: an append-only event log shared by the browser UI and the user's Claude Code session (card formats: skills/gameanything/references/cards.md).

    <project>/conversation/thread.jsonl   one event per line (text / card / answer / status), appended under a file lock
    <project>/conversation/files/         attachments and frames grabbed from the play workspace
    <project>/conversation/.agent_cursor  id of the last user event the session has read (`gameanything chat read`)
    <project>/conversation/.agent_read_at when the cursor last moved (the "Seen 14:05" under the user's message; optional, older projects have none)
    <project>/conversation/.agent_seen    when the session last looked (`gameanything chat wait` touches it); drives the "agent online" light
    <project>/conversation/.agent_owner.json  {session, host, pid, since, last_seen[, proc, proc_start, released]}: the one agent session that owns this
                                          conversation (`gameanything chat claim`). With `proc` (a supervised run, `gameanything agentd`) the owner is live exactly while
                                          that process runs on this host; otherwise while last_seen is younger than OWNER_STALE_SECS
    <project>/conversation/.agent_calling an agent is being called for this user event ({at, event}; `gameanything agentd`, `chat wait --unowned`)
The user's own words are copied verbatim into feedback/answers.md by `read`, under one "## <date> 对话（界面）" heading per day.
"""
import json
import os
import re
import secrets
import shutil
import socket
import time
from datetime import datetime
from pathlib import Path

import yaml

from . import clock
from . import layout, osdirs

FRAME_MAX = 12 << 20                          # largest decoded frame (PNG / JPEG) a chat message may carry
ONLINE_SECS = 300
MSG_MAX = 20000                                # longest chat message (characters); longer text goes in as an attached file
CALLING_MAX_SECS = 180                         # 「正在叫 agent」 is shown this long at most: a run starts within seconds or the call failed
BUSY_MAX_SECS = 6 * 3600                       # a "working" mark older than this is shown as idle (a session that died mid-task)
OWNER_STALE_SECS = 90                          # an owner without a process to check, not seen for this long, is gone (listeners beat every 20 s)
TWO_SESSIONS_SECS = 600                        # agent sessions that spoke within this window count for the "two sessions" warning
MEDIA_PREFIXES = ("/media/", "/art/", "/build/", "/conv/")
ROUTES_RE = re.compile(r"^#[a-z]+(/[\w.-]+)*$")


class CardError(ValueError):
    pass


class Owned(CardError):
    """Another live agent session owns the conversation (CLI exit code 3)."""


def default_session() -> str:
    """$GAMEANYTHING_SESSION (set by `gameanything agentd` for its runs), else $CLAUDE_SESSION_ID, else host:ppid."""
    return os.environ.get("GAMEANYTHING_SESSION") or os.environ.get("CLAUDE_SESSION_ID") or f"{socket.gethostname()}:{os.getppid()}"


def instance() -> str:
    """Which running agent session this is, apart from its chosen name: two sessions that both call themselves "wenyi-main"
    (e.g. one resumed in a new window while the old one still runs) are still told apart. None when the agent gives no id."""
    return os.environ.get("GAMEANYTHING_INSTANCE") or os.environ.get("CLAUDE_CODE_SESSION_ID") or None


# ---- card validation (one row per kind of the protocol's table) ----
def _need(c, key, typ, what=None):
    if key not in c or c[key] in (None, ""): raise CardError(f"卡片缺少 {key}" + (f"（{what}）" if what else ""))
    if not isinstance(c[key], typ): raise CardError(f"{key} 的类型不对：应该是 {typ.__name__ if isinstance(typ, type) else '/'.join(t.__name__ for t in typ)}")


def _items(c, key, fields, min_n=1):
    _need(c, key, list)
    if len(c[key]) < min_n: raise CardError(f"{key} 不能是空的")
    for i, it in enumerate(c[key], 1):
        if not isinstance(it, dict): raise CardError(f"{key} 第 {i} 项应该是带字段的对象")
        for f in fields:
            if it.get(f) in (None, ""): raise CardError(f"{key} 第 {i} 项缺少 {f}")


def _url(u, where):
    if u and not (isinstance(u, str) and u.startswith(MEDIA_PREFIXES)):
        raise CardError(f"{where} 只能用项目里已有的文件（{' '.join(MEDIA_PREFIXES)} 开头），收到：{u}")


def _open(c):
    if c.get("open") and not ROUTES_RE.match(str(c["open"])): raise CardError(f"open 应该是工作区路由，例如 #play/m2，收到：{c['open']}")


def check_length(text):
    """A chat message longer than MSG_MAX is refused with the reason (the page counts too, shell.js)."""
    n = len((text or "").strip()) if isinstance(text, str) else 0
    if n > MSG_MAX: raise CardError(f"消息太长（{n} 个字）：一条最多 {MSG_MAX} 个字。长的内容请存成文件，作为附件发")


EN_KEEP = {"text_en", "now_en"}                 # fields a card kind reads as such (progress: now_en, alert.text_en): never moved


def en_fields(x):
    """The English that a card carries as `<field>_en` (title_en, desc_en, items[i].title_en …) as an English card overlay (the shape of
    `en:`), or None. The *_en fields stay in the card (harmless in Chinese)."""
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            if isinstance(k, str) and k.endswith("_en") and k not in EN_KEEP and len(k) > 3 and isinstance(v, (str, list, dict)):
                out[k[:-3]] = v
            elif isinstance(v, (dict, list)):
                sub = en_fields(v)
                if sub: out[k] = sub
        return out or None
    if isinstance(x, list):
        subs = [en_fields(v) if isinstance(v, (dict, list)) else None for v in x]
        return [s or {} for s in subs] if any(subs) else None
    return None


def merge_en(base, en):
    """A card with its English overlay: dicts merge key by key, lists of dicts item by item (by `key` / `n` / `id` when both sides have
    it, else by position), anything else is replaced. What the overlay leaves out stays, so pictures, urls and numbers of the Chinese card
    are kept when the English names only the words (translate.localize, the public demo)."""
    if isinstance(base, dict) and isinstance(en, dict):
        return {**base, **{k: merge_en(base.get(k), v) if k in base else v for k, v in en.items()}}
    if isinstance(base, list) and isinstance(en, list) and base and all(isinstance(v, dict) for v in base) and all(isinstance(v, dict) for v in en):
        idk = next((f for f in ("key", "n", "id") if all(f in v for v in base) and all(f in v for v in en if v)), None)
        if idk:
            by = {str(v[idk]): v for v in en if v}
            return [merge_en(b, by[str(b[idk])]) if str(b[idk]) in by else b for b in base]
        if len(en) == len(base): return [merge_en(b, e) for b, e in zip(base, en)]
        return en
    return base if en is None else en


def check_card(c: dict) -> dict:
    """Validate a card (a dict from yaml/json); returns it normalised. Raises CardError with a message saying what is wrong."""
    if not isinstance(c, dict): raise CardError("卡片应该是一个带字段的对象")
    kind = c.get("kind")
    if kind not in KINDS: raise CardError(f"不认识的卡片 kind：{kind!r}。可用：{' '.join(KINDS)}")
    if kind != "progress": _need(c, "title", str)
    if c.get("key") is not None and not isinstance(c["key"], str): raise CardError("key 应该是字符串")
    KINDS[kind](c); _open(c)
    return c


def _permission(c):
    _need(c, "will_send", list); _need(c, "will_not_send", list); _need(c, "to", str, "发给谁")
    if c.get("cost_usd") is not None and not isinstance(c["cost_usd"], (int, float)): raise CardError("cost_usd 应该是数字")
    fs = c.get("files")                 # gameanything gen: the project files (globs) that may be sent; every picture of the request must match one
    if fs is not None and not (isinstance(fs, list) and all(isinstance(x, str) and x.strip() for x in fs)): raise CardError("files 应该是项目里的路径 / 通配符列表")


def _questions(c):
    _items(c, "items", ["n", "text"]); [_url(i.get("image"), "items.image") for i in c["items"]]
    if len({str(i["n"]) for i in c["items"]}) != len(c["items"]): raise CardError("items 里的 n 有重复")


def _understanding(c):
    _items(c, "points", ["id", "text"])
    if len({str(i["id"]) for i in c["points"]}) != len(c["points"]): raise CardError("points 里的 id 有重复")


def _result(c):
    _need(c, "milestone", str); _url(c.get("image"), "image")
    if c.get("stats") is not None and not isinstance(c["stats"], list): raise CardError("stats 应该是列表")


def _options(c):
    _items(c, "items", ["key", "title"])
    if len({str(i["key"]) for i in c["items"]}) != len(c["items"]): raise CardError("items 里的 key 有重复")


def _candidates(c):
    if c.get("media") not in ("audio", "image"): raise CardError("media 应该是 audio 或 image")
    _items(c, "items", ["key", "title", "url"])
    for i in c["items"]: _url(i["url"], "items.url")


def _go(c):
    _need(c, "milestone", str); _need(c, "items", list)
    if not c["items"]: raise CardError("items 不能是空的")
    for f in ("eta_hours", "cost_usd", "max_images"):
        if c.get(f) is not None and not isinstance(c[f], (int, float)): raise CardError(f"{f} 应该是数字")
    if c.get("estimate") is not None: _estimate(c["estimate"])
    rs = c.get("runners")
    if rs is not None:          # what the build runs with (D21): harness + model, each with its own estimate; the user picks one
        if not (isinstance(rs, list) and rs): raise CardError("runners 应该是非空列表")
        for r in rs:
            if not isinstance(r, dict) or not all(isinstance(r.get(k), str) and r.get(k) for k in ("id", "harness", "model")):
                raise CardError("runners 的每一项要有 id、harness、model")
            if r.get("estimate") is not None: _estimate(r["estimate"])
        if len({r["id"] for r in rs}) != len(rs): raise CardError("runners 的 id 不能重复")
    pr = c.get("playtest_rounds")                 # how many playtest rounds the build may use (the user can change it on the card)
    if pr is not None and not (isinstance(pr, int) and 1 <= pr <= 10): raise CardError("playtest_rounds 应该是 1 到 10 的整数")
    wh = c.get("wall_hours")
    if wh is not None and not (isinstance(wh, (int, float)) and 0 < wh <= 12): raise CardError("wall_hours 应该是 0 到 12 小时")


def _estimate(e):
    if not isinstance(e, dict): raise CardError("estimate 应该是带字段的对象")
    num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0
    w = e.get("wall_h")
    if not (isinstance(w, list) and len(w) == 2 and all(map(num, w)) and w[0] <= w[1]): raise CardError("estimate.wall_h 应该是 [最少小时, 最多小时]")
    cu = e.get("cost_usd")
    if cu is not None and not (isinstance(cu, list) and len(cu) == 2 and all(map(num, cu)) and cu[0] <= cu[1]):
        raise CardError("estimate.cost_usd 应该是 [最少美元, 最多美元]，或者 null（订阅 / 估不出来）")
    if e.get("account") not in ("subscription", "api"): raise CardError("estimate.account 应该是 subscription 或 api")
    for f in ("agent", "model", "note"):
        if e.get(f) is not None and not isinstance(e[f], str): raise CardError(f"estimate.{f} 应该是字符串")


def _progress(c):
    _need(c, "milestone", str); _need(c, "key", str, "进度卡靠 key 原地更新")
    _items(c, "steps", ["text", "state"])
    for s in c["steps"]:
        if s["state"] not in ("done", "current", "todo"): raise CardError(f"步骤状态应该是 done / current / todo，收到：{s['state']}")
    c.setdefault("title", "进行中")
    m = c.get("meter")                                   # a running build (gameanything build watch): round k of N, minutes so far of the limit, what runs it
    if m is not None:
        if not isinstance(m, dict): raise CardError("meter 应该是对象")
        for f in ("round", "max_rounds", "elapsed_min", "wall_min"):
            if f in m and not (isinstance(m[f], (int, float)) and m[f] >= 0): raise CardError(f"meter.{f} 应该是非负数")
    for f in ("now", "now_en", "now_at"):                # agentd's live build card (live.py): what the builder does right now
        if c.get(f) is not None and not isinstance(c[f], str): raise CardError(f"{f} 应该是字符串")
    if c.get("images") is not None:
        if not isinstance(c["images"], list) or len(c["images"]) > 6: raise CardError("images 应该是最多 6 个图片地址的列表")
        for u in c["images"]: _url(u if isinstance(u, str) else (u or {}).get("url"), "images")
    a = c.get("alert")
    if a is not None and not (isinstance(a, dict) and a.get("kind") in ("stall", "pause", "auth", "slow", "died", "done", "stopped") and isinstance(a.get("text"), str)):
        raise CardError("alert 应该是 {kind: stall|pause|auth|slow|died|done|stopped, text}")


def _task(c):
    _need(c, "body", str); _need(c, "open", str, "要去哪个工作区，例如 #people/tag")
    for f in ("estimate", "done_hint"):
        if c.get(f) is not None and not isinstance(c[f], str): raise CardError(f"{f} 应该是字符串")


KINDS = {"permission": _permission, "questions": _questions, "understanding": _understanding, "result": _result,
         "options": _options, "candidates": _candidates, "go": _go, "progress": _progress, "task": _task}
ANSWERABLE = {"permission", "questions", "understanding", "options", "candidates", "go", "task"}


# the workspace pages (ui/static/app.js SCREENS) of each project kind, and the other kinds' names that open them there (app.js redirects)
PAGES_ALL = ["gather", "plan", "play", "status", "keep", "now", "prefs"]
PAGES = {"memory": ["home", "board", "people"], "adaptation": ["scenes", "characters"], "feature": ["spec"],
         "gameplay": ["mechanics", "content", "balance"]}
PAGE_ALIAS = {"adaptation": {"home": "scenes", "board": "scenes", "people": "characters"},
              "feature": {"home": "spec", "board": "spec", "people": "spec"},
              "gameplay": {"home": "mechanics", "board": "mechanics", "people": "content"}}


def _yaml_file(p) -> dict:
    try: d = yaml.safe_load(Path(p).read_text(encoding="utf-8")) or {}
    except Exception: return {}
    return d if isinstance(d, dict) else {}


def check_answer(kind: str, a: dict) -> dict:
    if not isinstance(a, dict): raise CardError("回答应该是一个对象")
    if kind not in ANSWERABLE: raise CardError(f"{kind} 卡不需要回答")
    if kind == "permission" and a.get("decision") not in ("yes", "no"): raise CardError("decision 应该是 yes 或 no")
    if kind == "go" and a.get("decision") not in ("start", "wait"): raise CardError("decision 应该是 start 或 wait")
    if kind == "go" and a.get("runner") is not None and not isinstance(a["runner"], str): raise CardError("runner 应该是 runners 里的一个 id")
    if kind == "go" and a.get("playtest_rounds") is not None and not (isinstance(a["playtest_rounds"], int) and 1 <= a["playtest_rounds"] <= 10):
        raise CardError("playtest_rounds 应该是 1 到 10")
    if kind == "questions" and not isinstance(a.get("answers", {}), dict): raise CardError("answers 应该是 {n: 原话}")
    if kind == "understanding" and not (a.get("ok") or a.get("edits") or str(a.get("note") or "").strip()):
        raise CardError("应该是 ok: true、edits: {id: 改后的话}，或者只有一句意见 note")
    if kind in ("options", "candidates") and not isinstance(a.get("picked", []), list): raise CardError("picked 应该是列表")
    if kind == "task":
        if bool(a.get("done")) == bool(a.get("later")): raise CardError("应该是 done: true，或者 later: true（二选一）")
        if a.get("note") is not None and not isinstance(a["note"], str): raise CardError("note 应该是字符串")
    return a


def now() -> str: return datetime.now().isoformat(timespec="seconds")


def _by(author, author_name) -> dict:
    return {"author": author, "author_name": author_name or author} if author else {}


def phase(evs, info):
    """The status line under the user's last message (the page draws it), from the events and online()'s info:
    None (nothing to show) | sent (delivered, an agent will read it) | calling (an agent is being started for it) | queued (waits for a free
    slot) | working (read / being worked on; also while a run goes on after its reply) | failed (the run did not answer, see info.failed) |
    paused (the agent CLI is backed off: login / key, usage limit, its sandbox; info.backoff says why and until when; one steady state,
    QA2 2026-10-30: it flipped between 「正在叫」, 「等 agent 读取」 and 「没能回复」) | down (nothing will pick it up: no supervisor, no live session)."""
    ids = [e.get("id") for e in evs]
    users = [i for i, e in enumerate(evs) if e.get("from") == "user" and e.get("type") in ("text", "answer") and e.get("source") == "ui"]
    working = bool(info.get("run") or info.get("busy"))
    if not users: return "working" if info.get("run") else None
    li = users[-1]; le = evs[li]
    if any(e.get("from") == "agent" for e in evs[li + 1:]): return "working" if working else None
    pos = lambda x: ids.index(x) if x in ids else -1
    if li <= max(pos(info.get("cursor")), pos(info.get("noticed"))): return "working"
    if info.get("run"): return "calling"
    up = info.get("owner_live") or (info.get("agentd") or {}).get("alive")
    if info.get("backoff") and up: return "paused"
    f = info.get("failed") or {}
    if f and pos(f.get("event")) >= li: return "failed"
    if not up: return "down"                       # nobody will come: no supervisor, no live session (a stale 「正在叫」 never hides that)
    if info.get("queued"): return "queued"
    c = info.get("calling") or {}
    fresh = Thread._age(c.get("at")) <= CALLING_MAX_SECS if c.get("at") else False
    if c and fresh and (pos(c.get("event")) >= li or (c.get("event") is None and str(c.get("at") or "") >= str(le.get("at") or ""))): return "calling"
    return "sent"


class Thread:
    def __init__(self, root: Path):
        self.root = Path(root); self.dir = self.root / "conversation"
        self.log = self.dir / "thread.jsonl"; self.files = self.dir / "files"

    def _ensure(self): self.files.mkdir(parents=True, exist_ok=True)

    # ---- storage ----
    def events(self, after: str = None):
        if not self.log.exists(): return []
        out = []
        from . import decisions
        pid, floor = decisions.answer_floor(self.root)                      # isolation on: her answers count only when the page signed them
        if floor is not None:
            from . import isolation
            if not isolation.trusted(self.log): floor = 0                  # not the server's file: no unsigned answer counts at all
        i = -1
        for ln in self.log.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                i += 1
                try: e = json.loads(ln)
                except ValueError: continue                                # a half-written line is never returned
                if floor is not None and isinstance(e, dict) and e.get("type") == "answer" and not decisions.answer_ok(self.root, e, i, pid, floor):
                    continue
                out.append(e)
        if after:
            ids = [e["id"] for e in out]
            if after in ids: out = out[ids.index(after) + 1:]
        return out

    def append(self, ev: dict) -> dict:
        from . import isolation
        if isolation.forwarded():                                          # a command the gate runs for an agent run (gate.py)
            if ev.get("from") == "user" or ev.get("type") == "answer": raise CardError("agent 不能替用户说话或回答卡片")
            if ev.get("from") == "agent":
                ev = {**ev, "via": "gate", "run": os.environ.get("GAMEANYTHING_GATE_RUN") or None}
        self._ensure()
        ev = {"id": f"e_{datetime.now():%Y%m%dT%H%M%S}_{secrets.token_hex(2)}", "at": now(), **ev}
        if ev.get("from") == "user" and ev.get("type") == "answer":
            from . import decisions
            ev = decisions.sign_event(self.root, {k: v for k, v in ev.items() if k not in ("kid", "sig")})
        line = (json.dumps(ev, ensure_ascii=False) + "\n").encode()
        with open(self.dir / ".lock", "a", encoding="utf-8") as lk:
            osdirs.lock(lk)
            fd = os.open(self.log, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)   # Windows: no \n -> \r\n
            try: os.write(fd, line)                                          # one write on an O_APPEND fd: lines never interleave
            finally: os.close(fd)
        return ev

    # ---- writers ----
    def user_text(self, text, context=None, source="ui", auto=None, text_en=None, author=None, author_name=None):
        """auto: the page generated this line from a verdict click (not the user's words): shown as "（页面操作）", never copied to answers.md.
        author / author_name: the hub user who wrote it (`gameanything hub`; none in the single-user UI)."""
        text = (text or "").strip()
        if not text and not any(c.get("kind") == "file" for c in context or []): raise CardError("说点什么吧")
        check_length(text)
        ev = {"from": "user", "type": "text", "text": text, "source": source, **_by(author, author_name)}
        if auto: ev["auto"] = True
        if auto and text_en: ev["text_en"] = text_en
        if context: ev["context"] = context
        return self.append(ev)

    def agent_text(self, text, text_en=None, session=None, attach=()):
        """attach: files to offer as download buttons under the message (copied into conversation/files/, served at /conv/<name>)."""
        names = []
        for f in attach:
            f = Path(f); self.files.mkdir(parents=True, exist_ok=True); shutil.copy2(f, self.files / f.name); names.append(f.name)
        return self.append({"from": "agent", "type": "text", "text": text, **({"text_en": text_en.strip()} if text_en else {}), "source": "terminal",
                            **({"session": session} if session else {}), **({"files": names} if names else {})})

    def _versioned(self, x):
        """/art/… and /build/<m>/… picture links get ?v=<file mtime>: a picture redrawn under the same name is a new URL, so the page does not
        reuse the old one it already shows in an earlier card."""
        if isinstance(x, dict): return {k: self._versioned(v) for k, v in x.items()}
        if isinstance(x, list): return [self._versioned(v) for v in x]
        if isinstance(x, str) and "?" not in x and (x.startswith("/art/") or x.startswith("/build/")):
            if x.startswith("/art/"): f = self.root / "4_design" / "art" / x[len("/art/"):]
            else:
                m, _, rest = x[len("/build/"):].partition("/"); f = self.root / "5_build" / m / "play" / rest
            if f.is_file(): return f"{x}?v={int(f.stat().st_mtime)}"
        return x

    def _pictures_ok(self, x):
        """Every /media/, /art/ and /build/ link in a card must be a file the page can show; otherwise the card would go out with a broken
        picture (a 404 in her browser), so it is refused here with the reason and the agent fixes the path first."""
        if isinstance(x, dict): [self._pictures_ok(v) for v in x.values()]
        elif isinstance(x, list): [self._pictures_ok(v) for v in x]
        elif isinstance(x, str) and x.startswith(("/media/", "/art/", "/build/")):
            u = x.split("?", 1)[0]
            if u.startswith("/media/"):
                if layout.media_file(self.root, u) is None:
                    raise CardError(f"卡片里的图 {u} 网页打不开：文件不存在，或不在工作文件夹里（只能放在 {'、'.join(layout.MEDIA_ROOTS)} 下面，"
                                    f"且是图片/视频/声音文件，不能在 . 开头的文件夹里）。先把图放对地方再发卡。")
            else:
                if u.startswith("/art/"): f = self.root / layout.DESIGN / "art" / u[len("/art/"):]
                else:
                    m, _, rest = u[len("/build/"):].partition("/"); f = self.root / "5_build" / m / "play" / rest
                if not f.is_file(): raise CardError(f"卡片里的图 {u} 网页打不开：{f.relative_to(self.root)} 不存在。先把图放对地方再发卡。")

    STUDY_KEYS = ("feedback-judge",)            # cards that exist only for the study (judge.CONSENT_KEY): never sent with study mode off

    def _study_ok(self, card):
        if isinstance(card, dict) and card.get("key") in self.STUDY_KEYS:
            from . import study
            if not study.on(self.root):
                raise CardError(f"{card['key']} 是研究用的卡：这个项目没开研究模式（study.py），不发；也不要跟她提研究")

    def card(self, card: dict, text: str = None, text_en: str = None, card_en: dict = None, session=None, flow_step=None):
        """card_en: the English card (same shape; also accepted as `en:` inside the card). Only what differs from the card needs to be in it."""
        card = dict(card) if isinstance(card, dict) else card
        if isinstance(card, dict) and "en" in card: card_en = card_en or card.pop("en")
        if isinstance(card, dict) and (card_en is None or isinstance(card_en, dict)):
            side = en_fields(card)                      # `title_en: …` next to `title` (the other way agents write it): the same English card
            if side: card_en = merge_en(side, card_en) if card_en else side
        self._pictures_ok(card); self._pictures_ok(card_en)
        self._study_ok(card)
        card = self._versioned(check_card(card))
        self._go_milestone(card, flow_step)
        if card.get("kind") == "task": card["open"] = self._page(card["open"])
        ev = {"from": "agent", "type": "card", "text": text or "", "card": card, "source": "terminal", **({"session": session} if session else {})}
        if text_en: ev["text_en"] = text_en.strip()
        if flow_step: ev["flow_step"] = flow_step                       # the flow step the agent worked on when it sent this (flow.py)
        if card_en is not None:
            if not isinstance(card_en, dict): raise CardError("en 应该是一张英文卡片（和 card 同样的字段）")
            check_card(merge_en(card, card_en))
            ev["card_en"] = card_en
        same = self._open_same(ev)
        if same: return same                            # the very same card sent again while it is still open: nothing new to show
        sup = self._superseded_go(card)
        if sup: ev["supersedes"] = sup
        return self.append(ev)

    def _superseded_go(self, card) -> list:
        """A go card for a version: the ids of the older go cards for the same milestone still open under ANOTHER key (or none). A wrong go
        card without a key stayed clickable next to the right one (hotfix 2026-10-30); cards() and shell.js cardState drop them like a
        card replaced under its own key."""
        if not isinstance(card, dict) or card.get("kind") != "go": return []
        m, k = str(card.get("milestone") or ""), card.get("key")
        return [cid for cid, x in self.cards().items() if x["card"].get("kind") == "go" and str(x["card"].get("milestone") or "") == m
                and x["card"].get("key") != k and not x["answers"]]

    def _go_milestone(self, card, flow_step):
        """A go card names the version by its id (world_plan.yaml milestones: m1, m2…), not by its name: 「第一版」 left the card without
        its build model row and the flow without its go card (QA2 2026-10-30). Preview / perceive go cards are not a version's."""
        if not isinstance(card, dict) or card.get("kind") != "go" or flow_step in ("preview", "perceive"): return
        m = str(card.get("milestone") or "")
        if m.isascii(): return
        ms = {}
        try:
            wp = yaml.safe_load((self.root / "4_design" / "world_plan.yaml").read_text(encoding="utf-8")) or {}
            ms = (wp.get("world_plan") or {}).get("milestones") or {} if isinstance(wp, dict) else {}
        except Exception: pass
        ids = [k for k in ms] if isinstance(ms, dict) else []
        hit = next((k for k, v in (ms.items() if isinstance(ms, dict) else []) if isinstance(v, dict) and m in (v.get("name"), v.get("name_en"))), None)
        raise CardError(f"go 卡的 milestone 要写版本的 id（{hit or (' / '.join(map(str, ids[:4])) if ids else 'm1、m2…')}，world_plan.yaml milestones 里的键），"
                        f"不是名字「{m}」")

    def _page(self, route) -> str:
        """A task card's `open:` as a page this kind of project has (QA2 2026-10-30: #people for an adaptation's characters review, #home
        for its scenes): the kind's own name of an alias (adaptation #people -> #characters), or CardError naming the pages there are."""
        r = str(route or "").strip().lstrip("#"); name, _, rest = r.partition("/")
        kind = (_yaml_file(self.root / layout.CONFIG / "project.yaml").get("kind") or "memory")
        own, alias = PAGES.get(kind, PAGES["memory"]), PAGE_ALIAS.get(kind, {})
        name = alias.get(name, name)
        if name not in own + PAGES_ALL:
            raise CardError(f"open 不是这个项目（{kind}）有的页面：#{r}。可以用：" + "、".join("#" + x for x in own + PAGES_ALL))
        return "#" + name + ("/" + rest if rest else "")

    def _open_same(self, ev):
        """The open (unanswered, newest of its key) card that is exactly this one (card, its English and the words with it), or None.
        An agent that posts the same card twice (a retry, a loop) must not put two of them in her chat. A card that changed is appended:
        it supersedes the older one (cards(); the page shows only the newest of an unanswered key). Progress cards update in place anyway."""
        c = ev["card"]; k = c.get("key") if isinstance(c, dict) else None
        if not k or c.get("kind") == "progress": return None
        for x in self.cards().values():
            e = x["event"]
            if x["card"].get("key") == k and not x["answers"] and x["card"] == c and e.get("card_en") == ev.get("card_en") \
                    and (e.get("text") or "") == (ev.get("text") or "") and e.get("text_en") == ev.get("text_en") and e.get("from") == ev.get("from"):
                return e
        return None

    def system_card(self, card: dict, card_en: dict = None, **extra):
        """A card GameAnything itself posts (agentd's live build card, live.py): the same checks as an agent's card, from "system"."""
        self._pictures_ok(card)
        card = self._versioned(check_card(dict(card)))
        if card_en: check_card(merge_en(card, card_en))
        return self.append({"from": "system", "type": "card", "text": "", "card": card, "source": "agentd", **({"card_en": card_en} if card_en else {}), **extra})

    def answer(self, card_id, answer, source="ui", author=None, author_name=None):
        c = self.cards().get(card_id)
        if not c and self._any_card(card_id): raise CardError("这张卡已经更新了（同一个 key 发了新的一张），请回答下面新的那张")
        if not c: raise CardError("找不到这张卡")
        check_answer(c["card"]["kind"], answer)
        rs = c["card"].get("runners") or []
        if answer.get("runner") is not None and answer["runner"] not in {r["id"] for r in rs}: raise CardError("runner 不在这张卡的 runners 里")
        ev = self.append({"from": "user", "type": "answer", "card_id": card_id, "answer": answer, "source": source, **_by(author, author_name)})
        try:                                                # approving the plan on a card counts like 「就按这个做」 on the 方案 page
            from . import flow
            flow.record_answer(self.root, c["event"], answer)
        except Exception:
            pass
        return ev

    def save_frame(self, data_url: str) -> str:
        """A PNG frame (data URL) grabbed from the play workspace -> conversation/files/; returns the project-relative path."""
        import base64
        self._ensure()
        m = re.match(r"^data:image/(png|jpeg);base64,", data_url or "")
        if not m: raise CardError("画面格式不对")
        if len(data_url) > (FRAME_MAX * 4) // 3 + m.end() + 8: raise CardError("画面太大")
        try: raw = base64.b64decode(data_url[m.end():], validate=True)
        except ValueError: raise CardError("画面格式不对")
        if not raw.startswith(b"\x89PNG\r\n\x1a\n" if m.group(1) == "png" else b"\xff\xd8\xff") or len(raw) > FRAME_MAX: raise CardError("画面格式不对")
        name = f"f_{datetime.now():%Y%m%dT%H%M%S}_{secrets.token_hex(2)}.{'png' if m.group(1) == 'png' else 'jpg'}"
        (self.files / name).write_bytes(raw)
        return f"conversation/files/{name}"

    def file_path(self, name: str) -> Path:
        p = (self.files / name).resolve()
        if self.files.resolve() not in p.parents or not p.is_file(): raise FileNotFoundError(name)
        return p

    # ---- derived state ----
    def cards(self):
        """{card_id: {"card", "event", "answers": [...]}} for the latest card of each key; superseded ones are dropped (an answer belongs to
        the card id it was given to, so a new card under an old key starts unanswered). The page (shell.js cardState) agrees: the new card
        is the live one at the bottom, the older one stays in the history read-only with its own answers."""
        out, by_key = {}, {}
        for e in self.events():
            if e["type"] == "card":
                k = e["card"].get("key")
                if k in by_key: out.pop(by_key[k], None)
                for old in e.get("supersedes") or (): out.pop(old, None)      # older open go cards of the same version (_superseded_go)
                if k: by_key[k] = e["id"]
                out[e["id"]] = {"card": e["card"], "event": e, "answers": []}
            elif e["type"] == "answer" and e.get("card_id") in out:
                out[e["card_id"]]["answers"].append(e)
        return out

    # ---- agent side ----
    def seen(self):
        self._ensure(); (self.dir / ".agent_seen").write_text(now(), encoding="utf-8")

    # ---- single owner (advisory, enforced by the CLI) ----
    def owner(self):
        try: return json.loads((self.dir / ".agent_owner.json").read_text(encoding="utf-8"))
        except (OSError, ValueError): return None

    @staticmethod
    def _age(ts):
        try: return time.time() - clock.epoch(ts)
        except (TypeError, ValueError): return 1e9

    def owner_live(self, o=None):
        """A supervised owner (`proc`, on this host) is live while its process runs: a dead run is seen at once. Others (interactive sessions,
        another host) are live while last_seen is younger than OWNER_STALE_SECS. A released owner is never live."""
        o = o or self.owner()
        if not o or o.get("released"): return False
        if o.get("proc") and o.get("host") == socket.gethostname(): return osdirs.pid_alive(o["proc"], o.get("proc_start"))
        return self._age(o.get("last_seen")) <= OWNER_STALE_SECS

    def _write_owner(self, o):
        self._ensure(); tmp = self.dir / ".agent_owner.tmp"
        tmp.write_text(json.dumps(o, ensure_ascii=False), encoding="utf-8"); os.replace(tmp, self.dir / ".agent_owner.json")

    def claim(self, session=None, force=False, proc=None, inst=None):
        """Become the owner. -> (owner, took_over). Raises Owned when another live owner exists and not force.
        proc / inst: a supervisor claiming for a run it just started (its pid and instance id): live exactly while that process runs."""
        session = session or default_session(); self._ensure()
        with open(self.dir / ".lock", "a", encoding="utf-8") as lk:
            osdirs.lock(lk)
            o = self.owner(); live = self.owner_live(o); mine = self.is_mine(o, session, inst) and not (o or {}).get("released") and proc is None
            if live and not mine and not force: raise Owned(self.owned_msg(o))
            if mine: o["last_seen"] = now(); o["instance"] = o.get("instance") or inst or instance()
            else:
                o = {"session": session, "instance": inst or instance(), "host": socket.gethostname(), "pid": os.getppid(), "since": now(), "last_seen": now()}
                if proc: o.update(proc=int(proc), proc_start=osdirs.pid_start(proc))
            took = bool(force and live and not mine)
            self._write_owner(o)
        if took:
            self.append({"from": "system", "type": "status", "text": "另一个会话接手了对话", "text_en": "Another session took over the conversation", "session": session})
        self.seen(); return o, took

    @staticmethod
    def is_mine(o, session, inst=None) -> bool:
        """Same name and, when both sides have one, the same running instance."""
        if not o or o.get("session") != session: return False
        a, b = o.get("instance"), inst or instance()
        return not a or not b or a == b

    def release(self, session=None, inst=None) -> bool:
        """The owner lets the conversation go (a finished run, `gameanything chat release`): the next message can be taken at once. -> was it ours."""
        session = session or default_session(); self._ensure()
        with open(self.dir / ".lock", "a", encoding="utf-8") as lk:
            osdirs.lock(lk)
            o = self.owner()
            if not self.is_mine(o, session, inst) or o.get("released"): return False
            o["released"] = now(); self._write_owner(o)
        self.mark_waiting(); return True

    def owned_msg(self, o):
        same = "它和你同名，但不是同一个正在运行的会话（多半是旧窗口还开着）：先确认旧的那个已经停了。" if o.get("instance") and o.get("instance") != instance() else ""
        how = "它是后台调度（gameanything agentd）启动的一次运行，运行结束就会放开" if o.get("proc") else f"它超过 {OWNER_STALE_SECS} 秒没出现也可以直接 claim"
        return (same + f"这个对话现在归会话 {o.get('session')} 管（{o.get('host')}，自 {o.get('since')}，最后一次出现 {o.get('last_seen')}）。"
                f"不要两个会话同时用。要接手：gameanything chat claim --force --session <你的名字>；{how}。")

    def guard(self, session=None):
        """Called by every agent-side command: the caller must be the owner (an absent / stale owner is claimed). Refreshes last_seen. -> session name."""
        session = session or default_session(); o = self.owner()
        if o and not self.is_mine(o, session) and self.owner_live(o): raise Owned(self.owned_msg(o))
        if not self.is_mine(o, session) or not o.get("instance") or o.get("released"): self.claim(session)
        else: self.touch_owner(session)
        return session

    def touch_owner(self, session):
        self._ensure()
        with open(self.dir / ".lock", "a", encoding="utf-8") as lk:
            osdirs.lock(lk)
            o = self.owner()
            if self.is_mine(o, session) and not o.get("released"): o["last_seen"] = now(); self._write_owner(o)
        self.seen()

    def two_sessions(self, o):
        """Agent sessions that spoke in the last 10 min since the owner took over, when there are two or more (drives the warning bar)."""
        since = (o or {}).get("since") or ""; names = []
        for e in self.events()[-200:]:
            s_ = e.get("session")
            if e.get("from") == "agent" and s_ and self._age(e["at"]) <= TWO_SESSIONS_SECS and e["at"] >= since and s_ not in names: names.append(s_)
        return names if len(names) > 1 else []

    def mark_busy(self):
        """An agent-side command (read / say / card / progress) ran: the session is working on this project until it waits again."""
        self._ensure(); (self.dir / ".agent_busy").write_text(now(), encoding="utf-8")

    def mark_waiting(self):
        """`chat wait` is running for this project: the session is idle here."""
        self._ensure(); (self.dir / ".agent_waiting").write_text(now(), encoding="utf-8")

    def busy(self):
        """True while the session has worked on this project since it last waited (the page shows "the agent is working")."""
        def at(n):
            try: return (self.dir / n).read_text(encoding="utf-8").strip()
            except OSError: return ""
        b, w = at(".agent_busy"), at(".agent_waiting")
        return bool(b) and b > w and self._age(b) <= BUSY_MAX_SECS and self.owner_live()

    def calling(self):
        """{at, event}: an agent is being called for the user's words (`gameanything agentd`, `chat wait --unowned`); None when never.
        Older files hold only the time."""
        try: raw = (self.dir / ".agent_calling").read_text(encoding="utf-8").strip()
        except OSError: return None
        try: c = json.loads(raw)
        except ValueError: c = {"at": raw, "event": None}
        return c if isinstance(c, dict) else None

    def set_calling(self, event_id):
        self._ensure(); tmp = self.dir / ".agent_calling.tmp"
        tmp.write_text(json.dumps({"at": now(), "event": event_id}), encoding="utf-8"); os.replace(tmp, self.dir / ".agent_calling")

    def notice(self, eid):
        """`chat wait` saw a new user event: the page switches to "the agent is on it" before the session has even read it."""
        (self.dir / ".agent_noticed").write_text(eid, encoding="utf-8")

    def _noticed(self):
        try: return (self.dir / ".agent_noticed").read_text(encoding="utf-8").strip() or None
        except OSError: return None

    def _read_at(self):
        try: return (self.dir / ".agent_read_at").read_text(encoding="utf-8").strip() or None
        except OSError: return None

    def online(self, evs=None):
        """What the page shows about the agent: online light, read receipt, queue, the supervisor (agentd) and `phase`, the status line under
        the user's last message (see phase())."""
        p = self.dir / ".agent_seen"; o = self.owner()
        from . import agentd
        from .dispatch import queued
        run = agentd.active_run(self)
        info = {"cursor": self._cursor(), "noticed": self._noticed(), "read_at": self._read_at(), "owner": {k: o.get(k) for k in ("session", "since", "last_seen")} if o else None,
                "owner_live": self.owner_live(o), "sessions": self.two_sessions(o), "queued": queued(self), "busy": self.busy() or bool(run),
                "run": {"started": run.get("started"), "resume": bool(run.get("resume"))} if run else None, "agentd": agentd.daemon_state(),
                "calling": self.calling(), "failed": agentd.failed(self), "backoff": agentd.backoff(self)}
        if not p.exists(): info.update(online=info["busy"], last_seen=None)
        else:
            mt = p.stat().st_mtime; age = time.time() - mt
            # a supervised run that ended (or died after 10 s) is not "online" for 5 more minutes: online = a run goes on, a live owner, or
            # a session seen lately that is not the run that just ended (QA 2026-10-29)
            last = agentd._read(agentd.run_path(self)) or {}
            gone = bool(last.get("ended")) and agentd._ts(last.get("ended")) >= mt - 5 and not info["owner_live"]
            info.update(online=info["busy"] or info["owner_live"] or (age < ONLINE_SECS and not gone),
                        last_seen=datetime.fromtimestamp(mt).isoformat(timespec="seconds"))
        info["phase"] = phase(self.events() if evs is None else evs, info)
        return info

    def _cursor(self):
        p = self.dir / ".agent_cursor"; return p.read_text(encoding="utf-8").strip() if p.exists() else None

    def _new(self, evs):
        cur = self._cursor(); ids = [e["id"] for e in evs]
        return [e for e in (evs[ids.index(cur) + 1:] if cur in ids else evs) if e["from"] == "user" and e.get("source") == "ui"]

    def unread(self):
        """User events the session has not read yet (typed in the browser; terminal / import events are already known)."""
        return self._new(self.events())

    def read(self):
        """-> (readable lines, raw events); advances the cursor and appends the user's verbatim words to feedback/answers.md."""
        evs = self.events()
        if not evs: return [], []
        mine = self._new(evs); lines = [self.render(e) for e in mine]
        words = [e for e in mine if not e.get("auto")]                       # page-generated lines are not the user's words
        if words: self.to_answers_md([(e, self.render(e, md=True)) for e in words])
        if self._cursor() != evs[-1]["id"]:
            (self.dir / ".agent_cursor").write_text(evs[-1]["id"], encoding="utf-8"); (self.dir / ".agent_read_at").write_text(now(), encoding="utf-8")
        self.seen()
        return lines, mine

    # ---- rendering ----
    def lookup(self):
        def y(p):
            try: return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except Exception: return {}
        board = y(self.root / layout.REMEMBER / "board.yaml").get("experience_board", {})
        people = y(self.root / layout.REMEMBER / "people.yaml").get("people", [])
        return {"owner": y(self.root / layout.CONFIG / "project.yaml").get("owner"),"moments": {m["id"]: m.get("title", m["id"]) for m in board.get("moments", [])},
                "people": {p["id"]: p.get("name") or p["id"] for p in people}}

    def ctx_text(self, c, lk=None):
        lk = lk or self.lookup(); k = c.get("kind")
        if k == "moment": return f"时刻：{lk['moments'].get(c.get('id')) or c.get('label') or c.get('id')}"
        if k == "person": return f"人物：{lk['people'].get(c.get('id')) or c.get('label') or c.get('id')}"
        if k == "video":
            n = re.sub(r"\D", "", str(c.get("m", ""))); t = float(c.get("t") or 0)
            return f"试玩 第 {n or c.get('m', '?')} 版 {int(t // 60)}:{int(t % 60):02d}" + (f"（画面：{c['frame']}）" if c.get("frame") else "")
        if k == "file": return f"文件：{c.get('path')}"
        if k == "check": return f"检查：{c.get('label') or c.get('id')}"
        if k == "region": return f"画面框选：{c.get('m')} {c.get('label') or c.get('file')} {c.get('box')}"
        if k == "plan": return f"方案条目 {c.get('id')}：{c.get('label')}"
        return str(c.get("label") or c)

    def render(self, e, md=False):
        """One user event as a readable line. md=True: the answers.md form (verbatim words + context in parentheses)."""
        lk = self.lookup()
        # a collaborator's words (hub): say who wrote them; the owner's own words stay as before
        who = f"【{e.get('author_name') or e['author']}】" if e.get("author") and e["author"] != lk.get("owner") else ""
        if e["type"] == "text":
            if e.get("auto") and not md: return who + "（页面操作）" + e["text"] + self._ctx_suffix(e, lk)
            ctx = "；".join(self.ctx_text(c, lk) for c in e.get("context") or [])
            if md: return who + ((e["text"] + (f"（{ctx}）" if ctx else "")) if e["text"] else ctx)
            return who + e["text"] + (f"\n    [{ctx}]" if ctx else "")
        if e["type"] == "answer":
            card = self._any_card(e["card_id"])
            title = card["title"] if card else e["card_id"]
            body = self.answer_text(card, e["answer"]) if card else json.dumps(e["answer"], ensure_ascii=False)
            if card and card.get("kind") == "task": return f"{who}对《{title}》：{body}"
            return f"{who}对《{title}》的回答：{body}"
        return e.get("text", "")

    def _ctx_suffix(self, e, lk):
        ctx = "；".join(self.ctx_text(c, lk) for c in e.get("context") or [])
        return f"\n    [{ctx}]" if ctx else ""

    def _any_card(self, cid):
        for e in self.events():
            if e["id"] == cid and e["type"] == "card": return e["card"]

    def answer_text(self, card, a):
        k = card["kind"]; note = f"；补充：{a['note']}" if a.get("note") else ""
        if k == "permission": return ("同意" if a.get("decision") == "yes" else "不同意") + note
        if k == "task": return ("做好了" if a.get("done") else "稍后") + (f"：{a['note']}" if a.get("note") else "")
        if k == "go":
            rn = next((r for r in card.get("runners") or [] if r["id"] == a.get("runner")), None)
            how = f"（用 {rn['harness']} + {rn['model']}，runner={rn['id']}）" if rn and a.get("decision") == "start" else ""
            if a.get("decision") == "start" and a.get("playtest_rounds"): how += f"（最多 {a['playtest_rounds']} 轮试玩）"
            return ("开始" if a.get("decision") == "start" else "先等等") + how + note
        if k == "questions":
            s = "；".join(f"{n}. {v}" for n, v in (a.get("answers") or {}).items() if str(v).strip())
            sk = a.get("skipped") or []
            return (s or "（都没答）") + (f"；跳过：{'、'.join(str(x) for x in sk)}" if sk else "")
        if k == "understanding":
            if a.get("ok") and not a.get("edits"): return "都对，没有要改的" + note
            if not a.get("edits"): return f"有意见（没改条目）：{a.get('note', '')}"
            pts = {str(p["id"]): p["text"] for p in card["points"]}
            return "；".join(f"“{pts.get(str(i), i)}”改成：{t}" for i, t in (a.get("edits") or {}).items()) + note
        if k in ("options", "candidates"):
            names = {str(i["key"]): i["title"] for i in card["items"]}; pk = a.get("picked") or []
            return ("、".join(f"{x}（{names.get(str(x), x)}）" for x in pk) if pk else ("都不要" if k == "candidates" else "没选")) + note
        return json.dumps(a, ensure_ascii=False)

    # ---- feedback/answers.md ----
    def to_answers_md(self, items):
        """items: [(event, text)]; lines go under the day's "## <date> 对话（界面）" heading (created if missing, inside its own section)."""
        f = self.root / layout.FEEDBACK / "answers.md"; f.parent.mkdir(exist_ok=True)
        text = f.read_text(encoding="utf-8") if f.exists() else "# 你的回答\n"
        by_day = {}
        for e, t in items:
            line = "- " + t.replace("\n", "\n  ")
            by_day.setdefault(e["at"][:10], []).append(line)
        for day, lines in by_day.items():
            head = f"## {day} 对话（界面）"; body = "\n".join(lines) + "\n"
            m = re.search(rf"^{re.escape(head)}[^\n]*\n", text, re.M)
            if not m: text = text.rstrip("\n") + f"\n\n{head}\n\n{body}"; continue
            nxt = re.search(r"^## ", text[m.end():], re.M)
            end = m.end() + nxt.start() if nxt else len(text)
            sec = text[m.end():end].rstrip("\n") + "\n" + body
            text = text[:m.end()] + sec + ("\n" if nxt else "") + text[end:]
        f.write_text(text, encoding="utf-8")

    # ---- import ----
    def import_answers(self):
        """Seed history from feedback/answers.md: each "## <date> <title>" round becomes one user event (source import, at = that date).
        Rounds already imported (same text) are skipped; nothing is invented on the agent's side."""
        f = self.root / layout.FEEDBACK / "answers.md"
        if not f.exists(): raise CardError(f"没有 {f}")
        have = {e.get("text") for e in self.events() if e.get("source") == "import"}
        n = 0
        for m in re.finditer(r"^## (\d{4}-\d\d-\d\d) ([^\n]*)\n(.*?)(?=^## |\Z)", f.read_text(encoding="utf-8"), re.M | re.S):
            day, title, body = m.groups(); body = body.strip()
            if not body or "对话（界面）" in title or body in have: continue
            self.append({"from": "user", "type": "text", "text": body, "source": "import", "round": title.strip(), "at": f"{day}T12:00:00"}); n += 1
        return n
