"""What the background work of a project is doing, told to her by agentd itself (no agent has to remember to report).

agentd calls these every scan (builds.py while a builder runs, agentd.py for resident runs and paid generation):

    Live.build(e, T, m, r)          a running builder: its activity (activity.Tail over the builder's log), STATUS.yaml item changes, the
                                    playtest round, new screenshots (under 5_build/<m>/, and the pictures the builder looked at), and
                                    stalled / paused (usage limit, login) / slow-step alerts -> ONE live card in her chat (key live-<m>,
                                    from GameAnything, updated in place) + a short status line only for the moments that matter (started, paused,
                                    stalled, ended). Throttled: the card at most every CARD_EVERY_SECS (CARD_NOW_SECS when only the
                                    activity line changed), alerts and the end at once.
    Live.build_end(e, T, m, r, …)   the end: done / stopped / paused by the limit / died, into the card and one status line
    Live.resident(e, T, run)        a resident run that is slow to answer: paused by a usage limit / login, or quiet for STALL_SECS
    Live.gen(e, T)                  a paid generation whose log stays quiet for STALL_SECS
    now_state(root, lang)           what the 工作台 / Now panel shows (the page polls /api/now)

Files: conversation/.activity/<run>.jsonl + <run>.json (activity.py; the build's live state is under "live" there),
conversation/files/now_<run>_<n>.jpg (small copies of the pictures a builder looked at, at most SHOTS_KEEP per run).
"""
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from . import clock
from . import activity as A
from .conversation import CardError, now

STALL_SECS = 600
SLOW_TOOL_SECS = 1800
CARD_EVERY_SECS = 120
CARD_NOW_SECS = 300
FILES_EVERY_SECS = 60
NATIVE_SHOT_SECS = 60
SHOTS_KEEP = 12
THUMB_PX = 960
PROVIDER_NAME = {"claude-code": "Claude", "codex": "Codex", "opencode": "OpenCode", "gemini": "Gemini", "dsh": "DeepSeek Harness"}


def _read(p):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError): return None


def _ts(s) -> float:
    try: return clock.epoch(s)
    except (TypeError, ValueError): return 0.0


def _hm(mins) -> tuple:
    n = int(round(mins or 0)); h, m = divmod(n, 60)
    return (f"{h} 小时 {m} 分" if h else f"{m} 分钟"), (f"{h} h {m} min" if h else f"{m} min")


def run_label(r) -> str:
    """The agent and model a build runs with, for the card: "Claude · opus" (the model the builder was started with, builds.py)."""
    from . import models
    p = r.get("provider") or ""; m = models.shown_model(p, r.get("model") or "")
    return PROVIDER_NAME.get(p, p) + (f" · {m}" if m and p else "")


def where(r) -> tuple:
    """Where a build runs, in words: (zh, en)."""
    if r.get("build_mode") == "native": return "你的电脑上", "on your computer"
    lease = str(r.get("lease") or "")
    m = re.match(r"^[^/]+/[^/]+/([^:]+):(.+)$", lease)
    if m:
        sb, seat = m.group(1), m.group(2)
        if seat in ("whole", "all", "-"): return f"服务器沙箱 {sb}", f"the server sandbox {sb}"
        return f"服务器沙箱 {sb}（座位 {seat}）", f"the server sandbox {sb} (seat {seat})"
    return "服务器沙箱", "a server sandbox"


def go_estimate(T, gid):
    """[min, max] hours of the go card's estimate (the runner she picked, else the card's), or None."""
    for e in T.events():
        if e.get("id") == gid and e.get("type") == "card":
            c = e.get("card") or {}; ans = next((a for a in reversed(T.events()) if a.get("type") == "answer" and a.get("card_id") == gid), None)
            rid = ((ans or {}).get("answer") or {}).get("runner")
            rs = c.get("runners") or []; R = next((x for x in rs if x.get("id") == rid), None) or next((x for x in rs if x.get("recommended")), None)
            est = (R or {}).get("estimate") or c.get("estimate") or {}
            w = est.get("wall_h")
            if isinstance(w, list) and len(w) == 2: return [float(w[0]), float(w[1])]
            if c.get("eta_hours"): return [float(c["eta_hours"])] * 2
    return None


