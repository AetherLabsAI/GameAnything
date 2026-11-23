"""The agent-side install routes (README "Install"): plugin manifests for Claude Code, Codex, Cursor, Gemini CLI, VS Code / Copilot
and OpenCode, the skill copies each harness looks for in a clone, the bin/gameanything launcher and the PATH hook.
Field names follow each tool's docs (2026-10)."""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import sync_skills  # noqa: E402

NAME = "gameanything"


def _json(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def _version():
    m = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    return m.group(1)


def test_manifest_licenses_match_pyproject():
    lic = re.search(r'^license = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    for rel in ("plugin.json", ".claude-plugin/plugin.json", ".codex-plugin/plugin.json", ".cursor-plugin/plugin.json",
                "plugins/opencode/package.json"):
        assert _json(rel).get("license") == lic, rel


def test_skill_copies_in_sync():
    # skills/gameanything is the only copy you edit; refresh the others with `python tools/sync_skills.py`
    assert sync_skills.drift() == []


def test_skill_copies_are_plain_folders():
    # a symlink becomes a one-line text file in a Windows clone without developer mode
    for c in sync_skills.COPIES:
        d = ROOT / c / NAME
        assert d.is_dir() and not d.is_symlink(), d
        assert not any(p.is_symlink() for p in d.rglob("*"))


def test_one_skill_name_everywhere():
    for c in ("skills", *sync_skills.COPIES):
        assert sorted(p.name for p in (ROOT / c).iterdir() if p.is_dir()) == [NAME], c


def test_manifest_names_and_versions():
    v = _version()
    for rel in ("plugin.json", ".codex-plugin/plugin.json", ".cursor-plugin/plugin.json", "gemini-extension.json"):
        d = _json(rel)
        assert d["name"] == NAME and d["version"] == v and d["description"], rel
    # no version on purpose: Claude Code then treats every commit as an update (with one it waits for a version bump)
    c = _json(".claude-plugin/plugin.json")
    assert c["name"] == NAME and "version" not in c
    assert _json("plugins/opencode/package.json")["version"] == v


def test_agent_plugins_root_manifest():
    # Agent Plugins 1.0 (agent-plugins.org): read by VS Code / Copilot, Codex (before .codex-plugin) and Cursor. The schema rejects
    # unknown top-level keys; an `extensions` key would replace Codex's whole .codex-plugin overlay, so it stays out.
    d = _json("plugin.json")
    assert d["$schema"] == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    assert set(d) <= {"$schema", "name", "version", "description", "author", "homepage", "repository", "license", "keywords"}


def test_marketplaces_point_at_this_plugin():
    for rel in (".claude-plugin/marketplace.json", ".cursor-plugin/marketplace.json"):
        d = _json(rel)
        assert d["name"] == NAME and d["owner"]["name"]
        assert [(p["name"], p["source"]) for p in d["plugins"]] == [(NAME, "./")], rel
    cx = _json(".agents/plugins/marketplace.json")                     # Codex: one entry, a git URL of this repo
    (p,) = cx["plugins"]
    assert p["name"] == NAME and p["source"]["source"] == "url" and p["source"]["url"].endswith("/GameAnything.git")
    assert p["policy"]["installation"] == "AVAILABLE" and p["category"]


def test_codex_plugin_paths():
    d = _json(".codex-plugin/plugin.json")
    assert d["skills"] == "./skills/" and (ROOT / "skills" / NAME / "SKILL.md").is_file()
    i = d["interface"]
    assert i["displayName"] and i["shortDescription"] and i["defaultPrompt"] and re.fullmatch(r"#[0-9a-fA-F]{6}", i["brandColor"])


def test_gemini_and_opencode_context():
    assert (ROOT / _json("gemini-extension.json")["contextFileName"]).is_file()
    oc = _json("opencode.json")
    assert all((ROOT / f).is_file() for f in oc["instructions"])
    # `skills: {paths}` is deprecated and `plugins` makes OpenCode <= 1.18 reject the file: the skill comes from .agents/skills
    assert "skills" not in oc and "plugins" not in oc and "plugin" not in oc
    for rel in ("CLAUDE.md", "GEMINI.md"):
        assert (ROOT / rel).read_text(encoding="utf-8").startswith("@AGENTS.md")


def test_session_start_hooks():
    for rel, root in (("hooks/hooks.json", "${CLAUDE_PLUGIN_ROOT}"), (".claude/settings.json", "$CLAUDE_PROJECT_DIR")):
        (entry,) = _json(rel)["hooks"]["SessionStart"]
        (h,) = entry["hooks"]
        assert h["type"] == "command" and f'"{root}/hooks/add-to-path.sh"' in h["command"], rel
    assert (ROOT / "hooks/add-to-path.sh").is_file()


def test_line_endings_and_modes():
    attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "bin/gameanything text eol=lf" in attrs and "*.sh text eol=lf" in attrs and "*.cmd text eol=crlf" in attrs
    for rel in ("bin/gameanything", "hooks/add-to-path.sh"):
        assert b"\r" not in (ROOT / rel).read_bytes(), rel
    if shutil.which("git") and (ROOT / ".git").exists():
        out = subprocess.run(["git", "ls-files", "-s", "bin/gameanything", "hooks/add-to-path.sh"], cwd=ROOT, capture_output=True,
                             text=True, encoding="utf-8").stdout
        modes = {line.split("\t")[1]: line.split()[0] for line in out.splitlines()}
        assert all(modes.get(f) in (None, "100755") for f in ("bin/gameanything", "hooks/add-to-path.sh")), modes


def _cli_commands():
    from gameanything import cli
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), pytest.raises(SystemExit):
        cli.main(["--help"])
    return re.search(r"\{([a-z0-9_,-]+)\}", buf.getvalue()).group(1).split(",")


