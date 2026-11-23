"""Web search for public places (landmark-references.md): both providers give residents and builders web search; reference pictures are
saved only through `gameanything refs fetch` after her yes on a websearch card, with no private names in the query; `gameanything flow check` fails on
web refs without consent. No network: the download goes through a fake opener and a fake DNS resolver."""
import io
import json
import urllib.request
from pathlib import Path

import pytest
import yaml

from gameanything import agent_providers, agentd, cli, flow, projects, refs
from gameanything.conversation import Thread

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PUBLIC = lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))]
PRIVATE = lambda host, port: [(2, 1, 6, "", ("10.0.0.7", 0))]
URL = "https://upload.wikimedia.org/geisel.png"


class FakeResp(io.BytesIO):
    def __init__(self, data, ct="image/png"): super().__init__(data); self.headers = {"Content-Type": ct}
    def __enter__(self): return self
    def __exit__(self, *a): self.close()


class Opener:
    def __init__(self, data=PNG, ct="image/png"): self.data, self.ct, self.urls = data, ct, []
    def open(self, req, timeout=None): self.urls.append(req.full_url); return FakeResp(self.data, self.ct)


def project(owner=None, people=("林小雨",)):
    e = projects.create("校园", "memory", game="minecraft", **({"owner": owner} if owner else {})); root = Path(e["path"])
    (root / "3_remember").mkdir(exist_ok=True)
    (root / "3_remember" / "people.yaml").write_text(yaml.safe_dump({"people": [{"name": n} for n in people]}, allow_unicode=True), encoding="utf-8")
    return root, Thread(root)


def consent(T, answer="yes", key="websearch-geisel", kind="permission"):
    if kind == "permission":
        c = T.card({"kind": "permission", "key": key, "title": "要不要上网搜几张 Geisel 图书馆的参考图？", "to": "网页搜索",
                    "will_send": ["搜索词：Geisel Library UCSD exterior"], "will_not_send": ["你的照片、名字"]})
        if answer: T.answer(c["id"], {"decision": answer})
    else:
        c = T.card({"kind": "options", "key": key, "title": "上网搜 Geisel 图书馆的参考图？",
                    "items": [{"key": "yes", "title": "搜吧"}, {"key": "no", "title": "不要，只用我的照片"}]})
        if answer: T.answer(c["id"], {"picked": [answer]})
    return c


def req(**kw):
    return {"place": "Geisel Library", "url": URL, "query": "Geisel Library UCSD exterior", "consent": "websearch-geisel",
            "license": "CC BY-SA 4.0", "page": "https://commons.wikimedia.org/wiki/File:Geisel.png", **kw}


# ---------------------------------------------------------------- command lines: both providers, both roles
@pytest.mark.parametrize("role", ["resident", "builder"])
def test_claude_runs_have_web_search_and_fetch_and_keep_the_deny_lists(tmp_path, role):
    p = agent_providers.provider("claude-code", binary="claude")
    cmd = p.command("go", "SYS", "sid", False, tmp_path, role=role)
    tools = cmd[cmd.index("--tools") + 1].split(","); allowed = cmd[cmd.index("--allowedTools") + 1].split()
    assert {"WebSearch", "WebFetch", "Bash", "Read"} <= set(tools) and set(tools) == set(allowed)
    deny = cmd[cmd.index("--disallowedTools") + 1: cmd.index("--append-system-prompt")]
    assert "Bash(*python* *gen_*.py*)" in deny and "Bash(*docker run*)" in deny and "Bash(*pkill*)" in deny
    assert ("Bash(*mclab_rt*)" in deny) == (role == "resident")
    assert not any(d.startswith(("WebSearch", "WebFetch")) for d in deny)


@pytest.mark.parametrize("role,network", [("resident", False), ("builder", True)])
@pytest.mark.parametrize("resume", [False, True])
def test_codex_runs_have_live_web_search_but_a_resident_sandbox_stays_offline(tmp_path, role, network, resume):
    p = agent_providers.provider("codex", binary="codex")
    cmd = p.command("go", "SYS", "t-1", resume, tmp_path, role=role, network=network, env={"CODEX_HOME": str(tmp_path / "none")})
    assert 'web_search="live"' in cmd and 'web_search="disabled"' not in cmd
    assert ("sandbox_workspace_write.network_access=true" in cmd) == network


