"""QA 2026-10-30 (three retests): an agent running shell commands as her OS user could still make her confirmations. Each bypass is
reproduced here as the agent did it: (1) delete conversation/.user_decisions.jsonl, (2) sign a ledger line from its own Python process,
(3) POST a review to the page server without Origin / without the page's decision cookie. Plus: the signature covers the project id (a
moved project keeps her confirmations), no 「确认了…」 in her name after an agent's 'confirmed', and her chat says an agent's
confirmation does not count."""
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from gameanything import agent_providers, decisions, ed25519, flow, projects
from gameanything.conversation import Thread
from gameanything.ui import screens

REPO = Path(__file__).resolve().parents[1]


def wy(root, rel, d):
    p = Path(root) / rel; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")


class Proj:
    def __init__(self, root): self.root = Path(root); self.lock = threading.Lock(); self.told = []
    def tell(self, text, en=None, ctx=None, auto=False): self.told.append((text, en, auto))
    def feedback_ui(self, e): pass


def gameplay_project(title="夜班护士"):
    e = projects.create(title, "gameplay", game="slay_the_spire"); root = Path(e["path"])
    wy(root, "3_remember/gameplay.yaml", {"title": "夜班", "mapping": [{"id": "m1", "experience": "熬夜", "mechanic": "能量", "kind": "resource"}],
                                         "core": {"fantasy": "护士", "character": {"name": "小林", "hp": 70}}})
    return root


def ud(root):
    return next(x for x in flow.check(root)["criteria"] if x["id"] == "user_decisions")


def test_ed25519_matches_rfc8032():
    sk = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    assert ed25519.public_key(sk).hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    sig = ed25519.sign(sk, b"")
    assert sig.hex().startswith("e5564300c360ac729086e2cc806e828a") and ed25519.verify(ed25519.public_key(sk), b"", sig)
    assert not ed25519.verify(ed25519.public_key(sk), b"x", sig) and not ed25519.verify(ed25519.public_key(sk), b"", sig[:-1] + b"\0")


# ---------------------------------------------------------------- bypass 1: delete the ledger
def test_deleting_the_ledger_does_not_make_the_project_legacy():
    root = gameplay_project()
    wy(root, "feedback/gameplay_review.yaml", {"mapping": {"state": "confirmed"}})          # the agent's own 'confirmed'
    decisions.ledger(root).unlink()                                                          # ... and the ledger gone (qa2 H1)
    assert decisions.strict(root), "still under the ledger rule"
    assert not flow.facts(root)["s"]["mapping_ok"], "a strict project without its ledger has no confirmations"
    c = ud(root); assert not c["ok"] and "被动过" in c["why"]
    decisions.ledger(root).write_text("", encoding="utf-8")                                   # emptied instead of deleted
    assert not flow.facts(root)["s"]["mapping_ok"] and not ud(root)["ok"]


def test_a_project_with_a_ledger_from_before_stays_strict_after_the_ledger_is_deleted():
    root = gameplay_project()
    f = root / "config" / "project.yaml"; cfg = yaml.safe_load(f.read_text(encoding="utf-8"))
    cfg.pop("decisions", None); f.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")   # a ledger project from 2026-10-29
    (decisions.keys_dir() / decisions.STRICT_LIST).unlink()
    assert decisions.strict(root)                       # seen once with its ledger: on the server's strict list from now on
    decisions.ledger(root).unlink(); wy(root, "feedback/gameplay_review.yaml", {"mapping": {"state": "confirmed"}})
    assert decisions.strict(root) and not flow.facts(root)["s"]["mapping_ok"]


def test_legacy_projects_without_a_ledger_keep_the_file_rule():
    root = gameplay_project(); decisions.ledger(root).unlink()
    f = root / "config" / "project.yaml"; cfg = yaml.safe_load(f.read_text(encoding="utf-8")); cfg.pop("decisions", None)
    f.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8"); (decisions.keys_dir() / decisions.STRICT_LIST).unlink()
    wy(root, "feedback/gameplay_review.yaml", {"mapping": {"state": "confirmed"}})
    assert not decisions.strict(root) and flow.facts(root)["s"]["mapping_ok"] and ud(root)["ok"]


# ---------------------------------------------------------------- bypass 2: sign from the agent's own process
AGENT_PY = """
import sys
from pathlib import Path
from gameanything import decisions
root = Path(sys.argv[1])
try:
    decisions.record(root, "gameplay:mapping", "confirmed", via="ui gameplay mapping"); print("SIGNED")
except decisions.NotTheServer:
    print("REFUSED")
"""


