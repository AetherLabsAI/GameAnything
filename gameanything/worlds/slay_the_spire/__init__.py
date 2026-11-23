"""Slay the Spire world (native mode): a smoke-test mod (smoke/: every run starts with 999 gold, and the log lines "[M2W-smoke] loaded" /
"[M2W-smoke] gold set to 999" in sendToDevs/logs/SlayTheSpire.log). Layout `gameanything native build --game slay_the_spire` reads, the same as the
lab's sts-build: src/**/*.java + resources/ModTheSpire.json (+ resources/<modid>/...) -> <modid>.jar. Needs ModTheSpire + BaseMod."""
from pathlib import Path

SMOKE = Path(__file__).parent / "smoke"
