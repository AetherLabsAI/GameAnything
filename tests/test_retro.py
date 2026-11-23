"""The outer loop's agent steps (gameanything/retro.py, docs/feedback-loop.md 2.1, 2.4): the retrospective (proposals with evidence ->
profile candidates / candidate lessons / a coordinator request), the critic (predictions logged, matched later), both obeying the blind
condition; the builder prompt names the retrospective; datacheck lists every datum. A FAKE agent answers the requests."""
from pathlib import Path

import pytest
import yaml

from gameanything import cli, devstatus as S, feedback as F, lessons, profile as P, retro as R
from gameanything.conversation import Thread
from test_feedback import proj, say_at, study_on  # noqa: F401,F811  (fixtures; study_on: study mode on)


def _history(proj):
    say_at(proj, "这里有点简陋 没有那种酒店等感觉", "m1", 308.1, at="2026-10-26T19:09:32")
    say_at(proj, "卡片里看不到图", "m1", 10, at="2026-10-26T19:12:00")
    say_at(proj, "这里这个客厅还是太简陋了", "m2", 330, at="2026-10-26T22:04:00")
    F.capture(proj, Thread(proj).events())
    F.set_fields(proj, "f1", interpretation="客厅太简陋", target="客厅", certainty="high"); F.link(proj, "f1", new_item="客厅要有酒店的奢华感")
    S.set_item(proj, "r1", "done", build="m2", by="builder", evidence="加了家具")
    F.set_fields(proj, "f3", interpretation="客厅还是简陋", target="客厅", certainty="high")


def _answer(req_file, doc):
    t = Path(req_file).read_text(encoding="utf-8"); out = Path(t.split("to:\n", 1)[1].splitlines()[0].strip())
    out.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8"); return out


def test_retrospective_routes_by_scope(proj, monkeypatch):
    _history(proj)
    added = []
    monkeypatch.setattr(lessons, "add", lambda *a, **k: added.append((a, k)) or {"id": "L9", "action": "added"})
    P.add("local", "场景要丰富", kind="sparse_plain", by="her")
    r = R.retro_emit(proj, "m2"); assert r["repeats"] == 1 and r["resolved"] == 1
    req = Path(r["request"]).read_text(encoding="utf-8"); assert "f3" in req and "加了家具" in req and "her_profile" in req
    _answer(r["request"], {"proposals": [
        {"scope": "user", "kind": "sparse_plain", "evidence": ["f1", "f3"], "why": "repeat", "merge_into": "p1"},
        {"scope": "user", "kind": "mood", "evidence": ["f1"], "why": "generalises", "text": "大宅要有酒店的奢华感", "text_en": "luxury"},
        {"scope": "craft", "kind": "sparse_plain", "evidence": ["f3"], "why": "repeat", "symptom": "rooms read as bare from the tour camera",
         "cause": "props only along walls", "fix": "fill the camera's foreground"},
        {"scope": "system", "kind": "ui_delivery", "evidence": ["f2"], "why": "system_bug", "text": "card pictures not visible"},
        {"scope": "game", "kind": "clipping", "evidence": ["f99"], "why": "x", "symptom": "s", "fix": "f"}]})
    out = R.retro_collect(proj, "m2", model="fake")
    res = [a["result"] for a in out["applied"]]
    assert res[0].startswith("profile:p1") and res[1] == "profile:p2 (candidate, off)" and res[2] == "lesson:L9 (added)" and res[3].startswith("request:")
    assert out["refused"][0]["refused"].startswith("不认识的记录") and out["uncovered_repeats"] == []
    pr = P.load("local")["entries"]
    assert {x["record"] for x in pr[0]["from"]} == {"f1", "f3"} and pr[1]["on"] is False and pr[1]["status"] == "candidate" and pr[1]["by"] == "retrospective"
    assert added[0][1]["general"] is True and added[0][1]["project"] == proj.resolve()                              # the privacy guard sees the project
    ev = F.events(proj, "retro")[-1]; assert ev["m"] == "m2" and len(ev["proposals"]) == 5 and ev["repeats"] == ["f3"]
    with pytest.raises(R.RetroError, match="已经收过"): R.retro_collect(proj, "m2")
    assert R.retro_todo(proj) == ["m1"]


