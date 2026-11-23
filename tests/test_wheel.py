"""An installed m2w (a wheel: `pip install .`, `uv tool install`) carries the skill and reads it from inside the package (shipped.py,
setup.py): the wheel's file list, and a run of the installed copy (flow next, an agentd prompt with a fake spawn, lessons written to the
data dir and never into the package). Builds without network: setuptools must already be importable (CI installs it), else skipped."""
import ast
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from gameanything import agentd, builds, flow, lessons, shipped

ROOT = Path(__file__).resolve().parents[1]
MUST = ["skills/gameanything/core.md", "skills/gameanything/roles/builder.md", "skills/gameanything/references/resident-prompt.md",
        "skills/gameanything/modes/adaptation.md", "AGENTS.md", "lab/images/common/security/seccomp-steam.json",
        "lab/images/common/security/gameanything-steam-u2204.apparmor"]


def _setup_bundled():
    tree = ast.parse((ROOT / "setup.py").read_text(encoding="utf-8"))
    return next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "BUNDLED")


def test_checkout_reads_the_skill_from_the_repo():
    assert _setup_bundled() == shipped.BUNDLED
    assert shipped.in_checkout() and shipped.ROOT == ROOT and not shipped.read_only(ROOT / "gameanything" / "games")
    for p in (agentd.SKILL, flow.SKILL): assert p == ROOT / "skills" / "gameanything"
    assert builds.ROLE.is_file() and agentd.CORE.is_file() and lessons.ROLE_DIR == ROOT / "skills/gameanything/references/lessons"
    for d in ("skills/gameanything", "docs/lessons/games", "lab/images/common/security"):
        assert f"graft {d}" in (ROOT / "MANIFEST.in").read_text(encoding="utf-8")


def test_image_build_context_has_everything_the_wheel_bundles():
    """lab/images/*/Dockerfile `pip install`s the repository from a context cut by .dockerignore (`*`, then `!` lines): every
    BUNDLED path must be let back in, else setup.py stops ("... is missing (the wheel needs it)") and no image builds."""
    keep = [ln[1:].strip().rstrip("/") for ln in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines() if ln.startswith("!")]
    for b in shipped.BUNDLED:
        assert any(b == k or b.startswith(k + "/") for k in keep), f".dockerignore leaves out {b}"
    for f in ("setup.py", "pyproject.toml", "MANIFEST.in", "README.md", "LICENSE"): assert f in keep


def _setuptools_ok():
    try:
        import setuptools
        v = tuple(int(x) for x in setuptools.__version__.split(".")[:2])
    except (ImportError, ValueError): return False
    return v >= (77, 0)   # pyproject's `license = "Apache-2.0"` (PEP 639) needs setuptools 77


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    if not _setuptools_ok(): pytest.skip("setuptools >= 77 is not installed: pip install -U setuptools")
    t = tmp_path_factory.mktemp("wheel"); src = t / "src"; out = t / "dist"; out.mkdir()
    ign = shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info", "build")
    shutil.copytree(ROOT / "gameanything", src / "gameanything", ignore=ign)
    for rel in ("skills/gameanything", "docs/lessons/games", "lab/images/common/security", "plugins/dsh-web-search-openai-compatible"): shutil.copytree(ROOT / rel, src / rel, ignore=ign)
    for f in ("pyproject.toml", "setup.py", "MANIFEST.in", "README.md", "AGENTS.md"): shutil.copy2(ROOT / f, src / f)
    code = ("import sys; from setuptools import build_meta as b; o = sys.argv[1]; "
            "print(b.build_wheel(o)); print(b.build_sdist(o))")
    r = subprocess.run([sys.executable, "-c", code, str(out)], cwd=src, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-3000:]
    return next(out.glob("*.whl")), next(out.glob("*.tar.gz")), t


def test_wheel_and_sdist_carry_the_skill(built):
    whl, sdist, _ = built
    names = set(zipfile.ZipFile(whl).namelist())
    for m in MUST: assert f"gameanything/_bundle/{m}" in names, m
    steps = {n for n in names if n.startswith("gameanything/_bundle/skills/gameanything/steps/adaptation/") and n.endswith(".md")}
    assert {Path(n).stem for n in steps} >= {s["id"] for s in flow.ADAPTATION}
    assert "gameanything/shipped.py" in names and "gameanything/ui/static/hub.js" in names and not any("__pycache__" in n for n in names)
    with tarfile.open(sdist) as tf: sn = tf.getnames()
    assert any(n.endswith("/skills/gameanything/core.md") for n in sn) and any(n.endswith("/setup.py") for n in sn)


