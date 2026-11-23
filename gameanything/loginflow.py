"""`gameanything lab login steam|microsoft|ea`: the user signs in to THEIR OWN store account inside their sandbox, with live progress in
their language and the watchdog (watchdog.py) on every wait (added 2026-10-29, from the user-sandbox Steam and Minecraft tests).

    gameanything lab login steam     [--project P | --container C] [--app APPID] [--install] [--lang zh|en] [--json] [--timeout S] [--status]
    gameanything lab login microsoft [--project P | --container C] ...
    gameanything lab login ea        [--project P | --container C | --local] [--install] ...   The Sims 4 (verified in the lab 2026-10-29)
    gameanything lab consent --app APPID|ea|ea_ts4_terms [--project P] --yes [--note TEXT] [--click-for-me --words "同意，帮我点"]
                                     record that the user said yes to a publisher agreement (watchdog.record_consent); they still
                                     click Accept themselves in the viewer, unless they said "click it for me" for that dialog just
                                     now (--click-for-me: the watchdog clicks it once within 15 min, logged with a screenshot)

Steam:     check the sandbox (the container answers, ga-steam is in the image, the 1-second mount-namespace probe, the screen) ->
           start the client (first start: Debian's installer notice, a ~500 MB self-update, usually 5-20 min) -> the sign-in window
           (the viewer URL; "tick Remember me"; "approve Steam Guard on your phone") -> signed in -> the game's licence
           (`ga-steam owns`; with --install: the install itself, watched: Install window, publisher EULA, 0 bps, commit)
Microsoft: check -> a saved sign-in still valid? (`ga-mc account status --recheck`, no code needed) -> else `ga-mc account login` in
           the background (one at a time: an existing one is reused) -> the code + microsoft.com/link for the user's own phone; an
           expired code is replaced by itself and the new one is shown -> signed in -> owns Minecraft: Java Edition?
EA App:    check (ga-ea in the sandbox, the screen) -> first time: `ga-ea setup` (Wine + mono + gecko + DXVK) and the installer, whose
           first page is EA's User Agreement (the user clicks LET'S GO; never clicked for them: exit 4 until they do) -> the app starts
           (later: `ga-ea start`, the saved login signs in by itself in ~30 s) -> the sign-in form (DesktopFSM awaitingAuthentication;
           no screenshot) -> authenticated -> The Sims 4 in the account? linked from Steam = the EA App cannot download it (exit 4,
           the reason said plainly) -> with --install: the user clicks DOWNLOAD, the folder size is reported

Every state is read INSIDE the sandbox (docker exec: processes, windows, logs/steamui_login.txt WaitingForCredentials, the account
folder), never from host-cached files. Nothing the user types is read, logged or captured (no screenshot while a sign-in window is open);
tokens stay in the sandbox's data volume and are never printed. `--json`: one JSON event per line (both languages), the result last.

Exit codes: 0 signed in (and owned when checked), 1 failed, 2 usage, 3 refused (a resident run), 4 needs the user (a question was
printed: a licence, a missing sandbox option), 5 the sandbox is not running, 6 unsupported (no ga-steam / ga-ea / ga-mc), 7 not owned, 8 timeout,
9 EA: the app says ANOTHER store manages the game (gameStatus managedBy != EA; a linked account's externalSource alone does not
count: 10-29 it was STEAM and the EA App downloaded the game itself): the EA App cannot download it; the JSON result has
external_source, external_store and next_command (the Steam download).
"""
import json
import os
import re
import sys
import time
from pathlib import Path

from . import hiccups, watchdog
from . import osdirs

CODES = {"ok": 0, "failed": 1, "usage": 2, "refused": 3, "needs_user": 4, "down": 5, "unsupported": 6, "not_owned": 7, "timeout": 8,
         "other_store": 9}
# EA: the game came from another store (externalSource): what to run instead (verified only up to the hand-off, 2026-10-29)
OTHER_STORE_NEXT = {"STEAM": "gameanything lab login steam --project {project} --app 1222670 --install"}
STEAM_TIMEOUT, MS_TIMEOUT = 3600, 1800
POLL = 5
MC_LOGIN_START = ("mkdir -p /sandbox/logs /sandbox/run && cd /sandbox && "
                  "setsid nohup ga-mc account login --wait {wait} > /sandbox/logs/mc-login.log 2>&1 < /dev/null & "
                  "echo $! > /sandbox/run/mc-login.pid; echo started")
SCREEN_TOOLS = ("ga-sdv", "ga-ksp", "ga-sts", "ga-mc")