def items_of(root, m) -> list:
    """STATUS.yaml items that belong to this build (not done yet, or done in it): [{id, text, text_en, state, evidence}]."""
    from . import devstatus
    try: d, _ = devstatus.load(root)
    except Exception: return []
    out = []
    for x in d.get("items") or []:
        st = x.get("state") or "todo"
        if st == "done" and str(x.get("since") or "") not in (m, "") and str(x.get("build") or "") != m: continue
        out.append({"id": str(x.get("id")), "text": str(x.get("text") or ""), "text_en": str(x.get("text_en") or ""), "state": st,
                    "evidence": str(x.get("evidence") or "")})
    return out


def step_state(s) -> str: return "done" if s == "done" else "current" if s == "partial" else "todo"


def media_url(root, f) -> str:
    """/media/<rel> for a picture in the project's work folders the page may show, else ''."""
    from . import layout
    try: r = Path(f).resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError): return ""
    return f"/media/{r}" if layout.media_file(root, r) is not None else ""


def evidence_pics(root, m, text) -> list:
    out = []
    for p in re.findall(r"[\w./\-]+\.(?:png|jpe?g|webp)", str(text or ""), re.I):
        for base in (Path(root) / "5_build" / m, Path(root) / "5_build" / m / "play", Path(root) / "5_build", Path(root)):
            u = media_url(root, base / p) if (base / p).is_file() else ""
            if u: out.append(u); break
    return out


