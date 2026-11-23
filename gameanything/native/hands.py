"""本机模式少打扰, part 2 (2026-10-24): look at and press keys in ONLY the game GameAnything opened, without taking her screen,
mouse or keyboard focus. Ideas from Universal Modder (MIT License, Copyright (c) 2026 Rehan and
universal-modder contributors, https://github.com/rehan-remade/universal-modder: `um win drive` / WinDrive.ps1 — input only goes to the game,
check `idle` before driving); no code was copied, the code here is our own.

    target(root, g)                    the game GameAnything opened for this project (recorded at `gameanything native launch`) -> (launch, pids); anything
                                       else (her own game, nothing open) is refused - with native_drive: always her running game is taken over
    shot(root, g, out=None)            a picture of that game's window only (not the screen), never bringing it to the front
    drive(root, g, steps)              keys / clicks / text sent to that window only; refused while she is using the computer (input in the
                                       last DRIVE_IDLE_SECS) unless she chose 「我在用电脑时也可以」 (native_drive: always); stops (pauses) as
                                       soon as she touches the mouse or keyboard again
    permissions(sys_)                  what this computer allows (macOS Accessibility + Screen Recording), and how to grant it; each item
                                       says what it is needed for (needs: look | act | both | ""), ready.py turns that into a level

Per system:
    macOS     windows: CGWindowListCopyWindowInfo (by owner pid); picture: `screencapture -x -o -l <window id>`; input: CGEventPostToPid
              (to the game process, no focus change). Needs Accessibility (input) and Screen Recording (picture) for the app that runs GameAnything.
              A click lands on whatever window is at that point (her Mac, 2026-10-25: with the Claude app over the game, drive's clicks
              went to Claude and the game lost focus): before clicking, the windows in front of the game (z-order + bounds) are checked
              and a covered click is refused (with native_drive: always the game is brought to the front first). Games whose buttons
              ignore CGEventPostToPid clicks (Game.mac_click = "hid": Stardew Valley, Slay the Spire) get a real cursor move + click
              (CGEventPost to the HID tap; her cursor is put back), ONLY while the game is the front window and she is away
              (native_drive: always: any time, her rule 2026-10-29).
    Windows   windows: EnumWindows by pid; picture: PrintWindow(PW_RENDERFULLCONTENT) into a bitmap (a GPU game may come out black: then
              use ffmpeg's gfxcapture, docs); input: SendInput, which goes to the foreground window: ONLY while the game already is the
              foreground window, else refused - unless she ticked 「测试时允许把游戏切到前面」 (native_front: away, her decision 2026-11-01):
              then, and only while she has been away DRIVE_IDLE_SECS (idle known), the game GameAnything opened is brought to the front
              (restored when minimized; AttachThreadInput + SetForegroundWindow) and the result records it (`fronted`).
    Linux     X11 only: `xdotool search --pid`, `xdotool key|type|click --window <id>` (no activation), `import -window <id>` or ffmpeg
              x11grab of the window's rectangle. Wayland lets no program do this: refused. A game window without _NET_WM_PID (LWJGL 2:
              Slay the Spire's game window, while xdotool finds only ModTheSpire's launcher by pid) is found by the game's exact
              `window_titles`, and only when no other process claims it.
Steps (each one argument): `key <name>` (a-z 0-9 return/enter escape/esc space tab backspace up down left right f1-f12), `click <x> <y>
[right]` (in the window, from its top-left corner), `type <text>`, `sleep <ms>`.
"""
import ctypes
import os
import re
import shutil
import struct
import sys
import time
import zlib
from datetime import datetime
from pathlib import Path

from .. import osdirs
from . import idle as idlemod
from . import quiet
from .games import NativeError, _run

DRIVE_IDLE_SECS = 60          # she touched the mouse / keyboard less than this long ago: she is at the computer, do not drive
OWN_INPUT_SLACK = 1.5         # an input event at most this long after GameAnything's last step is GameAnything's own (Windows counts SendInput as input)
SHOT_DIR = "5_build/native-shots"


class Refused(NativeError):
    """code: why nothing was done; pending=True when it may work later (she is at the computer), else it will not work as asked."""
    def __init__(self, code, why, pending=False):
        super().__init__(why); self.code = code; self.why = why; self.pending = pending


# ---------------------------------------------------------------- steps
KEY_NAMES = [*"abcdefghijklmnopqrstuvwxyz0123456789", "return", "escape", "space", "tab", "backspace", "up", "down", "left", "right",
             *[f"f{i}" for i in range(1, 13)]]
ALIASES = {"enter": "return", "esc": "escape", "bksp": "backspace"}


def parse_steps(steps) -> list:
    out = []
    for s in steps:
        w = str(s).strip().split(None, 1); verb = w[0].lower() if w else ""; rest = w[1] if len(w) > 1 else ""
        if verb == "key":
            k = ALIASES.get(rest.strip().lower(), rest.strip().lower())
            if k not in KEY_NAMES: raise ValueError(f"不认识的键 {rest!r}：可以用 {' '.join(KEY_NAMES[36:])}、字母和数字")
            out.append(("key", k))
        elif verb == "click":
            p = rest.split()
            if len(p) not in (2, 3) or not all(x.isdigit() for x in p[:2]) or (len(p) == 3 and p[2] not in ("left", "right")):
                raise ValueError(f"click 要写成 click <x> <y> [right]（窗口里的坐标）：{s!r}")
            out.append(("click", int(p[0]), int(p[1]), p[2] if len(p) == 3 else "left"))
        elif verb == "type":
            if not rest: raise ValueError("type 后面要写字")
            out.append(("type", rest))
        elif verb == "sleep":
            if not rest.strip().isdigit() or int(rest) > 60000: raise ValueError(f"sleep 要写毫秒数（最多 60000）：{s!r}")
            out.append(("sleep", int(rest)))
        else: raise ValueError(f"不认识的步骤 {s!r}：key / click / type / sleep")
    if not out: raise ValueError("没有步骤")
    return out


# ---------------------------------------------------------------- the target: only the game GameAnything opened
def target(root, g, now=None):
    x, ps = quiet.current(root, g, now)                                # native_drive: always also takes over a game she opened
    if x is None:
        if g.running(): raise Refused("not_ours", f"{g.title} 开着，但不是 GameAnything 开的（是她自己开的）：不截图、不操作")
        raise Refused("none", "没有 GameAnything 开着的游戏：先 gameanything native launch --project P")
    if not ps: raise Refused("gone", "GameAnything 开的游戏已经关了（或者还没认出它的进程）")
    return x, [int(p["pid"]) for p in ps]


def pick(wins, pids):
    """The game's main window: the largest visible, not minimized one of these processes (macOS: normal window layer 0)."""
    c = [w for w in wins if int(w["pid"]) in set(pids) and not w.get("minimized") and w.get("layer", 0) == 0 and w["w"] > 0 and w["h"] > 0]
    return max(c, key=lambda w: w["w"] * w["h"]) if c else None


