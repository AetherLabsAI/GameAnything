"""gameanything hub (ui/hub.py, users.py): users and passwords, sessions, roles, the access-request card, authors on chat events, the read-only
UI, migration of existing projects, and agentd running each project with its OWNER's Claude login (spawn mocked: nothing runs)."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from gameanything import agentd, cli, dispatch, games as registry, projects, users
from gameanything.conversation import Thread

STATIC = Path(users.__file__).parent / "ui" / "static"
PW = {"alice": "alice-pass-123", "bob": "bob-pass-4567", "carol": "carol-pass-89"}


# ---------------------------------------------------------------- helpers
def add(name, admin=False, login=True, **kw):
    home = Path.home()
    u = users.add_user(name, PW[name], admin, name.title(), home / name / "m2w", home / name / ".claude-m2w", **kw)
    if login:
        d = Path(u["claude_config_dir"]); d.mkdir(parents=True, exist_ok=True); (d / ".credentials.json").write_text("{}", encoding="utf-8")
    return u


class Spawner:
    def __init__(self): self.calls = []; self.procs = []

    def __call__(self, cmd, cwd, env, log):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        self.calls.append({"cwd": Path(cwd), "env": env}); self.procs.append(p); return p

    def stop_all(self):
        for p in self.procs:
            if p.poll() is None: p.kill(); p.wait(10)


@pytest.fixture
def spawner():
    s = Spawner(); yield s; s.stop_all()


class Client:
    """One browser: a cookie jar, the page's Origin."""
    def __init__(self, base): self.base = base; self.cookie = None

    def req(self, method, path, data=None, headers=None, origin=True):
        h = {"Content-Type": "application/json", **(headers or {})}
        if origin and method == "POST": h.setdefault("Origin", self.base)
        if self.cookie: h["Cookie"] = self.cookie
        r = urllib.request.Request(self.base + path, json.dumps(data).encode() if data is not None else (b"{}" if method == "POST" else None), h, method=method)
        opener = urllib.request.build_opener(NoRedirect)
        try: resp = opener.open(r, timeout=20); code = resp.status
        except urllib.error.HTTPError as e: resp = e; code = e.code
        body = resp.read(); sc = resp.headers.get("Set-Cookie")
        if sc and sc.startswith("m2w_hub="): v = sc.split(";")[0]; self.cookie = None if v == "m2w_hub=" else v
        try: j = json.loads(body)
        except ValueError: j = body
        return code, j, resp.headers

    def get(self, path, **kw): return self.req("GET", path, **kw)
    def post(self, path, data=None, **kw): return self.req("POST", path, data or {}, **kw)

    def login(self, name):
        code, j, h = self.post("/api/login", {"name": name, "password": PW[name]}); assert code == 200, j
        assert "HttpOnly" in h["Set-Cookie"] and "SameSite=Strict" in h["Set-Cookie"]
        return self


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None


@pytest.fixture
def hub():
    from gameanything.ui.hub import serve
    add("alice", admin=True); add("bob"); add("carol", login=False)
    box, ready = {}, threading.Event()

    def up(srv): box["srv"] = srv; ready.set()
    threading.Thread(target=serve, kwargs={"port": 0, "ready": up}, daemon=True).start()
    assert ready.wait(20), "the hub did not start"
    base = f"http://127.0.0.1:{box['srv'].server_port}"
    yield base
    box["srv"].shutdown(); box["srv"].server_close()


def new_alice_project(c):
    code, r, _ = c.post("/api/hub/new", {"title": "Alice Garden", "kind": "feature", "game": "stardew", "lang": "en"}); assert code == 200 and r["ok"], r
    return r["id"], Path(projects.find(r["id"])["path"])


# ---------------------------------------------------------------- users, passwords, sessions
def test_password_hashes_and_users_file():
    h = users.hash_password("correct horse")
    assert h.startswith("scrypt$") and "correct horse" not in h
    assert users.check_password("correct horse", h) and not users.check_password("wrong horse", h)
    assert h != users.hash_password("correct horse")                                       # salted
    import hashlib
    salt = os.urandom(8); pb = f"pbkdf2_sha256$1000${salt.hex()}${hashlib.pbkdf2_hmac('sha256', b'pw-12345', salt, 1000).hex()}"
    assert users.check_password("pw-12345", pb) and not users.check_password("pw-x", pb) and not users.check_password("x", "garbage")
    add("alice", admin=True)
    raw = users.users_file().read_text(encoding="utf-8")
    assert PW["alice"] not in raw and "password_hash: scrypt$" in raw
    if os.name != "nt": assert (users.users_file().stat().st_mode & 0o777) == 0o600
    with pytest.raises(users.HubError): users.add_user("alice", "another-pass")             # exists
    with pytest.raises(users.HubError): users.add_user("Bad Name", "another-pass")
    with pytest.raises(users.HubError): users.add_user("dave", "short")
    d = users.add_user("dave", "dave-pass-1")                                              # defaults: ~/workspace/<name>/...
    assert d["data_root"] == str(Path.home() / "workspace" / "dave" / "m2w") and d["claude_config_dir"] == str(Path.home() / "workspace" / "dave" / ".claude-m2w")


def test_sessions_sign_expire_logout_and_password_change(monkeypatch):
    add("alice")
    c = users.make_session("alice")
    assert users.session_user(c)["name"] == "alice"
    name, exp, nonce, sig = c.split(":")
    assert users.session_user(f"bob:{exp}:{nonce}:{sig}") is None                          # another name
    assert users.session_user(f"alice:{int(exp) + 1}:{nonce}:{sig}") is None                 # another expiry
    assert users.session_user("nonsense") is None and users.session_user(None) is None
    users.end_session(c); assert users.session_user(c) is None                             # logout
    c2 = users.make_session("alice"); users.set_password("alice", "a-new-password"); assert users.session_user(c2) is None
    c3 = users.make_session("alice"); monkeypatch.setattr(time, "time", lambda: int(exp) + users.SESSION_SECS * 2)
    assert users.session_user(c3) is None                                                  # expired


