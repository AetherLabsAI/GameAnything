"""The Sims 4 world: the mod template a build starts from (template/: a script + a tuning package) and a smoke-test mod (smoke/: the
console command `m2w.hello` and the log line "[M2W-smoke] loaded"). Both have the layout `gameanything native build --game sims4` reads:
scripts/**/*.py -> <name>.ts4script (compiled with Python 3.7, the game's version) and package/ -> <name>.package (native/s4pkg.py).
The game must be run once, and Game Options > Other > "Enable Custom Content and Mods" + "Script Mods Allowed" switched on
(`install` does the latter in Options.ini). Sims 4 is native mode only: her own Windows / Mac."""
from pathlib import Path

TEMPLATE = Path(__file__).parent / "template"
SMOKE = Path(__file__).parent / "smoke"
