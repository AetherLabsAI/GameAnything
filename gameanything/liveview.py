"""Watching the game of a running lab build, only after she said yes (Stage C of the live view; live.py posts the question).

    consent(root, m) -> bool         her yes on the permission card `live-view-<m>` (or the panel's switch), not turned off since
    set_consent(root, m, on, who)    the panel's 「打开 / 关掉实时画面」
    upstream(r) -> (host, port)      where the sandbox seat's viewer (noVNC + websockify, gamebench docker/viewer.py) listens, from the
                                     build's lab lease: a docker-rt pod by its IP (like /opt/docker-rt/view-proxy.py), the seat's port
                                     6080 + 10 * (seat - 1); $GAMEANYTHING_LIVE_UPSTREAM (host:port) overrides it (tests, another lab)
    allowed(root) -> (m, r, (host, port)) | None     a running lab build of this project she agreed to watch, else None
    serve(handler, root, rest)       the GameAnything UI route /live/<rest> (same origin, so no port forwarding): `novnc/…` files and `websockify`
                                     (the VNC websocket), nothing else of the viewer. VIEW ONLY on the server side too: the websocket from
                                     the browser is read frame by frame and the RFB input messages (keys, pointer, clipboard, desktop size)
                                     are dropped before they reach the game; an RFB stream it cannot follow is closed.
The page's iframe: <base>/live/novnc/vnc.html?autoconnect=1&view_only=1&resize=scale&path=<base without the first />/live/websockify
Access: the UI's own rules (127.0.0.1; with a hub, users.role_of: anyone who can open the project). It stops when the build ends or she
turns it off: every open stream checks allowed() every few seconds.
"""
import http.client
import json
import os
import re
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

CHECK_SECS = 5
POD_IP_SECS = 600
DOCKER = os.environ.get("DOCKER_BIN", "/opt/docker-rt/bin/docker")
DOCKER_HOST = os.environ.get("GAMEANYTHING_DOCKER_RT_HOST", "unix:///tmp/docker-rt.sock")
_ips = {}                                    # sandbox -> (ip, when)


def key(m) -> str: return f"live-view-{m}"


def _file(root) -> Path: return Path(root) / "conversation" / ".live_view.json"


def _read(p):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError): return None


def consent(root, m) -> bool:
    """Her newest word on watching build m: the card's answer or the panel's switch, whichever came last."""
    from .conversation import Thread
    T = Thread(root); best = (None, False); cids = set()
    for e in T.events():
        if e.get("type") == "card" and (e.get("card") or {}).get("key") == key(m): cids.add(e["id"])
        elif e.get("type") == "answer" and e.get("card_id") in cids:
            best = (e.get("at") or "", (e.get("answer") or {}).get("decision") == "yes")
    s = (_read(_file(root)) or {}).get(m) or {}
    if s.get("at") and (best[0] is None or str(s["at"]) >= str(best[0])): return bool(s.get("on"))
    return best[1]


def asked(root, m) -> bool:
    from .conversation import Thread
    return any(e.get("type") == "card" and (e.get("card") or {}).get("key") == key(m) for e in Thread(root).events())


def set_consent(root, m, on, who=None):
    from .conversation import now
    d = _read(_file(root)) or {}; d[m] = {"on": bool(on), "at": now(), "by": who}
    f = _file(root); f.parent.mkdir(parents=True, exist_ok=True); tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8"); os.replace(tmp, f)
    return d[m]


# ---------------------------------------------------------------- where the viewer is
def _pod_ip(sandbox):
    ip, at = _ips.get(sandbox, (None, 0))
    if ip and time.time() - at < POD_IP_SECS: return ip
    env = {**os.environ, "DOCKER_HOST": os.environ.get("DOCKER_HOST") or DOCKER_HOST}
    for flag in ("-I", "-i"):                                   # the same lookup as /opt/docker-rt/view-proxy.py (read only)
        try: out = subprocess.run([DOCKER, "exec", sandbox, "hostname", flag], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=20).stdout
        except (OSError, subprocess.SubprocessError): return None
        for tok in out.split():
            if tok.count(".") == 3 and not tok.startswith("127."): _ips[sandbox] = (tok, time.time()); return tok
    return None