MSG = {
    "checking": {"zh": "正在检查沙箱 {box} ……", "en": "Checking the sandbox {box} ..."},
    "down": {"zh": "沙箱 {box} 没有在运行：先启动它（docker start {box}）再来。", "en": "The sandbox {box} is not running: start it (docker start {box}) and try again."},
    "no_steam": {"zh": "这个沙箱的镜像里没有 Steam：用 `gameanything lab setup --image {game}` 重新拉取（能从 Steam 下载的游戏，镜像里都带 Steam 层）。",
                 "en": "This sandbox image has no Steam: get it again with `gameanything lab setup --image {game}` (the image of every game that can come from Steam has the Steam layer)."},
    "no_mc": {"zh": "这个沙箱不是 Minecraft 沙箱（里面没有 ga-mc）。", "en": "This is not a Minecraft sandbox (no ga-mc in it)."},
    "screen": {"zh": "先打开沙箱的屏幕和查看器 ……", "en": "Starting the sandbox's screen and viewer first ..."},
    "no_screen": {"zh": "沙箱的屏幕起不来，Steam 没地方显示：看一下 /sandbox/logs/xvfb.log 或 xorg.log。",
                  "en": "The sandbox's screen does not come up, so Steam has nowhere to show: see /sandbox/logs/xvfb.log or xorg.log."},
    "steam_start_first": {"zh": "启动 Steam。这是第一次：Steam 会先自我更新（约 500 MB，一般 5–20 分钟），之后才出登录窗口；现在不用点任何东西。",
                          "en": "Starting Steam. This is the first start: Steam updates itself first (about 500 MB, usually 5-20 min); the "
                                "sign-in window comes after that. You do not need to click anything yet."},
    "steam_start_again": {"zh": "启动 Steam（已经装好了，一般 30–60 秒）。", "en": "Starting Steam (already installed, usually 30-60 s)."},
    "steam_running": {"zh": "Steam 已经在运行。", "en": "Steam is already running."},
    "before_login": {"zh": "登录前要知道：你在查看器 {viewer} 里自己输入账号密码，我看不到也不保存；勾上「记住我」，以后不用再登录；手机上准备好 Steam 令牌，要你确认一下。",
                     "en": "Before you sign in: you type your account and password yourself in the viewer {viewer}; I cannot see them "
                           "and nothing is saved. Tick 'Remember me' so you do not have to sign in again; keep your phone ready for Steam Guard."},
    "auto_logon": {"zh": "用保存的登录自动登录中（一般 30–60 秒，不用输入）……", "en": "Signing in with the saved login (usually 30-60 s, nothing to type) ..."},
    "waiting_you": {"zh": "在等你登录 ……", "en": "Waiting for you to sign in ..."},
    "signed_in": {"zh": "已登录 {store}。", "en": "Signed in to {store}."},
    "already": {"zh": "已经登录着 {store}，不用再登录。", "en": "Already signed in to {store}; no new sign-in needed."},
    "owns": {"zh": "{game} 在你的账号里。", "en": "{game} is in your account."},
    "owns_unknown": {"zh": "还看不出 {game} 在不在你的 Steam 库里（Steam 不把许可列表写成能读的文件）。下载那一步会知道：出 Install 窗口 = 有；出带价格的商店页面 = 没有。",
                     "en": "I cannot tell yet whether {game} is in your Steam library (Steam keeps its licence list unreadable). The "
                           "download step shows it: an Install window = owned; a store page with a price = not owned."},
    "not_owned": {"zh": "{game} 不在你登录的账号里：请换成买了它的账号。", "en": "{game} is not in the account you signed in with: please use the account that owns it."},
    "eula_ahead": {"zh": "提前说一下：安装 {game} 时 Steam 会显示「{publisher}」的协议（{agreement}，{url}）。请你自己读了再决定点不点 Accept，我不会替你点。",
                   "en": "Heads-up: installing {game}, Steam will show {publisher}'s agreement ({agreement}, {url}). Read it and decide "
                         "yourself whether to click Accept; I will not click it for you."},
    "install_start": {"zh": "请 Steam 安装 {game}（app {app}）……", "en": "Asking Steam to install {game} (app {app}) ..."},
    "install_progress": {"zh": "下载 {game}：{pct}%（{done} / {total} MB）", "en": "Downloading {game}: {pct}% ({done} / {total} MB)"},
    "installed": {"zh": "{game} 已经装好了。", "en": "{game} is installed."},
    "ms_reuse": {"zh": "沙箱里已经有一个微软登录在等，继续用它（不再开第二个，免得出两个代码）。",
                 "en": "A Microsoft sign-in is already waiting in the sandbox: using it (not a second one, which would show a second code)."},
    "ms_start": {"zh": "向微软要一个登录代码 ……", "en": "Asking Microsoft for a sign-in code ..."},
    "ms_new_code": {"zh": "上一个代码过期了，新代码：{mc_code}（还是在 {mc_url} 输入）。", "en": "The last code expired. New code: {mc_code} (enter it at {mc_url} as before)."},
    "ms_failed": {"zh": "微软登录没成功：{why}", "en": "The Microsoft sign-in did not work: {why}"},
    "timeout": {"zh": "等了 {elapsed} 还没完成（{phase}）。请在查看器里看一眼，告诉我你看到了什么。", "en": "Not done after {elapsed} ({phase}). Please look at the viewer and tell me what you see."},
    "no_ea": {"zh": "这个沙箱里没有 ga-ea（EA App 工具）：模拟人生 4 的沙箱要带它（lab/images/common/ga-ea）。",
              "en": "This sandbox has no ga-ea (the EA App tool): a Sims 4 sandbox needs it (lab/images/common/ga-ea)."},
    "ea_setup": {"zh": "第一次：在沙箱里装 Wine 和 EA App 要用的组件（约 1–2 分钟，约 300 MB），现在不用点任何东西。",
                 "en": "First time: installing Wine and what the EA App needs in the sandbox (about 1-2 min, about 300 MB); nothing to click yet."},
    "ea_setup_failed": {"zh": "Wine 环境没装好：{why}", "en": "Setting up Wine did not work: {why}"},
    "ea_install_app": {"zh": "启动 EA App 安装程序。它第一页是 EA 用户协议，要你自己决定。", "en": "Starting the EA App installer. Its first page is EA's User Agreement: your decision."},
    "ea_start": {"zh": "启动 EA App（已经装好了，一般 10–30 秒）。", "en": "Starting the EA App (already installed, usually 10-30 s)."},
    "ea_before_login": {"zh": "EA 的登录窗口出来了：请在查看器 {viewer} 里用你买了模拟人生 4 的 EA 账号登录。邮箱、密码、邮件或手机验证码都由你自己输入，我看不到也不保存，登录窗口开着时不截图。勾上「记住我」，以后不用再登录。",
                        "en": "EA's sign-in window is up: in the viewer {viewer} sign in with the EA account that owns The Sims 4. You type the "
                              "e-mail, password and any e-mail / phone code yourself; I cannot see them, nothing is saved and no screenshot is "
                              "taken while the sign-in window is open. Tick 'Remember me' so you do not have to sign in again."},
    "ea_owns_unknown": {"zh": "还看不出 {game} 在不在你的 EA 库里；下载那一步会知道。", "en": "I cannot tell yet whether {game} is in your EA library; the download step will show it."},
    "ea_install_start": {"zh": "请在查看器里打开 EA App 的「Library」，点 {game}，再点蓝色的「DOWNLOAD」（基础游戏几十 GB，看网速十几分钟到一小时以上）。我盯着下载进度。",
                         "en": "In the viewer open the EA App's Library, click {game}, then the blue DOWNLOAD (the base game is tens of GB: 15 min "
                               "to over an hour, depending on the network). I am watching the progress."},
    "ea_install_progress": {"zh": "下载 {game}：已 {done} GB", "en": "Downloading {game}: {done} GB so far"},
    "resident": {"zh": "常驻 agent 不能在沙箱里启动 Steam 或登录：请用户自己的 agent（或构建 agent）来做；可以用 --status 只看状态。",
                 "en": "A resident agent may not start Steam or a sign-in in a sandbox: the user's own agent (or a builder) does it; --status only reads the state."},
    "status": {"zh": "状态：{state}", "en": "State: {state}"},
}
STORE = {"steam": "Steam", "microsoft": "Microsoft", "ea": "EA App"}


