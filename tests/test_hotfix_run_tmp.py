"""Hotfix 2026-10-30: runs shared the daemon's $TMPDIR and the skill said `$TMPDIR/go.yaml`, so one project's go card (with invented
quotes) was posted in another project's chat; a wrong go card without a key stayed clickable after the right one was posted.
Every run gets its own temp folder (removed when it ends), `chat card` refuses another project's card and a go / permission card without
a key, and a newer go card for the same version supersedes the older open ones."""
import json
import os
import shutil
from pathlib import Path

import pytest
import yaml

from gameanything import agent_providers as ap, agentd, cli, projects
from gameanything.conversation import Thread
from test_agentd import Spawner, daemon as resident_daemon, new_project
from test_card_keys import run_shell
import test_builds as tb


@pytest.fixture
def spawner():
    s = Spawner(); yield s; s.stop_all()


def test_run_tmpdir_is_private_and_removed():
    a, b = ap.run_tmpdir("proj-a", "r1"), ap.run_tmpdir("proj-b", "r2")
    assert a != b and a.is_dir() and b.is_dir() and a.parent == b.parent == ap.run_tmp_base()
    assert os.name == "nt" or oct(a.stat().st_mode & 0o777) == "0o700"         # (Windows: no mode bits; the user's own %TEMP% is private)
    env = ap.with_run_tmp({"TMPDIR": "/tmp", "X": "1"}, a)
    assert env["TMPDIR"] == env["TMP"] == env["TEMP"] == env["GAMEANYTHING_RUN_TMP"] == str(a) and env["X"] == "1"
    assert ap.run_tmp_project(a / "card-x.yaml") == "proj-a" and ap.run_tmp_project("/etc/passwd") is None
    ap.drop_run_tmp(a); assert not a.exists() and b.exists()
    ap.drop_run_tmp("/"); ap.drop_run_tmp(None)                         # never anything outside the base
    old = ap.run_tmpdir("proj-c", "r3"); os.utime(old, (0, 0))
    ap.run_tmpdir("proj-d", "r4"); assert not old.exists(), "a folder of a run that never ended is pruned"


def test_resident_runs_get_their_own_tmpdir(spawner, monkeypatch):
    monkeypatch.setattr(agentd, "MAX_CORRECTIONS", 0); monkeypatch.setattr(agentd, "MAX_CONTINUE", 0)
    ea, A = new_project("项目甲"); eb, B = new_project("项目乙")
    for T in (A, B): T.append({"from": "agent", "type": "text", "text": "你好", "source": "terminal"})
    D = resident_daemon(spawner)
    A.user_text("甲的话"); B.user_text("乙的话")
    D.tick(); D.tick()
    assert len(spawner.calls) == 2
    tmps = [Path(c["env"]["TMPDIR"]) for c in spawner.calls]
    assert tmps[0] != tmps[1] and all(t.is_dir() and t.parent == ap.run_tmp_base() for t in tmps)
    assert {ap.run_tmp_project(t / "x") for t in tmps} == {ea["id"], eb["id"]}
    assert all(c["env"]["TMP"] == c["env"]["TMPDIR"] == c["env"]["GAMEANYTHING_RUN_TMP"] for c in spawner.calls)
    i = next(n for n, c in enumerate(spawner.calls) if c["cwd"] in (A.root, A.root.resolve()))
    spawner.end(i); D.tick()
    assert not tmps[i].exists(), "removed when the run ended"


def test_builder_runs_get_their_own_tmpdir(spawner, tmp_path, monkeypatch):
    monkeypatch.setenv("GAMEANYTHING_PARENT_REQUESTS", str(tmp_path / "req")); monkeypatch.setenv("M2W_LAB_USER", "tester")
    e, T = tb.project(); tb.go(T); lab = tb.FakeLab()
    D = tb.daemon(spawner, lab, tmp_path); tb.request(T); D.tick()
    (b,) = [c for c in spawner.calls if c["env"].get("GAMEANYTHING_ROLE") == "builder"]
    t = Path(b["env"]["TMPDIR"]); assert t.is_dir() and ap.run_tmp_project(t / "x") == e["id"]
    assert tb.rec(T)["tmpdir"] == str(t)


