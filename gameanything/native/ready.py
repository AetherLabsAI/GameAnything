"""能不能操作屏幕 (2026-11-01): can the agent that runs this command look at / click her game? Checked FROM THE CALLING PROCESS, so
when an agent runs `gameanything native ready`, the answer is the one for that agent's framework, its sandbox and the app it runs in.

Two layers decide it:
    (a) the agent framework runs shell commands, and its sandbox lets `native shot` / `native drive` reach the window server
        (Codex runs commands in its own sandbox: macOS seatbelt, Linux bubblewrap / landlock; never weakened for this);
    (b) the system allows it: macOS Accessibility (act) + Screen Recording (look) for the RESPONSIBLE app (Terminal / iTerm / VS Code /
        Cursor / Claude.app, or python when agentd / `gameanything ui` was started without a terminal: hands.mac_app); Windows: no
        permission, but her interactive desktop session (not SSH / a service / session 0), the game not elevated (UIPI), and not inside
        a packaged MSIX app (osdirs.windows_package: files land in a redirected AppData); Linux: X11 (not Wayland), xdotool, import / ffmpeg.

    check(root, role)  -> {level: full | look | none, look, act, items: [{name, ok, why, how, needs}], caller, probe, for, at}
                          hands.permissions() + a real capture probe: ONE tiny region (16-32 px: the macOS menu bar's corner, the Linux
                          screen's corner, the middle of the Windows screen) read into memory or a temp file that is deleted at once;
                          only "are the pixels all the same" is kept - the picture is never saved, sent or logged. Never a key or click.
    run(root, ...)     -> check() + her answer on the readiness card + the record; `next` says what the resident does:
                          ok | card (post ONE card: card_body()) | wait (the card is out, unanswered) | self (she clicks, native_hands: self)
    state(root, role)  -> the record and whether it still holds (the agent / model of the role changed -> check again)

The record is <project>/conversation/.native_ready.json {"chat": rec, "build": rec}: permissions belong to the app / sandbox the agent
runs in, so a check holds only for the agent + model (models.effective) it was made with. Texts in TEXTS: quiet.TEXTS (the menu dialog).
"""
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from .. import osdirs
from . import hands, idle as idlemod, quiet
from .games import _run

CARD_KEY = "native-ready"
LEVELS = ("none", "look", "full")
EXIT = {"full": 0, "look": 1, "none": 3}                 # `gameanything native ready` exit codes
LEVEL_TEXT = {"full": "能看、能点", "look": "只能看，不能点", "none": "不能看也不能点"}
LEVEL_EN = {"full": "can look and click", "look": "can look, cannot click", "none": "can neither look nor click"}
SANDBOX_ERR = re.compile(r"operation not permitted|not authorized|sandbox|deny|denied|seatbelt|bwrap|landlock|seccomp", re.I)


# ---------------------------------------------------------------- (a) which agent framework / app / sandbox runs this command
def caller(env=None) -> dict:
    """Heuristics from the environment the agent's shell passes down -> {framework, app, sandbox, signs}. Markers (2026-11-01; the
    ones marked ? are not checked on a real machine): Codex CODEX_SANDBOX (=seatbelt on macOS) / CODEX_SANDBOX_NETWORK_DISABLED;
    Claude Code CLAUDECODE=1 + CLAUDE_CODE_ENTRYPOINT; OpenCode OPENCODE=1 (seen in her Terminal, 2026-11-01); Gemini CLI GEMINI_CLI=1 (seen in her Terminal, 2026-11-01); dsh DSH_HOME (seen in a real dsh run, 2026-11-01); agentd's
    runs GAMEANYTHING_INSTANCE; the app: TERM_PROGRAM (vscode is also Cursor), __CFBundleIdentifier (macOS), WT_SESSION, SSH_*."""
    env = os.environ if env is None else env; signs = []
    fw = ""
    for k, name in (("CODEX_SANDBOX", "codex"), ("CODEX_SANDBOX_NETWORK_DISABLED", "codex"), ("CODEX_THREAD_ID", "codex"),
                    ("CLAUDECODE", "claude-code"), ("OPENCODE", "opencode"), ("GEMINI_CLI", "gemini"), ("DSH_HOME", "dsh")):
        if env.get(k):
            signs.append(f"{k}={env[k]}" if len(str(env[k])) < 40 else k)
            fw = fw or name
    if env.get("CLAUDE_CODE_ENTRYPOINT"): signs.append(f"CLAUDE_CODE_ENTRYPOINT={env['CLAUDE_CODE_ENTRYPOINT']}")
    agentd = bool(env.get("GAMEANYTHING_INSTANCE"))
    if agentd: signs.append("GAMEANYTHING_INSTANCE (started by agentd)")
    bundle = env.get("__CFBundleIdentifier") or ""; term = env.get("TERM_PROGRAM") or ""
    app = ""
    if "claude" in bundle.lower() or env.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("claude-desktop"): app = "Claude 桌面 app"
    elif "cursor" in bundle.lower(): app = "Cursor"
    elif term == "vscode" or "vscode" in bundle.lower() or env.get("CLAUDE_CODE_ENTRYPOINT") == "claude-vscode": app = "VS Code / Cursor"
    elif term: app = {"Apple_Terminal": "Terminal", "iTerm.app": "iTerm"}.get(term, term)
    elif env.get("WT_SESSION"): app = "Windows Terminal"
    if bundle: signs.append(f"__CFBundleIdentifier={bundle}")
    if term: signs.append(f"TERM_PROGRAM={term}")
    ssh = bool(env.get("SSH_CONNECTION") or env.get("SSH_CLIENT") or env.get("SSH_TTY"))
    if ssh: signs.append("SSH")
    sb = ""
    if fw == "codex": sb = "Codex" + (f" ({env['CODEX_SANDBOX']})" if env.get("CODEX_SANDBOX") else "")
    elif env.get("APP_SANDBOX_CONTAINER_ID"): sb = "macOS App Sandbox"; signs.append("APP_SANDBOX_CONTAINER_ID")
    return {"framework": fw or ("agentd" if agentd else ""), "agentd": agentd, "app": app, "ssh": ssh, "sandbox": sb, "signs": signs}


