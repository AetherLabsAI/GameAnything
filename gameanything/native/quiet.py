"""本机模式少打扰 (2026-10-24): in native mode the game runs on HER computer, so agents open it only with her yes, as
seldom as possible, and close only what they opened.

    policy(root) / set_policy(ref, mode, window, minutes, drive)
                         config/project.yaml `native_launch: ask | window | always | idle` (default ask), `native_launch_window:
                         "22:00-08:00"` (local time; used by `window`, and for the card's 「今晚 HH:MM 后」), `native_launch_idle_minutes: 10`
                         (`idle` = 「我没在用电脑时」: open only after she has not touched mouse / keyboard that long; idle.py; when this
                         computer cannot tell, it asks with the card instead) and `native_drive: idle | always` (may `gameanything native drive`
                         press keys in the game GameAnything opened while she is at the computer; hands.py; default idle = only when she is away),
                         `native_front: never | away` (Windows: may drive bring ONLY the game GameAnything opened to the front while she has been
                         away DRIVE_IDLE_SECS; her decision 2026-11-01; default never) and `native_hands: agent | self` (「不给，我自己点」 on the
                         readiness card, ready.py: agents never call drive, she clicks; default agent)
    decide(root, g)      may the game be opened now? -> {state: go | pending | refused, why, ...}; in `ask` mode it posts the card
                         「要开游戏测一下，现在可以吗？」 (现在可以 / 等我说 / 今晚 HH:MM 后) and only her answer on it in the thread (from the
                         page, the newest one, not used for an earlier launch, at most YES_VALID_SECS old) lets a launch through
    launch(root, g)      decide, then the small-window settings, open the game (Steam link; macOS in the background), record it
    close(root, g)       end ONLY a game GameAnything opened (the process ids recorded at launch, same start time); a game she opened is never closed
                         (native_drive: always: one she opened is taken over - see current() - and asked to quit, never SIGTERMed).
                         macOS: the app's own Quit first (like Cmd-Q; SIGTERM made Stardew Valley show 「quit unexpectedly」 on her Mac),
                         SIGTERM only when it is still open after QUIT_WAIT_SECS (Java games: SIGTERM at once, Game.mac_quit)
    launches(root)       the record: what was opened when, for which round (the progress card says how many launches a round used)
    small_window(g) / restore_window(g)   per-game settings files changed for a test launch (key by key, backed up) and put back after

The ledger is <project>/conversation/.native_launch.json; the window backups are <data>/native/window/<game>.json. Texts in TEXTS are the
Chinese source keys the page translates (i18n.js)."""
import json
import os
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from .. import games as registry, layout, osdirs, projects
from ..conversation import Thread
from . import idle as idlemod
from .games import Game, NativeError, _run

POLICIES = ("ask", "window", "always", "idle")
DRIVES = ("idle", "always")
FRONTS = ("never", "away")                  # native_front (Windows): kept apart from native_drive on purpose - drive: always means "also while she
                                            # is at the computer", front: away means "only while she is away"; one key could not say both (2026-11-01)
HANDS = ("agent", "self")                   # native_hands: who presses the keys / clicks in a test (ready.py)
DEFAULT_WINDOW = "22:00-08:00"
DEFAULT_IDLE_MIN = 10                       # `idle`: she has not touched the computer for this many minutes
CARD_KEY = "native-launch"
SESSION = "m2w-native"                      # the card is posted by the tool, not by an agent session (builders never post in chats)
YES_VALID_SECS = 2 * 3600                   # a 「现在可以」 older than this is stale: ask again
LATER_VALID_SECS = 10 * 3600                # 「今晚 22:00 后」 holds this long after 22:00
ADOPT_SECS = 15 * 60                        # a game process that appears this soon after GameAnything opened it is the one GameAnything opened
CLOSE_WAIT_SECS = 30
QUIT_WAIT_SECS = 20                         # macOS: how long the app's own Quit may take before SIGTERM