INSTALLED_RUN = r'''
import contextlib, io, json, subprocess, sys
from pathlib import Path
site = Path(sys.argv[1]).resolve()
import gameanything
from gameanything import agentd, builds, cli, flow, lessons, projects, shipped
from gameanything.conversation import Thread
assert Path(gameanything.__file__).resolve().is_relative_to(site), gameanything.__file__
assert shipped.ROOT == shipped.BUNDLE and not shipped.in_checkout() and agentd.SKILL.is_relative_to(site) and builds.ROLE.is_file()
from gameanything import sandbox      # Steam's seccomp profile for `lab sandbox up` (a uv tool install had none, 2026-10-30)
sec = sandbox.security_folder(); assert (sec / "seccomp-steam.json").is_file() and sec.resolve().is_relative_to(site), sec
assert any(x.endswith("seccomp-steam.json") and str(site) in x for x in sandbox.steam_run_args("h", "g", apparmor=False))
e = projects.create("Book", "adaptation", game="minecraft", lang="zh"); root = Path(e["path"])
buf = io.StringIO()
with contextlib.redirect_stdout(buf): assert cli.main(["flow", "next", "--project", str(root), "--json"]) == 0
n = json.loads(buf.getvalue()); doc = Path(n["step"]["doc"]); assert doc.is_file() and doc.resolve().is_relative_to(site), doc
procs, cmds = [], []
def spawn(cmd, cwd, env, log):
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    procs.append(p); cmds.append(cmd); return p
Thread(root).user_text("hi")
try: agentd.Agentd(claude="/bin/false", spawn=spawn, quiet=True).tick()
finally:
    for p in procs: p.kill(); p.wait(10)
sysp = cmds[0][cmds[0].index("--append-system-prompt") + 1]
line = lambda f: max((x for x in f.read_text(encoding="utf-8").splitlines() if "{{" not in x), key=len)     # a line with no placeholder
assert line(agentd.CORE) in sysp and line(doc) in sysp and "{{" not in sysp and str(shipped.ROOT) in sysp, sysp[:2000]
assert (shipped.ROOT / "AGENTS.md").is_file()
m = projects.create("Day", "memory"); p2 = agentd.render_prompt(m, Path(m["path"]), "s", Path(m["path"]))
assert "{{skill_dir}}" not in p2 and "{{repo}}" not in p2 and str(shipped.SKILL) in p2 and f"{shipped.ROOT}/AGENTS.md" in p2
r = lessons.add("minecraft", "builder", "the build window closes at once", "", "start the server first")
f = Path(r["file"]); assert f.is_relative_to(lessons.shared_dir()) and not f.resolve().is_relative_to(site), f
r2 = lessons.add(None, "playtester", "replay first frame is black", "", "wait two seconds", general=True)
assert Path(r2["file"]).is_relative_to(lessons.shared_dir())
ids = {x["id"] for x in lessons.show("minecraft", "builder")}; assert r["id"] in ids
assert all(d.is_relative_to(lessons.shared_dir()) for d in lessons.write_dirs("minecraft"))
shipped_ids = [x["id"] for x in lessons.collect() if shipped.read_only(x["_file"])]
if shipped_ids:
    try: lessons.confirm(shipped_ids[0]); raise SystemExit("confirmed a shipped lesson inside the package")
    except lessons.LessonError: pass
lessons.confirm(r["id"])
print("INSTALLED-OK")
'''


def test_installed_copy_runs_from_the_package(built, tmp_path):
    whl, _, _ = built
    site = tmp_path / "site"; zipfile.ZipFile(whl).extractall(site)
    before = sorted(p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file())
    env = {**os.environ, "PYTHONPATH": str(site), "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([sys.executable, "-c", INSTALLED_RUN, str(site)], cwd=tmp_path, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    assert r.returncode == 0 and "INSTALLED-OK" in r.stdout, r.stdout[-3000:] + r.stderr[-3000:]
    after = sorted(p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file())
    assert after == before, "a run wrote into the installed package: " + json.dumps(sorted(set(after) - set(before))[:10])