def test_cli_user_commands(tmp_path, capsys):
    pf = tmp_path / "pw"; pf.write_text("the-password-1\nignored\n", encoding="utf-8")
    assert cli.main(["hub", "user", "add", "erin", "--admin", "--display", "Erin", "--password-file", str(pf)]) == 0
    out = capsys.readouterr().out
    assert "added erin (admin)" in out and "gameanything hub user login erin" in out and "the-password-1" not in out
    assert users.check_password("the-password-1", users.get_user("erin")["password_hash"])
    assert cli.main(["hub", "user", "list"]) == 0
    out = capsys.readouterr().out; assert "erin" in out and "claude NO" in out and "password" not in out.lower()
    pf.write_text("second-password\n", encoding="utf-8")
    assert cli.main(["hub", "user", "passwd", "erin", "--password-file", str(pf)]) == 0
    assert users.check_password("second-password", users.get_user("erin")["password_hash"])
    assert cli.main(["hub", "user", "remove", "erin", "--yes"]) == 0 and users.get_user("erin") is None


# ---------------------------------------------------------------- roles and migration
def test_roles_members_private():
    add("alice"); add("bob")
    e = projects.create("P", "feature", owner="alice"); root = Path(e["path"])
    assert users.owner_of(root) == "alice" and users.role_of("alice", root) == "owner"
    assert users.role_of("bob", root) == "view" and users.role_of(None, root) is None    # logged-in non-members read
    users.set_member(root, "bob", "comment"); assert users.role_of("bob", root) == "comment" and users.members_of(root) == {"bob": "comment"}
    users.set_member(root, "bob", None); assert users.members_of(root) == {}
    f = root / "config" / "project.yaml"; f.write_text(f.read_text(encoding="utf-8") + "visibility: private\n", encoding="utf-8")
    assert users.role_of("bob", root) is None
    with pytest.raises(users.HubError): users.set_member(root, "alice", "edit")
    assert users.at_least("owner", "edit") and users.at_least("edit", "comment") and not users.at_least("view", "comment") and not users.at_least(None, "view")


def test_migrate_gives_existing_projects_an_owner_and_keeps_the_rest(capsys):
    a = projects.create("Old one", "memory"); b = projects.create("Other", "feature", owner="bob")
    fa = Path(a["path"]) / "config" / "project.yaml"
    fa.write_text("# hand-written note\n" + fa.read_text(encoding="utf-8") + "extra:\n  nested: 1\n", encoding="utf-8")
    before = fa.read_text(encoding="utf-8")
    assert cli.main(["hub", "migrate", "--owner", "wenyi", "--dry-run"]) == 0 and fa.read_text(encoding="utf-8") == before
    assert "owner -> wenyi (dry run)" in capsys.readouterr().out
    assert cli.main(["hub", "migrate", "--owner", "wenyi"]) == 0
    out = capsys.readouterr().out
    assert "is not a hub user yet" in out and "kept owner bob" in out
    t = fa.read_text(encoding="utf-8")
    assert t.startswith("# hand-written note\n") and "extra:\n  nested: 1" in t and yaml.safe_load(t)["owner"] == "wenyi"
    assert users.owner_of(b["path"]) == "bob" and projects.load()[0]["id"] == a["id"]          # the project list is untouched
    users.set_member(a["path"], "bob", "edit"); users.set_member(a["path"], "carol", "view")
    assert yaml.safe_load(fa.read_text(encoding="utf-8"))["members"] == {"bob": "edit", "carol": "view"} and "# hand-written note" in fa.read_text(encoding="utf-8")


# ---------------------------------------------------------------- the server: login, read-only, the access request flow
def test_login_and_pages(hub):
    c = Client(hub)
    code, _, h = c.get("/"); assert code == 302 and h["Location"] == "/login"
    code, _, h = c.get("/p/x/"); assert code == 302 and h["Location"] == "/login?next=/p/x/"
    code, page, _ = c.get("/login"); assert code == 200 and b"/hub.js" in page
    assert c.get("/api/hub")[0] == 401 and c.get("/p/x/api/thread")[0] == 401
    code, r, _ = c.post("/api/login", {"name": "alice", "password": "wrong-one"}); assert code == 401 and not r["ok"] and c.cookie is None
    code, r, _ = c.post("/api/login", {"name": "alice", "password": PW["alice"]}, headers={"Origin": "http://evil.example"}); assert code == 403
    c.login("alice")
    code, d, _ = c.get("/api/hub"); assert code == 200 and d["user"]["name"] == "alice" and d["user"]["claude_login"] and d["projects"] == []
    code, _, _ = c.post("/api/logout"); assert code == 200 and c.cookie is None


