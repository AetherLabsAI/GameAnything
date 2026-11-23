# Setting: Windows, native (the user's own game)

GameAnything installs the mod straight into the user's own game on their Windows PC. Saves are backed up first, only the loader's mod
folder changes, replaced files go to GameAnything's `.trash`, other mods are never touched, and native builds never use Docker.
**No game has a verified native round trip on Windows yet** (the tests run on Windows CI with fake game folders only).

## Checklist
- `gameanything native doctor --game <game>` finds the game, the loader and the build tool (`build ok`).
- Install the missing build tool (.NET SDK, JDK, Python 3.7 for Sims 4 scripts); see Prerequisites.
- Do not run the game as administrator (Windows then blocks the keys GameAnything sends).
- `gameanything native ready --project "$P" --if-needed --card-file "$TMPDIR/ready.yaml"` before the first launch and after an agent / model
  change (run by the agent itself): no permission is needed on Windows, but the agent must run in her interactive desktop session (not SSH,
  a service or session 0; not while the screen is locked), and inside a packaged app (the Claude desktop app's Code tab, MSIX) files under
  AppData are redirected (`native doctor` warns). Below `full` the resident posts the one readiness card (docs/cross-platform.md §8a).
- The game opens only through `gameanything native launch --project "$P"` after her 「现在可以」; close only with `gameanything native close --project "$P"`.
- Ask the user to close Minecraft themselves before `restore` (Windows cannot see which `.minecraft` a running Minecraft uses).
- Test in a throwaway local save; never join a server with a test mod.

## Prerequisites
- The game from Steam (or the EA app for The Sims 4), started once without mods.
- Build tools: the .NET SDK 6 or newer, 8 for Terraria and KSP (`winget install Microsoft.DotNet.SDK.8`); a JDK for Java mods
  (e.g. Adoptium Temurin); Python 3.7 for Sims 4 scripts (`py -3.7`; the bytecode must be 3.7).
- The game's mod loader (doctor prints how to get it). BepInEx games (Overcooked! 2, Valheim) load through `winhttp.dll` +
  `doorstop_config.ini` in the game folder.
- Stardew Valley content packs (`ContentPackFor: Pathoschild.ContentPatcher`) need Content Patcher in `Mods/` (https://www.nexusmods.com/stardewvalley/mods/1915): `native doctor --game stardew` shows it as `extra  Content Patcher` (a hint: C# mods do not need it), `native check` refuses a pack without it.
- `gameanything` on PATH: `uv tool install ...`, or in a clone the `bin` folder (`bin/gameanything.cmd`).

## Settings to change
- The game windowed, not fullscreen (`native launch` sets the ones it can and restores them at `close`).
- The project's 「什么时候开游戏」 policy (`gameanything project set-launch`).
- Windows Security > Ransomware protection > Controlled folder access: allow the terminal / Python when it blocks writes to
  `Documents` (The Sims 4, Terraria keep their saves there).

## How to check
- `gameanything native doctor [--game <game>] [--json]`.
- `gameanything native check --project "$P" --src <built mod>` (no game opened).
- `gameanything native log --game <game> --grep <marker>`, `gameanything native mods --game <game>`.

## Resources
- The game's own requirements; the SDK / JDK and their caches need about 1-2 GB.

## Games in this setting
<!-- setup-games:begin (gameanything setup tables --write) -->
| Game | Verdict | Verified on this system | Why |
|---|---|---|---|
| Stardew Valley (`stardew`) | available | 2026-11-01 | The sandbox is recommended on Windows; native installs into the user's own game (saves backed up first, only the Mods folder changes) |
| Minecraft (`minecraft`) | available | 2026-11-01 | The sandbox is recommended on Windows; native installs into the user's own game (saves backed up first, only the Mods folder changes) |
| Cities: Skylines (`cities_skylines`) | available | 2026-11-01 | The sandbox is recommended on Windows; native installs into the user's own game (saves backed up first, only the Mods folder changes) |
| Slay the Spire (`slay_the_spire`) | available | 2026-11-01 | The sandbox is recommended on Windows; native installs into the user's own game (saves backed up first, only the Mods folder changes) |
| Overcooked! 2 (`overcooked2`) | available | 2026-11-01 | The sandbox is recommended on Windows; native installs into the user's own game (saves backed up first, only the Mods folder changes) |
| The Sims 4 (`sims4`) | available | not yet verified | The sandbox is recommended on Windows; native installs into the user's own game (saves backed up first, only the Mods folder changes) |
| Valheim (`valheim`) | available | 2026-11-01 | The sandbox is recommended on Windows; native installs into the user's own game (saves backed up first, only the Mods folder changes) |
| Terraria (`terraria`) | available | 2026-11-01 | The sandbox is recommended on Windows; native installs into the user's own game (saves backed up first, only the Mods folder changes) |
| Sid Meier's Civilization VI (`civ6`) | available | 2026-11-01 | The sandbox is recommended on Windows; native installs into the user's own game (saves backed up first, only the Mods folder changes) |
| Kerbal Space Program (`ksp`) | available | 2026-11-01 | The sandbox is recommended on Windows; native installs into the user's own game (saves backed up first, only the Mods folder changes) |
| No Man's Sky (`nms`) | recommended | 2026-11-01 | Not in the sandbox wizard: native mode is the way for this game |
<!-- setup-games:end -->

## Known pitfalls
- `native drive` presses keys (`SendInput`) only while the game is the foreground window; otherwise it refuses (exit 2,
  `not_foreground`). Only when she ticked 「测试时允许把游戏切到前面」 (`native_front: away`, `gameanything project set-launch <id> --front away`)
  AND she has been away 60 s (idle known) does it bring the game GameAnything opened to the front (restoring it when minimized) and record
  it as `fronted`; never while she is at the computer, never her own game. Not yet tested on a real PC.
- `native shot` uses `PrintWindow`; a GPU-drawn game can come out black: ffmpeg 8's `gfxcapture` filter is the fallback.
- Windows counts injected key presses as user input; `idle` ignores the 1.5 s after GameAnything's own last key.
- Paths: a user folder with Chinese characters, `Documents` / `AppData` redirected to OneDrive, and paths over 260 characters (long
  paths off) are handled in code but not yet verified on a real PC.
- Defender / SmartScreen can quarantine the launcher or a built mod DLL.
- Not yet verified: `taskkill` without `/F` closing every game cleanly, Valheim's doorstop and folders, the Cities: Skylines mod switch
  (the game must show the mod as enabled after `install`), Fabric and SMAPI loading the installed mod, the Sims 4 Python 3.7 compile.

## Tell the user before launching
- Their saves are backed up first and only the Mods folder changes; how to undo it (`native restore`, `native uninstall`).
- The game opens only after they say 「现在可以」 on the card; GameAnything closes only a game it opened, never by force.
- Windows has not been fully tested yet with real games: if something looks wrong, tell you, and nothing is deleted.
