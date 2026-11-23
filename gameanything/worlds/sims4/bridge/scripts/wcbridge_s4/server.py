"""Two TCP listeners (agent / harness channel), newline-delimited JSON-RPC 2.0 (WCP v0.1, note/wcp-spec-v0.md).
I/O runs on daemon threads; anything touching game state is handed to the simulation thread through dispatch.submit."""
import json, socket, threading, time, traceback
from . import config, dispatch, handlers, log

NOT_READY, FORBIDDEN, UNAVAILABLE, ACTION_FAILED, TIMEOUT = 1001, 1002, 1003, 1004, 1005
BOTH = {"hello", "health"}
AGENT = {"get_state", "list_actions", "act"}
HARNESS = {"pause", "resume", "advance", "eval_query", "set_speed", "reload"}


def in_zone():
    return time.time() - dispatch.LAST_TICK[0] < 3.0


def _err(rid, code, msg, data=None):
    e = {"code": code, "message": msg}
    if data is not None:
        e["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": e}


def handle(req, channel):
    rid, method, params = req.get("id"), req.get("method"), req.get("params") or {}
    if method in BOTH:
        if method == "hello":
            return {"jsonrpc": "2.0", "id": rid, "result": handlers.hello(channel)}
        if not in_zone():  # no Python tick: main menu, loading screen, or a hung game
            return {"jsonrpc": "2.0", "id": rid, "result": {"status": "menu", "tick": dispatch.TICKS[0], "paused": None}}
    elif method in AGENT or method in HARNESS:
        if method in HARNESS and channel != "harness":
            return _err(rid, FORBIDDEN, "%s is a harness-channel method" % method)
        if not in_zone():
            return _err(rid, NOT_READY, "not in a zone (main menu or loading)")
    else:
        return _err(rid, -32601, "method not found: %s" % method)
    fn = getattr(handlers, method)
    result, error = dispatch.submit(lambda: fn(**params), timeout=float(params.get("timeout_s", 60)) if isinstance(params, dict) else 60)
    if error is not None:
        if isinstance(error, TimeoutError):
            return _err(rid, TIMEOUT, str(error))
        if isinstance(error, TypeError):
            return _err(rid, -32602, "invalid params: %s" % error)
        code = getattr(error, "wcp_code", ACTION_FAILED)
        return _err(rid, code, "%s: %s" % (type(error).__name__, error),
                    {"traceback": "".join(traceback.format_exception(type(error), error, error.__traceback__))[-3000:]})
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def serve_conn(conn, channel):
    f = conn.makefile("rwb")
    try:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line.decode("utf-8"))
                resp = handle(req, channel)
            except ValueError as e:
                resp = _err(None, -32700, "parse error: %s" % e)
            except Exception as e:
                resp = _err(None, -32603, "internal error: %r" % (e,))
            f.write((json.dumps(resp, default=str) + "\n").encode("utf-8")); f.flush()
    except OSError:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def listen(port, channel):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port)); s.listen(8)
    log.write("%s channel listening on 127.0.0.1:%d" % (channel, port))
    while True:
        conn, _ = s.accept()
        threading.Thread(target=serve_conn, args=(conn, channel), daemon=True, name="wc-%s-conn" % channel).start()


def start():
    agent, harness, src = config.ports()
    log.write("wcbridge_s4 starting (ports from %s)" % src)
    for port, ch in ((agent, "agent"), (harness, "harness")):
        threading.Thread(target=listen, args=(port, ch), daemon=True, name="wc-%s" % ch).start()