class Live:
    def __init__(self, log=None, clock=time.time):
        self.tails = {}; self.log = log or (lambda m: None); self.clock = clock
        self.paused = {}                   # provider -> {resets, since, project}: the last usage limit any run hit (agentd's heartbeat)

    def tail(self, root, run_id, log, provider, role) -> A.Tail:
        k = f"{root}|{run_id}"; t = self.tails.get(k)
        if t is None or str(t.log) != str(log):
            t = A.Tail(root, run_id, log, provider, role, clock=self.clock); self.tails[k] = t
        return t

    def forget(self, root, run_id): self.tails.pop(f"{root}|{run_id}", None)

    def _status(self, T, zh, en, kind):
        try: T.append({"from": "system", "type": "status", "text": zh, "text_en": en, "live": kind})
        except OSError: pass

    def _note_pause(self, t, root, new=()):
        """The last usage limit of each provider (agentd's heartbeat: the page says when every agent is paused); cleared by later work."""
        p = t.state.get("pause")
        if p and p.get("kind") == "limit": self.paused[t.provider] = {"resets": p.get("resets"), "since": p.get("since"), "project": Path(root).name}
        elif not p and any(x.get("kind") in ("tool", "edit", "look", "wait") for x in new): self.paused.pop(t.provider, None)

    # ---------------------------------------------------------------- builds
    def build(self, e, T, m, r):
        root = Path(e["path"]); rid = r.get("run_id") or "build"
        t = self.tail(root, rid, r.get("log"), r.get("provider") or "claude-code", "builder")
        new = t.step(); self._note_pause(t, root, new)
        S = t.state.setdefault("live", {}); clk = self.clock(); urgent = False; major = False
        if not S.get("announced"):
            S["announced"] = now(); S["m"] = m
            wz, we = where(r); n = r.get("playtest_rounds")
            est = go_estimate(T, r.get("go_card")); S["est_h"] = est
            ez = f"，预计 {est[0]:g}–{est[1]:g} 小时" if est and est[0] != est[1] else f"，预计 {est[0]:g} 小时" if est else ""
            ee = f", about {est[0]:g}-{est[1]:g} h" if est and est[0] != est[1] else f", about {est[0]:g} h" if est else ""
            k = len(r.get("resume_logs") or [])
            if k: self._status(T, f"后台构建接着做了：{m}（第 {k} 次接着上次停下的地方），在{wz}。", f"The background build goes on: {m} (resume {k}), on {we}.", "build_start")
            else: self._status(T, f"后台构建开始了：{m}，最多 {n} 轮试玩，在{wz}{ez}。点卡片上的「看工作台」随时看它在做什么。",
                              f"The background build started: {m}, at most {n} playtest rounds, on {we}{ee}. Open the work view from the card any time.", "build_start")
            urgent = True
            self._ask_view(T, m, r)
        # her requirements (STATUS.yaml): what changed since the last scan
        items = items_of(root, m); prev = S.get("items")
        cur = {x["id"]: x["state"] for x in items}
        if prev is not None and cur != prev:
            major = True
            for x in items:
                if prev.get(x["id"]) != x["state"] and x["state"] in ("done", "partial"):
                    for u in evidence_pics(root, m, x["evidence"]): self._shot(S, u, x["text"][:40])
        S["items"] = cur
        rd = r.get("rounds")
        if rd != S.get("round"): S["round"] = rd; major = True
        # pictures: the ones the builder looked at (small copies), and new ones under 5_build/<m>/
        for im in t.images[-2:]:
            u = self._thumb(root, rid, im["path"], S)
            if u: self._shot(S, u, im["zh"]); major = True
        if clk - float(S.get("files_at") or 0) >= FILES_EVERY_SECS:
            S["files_at"] = clk
            for u in self._new_files(root, m, r, S): self._shot(S, u, ""); major = True
        if r.get("build_mode") == "native": self._native_shot(root, m, r, S)
        # alerts
        alert = self._alert(t, alive=True)
        ak = (alert or {}).get("kind")
        if ak != S.get("alert"):
            if ak == "pause" and (t.state.get("pause") or {}).get("since") != S.get("paused"):
                S["paused"] = t.state["pause"]["since"]
                self._status(T, "后台构建暂停了：" + alert["text"], "The background build is paused: " + alert["text_en"], "build_pause")
            elif ak == "auth":
                self._status(T, "后台构建停下了：" + alert["text"], "The background build stopped: " + alert["text_en"], "build_auth")
            elif ak == "stall" and S.get("stalled") != t.state.get("grew_at"):
                S["stalled"] = t.state.get("grew_at")
                self._status(T, "后台构建可能卡住了：" + alert["text"], "The background build may be stuck: " + alert["text_en"], "build_stall")
            S["alert"] = ak; urgent = True
        last = S.get("card_at") or 0; nowline = (t.state.get("now") or {}).get("zh")
        due = urgent or (major and clk - last >= CARD_EVERY_SECS) or (nowline != S.get("card_now") and clk - last >= CARD_NOW_SECS)
        if due: self._card(T, m, r, S, t, alert)
        t.save()
        return new

    def _alert(self, t, alive=True): return alert_of(t, alive)

    def _ask_view(self, T, m, r):
        """Once per build: may she watch the game? (liveview.py; nothing is shown before her yes)"""
        from . import liveview
        if liveview.asked(T.root, m): return
        lab = r.get("build_mode") == "lab"
        card = {"kind": "permission", "key": liveview.key(m), "title": "要不要看游戏的实时画面？" if lab else "要不要每分钟看一眼游戏窗口？",
                "to": "只有能打开这个项目的人（这台电脑上的 GameAnything 页面）",
                "will_send": ["游戏的实时画面，在「工作台」里（只能看、不能点）"] if lab else ["游戏窗口的截图，每分钟一张，在「工作台」里（只截游戏窗口，不截别的）"],
                "will_not_send": ["不对外公开，别人看不到", "不能操作游戏，不会打扰构建", "随时可以在工作台里关掉"]}
        en = {"title": "Watch the game live?" if lab else "A look at the game window every minute?", "to": "Only people who can open this project (the GameAnything page on this computer)",
              "will_send": ["The live game picture, in the work view (view only, no clicks)"] if lab else ["A screenshot of the game window every minute, in the work view (the game window only)"],
              "will_not_send": ["Not public; nobody else sees it", "Nobody can control the game; the build is not disturbed", "You can turn it off any time in the work view"]}
        try: T.system_card(card, en)
        except Exception as x: self.log(f"{T.root.name}: live view question not posted ({x})")

    def _native_shot(self, root, m, r, S):
        """Native build, after her yes: a picture of ONLY the game window GameAnything opened, every NATIVE_SHOT_SECS (never brings it to the front)."""
        from . import liveview
        if self.clock() - float(S.get("native_at") or 0) < NATIVE_SHOT_SECS or not liveview.consent(root, m): return
        S["native_at"] = self.clock()
        try:
            from . import native, projects
            from .native import hands
            g = native.get(r.get("game") or projects.game_of(root))
            d = Path(root) / "conversation" / "files"; d.mkdir(parents=True, exist_ok=True); out = d / f".now_native_{m}.png"
            hands.shot(root, g, out)
            u = self._thumb(root, f"native_{m}", out, S); out.unlink(missing_ok=True)
            if u: self._shot(S, u, "游戏窗口")
        except Exception: pass                                        # no window yet / she closed it / this computer cannot: skip quietly

    def _shot(self, S, url, label):
        shots = S.setdefault("shots", [])
        if any(x.get("url") == url for x in shots): return
        shots.append({"url": url, "at": now(), "label": A.clean(label, 40)}); del shots[:-SHOTS_KEEP]

    def _thumb(self, root, rid, path, S):
        """A small copy of a picture the builder looked at -> /conv/now_<run>_<n>.jpg (at most SHOTS_KEEP kept)."""
        p = Path(path) if Path(str(path)).is_absolute() else Path(root) / str(path)
        try:
            if not p.is_file() or p.suffix.lower() not in A.IMAGE or p.stat().st_size > 40 << 20: return None
            from PIL import Image
            n = int(S.get("thumbs") or 0) + 1; S["thumbs"] = n
            d = Path(root) / "conversation" / "files"; d.mkdir(parents=True, exist_ok=True)
            out = d / f"now_{rid}_{n}.jpg"
            with Image.open(p) as im:
                im.thumbnail((THUMB_PX, THUMB_PX)); im.convert("RGB").save(out, "JPEG", quality=82)
            for old in sorted(d.glob(f"now_{rid}_*.jpg"), key=lambda f: f.stat().st_mtime)[:-SHOTS_KEEP]: old.unlink(missing_ok=True)
            return f"/conv/{out.name}"
        except Exception:
            return None

    def _new_files(self, root, m, r, S) -> list:
        """The newest pictures saved under 5_build/<m>/ since the last look (at most 2), as /media/ URLs."""
        base = Path(root) / "5_build" / m; since = max(_ts(r.get("started")), float(S.get("files_mtime") or 0)); best = []; n = 0
        if not base.is_dir(): return []
        for dp, dns, fns in os.walk(base):
            dns[:] = [d for d in dns if not d.startswith(".") and Path(dp, d).relative_to(base).as_posix().count("/") < 4]
            for fn in fns:
                n += 1
                if n > 4000: break
                if not fn.lower().endswith((".png", ".jpg", ".jpeg", ".webp")): continue
                f = Path(dp) / fn
                try: mt = f.stat().st_mtime
                except OSError: continue
                if mt > since: best.append((mt, f))
        best.sort()
        if best: S["files_mtime"] = best[-1][0]
        return [u for _, f in best[-2:] for u in [media_url(root, f)] if u]

    def _card(self, T, m, r, S, t, alert, final=None):
        items = items_of(T.root, m)
        steps = [{"text": A.clean(x["text"], 48), "state": step_state(x["state"])} for x in items][:12]
        steps_en = [{"text": A.clean(x["text_en"] or x["text"], 48), "state": step_state(x["state"])} for x in items][:12]
        if not steps:
            steps = [{"text": "构建 agent 在工作", "state": "done" if final == "done" else "current"}]
            steps_en = [{"text": "The builder is working", "state": steps[0]["state"]}]
        started = _ts(r.get("started")); el = max(0, (self.clock() if not final else _ts(r.get("ended")) or self.clock()) - started) / 60 if started else 0
        wz, we = where(r); prov = run_label(r)
        meter = {"round": int(r.get("rounds") or 0), "max_rounds": int(r.get("playtest_rounds") or 0), "elapsed_min": round(el),
                 "wall_min": round(float(r.get("wall_hours") or 5) * 60), "runner": f"{prov} · {wz}".strip(" ·"), "done": bool(final)}
        if S.get("est_h"): meter["est_h"] = S["est_h"]
        nw = t.state.get("now") or {}
        card = {"kind": "progress", "key": f"live-{m}", "milestone": m, "title": "后台构建 · 现在", "steps": steps, "meter": meter,
                "open": "#now", "live": True, "images": [x["url"] for x in (S.get("shots") or [])[-3:]]}
        if nw.get("zh") and not final: card.update(now=nw["zh"], now_en=nw.get("en") or nw["zh"], now_at=str(nw.get("at") or ""))
        if alert: card["alert"] = {"kind": alert["kind"], "text": alert["text"], "text_en": alert.get("text_en") or alert["text"]}
        en = {"title": "Background build · now", "steps": steps_en, "meter": {**meter, "runner": f"{prov} · {we}".strip(" ·")}}
        try:
            T.system_card(card, en); S["card_at"] = self.clock(); S["card_now"] = nw.get("zh")
        except (CardError, OSError) as x:
            card.pop("images", None)
            try: T.system_card(card, en); S["card_at"] = self.clock(); S["card_now"] = nw.get("zh")
            except (CardError, OSError): self.log(f"{T.root.name}: live card for {m} not posted ({x})")

    def build_end(self, e, T, m, r, state, ok, problems=""):
        root = Path(e["path"]); rid = r.get("run_id") or "build"
        t = self.tail(root, rid, r.get("log"), r.get("provider") or "claude-code", "builder"); t.step()
        S = t.state.setdefault("live", {})
        if S.get("ended"): return
        S["ended"] = now(); p = t.state.get("pause"); last = (t.state.get("now") or {})
        prov = PROVIDER_NAME.get(r.get("provider"), r.get("provider") or "")
        if ok: kind, zh, en = "done", f"后台构建做好了：{m}（build check 通过）。驻场 agent 会发成果卡给你。", f"The background build is done: {m} (build check passed). The agent will send you the result card."
        elif p and p.get("kind") == "limit":
            rz = f"，大约 {A.hhmm(p['resets'])} 恢复" if p.get("resets") else ""
            kind, zh, en = "pause", f"后台构建停了：{prov} 的用量到上限{rz}。{m} 还没做完。", f"The background build stopped: the {prov} usage limit was reached{(' (resets around ' + A.hhmm(p['resets'], 'en') + ')') if p.get('resets') else ''}. {m} is not finished."
        elif p and p.get("kind") == "auth": kind, zh, en = "auth", f"后台构建停了：{prov} 的登录失效了。{m} 还没做完。", f"The background build stopped: the {prov} login expired. {m} is not finished."
        elif state == "stopped": kind, zh, en = "stopped", f"后台构建到了时间上限，停下了：{m} 还没交付。", f"The background build reached its time limit and was stopped: {m} is not delivered."
        elif state == "interrupted": kind, zh, en = "died", f"后台构建在后台重启时中断了：{m}，结果不确定。", f"The background build was interrupted by a restart: {m}, the outcome is unclear."
        else:
            lz = f"最后一步是「{last.get('zh')}」。" if last.get("zh") else ""
            kind, zh, en = "died", f"后台构建停了：{m} 还没交付（构建 agent 退出了，退出码 {r.get('rc')}）。{lz}", f"The background build stopped: {m} is not delivered (the builder exited, code {r.get('rc')})."
        self._status(T, zh, en, "build_end")
        self._card(T, m, r, S, t, {"kind": kind, "text": zh, "text_en": en}, final=kind)
        t.save(); self.forget(root, rid)

    # ---------------------------------------------------------------- residents: a reply that does not come
    def resident(self, e, T, run):
        root = Path(e["path"]); rid = run.get("run_id")
        if not rid or not run.get("log"): return None
        t = self.tail(root, rid, run.get("log"), run.get("agent_provider") or "claude-code", "resident"); self._note_pause(t, root, t.step())
        S = t.state.setdefault("live", {}); a = self._alert(t, alive=True)
        if a and a["kind"] in ("pause", "auth") and not S.get("said_pause"):
            S["said_pause"] = now()
            tail_zh = "到时候会自动接着回复你。" if a["kind"] == "pause" else "请协调者帮忙重新登录。"
            tail_en = "It will answer by itself after that." if a["kind"] == "pause" else "Ask the coordinator to log in again."
            self._status(T, f"agent 现在回复不了：{a['text']}。{tail_zh}", f"The agent cannot answer right now: {a['text_en']}. {tail_en}", "resident_pause")
        elif a and a["kind"] == "stall" and S.get("said_stall") != t.state.get("grew_at"):
            S["said_stall"] = t.state.get("grew_at")
            self._status(T, f"agent 好像卡住了：{a['text']} 超过 45 分钟会自动停下重来。", f"The agent seems stuck: {a['text_en']} After 45 minutes it is stopped and started again.", "resident_stall")
        t.save()
        return t

    def resident_end(self, root, run):
        rid = run.get("run_id")
        if not rid: return None
        t = self.tail(root, rid, run.get("log"), run.get("agent_provider") or "claude-code", "resident"); t.step(); self.forget(root, rid)
        return t.state

    # ---------------------------------------------------------------- paid generation
    def gen(self, e, T):
        from . import genrun
        for gid, r in (genrun.used(T.root) or {}).items():
            if r.get("state") != "running" or not r.get("log"): continue
            try: q = self.clock() - Path(r["log"]).stat().st_mtime
            except OSError: q = self.clock() - _ts(r.get("started"))
            said = T.dir / ".activity" / f"gen-{gid}.said"
            if q >= STALL_SECS and not said.exists():
                said.parent.mkdir(parents=True, exist_ok=True); said.write_text(now(), encoding="utf-8")
                mz, me = _hm(q / 60)
                self._status(T, f"付费生成（{r.get('script')}）已经 {mz}没有新进展了，可能在等服务排队，也可能卡住了。", f"The paid generation ({r.get('script')}) shows no progress for {me}: it may wait in the service's queue, or be stuck.", "gen_stall")


