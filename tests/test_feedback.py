"""Her feedback as records (gameanything/feedback.py, `gameanything feedback …`, docs/feedback-loop.md): records from the channels (`chat read`), the
heuristic labeller, the lifecycle (reading, confirmation, STATUS link, fixed by set-item), repeats and the metrics, the backfill, same-anchor
verification (pairs, the chapter-offset frame, deliver / check / result card), the cards, the brief and its retrieval log, run usage."""
import json
from pathlib import Path

import pytest
import yaml

from gameanything import cli, delivery, devstatus as S, feedback as F, projects
from gameanything.conversation import Thread, check_card

PLAN = """world_plan:
  milestones:
    m1: {name: 第一版, status: built, at: "2026-10-26T18:00:00"}
    m2: {name: 第二版, status: built, at: "2026-10-26T21:00:00"}
    m3: {name: 第三版, status: next}
"""


def png(p: Path, color=(200, 30, 30), size=(64, 36)):
    from PIL import Image
    p.parent.mkdir(parents=True, exist_ok=True); Image.new("RGB", size, color).save(p); return p


@pytest.fixture(autouse=True)
def study_on(isolated):
    """These tests are the study's behaviour (study mode on: conditions, metrics log, panel); tests/test_study.py has the default, off."""
    from gameanything import study
    study.set_global(True, by="test")


@pytest.fixture
def proj():
    root = Path(projects.create("无人生还", "adaptation", lang="zh", game="minecraft")["path"])
    (root / "4_design").mkdir(exist_ok=True); (root / "4_design" / "world_plan.yaml").write_text(PLAN, encoding="utf-8")
    (root / "3_remember").mkdir(exist_ok=True)
    (root / "3_remember" / "adaptation.yaml").write_text(yaml.safe_dump({"places": [{"id": "p-drawing", "name": "客厅"}, {"id": "p-up", "name": "楼上走廊与客房"}]},
                                                                         allow_unicode=True), encoding="utf-8")
    for m in ("m1", "m2"):
        play = root / "5_build" / m / "play"; play.mkdir(parents=True)
        (play / "play.yaml").write_text(yaml.safe_dump({"milestone": m, "video": "video.mp4", "chapters": [
            {"moment": "full", "title": "完整录像", "t": 0}, {"moment": "drawing", "title": "客厅", "t": 300}]}, allow_unicode=True), encoding="utf-8")
    return root


def say_at(root, text, m, t, frame=None, at=None):
    """Her comment on the 试玩 page at second t (what the UI writes: the frame under feedback/frames/, a thread event with video context)."""
    ctx = [{"kind": "video", "m": m, "t": t}]
    if frame: ctx[0]["frame"] = frame
    ev = Thread(root).user_text(text, ctx)
    if at: _retime(root, ev["id"], at)
    return ev


def _retime(root, eid, at):
    T = Thread(root); lines = []
    for e in T.events():
        if e["id"] == eid: e["at"] = at
        lines.append(json.dumps(e, ensure_ascii=False))
    T.log.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(*a): return cli.main(list(a))


# ---------------------------------------------------------------- labels, targets, versions
def test_heuristic_labels():
    L = F.heuristic_label
    assert L("这里有点简陋 没有那种酒店等感觉")["kind"] == "sparse_plain" and L("这里有点简陋")["class"] == "taste"
    assert L("这里穿模了") == {"kind": "clipping", "class": "bug", "marker": False}
    assert L("这里周围飘着的那些珠子 白色方块 黄色方块是啥") == {"kind": "unreadable_object", "class": "question", "marker": False}
    assert L("这里这个客厅还是太简陋了")["marker"] is True
    assert L("卡片里看不到图")["kind"] == "ui_delivery" and L("游戏界面又报错了")["kind"] == "game_error"
    assert L("我有MESHY的API可以生产3D资产啊")["kind"] == "other"
    assert set(k for k, _, _ in F.RULES) <= set(F.KINDS)


def test_targets_and_versions(proj):
    tg = F.targets(proj)
    assert F.find_target("这里这个客厅还是太简陋了", tg) == "客厅" and F.find_target("楼上那几扇门看不清", tg) == "楼上走廊与客房"
    assert F.find_target("这里", tg) is None
    vs = F.versions(proj); assert [v["m"] for v in vs] == ["m1", "m2"]
    assert F.version_at(vs, "2026-10-26T19:00:00") == "m1" and F.version_at(vs, "2026-10-26T17:00:00") is None
    assert F.chapter_at(proj, "m1", 308.1)["moment"] == "drawing" and F.chapter_at(proj, "m1", 10)["moment"] == "full"


# ---------------------------------------------------------------- channels -> records
def test_chat_read_creates_records_for_anchored_words(proj, capsys):
    fr = "feedback/frames/m1_x.png"; png(proj / fr)
    say_at(proj, "这里有点简陋 没有那种酒店等感觉", "m1", 308.1, fr)
    Thread(proj).user_text("进度如何了")                                              # logistics: no record
    Thread(proj).user_text("（页面操作）", auto=True)                                   # page line, not her words
    Thread(proj).user_text("参考图", [{"kind": "file", "path": "0_inbox/a.jpg"}])        # a picture she attached
    Thread(proj).user_text("这个房间", [{"kind": "region", "m": "m1", "file": "s1.png", "box": [0.1, 0.2, 0.5, 0.6]}])
    assert run("chat", "read", "--project", str(proj)) == 0
    out = capsys.readouterr().out
    rs = F.load(proj); assert [r["modality"] for r in rs] == ["video_moment", "image", "image_region"]
    r = rs[0]
    assert r["words"] == "这里有点简陋 没有那种酒店等感觉" and r["state"] == "new" and r["milestone"] == "m1" and r["source"] == "playtest"
    assert r["anchor"]["frame"] == fr and r["anchor"]["video"] == {"m": "m1", "t": 308.1} and r["anchor"]["chapter"]["moment"] == "drawing"
    assert r["kind"] == "sparse_plain" and r["labelled_by"] == "heuristic" and "新记录 f1" in out
    assert rs[2]["anchor"]["image"] == "5_build/m1/play/s1.png" and rs[2]["anchor"]["region"] == [0.1, 0.2, 0.5, 0.6]
    assert run("chat", "read", "--project", str(proj)) == 0 and len(F.load(proj)) == 3                       # read again: nothing doubled
    ev = [e for e in F.events(proj) if e["ev"] == "record_created"]; assert len(ev) == 3


def test_add_from_event_keeps_her_words(proj):
    e = Thread(proj).user_text("而且文字要改成英文。另外我们的场景能不能做的更丰富宏大？")
    r1 = F.add(proj, "而且文字要改成英文", e["id"], interpretation="游戏里所有文字改成英文", cls="request", kind="text_language", certainty="high")
    r2 = F.add(proj, "另外我们的场景能不能做的更丰富宏大", e["id"], cls="taste", kind="sparse_plain")
    assert r1["event"] == r2["event"] == e["id"] and r1["state"] == "interpreted" and r2["state"] == "new"
    with pytest.raises(F.FeedbackError, match="原话"): F.add(proj, "改成中文", e["id"])               # not her words
    with pytest.raises(F.FeedbackError, match="--kind"): F.add(proj, None, e["id"], kind="weird")
    a = Thread(proj).agent_text("好的")
    with pytest.raises(F.FeedbackError, match="不是她说的话"): F.add(proj, None, a["id"])