def agent_run(code, *args):
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    r = subprocess.run([sys.executable, "-c", code, *map(str, args)], env=env, capture_output=True, text=True, timeout=120)
    return r.stdout.strip() + r.stderr.strip()


def test_an_agent_process_cannot_sign_her_decision():
    root = gameplay_project()
    wy(root, "feedback/gameplay_review.yaml", {"mapping": {"state": "confirmed"}})
    out = agent_run(AGENT_PY, root)
    assert "REFUSED" in out, out
    assert not decisions.confirmed(root, "gameplay:mapping") and not ud(root)["ok"]


def test_no_secret_on_disk_signs_a_line_that_counts(tmp_path):
    """Whatever an agent can read (the data folder, the server folder) does not let it sign: the old HMAC key file and every file of the
    server folder, used as an HMAC key or as an Ed25519 secret, give lines that do not count."""
    root = gameplay_project()
    wy(root, "feedback/gameplay_review.yaml", {"mapping": {"state": "confirmed"}})
    files = [p for d in (projects.data_dir(), decisions.keys_dir(), projects.home()) if d.is_dir() for p in d.rglob("*") if p.is_file()]
    assert files and not (projects.data_dir() / "decisions.key").exists()
    pid = decisions.project_id(root); kr = decisions._keyring()
    for p in files:
        raw = p.read_bytes()
        for key in (raw, raw.strip()):
            d = {"what": "gameplay:mapping", "state": "confirmed", "at": "2026-10-30T09:00:00", "via": "ui gameplay mapping"}
            m = json.dumps([root.name, d["what"], d["state"], d["at"], d["via"]], ensure_ascii=False).encode()
            lines = [{**d, "sig": hmac.new(key, m, hashlib.sha256).hexdigest()[:32]}]
            if len(key) >= 32:
                sk = key[:32]
                for kid in kr: lines.append({**d, "kid": kid, "sig": ed25519.sign(sk, decisions._msg(pid, d)).hex()})
            with open(decisions.ledger(root), "a", encoding="utf-8") as fh:
                for x in lines: fh.write(json.dumps(x) + "\n")
    assert not decisions.confirmed(root, "gameplay:mapping")


def test_an_old_hmac_key_made_by_the_agent_does_not_count():
    """Lines signed the old way count only with the key that was there when the new code first ran, and only until a new server
    migrated them; a decisions.key the agent writes later is not that key."""
    root = gameplay_project()
    key = os.urandom(32); (projects.data_dir() / "decisions.key").write_text(key.hex(), encoding="utf-8")
    d = {"what": "gameplay:mapping", "state": "confirmed", "at": "2026-10-30T09:00:00", "via": "ui"}
    m = json.dumps([root.name, d["what"], d["state"], d["at"], d["via"]], ensure_ascii=False).encode()
    with open(decisions.ledger(root), "a", encoding="utf-8") as fh: fh.write(json.dumps({**d, "sig": hmac.new(key, m, hashlib.sha256).hexdigest()[:32]}) + "\n")
    wy(root, "feedback/gameplay_review.yaml", {"mapping": {"state": "confirmed"}})
    assert not decisions.confirmed(root, "gameplay:mapping")


def test_old_lines_signed_with_the_old_key_are_migrated_by_the_server(monkeypatch):
    root = gameplay_project()
    signer = decisions._signer; decisions._signer = None              # before the new server started: an old one wrote the ledger
    key = os.urandom(32); kf = projects.data_dir() / "decisions.key"; kf.write_text(key.hex(), encoding="utf-8")
    d = {"what": "gameplay:mapping", "state": "confirmed", "at": "2026-10-29T09:00:00", "via": "ui gameplay mapping"}
    m = json.dumps([root.name, d["what"], d["state"], d["at"], d["via"]], ensure_ascii=False).encode()
    decisions.ledger(root).write_text(json.dumps({**d, "sig": hmac.new(key, m, hashlib.sha256).hexdigest()[:32]}) + "\n", encoding="utf-8")
    wy(root, "feedback/gameplay_review.yaml", {"mapping": {"state": "confirmed"}})
    for f in (decisions.keys_dir() / decisions.LEGACY_PIN, decisions.keys_dir() / decisions.LEGACY_CLOSED): f.unlink(missing_ok=True)
    assert decisions.confirmed(root, "gameplay:mapping"), "the deploy keeps her real confirmations until the server restarts"
    decisions._signer = signer; decisions.serve_signing()            # the new server starts: signs them again, removes the old key
    assert not kf.exists() and decisions.confirmed(root, "gameplay:mapping")
    assert all(x.get("kid") for x in map(json.loads, decisions.ledger(root).read_text(encoding="utf-8").splitlines()))
    kf.write_text(key.hex(), encoding="utf-8")                        # the agent puts the old key back and writes a new old-style line
    d2 = {**d, "what": "gameplay:content", "at": "2026-10-30T10:00:00"}
    m2 = json.dumps([root.name, d2["what"], d2["state"], d2["at"], d2["via"]], ensure_ascii=False).encode()
    with open(decisions.ledger(root), "a", encoding="utf-8") as fh: fh.write(json.dumps({**d2, "sig": hmac.new(key, m2, hashlib.sha256).hexdigest()[:32]}) + "\n")
    assert not decisions.confirmed(root, "gameplay:content")


