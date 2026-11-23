"""Security regressions of the multi-user hub (QA 2026-10-29): milestone path traversal and frame writes (B1), welcome examples of other
users (B2), the comment role deciding (M1), import / export zips (M2), login throttling (M3), Origin behind a proxy (M5), headers, paths
in errors and owner-only panels (m6), access-request spam and re-answers (m7), private titles in the list (m8)."""
import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from gameanything import projects, users
from gameanything.conversation import Thread

from test_hub import Client, NoRedirect, hub, new_alice_project  # noqa: F401  (hub is a fixture)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PNG_URL = "data:image/png;base64," + base64.b64encode(PNG).decode()


def make_play(root: Path, m="m1", secret="mine"):
    d = root / "5_build" / m / "play"; d.mkdir(parents=True, exist_ok=True)
    (d / "play.yaml").write_text("chapters: []\n", encoding="utf-8")
    (d / "user_review.yaml").write_text(yaml.safe_dump({"moments": {}, "checks": {}, "sounds": {}, "notes": [{"note": secret}]}), encoding="utf-8")
    (d / "result").mkdir(exist_ok=True); (d / "result" / "shot.png").write_bytes(PNG)
    return d


def new_project(c, title):
    code, r, _ = c.post("/api/hub/new", {"title": title, "kind": "memory", "game": "stardew", "lang": "en"}); assert code == 200, r
    return r["id"], Path(projects.find(r["id"])["path"])


def raw_post(c, path, body: bytes, headers):
    h = {"Origin": c.base, "Cookie": c.cookie, **headers}
    r = urllib.request.Request(c.base + path, body, h, method="POST")
    try: resp = urllib.request.build_opener(NoRedirect).open(r, timeout=20); code = resp.status
    except urllib.error.HTTPError as e: resp = e; code = e.code
    return code, json.loads(resp.read() or b"{}")


def upload_import(c, pid, data: bytes, name="backup.zip", uid="upl-0123456789"):
    return raw_post(c, f"/p/{pid}/api/upload", data, {"X-Upload-Id": uid, "X-File-Name": name, "X-Upload-Target": "import",
                                                       "Content-Range": f"bytes 0-{len(data) - 1}/{len(data)}", "Content-Type": "application/octet-stream"})


def wait_job(c, url):
    for _ in range(200):
        code, j, _ = c.get(url)
        if code != 200 or j.get("state") != "running": return code, j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


# ---------------------------------------------------------------- B1
def test_play_milestone_traversal_and_frames(hub):
    a = Client(hub).login("alice"); b = Client(hub).login("bob")
    apid, aroot = new_project(a, "Alice Day"); bpid, broot = new_project(b, "Bob Secret")
    make_play(aroot, "m1"); bplay = make_play(broot, "m1", secret="bob's private words")
    users._write_cfg_key(broot, "visibility", "private")
    up = os.path.relpath(broot / "5_build" / "m1", aroot / "5_build")
    code, r, _ = a.get(f"/p/{apid}/api/play?m={up}")
    assert code == 404 and b"bob's private" not in (r if isinstance(r, bytes) else json.dumps(r).encode())
    before = (bplay / "user_review.yaml").read_text(encoding="utf-8")
    for m in (up, "../m1", "m1/../m1", "", None, ".hidden", "m2"):
        code, r, _ = a.post(f"/p/{apid}/api/play_feedback", {"m": m, "kind": "time", "note": "x", "t": 1})
        assert code == 400, (m, r)
        assert a.post(f"/p/{apid}/api/next_round", {"m": m, "items": []})[0] == 400
    assert (bplay / "user_review.yaml").read_text(encoding="utf-8") == before and not (bplay / "next_round_request.yaml").exists()
    # the frame: a PNG only, inside this project's feedback/frames
    for bad in ("data:image/png;base64," + base64.b64encode(b"#!/bin/sh\necho owned\n").decode(), "data:text/plain;base64,AAAA", "nope"):
        assert a.post(f"/p/{apid}/api/play_feedback", {"m": "m1", "kind": "time", "note": "x", "t": 1, "frame": bad})[0] == 400
    assert not (aroot / "feedback" / "frames").exists() or not list((aroot / "feedback" / "frames").iterdir())
    code, r, _ = a.post(f"/p/{apid}/api/play_feedback", {"m": "m1", "kind": "time", "note": "look here", "t": 2, "frame": PNG_URL}); assert code == 200, r
    fr = list((aroot / "feedback" / "frames").iterdir()); assert len(fr) == 1 and fr[0].read_bytes() == PNG
    code, r, _ = a.get(f"/p/{apid}/api/play?m=m1"); assert code == 200 and r["m"] == "m1"
    # the same pattern elsewhere: a look id names a file, chat frames and file contexts
    assert a.post(f"/p/{apid}/api/look", {"id": "../../../x", "look": {}, "rev": "-"})[0] == 400
    assert a.post(f"/p/{apid}/api/thread", {"text": "hi", "context": [{"kind": "moment", "id": "m", "frame_data": "data:image/png;base64," + base64.b64encode(b"GIF89a").decode()}]})[0] == 400
    assert a.post(f"/p/{apid}/api/thread", {"text": "hi", "context": [{"kind": "file", "path": str(bplay / "user_review.yaml")}]})[0] == 400
    assert a.post(f"/p/{apid}/api/thread", {"text": "hi", "context": [{"kind": "file", "path": "5_build/m1/play/play.yaml"}]})[0] == 200
    code, _, h = a.get(f"/p/{apid}/play?m=x%0d%0aSet-Cookie:%20a=b"); assert code == 302 and "Set-Cookie" not in h and h["Location"].endswith("/#play")


