"""Optional features (extras.py, 2026-11-01): a missing one is skipped with a note, the install waits for her yes on a card."""
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from gameanything import cli, extras, projects
from gameanything.conversation import Thread

CJK = re.compile(r"[　-〿一-鿿＀-￯]")


@pytest.fixture
def proj():
    return Path(projects.create("可选功能", "memory")["path"])


def _ok(rc=0, out="installed"): return lambda cmd, **k: SimpleNamespace(returncode=rc, stdout=out, stderr="")


def test_command_uses_uv_into_this_python_else_pip():
    assert extras.command("transcribe", which=lambda n: "/x/uv") == ["/x/uv", "pip", "install", "--python", sys.executable, "faster-whisper>=1.0"]
    assert extras.command("detect", which=lambda n: None) == [sys.executable, "-m", "pip", "install", "torch>=2.1", "torchvision>=0.16"]


def test_card_says_what_it_is_for_how_big_and_what_happens_without_it_in_both_languages():
    for n in extras.FEATURES:
        c = extras.card_body(n)
        assert c["key"] == f"extra-{n}" and [i["key"] for i in c["items"]] == ["install", "no"]
        assert "大小" in c["items"][0]["desc"] and extras.FEATURES[n]["without"] in c["items"][1]["desc"]
        en = c["en"]; assert "Size:" in en["items"][0]["desc"] and not CJK.search(en["title"] + "".join(i["title"] + i["desc"] for i in en["items"]))


def test_install_only_after_her_click(proj):
    runs = []; run = lambda cmd, **k: (runs.append(cmd), SimpleNamespace(returncode=0, stdout="ok", stderr=""))[1]
    have = {"v": False}; avail = lambda n: have["v"]
    d = extras.install(proj, "transcribe", run=run, is_available=avail); assert d["state"] == "pending" and d["code"] == "asked" and not runs
    assert extras.install(proj, "transcribe", run=run, is_available=avail)["code"] == "waiting"            # never a second card
    T = Thread(proj); c = next(v for v in T.cards().values() if v["card"]["key"] == "extra-transcribe")
    T.answer(c["event"]["id"], {"picked": ["install"]}, source="terminal")                                 # typed by an agent: not her click
    assert extras.install(proj, "transcribe", run=run, is_available=avail)["state"] == "pending" and not runs

    def run_ok(cmd, **k): runs.append(cmd); have["v"] = True; return SimpleNamespace(returncode=0, stdout="ok", stderr="")
    T.answer(c["event"]["id"], {"picked": ["install"]}, source="ui")
    d = extras.install(proj, "transcribe", run=run_ok, is_available=avail)
    assert d["state"] == "done" and len(runs) == 1 and "faster-whisper>=1.0" in runs[0]
    assert extras.install(proj, "transcribe", run=run_ok, is_available=avail)["state"] == "installed" and len(runs) == 1


def test_her_no_is_kept_and_a_failed_install_does_not_reuse_her_yes(proj):
    avail = lambda n: False; T = Thread(proj)
    extras.install(proj, "detect", run=_ok(), is_available=avail)
    c = next(v for v in T.cards().values() if v["card"]["key"] == "extra-detect")
    T.answer(c["event"]["id"], {"picked": ["no"]}, source="ui")
    assert extras.install(proj, "detect", run=_ok(), is_available=avail)["state"] == "refused"
    assert extras.install(proj, "detect", run=_ok(), is_available=avail, ask_again=True)["code"] == "asked"   # she brought it up
    c = next(v for v in T.cards().values() if v["card"]["key"] == "extra-detect")
    T.answer(c["event"]["id"], {"picked": ["install"]}, source="ui")
    d = extras.install(proj, "detect", run=_ok(rc=1, out="no space left on device"), is_available=avail)
    assert d["state"] == "failed" and "no space" in d["log"]
    assert extras.install(proj, "detect", run=_ok(), is_available=avail)["code"] == "asked"                   # one yes, one attempt


def test_cli_exit_codes_and_status(proj, monkeypatch, capsys):
    monkeypatch.setattr(extras, "available", lambda n: False)
    assert cli.main(["extras", "install", "transcribe", "--project", projects.find(str(proj))["id"]]) == 2
    assert "asked" in capsys.readouterr().out
    assert cli.main(["extras", "status"]) == 0
    o = capsys.readouterr().out; assert "NO  transcribe" in o and "install yourself:" in o and "'faster-whisper>=1.0'" in o   # quoted: >= is a redirect


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_ingest_adds_a_video_with_sound_without_speech_to_text(proj, tmp_path, monkeypatch):
    from gameanything import ingest
    monkeypatch.setattr(extras, "available", lambda n: False)
    monkeypatch.setattr(ingest.persons, "available", lambda: False)
    src = tmp_path / "src"; src.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=2",
                    "-shortest", str(src / "clip.mp4")], check=True)
    pack = ingest.ingest(src, proj)
    v = next(it for it in pack["items"] if it["kind"] == "video")
    assert v["derived"].get("audio") and "transcript" not in v["derived"] and "speech" not in v
    assert pack["summary"]["optional_missing"] == [{"feature": "transcribe", "items": 1}]
    assert any("gameanything extras install transcribe" in n for n in pack["summary"]["notes"])
    calls = []                                                       # installed later: the next ingest transcribes the video it skipped
    monkeypatch.setattr(extras, "available", lambda n: True)
    monkeypatch.setattr(ingest.video, "transcribe", lambda wav, dst, *a, **k: calls.append(wav) or
                        {"language": "en", "language_prob": 1.0, "speech_seconds": 1.0, "segments": [], "duration": 2.0})
    pack = ingest.ingest(src, proj)
    assert len(calls) == 1 and pack["summary"]["optional_missing"] == [] and next(it for it in pack["items"] if it["kind"] == "video")["speech"]


def test_ingest_takes_a_project_id_and_makes_no_folder_in_the_cwd(proj, tmp_path, monkeypatch):
    src = tmp_path / "src"; src.mkdir(); cwd = tmp_path / "cwd"; cwd.mkdir(); monkeypatch.chdir(cwd)
    pid = projects.find(str(proj))["id"]
    cli.main(["ingest", str(src), "--project", pid, "--no-transcribe", "--no-detect"])
    assert (proj / "1_ingest" / "pack.yaml").is_file() and not (cwd / pid).exists()
