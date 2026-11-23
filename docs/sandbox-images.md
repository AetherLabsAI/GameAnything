# Sandbox images

GameAnything's recommended way to work on a game is a Docker sandbox on your own computer. The images contain only the runtime: the
mod loader, the build tools, a virtual screen, a viewer in the browser, a recorder and GameAnything itself. **They never contain game
files, accounts, user data or API keys.** You bring the game: either your own game folder, mounted read-only, or a copy downloaded inside
the sandbox with your own store account. Which of these the wizard offers for each game and system is `gameanything/sandbox.py`.

Every game the wizard offers has an image (x86_64 only, see "Platforms"). They are **published as private packages** of
`ghcr.io/aetherlabsai/` (2026-10-29, Wenyi's decision: private until the public-release checklist below is done):

| Game | Image (`ghcr.io/aetherlabsai/...`) | Layers under it | Tool | Status |
|---|---|---|---|---|
| Stardew Valley | `gameanything-lab-stardew` | base, steam, dotnet | `ga-sdv` | pushed; the same recipe tested in a sandbox 2026-10-29; the 20261101a image (bd340f4) carries the Content Patcher 2.9.1 source + .NET SDK 10 (`ga-sdv layer` builds it); the 20261102a image (31120bb) lets `lab sandbox build` install a content pack (#57) |
| Slay the Spire | `gameanything-lab-sts` | base, java (+ Steam in its own layer) | `ga-sts` | pushed; recipe tested 2026-10-29; plain Docker 2026-10-30 |
| Minecraft: Java Edition | `gameanything-lab-minecraft` | base, java | `ga-mc` | pushed; recipe tested 2026-10-29 (needs a GPU) |
| Kerbal Space Program | `gameanything-lab-ksp` | base, steam, dotnet | `ga-ksp` | pushed; recipe tested 2026-10-29 (GPU); plain Docker 2026-10-30 |
| Terraria (tModLoader) | `gameanything-lab-terraria` | base, steam, dotnet | `ga-terraria` | pushed; tested in an image built from main and the 20261030c image on plain Docker 2026-10-30 (fixes sandbox-hiccups.md #24-#25); the 20261030d image (add7bc8) writes /sandbox/saves/config.json so a fresh volume skips tModLoader's first-start screens (#37): re-tested on plain Docker, menu in 25 s with no click |
| Valheim (BepInEx) | `gameanything-lab-valheim` | base, steam, dotnet | `ga-valheim` | pushed; tested in an image built from main on plain Docker 2026-10-30 (GPU); the 20261031a image (656e75a) has the #49 Local-save text |
| Overcooked! 2 (BepInEx) | `gameanything-lab-overcooked2` | base, steam, dotnet | `ga-oc2` | pushed; tested in an image built from main on plain Docker 2026-10-30 (GPU) |
| Cities: Skylines | `gameanything-lab-cities` | base, steam, dotnet | `ga-cities` | pushed; the 20261030b and 20261030c images tested on plain Docker 2026-10-30 (fixes sandbox-hiccups.md #28-#29) |
| Civilization VI | `gameanything-lab-civ6` | base, steam | `ga-civ6` | pushed; the 20261030c image runs as `--user 1004` with no workaround (sandbox-hiccups.md #30-#31); the 20261030d image (add7bc8) sets `ENV SCREEN=1600x900x24` (#36): re-tested on plain Docker, 1024x768 window, full main menu |
| The Sims 4 | `gameanything-lab-sims4` | base, wine | `ga-sims4` + `ga-ea` | pushed; the 20261030b image tested on plain Docker 2026-10-30 (EA App, download, M2WSmoke in the Mods dialog; fixes sandbox-hiccups.md #34); 20261030c too (an expired EA session: #38); the 20261030e image (c61d40f) re-tested: menu + M2WSmoke; the 20261031a image (656e75a): `run` closes a launcher left alone and tries once more (#54) |

"Pushed" means: built by kaniko, pushed, its manifest pulled back and checked (digest, size, x86_64, labels). "Recipe tested" means the
same `install.sh` set up a docker-rt test sandbox from `ubuntu:24.04` and the smoke mod was seen in the game (sections below). Plain
Docker (Ubuntu 22.04 server, 2026-10-29, sandbox-hiccups.md): a locally built Stardew image ran Steam to the sign-in and the download; the then
published steam layer failed Steam's first start (folders missing, fixed in the 2026-10-30 images, not yet re-run there). Windows and
Mac: plan tasks 11-12. The digests are in `gameanything/sandbox.py` `PUBLISHED`.

All fifteen images (the five layers and the ten games) were rebuilt from base again on 2026-10-30 from commit 3b2ecb0 (tags
`:20261030c`, `:3b2ecb0`, `:latest`), to carry the plain-Docker tester's fixes that came after the `:20261030b` images (1406889):
`/etc/passwd` and `/etc/group` mode 666 so `galab.ensure_account` can add the line of a `--user` uid (Civ VI segfaulted without one;
`ga-ea` needs it too), `galab stop` killing the sandbox layer's game processes, the ready markers of `ga-cities`, `SCREEN=1600x900` for
`ga-civ6` (124c14f); Terraria started through `LaunchUtils/ScriptCaller.sh` with `GAMEANYTHING_TERRARIA_USER_DIR=/sandbox/saves`
(df83d2f); `galab` `relaunch_name` / `pids_by_comm` and `ga-sims4` following the `TS4_x64.exe` the EA App starts again, window
`^The Sims`, waiting for the EA sign-in (81666bb). The first build of this round (from 81666bb, never pushed) showed the wine layer's
`/etc/group` back at 664 (rdma-core and winbind add system groups); `ga-readable` now sets both files back to 666 after every `RUN`
(3b2ecb0). The checks before the push are in "How they were built and pushed". Full digests in `sandbox.PUBLISHED` and
`LAYERS_PUBLISHED`. Civ VI and Terraria were then re-published alone from add7bc8 (tags `:20261030d`, `:add7bc8`, `:latest`), on
the same published base / steam / dotnet layers (same digests): Civ VI with `ENV SCREEN=1600x900x24` in its Dockerfile (the base's
`SCREEN=1280x720x24` had won over `ga-civ6`'s default, sandbox-hiccups.md #36), Terraria's `ga-terraria layer` writing
`/sandbox/saves/config.json` (`seed_config`: language and `LastLaunchedTModLoaderVersion`, #37). The Sims 4 was then re-published alone from c31790a (tags `:20261030e`, `:c31790a`, `:latest`) on the same published base / wine layers: `ga-sims4 run` keeps waiting while the EA App shows its sign-in window (`wait_signed_in`, c61d40f) instead of stopping after about 30 s (#38). **Then all fifteen were rebuilt from base again from 41de0a2** (tags `:20261030g`, `:41de0a2`, `:latest`; sandbox-hiccups.md #44-#47): `galab.fit_output` sets Xorg's output mode to the screen (the pointer reaches all of it, #44); base adds Noto Sans CJK (`fonts-noto-cjk`) and Droid Sans Fallback (a plain .ttf) next to WenQuanYi Zen Hei (+86 MB compressed, #45); `rec start` records the game's sound from the `rec` sink's monitor (it recorded the screen only), and `ga-ea` gives the EA App the PulseAudio socket (#47); `ga-valheim` names Steam Cloud saves written since the game started (#46). Valheim and The Sims 4 were then re-published alone from 656e75a (tags `:20261031a`, `:656e75a`, `:latest`) on the same published base / steam / dotnet and base / wine layers (same digests): `ga-valheim`'s help / run / stop text says Valheim 1.0 has no Cloud-save tick (create, then Manage saves > Move to local, and Remove the `_backup_auto` copy, #49); `ga-sims4 run` closes `TS4_Launcher_x64.exe` when it alone is left (no `TS4_x64.exe`: its own activate window), waits 60 s for the EA App's library and tries once more (#54). Stardew Valley was then re-published alone from bd340f4 (tags `:20261101a`, `:bd340f4`, `:latest`) on the same published base / steam / dotnet layers: the image carries the pinned Content Patcher 2.9.1 source, its NuGet packages for an offline build and Ubuntu's .NET SDK 10 (e04f90d), and `ga-sdv layer` builds Content Patcher into the layer's `Mods/` (+271 MB compressed: 1041 -> 1312 MB; about +630 MB unpacked). Stardew Valley was then re-published alone again from 31120bb (tags `:20261102a`, `:31120bb`, `:latest`) on the same published base / steam / dotnet layers: only its bundled GameAnything changed (a539a8a, sandbox-hiccups.md #57: `lab sandbox build` installs a Content Patcher content pack, a folder with `ContentPackFor` in manifest.json and no .cs, by copying it instead of refusing it); same size. Sizes are the compressed download of the whole image; the layers are shared, so a second dotnet game adds only
about 100-140 MB:

| Image | Digest | Compressed size | Built |
|---|---|---|---|
| `gameanything-lab-base` | `sha256:25c47851a445…` | 497 MB | 2026-10-30, 41de0a2 (20261030g) |
| `gameanything-lab-steam` | `sha256:e968d1cbe487…` | 686 MB | 2026-10-30, 41de0a2 (20261030g) |
| `gameanything-lab-dotnet` | `sha256:022104728f87…` | 897 MB | 2026-10-30, 41de0a2 (20261030g) |
| `gameanything-lab-java` | `sha256:88156ab5b1c1…` | 688 MB | 2026-10-30, 41de0a2 (20261030g) |
| `gameanything-lab-wine` | `sha256:d317ee4f6b17…` | 1032 MB | 2026-10-30, 41de0a2 (20261030g) |
| `gameanything-lab-stardew` | `sha256:45bc1cd4cd51…` | 1312 MB | 2026-11-02, 31120bb (20261102a) |
| `gameanything-lab-sts` | `sha256:dc6e25fc7c3f…` | 976 MB | 2026-10-30, 41de0a2 (20261030g) |
| `gameanything-lab-minecraft` | `sha256:c414edbfe61b…` | 790 MB | 2026-10-30, 41de0a2 (20261030g) |
| `gameanything-lab-ksp` | `sha256:dc3e726da95e…` | 999 MB | 2026-10-30, 41de0a2 (20261030g) |
| `gameanything-lab-terraria` | `sha256:4bb09516f61e…` | 999 MB | 2026-10-30, 41de0a2 (20261030g) |
| `gameanything-lab-valheim` | `sha256:b84ae6591c54…` | 1000 MB | 2026-10-31, 656e75a (20261031a) |
| `gameanything-lab-overcooked2` | `sha256:69e0dc1fc214…` | 1000 MB | 2026-10-30, 41de0a2 (20261030g) |
| `gameanything-lab-cities` | `sha256:5dd084ec176d…` | 999 MB | 2026-10-30, 41de0a2 (20261030g) |
| `gameanything-lab-civ6` | `sha256:5cdb7f382640…` | 788 MB | 2026-10-30, 41de0a2 (20261030g) |
| `gameanything-lab-sims4` | `sha256:3031be7b1c03…` | 1133 MB | 2026-10-31, 656e75a (20261031a) |

The images before them (`:20261030b` / `:1406889`, rebuilt from base because the earlier `:20261030` / `:7cee3d6` were built with
umask 077, sandbox-hiccups.md) are superseded: their `/etc/passwd` is 644, so a `--user` uid gets no account line.

### Getting an image

```bash
docker login ghcr.io -u <github user>  # once; the password is a classic PAT with ONLY read:packages (github.com/settings/tokens), typed by you
gameanything lab setup --image stardew  # pulls ghcr.io/aetherlabsai/gameanything-lab-stardew@sha256:... and tags it gameanything-lab-stardew
gameanything lab setup --image stardew --build    # or build it locally: base -> steam -> dotnet -> stardew, for your own uid
```

If the pull fails (not logged in, offline) `lab setup` says so and builds it locally instead (`labdocker.pull_images`). A pulled image is
built for uid 1000; `run_argv` starts it with `--user <your uid>` (see "Your uid" below), so nobody has to rebuild it for their uid.
Images pulled before 2026-10-30 lack Steam's folders (`~/.steam/debian-installation/steamapps`) and stop on Steam's first start with
`ln: failed to create symbolic link '/home/player/.steam/steam': Permission denied`: pull again.

**The viewer is published on 127.0.0.1 only** (`-p 127.0.0.1:6080:6080`, `sandbox.run_argv`). It shows the sandbox's screen, and
during a sign-in the Steam / EA / Microsoft login window: never publish it on all interfaces (a `-p` without `127.0.0.1:`) on a machine with a
public address. On a server, open a tunnel from your own computer and use the viewer there:

```bash
ssh -L 6080:127.0.0.1:6080 <you>@<server>      # then http://localhost:6080/vnc.html on your own computer
```

### Rebuilding the whole chain from the repository

Every layer's Dockerfile is in the repository (`lab/images/base`, `steam`, `dotnet`, `java`, `wine`, and one folder per game; on main
since commit fcd181b). With plain Docker, from the repository root, for your own uid:

```bash
git clone https://github.com/AetherLabsAI/GameAnything && cd GameAnything
gameanything lab setup --image stardew --build          # = the commands below (sandbox.chain_argvs), then the game layer
docker build -f lab/images/base/Dockerfile   --build-arg PLAYER_UID=$(id -u) -t gameanything-lab-base .
docker build -f lab/images/steam/Dockerfile  --build-arg BASE=gameanything-lab-base  -t gameanything-lab-steam .
docker build -f lab/images/dotnet/Dockerfile --build-arg BASE=gameanything-lab-steam -t gameanything-lab-dotnet .
docker build -f lab/images/stardew/Dockerfile --build-arg PLAYER_UID=$(id -u) --build-arg RUNTIME=gameanything-lab-dotnet -t gameanything-lab-stardew .
```

The other chains (the "Layers under it" column above): `java` and `wine` take `--build-arg BASE=gameanything-lab-base`; Civ VI takes
`RUNTIME=gameanything-lab-steam`, Minecraft and Slay the Spire `RUNTIME=gameanything-lab-java`, The Sims 4 `RUNTIME=gameanything-lab-wine`.
A second game of the same chain reuses the layers from Docker's cache. An image built this way records your uid in its label
`org.gameanything.player-uid` and runs without `--user`. To build one game layer on the published layers instead, pass
`--build-arg RUNTIME=<sandbox.LAYERS_PUBLISHED[...]>` (needs `docker login ghcr.io`).

### Layers

One recipe per layer (`lab/images/<layer>/Dockerfile`, the script in `lab/images/common/`), each game's own layer on top
(`lab/images/<game>/`: `Dockerfile`, `install.sh`, the tool). A registry and Docker store a shared layer once, so a second game image
of the same family downloads only its own layers.

| Layer | On | What it adds | Script |
|---|---|---|---|
| base | `ubuntu:24.04@sha256:fe81560990fa...` | the screen (Xvfb, Xorg for a GPU), x11vnc + noVNC, PulseAudio, ffmpeg, Mesa OpenGL + Vulkan, SDL2, OpenAL, fonts, Python 3, the user `player` | `install-system.sh` |
| steam | base | i386 multiarch, Ubuntu's `steam-installer` bootstrap, the 32-bit libraries, D-Bus, openbox, `ga-steam` | `install-steam.sh` |
| dotnet | steam | .NET SDK 8 (Ubuntu's build), ICU, libgdiplus, GTK 3, NSS, udev (Unity / FNA) | `install-dotnet.sh` |
| java | base | OpenJDK 25 | `install-java.sh` |
| wine | base | Wine 11.19 (Kron4ek staging, WoW64), wine-mono 11.3.0, wine-gecko 2.47.4, DXVK 3.1.1, CPython 3.7.17 (built from source) | `install-wine.sh` |
| the game | its runtime layer | GameAnything (venv), the tool, the smoke mod, the pinned mod loader (SMAPI, BepInEx) | `install-gameanything.sh` + `<game>/install.sh` |

Pinned: the Ubuntu image by digest; every apt package by one day of snapshot.ubuntu.com (`APT_SNAPSHOT=20261029T000000Z`, label
`org.gameanything.apt-snapshot`), so the GPL / LGPL source of each package is the Ubuntu source package of that day; every other
download by sha256 (SMAPI 4.5.2, the Content Patcher 2.9.1 source, BepInEx 5.4.23.5, Wine, mono, gecko, DXVK, Python 3.7.17). On a plain `ubuntu:24.04` (a test sandbox)
a game's `install.sh` installs the layers it is missing first (`layers.sh` `ga_need`), so the same script still sets one up by hand.

Never in any layer: game files, the Steam client itself (Steam downloads it into the user's volume on first start), the EA App
(`ga-ea install-app` downloads EA's installer into the user's volume), accounts, login data, tokens, user data.

Every tool except `ga-sdv` is built on `lab/images/common/galab.py` and has the same commands: `doctor`, `layer`, `up`, `run`,
`shot`, `rec start|stop`, `log`, `stop`, `down`. `up` starts Xorg on the NVIDIA GPU when the sandbox has one (`docker run --gpus all
-e NVIDIA_DRIVER_CAPABILITIES=all`), else Xvfb with software OpenGL. The Steam games (Terraria, Valheim, Overcooked! 2, Cities, Civ VI)
call SteamAPI, so their `run` wants the sandbox's Steam client running and logged in (`ga-steam start`; their `doctor` says
`steam_running`). The tools of the six games added on 2026-10-29 (`ga-terraria`, `ga-valheim`, `ga-oc2`, `ga-cities`, `ga-civ6`,
`ga-sims4`) follow the lab tools that ran those games, but have not run inside these images yet.

### Platforms

The images are **linux/amd64 (x86_64) only**. Docker Desktop on an Apple silicon Mac runs them under Rosetta (Settings > General >
"Use Rosetta for x86_64/amd64 emulation"): it works, more slowly; the wizard warns about it. An arm64 build is future work: Ubuntu, .NET 8,
OpenJDK and Mesa exist for arm64, but the games' own Linux builds, Steam and Wine's x86_64 build do not, so an arm64 image would need
box64 / FEX for the game itself.

### How they were built and pushed

**2026-11-02, Stardew Valley only (commit 31120bb = a539a8a's content-pack install + PR #7, tags `:20261102a` / `:31120bb` /
`:latest`).** Same method as 2026-11-01: one anonymous kaniko chain build (no `/etc/docker-image`, "configured: none", tar only), its
two game layers put on the published `dotnet` manifest (first 3 / 5 / 7 layers = the published base / steam / dotnet; the other
fourteen images keep their digests). Checked before the push: every GameAnything file of the game layers equals 31120bb's (now the
whole package, `gameanything/**/*.py`, 144 files, incl. `native/games.py` with `_stage_pack`; `ga-steam` is still the published steam
layer's); `chroot --userspec` as uid 1000 and 1004: `gameanything native build --game stardew --install` of a small content pack (no
.cs, `ContentPackFor` Pathoschild.ContentPatcher) against a fake game folder prints "content pack for Pathoschild.ContentPatcher:
nothing to compile" and installs it into `Mods/` (the `:20261101a` image refuses it: "no .cs"); a539a8a's two unit tests pass against
the image's own copy of the code; Content Patcher source sha256 == pin, NuGet folder and dpkg unchanged (672 packages); 0 problem
entries under the player's folders; no credentials in the new layers. Note: a folder named in Content Patcher's usual style,
`[CP] Name`, is refused by the mod-name rule (`mod 名字不合适`); use a name without brackets. 1311.7 -> 1311.6 MB compressed.
Evidence: `_agent/logs/2026-11-02/images10/`.

**2026-11-01, Stardew Valley only (commit bd340f4 = e04f90d's Content Patcher + a `.dockerignore` fix, tags `:20261101a` /
`:bd340f4` / `:latest`).** One anonymous kaniko chain build (base -> steam -> dotnet -> stardew), same safe method (no
`/etc/docker-image`, "configured: none", tar only); only its two game layers were put on the published `dotnet` manifest read from
the registry (the new manifest's first 3 / 5 / 7 layers are the published base / steam / dotnet; the other fourteen images keep their
digests). The first build, from cce0f80, stopped in `pip install`: `.dockerignore` left out `plugins/dsh-web-search-openai-compatible`,
which setup.py bundles since 9ed8537 (no image could be built from main); bd340f4 lets it in, and a test checks every bundled path.
The steam layer kept is the published one, so its `ga-steam` is 41de0a2's (bd340f4's adds only 3231827's arm64 / FEX path). Checked
before the push: `/opt/gameanything/vendor/ContentPatcher-2.9.1-src.tar.gz` sha256 == the pin in install.sh, `-LICENSE`, the NuGet
folder (ModBuildConfig 4.4.0, Microsoft.NETCore.App.Ref / Microsoft.AspNetCore.App.Ref 6.0.36), the VERSIONS lines (Content Patcher
2.9.1, .NET SDK 10.0.113); `dotnet --list-sdks` as uid 1000 and 1004: 8.0.132 and 10.0.113; `ga-sdv` has `install_cp` / `ensure_cp`
(the `:20261030g` image: 0); dpkg: the nine `*-10.0` packages added, `dotnet-host-8.0` replaced by `dotnet-host-10.0` (it serves
both SDKs); every GameAnything file of the game layers equals bd340f4's; 0 problem entries under the player's folders;
`/etc/passwd`, `/etc/group` 0666; `chroot --userspec` as uid 1000 and 1004 (imports, `gameanything --help`, `ga-sdv --help` /
`doctor` (`content_patcher_vendor` 2.9.1), `ga-steam status`, `ensure_account` -> `player1004`). An offline `dotnet restore` of the
Content Patcher project with only the image's NuGet folder (empty package cache, proxies to a dead port) restored with SDK
10.0.113 as uid 1000 (in a separate never-pushed kaniko build: a chroot here has no `/proc` for the .NET runtime). Building
Content Patcher needs the game's DLLs: done by `ga-sdv layer` (shown in a sandbox against the real game by e04f90d), to be
re-tested on plain Docker. Evidence: `_agent/logs/2026-11-01/images9/`.

**2026-10-31, Valheim and The Sims 4 only (commit 656e75a, tags `:20261031a` / `:656e75a` / `:latest`).** Two anonymous kaniko
chain builds (base -> steam -> dotnet -> valheim, base -> wine -> sims4) with the same safe method (no `/etc/docker-image`,
"configured: none", tar only); only each chain's own two game layers were put on the published `dotnet` / `wine` manifests read
from the registry, so base, steam, dotnet, java, wine and the other eight game images keep their digests (checked: the new
manifests' first 3 / 5 / 7 layers are the published base / steam / dotnet and base / wine). Checked before the push:
`/usr/local/bin/ga-valheim` has the #49 text (`_backup_auto` count 2; the `:20261030g` image, as the control: 0; "Move to local"
was there twice already, now 3); `/usr/local/bin/ga-sims4` has `only_launcher_left`, `close_launcher`, `library_wait` (the
`:20261030g` image: 0) and still `wait_signed_in`; every GameAnything file (galab.py, the `ga-*` tools, the venv's
`gameanything/*.py`) equals 656e75a's; 0 problem entries under the player's folders; `/etc/passwd`, `/etc/group` 0666; unpacked and
run with `chroot --userspec` as uid 1000 and 1004 (imports, tools, `doctor`, `ga-steam status` / `ga-ea --help`, `ensure_account`
-> `player1004`), plus the new code paths with stubs: `ga-valheim doctor` names a fake Cloud world and not a local one, and nothing
after the remote file is gone; `ga-sims4 run` with only the launcher left closes it (SIGTERM) and runs a second time, and keeps a
plain exit when no launcher is left. Evidence: `_agent/logs/2026-10-31/images8/`.

**2026-10-30, fourth rebuild from base (all fifteen, commit 41de0a2, tags `:20261030g` / `:41de0a2` / `:latest`).** The same
method as the third rebuild: ten anonymous kaniko chain builds from `ubuntu:24.04@sha256:...` (no `/etc/docker-image`, "configured:
none", tar only), assembled on this host (base / steam / dotnet from the Stardew chain, java from Minecraft's, wine from The Sims 4's;
the other chains' lower layers differ only in machine-id, layer markers, caches), pushed with `push.py`. Checked before the push:
0 problem entries under the player's folders and `/etc/passwd`, `/etc/group` 0666 in all fifteen; in the ten game images
`galab.py` has `fit_output` (count 2), `rec_argv` and the anonymous PulseAudio socket, and every GameAnything file (galab.py, the
`ga-*` tools, the venv's `gameanything/*.py`) equals the commit's; unpacked and run with `chroot --userspec` as uid 1000 and 1004
(imports, tools, `ga-steam status` / `ga-ea --help`, `ensure_account` -> `player1004`); `fc-list :lang=zh` lists Noto Sans CJK SC and
Droid Sans Fallback and `fc-match sans-serif:lang=zh-cn` is Noto Sans CJK SC; galab's PulseAudio + a 440 Hz tone played into `rec` (as a
game, and as the EA App's child with its own XDG_RUNTIME_DIR) recorded by `rec_argv` from another HOME: an audio track at -21 dB. The
published 3b2ecb0 Stardew image as the control: no `fit_output`, only WenQuanYi, a recording without an audio stream. A first build of
this round from 13de994 (only `fit_output`) was pushed as `:20261030f` / `:13de994` but never put in `PUBLISHED` (superseded the same
hour). Evidence: `_agent/logs/2026-10-30/images7/`.

**2026-10-30, The Sims 4 only (commit c31790a, tags `:20261030e` / `:c31790a` / `:latest`).** One anonymous kaniko chain build
(base -> wine -> sims4) with the same safe method; only its two game layers were put on the published `wine` manifest read from the
registry, so base and wine keep their digests (checked: the new manifest's first 3 / 5 layers are the published base / wine).
Checked before the push: `/usr/local/bin/ga-sims4` contains `wait_signed_in` (count 2; the `:20261030c` image, as the control: 0);
0 problem entries under the player's folders; `/etc/passwd`, `/etc/group` 0666; `chroot --userspec` as uid 1000 and 1004 (`player`,
`player1004`). Evidence: `_agent/logs/2026-10-30/images6/`.

**2026-10-30, Civ VI and Terraria only (commit add7bc8, tags `:20261030d` / `:add7bc8` / `:latest`).** Two anonymous kaniko
chain builds (base -> steam -> civ6, base -> steam -> dotnet -> terraria) with the same safe method; only each chain's own game
layers were taken and put on the published `steam` / `dotnet` manifests read from the registry, so base, steam and dotnet keep
their digests (checked: the new manifests' lower layers equal the published ones; the rebuilt lower layers differ from them only in
logs, caches, machine-id and the layer markers). Checked before the push: (a) 0 problem entries under the player's folders; (b)
`/etc/passwd`, `/etc/group` 0666; (c) `chroot --userspec` as uid 1000 and 1004 as below (`player`, `player1004`); (d) the
effective config Env of the Civ VI image has `SCREEN=1600x900x24` (the `:20261030c` image, as the control: `1280x720x24`), and
`/usr/local/bin/ga-terraria` contains `seed_config` (the `:20261030c` one does not). Evidence: `_agent/logs/2026-10-30/images5/`.

**2026-10-30, third rebuild (the other thirteen current images, commit 3b2ecb0, tags `:20261030c` / `:3b2ecb0` / `:latest`).** The same method
as the second rebuild (ten anonymous kaniko chain builds from the public `ubuntu:24.04@sha256:...`, no `/etc/docker-image`, tar only;
the layers cut from the Stardew / Minecraft / Sims 4 chains; pushed from the maintainer's machine). Checked before the push, from the
layer tars and without `docker run`: (a) 0 entries under the player's folders that another uid cannot use, all 15 images; (b)
`/etc/passwd` and `/etc/group` mode 0666 in all 15 (the first build of this round, from 81666bb, had the wine layer's `/etc/group`
at 664 and was not pushed); (c) each game image unpacked and run with `chroot --userspec` as uid 1000 and 1004: the imports,
`gameanything --help`, the game's tool, `ga-steam status` / `ga-ea --help`, `ls /game /saves`, `ls -l /etc/passwd` = `-rw-rw-rw-`,
and `galab.ensure_account()` giving uid and gid 1004 their `player1004` lines (the `:20261030b` Civ VI image as the negative
control: 644, no `ensure_account`); (d) the tester's fixes in the files (`ensure_account`, `relaunch_name`, `pids_by_comm`,
`ScriptCaller`, `GAMEANYTHING_TERRARIA_USER_DIR` in the Terraria image's Env, `1600x900`, the Cities ready markers). Evidence:
`_agent/logs/2026-10-30/images4/` (maintainer's server).

**2026-10-30, second rebuild (superseded, commit 1406889, tags `:20261030b` / `:1406889`).** The same safe method
as the first 2026-10-30 rebuild below, now for the whole chain from base: ten anonymous kaniko builds (one per game, each the whole
chain base -> ... -> game as one multi-stage build from the public `ubuntu:24.04@sha256:...`, tar only, no registry credential, no
`/etc/docker-image`); on the maintainer's machine `base`, `steam`, `dotnet` were cut from the Stardew chain, `java` from the
Minecraft chain, `wine` from The Sims 4 chain, and each game image is its chain's own game layer on those (the lower part of every
other chain was compared file by file with the pushed layers: only logs, caches, machine-id, the layer markers' timestamps and Java's
cacerts keystore differ). Before the push every image's effective file modes were read from its layers (whiteouts honoured) and each
game image was unpacked and checked as uid 1000 and 1004 with `chroot --userspec` (watchdog and galab import, `gameanything --help`,
the game's tool, `ga-steam status`, `ls /game /saves`; the image before it fails all of these). Evidence:
`_agent/logs/2026-10-30/images3/` (maintainer's server).

**Why the first 2026-10-30 images were unreadable (umask 077).** docker-rt's kaniko worker script sets `umask 077` before it starts `/kaniko/executor`, to keep the registry
`config.json` it may write private; kaniko and every `RUN` inherit it, and kaniko itself makes the folders of a `COPY` with it (the
staging folders `/tmp/ga-layer` and `/opt/gameanything/src` came out 0700 again in the 1406889 builds: they are removed in the same
`RUN`). The first images of 2026-10-29 had the same problem in `base`; the 7cee3d6 rebuild kept that base. The Dockerfiles do not
depend on the builder's umask any more: every `RUN` starts with `umask 022` and ends with `lab/images/common/ga-readable` (adds
`go+rX` only where it is missing, under the player's folders; `GA_READABLE_PRIVATE` for a path meant to stay private, none today),
every install script sets `umask 022` itself, and every `COPY` lands in a staging folder that its `RUN` removes (or would need
`--chmod`). `tests/test_sandbox_images.py` checks all of that in every Dockerfile. A local build from a checkout made with umask 077
is fixed by the same step (cp keeps the sources' 0600).

**2026-10-30, first rebuild (superseded: built with umask 077).** No registry credential was in any build. On the maintainer's server
`docker build` is kaniko in a short-lived build pod (docker-rt); these builds ran with no credential at all, so they could only pull
public images: each one built a whole chain as one multi-stage build from the public `ubuntu:24.04@sha256:...` (the layer Dockerfiles
as stages, unchanged) and wrote the image to a tar file only. On the maintainer's own machine a small script then put each image
together from the tars and pushed it: the layers under the rebuilt one stay the published ones, the rebuilt layers come from the
tars, and the image's config is the built one with the lower layers' diff_ids. Rebuilt then: `steam`, `dotnet` and the images with
the Steam layer (tags `:20261030`, `:7cee3d6`). Evidence: `_agent/logs/2026-10-29/images2/` (maintainer's server).

**2026-10-29 (the first images).** kaniko pushed each image itself to the private package, and pulled the private layer images under it
with the same credential. In order: base, steam / java / wine, dotnet, then the games. Each game image is `FROM` its runtime layer by
digest (`--build-arg RUNTIME=...@sha256:...`).

Elsewhere, with plain Docker: `docker build` each layer in order (`sandbox.chain_argvs`, "Rebuilding the whole chain" above),
`docker tag` and `docker push`.

### Your uid (PLAYER_UID): passed for you

Some save files are private to their owner (a Minecraft world's `level.dat` is mode 0600), and the game in the sandbox runs as the user
`player`. So the game must run with your uid. You never pass it by hand. Two ways, both tested (`tests/test_sandbox.py`):

| Your image | How it runs (`sandbox.run_argv`, `run_user_args`, `steam_home`) | HOME (and the Steam volumes) |
|---|---|---|
| **pulled** (published, label `org.gameanything.player-uid=1000`) and your uid is not 1000 | `--user <uid>:<gid> -e HOME=/sandbox/home` (the default: no rebuild) | `/sandbox/home`: `-v ga-steam-home:/sandbox/home -v ga-steam-games:/sandbox/home/.steam/debian-installation/steamapps` |
| pulled, and your uid is 1000; or Windows without WSL; or root | nothing extra | `/home/player`: `-v ga-steam-home:/home/player -v ga-steam-games:/home/player/.steam/debian-installation/steamapps` |
| **rebuilt** for your uid (`gameanything lab setup --image <game> --build`, `--build-arg PLAYER_UID=$(id -u)`) | nothing extra: `player` has your uid | `/home/player` (as above) |

`/sandbox`, `/sandbox/home` and (since 2026-10-30) `/sandbox/home/.steam/debian-installation/steamapps` are mode 1777 in the image, and
`/home/player/.steam/debian-installation/steamapps` belongs to `player`, so a new volume mounted there is writable either way. Rebuild
only if you want `/home/player` with your own uid (for example to keep an existing `ga-steam-home` volume made for it); a Steam home
volume made for one of the two homes is not moved to the other. `doctor` still warns when the mounted folders belong to a uid other than
the game's.

| Where Docker runs | What is passed | Why |
|---|---|---|
| Linux, Docker Engine | your uid (`id -u`) | bind mounts keep the real owner and mode |
| Windows, WSL 2 (GameAnything run inside the WSL distro) | your WSL uid | files in the distro keep their Linux owner, same as Linux |
| Windows, Docker Desktop, GameAnything run from Windows itself | nothing: the image keeps uid 1000 | Windows has no uid; drives shared into Docker Desktop's VM (`C:\...`) appear as owned by root with mode 0777, readable by every uid |
| Mac, Docker Desktop | your Mac uid (501 ...) | the VM's file sharing makes your files readable to the container either way; passing the uid keeps the rule the same |
| as root | nothing | root reads every file; the image keeps its own `player` |

The gamebench lab images that `gameanything lab setup` pulls (`--stardew`, `--minecraft`) already run as the caller's uid (gamebench
`hosting/lab/seat.py` starts every seat with `--user`).

### Mac: games that need a GPU

Docker Desktop on a Mac runs the sandbox in a Linux VM without a GPU. Minecraft 26.x does not start at all on software OpenGL (seen in the
test below), and the 3D games are very slow. So on a Mac the wizard (`sandbox.sources`) puts **native mode first, recommended**, for every
game whose game.yaml `sandbox: gpu:` is `required` (Minecraft) or `recommended` (the default of a `three_d: true` game: KSP, Valheim,
Cities: Skylines, Civilization VI, Overcooked! 2, The Sims 4). The sandbox options stay selectable, not recommended, and their text says
why. 2D games (Stardew Valley, Terraria, Slay the Spire) keep the sandbox as the recommended way on a Mac.

## Stardew Valley

```bash
gameanything lab setup --image stardew       # = docker build -f lab/images/stardew/Dockerfile --build-arg PLAYER_UID=<your uid> -t gameanything-lab-stardew .
docker run -d --name ga-stardew -p 127.0.0.1:6080:6080 \
  -v "$HOME/.local/share/Steam/steamapps/common/Stardew Valley":/game:ro \
  -v "$HOME/.config/StardewValley":/saves:ro \
  -v ga-stardew:/sandbox gameanything-lab-stardew
docker exec ga-stardew ga-sdv layer          # the sandbox's own copy of the game + the pinned SMAPI; your folder is not touched
docker exec ga-stardew gameanything native build --game stardew --install /opt/gameanything/smoke/M2WSmoke
docker exec ga-stardew ga-sdv run            # then open http://localhost:6080/vnc.html
docker exec ga-stardew ga-sdv shot /sandbox/shots/now.png
docker exec ga-stardew ga-sdv rec start      # ... ga-sdv rec stop: /sandbox/rec/*.mkv (MJPEG), encode the final video outside
docker exec ga-stardew ga-sdv down
```

How the user's folder stays unchanged:

- `/game` and `/saves` are mounted read-only (`:ro`); the sandbox cannot write to them.
- `ga-sdv layer` builds `/sandbox/game` on the writable volume. It copies the small files (about 230 entries, 150 MB, about 20 s) and
  links `Content/` (537 MB) to the read-only mount. It leaves out the user's own SMAPI, mods and backups, installs the image's pinned
  SMAPI 4.5.2 with the official installer, and starts with a fresh `Mods/` that holds Content Patcher 2.9.1, built offline from the
  image's pinned source against this layer (~15 s; log `/sandbox/logs/content-patcher-build.log`; a failed build is reported and the
  layer still works for SMAPI C# mods). Run on a layer made before, `ga-sdv layer` only adds Content Patcher when that version is missing.
- Saves are copied to `/sandbox/saves`, and the game's `~/.config/StardewValley` points there.
- An overlay filesystem would avoid the copy, but it needs privileges that Docker Desktop and many hosts do not give. The copy works everywhere.

Only the Linux build of the game runs in the sandbox. `ga-sdv doctor` says which build is mounted. Windows and Mac users download the Linux
build inside the sandbox with Steam: see "Steam inside the sandbox" below.

### Test on 2026-10-29 (maintainer's server, docker-rt)

The docker-rt cluster cannot pull private ghcr packages. So the run used the official `ubuntu:24.04` image with this repository mounted,
and `install.sh` ran as root. `install.sh` is the same script the Dockerfile runs, so the result has the same files as the image.
The image itself was built with kaniko, and the result is `ghcr.io/aetherlabsai/m2w-lab-dotnet:ga-stardew-usersandbox-20261029`, which is
private.

1. The sdlab's Stardew folder (826 MB, 4248 entries) was mounted read-only at `/game`, and its saves at `/saves`. Writing to either failed
   with "Read-only file system".
2. `ga-sdv layer` took 18.7 s and installed SMAPI 4.5.2.
3. `gameanything native build --install` built the M2WSmoke smoke mod.
4. `ga-sdv run` started the game, and SMAPI loaded 3 mods, among them M2WSmoke ("[M2W-smoke] loaded").
5. A save was loaded, and the screenshot shows the mod's HUD message "[M2W-smoke] hello from GameAnything".
6. A 55 s recording was made and encoded to H.264 on the host. Then the game was stopped and the sandbox deleted.
7. The sha256 of every file and the type, mode, size and mtime of every entry were recorded before and after, for the game folder and the saves folder. Both were identical.

Still to do: run the published image on a real Linux machine with Docker Engine, on Windows with WSL2 and Docker Desktop, and on a Mac
with Docker Desktop (Apple silicon emulates x86 images).

## Kerbal Space Program

```bash
gameanything lab setup --image ksp           # builds gameanything-lab-ksp for your uid
docker run -d --name ga-ksp -p 127.0.0.1:6080:6080 --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all \
  -v "$HOME/.local/share/Steam/steamapps/common/Kerbal Space Program":/game:ro -v ga-ksp:/sandbox gameanything-lab-ksp
docker exec ga-ksp ga-ksp layer
docker exec ga-ksp gameanything native build --game ksp --install /opt/gameanything/smoke/M2WSmoke
docker exec ga-ksp ga-ksp run                # to the main menu
```

KSP keeps saves and `settings.cfg` in the game folder, so one read-only mount covers everything. `ga-ksp layer` links `KSP_Data/`
(3.5 GB) and the player libraries into `/game`, and copies `GameData/Squad*` (1.1 GB, about a minute): KSP opens its part files
read-write, and links into a read-only folder stop the loading screen. The user's own mods in `GameData/` are left out; `saves/` and
`settings.cfg` are copied, and the copy is set to windowed 1280x720 without pop-ups.

### Test on 2026-10-29 (docker-rt, ubuntu:24.04 + `install.sh`, 4 CPU, 8 GB, one L40S)

1. The lab's KSP 1.12.5 Linux folder (4.7 GB, 3875 entries) was mounted read-only at `/game`; writing to it failed.
2. `ga-ksp layer`: 62 s. `gameanything native build --install` built M2WSmoke into `GameData/M2WSmoke/Plugins/`.
3. `ga-ksp up` started Xorg on the GPU (`Renderer: NVIDIA L40S`). `ga-ksp run` reached the main menu in 39 s. The log shows
   `[M2W-smoke] loaded` and `main menu message shown`, and the screenshot shows the plugin's line "M2W smoke: plugin loaded".
4. A 43 s clip (main menu, then Start Game) was encoded on the host. The game was stopped and the sandbox deleted.
5. The sha256 of every file and the type, mode, size and mtime of every entry were identical before and after.

## Minecraft: Java Edition

```bash
gameanything lab setup --image minecraft     # builds gameanything-lab-minecraft for your uid
docker run -d --name ga-mc -p 127.0.0.1:6080:6080 --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all \
  -v "$HOME/.minecraft":/game:ro -v ga-mc:/sandbox gameanything-lab-minecraft
docker exec ga-mc ga-mc layer
docker exec ga-mc gameanything native build --game minecraft --install /opt/gameanything/smoke/M2WSmoke
docker exec ga-mc ga-mc run --world "<a world>"   # straight into that world (quick play)
```

- `/game` is the user's `.minecraft`: `versions/` with a Fabric profile, `libraries/`, `assets/`, and the launcher's Java `runtime/`.
  Launchers that keep worlds apart (Prism, MultiMC, portablemc `--work-dir`) mount that game folder at `/saves` as well.
- `ga-mc layer` links `versions/`, `libraries/`, the asset objects and the runtime, and copies `saves/`, `config/`, `options.txt` and
  `resourcepacks/`. `mods/` starts fresh with only the user's Fabric API jar. Launcher accounts and tokens are never copied.
- A Windows or Mac `.minecraft` has only its own system's native jars. `ga-mc layer` then downloads the Linux ones once, from the
  public URLs in the version file, with no login, and checks their sha1. The image's OpenJDK 25 runs the game when the launcher's own
  Java is not a Linux one.
- `ga-mc run` starts the profile **offline**: a local player name, single-player only, no account in the sandbox. This is the product
  behaviour (decided 2026-10-29): developing and testing mods needs **no Microsoft login**. The game files come from the user's own
  launcher. The wizard's "Microsoft account" option only downloads those files once, for a user who has none on their computer yet; it is
  not needed for playing.
- Minecraft 26.x needs a GPU (step 2 of the test below). On a Mac, where Docker Desktop has none, the wizard recommends native mode.
- `gameanything native build --game minecraft` compiles with `javac` against the profile's own jars, with no Gradle and no network.
  Minecraft 26.x ships unobfuscated, so no remapping is needed. Fabric API's inner jars are unpacked for the compiler. Older,
  obfuscated versions still need the Fabric example mod's Gradle setup.

### Test on 2026-10-29 (docker-rt, ubuntu:24.04 + `install.sh`, 4 CPU, 8 GB)

1. The lab's `.minecraft` stand-in was mounted read-only: `minecraft/main` (versions, libraries, assets, Java runtime; 739 MB, 5831 entries)
   at `/game`, and the instance `instances/rt` (a world, Fabric API, the lab's bridge mod) at `/saves`. Writing to either failed.
2. First try without a GPU (Xvfb, Mesa llvmpipe, OpenGL 4.5): Minecraft 26.3 stops with "Couldn't find matching GLX visual", and its
   Vulkan fallback fails as well. **Minecraft 26.x needs a GPU in the sandbox.** The test was rerun with one L40S.
3. The world's `level.dat` is mode 0600 and owned by uid 1006, so the sandbox user had to be uid 1006 (`PLAYER_UID`; since then
   `gameanything lab setup --image` passes it automatically).
4. `ga-mc layer` took 0.8 s; the lab's bridge mod was left out. `native build --install` compiled M2WSmoke against 119 jars.
5. `ga-mc run --world ...` started Fabric 0.19.5 on Minecraft 26.3 from the mounted Java runtime, and the log listed 50 mods, among them
   m2wsmoke. The log has `[M2W-smoke] loaded`, the player joined the world, and the chat shows "[M2W-smoke] hello from GameAnything"
   in the screenshot.
6. A 61 s clip was encoded on the host. The game was stopped and the sandbox deleted. Both folders were identical before and after,
   by every sha256 and every entry's metadata.

### No .minecraft yet: download with a Microsoft account

```bash
docker exec ga-mc ga-mc account login     # shows a code: open https://www.microsoft.com/link on your phone, type it, sign in there
docker exec ga-mc ga-mc download          # 26.3 + Fabric 0.19.5 + Fabric API 0.162.0 into /sandbox/minecraft, every hash checked
docker run ... -e GA_GAME=/sandbox/minecraft ...   # (or GA_GAME in the exec) ga-mc layer / run use the downloaded copy as /game
```

- The sign-in is Microsoft's **device-code flow** with the Minecraft launcher's public client id (`00000000402b5328`), the same chain as
  the official launcher: Xbox Live, XSTS, Minecraft services, then the account's entitlements. The user types the code and their password
  on Microsoft's own page on their own device; nothing is typed into the sandbox (`gameanything/native/msauth.py`).
- The account only proves that the user owns Minecraft: Java Edition. `ga-mc download` refuses without it. The files come from the
  official public sources (Mojang's piston-meta and resources servers, Mojang's Java runtime, meta.fabricmc.net and its maven, Modrinth
  for Fabric API), and every file is checked against its official sha1 (sha512 for Fabric API). Fabric's loader and intermediary have
  no hash in the profile, so their maven `.sha1` is used (`gameanything/native/mcdownload.py`).
- Kept in the volume, mode 0600: the Microsoft refresh token (`/sandbox/account/microsoft.json`) and the ownership result without any
  token. No game token is kept; play is offline. `ga-mc account status [--recheck]` never prints a token; `ga-mc account logout`
  deletes them. A refresh token unused for about 90 days expires; then the user signs in with a new code.
- portablemc (which the lab uses for its own files) is not used here: its Microsoft login is the authorization-code flow, which needs a
  browser inside the sandbox.

### Test on 2026-10-29 (Microsoft download; in the Minecraft lab `mclab-hlm-m1`, L40S, under a lease)

No new sandbox was allowed, so the test ran in a separate folder of the existing lab, with `ga-mc` from this repository and the folder
as `/sandbox`. The lab's own Minecraft files were not used.

1. `ga-mc account login` showed a code; the maintainer signed in on her own device within a minute. Entitlements: `game_minecraft`,
   `product_minecraft`, and a Java profile.
2. `ga-mc download`: 702 MB, 5372 files (client, 66 libraries, 5147 assets, the 147-file Java 25 runtime, 7 Fabric libraries, Fabric API).
   The assets took 101 s on the lab's network disk.
3. With `GA_GAME` on the download: `ga-mc layer`, `native build --install M2WSmoke`, `ga-mc run`. A fresh download has no world, and
   quick play into a missing world fails ("Could not find a world"), so the first world was made with two clicks (Create New World).
   Offline player `Player`, 50 mods with m2wsmoke, and the chat line "[M2W-smoke] hello from GameAnything". A 40 s clip was encoded on the host.
4. Reuse: with everything outside the volume removed, `ga-mc account status --recheck` checked ownership again from the saved refresh
   token with no sign-in, `ga-mc download` fetched 0 of 5372 files, and `ga-mc run --world "New World"` was in the world in 21 s
   with the mod loaded.

## Slay the Spire

```bash
gameanything lab setup --image slay_the_spire   # builds gameanything-lab-sts for your uid
S="$HOME/.local/share/Steam/steamapps"
docker run -d --name ga-sts -p 127.0.0.1:6080:6080 -v "$S/common/SlayTheSpire":/game:ro -v "$S/workshop/content/646570":/workshop:ro \
  -v ga-sts:/sandbox gameanything-lab-sts
docker exec ga-sts ga-sts layer
docker exec ga-sts gameanything native build --game slay_the_spire --install /opt/gameanything/smoke/M2WSmoke
docker exec ga-sts ga-sts run
```

The game keeps `saves/`, `preferences/` (unlocks) and `runs/` in its own folder. `ga-sts layer` links `desktop-1.0.jar` and `jre/`, and
copies the rest. It takes ModTheSpire and BaseMod (and StSLib) from the game folder or the Workshop mount; the image does not carry them.
`mods/` starts with only those, and the user's other mods are left out. The game runs on its own Java 8; the image's OpenJDK 21 only
compiles mods (`javac --release 8`). It is a 2D game and needs no GPU.

### Test on 2026-10-29 (docker-rt, ubuntu:24.04 + `install.sh`, 2 CPU, 4 GB, no GPU)

1. The lab's Slay the Spire folder (599 MB, 805 entries, with ModTheSpire, BaseMod, saves and unlocks) was mounted read-only at `/game`.
   Writing to it, to `saves/` or to `preferences/` failed. Its files belong to uid 1006, so `PLAYER_UID=1006`.
2. `ga-sts layer` took 8.6 s, and the lab's other five mods were left out. `native build --install` built M2WSmoke. The smoke mod now also
   draws one line on every screen, so a screenshot proves it is loaded.
3. `ga-sts run` reached the main menu in 25 s on Xvfb, with BaseMod 5.56 and m2wsmoke loaded under ModTheSpire 3.30.3. The log has
   `[M2W-smoke] loaded`, and the screenshot shows "[M2W-smoke] hello from GameAnything" and "ModTheSpire 3.30.3 - 2 mods".
4. A 39 s clip (the main menu, then the Mods list) was encoded on the host. The game was stopped and the sandbox deleted. The folder was
   identical before and after, by every sha256 and every entry's metadata.

Still to do for all four images: run the published images with a real Docker Engine on Linux, with Docker Desktop on Windows (WSL2), and on a Mac.

## Steam inside the sandbox (download the Linux build with your own account)

For Windows and Mac users, whose installed game is not the Linux build, and for anyone who prefers it. Every image of a game that can
come from Steam has the Steam layer (since 2026-10-29; before, it was the optional `--steam` / `STEAM=1` build); the user logs in in
the sandbox's viewer, and Steam downloads the Linux build into the user's volume.

Once per host with AppArmor (Ubuntu, Debian), load the profile `gameanything-steam`. Both files define the same profile; load the one
for your AppArmor version (`sandbox.apparmor_profile_file()` / `apparmor_load_commands()` pick it: `/etc/apparmor.d/abi/4.0` exists = 4):

| Host | File (`lab/images/common/security/`) | Why |
|---|---|---|
| Ubuntu 24.04 and later (AppArmor 4) | `gameanything-steam.apparmor` | has the `userns` rule (24.04 restricts unprivileged user namespaces) |
| Ubuntu 22.04 (AppArmor 3), Debian 12 | `gameanything-steam-u2204.apparmor` | AppArmor 3 has no `abi/4.0` and no `userns` rule (the 24.04 file fails with "Could not open 'abi/4.0'"); 22.04 does not restrict user namespaces. Tested 2026-10-29 on Ubuntu 22.04.5 |
| Docker Desktop (Windows, Mac), Fedora / RHEL (SELinux) | none: leave `--security-opt apparmor=...` out | no AppArmor (`steam_run_args(apparmor="auto")` leaves it out) |

```bash
F=lab/images/common/security/gameanything-steam.apparmor; [ -e /etc/apparmor.d/abi/4.0 ] || F=lab/images/common/security/gameanything-steam-u2204.apparmor
sudo install -m 644 "$F" /etc/apparmor.d/gameanything-steam && sudo apparmor_parser -r -W /etc/apparmor.d/gameanything-steam
```

Then (an image built for your uid, or your uid is 1000):

```bash
gameanything lab setup --image stardew              # every Steam game's image has the Steam layer
docker volume create ga-steam-home; docker volume create ga-steam-games
docker run -d --name ga-stardew-steam -p 127.0.0.1:6080:6080 --shm-size 1g \
  --security-opt seccomp=lab/images/common/security/seccomp-steam.json \
  --security-opt apparmor=gameanything-steam \
  -v ga-steam-home:/home/player -v ga-steam-games:/home/player/.steam/debian-installation/steamapps \
  -v ga-stardew:/sandbox gameanything-lab-stardew
docker exec ga-stardew-steam ga-sdv up && docker exec ga-stardew-steam ga-steam start     # then log in at http://localhost:6080/vnc.html
docker exec ga-stardew-steam ga-steam wait --timeout 2400
docker exec ga-stardew-steam ga-steam install 413150 && docker exec ga-stardew-steam ga-steam app 413150
docker exec -e GA_GAME="/home/player/.steam/debian-installation/steamapps/common/Stardew Valley" ga-stardew-steam ga-sdv layer
```

A pulled image (uid 1000) on a host user with another uid: the same, plus `--user $(id -u):$(id -g) -e HOME=/sandbox/home`, and the two
Steam volumes at `/sandbox/home` and `/sandbox/home/.steam/debian-installation/steamapps` (`GA_GAME` under `/sandbox/home/...` too):

```bash
docker run -d --name ga-stardew-steam -p 127.0.0.1:6080:6080 --shm-size 1g --user $(id -u):$(id -g) -e HOME=/sandbox/home \
  --security-opt seccomp=lab/images/common/security/seccomp-steam.json --security-opt apparmor=gameanything-steam \
  -v ga-steam-home:/sandbox/home -v ga-steam-games:/sandbox/home/.steam/debian-installation/steamapps \
  -v ga-stardew:/sandbox gameanything-lab-stardew
```

On a server, add a memory limit on a shared machine (`--memory 16g`) and reach the viewer through `ssh -L 6080:127.0.0.1:6080 <server>`.
`sandbox.steam_run_args(home_volume, games_volume, image_uid=..., uid=...)` gives these arguments (home and AppArmor chosen for the host).

- `lab/images/common/install-steam.sh` adds i386 multiarch, Ubuntu's `steam-installer` (the bootstrap only: Steam downloads the client
  itself into the user's home on first start), the 32-bit libraries, D-Bus, openbox and `ga-steam` (the shared layer "steam").
  It also makes `~/.steam/debian-installation/steamapps` (owned by `player`) and the same folders under `/sandbox/home` (mode 1777): the
  steamapps volume mounts inside the home volume, and without them Docker created them as root and Steam's first start stopped
  (`ln: failed to create symbolic link '/home/player/.steam/steam': Permission denied`, plain Docker on Ubuntu 22.04, 2026-10-29).
- **Persistent:** the Steam home (`/home/player`: the client, `~/.steam/registry.vdf`, `config/loginusers.vdf`, `config/config.vdf`) and
  the library (`steamapps/`) are volumes. A new sandbox with the same volumes starts logged in and has the games already.
- **The user types the password and approves Steam Guard on the phone themselves.** No tool reads, logs or stores it. Tick "Remember me".
- **What Steam needs from Docker** (no capability, no `--privileged`): the client checks with bubblewrap that it can create a user AND a
  mount namespace and `pivot_root`. Docker's default seccomp blocks `unshare`, `mount` and `pivot_root`; `seccomp-steam.json` is Docker's
  default plus exactly those (and `setns`, `clone`, `clone3`, `umount2`). On a host with AppArmor (Ubuntu 23.10+ also sets
  `kernel.apparmor_restrict_unprivileged_userns=1`) only a profile with a `userns` rule may create one: load the profile `gameanything-steam` once
  (the table above: the 4.0 file on Ubuntu 24.04+, the u2204 file on 22.04; Docker's default profile plus `userns` where AppArmor has it,
  `mount`, `pivot_root`). On Ubuntu 22.04 the profile is needed too: with Docker's default AppArmor, `unshare --mount` fails
  ("cannot change root filesystem propagation: Permission denied"). Docker Desktop (Windows, Mac) has no AppArmor: leave that option out. Steam's web UI also needs `--shm-size 1g`
  (Docker's default is 64 MB). Without these, Steam stops with "Steam now requires user namespaces to be enabled"
  (`~/.steam/debian-installation/logs/console-linux.txt`). Probe in one second: `docker exec <c> unshare --user --map-root-user --mount true`.
- The client runs with `-no-cef-sandbox` (as in the maintainer's Steam lab). Stardew itself runs natively from the downloaded folder;
  it does not need Steam's runtime container.

### Test on 2026-10-29 (maintainer's server: docker-rt pod, then the wc-cities Steam lab)

- **A fresh docker-rt pod cannot run Steam:** user namespaces work, mount namespaces do not (`unshare --user --mount`: Permission denied
  under the cluster's default AppArmor `cri-containerd.apparmor.d`; /dev/shm 64 MB). That is the same restriction as a plain
  `docker run` without the options above. The test therefore ran in `wc-cities`, the one pod with a Steam-capable AppArmor profile,
  with a separate, empty test HOME (`/home/player/ga-steam-test`) so the login was real and the lab's own Steam data was untouched.
- First start: the Debian "Steam installer" notice (click Install), a 505 MB client update, two extract/install rounds (about 20 minutes
  on JuiceFS), then the sign-in window. The maintainer typed her password and approved Steam Guard on her phone (about 6 minutes).
- `steam://install/413150` opened Steam's Install dialog (676 MB; one click). Steam downloaded depot **413153, the Linux build**
  (manifest 6005910083361727734, 709 MB) plus the Steam Linux Runtime, in about 3 minutes. The folder has `libcoreclr.so`, no `.exe`;
  `ga-sdv doctor` says `game_build linux`.
- Smoke flow on the downloaded copy: `ga-sdv layer` (15 s, 226 entries, pinned SMAPI 4.5.2), M2WSmoke built and installed,
  SMAPI "Loaded 3 mods", HUD "[M2W-smoke] hello from GameAnything" after loading a save, a 38-second clip (encoded on the host).
  With Steam running the game logs `Steam logged on: True`.
- Reuse: quit Steam, start it again with the same home: logged on by itself in 61 s, no password, no code; Stardew still
  installed (StateFlags 4), nothing downloaded again.
- Afterwards the lab's own Steam (its original home) logged on by itself again (`gameanything lab env up`, 34 s).

### More games, same test home (2026-10-29, later the same day)

The same test HOME in `wc-cities`, under one lease; the lab's own Steam was stopped first and restarted with `lab env up` at the end.
Steam logged on by itself (about 30 s, no password, no Steam Guard). Each game was downloaded with `steam://install/<appid>` + the
Install click, its folder checked for the Linux build, smoked with the lab's own tools pointed at the test library, recorded, then
uninstalled with Steam's Uninstall dialog.

| Game | Linux depot | Size | Mod loader | Smoke result |
|---|---|---|---|---|
| Terraria + tModLoader | 105602 (Terraria), 1281933 (tModLoader) | 0.8 + 0.17 GB | tModLoader 2026.8 | `[M2W-smoke] loaded`, chat line in the world |
| Valheim | 892971 | 4.2 GB | BepInEx 5.4.23.5 (BepInExPack_Valheim) | banner "M2W smoke: plugin loaded" |
| Overcooked! 2 | 728882 | 8.7 GB | BepInEx 5.4.23.5 | banner on the title screen |

What the user should know (the wizard says it): tModLoader, Cities: Skylines (Paradox User Agreement) and Civilization VI (Take-Two EULA)
show the publisher's license agreement in Steam after Install, which the user accepts themselves; nothing downloads until then. On a
slow network disk the "installing files" phase can take longer than the download (Terraria: ~16,000 small files). After a game is
stopped by force, restart Steam before the next install or uninstall: Steam keeps it "running" and does nothing meanwhile.

### Cities: Skylines and Civilization VI in an ordinary Kubernetes pod (2026-10-29, evening)

A user's existing pod (Ubuntu 22.04, 16 GB, one L40S, Xorg on the GPU; the mount-namespace probe passed), not a lab: `install-base.sh`
+ `install-steam.sh`, a fresh test HOME, the user signed in once in the viewer. Everything added was removed afterwards.

| Game | Linux depot | Size | Smoke result | Memory |
|---|---|---|---|---|
| Cities: Skylines | 255713 | 17.1 GB on disk (6.3 GB download, ~7 min) | M2WSmoke compiled by the game, `[M2W-smoke] city loaded (NewGame)` | game 8.4 GB RSS |
| Civilization VI | 533502 + 533503 (Aspyr), 533504, 289089 | 25.5 GB on disk (10.9 GB download, ~11 min) | `Applying Component - M2WSmokeGameplay`, "[M2W-smoke]" in the menu and World Tracker | game 3.0 GB RSS |

What it taught (HICCUPS steam #26-30):
- **64 MB /dev/shm** (the Kubernetes / Docker default; cannot be remounted in the pod): Steam fills ~55 MB itself and the sign-in
  window's renderer crashes every ~2 s, so the window never shows. `ga-steam shm-fix` (run by `ga-steam start` and by the watchdog,
  entry `steam_small_shm`) adds `--disable-dev-shm-usage` to `ubuntu12_64/steamwebhelper_sniper_wrap.sh` **at the same file size**:
  Steam checks its own files by size at every start and re-extracts the whole client when one differs. Better: `--shm-size 1g`.
- Ubuntu 22.04 has the pre-`t64` library names: the install scripts pick the name the release has.
- The Dockerfiles delete /opt/gameanything/src, so ga-steam imports the watchdog from /opt/gameanything/lib-src (install-gameanything.sh).
- Both publisher agreements come after Steam's Install window; the user clicked Install and Accept herself. Cities shows Paradox's
  in-game Legal Disclaimer on its first start (the user's Agree) and starts new mods switched off (userGameState.cgs). Civ VI's first
  start switches the screen to 1024x768 full screen (the lab's click positions then miss): `FullScreen 0` in AppOptions.txt.

### Plain Docker Engine on Linux + NVIDIA (2026-10-29)

The first test outside the maintainer's cluster: a stock Ubuntu 22.04.5 server (Docker client 27.5.1 / engine 29.5.3, cgroup v2,
AppArmor 3.0.4, 8x L40S, NVIDIA Container Toolkit in CDI mode), images built locally for the host user (uid 1004). Stardew Valley
(Steam download, mounted folder, reuse, sha256, out of memory) and Minecraft (Microsoft download, GPU, reuse, a 0600 world mounted
read-only) passed after fixes; every step, time and fix is in `docs/sandbox-hiccups.md`. What a plain Linux host needed:

- The Steam AppArmor profile: on 22.04 the AppArmor 3 variant `security/gameanything-steam-u2204.apparmor` (the AppArmor 4 one does
  not load). Without a profile, also with `seccomp-steam.json`: `cannot change root filesystem propagation: Permission denied`.
- `~/.steam/debian-installation/steamapps` in the image (now in `install-steam.sh`, also under `/sandbox/home` for a pulled image run
  with `--user`): else Steam's first start stops with `Permission denied`. **The published images of 2026-10-29 lack them.**
- After an NVIDIA driver update, `sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml`, else `--gpus all` fails.
- Images go to `/var/lib/containerd` (Engine 29's containerd store), here on the root disk, not to `/var/lib/docker`: the builds of
  the other games filled the shared root disk and were stopped; `lab setup --image` now checks that disk first. The other games are
  not yet tested on plain Docker. `docker builder prune` frees little there (the old cache records are snapshots the images still
  use; 1.3 GB of 37.6 GB "reclaimable"): move /var/lib/containerd to the big disk instead.
- On a server, publish the viewer on `127.0.0.1` and use an SSH tunnel.
- The republished images of 2026-10-30 (7cee3d6): `.steam` fixed (Steam's first start reached the sign-in window for uid 1000 and
  `--user 1004`), but built with umask 077: /opt/gameanything, /usr/local/lib/gameanything, /game, /saves are root-only and
  `ga-steam` / `ga-sdv` crash for the player. Fixed in the images of 1406889 (`:20261030b`, rebuilt from base); the images of
  3b2ecb0 (`:20261030c`) add the tester's later fixes (passwd/group 666 for `--user`, Terraria, Cities, Civ VI, The Sims 4); Civ VI
  and Terraria are `:20261030d` (add7bc8: `echo $SCREEN` is `1600x900x24` in Civ VI, `grep -c seed_config /usr/local/bin/ga-terraria` > 0); The Sims 4 is `:20261030e` (c31790a: `grep -c wait_signed_in /usr/local/bin/ga-sims4` > 0). All fifteen are `:20261030g` (41de0a2: `grep -c fit_output /usr/local/lib/gameanything/galab.py` > 0, `fc-list :lang=zh family | grep -c 'Noto Sans CJK'` > 0, a `rec` file has an audio stream in `ffprobe`). Valheim and The Sims 4 are `:20261031a` (656e75a: `grep -c _backup_auto /usr/local/bin/ga-valheim` > 0, `grep -c only_launcher_left /usr/local/bin/ga-sims4` > 0). Stardew Valley is `:20261102a` (31120bb: the 20261101a checks (`ls /opt/gameanything/vendor/ContentPatcher-2.9.1-src.tar.gz`, `dotnet --list-sdks` lists 10.0.113) plus `grep -c _stage_pack /opt/gameanything/venv/lib/python3.12/site-packages/gameanything/native/games.py` > 0). Check after a pull:
  `docker run --rm --user 1000 --entrypoint sh IMG -c 'ga-steam status >/dev/null 2>&1 || echo FAIL; find /opt/gameanything /usr/local/lib/gameanything /game /saves -maxdepth 2 ! -perm -o=r'`
  prints nothing (Minecraft and The Sims 4 have no `ga-steam`: there it prints FAIL, use the find part).
- 2026-10-30, images built here from main (umask fix): Slay the Spire, KSP, Terraria + tModLoader, Valheim, Overcooked! 2 pass (smoke
  mod on screen, reuse, read-only `/game` identical by sha256; sandbox-hiccups.md). A game Steam downloaded in the sandbox is mounted from the
  library volume with `--mount "type=volume,src=ga-steam-games,dst=/game,volume-subpath=common/<folder>,readonly"` (Engine 26+).
  The Terraria fixes of that day (sandbox-hiccups.md #24-#25) are in the `:20261030c` images (3b2ecb0).

## Logging in and downloading, watched (`gameanything lab login`, the setup watchdog)

One command for the user's own store account, from the host (added 2026-10-29 from the runs above):

```bash
gameanything lab login steam --project P [--app 413150] [--install] [--lang zh|en] [--json]   # or --container ga-stardew-steam
gameanything lab login microsoft --project P                                                 # Minecraft: the device code
gameanything lab login ea --project P [--install]   # or --local inside the sandbox   # The Sims 4: Wine + EA App (lab 10-29)
gameanything lab consent --app 255710 --project P --yes --note "said yes in chat"            # the user agreed; they still click Accept
```

- **Steam:** the sandbox answers, `ga-steam` is in the image, the one-second mount-namespace probe (it names the missing
  `docker run` options), the screen; then the client (first start: the Debian notice is clicked, the ~500 MB self-update is reported in
  percent), the sign-in window (detected from `steamui_login.txt` `WaitingForCredentials` / `webhelper.txt` `DesktopLoginWindow`,
  not from window titles), the viewer URL with "tick Remember me, approve Steam Guard on your phone", `[Logged On`, then the licence
  (`ga-steam owns`: installed = yes, Steam's "No licenses" = no, else the install shows it). `--install` continues into the download.
- **Microsoft:** a saved sign-in is rechecked first (no code); otherwise one `ga-mc account login` in the background (an existing one
  is reused, never a second code); the code and microsoft.com/link are shown, a new code when one expires; then ownership of Java Edition.
- Progress lines are in the user's language; `--json` prints one event per line with both languages and the result last. Exit codes:
  0 ok, 4 the user must act, 5 sandbox not running, 6 unsupported / not verified, 7 not owned, 8 timeout.
- Inside the sandbox the same watching: `ga-steam install APPID --wait`, `ga-steam app APPID --watch`, `ga-steam wait`;
  `ga-mc download` prints a line at least every ~2 min; `ga-mc run` stops with the words of a known situation (a missing world).

**The watchdog** (`gameanything/watchdog.py`): every wait loop calls `Watchdog.tick()`. A tick snapshots the sandbox from inside (one
`python3 -c` exec: windows with sizes, processes by `/proc/<pid>/exe` and argv element, log tails, one grepped value from
`config.vdf`, app manifests, folder sizes, the library's filesystem) and matches the facts against the KNOWN table
(`gameanything/hiccups.py`, 25 situations from the HICCUPS lists). It acts (only the safe scripts in `watchdog.ACTIONS`), tells the
user, or stops and asks. When nothing changed for ~60 s it saves a redacted snapshot and a screenshot (read through the exec, never
while a sign-in or Friends window is open) and, if no known situation matches, tells the user what it sees with the screenshot path.
It never stays silent more than ~110 s. Licence entries can never be automatic (`hiccups.validate()`, and refused at run time).

### Adding a known situation
1. Add ONE entry to `KNOWN` in `gameanything/hiccups.py`: `id`, `flows`, `phases`, `when` (facts that must hold), `min_stall_s`,
   `kind` (`auto` with an `action` from `watchdog.ACTIONS`, `tell`, `ask`, `ignore`), `say` with the exact `zh` and `en` words,
   `max_wait_s` and optionally `then` (the escalation), `source` (where it was seen).
2. If no existing fact detects it, add the fact in `watchdog.facts()` (and, if it needs a new file, the path in `watchdog.SPECS`;
   never a whole login or token file).
3. Add a snapshot to `tests/fixtures/watchdog/snapshots.json` (text logs and window lists only, no images, no personal data) with
   `"expect": "<id>"`; `tests/test_watchdog.py` checks it and `hiccups.validate()`.
4. A publisher agreement is `license: True` with `kind: ask` and goes into `EULAS` too.

## Licenses of what is in the image

Everything in the images may be redistributed (the Steam bootstrap: see its row). The GPL and LGPL parts must ship with their license
texts and with an offer of their source code; the **GPL** column marks the copyleft parts. Today the images are private packages
(2026-10-29); the checklist below says what still has to be done before any image is made public.

| Component | Where from | License | Redistribute? | Notes |
|---|---|---|---|---|
| **Layer base, steam, dotnet, java, wine; per game: see the Images table** | | | | |
| Ubuntu 24.04 base and apt packages | official `ubuntu:24.04` image, Ubuntu archive | mixed free licenses (GPL, LGPL, MIT, BSD, ...) | yes | Canonical allows unmodified Ubuntu packages in images; GPL source = the Ubuntu source packages (pin an archive snapshot so they match) |
| Xvfb / X.Org server | apt `xvfb` | MIT/X11 | yes | |
| x11vnc | apt | GPL-2.0-or-later | yes | **GPL**: source offer (Ubuntu source package of the snapshot day) |
| noVNC | apt `novnc` | MPL-2.0 (some files BSD / MIT / OFL fonts) | yes | |
| websockify | apt | LGPL-3.0 | yes | |
| xdotool | apt | BSD-3-Clause | yes | |
| Mesa (llvmpipe software GL) | apt | MIT | yes | |
| SDL2, OpenAL Soft, libgdiplus, ICU | apt | zlib, LGPL-2.0+, MIT, Unicode | yes | the game's own native libraries load these |
| PulseAudio | apt | LGPL-2.1+ (some modules GPL) | yes | **GPL** modules: source offer; null sink only |
| FFmpeg | apt `ffmpeg` (Ubuntu build) | GPL-2.0-or-later (built with x264/x265) | yes | **GPL**: source offer; H.264/HEVC may be patent-encumbered in some countries; the sandbox records MJPEG, encoding is the user's choice |
| .NET SDK 8 | apt `dotnet-sdk-8.0` (Ubuntu's source build) | MIT | yes | not Microsoft's binary tarball; telemetry off (`DOTNET_CLI_TELEMETRY_OPTOUT=1`) |
| SMAPI 4.5.2 installer | GitHub release zip, sha256-pinned | LGPL-3.0 (bundled Harmony, Newtonsoft.Json, Mono.Cecil, Pintail: MIT) | yes, unmodified | ship the license and a link to https://github.com/Pathoschild/SMAPI; the user's game is never part of it |
| Content Patcher 2.9.1 source (Stardew image) | GitHub tag `content-patcher/2.9.1` of Pathoschild/StardewMods (codeload tarball), sha256-pinned; `/opt/gameanything/vendor/ContentPatcher-2.9.1-src.tar.gz` + `-LICENSE` | MIT | yes | the built mod is only on Nexus (https://www.nexusmods.com/stardewvalley/mods/1915, login): `ga-sdv layer` builds it offline from this source into the sandbox's own layer (never the user's folder); the image holds no built copy |
| Pathoschild.Stardew.ModBuildConfig 4.4.0, Microsoft.NETCore.App.Ref / Microsoft.AspNetCore.App.Ref 6.0 (Stardew image) | NuGet, restored at image build into `/opt/gameanything/vendor/ContentPatcher-2.9.1-nuget` (the offline source for that build) | MIT | yes | unmodified .nupkg files |
| .NET SDK 10 (Stardew image) | apt `dotnet-sdk-10.0` (Ubuntu's source build) | MIT | yes | Content Patcher 2.9.1 is C# 14; next to the dotnet layer's SDK 8, the default `dotnet` there |
| OpenJDK 25 (layer java: Minecraft, Slay the Spire) | apt `openjdk-25-jdk-headless` | GPL-2.0 with Classpath Exception | yes | **GPL** (+ Classpath Exception): source offer (Ubuntu source packages); Slay the Spire's mods use `javac --release 8` |
| Xorg server (`xserver-xorg-core`) | apt | MIT/X11 | yes | GPU screen; the NVIDIA driver and its X module come from the host at run time (`--gpus`), never in the image |
| GTK 3, NSS, udev libraries (KSP image) | apt | LGPL-2.1+, MPL-2.0, LGPL-2.1+ | yes | Unity's player loads them |
| Python 3.12 | apt | PSF-2.0 | yes | |
| GameAnything | this repository | Apache-2.0 | yes | **only once the repository is public**: the image carries its code |
| pillow / pyyaml / numpy / opencc / pypdfium2 | PyPI wheels | HPND, MIT, BSD-3 (OpenBLAS BSD, libgfortran GPL + runtime exception), Apache-2.0, Apache-2.0/BSD-3 (PDFium) | yes | |
| pillow-heif | PyPI wheel | BSD-3; the wheel bundles libheif / libde265 (LGPL-3.0) and x265 (GPL-2.0) | yes | **GPL**: source offer for the bundled libraries |
| PyAV (`av`) | PyPI wheel | BSD-3; the wheel bundles an FFmpeg build (LGPL / GPL parts) | yes | **GPL** parts possible: check the wheel's bundled license list before publishing |
| DejaVu and WenQuanYi Zen Hei fonts | apt | Bitstream Vera; GPL-2.0 with font exception | yes | **GPL** (font exception: documents using it are not covered) |
| Noto Sans / Serif CJK, Droid Sans Fallback fonts | apt `fonts-noto-cjk`, `fonts-droid-fallback` | OFL-1.1; Apache-2.0 | yes | ship the licenses (in /usr/share/doc) |
| tini | apt | MIT | yes | |
| Vulkan loader, Mesa Vulkan drivers (lavapipe) | apt `libvulkan1`, `mesa-vulkan-drivers` (base, wine) | Apache-2.0, MIT | yes | DXVK and Unity's Vulkan path; the NVIDIA ICD comes from the host |
| Steam bootstrap (layer steam; Stardew, KSP, Terraria, Valheim, Overcooked! 2, Cities, Civ VI, Slay the Spire) | apt `steam-installer` (Ubuntu multiverse), `steam-libs-*` | Valve's Steam license for the bootstrap tarball; the libs are free | Ubuntu redistributes it in multiverse; **review before a public image** | only the bootstrap: the client (~500 MB) is downloaded by Steam into the user's own volume on first start, under the Steam Subscriber Agreement the user accepts |
| i386 libraries for Steam (Mesa, libGL, Vulkan) | apt `:i386` (layer steam) | MIT and others | yes | |
| GTK 3, NSS, GLib, udev (layer dotnet) | apt | LGPL-2.1+, MPL-2.0, LGPL-2.1+, LGPL-2.1+ | yes | Unity players load them |
| Wine 11.19 staging, WoW64 build (layer wine) | Kron4ek/Wine-Builds release tarball, sha256-pinned | LGPL-2.1-or-later | yes | **GPL-family (LGPL)**: source = WineHQ 11.19 + wine-staging 11.19 (Kron4ek builds unmodified); ship the license and the source link |
| wine-mono 11.3.0 (layer wine) | dl.winehq.org MSI, sha256-pinned | MIT, with LGPL-2.1 / GPL-2.0 / MS-PL parts (its COPYING) | yes | **GPL parts**: source at github.com/madewokherd/wine-mono tag 11.3.0 |
| wine-gecko 2.47.4 (layer wine) | dl.winehq.org MSIs, sha256-pinned | MPL-2.0 | yes | source at the WineHQ wine-gecko 2.47.4 tarball |
| DXVK 3.1.1 (layer wine) | GitHub release, sha256-pinned | zlib | yes | |
| CPython 3.7.17 (layer wine) | python.org source tarball, sha256-pinned, built in the image | PSF-2.0 | yes | only for The Sims 4 script mods (`.pyc` of 3.7); no ssl module |
| GStreamer, GnuTLS, FreeType, fontconfig, Kerberos, CUPS libs, cabextract, winbind (layer wine) | apt | LGPL-2.1+, LGPL-2.1+, FTL/GPL-2, MIT, MIT, Apache-2.0, GPL-3+, GPL-3+ | yes | **GPL**: cabextract, winbind (Samba): source offer (Ubuntu source packages) |
| BepInEx 5.4.23.5 (Valheim, Overcooked! 2) | GitHub release zip, sha256-pinned | LGPL-2.1 (bundles HarmonyX, MonoMod, Mono.Cecil: MIT; UnityDoorstop: LGPL-2.1) | yes, unmodified | **LGPL**: ship the license and https://github.com/BepInEx/BepInEx; unpacked only into the sandbox's copy of the game |
| M2WSmoke smoke mods (source: Stardew, KSP, Minecraft, Slay the Spire) | this repository | Apache-2.0 | yes | built by the user, against their own game |

**Never in the image:**

| Item | License | Reason |
|---|---|---|
| Stardew Valley game files | ConcernedApe EULA | not redistributable |
| Steam client, steamcmd and Proton | Valve Steam Subscriber Agreement | not redistributable; the steam layer only adds Ubuntu's `steam-installer` bootstrap (multiverse), and Steam downloads the client into the user's own volume on first start. The bootstrap is in the PRIVATE images; check it again before an image is public |
| EA App | EA User Agreement | not redistributable: `ga-ea install-app` downloads EA's installer into the user's volume, and the user accepts EA's agreement in it |
| Terraria, tModLoader, Valheim, Overcooked! 2, Cities: Skylines, Civilization VI, The Sims 4 game files | their publishers' EULAs (tModLoader: its own EULA) | not redistributable; mounted read-only or downloaded with the user's own account |
| EA App and Microsoft or Mojang launchers | their own terms | same as Steam |
| StarDojo harness mod | MIT | redistributable, but this image does not need it |
| KSP, Minecraft (client jar, libraries, assets), Slay the Spire game files | Take-Two / Mojang EULA / Mega Crit | not redistributable; mounted from the user's folder |
| ModTheSpire, BaseMod, StSLib | MIT | redistributable, but the image takes the user's Workshop copies (the versions that match their game) |
| Fabric loader and Fabric API | Apache-2.0 | come with the user's own Fabric profile and `mods/` |
| NVIDIA driver libraries | NVIDIA license | injected by the container runtime from the host |

**Checklist before publishing any image publicly (task 9):** (done 2026-10-29: all ten pushed as PRIVATE packages, Wenyi's decision)

0. Check the Steam bootstrap (`steam-installer`) row again: it is fine in private images; a public image needs a clear answer.
1. Generate an SBOM of the built image with license fields, and compare it with the table above.
2. Put the license texts in `/usr/share/doc/gameanything/` (the apt packages already keep theirs in `/usr/share/doc/<package>/copyright`).
3. Add a SOURCES note that names the Ubuntu snapshot and the wheel versions, so the GPL and LGPL source can be found.
4. Make the GameAnything repository public first.
5. Get Wenyi's yes.

## EA App download of The Sims 4 (lab test 2026-10-29)

`lab/images/common/ga-ea` (stdlib; copy it into a Sims 4 image next to the watchdog, like ga-steam) puts Wine and the EA App under
`GA_EA_HOME` (default /sandbox/ea, the data volume): Kron4ek wine-11.19-staging-amd64-wow64 (no 32-bit libraries), wine-mono 11.3.0 and
wine-gecko 2.47.4 placed next to Wine (no "Wine Mono Installer" box; the EA installer's .NET custom action needs mono), DXVK 3.1.1, the
EA App installer. Tested in mclab-hlm-m1 seat 2 (Xvfb :106) with a fresh prefix, run INSIDE the sandbox (`lab login ea --local`):

| Step | Result | Time |
|---|---|---|
| `ga-ea setup` | Wine 11.19 + mono + gecko + DXVK in a new prefix | 72 s |
| installer, first page | EA User Agreement: the user read it and clicked LET'S GO herself | (her decision) |
| EA App 13.813.1.6327 install | `Apply complete, result: 0x0`; the app starts by itself (no D0-4A8E error this time) | 20 s |
| sign-in | the user in the viewer (e-mail, password, code); `DesktopFSM[authenticated]` | 3.5 min |
| restart with the same prefix | signed in by itself, nothing typed | 32 s |
| ownership | The Sims 4 "Standard Edition owned" (`externalSource: STEAM` = the account is linked to Steam; `managedBy: EA`) | seconds |
| download options | tile "..." > Download: EA's own dialog, C:\Program Files\EA Games\The Sims 4, 26.33 GB | seconds |
| Terms of play | EA User Agreement + Microsoft VC++ 2015/2019 Runtime Agreements; DOWNLOAD = agreeing (the user's decision) | - |

Correction: a first attempt concluded "the EA App hands the download to Steam". That was a misclick: the window had been maximised
without a window manager, clicks landed on a banner link (winebrowser). See skills/.../sandbox-logins.md "Verify before concluding".

Memory: the EA App idle is about 2.9 GB RSS (Qt WebEngine: browser 1.0 GB, renderers 0.7 GB, GPU process 0.35 GB). The pod-local disk
was used for the prefix (JuiceFS writes had stalled earlier). Then (20:04-20:18): the user clicked DOWNLOAD; 26.3 GB in about 4.5 min (`title.install.finished`); Play in the EA App started
1.129.39.1030 (DX11 via DXVK, on Xvfb); `gameanything native install --game sims4` of a package-only smoke mod (STBL overrides):
the Mods dialog lists M2WMenuTest and the menu reads "M2W Mod Loaded". Memory: game 1.6 GB + EA App 2.9 GB. Reuse: app restarted,
signed in after 29 s, game still installed. The test prefix (31 GB with the game) stays on the pod's local disk for re-tests.

