# Cross-platform checks (Windows, macOS, Linux)

`.github/workflows/ci.yml` runs on every push to `main`, every pull request, and by hand (Actions → ci → Run workflow).
No game is installed on the runners. The tests build fake game folders and fake saves in temp folders and make no network calls.

## What CI covers

| | ubuntu-latest (py3.10, py3.12) | windows-latest (py3.12) | macos-latest (py3.12) |
|---|---|---|---|
| `pip install -e .` with no optional extras (all dependencies ship binary wheels) | yes | yes | yes |
| `pytest`: `tests/test_native.py`, `tests/test_packaging.py`, `tests/test_crossplatform.py` | yes | yes | yes |
| Game packages (docs/games.md): `tests/test_games_registry.py` (built-in packages, an entry-point plugin, `gameanything game new / check`), `tests/games/test_<id>.py` (each game's fake folders on all three systems) | yes | yes | yes |
| Tests run again with `EncodingWarning` as an error (any text file opened without `encoding=`) | py3.12 only | | |
| CLI smoke test: `gameanything --help`, `project new` (path with a space), `project list`, `native doctor` (text and `--json`) | yes | yes | yes |
| UI smoke test (`.github/scripts/ui_smoke.py`): starts `gameanything ui` on a free port, fetches `/`, `/api/shell`, the JS / CSS / font files with urllib, then stops it | yes | yes | yes |

What `tests/test_crossplatform.py` checks:
- **Default folders.** Each game's folders on each system (Stardew Saves under `%APPDATA%\StardewValley` or `~/.config/StardewValley`; `.minecraft`;
  Cities: Skylines under `%LOCALAPPDATA%`, `~/Library/Application Support` or `~/.local/share`; the Steam folders; gameanything's own folders;
  The Sims 4 under `Documents\Electronic Arts\The Sims 4` (`%USERPROFILE%`, OneDrive-redirected or `文档`) or `~/Documents/Electronic Arts/The Sims 4`).
  Windows paths are checked as `PureWindowsPath` with a Chinese user name (`C:\Users\小雨`), so the Windows rules are tested on every runner.
- **Where builds run (`tests/test_buildmode.py`).** Each project has `build_mode: lab | native` in `config/project.yaml`, picked in the new-project
  wizard step 「在哪里做」. The recommendation table (`buildmode.options`) is checked for Linux, macOS and Windows; with and without a working
  lab (gamebench launch scripts for the engine: docker-rt or a local Docker; a bare Docker Desktop is not a lab); the game installed or not; a game with
  no native adapter; a game no sandbox in the broker pool runs; a multi-user hub and a headless server. Also: the wizard API writes the choice,
  `gameanything project new --mode`, `gameanything project set-mode`, `gameanything project migrate-mode` (opt-in), and that a project without `build_mode` keeps the old
  automatic rule (Linux with a docker client = lab, else native).
- **The take-home (带回家) round trip through the CLI.** `native doctor` → `backup` → `install` → `mods` → `log` → `restore` → `uninstall`,
  with plain paths, paths with spaces and Chinese, and paths over 260 characters. On Windows the long-path case is skipped if the machine has long paths turned off.
  The test checks four things:
  - every file-system write stays inside the test's temp folder (a Python audit hook records them);
  - in the game folder, only `Mods/` changes;
  - the old save and the uninstalled mod end up in gameanything's `.trash/`;
  - nothing of someone else's is uninstalled.
  One case runs the Windows rules (`%APPDATA%`, `tasklist`, UTF-8 output) on whatever system runs the test.
- **Minecraft and Cities: Skylines installs.** Minecraft installs a `.jar`. Cities installs with the real system's rules and sets the mod switch in
  `userGameState.cgs`. On Windows that switch's key is built from a path with backslashes.
- **The Sims 4 (`tests/test_native.py`, fake folders only).**
  - The user folder on Windows, macOS and a Linux Proton prefix, with OneDrive-redirected Documents and a localised folder name.
  - `Options.ini`: only `modsdisabled` and `scriptmodsenabled` change (CRLF kept); `Mods/Resource.cfg` is written only when missing.
  - Install, uninstall and backup; scripts at most one folder deep under `Mods`, packages at most five.
  - A package-only build read back with the ported DBPF reader; a mod with scripts and no Python 3.7 fails with a clear message.
    The real 3.7 compile test is skipped on machines without Python 3.7.
- **Slay the Spire and Overcooked! 2 (`tests/test_native.py`, `tests/test_crossplatform.py`, fake folders only).**
  - Slay the Spire: the game folder on each system (macOS: `SlayTheSpire.app/Contents/Resources`), ModTheSpire / BaseMod found in the
    game folder or as Steam Workshop items, saves + `preferences/` backed up and restored, a `.jar` with `ModTheSpire.json` installed into
    `mods/`, `build` = the lab's `sts-build` (javac `--release 8` + one jar; checked byte for byte against the lab's 读博 jar on Linux).
  - Overcooked! 2: `BepInEx/plugins/<name>/`, BepInEx + doorstop (`winhttp.dll` / `run_bepinex.sh`) detection, saves under Unity's
    persistentDataPath (`AppData\LocalLow\Team17\Overcooked2`, `~/Library/Application Support/Team17/Overcooked2`, `~/.config/unity3d/...`),
    `build` points the lab csproj's `Overcooked2_Data/Managed` hint paths at this copy's Managed folder (inside the app on macOS).
  - The CLI round trip for both with Chinese and space paths, and with the Windows rules.
