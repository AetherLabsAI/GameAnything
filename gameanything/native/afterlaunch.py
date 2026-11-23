"""The steps right after `gameanything native launch` opened a game (Game.after_launch: Civ VI on macOS presses its launcher's PLAY and
skips the intro), as a process of its own: started detached by quiet.launch, so it finishes even when the agent that ran `launch` ends
(her Mac 2026-10-29: the agent's session ended during the intro, the launch command went with it, and the intro was never skipped).
The result goes into the launch's record ("after"; `gameanything native launches`) and this log: <project>/conversation/.native_after.log

    python -m gameanything.native.afterlaunch <project folder> <game id> <launch id> <pid> [<pid> ...]"""
import json
import sys
from datetime import datetime
from pathlib import Path


def main(argv) -> int:
    from . import get, quiet
    root, gid, lid, pids = Path(argv[0]), argv[1], argv[2], [int(p) for p in argv[3:]]
    g = get(gid)
    try: after = g.after_launch(root, pids)
    except Exception as e: after = {"step": "after_launch", "why": f"{type(e).__name__}: {e}"}     # (a detached process: always record why)
    quiet._update(root, lambda L: [y.update(after=after) for y in L["launches"] if y["id"] == lid])
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {gid} {lid}: {json.dumps(after, ensure_ascii=False)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
