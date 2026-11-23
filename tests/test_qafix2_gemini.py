"""QA2 2026-10-30: Gemini runs never on the CLI's "auto" router (its classifier calls gemini-2.5-flash-lite, which 404s on every run and
leaves gemini-client-error-*.json behind); the menu lists models that work; gemini-3-flash (ModelNotFound) is refused; a card file the
agent wrote in the project root is not left there."""
import pytest

from gameanything import agent_providers as ap, cli, models, projects
from gameanything.conversation import Thread


def test_gemini_never_runs_without_a_model(monkeypatch):
    monkeypatch.delenv("GAMEANYTHING_GEMINI_MODEL", raising=False)
    p = ap.provider("gemini", binary="gemini")
    assert p.model == ap.GEMINI_DEFAULT_MODEL == "gemini-3.5-flash"
    cmd = p.command("hi", "sys", None, False, "/tmp")
    assert cmd[cmd.index("--model") + 1] == "gemini-3.5-flash"


def test_gemini_menu_lists_working_models():
    ids = [m["id"] for m in models.catalog("gemini")["models"]]
    assert "gemini-3.1-pro-preview" in ids and "gemini-3-flash" not in ids
    assert not any("flash-lite" in i for i in ids)
    assert models.label("gemini", "") and "3.5-flash" in models.shown_model("gemini", "")
    for bad in ("gemini-3-flash", "gemini-2.5-flash-lite"):
        with pytest.raises(models.ModelError): models.check("gemini", bad)
    assert models.check("gemini", "gemini-3.1-pro-preview") == "gemini-3.1-pro-preview"


def test_gemini_temp_files_stay_in_its_home(tmp_path):
    p = ap.provider("gemini", binary="gemini")
    _cmd, env = p.launch("hi", "sys", None, False, tmp_path, env={"GEMINI_API_KEY": "k", "GAMEANYTHING_GEMINI_HOME": str(tmp_path / "gh")})
    assert env["TMPDIR"].startswith(str(tmp_path / "gh"))


def test_card_file_in_the_project_root_is_removed(capsys):
    e = projects.create("卡片", kind="memory"); root = projects.resolve(e["id"])
    f = root / "plan_card.yaml"
    f.write_text("kind: result\nkey: r1\nmilestone: m1\ntitle: 好了\nbody: 方案写好了\n", encoding="utf-8")
    rc = cli.main(["chat", "card", "--project", str(root), "--file", str(f)])
    assert rc == 0 and not f.exists(), "a temp card file in the project root is removed after posting"
    assert any(ev.get("type") == "card" for ev in Thread(root).events())