def test_owner_reader_request_approve_chat(hub):
    a = Client(hub).login("alice"); b = Client(hub).login("bob")
    pid, root = new_alice_project(a)
    assert users.owner_of(root) == "alice" and str(root).startswith(str(Path.home() / "alice" / "m2w" / "projects"))
    # B sees it read-only
    d = b.get("/api/hub")[1]; p = next(x for x in d["projects"] if x["id"] == pid)
    assert p["section"] == "others" and p["role"] == "view" and p["owner"] == "alice" and "members" not in p
    assert b.get(f"/p/{pid}/api/thread")[0] == 200
    sh = b.get(f"/p/{pid}/api/shell")[1]["hub"]
    assert sh["role"] == "view" and sh["can"] == {"chat": False, "cards": False, "edit": False, "owner": False, "admin": False} and sh["owner"] == "alice"
    page = b.get(f"/p/{pid}/")[1]
    assert b'window.M2W_HUB={"base": "/p/' + pid.encode() + b'"' in page and b'"role": "view"' in page
    code, r, _ = b.post(f"/p/{pid}/api/thread", {"text": "hi"}); assert code == 403 and r["need"] == "comment"
    code, r, _ = b.post(f"/p/{pid}/api/thread/answer", {"card_id": "x", "answer": {"decision": "yes"}}); assert code == 403 and r["need"] == "edit"
    assert b.post(f"/p/{pid}/api/next_round", {})[0] == 403 and b.post(f"/p/{pid}/api/projects/game", {"game": "minecraft"})[0] == 403
    assert not Thread(root).events()
    # B asks for edit; the card lands in A's project thread
    code, r, _ = b.post("/api/access/request", {"project": pid, "role": "edit", "note": "let me help"}); assert code == 200 and r["request"]["state"] == "pending"
    assert b.post("/api/access/request", {"project": pid, "role": "view"})[0] == 400                     # already has view
    ev = [e for e in a.get(f"/p/{pid}/api/thread")[1]["events"] if e["type"] == "card"]
    assert len(ev) == 1 and ev[0]["card"]["kind"] == "permission" and ev[0]["card"]["access"] == {"request": r["request"]["id"], "user": "bob", "role": "edit"}
    assert "Claude 登录和额度" in " ".join(ev[0]["card"]["will_send"]) and ev[0]["text"] == "附言：let me help"
    en = [e for e in a.get(f"/p/{pid}/api/thread", headers={"X-Lang": "en"})[1]["events"] if e["type"] == "card"][0]
    assert "YOUR Claude login and quota" in " ".join(en["card"]["will_send"])
    assert Thread(root).unread() == []                                     # the request card does not wake the agent
    cid = ev[0]["id"]
    assert b.post(f"/p/{pid}/api/thread/answer", {"card_id": cid, "answer": {"decision": "yes"}})[0] == 403      # not B's to decide
    assert a.get("/api/hub")[1]["projects"][0]["pending"] == 1
    # A approves through the card
    code, r, _ = a.post(f"/p/{pid}/api/thread/answer", {"card_id": cid, "answer": {"decision": "yes"}}); assert code == 200 and r["ok"]
    assert users.members_of(root) == {"bob": "edit"} and r["event"]["source"] == "hub" and r["event"]["author"] == "alice"
    assert Thread(root).unread() == []                                     # nor does the owner's decision
    p = next(x for x in b.get("/api/hub")[1]["projects"] if x["id"] == pid)
    assert p["section"] == "shared" and p["role"] == "edit" and p["request"]["state"] == "approved"
    # B chats; the event names B
    code, r, _ = b.post(f"/p/{pid}/api/thread", {"text": "hello from bob"}); assert code == 200
    assert r["event"]["author"] == "bob" and r["event"]["author_name"] == "Bob"
    last = Thread(root).events()[-1]; assert last["author"] == "bob" and last["text"] == "hello from bob"
    lines, _ = Thread(root).read(); assert lines == ["【Bob】hello from bob"]                 # the agent sees who wrote it
    code, r, _ = a.post(f"/p/{pid}/api/thread", {"text": "and me"}); assert r["event"]["author"] == "alice"
    assert Thread(root).read()[0] == ["and me"]                                          # the owner's own words as before
    # an editor still may not delete the project or change members
    assert b.post(f"/p/{pid}/api/projects/remove", {"id": pid})[0] == 403
    assert b.post("/api/members", {"project": pid, "user": "carol", "role": "edit"})[0] == 403
    assert b.post(f"/p/{pid}/api/settings", {"max_active_projects": 5})[0] == 403          # global settings: admins
    # A denies a later request: the role it had stays
    Client(hub).login("carol").post("/api/access/request", {"project": pid, "role": "comment"})
    cid2 = [e for e in Thread(root).events() if e["type"] == "card"][-1]["id"]
    assert a.post(f"/p/{pid}/api/thread/answer", {"card_id": cid2, "answer": {"decision": "no"}})[0] == 200
    assert users.members_of(root) == {"bob": "edit"} and users.latest_request(root, "carol")["state"] == "denied"
    # the owner changes members directly, and may delete
    assert a.post("/api/members", {"project": pid, "user": "bob", "role": "comment"})[0] == 200 and users.role_of("bob", root) == "comment"
    assert b.post(f"/p/{pid}/api/thread/answer", {"card_id": cid, "answer": {"decision": "no"}})[0] == 403        # comment: no card decisions
    assert b.post(f"/p/{pid}/api/thread", {"text": "a comment"})[0] == 200
    code, r, _ = a.post(f"/p/{pid}/api/projects/remove", {"id": pid}); assert code == 200 and r["go"] == "/" and not root.exists()


def test_private_project_referer_redirects_and_origin(hub):
    a = Client(hub).login("alice"); b = Client(hub).login("bob")
    pid, root = new_alice_project(a)
    f = root / "config" / "project.yaml"; f.write_text(f.read_text(encoding="utf-8") + "visibility: private\n", encoding="utf-8")
    p = next(x for x in b.get("/api/hub")[1]["projects"] if x["id"] == pid); assert p["role"] is None and p["private"]
    assert b.get(f"/p/{pid}/api/thread")[0] == 403 and b.get(f"/p/{pid}/")[0] == 403
    assert b.post("/api/access/request", {"project": pid, "role": "view"})[0] == 200          # a private project: view is worth asking for
    # a link the page built without the prefix is found through the page it came from
    ref = {"Referer": f"{hub}/p/{pid}/"}
    code, d, _ = a.get("/api/shell", headers=ref); assert code == 200 and d["project_id"] == pid
    code, _, h = a.get("/?embed=1", headers=ref); assert code == 302 and h["Location"] == f"/p/{pid}/?embed=1"
    assert b.get("/api/shell", headers=ref)[0] == 403                                       # the role check is the same
    code, _, h = a.get(f"/p/{pid}/tag"); assert code == 302 and h["Location"] == f"/p/{pid}/#people/tag"      # the UI's own redirects keep the prefix
    assert a.get(f"/p/{pid}")[0] == 302
    assert a.post(f"/p/{pid}/api/thread", {"text": "x"}, headers={"Origin": "http://evil.example"})[0] == 403
    assert a.get("/p/no-such/api/thread")[0] == 404
    # the project list in the shell: only what the user may open; opening another one gives its address
    pb = b.post("/api/hub/new", {"title": "Bob Lab", "kind": "feature"})[1]["id"]
    ids = [x["id"] for x in b.get(f"/p/{pb}/api/shell")[1]["projects"]]; assert pb in ids and pid not in ids
    assert b.post(f"/p/{pb}/api/projects/open", {"id": pb})[1]["go"] == f"/p/{pb}/"


def test_static_hub_pages_and_patch_in_node(hub):
    if not shutil.which("node"): pytest.skip("node is not installed")
    from gameanything.ui.hub import PATCH
    probe = """
const calls = []; globalThis.window = globalThis; window.M2W_HUB = { base: "/p/x", role: "view" }; window.M2W_BASE = "/p/x";
window.fetch = (u, o) => calls.push(u); globalThis.XMLHttpRequest = function () {}; XMLHttpRequest.prototype.open = function (m, u) { calls.push(m + " " + u); };
globalThis.document = { documentElement: { classList: { list: [], add(c) { this.list.push(c); } } } };
""" + PATCH + """
fetch("/api/thread"); fetch("/p/x/api/shell"); fetch("//other/x"); fetch("http://h/x"); new XMLHttpRequest().open("POST", "/api/upload");
window.M2W_BASE = "/p/y"; fetch("/api/upload");
console.log(JSON.stringify({ calls, cls: document.documentElement.classList.list }));"""
    out = json.loads(subprocess.run(["node", "-"], input=probe, capture_output=True, text=True, encoding="utf-8", check=True).stdout)
    assert out["calls"] == ["/p/x/api/thread", "/p/x/api/shell", "//other/x", "http://h/x", "POST /p/x/api/upload", "/p/y/api/upload"]
    assert out["cls"] == ["m2w-hub", "m2w-role-view"]
    for f in ("hub.js", "shell.js", "manage.js", "onboard.js"):
        assert subprocess.run(["node", "--check", str(STATIC / f)]).returncode == 0
    c = Client(hub)
    assert c.get("/hub.js")[0] == 200 and c.get("/i18n.js")[0] == 200 and c.get("/app.css")[0] == 200