APP_EN = {"Claude 桌面 app": "Claude desktop app"}


def app_text(app: str, lang: str = "zh") -> str:
    """The app's name in the language of the text around it (the record keeps the Chinese one; --lang en printed "Claude 桌面 app")."""
    return APP_EN.get(app, app) if lang == "en" else app


# ---------------------------------------------------------------- (b) Windows: her interactive desktop?
def win_desktop(user32=None, kernel32=None) -> dict:
    """-> {session, console, input_desktop}: the process's session id (0 = services: no desktop at all), the console session, and whether
    the input desktop opens (it does not from a service / SSH session, nor while the screen is locked or a UAC prompt is up)."""
    import ctypes
    if user32 is None:
        user32 = ctypes.WinDLL("user32"); kernel32 = ctypes.WinDLL("kernel32")
        user32.OpenInputDesktop.restype = ctypes.c_void_p; user32.OpenInputDesktop.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
        user32.CloseDesktop.argtypes = [ctypes.c_void_p]; kernel32.WTSGetActiveConsoleSessionId.restype = ctypes.c_uint32
    sid = ctypes.c_ulong(0)
    s = sid.value if kernel32.ProcessIdToSessionId(kernel32.GetCurrentProcessId(), ctypes.byref(sid)) else None
    con = kernel32.WTSGetActiveConsoleSessionId(); h = user32.OpenInputDesktop(0, False, 0x0001)      # DESKTOP_READOBJECTS
    if h: user32.CloseDesktop(h)
    return {"session": s, "console": None if con in (None, 0xFFFFFFFF) else int(con), "input_desktop": bool(h)}


def win_grab(size=32, region=None):
    """Windows: `size` x `size` pixels from the middle of the screen (or region = (x, y, w, h): a negative x / y counts from the right /
    bottom edge, y None is the middle, w 0 the whole width) into memory (BitBlt from the screen DC) -> BGRA bytes, or None. Nothing is
    written anywhere."""
    import ctypes
    V = ctypes.c_void_p; u = ctypes.WinDLL("user32"); g = ctypes.WinDLL("gdi32")
    for f, r, a in ((u.GetDC, V, [V]), (u.ReleaseDC, ctypes.c_int, [V, V]), (u.GetSystemMetrics, ctypes.c_int, [ctypes.c_int]),
                    (g.CreateCompatibleDC, V, [V]), (g.CreateCompatibleBitmap, V, [V, ctypes.c_int, ctypes.c_int]), (g.SelectObject, V, [V, V]),
                    (g.BitBlt, ctypes.c_bool, [V, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, V, ctypes.c_int, ctypes.c_int, ctypes.c_uint32]),
                    (g.GetDIBits, ctypes.c_int, [V, V, ctypes.c_uint, ctypes.c_uint, V, V, ctypes.c_uint]), (g.DeleteObject, ctypes.c_bool, [V]),
                    (g.DeleteDC, ctypes.c_bool, [V])):
        f.restype = r; f.argtypes = a
    scr = u.GetDC(None)
    if not scr: return None
    sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    if region:
        x, y, w, h = region; w = w or sw
        x, y = (sw + x if x < 0 else x), (sh // 2 if y is None else sh + y if y < 0 else y)
    else: w = h = size; x, y = max(0, sw // 2 - size // 2), max(0, sh // 2 - size // 2)
    mem = g.CreateCompatibleDC(scr); bmp = g.CreateCompatibleBitmap(scr, w, h)
    try:
        g.SelectObject(mem, bmp)
        if not g.BitBlt(mem, 0, 0, w, h, scr, max(0, x), max(0, y), 0x00CC0020): return None            # SRCCOPY
        class BIH(ctypes.Structure): _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_uint16),
                                                 ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32),
                                                 ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]
        bi = BIH(); bi.biSize = ctypes.sizeof(BIH); bi.biWidth = w; bi.biHeight = -h; bi.biPlanes = 1; bi.biBitCount = 32
        buf = ctypes.create_string_buffer(w * h * 4)
        return buf.raw if g.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0) == h else None
    finally:
        g.DeleteObject(bmp); g.DeleteDC(mem); u.ReleaseDC(None, scr)