# ---------------------------------------------------------------- lifecycle
def test_lifecycle_confirm_link_fixed_verify_verdict(proj):
    F.condition(proj, "C4")                                                              # the full loop (outside the blind schedule)
    fr = "feedback/frames/m2_x.png"; png(proj / fr)
    say_at(proj, "这里周围飘着的那些珠子 白色方块 黄色方块是啥", "m2", 320, fr, at="2026-10-26T22:00:00"); Thread(proj).read()
    F.capture(proj, Thread(proj).events())
    r = F.set_fields(proj, "f1", interpretation="浮在空中的方块像掉落物，删掉", cls="question", kind="unreadable_object", certainty="low")
    assert r["state"] == "confirming"
    c = F.card(proj, "confirm"); check_card(dict(c)); assert c["key"] == "fbc-f1" and c["items"][0]["image"] == "/media/" + fr
    with pytest.raises(F.FeedbackError, match="interpretation"): F.confirm(proj, "f1", "corrected")
    r = F.confirm(proj, "f1", "corrected", "那是水晶吊灯，从这个角度看像浮块：让吊灯从门口看得出是一盏灯")
    assert r["state"] == "interpreted" and r["confirm"]["state"] == "corrected" and any(h.get("interpretation_was") for h in r["history"])
    r = F.link(proj, "f1", new_item="客厅吊灯从门口机位看得出是一盏灯")
    d, _ = S.load(proj); it = d["items"][0]
    assert r["state"] == "open" and r["status_item"] == it["id"] and it["source"].startswith("feedback:e_")
    S.set_item(proj, it["id"], "done", build="m3", by="builder", evidence="第 2 轮 3:40")
    r = F.get(F.load(proj), "f1"); assert r["state"] == "fixed" and r["resolution"]["m"] == "m3"
    assert [x["id"] for x in F.unverified(proj, "m3")] == ["f1"]
    after = png(proj / "5_build" / "m3" / "play" / "verify" / "f1_after.png", (20, 120, 40))
    r = F.verify(proj, "f1", "m3", after); v = r["verification"]
    assert r["state"] == "verifying" and v["method"] == "reshoot" and (proj / v["pair"]).is_file() and F.unverified(proj, "m3") == []
    vc = F.card(proj, "verify", "m3"); check_card(dict(vc)); assert vc["key"] == "verify-m3" and vc["items"][0]["image"].endswith("f1_pair.png")
    assert F.verdict(proj, "f1", True)["state"] == "closed"
    m = F.metrics(proj); assert m["verification"]["paired"] == 1 and m["verification"]["her_ok"] == 1 and m["interpretation"]["corrected"] == 1
    st = [e["to"] for e in F.events(proj, "record_state") if e["id"] == "f1"]
    assert st == ["new", "confirming", "interpreted", "open", "fixed", "verifying", "closed"]


def test_repeat_reopens_and_metrics(proj):
    say_at(proj, "这里有点简陋 没有那种酒店等感觉", "m1", 308.1, at="2026-10-26T19:09:32")
    say_at(proj, "这里穿模了", "m1", 380, at="2026-10-26T19:10:08")
    say_at(proj, "这里这个客厅还是太简陋了", "m2", 330, at="2026-10-26T22:04:00")
    say_at(proj, "这个房子有点简陋", "m2", 700, at="2026-10-26T22:05:00")
    F.capture(proj, Thread(proj).events())
    F.set_fields(proj, "f1", interpretation="客厅太简陋", target="客厅", certainty="high"); F.link(proj, "f1", new_item="客厅要有酒店的奢华感")
    S.set_item(proj, "r1", "done", build="m2", by="builder")
    assert F.get(F.load(proj), "f1")["state"] == "fixed"
    r = F.set_fields(proj, "f3", interpretation="客厅还是太简陋", certainty="high")
    assert r["repeat_of"] == ["f1"] and F.get(F.load(proj), "f1")["state"] == "reopened"
    m = F.metrics(proj)
    assert m["complaints"] == 4 and m["by_kind"] == {"sparse_plain": 3, "clipping": 1}
    assert m["rfr_strict"] == {"k": 1, "n": 2, "rate": 0.5} and m["rfr_loose"]["k"] == 2          # f4 (房子) is only a loose repeat
    assert [(v["m"], v["complaints"], v["repeats_strict"]) for v in m["versions"]] == [("m1", 2, 0), ("m2", 2, 1)]
    assert run("feedback", "metrics", "--project", str(proj)) == 0


def test_backfill_on_a_copy(proj):
    """Backfill: anchored words always, plain text only when it is a complaint; STATUS links by feedback:<event> and by m:ss in the item text."""
    say_at(proj, "这里有点简陋 没有那种酒店等感觉", "m1", 308.1, "feedback/frames/a.png", at="2026-10-26T19:09:32")
    say_at(proj, "这里穿模了", "m1", 380, at="2026-10-26T19:10:08")
    e3 = Thread(proj).user_text("而且文字要改成英文"); _retime(proj, e3["id"], "2026-10-26T19:11:30")
    e4 = Thread(proj).user_text("进度如何了"); _retime(proj, e4["id"], "2026-10-26T19:12:00")
    say_at(proj, "这里这个客厅还是太简陋了", "m2", 330, at="2026-10-26T22:04:00")
    S.set_item(proj, None, "done", "客厅要有欧式酒店的奢华感：现在太简陋(她在试玩 5:08 指出)", build="m2", by="builder")
    S.set_item(proj, None, "partial", "人物穿模要修", build="m2", by="builder", source=f"feedback:{Thread(proj).events()[1]['id']}")
    S.set_item(proj, None, "todo", "全部文字英文", source=f"feedback:{e3['id']}")
    r = F.backfill(proj)
    assert r["records"] == 4 and r["skipped_not_feedback"] == 1 and r["linked"] == 3 and r["fixed"] == 1
    rs = F.load(proj)
    assert rs[0]["status_item"] == "r1" and rs[0]["anchor"]["target"] == "客厅" and rs[0]["state"] == "fixed" and rs[0]["source"] == "backfill"
    assert rs[1]["state"] == "in_progress" and rs[2]["milestone"] == "m1" and rs[2]["modality"] == "text"
    assert rs[3]["repeat_of"] == ["f1"] and r["rfr_strict"] == {"k": 1, "n": 1, "rate": 1.0}
    assert rs[0]["labels"]["heuristic"]["kind"] == "sparse_plain"
    again = F.backfill(proj); assert again["added"] == 0 and again["already_recorded"] == 4 and len(F.load(proj)) == 4     # idempotent
    assert run("feedback", "backfill", "--project", str(proj)) == 0 and len(F.load(proj)) == 4
    assert [e["added"] for e in F.events(proj, "backfill")] == [4, 0, 0]
    assert all(e.get("backfill") for e in F.events(proj, "record_state"))


def test_backfill_on_a_live_project_merges(proj):
    """Live: records `chat read` made since the deploy (and her confirmations) are kept as they are; only the older history is added."""
    say_at(proj, "这里有点简陋 没有那种酒店等感觉", "m1", 308.1, at="2026-10-26T19:09:32")
    e2 = Thread(proj).user_text("而且文字要改成英文"); _retime(proj, e2["id"], "2026-10-26T19:11:30")
    say_at(proj, "这里周围飘着的那些珠子 白色方块 黄色方块是啥", "m2", 320, at="2026-10-26T22:00:00")
    live = F.capture(proj, [Thread(proj).events()[-1]])                                    # the live chat read saw only the newest one
    F.set_fields(proj, live[0]["id"], interpretation="浮块是什么", cls="question", kind="unreadable_object", certainty="low")
    F.confirm(proj, live[0]["id"], "corrected", "是水晶吊灯", event="e_x")
    before = F.get(F.load(proj), "f1")
    assert F.backfill(proj, dry_run=True) == {"would_add": 2, "existing": 1, "already_recorded": 1, "skipped_not_feedback": 0}
    r = F.backfill(proj); rs = F.load(proj)
    assert r["added"] == 2 and r["already_recorded"] == 1 and [x["id"] for x in rs] == ["f1", "f2", "f3"]
    assert rs[0] == before and rs[0]["confirm"]["state"] == "corrected" and rs[0]["interpretation"] == "是水晶吊灯"
    assert {x["event"] for x in rs[1:]} == {Thread(proj).events()[0]["id"], e2["id"]} and all(x["source"] == "backfill" for x in rs[1:])
    bk = Path(r["backup"]); assert (bk / "records.yaml").is_file() and "f1" in (bk / "records.yaml").read_text(encoding="utf-8")
    assert F.backfill(proj)["added"] == 0 and len(F.load(proj)) == 3


# ---------------------------------------------------------------- verification by chapter offset, deliver, check, result card
def _video(p: Path, seconds=4, fps=5):
    import av
    import numpy as np
    p.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(p), "w") as c:
        s = c.add_stream("mpeg4", rate=fps); s.width, s.height, s.pix_fmt = 64, 48, "yuv420p"
        for i in range(seconds * fps):
            img = np.full((48, 64, 3), (i * 10) % 255, dtype=np.uint8)
            for pk in s.encode(av.VideoFrame.from_ndarray(img, format="rgb24")): c.mux(pk)
        for pk in s.encode(): c.mux(pk)
    return p


def test_chapter_offset_pair_at_deliver(proj):
    F.condition(proj, "C4")                                                              # the full loop (outside the blind schedule)
    pytest.importorskip("av")
    fr = "feedback/frames/m1_y.png"; png(proj / fr)
    say_at(proj, "这里有点简陋", "m1", 301.5, fr, at="2026-10-26T19:09:32"); F.capture(proj, Thread(proj).events())
    F.link(proj, "f1", new_item="客厅更丰富")
    play = proj / "5_build" / "m3" / "play"; _video(play / "video.mp4")
    (play / "play.yaml").write_text(yaml.safe_dump({"milestone": "m3", "video": "video.mp4", "chapters": [
        {"moment": "full", "title": "完整录像", "t": 0}, {"moment": "drawing", "title": "客厅", "t": 1}]}, allow_unicode=True), encoding="utf-8")
    S.set_item(proj, "r1", "done", build="m3", by="builder")
    t, vid = F._offset_t(proj, F.get(F.load(proj), "f1"), "m3"); assert t == pytest.approx(2.5) and vid.name == "video.mp4"
    r = delivery.deliver(proj, "m3", "第三版")
    assert r["ok"], r["lines"]
    assert any("同一画面复拍：1/1" in t_ for _, t_ in r["lines"])
    rec = F.get(F.load(proj), "f1"); assert rec["verification"]["method"] == "chapter_offset" and (proj / rec["verification"]["pair"]).is_file()
    v = yaml.safe_load((play / "verify.yaml").read_text(encoding="utf-8")); assert v["pairs"][0]["id"] == "f1"
    c = S.result_card(proj, "m3"); assert any("同一画面复拍 1 条" in s for s in c["stats"]) and c["image"].endswith("f1_pair.png")
    assert [e["ev"] for e in F.events(proj) if e["ev"] == "delivered"] == ["delivered"]


def test_listed_when_no_anchor_can_be_reshot(proj):
    F.condition(proj, "C4")                                                              # the full loop (outside the blind schedule)
    fr = "feedback/frames/m1_z.png"; png(proj / fr)
    say_at(proj, "这里穿模了", "m1", 10, fr, at="2026-10-26T19:10:08"); F.capture(proj, Thread(proj).events())   # chapter `full`: no offset
    F.link(proj, "f1", new_item="穿模"); S.set_item(proj, "r1", "done", build="m2", by="builder")
    lines = F.on_deliver(proj, "m2"); assert any(k == "warn" and "没有在同一个画面复拍：f1" in t for k, t in lines)
    rows = delivery.check(proj, "m2", probe=False); assert any("同一个画面复拍" in w for w in rows[0]["warnings"])
    assert run("feedback", "pairs", "--project", str(proj), "--m", "m2", "--todo") == 0


# ---------------------------------------------------------------- brief, conditions, label sheets, usage
def test_brief_logs_retrieval_and_obeys_condition(proj, capsys):
    from gameanything import profile as P
    say_at(proj, "这里有点简陋", "m1", 308.1, at="2026-10-26T19:09:32"); say_at(proj, "还是很简陋", "m2", 330, at="2026-10-26T22:04:00")
    F.capture(proj, Thread(proj).events())
    P.add("local", "场景要丰富、精致", kind="sparse_plain", by="her")
    F.condition(proj, "C4", m="m3")                                                     # the coordinator fixes m3 before the schedule does
    r = F.brief(proj, budget=5, m="m3")
    assert r["condition"] == "C4" and any("她的偏好 p1" in x for x in r["lines"]) and any("她已经说过 2 次" in x for x in r["lines"])
    ev = F.events(proj, "retrieval")[-1]; assert ev["m"] == "m3" and {x["type"] for x in ev["entries"]} >= {"preference", "kind"}
    assert P.load("local")["entries"][0]["used"] == 1
    with pytest.raises(F.FeedbackError, match="已经定了"): F.condition(proj, "C1", m="m3")   # one condition per version
    F.condition(proj, "C1", m="m4"); assert not any("偏好" in x for x in F.brief(proj, m="m4")["lines"])
    F.condition(proj, "C0", m="m5"); assert F.brief(proj, m="m5")["lines"] == []
    with pytest.raises(F.FeedbackError): F.condition(proj, "C9")
    assert run("feedback", "brief", "--project", str(proj)) == 0


def test_rule_hits(proj):
    say_at(proj, "这里有点简陋", "m1", 308.1, at="2026-10-26T19:09:32"); say_at(proj, "这里穿模了", "m2", 50, at="2026-10-26T22:04:00")
    F.capture(proj, Thread(proj).events())
    F.log_event(proj, "retrieval", m="m2", entries=[{"type": "kind", "id": "sparse_plain", "kind": "sparse_plain"}, {"type": "lesson", "id": "x", "kind": "camera"}])
    h = F.metrics(proj)["rule_hits"]; assert h == {"retrieved": 2, "applicable": 1, "hits": 1, "rate": 1.0}      # no 简陋 on m2 after it was shown


