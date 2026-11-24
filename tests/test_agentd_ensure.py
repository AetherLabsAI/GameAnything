"""`gameanything ui` starts the supervisor itself (agentd.ensure_running), so a fresh page never says 「后台调度没有运行」."""
from unittest import mock

from gameanything import agentd


def test_off_switch_and_already_running():
    assert agentd.ensure_running({"GAMEANYTHING_NO_AGENTD": "1"}) == "off"
    with mock.patch.object(agentd, "daemon_state", return_value={"alive": True}):
        assert agentd.ensure_running({}) == "running"


def test_starts_detached_when_down(tmp_path):
    """The script beside this Python (its venv), never another install found on PATH (an old m2w on her Mac, 2026-11-01)."""
    venv = tmp_path / "venv" / "bin"; venv.mkdir(parents=True); (venv / "python").write_text("", encoding="utf-8"); (venv / "gameanything").write_text("", encoding="utf-8")
    with mock.patch.object(agentd, "daemon_state", return_value={"alive": False}), \
         mock.patch.object(agentd.shutil, "which", side_effect=lambda n, path=None: "/old/bin/" + n), \
         mock.patch.object(agentd.sys, "executable", str(venv / "python")), \
         mock.patch.object(agentd.projects, "data_dir", return_value=tmp_path), \
         mock.patch.object(agentd.subprocess, "Popen") as P:
        assert agentd.ensure_running({"PATH": "/old/bin"}) == "started"
    assert P.call_args[0][0] == [str(venv / "gameanything"), "agentd", "run"] and P.call_args[1]["start_new_session"] is True


def test_codex_provider_checks_codex_not_claude(tmp_path):
    seen = []
    def which(name, path=None):
        seen.append(name)
        return "/bin/" + name if name in ("codex", "gameanything") else None
    env = {"PATH": "/bin", "GAMEANYTHING_AGENT_PROVIDER": "codex"}
    with mock.patch.object(agentd, "daemon_state", return_value={"alive": False}), \
         mock.patch.object(agentd.shutil, "which", side_effect=which), \
         mock.patch.object(agentd.projects, "data_dir", return_value=tmp_path), \
         mock.patch.object(agentd.subprocess, "Popen") as P:
        assert agentd.ensure_running(env) == "started"
    assert "codex" in seen and "claude" not in seen and P.call_args[1]["env"]["GAMEANYTHING_AGENT_PROVIDER"] == "codex"


def test_no_script_beside_python_runs_this_python(tmp_path):
    """`python -c ... main()` has sys.argv[0] == "-c": the supervisor is started with this Python, never with "-c"."""
    with mock.patch.object(agentd, "daemon_state", return_value={"alive": False}), \
         mock.patch.object(agentd.sys, "executable", str(tmp_path / "python")), \
         mock.patch.object(agentd.shutil, "which", side_effect=lambda n, path=None: "/bin/claude" if n == "claude" else None), \
         mock.patch.object(agentd.projects, "data_dir", return_value=tmp_path), \
         mock.patch.object(agentd.subprocess, "Popen") as P:
        assert agentd.ensure_running({"PATH": "/bin"}) == "started"
    cmd = P.call_args[0][0]
    assert cmd[0] == str(tmp_path / "python") and cmd[-2:] == ["agentd", "run"] and "gameanything.cli" in cmd[2]


def test_start_that_cannot_spawn_is_reported(tmp_path):
    with mock.patch.object(agentd, "daemon_state", return_value={"alive": False}), \
         mock.patch.object(agentd.shutil, "which", side_effect=lambda n, path=None: "/bin/" + n), \
         mock.patch.object(agentd.projects, "data_dir", return_value=tmp_path), \
         mock.patch.object(agentd.subprocess, "Popen", side_effect=FileNotFoundError("m2w")):
        assert agentd.ensure_running({"PATH": "/bin"}) == "failed"


def test_auth_failed_reads_the_run_log(tmp_path):
    f = tmp_path / "run.jsonl"
    f.write_text('{"error":"authentication_failed","result":"Failed to authenticate. API Error: 401"}\n', encoding="utf-8")
    assert agentd.auth_failed(f) is True
    f.write_text('{"type":"result","result":"done"}\n', encoding="utf-8")
    assert agentd.auth_failed(f) is False
    assert agentd.auth_failed(tmp_path / "missing") is False
