# Add a game to GameAnything

Use this when someone wants GameAnything to work with a game it does not know yet ("add Terraria", "can I use it with my favourite
game?"), or when you contribute a game package as a pull request. The result is a **game package**: `gameanything/games/<id>/` in this
repository (a PR), or a separate pip-installable plugin (entry point group `gameanything.games`) that needs no fork. Terraria
(`gameanything/games/terraria/`) is the worked example: read its `game.yaml`, `adapter.py` and `smoke/` before you start.

The recon steps and the knowledge-base habit below borrow from Universal Modder's `game-recon` and `mod-any-game` skills (MIT, (c) 2026
Rehan and universal-modder contributors): its field notes (`knowledge/games/<game>/`) are worth a search before you touch anything.

## 0. Hard rules (stop if any is broken)

- **Never ship game files.** No DLLs, assets, executables or decompiled code of the game or its loader in the package, the smoke mod or
  the PR. Build against the user's own installed copy (reference it, `Private=false`), never copy it. `gameanything game check` refuses binaries
  in a smoke mod.
- **No DRM or ownership bypass.** A loader that needs the game (or itself, like tModLoader) in the Steam library stays that way. Never
  patch a launcher or a licence check, never point users at cracked copies or unofficial downloads of the game.
- **No anti-cheat, no online cheating.** If the game has anti-cheat (EAC, BattlEye, Vanguard, ...) or the mod would touch online play,
  ranked modes, other players or a server you do not own: do not add it, or limit it to an offline / single-player mode the developer
  allows, and say so in `game.yaml` (`launch.hint`) and the docs. Tests use a throwaway local save, never a public server.