# ---------------------------------------------------------------- pictures
def write_png(path: Path, w: int, h: int, rgb: bytes):
    """A plain 8-bit RGB PNG (no Pillow needed)."""
    stride = w * 3
    raw = b"".join(b"\x00" + bytes(rgb[y * stride:(y + 1) * stride]) for y in range(h))
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def bgra_to_rgb(b: bytes) -> bytes:
    rgb = bytearray(len(b) // 4 * 3); rgb[0::3] = b[2::4]; rgb[1::3] = b[1::4]; rgb[2::3] = b[0::4]; return bytes(rgb)


# ---------------------------------------------------------------- macOS (ctypes: CoreGraphics / CoreFoundation / ApplicationServices)
MAC_KEY_HOLD = 0.08          # seconds a key stays down (several frames even at 20-30 fps): see MacInput.send
MAC_HID_STEP = 0.12          # seconds between a real click's move / down / up and before the cursor goes back: games that POLL the mouse once
                             # per frame (tModLoader / FNA) missed 50 ms steps - press and release fell between two frames, and the cursor
                             # was back at her spot when the frame looked (her Mac, 2026-10-29)
MAC_KEYS = {"a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15,
            "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "9": 25, "7": 26, "8": 28, "0": 29, "o": 31, "u": 32,
            "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46, "return": 36, "tab": 48, "space": 49, "backspace": 51,
            "escape": 53, "left": 123, "right": 124, "down": 125, "up": 126, "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
            "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111}
_FW = "/System/Library/Frameworks/{0}.framework/{0}"


class _CGPoint(ctypes.Structure): _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]
class _CGSize(ctypes.Structure): _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]
class _CGRect(ctypes.Structure): _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