def test_label_sheet_round_trip(proj, tmp_path):
    say_at(proj, "这里有点简陋", "m1", 308.1, at="2026-10-26T19:09:32"); F.capture(proj, Thread(proj).events())
    f = F.label_export(proj); row = json.loads(f.read_text(encoding="utf-8").splitlines()[0]); assert row["words"] == "这里有点简陋" and row["kind"] is None
    g = tmp_path / "judge.jsonl"; g.write_text(json.dumps({"id": "f1", "class": "taste", "kind": "mood"}) + "\n", encoding="utf-8")
    assert F.label_import(proj, g, "judge") == 1
    r = F.get(F.load(proj), "f1"); assert r["kind"] == "sparse_plain" and r["labels"]["judge"]["kind"] == "mood" and r["labels"]["heuristic"]["kind"] == "sparse_plain"
    assert F.relabel([r], "judge")[0]["kind"] == "mood" and F.relabel([r], "human")[0]["_unlabelled"]
    assert F.label_import(proj, g, "human", name="anna", apply=True) == 1
    r = F.get(F.load(proj), "f1"); assert r["kind"] == "mood" and r["labelled_by"] == "human" and "human:anna" in r["labels"]


def test_run_usage(tmp_path):
    log = tmp_path / "run.jsonl"
    log.write_text("\n".join(json.dumps(x) for x in [{"type": "assistant", "message": {}},
                   {"type": "result", "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100}, "total_cost_usd": 0.5, "num_turns": 3, "duration_ms": 1000}]),
                   encoding="utf-8")
    u = F.run_usage(log); assert u["usage"]["input_tokens"] == 10 and u["usage"]["cache_read_input_tokens"] == 100 and u["cost_usd"] == 0.5 and u["num_turns"] == 3
    assert F.run_usage(tmp_path / "missing") == {}


def test_broken_records_file_is_never_overwritten(proj):
    F.path(proj).parent.mkdir(parents=True, exist_ok=True); F.path(proj).write_text("records: [\n", encoding="utf-8")
    assert F.load(proj) == []
    with pytest.raises(F.FeedbackError, match="读不了"): F.add(proj, "x")


# ---------------------------------------------------------------- blind conditions
def test_blind_schedule_is_abba_reproducible_and_logged(proj):
    seq = [F.scheduled("p-x", i) for i in range(8)]
    assert seq[:4] in (["C1", "C4", "C4", "C1"], ["C4", "C1", "C1", "C4"]) and seq[4:] == seq[:4]
    assert {F.scheduled(f"p{i}", 0) for i in range(20)} == {"C1", "C4"}                            # counterbalanced across projects
    got = [F.assign(proj, m) for m in ("m1", "m2", "m3", "m4")]
    assert got == [F.scheduled(F.project_id(proj), i) for i in range(4)]
    assert F.assign(proj, "m2") == got[1] and len(F.events(proj, "condition")) == 4                  # assigned once
    ev = F.assignments(proj)["m3"]; assert ev["how"] == "schedule" and ev["schedule"] == F.SCHEDULE and ev["index"] == 2
    assert "condition" not in F.metrics(proj)                                                     # the page never gets it
    F.condition(proj, "C4"); assert F.assign(proj, "m9") == "C4" and F.assignments(proj)["m9"]["how"] == "manual_project"


def test_condition_gates_verification(proj):
    fr = "feedback/frames/m1_z.png"; png(proj / fr)
    say_at(proj, "这里穿模了", "m1", 10, fr, at="2026-10-26T19:10:08"); F.capture(proj, Thread(proj).events())
    F.link(proj, "f1", new_item="穿模"); S.set_item(proj, "r1", "done", build="m2", by="builder")
    F.condition(proj, "C1", m="m2")
    assert F.unverified(proj, "m2") == [] and F.on_deliver(proj, "m2") == []
    assert F.events(proj, "delivered")[-1]["verify_step"] is False
    assert not any("复拍" in x for x in S.result_card(proj, "m2")["stats"])
