"""memory2world became GameAnything (2026-10-27). What still works with the old names: M2W_* variables (envcompat), the config and data
folders (moved once, a link left behind), the macOS Keychain entries, and game plugins in the old entry-point group. The
`memory2world` package and the `m2w` command were removed before the public release (2026-11-01)."""
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from gameanything import envcompat, osdirs

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- environment variables
def test_old_names_are_adopted_and_the_new_name_wins():
    env = {"M2W_DATA": "/old", "M2W_NO_AGENTD": "1", "GAMEANYTHING_NO_AGENTD": "", "M2W_LAB_HOME": "/lab", "M2W_LEASES": "/l.json"}
    envcompat.adopt(env)
    assert env["GAMEANYTHING_DATA"] == "/old" and env["M2W_DATA"] == "/old"           # copied, the old one stays (other tools read it)
    assert env["GAMEANYTHING_NO_AGENTD"] == ""                                       # set: the new name wins, even when empty
    assert "GAMEANYTHING_LAB_HOME" not in env and "GAMEANYTHING_LEASES" not in env    # the lab's own names (gamebench) are not copied
    assert envcompat.get("DATA", env={"M2W_DATA": "/o"}) == "/o" and envcompat.get("DATA", env={"GAMEANYTHING_DATA": "/n", "M2W_DATA": "/o"}) == "/n"
    assert envcompat.get("X", "d", env={}) == "d"


def test_drop_removes_both_spellings():
    env = {"GAMEANYTHING_SESSION": "a", "M2W_SESSION": "b", "PATH": "/bin"}
    assert envcompat.drop(env, "SESSION") == {"PATH": "/bin"}
    assert envcompat.names("INSTANCE") == ("GAMEANYTHING_INSTANCE", "M2W_INSTANCE")


def test_a_supervised_run_never_inherits_an_old_session(monkeypatch):
    from gameanything import agentd
    env = agentd.clean_env({"M2W_SESSION": "stale", "M2W_INSTANCE": "x", "GAMEANYTHING_SESSION": "y", "PATH": "/bin"})
    assert env == {"PATH": "/bin"}


def test_the_package_adopts_old_names_at_import(tmp_path):
    code = "import os, gameanything; print(os.environ.get('GAMEANYTHING_DATA'))"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("M2W_", "GAMEANYTHING_"))}
    r = subprocess.run([sys.executable, "-c", code], env={**env, "M2W_DATA": str(tmp_path)}, capture_output=True, text=True, encoding="utf-8")
    assert r.stdout.strip() == str(tmp_path), r.stderr


def test_a_pin_variable_is_read_in_both_spellings(tmp_path):
    from gameanything.native import games
    d = tmp_path / "sdv"; d.mkdir()
    assert envcompat.legacy_pin("M2W_FOO_DIR") == ("GAMEANYTHING_FOO_DIR", "M2W_FOO_DIR")
    for var in ("GAMEANYTHING_STARDEW_DIR", "M2W_STARDEW_DIR"):
        g = games.get("stardew", sys_="linux", home=tmp_path / "h", env={var: str(d), "GAMEANYTHING_DATA": str(tmp_path / "data")})
        assert g._env_dir(g.pin_var) == d, var


# ---------------------------------------------------------------- folders
def test_old_config_folder_is_moved_and_linked(tmp_path, monkeypatch):
    if osdirs.system() == "windows": pytest.skip("XDG folders")
    base = tmp_path / "cfg"; old = base / "memory2world"; old.mkdir(parents=True)
    (old / "projects.yaml").write_text("projects: []\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(base))
    h = osdirs.config_home()
    assert h == base / "gameanything" and (h / "projects.yaml").read_text(encoding="utf-8") == "projects: []\n"
    assert old.is_symlink() and (old / "projects.yaml").is_file()                     # an older m2w still finds its files
    assert osdirs.config_home() == h                                                   # once only


def test_a_new_install_and_an_existing_new_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "d")); monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "d"))
    assert osdirs.data_home() == tmp_path / "d" / "gameanything" and not (tmp_path / "d" / "memory2world").exists()
    b = tmp_path / "b"; (b / "gameanything").mkdir(parents=True); (b / "memory2world").mkdir()
    assert osdirs.migrate_home(b) == b / "gameanything" and (b / "memory2world").is_dir() and not (b / "memory2world").is_symlink()   # both there: nothing moves


def test_no_link_possible_keeps_the_old_folder(tmp_path):
    b = tmp_path / "b"; (b / "memory2world").mkdir(parents=True); (b / "memory2world" / "f").write_text("x", encoding="utf-8")
    with mock.patch.object(osdirs.os, "symlink", side_effect=OSError("no privilege")):
        assert osdirs.migrate_home(b) == b / "memory2world"
    assert (b / "memory2world" / "f").is_file() and not (b / "gameanything").exists()


def test_old_project_list_still_opens(tmp_path, monkeypatch):
    """A projects.yaml written by memory2world (in ~/.config/memory2world) lists the same projects after the rename, no manual step."""
    if osdirs.system() == "windows": pytest.skip("XDG folders")
    from gameanything import projects
    base = tmp_path / "cfg"; old = base / "memory2world"; old.mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(base)); monkeypatch.delenv("GAMEANYTHING_HOME", raising=False)
    proj = tmp_path / "data2" / "memory2world" / "projects" / "wedding"; (proj / "config").mkdir(parents=True)
    (old / "projects.yaml").write_text(f"# Memory2World project list (m2w project ...).\n- id: wedding\n  title: 婚礼\n  path: {proj}\n  kind: memory\n",
                                       encoding="utf-8")
    assert [Path(e["path"]) for e in projects.load()] == [proj] and projects.resolve("wedding") == proj


# ---------------------------------------------------------------- plugins, deny lists
def test_plugins_in_the_old_entry_point_group_still_load():
    from gameanything import games
    class EP:
        def __init__(self, name, group): self.name, self.value, self.group = name, f"pkg_{name}", group
    eps = {"gameanything.games": [EP("a", "gameanything.games")], "memory2world.games": [EP("b", "memory2world.games"), EP("a", "gameanything.games")]}
    with mock.patch("importlib.metadata.entry_points", side_effect=lambda group=None: eps.get(group, [])):
        assert [e.name for e in games._entry_points()] == ["a", "b"]


def test_deny_lists_cover_both_command_names():
    from gameanything import agent_providers
    deny = " ".join(agent_providers.DENY_LAB_ENV)
    assert all(f"*{n} lab env*" in deny for n in ("gameanything", "m2w", "memory2world"))
