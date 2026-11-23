"""How long since she last touched the mouse or keyboard on this computer (本机模式少打扰, 2026-10-24). Used by
`native_launch: idle` (open the game only after she has been away N minutes) and by `gameanything native drive` (never send input while she is at
the computer). The idea of checking idle time before driving a game comes from Universal Modder (MIT License, Copyright (c) 2026 Rehan and
universal-modder contributors, https://github.com/rehan-remade/universal-modder: `um win drive idle`); no code was copied.

    seconds(sys_=None, env=None) -> float | None      None = this computer cannot tell (Wayland without GNOME, no display, no tool)
    probe(sys_=None, env=None)   -> {"seconds": float | None, "source": str}

Per system:
    macOS     `ioreg -c IOHIDSystem` HIDIdleTime (nanoseconds); no permission needed
    Windows   GetLastInputInfo (ctypes, user32) against GetTickCount
    Linux     X11: `xprintidle` (milliseconds), else the XScreenSaver extension through ctypes (libXss);
              Wayland: GNOME's org.gnome.Mutter.IdleMonitor over `gdbus` when it answers, else unknown (other compositors do not tell
              ordinary programs; an X11 query under XWayland would only see X11 windows, so it is not used)
"""
import ctypes
import ctypes.util
import os
import re
import shutil

from .. import osdirs
from .games import _run


# ---------------------------------------------------------------- parsers (kept apart so tests can feed them fake output)
def parse_ioreg(text: str):
    """`ioreg -c IOHIDSystem` lists "HIDIdleTime" = <nanoseconds> (once per HID system object): the smallest one, in seconds."""
    v = [int(x) for x in re.findall(r'"HIDIdleTime"\s*=\s*(\d+)', text or "")]
    return min(v) / 1e9 if v else None


def parse_xprintidle(text: str):
    """xprintidle prints the idle time in milliseconds."""
    s = (text or "").strip()
    return int(s) / 1000 if s.isdigit() else None


def parse_mutter(text: str):
    """gdbus call ... org.gnome.Mutter.IdleMonitor.GetIdletime -> "(uint64 12345,)" (milliseconds)."""
    m = re.search(r"uint64\s+(\d+)", text or "")
    return int(m.group(1)) / 1000 if m else None


def win_idle(user32=None, kernel32=None):
    """Windows: milliseconds since the last input event (GetLastInputInfo) -> seconds. The tick counters are 32 bit and wrap after 49.7
    days, so the difference is taken modulo 2**32."""
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    if user32 is None:
        user32 = ctypes.WinDLL("user32"); kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetTickCount.restype = ctypes.c_uint32
    li = LASTINPUTINFO(); li.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(li)): return None
    return ((int(kernel32.GetTickCount()) - li.dwTime) & 0xFFFFFFFF) / 1000


def x11_idle(lib_x11=None, lib_xss=None):
    """X11 without xprintidle: XScreenSaverQueryInfo(display, root, info).idle (milliseconds). None when the libraries or the display are
    missing."""
    class Info(ctypes.Structure):
        _fields_ = [("window", ctypes.c_ulong), ("state", ctypes.c_int), ("kind", ctypes.c_int), ("til_or_since", ctypes.c_ulong),
                    ("idle", ctypes.c_ulong), ("eventMask", ctypes.c_ulong)]
    try:
        if lib_x11 is None:
            nx, ns = ctypes.util.find_library("X11"), ctypes.util.find_library("Xss")
            if not nx or not ns: return None
            lib_x11, lib_xss = ctypes.CDLL(nx), ctypes.CDLL(ns)
            lib_x11.XOpenDisplay.restype = ctypes.c_void_p; lib_x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            lib_x11.XDefaultRootWindow.restype = ctypes.c_ulong; lib_x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            lib_x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
            lib_xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(Info)
            lib_xss.XScreenSaverQueryInfo.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Info)]
            lib_x11.XFree.argtypes = [ctypes.c_void_p]
        dpy = lib_x11.XOpenDisplay(None)
        if not dpy: return None
        try:
            info = lib_xss.XScreenSaverAllocInfo()
            if not info: return None
            try:
                if not lib_xss.XScreenSaverQueryInfo(dpy, lib_x11.XDefaultRootWindow(dpy), info): return None
                return info.contents.idle / 1000
            finally: lib_x11.XFree(info)
        finally: lib_x11.XCloseDisplay(dpy)
    except (OSError, AttributeError, ValueError, ctypes.ArgumentError):
        return None


def session(env=None) -> str:
    """Linux: "wayland", "x11" or "" (no graphical session this process can see)."""
    env = os.environ if env is None else env
    if env.get("WAYLAND_DISPLAY") or env.get("XDG_SESSION_TYPE") == "wayland": return "wayland"
    return "x11" if env.get("DISPLAY") else ""


# ---------------------------------------------------------------- per system
def probe(sys_=None, env=None, run=None) -> dict:
    sys_ = sys_ or osdirs.system(); run = run or _run
    if sys_ == "mac":
        r = run(["ioreg", "-c", "IOHIDSystem"])
        s = parse_ioreg(r.stdout) if r is not None and r.returncode == 0 else None
        return {"seconds": s, "source": "ioreg HIDIdleTime" if s is not None else "ioreg gave no HIDIdleTime"}
    if sys_ == "windows":
        try: s = win_idle()
        except (OSError, AttributeError): s = None
        return {"seconds": s, "source": "GetLastInputInfo" if s is not None else "GetLastInputInfo failed"}
    kind = session(env)
    if kind == "wayland":
        if shutil.which("gdbus"):
            r = run(["gdbus", "call", "--session", "--dest", "org.gnome.Mutter.IdleMonitor", "--object-path", "/org/gnome/Mutter/IdleMonitor/Core",
                     "--method", "org.gnome.Mutter.IdleMonitor.GetIdletime"], timeout=5)
            s = parse_mutter(r.stdout) if r is not None and r.returncode == 0 else None
            if s is not None: return {"seconds": s, "source": "GNOME Mutter IdleMonitor (Wayland)"}
        return {"seconds": None, "source": "Wayland: the compositor does not tell other programs how long you have been idle"}
    if kind == "x11":
        if shutil.which("xprintidle"):
            r = run(["xprintidle"], timeout=5)
            s = parse_xprintidle(r.stdout) if r is not None and r.returncode == 0 else None
            if s is not None: return {"seconds": s, "source": "xprintidle"}
        s = x11_idle()
        return {"seconds": s, "source": "XScreenSaver extension" if s is not None else "X11: no xprintidle and no libXss"}
    return {"seconds": None, "source": "no graphical session (no DISPLAY / WAYLAND_DISPLAY)"}


def seconds(sys_=None, env=None):
    return probe(sys_, env)["seconds"]
