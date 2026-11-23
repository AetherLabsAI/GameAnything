"""Shared fixtures. Every test runs with its home, config, data and game folders inside its own tmp_path, so a test can never touch the
real user's files on Windows, macOS or Linux; `writes` records every file-system write a block makes (Python audit hooks), to prove it."""
import os
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

_ENV_DIRS = ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "GAMEANYTHING_HOME", "GAMEANYTHING_DATA")
_ENV_DROP = ("GAMEANYTHING_STARDEW_DIR", "GAMEANYTHING_MINECRAFT_DIR", "GAMEANYTHING_CITIES_DIR", "GAMEANYTHING_STS_DIR", "GAMEANYTHING_OC2_DIR", "GAMEANYTHING_VALHEIM_DIR", "GAMEANYTHING_TERRARIA_DIR", "GAMEANYTHING_TERRARIA_GAME_DIR", "GAMEANYTHING_STEAM_DIR", "HF_TOKEN", "OPENROUTER_API_KEY",
            "FAL_KEY", "MESHY_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "COMFYUI_URL", "GAMEANYTHING_KEYS_FILE", "GAMEANYTHING_GEN_OFF",
            "GAMEANYTHING_AGENT_USERS", "GAMEANYTHING_AGENT_ROOT", "GAMEANYTHING_GATE", "GAMEANYTHING_GATE_SOCKET", "GAMEANYTHING_GATE_FORWARDED")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Point every per-user folder of every system at tmp_path/env/...; -> that root."""
    root = tmp_path / "env"
    for v in _ENV_DIRS:
        d = root / v.lower(); d.mkdir(parents=True); monkeypatch.setenv(v, str(d))
    for v in _ENV_DROP: monkeypatch.delenv(v, raising=False)
    # Windows finds Steam machine-wide (C:\Program Files (x86)\Steam, steam.candidates): a PC with real games must not leak them into tests
    from gameanything.native import steam
    real_roots = steam.roots
    monkeypatch.setattr(steam, "roots", lambda *a, **k: [r for r in real_roots(*a, **k) if r.resolve().is_relative_to(tmp_path.resolve())])
    for v in [k for k in os.environ if k.startswith("M2W_")]: monkeypatch.delenv(v, raising=False)    # the old names (envcompat) from the shell
    monkeypatch.setenv("GAMEANYTHING_NO_KEYRING", "1")     # never read the real system keyring (keys.py); a test that wants one fakes osdirs.secret_*
    monkeypatch.setenv("GAMEANYTHING_NO_AGENTD", "1")      # a test's `gameanything ui` must never start a real supervisor (it would run claude)
    monkeypatch.setenv("GAMEANYTHING_RUN_TMP_BASE", str(tmp_path / "runtmp"))   # agent runs' own temp folders (agent_providers.run_tmpdir)
    monkeypatch.delenv("GAMEANYTHING_RUN_TMP", raising=False)
    monkeypatch.setenv("GAMEANYTHING_CODEX_SANDBOX", "ok")   # never probe the real codex (agent_providers.codex_sandbox_probe); tests that want it set it
    from gameanything import decisions
    decisions.serve_signing()          # the test process plays the UI server: it may sign her decisions (tests of an agent's process unset it)
    return root


# ---------------------------------------------------------------- write audit
_rec = []          # the active recorders (lists); the hook is installed once and stays (audit hooks cannot be removed)
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
_PATH_EVENTS = {"os.mkdir": (0,), "os.remove": (0,), "os.rmdir": (0,), "os.rename": (0, 1), "os.symlink": (1,), "os.chmod": (0,),
                "os.utime": (0,), "os.truncate": (0,), "shutil.copyfile": (1,), "shutil.copytree": (1,), "shutil.move": (0, 1),
                "shutil.rmtree": (0,)}


def _hook(event, args):
    if not _rec: return
    paths = []
    if event == "open":
        path, mode, flags = (tuple(args) + (None, None))[:3]
        writing = any(c in mode for c in "wax+") if isinstance(mode, str) else bool(isinstance(flags, int) and flags & _WRITE_FLAGS)
        if writing: paths.append(path)
    elif event in _PATH_EVENTS:
        paths += [args[i] for i in _PATH_EVENTS[event] if i < len(args)]
    for p in paths:
        if isinstance(p, int) or p is None: continue                       # an fd (os.utime / os.chmod on an open file)
        p = os.fsdecode(p) if isinstance(p, bytes) else str(p)
        if "__pycache__" in p or p.endswith(".pyc"): continue
        for r in _rec: r.append(os.path.realpath(p))


sys.addaudithook(_hook)


@pytest.fixture
def writes():
    """with writes() as w: ...   -> w is the list of real paths written inside the block."""
    @contextmanager
    def rec():
        out = []; _rec.append(out)
        try: yield out
        finally: _rec.remove(out)
    return rec


def _inside(p, root) -> bool:
    try: return os.path.commonpath([os.path.normcase(p), root]) == root
    except ValueError: return False                                         # Windows: another drive


def outside(paths, root) -> list:
    root = os.path.normcase(os.path.realpath(root))
    return sorted({p for p in paths if not _inside(p, root)})


@pytest.fixture
def assert_inside():
    def check(paths, root):
        bad = outside(paths, Path(root))
        assert not bad, f"wrote outside {root}: {bad[:10]}"
    return check


def her_clicks(root):
    """Tests that write her review files directly: record her decisions for what they claim, as the UI does when she clicks (decisions.py)."""
    from gameanything import decisions
    for what, _ in decisions.claims(root):
        if not decisions.confirmed(root, what): decisions.record(root, what, "confirmed", via="test")
