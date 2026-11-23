"""The LLM judge behind her per-project permission card (gameanything/judge.py, docs/feedback-loop.md 7.4): no yes -> nothing is
written for a model; requests in two prompt orders; a FAKE agent answers them; collect stores the labels next to the keyword ones with
model + rubric + prompt version, writes one privacy_ledger.yaml entry and a `judge` event; the agreement numbers."""
import json
from pathlib import Path

import pytest
import yaml

from gameanything import cli, feedback as F, judge as J
from gameanything.conversation import Thread, check_card
from test_feedback import proj, say_at, study_on  # noqa: F401,F811  (fixtures; study_on: study mode on)


def _records(proj):
    say_at(proj, "这里有点简陋 没有那种酒店等感觉", "m1", 308.1, at="2026-10-26T19:09:32")
    say_at(proj, "这里穿模了", "m1", 380, at="2026-10-26T19:10:08")
    say_at(proj, "这里这个客厅还是太简陋了", "m2", 330, at="2026-10-26T22:04:00")
    F.capture(proj, Thread(proj).events())


def _yes(proj, frames=False, decision="yes"):
    c = J.consent_card(proj, frames); check_card(dict(c)); ev = Thread(proj).card(c)
    Thread(proj).answer(ev["id"], {"decision": decision}); return ev


def fake_agent(req: Path, kind_of=lambda w: "sparse_plain" if "简陋" in w else "clipping"):
    """What the agent CLI does with a request: read it, write the JSON lines to the output file it names."""
    t = req.read_text(encoding="utf-8"); out = Path(t.split("to:\n", 1)[1].splitlines()[0].strip())
    rows = []
    if req.name.startswith("pairs_"):
        for ln in t.split("Pairs (JSON, one per line):\n", 1)[1].split("\n\nAnswer", 1)[0].splitlines():
            p = json.loads(ln); rows.append({"first": p["first"]["id"], "second": p["second"]["id"], "same_kind": "yes", "same_target": "yes", "answer": "yes", "reason": "both bare"})
    else:
        for ln in t.split("given):\n", 1)[1].split("\n\nAnswer", 1)[0].splitlines():
            r = json.loads(ln); rows.append({"id": r["id"], "class": "taste", "kind": kind_of(r["words"]), "target": "客厅" if "客厅" in r["words"] else None, "explanation": "x"})
    out.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n", encoding="utf-8")


def test_no_yes_no_judge(proj):
    _records(proj)
    with pytest.raises(J.JudgeError, match="还没有发许可卡"): J.emit(proj, "claude-opus")
    _yes(proj, decision="no")
    with pytest.raises(J.JudgeError, match="没有同意"): J.emit(proj, "claude-opus")
    assert not J.base(proj).exists() and not (proj / "privacy_ledger.yaml").exists()
    _yes(proj)
    with pytest.raises(J.JudgeError, match="截图"): J.emit(proj, "claude-opus", frames=True)        # the card did not cover frames


def test_emit_fake_agent_collect(proj):
    _records(proj); card = _yes(proj)
    r = J.emit(proj, "claude-opus-5-5"); reqs = [Path(x) for x in r["requests"]]
    assert r["records"] == 3 and r["pairs"] >= 1 and {p.name for p in reqs} >= {"req_a_1.md", "req_b_1.md", "pairs_a.md", "pairs_b.md"}
    a, b = (Path(r["dir"]) / "req_a_1.md").read_text(encoding="utf-8"), (Path(r["dir"]) / "req_b_1.md").read_text(encoding="utf-8")
    assert a.index("- sparse_plain") < a.index("- other") and b.index("- other") < b.index("- sparse_plain")        # two prompt orders
    assert "frame" not in a.split("given):\n", 1)[1] and "heuristic" not in a                                          # no frames, no live labels
    for q in reqs: fake_agent(q)
    c = J.collect(proj)
    assert c["labelled"] == {"a": 3, "b": 3} and not any(c["missing"].values())
    rec = F.get(F.load(proj), "f3"); L = rec["labels"]
    assert L["judge"]["kind"] == "sparse_plain" and L["judge"]["model"] == "claude-opus-5-5" and L["judge"]["prompt_version"] == J.PROMPT_VERSION
    assert L["judge"]["rubric"] == J.RUBRIC_VERSION and L["judge_b"]["order"] == "b" and L["heuristic"]["kind"] == "sparse_plain"
    assert L["judge"]["pairs"][0]["answer"] == "yes" and rec["kind"] == "sparse_plain" and rec["labelled_by"] == "heuristic"   # live labels unchanged
    led = yaml.safe_load((proj / "privacy_ledger.yaml").read_text(encoding="utf-8"))["requests"][-1]
    assert led["purpose"] == "feedback-judge" and led["model"] == "claude-opus-5-5" and led["consent_card"] == card["id"] and led["images"] == []
    ev = F.events(proj, "judge")[-1]; assert ev["order_agreement"] == 1.0 or ev["order_agreement"] is None
    with pytest.raises(J.JudgeError, match="已经收过"): J.collect(proj)


def test_agreement_kappa_alpha_and_human_path(proj, tmp_path):
    _records(proj); _yes(proj); r = J.emit(proj, "m")
    for q in r["requests"]: fake_agent(Path(q))
    J.collect(proj)
    sheet = J.sample_sheet(proj, tmp_path / "h.jsonl"); rows = [json.loads(x) for x in sheet.read_text(encoding="utf-8").splitlines()]
    assert {x["id"] for x in rows} == {"f1", "f2", "f3"} and all(x["kind"] is None for x in rows)
    for x in rows: x.update({"class": "taste", "kind": "sparse_plain" if x["id"] != "f2" else "layout_scale"})
    sheet.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows), encoding="utf-8")
    assert F.label_import(proj, sheet, "human", name="anna") == 3
    k = J.agreement([proj], "judge", "human:anna")
    assert k["n"] == 3 and k["observed"] == pytest.approx(2 / 3) and k["confusion"]["clipping"]["layout_scale"] == 1
    assert J.agreement([proj], "judge", "judge_b")["kappa"] == 1.0
    assert J.agreement([proj], "judge", "nobody")["kappa"] is None
    al = J.alpha([proj]); assert al["raters"] == ["judge", "human:anna"] and al["units"] == 3 and al["alpha"] < 1
    perfect = J.alpha([proj], ["judge", "judge_b"]); assert perfect["alpha"] == pytest.approx(1.0)
    assert cli.main(["feedback", "agreement", "--project", str(proj), "--a", "judge", "--b", "human:anna"]) == 0


def test_cli_card_and_status(proj, tmp_path, capsys):
    _records(proj)
    assert cli.main(["feedback", "judge", "--project", str(proj), "--card", "--out", str(tmp_path / "c.yaml")]) == 0
    c = yaml.safe_load((tmp_path / "c.yaml").read_text(encoding="utf-8")); assert c["key"] == "feedback-judge" and c["en"]["title"]
    assert cli.main(["feedback", "judge", "--project", str(proj)]) == 0 and "还没有发许可卡" in capsys.readouterr().out
