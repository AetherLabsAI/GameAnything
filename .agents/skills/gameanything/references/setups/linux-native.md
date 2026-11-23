# Setting: Linux, native (the user's own game)

GameAnything installs the mod straight into the user's own copy of the game on this Linux computer. Saves are backed up first, only
the loader's mod folder changes, nothing is deleted directly (replaced files go to GameAnything's `.trash`), mods GameAnything did not
install are never touched, and native builds never use Docker.

## Checklist
- `gameanything native doctor --game <game>` finds the game, the mod loader and the build tool (`build ok`).
- Install what doctor says is missing (loader, .NET SDK or JDK) before the first build.
- The game opens only through `gameanything native launch --project "$P"` (her 「现在可以」 on the card first); close only with `gameanything native close --project "$P"`.
- Batch each round: build, `gameanything native check --project "$P" --src <built mod>`, then ONE launch.
- Test in a throwaway local save (Valheim, Terraria: local, not Steam Cloud); never join a server with a test mod.
- A headless server (no display) is not a native setting: use the sandbox.
- `gameanything native ready --project "$P" --if-needed` before the first launch and after an agent / model change: X11 (not Wayland),
  xdotool, ffmpeg or ImageMagick, and a tiny capture probe from the agent's own process (its sandbox included).

## Prerequisites
- The game, installed by Steam (`~/.local/share/Steam/steamapps/common/<Game>`, with its `appmanifest_<id>.acf`) or pinned with the
  game's variable (`GAMEANYTHING_STARDEW_DIR`, ...; `gameanything native doctor` lists them).
- The game's mod loader (doctor prints how to get it): SMAPI, Fabric (+ Fabric API in `mods/`), ModTheSpire + BaseMod, BepInEx 5,
  BepInExPack_Valheim, tModLoader (a free Steam app; Terraria must be owned and installed).
- Stardew Valley content packs (`ContentPackFor: Pathoschild.ContentPatcher`) need Content Patcher in `Mods/` (https://www.nexusmods.com/stardewvalley/mods/1915): `native doctor --game stardew` shows it as `extra  Content Patcher` (a hint: C# mods do not need it), `native check` refuses a pack without it.
- Build tools: the .NET SDK (6 or newer; 8 for Terraria and KSP) for C# mods; a JDK for Java mods (JDK 25 was used for Minecraft 26.x
  and Slay the Spire with `--release 8`); none for Civilization VI (Lua + SQL / XML).

## Settings to change
- The game's window: windowed, not fullscreen (each game's `window.how` in its game.yaml; `native launch` sets the ones it can and puts
  them back at `close`).
- The project's 「什么时候开游戏」 policy (`gameanything project set-launch`): ask (default), a time window, idle, always.

## How to check
- `gameanything native doctor [--game <game>] [--json]`: game folder, loader, mod folder, saves, build tool.
- `gameanything native check --project "$P" --src <built mod>`: references against the game's assemblies / jars without opening the
  game (Minecraft `--server`: a headless server run).
- `gameanything native mods --game <game>`, `gameanything native log --game <game> --grep <marker>`.

## Resources
- The game's own requirements; building needs about 1-2 GB for the SDK / JDK and their caches.
- The game runs on the user's screen: launches are batched (one per round) to disturb them little.

## Games in this setting
<!-- setup-games:begin (gameanything setup tables --write) -->
| Game | Verdict | Verified on this system | Why |
|---|---|---|---|
| Stardew Valley (`stardew`) | available | 2026-10-24 | The sandbox is recommended on Linux; native installs into the user's own game (saves backed up first, only the Mods folder changes) |
| Minecraft (`minecraft`) | available | 2026-10-24 | The sandbox is recommended on Linux; native installs into the user's own game (saves backed up first, only the Mods folder changes) |
| Cities: Skylines (`cities_skylines`) | available | 2026-10-25 | The sandbox is recommended on Linux; native installs into the user's own game (saves backed up first, only the Mods folder changes) |
| Slay the Spire (`slay_the_spire`) | available | 2026-10-24 | The sandbox is recommended on Linux; native installs into the user's own game (saves backed up first, only the Mods folder changes) |
| Overcooked! 2 (`overcooked2`) | available | 2026-10-25 | The sandbox is recommended on Linux; native installs into the user's own game (saves backed up first, only the Mods folder changes) |
| The Sims 4 (`sims4`) | available | not yet verified | The sandbox is recommended on Linux; native installs into the user's own game (saves backed up first, only the Mods folder changes) |
| Valheim (`valheim`) | available | 2026-10-25 | The sandbox is recommended on Linux; native installs into the user's own game (saves backed up first, only the Mods folder changes) |
| Terraria (`terraria`) | available | 2026-10-28 | The sandbox is recommended on Linux; native installs into the user's own game (saves backed up first, only the Mods folder changes) |
| Sid Meier's Civilization VI (`civ6`) | available | 2026-10-28 | The sandbox is recommended on Linux; native installs into the user's own game (saves backed up first, only the Mods folder changes) |
| Kerbal Space Program (`ksp`) | available | 2026-10-25 | The sandbox is recommended on Linux; native installs into the user's own game (saves backed up first, only the Mods folder changes) |
| No Man's Sky (`nms`) | recommended | not yet verified | Not in the sandbox wizard: native mode is the way for this game |
<!-- setup-games:end -->

## Known pitfalls
- Linux `pgrep` matches only the first 15 characters of a process name; GameAnything handles it, keep it in mind when checking by hand.
- Cities: Skylines on Linux does not reload a replaced DLL (tested 2026-10-25): `reload` says to restart. Chinese text in its UI is
  blank on Linux; a CJK font in the user font folder does not help, and a large CJK font can hang the start.
- Civilization VI (Aspyr) uses the home folder from passwd, not `$HOME` / `$XDG_*`; its Linux mod switch is in `ModGroupItems`.
- Slay the Spire's LWJGL 2 window has no `_NET_WM_PID`: `shot` / `drive` find it by its window title.
- Valheim and Terraria make Steam Cloud characters and worlds by default; GameAnything backs up only local saves. Move test saves to
  local first.
- The Sims 4 has no Linux build; it runs only under Proton / Wine. Not yet verified natively on Linux.
- Some games ignore synthetic input (`XSendEvent`): check with `gameanything native shot` and use the mod's own commands instead.

## Tell the user before launching
- Their saves are backed up first and only the Mods folder changes; how to undo it (`native restore`, `native uninstall`).
- The game opens on their screen only after they say 「现在可以」 on the card, and GameAnything closes only a game it opened.
- How many launches this round needs (usually one).