# ---------------------------------------------------------------- the capture probe
def varied(px: bytes, step: int) -> bool:
    """Are the pixels not all the same colour? (alpha ignored)"""
    if not px or len(px) < step * 2: return False
    c = min(step, 3); first = px[:c]
    return any(px[i:i + c] != first for i in range(step, len(px) - step + 1, step))


def bmp_pixels(b: bytes):
    """An uncompressed BMP (screencapture -t bmp) -> (pixel bytes, bytes per pixel), or None."""
    if len(b) < 54 or b[:2] != b"BM": return None
    off = int.from_bytes(b[10:14], "little"); bpp = int.from_bytes(b[28:30], "little"); comp = int.from_bytes(b[30:34], "little")
    if bpp not in (24, 32) or comp not in (0, 3) or off >= len(b): return None
    return b[off:], bpp // 8


def capture_probe(sys_=None, env=None, run=None, which=None, grab=None, tmp=None, strips=None) -> dict:
    """-> {ok: True (pixels came back and vary) | None (they came back all one colour: cannot tell) | False (no picture), why, sandbox_hint}.
    The region is tiny and is never kept: macOS / Linux write it to a temp file that is read and deleted at once, Windows keeps it in memory."""
    sys_ = sys_ or osdirs.system(); run = run or _run; which = which or shutil.which; env = os.environ if env is None else env

    def res(px, step, how):
        if px is None: return {"ok": False, "why": f"{how[0]}：没有拿到图像", "why_en": f"{how[1]}: no picture came back"}
        if varied(px, step): return {"ok": True, "why": f"{how[0]}：拿到了一小块图像（看完就删了，没有保存）",
                                     "why_en": f"{how[1]}: got a small picture (deleted right after the look, never saved)"}
        return {"ok": None, "why": f"{how[0]}：拿到的一小块全是同一个颜色，看不出来是不是真的截到了",
                "why_en": f"{how[1]}: the small picture is all one colour, so it cannot tell whether the capture really worked"}

    if sys_ == "windows":
        try: px = (grab or win_grab)()
        except (OSError, AttributeError, ValueError) as e:
            return {"ok": False, "why": f"BitBlt 32x32：{e}", "why_en": f"BitBlt 32x32: {e}", "sandbox_hint": bool(SANDBOX_ERR.search(str(e)))}
        r = res(px, 4, ("屏幕中间 32x32（BitBlt，只在内存里）", "32x32 in the middle of the screen (BitBlt, in memory only)"))
        if strips is None and grab is None: strips = lambda: [win_grab(region=(0, y, 0, 2)) for y in (None, -24)]
        if r["ok"] is None and strips and any(px or b""):
            # one colour but not black: the middle of a plain window (a real Windows 11 PC 2026-11-02: the Claude app's dark pane).
            # Two thin lines across the whole screen, the middle and the taskbar, almost always cross something else
            try: more = strips()
            except (OSError, AttributeError, ValueError): more = []
            for strip in [s for s in more if s]:
                if varied(strip, 4):
                    r = {"ok": True, "why": "屏幕中间 32x32 是同一个颜色，横穿屏幕的一条线有不同颜色：截得到（只在内存里，没有保存）",
                         "why_en": "32x32 in the middle is one colour, a line across the screen is not: capture works (in memory only, never saved)"}
                    break
        if r["ok"] is None and px is not None and not any(px):
            r = {"ok": False, "why": "屏幕中间 32x32 是全黑的：这个进程不在她的桌面会话里（服务 / SSH / 锁屏）",
                 "why_en": "32x32 in the middle of the screen is all black: this process is not in your desktop session (a service / SSH / locked screen)"}
        return r
    d = Path(tempfile.mkdtemp(prefix="ga-ready-", dir=tmp)); out = None
    try:
        if sys_ == "mac":
            f = d / "p.bmp"; out = run(["screencapture", "-x", "-R0,0,16,16", "-t", "bmp", str(f)], timeout=20); how = ("菜单栏左上角 16x16（screencapture）", "16x16 at the menu bar's left corner (screencapture)")
            got = bmp_pixels(f.read_bytes()) if f.is_file() else None
            if got is None and f.is_file(): return {"ok": None, "why": how[0] + "：截到了，但读不出像素", "why_en": how[1] + ": captured, but the pixels could not be read"}
            px, step = got if got else (None, 4)
        else:
            if idlemod.session(env) != "x11": return {"ok": False, "why": "没有 X11 会话：截不了窗口", "why_en": "No X11 session: windows cannot be captured"}
            f = d / "p.rgb"; disp = env.get("DISPLAY") or ":0"
            if which("ffmpeg"):
                how = ("屏幕左上角 16x16（ffmpeg x11grab）", "16x16 at the screen's top-left corner (ffmpeg x11grab)")
                out = run(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-video_size", "16x16", "-i", f"{disp}+0,0", "-frames:v", "1",
                           "-f", "rawvideo", "-pix_fmt", "rgb24", str(f)], timeout=20)
            elif which("import"):
                how = ("屏幕左上角 16x16（import）", "16x16 at the screen's top-left corner (import)")
                out = run(["import", "-silent", "-window", "root", "-crop", "16x16+0+0", "+repage", "-depth", "8", f"rgb:{f}"], timeout=20)
            else: return {"ok": False, "why": "没有 ffmpeg 也没有 import（ImageMagick）：截不了", "why_en": "Neither ffmpeg nor import (ImageMagick): cannot capture"}
            px, step = (f.read_bytes() if f.is_file() else None), 3
        r = res(px, step, how)
        if r["ok"] is False:
            err = (getattr(out, "stderr", "") or "").strip()[:200]
            if err: r["why"] += f"（{err}）"; r["why_en"] += f" ({err})"
            r["sandbox_hint"] = bool(SANDBOX_ERR.search(err))
        return r
    finally:
        shutil.rmtree(d, ignore_errors=True)                           # the picture is gone right away, whatever happened