def alert_of(t, alive=True):
    """The banner of a run from its tail: pause (usage limit) / auth / stall / slow step, or None."""
    p = t.state.get("pause"); prov = PROVIDER_NAME.get(t.provider, t.provider)
    if p and p.get("kind") == "auth":
        return {"kind": "auth", "text": f"{prov} 的登录失效了，需要重新登录", "text_en": f"the {prov} login expired; it needs a new login"}
    if p:
        r = p.get("resets")
        return {"kind": "pause", "text": f"{prov} 的用量到上限了" + (f"，大约 {A.hhmm(r)} 恢复" if r else "，要等额度恢复"),
                "text_en": f"the {prov} usage limit is reached" + (f"; it resets around {A.hhmm(r, 'en')}" if r else "; waiting for it to reset"), "resets": r}
    if not alive: return None
    q = t.quiet_secs(); last = t.state.get("now") or t.state.get("last") or {}
    lz, le = last.get("zh") or "开始工作", last.get("en") or "starting"
    if q >= STALL_SECS:
        mz, me = _hm(q / 60); bg = " 它在等一个后台任务。" if t.state.get("bg") else ""
        return {"kind": "stall", "text": f"已经 {mz}没有新动静，最后一步是「{lz}」。{bg}".replace("  ", " ").strip(),
                "text_en": f"nothing new for {me}; the last step was \"{le}\"." + (" It is waiting for a background task." if t.state.get("bg") else "")}
    o = t.open_tool()
    if o and o[0] >= SLOW_TOOL_SECS:
        mz, me = _hm(o[0] / 60)
        return {"kind": "slow", "text": f"这一步已经 {mz}了：{o[1].get('zh')}", "text_en": f"this step has taken {me}: {o[1].get('en')}"}
    return None


