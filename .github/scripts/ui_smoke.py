"""CI smoke test of the browser UI, the way a user starts it: `gameanything ui --project <dir> --port <free>` in the background, then fetch
the shell page, /api/shell and the static files with urllib (not curl: it differs on Windows), then stop the server.

    python .github/scripts/ui_smoke.py <project dir>
Exit 0 when every page answered as expected; prints what it fetched.
"""
import json
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); return s.getsockname()[1]


def main(project: str) -> int:
    for s in (sys.stdout, sys.stderr):            # the server prints Chinese (e.g. the no-claude notice); Windows' pipe is cp1252
        if hasattr(s, "reconfigure"): s.reconfigure(encoding="utf-8", errors="replace")
    m2w = shutil.which("gameanything")            # the installed console script (gameanything.exe on Windows)
    if not m2w: print("gameanything is not on PATH"); return 1
    p = subprocess.Popen([m2w, "ui", "--project", project, "--port", str(free_port())], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    q = queue.Queue(); threading.Thread(target=lambda: [q.put(l) for l in iter(p.stdout.readline, b"")], daemon=True).start()
    url = None; log = []; end = time.time() + 60
    try:
        while url is None and time.time() < end:
            try: line = q.get(timeout=1).decode("utf-8", "replace")
            except queue.Empty: line = ""
            if line: log.append(line); print("[server]", line.rstrip())
            if "open http://127.0.0.1:" in line: url = line.split("open ")[1].split()[0].rstrip("/")
            if p.poll() is not None and q.empty(): break
        if url is None: print("the UI did not start"); return 1
        checks = [("/", "text/html", b"<html"), ("/api/shell", "application/json", b"{"), ("/api/feature", "application/json", b"{"), ("/shell.js", "text/javascript", b""), ("/onboard.js", "text/javascript", b""), ("/api/welcome", "application/json", b"{"), ("/api/feedback", "application/json", b"{"), ("/api/profile", "application/json", b"{"),
                  ("/app.js", "text/javascript", b""), ("/app.css", "text/css", b""), ("/i18n.js", "text/javascript", b""),
                  ("/fonts/inter-latin-wght-normal.woff2", "font/woff2", b"")]
        bad = 0
        for path, ctype, start in checks:
            try:
                with urllib.request.urlopen(url + path, timeout=20) as r:
                    body = r.read(); ct = r.headers.get("Content-Type", "")
                    ok = r.status == 200 and ct.startswith(ctype) and len(body) > 0 and (not start or start in body[:4096].lower())
                    if path in ("/api/shell", "/api/feature", "/api/welcome", "/api/feedback", "/api/profile"): json.loads(body)
            except Exception as e:                # noqa: report every failure, then fail the step
                ok, ct, body = False, repr(e), b""
            bad += not ok
            print(f"{'ok  ' if ok else 'FAIL'} {path:<40} {ct:<35} {len(body)} bytes")
        return 1 if bad else 0
    finally:
        p.terminate()
        try: p.wait(15)
        except subprocess.TimeoutExpired: p.kill()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
