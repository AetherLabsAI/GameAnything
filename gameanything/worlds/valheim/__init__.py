"""Valheim world (native mode): a smoke-test BepInEx 5 plugin (smoke/: a yellow banner "M2W smoke: plugin loaded" at the top of the
screen, and "[M2W-smoke] loaded" / "[M2W-smoke] scene -> <name>" in BepInEx/LogOutput.log). `gameanything native build --game valheim` compiles a
folder of *.cs (+ an optional *.csproj, e.g. the lab's ModLab.csproj) against this copy's valheim_Data/Managed and BepInEx/core (net462,
like the lab). Needs BepInExPack_Valheim. Test in a local world only: never join a public server with a test mod."""
from pathlib import Path

SMOKE = Path(__file__).parent / "smoke"