# ---------------------------------------------------------------- consent and query hygiene
def test_fetch_needs_her_yes_on_a_websearch_card():
    root, T = project()
    with pytest.raises(refs.RefsError, match="找不到许可卡"): refs.fetch_now(root, req(), Opener(), PUBLIC)
    consent(T, answer=None)
    with pytest.raises(refs.RefsError, match="还没有"): refs.fetch_now(root, req(), Opener(), PUBLIC)
    consent(T, answer="no")
    with pytest.raises(refs.RefsError, match="还没有"): refs.fetch_now(root, req(), Opener(), PUBLIC)
    T.card({"kind": "permission", "key": "preview", "title": "发给生图模型？", "to": "x", "will_send": ["a"], "will_not_send": ["b"]})
    with pytest.raises(refs.RefsError): refs.fetch_now(root, req(consent="preview"), Opener(), PUBLIC)      # not a websearch card
    c = consent(T, "yes")
    e = refs.fetch_now(root, req(), Opener(), PUBLIC)
    assert e["consent"] == c["id"] and e["source"] == "web" and e["query"] == "Geisel Library UCSD exterior" and e["license"] == "CC BY-SA 4.0"
    folder = root / "2_perceive" / "landmark_refs" / "Geisel-Library"
    assert (folder / e["file"]).read_bytes() == PNG
    idx = yaml.safe_load((folder / "sources.yaml").read_text(encoding="utf-8"))
    assert idx["place"] == "Geisel Library" and idx["refs"][0]["url"] == URL and idx["refs"][0]["page"].startswith("https://commons")
    assert refs.fetch_now(root, req(), Opener(), PUBLIC).get("duplicate") and len(list(folder.glob("*.png"))) == 1


def test_options_card_yes_counts():
    root, T = project(); consent(T, "yes", kind="options")
    assert refs.fetch_now(root, req(), Opener(), PUBLIC)["file"].endswith(".png")


@pytest.mark.parametrize("query", ["Geisel Library 林小雨", "wenyi Geisel Library", "Geisel Library someone@ucsd.edu", "温怡 UCSD"])
def test_queries_with_private_names_are_refused(query, monkeypatch):
    from gameanything import users
    root, T = project(owner="wenyi"); consent(T)
    monkeypatch.setattr(users, "display", lambda n: "温怡" if n == "wenyi" else n)
    with pytest.raises(refs.RefsError, match="私人信息"): refs.fetch_now(root, req(query=query), Opener(), PUBLIC)
    assert not (root / "2_perceive" / "landmark_refs").exists()


def test_only_public_images():
    root, T = project(); consent(T)
    with pytest.raises(refs.RefsError, match="公网"): refs.fetch_now(root, req(), Opener(), PRIVATE)
    with pytest.raises(refs.RefsError, match="http"): refs.fetch_now(root, req(url="file:///etc/passwd"), Opener(), PUBLIC)
    with pytest.raises(refs.RefsError, match="不是图片"): refs.fetch_now(root, req(), Opener(b"<html>hi</html>", "text/html"), PUBLIC)
    h = refs._Redirects(PRIVATE)
    with pytest.raises(refs.RefsError, match="公网"):
        h.redirect_request(urllib.request.Request(URL), None, 302, "Found", {}, "http://intranet.local/x.png")


