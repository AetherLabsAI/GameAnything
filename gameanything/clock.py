"""Reading back the local-time stamps gameanything writes (datetime.now().isoformat(): no UTC offset).

    epoch(s, now=None)   the Unix time of an ISO stamp. A stamp with an offset is exact. A stamp without one is local time, and in the
                         hour that repeats when daylight saving ends (01:00-02:00 twice) it names two moments an hour apart:
                         datetime.timestamp() always takes the first, so a line written a second ago in the second pass read as an
                         hour old (the agent looked offline, a run looked stalled; 2026-11-01). Of the two, the later one that is not
                         in the future (`now`, default time.time()) wins: the stamps read here were written in the recent past.
"""
import time
from datetime import datetime


def epoch(s, now=None) -> float:
    """ValueError / TypeError for a value that is not an ISO stamp, like datetime.fromisoformat."""
    d = datetime.fromisoformat(str(s))
    if d.tzinfo is not None: return d.timestamp()
    t0, t1 = d.replace(fold=0).timestamp(), d.replace(fold=1).timestamp()
    if t0 == t1: return t0
    n = time.time() if now is None else now
    late, early = max(t0, t1), min(t0, t1)
    return late if late <= n + 1 else early