TEXTS = {   # the 「什么时候开游戏」 dialog in the project menu (manage.js) and its errors
    "什么时候开游戏", "在你自己的电脑上测试时，agent 要开、关你的游戏。选它什么时候可以开：", "每次先问我",
    "开游戏前在对话里发一张卡，你点「现在可以」才开（推荐）", "只在这个时间段", "比如夜里你不用电脑的时候；其他时间不开，也不问你", "随时可以",
    "不问你，直接开；两次之间至少隔 10 分钟，一轮尽量只开一次", "从", "到", "只在「我的电脑（本机）」模式下用到；沙箱里的游戏不占你的屏幕和鼠标。",
    "关游戏：只关 agent 自己开的那次；你自己开的游戏从来不关。", "我没在用电脑时",
    "你离开电脑（不动鼠标键盘）这么久以后才开，不问你；你一回来，agent 就停下不操作游戏，等你再离开", "分钟", "我在用电脑时也可以操作游戏窗口",
    "按键只发给 agent 开的那个游戏窗口，不抢焦点、不动你别的程序；不勾的话，你在用电脑时 agent 不碰游戏（推荐不勾）",
    "测试时允许把游戏切到前面", "只在 Windows 上用到：Windows 只把按键发给最前面的窗口。勾上后，你离开电脑（1 分钟不动鼠标键盘）时 agent 可以把它自己开的游戏切到前面再按；"
    "你一动鼠标键盘它就停下；你在用电脑时从来不切。macOS / Linux 不受影响",
    "谁来点游戏", "agent 自己看、自己点", "agent 用 gameanything native shot / drive 看游戏、按键（要这台电脑允许，见下面的检查结果）",
    "我自己点", "agent 不操作游戏：每一轮在进度卡里写清楚要你点哪里，你点完说「好了」", "agent 能不能看、点你的游戏",
    "能看、能点", "只能看，不能点", "不能看也不能点", "还没查过（第一次开游戏前会查）", "{who}，{t} 查的", "换了 agent 或模型：下次开游戏前会重新查",
}
ERR = {"policy": "开游戏的设置应该是 ask、window、always 或 idle", "window": "时间段应该像 22:00-08:00",
       "minutes": "没在用电脑的分钟数应该是 1 到 720 之间的整数", "drive": "操作游戏的设置应该是 idle 或 always",
       "front": "切到前面的设置应该是 never 或 away", "hands": "谁来点游戏应该是 agent 或 self"}


# ---------------------------------------------------------------- the project's setting
def parse_window(s: str):
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", str(s or ""))
    if not m: raise ValueError(ERR["window"])
    a, b, c, d = map(int, m.groups())
    if a > 23 or c > 23 or b > 59 or d > 59 or (a, b) == (c, d): raise ValueError(ERR["window"])
    return a * 60 + b, c * 60 + d


def norm_window(s: str) -> str:
    a, b = parse_window(s); return f"{a // 60:02d}:{a % 60:02d}-{b // 60:02d}:{b % 60:02d}"


def norm_minutes(v) -> int:
    try: n = int(str(v).strip())
    except (TypeError, ValueError): raise ValueError(ERR["minutes"]) from None
    if not 1 <= n <= 720: raise ValueError(ERR["minutes"])
    return n


def policy(root) -> dict:
    cfg = projects.config_of(root) if root else {}
    mode = cfg.get("native_launch") if cfg.get("native_launch") in POLICIES else "ask"
    try: win = norm_window(cfg.get("native_launch_window") or DEFAULT_WINDOW)
    except ValueError: win = DEFAULT_WINDOW
    try: mins = norm_minutes(cfg.get("native_launch_idle_minutes") or DEFAULT_IDLE_MIN)
    except ValueError: mins = DEFAULT_IDLE_MIN
    drive = cfg.get("native_drive") if cfg.get("native_drive") in DRIVES else "idle"
    front = cfg.get("native_front") if cfg.get("native_front") in FRONTS else "never"
    hands = cfg.get("native_hands") if cfg.get("native_hands") in HANDS else "agent"
    return {"mode": mode, "window": win, "idle_minutes": mins, "drive": drive, "front": front, "hands": hands, "chosen": cfg.get("native_launch") in POLICIES}


def _set_line(text: str, key: str, value: str) -> str:
    line = f"{key}: {value}"
    if re.search(rf"(?m)^{key}:.*$", text): return re.sub(rf"(?m)^{key}:.*$", lambda _: line, text, count=1)
    return (text.rstrip("\n") + "\n" if text else "") + line + "\n"


def set_policy(ref, mode: str, window: str = None, minutes=None, drive: str = None, front: str = None, hands: str = None) -> dict:
    """Edit only the native_launch / native_launch_window / native_launch_idle_minutes / native_drive / native_front / native_hands lines
    of config/project.yaml. mode None = keep the current one (front / hands alone, from the readiness card). -> the project entry."""
    if mode is not None and mode not in POLICIES: raise ValueError(ERR["policy"])
    if drive is not None and drive not in DRIVES: raise ValueError(ERR["drive"])
    if front is not None and front not in FRONTS: raise ValueError(ERR["front"])
    if hands is not None and hands not in HANDS: raise ValueError(ERR["hands"])
    win = norm_window(window) if window else None
    mins = norm_minutes(minutes) if minutes not in (None, "") else None
    e = projects.find(ref); f = Path(e["path"]) / layout.CONFIG / "project.yaml"
    t = f.read_text(encoding="utf-8") if f.exists() else ""
    if mode is not None: t = _set_line(t, "native_launch", mode)        # (None: her launch choice stays unchosen - `chosen` in policy())
    if win: t = _set_line(t, "native_launch_window", f'"{win}"')
    if mins: t = _set_line(t, "native_launch_idle_minutes", str(mins))
    if drive: t = _set_line(t, "native_drive", drive)
    if front: t = _set_line(t, "native_front", front)
    if hands: t = _set_line(t, "native_hands", hands)
    f.parent.mkdir(parents=True, exist_ok=True); f.write_text(t, encoding="utf-8")
    return e


