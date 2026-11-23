"""Plain-file log next to the Mods folder (sims4.log output is dropped in release builds)."""
import os, time, threading
_lock = threading.Lock()
PATH = None


def _path():
    global PATH
    if PATH is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../Mods/<x>.ts4script -> .../Mods
        if base.lower().endswith(".ts4script"):
            base = os.path.dirname(base)
        PATH = os.path.join(base, "wcbridge_s4.log")
    return PATH


def write(msg):
    try:
        with _lock, open(_path(), "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass
