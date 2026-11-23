"""Builds delivered as folders only (2026-10-24: feature m3 / m3b, sims4-flying-car round2): the 试玩 page still lists and plays them,
`gameanything build deliver` registers + fixes them in one go, `gameanything build check` says what is missing."""
import os
from pathlib import Path

import pytest
import yaml

from gameanything import cli, delivery, projects
from gameanything.ui import Project, screens

PLAN = """# the plan (agent's file)
world_plan:
  title: "香港美食"
  milestones:   # rounds
    m1:
      name: 第一版 茶餐厅
      status: built
      at: "2026-10-20T10:00:00"   # first one
      what: "茶餐厅"
    m2:
      name: 第二版
      status: building
  # end of milestones
"""


@pytest.fixture
def proj(monkeypatch):
    root = Path(projects.create("香港美食", "feature", lang="zh")["path"])
    (root / "4_design").mkdir(exist_ok=True); (root / "4_design" / "world_plan.yaml").write_text(PLAN, encoding="utf-8")
    monkeypatch.setattr(delivery, "probe_video", lambda f: (f.is_file() and f.stat().st_size > 0, "fake video"))
    return root


def play(root, m, video=True, yml=None):
    d = root / "5_build" / m / "play"; d.mkdir(parents=True, exist_ok=True)
    if video: (d / "video.mp4").write_bytes(b"\0" * 64)
    if yml is not None: (d / "play.yaml").write_text(yml, encoding="utf-8")
    return d


def test_rounds_list_unregistered_builds(proj):
    play(proj, "m1", yml="video: video.mp4\nchapters:\n- {moment: a, title: A, t: 0}\n")
    old = play(proj, "round1"); new = play(proj, "round2")                     # folders only: a video, no play.yaml, no milestone
    (proj / "5_build" / "meshy").mkdir()                                         # not a build
    os.utime(old, (1_700_000_000, 1_700_000_000)); os.utime(new, (1_900_000_000, 1_900_000_000))
    rs = screens.Data(proj).rounds("zh"); by = {r["m"]: r for r in rs}
    assert "meshy" not in by and by["round2"]["state"] == "done" and by["round2"]["play"] and by["round2"]["name"] == "round2"
    assert by["round2"]["sub"] == "做好了 · 还没登记"
    done = [r["m"] for r in rs if r["state"] == "done"]
    assert done.index("round2") < done.index("m1") < done.index("round1")      # newest first: folder time for unregistered builds
    assert {r["m"]: r for r in screens.Data(proj, "en").rounds("en")}["round2"]["sub"] == "Built · not registered yet"
    assert [r["m"] for r in screens.shell(proj, "zh")["rounds"] if r["state"] == "done"] == done
    assert Project(proj).builds()[-1] == "round2"                                 # /api/play without ?m= opens the newest


def test_api_play_synthesizes_play_yaml(proj):
    play(proj, "round2")
    s = Project(proj).play_state("round2", "zh")
    assert s["play"]["video"] == "video.mp4" and s["play"]["chapters"] == [{"moment": "full", "title": "完整录像", "t": 0}]
    assert "round2" in s["milestones"]
    assert Project(proj).play_state("round2", "en")["play"]["chapters"][0]["title"] == "Full recording"
    assert not (proj / "5_build" / "round2" / "play" / "play.yaml").exists()      # the page never writes it
    screens.day(proj, "zh")                                                        # the day page reads the same builds


@pytest.mark.parametrize("chapters", ["chapters: oops", "chapters: [{title: no t}, {moment: b, t: x}, just a title, 5, {moment: c, title: C, t: 3}]",
                                      "chapters: {a: 0, b: {title: B, t: 9}}", "chapters:", "checks: [1, {item: x}]\nchapters: [{t: 2}]", "- not a mapping"])
def test_malformed_play_yaml_is_normalized(proj, chapters):
    play(proj, "m1", yml=chapters + "\n")
    s = Project(proj).play_state("m1", "zh")
    ch = s["play"]["chapters"]
    assert ch and all(isinstance(c["moment"], str) and isinstance(c["title"], str) and isinstance(c["t"], (float, int)) for c in ch)
    assert [c["t"] for c in ch] == sorted(c["t"] for c in ch)
    assert all(isinstance(c, dict) and c.get("id") for c in s["play"].get("checks") or [])
    screens.day(proj, "zh"); screens.Data(proj).rounds("zh")


def test_normalize_keeps_good_chapters():
    ch = [{"moment": "a", "title": "A", "t": 0}, {"moment": "b", "title": "B", "t": 12.5, "extra": 1}]
    assert delivery.normalize_chapters(ch) == ch and delivery.chapter_problems(ch) == []
    assert delivery.chapter_problems([{"moment": "a"}]) == ["chapters[0] 缺 title", "chapters[0] 缺 t（从录像开头算的秒数）"]


def run(*args):
    return cli.main(["build", *args])


def test_deliver_registers_and_writes_play_yaml_idempotently(proj, capsys):
    play(proj, "m3")
    assert run("deliver", "--project", str(proj), "--m", "m3", "--name", "第三版 3D 菜品", "--what", "3D 菜") == 0
    wp = proj / "4_design" / "world_plan.yaml"; text = wp.read_text(encoding="utf-8")
    assert "# the plan (agent's file)" in text and "# first one" in text and "# end of milestones" in text and "# rounds" in text
    m3 = yaml.safe_load(text)["world_plan"]["milestones"]["m3"]
    assert m3["name"] == "第三版 3D 菜品" and m3["status"] == "built" and m3["what"] == "3D 菜" and m3["at"]
    py = yaml.safe_load((proj / "5_build" / "m3" / "play" / "play.yaml").read_text(encoding="utf-8"))
    assert py == {"milestone": "m3", "video": "video.mp4", "chapters": [{"moment": "full", "title": "完整录像", "t": 0}]}
    files = {f: f.read_bytes() for f in (wp, proj / "5_build" / "m3" / "play" / "play.yaml")}
    assert run("deliver", "--project", str(proj), "--m", "m3") == 0               # again: nothing changes
    assert {f: f.read_bytes() for f in files} == files
    out = capsys.readouterr().out
    assert "交付好了" in out and "已登记" in out
    by = {r["m"]: r for r in screens.Data(proj).rounds("zh")}
    assert by["m3"]["name"].endswith("3D 菜品") and by["m3"]["status"] == "built"


def test_deliver_updates_a_building_milestone_and_keeps_fields(proj):
    play(proj, "m2", yml="# notes\nchapters:\n- {moment: a, title: A, t: 0}\n- {moment: b, title: B, t: 30}\nchecks:\n- {id: c1, item: x, verdict: ok, note: ''}\n")
    assert run("deliver", "--project", str(proj), "--m", "m2") == 0
    plan = yaml.safe_load((proj / "4_design" / "world_plan.yaml").read_text(encoding="utf-8"))["world_plan"]
    assert plan["milestones"]["m2"]["status"] == "built" and plan["milestones"]["m2"]["name"] == "第二版" and plan["milestones"]["m2"]["at"]
    assert plan["milestones"]["m1"] == {"name": "第一版 茶餐厅", "status": "built", "at": "2026-10-20T10:00:00", "what": "茶餐厅"}
    t = (proj / "5_build" / "m2" / "play" / "play.yaml").read_text(encoding="utf-8")
    assert t.startswith("# notes\nmilestone: \"m2\"\nvideo: \"video.mp4\"\n") and len(yaml.safe_load(t)["chapters"]) == 2


def test_deliver_with_chapters_file(proj, tmp_path):
    play(proj, "m4"); f = tmp_path / "final.chapters.yaml"
    f.write_text("chapters:\n- {moment: gate, title: 园门, t: 0}\n- {moment: hall, title: 大厅, t: 17.5}\n", encoding="utf-8")
    assert run("deliver", "--project", str(proj), "--m", "m4", "--chapters", str(f)) == 0
    assert [c["moment"] for c in yaml.safe_load((proj / "5_build/m4/play/play.yaml").read_text(encoding="utf-8"))["chapters"]] == ["gate", "hall"]