def test_her_switch_confirms_a_candidate():
    e = P.add("local", "镜头要稳", kind="camera", by="retrospective", sources=["x:f1"])
    assert e["status"] == "candidate" and e["history"][0]["op"] == "add"
    P.toggle("local", e["id"], True)                                    # an agent switching it on does not confirm it
    assert P.load("local")["entries"][-1]["status"] == "candidate"
    P.toggle("local", e["id"], False); P.toggle("local", e["id"], True, by="her")
    x = P.load("local")["entries"][-1]; assert x["status"] == "confirmed" and [h["op"] for h in x["history"]] == ["add", "on", "off", "confirm", "on"]


def test_critic_obeys_condition_logs_and_matches(proj):
    _history(proj)
    F.condition(proj, "C1", m="m3")
    assert R.critic_emit(proj, "m3")["skip"] is True and F.events(proj, "critic_skip")
    F.condition(proj, "C4", m="m4")
    play = proj / "5_build" / "m4" / "play"; play.mkdir(parents=True)
    r = R.critic_emit(proj, "m4"); req = Path(r["request"]).read_text(encoding="utf-8")
    assert "这里这个客厅还是太简陋了" in req and "her_preferences" in req and not r["skip"]
    _answer(r["request"], {"predictions": [{"kind": "sparse_plain", "target": "客厅", "p": 0.8, "text": "还是简陋"},
                                           {"kind": "camera", "target": None, "p": 0.2, "text": "镜头"}, {"kind": "bogus", "p": 2}]})
    c = R.critic_collect(proj, "m4", model="fake")
    assert len(c["predictions"]) == 2 and [p["kind"] for p in c["high"]] == ["sparse_plain"] and c["problems"]
    ev = F.events(proj, "critic")[-1]; assert ev["m"] == "m4" and ev["predictions"][0] == {"kind": "sparse_plain", "target": "客厅", "chapter": None, "t": None, "p": 0.8}
    say_at(proj, "客厅还是太简陋", "m4", 300, at="2099-01-01T00:00:00")                 # her later complaint on m4
    new = F.capture(proj, Thread(proj).events()); assert new[0]["milestone"] == "m4" and new[0]["anchor"]["target"] == "客厅"
    mt = R.match(proj, "m4")
    assert mt["loose"]["precision"] == 1.0 and mt["loose"]["recall"] == 1.0 and mt["strict"]["tp_predictions"] == 1
    assert mt["loose"]["brier"] == pytest.approx(((0.8 - 1) ** 2 + 0.2 ** 2) / 2)
    assert F.match_predictions(proj, "m4")["loose"]["precision"] == 1.0


def test_deliver_warns_when_the_critic_was_skipped(proj):
    F.condition(proj, "C4")
    assert any("预评" in t for _, t in F.on_deliver(proj, "m2"))
    F.condition(proj, "C1", m="m5"); assert not any("预评" in t for _, t in F.on_deliver(proj, "m5"))


def test_builder_prompt_names_the_retrospective(proj):
    from gameanything.builds import Builds
    _history(proj)
    b = Builds.__new__(Builds)
    r = {"milestone": "m3", "build_mode": "lab", "playtest_rounds": 1, "wall_hours": 1, "retro_todo": R.retro_todo(proj, before="m3")}
    t = b.user_prompt(r); assert "retrospective of m1, m2" in t and "gameanything feedback retro" in t
    assert "C1" not in t and "C4" not in t and "condition" not in t.lower()


def test_datacheck_lists_every_datum(proj, capsys):
    _history(proj)
    d = F.datacheck(proj); names = [r["datum"] for r in d["rows"]]
    for need in ("state transitions", "condition assigned", "build start", "build end", "retrieval", "critic predictions", "retrospective applied",
                 "LLM-judge labels", "human labels", "deliveries", "her verdict"):
        assert any(n.startswith(need) for n in names), need
    assert not F.assignments(proj)                                                          # read-only: it never assigns a condition
    F.log_event(proj, "build_start", m="m3", provider="claude-code", condition="C4")
    d = F.datacheck(proj); row = {r["datum"].split(" (")[0]: r for r in d["rows"]}
    assert "m3" in d["live_versions"] and row["build end"]["state"] == "missing" and "build end (wall time, rounds, tokens, cost)" in d["missing"]
    assert cli.main(["feedback", "datacheck", "--project", str(proj)]) == 1 and "✗" in capsys.readouterr().out
