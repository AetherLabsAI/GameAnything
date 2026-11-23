"""Maintainer-only guidance: internal/ at the repository root (git-ignored since 2026-11-01: not in the public repository; maintainers keep
their own copy in their checkouts) (the gamebench labs: seats, the broker, the coordinator, each game's lab tools;
the hub: several users on one server). Not the user's flow: it is not in skills/ (so not in the plugin, the skill copies or the installed
package), and an agent's prompt gets it only where it applies: a machine with a gamebench lab (buildmode.lab_kit) or the hub
(setupguide.is_hub). On a user's machine none of it exists and nothing points at it.

    GAMEBENCH       internal/agent/gamebench-lab.md   appended to the resident's and the builder's prompt (agentd.py, builds.py)
    SERVER_GUIDE    internal/setups/server-sandbox.md the hub's `setup guide` (setupguide.guide_path)
    addendum(root, env)  "" or the text to append
"""
from pathlib import Path

from . import shipped

DIR = shipped.CHECKOUT / "internal"
GAMEBENCH = DIR / "agent" / "gamebench-lab.md"
SERVER_GUIDE = DIR / "setups" / "server-sandbox.md"


def applies(root=None, env=None) -> bool:
    from . import buildmode, setupguide
    try:
        if buildmode.lab_kit(env): return True
    except Exception: pass
    try: return bool(setupguide.is_hub(root, env))
    except Exception: return False


def addendum(root=None, env=None, role="resident") -> str:
    """The builder's prompt fills {{lease}} / {{milestone}} (builds.py); the resident has neither: plain words instead of a raw {{...}}."""
    if not GAMEBENCH.is_file() or not applies(root, env): return ""
    t = GAMEBENCH.read_text(encoding="utf-8")
    if role != "builder": t = t.replace("{{lease}}", "the builder's Lab line").replace("{{milestone}}", "<milestone>")
    return "\n\n" + t