# ---------------------------------------------------------------- the 工作台 / Now panel
def now_state(root, lang="zh") -> dict:
    """{build, resident, paused, agentd}: the panel's data (/api/now). Never raises on a half-written file."""
    from . import builds, agentd
    from .conversation import Thread
    root = Path(root); T = Thread(root); en = lang == "en"; out = {"build": None, "resident": None, "paused": None, "at": now()}
    pick = lambda x, k="": (x.get(k + "en") if en and x.get(k + "en") else x.get(k + "zh")) if x else None
    try:
        m, r = builds.current(root)
        if r is None:                                                  # the newest one that ended in the last 12 hours
            rec = [(mm, rr) for mm, rr in builds.records(root) if rr.get("ended") and time.time() - _ts(rr.get("ended")) < 12 * 3600]
            if rec: m, r = max(rec, key=lambda x: _ts(x[1].get("ended")))
        if r is not None:
            st = A.state(root, r.get("run_id") or "build"); S = st.get("live") or {}
            tl = A.lines(root, r.get("run_id") or "build", 60)
            started = _ts(r.get("started")); end = _ts(r.get("ended")) if r.get("ended") else time.time()
            wz, we = where(r)
            t = A.Tail(root, r.get("run_id") or "build", r.get("log"), r.get("provider") or "claude-code", "builder")
            alert = alert_of(t, alive=r.get("state") == "running") if st else None
            items = items_of(root, m)
            out["build"] = {
                "m": m, "state": r.get("state"), "why": r.get("why"), "round": r.get("rounds"), "max_rounds": r.get("playtest_rounds"),
                "started": r.get("started"), "ended": r.get("ended"), "elapsed_min": round((end - started) / 60) if started else None,
                "wall_h": r.get("wall_hours"), "est_h": S.get("est_h") or go_estimate(T, r.get("go_card")), "where": we if en else wz,
                "provider": PROVIDER_NAME.get(r.get("provider"), r.get("provider")), "model": r.get("model") or None, "runner": run_label(r), "build_mode": r.get("build_mode"), "lease": r.get("lease"),
                "now": pick(st.get("now")), "now_at": (st.get("now") or {}).get("at"), "quiet_min": round(t.quiet_secs() / 60) if st.get("grew_at") else None,
                "alert": {"kind": alert["kind"], "text": alert["text_en"] if en else alert["text"]} if alert else None,
                "items": [{"id": x["id"], "text": (x["text_en"] if en and x["text_en"] else x["text"]), "state": x["state"]} for x in items],
                "shots": list(reversed(S.get("shots") or []))[:6],
                "timeline": [{"at": x.get("at"), "kind": x.get("kind"), "text": pick(x), "n": x.get("n")} for x in reversed(tl)][:60]}
        if r is not None:
            from . import liveview
            run_ = r.get("state") == "running"
            out["live"] = {"possible": run_ and r.get("build_mode") == "lab" and bool(r.get("lease")), "on": liveview.consent(root, m), "mode": r.get("build_mode")}
    except Exception as x:                                             # the panel never breaks on a bad file
        out["error"] = f"{type(x).__name__}"
    try:
        run = agentd.active_run(T)
        if run:
            st = A.state(root, run.get("run_id")); tl = A.lines(root, run.get("run_id"), 12)
            out["resident"] = {"started": run.get("started"), "why": run.get("why"), "now": pick(st.get("now")),
                               "timeline": [{"at": x.get("at"), "kind": x.get("kind"), "text": pick(x)} for x in reversed(tl)]}
    except Exception: pass
    try:
        hb = _read(agentd.heartbeat_path()) or {}
        ps = [v for v in (hb.get("paused") or {}).values() if v and (not v.get("resets") or float(v["resets"]) > time.time())]
        if ps: out["paused"] = {"resets": ps[0].get("resets"), "resets_hm": A.hhmm(ps[0]["resets"]) if ps[0].get("resets") else None}
        out["agentd"] = agentd.daemon_state()["alive"]
    except Exception: pass
    return out