# ---------------------------------------------------------------- flow check
def test_flow_check_fails_on_web_refs_without_consent(capsys):
    root, T = project()
    assert refs.problems(root) == []
    folder = root / "2_perceive" / "landmark_refs" / "Geisel"; folder.mkdir(parents=True)
    (folder / "a.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 10)
    P = refs.problems(root); assert len(P) == 1 and "没有登记" in P[0]
    (folder / "sources.yaml").write_text(yaml.safe_dump({"refs": [{"file": "a.jpg", "url": URL, "query": "Geisel Library", "license": "unknown"}]}), encoding="utf-8")
    P = refs.problems(root); assert len(P) == 1 and "许可卡" in P[0]
    c = flow.check(root); wr = next(x for x in c["criteria"] if x["id"] == "web_refs_consent")
    assert not c["ok"] and not wr["ok"] and "许可卡" in wr["why"]
    assert any("参考图" in a for a in flow.next_step(root)["actions"])
    assert cli.main(["refs", "check", "--project", str(root)]) == 1
    capsys.readouterr()
    cid = consent(T)["id"]
    (folder / "sources.yaml").write_text(yaml.safe_dump({"refs": [{"file": "a.jpg", "url": URL, "query": "Geisel Library", "license": "unknown", "consent": cid},
                                                                   {"file": "b.jpg", "source": "user"}]}), encoding="utf-8")
    (folder / "b.jpg").write_bytes(b"\xff\xd8\xff")
    assert refs.problems(root) == [] and next(x for x in flow.check(root)["criteria"] if x["id"] == "web_refs_consent")["ok"]
    (folder / "sources.yaml").write_text(yaml.safe_dump({"refs": [{"file": "a.jpg", "url": URL, "consent": cid}, {"file": "b.jpg", "source": "user"}]}), encoding="utf-8")
    assert refs.problems(root) == ["Geisel/a.jpg 的 sources.yaml 缺 query / license"]


# ---------------------------------------------------------------- in a run: queue; agentd downloads on the host
def test_a_run_queues_and_agentd_downloads(monkeypatch, capsys):
    root, T = project(); consent(T)
    monkeypatch.setenv("GAMEANYTHING_GEN_OFF", "1")
    monkeypatch.setattr(refs, "download", lambda *a, **k: (_ for _ in ()).throw(AssertionError("a run never downloads")))
    with pytest.raises(refs.RefsError, match="私人信息"): refs.request(root, **{**req(), "query": "林小雨 Geisel"})
    assert refs.pending(root) == []
    # agentd is not running: queued, and the outcome will come back as a note
    assert cli.main(["refs", "fetch", "--project", str(root), "--place", "Geisel Library", "--url", URL, "--query", "Geisel Library UCSD",
                     "--consent", "websearch-geisel", "--license", "CC BY-SA 4.0"]) == 0
    assert "已排队" in capsys.readouterr().out
    (qf,) = refs.pending(root); assert qf.with_suffix(".notify").exists()
    monkeypatch.undo()
    D = agentd.Agentd(claude="/bin/false", spawn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no run")), quiet=True)
    D.refs_opener, D.refs_resolve = Opener(), PUBLIC
    D._refs(T); D.refs[str(T.root)].join(10)
    st, res = refs.result_of(qf)
    assert st == "done" and res["entry"]["consent"] and refs.pending(root) == [] and not qf.with_suffix(".notify").exists()
    (note,) = [json.loads(f.read_text(encoding="utf-8")) for f in agentd.inbox(T)]
    assert note["from"] == "refs" and "参考图已保存" in note["text"]
    assert refs.problems(root) == []


def test_agentd_rejects_a_request_whose_consent_was_taken_back():
    root, T = project(); c = consent(T)
    qf = refs.request(root, **req())
    T.answer(c["id"], {"decision": "no"})
    st, res = refs.process(root, qf, Opener(), PUBLIC)
    assert st == "rejected" and "同意" in res["why"] and not (root / "2_perceive" / "landmark_refs").exists()


def test_wait_returns_the_outcome_or_leaves_a_notify_mark(tmp_path):
    root, T = project(); consent(T); qf = refs.request(root, **req())
    t = [0.0]
    st, res = refs.wait(qf, secs=1, clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s))
    assert st is None and qf.with_suffix(".notify").exists()
    refs.process(root, qf, Opener(), PUBLIC, notify=lambda r, text: None)
    assert refs.wait(qf, secs=1)[0] == "done"


def test_direct_fetch_outside_a_run(monkeypatch, capsys):
    root, T = project(); consent(T)
    monkeypatch.delenv("GAMEANYTHING_GEN_OFF", raising=False)
    monkeypatch.setattr(refs, "download", lambda url, opener=None, resolve=None: (PNG, ".png"))
    assert cli.main(["refs", "fetch", "--project", str(root), "--place", "Geisel Library", "--url", URL, "--query", "Geisel Library",
                     "--consent", "websearch-geisel"]) == 0
    assert "参考图已保存" in capsys.readouterr().out
    assert cli.main(["refs", "status", "--project", str(root)]) == 0 and "Geisel-Library: 1 张" in capsys.readouterr().out


def test_refs_saved_before_the_rule_are_not_rejudged(tmp_path):
    import os
    from gameanything import refs
    d = tmp_path / "2_perceive" / "landmark_refs" / "cove"; d.mkdir(parents=True)
    old, new = d / "cove_02.jpg", d / "cove_09.jpg"
    for f in (old, new): f.write_bytes(b"\xff\xd8\xff" + b"0" * 10)
    os.utime(old, (refs.RULE_SINCE - 86400, refs.RULE_SINCE - 86400))    # an older Wikimedia ref in an older sources.yaml format
    (d / "sources.yaml").write_text("place: cove\nimages:\n- file: cove_02.jpg\n", encoding="utf-8")
    ps = refs.problems(tmp_path)
    assert not any("cove_02" in p for p in ps) and any("cove_09" in p for p in ps)