# ---------------------------------------------------------------- the check
def _fix_text(items, lang="zh") -> list:
    sep = ": " if lang == "en" else "："
    return [f"{hands.text(i, 'name', lang)}{sep}{hands.text(i, 'how', lang)}" for i in items if i["ok"] is False and i.get("how")]


def _en(i, **kw):
    """Set an item's English texts (kw: name / why / how) next to the Chinese ones."""
    i["en"] = {**(i.get("en") or {}), **kw}; return i


def win_elevated(pid: int):
    """Windows: does process `pid` run elevated (as administrator)? -> True / False, or None when it cannot tell. A normal process may
    not open an elevated one's token: that refusal (ERROR_ACCESS_DENIED) also means elevated."""
    import ctypes
    from ctypes import wintypes as W
    k = ctypes.WinDLL("kernel32", use_last_error=True); a = ctypes.WinDLL("advapi32", use_last_error=True)
    k.OpenProcess.restype = W.HANDLE; k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    a.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, ctypes.POINTER(W.HANDLE)]
    a.GetTokenInformation.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD)]
    h = k.OpenProcess(0x1000, False, int(pid))                         # PROCESS_QUERY_LIMITED_INFORMATION
    if not h: return None
    try:
        tok = W.HANDLE()
        if not a.OpenProcessToken(h, 0x0008, ctypes.byref(tok)):        # TOKEN_QUERY
            return True if ctypes.get_last_error() == 5 else None
        try:
            v = W.DWORD(); n = W.DWORD()
            if not a.GetTokenInformation(tok, 20, ctypes.byref(v), ctypes.sizeof(v), ctypes.byref(n)): return None     # TokenElevation
            return bool(v.value)
        finally: k.CloseHandle(tok)
    finally: k.CloseHandle(h)


def _project_game_pids(root) -> list:
    from . import get as game
    from .. import projects
    return game(projects.game_of(root)).pids() or []


