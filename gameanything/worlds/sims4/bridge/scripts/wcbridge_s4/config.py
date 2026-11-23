"""Ports: environment (S4BRIDGE_PORT / S4BRIDGE_HARNESS_PORT, passed from the container through Steam and Proton), else
Mods/wcbridge_s4.cfg (JSON {"port": .., "harness_port": ..}, written by the launcher), else 6531 / 6631 (slot sims4 = 31)."""
import json, os
from . import log


def ports():
    agent, harness = os.environ.get("S4BRIDGE_PORT"), os.environ.get("S4BRIDGE_HARNESS_PORT")
    if agent and harness:
        return int(agent), int(harness), "env"
    cfg = os.path.join(os.path.dirname(log._path()), "wcbridge_s4.cfg")
    try:
        d = json.load(open(cfg, encoding="utf-8"))
        return int(d["port"]), int(d["harness_port"]), "cfg"
    except Exception:
        return 6531, 6631, "default"
