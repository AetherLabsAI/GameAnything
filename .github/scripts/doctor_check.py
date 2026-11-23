"""CI: check `gameanything native doctor --json` (path in argv[1]). Every native adapter is listed, and the automatic build mode follows the rule:
lab only where the lab is usable (Linux, docker and a gamebench kit for its backend); a runner has no gamebench, so native."""
import json
import sys

from gameanything import native

d = json.load(open(sys.argv[1], encoding="utf-8"))
games = [g["game"] for g in d["games"]]
assert games == list(native.GAMES), games
assert d["mode_source"] == "auto" and d["mode"] == d["auto_mode"], d
assert d["auto_mode"] == ("lab" if d["system"] == "linux" and d["lab"]["kit"] else "native"), {k: d[k] for k in ("system", "lab", "auto_mode")}
assert d["lab"]["gamebench"] is None and d["mode"] == "native", {k: d[k] for k in ("system", "lab", "mode", "mode_why")}   # no gamebench on a runner
print("doctor:", d["system"], d["mode"], "-", d["mode_why"])