def check(root=None, role="chat", sys_=None, env=None, perms=None, probe=None, desktop=None, package=None, who=None, now=None,
          game_pids=None, elevated=None) -> dict:
    """Both layers from this process. perms / probe / desktop / package / game_pids / elevated: fakes for the tests (hands.permissions,
    capture_probe, win_desktop, osdirs.windows_package, the project's game processes, win_elevated)."""
    sys_ = sys_ or osdirs.system(); env = os.environ if env is None else env
    c = caller(env); pol = quiet.policy(root) if root else {"drive": "idle"}
    p = perms() if perms else hands.permissions(sys_, env)
    items = [dict(i) for i in p["items"]]
    for i in items:
        if i.get("needs") == "idle":                                   # drive refuses without idle unless native_drive: always
            i["needs"] = "" if pol.get("drive") == "always" else "act"
            if i["needs"] and i["ok"] is False:
                xp = "xprintidle" in (i.get("how") or "")
                i["how"] = ((i["how"] + "；") if xp else "") + \
                    "看不出她在不在时 drive 不按键；要按就请她在项目菜单「什么时候开游戏」勾「我在用电脑时也可以操作游戏窗口」"
                _en(i, how=((hands.text(i, "how", "en") + "; ") if xp else "") + "while it cannot tell whether you are at the computer, drive presses no keys; "
                    "to allow it, tick \"Agents may operate the game window while I'm using the computer\" in the project menu's \"When to open the game\"")
    if sys_ == "windows":
        try: dk = desktop() if desktop else win_desktop()
        except (OSError, AttributeError) as e: dk = {"session": None, "console": None, "input_desktop": None, "error": str(e)}
        bad = dk.get("session") == 0 or dk.get("input_desktop") is False
        items.append(_en({"name": "她的桌面会话（看、按都要）", "ok": None if dk.get("input_desktop") is None and dk.get("session") is None else not bad, "needs": "both",
                          "why": (f"会话 {dk.get('session')}（控制台会话 {dk.get('console')}），" + ("打得开她的桌面" if dk.get("input_desktop") else "打不开她的桌面")
                                  + ("；是通过 SSH 运行的" if c["ssh"] else "")),
                          "how": "在她登录的 Windows 桌面里运行（开始菜单里的 Windows Terminal / PowerShell，或者从那里开的 agent）；SSH、Windows 服务、"
                                 "计划任务里看不到也按不到她的桌面。锁屏、UAC 弹窗时也不行：解锁后再查一次"},
                         name="Your desktop session (needed to look and to click)",
                         why=(f"session {dk.get('session')} (console session {dk.get('console')}), " + ("your desktop opens" if dk.get("input_desktop") else "your desktop does not open")
                              + ("; run over SSH" if c["ssh"] else "")),
                         how="Run it in the Windows desktop you are logged in to (Windows Terminal / PowerShell from the Start menu, or an agent started from there); "
                             "SSH, Windows services and scheduled tasks cannot see or click your desktop. Not while the screen is locked or a UAC prompt is up either: "
                             "unlock and check again"))
        try: pkg = package() if package else osdirs.windows_package()
        except OSError: pkg = None
        items.append(_en({"name": "打包的 app（MSIX）", "ok": None if not pkg else False, "needs": "",
                          "why": f"在打包的 app {pkg} 里运行：新建在 AppData 下的文件夹被 Windows 挪到它自己的 LocalCache，从 Steam 开的游戏看不到（mod、备份）；"
                                 "看、按游戏本身不受影响（未实测）" if pkg else "不在打包的 app 里（或看不出来）",
                          "how": "装 mod、备份、开游戏用普通终端（Windows Terminal / PowerShell）里的 gameanything；Claude 桌面 app 的 Code 页就是打包的 app" if pkg else ""},
                         name="Packaged app (MSIX)",
                         why=f"Running inside the packaged app {pkg}: Windows moves new folders under AppData to the app's own LocalCache, where a game started from "
                             "Steam does not see them (mods, backups); looking at and clicking the game is not affected (not tested)" if pkg else
                             "Not inside a packaged app (or it cannot tell)",
                         how="Install mods, back up and open the game with gameanything in a normal terminal (Windows Terminal / PowerShell); the Claude desktop "
                             "app's Code tab is a packaged app" if pkg else ""))
        # the game's own process, when the project's game is open: its token says whether it runs elevated (it was always "cannot tell")
        try:
            pids = (game_pids() if game_pids else _project_game_pids(root)) if root or game_pids else []
            elev = [(elevated or win_elevated)(p) for p in pids or []]
        except (OSError, AttributeError, ValueError): elev = []
        up = any(e is True for e in elev); known = bool(elev) and all(e is not None for e in elev)
        items.append(_en({"name": "游戏不是管理员身份", "ok": False if up else True if known else None, "needs": "act" if up else "",
                          "why": "游戏是以管理员身份运行的：它不收普通程序的按键（UIPI），drive 按不到" if up else
                                 "开着的游戏是普通身份：按键收得到" if known else "以管理员身份开的游戏不收普通程序的按键（UIPI）；游戏开着之前看不出来",
                          "how": "关掉游戏，别用「以管理员身份运行」开游戏或 Steam，再开一次" if up else "不要右键「以管理员身份运行」游戏或 Steam"},
                         name="The game is not running as administrator",
                         why="The game runs as administrator: it ignores keys from normal programs (UIPI), drive cannot press them" if up else
                             "The open game runs as a normal user: it gets the keys" if known else
                             "A game started as administrator ignores keys from normal programs (UIPI); this cannot be seen before the game is open",
                         how="Close the game and start it (or Steam) again without \"Run as administrator\"" if up else
                             "Do not right-click the game or Steam and choose \"Run as administrator\""))
    pr = probe() if probe else capture_probe(sys_, env)
    scr = next((i for i in items if i.get("needs") == "look" and i["ok"] is False), None)
    if sys_ == "mac" and pr["ok"] and scr:                             # macOS shows the menu bar to anyone (seen in Terminal without the permission, 2026-11-01)
        pr = {**pr, "ok": None, "why": pr["why"] + "；可是菜单栏不要「屏幕录制」也截得到，所以这一项说明不了能不能截游戏窗口",
              "why_en": pr.get("why_en", pr["why"]) + "; but the menu bar can be captured without Screen Recording, so this says nothing about the game window"}
    if sys_ == "mac" and c["sandbox"]:                                 # inside Codex the permission checks said no although the app had both (2026-11-01)
        for i in items:
            if i.get("needs") in ("look", "act") and i["ok"] is False and i["name"].startswith(("辅助功能", "屏幕录制")):
                i["why"] += f"；在 {c['sandbox']} 沙箱里查的：沙箱本身就可能让这一项查不到，给了权限也不一定有用"
                i["how"] = "不要为这个关掉或放宽沙箱；换一个不在沙箱里的 agent（例如终端里的 Claude Code），或者选「不给，我自己点」"
                _en(i, why=hands.text(i, "why", "en") + f"; checked inside the {c['sandbox']} sandbox: the sandbox itself may hide this permission, so "
                    "turning it on may not help", how="Do not turn off or loosen the sandbox for this; use an agent that is not sandboxed (e.g. Claude Code "
                    "in a terminal), or choose \"No, I'll click myself\"")
    boxed = c["sandbox"] or pr.get("sandbox_hint")
    items.append(_en({"name": "试截一小块（不保存）", "ok": pr["ok"], "why": pr["why"], "needs": "look",
                      "how": ("在 agent 的沙箱里截不了：不要为这个关掉或放宽沙箱；换一个能截图的 agent，或者选「不给，我自己点」" if boxed else
                              "macOS：照上面的「屏幕录制」打开，退出重开那个程序" if sys_ == "mac" else
                              "在她登录的桌面里运行（不是 SSH / 服务）" if sys_ == "windows" else "在她登录的 X11 桌面里运行，装 ffmpeg 或 imagemagick")},
                     name="A tiny test capture (not saved)", why=pr.get("why_en", pr["why"]),
                     how=("The agent's sandbox blocks the capture: do not turn off or loosen the sandbox for this; use an agent that can capture, or choose "
                          "\"No, I'll click myself\"" if boxed else
                          "macOS: turn on Screen Recording as above, then quit and reopen that app" if sys_ == "mac" else
                          "Run it in the desktop you are logged in to (not SSH / a service)" if sys_ == "windows" else
                          "Run it in the X11 desktop you are logged in to, with ffmpeg or imagemagick installed")))
    if boxed:
        items.append(_en({"name": "agent 的沙箱", "ok": None, "needs": "",
                          "why": (f"在 {c['sandbox']} 沙箱里运行：上面的结果就是沙箱里的结果" if c["sandbox"] else "报错像是沙箱挡住了")
                                 + "；按键能不能到游戏，不按键就没法验证（未实测），第一次 drive 报错就是被挡住了",
                          "how": "不要为这个关掉或放宽 agent 的沙箱（Codex 的 workspace-write 也不改）：换 agent（Claude Code 等）或选「不给，我自己点」"},
                         name="The agent's sandbox",
                         why=(f"Running inside the {c['sandbox']} sandbox: the results above are the sandbox's" if c["sandbox"] else "The error looks like a sandbox blocked it")
                             + "; whether keys reach the game cannot be known without pressing one (not tested): if the first drive fails, the sandbox blocked it",
                         how="Do not turn off or loosen the agent's sandbox for this (Codex's workspace-write stays as it is): use another agent (Claude Code, …) "
                             "or choose \"No, I'll click myself\""))
    look = all(i["ok"] is not False for i in items if i.get("needs") in ("look", "both"))
    act = all(i["ok"] is not False for i in items if i.get("needs") in ("act", "both"))
    level = "full" if look and act else "look" if look else "none"
    if sys_ == "mac" and who is None: who = hands.mac_app()
    from .. import models
    eff = models.effective(root, role) if root else {"agent": "", "model": ""}
    return {"system": sys_, "level": level, "look": look, "act": act, "items": items, "fix": _fix_text(items), "fix_en": _fix_text(items, "en"), "caller": c,
            "app": who or "", "role": role, "for": {"agent": eff.get("agent") or "", "model": eff.get("model") or ""},
            "at": quiet._iso(now or datetime.now())}