def T(key, **kw) -> dict:
    return {k: watchdog.fmt(MSG[key][k], kw) for k in ("zh", "en")}


class Flow:
    """One login run: where to talk (say / emit), the sandbox (box), time (clock / sleep; fakes in the tests)."""

    def __init__(self, box, store, lang="en", say=None, emit=None, clock=time.time, sleep=time.sleep, evidence=None, viewer=None,
                 game=None, title=None, app=None, timeout=None, consent=None, install=False, poll=POLL, stall_s=60, heartbeat_s=110,
                 box_name="?", ea_root=None, project=None):
        self.box, self.store, self.lang = box, store, lang if lang in ("zh", "en") else "en"
        self.say_fn, self.emit_fn = say or (lambda m: print(m, flush=True)), emit or (lambda e: None)
        self.clock, self.sleep, self.evidence, self.viewer = clock, sleep, evidence, viewer or "http://localhost:6080/vnc.html"
        self.game, self.title, self.app, self.install, self.poll = game, title or game or "", app, install, poll
        self.timeout = timeout or (STEAM_TIMEOUT if store in ("steam", "ea") else MS_TIMEOUT)
        self.consent, self.stall_s, self.heartbeat_s, self.box_name = consent or {}, stall_s, heartbeat_s, box_name
        self.ea_root, self.project = ea_root, project
        self.events = []

    def out(self, kind, words, **kw):
        ev = {"kind": kind, "at": int(self.clock()), "zh": words["zh"], "en": words["en"], **kw}
        self.events.append(ev); self.emit_fn(ev); self.say_fn(words[self.lang])
        return ev

    def result(self, state, words=None, **kw):
        r = {"result": True, "store": self.store, "state": state, "code": CODES[state], "sandbox": self.box_name, **kw}
        if words: r.update(zh=words["zh"], en=words["en"]); self.out("result", words, state=state)
        return r

    def dog(self, flow, phase, **ctx):
        return watchdog.Watchdog(self.box, flow, phase, lang=self.lang, say=self.say_fn, emit=lambda e: (self.events.append(e), self.emit_fn(e)),
                                 ctx={"viewer": self.viewer, "game": self.title, **({"app": self.app} if self.app else {}), **ctx},
                                 evidence=self.evidence, stall_s=self.stall_s, heartbeat_s=self.heartbeat_s, clock=self.clock,
                                 consent=self.consent, actions={"mc_login_again": MC_LOGIN_START.format(wait=MS_TIMEOUT)},
                                 root=self.ea_root if flow == "ea" else None)

    def sh(self, script, timeout=90): return self.box.sh(script, timeout)

    def has(self, tool): return self.sh(f"command -v {tool} >/dev/null 2>&1 && echo yes || echo no", 30)[1].strip().endswith("yes")

    def jsn(self, script, timeout=90):
        """The JSON object a tool printed: the whole output (ga-steam status --json is indented over many lines), else the last line
        that is an object. Only a dict counts: line by line, an indented list item ("  1070560", "  null") parsed as a number or None
        (2026-10-29: a crash once Steam had apps, and before that a false "first start")."""
        rc, out = self.sh(script, timeout)
        out = (out or "").strip()
        try:
            v = json.loads(out)
            if isinstance(v, dict): return v
        except ValueError: pass
        for line in reversed(out.splitlines()):
            try: v = json.loads(line)
            except ValueError: continue
            if isinstance(v, dict): return v
        return None