# ---------------------------------------------------------------- agentd: the owner's login
def test_agentd_uses_the_owners_config_dir(spawner, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "supervisor-key"); monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "supervisor-token")
    monkeypatch.setenv("OPENROUTER_API_KEY", "supervisor-or")
    envf = Path.home() / "bob.env"; envf.write_text("OPENROUTER_API_KEY=bobs-own\n", encoding="utf-8")
    add("alice"); add("bob", env_file=envf); add("carol", login=False)
    # alice's login is the default ~/.claude (the supervisor's own, like the server owner's /root/.claude)
    us = users.load_users(); us["alice"]["claude_config_dir"] = str(Path.home() / ".claude"); users.save_users(us)
    (Path.home() / ".claude").mkdir(exist_ok=True); (Path.home() / ".claude" / ".credentials.json").write_text("{}", encoding="utf-8")
    pa = projects.create("A", "feature", owner="alice"); pb = projects.create("B", "feature", owner="bob")
    pc = projects.create("C", "feature", owner="carol"); pn = projects.create("Unowned", "feature")
    for e in (pa, pb, pc, pn): Thread(Path(e["path"])).user_text("hello", author="bob")
    d = agentd.Agentd(claude="/bin/false", spawn=spawner, quiet=True); d.tick()
    env = {Path(c["cwd"]).name: c["env"] for c in spawner.calls}
    assert set(env) == {Path(pa["path"]).name, Path(pb["path"]).name}
    ea, eb = env[Path(pa["path"]).name], env[Path(pb["path"]).name]
    assert "CLAUDE_CONFIG_DIR" not in ea and ea["ANTHROPIC_API_KEY"] == "supervisor-key" and ea["GAMEANYTHING_USER"] == "alice" and "GAMEANYTHING_KEYS_FILE" not in ea
    assert eb["CLAUDE_CONFIG_DIR"] == users.get_user("bob")["claude_config_dir"] and eb["GAMEANYTHING_USER"] == "bob"
    assert "ANTHROPIC_API_KEY" not in eb and "CLAUDE_CODE_OAUTH_TOKEN" not in eb and eb["GAMEANYTHING_KEYS_FILE"] == str(envf)
    # paid keys never reach a run (the supervisor's nor the owner's own); paid generation gets the owner's through gen_env (genrun.py)
    assert "OPENROUTER_API_KEY" not in ea and "OPENROUTER_API_KEY" not in eb and ea["GAMEANYTHING_GEN_OFF"] == eb["GAMEANYTHING_GEN_OFF"] == "1"
    assert users.gen_env(pb["path"], {})[0]["OPENROUTER_API_KEY"] == "bobs-own"
    assert set(d.blocked) == {pc["id"], pn["id"]} and "no Claude login" in d.blocked[pc["id"]] and "no owner" in d.blocked[pn["id"]]
    st = "\n".join(agentd.status_lines()); assert "NOT RUN: owner carol has no Claude login yet" in st
    assert not users.default_login_may_run(pb["path"]) and users.default_login_may_run(pa["path"])
    ready = [e["id"] for e, _ in dispatch.scan_unowned()] if not agentd.daemon_state()["alive"] else []
    assert pb["id"] not in ready and pc["id"] not in ready