class MacBackend:
    name = "macOS"

    def __init__(self, run=None):
        self.run = run or _run
        V, P = ctypes.c_void_p, ctypes.c_void_p
        cf = self.cf = ctypes.CDLL(_FW.format("CoreFoundation")); cg = self.cg = ctypes.CDLL(_FW.format("CoreGraphics"))
        cg.CGWindowListCopyWindowInfo.restype = V; cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        cf.CFArrayGetCount.restype = ctypes.c_long; cf.CFArrayGetCount.argtypes = [V]
        cf.CFArrayGetValueAtIndex.restype = V; cf.CFArrayGetValueAtIndex.argtypes = [V, ctypes.c_long]
        cf.CFDictionaryGetValue.restype = V; cf.CFDictionaryGetValue.argtypes = [V, V]
        cf.CFStringCreateWithCString.restype = V; cf.CFStringCreateWithCString.argtypes = [V, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFStringGetCString.restype = ctypes.c_bool; cf.CFStringGetCString.argtypes = [V, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
        cf.CFNumberGetValue.restype = ctypes.c_bool; cf.CFNumberGetValue.argtypes = [V, ctypes.c_int, P]
        cf.CFRelease.argtypes = [V]
        cg.CGRectMakeWithDictionaryRepresentation.restype = ctypes.c_bool; cg.CGRectMakeWithDictionaryRepresentation.argtypes = [V, ctypes.POINTER(_CGRect)]
        cg.CGEventCreateKeyboardEvent.restype = V; cg.CGEventCreateKeyboardEvent.argtypes = [V, ctypes.c_uint16, ctypes.c_bool]
        cg.CGEventCreateMouseEvent.restype = V; cg.CGEventCreateMouseEvent.argtypes = [V, ctypes.c_uint32, _CGPoint, ctypes.c_uint32]
        cg.CGEventKeyboardSetUnicodeString.argtypes = [V, ctypes.c_ulong, ctypes.POINTER(ctypes.c_uint16)]
        cg.CGEventPostToPid.argtypes = [ctypes.c_int, V]
        cg.CGEventPost.argtypes = [ctypes.c_uint32, V]
        cg.CGEventCreate.restype = V; cg.CGEventCreate.argtypes = [V]
        cg.CGEventGetLocation.restype = _CGPoint; cg.CGEventGetLocation.argtypes = [V]
        cg.CGWarpMouseCursorPosition.restype = ctypes.c_int32; cg.CGWarpMouseCursorPosition.argtypes = [_CGPoint]
        cg.CGEventSetIntegerValueField.argtypes = [V, ctypes.c_uint32, ctypes.c_int64]
        self._keys = {}
        self.click_method = "pid"                                    # drive() sets it from the game's mac_click

    def _k(self, s):
        if s not in self._keys: self._keys[s] = self.cf.CFStringCreateWithCString(None, s.encode(), 0x08000100)      # kCFStringEncodingUTF8
        return self._keys[s]

    def _num(self, d, key):
        v = self.cf.CFDictionaryGetValue(d, self._k(key)); out = ctypes.c_int64(0)
        return int(out.value) if v and self.cf.CFNumberGetValue(v, 4, ctypes.byref(out)) else None        # kCFNumberSInt64Type

    def _str(self, d, key):
        v = self.cf.CFDictionaryGetValue(d, self._k(key)); buf = ctypes.create_string_buffer(512)
        return buf.value.decode("utf-8", "replace") if v and self.cf.CFStringGetCString(v, buf, 512, 0x08000100) else ""

    def _float(self, d, key):
        v = self.cf.CFDictionaryGetValue(d, self._k(key)); out = ctypes.c_double(0)
        return float(out.value) if v and self.cf.CFNumberGetValue(v, 13, ctypes.byref(out)) else None      # kCFNumberDoubleType

    def _list(self, option, rel=0, pids=None):
        """CGWindowListCopyWindowInfo, front to back -> [{id, pid, layer, alpha, owner, title, x, y, w, h}] (only `pids`' when given)."""
        arr = self.cg.CGWindowListCopyWindowInfo(option, rel)
        if not arr: return []
        out = []
        try:
            for i in range(self.cf.CFArrayGetCount(arr)):
                d = self.cf.CFArrayGetValueAtIndex(arr, i); pid = self._num(d, "kCGWindowOwnerPID")
                if pids is not None and pid not in pids: continue
                r = _CGRect(); b = self.cf.CFDictionaryGetValue(d, self._k("kCGWindowBounds"))
                if not b or not self.cg.CGRectMakeWithDictionaryRepresentation(b, ctypes.byref(r)): continue
                owner = self._str(d, "kCGWindowOwnerName")
                out.append({"id": self._num(d, "kCGWindowNumber"), "pid": pid, "layer": self._num(d, "kCGWindowLayer") or 0,
                            "alpha": self._float(d, "kCGWindowAlpha"), "owner": owner, "title": self._str(d, "kCGWindowName") or owner,
                            "x": int(r.origin.x), "y": int(r.origin.y), "w": int(r.size.width), "h": int(r.size.height)})
        finally: self.cf.CFRelease(arr)
        return out

    def windows(self, pids):
        return self._list(1 | 16, 0, pids)                           # on screen only, without desktop elements

    def above(self, win):
        """Every on-screen window in front of the game window (kCGWindowListOptionOnScreenAboveWindow), front to back, any program."""
        return self._list(2 | 16, int(win["id"]))

    def bring_front(self, win):
        """The game app comes to the front: with native_drive: always (she allowed driving while she uses the computer), or before a real
        cursor click (only while she is away)."""
        from . import macapp
        return macapp.activate(win["pid"])

    def frontmost_pid(self):
        from . import macapp
        return macapp.frontmost_pid()

    def move_clear(self, win):
        """Move the game window to the top-left of the screen (below the menu bar), out from under a floating window."""
        from . import macapp
        return macapp.move_window(win["pid"], 0, 38)


    def shot(self, win, out: Path) -> dict:
        r = self.run(["screencapture", "-x", "-o", "-l", str(win["id"]), str(out)], timeout=30)
        if r is None or r.returncode != 0 or not out.is_file():
            raise NativeError("screencapture 没能截下游戏窗口：给运行 GameAnything 的程序打开「屏幕录制」权限（gameanything native permissions）")
        return {}

    def can_send(self, win, pids): return None                       # posted to the game process: no focus needed

    def _post(self, pid, ev):
        if not ev: raise NativeError("CGEvent 没有建出来")
        self.cg.CGEventPostToPid(int(pid), ev); self.cf.CFRelease(ev)

    def send(self, win, step):
        pid = win["pid"]
        if step[0] == "key":
            # hold the key MAC_KEY_HOLD: Unity polls the keyboard once per frame, and a 20 ms press fell between frames of KSP (Rosetta, window
            # not in front) - 1 of 4 F8 presses arrived on her Mac (2026-10-29)
            # games marked mac_keys: hid (tModLoader: FNA / SDL) ignored keys posted to the process (Escape and 1-9 did nothing in a
            # Terraria world on her Mac, 2026-10-29; typed text did arrive): their keys go to the HID tap too (drive checked: she is away, game in front)
            for down in (True, False):
                ev = self.cg.CGEventCreateKeyboardEvent(None, MAC_KEYS[step[1]], down)
                if getattr(self, "key_method", None) == "hid":
                    if not ev: raise NativeError("CGEvent 没有建出来")
                    self.cg.CGEventPost(0, ev); self.cf.CFRelease(ev)
                else: self._post(pid, ev)
                time.sleep(MAC_KEY_HOLD if down else 0.02)
        elif step[0] == "type":
            for ch in step[1]:
                u = ch.encode("utf-16-le"); arr = (ctypes.c_uint16 * (len(u) // 2)).from_buffer_copy(u)
                for down in (True, False):
                    ev = self.cg.CGEventCreateKeyboardEvent(None, 0, down)
                    self.cg.CGEventKeyboardSetUnicodeString(ev, len(arr), arr); self._post(pid, ev)
                time.sleep(0.02)
        elif step[0] == "click":
            p = _CGPoint(win["x"] + step[1], win["y"] + step[2]); right = step[3] == "right"
            if self.click_method == "hid":                            # a real cursor move + click (drive checked: game in front, she is away)
                cur = self.cg.CGEventCreate(None); back = self.cg.CGEventGetLocation(cur) if cur else None
                if cur: self.cf.CFRelease(cur)
                try:
                    for t in ((5,) + ((3, 4) if right else (1, 2))):
                        ev = self.cg.CGEventCreateMouseEvent(None, t, p, 1 if right else 0)
                        if not ev: raise NativeError("CGEvent 没有建出来")
                        # kCGMouseEventClickState = 1 on down / up: without it a Chromium-style window (Civ VI's Aspyr launcher, her Mac
                        # 2026-10-29) took the press as the start of a window drag and moved the window instead of pressing PLAY
                        if t != 5: self.cg.CGEventSetIntegerValueField(ev, 1, 1)
                        self.cg.CGEventPost(0, ev); self.cf.CFRelease(ev); time.sleep(MAC_HID_STEP)     # kCGHIDEventTap
                finally:
                    if back is not None: self.cg.CGWarpMouseCursorPosition(back)            # her cursor goes back where it was
                return
            for t in ((5,) + ((3, 4) if right else (1, 2))):         # moved, then down / up (left 1 / 2, right 3 / 4)
                ev = self.cg.CGEventCreateMouseEvent(None, t, p, 1 if right else 0)
                if ev and t != 5: self.cg.CGEventSetIntegerValueField(ev, 1, 1)                  # click state 1 (see above)
                self._post(pid, ev); time.sleep(0.03)


def mac_permissions(ax=None, screen=None) -> list:
    """Accessibility (AXIsProcessTrusted) and Screen Recording (CGPreflightScreenCaptureAccess): True / False / None (cannot tell).
    Neither call shows a prompt."""
    def call(lib, fn):
        try:
            f = getattr(ctypes.CDLL(_FW.format(lib)), fn); f.restype = ctypes.c_bool; return bool(f())
        except (OSError, AttributeError): return None
    a = ax() if ax else call("ApplicationServices", "AXIsProcessTrusted")
    s = screen() if screen else call("CoreGraphics", "CGPreflightScreenCaptureAccess")
    return [a, s]


def mac_app(run=None) -> str:
    """The app this process runs under (Terminal, iTerm, Visual Studio Code, …): macOS gives the permission to that app, not to python.
    A framework Python (Homebrew, python.org) runs as …/Python.app/Contents/MacOS/Python: that bundle is the interpreter, not the app,
    and is the answer only when no other app is above it (agentd / `gameanything ui` started by launchd; seen 2026-11-01: the
    Claude desktop app's Code tab was reported as Python.app)."""
    run = run or _run; pid = os.getpid(); interp = ""
    for _ in range(12):
        r = run(["ps", "-o", "ppid=,comm=", "-p", str(pid)])
        if r is None or r.returncode != 0 or not r.stdout.strip(): break
        ppid, _, comm = r.stdout.strip().partition(" ")
        m = re.search(r"/([^/]+\.app)/", comm.strip())
        if m and m.group(1) == "Python.app": interp = interp or m.group(1)
        elif m: return m.group(1)
        if not ppid.strip().isdigit() or int(ppid) <= 1: break
        pid = int(ppid)
    return interp


# ---------------------------------------------------------------- Windows (ctypes: user32 / gdi32)
WIN_VK = {**{c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz0123456789"}, "return": 0x0D, "escape": 0x1B, "space": 0x20, "tab": 0x09,
          "backspace": 0x08, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, **{f"f{i}": 0x6F + i for i in range(1, 13)}}


class WinBackend:
    name = "Windows"
    needs_front = True                                               # SendInput reaches only the foreground window (drive: native_front)

    def __init__(self):
        V = ctypes.c_void_p
        u = self.u = ctypes.WinDLL("user32"); gd = self.g = ctypes.WinDLL("gdi32")
        class RECT(ctypes.Structure): _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        class POINT(ctypes.Structure): _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        UP = ctypes.c_size_t
        class KI(ctypes.Structure): _fields_ = [("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16), ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("dwExtraInfo", UP)]
        class MI(ctypes.Structure): _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_uint32), ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("dwExtraInfo", UP)]
        class U(ctypes.Union): _fields_ = [("ki", KI), ("mi", MI)]                    # (HARDWAREINPUT is smaller than both)
        class INPUT(ctypes.Structure): _fields_ = [("type", ctypes.c_uint32), ("u", U)]
        class BIH(ctypes.Structure): _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_uint16),
                                                 ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32),
                                                 ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]
        self.RECT, self.POINT, self.KI, self.MI, self.INPUT, self.BIH = RECT, POINT, KI, MI, INPUT, BIH
        self.ENUM = ctypes.WINFUNCTYPE(ctypes.c_bool, V, V)
        for n, res, args in (("GetForegroundWindow", V, []), ("GetWindowThreadProcessId", ctypes.c_ulong, [V, ctypes.POINTER(ctypes.c_ulong)]),
                             ("IsWindowVisible", ctypes.c_bool, [V]), ("IsIconic", ctypes.c_bool, [V]), ("GetClientRect", ctypes.c_bool, [V, ctypes.POINTER(RECT)]),
                             ("ClientToScreen", ctypes.c_bool, [V, ctypes.POINTER(POINT)]), ("GetWindowTextW", ctypes.c_int, [V, ctypes.c_wchar_p, ctypes.c_int]),
                             ("GetDC", V, [V]), ("ReleaseDC", ctypes.c_int, [V, V]), ("PrintWindow", ctypes.c_bool, [V, V, ctypes.c_uint]),
                             ("SendInput", ctypes.c_uint, [ctypes.c_uint, V, ctypes.c_int]), ("SetCursorPos", ctypes.c_bool, [ctypes.c_int, ctypes.c_int]),
                             ("EnumWindows", ctypes.c_bool, [self.ENUM, V]), ("ShowWindow", ctypes.c_bool, [V, ctypes.c_int]),
                             ("SetForegroundWindow", ctypes.c_bool, [V]), ("BringWindowToTop", ctypes.c_bool, [V]),
                             ("AttachThreadInput", ctypes.c_bool, [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool]),
                             ("AllowSetForegroundWindow", ctypes.c_bool, [ctypes.c_ulong]), ("IsWindow", ctypes.c_bool, [V])):
            f = getattr(u, n); f.restype = res; f.argtypes = args
        self.k = ctypes.WinDLL("kernel32"); self.k.GetCurrentThreadId.restype = ctypes.c_ulong
        for n, res, args in (("CreateCompatibleDC", V, [V]), ("CreateCompatibleBitmap", V, [V, ctypes.c_int, ctypes.c_int]), ("SelectObject", V, [V, V]),
                             ("GetDIBits", ctypes.c_int, [V, V, ctypes.c_uint, ctypes.c_uint, V, V, ctypes.c_uint]), ("DeleteObject", ctypes.c_bool, [V]),
                             ("DeleteDC", ctypes.c_bool, [V])):
            f = getattr(gd, n); f.restype = res; f.argtypes = args

    def _pid(self, h):
        p = ctypes.c_ulong(0); self.u.GetWindowThreadProcessId(h, ctypes.byref(p)); return p.value

    def windows(self, pids):
        out = []

        def cb(h, _):
            pid = self._pid(h)
            if pid in pids and self.u.IsWindowVisible(h):
                r = self.RECT(); self.u.GetClientRect(h, ctypes.byref(r)); p = self.POINT(0, 0); self.u.ClientToScreen(h, ctypes.byref(p))
                buf = ctypes.create_unicode_buffer(256); self.u.GetWindowTextW(h, buf, 256)
                out.append({"id": h, "pid": pid, "title": buf.value, "x": p.x, "y": p.y, "w": r.right, "h": r.bottom, "minimized": bool(self.u.IsIconic(h))})
            return True
        self.u.EnumWindows(self.ENUM(cb), None)
        return out

    def shot(self, win, out: Path) -> dict:
        w, h = win["w"], win["h"]; scr = self.u.GetDC(None); mem = self.g.CreateCompatibleDC(scr); bmp = self.g.CreateCompatibleBitmap(scr, w, h)
        try:
            self.g.SelectObject(mem, bmp)
            if not self.u.PrintWindow(win["id"], mem, 3): raise NativeError("PrintWindow 没能画出游戏窗口")   # PW_CLIENTONLY | PW_RENDERFULLCONTENT
            bi = self.BIH(); bi.biSize = ctypes.sizeof(self.BIH); bi.biWidth = w; bi.biHeight = -h; bi.biPlanes = 1; bi.biBitCount = 32
            buf = ctypes.create_string_buffer(w * h * 4)
            if self.g.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0) != h: raise NativeError("GetDIBits 没读出图像")
        finally:
            self.g.DeleteObject(bmp); self.g.DeleteDC(mem); self.u.ReleaseDC(None, scr)
        rgb = bgra_to_rgb(buf.raw); write_png(out, w, h, rgb)
        return {"warning": "PrintWindow 截出来是全黑的（用显卡画的游戏常这样）：改用 ffmpeg 的 gfxcapture，见 docs/cross-platform.md"} if not any(rgb) else {}

    def can_send(self, win, pids):
        fg = self.u.GetForegroundWindow(); p = self._pid(fg) if fg else 0
        if p in pids: return None
        return ("Windows 上只在游戏已经是最前面的窗口时才发按键：现在最前面的是别的程序（她在项目菜单勾了「测试时允许把游戏切到前面」时，"
                "她离开电脑 1 分钟以上 GameAnything 会把游戏切到前面再按；没勾就不切，免得抢她的键盘）")

    def foreground(self):
        """-> {id, pid, title} of the foreground window, or None."""
        fg = self.u.GetForegroundWindow()
        if not fg: return None
        buf = ctypes.create_unicode_buffer(256); self.u.GetWindowTextW(fg, buf, 256)
        return {"id": fg, "pid": self._pid(fg), "title": buf.value}

    def bring_front(self, win) -> dict:
        """ONLY drive calls this, ONLY for the game GameAnything opened, ONLY with native_front: away while she is away (her decision
        2026-11-01). Windows lets a background process take the foreground only in some cases: the game is restored when minimized
        (SW_RESTORE), then this thread is attached to the foreground window's input queue (AttachThreadInput) so SetForegroundWindow is
        allowed, and detached at once. No ALT key trick: a synthetic ALT opens the menu bar of whatever program is in front.
        -> {ok, prev: the window that was in front (recorded; not put back - closing the game gives the foreground back to it)}."""
        h = win["id"]; prev = self.foreground()
        if self.u.IsIconic(h): self.u.ShowWindow(h, 9)                                       # SW_RESTORE
        me = self.k.GetCurrentThreadId(); them = self.u.GetWindowThreadProcessId(prev["id"], None) if prev else 0
        attached = bool(them and them != me and self.u.AttachThreadInput(me, them, True))
        try:
            self.u.AllowSetForegroundWindow(win["pid"]); self.u.BringWindowToTop(h); self.u.SetForegroundWindow(h)
        finally:
            if attached: self.u.AttachThreadInput(me, them, False)
        fg = self.foreground()
        return {"ok": bool(fg and fg["pid"] == win["pid"]), "prev": prev}

    def _send(self, *inputs):
        arr = (self.INPUT * len(inputs))(*inputs)
        if self.u.SendInput(len(inputs), arr, ctypes.sizeof(self.INPUT)) != len(inputs): raise NativeError("SendInput 被拒绝（游戏是用管理员权限运行的？）")

    def _key(self, vk=0, scan=0, flags=0):
        i = self.INPUT(type=1); i.u.ki = self.KI(wVk=vk, wScan=scan, dwFlags=flags); return i

    def send(self, win, step):
        if step[0] == "key": self._send(self._key(WIN_VK[step[1]]), self._key(WIN_VK[step[1]], flags=2))      # KEYEVENTF_KEYUP
        elif step[0] == "type":
            u = step[1].encode("utf-16-le")
            for k in range(0, len(u), 2):
                sc = int.from_bytes(u[k:k + 2], "little"); self._send(self._key(scan=sc, flags=4), self._key(scan=sc, flags=4 | 2)); time.sleep(0.01)
        elif step[0] == "click":
            self.u.SetCursorPos(win["x"] + step[1], win["y"] + step[2]); d, up = (8, 16) if step[3] == "right" else (2, 4)
            self._send(self._mouse(d), self._mouse(up))

    def _mouse(self, flags):
        i = self.INPUT(type=0); i.u.mi = self.MI(dwFlags=flags); return i


# ---------------------------------------------------------------- Linux X11 (xdotool, ImageMagick import / ffmpeg)
X11_KEYS = {**{c: c for c in "abcdefghijklmnopqrstuvwxyz0123456789"}, "return": "Return", "escape": "Escape", "space": "space", "tab": "Tab",
            "backspace": "BackSpace", "left": "Left", "right": "Right", "up": "Up", "down": "Down", **{f"f{i}": f"F{i}" for i in range(1, 13)}}


class X11Backend:
    name = "Linux X11"

    def __init__(self, run=None, which=None, env=None):
        self.run = run or _run; self.which = which or shutil.which; self.env = os.environ if env is None else env

    def _ok(self, args, what):
        r = self.run(args, timeout=30)
        if r is None or r.returncode != 0: raise NativeError(f"{what} 失败：{(r.stderr if r is not None else '').strip()[:200] or args[0] + ' 不能运行'}")
        return r

    def windows(self, pids, titles=()):
        """The visible windows of these processes; plus, for `titles` (the game's exact window titles), windows with that title that carry
        no _NET_WM_PID (LWJGL 2 sets none) or one of these pids, counted as pids[0]'s."""
        if not self.which("xdotool"): raise NativeError("要装 xdotool（sudo apt install xdotool）才能找到游戏窗口")
        out = []; seen = set()

        def add(wid, pid):
            gm = self.run(["xdotool", "getwindowgeometry", "--shell", wid])
            if gm is None or gm.returncode != 0: return
            v = dict(re.findall(r"(?m)^(\w+)=(-?\d+)$", gm.stdout))
            if not {"X", "Y", "WIDTH", "HEIGHT"} <= set(v): return
            nm = self.run(["xdotool", "getwindowname", wid]); seen.add(wid)
            out.append({"id": int(wid), "pid": pid, "title": nm.stdout.strip() if nm is not None else "", "x": int(v["X"]), "y": int(v["Y"]),
                        "w": int(v["WIDTH"]), "h": int(v["HEIGHT"])})
        for pid in pids:
            r = self.run(["xdotool", "search", "--onlyvisible", "--pid", str(pid)])
            for wid in (r.stdout.split() if r is not None and r.returncode == 0 else []): add(wid, pid)
        for t in (titles if pids else ()):
            rx = "^" + re.sub(r"([.^$*+?()\[\]{}|\\])", r"\\\1", t) + "$"
            r = self.run(["xdotool", "search", "--onlyvisible", "--name", rx])
            for wid in (r.stdout.split() if r is not None and r.returncode == 0 else []):
                if wid in seen: continue
                o = self.run(["xdotool", "getwindowpid", wid])                  # fails when the window has no _NET_WM_PID
                owner = o.stdout.strip() if o is not None and o.returncode == 0 else ""
                if owner and not (owner.isdigit() and int(owner) in set(int(p) for p in pids)): continue      # another program's window
                add(wid, int(owner) if owner else pids[0])
        return out

    def shot(self, win, out: Path) -> dict:
        out.parent.mkdir(parents=True, exist_ok=True)
        if self.which("import"): self._ok(["import", "-silent", "-window", str(win["id"]), str(out)], "import -window"); return {}
        if self.which("ffmpeg"):
            self._ok(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-video_size", f"{win['w']}x{win['h']}",
                      "-i", f"{self.env.get('DISPLAY') or ':0'}+{win['x']},{win['y']}", "-frames:v", "1", str(out)], "ffmpeg x11grab")
            return {"warning": "ffmpeg x11grab 截的是游戏窗口所在的那块屏幕：上面盖着别的窗口时会一起截进来（装 ImageMagick 的 import 更准）"}
        raise NativeError("要装 ImageMagick（import）或 ffmpeg 才能截游戏窗口")

    def can_send(self, win, pids): return None

    def send(self, win, step):
        w = str(win["id"])
        if step[0] == "key": self._ok(["xdotool", "key", "--window", w, X11_KEYS[step[1]]], "xdotool key")
        elif step[0] == "type": self._ok(["xdotool", "type", "--window", w, "--", step[1]], "xdotool type")
        elif step[0] == "click":
            self._ok(["xdotool", "mousemove", "--window", w, str(step[1]), str(step[2]), "click", "--window", w, "3" if step[3] == "right" else "1"], "xdotool click")


