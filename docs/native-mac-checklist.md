# How to verify a game on macOS (native mode)

A checklist for contributors who want to confirm that `gameanything native` works for a game on a real Mac, or who add a game
and need a macOS result for `verified:` in its `game.yaml`. Test small features only (a smoke mod), never a real project.
Record the result as a row in [cross-platform.md](cross-platform.md#verified-on-real-games).

The Mac native setting itself (prerequisites, build tools, loader notes per game, permissions, pitfalls) is in
[skills/gameanything/references/setups/mac-native.md](../skills/gameanything/references/setups/mac-native.md), the guide agents read;
this page adds only the test procedure.

The rules gameanything keeps, which the test should confirm:
- saves are backed up before anything is installed;
- nothing is restored or installed while the game runs (when gameanything can see that it runs);
- in the game folder only the loader's mod folder changes (`Mods/`, `mods/`, `BepInEx/plugins/`, …);
- anything replaced or removed goes to gameanything's `.trash`, nothing is deleted directly;
- mods that gameanything did not install are never touched.

## 0. Preparation (once)

```bash
git clone https://github.com/AetherLabsAI/GameAnything && cd GameAnything
python3 -m venv .venv && .venv/bin/pip install -e .
source .venv/bin/activate
gameanything native doctor                    # every supported game is listed; the ones you own show their folders
gameanything project new --title "native-test" --kind feature --game <game> --mode native
gameanything ui                               # open the "native-test" project: the launch card appears in its chat
```

Opening the game asks first: `gameanything native launch --project native-test --game <game>` posts a card
「要开游戏测一下，现在可以吗？」 in the project's chat. Answer 「现在可以」 on the page and run the same command again to open the game.
Starting the game yourself from Steam also works, but gameanything will not close a game it did not open.

Build tools and loaders: see [mac-native.md](../skills/gameanything/references/setups/mac-native.md#prerequisites).
`gameanything native doctor` shows `build ok` for the game once its tool is found.

## 1. The round trip (every game)

```bash
gameanything native doctor --game <game>          # loader found, mod folder, save folders
gameanything native backup --game <game>          # prints a stamp such as 20261024-153012-123456; `native backups` lists them
gameanything native build --game <game> <smoke folder> --install    # or: native install --game <game> <built mod>
gameanything native check --project native-test --game <game> --src <built mod>   # checks without opening the game
gameanything native mods --game <game>
gameanything native launch --project native-test --game <game>      # card first, then again after 「现在可以」
gameanything native log --game <game> --grep <marker>
gameanything native close --project native-test --game <game>
gameanything native restore --game <game> <stamp>
gameanything native uninstall --game <game> <mod name>
```

It passes when:
- the loader's log shows the mod loaded and `native log` prints the same lines;
- the mod's effect is visible in the game (the smoke mods show a banner or a message);
- `restore`, `install` and a second `launch` refuse while the game runs;
- `close` ends the game normally (no 「… quit unexpectedly」 report) and only a game gameanything opened;
- after `restore` the saves are byte-identical to before, and after `uninstall` the mod folder lists only what was there before.

Each game has a smoke mod under `gameanything/worlds/<game>/smoke` or `gameanything/games/<game>/smoke`.

## 2. Loader notes per game

In [mac-native.md](../skills/gameanything/references/setups/mac-native.md#prerequisites) (one source for agents and people).

## 3. Quiet mode (本机模式少打扰)

The rules are in [cross-platform.md](cross-platform.md#本机模式少打扰). Check in the "native-test" project:
1. `launch` posts one card and stays `pending`; a second call posts no second card; after 「现在可以」 it opens the game once.
2. `close` ends only the game gameanything opened; a game started from Steam is `not_ours`.
3. The time window and 「今晚 HH:MM 后」 answers delay the launch; `idle` waits until the computer was not used for N minutes.
4. Window settings (Slay the Spire, Minecraft `options.txt`, Stardew `pauseWhenOutOfFocus`) change at `launch` and come back at `close`.
5. `gameanything native permissions` lists Accessibility and Screen Recording for the terminal app; `--open` opens both settings pages.
6. `native shot` captures only the game window, even when another window covers it; `native drive` refuses while the user is active,
   and refuses a click when another app's window covers the point.
7. Unity games keep running in the background (`runInBackground True` in the log, frames still changing when unfocused).
8. Hot reload with BepInEx.Debug's ScriptEngine (`native reload --setup`, then `reload` of a new build): the banner changes in seconds.

## 4. What to report

One row per game:

| Game | doctor | backup | install | effect in game | log line | restore | uninstall | notes (error text verbatim) |
|---|---|---|---|---|---|---|---|---|

Attach `gameanything native doctor --json`, `gameanything native log --game <game> --lines 200` for each game, a screenshot of the
effect, and the full terminal output of any step that failed. Do not include saves, personal folders or anything else from your home.