def test_without_a_hub_agentd_env_is_unchanged(spawner, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/somewhere")
    e = projects.create("Solo", "feature"); Thread(Path(e["path"])).user_text("hi")
    assert not users.enabled() and users.blocked(e["path"]) is None
    agentd.Agentd(claude="/bin/false", spawn=spawner, quiet=True).tick()
    assert spawner.calls[0]["env"]["CLAUDE_CONFIG_DIR"] == "/somewhere" and "GAMEANYTHING_USER" not in spawner.calls[0]["env"]


def test_keys_file_of_a_hub_run(monkeypatch, tmp_path):
    from gameanything import keys
    f = tmp_path / "k.env"; f.write_text("OPENROUTER_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("GAMEANYTHING_KEYS_FILE", str(f)); assert keys.get("OPENROUTER_API_KEY") == "from-file"
    monkeypatch.setenv("GAMEANYTHING_KEYS_FILE", ""); assert not keys.available("OPENROUTER_API_KEY")


# ---------------------------------------------------------------- 「我的 Claude」, passwords, 「用户管理」
OAT = "sk-ant-oat01-" + "A1b2C3d4E5f6G7h8I9j0" * 4 + "-WXyz"
APIK = "sk-ant-api03-" + "Zz9Yy8Xx7Ww6Vv5Uu4Tt" * 4 + "-Q7r8"


def no_secret(*objs):
    for o in objs:
        s = o.decode("utf-8", "replace") if isinstance(o, bytes) else o if isinstance(o, str) else json.dumps(o, ensure_ascii=False)
        assert OAT not in s and APIK not in s and OAT[13:-5] not in s and APIK[13:-5] not in s


def test_claude_token_stored_0600_never_returned_and_counts_for_agentd(hub, spawner):
    c = Client(hub).login("carol")                                               # carol has no Claude login
    d = c.get("/api/hub")[1]; assert not d["user"]["claude_login"] and d["user"]["claude"]["connected"] is False
    assert c.get("/api/me/claude")[1]["claude"] == {"connected": False, "kind": None, "last4": None, "login": False}
    pc = projects.create("C", "feature", owner="carol"); Thread(Path(pc["path"])).user_text("hi")
    assert "no Claude login" in users.blocked(pc["path"])
    # format checks (loose prefixes)
    for kind, tok in (("subscription", APIK), ("subscription", "hello"), ("api_key", OAT), ("api_key", "sk-ant-api03-short"), ("x", OAT)):
        code, r, _ = c.post("/api/me/claude", {"kind": kind, "token": tok}); assert code == 400 and not r["ok"], (kind, tok); no_secret(r)
    assert c.post("/api/me/claude", {"kind": "subscription", "token": OAT}, headers={"Origin": "http://evil.example"})[0] == 403
    assert c.get("/api/me/claude/test")[0] == 404 and c.get("/api/me/claude/disconnect")[0] == 404        # actions are POST only
    # a subscription token, pasted with the line breaks of a terminal copy
    code, r, _ = c.post("/api/me/claude", {"kind": "subscription", "token": OAT[:30] + "\n  " + OAT[30:] + "\n"}); assert code == 200, r
    assert r["claude"] == {"connected": True, "kind": "subscription", "last4": OAT[-4:], "login": False}
    u = users.get_user("carol"); f = Path(u["env_file"])
    assert f == Path.home() / "workspace" / "carol" / ".m2w-env" and (os.name == "nt" or (f.stat().st_mode & 0o777) == 0o600)
    assert f"CLAUDE_CODE_OAUTH_TOKEN={OAT}\n" in f.read_text(encoding="utf-8")
    assert users.blocked(pc["path"]) is None                                     # agentd's login check accepts it
    agentd.Agentd(claude="/bin/false", spawn=spawner, quiet=True).tick()
    env = spawner.calls[-1]["env"]; assert env["CLAUDE_CODE_OAUTH_TOKEN"] == OAT and "ANTHROPIC_API_KEY" not in env and env["GAMEANYTHING_USER"] == "carol"
    # switching to an API key replaces the token; other lines of the file stay
    with open(f, "a", encoding="utf-8") as fh: fh.write("OPENROUTER_API_KEY=carols-own\n")
    code, r, _ = c.post("/api/me/claude", {"kind": "api_key", "token": APIK}); assert code == 200 and r["claude"]["kind"] == "api_key" and r["claude"]["last4"] == APIK[-4:]
    t = f.read_text(encoding="utf-8"); assert "CLAUDE_CODE_OAUTH_TOKEN" not in t and f"ANTHROPIC_API_KEY={APIK}" in t and "OPENROUTER_API_KEY=carols-own" in t
    assert os.name == "nt" or (f.stat().st_mode & 0o777) == 0o600                  # POSIX file modes only
    # never in any answer: the list, the status, the admin list, the shell of a project
    a = Client(hub).login("alice")
    seen = [c.get("/api/hub")[1], c.get("/api/me/claude")[1], a.get("/api/admin/users")[1], r, c.get(f"/p/{pc['id']}/api/shell")[1], c.get("/")[1]]
    no_secret(*seen)
    assert next(x for x in a.get("/api/admin/users")[1]["users"] if x["name"] == "carol")["claude"] is True
    # 断开
    code, r, _ = c.post("/api/me/claude/disconnect"); assert code == 200 and r["claude"]["connected"] is False
    t = f.read_text(encoding="utf-8"); assert "ANTHROPIC_API_KEY" not in t and "OPENROUTER_API_KEY=carols-own" in t
    assert "no Claude login" in users.blocked(pc["path"])


def test_claude_test_connection_env_redaction_and_rate_limit(hub, monkeypatch):
    from gameanything.ui import hub as hubmod
    monkeypatch.setenv("ANTHROPIC_API_KEY", "supervisor-key-xyz"); monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "supervisor-token-xyz")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli"); monkeypatch.setenv("GAMEANYTHING_CLAUDE", "/opt/fake/claude")
    calls = []; reply = {"rc": 0, "out": "OK\n", "err": ""}

    def fake_run(cmd, **kw):
        calls.append({"cmd": cmd, **kw}); return subprocess.CompletedProcess(cmd, reply["rc"], reply["out"], reply["err"])
    monkeypatch.setattr(subprocess, "run", fake_run)
    c = Client(hub).login("carol")
    code, r, _ = c.post("/api/me/claude/test"); assert code == 200 and r["test"]["ok"] is False and not calls     # nothing to test yet
    hubmod.TESTS.clear()
    c.post("/api/me/claude", {"kind": "subscription", "token": OAT})
    code, r, _ = c.post("/api/me/claude/test"); assert code == 200 and r["test"] == {"ok": True, "text": "OK"}
    k = calls[-1]; env = k["env"]
    assert k["cmd"][0] == "/opt/fake/claude" and k["cmd"][1:3] == ["-p", "reply OK"] and "--max-turns" in k["cmd"] and k["timeout"] == 60
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == OAT and "ANTHROPIC_API_KEY" not in env and "CLAUDE_CODE_ENTRYPOINT" not in env
    assert env["CLAUDE_CONFIG_DIR"] == users.get_user("carol")["claude_config_dir"] and Path(env["CLAUDE_CONFIG_DIR"]).is_dir()
    assert "supervisor-key-xyz" not in json.dumps(env) and "supervisor-token-xyz" not in json.dumps(env)
    assert Path(k["cwd"]) != Path.cwd() and not Path(k["cwd"]).exists()            # a scratch folder, gone afterwards
    # rate limit: 15 s apart
    code, r, _ = c.post("/api/me/claude/test"); assert code == 429 and "秒" in r["error"]
    assert c.post("/api/me/claude/test", headers={"X-Lang": "en"})[1]["error"].startswith("Too many tests")
    # an error that quotes the token comes back redacted
    hubmod.TESTS.clear(); reply.update(rc=1, out="", err=f"Invalid API key · token {OAT} rejected (also {APIK[:20]}abcdef)")
    code, r, _ = c.post("/api/me/claude/test"); assert code == 200 and r["test"]["ok"] is False
    assert "Invalid API key" in r["test"]["text"] and "***" in r["test"]["text"]; no_secret(r)
    assert APIK[:20] not in r["test"]["text"]
    # a timeout
    hubmod.TESTS.clear()

    def slow(cmd, **kw): raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    monkeypatch.setattr(subprocess, "run", slow)
    code, r, _ = c.post("/api/me/claude/test"); assert r["test"] == {"ok": False, "text": "60 秒内没有回应"}
    hubmod.TESTS.clear()


OAI = "sk-proj-" + "Kk1Ll2Mm3Nn4Oo5Pp6Qq" * 3 + "Zz"


def test_codex_per_user_key_login_choice_and_no_leaks(hub, spawner, monkeypatch):
    from gameanything.ui import hub as hubmod
    monkeypatch.setenv("ANTHROPIC_API_KEY", "supervisor-key-xyz"); monkeypatch.setenv("OPENAI_API_KEY", "supervisor-openai-xyz")
    monkeypatch.setenv("CODEX_API_KEY", "supervisor-codex-xyz"); monkeypatch.setenv("CODEX_HOME", str(Path.home() / "supervisor-codex"))
    c = Client(hub).login("carol")
    st = c.get("/api/me/claude")[1]["agent"]; assert st["agent"] == "claude-code" and not st["connected"] and st["codex"]["connected"] is False
    for bad in ("hello", OAT, "sk-x"):
        code, r, _ = c.post("/api/me/codex", {"token": bad}); assert code == 400 and not r["ok"]; no_secret(r)
    assert c.post("/api/me/agent", {"agent": "aider"})[0] == 400
    code, r, _ = c.post("/api/me/agent", {"agent": "codex"}); assert code == 200 and r["agent"]["agent"] == "codex" and not r["agent"]["connected"]
    pc = projects.create("C", "feature", owner="carol"); Thread(Path(pc["path"])).user_text("hi")
    assert "no Codex login" in users.blocked(pc["path"], "claude-code"), "her choice wins over the daemon's provider"
    code, r, _ = c.post("/api/me/codex", {"token": OAI}); assert code == 200 and r["agent"]["connected"] and r["agent"]["kind"] == "api_key"
    assert r["agent"]["last4"] == OAI[-4:] and OAI not in json.dumps(r) and OAI not in json.dumps(c.get("/api/hub")[1])
    u = users.get_user("carol"); f = Path(u["env_file"]); assert f"OPENAI_API_KEY={OAI}" in f.read_text(encoding="utf-8")
    assert users.codex_home(u).is_dir() and users.blocked(pc["path"], "claude-code") is None
    # agentd runs carol's project with Codex (the daemon itself is on Claude Code), on her key and CODEX_HOME only
    agentd.Agentd(claude="/bin/false", spawn=spawner, quiet=True).tick()
    env = spawner.calls[-1]["env"]
    assert env["CODEX_HOME"] == str(users.codex_home(u)) and env["CODEX_API_KEY"] == OAI and env["GAMEANYTHING_USER"] == "carol"
    assert "OPENAI_API_KEY" not in env and "ANTHROPIC_API_KEY" not in env and "supervisor" not in json.dumps(env)
    run = json.loads(agentd.run_path(Thread(Path(pc["path"]))).read_text(encoding="utf-8")); assert run["agent_provider"] == "codex"
    # the test button runs codex with her env
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: (calls.append({"cmd": cmd, **kw}), subprocess.CompletedProcess(cmd, 0, "OK\n", ""))[1])
    hubmod.TESTS.clear(); code, r, _ = c.post("/api/me/claude/test"); assert code == 200 and r["test"]["ok"], r
    assert calls[-1]["cmd"][1] == "exec" and "read-only" in calls[-1]["cmd"] and calls[-1]["env"]["CODEX_API_KEY"] == OAI
    assert "supervisor" not in json.dumps(calls[-1]["env"])
    hubmod.TESTS.clear()
    a = Client(hub).login("alice"); row = next(x for x in a.get("/api/admin/users")[1]["users"] if x["name"] == "carol")
    assert row["agent"] == "codex" and row["claude"] is True
    code, r, _ = c.post("/api/me/codex/disconnect"); assert code == 200 and not r["agent"]["connected"] and "OPENAI_API_KEY" not in f.read_text(encoding="utf-8")
    assert "no Codex login" in users.blocked(pc["path"])


