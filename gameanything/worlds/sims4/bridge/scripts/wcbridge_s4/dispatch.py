"""Run requests on the simulation thread: a wrapper around Zone.update drains the request queue every tick, with a small
time budget so a burst of requests cannot stall the game. Outside a zone (main menu, loading) nothing ticks Python;
server.py then answers health itself and rejects everything else with NOT_READY."""
import queue, time
from . import log

REQUESTS = queue.Queue()
LAST_TICK = [0.0]      # wall time of the last Zone.update (server.py uses it to tell "in zone" from "menu/loading")
TICKS = [0]
BUDGET_S = 0.05
TICK_CALLBACKS = []    # optional per-tick callbacks (no args, simulation thread), e.g. a project mod's ticker; errors are logged and the callback dropped


class Job:
    __slots__ = ("fn", "done", "result", "error")

    def __init__(self, fn):
        self.fn, self.result, self.error = fn, None, None
        import threading
        self.done = threading.Event()


def submit(fn, timeout=60.0):
    """Called from the server thread; blocks until the simulation thread ran fn. Returns (result, error)."""
    job = Job(fn)
    REQUESTS.put(job)
    if not job.done.wait(timeout):
        return None, TimeoutError("simulation thread did not run the request within %ss" % timeout)
    return job.result, job.error


def drain():
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < BUDGET_S:
        try:
            job = REQUESTS.get_nowait()
        except queue.Empty:
            return
        try:
            job.result = job.fn()
        except BaseException as e:  # report to the caller, keep the game running
            job.error = e
        finally:
            job.done.set()


def install():
    import zone
    if getattr(zone.Zone.update, "_wc_wrapped", False):
        return
    orig = zone.Zone.update

    def update(self, absolute_ticks):
        r = orig(self, absolute_ticks)
        LAST_TICK[0] = time.time(); TICKS[0] += 1
        try:
            drain()
        except Exception as e:
            log.write("drain error: %r" % (e,))
        for cb in list(TICK_CALLBACKS):
            try:
                cb()
            except Exception as e:
                log.write("tick callback dropped: %r" % (e,))
                try:
                    TICK_CALLBACKS.remove(cb)
                except ValueError:
                    pass
        return r

    update._wc_wrapped = True
    zone.Zone.update = update
    log.write("Zone.update hooked")
