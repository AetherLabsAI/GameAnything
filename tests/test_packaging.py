"""Packaging checks: manifests parse, the skill frontmatter is valid, one source of truth for the guide."""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
JSONS = [".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", ".codex-plugin/plugin.json",
         ".agents/plugins/marketplace.json", "gemini-extension.json", "opencode.json"]


def test_manifests_parse():
    for f in JSONS:
        json.loads((ROOT / f).read_text(encoding="utf-8"))
    assert json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))["plugins"][0]["source"] == "./"
    assert json.loads((ROOT / "gemini-extension.json").read_text(encoding="utf-8"))["contextFileName"] == "AGENTS.md"


def test_skill_frontmatter():
    t = (ROOT / "skills/gameanything/SKILL.md").read_text(encoding="utf-8")
    assert t.startswith("---\n")
    fm = yaml.safe_load(t.split("---\n")[1])
    assert fm["name"] == "gameanything" and len(fm["description"]) > 40 and len(fm["description"]) <= 1024
    for ref in (ROOT / "skills/gameanything").glob("references/*.md"):
        assert f"references/{ref.name}" in t, f"SKILL.md does not link {ref.name}"


def test_card_examples_parse():
    for f in (ROOT / "skills/gameanything/references/card-examples").glob("*.yaml"):
        yaml.safe_load(f.read_text(encoding="utf-8"))


def test_single_source_of_truth():
    # AGENTS.md points into skills/; the guide's content lives only there. Guard against a second copy at the top level.
    assert not (ROOT / "AGENT_GUIDE.md").exists()
    for ref in ("rules-and-loop.md", "cards.md", "memory-project-flow.md", "feature-flow.md", "pitfalls.md"):
        assert (ROOT / "skills/gameanything/references" / ref).is_file() and f"references/{ref}" in (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert (ROOT / "CLAUDE.md").read_text(encoding="utf-8").startswith("@AGENTS.md")
    assert (ROOT / "GEMINI.md").read_text(encoding="utf-8").strip() == "@AGENTS.md"


def _project_deps():
    """requires-python and the dependency strings of pyproject.toml (a plain read: tomllib is 3.11+)."""
    import re
    t = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    rp = re.search(r'^requires-python = "([^"]+)"', t, re.M).group(1)
    block = re.search(r"^dependencies = \[\n(.*?)^\]", t, re.M | re.S).group(1)
    return rp, [m.group(1) for m in re.finditer(r'^\s*"([^"]+)",', block, re.M)]


def _packaging():
    try:
        from packaging import markers, requirements, specifiers
    except ImportError:
        from pip._vendor.packaging import markers, requirements, specifiers
    return markers, requirements, specifiers


# (sys_platform, platform_machine) as Python reports them: Windows says AMD64 / ARM64, macOS arm64, Linux x86_64 / aarch64
PLATFORMS = [("win32", "AMD64"), ("win32", "ARM64"), ("darwin", "arm64"), ("darwin", "x86_64"), ("linux", "x86_64"), ("linux", "aarch64")]


def test_one_opencc_on_every_platform():
    # A real Windows 11 ARM64 PC (2026-10-31): OpenCC ships no win_arm64 wheel, the install then needs CMake and a C++ compiler and
    # fails. There the pure-Python reimplementation stands in: the same `opencc` module and OpenCC("t2s").convert (textconv.py).
    _, requirements, _ = _packaging()
    reqs = [requirements.Requirement(d) for d in _project_deps()[1]]
    for plat, mach in PLATFORMS:
        env = {"sys_platform": plat, "platform_machine": mach}
        names = [r.name for r in reqs if r.name.startswith("opencc") and (r.marker is None or r.marker.evaluate(env))]
        want = ["opencc-python-reimplemented"] if (plat, mach) == ("win32", "ARM64") else ["opencc"]
        assert names == want, (plat, mach, names)


def test_requires_python_skips_versions_without_wheels():
    # `uv tool install` takes the newest Python it can get: 3.15 on a fresh Windows PC (2026-10-31), where pyyaml and opencc have no
    # wheels yet and the install asks for Microsoft C++ Build Tools. Raise the cap once they publish cp315 Windows wheels.
    _, _, specifiers = _packaging()
    rp = specifiers.SpecifierSet(_project_deps()[0])
    assert "3.10.0" in rp and "3.14.2" in rp and "3.15.0" not in rp


def test_simplified_chinese_with_the_installed_opencc():
    from gameanything import textconv
    t = "這是一個測試，憂鬱的臺灣烏龜"
    assert textconv.to_simplified(t) == "这是一个测试，忧郁的台湾乌龟"
    assert textconv.traditional_ratio(t) > 0.5 and textconv.traditional_ratio("这是一个测试") == 0


def test_launchers_ask_uv_for_the_same_python():
    # bin/gameanything(.cmd) run a clone through `uv run --no-project`, which ignores requires-python: on the same PC it took 3.15 and
    # failed on pyyaml. Both launchers pass pyproject's range with --python.
    rp = _project_deps()[0]
    for f in ("bin/gameanything", "bin/gameanything.cmd"):
        line = next(ln for ln in (ROOT / f).read_text(encoding="utf-8").splitlines() if "uv run" in ln and not ln.lstrip().startswith(("#", "rem")))
        assert f'--python "{rp}"' in line, f
