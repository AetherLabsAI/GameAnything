"""Where the files that ship with GameAnything but live outside the Python package in a checkout are: the skill (skills/gameanything/: core.md,
modes/, steps/, roles/, references/, the role lessons), AGENTS.md (the hard rules the prompts point at), docs/lessons/games/ and the
sandbox's security profiles lab/images/common/security/ (Steam's seccomp / AppArmor: `lab sandbox up` passes them to docker run) and the
DeepSeek Harness search plugin plugins/dsh-web-search-openai-compatible/ (dsh loads it from here).

    checkout / editable install   they are at the repo root, next to gameanything/ (the plugin manifests point there too)
    wheel / `pip install .` / `uv tool install`   setup.py copies them into gameanything/_bundle/ with the same layout

    ROOT          the folder that holds skills/gameanything/ and AGENTS.md: the checkout when GameAnything runs from one, else gameanything/_bundle
    SKILL         ROOT/skills/gameanything
    read_only(p)  p is inside an installed package (site-packages): a run never writes there (lessons.py writes to the data dir instead)
"""
from pathlib import Path

PKG = Path(__file__).resolve().parent
BUNDLE = PKG / "_bundle"
CHECKOUT = PKG.parent
BUNDLED = ("skills/gameanything", "AGENTS.md", "docs/lessons/games", "lab/images/common/security",
           "plugins/dsh-web-search-openai-compatible")      # what setup.py copies into _bundle (keep the two lists the same)


def in_checkout() -> bool:
    """GameAnything runs from a source tree (a clone, an editable install), not from an installed copy of the package."""
    return (CHECKOUT / "pyproject.toml").is_file()


def root() -> Path:
    """A checkout always reads its own skills/ (a stray _bundle there is never used); an installed package its _bundle."""
    if in_checkout() and (CHECKOUT / "skills" / "gameanything" / "core.md").is_file(): return CHECKOUT
    return BUNDLE if (BUNDLE / "skills" / "gameanything" / "core.md").is_file() else CHECKOUT


ROOT = root()
SKILL = ROOT / "skills" / "gameanything"


def read_only(p) -> bool:
    if in_checkout(): return False
    try: Path(p).resolve().relative_to(PKG)
    except (ValueError, OSError): return False
    return True
