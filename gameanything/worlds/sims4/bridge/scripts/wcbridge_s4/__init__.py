"""WorldCritic Sims 4 bridge (WCP v0.1) as a script mod. Importing it (the game imports every top-level module in a
.ts4script under Mods/) starts the TCP servers and hooks Zone.update so requests run on the simulation thread."""
from .version import VERSION, PROTOCOL  # noqa: F401

try:
    from . import server, dispatch, errors
    errors.install()
    dispatch.install()
    server.start()
except Exception:  # never break game start-up because of the bridge
    import traceback
    from . import log
    log.write("bridge start failed:\n" + traceback.format_exc())
