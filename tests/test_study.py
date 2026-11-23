"""Study mode (gameanything/study.py, docs/feedback-loop.md 0): OFF by default. Off = the product loop only: every version runs the full
loop (brief with her profile and repeat kinds, re-shoots, the critic, the retrospective), no blind condition and no `condition` event, no
LLM-judge card or run, no label sheets / agreement, nothing in feedback/metrics.jsonl, the 「反馈和改进」 panel hidden. On = the study
(tests/test_feedback.py, test_judge.py, test_retro.py run with it on). The switch is per project with a global default, read fresh on
every call (a running build sees a change at once), and its on / off boundaries are logged."""
import json
from pathlib import Path

import pytest
import yaml

from gameanything import cli, delivery, devstatus as S, feedback as F, judge as J, projects, retro as R, study
from gameanything.conversation import CardError, Thread
from gameanything.ui import screens
from test_feedback import PLAN, png, say_at  # noqa: F401


@pytest.fixture
def proj():
    root = Path(projects.create("无人生还", "adaptation", lang="zh", game="minecraft")["path"])
    (root / "4_design").mkdir(exist_ok=True); (root / "4_design" / "world_plan.yaml").write_text(PLAN, encoding="utf-8")
    for m in ("m1", "m2"):
        play = root / "5_build" / m / "play"; play.mkdir(parents=True)
        (play / "play.yaml").write_text(yaml.safe_dump({"milestone": m, "video": "video.mp4", "chapters": [
            {"moment": "full", "title": "完整录像", "t": 0}, {"moment": "drawing", "title": "客厅", "t": 300}]}, allow_unicode=True), encoding="utf-8")
    return root


def _records(root):
    fr = "feedback/frames/m1_a.png"; png(root / fr)
    say_at(root, "这里有点简陋", "m1", 308.1, fr, at="2026-10-26T19:09:32")
    say_at(root, "这里这个客厅还是太简陋了", "m2", 330, at="2026-10-26T22:04:00")
    return F.capture(root, Thread(root).events())


def _log(root): return F.log_path(root)


# ---------------------------------------------------------------- the switch
def test_off_by_default_and_the_switch(proj, capsys):
    assert projects.settings()["study"] is False and study.on(proj) is False and study.state(proj)["source"] == "global"
    assert cli.main(["project", "set-study", F.project_id(proj)]) == 0 and "study=off (the global default)" in capsys.readouterr().out
    assert cli.main(["project", "set-study", F.project_id(proj), "on"]) == 0 and "study=on;" in capsys.readouterr().out
    assert study.on(proj) and "study: true" in (proj / "config" / "project.yaml").read_text(encoding="utf-8")
    assert projects.config_of(proj)["title"] == "无人生还"                                     # the rest of the config untouched
    ev = F.events(proj, "study"); assert [e["on"] for e in ev] == [True] and ev[0]["scope"] == "project"
    assert cli.main(["project", "set-study", F.project_id(proj), "off"]) == 0
    assert [e["on"] for e in F.events(proj, "study")] == [True, False]                       # where this project's study data stops
    F.log_event(proj, "record_state", id="f1"); assert [e["ev"] for e in F.events(proj)] == ["study", "study"]   # nothing more while off
    assert cli.main(["project", "set-study", F.project_id(proj), "default"]) == 0
    assert "study:" not in (proj / "config" / "project.yaml").read_text(encoding="utf-8") and len(F.events(proj, "study")) == 2


def test_global_default_and_project_override(proj, capsys):
    other = Path(projects.create("别的", "memory", lang="zh")["path"]); study.set_project(other, False)
    assert cli.main(["project", "settings", "--study", "on"]) == 0
    assert json.loads(capsys.readouterr().out)["study"] is True
    assert study.on(proj) and not study.on(other)                                             # her own `study: false` wins
    assert [e["scope"] for e in F.events(proj, "study")] == ["global"] and not _log(other).exists()
    study.set_global(False)
    assert not study.on(proj) and [e["on"] for e in F.events(proj, "study")] == [True, False]
    with pytest.raises(ValueError): study.set_project(proj, "yes")


def test_the_browser_settings_cannot_switch_it(proj):
    from gameanything.ui.manage import Manager
    m = Manager.__new__(Manager)
    assert m.settings({"study": True, "record_builds": False})["study"] is False and projects.settings()["record_builds"] is False


# ---------------------------------------------------------------- OFF: the product loop, nothing for the study
def test_off_records_and_cards_work_and_nothing_is_logged(proj):
    new = _records(proj); assert [r["id"] for r in new] == ["f1", "f2"]
    F.set_fields(proj, "f1", interpretation="客厅太简陋", cls="taste", kind="sparse_plain", certainty="low", target="客厅")
    c = F.card(proj, "confirm", ids=["f1"]); assert c["key"] == "fbc-f1" and c["items"][0]["image"].startswith("/media/feedback/frames/")
    F.confirm(proj, "f1", "corrected", "客厅要更像酒店"); F.link(proj, "f1", new_item="客厅要有酒店的奢华感")
    assert F.get(F.load(proj), "f1")["history"]                                                # the record keeps its own history
    assert not _log(proj).exists()                                                            # no metrics log at all
    assert F.metrics(proj)["records"] == 2                                                    # (the function still works for code that needs it)


def test_off_every_version_runs_the_full_loop_without_a_condition(proj):
    _records(proj)
    assert F.assign(proj, "m3") == "C4" and F.peek(proj, "m3") == "C4" and F.condition(proj, m="m3") == "C4"
    assert all(F.uses(proj, "m3", p) for p in F.USES) and not F.assignments(proj) and not _log(proj).exists()
    with pytest.raises(F.FeedbackError, match="研究模式没开"): F.condition(proj, "C1", m="m3")
    from gameanything import profile as P
    P.add("local", "场景要丰富、精致", kind="sparse_plain", by="her")
    b = F.brief(proj, m="m3")
    assert any("她的偏好 p1" in x for x in b["lines"]) and any("她已经说过 2 次" in x for x in b["lines"])   # the full brief
    assert P.load("local")["entries"][0]["used"] == 1 and not _log(proj).exists()             # last-used on her page; no retrieval event