def test_models_only_the_owner_changes_them(hub):
    a = Client(hub).login("alice"); pid, root = new_alice_project(a)
    code, st, _ = a.get(f"/p/{pid}/api/models"); assert code == 200 and st["can_edit"] and st["hub"] and [g["id"] for g in st["agents"]] == ["claude-code"]
    b = Client(hub).login("bob")
    code, st, _ = b.get(f"/p/{pid}/api/models"); assert code == 200 and not st["can_edit"] and st["chat"]["agent"] == "claude-code"
    code, r, _ = b.post(f"/p/{pid}/api/models", {"role": "chat", "agent": "claude-code", "model": "opus"}); assert code == 403 and r["need"] == "owner"
    users.set_member(root, "bob", "edit")
    code, r, _ = b.post(f"/p/{pid}/api/models", {"role": "chat", "agent": "claude-code", "model": "opus"}); assert code == 403
    code, r, _ = a.post(f"/p/{pid}/api/models", {"role": "chat", "agent": "claude-code", "model": "opus"}); assert code == 200 and r["models"]["chat"]["model"] == "opus"
    code, r, _ = a.post(f"/p/{pid}/api/models", {"role": "build", "agent": "codex", "model": ""}); assert code == 400 and "Codex" in r["error"]
    assert projects.config_of(root)["chat_model"] == {"agent": "claude-code", "model": "opus"} and "build_model" not in projects.config_of(root)


def test_admin_apis_need_admin(hub):
    b = Client(hub).login("bob")
    assert b.get("/api/admin/users")[0] == 403
    for path, d in (("add", {"name": "dave", "password": "dave-pass-1"}), ("passwd", {"name": "alice"}), ("remove", {"name": "alice"}),
                    ("admin", {"name": "bob", "admin": True})):
        code, r, _ = b.post(f"/api/admin/user/{path}", d); assert code == 403 and not r["ok"], path
    assert users.get_user("dave") is None and not users.get_user("bob").get("admin") and users.get_user("alice")
    assert Client(hub).get("/api/admin/users")[0] == 401
    a = Client(hub).login("alice")
    assert a.post("/api/admin/user/add", {"name": "dave", "password": "dave-pass-1"}, headers={"Origin": "http://evil.example"})[0] == 403
    assert a.get("/api/admin/user/add")[0] == 404                                 # POST only


