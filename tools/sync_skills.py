"""Copy skills/gameanything (the only copy you edit) to where each agent looks for skills in a clone:

    .agents/skills/gameanything   Codex, Gemini CLI, Cursor, VS Code / Copilot, OpenCode
    .claude/skills/gameanything   Claude Code (Cursor, Copilot and OpenCode read it too)

Plain copies, not symlinks: a Windows clone without developer mode checks a symlink out as a text file with the target path in it.
Plugin installs (Claude Code, Codex, Cursor, Gemini CLI, VS Code) read skills/ itself; the wheel carries its own copy (setup.py).

    python tools/sync_skills.py           refresh the copies
    python tools/sync_skills.py --check   exit 1 and list what differs (tests/test_plugins.py runs the same check)
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skills"
SKILLS = ("gameanything",)
COPIES = (".agents/skills", ".claude/skills")


def _files(d: Path) -> dict:
    """{relative posix path: bytes} of every file under d (no caches)."""
    if not d.is_dir(): return {}
    return {f.relative_to(d).as_posix(): f.read_bytes() for f in sorted(d.rglob("*"))
            if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc"}


def drift() -> list:
    """One line per difference between skills/<name> and each copy; [] = in sync."""
    out = []
    for name in SKILLS:
        src = _files(SOURCE / name)
        for c in COPIES:
            cp = _files(ROOT / c / name)
            out += [f"{c}/{name}/{r}: missing" for r in sorted(src.keys() - cp.keys())]
            out += [f"{c}/{name}/{r}: not in skills/{name}" for r in sorted(cp.keys() - src.keys())]
            out += [f"{c}/{name}/{r}: differs" for r in sorted(src.keys() & cp.keys()) if src[r] != cp[r]]
    return out


def sync() -> None:
    for name in SKILLS:
        for c in COPIES:
            dest = ROOT / c / name
            if dest.is_symlink() or dest.is_file(): dest.unlink()
            elif dest.exists(): shutil.rmtree(dest)
            shutil.copytree(SOURCE / name, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if args == ["--check"]:
        d = drift()
        for line in d: print(line)
        if d: print("skill copies are stale: run `python tools/sync_skills.py`", file=sys.stderr)
        return 1 if d else 0
    if args: print(__doc__); return 2
    sync(); print(f"[sync-skills] skills/{', '.join(SKILLS)} -> {', '.join(COPIES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