def backend(sys_=None, env=None):
    """-> the backend for this computer, or raises Refused when this computer cannot look at / press keys in one window."""
    sys_ = sys_ or osdirs.system()
    try:
        if sys_ == "mac": return MacBackend()
        if sys_ == "windows": return WinBackend()
    except (OSError, AttributeError) as e:
        raise Refused("unsupported", f"这台电脑不能只对游戏窗口截图 / 发按键：{e}")
    s = idlemod.session(env)
    if s == "x11": return X11Backend(env=env)
    if s == "wayland": raise Refused("wayland", "Wayland 不让别的程序给某一个窗口发按键、截某一个窗口：shot / drive 用不了（登录时选 X11 会话，例如「Ubuntu on Xorg」）")
    raise Refused("no_display", "没有图形界面（没有 DISPLAY）：没有游戏窗口可看")


# ---------------------------------------------------------------- shot / drive
# ---------------------------------------------------------------- macOS: what is in front of the game window
def _hit(w, x, y, ww=1, hh=1) -> bool:
    return w["x"] < x + ww and x < w["x"] + w["w"] and w["y"] < y + hh and y < w["y"] + w["h"]


def covering(above, pids, rect) -> list:
    """The windows of OTHER programs in `above` (the windows in front of the game window, front to back) that overlap rect
    (x, y, w, h in screen points): normal and floating windows (layer 0..19) that are not fully transparent; the Dock, the menu bar and
    status items (layer 20+) do not count."""
    x, y, ww, hh = rect; ps = set(int(p) for p in pids)
    return [w for w in above if int(w["pid"]) not in ps and 0 <= w.get("layer", 0) < 20 and (w.get("alpha") is None or w["alpha"] > 0.05)
            and w["w"] > 0 and w["h"] > 0 and _hit(w, x, y, ww, hh)]