# ---------------------------------------------------------------- B2
def test_welcome_examples_only_the_users_own(hub):
    a = Client(hub).login("alice"); b = Client(hub).login("bob")
    bpid, broot = new_project(b, "Bob Secret Trip"); make_play(broot)
    users._write_cfg_key(broot, "visibility", "private")
    _, open_root = new_project(b, "Bob Open Trip"); make_play(open_root)
    apid, aroot = new_project(a, "Alice Day")
    code, w, _ = a.get(f"/p/{apid}/api/welcome"); assert code == 200
    assert "Bob" not in json.dumps(w["examples"]) and "Bob Secret" not in json.dumps(w) and all(x["source"] == "bundled" for x in w["examples"])
    assert a.get(f"/p/{apid}/example/0/image")[0] == 404
    make_play(aroot)
    w = a.get(f"/p/{apid}/api/welcome")[1]; assert [x["title"] for x in w["examples"]] == ["Alice Day"]
    code, img, _ = a.get(f"/p/{apid}/example/0/image"); assert code == 200 and img == PNG
    assert b.get(f"/p/{bpid}/api/welcome")[1]["examples"][0]["title"].startswith("Bob")


# ---------------------------------------------------------------- M1
def test_comment_role_cannot_decide(hub):
    a = Client(hub).login("alice"); b = Client(hub).login("bob"); c = Client(hub).login("carol")
    pid, root = new_alice_project(a); make_play(root)
    users.set_member(root, "bob", "comment"); users.set_member(root, "carol", "edit")
    for path, body in (("/api/plan_review", {"m": "m1", "state": "confirmed", "rev": "x"}), ("/api/board_review", {"state": "confirmed"}),
                       ("/api/review", {"id": "p1", "status": "ok"}), ("/api/adaptation_review", {}), ("/api/gameplay_review", {}),
                       ("/api/feature_review", {}), ("/api/thread/answer", {"card_id": "x", "answer": {}}), ("/api/next_round", {"m": "m1"}),
                       ("/api/backup/enable", {"ack": True})):
        code, r, _ = b.post(f"/p/{pid}{path}", body); assert code == 403 and r["need"] in ("edit", "owner"), path
    for k in ("all_ok", "moment", "check", "sound"):
        code, r, _ = b.post(f"/p/{pid}/api/play_feedback", {"m": "m1", "kind": k, "moments": ["x"], "moment": "x", "id": "c1", "status": "ok", "verdict": "ok"})
        assert code == 403, (k, r)
    assert not (yaml.safe_load((root / "5_build/m1/play/user_review.yaml").read_text(encoding="utf-8")).get("moments"))
    code, r, _ = b.post(f"/p/{pid}/api/play_feedback", {"m": "m1", "kind": "time", "t": 3, "note": "this bit is too fast"}); assert code == 200, r
    assert b.post(f"/p/{pid}/api/thread", {"text": "nice"})[0] == 200
    code, r, _ = c.post(f"/p/{pid}/api/play_feedback", {"m": "m1", "kind": "all_ok", "moments": ["x"]}); assert code == 200, r