def test_admin_add_reset_remove_and_last_admin_guard(hub, monkeypatch):
    a = Client(hub).login("alice"); b = Client(hub).login("bob")
    code, r, _ = a.get("/api/admin/users"); assert code == 200 and r["admins"] == 1
    row = {x["name"]: x for x in r["users"]}; assert row["alice"]["me"] and row["bob"]["claude"] is True and row["carol"]["claude"] is False
    assert "password_hash" not in json.dumps(r) and "claude_config_dir" not in json.dumps(r)
    # add with a generated password, shown once
    code, r, _ = a.post("/api/admin/user/add", {"name": "Dave", "display": "戴夫"}); assert code == 200 and r["name"] == "dave" and len(r["password"]) >= 12
    monkeypatch.setitem(PW, "dave", r["password"]); d = Client(hub).login("dave"); assert d.get("/api/hub")[1]["user"]["display"] == "戴夫"
    assert "password" not in a.post("/api/admin/user/add", {"name": "erin", "password": "erin-pass-12"})[1]
    assert a.post("/api/admin/user/add", {"name": "erin", "password": "erin-pass-12"})[0] == 400        # exists
    assert a.post("/api/admin/user/add", {"name": "x y", "password": "erin-pass-12"})[0] == 400
    # bob owns a project shared with dave
    pid = b.post("/api/hub/new", {"title": "Bob Lab", "kind": "feature"})[1]["id"]; root = Path(projects.find(pid)["path"])
    users.set_member(root, "dave", "comment")
    # reset: the old sessions end, the new password works
    code, r, _ = a.post("/api/admin/user/passwd", {"name": "bob"}); assert code == 200 and r["password"]
    assert b.get("/api/hub")[0] == 401
    monkeypatch.setitem(PW, "bob", r["password"]); b = Client(hub).login("bob")
    # remove: the projects stay, the owner is unchanged, the lists say 已移除用户
    assert a.post("/api/admin/user/remove", {"name": "bob"})[0] == 200
    assert users.get_user("bob") is None and root.is_dir() and users.owner_of(root) == "bob" and b.get("/api/hub")[0] == 401
    p = next(x for x in d.get("/api/hub")[1]["projects"] if x["id"] == pid); assert p["owner"] == "bob" and p["owner_removed"] is True
    assert d.get(f"/p/{pid}/api/shell")[1]["hub"]["owner_name"] == "已移除用户"
    assert d.get(f"/p/{pid}/api/shell", headers={"X-Lang": "en"})[1]["hub"]["owner_name"] == "Removed user"
    r = a.get("/api/admin/users")[1]; assert {"name": "bob", "projects": 1} in r["removed"] and "bob" not in [x["name"] for x in r["users"]]
    assert "not a hub user" in users.blocked(root)
    # guards: not yourself, not the last admin
    code, r, _ = a.post("/api/admin/user/remove", {"name": "alice"}); assert code == 400 and "你自己" in r["error"]
    code, r, _ = a.post("/api/admin/user/admin", {"name": "alice", "admin": False}); assert code == 400 and "管理员" in r["error"]
    assert users.get_user("alice")["admin"]
    assert a.post("/api/admin/user/admin", {"name": "dave", "admin": True})[0] == 200 and users.get_user("dave")["admin"]
    assert d.get("/api/admin/users")[0] == 200                                    # dave is an admin now
    assert a.post("/api/admin/user/admin", {"name": "alice", "admin": False})[0] == 200        # another admin stays
    assert d.post("/api/admin/user/remove", {"name": "alice"})[0] == 200
    code, r, _ = d.post("/api/admin/user/admin", {"name": "dave", "admin": False}); assert code == 400 and users.get_user("dave")["admin"]
    with pytest.raises(users.HubError): users.remove_user("dave")                # last admin while others remain (the CLI too)
    assert a.post("/api/admin/user/remove", {"name": "nobody"})[0] in (401, 400)


def test_change_own_password(hub):
    c = Client(hub).login("bob"); other = Client(hub).login("bob")
    code, r, _ = c.post("/api/me/password", {"old": "wrong-one-1", "new": "bob-new-pass-1"}); assert code == 400 and not r["ok"]
    code, r, _ = c.post("/api/me/password", {"old": PW["bob"], "new": "short"}); assert code == 400
    assert c.post("/api/me/password", {"old": PW["bob"], "new": "bob-new-pass-1"}, headers={"Origin": "http://evil.example"})[0] == 403
    code, r, _ = c.post("/api/me/password", {"old": PW["bob"], "new": "bob-new-pass-1"}); assert code == 200 and r["ok"]
    assert c.get("/api/hub")[0] == 200                                            # this browser gets a fresh session
    assert other.get("/api/hub")[0] == 401                                        # the other one is logged out
    assert users.check_password("bob-new-pass-1", users.get_user("bob")["password_hash"])


def test_build_mode_in_the_hub(hub, monkeypatch):
    """「在哪里做」 in the hub: chosen on /api/hub/new, changed under /p/<id>/ by edit or owner only; the hub recommends the sandbox."""
    from gameanything import buildmode
    from gameanything.ui import onboard
    monkeypatch.setattr(onboard, "machine", lambda: {"system": "linux", "backend": "docker-rt", "kit": True, "docker": True, "pool": None,
                                                   "scripts": {"stardew", "minecraft", "cities_skylines", "slay_the_spire", "overcooked2", "valheim", "ksp", "terraria", "civ6"}, "headless": False})
    a = Client(hub).login("alice"); b = Client(hub).login("bob")
    code, r, _ = a.post("/api/hub/new", {"title": "Lab garden", "kind": "memory", "game": "stardew", "mode": "native", "lang": "en"}); assert code == 200
    pid, root = r["id"], Path(projects.find(r["id"])["path"]); assert buildmode.mode_of(root) == "native"
    G = a.get(f"/p/{pid}/api/onboard/games?force=1")[1]; assert G["hub"] and all(g["modes"]["recommended"] == "lab" for g in G["games"] if g["id"] != "sims4" and registry.lab_supported(g["id"]))   # no lab: game.yaml lab.supported false (e.g. nms)
    assert b.post(f"/p/{pid}/api/projects/mode", {"mode": "lab"})[0] == 403 and buildmode.mode_of(root) == "native"     # a reader cannot
    users.set_member(root, "bob", "edit")
    code, r, _ = b.post(f"/p/{pid}/api/projects/mode", {"mode": "lab"}); assert code == 200 and r["build_mode"] == "lab" and buildmode.mode_of(root) == "lab"
    code, r, _ = a.post(f"/p/{pid}/api/projects/mode", {"mode": "native", "id": "someone-else"}); assert code == 200 and buildmode.mode_of(root) == "native"


def test_native_launch_setting_in_the_hub(hub):
    """「什么时候开游戏」 under /p/<id>/: edit or owner only, and only the project the page is bound to."""
    from gameanything.native import quiet
    a = Client(hub).login("alice"); b = Client(hub).login("bob")
    pid, root = new_alice_project(a)
    assert b.post(f"/p/{pid}/api/projects/launch", {"mode": "always"})[0] == 403 and quiet.policy(root)["mode"] == "ask"
    users.set_member(root, "bob", "edit")
    code, r, _ = b.post(f"/p/{pid}/api/projects/launch", {"mode": "window", "window": "22:30-07:00", "id": "someone-else"})
    assert code == 200 and quiet.policy(root) == {"mode": "window", "window": "22:30-07:00", "idle_minutes": 10, "drive": "idle", "front": "never", "hands": "agent", "chosen": True}
    assert a.get(f"/p/{pid}/api/shell")[1]["native_launch"]["mode"] == "window"


# ---------------------------------------------------------------- 「用 ChatGPT 登录 Codex」 in the page (a fake codex: nothing goes out)
FAKE_CODEX = r'''
import os, sys, time, pathlib
home = pathlib.Path(os.environ["CODEX_HOME"]); (home / "pids").open("a", encoding="utf-8").write(f"{os.getpid()} {os.getppid()}\n")
print("Welcome to Codex [v\x1b[90m0.160.0\x1b[0m]\n\x1b[90mOpenAI's command-line coding agent\x1b[0m\n", flush=True)
print("Follow these steps to sign in with ChatGPT using device code authorization:\n\n1. Open this link in your browser and sign in to your account\n"
      "   \x1b[94mhttps://auth.openai.com/codex/device\x1b[0m\n\n2. Enter this one-time code \x1b[90m(expires in 15 minutes)\x1b[0m\n"
      "   \x1b[94mAB1C-DE234\x1b[0m\n", flush=True)
go = home / "go"
while not go.exists(): time.sleep(0.05)
if go.read_text(encoding="utf-8") == "fail": print("Error: login failed refresh_token=rt-SECRET-999", flush=True); sys.exit(1)
(home / "auth.json").write_text('{"tokens": {"access_token": "at-SECRET-123", "refresh_token": "rt-SECRET-999"}}', encoding="utf-8")
print("Successfully logged in (at-SECRET-123)", flush=True)
'''


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    f = tmp_path / "fake_codex.py"; f.write_text(FAKE_CODEX, encoding="utf-8")
    monkeypatch.setattr(users, "codex_login_cmd", lambda binary=None: [sys.executable, str(f), "login", "--device-auth"])
    yield f
    for s in list(users.CODEX_LOGINS.values()):
        if s["proc"].poll() is None: s["proc"].kill(); s["proc"].wait(10)
    users.CODEX_LOGINS.clear()


def wait_login(c, states, secs=20):
    t0 = time.time()
    while time.time() - t0 < secs:
        code, r, _ = c.get("/api/me/codex/login"); assert code == 200, r
        if r["login"]["state"] in states: return r
        time.sleep(0.1)
    raise AssertionError(f"login never reached {states}: {r}")


def test_codex_web_login_device_auth(hub, fake_codex, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "supervisor-openai-xyz")
    c = Client(hub).login("carol"); c.post("/api/me/agent", {"agent": "codex"})
    assert Client(hub).get("/api/me/codex/login")[0] == 401 and Client(hub).post("/api/me/codex/login")[0] == 401
    assert c.post("/api/me/codex/login", headers={"Origin": "http://evil.example"})[0] == 403 and not users.CODEX_LOGINS
    code, r, _ = c.post("/api/me/codex/login"); assert code == 200 and r["login"]["state"] in ("starting", "waiting"), r
    r = wait_login(c, ("waiting",))["login"]
    assert r["url"] == "https://auth.openai.com/codex/device" and r["code"] == "AB1C-DE234" and r["expires"] > time.time() + 800
    assert not r["codex"]["connected"]
    proc = users.CODEX_LOGINS["carol"]["proc"]
    assert c.post("/api/me/codex/login")[1]["login"]["state"] == "waiting" and users.CODEX_LOGINS["carol"]["proc"] is proc    # one at a time
    home = users.codex_home(users.get_user("carol"))
    (line,) = (home / "pids").read_text(encoding="utf-8").splitlines(); pid, ppid = map(int, line.split())
    assert pid == proc.pid or (os.name == "nt" and ppid == proc.pid)      # Windows: a venv's python.exe is a launcher, the script its child
    # her own login only: bob sees none and cannot cancel hers
    b = Client(hub).login("bob")
    assert b.get("/api/me/codex/login")[1]["login"]["state"] == "idle" and b.post("/api/me/codex/login/cancel")[1]["login"]["state"] == "idle"
    assert proc.poll() is None
    (home / "go").write_text("ok", encoding="utf-8")
    r = wait_login(c, ("done", "failed"))
    assert r["login"]["state"] == "done" and "url" not in r["login"] and "code" not in r["login"]
    assert r["agent"]["connected"] and r["agent"]["kind"] == "login" and r["agent"]["codex"]["login"]
    s = json.dumps([r, c.get("/api/me/claude")[1], c.get("/api/hub")[1]]); assert "SECRET" not in s and "supervisor" not in s
    assert "SECRET" not in json.dumps({k: v for k, v in users.CODEX_LOGINS["carol"].items() if k != "proc"})
    assert users.get_user("carol")["codex_home"] == str(home)


def test_codex_web_login_cancel_expire_fail(hub, fake_codex, monkeypatch):
    c = Client(hub).login("bob")
    c.post("/api/me/codex/login"); wait_login(c, ("waiting",)); proc = users.CODEX_LOGINS["bob"]["proc"]
    code, r, _ = c.post("/api/me/codex/login/cancel"); assert code == 200 and r["login"]["state"] == "cancelled" and "code" not in r["login"]
    assert proc.poll() is not None, "cancel ends that exact login process"
    monkeypatch.setattr(users, "CODEX_LOGIN_SECS", 1.5)
    c.post("/api/me/codex/login"); proc2 = users.CODEX_LOGINS["bob"]["proc"]; assert proc2 is not proc
    assert wait_login(c, ("expired", "failed", "done"))["login"]["state"] == "expired" and proc2.wait(10) is not None
    monkeypatch.setattr(users, "CODEX_LOGIN_SECS", 600)
    c.post("/api/me/codex/login"); wait_login(c, ("waiting",))
    (users.codex_home(users.get_user("bob")) / "go").write_text("fail", encoding="utf-8")
    r = wait_login(c, ("failed", "done")); assert r["login"]["state"] == "failed" and not r["agent"]["codex"]["login"] and "SECRET" not in json.dumps(r)