# ---------------------------------------------------------------- Steam
def screen_up(fl) -> bool:
    rc, out = fl.sh('xdpyinfo -display "${DISPLAY:-:99}" >/dev/null 2>&1 && echo x=1 || echo x=0', 30)
    if "x=1" in out: return True
    tool = next((t for t in SCREEN_TOOLS if fl.has(t)), None)
    if not tool: return False
    fl.out("progress", T("screen"), phase="check")
    fl.sh(f"{tool} up", 120)
    return "x=1" in fl.sh('xdpyinfo -display "${DISPLAY:-:99}" >/dev/null 2>&1 && echo x=1 || echo x=0', 30)[1]


def steam(fl, status_only=False) -> dict:
    fl.out("progress", T("checking", box=fl.box_name), phase="check")
    st = getattr(fl.box, "state", lambda: "up")()
    if st != "up": return fl.result("down", T("down", box=fl.box_name))
    if not fl.has("ga-steam"): return fl.result("unsupported", T("no_steam", game=fl.game or "<game>"))
    s = fl.jsn("ga-steam status --json") or {}
    if status_only:
        state = "signed_in" if s.get("logged_on_since_start") else ("login_window" if s.get("login_window") else
                                                                     ("updating" if s.get("updating") else ("running" if s.get("running") else "stopped")))
        return fl.result("ok", T("status", state=state), status=state, steam=s)
    dog = fl.dog("steam", "check")
    dog.probe_ns = True
    r = dog.tick()
    dog.probe_ns = False
    if r["stop"]: return fl.result("needs_user", None, why=r["stop"]["id"])
    if not screen_up(fl): return fl.result("failed", T("no_screen"))
    if s.get("logged_on_since_start"):
        fl.out("progress", T("already", store="Steam"), phase="login")
    else:
        if not s.get("running"):
            first = not s.get("client_installed")
            fl.out("progress", T("steam_start_first" if first else "steam_start_again"), phase="start")
            fl.sh("ga-steam start", 60)
        else:
            fl.out("progress", T("steam_running"), phase="start")
        r = wait_steam_logon(fl, dog, cached=bool(s.get("login_cache")))
        if r: return r
    return steam_after_login(fl)


def wait_steam_logon(fl, dog, cached):
    t0 = fl.clock(); said_wait = said_auto = False
    dog.set_phase("start")
    while fl.clock() - t0 < fl.timeout:
        r = dog.tick()
        f = r["facts"]
        if r["stop"]: return fl.result("needs_user", None, why=r["stop"]["id"])
        if f.get("logged_on"):
            fl.out("progress", T("signed_in", store="Steam"), phase="login"); return None
        if f.get("bootstrap_stage") or f.get("updater_window") or f.get("installer_dialog"): dog.set_phase("updating")
        elif f.get("login_window"):
            dog.set_phase("login")
            if not said_wait:
                if not cached: fl.out("progress", T("before_login", viewer=fl.viewer), phase="login")
                fl.out("progress", T("waiting_you"), phase="login"); said_wait = True
        elif cached and f.get("webhelper"):
            dog.set_phase("auto_logon")
            if not said_auto: fl.out("progress", T("auto_logon"), phase="auto_logon"); said_auto = True
        fl.sleep(fl.poll)
    ph = hiccups.PHASES.get(dog.phase, {})
    return fl.result("timeout", T("timeout", elapsed=watchdog.human_s(fl.clock() - t0, fl.lang), phase=ph.get(fl.lang, dog.phase)))


