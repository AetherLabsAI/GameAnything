"""Write to Mods/<name>/<name>.log next to <name>.ts4script (`m2w native log --game sims4` shows it). print() and sims4.log output go
nowhere in the release game. This file sits inside the .ts4script zip, so the log path is derived from the zip's own path."""
import os, time

_ZIP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))                   # .../Mods/<name>/<name>.ts4script
PATH = (_ZIP[:-len(".ts4script")] if _ZIP.endswith(".ts4script") else _ZIP + "-m2w") + ".log"


def write(msg):
    try:
        with open(PATH, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass
