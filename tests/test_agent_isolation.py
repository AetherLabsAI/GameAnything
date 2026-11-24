"""Agents under their own OS accounts (docs/agent-isolation.md). Every bypass of QA round 3 (qa3-a, qa3-b: H1-H4, the four ★, M rollback)
is tried again here with isolation on. The tests marked `real_user` create throwaway OS accounts (gat-*) and run the attack AS that account
(the system Python, no GameAnything code: the agent's own script); they are skipped when this machine cannot create users (not root, no
useradd, or a file system without POSIX ACLs)."""
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import urllib.request
from pathlib import Path

import pytest
import yaml

from gameanything import decisions, ed25519, gate, isolation, projects
from gameanything.conversation import Thread


def wy(p, d):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")


@pytest.fixture
def on(monkeypatch, tmp_path):
    if os.name == "nt": pytest.skip("agent isolation needs POSIX accounts; on Windows the switch stays off (docs/agent-isolation.md)")
    monkeypatch.setenv("GAMEANYTHING_AGENT_USERS", "on"); monkeypatch.setenv("GAMEANYTHING_AGENT_ROOT", str(tmp_path / "agents"))
    monkeypatch.setenv("GAMEANYTHING_SERVICE_UID", str(os.geteuid()))     # the files this test writes are the service's (root in the lab, not on a Mac)
    yield


def project(title="婚礼"):
    e = projects.create(title, "memory", game="stardew"); return Path(e["path"]), e["id"]


# ================================================================ off: nothing changes
def test_off_by_default(monkeypatch):
    monkeypatch.delenv("GAMEANYTHING_AGENT_USERS", raising=False)
    assert not isolation.enabled() and not isolation.client_mode() and not decisions.enforced()
    root, pid = project()
    T = Thread(root); c = T.card({"kind": "options", "key": "plan", "title": "方案", "items": [{"key": "ok", "title": "就按这个做"}]})
    T.append({"from": "user", "type": "answer", "card_id": c["id"], "answer": {"picked": ["ok"]}, "source": "ui"})   # unsigned: the old rule
    assert T.cards()[c["id"]]["answers"]


# ================================================================ the gate's rules (pure)
RUN = {"root": "/p/wedding", "project": "wedding", "session": "agentd:wedding", "run_id": "r1", "role": "resident", "account": "ga-wenyi"}


@pytest.mark.parametrize("argv", [
    ["chat", "say", "--user", "--text", "好的就这样"],               # her words (H: the agent speaking as her)
    ["chat", "say", "--us", "--text", "x"],                         # argparse abbreviations are no way around it
    ["chat", "claim", "--force"], ["chat", "say", "--session", "her", "--text", "x"], ["chat", "wait", "--all"],
    ["chat", "card", "--file", "/root/wenyi/.env"],                 # a file the service account would read
    ["agentd", "request", "--kind", "other", "--text", "x", "--details", "@/root/.config/gameanything/hub_secret"],
    ["gen", "request", "--inputs", "/etc/shadow"], ["gen", "request", "--image", "../../other/x.png"],
    ["agentd", "run"], ["hub", "user", "add", "x"], ["project", "set-model", "x"], ["lab", "acquire"],
    ["agentd", "notify", "--text", "图画好了"],                       # a resident never writes notes to itself
    ["lab", "env", "up"],                                           # no lease: no lab
])
def test_gate_refuses(argv):
    with pytest.raises(gate.GateError): gate.check_argv(argv, RUN)


def test_gate_uses_the_runs_project_and_sender():
    out = gate.check_argv(["chat", "say", "--project", "/p/OTHER", "--text", "你好"], RUN)
    assert out == ["chat", "say", "--text", "你好", "--project", "/p/wedding"]
    out = gate.check_argv(["chat", "card", "--file=@gate:0", "--project=/p/OTHER"], RUN)
    assert out == ["chat", "card", "--file=@gate:0", "--project", "/p/wedding"]
    b = {**RUN, "role": "builder", "lease": "lab-1:s3"}
    assert gate.check_argv(["agentd", "notify", "--from", "coordinator", "--text", "x"], b)[-2:] == ["--from", "builder"]
    with pytest.raises(gate.GateError): gate.check_argv(["chat", "say", "--text", "x"], b)      # builders never post in her chat
    assert gate.check_argv(["lab", "env", "up", "--json"], b) == ["lab", "env", "up", "--json", "--lease", "lab-1:s3"]


def test_client_sends_files_as_bytes(tmp_path):
    f = tmp_path / "go.yaml"; f.write_bytes(b"kind: go\n")                       # bytes: write_text would give CRLF on Windows
    argv, files = gate._client_files(["chat", "card", "--file", str(f), "--text", "开工"])
    assert argv == ["chat", "card", "--file", "@gate:0", "--text", "开工"] and base64.b64decode(files[0]["data"]) == b"kind: go\n"
    argv, files = gate._client_files(["agentd", "request", "--details", f"@{f}"])
    assert argv == ["agentd", "request", "--details", "@@gate:0"]


# ================================================================ H4: strictness cannot be edited away
def test_h4_config_id_and_strict_cannot_be_dropped(on):
    root, pid = project()
    decisions.start(root, pid); decisions.record(root, "board", "confirmed")
    cfg = root / "config" / "project.yaml"; d = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    d["id"] = "fresh-legacy-id"; d.pop("decisions", None); cfg.write_text(yaml.safe_dump(d), encoding="utf-8")   # the agent's edit
    assert decisions.project_id(root) == pid and decisions.strict(root)                    # the server's id and its strict list
    shutil.move(str(decisions.ledger(root)), str(root / "ledger.bak"))                  # (as root here: as the agent this fails, below)
    assert decisions.tampered(root) and not decisions.confirmed(root, "board")


# ================================================================ M: the ledger cannot be rolled back
def test_rollback_is_seen(on):
    root, pid = project(); decisions.start(root, pid)
    decisions.record(root, "board", "confirmed"); decisions.record(root, "board", "draft")
    f = decisions.ledger(root); lines = f.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[1])["prev"] == decisions._h(lines[0])                      # each line names the one before it
    f.write_text(lines[0] + "\n", encoding="utf-8")                                     # the agent deletes her 'draft'
    assert decisions.entries(root) == [] and "改回去" in decisions.tampered(root) and not decisions.confirmed(root, "board")


def test_lines_the_server_did_not_write_never_count(on):
    root, pid = project(); decisions.start(root, pid)
    decisions.record(root, "board", "draft"); good = decisions.ledger(root).read_text(encoding="utf-8").splitlines()
    decisions.record(root, "board", "confirmed"); conf = decisions.ledger(root).read_text(encoding="utf-8").splitlines()[-1]
    decisions.record(root, "board", "draft")
    with open(decisions.ledger(root), "a", encoding="utf-8") as fh: fh.write(conf + "\n")   # her old 'confirmed' replayed at the end
    assert decisions.last(root, "board")["state"] == "draft"


# ================================================================ H3: card answers need the page server's signature
def _plan_card(T):
    return T.card({"kind": "options", "key": "plan", "title": "方案", "items": [{"key": "ok", "title": "就按这个做"}, {"key": "no", "title": "再想想"}]})


def test_h3_unsigned_answer_does_not_count(on):
    root, pid = project(); decisions.start(root, pid)
    T = Thread(root); c = _plan_card(T)
    with open(T.log, "a", encoding="utf-8") as fh:                                       # qa3-b H3: appended by hand
        fh.write(json.dumps({"id": "e_x", "at": "2026-10-30T09:00:00", "from": "user", "type": "answer", "card_id": c["id"],
                             "answer": {"picked": ["ok"]}, "source": "ui"}) + "\n")
    assert not T.cards()[c["id"]]["answers"]
    from gameanything import flow
    assert not flow.plan_approvals({"cards": [e for e in T.events() if e.get("type") == "card"],
                                    "answers": {e["card_id"]: e for e in T.events() if e.get("type") == "answer"}})
    ev = T.answer(c["id"], {"picked": ["ok"]})                                         # her click, signed by the page server
    assert ev.get("sig") and T.cards()[c["id"]]["answers"][0]["id"] == ev["id"]
    forged = dict(ev, answer={"picked": ["no"]})                                        # a signed answer, changed
    with open(T.log, "a", encoding="utf-8") as fh: fh.write(json.dumps(forged) + "\n")
    assert [a["answer"] for a in T.cards()[c["id"]]["answers"]] == [{"picked": ["ok"]}]


def test_h3_answers_from_before_signing_still_count(on):
    root, pid = project(); T = Thread(root); c = _plan_card(T)
    T.append({"from": "user", "type": "answer", "card_id": c["id"], "answer": {"picked": ["ok"]}, "source": "ui", "kid": None})
    lines = T.log.read_text(encoding="utf-8").splitlines(); old = json.loads(lines[-1]); old.pop("kid", None); old.pop("sig", None)
    T.log.write_text("\n".join(lines[:-1] + [json.dumps(old)]) + "\n", encoding="utf-8")
    decisions.start(root, pid); decisions._set_head(pid, answers_from=len(lines))      # sealed after her old answer
    assert T.cards()[c["id"]]["answers"]


# ================================================================ ★2: a key the agent made is not the server's
def test_star2_own_keypair_does_not_sign(on):
    root, pid = project(); decisions.start(root, pid)
    s, p = ed25519.keypair(); kid = decisions._kid(p)
    d = {"what": "board", "state": "confirmed", "at": "2026-10-30T10:00:00", "via": "ui"}
    raw = decisions._raw(root); d.update(prev=decisions._h(raw[-1]) if raw else "", n=len(raw), kid=kid)
    d["sig"] = ed25519.sign(s, decisions._msg(pid, d)).hex()
    with open(decisions.ledger(root), "a", encoding="utf-8") as fh: fh.write(json.dumps(d) + "\n")
    assert not decisions.confirmed(root, "board")              # beyond the server's head (and as the agent: the keyring is not writable)


# ================================================================ the server never follows an agent's link
def test_guard_refuses_a_link_out_of_the_project(on, tmp_path):
    root, pid = project()
    secret = tmp_path / "server-secret"; secret.write_text("s3cret", encoding="utf-8")
    (root / "feedback").mkdir(exist_ok=True)
    os.symlink(secret, root / "feedback" / "board_review.yaml")
    os.symlink("../3_remember", root / "feedback" / "inside")                          # a link inside the project is fine
    os.chmod(root, 0o3770)                                                            # (prepared)
    isolation.invalidate(); assert isolation.install_guard()
    try:
        with pytest.raises(PermissionError): (root / "feedback" / "board_review.yaml").write_text("state: confirmed\n", encoding="utf-8")
        with pytest.raises(PermissionError): (root / "feedback" / "board_review.yaml").read_text(encoding="utf-8")
        (root / "feedback" / "x").write_text("state: draft\n", encoding="utf-8")
        os.replace(root / "feedback" / "x", root / "feedback" / "board_review.yaml")      # replaces the link itself, never its target
        assert not (root / "feedback" / "board_review.yaml").is_symlink()
        (root / "feedback" / "inside" / "ok.yaml").write_text("a: 1\n", encoding="utf-8")
        assert (root / "3_remember" / "ok.yaml").read_text(encoding="utf-8") == "a: 1\n"
        os.symlink(str(tmp_path), root / "evil_dir")
        with pytest.raises(PermissionError): (root / "evil_dir" / "server-secret").write_text("x", encoding="utf-8")
    finally: isolation.uninstall_guard()
    assert secret.read_text(encoding="utf-8") == "s3cret"


def test_layout_and_trust(on, tmp_path, monkeypatch):
    root, pid = project()
    monkeypatch.setattr(isolation, "ids", lambda a: (os.getuid() + 0, os.getgid()) if a else None)
    assert isolation.layout_problems(root, "ga-x")                                   # the old one-user layout
    assert isolation.trusted(root / "conversation" / "thread.jsonl")                 # (root-owned here)


# ================================================================ the real thing: attacks run AS another OS account
def _can_make_users():
    if os.name == "nt" or not hasattr(os, "geteuid") or os.geteuid() != 0: return "needs root"
    if not shutil.which("useradd") or not shutil.which("groupadd"): return "no useradd / groupadd"
    if not Path("/usr/bin/python3").exists(): return "no system python3 for the agent's script"
    return ""


WHY = _can_make_users()
real_user = pytest.mark.skipif(bool(WHY), reason=f"cannot create test OS users here: {WHY}")
SYSPY = "/usr/bin/python3"


@pytest.fixture
def accounts(monkeypatch, tmp_path):
    """gat-agents + gat-alice + gat-bob (deleted after); a base folder every account can enter (/tmp/ga-iso-*)."""
    tag = f"{os.getpid() % 10000}"
    G, A, B = f"gat{tag}-agents", f"gat{tag}-alice", f"gat{tag}-bob"
    made = []
    try:
        subprocess.run(["groupadd", G], check=True); made.append(("g", G))
        for u in (A, B):
            subprocess.run(["useradd", "-M", "-d", "/nonexistent", "-s", "/usr/sbin/nologin", "-G", G, u], check=True); made.append(("u", u))
        base = Path(tempfile.mkdtemp(prefix="ga-iso-", dir="/tmp")); os.chmod(base, 0o711)
        try:
            os.setxattr(base, isolation.ACL_ACCESS, isolation._acl_bytes({**isolation._acl_from_mode(0o711)}), follow_symlinks=False)
            isolation.acl_set(base, {(isolation.GROUP_E, isolation.group_gid(G)): 1})
        except OSError:
            pytest.skip("this file system keeps no POSIX ACLs")
        monkeypatch.setattr(isolation, "PREFIX", f"gat{tag}-"); monkeypatch.setattr(isolation, "GROUP", G)
        monkeypatch.setenv("GAMEANYTHING_AGENT_USERS", "on"); monkeypatch.setenv("GAMEANYTHING_AGENT_ROOT", str(base / "agents"))
        monkeypatch.setenv("GAMEANYTHING_DATA", str(base / "data")); (base / "data").mkdir(); os.chmod(base / "data", 0o755)
        server = base / "server"; server.mkdir(mode=0o700)                             # hub_secret, users.yaml, the private keys folder
        (server / "hub_secret").write_text("ab" * 32, encoding="utf-8"); (server / "users.yaml").write_text("wenyi: {}\n", encoding="utf-8")
        yield {"base": base, "alice": A, "bob": B, "group": G, "server": server}
    finally:
        for kind, n in reversed(made):
            subprocess.run(["userdel" if kind == "u" else "groupdel", n], check=False, stderr=subprocess.DEVNULL)
        try: shutil.rmtree(base, ignore_errors=True)
        except NameError: pass


def as_agent(account, script, env=None, timeout=60):
    """Run the agent's own Python script as `account` (the system Python in isolated mode: none of GameAnything's code)."""
    import pwd
    pw = pwd.getpwnam(account)
    p = subprocess.run([SYSPY, "-I", "-c", textwrap.dedent(script)], user=pw.pw_uid, group=pw.pw_gid,
                       extra_groups=os.getgrouplist(account, pw.pw_gid), env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", **(env or {})},
                       capture_output=True, text=True, timeout=timeout, cwd="/", encoding="utf-8")
    return p


ATTACKS = r'''
import json, os, sys, socket, struct, urllib.request
R = {}
P = os.environ["P"]
def t(name, fn):
    try: fn(); R[name] = "OK"
    except Exception as e: R[name] = type(e).__name__
t("append_answer_to_thread", lambda: open(P + "/conversation/thread.jsonl", "a").write(json.dumps({"from": "user", "type": "answer", "card_id": os.environ["CARD"], "answer": {"picked": ["ok"]}}) + "\n"))
t("write_ledger", lambda: open(P + "/conversation/.user_decisions.jsonl", "a").write('{"what":"board","state":"confirmed"}\n'))
t("truncate_ledger", lambda: open(P + "/conversation/.user_decisions.jsonl", "w").write(""))
t("move_conversation", lambda: os.rename(P + "/conversation", P + "/conversation.old"))
t("move_ledger", lambda: os.rename(P + "/conversation/.user_decisions.jsonl", P + "/ledger.bak"))
t("new_file_in_conversation", lambda: open(P + "/conversation/.agent_owner.json", "w").write("{}"))
t("append_keyring", lambda: open(os.environ["PUB"] + "/decision-keys.txt", "a").write("x y\n"))
t("edit_heads", lambda: open(os.environ["PUB"] + "/ledger-heads.json", "w").write("{}"))
t("read_hub_secret", lambda: open(os.environ["SERVER"] + "/hub_secret").read())
t("read_users_yaml", lambda: open(os.environ["SERVER"] + "/users.yaml").read())
t("read_other_users_project", lambda: os.listdir(os.environ["OTHER"]))
t("edit_own_config", lambda: open(P + "/config/project.yaml", "a").write("decisions: legacy\nid: other-id\n"))
t("write_own_design", lambda: open(P + "/4_design/notes.md", "w").write("mine"))
t("plant_link", lambda: os.symlink(os.environ["SERVER"] + "/hub_secret", P + "/4_design/board_review.yaml"))
def http():
    u = os.environ.get("UI")
    if not u: return
    r = urllib.request.Request(u + "/app", headers={"Sec-Fetch-Dest": "document", "Sec-Fetch-Site": "none"})
    with urllib.request.urlopen(r, timeout=10) as x:
        R["cookie_given"] = "ga_decide" in (x.headers.get("Set-Cookie") or "")
    body = json.dumps({"rev": os.environ["REV"], "state": "confirmed", "items": {}}).encode()
    r = urllib.request.Request(u + "/api/board_review", body, {"Content-Type": "application/json", "Origin": u, "Cookie": os.environ["COOKIE"]},
                               method="POST")                                          # even with her real decision cookie (stolen)
    try:
        with urllib.request.urlopen(r, timeout=10) as x: R["post_board"] = x.status
    except urllib.error.HTTPError as e: R["post_board"] = e.code
    with urllib.request.urlopen(u + "/api/shell", timeout=10) as x: R["get_ok"] = x.status
t("http", http)
def gate_call(argv, stdin=None):
    s = socket.socket(socket.AF_UNIX); s.connect(os.environ["GATE"])
    b = json.dumps({"argv": argv, "stdin": stdin, "files": []}).encode(); s.sendall(struct.pack(">I", len(b)) + b)
    n = struct.unpack(">I", s.recv(4))[0]; buf = b""
    while len(buf) < n: buf += s.recv(n - len(buf))
    return json.loads(buf)
if os.environ.get("GATE"):
    R["gate_user_words"] = gate_call(["chat", "say", "--user", "--text", "就按这个做"]).get("error") or "ACCEPTED"
    R["gate_answer_file"] = gate_call(["chat", "card", "--file", os.environ["SERVER"] + "/hub_secret"]).get("error") or "ACCEPTED"
    r = gate_call(["chat", "say", "--project", "/elsewhere", "--text", "你好，我看完了"])
    R["gate_say"] = r.get("error") or r.get("code")
print(json.dumps(R))
'''


@real_user
def test_real_account_every_bypass_fails(accounts, tmp_path, monkeypatch):
    from gameanything.ui import serve, screens
    A, base = accounts["alice"], accounts["base"]
    pub = isolation.public_dir(); pub.mkdir(parents=True); os.chmod(pub, 0o755)
    monkeypatch.setenv("GAMEANYTHING_DECISION_KEYS", str(accounts["server"] / "keys"))
    decisions._published.clear(); decisions._publish()                                # keyring + its public copy
    # her project, then another user's (bob's): both under a root-owned folder the accounts can enter
    pdir = base / "data" / "projects"; pdir.mkdir(parents=True); os.chmod(pdir, 0o755)
    monkeypatch.setenv("GAMEANYTHING_DATA", str(base / "data"))
    root, pid = project("婚礼"); other, _ = project("别人的")
    assert root.parent == pdir, root
    (root / "4_design").mkdir(exist_ok=True)
    decisions.start(root, pid); decisions.record(root, "board", "draft")
    T = Thread(root); c = _plan_card(T)
    isolation.prepare_project(root, A); isolation.prepare_project(other, accounts["bob"])
    decisions.write_server_id(root)
    assert isolation.layout_problems(root, A) == []
    # the page server, and the gate with a "run" that is the attacker's process
    box, ready = {}, threading.Event()
    th = threading.Thread(target=serve, args=(root,), kwargs={"port": 18951, "ready": lambda s: (box.setdefault("srv", s), ready.set())}, daemon=True)
    th.start(); assert ready.wait(20)
    url = f"http://127.0.0.1:{box['srv'].server_port}"
    with urllib.request.urlopen(urllib.request.Request(url + "/app", headers={"Sec-Fetch-Dest": "document", "Sec-Fetch-Site": "none"}), timeout=10) as x:
        cookie = (x.headers.get("Set-Cookie") or "").split(";")[0]
    assert cookie.startswith("ga_decide_")                                              # her browser (not an agent account) gets it
    runs = {}
    G = gate.Gate(lambda pids: runs.get("run") if runs.get("pid") in pids else None, log=lambda m: None, path=base / "agents" / "gate" / "agent.sock").start()
    try:
        env = {"P": str(root), "CARD": c["id"], "PUB": str(pub), "SERVER": str(accounts["server"]), "OTHER": str(other), "UI": url,
               "REV": "", "GATE": str(G.path), "COOKIE": cookie}
        import pwd
        pw = pwd.getpwnam(A)
        proc = subprocess.Popen([SYSPY, "-I", "-c", textwrap.dedent(ATTACKS)], user=pw.pw_uid, group=pw.pw_gid,
                                extra_groups=os.getgrouplist(A, pw.pw_gid), env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", **env},
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd="/", encoding="utf-8")
        runs.update(pid=proc.pid, run={"root": str(root), "project": pid, "session": f"agentd:{pid}", "run_id": "run1", "role": "resident", "account": A})
        out, err = proc.communicate(timeout=120)
        R = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
        assert R, err
    finally:
        G.close(); box["srv"].shutdown(); box["srv"].server_close()
    denied = ("PermissionError",)
    for k in ("append_answer_to_thread", "write_ledger", "truncate_ledger", "move_conversation", "move_ledger", "new_file_in_conversation",
              "append_keyring", "edit_heads", "read_hub_secret", "read_users_yaml", "read_other_users_project"):
        assert R[k] in denied, (k, R[k], R)
    assert R["edit_own_config"] == "OK" and R["write_own_design"] == "OK" and R["plant_link"] == "OK"     # its own working files
    assert R["cookie_given"] is False and R["post_board"] == 403 and R["get_ok"] == 200, R             # H1: pages yes, decisions no
    assert "--user" in R["gate_user_words"] and "--file" in R["gate_answer_file"], R
    assert R["gate_say"] == 0, R
    ev = [e for e in Thread(root).events() if e.get("type") == "text"][-1]
    assert ev["from"] == "agent" and ev["via"] == "gate" and ev["run"] == "run1" and ev["session"] == f"agentd:{pid}"
    # what the edits did NOT change: still strict under the server's id, no answer of hers, no confirmation
    assert decisions.project_id(root) == pid and decisions.strict(root) and not decisions.confirmed(root, "board")
    assert not Thread(root).cards()[c["id"]]["answers"]
    # the planted link: the service account refuses to follow it
    isolation.invalidate(); isolation.install_guard()
    try:
        with pytest.raises(PermissionError): (root / "4_design" / "board_review.yaml").write_text("x", encoding="utf-8")
    finally: isolation.uninstall_guard()
    assert (accounts["server"] / "hub_secret").read_text(encoding="utf-8") == "ab" * 32


@real_user
def test_real_account_not_inside_a_run_is_refused(accounts):
    G = gate.Gate(lambda pids: None, log=lambda m: None, path=accounts["base"] / "agents" / "gate" / "agent.sock").start()
    try:
        r = as_agent(accounts["alice"], r'''
            import json, os, socket, struct
            s = socket.socket(socket.AF_UNIX); s.connect(os.environ["GATE"])
            b = json.dumps({"argv": ["chat", "say", "--text", "x"]}).encode(); s.sendall(struct.pack(">I", len(b)) + b)
            n = struct.unpack(">I", s.recv(4))[0]; print(s.recv(n).decode())''', env={"GATE": str(G.path)})
    finally: G.close()
    assert "not inside a live agentd run" in r.stdout, (r.stdout, r.stderr)