# ---------------------------------------------------------------- the record + her answer
def _file(root) -> Path: return Path(root) / "conversation" / ".native_ready.json"


def records(root) -> dict:
    try: d = json.loads(_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}
    return d if isinstance(d, dict) else {}


def _save(root, role, rec):
    d = records(root); d[role] = rec; f = _file(root); f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".tmp"); tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8"); os.replace(tmp, f)


def default_role(env=None) -> str:
    env = os.environ if env is None else env
    return "build" if env.get("GAMEANYTHING_ROLE") == "builder" else "chat"


def state(root, role="chat", sys_=None) -> dict:
    """-> {rec, fresh, why}: fresh = the record was made for the agent + model this role uses now, on this system."""
    from .. import models
    rec = records(root).get(role); eff = models.effective(root, role)
    if not rec: return {"rec": None, "fresh": False, "why": "还没查过"}
    was = rec.get("for") or {}
    if (was.get("agent") or "", was.get("model") or "") != (eff.get("agent") or "", eff.get("model") or ""):
        return {"rec": rec, "fresh": False, "why": f"上次查的是 {models.label(was.get('agent') or '', was.get('model') or '')}，现在是 "
                                                  f"{models.label(eff.get('agent') or '', eff.get('model') or '')}：换了 agent / 模型，权限可能不一样"}
    if rec.get("system") != (sys_ or osdirs.system()): return {"rec": rec, "fresh": False, "why": "上次是在另一种系统上查的"}
    return {"rec": rec, "fresh": True, "why": "这个 agent / 模型查过了"}