def in_front(above, pids) -> bool:
    """Is the game the front app? No normal window (layer 0) of another program is in front of the game window anywhere on screen."""
    ps = set(int(p) for p in pids)
    return not [w for w in above if int(w["pid"]) not in ps and w.get("layer", 0) == 0 and (w.get("alpha") is None or w["alpha"] > 0.05) and w["w"] > 0]


def _names(ws) -> str:
    return "、".join(sorted({w.get("owner") or w.get("title") or f"pid {w['pid']}" for w in ws}))


def _click_points(win, clicks):
    return [(win["x"] + c[1], win["y"] + c[2], 1, 1) for c in clicks]


def _blocked(be, win, pids, clicks, need_front):
    """-> (code, why) when the clicks must not be sent now, else None."""
    above = be.above(win)
    cov = [w for r in _click_points(win, clicks) for w in covering(above, pids, r)]
    if cov:
        return "covered", (f"游戏窗口被「{_names(cov)}」盖住了：点击会落到那个程序上（还会让游戏失焦），所以不点。把游戏窗口拉到最前面或把那个窗口挪开再来；"
                           "她选了「我在用电脑时也可以」时 GameAnything 会先把游戏拉到前面")
    if need_front and not in_front(above, pids):
        return "not_frontmost", ("这个游戏的按钮只认真实光标的点击（CGEventPost），这种点击只在游戏是最前面的窗口时才发：现在前面是"
                                 f"「{_names([w for w in above if int(w['pid']) not in set(pids) and w.get('layer', 0) == 0]) or '别的程序'}」")
    return None