- **Respect the game's mod policy / EULA.** If the developer forbids mods, stop and tell the user.
- **Her saves are sacred.** Every folder with saves goes into `saves:` so `native backup` copies it before the first install and
  `native restore` puts it back byte for byte. Cloud saves (Steam Cloud, the game's own) are not backed up: say so and test with local ones.
- Only the mods folder (and the loader's own switch file, e.g. `enabled.json`) is written by install; nothing is ever deleted (gameanything moves
  things to its trash).

## 1. Recon (about ten minutes, write it down)

1. **Install and versions:** where the game is (Steam app id and `steamapps/common/<dir>`, GOG, the developer's launcher), the game
   version, the systems it runs on (Windows / macOS / Linux native, Proton only?).
2. **Engine and code:** Unity Mono (a `<Game>_Data/Managed/Assembly-CSharp.dll`) or IL2CPP (`GameAssembly.dll`), XNA / FNA / MonoGame
   (.NET), Java (a jar), Unreal, Godot, a custom engine with scripts. That decides the loader and the toolchain.
3. **The community's mod loader:** search "<game> modding", the game's wiki, Nexus Mods, Thunderstore (Unity games: BepInEx packs),
   mod.io, the Steam Workshop, GitHub. Capture: the loader's name, official download page, **current version and install steps**, the
   game versions it supports, a hello-world mod, where mods go, where its log goes, and how mods are enabled (a folder? a json list?
   an in-game switch?).
4. **Saves, settings, logs:** the folders per system. Look for cloud-save defaults.
5. **Process and window:** the process name(s) per system (`ps`, Task Manager), the window title, how Steam starts it (a launch script?).
6. **Legality** (rules above): anti-cheat, online parts, the mod policy.
7. **Hot reload:** does the loader reload a changed mod without a restart (BepInEx ScriptEngine, a file watcher)? If only through a menu
   click, gameanything cannot automate it: say so in `reload.none`.

Choose the route: the loader's API > data / content packs > managed patching (Harmony) > anything lower. GameAnything only adds games
with a real loader route.

## 2. Scaffold and fill the package

```bash
gameanything game new <id> --title "<Game>" --loader <bepinex|smapi|tmodloader|fabric|modthespire|script|builtin|other> \
    --engine <engine> --steam-appid <appid>                 # in this checkout (for a PR)
gameanything game new <id> --title "<Game>" --loader ... --plugin ../m2w-<id>       # or a separate plugin (pip install -e ../m2w-<id>)
```

This writes `game.yaml`, `adapter.py`, `smoke/M2WSmoke/` (a skeleton for that loader) and a test file. Fill **every** `TODO`:

- `game.yaml`: `folders.game.marker` (a file only this game's install has), `folders.user` for each system (placeholders `{home}`
  `{documents}` `{appdata}` `{localappdata}` `{xdg_data}` `{xdg_config}` `{game}` `{user}` `{mods}`), `folders.mods`, `saves`
  (every save folder), `extra_files` (switch / settings files install changes), `logs`, `process_names`, `launch` (url + hint),
  `toolchain`, `loader` (`name`, `type`, `url`, `fix` + `fix_en`, `check`: files that exist once the loader is installed),
  `desc` + `desc_en` (the wizard's one line, Chinese + English), `window.how`, `reload.none` (or a `reload_mod` in adapter.py),
  `lab.supported` (false unless a gamebench lab runs it), `tests`. Chinese texts are what the page shows; every one needs its English.
- `adapter.py` (only what game.yaml cannot say): `build(src, name)` into `<data>/native/build/<name>/` (never into the game's folders;
  if the loader's build tool deploys by itself, redirect it, as Terraria does with `-tmlsavedirectory`), `check_installable(src)`
  (refuse what the loader would silently skip), `check_mod(src, it)` (headless checks for `gameanything native check`), `after_install` /
  `after_uninstall` (the loader's enable switch), `running()` / `pids()` when the process name alone cannot tell (a `dotnet` / `java`
  process). Delete the `adapter:` line when game.yaml is enough.
- `smoke/M2WSmoke/`: the smallest mod that logs `[M2W-smoke] loaded` and shows one thing on screen (banner, chat line, HUD message).
  If the game pauses when unfocused, make the smoke mod keep it running (Unity: `Application.runInBackground = true`).
- `LESSONS.md`: what builders and playtesters learn about this game, in two sections `## 开发` (builder) and `## 试玩` (playtester)
  (`gameanything game new` writes it empty; format in `lessons.md`). Every pitfall of your own round trip goes in as a lesson
  (`gameanything lessons add --game <id> --role builder --symptom … --cause … --fix … --evidence …`): the next person starts from it. Never
  saves, account names or paths with a user name in it; machine-only notes go into the local layer (`--local`). `gameanything game check` reads it.

Then `gameanything game check <id>` (or `--path <package folder>` before it is installed) until it prints `ok`.

## 3. Tests (fake folders, no game; CI runs them on Linux, Windows and macOS)

`tests/games/test_<id>.py` (a plugin: its own `tests/`). Use `gameanything.games.testing`: `fake_steam_app(tmp, appid, dir, files=[marker])`
and `make(id, tmp, env=..., sys_=...)`. Cover at least: the package check is clean; folders on all three systems; install -> the
loader's switch -> uninstall; backup -> restore byte-identical; refusing to install / restore while the game runs; `build` with a stand-in
toolchain (see `tests/games/test_terraria.py`); `check`; `reload` says why not. Run `python -m pytest -q`.

## 4. The native round trip on a real copy (needs the user's yes to open the game)

On a machine with the game, its loader and the toolchain (the project's `build_mode: native`):

1. `gameanything native doctor --game <id> --json` -> found, loader ok, toolchain ok (save the json).
2. `gameanything native build --game <id> gameanything/games/<id>/smoke/M2WSmoke` -> the staged mod.
3. `gameanything native check --project P --src <staged>`.
4. `gameanything native backup --game <id>` (also done by install when saves changed).
5. `gameanything native install --game <id> <staged>` (and the loader's switch).
6. `gameanything native launch --project P --reason "..."`: it posts the card; only her 「现在可以」 opens the game. Never start a game otherwise.
7. Verify: the log has `[M2W-smoke] loaded` (`gameanything native log --game <id> --grep M2W-smoke`), and `gameanything native shot --project P` shows
   the smoke mod's banner / message. Check it keeps running when another window is in front.
8. `gameanything native reload` if the game supports it; otherwise note the restart.
9. `gameanything native close --project P` (only the process gameanything opened), `gameanything native restore --game <id> <stamp>` -> saves byte-identical,
   `gameanything native uninstall --game <id> M2WSmoke`.

Record the result: a row in `docs/cross-platform.md` ("Verified on real games", any system; macOS steps in `docs/native-mac-checklist.md`), and
`verified:` in game.yaml (then `gameanything game list --write-docs`).

## 5. Optional: sandbox support

Only when the game has a sandbox image (`lab/images/<game>/`: Dockerfile, install.sh and the game's tool `ga-<game>`, added to
`gameanything/sandbox.py` IMAGES / TOOLS / STEAM_FOLDER and tested with its smoke mod, docs/sandbox-images.md): set `sandbox:` (build,
three_d) and keep `lab: {supported: true}`. Otherwise set `lab: {supported: false}` and the wizard offers native only.

## 6. Docs and the pull request

- `gameanything game list --write-docs` (docs/games.md's table; a test fails when it is stale), and a short section for the game in
  `docs/games.md` (folders, build, reload, what is not automatable).
- Open the PR with the "Adding a game" checklist of `.github/pull_request_template.md` (CONTRIBUTING.md): which OS you verified on,
  `native doctor --json`, the log lines, one screenshot, and the legality notes. Never attach saves or game files.
