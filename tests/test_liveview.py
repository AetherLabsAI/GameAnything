"""The 工作台 panel's data and the live game view (live.py now_state, liveview.py): nothing is shown before her yes, the view goes through
the m2w UI itself (same origin, /live/…), and it is view only on the server side too: keys, pointer and clipboard never reach the game.
A fake viewer (noVNC page + websockify) stands in for the sandbox seat."""
import base64
import hashlib
import json
import socket
import struct
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from gameanything import builds, live, liveview, projects
from gameanything.conversation import Thread

OPEN = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class FakeViewer(BaseHTTPRequestHandler):
    got = []

    def log_message(self, *a): pass

    def do_GET(self):
        if self.path.startswith("/novnc/"):
            b = b"<html>noVNC page</html>"; self.send_response(200); self.send_header("Content-Type", "text/html")
            self.send_header("Set-Cookie", "x=1"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        if self.path == "/websockify":
            k = self.headers["Sec-WebSocket-Key"]
            acc = base64.b64encode(hashlib.sha1((k + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            self.wfile.write(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {acc}\r\n\r\n".encode())
            self.wfile.write(liveview.frame(2, b"RFB 003.008\n", mask=False)); self.wfile.flush()
            while True:
                f = liveview.read_frame(self.rfile)
                if f is None or f[1] == 8: return
                FakeViewer.got.append(f[2])
        self.send_response(404); self.end_headers()


@pytest.fixture
def viewer(monkeypatch):
    FakeViewer.got = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeViewer); threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("GAMEANYTHING_LIVE_UPSTREAM", f"127.0.0.1:{srv.server_port}")
    yield srv
    srv.shutdown(); srv.server_close()


@pytest.fixture
def proj_ui():
    e = projects.create("看游戏", "feature", game="minecraft", build_mode="lab"); root = Path(e["path"])
    Thread(root).append({"from": "agent", "type": "text", "text": "你好", "source": "terminal"})
    from gameanything.ui import serve
    box, ready = {}, threading.Event()
    threading.Thread(target=serve, args=(root,), kwargs={"port": 0, "ready": lambda s: (box.update(srv=s), ready.set())}, daemon=True).start()
    assert ready.wait(20)
    yield e, root, f"http://127.0.0.1:{box['srv'].server_port}/p/{e['id']}"
    box["srv"].shutdown(); box["srv"].server_close()


def running(root, state="running", mode="lab"):
    f = builds.run_file(root, "m1"); f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"state": state, "milestone": "m1", "build_mode": mode, "lease": "tester/p/mclab-x:2", "run_id": "r1", "started": "2026-10-26T10:00:00",
                             "playtest_rounds": 3, "rounds": 1, "wall_hours": 5, "provider": "claude-code", "log": str(root / "run.jsonl")}), encoding="utf-8")


def get(url, data=None):
    r = urllib.request.Request(url, json.dumps(data).encode() if data is not None else None, {"Content-Type": "application/json"})
    try:
        with OPEN.open(r, timeout=20) as x: return x.status, x.read(), x.headers
    except urllib.error.HTTPError as x: return x.code, x.read(), x.headers


def ws_open(base):
    host, port = base.split("//")[1].split("/")[0].split(":")
    s = socket.create_connection((host, int(port)), timeout=10)
    path = "/" + base.split("/", 3)[3] + "/live/websockify"
    s.sendall(f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
              f"Sec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: binary\r\n\r\n".encode())
    f = s.makefile("rb"); head = b""
    while not head.endswith(b"\r\n\r\n"): head += f.read(1)
    return s, f, head


def test_view_only_filter_drops_input_and_follows_split_messages():
    v = liveview.ViewOnly()
    msgs = (b"RFB 003.008\n" + b"\x01" + b"\x00" + bytes([3, 0]) + struct.pack(">HHHH", 0, 0, 64, 64) + bytes([5, 1]) + struct.pack(">HH", 3, 4)
            + bytes([4, 1, 0, 0]) + struct.pack(">I", 65) + bytes([6, 0, 0, 0]) + struct.pack(">i", 3) + b"abc" + bytes([2, 0]) + struct.pack(">H", 1) + b"\0\0\0\0")
    out = b"".join(v.feed(msgs[i:i + 3]) for i in range(0, len(msgs), 3))
    assert out == b"RFB 003.008\n\x01\x01" + bytes([3, 0]) + struct.pack(">HHHH", 0, 0, 64, 64) + bytes([2, 0]) + struct.pack(">H", 1) + b"\0\0\0\0"
    assert v.dropped == 3 and not v.broken
    w = liveview.ViewOnly(); w.feed(b"RFB 003.003\n"); assert w.broken, "an RFB version it cannot follow closes the stream"
    x = liveview.ViewOnly(); x.feed(b"RFB 003.008\n\x01\x01" + bytes([99])); assert x.broken, "an unknown message closes the stream"


def test_nothing_before_her_yes_then_view_only_through_the_ui_and_off_again(proj_ui, viewer):
    e, root, base = proj_ui
    running(root)
    st, body, _ = get(base + "/live/novnc/vnc.html"); assert st == 404, "no consent yet"
    n = json.loads(get(base + "/api/now")[1]); assert n["build"]["m"] == "m1" and n["live"] == {"possible": True, "on": False, "mode": "lab"}
    # her yes on the permission card agentd posted
    T = Thread(root); live.Live()._ask_view(T, "m1", builds.current(root)[1]); live.Live()._ask_view(T, "m1", builds.current(root)[1])
    cards = [c for c in T.events() if c.get("type") == "card" and c["card"]["key"] == "live-view-m1"]
    assert len(cards) == 1 and cards[0]["from"] == "system" and "实时画面" in cards[0]["card"]["title"] and cards[0]["card_en"]["title"]
    T.answer(cards[0]["id"], {"decision": "yes"})
    st, body, h = get(base + "/live/novnc/vnc.html"); assert st == 200 and b"noVNC page" in body and h.get("Set-Cookie") is None
    assert get(base + "/live/stream.mp3")[0] == 404 and get(base + "/live/novnc/../x")[0] == 404, "only the viewer page and the websocket"
    s, f, head = ws_open(base); assert head.startswith(b"HTTP/1.1 101")
    first = liveview.read_frame(f); assert first[2] == b"RFB 003.008\n"
    for part in (b"RFB 003.008\n", b"\x01", b"\x00", bytes([3, 0]) + struct.pack(">HHHH", 0, 0, 8, 8), bytes([5, 1]) + struct.pack(">HH", 1, 1), bytes([4, 1, 0, 0, 0, 0, 0, 65])):
        s.sendall(liveview.frame(2, part))
    t0 = time.time()
    while len(b"".join(FakeViewer.got)) < 26 and time.time() - t0 < 10: time.sleep(0.05)
    time.sleep(0.3)
    assert b"".join(FakeViewer.got) == b"RFB 003.008\n\x01\x01" + bytes([3, 0]) + struct.pack(">HHHH", 0, 0, 8, 8), "the pointer and the key never reached the game"
    s.close()
    # she turns it off in the panel: refused again
    st, body, _ = get(base + "/api/live", {"on": False}); assert st == 200 and json.loads(body)["live"]["on"] is False
    assert get(base + "/live/novnc/vnc.html")[0] == 404 and json.loads(get(base + "/api/now")[1])["live"]["on"] is False
    get(base + "/api/live", {"on": True}); assert get(base + "/live/novnc/vnc.html")[0] == 200
    running(root, state="done"); assert get(base + "/live/novnc/vnc.html")[0] == 404, "the build ended: the view stops"


def test_native_builds_get_window_pictures_not_a_port(proj_ui, monkeypatch, tmp_path):
    e, root, base = proj_ui
    running(root, mode="native"); r = builds.current(root)[1]
    assert json.loads(get(base + "/api/now")[1])["live"]["possible"] is False
    from gameanything.native import hands
    from PIL import Image
    shots = []
    def fake_shot(rt, g, out): Image.new("RGB", (320, 200), (1, 2, 3)).save(out); shots.append(out); return {"path": str(out)}
    monkeypatch.setattr(hands, "shot", fake_shot)
    L = live.Live(); S = {}
    L._native_shot(root, "m1", r, S); assert shots == [], "no picture before her yes"
    liveview.set_consent(root, "m1", True)
    L._native_shot(root, "m1", r, S); assert len(shots) == 1 and S["shots"][-1]["url"].startswith("/conv/now_native_m1_")
    L._native_shot(root, "m1", r, S); assert len(shots) == 1, "at most one per NATIVE_SHOT_SECS"


@pytest.mark.skipif(not __import__("shutil").which("node"), reason="node is not installed")
def test_panel_renders_in_node(proj_ui):
    """SCREENS.now with real /api/now data and a fake DOM, in zh and en."""
    import subprocess
    e, root, base = proj_ui
    running(root)
    from gameanything import activity as A
    (root / "run.jsonl").write_text(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "a", "name": "Edit", "input": {"file_path": "Story.java"}}]}}) + "\n", encoding="utf-8")
    A.Tail(root, "r1", root / "run.jsonl", "claude-code", "builder").step()
    static = Path(live.__file__).parent / "ui" / "static"
    app = (static / "app.js").read_text(encoding="utf-8")
    part = app[app.index("/* ------------------------------------------------------------ 工作台 / Now"):app.index("\nroute();          // last")]
    out = {}
    for lang in ("zh", "en"):
        data = json.dumps(live.now_state(root, lang), ensure_ascii=False)
        js = ("globalThis.window={addEventListener(){}};globalThis.document={documentElement:{dataset:{},getAttribute(){return null},setAttribute(){}},"
              "addEventListener(){},querySelectorAll(){return[]}};globalThis.localStorage={getItem(){return null},setItem(){}};\n"
              + (static / "i18n.js").read_text(encoding="utf-8")
              + f"\nM2W.lang={json.dumps(lang)};const SCREENS={{}};const esc=s=>String(s??'');const els={{}};const $=s=>(els[s]=els[s]||{{innerHTML:''}});const $$=()=>[];"
              "const topbar=c=>c;const post=async()=>({});"
              f"const get=async()=>({data});\n" + part
              + "\nSCREENS.now([],()=>false).then(()=>console.log(els['#nowbody'].innerHTML + '|||' + nowHtml(" + data + ",false)));")
        out[lang] = subprocess.run(["node", "-"], input=js, capture_output=True, text=True, check=True, encoding="utf-8").stdout
    assert "在改剧情镜头的代码 Story.java" in out["zh"] and "第 1 / 3 轮" in out["zh"] and "打开工作台" in out["zh"]
    assert "Editing the story camera code Story.java" in out["en"] and "Open the work view" in out["en"]
