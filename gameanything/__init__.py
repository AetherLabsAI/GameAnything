"""GameAnything: memories -> experience board -> world plan -> playable game content."""
from . import envcompat as _envcompat

__version__ = "0.0.1"

_envcompat.adopt()          # the old M2W_* variables still work (the new GAMEANYTHING_* name wins); envcompat.py
