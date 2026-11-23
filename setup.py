"""Only the build step that pyproject.toml cannot say: a wheel (`pip install .`, `uv tool install`) also carries the skill, AGENTS.md,
docs/lessons/games/ and the dsh search plugin, copied into gameanything/_bundle/ with their checkout layout (gameanything/shipped.py finds them there). An editable
install skips the copy: it reads them from the checkout, as the plugin manifests do."""
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

HERE = Path(__file__).resolve().parent
BUNDLED = ("skills/gameanything", "AGENTS.md", "docs/lessons/games", "lab/images/common/security",
           "plugins/dsh-web-search-openai-compatible")      # the same list as gameanything/shipped.py


def bundle_files() -> list:
    """[(source, path relative to the repo root)] of every file that goes into gameanything/_bundle/."""
    out = []
    for rel in BUNDLED:
        src = HERE / rel
        if not src.exists(): raise SystemExit(f"setup.py: {rel} is missing (the wheel needs it)")
        fs = sorted(f for f in src.rglob("*") if f.is_file()) if src.is_dir() else [src]
        out += [(f, f.relative_to(HERE).as_posix()) for f in fs if "__pycache__" not in f.parts and f.suffix != ".pyc"]
    return out


class BuildPyWithBundle(build_py):
    def run(self):
        super().run()
        if getattr(self, "editable_mode", False): return
        dest = Path(self.build_lib) / "gameanything" / "_bundle"
        for src, rel in bundle_files():
            t = dest / rel; self.mkpath(str(t.parent)); self.copy_file(str(src), str(t))


setup(cmdclass={"build_py": BuildPyWithBundle})