def test_off_a_version_assigned_during_a_study_gets_the_full_loop(proj):
    study.set_project(proj, True); F.condition(proj, "C1", m="m3"); assert F.uses(proj, "m3", "verify") is False
    study.set_project(proj, False)
    assert F.peek(proj, "m3") == "C4" and all(F.uses(proj, "m3", p) for p in F.USES)            # nothing withheld once it is off


def test_off_running_build_reads_the_switch_fresh(proj):
    """agentd and the builder's commands re-read the config on every call: a build that started before the switch flips obeys it."""
    assert F.assign(proj, "m3") == "C4" and not F.assignments(proj)
    study.set_project(proj, True)
    name = F.assign(proj, "m3"); assert F.assignments(proj)["m3"]["name"] == name
    study.set_project(proj, False); assert F.peek(proj, "m3") == "C4"


def test_off_verification_critic_and_retro_run(proj):
    fr = "feedback/frames/m1_z.png"; png(proj / fr)
    say_at(proj, "这里穿模了", "m1", 10, fr, at="2026-10-26T19:10:08"); F.capture(proj, Thread(proj).events())
    F.link(proj, "f1", new_item="穿模"); S.set_item(proj, "r1", "done", build="m2", by="builder")
    lines = F.on_deliver(proj, "m2")
    assert any("预评" in t for _, t in lines) and any("没有在同一个画面复拍：f1" in t for _, t in lines)   # critic due, re-shoot asked
    assert [r["id"] for r in F.unverified(proj, "m2")] == ["f1"]
    rows = delivery.check(proj, "m2", probe=False); assert any("同一个画面复拍" in w for w in rows[0]["warnings"])
    r = R.critic_emit(proj, "m2"); assert r["skip"] is False and Path(r["request"]).is_file()
    Path(r["out"]).write_text(yaml.safe_dump({"predictions": [{"kind": "clipping", "p": 0.7, "text": "还会穿模"}]}, allow_unicode=True), encoding="utf-8")
    c = R.critic_collect(proj, "m2"); assert [p["kind"] for p in c["high"]] == ["clipping"]
    assert yaml.safe_load(R.critic_file(proj, "m2").read_text(encoding="utf-8"))["collected"]
    assert not any("预评" in t for _, t in F.on_deliver(proj, "m2"))
    assert "m1" in R.retro_todo(proj)                                                         # her m1 feedback awaits the retrospective
    e = R.retro_emit(proj, "m1"); assert Path(e["request"]).is_file()
    assert not _log(proj).exists()                                                            # all of it ran, none of it logged


def test_off_builder_start_note_still_has_the_retrospective(proj):
    from gameanything.builds import Builds
    _records(proj)
    b = Builds.__new__(Builds)
    r = {"milestone": "m3", "build_mode": "lab", "playtest_rounds": 1, "wall_hours": 1, "retro_todo": R.retro_todo(proj, before="m3")}
    t = b.user_prompt(r); assert "retrospective of m1, m2" in t and "study" not in t.lower()


def test_off_no_judge_no_card_no_labels(proj, tmp_path, capsys):
    _records(proj)
    with pytest.raises(J.JudgeError, match="研究模式没开"): J.consent_card(proj)
    with pytest.raises(J.JudgeError, match="研究模式没开"): J.emit(proj, "m")
    with pytest.raises(J.JudgeError, match="研究模式没开"): J.collect(proj)
    with pytest.raises(J.JudgeError, match="研究模式没开"): J.sample_sheet(proj)
    assert J.consent(proj)[0] is False
    with pytest.raises(F.FeedbackError, match="研究模式没开"): F.label_export(proj)
    card = {"kind": "permission", "key": J.CONSENT_KEY, "title": "x", "will_send": ["a"], "will_not_send": ["b"], "to": "c"}
    with pytest.raises(CardError, match="研究"): Thread(proj).card(card)                    # the resident cannot send it at all
    for w in ("judge", "metrics", "condition", "datacheck", "agreement", "label"):
        with pytest.raises(SystemExit, match="研究模式没开"): cli.main(["feedback", w, "--project", str(proj), "--export"] if w == "label" else ["feedback", w, "--project", str(proj)])
    with pytest.raises(SystemExit, match="研究模式没开"): cli.main(["feedback", "match", "--project", str(proj), "--m", "m2"])
    assert cli.main(["feedback", "show", "--project", str(proj)]) == 0                       # the product commands stay
    assert not (proj / "feedback" / "labels").exists() and not _log(proj).exists()


def test_off_panel_hidden_on_panel_and_owner_badge(proj):
    _records(proj)
    d = screens.feedback_state(proj, owner=True)
    assert d == {"study": False, "exists": True, "profile_on": 0}                            # no records, no metrics reach the page
    study.set_project(proj, True)
    d = screens.feedback_state(proj, owner=True); assert d["study"] and d["study_badge"] and len(d["records"]) == 2 and "metrics" in d
    assert screens.feedback_state(proj, owner=False)["study_badge"] is False
    app = (Path(screens.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
    assert "if (F && !F.study)" in app and "研究模式开着" in app


def test_on_judge_card_can_be_sent(proj):
    study.set_project(proj, True); _records(proj)
    ev = Thread(proj).card(J.consent_card(proj)); assert ev["card"]["key"] == J.CONSENT_KEY