def test_deliver_fails_without_video(proj, capsys):
    before = (proj / "4_design" / "world_plan.yaml").read_bytes()
    play(proj, "m5", video=False)
    assert run("deliver", "--project", str(proj), "--m", "m5") == 1
    assert "没有录像" in capsys.readouterr().out
    assert (proj / "4_design" / "world_plan.yaml").read_bytes() == before and not (proj / "5_build/m5/play/play.yaml").exists()
    (proj / "5_build/m5/play/video.mp4").write_bytes(b"")                           # an empty file does not play
    assert run("deliver", "--project", str(proj), "--m", "m5") == 1
    assert run("deliver", "--project", str(proj), "--m", "nope") == 1               # no folder at all


def test_deliver_fails_on_bad_play_yaml_and_missing_stills(proj, capsys):
    play(proj, "m6", yml="video: video.mp4\nchapters:\n- {moment: a, t: 0}\n")
    assert run("deliver", "--project", str(proj), "--m", "m6") == 1 and "缺 title" in capsys.readouterr().out
    play(proj, "m7", yml="video: video.mp4\nchapters: [{moment: a, title: A, t: 0}]\nstills: [still_a.png]\nscenes: [{moment: a, file: s.png}]\n")
    assert run("deliver", "--project", str(proj), "--m", "m7") == 1
    out = capsys.readouterr().out; assert "stills: still_a.png" in out and "scenes: s.png" in out
    (proj / "5_build/m7/play/still_a.png").write_bytes(b"x"); (proj / "5_build/m7/play/scenes").mkdir(); (proj / "5_build/m7/play/scenes/s.png").write_bytes(b"x")
    assert run("deliver", "--project", str(proj), "--m", "m7") == 0
    play(proj, "m8", yml="video: [unclosed\n")
    assert run("deliver", "--project", str(proj), "--m", "m8") == 1 and "YAML" in capsys.readouterr().out


def test_check_lists_what_is_missing(proj, capsys):
    play(proj, "m1", yml="video: video.mp4\nchapters: [{moment: a, title: A, t: 0}]\n")
    play(proj, "round2"); (proj / "5_build" / "meshy").mkdir()
    assert run("check", "--project", str(proj)) == 1
    out = capsys.readouterr().out
    assert "OK m1" in out and "NO round2" in out and "没有 play.yaml" in out and "world_plan.yaml 里没有这个里程碑" in out
    assert "meshy" in out and "gameanything build deliver" in out
    rows = {r["m"]: r for r in delivery.check(proj)}
    assert rows["m1"]["ok"] and rows["m1"]["warnings"] == ["play.yaml 没写 milestone"] and rows["meshy"].get("skip") and rows["meshy"]["ok"]
    assert "m2" not in rows                                                       # building, no folder yet: not a problem
    assert run("deliver", "--project", str(proj), "--m", "round2", "--name", "第 13 版") == 0
    assert run("check", "--project", str(proj)) == 0 and "全部交付好了" in capsys.readouterr().out


def test_status_done_warns_when_not_delivered(proj, capsys):
    play(proj, "round2")
    assert run("status", "--project", str(proj), "--m", "round2", "--done") == 0
    assert "gameanything build deliver" in capsys.readouterr().err
    assert run("deliver", "--project", str(proj), "--m", "round2") == 0; capsys.readouterr()
    assert run("status", "--project", str(proj), "--m", "round2", "--done") == 0
    assert "deliver" not in capsys.readouterr().err


def test_probe_video_real_file(tmp_path):
    f = tmp_path / "e.mp4"; f.write_bytes(b"")
    assert delivery.probe_video(f)[0] is False and delivery.probe_video(tmp_path / "none.mp4")[0] is False
