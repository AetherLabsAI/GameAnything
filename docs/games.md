# Games

Every game GameAnything can make content for is a **game package** (`gameanything/games/<id>/`: `game.yaml`, optional `adapter.py`,
a smoke mod, tests) or a pip-installed plugin that adds one (entry point group `gameanything.games`). The new-project wizard, the
「换游戏」 dialog, `gameanything project new --game`, `gameanything native ...` and the lab's game tables all read the same registry.

- Bring your own game: [`skills/gameanything/references/add-a-game.md`](../skills/gameanything/references/add-a-game.md) (for agents and
  people), and [CONTRIBUTING.md](../CONTRIBUTING.md#adding-a-game) for the pull request.
- `gameanything game list` (this table, live, plugins included), `gameanything game new <id> --title ... --loader ...`, `gameanything game check <id> [--build]`.
- What agents learned about each game: the package's `LESSONS.md` (`gameanything lessons show --game <id>`; format in
  [`skills/gameanything/references/lessons.md`](../skills/gameanything/references/lessons.md)).
- Results of real round trips on real games: [cross-platform.md, "Verified on real games"](cross-platform.md#verified-on-real-games).

The table below is generated (`gameanything game list --write-docs`); a test fails when it is out of date.

<!-- games:begin (gameanything game list --markdown) -->
| id | Game | Engine | Mod loader | Steam app | Adapter | Lab | Verified on real games |
|---|---|---|---|---|---|---|---|
| `stardew` | Stardew Valley | xna-monogame (.NET 6) | SMAPI | 413150 | code (native/games.py) | yes | linux 2026-10-24, mac 2026-10-25, windows 2026-11-01 |
| `minecraft` | Minecraft | java (LWJGL) | Fabric | - | code (native/games.py) | yes | linux 2026-10-24, mac 2026-10-29, windows 2026-11-01 |
| `cities_skylines` | Cities: Skylines | unity-mono (.NET 3.5) | built-in | 255710 | code (native/games.py) | yes | mac 2026-10-24, linux 2026-10-25, windows 2026-11-01 |
| `slay_the_spire` | Slay the Spire | java (libGDX, LWJGL 2) | ModTheSpire + BaseMod | 646570 | code (native/games.py) | yes | linux 2026-10-24, mac 2026-10-25, windows 2026-11-01 |
| `overcooked2` | Overcooked! 2 | unity-mono (Unity 2017.4, .NET 3.5) | BepInEx 5 | 728880 | code (native/games.py) | yes | linux 2026-10-25, mac 2026-10-25, windows 2026-11-01 |
| `sims4` | The Sims 4 | custom (Python 3.7 scripts) | built-in (Options.ini) | 1222670 | code (native/games.py) | yes | mac 2026-10-24 |
| `valheim` | Valheim | unity-mono (Unity 6) | BepInExPack_Valheim (BepInEx 5) | 892970 | code (native/games.py) | yes | linux 2026-10-25, mac 2026-10-25, windows 2026-11-01 |
| `terraria` | Terraria | xna-fna (.NET 8) | tModLoader | 1281930 | adapter.py | yes | linux 2026-10-28, mac 2026-10-29, windows 2026-11-01 |
| `civ6` | Sid Meier's Civilization VI | custom (Firaxis, Lua + SQL/XML) | built-in (official mod support, Additional Content) | 289070 | adapter.py | yes | linux 2026-10-28, mac 2026-10-29, windows 2026-11-01 |
| `ksp` | Kerbal Space Program | unity-mono (Unity 2019.4, .NET 4.x) | built-in (KSP AddonLoader, GameData/<Mod>/Plugins) | 220200 | adapter.py | yes | linux 2026-10-25, mac 2026-10-29, windows 2026-11-01 |
| `nms` | No Man's Sky | custom (Hello Games, MBIN / MXML data) | built-in (GAMEDATA/MODS loose EXML / MBIN loader; checked against Windows build 25732212 / game 7.06) | 275850 | adapter.py | no | windows 2026-11-01 |
<!-- games:end -->

## Terraria (tModLoader)

The first game added through the package framework (`gameanything/games/terraria/`); verified on Linux 2026-10-28 (tModLoader v2026.8.3.0 from real Steam, full native round trip).

- **Two Steam apps.** tModLoader is a free app of its own (1281930); Terraria (105600) must be owned and installed, tModLoader reads its
  `Content/`. gameanything finds both through Steam's library files (or `GAMEANYTHING_TERRARIA_DIR` = the tModLoader folder, `GAMEANYTHING_TERRARIA_GAME_DIR` =
  Terraria's). Start **tModLoader**, not Terraria (`steam://rungameid/1281930`).
- **Folders.** tModLoader's user folder: Windows `Documents\My Games\Terraria\tModLoader`, Linux `~/.local/share/Terraria/tModLoader`
  (`$XDG_DATA_HOME`), macOS `~/Library/Application Support/Terraria/tModLoader`. In it: `Mods/` (`<Name>.tmod` + `enabled.json`, the list
  of enabled mods), `ModSources/`, `Players/`, `Worlds/`, `config.json`. Logs: `<tModLoader install>/tModLoader-Logs/client.log`.
- **Backups.** `Players/` and `Worlds/` (local saves) plus `Mods/enabled.json` and `config.json`. Characters and worlds saved to
  **Steam Cloud** live in Steam's `userdata/<id>/1281930/remote/` and are not backed up: test with a throwaway local character and world
  (the cloud icon off in the character / world list); never join a server with a test mod.
- **Build** (`gameanything native build --game terraria <mod folder>`; the mod folder has `build.txt`, `*.cs` and optionally `<Name>.csproj`).
  tModLoader 2022.x and later builds a mod like this: `dotnet build` of the mod's `.csproj`, which imports `ModSources/tModLoader.targets`
  (tModLoader writes that file; it imports `<install>/tMLMod.targets`). The targets compile the DLL with the .NET SDK (net8.0) and then
  run tModLoader's own packer, `dotnet tModLoader.dll -server -build <dir> -eac <dll>`, which writes `<save folder>/Mods/<Name>.tmod`
  and enables it. gameanything copies the source into its own build folder, writes its own `tModLoader.targets` there that adds
  `-tmlsavedirectory <build folder>` (`ExtraBuildModFlags`), so the `.tmod` lands in gameanything's folder and **not** in her `Mods/`;
  `gameanything native install` then copies it in (saves backed up first) and adds it to `enabled.json`. Needs the .NET 8 SDK (the packer runs on
  the .NET 8 runtime). The packer writes its own log into the tModLoader folder's `tModLoader-Logs/`. No space may be in the build path
  (the targets pass it unquoted): gameanything uses the temp folder then.
- **Check** (`gameanything native check`): the `.tmod` header and SHA-1, `Info` and `<Name>.dll` inside, the DLL's references against
  `tModLoader.dll` and its `Libraries/`, and whether her tModLoader is older than the one the mod was packed with.
- **Reload.** Not automatable without clicks: tModLoader reloads mods only from its menus (Workshop > Develop Mods > Build + Reload, or
  Mods > Reload). gameanything closes the game, installs the new `.tmod` and opens it again (one launch per round).
- **Running / close.** The game is `dotnet tModLoader.dll` (the dotnet tModLoader installs in `<install>/dotnet/`, or a system one):
  gameanything finds it by that command line (Linux: `/proc`, only when its working folder is this install; macOS: `ps`; Windows: PowerShell's
  process command lines, not verified yet) and closes only the process it started itself.
- **Lab** (2026-10-28): gamebench `hosting/launch_rt/terraria.sh` on the Steam sandbox `wc-cities` (tools `tr-build`, `tr-game`,
  `tr-world`, `tr-shot`, `tr-log`, host-side `record`; guide `hosting/modlab/terraria/rt/CLAUDE.md`): the lab's own save folder
  (`-tmlsavedirectory`), straight into a local lab world (`-skipselect`), one restart per round.
- **Smoke mod** (`gameanything/games/terraria/smoke/M2WSmoke`): `[M2W-smoke] loaded` in `client.log`, a yellow chat line
  `[M2W-smoke] hello from GameAnything` on entering a world, and full speed while the window is unfocused (`InactiveSleepTime = 0`, an
  idea from Universal Modder's Terraria notes, MIT).

## Sid Meier's Civilization VI (official mod support)

`gameanything/games/civ6`: a mod is a folder with one `<Name>.modinfo` (GUID id, `CompatibleVersions 2.0`, FrontEndActions /
InGameActions) and the Lua / XML / SQL files it lists; nothing is compiled.

- **Folders.** Linux (Aspyr build): `~/.local/share/aspyr-media/Sid Meier's Civilization VI` (the game takes the home from passwd and
  ignores `XDG_DATA_HOME` and `$HOME`); Windows `Documents/My Games/...`; macOS `~/Library/Application Support/...`. Mods in `Mods/`,
  the enabled switch in `Mods.sqlite` (`ModGroupItems` of the selected group); backups cover `Saves/` and `Mods.sqlite`.
- **Install / switch.** The game scans a new mod at its next start and switches a compatible one on by itself; GameAnything only
  edits rows the game made (game closed). `native check` / `build` refuse what the game would not load (no `CompatibleVersions 2.0`,
  missing files, bad XML) and warn about text files under a top-level `<LocalizedText>` (never loaded: use `UpdateText`).
- **Close.** SIGTERM makes the game show its "Are you sure?" box: `native close` says so and she clicks Yes. No hot reload.
- **Lab** (2026-10-28): gamebench `hosting/launch_rt/civ6.sh` on the Steam sandbox `wc-cities` (tools `c6-build`, `c6-game
  start / wait / play / resume / stop`, `c6-ui`, `c6-mods`, `c6-save`, `c6-log`, `c6-shot`, host-side `record`; guide
  `hosting/modlab/civ6/rt/CLAUDE.md`): the lab declines 2K's online terms, Play Now into a new single-player game, one restart per round.
  No Lua.log on the Linux build: proofs are on screen.
- **Smoke mod** (`gameanything/games/civ6/smoke/M2WSmoke`): text only, `Exit to Desktop [M2W-smoke]` on the main menu and
  `[M2W-smoke] loaded - Choose Research` in the World Tracker of a new game.

## Kerbal Space Program (KSP 1, the game's own plugin loader)

Added with `gameanything game new ksp --loader builtin` (`gameanything/games/ksp/`); verified on Linux 2026-10-25 (docs/cross-platform.md).

- **Folders.** Everything is in the game folder (Steam app 220200, `steamapps/common/Kerbal Space Program`; `GAMEANYTHING_KSP_DIR` pins it, e.g. a
  DRM-free copy from outside Steam): `GameData/` (mods; `Squad/` and `SquadExpansion/` are the game's own and are never touched),
  `saves/<profile>/` (plus the game's `scenarios/` and `training/`), `settings.cfg`, `KSP.log`. Unity's `Player.log`: Linux
  `~/.config/unity3d/Squad/Kerbal Space Program/`, Windows `%USERPROFILE%\AppData\LocalLow\Squad\Kerbal Space Program\`, macOS
  `~/Library/Logs/Squad/Kerbal Space Program/` (or `~/Library/Logs/Unity/`). KSP flushes `KSP.log` in batches; `Player.log` has the lines at once.
- **Backups.** All of `saves/` and `settings.cfg`. Steam Cloud is not used by KSP 1 for saves.
- **Build** (`gameanything native build --game ksp <folder with *.cs>`): a net472 DLL against the game's own `Managed/` folder (`KSP_Data`,
  `KSP_x64_Data` or `KSP.app/Contents/Resources/Data`) with `NoStdLib` + `FrameworkPathOverride`, so no NuGet reference packs and no network;
  an optional `*.csproj` gives the assembly name and extra `<Reference Include>` names. Staged as `<Name>/Plugins/<Name>.dll` plus the
  folder's other files (part `.cfg`, textures); `install` copies it to `GameData/<Name>/`.
- **Check:** the DLL's references against `Managed/` (and other mods' `Plugins/`), Mono 4.x rules, and whether it uses `KSPAddon`,
  `PartModule`, `ScenarioModule` or `VesselModule` (otherwise the game loads it but starts nothing).
- **Reload:** none; KSP loads plugins only at start-up (about 30 s to the main menu on the test machine). One launch per round.
- **Smoke plugin:** `[KSPAddon(Instantly)]` logs `[M2W-smoke] loaded` and sets `Application.runInBackground`; `[KSPAddon(MainMenu)]` posts
  a screen message and draws a banner `M2W smoke: plugin loaded`.
- **Legal:** offline single-player game, no anti-cheat; Squad / Private Division allow mods. Test in a throwaway save profile.
- **Lab** (2026-10-28, `lab: {supported: true}`): gamebench `agent/modlab/ksp/kslab_rt.py` (entry `hosting/launch_rt/ksp.sh`, builder guide
  `hosting/modlab/ksp/rt/CLAUDE.md`) on one seat of the shared lab sandbox `mclab-hlm-m1` (pool game `ksp`, 3 GB, GPU), the lab's own DRM-free
  KSP 1.12.5 Linux copy, no Steam. Each run gets its own game folder (hard links of a read-only base, own `GameData/` and saves); the
  KSPLabBridge plugin takes commands from files (scene, load a save or stock scenario, camera, orbit, hide UI, dismiss pop-ups, state);
  shots and clips are grabbed in the sandbox and encoded on the host.