def steam_after_login(fl):
    if not fl.app: return fl.result("ok", None, signed_in=True, owned=None)
    e = hiccups.EULAS.get(int(fl.app))
    if e: fl.out("progress", T("eula_ahead", game=e["game"], publisher=e["publisher"], agreement=e["agreement"], url=e["url"]), phase="ownership", eula=e)
    o = fl.jsn(f"ga-steam owns {int(fl.app)} --json") or {}
    if o.get("owned") is False:
        return fl.result("not_owned", T("not_owned", game=fl.title), signed_in=True, owned=False, how=o.get("how"))
    if o.get("owned") and not fl.install:
        fl.out("progress", T("owns", game=fl.title), phase="ownership")
        return fl.result("ok", None, signed_in=True, owned=True, how=o.get("how"))
    if not fl.install:
        fl.out("progress", T("owns_unknown", game=fl.title), phase="ownership")
        return fl.result("ok", None, signed_in=True, owned=None, how=o.get("how"))
    return steam_install(fl)


def steam_install(fl):
    app = int(fl.app)
    dog = fl.dog("steam", "install", install_requested_at=fl.clock())
    pre = dog.tick()
    if pre["facts"].get("app_installed"):
        fl.out("progress", T("installed", game=fl.title), phase="install"); return fl.result("ok", None, signed_in=True, owned=True, installed=True)
    fl.out("progress", T("install_start", game=fl.title, app=app), phase="install")
    fl.sh(f"ga-steam install {app}", 90)
    dog.ctx["install_requested_at"] = fl.clock()
    t0, last_pct = fl.clock(), -1
    while fl.clock() - t0 < fl.timeout:
        fl.sleep(fl.poll)
        r = dog.tick()
        f = r["facts"]
        if r["stop"]:
            owned = False if r["stop"]["id"] == "steam_not_owned" else None
            return fl.result("not_owned" if owned is False else "needs_user", None, why=r["stop"]["id"], signed_in=True, owned=owned)
        if f.get("app_installed"):
            fl.out("progress", T("installed", game=fl.title), phase="install")
            return fl.result("ok", None, signed_in=True, owned=True, installed=True)
        if f.get("app_downloading") and f.get("app_bytes_total") and f["app_pct"] >= last_pct + 10:
            last_pct = f["app_pct"] - f["app_pct"] % 10
            fl.out("progress", T("install_progress", game=fl.title, pct=f["app_pct"], done=f["app_bytes_dl"] // 2 ** 20,
                                 total=f["app_bytes_total"] // 2 ** 20), phase="install", pct=f["app_pct"])
    return fl.result("timeout", T("timeout", elapsed=watchdog.human_s(fl.clock() - t0, fl.lang), phase=hiccups.PHASES["install"][fl.lang]))


# ---------------------------------------------------------------- Microsoft (Minecraft)
def microsoft(fl, status_only=False) -> dict:
    fl.out("progress", T("checking", box=fl.box_name), phase="check")
    st = getattr(fl.box, "state", lambda: "up")()
    if st != "up": return fl.result("down", T("down", box=fl.box_name))
    if not fl.has("ga-mc"): return fl.result("unsupported", T("no_mc"))
    s = fl.jsn("ga-mc account status") or {}
    if status_only:
        return fl.result("ok", T("status", state="signed_in" if s.get("signed_in") else "signed_out"), status=s)
    if s.get("signed_in"):
        rc, out = fl.sh("ga-mc account status --recheck", 120)
        lines = [ln for ln in (out or "").splitlines() if ln.strip().startswith("{")]
        failed = any('"recheck"' in ln for ln in lines)
        try: r = json.loads(lines[-1]) if lines else {}
        except ValueError: r = {}
        if r.get("signed_in") and r.get("owns_java") and not failed:
            fl.out("progress", T("already", store="Microsoft"), phase="login")
            fl.out("progress", T("owns", game="Minecraft: Java Edition"), phase="ownership")
            return fl.result("ok", None, signed_in=True, owned=True)
    dog = fl.dog("microsoft", "login")
    f = watchdog.facts(watchdog.collect(fl.box, "microsoft"))          # facts only: no automatic action before the start
    if f.get("mc_login_procs"): fl.out("progress", T("ms_reuse"), phase="login")
    else:
        fl.out("progress", T("ms_start"), phase="login")
        fl.sh(MC_LOGIN_START.format(wait=int(fl.timeout)), 30)
    t0, code, seen = fl.clock(), None, False
    while fl.clock() - t0 < fl.timeout:
        fl.sleep(fl.poll)
        r = dog.tick()
        f = r["facts"]
        if r["stop"]: return fl.result("needs_user", None, why=r["stop"]["id"])
        if f.get("mc_code"):
            seen = True
            if code and f["mc_code"] != code: fl.out("progress", T("ms_new_code", mc_code=f["mc_code"], mc_url=f["mc_url"]), phase="login")
            code = f["mc_code"]
        if seen and not f.get("mc_login_procs") and not f.get("mc_code"):
            break
        if not seen and not f.get("mc_login_procs") and fl.clock() - t0 > 30:
            break
    else:
        return fl.result("timeout", T("timeout", elapsed=watchdog.human_s(fl.clock() - t0, fl.lang), phase=hiccups.PHASES["ms_code"][fl.lang]))
    s = fl.jsn("ga-mc account status") or {}
    if not s.get("signed_in"):
        tail = watchdog.redact((fl.sh("tail -n 3 /sandbox/logs/mc-login.log", 30)[1] or "").strip())[-300:]
        return fl.result("failed", T("ms_failed", why=tail or "-"))
    fl.out("progress", T("signed_in", store="Microsoft"), phase="login")
    dog.set_phase("ownership")
    r = dog.tick()
    if not s.get("owns_java"):
        if not r["stop"]: fl.out("needs_user", watchdog.say_of(hiccups.entry("ms_not_owned"), fl.lang, {}), id="ms_not_owned")
        return fl.result("not_owned", None, signed_in=True, owned=False)
    fl.out("progress", T("owns", game="Minecraft: Java Edition"), phase="ownership")
    return fl.result("ok", None, signed_in=True, owned=True)


# ---------------------------------------------------------------- EA App (The Sims 4), verified in the lab 2026-10-29
def ea_status(fl) -> dict:
    return fl.jsn("ga-ea status --json", 120) or {}


def ea_home():
    """The EA App's folder INSIDE the sandbox (ga-ea's HOME): GA_EA_HOME when set, else /sandbox/ea as in every image. 2026-10-31: None
    sent the watchdog to ~/.steam/debian-installation, so it never read EADesktop.log: no "signed in" (every own-sandbox EA login ran
    into its timeout) and no "sign-in window open" (one stall screenshot was taken while it was)."""
    return os.environ.get("GA_EA_HOME") or "/sandbox/ea"


def ea(fl, status_only=False) -> dict:
    fl.out("progress", T("checking", box=fl.box_name), phase="check")
    st = getattr(fl.box, "state", lambda: "up")()
    if st != "up": return fl.result("down", T("down", box=fl.box_name))
    if not fl.has("ga-ea"): return fl.result("unsupported", T("no_ea", game=fl.game or "sims4"))
    s = ea_status(fl)
    if status_only:
        state = ("signed_in" if s.get("signed_in") else "login_window" if s.get("login_window") else "running" if s.get("app_running")
                 else "installing_app" if s.get("installer_running") else "stopped" if s.get("app_installed") else "not_installed")
        return fl.result("ok", T("status", state=state), status=state, ea=s)
    if not screen_up(fl): return fl.result("failed", T("no_screen"))
    dog = fl.dog("ea", "check")
    if not s.get("app_installed"):
        if not s.get("installer_running"):
            fl.out("progress", T("ea_setup"), phase="start")
            rc, out = fl.sh("ga-ea setup", 1800)
            if rc != 0: return fl.result("failed", T("ea_setup_failed", why=watchdog.redact((out or "").strip()[-300:]) or "-"))
            fl.out("progress", T("ea_install_app"), phase="start")
            dog.ctx["ea_started_at"] = fl.clock()
            fl.sh("ga-ea install-app", 60)
        r = ea_wait(fl, dog, lambda f: f.get("ea_app_running"), "ea_start")
        if r: return r
    elif not s.get("app_running"):
        fl.out("progress", T("ea_start"), phase="start")
        dog.ctx["ea_started_at"] = fl.clock()
        fl.sh("ga-ea start", 60)
    if s.get("signed_in"):
        fl.out("progress", T("already", store="EA"), phase="login")
    else:
        said = [False]

        def signed(f):
            if f.get("ea_login_window") and not said[0]:
                dog.set_phase("ea_login")
                fl.out("progress", T("ea_before_login", viewer=fl.viewer), phase="login"); fl.out("progress", T("waiting_you"), phase="login")
                said[0] = True
            return f.get("ea_signed_in")
        r = ea_wait(fl, dog, signed, "ea_start")
        if r: return r
        fl.out("progress", T("signed_in", store="EA"), phase="login")
    return ea_after_login(fl, dog)


def ea_wait(fl, dog, done, phase):
    t0 = fl.clock()
    dog.set_phase(phase)
    while fl.clock() - t0 < fl.timeout:
        r = dog.tick()
        if r["stop"]: return fl.result("needs_user", None, why=r["stop"]["id"])
        if done(r["facts"]): return None
        fl.sleep(fl.poll)
    ph = hiccups.PHASES.get(dog.phase, {})
    return fl.result("timeout", T("timeout", elapsed=watchdog.human_s(fl.clock() - t0, fl.lang), phase=ph.get(fl.lang, dog.phase)))


def ea_after_login(fl, dog):
    o = fl.jsn("ga-ea owns --json", 120) or {}
    src = o.get("source")
    if o.get("other_store") and src:              # entitlement data only: another store MANAGES the game (not just a linked account)
        e = hiccups.entry("ea_steam_owned")
        store = {"STEAM": "Steam", "EPIC": "Epic Games"}.get(src, src.title())
        nxt = OTHER_STORE_NEXT.get(src, "").format(project=fl.project or "<project>")
        w = {k: watchdog.say_of(e, k, {"game": ("模拟人生 4" if k == "zh" and fl.game == "sims4" else fl.title or "The Sims 4"),
                                        "ea_store_name": store})[k] for k in ("zh", "en")}
        if nxt: w = {k: w[k] + (f" 下一步：{nxt}" if k == "zh" else f" Next: {nxt}") for k in w}
        fl.out("needs_user", w, id=e["id"], external_source=src)
        return fl.result("other_store", None, why=e["id"], signed_in=True, owned=True, external_source=src, external_store=store,
                         next_command=nxt or None, zh=w["zh"], en=w["en"])
    if o.get("owned") is False: return fl.result("not_owned", T("not_owned", game=fl.title or "The Sims 4"), signed_in=True, owned=False)
    if o.get("owned") is None and not fl.install:
        fl.out("progress", T("ea_owns_unknown", game=fl.title or "The Sims 4"), phase="ownership")
        return fl.result("ok", None, signed_in=True, owned=None)
    if o.get("installed"):
        fl.out("progress", T("installed", game=fl.title or "The Sims 4"), phase="install")
        return fl.result("ok", None, signed_in=True, owned=True, installed=True)
    if o.get("owned"): fl.out("progress", T("owns", game=fl.title or "The Sims 4"), phase="ownership")
    if not fl.install: return fl.result("ok", None, signed_in=True, owned=o.get("owned"))
    return ea_install(fl, dog)


def ea_install(fl, dog):
    game = fl.title or "The Sims 4"
    fl.out("progress", T("ea_install_start", game=game), phase="install")
    dog.set_phase("ea_install")
    t0, last = fl.clock(), -1
    while fl.clock() - t0 < fl.timeout:
        fl.sleep(fl.poll)
        r = dog.tick()
        f = r["facts"]
        if r["stop"]: return fl.result("needs_user", None, why=r["stop"]["id"], signed_in=True)
        if f.get("ea_game_installed"):
            fl.out("progress", T("installed", game=game), phase="install")
            return fl.result("ok", None, signed_in=True, owned=True, installed=True)
        gb = (f.get("ts4_bytes") or 0) / 2 ** 30                 # the game folder on disk (the app writes no readable percentage)
        if gb >= last + 2:
            last = gb
            fl.out("progress", T("ea_install_progress", game=game, done=round(gb, 1)), phase="install", gb=round(gb, 1))
    return fl.result("timeout", T("timeout", elapsed=watchdog.human_s(fl.clock() - t0, fl.lang), phase=hiccups.PHASES["ea_install"][fl.lang]))


FLOWS = {"steam": steam, "microsoft": microsoft, "ea": ea}


# ---------------------------------------------------------------- the command
def resident_run(env=None) -> bool:
    env = os.environ if env is None else env
    return bool(env.get("GAMEANYTHING_INSTANCE")) and env.get("GAMEANYTHING_ROLE") != "builder"


def containers_for(store, game) -> list:
    from . import sandbox
    img = sandbox.IMAGES.get(game or ("minecraft" if store == "microsoft" else "stardew"), game or "stardew")
    return [f"ga-{img}-steam", f"ga-{img}"] if store == "steam" else [f"ga-{img}"]


def viewer_of(box) -> str:
    eng = getattr(box, "engine", None)
    if eng is not None:
        try:
            rc, out = eng._run(["port", box.name, "6080/tcp"], 20)
            m = re.search(r":(\d+)\s*$", (out or "").strip().splitlines()[0]) if rc == 0 and out.strip() else None
            if m: return f"http://localhost:{m.group(1)}/vnc.html"
        except Exception: pass
    return "http://localhost:6080/vnc.html"


def main(argv) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="gameanything lab login", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("store", choices=sorted(FLOWS))
    ap.add_argument("--project", default=None, help="the project (its game, language and sandbox)")
    ap.add_argument("--container", default=None, help="the sandbox container (default: ga-<game>-steam / ga-<game>, ga-minecraft)")
    ap.add_argument("--app", type=int, default=None, help="Steam: the appid to check (default: the project game's steam_appid)")
    ap.add_argument("--install", action="store_true", help="Steam / EA: download the game after the sign-in, watched")
    ap.add_argument("--lang", choices=["zh", "en"], default=None, help="the user's language (default: the project's lang, else en)")
    ap.add_argument("--json", action="store_true", help="one JSON event per line, the result last (both languages)")
    ap.add_argument("--timeout", type=float, default=None)
    ap.add_argument("--status", action="store_true", help="only read the state, start nothing")
    ap.add_argument("--viewer", default=None, help="the viewer URL to tell the user (default: from docker port, else localhost:6080)")
    ap.add_argument("--evidence", type=Path, default=None, help="where stall snapshots and screenshots go")
    ap.add_argument("--local", action="store_true", help="run inside the sandbox itself (its own processes and screen), not via docker exec")
    a = ap.parse_args(argv)
    root = cfg = None
    if a.project:
        from . import projects
        root = projects.resolve(a.project); cfg = projects.config_of(root)
    cfg = cfg or {}
    lang = a.lang or (cfg.get("lang") if cfg.get("lang") in ("zh", "en") else "en")
    say = (lambda m: print(m, file=sys.stderr, flush=True)) if a.json else (lambda m: print(f"[login] {m}", flush=True))
    emit = (lambda e: print(osdirs.json_text(e), flush=True)) if a.json else None
    if resident_run() and not a.status:
        w = MSG["resident"]; say(w[lang])
        if a.json: print(osdirs.json_text({"result": True, "state": "refused", "code": 3, **w}))
        return CODES["refused"]
    game = cfg.get("game") or ("minecraft" if a.store == "microsoft" else None)
    title, app = game, a.app
    if game:
        from . import games as registry
        spec = registry.games().get(game) or {}
        title = getattr(spec, "title", None) or game
        if app is None and a.store == "steam": app = spec.get("steam_appid")
    elif app is not None and a.store == "steam":  # --container C --app N without a project: the game of that appid (10-29: "还看不出  在不在")
        from . import games as registry
        for gid, spec in registry.games().items():
            if spec.get("steam_appid") == app: game, title = gid, getattr(spec, "title", None) or gid; break
        else: title = f"Steam app {app}"
    if a.store == "ea" and not game: game, title = "sims4", "The Sims 4"      # the EA App flow is for The Sims 4
    if a.local:                                   # inside the sandbox itself (docker-rt refuses the snapshot exec from outside)
        box, name = watchdog.LocalBox(), os.environ.get("HOSTNAME", "local")
    else:
        from .labup import Engine
        eng = Engine()
        names = [a.container] if a.container else (containers_for(a.store, game) if game else [])
        if not names:
            say({"zh": "要指定 --project 或 --container", "en": "give --project or --container"}[lang]); return CODES["usage"]
        name = next((n for n in names if eng.state(n) == "up"), names[0])
        box = watchdog.DockerBox(name, eng)
    if True:
        day = time.strftime("%Y-%m-%d")
        ev = a.evidence or ((root / "5_build" / "setup-watch" / day) if root else Path.home() / ".cache" / "gameanything" / "setup-watch" / day)
        cons = {**watchdog.consents(consent_file()), **(watchdog.consents(consent_file(root)) if root else {})}   # the user's own + the project's
        fl = Flow(box, a.store, lang, say, emit, evidence=ev, viewer=a.viewer or viewer_of(box), game=game, title=title, app=app,
                  timeout=a.timeout, consent=cons, install=a.install, box_name=name, ea_root=ea_home(), project=a.project)
        r = FLOWS[a.store](fl, status_only=a.status)
    if a.json: print(osdirs.json_text(r))
    return r["code"]


def consent_file(root=None) -> Path:
    return (Path(root) / "config" / "consents.json") if root else Path.home() / ".config" / "gameanything" / "consents.json"


def consent_main(argv) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="gameanything lab consent", description="record that the USER said yes to a publisher agreement "
                                 "(they still click Accept themselves; nothing is clicked for them)")
    ap.add_argument("--app", required=True, help="the Steam appid, or 'ea' for the EA App's User Agreement"); ap.add_argument("--project", default=None)
    ap.add_argument("--yes", action="store_true", help="the user said yes in their own words (required)"); ap.add_argument("--note", default="")
    ap.add_argument("--click-for-me", action="store_true", help="the user said, just now and for THIS dialog, 'agree, click it for me' "
                    "(valid 15 min; needs --words)")
    ap.add_argument("--words", default="", help="the user's own words, e.g. 「同意，帮我点」")
    a = ap.parse_args(argv)
    if not a.yes: print("[consent] only with --yes, after the user said yes themselves", file=sys.stderr); return CODES["usage"]
    a.app = int(a.app) if str(a.app).isdigit() else str(a.app)
    if a.app not in hiccups.EULAS: print(f"[consent] no known publisher agreement for app {a.app}", file=sys.stderr); return CODES["usage"]
    root = None
    if a.project:          # a GameAnything project -> its config/consents.json; a lab-lease project name (e.g. steam-dl) -> the user's file
        from . import projects
        try: root = projects.resolve(a.project)
        except SystemExit: print(f"[consent] {a.project} is not a GameAnything project: recording it in the user's file, tagged with it")
    if a.click_for_me and not a.words.strip():
        print("[consent] --click-for-me needs --words: the user's own words for this dialog", file=sys.stderr); return CODES["usage"]
    c = watchdog.record_consent(consent_file(root), a.app, note=a.note, click_for_me=a.click_for_me, words=a.words, project=a.project)
    print(f"[consent] recorded: {c['publisher']} {c['agreement']} ({c['url']}) at {c['at']}"
          f"{' click-for-me (15 min)' if c['click_for_me'] else ''} -> {consent_file(root)}")
    return 0