def test_moving_an_old_line_down_does_not_bring_back_a_confirmation_she_withdrew(monkeypatch):
    import datetime as dt
    root = gameplay_project(); t = iter(["2026-10-30T09:00:00", "2026-10-30T09:05:00"])
    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None): return dt.datetime.fromisoformat(next(t))
    monkeypatch.setattr(decisions, "datetime", Clock)
    decisions.record(root, "board", "confirmed"); old = decisions.ledger(root).read_text(encoding="utf-8").splitlines()[-1]
    decisions.record(root, "board", "draft")
    with open(decisions.ledger(root), "a", encoding="utf-8") as fh: fh.write(old + "\n")         # her old 'confirmed' line again, last
    assert decisions.last(root, "board")["state"] == "draft"


# ---------------------------------------------------------------- bypass 3: POST to the page server like a script
@pytest.fixture
def ui():
    from gameanything.ui import serve
    root = gameplay_project()
    box, ready = {}, threading.Event()
    th = threading.Thread(target=serve, args=(root,), kwargs={"port": 18911, "ready": lambda s: (box.setdefault("srv", s), ready.set())}, daemon=True)
    th.start(); assert ready.wait(20)
    yield f"http://127.0.0.1:{box['srv'].server_port}", root
    box["srv"].shutdown(); box["srv"].server_close()


def call(url, data=None, headers=None):
    r = urllib.request.Request(url, json.dumps(data).encode() if data is not None else None, {"Content-Type": "application/json", **(headers or {})},
                               method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(r, timeout=20) as x: return x.status, x.read(), x.headers
    except urllib.error.HTTPError as e: return e.code, e.read(), e.headers


def test_a_script_cannot_post_her_decision(ui):
    url, root = ui
    body = lambda: {"rev": screens.gameplay_rev(root), "stage": "mapping", "state": "confirmed", "items": {}}
    for h in ({}, {"Origin": url}, {"Origin": url, "Cookie": "ga_decide_0=x"}):            # qa2: no Origin; then Origin without the cookie
        st, b, _ = call(url + "/api/gameplay_review", body(), h)
        assert st == 403, (h, st, b)
    assert not decisions.confirmed(root, "gameplay:mapping")
    st, _, h = call(url + "/", headers={"Origin": url})                                   # a script's GET of the page: no cookie
    assert "ga_decide" not in (h.get("Set-Cookie") or "")
    # her browser: the page (Sec-Fetch-Dest: document) sets the cookie, the page's POST carries it and its Origin
    st, _, h = call(url + "/app", headers={"Sec-Fetch-Dest": "document", "Sec-Fetch-Site": "none"})
    ck = (h.get("Set-Cookie") or "").split(";")[0]
    assert st == 200 and ck.startswith("ga_decide_") and "HttpOnly" in h["Set-Cookie"] and "SameSite=Strict" in h["Set-Cookie"]
    st, b, _ = call(url + "/api/gameplay_review", body(), {"Origin": url, "Cookie": ck})
    assert st == 200 and json.loads(b)["ok"], b
    assert decisions.confirmed(root, "gameplay:mapping")
    st, _, _ = call(url + "/api/gameplay_review", body(), {"Origin": "http://evil.example", "Cookie": ck})
    assert st == 403


def test_card_answers_need_the_page_too(ui):
    url, root = ui
    T = Thread(root)
    c = T.card({"kind": "options", "key": "plan", "title": "方案", "items": [{"key": "ok", "title": "就按这个做"}, {"key": "no", "title": "再想想"}]})
    st, _, _ = call(url + "/api/thread/answer", {"card_id": c["id"], "answer": {"picked": ["ok"]}})
    assert st == 403 and not decisions.last(root, "plan:m1")


# ---------------------------------------------------------------- the deny rules every provider gets
def test_every_provider_denies_the_ledger_the_keys_and_the_signing_code(tmp_path):
    for role in ("resident", "builder"):
        D = set(agent_providers.DENY_BUILDER if role == "builder" else agent_providers.DENY_RESIDENT)
        for r in ("Bash(*user_decisions*)", "Bash(*decision-keys*)", "Bash(*decisions.record*)", "Bash(*gameanything.decisions*)",
                  "Bash(*api/*_review*)", "Bash(*api/thread/answer*)", "Bash(*decisions.key*)"):
            assert r in D, (role, r)
    cmd = agent_providers.provider("claude-code", binary="claude").command("p", "s", "sid", False, tmp_path)
    assert any(x.startswith("Edit(**/.user_decisions.jsonl") for x in cmd) and any(x.startswith("Read(/") and "server" in x for x in cmd)
    oc = agent_providers.opencode_permission("resident", tmp_path, [])
    assert oc["bash"]["*user_decisions*"] == "deny" and oc["bash"]["*decisions.record*"] == "deny"
    gp = agent_providers.gemini_policy("resident")
    assert "user_decisions" in gp and "decisions\\.record" in gp


# ---------------------------------------------------------------- the project id, not the folder name
def test_a_moved_project_keeps_her_confirmations(tmp_path):
    root = gameplay_project(); decisions.record(root, "gameplay:mapping", "confirmed")
    wy(root, "feedback/gameplay_review.yaml", {"mapping": {"state": "confirmed"}})
    dst = tmp_path / "elsewhere" / "renamed-folder"; dst.parent.mkdir(); shutil.copytree(root, dst)
    assert decisions.confirmed(dst, "gameplay:mapping") and decisions.forged(dst) == []
    shutil.rmtree(root); assert decisions.confirmed(dst, "gameplay:mapping")


# ---------------------------------------------------------------- no 「确认了…」 in her name after an agent's 'confirmed'
def test_her_item_click_after_a_forged_confirm_posts_nothing_in_her_name():
    e = projects.create("白雪公主", "adaptation"); root = Path(e["path"])
    wy(root, "3_remember/adaptation.yaml", {"work": {"title": "白雪"}, "scenes": [{"id": "s1", "title": "镜子"}], "places": [], "characters": [{"name": "王后"}]})
    wy(root, "feedback/adaptation_review.yaml", {"state": "confirmed", "state_characters": "confirmed"})       # the agent wrote both
    p = Proj(root)
    r = screens.save_adaptation(p, {"rev": screens.adaptation_rev(root), "items": {"scene:s1": {"choice": "keep"}}})
    assert r["ok"] and r["state"] == "draft" and r["state_characters"] == "draft"
    assert not any(t.startswith("确认了") for t, _, _ in p.told), p.told
    e = projects.create("钓鱼", "feature", game="overcooked2"); root = Path(e["path"])
    wy(root, "3_remember/feature.yaml", {"title": "钓鱼", "items": [{"id": "i1", "what": "钓竿"}]})
    wy(root, "feedback/feature_review.yaml", {"state": "confirmed"})
    p = Proj(root); r = screens.save_feature(p, {"rev": screens.feature_rev(root), "items": {"item:i1": {"choice": "keep"}}})
    assert r["ok"] and r["state"] == "draft" and not any(t.startswith("确认了") for t, _, _ in p.told)
    root = gameplay_project("夜班2"); wy(root, "feedback/gameplay_review.yaml", {"mapping": {"state": "confirmed"}})
    p = Proj(root); r = screens.save_gameplay(p, {"rev": screens.gameplay_rev(root), "items": {"map:m1": {"choice": "keep"}}})
    assert r["ok"] and r["review"]["mapping"]["state"] == "draft" and not any(t.startswith("确认了") for t, _, _ in p.told)


# ---------------------------------------------------------------- her chat says an agent's confirmation does not count
def test_her_chat_says_an_agent_confirmation_does_not_count():
    root = gameplay_project()
    wy(root, "feedback/gameplay_review.yaml", {"mapping": {"state": "confirmed"}})
    assert decisions.note_forged(root) == ["gameplay:mapping"]
    sys_lines = [e for e in Thread(root).events() if e.get("notice") == "forged_confirmation"]
    assert len(sys_lines) == 1 and "agent 写的确认不算数，请你自己在页面上确认" in sys_lines[0]["text"] and "机制映射" in sys_lines[0]["text"]
    assert decisions.note_forged(root) == [], "once per claim"
    wy(root, "feedback/gameplay_review.yaml", {"mapping": {"state": "draft"}}); decisions.note_forged(root)
    wy(root, "feedback/gameplay_review.yaml", {"mapping": {"state": "confirmed"}}); assert decisions.note_forged(root) == ["gameplay:mapping"]
