# {{Name}}: the smoke mod of {{title}} (a script mod)

For a game that loads scripts (Lua, Python, JavaScript, its own language) from a mods folder. Replace main.lua with the smallest
script the game's loader runs, in its language: it must write "[M2W-smoke] loaded" to the game's log and show one thing on
screen (a message, a banner). Keep the folder layout the loader expects (manifest file, entry script name).