def _window(be, pids, titles=(), any_space=False):
    w = pick(be.windows(pids, titles) if titles and isinstance(be, X11Backend) else be.windows(pids), pids)
    if w is None and any_space and hasattr(be, "_list"):
        # macOS: a game that went full screen sits in its own Space, not on the current desktop (Cities: Skylines' first start on her
        # Mac, 2026-10-31): `screencapture -l <id>` still takes its picture. Only for shot: a click needs the window on screen.
        w = pick([x for x in be._list(0, 0, pids) if x["w"] >= 400 and x["h"] >= 300], pids)
    if w is None: raise Refused("no_window", "找不到游戏的窗口（还在启动、被最小化了，或者不在当前桌面）", pending=True)
    return w


def shot(root, g, out=None, be=None, now=None) -> dict:
    """A picture of the game window GameAnything opened. Never brings it to the front, never needs her to be away (it does not touch her input)."""
    x, pids = target(root, g, now)
    be = be or backend(); win = _window(be, pids, g.window_titles, any_space=True)
    out = Path(out) if out else Path(root) / SHOT_DIR / f"{g.id}-{datetime.now():%Y%m%d-%H%M%S}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    r = dict(be.shot(win, out) or {})
    if hasattr(be, "above"):                                           # macOS: say when other windows cover the game (the picture is the
        cov = covering(be.above(win), pids, (win["x"], win["y"], win["w"], win["h"]))   # game's own window, but a game that lost focus may
        if cov:                                                        # pause or stop drawing)
            r["covered_by"] = sorted({w.get("owner") or w.get("title") or str(w["pid"]) for w in cov})
            r["warning"] = (f"游戏窗口被「{_names(cov)}」盖住了：截图是游戏窗口自己的画面（不会把那个窗口截进来），但游戏不在最前面时可能暂停、不刷新，"
                            "图上可能是旧画面；drive 的点击这时会被拒绝")
    px = png_size(out)
    if px and win["w"] and abs(px[0] / win["w"] - 1) > 0.05:          # Retina / display scaling: drive's click coordinates are window units
        r["scale"] = round(px[0] / win["w"], 3)
        r["note"] = f"图片是 {px[0]}x{px[1]} 像素，窗口是 {win['w']}x{win['h']}：drive 的 click 坐标 = 图片上的坐标 ÷ {r['scale']:g}"
    return {"path": str(out), "window": {k: win[k] for k in ("id", "pid", "title", "x", "y", "w", "h") if k in win}, "backend": be.name, **r}


def png_size(f: Path):
    try: b = Path(f).read_bytes()[:24]
    except OSError: return None
    return struct.unpack(">II", b[16:24]) if len(b) == 24 and b[:8] == b"\x89PNG\r\n\x1a\n" and b[12:16] == b"IHDR" else None


def _set(root, lid, **kw):
    quiet._update(root, lambda L: [y.update(**kw) for y in L["launches"] if y["id"] == lid])


def attention(x, pol, idle_s, now_ts) -> dict:
    """Is she at the computer? -> {away: bool, her_idle, why}. When GameAnything drove last (drove_until) and the newest input event is no later
    than that, the event was GameAnything's own (Windows counts SendInput as input): her idle time then runs from before GameAnything started."""
    if pol.get("drive") == "always": return {"away": True, "her_idle": idle_s, "why": "她选了「我在用电脑时也可以」"}
    if idle_s is None:
        return {"away": False, "her_idle": None, "unknown": True,
                "why": "这台电脑看不出她在不在用（gameanything native idle 是 unknown）：不操作游戏；要操作就请她在「什么时候开游戏」里勾「我在用电脑时也可以」"}
    last = now_ts - idle_s; ours = x.get("drove_until"); since = x.get("her_last_input")
    her = (now_ts - since) if ours and since is not None and last <= ours + OWN_INPUT_SLACK else idle_s
    if her < DRIVE_IDLE_SECS:
        return {"away": False, "her_idle": her, "why": f"她 {int(her)} 秒前还在用鼠标键盘：先不操作游戏（她离开 {DRIVE_IDLE_SECS} 秒以上再来）"}
    return {"away": True, "her_idle": her, "why": f"她已经 {int(her)} 秒没动电脑了"}


