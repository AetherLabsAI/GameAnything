# Setting: Mac, native (the user's own game)

GameAnything installs the mod straight into the user's own game on their Mac, using the Mac's own GPU. This is the recommended setting
on a Mac for 3D games and Minecraft (the sandbox has no GPU there). Saves are backed up first, only the loader's mod folder changes,
replaced files go to GameAnything's `.trash`, other mods are never touched, and native builds never use Docker.

## Checklist
- While a game runs: `gameanything native shot --project "$P"` after every launch / drive / close and at least every ~10 s while it starts or changes screens (SKILL.md 4d); dialogs and promos never show in the logs.
- `gameanything native doctor --game <game>` finds the game, the loader and the build tool (`build ok`).
- Install the missing build tool: a JDK (Java mods) or the .NET SDK (C# mods); see Prerequisites.
- `gameanything native permissions`: Accessibility and Screen Recording for the app that runs GameAnything (`--open` opens both settings pages).
- `gameanything native ready --project "$P" --if-needed --card-file "$TMPDIR/ready.yaml"` before the first launch and after an agent / model
  change: run by the agent itself, it reports `full` / `look` / `none` for THAT agent (its sandbox and the app it runs in: Terminal, iTerm,
  VS Code, Cursor, Claude.app; python when agentd / `gameanything ui` was started without a terminal) and the exact steps naming that app;
  below `full` the resident posts the one readiness card (docs/cross-platform.md §8a).
- Downloaded loaders and DLLs: remove the quarantine (`xattr -dr com.apple.quarantine <files>`).
- The game opens only through `gameanything native launch --project "$P"` after her 「现在可以」; close only with `gameanything native close --project "$P"`.
- Test in a throwaway local save; never join a server with a test mod.

## Prerequisites
- The game from Steam for Mac (or the EA app for The Sims 4), started once without mods.
- Build tools (only when the game's mods are compiled):
  - Java mods (Slay the Spire, Minecraft): a JDK, e.g. Adoptium Temurin unpacked to `~/.local/jdk` or `brew install --cask temurin`.
    Homebrew's `openjdk@17` needs Xcode on macOS 14.
  - C# mods (Stardew Valley, Overcooked! 2, Valheim, Cities: Skylines, Terraria, KSP): the .NET SDK 6 or newer
    (`brew install --cask dotnet-sdk`; 8 for Terraria and KSP).
  - The Sims 4 scripts: Python 3.7 (e.g. pyenv); the bytecode must be 3.7. A package-only mod needs none.
- Loader per game:
  - **Stardew Valley (SMAPI):** the installer from https://smapi.io (`install on macOS.command`; right-click > Open when Gatekeeper
    blocks it). A mod folder needs `manifest.json`, or `install` refuses. `native build --game stardew` uses `dotnet build` with
    Pathoschild.Stardew.ModBuildConfig (network on the first build). Log: `~/.config/StardewValley/ErrorLogs/SMAPI-latest.txt`.
    Content packs (`ContentPackFor: Pathoschild.ContentPatcher`) need Content Patcher in `Mods/` (https://www.nexusmods.com/stardewvalley/mods/1915): `native doctor
    --game stardew` shows it as `extra  Content Patcher` (a hint), `native check` refuses a pack without it.
  - **Minecraft (Fabric):** run the Fabric installer, start the `fabric-loader-…` profile once to create `mods/`, put Fabric API into
    `~/Library/Application Support/minecraft/mods/`. GameAnything cannot start Minecraft: the user starts it from the launcher.
    `logs/latest.log` lists the loaded mods.
  - **Slay the Spire (ModTheSpire + BaseMod):** subscribe in the Workshop, or `ModTheSpire.jar` in `SlayTheSpire.app/Contents/Resources`
    and `BaseMod.jar` in `mods/`. Steam for Mac offers "Play With Mods". Log: `sendToDevs/logs/SlayTheSpire.log` in the game folder.
  - **Overcooked! 2 (BepInEx 5, `macos_x64`):** unpack next to `Overcooked2.app`, remove the quarantine
    (`xattr -dr com.apple.quarantine BepInEx run_bepinex.sh *.dylib doorstop_libs`), `chmod +x run_bepinex.sh`, set
    `executable_name="Overcooked2.app"` in it, and **paste** the launch option from `gameanything native doctor --game overcooked2 --copy`
    into Steam (typing it turns quotes into curly quotes). Start once without mods so `BepInEx/LogOutput.log` exists.
  - **Valheim (BepInExPack_Valheim):** unpack the pack's `BepInExPack_Valheim/` next to `valheim.app`, remove the quarantine.
    `gameanything native launch` runs `start_game_bepinex.sh` itself (it sets `executable_name="valheim.app"` and re-runs under
    `arch -x86_64` on Apple silicon); the Steam client must be running. A Steam launch option did not load BepInEx.
  - **Cities: Skylines:** the Mac game has no compiler: `gameanything native build --game cities_skylines <mod> --install` (needs the
    .NET SDK). `install` switches the mod on; the game must be closed.
  - **The Sims 4:** `install` writes the `Options.ini` settings; the game must be closed.

## Settings to change
- System Settings > Privacy & Security > Accessibility, and > Screen Recording (macOS 15: "Screen & System Audio Recording"), for the
  terminal or app that runs GameAnything (`gameanything native permissions --open`). Needed for `native shot` and `native drive`.
- The game windowed, not fullscreen (`native launch` sets the ones it can and restores them at `close`).
- The project's 「什么时候开游戏」 policy (`gameanything project set-launch`).

## How to check
- `gameanything native doctor [--game <game>] [--json]`, `gameanything native permissions [--json]`.
- `gameanything native check --project "$P" --src <built mod>` (no game opened; Minecraft `--server` runs it headless).
- `gameanything native log --game <game> --grep <marker>`, `gameanything native mods --game <game>`.
- A full round trip for contributors: [docs/native-mac-checklist.md](../../../../docs/native-mac-checklist.md).

## Resources
- The game's own requirements. Apple silicon runs x86_64 loaders (BepInEx doorstop) under Rosetta; install Rosetta when macOS asks.

## Games in this setting
<!-- setup-games:begin (gameanything setup tables --write) -->
| Game | Verdict | Verified on this system | Why |
|---|---|---|---|
| Stardew Valley (`stardew`) | recommended | 2026-10-25 | Recommended: on a Mac use native mode, with the game and graphics card on your computer (saves are backed up first, only the Mods folder changes) |
| Minecraft (`minecraft`) | recommended | 2026-10-29 | Recommended: on a Mac use native mode, with the game and graphics card on your computer (saves are backed up first, only the Mods folder changes) |
| Cities: Skylines (`cities_skylines`) | recommended | 2026-10-24 | Recommended: on a Mac use native mode, with the game and graphics card on your computer (saves are backed up first, only the Mods folder changes) |
| Slay the Spire (`slay_the_spire`) | recommended | 2026-10-25 | Recommended: on a Mac use native mode, with the game and graphics card on your computer (saves are backed up first, only the Mods folder changes) |
| Overcooked! 2 (`overcooked2`) | recommended | 2026-10-25 | Recommended: on a Mac use native mode, with the game and graphics card on your computer (saves are backed up first, only the Mods folder changes) |
| The Sims 4 (`sims4`) | recommended | 2026-10-24 | Recommended: on a Mac use native mode, with the game and graphics card on your computer (saves are backed up first, only the Mods folder changes) |
| Valheim (`valheim`) | recommended | 2026-10-25 | Recommended: on a Mac use native mode, with the game and graphics card on your computer (saves are backed up first, only the Mods folder changes) |
| Terraria (`terraria`) | recommended | 2026-10-29 | Recommended: on a Mac use native mode, with the game and graphics card on your computer (saves are backed up first, only the Mods folder changes) |
| Sid Meier's Civilization VI (`civ6`) | recommended | 2026-10-29 | Recommended: on a Mac use native mode, with the game and graphics card on your computer (saves are backed up first, only the Mods folder changes) |
| Kerbal Space Program (`ksp`) | recommended | 2026-10-29 | Recommended: on a Mac use native mode, with the game and graphics card on your computer (saves are backed up first, only the Mods folder changes) |
| No Man's Sky (`nms`) | recommended | not yet verified | Not in the sandbox wizard: native mode is the way for this game |
<!-- setup-games:end -->

## Known pitfalls
- SIGTERM made Stardew show 「quit unexpectedly」: `native close` asks the app to quit like Cmd-Q first (fixed). Java games get SIGTERM.
- Clicks sent to a process (`CGEventPostToPid`) do not press buttons in Stardew and Slay the Spire: those use the real cursor, only when
  the game is in front and the user has been away (`mac_click: hid`).
- `drive` coordinates are points: on a Retina screen, screenshot pixels / 2.
- The process name `StardewModdingAPI` is 17 characters; check that `restore` refuses while the game runs.
- Slay the Spire: Steam Cloud may report a conflict after `restore`: choose the local files.
- Cities: Skylines: pressing CONTINUE on the Paradox launcher's welcome page logged the account out and the game did not start.
- The Sims 4: importing a module under `~/Documents` triggers a "wants to access Documents" prompt that blocks the game; the game
  rewrites `Options.ini` when it quits.
- The macOS keychain asks once on the first `gameanything backup token set`.
- Valheim: test saves must be local (Manage saves > Move to local); GameAnything backs up only `worlds_local` / `characters_local`.

## Tell the user before launching
- Their saves are backed up first and only the Mods folder changes; how to undo it (`native restore`, `native uninstall`).
- The game opens only after they say 「现在可以」 on the card; GameAnything closes only a game it opened, never by force.
- macOS will ask for Accessibility and Screen Recording for the app running GameAnything, and why (looking at and pressing keys in
  the game window only). Without them she can choose 「不给，我自己点」: the agent never presses keys and each round lists her clicks.