def test_gemini_uses_the_run_tmpdir(tmp_path):
    p = ap.provider("gemini", binary="gemini"); t = ap.run_tmpdir("p", "r")
    _cmd, env = p.launch("hi", "sys", None, False, tmp_path, env=ap.with_run_tmp({"GEMINI_API_KEY": "k", "GAMEANYTHING_GEMINI_HOME": str(tmp_path / "gh")}, t))
    assert env["TMPDIR"] == str(t)
    assert str(t) in [_cmd[i + 1] for i, x in enumerate(_cmd) if x == "--include-directories"], "its file tools may write the card files there"


def _card(root, body, where):
    where.parent.mkdir(parents=True, exist_ok=True); where.write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
    return cli.main(["chat", "card", "--project", str(root), "--file", str(where)])


GO = {"kind": "go", "key": "m1-go", "title": "开工做第 1 版", "milestone": "m1", "items": ["做第一版"]}


def test_chat_card_refuses_another_projects_card(tmp_path):
    a = projects.create("甲", kind="memory"); b = projects.create("乙", kind="memory")
    ra, rb = projects.resolve(a["id"]), projects.resolve(b["id"])
    task = {"kind": "task", "key": "t1", "title": "看看", "body": "去看看", "open": "#people/tag"}
    with pytest.raises(SystemExit) as x: _card(ra, {**task, "project": b["id"]}, tmp_path / "c1.yaml")
    assert b["id"] in str(x.value) and "mktemp" in str(x.value)
    other = ap.run_tmpdir(b["id"], "run1")
    with pytest.raises(SystemExit) as x: _card(ra, task, other / "go.yaml")
    assert "另一个项目" in str(x.value)
    assert not [e for e in Thread(ra).events() if e.get("type") == "card"], "nothing was posted in 甲"
    mine = ap.run_tmpdir(a["id"], "run2")
    assert _card(ra, {**task, "project": a["id"]}, mine / "card-1.yaml") == 0
    (c,) = [e for e in Thread(ra).events() if e.get("type") == "card"]
    assert "project" not in c["card"], "the stamp is not part of the card"
    assert _card(rb, task, other / "card-2.yaml") == 0, "乙's own run folder is fine for 乙"


@pytest.mark.parametrize("kind", ["go", "permission"])
def test_go_and_permission_cards_need_a_key(tmp_path, kind):
    e = projects.create("丙", kind="memory"); root = projects.resolve(e["id"])
    body = dict(GO) if kind == "go" else {"kind": "permission", "key": "p", "title": "许可", "will_send": ["a"], "will_not_send": ["b"], "to": "fal"}
    body.pop("key")
    with pytest.raises(SystemExit) as x: _card(root, body, tmp_path / "c.yaml")
    assert "key" in str(x.value)


def test_newer_go_card_supersedes_older_open_ones():
    e = projects.create("丁", kind="memory"); T = Thread(projects.resolve(e["id"]))
    wrong = T.card({k: v for k, v in GO.items() if k != "key"} | {"title": "错的开工卡"})          # keyless, as the stray one was
    other = T.card({**GO, "key": "m2-go", "milestone": "m2"})
    right = T.card(GO)
    assert right["supersedes"] == [wrong["id"]]
    cs = T.cards(); assert wrong["id"] not in cs and other["id"] in cs and right["id"] in cs
    with pytest.raises(Exception, match="已经更新"): T.answer(wrong["id"], {"decision": "start"})
    if shutil.which("node"):                                                   # the page (shell.js) needs node
        out = run_shell("zh", [T.events()])
        ids = [k["id"] for k in out["kids"]]
        assert wrong["id"] not in ids and right["id"] in ids and other["id"] in ids, "the page hides it too (shell.js cardState)"
    # an answered older go card is history: it stays, read-only, and is not superseded
    T.answer(right["id"], {"decision": "wait"})
    again = T.card({**GO, "key": "m1-go-2", "title": "再开工"})
    assert "supersedes" not in again and right["id"] in T.cards()
