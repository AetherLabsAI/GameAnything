## What and why

<!-- One or two sentences. Link the issue / conversation if there is one. -->

## How it was tested

- [ ] `python -m pytest -q` passes locally
- [ ] Tried in the real app / game (say where), or not needed

## Adding a game (delete this section if the PR adds no game)

See CONTRIBUTING.md "Adding a game" and skills/gameanything/references/add-a-game.md.

- Game, store / app id, engine, mod loader (name, version, official URL):
- Verified on (real copy of the game): <!-- Windows / macOS / Linux + versions -->

- [ ] Legality: no game files or decompiled code in this PR; no DRM / ownership bypass; no anti-cheat or online play touched; tests used a throwaway local save
- [ ] `gameanything game check <id>` prints `ok` (paste the output below)
- [ ] Fake-folder tests in `tests/games/test_<id>.py` (folders on all three systems, install / switch / uninstall, backup / restore, build, check)
- [ ] Real round trip: doctor -> build -> check -> backup -> install -> launch (with the user's yes) -> loaded in the log + screenshot -> close -> restore byte-identical -> uninstall
- [ ] `LESSONS.md` in the package (sections ## 开发 / ## 试玩) with what the round trip taught (no saves, names or user paths)
- [ ] `gameanything game list --write-docs`; the game's section in docs/games.md; the result row in docs/cross-platform.md; `verified:` in game.yaml
- [ ] Not automatable, said honestly (e.g. reload only from the game's menu):

Evidence (attach or paste; never saves or game files):

- `gameanything native doctor --game <id> --json`:
- the log lines with `[M2W-smoke] loaded`:
- a screenshot of the smoke mod in the game:
- `gameanything game check <id>`:
