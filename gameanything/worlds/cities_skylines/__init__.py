"""Cities: Skylines 1 world: the mod template a build starts from (template/) and a smoke-test mod (smoke/: proves install ->
switched on -> loaded -> a city started by itself, in the log as "[M2W-smoke] city loaded"). On Windows / Linux the game
compiles Source/*.cs itself; the macOS game ships no compiler, so there `gameanything native build --game cities_skylines <mod>` compiles
Mod.csproj against the game's Managed assemblies first (native/games.py). `install` copies into Addons/Mods and switches it on."""
from pathlib import Path

TEMPLATE = Path(__file__).parent / "template"