def test_opencode_plugin_lists_every_command():
    src = (ROOT / "plugins/opencode/index.ts").read_text(encoding="utf-8")
    block = src[src.index("const GROUPS = ["):]
    block = block[:block.index("\n]")]
    assert re.findall(r'\{\s*name:\s*"([a-z0-9_-]+)"', block) == _cli_commands()
    assert 'id: "gameanything"' in src and 'join(root, "bin", "gameanything")' in src and 'namespace: "gameanything"' in src


def _env():
    e = dict(os.environ, GAMEANYTHING_NO_UV="1")
    e["PATH"] = os.path.dirname(sys.executable) + os.pathsep + e.get("PATH", "")
    return e


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="bin/gameanything is the bash launcher")
def test_bin_launcher_runs_this_checkout():
    r = subprocess.run(["bash", str(ROOT / "bin" / "gameanything"), "--help"], capture_output=True, text=True, encoding="utf-8", env=_env(),
                       timeout=120)
    assert r.returncode == 0 and "usage: gameanything" in r.stdout, r.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="bin/gameanything.cmd is the Windows launcher")
@pytest.mark.parametrize("name", ["gameanything.cmd", "m2w.cmd"])
def test_bin_launcher_cmd_runs_this_checkout(name):
    r = subprocess.run(["cmd", "/c", str(ROOT / "bin" / name), "--help"], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=_env(), timeout=120)
    assert r.returncode == 0 and "usage: gameanything" in r.stdout, r.stderr


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="the hook runs in bash")
def test_path_hook(tmp_path):
    envf = tmp_path / "env.sh"
    base = dict(os.environ, CLAUDE_ENV_FILE=str(envf), PATH="/usr/bin:/bin")
    for _ in range(2):                                                   # the second run adds nothing
        subprocess.run(["bash", str(ROOT / "hooks/add-to-path.sh"), str(ROOT)], env=base, check=True)
    assert envf.read_text(encoding="utf-8") == f'export PATH="{ROOT}/bin:$PATH"  # gameanything-path\n'
    envf.write_text(f'export PATH="{ROOT}/bin:$PATH"  # memory2world-path\n', encoding="utf-8")       # written before the rename
    subprocess.run(["bash", str(ROOT / "hooks/add-to-path.sh"), str(ROOT)], env=base, check=True)
    assert envf.read_text(encoding="utf-8").count("export PATH") == 1
    envf.unlink()
    fake = tmp_path / "bin"; fake.mkdir(); (fake / "gameanything").write_text("#!/bin/sh\n", encoding="utf-8"); (fake / "gameanything").chmod(0o755)
    subprocess.run(["bash", str(ROOT / "hooks/add-to-path.sh"), str(ROOT)], env=dict(base, PATH=f"{fake}:/usr/bin:/bin"), check=True)
    assert not envf.exists()                                             # an installed gameanything is never shadowed