def in_window(win: str, now: datetime) -> bool:
    a, b = parse_window(win); m = now.hour * 60 + now.minute
    return a <= m < b if a < b else (m >= a or m < b)


def window_opens(win: str, now: datetime) -> datetime:
    a, _ = parse_window(win)
    t = now.replace(hour=a // 60, minute=a % 60, second=0, microsecond=0)
    return t if t > now else t + timedelta(days=1)


# ---------------------------------------------------------------- the ledger
def _ledger_file(root) -> Path: return Path(root) / "conversation" / ".native_launch.json"


def ledger(root) -> dict:
    try: d = json.loads(_ledger_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError): d = {}
    d.setdefault("used", {}); d.setdefault("launches", []); return d


def _update(root, fn):
    """Change the ledger under the conversation lock -> fn's result."""
    (Path(root) / "conversation").mkdir(parents=True, exist_ok=True)
    with open(Path(root) / "conversation" / ".lock", "a", encoding="utf-8") as lk:
        osdirs.lock(lk)
        d = ledger(root); out = fn(d)
        f = _ledger_file(root); tmp = f.with_name(f".{f.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8"); os.replace(tmp, f)
    return out


def launches(root, round_=None) -> list:
    return [x for x in ledger(root)["launches"] if round_ is None or x.get("round") == round_]


def _ts(s):
    try: return datetime.fromisoformat(str(s))
    except (TypeError, ValueError): return None


def _iso(t: datetime) -> str: return t.isoformat(timespec="seconds")


def _ago(s: float) -> str: return f"{int(s)} 秒" if s < 120 else f"{int(s // 60)} 分钟"


# ---------------------------------------------------------------- processes
def proc_start(pid):
    """Which process this pid is (its start time, opaque): Linux /proc, other POSIX `ps -o lstart=`; None when unknown (Windows)."""
    s = osdirs.pid_start(pid)
    if s or os.name == "nt": return s
    r = _run(["ps", "-o", "lstart=", "-p", str(int(pid))])
    return (r.stdout.strip() or None) if r is not None and r.returncode == 0 else None


def _started_at(pid):
    """When the process started (local time), or None when unknown (Windows, or `ps` failed)."""
    if os.name == "nt": return None
    r = _run(["ps", "-o", "lstart=", "-p", str(int(pid))])
    if r is None or r.returncode != 0: return None
    try: return datetime.strptime(" ".join(r.stdout.split()), "%a %b %d %H:%M:%S %Y")
    except ValueError: return None


def _alive(p: dict) -> bool:
    if not osdirs.pid_alive(p["pid"]): return False
    return p.get("start") is None or proc_start(p["pid"]) in (None, p["start"])


def _terminate(pid) -> bool:
    """A polite stop (SIGTERM; Windows: taskkill without /F, which asks the window to close). Never a forced kill."""
    args = ["taskkill", "/PID", str(int(pid))] if os.name == "nt" else ["kill", "-TERM", str(int(pid))]
    try: return subprocess.run(args, capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError, ValueError): return False


def _mac_quit(g, pid, only_ours: bool) -> str:
    """Ask a macOS app to quit like Cmd-Q -> how ("NSRunningApplication" / "AppleScript"), or "" when neither could be sent. The AppleScript
    way quits the app by its bundle id: only used when every running copy of the game is the one GameAnything opened (only_ours)."""
    from . import macapp
    if macapp.terminate(pid): return "NSRunningApplication"
    bid = g.mac_bundle_id() if only_ours else None
    if bid and macapp.quit_bundle(bid): return "AppleScript"
    return ""


def open_link(url: str, sys_=None) -> bool:
    """Open a steam:// link; on macOS with `open -g` (Steam is not brought to the front; the game window itself still appears)."""
    if url.startswith("script:"):                         # a start script run in its own folder, detached (Valheim on macOS, SMAPI on Windows)
        sc = Path(url[len("script:"):])
        # Windows: its own console with its own handles (SMAPI is a console program: redirected handles make it fail)
        io = ({"creationflags": getattr(subprocess, "CREATE_NEW_CONSOLE", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
              if (sys_ or osdirs.system()) == "windows" else
              {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "start_new_session": True})
        try: subprocess.Popen([str(sc)], cwd=str(sc.parent), **io)
        except OSError: return False
        return True
    if (sys_ or osdirs.system()) == "mac":
        r = _run(["open", "-g", url]); return r is not None and r.returncode == 0
    return osdirs.open_url(url)


# ---------------------------------------------------------------- small window (per game; key by key, put back after)
def _line(n): return rf"\A(?:[^\n]*\n){{{n}}}([^\r\n]*)"


def window_plan(g) -> list:
    """[(file, [(name, regex with one group = the value, new value)])]: only keys the file already has are changed."""
    if g.id == "minecraft":       # options.txt: windowed, and keep running when it loses focus (it does not need her mouse to stay put)
        return [(g.user_dir() / "options.txt", [("fullscreen", r"(?m)^fullscreen:([^\r\n]*)", "false"),
                                                ("pauseOnLostFocus", r"(?m)^pauseOnLostFocus:([^\r\n]*)", "false")])]
    if g.id == "slay_the_spire":  # info.displayconfig: width, height, fps, fullscreen, windowed fullscreen, vsync (one per line)
        return [(g.user_dir() / "info.displayconfig", [("width", _line(0), "1280"), ("height", _line(1), "720"),
                                                       ("fullscreen", _line(3), "false"), ("wfs", _line(4), "false")])]
    if g.id == "sims4":           # Options.ini (UNTESTED keys: only changed when present)
        k = lambda n: rf"(?mi)^[ \t]*{n}[ \t]*=[ \t]*([^\r\n]*)"
        return [(g.options_file(), [("fullscreen", k("fullscreen"), "0"), ("resolutionwidth", k("resolutionwidth"), "1280"),
                                    ("resolutionheight", k("resolutionheight"), "720")])]
    if g.id == "stardew":         # startup_preferences (XML): keep running unfocused (UNTESTED key: only changed when the file has it)
        return [(g.user_dir() / "startup_preferences", [("pauseWhenOutOfFocus", r"<pauseWhenOutOfFocus>([^<]*)</pauseWhenOutOfFocus>", "false")])]
    return []                     # Cities, Overcooked 2, Valheim: no file GameAnything edits; their smoke plugins set Application.runInBackground (docs)


WINDOW_HOW = registry.window_how()   # what she can set once herself, for games GameAnything does not edit: game.yaml `window.how`


def _window_file(g) -> Path: return g.root / "window" / f"{g.id}.json"


def small_window(g) -> dict:
    """Before a test launch (the game closed): set the windowed / small keys and remember the old values. A backup that was never put back
    is kept (its old values are hers). -> {changed: [names], file}."""
    st = _window_file(g)
    try: prev = json.loads(st.read_text(encoding="utf-8"))
    except (OSError, ValueError): prev = None
    out = {"changed": [], "files": [], **({"how": WINDOW_HOW[g.id]} if g.id in WINDOW_HOW else {})}
    plan = window_plan(g)
    if not plan: return {**out, "how": WINDOW_HOW.get(g.id, "")}
    rec = prev or {"game": g.id, "at": _iso(datetime.now()), "files": []}
    for f, keys in plan:
        try: raw = f.read_bytes()
        except OSError: continue
        t = raw.decode("latin-1"); old = next((x for x in rec["files"] if x["file"] == str(f)), None)
        changes = old["changes"] if old else []
        for name, rx, new in keys:
            m = re.search(rx, t)
            if not m or m.group(1).strip() == new: continue
            if not any(c["name"] == name for c in changes): changes.append({"name": name, "re": rx, "old": m.group(1), "new": new})
            t = t[:m.start(1)] + new + t[m.end(1):]; out["changed"].append(name)
        if t.encode("latin-1") != raw:
            tmp = f.with_name(f".{f.name}.m2w-tmp"); tmp.write_bytes(t.encode("latin-1")); os.replace(tmp, f)
        if changes and not old: rec["files"].append({"file": str(f), "changes": changes})
        out["files"].append(str(f))
    if rec["files"]:
        st.parent.mkdir(parents=True, exist_ok=True); st.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def restore_window(g) -> dict:
    """Put the old values back (the game must be closed: some games rewrite their settings when they exit). A key she changed since
    (not what GameAnything set) is left as she set it. -> {restored: [names], kept: [names]} or {} when there was nothing to put back."""
    st = _window_file(g)
    try: rec = json.loads(st.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}
    if g.running(): return {"pending": True}
    out = {"restored": [], "kept": []}
    for x in rec.get("files", []):
        f = Path(x["file"])
        try: t = f.read_bytes().decode("latin-1")
        except OSError: continue
        for c in x["changes"]:
            m = re.search(c["re"], t)
            if m and m.group(1).strip() == c["new"]: t = t[:m.start(1)] + c["old"] + t[m.end(1):]; out["restored"].append(c["name"])
            else: out["kept"].append(c["name"])
        tmp = f.with_name(f".{f.name}.m2w-tmp"); tmp.write_bytes(t.encode("latin-1")); os.replace(tmp, f)
    os.replace(st, st.with_name(f".restored-{datetime.now():%Y%m%d-%H%M%S}-{st.name}"))         # kept, never deleted
    return out


# ---------------------------------------------------------------- the card
def _later_time(card, answer) -> str:
    m = re.search(r"(\d{1,2})[:：](\d{2})", str((answer or {}).get("note") or ""))        # she may write another time in the note
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60: return f"{int(m.group(1)):02d}:{m.group(2)}"
    return card.get("later_at") or DEFAULT_WINDOW[:5]


def post_card(root, g, pol, reason=None, reason_en=None, minutes=None) -> str:
    later = pol["window"][:5]; mins = f"（大约 {minutes} 分钟）" if minutes else ""; mins_en = f" (about {minutes} min)" if minutes else ""
    card = {"kind": "options", "key": CARD_KEY, "multi": False, "title": "要开游戏测一下，现在可以吗？", "game": g.id, "later_at": later,
            "items": [{"key": "now", "title": "现在可以", "desc": f"马上在你的电脑上打开 {g.title}，测完我会关掉它{mins}", "recommended": True},
                      {"key": "wait", "title": "等我说", "desc": "先不开；你方便的时候在对话里说一声"},
                      {"key": "later", "title": f"今晚 {later} 后", "desc": "到点再开，你不用守着（也可以在下面写别的时间，例如 23:30）"}],
            "en": {"title": "I'd like to open the game for a quick test. Is now OK?",
                   "items": [{"key": "now", "title": "Now is fine", "desc": f"Open {g.title} on your computer now; I close it when the test is done{mins_en}", "recommended": True},
                             {"key": "wait", "title": "Wait until I say", "desc": "Not now; tell me in the chat when it suits you"},
                             {"key": "later", "title": f"Tonight after {later}", "desc": "Open it then; you don't need to be there (or write another time below, e.g. 23:30)"}]}}
    text = reason or f"这一轮的改动都编译、检查过了，想在你的电脑上开一次 {g.title} 一起测。"
    text_en = reason_en or f"This round's changes are compiled and checked; I'd like to open {g.title} once on your computer to test them together."
    return Thread(root).card(card, text=text, text_en=text_en, session=SESSION)["id"]


def _answer(c):
    ans = [a for a in c["answers"] if a.get("from") == "user" and a.get("source") == "ui"]     # her click in the page, nothing typed by an agent
    return ans[-1] if ans else None


# ---------------------------------------------------------------- deciding
def _open_launch(root, g):
    """The newest launch GameAnything recorded for this game that is not closed yet, or None."""
    for x in reversed(ledger(root)["launches"]):
        if x.get("game") == g.id and x.get("by") == "m2w" and x.get("state") == "open": return x
    return None


def _adopt(root, g, x, now=None):
    """The game processes GameAnything opened: recorded at launch, or (Steam starts the game a little later) the ones that appeared within
    ADOPT_SECS of the launch while nothing of this game ran before it."""
    if x.get("pids") or x.get("running_before"): return x.get("pids") or []
    at = _ts(x.get("at")); now = now or datetime.now()
    if not at: return []
    ps = g.pids() or []
    if (now - at).total_seconds() > ADOPT_SECS:
        # asked late (a screenshot long after the launch): adopt only processes that themselves STARTED within ADOPT_SECS of the launch.
        # tModLoader's first start on her Mac (2026-10-29) came 13 min after the launch (macOS verifying + its .NET download), and the
        # first `shot` a few minutes later was refused as "gone" because the window was counted from the launch to now.
        ps = [p for p in ps if (s := _started_at(p)) is not None and -5 <= (s - at).total_seconds() <= ADOPT_SECS]
    found = [{"pid": int(p), "start": proc_start(p)} for p in ps]
    if found:
        def put(d):
            for y in d["launches"]:
                if y["id"] == x["id"] and not y.get("pids"): y["pids"] = found
        _update(root, put)
    return found


def _take_over(root, g, pids, now=None):
    """Record a running game she opened herself as the open launch (native_drive: always)."""
    now = now or datetime.now()
    rec = {"id": f"{now:%Y%m%dT%H%M%S}_{secrets.token_hex(2)}", "game": g.id, "at": _iso(now), "code": "took_over", "running_before": True,
           "url": None, "pids": [{"pid": int(p), "start": proc_start(p)} for p in pids], "state": "open", "by": "m2w", "took_over": True}
    _update(root, lambda L: L["launches"].append(rec))
    return rec


def current(root, g, now=None):
    """-> (the open launch of this game, its live processes [{pid, start}]); (None, []) when GameAnything may use none.
    native_drive: always (her rule 2026-10-29): every running process of this game is the test game - one she opened herself is taken
    over (recorded as a launch), and processes that come up later (a launcher's game process) need no ADOPT_SECS window.
    Otherwise only what GameAnything opened: the processes recorded at launch or adopted within ADOPT_SECS."""
    x = _open_launch(root, g); live = g.pids()
    if policy(root)["drive"] == "always" and live is not None:
        if not live: return x, []
        if x is None: x = _take_over(root, g, live, now)
        else: add_pids(root, g, live)
        return x, [{"pid": int(p), "start": proc_start(p)} for p in live]
    if x is None: return None, []
    ps = [p for p in _adopt(root, g, x, now) if _alive(p)]
    if live is not None: ps = [p for p in ps if p["pid"] in set(int(i) for i in live)]
    return x, ps


def decide(root, g, now=None, post=True, reason=None, reason_en=None, minutes=None, ask_again=False) -> dict:
    now = now or datetime.now(); pol = policy(root)
    if pol["drive"] == "always" and g.running():                         # her rule 2026-10-29: use the running game, do not open another
        x, ps = current(root, g, now)
        if x and ps:
            return {"state": "open", "code": x["code"] if x.get("took_over") else "open", "launch_id": x["id"],
                    "why": f"{g.title} 已经开着" + ("（她开的，现在当作测试用的游戏）" if x.get("took_over") else "") + "：直接用它测（shot / drive / close），不再开一次"}
    mine = _open_launch(root, g)
    if mine and any(_alive(p) for p in _adopt(root, g, mine, now)):
        return {"state": "refused", "code": "open", "why": "上一次 GameAnything 开的游戏还开着：接着用它测，或者先 gameanything native close"}
    run = g.running()
    if run:
        return {"state": "refused", "code": "running", "why": f"{g.title} 已经开着（可能是她在玩）：不打扰她，也不会关它。等她退出后再测"}
    unknown = ""
    if pol["mode"] == "idle":
        s = idlemod.seconds()
        if s is None: unknown = "看不出她在不在用电脑（gameanything native idle 是 unknown），改成先问她："
        elif s < pol["idle_minutes"] * 60:
            return {"state": "pending", "code": "busy", "idle": s,
                    "why": f"她 {_ago(s)}前还在用电脑：等她 {pol['idle_minutes']} 分钟没动鼠标键盘再开（不发卡、不问她）"}
        else: return {"state": "go", "code": "idle", "idle": s, "why": f"她已经 {_ago(s)}没动电脑了（她的设置：我没在用电脑时）"}
    if pol["mode"] in ("always", "window"):
        if pol["mode"] == "window" and not in_window(pol["window"], now):
            t = window_opens(pol["window"], now)
            return {"state": "pending", "code": "window", "until": _iso(t), "why": f"她只允许在 {pol['window']} 开游戏：{t:%H:%M} 以后再开（不发卡、不问她）"}
        return {"state": "go", "code": pol["mode"], "why": "她的设置：随时可以" if pol["mode"] == "always" else f"在她允许的时间段 {pol['window']} 里"}
    # ask: her answer on the newest launch card
    T = Thread(root); c = next((v for v in T.cards().values() if v["card"].get("key") == CARD_KEY), None)
    used = ledger(root)["used"]

    def ask(why, code):
        why = unknown + why
        if not post: return {"state": "pending", "code": code, "why": why + "（没有发卡：--no-post）"}
        cid = post_card(root, g, pol, reason, reason_en, minutes)
        return {"state": "pending", "code": code, "card": cid, "why": why + "：已经在对话里发卡问她，等她点「现在可以」"}

    if c is None: return ask("还没问过她", "asked")
    a = _answer(c); cid = c["event"]["id"]
    if a is None:
        if ask_again: return ask("重新问她", "asked")
        return {"state": "pending", "code": "waiting", "card": cid, "why": "卡已经发了，她还没回答：不要再发，等她点"}
    pick = ((a.get("answer") or {}).get("picked") or [None])[0]; at = _ts(a.get("at")) or now
    if a["id"] in used: return ask("她上次的同意已经用过一次（一次同意开一次）", "asked")
    if pick == "now":
        if (now - at).total_seconds() > YES_VALID_SECS: return ask(f"她 {at:%m-%d %H:%M} 点的「现在可以」已经过去太久", "asked")
        return {"state": "go", "code": "yes", "card": cid, "answer": a["id"], "why": f"她 {at:%H:%M} 点了「现在可以」"}
    if pick == "later":
        hhmm = _later_time(c["card"], a.get("answer")); h, m = map(int, hhmm.split(":"))
        t = at.replace(hour=h, minute=m, second=0, microsecond=0)
        if t <= at: t += timedelta(days=1)
        if now < t: return {"state": "pending", "code": "later", "card": cid, "until": _iso(t), "why": f"她说 {hhmm} 以后可以：到时候再运行这条命令"}
        if (now - t).total_seconds() > LATER_VALID_SECS: return ask(f"她说的 {hhmm} 以后已经过去太久", "asked")
        return {"state": "go", "code": "later", "card": cid, "answer": a["id"], "why": f"她说 {hhmm} 以后可以，现在 {now:%H:%M}"}
    if pick == "wait":
        if ask_again: return ask("她说过「等我说」，现在重新问她", "asked")
        return {"state": "pending", "code": "wait", "card": cid, "why": "她说「等我说」：等她在对话里说可以了，再用 --ask-again 重新发卡（不要自己开）"}
    return {"state": "pending", "code": "note", "card": cid, "why": "她没选，只写了一句话：先看她写了什么（gameanything chat read）"}


def wait_decision(root, g, wait_secs, poll=5.0, sleep=time.sleep, **kw) -> dict:
    """decide(); while it is pending for her answer (the card, or 「今晚 HH:MM 后」 within the wait), look again every `poll` seconds."""
    end = time.monotonic() + wait_secs; d = decide(root, g, **kw); kw["post"] = False
    while d["state"] == "pending" and d.get("code") in ("asked", "waiting", "later", "busy") and time.monotonic() < end:
        sleep(poll); d2 = decide(root, g, **kw)
        if d2.get("code") == "asked": break                              # (only with --no-post) nothing new to wait for
        d = d2
    return d


# ---------------------------------------------------------------- launch / close
def launch(root, g, now=None, opener=None, settle=30.0, round_=None, keep_window=False, dry_run=False, sleep=time.sleep, spawner=None, **kw) -> dict:
    """-> the decision, plus on go: {launched, url, window, launch_id}. Nothing is opened unless the decision is go."""
    restore_window(g)                                                     # a test window left from last time, if the game is closed now
    d = kw.pop("decision", None) or decide(root, g, now=now, **kw)
    if d["state"] != "go" or dry_run: return {**d, "launched": False}
    url = g.launch_url(); now = now or datetime.now()
    lid = f"{now:%Y%m%dT%H%M%S}_{secrets.token_hex(2)}"
    rec = {"id": lid, "game": g.id, "at": _iso(now), "round": round_, "code": d["code"], "card": d.get("card"), "answer": d.get("answer"),
           "running_before": bool(g.running()), "url": url, "pids": [], "state": "open", "by": "m2w" if url else "user"}

    def put(L):
        if d.get("answer"):
            if d["answer"] in L["used"]: raise NativeError("她的这次同意刚刚已经被另一次开游戏用掉了")
            L["used"][d["answer"]] = lid
        L["launches"].append(rec)
    if not url:
        rec["state"] = "manual"; _update(root, put)
        return {**d, "launched": False, "manual": True, "launch_id": lid,
                "why": d["why"] + f"；{g.title} 不能从这里启动：请她自己打开（{g.launch_hint() or '启动器里选带 mod 的配置'}）。她开的游戏 GameAnything 不会关"}
    win = {} if keep_window else small_window(g)
    _update(root, put)
    g.prepare_launch()
    if not (opener or open_link)(url):
        _update(root, lambda L: [y.update(state="failed") for y in L["launches"] if y["id"] == lid])
        restore_window(g)
        raise NativeError(f"没能打开 {url}：Steam 装了吗？")
    pids = []; end = time.monotonic() + (settle if g.launch_needs_game_pid else 0)   # (a launcher first: after_launch waits for the game)
    while not pids and time.monotonic() < end:
        sleep(2); pids = g.pids() or []
    if pids:
        found = [{"pid": int(p), "start": proc_start(p)} for p in pids]
        _update(root, lambda L: [y.update(pids=found) for y in L["launches"] if y["id"] == lid])
    after = None
    if (pids or not g.launch_needs_game_pid) and type(g).after_launch is not Game.after_launch:
        # its own detached process (afterlaunch.py): the steps take a minute or two and must not end with the agent that ran launch
        try: after = {"after_launch": f"running in the background (result: gameanything native launches; log {(spawner or spawn_after)(root, g, lid, pids)})"}
        except OSError as e: after = {"step": "after_launch", "why": str(e)}
    return {**d, "launched": True, "url": url, "window": win, "launch_id": lid, "pids": pids, "after": after}


def spawn_after(root, g, lid, pids) -> Path:
    """Start afterlaunch.py for this launch, detached (its own session: it outlives the calling process). -> its log file."""
    log = Path(root) / "conversation" / ".native_after.log"; log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as out:
        subprocess.Popen([sys.executable, "-m", "gameanything.native.afterlaunch", str(root), g.id, lid, *map(str, pids)],
                         stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
    return log


def add_pids(root, g, pids) -> None:
    """Record more processes as GameAnything's for the open launch of this game (a game whose launcher starts the real game process)."""
    x = _open_launch(root, g)
    if x is None: return
    have = {int(p["pid"]) for p in x.get("pids") or []}
    new = [{"pid": int(p), "start": proc_start(p)} for p in pids if int(p) not in have]
    if new: _update(root, lambda L: [y.update(pids=(y.get("pids") or []) + new) for y in L["launches"] if y["id"] == x["id"]])


def close(root, g, wait=CLOSE_WAIT_SECS, sleep=time.sleep, now=None) -> dict:
    """End the game GameAnything opened for this project (recorded pids, same process). Never anything else. -> {closed, why, window}."""
    x, ps = current(root, g, now)
    if x is None:
        r = g.running()
        why = (f"{g.title} 开着，但不是 GameAnything 开的（是她自己开的）：不关" if r else "没有 GameAnything 开着的游戏")
        return {"closed": False, "code": "not_ours" if r else "none", "why": why}
    mine = set(int(p) for p in (g.pids() or [])) if g.pids() is not None else None
    if not ps:
        _update(root, lambda L: [y.update(state="gone", closed=_iso(datetime.now())) for y in L["launches"] if y["id"] == x["id"]])
        return {"closed": True, "code": "gone", "why": "游戏已经关了", "window": restore_window(g)}
    how = ""
    if g.sys == "mac" and getattr(g, "mac_quit", "app") == "app":
        ours = mine is not None and mine <= {p["pid"] for p in ps}
        if policy(root)["drive"] == "always":
            # a Unity game in the background (Cities: Skylines full screen in its own Space, Valheim; her Mac 2026-10-31) ignored the
            # app's Quit and got SIGTERM 20 s later: in front it takes it
            from . import macapp
            for p in ps: macapp.activate(p["pid"])
        hows = [_mac_quit(g, p["pid"], ours) for p in ps]; how = next((h for h in hows if h), "")
        if how:
            end = time.monotonic() + min(QUIT_WAIT_SECS, wait)
            while time.monotonic() < end and any(_alive(p) for p in ps): sleep(1)
    left = [p for p in ps if _alive(p)]
    if left:                                                              # the game may be asking 「are you sure?」: its adapter answers it
        try: ok = g.confirm_quit(root)
        except NativeError: ok = None
        if ok:
            how = (how + " -> " if how else "") + ok
            end = time.monotonic() + min(QUIT_WAIT_SECS, wait)
            while time.monotonic() < end and any(_alive(p) for p in left): sleep(1)
            left = [p for p in ps if _alive(p)]
    if left and x.get("took_over"):                                       # a game she opened: its own Quit only, never SIGTERM (her progress)
        return {"closed": False, "code": "still_running", "how": how,
                "why": f"请她开的 {g.title} 退出了，但它还开着（可能在问「确定退出吗」）：不强制关，点它的确认或告诉她"}
    if left:
        for p in left: _terminate(p["pid"])
        how = (how + " -> SIGTERM" if how else "SIGTERM") if os.name != "nt" else "taskkill"
        end = time.monotonic() + wait
        while time.monotonic() < end and any(_alive(p) for p in left): sleep(1)
    left = [p["pid"] for p in ps if _alive(p)]
    if left: return {"closed": False, "code": "still_running", "how": how, "why": f"请游戏退出了，但它还开着（pid {', '.join(map(str, left))}）：没有强制关，告诉她"}
    _update(root, lambda L: [y.update(state="closed", closed=_iso(datetime.now()), how=how) for y in L["launches"] if y["id"] == x["id"]])
    return {"closed": True, "code": "closed", "how": how, "why": f"关掉了 GameAnything 开的游戏（{how}）", "window": restore_window(g)}