# ---------------------------------------------------------------- M2
def test_import_uploads_are_per_user_and_exports_owner_editor(hub):
    a = Client(hub).login("alice"); b = Client(hub).login("bob")
    pid, root = new_alice_project(a); bpid, _ = new_project(b, "Bob Lab")
    # export: view-only bob may neither start, poll nor download it; the name is not guessable
    assert b.post(f"/p/{pid}/api/export/start")[0] == 403
    code, r, _ = a.post(f"/p/{pid}/api/export/start"); assert code == 200, r
    assert b.get(f"/p/{pid}/api/export?id={r['job']['id']}")[0] == 403
    code, j = wait_job(a, f"/p/{pid}/api/export?id={r['job']['id']}"); assert code == 200 and j["state"] == "done", j
    assert "path" not in j and len(j["name"]) > len(pid) + 30
    assert b.get(f"/p/{pid}{j['url']}")[0] == 403
    code, data, _ = a.get(f"/p/{pid}{j['url']}"); assert code == 200 and data[:2] == b"PK"
    # alice uploads it for import: a random name, in her own folder; bob can neither see her upload nor import it
    code, u = upload_import(a, pid, data); assert code == 200 and u["done"], u
    assert u["path"] != "backup.zip" and u["path"].endswith(".zip")
    assert b.get(f"/p/{bpid}/api/upload?target=import&id=upl-0123456789")[1]["received"] == 0
    for path in (u["path"], f"../.u-alice/{u['path']}", "../../alice/m2w/imports/.u-alice/" + u["path"]):
        code, r, _ = b.post(f"/p/{bpid}/api/import/start", {"path": path}); assert code == 400, (path, r)
    code, r, _ = a.post(f"/p/{pid}/api/import/start", {"path": u["path"]}); assert code == 200, r
    assert b.get(f"/p/{pid}/api/import?id={r['job']['id']}")[0] in (403, 404)
    code, j = wait_job(a, f"/p/{pid}/api/import?id={r['job']['id']}"); assert j["state"] == "done", j
    assert b.get(f"/p/{pid}/api/import?id={r['job']['id']}")[0] in (403, 404)                   # still hers once done (its result has a "kind")
    assert "path" not in j and users.owner_of(projects.find(j["id"])["path"]) == "alice"
    assert not list((Path.home() / "alice" / "m2w" / "imports").rglob("*.zip"))                  # deleted after the import
    # export zips are short-lived
    from gameanything.ui import hub as hubmod
    zf = next((Path(projects.data_dir(root)) / "exports").glob("*.zip")); old = time.time() - hubmod.EXPORT_TTL - 5; os.utime(zf, (old, old))
    assert a.get(f"/p/{pid}/exports/{zf.name}")[0] == 404 and not zf.exists()


# ---------------------------------------------------------------- M3
def test_login_throttle_per_user_and_ip(hub):
    from gameanything.ui import hub as hubmod
    hubmod.FAILS.clear()
    c = Client(hub)
    for _ in range(hubmod.FAIL_MAX): assert c.post("/api/login", {"name": "nosuchuser", "password": "wrong-pass-1"})[0] == 401
    assert c.post("/api/login", {"name": "nosuchuser", "password": "wrong-pass-1"})[0] == 429
    Client(hub).login("alice"); Client(hub).login("bob")                 # a mistyped name never locks out the others behind this IP
    for _ in range(hubmod.FAIL_MAX): c.post("/api/login", {"name": "alice", "password": "wrong-pass-1"})
    assert Client(hub).post("/api/login", {"name": "alice", "password": "alice-pass-123"})[0] == 429
    Client(hub).login("bob")
    hubmod.FAILS.clear()
    for i in range(hubmod.FAIL_MAX_IP): c.post("/api/login", {"name": f"guess{i}", "password": "wrong-pass-1"})
    assert Client(hub).post("/api/login", {"name": "bob", "password": "bob-pass-4567"})[0] == 429       # the softer per-IP limit
    hubmod.FAILS.clear()


