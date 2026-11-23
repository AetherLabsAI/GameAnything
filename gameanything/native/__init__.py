"""Native mode (D19): build and test in the user's own copy of the game, no container. Since 2026-10-24 each project chooses where its
builds run (config/project.yaml `build_mode: lab | native`, buildmode.py); a project without one gets the automatic rule: Linux with
docker and a gamebench kit = the lab, else native.

    doctor(game, project)   what this machine has: system, mode (the project's chosen one when given, else the automatic rule),
                            ffmpeg / dotnet / java, and each game (games.py)
    games.get(g)  the adapter of one game: folders, backup / restore, install / uninstall, mod switches, launch link, log
`gameanything native ...` is the command line for both.
"""
import os
import shutil

from .. import buildmode, osdirs
from .games import GAMES, NativeError, data_root, dotnet, get, java  # noqa: F401


def doctor(game: str = None, project=None) -> dict:
    """project: a project folder; then `mode` is its build_mode (`mode_source` project) unless it has none (`auto`), and `project` says which."""
    sys_ = osdirs.system()
    auto = buildmode.auto_mode(sys_)
    mode, src = buildmode.effective(project, sys_) if project else (auto, "auto")
    lab = mode == "lab"
    tools = {"ffmpeg": shutil.which("ffmpeg"), "ffprobe": shutil.which("ffprobe"), "dotnet": dotnet(), "java": java(sys_)}
    why = ("this project chose " + ("the lab (the server's docker sandbox)" if lab else "native: your own copy of the game, never docker (saves backed up first, only the Mods folder is changed)")
           if src == "project" else
           "Linux with docker and a gamebench lab: builds run in the lab" if lab else
           ("no docker lab here: " if sys_ == "linux" else "") +
           "builds use your own copy of the game (saves backed up first, only the Mods folder is changed); "
           "a sandbox on this computer instead: gameanything setup guide --mode sandbox")      # (no gamebench talk for a user: her Mac 2026-10-30)
    gb = buildmode.gamebench() if sys_ == "linux" else None; be = buildmode.backend() if sys_ == "linux" else None
    lab_info = {"backend": be, "gamebench": str(gb) if gb else None, "kit": sys_ == "linux" and buildmode.lab_kit(backend_=be),
                "pool": str(buildmode.pool_path() or "") or None if sys_ == "linux" and buildmode.pool() is not None else None}
    out = {"system": sys_, "mode": mode, "lab": lab_info, "mode_source": src, "auto_mode": auto, "mode_why": why, "data": str(data_root()), "tools": tools,
           "games": [get(g).info() for g in ([game] if game else GAMES)]}
    if project: out["project"] = {"path": str(project), "build_mode": buildmode.mode_of(project)}
    out["windows_package"] = osdirs.windows_package()
    return out