def upstream(r):
    """(host, port) of the viewer of the build's lab seat, or None."""
    o = os.environ.get("GAMEANYTHING_LIVE_UPSTREAM")
    if o and ":" in o: h, _, p = o.rpartition(":"); return h, int(p)
    m = re.match(r"^[^/]+/[^/]+/([A-Za-z0-9_.-]+):(\w+)$", str(r.get("lease") or ""))
    if not m: return None
    sb, seat = m.group(1), m.group(2)
    port = 6080 + 10 * (int(seat) - 1) if seat.isdigit() else 6080          # lab-display.sh N: viewer 6080+10*(N-1); a whole sandbox: 6080
    ip = _pod_ip(sb)
    return (ip, port) if ip else None


def allowed(root):
    """(m, build record, (host, port)) when this project's lab build runs and she agreed to watch it, else None."""
    from . import builds
    m, r = builds.current(root)
    if not r or r.get("state") != "running" or r.get("build_mode") != "lab" or not consent(root, m): return None
    up = upstream(r)
    return (m, r, up) if up else None


# ---------------------------------------------------------------- view only: the browser's RFB messages, input dropped
class ViewOnly:
    """Follows the client half of an RFB stream (3.7 / 3.8, security None or VNC auth) and lets through only what does not touch the game:
    the handshake, SetPixelFormat, SetEncodings, FramebufferUpdateRequest, EnableContinuousUpdates, Fence. KeyEvent, PointerEvent,
    ClientCutText, SetDesktopSize, xvp and anything unknown are dropped; a stream it cannot follow sets .broken (the tunnel closes)."""
    FIXED = {0: 20, 3: 10, 150: 10, 4: 8, 5: 6, 252: 4}
    PASS = {0, 2, 3, 150, 248}

    def __init__(self): self.buf = b""; self.st = "version"; self.broken = False; self.dropped = 0

    def feed(self, data: bytes) -> bytes:
        self.buf += data; out = b""
        while not self.broken:
            b = self.buf
            if self.st == "version":
                if len(b) < 12: break
                v = b[:12]
                if not re.match(rb"RFB 003\.00[78]\n", v): self.broken = True; break
                out += v; self.buf = b[12:]; self.st = "security"; continue
            if self.st == "security":
                if len(b) < 1: break
                t = b[0]
                if t not in (1, 2): self.broken = True; break
                out += b[:1]; self.buf = b[1:]; self.st = "auth" if t == 2 else "init"; continue
            if self.st == "auth":
                if len(b) < 16: break
                out += b[:16]; self.buf = b[16:]; self.st = "init"; continue
            if self.st == "init":
                if len(b) < 1: break
                out += b"\x01"; self.buf = b[1:]; self.st = "msg"; continue      # shared: never disconnect the builder's own viewer
            if not b: break
            t = b[0]
            if t in self.FIXED: n = self.FIXED[t]
            elif t == 2:
                if len(b) < 4: break
                n = 4 + 4 * struct.unpack(">H", b[2:4])[0]
            elif t == 6:
                if len(b) < 8: break
                n = 8 + abs(struct.unpack(">i", b[4:8])[0])
            elif t == 248:
                if len(b) < 9: break
                n = 9 + b[8]
            elif t == 251:
                if len(b) < 8: break
                n = 8 + 16 * b[6]
            else: self.broken = True; break
            if len(b) < n: break
            if t in self.PASS: out += b[:n]
            else: self.dropped += 1
            self.buf = b[n:]
        return out


# ---------------------------------------------------------------- websocket frames (RFC 6455)
def read_frame(rf):
    """-> (fin, opcode, payload, raw) from a file-like reader, or None at the end."""
    h = rf.read(2)
    if len(h) < 2: return None
    fin, op, masked, n = h[0] >> 7, h[0] & 15, h[1] >> 7, h[1] & 127; raw = h
    if n == 126: x = rf.read(2); raw += x; n = struct.unpack(">H", x)[0]
    elif n == 127: x = rf.read(8); raw += x; n = struct.unpack(">Q", x)[0]
    mk = rf.read(4) if masked else b""; raw += mk
    if n > 64 << 20: return None
    data = rf.read(n) if n else b""
    if len(data) < n: return None
    raw += data
    if masked: data = bytes(c ^ mk[i % 4] for i, c in enumerate(data))
    return fin, op, data, raw