def _card(root):
    from ..conversation import Thread
    return next((v for v in Thread(root).cards().values() if v["card"].get("key") == CARD_KEY), None)


def card_body(r: dict, game_title: str = "游戏") -> dict:
    """The ONE card the resident posts (gameanything chat card --file) when the level is below full: the exact steps, two choices."""
    hint = [i for i in r["items"] if i["ok"] is None and i.get("how") and i.get("needs")]
    steps = r["fix"] or [f"{i['name']}：{i['how']}" for i in hint]
    steps_en = r.get("fix_en") or _fix_text([i for i in r["items"] if i["ok"] is False and i.get("how")], "en") \
        or [f"{hands.text(i, 'name', 'en')}: {hands.text(i, 'how', 'en')}" for i in hint]
    lvl = LEVEL_TEXT[r["level"]]; who = f"「{r['app']}」" if r.get("app") else "运行 agent 的那个程序"
    sb = r["caller"].get("sandbox")
    lead = (f"现在 agent {lvl}你电脑上的{game_title}窗口（{'在 ' + sb + ' 沙箱里，' if sb else ''}权限要给{who}）。"
            "给了以后，测试时 agent 自己看画面、自己按键，你不用守着；不给也行，那就每一轮告诉你要点哪里，你点完说「好了」。")
    title_en = game_title if game_title != "游戏" else "game"
    lead_en = (f"Right now the agent can {'look at but not click' if r['level'] == 'look' else 'neither look at nor click'} your {title_en} window"
               f"{' (inside the ' + sb + ' sandbox)' if sb else ''}{' (the permission goes to ' + chr(34) + app_text(r['app'], 'en') + chr(34) + ')' if r.get('app') else ''}. "
               "With the permission it looks and presses keys by itself during tests; without it, each round tells you what to click and you say \"done\".")
    how_en = (" Turn it on like this: " + "; ".join(f"{n + 1}. {s}" for n, s in enumerate(steps_en))) if steps_en else " Follow the steps gameanything native ready prints."
    how = "照这样打开：" + "；".join(f"{n + 1}. {s}" for n, s in enumerate(steps)) if steps else "照 gameanything native ready 打印的步骤打开"
    return {"kind": "options", "key": CARD_KEY, "multi": False, "title": "让 agent 能看、能点你的游戏窗口吗？", "level": r["level"], "role": r["role"],
            "items": [{"key": "again", "title": "我打开了，再查一次", "desc": lead + how, "recommended": True},
                      {"key": "self", "title": "不给，我自己点", "desc": "agent 不操作游戏：每一轮在进度卡里写清楚要你点哪里，你点完说「好了」"
                                                                       + ("；它也看不到画面时会请你发截图或说说看到了什么" if r["level"] == "none" else "")}],
            "en": {"title": "Let the agent look at and click your game window?",
                   "items": [{"key": "again", "title": "I turned it on, check again", "desc": lead_en + how_en, "recommended": True},
                             {"key": "self", "title": "No, I'll click myself", "desc": "The agent never presses keys in the game: each round's progress card lists what to "
                                                                                      "click, and you say \"done\" when you have"
                                                                                      + ("; as it cannot see the screen either, it asks you for a screenshot or what you see"
                                                                                         if r["level"] == "none" else "")}]}}