# ---------------------------------------------------------------- M5
def test_origin_https_and_trusted_proxy(hub, monkeypatch):
    host = hub.split("://", 1)[1]; body = {"name": "alice", "password": "alice-pass-123"}
    assert Client(hub).post("/api/login", body, headers={"Origin": f"https://{host}"})[0] == 200
    assert Client(hub).post("/api/login", body, headers={"Origin": f"https://{host}.evil.example"})[0] == 403
    assert Client(hub).post("/api/login", body, headers={"Origin": "null"})[0] == 403
    px = {"Origin": "https://hub.example.com", "X-Forwarded-Host": "hub.example.com", "X-Forwarded-Proto": "https"}
    assert Client(hub).post("/api/login", body, headers=px)[0] == 403                                  # not believed unless configured
    monkeypatch.setenv("GAMEANYTHING_HUB_TRUST_PROXY", "1")
    assert Client(hub).post("/api/login", body, headers=px)[0] == 200
    assert Client(hub).post("/api/login", body, headers={**px, "X-Forwarded-Proto": "http"})[0] == 403
    assert Client(hub).post("/api/login", body, headers={**px, "Origin": "https://evil.example"})[0] == 403


# ---------------------------------------------------------------- m6
def test_headers_paths_and_owner_panels(hub):
    from gameanything.ui.i18n import scrub_paths
    a = Client(hub).login("alice"); b = Client(hub).login("bob")
    pid, root = new_alice_project(a)
    code, _, h = a.get(f"/p/{pid}/"); assert code == 200 and h["X-Content-Type-Options"] == "nosniff" and "frame-ancestors 'self'" in h["Content-Security-Policy"]
    assert Client(hub).get("/login")[2]["X-Content-Type-Options"] == "nosniff"
    for p in ("/api/settings", "/api/backup"):
        assert a.get(f"/p/{pid}{p}")[0] == 200
        code, r, _ = b.get(f"/p/{pid}{p}"); assert code == 403 and r["need"] == "owner", p
    m = scrub_paths(f"[Errno 2] No such file or directory: '{root}/5_build/x/play/user_review.yaml'")
    assert str(root) not in m and "user_review.yaml" in m and "/home/" not in scrub_paths("see /home/bob/x.txt") and scrub_paths("/api/thread") == "/api/thread"
    users.set_member(root, "bob", "edit")
    code, r, _ = b.post(f"/p/{pid}/api/play_feedback", {"m": "m1", "kind": "x"}); assert code == 400 and str(Path.home()) not in r["error"]


# ---------------------------------------------------------------- m7
def test_access_requests_rate_limited_and_answered_once(hub, monkeypatch):
    a = Client(hub).login("alice"); b = Client(hub).login("bob")
    pid, root = new_alice_project(a)
    assert b.post("/api/access/request", {"project": pid, "role": "comment"})[0] == 200
    code, r, _ = b.post("/api/access/request", {"project": pid, "role": "edit"}); assert code == 400 and "分钟" in r["error"]
    assert len([e for e in Thread(root).events() if e["type"] == "card"]) == 1
    cid = [e for e in Thread(root).events() if e["type"] == "card"][-1]["id"]
    assert a.post(f"/p/{pid}/api/thread/answer", {"card_id": cid, "answer": {"decision": "yes"}})[0] == 200
    assert users.members_of(root) == {"bob": "comment"}
    assert a.post(f"/p/{pid}/api/thread/answer", {"card_id": cid, "answer": {"decision": "no"}})[0] == 400
    assert users.members_of(root) == {"bob": "comment"}
    monkeypatch.setattr(users, "REQ_GAP", 0)
    for _ in range(users.REQ_MAX - 1): assert b.post("/api/access/request", {"project": pid, "role": "edit"})[0] == 200
    code, r, _ = b.post("/api/access/request", {"project": pid, "role": "edit"}); assert code == 400


# ---------------------------------------------------------------- m8
def test_private_titles_hidden_from_others(hub):
    a = Client(hub).login("alice"); b = Client(hub).login("bob")
    pid, root = new_alice_project(a); users._write_cfg_key(root, "visibility", "private")
    p = next(x for x in b.get("/api/hub")[1]["projects"] if x["id"] == pid)
    assert p["title"] == "" and p["title_hidden"] and p["role"] is None
    assert next(x for x in a.get("/api/hub")[1]["projects"] if x["id"] == pid)["title"] == "Alice Garden"
    users.set_member(root, "bob", "view")
    assert next(x for x in b.get("/api/hub")[1]["projects"] if x["id"] == pid)["title"] == "Alice Garden"