def drive(root, g, steps, be=None, idle=None, clock=time.time, sleep=time.sleep, now=None, click=None, launcher=None) -> dict:
    """Send the steps to the game window GameAnything opened. -> {done: n, ...}; raises Refused (pending=True: she is at the computer, try later).
    click: macOS click method "pid" | "hid" (default: the game's mac_click).
    launcher: pids of the game's own launcher, which GameAnything opened with this launch and whose process is not the game's
    (Minecraft's Launcher, Game.after_launch): the steps go to its window instead (the launch must be open).
    Real (HID) clicks and keys: with native_drive: always at any time (her rule 2026-10-29); otherwise only while she is away."""
    parsed = parse_steps(steps)
    if click not in (None, "auto", "pid", "hid"): raise ValueError(f"click 方式应该是 pid 或 hid：{click!r}")
    if quiet.policy(root).get("hands") == "self":                     # 「不给，我自己点」 on the readiness card (ready.py, 2026-11-01)
        raise Refused("self", "她选了「不给，我自己点」（native_hands: self）：agent 不操作游戏。把要点的地方写进进度卡，等她点完说「好了」；"
                              "她可以在项目菜单「什么时候开游戏」的「谁来点游戏」里改回来")
    if launcher:
        x = quiet._open_launch(root, g)
        if x is None: raise Refused("none", "没有 GameAnything 开着的游戏：先 gameanything native launch --project P")
        pids = [int(p) for p in launcher]
    else: x, pids = target(root, g, now)
    pol = quiet.policy(root); idle = idle or idlemod.seconds
    t0 = clock(); s0 = idle(); a = attention(x, pol, s0, t0)
    if not a["away"]:
        if not a.get("unknown"): _set(root, x["id"], paused=quiet._iso(datetime.now()))
        raise Refused("unknown" if a.get("unknown") else "active", a["why"], pending=not a.get("unknown"))
    her_last = t0 - a["her_idle"] if a["her_idle"] is not None else None
    be = be or backend(); fronted = None; ours = None
    # Windows, native_front: away (her decision 2026-11-01): the game may come to the front ONLY while she really is away - her own idle
    # time, also with native_drive: always (that one means "while I use it too", which must never take her foreground); unknown = no
    front_ok = getattr(be, "needs_front", False) and pol.get("front") == "away"
    away = attention(x, {}, s0, t0) if front_ok else None
    try: win = _window(be, pids, g.window_titles)
    except Refused as e:
        mins = [w for w in be.windows(pids) if w.get("minimized")] if front_ok and e.code == "no_window" else []
        if not (mins and away["away"]): raise
        win = max(mins, key=lambda w: w["w"] * w["h"]); fronted = _front(root, x, be, win, clock, sleep)       # restored + brought to the front
        win = _window(be, pids, g.window_titles); ours = clock()
    why = be.can_send(win, pids)
    if why and front_ok and fronted is None:
        if not away["away"]: why += f"（她允许离开时把游戏切到前面，但{away['why']}）"
        else:
            fronted = _front(root, x, be, win, clock, sleep); win = _window(be, pids, g.window_titles); ours = clock()
            why = be.can_send(win, pids)
            if why: why = "试着把游戏切到前面了，Windows 没让切过去：" + why
    if why: raise Refused("not_foreground", why, pending=True)
    clicks = [st for st in parsed if st[0] == "click"]; method = None
    if clicks and hasattr(be, "above"):                                # macOS: a click lands on whatever window is at that point
        method = click if click in ("pid", "hid") else getattr(g, "mac_click", "pid")
        if method == "hid" and pol.get("drive") != "always":          # it moves HER cursor: only while she is away, unless she chose always
            h = attention(x, {}, s0, t0)
            if not h["away"]:
                raise Refused("unknown" if h.get("unknown") else "active", f"{g.title} 的点击要移动真实光标（CGEventPost）：只在她离开电脑时才点"
                              f"（她选「我在用电脑时也可以」就随时可以点）。{h['why']}", pending=not h.get("unknown"))
        b = _blocked(be, win, pids, clicks, method == "hid")
        if not b and method == "hid" and hasattr(be, "bring_front") and getattr(be, "frontmost_pid", lambda: None)() not in (None, int(win["pid"])):
            # a real click on a window of an app that is not active only activates that app: macOS keeps the click (tModLoader's language
            # button on her Mac, 2026-10-29). hid clicks happen only while she is away, so the game may come to the front first.
            be.bring_front(win); sleep(1.0); win = _window(be, pids, g.window_titles)
        if b and pol.get("drive") == "always" and hasattr(be, "bring_front"):
            # 1 s, not 0.5: a Unity game that just came to the front drops the first key (KSP on her Mac, 2026-10-29: 4 of 5 F8 presses
            # arrived after 0.5 s, 5 of 5 twice after 0.8 s)
            be.bring_front(win); sleep(1.0); win = _window(be, pids, g.window_titles); b = _blocked(be, win, pids, clicks, method == "hid")
        if b and b[0] == "covered" and pol.get("drive") == "always" and hasattr(be, "move_clear"):
            # still covered in front: a floating window (layer > 0) of another app stays above it (the Claude app's panel over Civ VI's
            # launcher PLAY, her Mac 2026-10-29): move the game window to the top-left and look again
            be.move_clear(win); sleep(0.5); win = _window(be, pids, g.window_titles); b = _blocked(be, win, pids, clicks, method == "hid")
        if b: raise Refused(b[0], b[1], pending=True)
        be.click_method = method
    keys = [st for st in parsed if st[0] == "key"]
    if keys and hasattr(be, "above") and getattr(g, "mac_keys", "pid") == "hid":
        # mac_keys: hid games read only real (HID) key presses (see MacBackend.send): the same rules as a real click - she is away, game in front
        h = attention(x, {}, s0, t0)
        if not h["away"] and pol.get("drive") != "always":
            raise Refused("unknown" if h.get("unknown") else "active", f"{g.title} 的按键要走真实键盘事件（CGEventPost）：只在她离开电脑时才按"
                          f"（她选「我在用电脑时也可以」就随时可以按）。{h['why']}", pending=not h.get("unknown"))
        if hasattr(be, "bring_front") and getattr(be, "frontmost_pid", lambda: None)() not in (None, int(win["pid"])):
            be.bring_front(win); sleep(1.0); win = _window(be, pids, g.window_titles)
        # keyboard focus: tModLoader took real key presses only after a real click INSIDE the game picture in the same session (bringing the
        # app to the front or clicking its title bar did not; her Mac 2026-10-29). Steps for these games start with such a click.
        be.key_method = "hid"
    done = 0; paused = None                                            # (ours: set when the game was brought to the front - that is GameAnything's input)
    try:
        for st in parsed:
            if st[0] == "sleep": sleep(st[1] / 1000); continue
            if pol.get("drive") != "always":                          # she came back (also during a sleep step): stop at once
                s = idle(); t = clock(); known = max(v for v in (her_last, x.get("drove_until"), ours) if v is not None)
                if s is None or t - s > known + OWN_INPUT_SLACK:
                    paused = quiet._iso(datetime.now())
                    raise Refused("active", f"她回到电脑前了：做了 {done} 步就停下，不再操作游戏（游戏开着不动，她的程序也不碰）", pending=True)
                if done:
                    why = be.can_send(win, pids)
                    if why: raise Refused("not_foreground", why, pending=True)
            if st[0] == "click" and method and done:                   # a window may have come up in front since the check
                b = _blocked(be, win, pids, [st], method == "hid")
                if b: raise Refused(b[0], f"做了 {done} 步后停下：" + b[1], pending=True)
            be.send(win, st); done += 1; ours = clock()
    finally:
        if ours is not None or paused: _set(root, x["id"], **({"drove_until": ours, "her_last_input": her_last} if ours is not None else {}), paused=paused)
    return {"done": done, "window": {k: win[k] for k in ("id", "pid", "title", "w", "h") if k in win}, "backend": be.name, "why": a["why"],
            **({"click_method": method} if method else {}), **({"fronted": fronted} if fronted else {})}


def _front(root, x, be, win, clock, sleep) -> dict:
    """Bring the game window to the front (Windows, native_front: away, she is away) and record it in the launch's `fronted` list."""
    r = be.bring_front(win); sleep(1.0)                                # (a game that just came to the front drops the first key: see macOS above)
    rec = {"at": quiet._iso(datetime.now()), "window": win.get("title") or str(win["id"]), "ok": bool(r.get("ok")),
           "prev": ((r.get("prev") or {}).get("title") or str((r.get("prev") or {}).get("id") or "")) or None}
    quiet._update(root, lambda L: [y.setdefault("fronted", []).append(rec) for y in L["launches"] if y["id"] == x["id"]])
    return rec


