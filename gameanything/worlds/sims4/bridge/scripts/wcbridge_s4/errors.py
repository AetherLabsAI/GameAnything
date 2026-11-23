"""Capture the game's Python errors with full tracebacks. Release loggers are suppressed (Logger.exception returns
early), so we wrap both Logger.exception / Logger.error and the module functions sims4.log.exception / error (a
thread-local flag keeps one report per error) and append each report (group, message, traceback) to
Mods/wcbridge_s4_errors.log. The harness and the lab's `s4 log errors` read that file. (The game itself also writes
Documents/.../lastException.txt for errors in the simulation timeline, without the source lines.)"""
import os, sys, time, traceback, threading
from . import log

_lock = threading.Lock()
_busy = threading.local()
MAX_BYTES = 5_000_000


def path():
    return os.path.join(os.path.dirname(log._path()), "wcbridge_s4_errors.log")


def _fmt(message, args):
    try:
        return str(message).format(*args) if args else str(message)
    except Exception:
        return "%s %r" % (message, args)


def record(kind, group, message, args, exc=None):
    try:
        if exc is None:
            exc = sys.exc_info()[1]
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)) if exc is not None \
            else "".join(traceback.format_stack(limit=25)[:-2])
        entry = "=== %s %s [%s] %s\n%s\n" % (time.strftime("%H:%M:%S"), kind, group, _fmt(message, args), tb)
        with _lock:
            p = path()
            if os.path.exists(p) and os.path.getsize(p) > MAX_BYTES:
                os.replace(p, p + ".old")
            with open(p, "a", encoding="utf-8") as f:
                f.write(entry)
    except Exception:
        pass


def _once(kind, group, message, args, exc, call):
    if getattr(_busy, "on", False):          # already recorded by the outer wrapper (Logger method -> module function)
        return call()
    _busy.on = True
    try:
        record(kind, group, message, args, exc)
        return call()
    finally:
        _busy.on = False


def install():
    import sims4.log as L
    if getattr(L.exception, "_wc_wrapped", False):
        return
    m_exc, m_err, c_exc, c_err = L.exception, L.error, L.Logger.exception, L.Logger.error

    def exception(group, message, *args, exc=None, **kw):
        return _once("EXCEPTION", group, message, args, exc, lambda: m_exc(group, message, *args, exc=exc, **kw))

    def error(group, message, *args, **kw):
        return _once("ERROR", group, message, args, None, lambda: m_err(group, message, *args, **kw))

    def logger_exception(self, message, *args, exc=None, **kw):
        return _once("EXCEPTION", getattr(self, "group", "?"), message, args, exc, lambda: c_exc(self, message, *args, exc=exc, **kw))

    def logger_error(self, message, *args, **kw):
        return _once("ERROR", getattr(self, "group", "?"), message, args, None, lambda: c_err(self, message, *args, **kw))

    for f in (exception, error, logger_exception, logger_error):
        f._wc_wrapped = True
    L.exception, L.error = exception, error
    L.Logger.exception, L.Logger.error = logger_exception, logger_error
    log.write("sims4.log exception/error captured to %s" % path())