def run(root, role=None, if_needed=False, sys_=None, card_file=None, game_title="游戏", **kw) -> dict:
    """The check (or the fresh record with if_needed), her answer on the readiness card applied, the record written. -> the check +
    {cached, hands, card: none | waiting | again | self, next: ok | card | wait | self, why}."""
    role = role or default_role(); sys_ = sys_ or osdirs.system()
    st = state(root, role, sys_)
    if if_needed and st["fresh"]: r = {**st["rec"], "cached": True}
    else: r = {**check(root, role, sys_=sys_, **kw), "cached": False}
    c = _card(root); a = quiet._answer(c) if c else None; pick = (((a or {}).get("answer") or {}).get("picked") or [None])[0]
    applied = set((records(root).get(role) or {}).get("answers_applied") or [])
    if a and pick == "self" and a["id"] not in applied:                # her click 「不给，我自己点」 -> native_hands: self (she can change it in the menu)
        from .. import projects
        quiet.set_policy(projects.find(str(root))["id"], None, hands="self"); applied.add(a["id"])
    elif a and pick == "again": applied.add(a["id"])
    hs = quiet.policy(root)["hands"]
    r["hands"] = hs; r["answers_applied"] = sorted(applied)
    r["card"] = "none" if c is None else "waiting" if a is None else (pick or "note")
    if hs == "self":
        r["next"] = "self"; r["why"] = ("她选了自己点（native_hands: self）：不调用 drive；每一轮的进度卡写清楚要她点哪里，等她说「好了」"
                                         + ("；shot 也用不了：请她发截图或说说看到了什么" if not r["look"] else "；可以用 shot 看画面"))
        r["why_en"] = ("The user chose to click herself (native_hands: self): no drive; each round's progress card says what to click, then wait for her \"done\""
                       + ("; shot does not work either: ask her for a screenshot or what she sees" if not r["look"] else "; shot can look at the screen"))
    elif r["level"] == "full": r["next"] = "ok"; r["why"] = "能看、能点：照常用 native shot / drive"; r["why_en"] = "Can look and click: use native shot / drive as usual"
    elif c is not None and a is None and (c["card"].get("role"), c["card"].get("level")) == (role, r["level"]):
        r["next"] = "wait"; r["why"] = "卡已经发了，她还没回答：不要再发；先用 shot（能看时）或请她帮忙点"
        r["why_en"] = "The card is out and not answered yet: do not post another; use shot meanwhile (when it can look) or ask her to click"
    else:
        r["next"] = "card"; r["why"] = f"{LEVEL_TEXT[r['level']]}：发一张卡（key {CARD_KEY}）请她打开权限，或者选「不给，我自己点」"
        r["why_en"] = f"{LEVEL_EN[r['level']].capitalize()}: post one card (key {CARD_KEY}) asking her to turn the permission on, or to choose \"No, I'll click myself\""
        if card_file:
            import yaml
            Path(card_file).parent.mkdir(parents=True, exist_ok=True)
            from .. import projects
            body = {**card_body(r, game_title), "project": projects.find(str(root))["id"]}     # `chat card` refuses it in another project's chat
            Path(card_file).write_text(yaml.safe_dump(body, allow_unicode=True, sort_keys=False), encoding="utf-8")
            r["card_file"] = str(card_file)
    if not r["cached"]:
        _save(root, role, {k: r[k] for k in ("system", "level", "look", "act", "items", "caller", "app", "role", "for", "at")} | {"answers_applied": r["answers_applied"]})
    elif applied != set((st["rec"] or {}).get("answers_applied") or []):
        _save(root, role, {**st["rec"], "answers_applied": r["answers_applied"]})
    return r


def summary(root) -> dict:
    """For the project menu: {hands, front, chat: {level, label, at, fresh, why} | None, build: …}."""
    from .. import models
    pol = quiet.policy(root); out = {"hands": pol["hands"], "front": pol["front"]}
    for role in ("chat", "build"):
        try: st = state(root, role)
        except Exception: st = {"rec": None, "fresh": False, "why": ""}
        rec = st["rec"]
        out[role] = None if not rec else {"level": rec.get("level"), "at": rec.get("at"), "fresh": st["fresh"], "why": st["why"], "system": rec.get("system"),
                                          "who": models.label((rec.get("for") or {}).get("agent") or "", (rec.get("for") or {}).get("model") or ""),
                                          "fix": _fix_text(rec.get("items") or []), "fix_en": _fix_text(rec.get("items") or [], "en")}
    return out