# ---------------------------------------------------------------- permissions
MAC_PANES = {"accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
             "screen": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"}


def permissions(sys_=None, env=None, mac=None, app=None, which=None) -> dict:
    """-> {system, items: [{name, ok: True | False | None, why, how, needs, en: {name, why, how}}], ok}. Only looks; nothing is changed and
    no prompt appears. name / why / how are Chinese, en the same in English (text(item, key, lang) picks one)."""
    sys_ = sys_ or osdirs.system(); which = which or shutil.which; items = []

    def add(ok, needs, zh, en): items.append({"name": zh[0], "ok": ok, "why": zh[1], "how": zh[2], "needs": needs, "en": dict(zip(("name", "why", "how"), en))})

    if sys_ == "mac":
        ax, scr = (mac or mac_permissions)(); who = app if app is not None else mac_app(); py = os.path.realpath(sys.executable)
        who_txt = f"「{who}」" if who else ("运行 GameAnything 的那个程序（终端 / iTerm / VS Code / agent 的 app）；没有终端、在后台跑时（agentd、"
                                             f"不是从终端开的 gameanything ui）就是这个 python：{py}")
        who_en = f"\"{who}\"" if who else ("the app that runs GameAnything (Terminal / iTerm / VS Code / the agent's app); without a terminal, in the "
                                            f"background (agentd, gameanything ui not started from a terminal) it is this python: {py}")
        add(ax, "act", ("辅助功能 Accessibility（gameanything native drive 发按键、点击）", "macOS 只让有「辅助功能」权限的程序给别的程序发按键",
                        f"系统设置 > 隐私与安全性 > 辅助功能（System Settings > Privacy & Security > Accessibility）：打开 {who_txt} 的开关；没有就点 + 加进去，然后把它退出重开"),
            ("Accessibility (gameanything native drive: keys and clicks)", "macOS lets only apps with the Accessibility permission send keys to other apps",
             f"System Settings > Privacy & Security > Accessibility: turn on {who_en}; if it is not listed, add it with +, then quit and reopen it"))
        add(scr, "look", ("屏幕录制 Screen Recording（gameanything native shot 截游戏窗口）", "macOS 只让有「屏幕录制」权限的程序截别的程序的窗口",
                          f"系统设置 > 隐私与安全性 > 录屏与系统录音（macOS 15 起；14 及以前叫「屏幕录制」；System Settings > Privacy & Security > Screen & System Audio Recording）：打开 {who_txt} 的开关，然后把它退出重开"),
            ("Screen Recording (gameanything native shot: pictures of the game window)", "macOS lets only apps with the Screen Recording permission capture other apps' windows",
             f"System Settings > Privacy & Security > Screen & System Audio Recording (macOS 15 and later; \"Screen Recording\" up to 14): turn on {who_en}, then quit and reopen it"))
        add(None, "", ("说明", "权限是给「程序」的，不是给 GameAnything 的：换一个终端或 app 跑 GameAnything 要再给一次。GameAnything 只看不改，也不会弹窗要权限。",
                       "gameanything native permissions --open 会打开这两个设置页"),
            ("Note", "The permissions belong to the app, not to GameAnything: run GameAnything from another terminal or app and it needs them again. "
                     "GameAnything only looks; it changes nothing and never asks for a permission itself.", "gameanything native permissions --open opens both settings panes"))
    elif sys_ == "windows":
        add(True, "act", ("发按键（gameanything native drive）", "不需要权限；只在游戏已经是最前面的窗口时才发",
                          "游戏如果是「以管理员身份运行」的，普通程序发的按键会被 Windows 挡住（UIPI）：不要用管理员身份开游戏"),
            ("Keys (gameanything native drive)", "No permission needed; keys are sent only while the game is the front window",
             "Windows blocks keys from normal programs to a game started \"as administrator\" (UIPI): do not start the game as administrator"))
        add(True, "look", ("截游戏窗口（gameanything native shot）", "PrintWindow 不需要权限；用显卡画的游戏可能截出全黑",
                           "全黑时用 ffmpeg 8 的 gfxcapture（见 docs/cross-platform.md「只看、只按游戏」）"),
            ("Pictures of the game window (gameanything native shot)", "PrintWindow needs no permission; a game drawn by the graphics card may come out black",
             "When it is black, use ffmpeg 8's gfxcapture (docs/cross-platform.md)"))
    else:
        s = idlemod.session(env)
        if s == "wayland":
            add(False, "both", ("Wayland", "Wayland 不让别的程序截某一个窗口或给它发按键", "登录时选 X11 会话（例如「Ubuntu on Xorg」）"),
                ("Wayland", "Wayland does not let other programs capture one window or send it keys", "Choose an X11 session when you log in (e.g. \"Ubuntu on Xorg\")"))
        elif s == "x11":
            add(bool(which("xdotool")), "both", ("xdotool（找窗口、发按键）", "按键用 XSendEvent 发给游戏窗口，不切换焦点；有的游戏不认这种按键", "sudo apt install xdotool"),
                ("xdotool (finds the window, sends keys)", "Keys go to the game window by XSendEvent without changing focus; some games ignore such keys", "sudo apt install xdotool"))
            add(bool(which("import") or which("ffmpeg")), "look", ("import / ffmpeg（截游戏窗口）", "ImageMagick 的 import -window 只截这个窗口", "sudo apt install imagemagick（或 ffmpeg）"),
                ("import / ffmpeg (pictures of the game window)", "ImageMagick's import -window captures just that window", "sudo apt install imagemagick (or ffmpeg)"))
        else: add(False, "both", ("图形界面", "没有 DISPLAY / WAYLAND_DISPLAY：这里没有游戏窗口", "在她登录的桌面里运行"),
                  ("Desktop", "No DISPLAY / WAYLAND_DISPLAY: there is no game window here", "Run it in the desktop session you are logged in to"))
    p = idlemod.probe(sys_, env); known = p["seconds"] is not None
    xpi = sys_ == "linux" and idlemod.session(env) == "x11"
    add(known, "idle",                                                 # (drive refuses without it unless native_drive: always: ready.py decides)
        ("看她在不在用电脑（gameanything native idle）", p["source"],
         "" if known else "装 xprintidle（sudo apt install xprintidle）" if xpi else "看不出时：「我没在用电脑时」会改成先发卡问她，drive 不操作游戏"),
        ("Whether you are using the computer (gameanything native idle)", p["source"],
         "" if known else "Install xprintidle (sudo apt install xprintidle)" if xpi else
         "Without it, \"while I'm away\" asks you on a card first, and drive does not touch the game"))
    return {"system": sys_, "items": items, "ok": all(i["ok"] is not False for i in items)}


def text(item: dict, key: str, lang: str = "zh") -> str:
    """An item's name / why / how in lang (en falls back to the Chinese when an item has no English)."""
    return ((item.get("en") or {}).get(key) or item.get(key) or "") if lang == "en" else (item.get(key) or "")


def open_panes(run=None):
    run = run or _run
    for u in MAC_PANES.values(): run(["open", u])
