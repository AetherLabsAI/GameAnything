"""Overcooked! 2 world (native mode): a smoke-test BepInEx 5 plugin (smoke/: a yellow banner "M2W smoke: plugin loaded" at the top of
the screen, and "[M2W-smoke] loaded" / "[M2W-smoke] scene -> <name>" in BepInEx/LogOutput.log). `gameanything native build --game overcooked2`
compiles a folder of *.cs (+ an optional *.csproj, e.g. the lab's) against this copy's Managed/ and BepInEx/core/. Needs BepInEx 5."""
from pathlib import Path

SMOKE = Path(__file__).parent / "smoke"