- **Valheim (`tests/test_native_valheim.py`, fake folders only; one real compile where the lab's copy is on the server).**
  - The game folder on each system: `steamapps/common/Valheim` with `valheim_Data/Managed/assembly_valheim.dll` (Windows default
    `C:\Program Files (x86)\Steam\steamapps\common\Valheim`, Linux `~/.local/share/Steam/steamapps/common/Valheim`), macOS
    `valheim.app/Contents/Resources/Data/Managed` (either capitalisation; **the Mac layout is not verified**), a pin to the app bundle.
  - BepInExPack_Valheim (denikson, Thunderstore; the lab pins 5.4.2351) detection: `BepInEx/core/BepInEx.dll` plus the doorstop
    (`winhttp.dll` on Windows; `start_game_bepinex.sh`, or the lab's `run_bepinex.sh`, on Linux / macOS) and the Steam launch-option hint
    `"<game>/start_game_bepinex.sh" %command%`.
  - Saves = Unity's persistentDataPath `IronGate/Valheim` (`%USERPROFILE%\AppData\LocalLow\IronGate\Valheim`, `~/.config/unity3d/IronGate/Valheim`,
    `~/Library/Application Support/IronGate/Valheim`) with `worlds_local/` + `characters_local/` (and the older `worlds/` + `characters/`):
    backed up before an install, `Player.log` does not count as a change; Steam-cloud worlds (Steam's `userdata`) are not touched.
  - `build` from the lab's mod template (`ModLab.csproj` + `Plugin.cs` + `Lib/` + `assets/`; net462 with `FrameworkPathOverride` pointed
    at this copy's Managed folder), a minimal net462 csproj for a folder of `*.cs` (with `UnityEngine.TextRenderingModule`: the lab's hello
    example failed without it), `ValheimBridge.dll` never staged or installed; `check` (mscorlib 4.0 is right here; a .NET 5+ build is an
    error); `reload` through ScriptEngine with the `.pdb`; the CLI round trip with Linux, macOS and Windows rules and Chinese / space paths.
  - On the maintainer's lab server the smoke plugin is also compiled with the .NET 8 SDK against the lab's real `Managed/` and `BepInEx/core` (read only;
    the test checks the lab's `BepInEx/` is unchanged) and `check`ed. Skipped elsewhere.
  - **Valheim has online play.** Every test runs in a local world (Start Game > a world of the test, "Start server" off). Never join a
    public or community server with a test mod; `launch_hint` says so.
  - **Valheim saves to Steam Cloud by default** (new characters and worlds on Steam, seen 2026-10-25). Cloud saves live in Steam, not in
    `worlds_local` / `characters_local`, so gameanything's backup does not cover them: test with local saves (Manage saves > Move to local) and never
    touch her cloud saves.
- **本机模式少打扰 (`tests/test_native_quiet.py`, fake folders and fake processes only).** No yes on the card → pending and nothing
  opened; her click 「现在可以」 opens the game once (a second launch needs a new card); an answer not typed in the page does not count;
  「等我说」 and 「今晚 HH:MM 后」 (also another time written in the note); the `window` and `always` settings and the 10-minute gap; a game
  that is already running is never opened again and never closed; `close` ends only the process gameanything recorded (a real child process on
  POSIX; a reused pid is left alone); the small-window keys are put back key by key; ScriptEngine / Cities hot reload; the headless checks
  against tiny .NET assemblies and class files the test writes itself (`tests/_fakedll.py`), and a fake `java` standing in for the Fabric
  server; the project-menu API, the hub's role check and the dialog's English.
- **本机模式少打扰 2: idle, shot / drive, run in background (`tests/test_native_hands.py`, fakes only: no real input, no real screen).**
  Idle time from fake `ioreg` output (macOS), fake `GetLastInputInfo` / `GetTickCount` calls including the 49.7-day wrap (Windows), fake
  `xprintidle` / GNOME Mutter output and Wayland without GNOME = unknown (Linux); `native_launch: idle` opens only after N minutes away,
  posts no card while she is there, asks with the card when idle is unknown, keeps the 10-minute gap; `shot` / `drive` refuse a game she
  opened and when nothing is open, `drive` refuses while she was active in the last 60 s, stops in the middle when she comes back, does not
  count gameanything's own key as hers, needs the game in front on Windows, and drives anyway with `native_drive: always`; the permission texts
  (macOS System Settings paths, the app that gets the permission); the exact `xdotool` / `import` / `ffmpeg x11grab` command lines; the
  PNG writer; `Application.runInBackground = true` in the Unity smoke plugins and the Cities template; Stardew's `pauseWhenOutOfFocus`.
- **Text, files and processes.**
  - A source scan fails if any `open` / `read_text` / `write_text` in the package has no `encoding`, or any text-mode subprocess has no `encoding` / `errors`.
  - No `shell=True`, no POSIX-only calls.
  - Locks are taken and released 50 times, and a second lock is refused while the first is held.
  - Piped stdout and stdin are UTF-8 on Windows.
  - A Hugging Face token file works on Windows.
  - A `.env` file with a BOM can be read.
- **Projects and the conversation in Chinese.**
  - A project with a Chinese title in a folder with a space.
  - The thread: user words, an agent message with a Chinese-named attachment, a card. `thread.jsonl` must be byte-identical on every system (no `\r\n`).
  - `answers.md` gets the user's words.
  - `gameanything project new / list`, `chat say` (text on stdin) and `chat read` run as separate processes with stdout on a pipe, the way an agent runs them.
  - Export / import of a project with Chinese file names.
- **The browser UI.**
  - Pages and static files are served with the right content types.
  - Pictures, art, play videos and attachments with Chinese names and spaces are served (URL-encoded, as a browser sends them).
  - Attempts to step outside the project (`../`, `..\`) get 404.
  - A second `gameanything ui` started on the same port moves to the next free port.

## Verified on real games

Native mode (no docker, the user's own copy of the game), the whole take-home round trip on the real game:
`native doctor` (text and `--json`) → `backup` → `install` → `mods` → start the game → the mod loads and does its thing → `native log` → `restore` → `uninstall`.

| System | Game | Result | Date | How |
|---|---|---|---|---|
| Linux (Ubuntu 24.04, Python 3.12, no docker) | Stardew Valley 1.6.15 + SMAPI 4.5.2 | pass | 2026-10-24 | A lab sandbox used as a player's PC (own `HOME`): the game in `~/.local/share/Steam/steamapps/common/Stardew Valley` with an `appmanifest_413150.acf`, SMAPI from its official installer (`--install --no-prompt`), a real save in `~/.config/StardewValley/Saves`. A small mod built with `dotnet build` (.NET 8 SDK, ModBuildConfig 4.3.0, which found the game by itself). Started with the game folder's `StardewValley` launcher (what Steam runs), loaded the save: SMAPI log and HUD show the mod's message. Only `Mods/` changed (plus SMAPI's own `save-backups/` and `smapi-internal/`); the save came back byte-identical; `restore` refused while the game ran. |
| Linux (same) | Minecraft: Java Edition 26.3 + Fabric Loader 0.19.5 + Fabric API 0.162.0 | pass | 2026-10-24 | `~/.minecraft` laid out as the official launcher leaves it (`versions/26.3`, `libraries`, `assets`, `launcher_profiles.json`), then the official Fabric installer 1.1.0 (`client -dir ~/.minecraft -mcversion 26.3 -loader 0.19.5`). A small mod built with `./gradlew build` (JDK 25, Loom). Started without a Microsoft login: `portablemc --main-dir ~/.minecraft --work-dir ~/.minecraft start fabric-loader-0.19.5-26.3 -u NativeTester` (offline mode). Joined a world: `latest.log` and the chat show the mod's message. Only `mods/` changed (plus the game's own caches and `options.txt`); the world came back identical; `restore` refused while the game ran. |
| Linux (same, 2026-10-30, images built on the host from main) | Slay the Spire 2.3.4 + ModTheSpire 3.30.3 + BaseMod 5.56 (Workshop), Steam download in the sandbox | pass | 2026-10-30 | Game and Workshop mounted read-only from the Steam library volume (volume subpath); 12 s to the menu, "[M2W-smoke] hello" on screen; reuse 16 s; sha256 unchanged. Needed the umask fix (published images of 10-30 are root-only inside). |
| Linux (same) | Kerbal Space Program 1.12.5, Steam download | pass | 2026-10-30 | Xorg on the GPU, 46 s to the menu, "M2W smoke: plugin loaded"; reuse 51 s; sha256 unchanged. A fresh install shows the What's new dialog (docs/sandbox-hiccups.md #22). |
| Linux (same) | Terraria 1.4.4.9 + tModLoader v2026.8.3.0, Steam download | pass (after two fixes) | 2026-10-30 | tModLoader's EULA accepted for the user; its start script returns at once and the mod went to the wrong user folder (fixed, tests); then Mods List "M2W Smoke v0.1 Enabled", 21 s to the menu. 20261030c image, fresh volume: tModLoader's language picker and Welcome (fixed: the layer writes config.json), then 24 s to the menu with no click. |
| Linux (same) | Valheim + BepInEx 5.4.23.5, Steam download | pass | 2026-10-30 | GPU, banner on screen, run 4 s, reuse 20 s, sha256 unchanged. |
| Linux (same) | Overcooked! 2 + BepInEx 5.4.23.5, Steam download | pass | 2026-10-30 | GPU, banner on the title screen, run 9 s, reuse 23 s, sha256 of 8.2 GB unchanged. |
| Linux (same; the re-published 20261030b images, `--user 1004`) | Cities: Skylines, Steam download | pass (after two fixes) | 2026-10-30 | Paradox agreement accepted for the user; menu after 26 s, the smoke mod started a city ("city loaded"); reuse 35 s; sha256 of 16 GB unchanged. Fixed: menu detection, a leftover game process. |
| Linux (same) | Civilization VI, Steam download | pass (after two fixes) | 2026-10-30 | Segfault as uid 1004 without a passwd line (fixed: the image adds one); the in-game 2K agreement needs a 1600x900 screen (set in the civ6 Dockerfile: the base's ENV had overridden the tool's default); menu "Exit to Desktop [M2W-smoke]"; reuse ~2.5 min. 20261030c image: `--user 1004` with no workaround, menu in 4 s. |
| Linux (same) | The Sims 4 1.129.39.1030 under Wine + DXVK, EA App download | pass (after a fix) | 2026-10-30 | The user accepted EA's agreements and signed in; 26 GB in ~3 min; M2WSmoke listed in the Mods dialog; reuse signed in after 18 s. Fixed: the game re-starts itself through the EA App, and its window title has a ™. |
| Linux (same) | Slay the Spire 2.3.4 (12-18-2022) + ModTheSpire 3.30.3 + BaseMod 5.56 | pass (software GL, no GPU) | 2026-10-24 | The game in `~/.local/share/Steam/steamapps/common/SlayTheSpire` with an `appmanifest_646570.acf`, its own saves / preferences / runs; ModTheSpire installed by hand (`ModTheSpire.jar` next to the game, `BaseMod.jar` in `mods/`, both the Workshop files). The smoke mod (`worlds/slay_the_spire/smoke`) built with `gameanything native build` (JDK 25, `--release 8`), `native check` ok. Opened with the new gating: `gameanything native launch --project P` posted the card (exit 2), a second call did not post again, the 「现在可以」 answer went in through the page's own API (`POST /p/<id>/api/thread/answer` of `gameanything ui`), then `launch` opened `steam://run/646570` via `xdg-open`. No Steam client can log in in the sandbox, so a stand-in steam:// handler (registered in `~/.config/mimeapps.list`) ran what "Play With Mods" ends in: `jre/bin/java -jar ModTheSpire.jar` in the game folder. The mods were ticked and the run started with `gameanything native drive` (clicks to the game window only): the log has `[M2W-smoke] loaded` and `gold set to 999`, the top bar shows 999 gold. `restore` / `uninstall` / a second `launch` refused while it ran; `gameanything native close` ended exactly the recorded process. After `restore` + `uninstall` saves, preferences and runs were byte-identical to before (a run had been abandoned and a new one started in between); only `mods/` changed during the test (plus the game's own `sendToDevs/logs`). |
| Linux (same; real logged-in Steam client, NVIDIA GPU) | Cities: Skylines 1.21.1-f9 (the game's own loader) | pass, except hot reload | 2026-10-25 | A lab sandbox as a player's PC: own `HOME` with `~/.steam` as a Linux Steam install has it (`steam` -> the user's `~/.local/share/Steam`, whose library holds the game via a symlink + `appmanifest_255710.acf`; `sdk64`, `steam.pid`, `steam.pipe` -> the running client, which SteamAPI needs). The game was started once before (settings files of its own). The smoke mod built with `gameanything native build --name M2WSmoke` (.NET 8, net35), `check` ok, `backup`, `install` (switch `M2WSmoke-1316647758.enabled`). Gating as for Slay the Spire (card, answer through `gameanything ui`'s API, `launch` -> `xdg-open steam://rungameid/255710`). Steam's Play button cannot start a game in that pod, so the steam:// handler (registered in `~/.config/mimeapps.list`, real `xdg-open`) starts `Cities.x64` the way the Cities lab does. The log has `Assembly M2WSmoke ... loaded`, `[M2W-smoke] enabled (runInBackground True)`, `city loaded (NewGame)`; the main menu shows 1/6 mods enabled; the game itself rewrote `userGameState.cgs` with the switch still on. With another window focused the city kept running and rendering (same CPU time, frames changing). Hot reload: **no** (the DLL replaced in the city and in the main menu, by rename and in place: no reload within a minute; `reload` now says so on Linux). `close` ended exactly the recorded process; after `restore` the settings files were byte-identical. Paradox's Legal Disclaimer comes up in a fresh home; pre-writing the `legal.*` keys into `colossal.cgs` does not stop it. |
| Linux (same) | Overcooked! 2 + BepInEx 5.4.23.5 (linux x64 zip) + ScriptEngine r11.2 | pass | 2026-10-25 | The same home; a separate copy of the game (the game's own files hard-linked, BepInEx unpacked from the official zip into it) at `~/.local/share/Steam/steamapps/common/Overcooked! 2` + `appmanifest_728880.acf`; a profile save from one start before. Smoke plugin (`worlds/overcooked2/smoke`) built with `native build`, `check` ok, `install` into `BepInEx/plugins/M2WSmoke/`. Started through the steam:// handler with `run_bepinex.sh` (the launch option `launch_hint` prints). `LogOutput.log` has `[M2W-smoke] loaded (runInBackground True)`, the yellow banner is on screen; unfocused it kept running and rendering. `restore` / `uninstall` / a second `launch` refused while it ran; `close` ended the recorded process (the game ignores SIGTERM). Hot reload with BepInEx.Debug's ScriptEngine (her one-time setup: `ScriptEngine.dll` in `BepInEx/plugins/`, one start for its config, `reload --setup`): ScriptEngine reads symbols, so the plugin's `.pdb` must go along (fixed); then `gameanything native reload` of a new build while the game ran -> `Unloading old plugin instances` ... `v3 loaded`, the banner changed, about 3 s later. After `restore` the saves and `prefs` were byte-identical. |
| Linux (same; real logged-in Steam client, NVIDIA GPU) | Valheim 1.0.20 (Deep North) + BepInExPack_Valheim 5.4.2351 + ScriptEngine r11.2 | pass | 2026-10-25 | A fresh test home in the Steam sandbox; a separate copy of the game (the lab's game files hard-linked; BepInExPack_Valheim unpacked from the lab's sha256-checked zip as a user would, so the doorstop is the pack's own `start_game_bepinex.sh`) at `~/.local/share/Steam/steamapps/common/Valheim` + `appmanifest_892970.acf`. One plain start first: a throwaway character and a throwaway **local** world made through the menus (Start server off), entered once and saved. `doctor` (text and `--json`) ok; smoke plugin (`worlds/valheim/smoke`) built with `native build` (.NET 8, net462, with its `.pdb`), `check` ok against the real `Managed/` + `BepInEx/core`, `backup` (worlds_local + characters_local), `install` into `BepInEx/plugins/M2WSmoke/`. Gating as for Cities / Overcooked (card, a second call does not post again, 「现在可以」 through `gameanything ui`'s API, `launch` -> `xdg-open steam://rungameid/892970`; the steam:// handler runs what the launch option `launch_hint` prints: `start_game_bepinex.sh` with the game). `LogOutput.log` has `[M2W-smoke] loaded (runInBackground True)` and `scene -> start` / `main`; the yellow banner shows in the intro, the main menu and in the local world; with another window focused the game kept running and rendering (same CPU time, frames changing); `native shot` took only the game window. `restore` / `uninstall` / `install` / a second `launch` refused while it ran; `close` ended exactly the recorded process. Hot reload: ScriptEngine (her one-time setup) + `reload --setup`, a second round loaded the plugin from `scripts/` at start, then `gameanything native reload` of a v2 build while the game ran -> `Unloading old plugin instances` ... `v2 loaded by ScriptEngine hot reload`, banner changed, about 3 s later. After `restore` the worlds and characters were byte-identical (they had changed while playing); `uninstall` took the DLL and `.pdb`; the game folder differs only by her ScriptEngine setup. The lab's own Valheim folder was identical afterwards (paths, sizes, mtimes, link counts; BepInEx sha256). **Found:** on Steam, Valheim makes new characters and worlds as **Steam Cloud saves** by default (the test moved its throwaway ones to local with Manage saves > Move to local before playing); gameanything backs up only the local folders, so a test must use local saves. |
| Linux (same; NVIDIA GPU, no Steam client) | Kerbal Space Program 1.12.5.3190 (the game's own AddonLoader) | pass, no hot reload (by design) | 2026-10-25 | The first game added with `gameanything game new` (package `gameanything/games/ksp/`). A lab sandbox as a player's PC (own `HOME`): the lab's Linux copy of the game (without the lab's mod) copied to `~/.local/share/Steam/steamapps/common/Kerbal Space Program` + `appmanifest_220200.acf`, a throwaway save profile `saves/m2w-test`. `doctor --json` ok (.NET 8 SDK); the smoke plugin built with `native build` (net472 against the game's `KSP_Data/Managed`, offline: no NuGet), `check` ok against the real `Managed/` (4 assemblies, 25 types, 21 members), `backup` (saves/ + settings.cfg), `install` into `GameData/M2WSmoke/Plugins/`. Gating as for Cities (card, 「现在可以」 through `gameanything ui`'s API, `launch` -> `xdg-open steam://rungameid/220200`); KSP is DRM-free, so the stand-in steam:// handler starts `KSP.x86_64` in the game folder (`vglrun -d egl` on the seat's Xvfb screen). Player.log (and KSP.log, which KSP flushes in batches) has `[M2W-smoke] loaded (runInBackground True)` and `main menu message shown`; the banner is on the main menu (`native shot` took the game window); unfocused it kept rendering. `restore` / `uninstall` / `install` refused while it ran; `reload` says why not; `close` ended exactly the recorded process (SIGTERM). After `restore` + `uninstall` saves/ and settings.cfg were byte-identical and GameData listed only `Squad/` again. |
| Linux (Ubuntu 22.04.5 server, plain Docker Engine 29.5 / client 27.5, NVIDIA L40S, Container Toolkit in CDI mode): **sandbox** mode | Stardew Valley 1.6.15 + SMAPI 4.5.2, the Linux build downloaded by Steam inside the sandbox | pass (after fixes) | 2026-10-29 | `lab login steam`: first start to sign-in window 2 min 23 s on a local disk, the user signed in in the viewer, `--install` 508 MB in under 4 min (Linux depot: `libcoreclr.so`, no .exe); `ga-sdv layer` 2.3 s, smoke mod 6 s, game up in 8 s, new farm, HUD line on screen. Reuse (container removed, same volumes): signed in by itself in 13 s, nothing downloaded. The same folder mounted read-only from the host: sha256 unchanged after a full run with a new save. `--memory 700m`: killed in the sandbox only, now said plainly. Needed: the AppArmor 3 profile on 22.04, `~/.steam` folders in the image, `127.0.0.1` for the viewer on a server; 16 hiccups in `docs/sandbox-hiccups.md`. |
| Linux (same) | Minecraft: Java Edition 26.3 + Fabric 0.19.5, downloaded with a Microsoft account inside the sandbox | pass (after a fix) | 2026-10-29 | Device code, the user signed in on her own device (63 s); `ga-mc download` 710 MB in 28 s, hashes checked; GPU (`--gpus all`, java on the GPU per `nvidia-smi pmon`); 50 mods with m2wsmoke, chat line in a new world. Reuse: ownership re-checked from the saved token, nothing downloaded, in the world in 36 s. Game files and a 0600 world (owner = the host uid) mounted read-only: loaded, sha256 unchanged; Fabric API is now taken from the game folder when the worlds folder has none. |
| macOS | The Sims 4 | pass | 2026-10-24 | On a tester's Mac. |
| macOS | Cities: Skylines | pass | 2026-10-24 | On a tester's Mac. |
| macOS 14.6 (Apple Silicon M3, Steam for Mac) | Stardew Valley 1.6.15 + SMAPI 4.5.2 | pass | 2026-10-25 | backup → build/install → launch → close → restore → uninstall. The smoke mod logs `[M2W-smoke] loaded` / `save loaded` and shows `M2W smoke: mod loaded` in a new save. `restore` and a second `launch` refused while the game ran; `pauseWhenOutOfFocus` came back after `close`; the tester's own five mods were untouched. |
| macOS (same) | Slay the Spire 2.3.4 + ModTheSpire 3.30.3 + BaseMod 5.56 | pass | 2026-10-25 | Steam for Mac offers "Play With Mods". With both mods ticked a run starts with **999** gold; the log has `[M2W-smoke] loaded` / `gold set to 999`. close / restore / uninstall ok. |
| macOS (same) | Overcooked! 2 + BepInEx 5.4.23.4 (macos_x64) | pass | 2026-10-25 | The doorstop injects under Rosetta. Launch option `"<game folder>/run_bepinex.sh" %command%` with `executable_name="Overcooked2.app"` in the script. Log `loaded (runInBackground True)`, `scene -> StartScreen`, the yellow banner on screen. Running `run_bepinex.sh` from a terminal does not work (the game needs Steamworks and quits). |
| macOS (same) | Valheim (universal, arm64 + x86_64) + BepInExPack_Valheim 5.4.2351 | pass (the script started directly, not via a Steam launch option) | 2026-10-25 | Not blocked by the hardened runtime (the game allows DYLD environment variables). `start_game_bepinex.sh` needs `executable_name="valheim.app"` and a re-exec under `arch -x86_64` on arm64 (the doorstop is x86_64 only); `gameanything native launch` now prepares and runs it directly with the Steam client open (`Valheim.prepare_launch`). Log `Chainloader startup complete (1 loaded)`, `[M2W-smoke] loaded`, `scene -> start`, banner in the intro. Via the Steam launch option BepInEx did not load (cause not found; suspect: Steam's launch wrapper rewrites the injection variables); `arch -x86_64 "…" %command%` as a launch option fails with `Failed to spawn process`. The full gameanything launch → close → restore → uninstall round trip was repeated after the change. |

| macOS 14.6 (Apple Silicon, 8 GB, games on an external USB Steam library) | Kerbal Space Program 1.12.5 (Rosetta) | pass | 2026-10-29 | A user-style plugin `MacHello` (a green panel on the main menu; F8 changes its text and logs). `build` (net472 against the game's Managed/), `check`, `backup`, `install`, `launch`, `log` (`[MacHello] main menu panel up`), `shot` (panel visible), `drive` (5/5 F8 presses arrived; the panel read "F8 pressed N times"), `close`, `restore`, `uninstall`. Launched as `KSP.app` directly: through `steam://rungameid` the game process sat at 0 % CPU with no window (see below). |
| macOS (same) | Minecraft 26.3 + Fabric Loader 0.20.1 + Fabric API 0.165.0 | pass | 2026-10-29 | `MacCraft` from the official Fabric example template, Java 25 (Temurin) + `./gradlew build`. `check` saw Java 25 bytecode and `minecraft ~26.3`; `install` refused the `-sources.jar`; in a new single-player world the green join line, the diamond and `/machello` all worked (`[MacCraft] loaded / joined / /machello used`). The tester logs in to the launcher herself; run the Fabric installer while the launcher is closed (a running launcher overwrites the new profile). A game started from the launcher is not GameAnything's, so `shot` / `drive` refuse it by design. `check --server` not run (EULA not accepted yet). |
| macOS (same) | Terraria (tModLoader v2026.8.3.0, Terraria 1.4.4.9) | pass | 2026-10-29 | `MacTerra` (a Mac Sword item, 999 damage, given on entering a world, green chat line). `build` (tModLoader's own packer), `check`, `install` (enabled.json), `launch`, `log` (`[MacTerra] loaded`, `entered world …, gave the Mac Sword`), `shot`, `drive` (real cursor clicks through language, character, world and into the world), `close`, `restore`, `uninstall`. The first tModLoader start downloads its own .NET first (minutes). New worlds default to Steam Cloud (not in the local Worlds/): turn the cloud icon off for tests. |
| macOS (same) | Civilization VI (Steam build 15296837, Aspyr launcher v1.4.6) | pass | 2026-10-29 | `MacCiv` (a menu label, Warrior 99 strength renamed, +500 gold on turn 1): build, check, install, launch, in game Mac Warrior 99 melee and gold 510, close, restore, uninstall. First, macOS refused to open Civ6.app (「"Civilization VI" is damaged」: missing files of DLC scenarios the account does not own break the app's seal; `xattr -cr` is refused); fixed by the user with Aspyr's route: System Settings > Privacy & Security > Open Anyway, then start from Steam (opening it outside Steam gave 「Game configuration unavailable」). `launch` presses the launcher's PLAY and skips the intro by itself (51 s to the main menu, nobody clicking); `close` answers 「Are you sure?」. |
| macOS 14.6 (Apple Silicon M3, 8 GB) + Docker Desktop (Rosetta) | the user's own sandbox (Slay the Spire image) | fail: not supported on a Mac | 2026-10-30 | Image pull and `lab sandbox up` work; the Steam client in the sandbox (32-bit, under qemu-i386) crashes with signal 11 after its self-update, every start. Her decision: a Mac is native only (docs/sandbox-hiccups.md). |
| macOS 14.6 (Apple Silicon M3, 8 GB) + Docker Desktop, linux/arm64 + FEX-Emu | the user's own sandbox, experimental: Slay the Spire, Stardew Valley, Terraria | partial | 2026-10-31 | Prototype container: Steam signs in and downloads; Slay the Spire (ModTheSpire + BaseMod + smoke) and Stardew (SMAPI + smoke) reach their menus; tModLoader (.NET 8) crashed in 6 of 7 starts, mods or not. Wired into the wizard for Apple silicon (native stays recommended); the arm64 chain built locally (Slay the Spire, 5.5 GB) and reached Steam's sign-in in it. docs/sandbox-hiccups.md F1-F10. |
| macOS 14.6 (Apple Silicon M3, 8 GB), a fresh `uv tool install` (data on an external drive) | KSP, Civ VI, Terraria, Stardew, Slay the Spire, Minecraft: each game's smoke mod | pass | 2026-10-30 | As a new user: `native doctor` found the 7 installed games (Sims 4: Python 3.7 missing, hint fixed), `build` + `check` of every smoke mod, then per game `backup`, `install`, `launch`, the smoke line in the game's log (KSP and Civ VI also on screen: "M2W smoke: plugin loaded", "Exit to Desktop [M2W-smoke]"), `close`, `uninstall`, `restore`. Civ VI: PLAY and the intro by itself (1 min 24 s), the quit box answered. Slay the Spire: Steam remembered Play With Mods; m2w clicked ModTheSpire's Play. Minecraft: in this run `launch` could not start it (the user opened the Launcher, PLAY) and `close` of that game stopped without SIGTERM (m2w clicked Quit Game); the same evening `launch` learnt it: it opens the Launcher and presses PLAY when the last used installation is Fabric (14-15 s to the game, twice), and `close` sends the app's Quit ("Stopping!", no crash report in the Launcher). Found on the way and fixed: one build folder per game (a Mac disk ignores case: m2wsmoke / M2WSmoke collided). |
| macOS (same, fresh install), games on the external USB Steam library | The Sims 4, Cities: Skylines, Valheim, Overcooked! 2: each game's smoke mod | pass | 2026-10-31 | `backup`, `install`, launch, the mod seen, `close`, `uninstall`, `restore` for each. First start of every game from the USB drive: macOS verification of 5-20 min (process at 0 % CPU; a CoreServicesUIAgent progress window); Valheim's and Overcooked's BepInEx scripts `exec` the game binary and the first try ended silently during that check, the second start went through. The Sims 4: needs Python 3.7 (python.org 3.7.9 installer), starts only from the EA App's PLAY (`launch` cannot yet), Esc closes its start-up promos, an old copy of the smoke mod with the same module name shadowed the new one (its log showed the load). Cities: opens the Paradox Launcher (dowser) first: PLAY clicked with drive(launcher=); the main menu showed Paradox's Legal Disclaimer (she said 「同意，帮我点」); the smoke city loaded (money set); the game went full screen into its own Space, so `shot` now also finds an off-screen window. Valheim: BepInExPack_Valheim 5.4.2351 from Thunderstore, "M2W smoke: plugin loaded" on screen. Overcooked! 2: Steam launch option pasted by her (doctor --copy), "M2W smoke: plugin loaded" on the start screen. |
| Windows 11 ARM64 (build 26300, Chinese, 4 GB; a Parallels VM on the M3 Mac), a fresh install: uv 0.13.6, no Python, no git | install, `--help`, `native doctor`, `setup guide`; no game installed | fail, then pass after a fix | 2026-10-31 | The README line `uv tool install git+https://...` stops at "Git executable not found" (and the repo is private). From a copy of the repo, `uv tool install .\GameAnything` failed twice: uv took the newest Python, 3.15.2, where pyyaml has no Windows wheel ("Microsoft Visual C++ 14.0 or greater is required"); and OpenCC has no Windows ARM64 wheel for any Python (pip on 3.14: CMake, `CMAKE_CXX_COMPILER not set`). `bin\gameanything.cmd` failed the same way (`uv run --no-project` ignores requires-python). Fixed: `requires-python = ">=3.10,<3.15"` (with an empty uv Python folder uv then downloads 3.14.10 by itself), `opencc-python-reimplemented` on Windows ARM64 (the same `opencc` module; 這是一個測試 → 这是一个测试), `--python` in both launchers; tests in `tests/test_packaging.py`. Then `uv tool install`, `pip install` into a venv and `bin\gameanything.cmd` all work; `--help`, `native doctor` (text and `--json`: no games, ffmpeg / dotnet / java missing), `project new` in `C:\Users\wwy\GA 测试\win smoke`, `setup guide` (with and without `--project`) ran with exit 0. Also found: `native doctor` took 20 s with no game installed (a `tasklist` per game, a 9.5 s PowerShell process query for Terraria), so the new-project wizard's game list timed out (`tests/test_buildmode.py::test_wizard_api_and_project_menu`); a game not found is no longer looked for among the processes: 1.5 s. The whole pytest suite in the VM (Python 3.14 ARM64, after both fixes): 45 of 1291 fail, all of them tests that assume Linux or a UTF-8 locale rather than product bugs: 24 in `test_sandbox_images.py` (the images' shell scripts), symlinks without the privilege (WinError 1314), `os.getuid`, `chmod 0o700`, `/bin/false`, `sh` / `du`, `read_text()` without `encoding=` on a GBK system, CRLF from `write_text`; and a Ctrl+C that stopped pytest during `test_watchdog.py`. That Ctrl+C came from `test_sandbox_images.py::test_pid_files_from_before_a_container_restart_are_stale`: ga-sdv's pid check is `os.kill(pid, 0)`, and on Windows signal 0 is `CTRL_C_EVENT`, so with pytest's own pid in the pid file it sent Ctrl+C to the whole console (it lands at the next blocking wait, the watchdog snapshot's subprocess). The sandbox tools run only in Linux, so the test is skipped off Linux. Fixed in the follow-up: the tests (explicit encodings, no `"`/`|` in temp names, a waiting fake agent that exits 0 instead of `terminate()` (exit code 1 on Windows), the venv launcher's child pid, skips with reasons for symlinks without Developer Mode, mode bits, `node`, and the Linux-only image tools) and three product points: agent isolation is always off on Windows (as this doc and agent-isolation.md say; switched on it trusted the agent's own `id:`), the hub reads the request body before a 403 on a project POST (else Windows resets the connection and the page sees no answer), and the watchdog snapshot no longer fails where there is no `/proc`. Then the whole suite in the VM: 1222 passed, 91 skipped (each with its reason), none failed, no Ctrl+C. The smoke-mod round trip was skipped: no supported game is installed in the VM (no Steam, no EA app). |

### Found on macOS

Found in the macOS test of 2026-10-25 (commit ids where fixed; the numbers are cited in lessons):
1. `drive` did not check whether another window covers the game. **Fixed (841be67):** before a click it checks the window stack and bounds
   (`CGWindowListCopyWindowInfo`) and refuses when another app's window covers the point (code `covered`, exit 2); with
   `native_drive: always` it first brings the game to the front (`NSRunningApplication activate`). `shot` captures the game window
   itself even when covered, with a WARNING and `covered_by`.
2. `drive` clicks (`CGEventPostToPid`) did not press buttons in Stardew Valley and Slay the Spire. **Fixed (841be67):** per game `mac_click`
   (`hid` for those two: a real cursor move and click to the HID tap, cursor put back, only when the game is frontmost and the user has
   been away 60 s; `pid` for the others); `drive --click pid|hid` overrides it.
3. `gameanything native build --game stardew` was missing. **Fixed (841be67):** `dotnet build` + Pathoschild.Stardew.ModBuildConfig
   (`-p:GamePath=<game>`, its own deploy and zip off), a net6.0 `.csproj` when there is none, `manifest.json` / `EntryDll` checked, output in
   `<data>/native/build/<name>/mod/<name>/`, `--install` installs it.
4. `native doctor` did not find JDKs in `~/.local/jdk/*` or Homebrew (fixed: 7e80312 `games.java()`). Homebrew's `openjdk@17` needs Xcode on
   macOS 14; Adoptium Temurin 17 unpacked to `~/.local/jdk` works.
5. Closing Stardew Valley with SIGTERM made macOS show 「Stardew Valley quit unexpectedly」. **Fixed (841be67):** on macOS `native close`
   first asks the app to quit like Cmd-Q (`NSRunningApplication terminate`, else `osascript … quit`), SIGTERM only after 20 s; JVM games get
   SIGTERM directly. Still to confirm on a Mac that Stardew quits cleanly this way.
6. Valheim's `launch_hint` (0845c3f, 841be67): on macOS `native launch` runs the prepared `start_game_bepinex.sh`; no Steam launch option is
   suggested (`doctor` gives no `option` for Valheim on macOS).
7. Steam's launch-option field: `keystroke` drops spaces, `!`, `_` and turns quotes into curly quotes. **Handled (841be67):** paste instead
   (`pbcopy` + Cmd-V); `gameanything native doctor --game <game> --copy` puts the option on the clipboard.
8. The `claude` CLI used by `gameanything agentd` needs its own login; the desktop app's login is not shared. The page now says so (f4d6175).

Found in the macOS test of 2026-10-29 (KSP, Minecraft, Terraria, Civilization VI; fixed in the commit that adds these lines):
9. KSP through `steam://rungameid/220200` stayed at 0 % CPU without a window or a log line. **Fixed:** on macOS `launch_url` is the game's
   own `KSP.app` (`open -g`; KSP 1 is DRM-free).
10. `log` for KSP printed another game's lines: the candidates included `~/Library/Logs/Unity/Player.log`, which every Unity game writes.
   **Fixed:** dropped; the macOS Player.log is `~/Library/Logs/Squad/KSP/Player.log` (the product folder is `KSP`).
11. `drive` keys were lost on macOS (1 of 4 F8 presses arrived): a 20 ms press fell between frames, and the first key after bringing the
   game to the front was dropped. **Fixed:** `MAC_KEY_HOLD` 80 ms, 1 s after `bring_front` (5/5).
12. A game that appeared more than 15 min after `launch` (tModLoader's first start: macOS verification, then its .NET download) was never
   adopted, so `shot` said it was gone. **Fixed:** `quiet._adopt` decides by the process's own start time (within `ADOPT_SECS` of the launch).
13. `macapp.activate` (`NSRunningApplication activateWithOptions`) answers YES on macOS 14 but the app stays behind. **Fixed:** it checks the
   frontmost pid and falls back to System Events `set frontmost`.
14. Terraria: clicks posted to the process do nothing (FNA / SDL). **Fixed:** `mac_click: hid`. Real clicks with 50 ms steps were missed (the
   game polls the mouse once per frame; press and release fell between frames and the cursor was already back): `MAC_HID_STEP` 120 ms, and
   before a real click the game is brought to the front when it is not the active app (else the click only activates the window).
15. Terraria: keys posted to the process (Esc, 1-9) do nothing; typed text arrives. **Fixed:** `mac_keys: hid` (keys to the HID tap, same
   rules as real clicks). The window takes keys only after a real click inside the game picture (bringing it to the front or clicking the
   title bar is not enough).
16. Not fixed, worth knowing: macOS verifies a newly installed big game on its first start (Civ VI, 25 GB on USB: over half an hour) and other
   new apps wait behind it (the Minecraft launcher was 「not responding」); Steam shows an invisible launch-option chooser for games with more
   than one launch entry (KSP, Civ VI with LaunchPad); `restore` keeps saves created after the backup (test characters / worlds stay);
   closing Minecraft with SIGTERM makes the launcher report 「Exit code: 143」 although nothing crashed (no crash report, a normal
   `Stopping server` in the log).

Fixed on the way (Linux): `running` counted zombie processes and another copy of the game (a second install) as this game; Stardew `install`
took a `bin/Release/net6.0` folder without `manifest.json` (SMAPI skips it in silence); Minecraft `install` took a `*-sources.jar` or a folder;
Minecraft `running` was always unknown (now: a process with `--gameDir <this .minecraft>`, Linux and macOS).
`native shot` / `drive` on Slay the Spire (Linux X11) went to ModTheSpire's launcher window: the LWJGL 2 game window has no `_NET_WM_PID`,
so `xdotool search --pid` cannot see it (now: the game's exact window titles, `Game.window_titles`, when no other process owns that window).
Cities: Skylines on Linux (2026-10-25): `uninstall` wrote the switch as `false`, so after `restore` + `uninstall` her `userGameState.cgs` was no
longer the backed-up file (now: switching off removes the key; a mod without one is off); `reload` claimed the game reloads a replaced DLL
(it did not on Linux: now it says to restart). Overcooked! 2: ScriptEngine (r11.2) reads every `scripts/*.dll` with symbols, and
`build` / `reload` left the `.pdb` out (SymbolsNotFoundException, nothing loaded): now the `.pdb` goes along, `uninstall` takes it too, and
`reload`'s temp file no longer ends in `.dll` (ScriptEngine's watcher and loader see every `*.dll`); `reload --setup` no longer says the auto reload works at once (ScriptEngine reads its settings only when the game starts).

## What still needs a person on real hardware

CI runs no game, so these need a person on a real machine:
- **The game itself** (Linux Stardew / Minecraft and macOS Sims 4 / Cities: Skylines: see the table above).
  - `gameanything native launch --project P` after her 「现在可以」 (Steam opens the game; on macOS with `open -g`), and `gameanything native close` ending
    exactly that game (see 「本机模式少打扰」 below for what is untested).
  - SMAPI loading the installed mod on Windows and macOS.
  - Cities: Skylines compiling `Source/*.cs` at start-up (Windows, Linux).
  - Fabric loading the `.jar` on Windows and macOS.
  - What the mod does in the game.
- **The Sims 4 on Windows (macOS: see the table above).**
  - The localised folder names under `Documents\Electronic Arts` (the detection looks for `Options.ini` or `Mods`, not for a list of names).
  - The game loading the `.package` that `gameanything native build` packs (DBPF 2.1 written by `native/s4pkg.py`) and the `.ts4script`.
  - The Python 3.7 compile on Windows (`py -3.7`) and macOS (pyenv); the bytecode must be 3.7.
  - The game starting with the two `Options.ini` switches on, and rewriting `Options.ini` on exit (so `install` needs the game closed).
  - `TS4_x64.exe` / `The Sims 4` process names; the EA app has no `launch` link, so the user starts the game herself.
- **Slay the Spire, Overcooked! 2 and Valheim on a real Mac.** How to test: [native-mac-checklist.md](native-mac-checklist.md). Open questions: whether Steam offers
  "Play With Mods" on macOS, the BepInEx 5 macOS doorstop under Rosetta, the Overcooked! 2 save / log folders and process name, whether
  Valheim on Steam for macOS has a `valheim.app` with `Contents/Resources/Data/Managed` and where it keeps its worlds.
- **Valheim on Windows.** `winhttp.dll` + `doorstop_config.ini` loading BepInEx, `valheim.exe` in `tasklist`, `%USERPROFILE%\AppData\LocalLow\IronGate\Valheim`.
- **Cities: Skylines mod switch on Windows and macOS.** The `userGameState.cgs` key hashes the mod folder path *as the game writes it*. This was checked
  only on Linux: against a file the game wrote there, and (2026-10-25) the game loading the mod after `install` and rewriting the file with the switch still on. On Windows, check that the game shows the mod as enabled after `gameanything native install`. If it does
  not, the game uses a different path spelling (forward slashes, or different letter case).
- **Is the game running?**
  - The real `tasklist` (Windows) and `pgrep` (macOS) check while the game is open.
  - On macOS, the process name `StardewModdingAPI` is 17 characters. `pgrep -x` may compare only the first 16, so check that `gameanything native restore`
    refuses while SMAPI is running.
- **Windows Defender / SmartScreen.** A quarantined or blocked `m2w.exe` launcher, or a built mod DLL. Controlled Folder Access can block writes to `Documents`.
- **macOS Gatekeeper.** A downloaded mod or `.dll` gets the quarantine attribute (`xattr -l`). The macOS keychain prompt appears on the first `gameanything backup token set`.
- **Real profiles.**
  - A Windows user folder with Chinese or other non-ASCII characters, OneDrive-redirected `Documents` / `AppData`, and paths over 260 characters with
    long paths turned off.
  - The Windows console (as opposed to a pipe) showing Chinese.
- **Tools.**
  - `ffmpeg` / `ffprobe` and `dotnet build` on each system. CI checks only that `native doctor` runs, not that these tools work.
  - On Windows, `claude.cmd` from npm (perceive's `claude-code` backend). Arguments that go through a `.cmd` file are re-parsed by `cmd.exe`.

## 本机模式少打扰

本机模式（`build_mode: native`）的构建和测试在她自己的电脑上、用她自己的游戏跑。agent 反复开关游戏会打断她用电脑（2026-10-24 定下面这些规矩）。
代码在 `gameanything/native/quiet.py`（开 / 关游戏）和 `gameanything/native/checks.py`（不开游戏的检查、热重载）。

### 1. 开游戏之前先问她
- 只有 `gameanything native launch --project P` 能开游戏，旧的 `launch --game G --yes` 不再开游戏。
- 项目设置 `native_launch`（`config/project.yaml`，项目菜单「什么时候开游戏」，就在「在哪里做」下面；命令行 `gameanything project set-launch <id> ask|window|always|idle [--window 22:00-08:00] [--minutes 10] [--drive idle|always]`）：
  - `ask`（默认）：`launch` 在对话里发一张卡「要开游戏测一下，现在可以吗？」，选项是「现在可以 / 等我说 / 今晚 HH:MM 后」，然后返回 pending（退出码 2）。
    游戏只在她在**网页上点了**「现在可以」之后才会开（读的是 `conversation/thread.jsonl` 里她对这张卡最新的回答，和付费生成核对卡片的做法一样）。
    - 一次同意只开一次：用过的回答记在 `conversation/.native_launch.json`。
    - 「现在可以」2 小时内有效。
    - 「今晚 HH:MM 后」到点才放行；她在备注里写了别的时间（例如 23:30），就按那个时间。
    - 「等我说」：等她在对话里说可以了，再用 `--ask-again` 重新发卡。
    - 卡发出去她还没回答时，不会再发第二张。
  - `window`：只在她给的时间段里开（例如 22:00-08:00），时间段外既不开也不发卡，告诉 agent 几点以后再来。
  - `always`：不问，直接开。
  - `idle`（「我没在用电脑时」）：她 N 分钟（`native_launch_idle_minutes`，默认 10）没碰鼠标键盘才开，不问她；见下面第 7 节。
  - 两次开游戏之间不再强制间隔（2026-10-29 她决定去掉原来的 10 分钟规则）；一轮的改动仍然尽量攒在一起开一次测完。
- 游戏已经开着（可能是她在玩）：拒绝，退出码 3。不会再开一个，也不会关掉它。
  - 例外（2026-10-29 她的规则）：选了「我在用电脑时也可以」（`native_drive: always`）时，开着的游戏不管是谁开的都直接拿来测（state `open`，退出码 0，她开的记成 `took_over`）；这个游戏后来出现的进程（启动器拉起的游戏进程）也算，不再有 15 分钟认领窗口。`close` 对她开的游戏只请它正常退出（必要时点它的确认框），从不 SIGTERM。
- 开游戏之后的步骤（`Game.after_launch`：文明 6 在 macOS 上点 Aspyr 启动器的 PLAY、按 Esc 跳过开场动画）在自己的后台进程里跑（`native/afterlaunch.py`），调用 `launch` 的 agent 断开也不影响；结果写进 `gameanything native launches` 和 `<项目>/conversation/.native_after.log`。
- `--wait 秒数` 在后台等她点卡；`--dry-run` 只说现在能不能开，不开、不发卡。
- 卡是 gameanything 工具自己发的（session `m2w-native`），构建 agent 仍然不在对话里说话。

### 2. 只关 agent 自己开的游戏
- `gameanything native close --project P` 只结束 `launch` 记下来的那个进程：进程号相同，启动时间也相同。
  - 只发正常退出，从不强杀：Linux 是 SIGTERM，Windows 是不带 `/F` 的 taskkill。
  - macOS 先让游戏自己退出，和 Cmd-Q 一样（`NSRunningApplication terminate`；找不到时用 `osascript -e 'tell application id "<bundle id>" to quit'`，
    而且只在开着的只有 gameanything 开的那一个时才用）。等 20 秒还没退，才发 SIGTERM。原因：在她的 Mac 上，SIGTERM 会让星露谷弹出
    「Stardew Valley quit unexpectedly」。杀戮尖塔、我的世界是 Java 程序，JVM 收到 SIGTERM 会正常退出，所以直接发 SIGTERM（`Game.mac_quit`）。
    `close` 会打印用的是哪种方式。
  - 退不掉的话照实告诉她。
- 没有记录、或者游戏是她自己开的：一律不关。
- 我的世界和 EA app 里的模拟人生 4 不能从这里启动：`launch` 只告诉 agent 请她自己打开，这样开的游戏 gameanything 也不会关。

### 3. 一轮只开一次
- 先把这一轮的改动都做完、编译完，再跑 `gameanything native check`，查出来的错先改。
- 然后只 `launch` 一次，把所有改动一起测，测完 `close`。
- `launch --round <标签>` 给每次开游戏记上轮次。`gameanything native launches --project P` 列出每一轮开了几次，进度卡里要写「这一轮开了 N 次游戏」。

### 4. 不开游戏的检查：`gameanything native check --project P [--src 构建出来的 mod]`
不给 `--src` 时，查 gameanything 装过的所有 mod。下面的检查都不开游戏窗口：

| 游戏 | 查什么 |
|---|---|
| 星露谷 | `manifest.json`：字段、EntryDll 在不在、内容包要的框架有没有装。DLL 引用的程序集、类型、成员（按名字）对照游戏文件夹和 `smapi-internal/`。按 .NET 6 编的（游戏用 .NET 6）。 |
| 城市：天际线 | DLL 对照游戏的 `Managed/`：mscorlib 2.0（.NET 3.5），实现了 `ICities.IUserMod`，类型和成员都在。 |
| 胡闹厨房 2 | 插件 DLL 对照 `Managed/` 和 `BepInEx/core`：mscorlib 2.0，有 `[BepInPlugin]`，类型和成员都在。 |
| Valheim（英灵神殿） | 插件 DLL 对照 `valheim_Data/Managed/` 和 `BepInEx/core`：.NET Framework 4.x / netstandard（不能是 .NET 5 以上），有 `[BepInPlugin]`，类型和成员都在；`ValheimBridge.dll`（实验室的工具插件）不算。 |
| 杀戮尖塔 | `ModTheSpire.json`，Java 8 字节码，用到的每个类都在游戏、ModTheSpire、BaseMod、StSLib 的 jar 里。 |
| 我的世界 | `fabric.mod.json`：id、入口类、mixin 配置和里面的类、access widener，以及 mods/ 里有没有 Fabric API。 |
| 模拟人生 4 | `.ts4script` 是 Python 3.7 的 `.pyc`，放在 Mods 下最多一层；`.package` 能读。 |

- 程序集读取器（`native/clrmeta.py`）是纯 Python，只读文件。用一个真编译器编出来的 DLL（pythonnet 的 `Python.Runtime.dll`）手动对过。
- 成员只按名字查，不看参数。
- 继承自泛型基类的成员不追查，算作「不知道」，不报错。

**我的世界：无界面服务器（`check --server`，可加 `--gametest`）**
- 她先做一次准备：
  1. 用 Fabric 安装器 `java -jar fabric-installer.jar server -downloadMinecraft -mcversion <版本> -dir <gameanything 数据>/native/mc-server`
     （或者在 fabricmc.net/use/server 下载 `fabric-server-mc.*.jar` 放进这个文件夹；也可以用 `GAMEANYTHING_MC_SERVER_DIR` 指定别的文件夹）。
  2. 自己读 Minecraft EULA，在那个文件夹的 `eula.txt` 里写 `eula=true`。**gameanything 不替她同意。**
- 之后 gameanything 每次检查：
  - 只把这个 mod 和它依赖的、她 mods/ 里已有的 mod（例如 Fabric API）放进服务器的 mods/。上一次放进去的挪进 `.trash`。
  - 只在 127.0.0.1 上无界面启动（`online-mode=false`，没人能加入）。
  - 看到 `Done (` 就算加载通过，然后发 `stop` 关掉服务器。日志在 `mc-server/m2w-check.log`。
  - `--gametest` 加上 `-Dfabric-api.gametest`：跑 mod 自己写的 GameTest，跑完服务器自己退出，退出码 0 才算通过。
- 只在客户端运行的 mod（`environment: client`）服务器测不了，只做静态检查。

### 5. 热重载：`gameanything native reload --project P <构建出来的 mod>`
- **胡闹厨房 2、Valheim：可以，用 BepInEx ScriptEngine。**
  - ScriptEngine 来自 BepInEx.Debug（https://github.com/BepInEx/BepInEx.Debug，MIT 许可，可以再分发）。gameanything 不联网下载，她一次性把 release 里的 `ScriptEngine.dll` 放进 `BepInEx/plugins/`。
  - `reload` 把插件 DLL 和它的 `.pdb` 放进 `BepInEx/scripts/`。ScriptEngine 读 DLL 时一定要符号文件，没有 `.pdb` 就加载失败（`SymbolsNotFoundException`），开游戏时的这个错误还会让文件监视不启动。`native build` 会带上 `.pdb`。
  - ScriptEngine 只在开游戏时读一次它的设置：`reload --setup` 改的设置下次开游戏才生效。
  - 2026-10-25 在 Linux 上实测通过（ScriptEngine r11.2）：游戏开着时 `reload` 一个新构建，约 3 秒后旧插件卸载、新插件加载，画面上的横幅也变了。
  - 开过一次游戏以后，`BepInEx/config/com.bepis.bepinex.scriptengine.cfg` 才会出现。`reload --setup` 把里面的 `EnableFileSystemWatcher`（文件变了约 3 秒后自动重载，`AutoReloadDelay`）和 `LoadOnStart`（开游戏时就从 `scripts/` 加载）打开，原文件先备份。
  - 不打开自动重载的话，要在游戏里按 F6，gameanything 不碰键盘。
  - 重载时旧插件的 GameObject 会被销毁，所以插件要在 `OnDestroy` 里 `harmony.UnpatchSelf()`。
  - 同一个插件不要同时留在 `plugins/` 里。
- **城市：天际线：Linux 不行（2026-10-25 实测）；Windows / macOS 没验证过。** 照说游戏会发现已装 mod 文件夹里的 DLL 变了并重新加载它（在主菜单时最稳），但 Linux 版在城市里、主菜单里换 DLL（改名替换、原地写）一分钟内都没有重新加载，所以 `reload` 在 Linux 上直接说要重开游戏。
  - mod 要先在游戏关着的时候 `install` 一次，这样 mod 开关才会打开。
- **星露谷（SMAPI）、杀戮尖塔（ModTheSpire）、模拟人生 4：不能热重载**，改了要重开游戏。
  - Content Patcher 内容包可以在 SMAPI 控制台输入 `patch reload <id>`，但那要在她的电脑上打字，gameanything 不做。
- **我的世界：在她的启动器里不能热重载。**
  - 开发环境里 Loom 的 `runClient` 配 JetBrains Runtime（`-XX:+AllowEnhancedClassRedefinition`）和 HotswapAgent，可以换方法体。但那是开发者自己的客户端，不是她的游戏，所以 gameanything 不做。
  - 改用 `check --server` 少开几次游戏。

### 6. 真开游戏时：小窗口，不抢焦点
- `launch` 前，把下面这些设置临时改成窗口 / 小窗口（`--keep-window` 不改）。`close` 或下一次 `launch`（游戏关着时）再按键改回去。
  - 只改文件里本来就有的键，旧值备份在 `<gameanything 数据>/native/window/<游戏>.json`。
  - 她中途自己改过的键保持她的值，不会被改回去。
- 各个游戏改什么：
  - 我的世界：`options.txt` 的 `fullscreen:false` 和 `pauseOnLostFocus:false`（失去焦点也不暂停，测试时不用她的鼠标停在游戏里）。
  - 杀戮尖塔：`info.displayconfig` 改成 1280×720，不全屏。
  - 模拟人生 4：`Options.ini` 的 `fullscreen`、`resolutionwidth`、`resolutionheight`（**键名没在真游戏上验证过**；只在文件里本来有这些键时才改）。
  - 星露谷：不改文件。请她在游戏里「选项 > 窗口模式」选「窗口」一次，游戏会记住。
  - 城市：天际线、胡闹厨房 2、Valheim（Unity）：不改文件。请她在 Steam 启动选项里加一次 `-screen-fullscreen 0 -screen-width 1280 -screen-height 720`；胡闹厨房 2 和 Valheim 加在 `%command%` 后面。
- macOS 上用 `open -g` 打开 steam:// 链接，Steam 不会跳到前面。游戏窗口自己还是会出现，所以一轮只开一次是减少打扰的主要办法。

### 7. 我没在用电脑时：`native_launch: idle`
- `gameanything native idle` 打印她多少秒没碰鼠标键盘，或者 `unknown`（来源打印在 stderr）：
  - macOS：`ioreg -c IOHIDSystem` 的 `HIDIdleTime`（纳秒），不要权限。
  - Windows：`GetLastInputInfo`（ctypes）。注意 Windows 把程序发的按键（SendInput）也算作输入，所以 drive 记下自己最后一步的时间，那以后 1.5 秒内的输入算 gameanything 自己的。
  - Linux X11：`xprintidle`，没有就用 XScreenSaver 扩展（ctypes 读 libXss）。Wayland：GNOME 的 `org.gnome.Mutter.IdleMonitor`（`gdbus`），别的 Wayland 桌面不告诉别的程序：`unknown`。
- `launch` 在 `idle` 设置下：
  - 她离开不到 N 分钟：pending（退出码 2，code `busy`），**不发卡、不问她**。`--wait 秒数` 会一直看到她离开为止。
  - 离开够 N 分钟：直接开（code `idle`）。
  - 这台电脑看不出（`unknown`）：退回到 `ask`，发卡问她。
- 游戏开着、她回到电脑前（最近 60 秒内有输入）：`gameanything native drive` 停下（退出码 2，code `active`），launch 记录里写 `paused`。游戏不关（关只由 `close` 做），她自己的程序一个也不碰。等她再离开，agent 才继续；要再开游戏也要等她离开 N 分钟。

### 8. 只看、只按游戏，不抢焦点：`gameanything native shot / drive / permissions`
（思路来自 Universal Modder，MIT 许可，Copyright (c) 2026 Rehan and universal-modder contributors，https://github.com/rehan-remade/universal-modder 的 `um win drive`：按键只发给游戏、开车前先看 idle。没有拷它的代码。）
- 两个命令都只对 **gameanything 自己开的那个游戏**（`launch` 记下的进程）有效。她自己开的游戏、或者没有开着的：拒绝，退出码 3。
- `gameanything native shot --project P [--out x.png]`：只截游戏窗口（不是整个屏幕），默认存到 `<项目>/5_build/native-shots/`。不把游戏拉到前面，不需要她离开电脑。
- `gameanything native drive --project P "key escape" "click 640 360" "type hello" "sleep 500"`：
  - 坐标是游戏窗口里的（从窗口左上角算），单位是窗口的单位：macOS 上是「点」，Retina 屏上等于截图像素 ÷ 2（`shot` 发现图片和窗口大小不一样时会打印换算）。键名：a-z、0-9、return/enter、escape/esc、space、tab、backspace、方向键、f1-f12。
  - 她 60 秒内碰过鼠标键盘：不发（退出码 2）。看不出她在不在（`idle` 是 unknown）：不发（退出码 3）。
  - 她在「什么时候开游戏」里勾了「我在用电脑时也可以操作游戏窗口」（`native_drive: always`）才不看 idle。
  - 每一步之前再看一次；她中途回来就停下。
- 各系统怎么做到的：

| 系统 | 找窗口 | 截图 | 按键 / 点击 | 要什么 |
|---|---|---|---|---|
| macOS | `CGWindowListCopyWindowInfo`，按进程号 | `screencapture -x -o -l <窗口号>`（游戏被别的窗口盖住时照样截游戏自己的画面，但会打印 WARNING：游戏不在最前面时可能不刷新） | 按键：`CGEventPostToPid`，直接发给游戏进程，不切换前台。点击：先看游戏窗口前面有没有别的程序的窗口盖住点击的位置（`kCGWindowListOptionOnScreenAboveWindow` 的层次 + 窗口范围），盖住了就拒绝（code `covered`），不会点到别的程序里；`native_drive: always` 时先把游戏拉到最前面。星露谷、杀戮尖塔的按钮不认 `CGEventPostToPid` 的点击（她的 Mac 上验证过），所以这两个游戏用真实光标移动 + 点击（`CGEventPost` 到 HID tap，点完把光标放回原处），只在游戏是最前面的窗口、而且她离开了电脑时才点；选了 always 时随时可以点（2026-10-29 她的规则）。拉到前面后点击位置仍然被别的程序的浮动窗口盖住（例如 Claude 的面板）时，先把游戏窗口挪到屏幕左上角再看一次。每个游戏用哪种写在适配器的 `mac_click` 里；`drive --click pid\|hid` 可以临时换 | 运行 gameanything 的程序要有「辅助功能」（按键）和「屏幕录制 / 录屏与系统录音」（截图）权限 |
| Windows | `EnumWindows`，按进程号 | `PrintWindow`（`PW_RENDERFULLCONTENT`），纯 ctypes 写 PNG | `SendInput`，**只在游戏已经是最前面的窗口时**；不是就拒绝（退出码 2，code `not_foreground`）。她在项目菜单勾了「测试时允许把游戏切到前面」（`native_front: away`，2026-11-01 她的决定）时例外：**只在她离开电脑 60 秒以上（idle 看得出）**，drive 把 gameanything 自己开的游戏切到前面（最小化的先 `SW_RESTORE`；`AttachThreadInput` + `SetForegroundWindow`，不用 ALT 键的办法，免得打开她前台程序的菜单）再按，结果和 launch 记录里写 `fronted`（切之前最前面的是哪个窗口）；她一动就停；她在或看不出时从来不切（`native_drive: always` 也不切）。不主动切回去：关游戏时 Windows 自己把前台还给原来那个窗口 | 游戏不要用管理员身份运行（否则 Windows 挡住普通程序的按键） |
| Linux X11 | `xdotool search --onlyvisible --pid` | `import -window <id>`（ImageMagick），没有就 `ffmpeg -f x11grab` 截窗口那块屏幕 | `xdotool key/type --window <id>`（XSendEvent，不激活窗口）；点击要先把鼠标移到窗口里（`mousemove --window`），她不在时才会发生 | `xdotool`，`imagemagick` 或 `ffmpeg` |
| Linux Wayland | 不行 | 不行 | 不行 | Wayland 不让程序截别的窗口、给别的窗口发按键：拒绝，登录时换 X11 会话 |

- `gameanything native permissions [--open] [--json]`：只看、不改，不弹窗。macOS 上用 `AXIsProcessTrusted` 和 `CGPreflightScreenCaptureAccess` 查两个权限，告诉她去哪里打开：
  - 系统设置 > 隐私与安全性 > 辅助功能（System Settings > Privacy & Security > Accessibility）；
  - 系统设置 > 隐私与安全性 > 录屏与系统录音（macOS 15 起；14 及以前叫「屏幕录制」）。
  - 权限给的是**运行 gameanything 的那个程序**（终端、iTerm、VS Code、agent 的 app；后台的 agentd 是它的 python），不是 gameanything。命令会打印它找到的 app 名字。打开开关后要把那个程序退出重开。`--open` 打开这两个设置页。
- 截图全黑（Windows 上用显卡画的游戏常见）：改用 ffmpeg 8 的 `gfxcapture` 滤镜（Windows.Graphics.Capture，能截被盖住的窗口），例如
  `ffmpeg -filter_complex "gfxcapture=hwnd=<窗口号>,hwdownload,format=bgra" -frames:v 1 shot.png`（窗口号就是 `gameanything native shot` 打印的那个；也可以用 `window_exe=Overcooked2\.exe`）。
  要 ffmpeg 8 以上、带 gfxcapture 的版本（`ffmpeg -filters` 里有 ` gfxcapture `）。**没在 gameanything 里接上，也没在真机上试过**。
- 老实话：有的游戏只认「真的」输入，不认发给它的事件（macOS 上不在前台时不读键盘、Linux 上不认 XSendEvent、DirectInput / raw input 的游戏）。不认的话 drive 会显示发了，但游戏没反应：用截图确认，再改用 mod 里的命令（例如 Cities 的 citybuilder 桥、Overcooked 2 的插件命令）。

- 为什么 `native_front` 是新的一项、不复用 `native_drive: always`：`always` 的意思是「我在用电脑时也可以」，macOS 上它同时允许把游戏拉到前面；
  Windows 的这次决定是「只在我不在时才切」。一个键说不清这两件事，所以分开：`native_front` 只在 Windows（要前台才能发按键的后端）上有用，macOS / Linux 的行为没变。

### 8a. 能不能操作屏幕：`gameanything native ready`
（2026-11-01）agent 能不能看、点她的游戏，由两层决定：
1. **agent 框架**：它能不能运行命令，它的沙箱让不让 `gameanything native shot / drive` 碰到窗口系统（macOS WindowServer、Windows 桌面、X11）。
2. **系统**：macOS 要给**负责的 app**（运行 agent 的终端 / iTerm / VS Code / Cursor / Claude.app；agentd 或 `gameanything ui` 不是从终端开的时候就是那个 python）
   「辅助功能」（按键）和「屏幕录制 / 录屏与系统录音」（截图）；Windows 不要权限，但要在她登录的桌面会话里（不是 SSH、服务、会话 0、锁屏），游戏不能是管理员身份（UIPI），
   在打包的 MSIX app 里（例如 Claude 桌面 app 的 Code 页）AppData 下的新文件夹会被挪走（`osdirs.windows_package`，装 mod / 备份受影响）；Linux 要 X11（不是 Wayland）、xdotool、ffmpeg 或 ImageMagick。

- `gameanything native ready [--project P] [--role chat|build] [--if-needed] [--card-file F] [--json]`：**从调用它的进程里查**，所以 agent 自己跑它，查到的就是这个 agent 的沙箱和 app。
  打印的语言：`--lang zh|en`，不写就跟项目的 lang，没有项目就是英文（和 `lab login` 一样；`native permissions` 也有 `--lang`）。每一项都有中英两份（`--json` 里 name / why / how 是中文，`en` 里是英文），卡片的英文版、项目菜单的步骤（`fix_en`）也是英文的。
  用 `hands.permissions()` 的结果，再真截一小块（macOS：菜单栏左上角 16x16，`screencapture -R`；Linux：屏幕左上角 16x16，ffmpeg x11grab / import；Windows：屏幕正中 32x32，BitBlt 只在内存里），
  只看像素是不是全一个颜色，临时文件马上删，不保存、不发送、不写日志。**从不发按键或点击来试**（按键能不能到，只能看权限；在沙箱里会写「未实测」）。
  退出码：0 = `full`（能看能点），1 = `look`（只能看），3 = `none`。每一项都写原因和怎么改（点名那个 app）。环境变量里看得出 Codex 沙箱（`CODEX_SANDBOX`、`CODEX_SANDBOX_NETWORK_DISABLED`）
  或者报错像沙箱挡的（Operation not permitted、sandbox、bwrap…）时会说出来；**从不为这个关掉或放宽任何沙箱**。
- `--project`：结果记在 `<项目>/conversation/.native_ready.json`，按角色（chat = 常驻，build = 构建）记下是给哪个 agent + 模型查的、什么时候查的；
  `--if-needed` 在 agent / 模型没变时直接用记录。项目换了 agent 或模型就重新查（权限属于 app / 沙箱）。`native launch` 发现没查过会在 stderr 提醒。
- 什么时候查：本机模式第一次 `native launch` 之前（常驻 agent 在本机准备时做），项目换了 agent / 模型以后。
- 不到 `full`：常驻 agent 用 `--card-file` 写好的卡片发**一张**卡（`gameanything chat card`，key `native-ready`）：她要做的每一步，两个选择
  「我打开了，再查一次」/「不给，我自己点」。卡还开着就不再发（`next: wait`）。她点「不给，我自己点」后再跑 `native ready` 会写下 `native_hands: self`：
  之后 drive 一律拒绝（code `self`，退出码 3），每一轮的进度卡写清楚要她点哪里，等她说「好了」；shot 也不行时请她发截图或描述。项目菜单「什么时候开游戏」里显示最近一次检查的结果，
  「谁来点游戏」可以随时改回来。

| agent 框架 | 能运行命令 | macOS：权限给谁 | Windows | 沙箱 | 预期 | 实测 |
|---|---|---|---|---|---|---|
| Claude Code，终端里（Terminal / iTerm / Windows Terminal） | 能 | Terminal / iTerm | 在她桌面里开的终端：可以；SSH 进去的不行 | 默认没有（开了 Claude Code 自己的 sandbox 时未实测） | full | 她的 Mac 上 shot / drive 用过（2026-10）；`native ready`：Terminal.app 认得对，但那次的 Terminal 是从 Claude 桌面 app 拉起来的（继承了它的环境），结果不算数，要她自己开 Terminal 再跑；发现菜单栏不要「屏幕录制」也截得到，试截这一项在 Mac 上没有权限时改成「说明不了」。2026-11-01 她自己开的 Terminal：`look`（`Terminal.app`，有屏幕录制、没有辅助功能），结果对；她给 Terminal 打开辅助功能、退出重开后再跑：`full` |
| Claude Code，VS Code / Cursor 里 | 能 | Visual Studio Code / Cursor | 同上 | 没有 | full | Mac 2026-11-01，她在 Cursor 自带的终端里跑：`look`，认出 `Cursor.app`（有屏幕录制、没有辅助功能；Terminal 的权限不算 Cursor 的），结果对。VS Code 未实测 |
| Claude 桌面 app 的 Code 页 | 能 | Claude | 可以；**是 MSIX 打包的 app**：AppData 下的新文件夹被挪到它的 LocalCache（装 mod、备份要在普通终端里做），看、按游戏未实测 | 未知 | full（Windows：看、按未实测） | Mac 实测 2026-11-01：`full`，认出「Claude 桌面 app」；权限落在 Code 页自带的 claude.app（`~/Library/Application Support/Claude/claude-code/<版本>/…`，经 Claude 的 disclaimer 启动），不是 Claude.app 本身（推断，没读 TCC 库）；之前错报成 Python.app，已修 |
| Claude 对话 / claude.ai / Claude in Chrome | **不能**（不能在她电脑上运行命令） | — | — | — | gameanything 跑不了：要么换成上面能跑命令的，要么她自己点、自己截图 | — |
| Codex（CLI / app） | 能，但每条命令都在它自己的沙箱里（`workspace-write`；macOS seatbelt，Linux bubblewrap / landlock） | 运行 Codex 的终端 / app | 未知 | **很可能挡住截图和按键**；绝不为这个放宽 | 要实测：`native ready` 会写出沙箱 | Mac 实测 2026-11-01（codex-cli 0.166.0，`exec --sandbox workspace-write`）：`none`，认出 `Codex (seatbelt)`；两个权限检查在沙箱里都报「没有」，而沙箱外同一个 app 两个都有，所以缺权限的步骤改成「别放宽沙箱：换 agent 或自己点」；卡片 → `wait` → 「不给，我自己点」→ `native_hands: self` → drive 拒绝（code self，退出码 3）都走通。2026-11-01 她自己在 Terminal 里交互式开 Codex（默认沙箱）再跑：同样 `none`，认出 `agent codex`、`Codex (seatbelt)`；Terminal 在沙箱外两个权限都有，沙箱里都报「没有」，试截报 `rect … does not intersect any displays`（沙箱里看不到显示器） |
| OpenCode、DeepSeek（dsh）、Gemini CLI（`tools.sandbox false`） | 能 | 它们所在的终端 | 同终端 | 没有 | 同终端 | Gemini CLI 0.66.0 在她的 Terminal 里（Mac 2026-11-01，没开 Gemini 自己的沙箱）：`full`，认出 `agent gemini`（`GEMINI_CLI`）和 `Terminal.app`，权限就是 Terminal 的。OpenCode 1.19.5 在她的 Terminal 里（免费模型 opencode/big-pickle 一类，没登录）：`full`，认出 `agent opencode`（`OPENCODE`）和 `Terminal.app`。dsh 0.2.1-rc.5（`openrouter/deepseek/deepseek-v4.1-flash`，她的 OpenRouter key），照 agentd 的方式启动（`agent_providers.Dsh.launch`），从 Claude 桌面 app 里：`full`，认出 `agent dsh`（`DSH_HOME`）和 `claude.app`（权限跟着启动它的 app） |
| agentd（后台常驻 / 构建） | 能 | 启动 `gameanything ui` 的那个 app；不是从终端开的（launchd、开机自启）就是 python 本身 | 要在她登录的桌面里启动（不是服务 / 计划任务） | 用哪个 agent 就是哪个的沙箱（Codex 见上） | 看启动方式 | 未实测 |

### 9. 游戏在后台也继续跑（不用把它放到前面）
- Unity 游戏没有焦点时默认暂停。gameanything 自己的插件在加载时打开 `Application.runInBackground = true`：
  - 胡闹厨房 2 冒烟插件 `worlds/overcooked2/smoke/Plugin.cs`（`Awake`），日志 `[M2W-smoke] loaded (runInBackground True)`；
  - Valheim 冒烟插件 `worlds/valheim/smoke/Plugin.cs`（`Awake`，同一行日志，画面上方黄色横幅）：在这台服务器上对实验室那份游戏的 `Managed/` 编译通过；
  - 城市：天际线冒烟 mod `worlds/cities_skylines/smoke`（`OnEnabled`）、项目 mod 模板 `worlds/cities_skylines/template`（`OnEnabled`），citybuilder 桥本来就有。
  - 这三个在这台服务器上对 Cities 自己的 `Managed/`（Unity 5.6）编译通过；胡闹厨房 2 的插件是对同一个 UnityEngine.dll 加一个 BepInEx 替身编译的（这里没有胡闹厨房 2 的 Managed/）。
- 项目自己的 BepInEx 插件（胡闹厨房 2、Valheim 这类 Unity + BepInEx 游戏）照着加一行：

  ```csharp
  void Awake() { Application.runInBackground = true; /* ... */ }
  ```
- 星露谷：`small_window` 把 `startup_preferences` 里的 `<pauseWhenOutOfFocus>` 临时改成 `false`（只在文件里有这个键时改，**键没在真游戏上验证过**），`close` 改回去。项目 mod 也可以在 SMAPI 的 `GameLaunched` 里写 `Game1.options.pauseWhenOutOfFocus = false;`。
- 我的世界：`options.txt` 的 `pauseOnLostFocus:false`（第 6 节，已经在做）。
- 杀戮尖塔：游戏没有这个设置；libGDX 在后台会降帧，但一般不暂停。没验证过。
- 模拟人生 4：不知道有没有对应设置，gameanything 不改。

### 没在真机上验证过的
- 第 8a 节全部（`native ready` 在 Mac、Windows 上，各个 agent 框架里，特别是 Codex 的沙箱）；Windows 的「测试时允许把游戏切到前面」（`AttachThreadInput` + `SetForegroundWindow` 能不能真的切过去）。
- 第 7–9 节全部：macOS 的 `ioreg`、`CGWindowListCopyWindowInfo` / `CGEventPostToPid` / `screencapture -l`、两个权限检查；Windows 的 `GetLastInputInfo`、`PrintWindow`、`SendInput`；
  游戏在后台收不收这些按键；`runInBackground` 在她的游戏里是不是真的让游戏在后台继续跑。CI 只用假数据测规则（见上面 `test_native_hands.py`）。
- Mac / Windows 上通过 Steam 链接开的游戏，`launch` 能不能在 30 秒内认出它的进程。认不出时，`close` 会在开游戏后 15 分钟内补认。
- Windows 上 `taskkill`（不带 `/F`）能不能让每个游戏正常退出。
- 模拟人生 4 `Options.ini` 的窗口键名；杀戮尖塔 `info.displayconfig` 的行顺序（宽、高、帧率、全屏、窗口化全屏、垂直同步）。
- ScriptEngine 在 Mac 版胡闹厨房 2、Valheim 上的表现；城市：天际线重载 DLL 的表现。
- Fabric 无界面服务器和 GameTest 在她的 Mac 上的表现（`-Dfabric-api.gametest` 要求 Fabric API 带 gametest 模块）。

## How to read CI results

- On GitHub: the **Actions** tab → **ci** → the run. There is one job per system and Python version, for example `windows-latest / py3.12`. A red job
  only fails its own system, because `fail-fast` is off and the other jobs keep running.
- Click the failed step:
  - **Install**: a dependency has no wheel for that system or Python.
  - **Tests**: pytest prints the test name, e.g. `test_crossplatform.py::test_take_home_stardew[unicode]`. The name says which user path broke.
  - **CLI / UI smoke**: the installed `gameanything` command or the server failed. The UI step prints one `ok` / `FAIL` line per URL and the server's own output.
- `-rs` lists skipped tests with the reason, for example the long-path case on a Windows runner without long paths.
- A failure only on the `EncodingWarning` step means some code opens a text file without `encoding="utf-8"`. Add the encoding there.
- To run the same checks locally: `pip install -e . pytest && python -m pytest -q -rs`, then the commands of the two smoke steps in `ci.yml`.

Cost: none on the public repository's standard runners, so Linux, Windows and macOS all run on every push and pull request (while the
repository was private, macOS minutes counted 10x and macOS ran only on pull requests).