def frame(op, data, fin=1, mask=True) -> bytes:
    n = len(data); h = bytes([(fin << 7) | op])
    mb = 0x80 if mask else 0
    h += bytes([mb | n]) if n < 126 else bytes([mb | 126]) + struct.pack(">H", n) if n < 65536 else bytes([mb | 127]) + struct.pack(">Q", n)
    if not mask: return h + data
    mk = os.urandom(4)
    return h + mk + bytes(c ^ mk[i % 4] for i, c in enumerate(data))


# ---------------------------------------------------------------- the route
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade", "set-cookie"}


def serve(h, root, rest):
    """The UI handler h answers GET /live/<rest>. -> True when answered."""
    a = allowed(root)
    if a is None: h.send(404, "实时画面没有打开（她还没同意，或者构建不在服务器沙箱里跑）".encode(), "text/plain; charset=utf-8"); return True
    m, r, (host, port) = a
    rest = rest.lstrip("/")
    if rest == "websockify" and "websocket" in (h.headers.get("Upgrade") or "").lower(): return _tunnel(h, root, host, port)
    if not re.match(r"^novnc/[\w./\-]+$", rest) or ".." in rest: h.send(404, b"not found", "text/plain"); return True
    q = h.path.partition("?")[2]
    try:
        c = http.client.HTTPConnection(host, port, timeout=15); c.request("GET", "/" + rest + (f"?{q}" if q else ""), headers={"Host": f"{host}:{port}"})
        res = c.getresponse(); body = res.read()
    except OSError:
        h.send(502, "游戏画面现在连不上".encode(), "text/plain; charset=utf-8"); return True
    h.send_response(res.status)
    for k, v in res.getheaders():
        if k.lower() not in HOP and k.lower() != "content-length": h.send_header(k, v)
    h.send_header("Content-Length", str(len(body))); h.end_headers(); h.wfile.write(body); c.close()
    return True


def _tunnel(h, root, host, port):
    try: up = socket.create_connection((host, port), timeout=15)
    except OSError: h.send(502, b"viewer unreachable", "text/plain"); return True
    hdr = ["GET /websockify HTTP/1.1", f"Host: {host}:{port}", "Upgrade: websocket", "Connection: Upgrade"]
    for k in ("Sec-WebSocket-Key", "Sec-WebSocket-Version", "Sec-WebSocket-Protocol", "Sec-WebSocket-Extensions"):
        if h.headers.get(k) and k != "Sec-WebSocket-Extensions": hdr.append(f"{k}: {h.headers[k]}")
    up.sendall(("\r\n".join(hdr) + "\r\n\r\n").encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        x = up.recv(4096)
        if not x: up.close(); h.send(502, b"viewer closed", "text/plain"); return True
        resp += x
    head, _, extra = resp.partition(b"\r\n\r\n")
    if not head.startswith(b"HTTP/1.1 101"): up.close(); h.send(502, b"viewer refused the websocket", "text/plain"); return True
    h.close_connection = True
    cl = h.connection; cl.sendall(head + b"\r\n\r\n" + extra)
    stop = threading.Event(); flt = ViewOnly()

    def down():                                      # the game's picture -> her browser, as it is
        up.settimeout(CHECK_SECS)
        while not stop.is_set():
            try: x = up.recv(65536)
            except socket.timeout:
                if allowed(root) is None: break
                continue
            except OSError: break
            if not x: break
            try: cl.sendall(x)
            except OSError: break
        stop.set()

    t = threading.Thread(target=down, daemon=True, name="live-view"); t.start()
    try:
        while not stop.is_set():
            f = read_frame(h.rfile)
            if f is None: break
            fin, op, data, raw = f
            if op in (0, 1, 2):
                ok = flt.feed(data)
                if flt.broken: break
                if ok: up.sendall(frame(2 if op == 1 else op or 2, ok, 1))
            elif op == 8: up.sendall(raw); break
            else: up.sendall(raw)
    except OSError: pass
    finally:
        stop.set()
        for s in (up, cl):
            try: s.shutdown(socket.SHUT_RDWR)
            except OSError: pass
        up.close(); t.join(CHECK_SECS + 1)
    return True
