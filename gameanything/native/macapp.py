"""macOS apps by process id, through AppKit's NSRunningApplication (ctypes + the Objective-C runtime; no PyObjC needed):

    terminate(pid)     ask the app to quit the way Cmd-Q does (a quit Apple event): the game saves its settings and exits normally, and
                       macOS shows no 「… quit unexpectedly」 report (which SIGTERM caused for Stardew Valley on a tester's Mac, 2026-10-25)
    activate(pid)      bring that app to the front (only when she allowed driving while she uses the computer: hands.py)
    quit_bundle(id)    `osascript -e 'tell application id "<id>" to quit'`: the AppleScript way, when the app is not found by pid

None of these needs a permission prompt except quit_bundle (macOS may ask once whether the terminal may control the game).
Every call returns False (never raises) when it cannot be done here.
"""
import ctypes
import re

from .games import _run

_APPKIT = "/System/Library/Frameworks/AppKit.framework/AppKit"
_OBJC = "/usr/lib/libobjc.A.dylib"


class _ObjC:
    def __init__(self):
        self.lib = ctypes.CDLL(_OBJC); ctypes.CDLL(_APPKIT)
        self.lib.objc_getClass.restype = ctypes.c_void_p; self.lib.objc_getClass.argtypes = [ctypes.c_char_p]
        self.lib.sel_registerName.restype = ctypes.c_void_p; self.lib.sel_registerName.argtypes = [ctypes.c_char_p]
        self.send = ctypes.cast(self.lib.objc_msgSend, ctypes.c_void_p).value

    def call(self, obj, sel: str, restype, *args):
        """objc_msgSend with exact argument types (arm64 needs them: it is not a C variadic call there). args: (ctype, value) pairs."""
        f = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *[t for t, _ in args])(self.send)
        return f(obj, self.lib.sel_registerName(sel.encode()), *[v for _, v in args])

    def app(self, pid):
        cls = self.lib.objc_getClass(b"NSRunningApplication")
        return self.call(cls, "runningApplicationWithProcessIdentifier:", ctypes.c_void_p, (ctypes.c_int, int(pid))) if cls else None


_objc = None


def _rt():
    global _objc
    if _objc is None: _objc = _ObjC()
    return _objc


def terminate(pid) -> bool:
    try:
        o = _rt(); a = o.app(pid)
        return bool(a) and bool(o.call(a, "terminate", ctypes.c_bool))
    except (OSError, AttributeError, ValueError, TypeError): return False


def frontmost_pid(run=None):
    """The pid of the frontmost app (System Events), or None."""
    r = (run or _run)(["osascript", "-e", 'tell application "System Events" to get unix id of first process whose frontmost is true'])
    s = r.stdout.strip() if r is not None and r.returncode == 0 else ""
    return int(s) if s.isdigit() else None


def activate(pid, run=None) -> bool:
    """Bring the app to the front. NSRunningApplication's activate answers YES from a background process but does not take the focus on
    macOS 14 (her Mac, 2026-10-29: tModLoader's dotnet window stayed behind Claude); System Events' `frontmost` does, so it is the fallback.
    True only when that pid really is in front afterwards."""
    try:
        o = _rt(); a = o.app(pid)
        if a: o.call(a, "activateWithOptions:", ctypes.c_bool, (ctypes.c_ulong, 2))         # NSApplicationActivateIgnoringOtherApps
    except (OSError, AttributeError, ValueError, TypeError): pass
    if frontmost_pid(run) == int(pid): return True
    (run or _run)(["osascript", "-e", f'tell application "System Events" to set frontmost of (first process whose unix id is {int(pid)}) to true'])
    return frontmost_pid(run) == int(pid)



def move_window(pid, x, y, run=None) -> bool:
    """Move the app's front window so its top-left corner is at (x, y) (screen points; System Events, needs Accessibility). A floating
    window of another app (layer > 0: the Claude app's panel on her Mac, 2026-10-29) stays in front of any normal window, even of the
    front app: moving the game window away from it is the only way a click reaches the game."""
    r = (run or _run)(["osascript", "-e", f'tell application "System Events" to set position of first window of (first process whose unix id is {int(pid)}) to {{{int(x)}, {int(y)}}}'])
    return r is not None and r.returncode == 0

def quit_bundle(bundle_id: str, run=None) -> bool:
    if not bundle_id or not re.fullmatch(r"[\w.-]+", bundle_id): return False
    r = (run or _run)(["osascript", "-e", f'tell application id "{bundle_id}" to quit'], timeout=20)
    return r is not None and r.returncode == 0


def copy(text: str, run=None) -> bool:
    """Put text on the clipboard (pbcopy). Steam's Launch Options box: paste it; typing can turn the quotes into curly quotes."""
    import subprocess
    try: return subprocess.run(["pbcopy"], input=text.encode("utf-8"), timeout=10).returncode == 0 if run is None else run(text)
    except (OSError, subprocess.SubprocessError): return False
