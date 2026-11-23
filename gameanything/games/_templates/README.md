Smoke mod skeletons for `gameanything game new <id> --loader <type>` (games/tools.py). Every file is copied into the new package's smoke/
with {{id}}, {{Name}} (the mod / assembly name, M2WSmoke) and {{title}} filled in. Each one does the same two things: logs
"[M2W-smoke] loaded" when the loader loads it, and shows something on screen (a banner, a chat line), so a real test can prove
build -> install -> load -> visible effect from the game's log and one screenshot.
