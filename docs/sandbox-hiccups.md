# HICCUPS: plain Docker + NVIDIA on a real Linux server (sandbox plan task 10)

Test host: the maintainer's GPU server, 2026-10-29. Stock Ubuntu 22.04.5, kernel 6.5.0-1024-nvidia, 503 GB RAM, 8x NVIDIA L40S
(driver 580.178.04), Docker client 27.5.1 / engine 29.5.3 (cgroupfs, cgroup v2), NVIDIA Container Toolkit in CDI mode, AppArmor
parser 3.0.4, `kernel.apparmor_restrict_unprivileged_userns` absent (0). A shared machine: other users' containers keep running, so the
Docker daemon was never stopped (the "not running" case is simulated with a DOCKER_HOST that has no engine).

Each entry: what appeared, how it was detected, how long it blocked, the fix or the words for the user.

| # | What appeared | How detected | Blocked | Fix / words for the user |
|---|---|---|---|---|
| 1 | `docker run --gpus all` failed: `failed to fulfil mount request: open /usr/lib/x86_64-linux-gnu/libEGL_nvidia.so.595.58.03`. /etc/cdi/nvidia.yaml was generated for driver 595, the running driver is 580.178.04 (the CDI spec was not regenerated after a driver change). | the error text names a library version that differs from `nvidia-smi`'s driver version | ~10 min (Wenyi ran the fix with sudo) | `sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml`. It fails in `docker run` itself, before any sandbox exists, so the watchdog cannot see it: no hiccups.py entry; it goes into the Linux setup page's pitfalls instead (the real error text). |
| 2 | Detection said "Docker ok" when the engine does not answer. Docker client 27.5.1 prints the error on stderr but `0` on stdout for `docker info --format {{.MemTotal}}`, and exits 0. | `DOCKER_HOST=unix:///tmp/no-such-docker.sock gameanything setup guide --mode sandbox` | 0 (found by the test) | code: MemTotal 0 = not_running (sandbox._docker); test added |
| 3 | Detection did not report the GPU (the plan's test 1 lists it). | reading `setup guide` output | 0 | code: `gpus` from `nvidia-smi --query-gpu=name` on Linux/Windows; the guide prints `GPU 8× NVIDIA L40S` |
| 4 | `gameanything lab setup` crashed (`AttributeError: 'NoneType' object has no attribute 'config_path'`) with a gamebench checkout of a branch without `hosting/lab/` (main and wenyi have none; only wenyi-west1 has it). | running `lab setup --yes` with GAMEANYTHING_GAMEBENCH=the wenyi checkout | ~5 min | code: a clear message naming the missing file; test added. Test used a separate worktree of wenyi-west1 on the test server. |
| 5 | `lab/images/common/security/gameanything-steam.apparmor` does not load on Ubuntu 22.04: `Could not open 'abi/4.0'` (AppArmor 3.0.4 has abi/3.0 only; the `userns` rule is AppArmor 4). | `apparmor_parser -Q -K <profile>` (parse only, nothing loaded) | (waiting for Wenyi's sudo) | Needed on this host: in the image, `unshare --user --map-root-user --mount true` fails with Docker defaults (`Operation not permitted`), and with seccomp-steam.json alone (`cannot change root filesystem propagation: Permission denied`, docker-default AppArmor); it works only with an AppArmor change (apparmor=unconfined tried as a diagnostic, never as the fix). Fix: lab/images/common/security/gameanything-steam-u2204.apparmor (abi/3.0, no `userns` rule; same profile name), loaded once with sudo. |
| 6 | No command starts a Steam sandbox: `sandbox.steam_run_args` exists but nothing calls it; the user types `docker run` by hand from the docs. | grep | 0 | recorded; the exact docker run lines go in docs/sandbox-images.md |
| 7 | The docs' `-p 6080:6080` publishes the noVNC viewer on every interface: on a server with a public IP that is the sandbox's screen (and the Steam sign-in window) open to the internet. | reading the docs before starting on a public-IP host | 0 | used `-p 127.0.0.1:6080:6080` and an SSH tunnel (`ssh -L 6080:127.0.0.1:6080 <server>`); the docs should say so for servers |
| 8 | Steam's first start stopped: `ln: failed to create symbolic link '/home/player/.steam/steam': Permission denied`. The steamapps volume is mounted INSIDE the home volume; the image had no ~/.steam/debian-installation/steamapps, so Docker created .steam, debian-installation and steamapps as root, and Steam (uid 1004) cannot write there. Not seen in the cluster tests (an existing HOME). | the watchdog (`lab login steam`): "63 s without change, not a situation I know" + the last log line; `ls -la ~/.steam` in the container | ~10 min + a rebuild | code: install-steam.sh makes the three folders owned by the player in the image (a new volume takes the image's ownership); hiccups.py `steam_home_not_writable` (kind ask: rebuild the image, remove the two new volumes, re-create) + a fixture test. Second path (found after main got the layered, published images): a pulled image run for another uid (`--user 1004`, HOME=/sandbox/home) hits the same error at /sandbox/home/.steam; install-steam.sh also makes those three folders, mode 1777. Probed both ways: the published gameanything-lab-steam fails for uid 1000 and 1004, a steam layer built with the fix on the published base passes both. The published images must be rebuilt and pushed (not done from this machine). |
| 9 | The watchdog said "还看不出  在不在你的 Steam 库里" (no game name) for `lab login steam --container C --app 413150` without a project. | reading its output | 0 | code: loginflow names the game from the registry by its steam_appid (else "Steam app N") |
| 10 | A second `lab login steam --install` while Steam was already running and signed in printed "启动 Steam。这是第一次……" (steam_start_first: `ga-steam status --json` gave no `running` / `client_installed` at that moment) and ran `ga-steam start`. The Steam process was NOT restarted (same pid, started 21:48:44) and it went on at once ("已登录 Steam"). | its output | 0 | cause not found yet: status answers correctly in 0.3 s afterwards; not reproduced. Words wrong, no harm. Cause found: #11. |
| 11 | The reuse test crashed: `AttributeError: 'int' object has no attribute 'get'` in loginflow.steam. `ga-steam status --json` is indented over many lines; `Flow.jsn` parsed it line by line from the end and took the app list's last item (`  1070560`) as the JSON. Also the cause of #10: before Steam had apps, a `null` item made the status empty -> "first start" + a second `ga-steam start`. | the reuse run | ~5 min | code: jsn reads the whole output first and accepts only a dict; test (fails on the old code) |
| 12 | Out of memory (`--memory 700m`): the kernel killed SMAPI a few seconds after start (cgroup memory.events oom_kill; dmesg CONSTRAINT_MEMCG, only the sandbox). `ga-sdv run` said only "SMAPI exited (code 137)"; the watchdog had no memory fact. | the OOM test | 0 | code: ga-sdv reads oom_kill + memory.max and says "out of memory ... only 0.7 GB ... needs about 1.5 GB ... --memory 4g. Your computer is not affected."; the watchdog snapshot reads the same counter, `sandbox_out_of_memory` (ask, all flows) fires on a kill after the watch began. Measured peaks: 1.32 GiB (build + game), 1.52 GiB (Steam sandbox). Host: other containers up, 441 GB available. |
| 13 | Minecraft, game files at /game (mods/fabric-api inside) and a world at /saves without mods: `ga-mc layer` took mods only from /saves (`mods []`), and the smoke mod failed to compile (`package net.fabricmc.fabric.api.client.event.lifecycle.v1 does not exist`). | the read-only mount test | ~5 min | code: the layer falls back to /game/mods for Fabric API and says plainly when neither has it; test (fails on the old code). Note: `ga-mc layer` keeps an existing layer (`--force` rebuilds it). |
| 14 | `docker stop` + `docker start` of a sandbox: "no X display :99", the container exited. The pid files live on the volume (/sandbox/run); after the restart the old Xvfb pid number belonged to another process, so Xvfb counted as running, was not started, and the stale /tmp/.X99-lock stayed. Same for x11vnc, websockify, the game ("already running") and Steam. | restarting the Stardew sandbox for more Steam downloads | ~10 min | code: ga-sdv, galab (every other ga-* tool) and ga-steam treat a pid file older than the container's PID 1 as stale (`container_started()` from /proc/1/stat + btime); test. Checked live: the stopped container started again with its screen and viewer. |
| 15 | After that restart, `lab login steam` said "已经登录着 Steam" with Steam not running: `ga-steam status` reported the previous start's "Logged On" line as `logged_on_since_start`. | the same | 0 | code: no client running = not signed in now |
| 16 | **The host's root disk filled up (100 %, 189 MB free).** Docker Engine 29 here uses the containerd image store: images and build cache are in /var/lib/containerd on `/` (256 GB, shared, 20 GB free at the start), not in /var/lib/docker (the 6.3 TB disk, where the volumes are). The build of the remaining images (sts, overcooked2, valheim, terraria, ksp, sims4, cities) stopped with "no space left on device"; other users were building large images on the same disk at the same time. | `lab setup --build` failed; `df -h /var/lib/containerd` | stops all further image builds on this host | freed only this test's own: the two pulled ghcr images, the unused base/java images, 12 GameAnything build-cache records of today (by id, `docker buildx prune --filter id=`): back to 4.4 GB. No more images built here. For users: check `df -h /var/lib/containerd` (not only /var/lib/docker) before `lab setup --image`; a server admin can move the containerd root to the big disk. |
| 17 | 2026-10-30, the republished images (sandbox.PUBLISHED, built from 7cee3d6 on the image server), pulled here: `ga-steam` crashed on every command, for uid 1000 AND for `--user 1004` (`PermissionError: '/opt/gameanything/lib-src/gameanything/watchdog.py'`); `ga-sdv doctor` too (`/game`). In the image /opt/gameanything, its layers/ lib-src/ vendor/ venv/, /usr/local/lib/gameanything (galab.py), /game and /saves are mode 700 root and APT_SNAPSHOT 600: the image server's build ran with umask 077, every install script relied on the default 022. The base layer has it too, so every published image is affected. | `docker exec ga-pub1000 ga-steam status`; `find` for paths without o+r as root in the pulled image | 0 (found before any login) | code: every lab/images install script sets `umask 022` right after `set -euo pipefail` (test); ga-steam / ga-ea skip a watchdog folder they cannot read instead of crashing. The images must be rebuilt from the base up (handoff-image-server-umask.md) |
| 18 | The same republished stardew image, with the permissions opened by hand in the two test containers (`chmod -R go+rX` as root, the container only): the `.steam` fix (#8) works. Fresh volumes, uid 1000 (HOME /home/player) and `--user 1004` (HOME /sandbox/home): Ubuntu's "Steam installer" dialog (Install clicked), bootstrap 100 %, the sign-in window 2 min 14 s after the click in both; `.steam/steam` link made by the player, no `Permission denied` except zenity's icon. Pull of the image by digest: 26 s, 2.5 GB on `/`. | `ga-steam status --json` every 30 s; steam.log | 0 | none (#8 confirmed on the published image). Not signed in: test containers and volumes removed after |
| 19 | `docker builder prune -f --filter until=72h` (by Wenyi, to free `/`) freed only 1.3 GB although `docker system df` showed 37.6 GB of build cache "reclaimable": with the containerd image store the old records are snapshots the images still use; a second run reported `Total: 0B`. Removing our own two local images and their 9 cache records freed 5.3 GB. | `df -h /`, `docker buildx du --verbose` | ~20 min | docs: on this kind of host free `/` by moving /var/lib/containerd, not by pruning build cache |
| 20 | With Steam inside the sandbox the game and its Workshop items are in the Steam library VOLUME, not in a host folder: the docs' `-v "$S/common/SlayTheSpire":/game:ro` has no host path to use. Docker's volume subpath does it (Engine 26+ / API 1.45; here client 27.5.1, engine 29): `--mount type=volume,src=ga-steam-games,dst=/game,volume-subpath=common/SlayTheSpire,readonly` (and `.../workshop/content/646570` at /workshop). Read-only held (`touch /game/x`: Read-only file system). | running Slay the Spire from the in-sandbox download | 0 | docs: the volume-subpath mount for a game downloaded in the sandbox |
| 21 | `lab setup --image` refuses below 15 GB free where Docker keeps images (#16), but a whole chain here took 5.5 GB of `/` (base + java + sts, built in 10 min): with 11 GB free the CLI path is closed although the build fits; built with the plain `docker build` lines (docs "Rebuilding the whole chain") under a 3 GB disk guard instead. | building with 11 GB free | 0 | open: 15 GB may be too strict for one game; left as is (the disk is shared) |
| 22 | KSP from a fresh Steam download: the "What's new in 1.12" dialog appeared over the main menu although `ga-ksp layer` writes `SHOW_WHATSNEW_DIALOG = False`; after the run settings.cfg has `SHOW_WHATSNEW_DIALOG = True` and an empty `SHOW_WHATSNEW_DIALOG_VersionsShown` (the lab's folder had them from earlier runs, so the lab test did not see it). An xdotool click on its Close did not register (Unity). | the screenshot | 0 (the menu and the smoke line are behind it) | open: probably needs `SHOW_WHATSNEW_DIALOG_VersionsShown` filled; not changed without a test on the real game |
| 23 | Installing tModLoader (1281930, free, needed for Terraria mods): `ga-steam install` showed the Install dialog, but after Install Steam opened tModLoader's **EULA** (publisher terms) and nothing downloaded until it is accepted; `ga-steam app` shows only `manifest False`. Before that, the store page's "Play Now" offered **Steam Remote Play from another computer on the same account** (the maintainer's Mac, where tModLoader is installed): Cancelled at once. So the account is online elsewhere, and a game that needs Steam running here (Terraria, Valheim, Overcooked 2) may take the session from that computer. | screenshots | ~15 min (Wenyi said 「都同意 继续 你帮我点」; recorded with `lab consent --click-for-me`, Accept clicked, 300 MB in under 2 min) | ask: the EULA is hers to accept (「同意 帮我点」); the watchdog could tell "a publisher agreement is open in Steam" for any app. Never click a store page's Play button: it may start Remote Play |
| 24 | Terraria, first run in the image: `ga-terraria run` said "the game exited" at 0 s while tModLoader was starting (it was downloading its own .NET 8 into /sandbox/game/dotnet, then reached the menu). tModLoader v2026.8.3.0's `start-tModLoader.sh` starts `LaunchUtils/ScriptCaller.sh ... &` and returns; galab watched that pid. | `ps` in the sandbox, the screenshot | ~10 min | code: ga-terraria runs `LaunchUtils/ScriptCaller.sh` (cd's to its folder, ends in `exec dotnet`) when present (test) |
| 25 | Then `native build --install M2WSmoke` put the .tmod in `~/.local/share/Terraria/tModLoader/Mods` (game.yaml's Linux user folder) while tModLoader runs with `-tmlsavedirectory /sandbox/saves`: enabled.json `[]`, the mod never loaded. And `run` waited 420 s for "Mods using the most RAM" / "Main Menu", which a start without mods never logs. The image had only been built, never run with the game (docs: "built only"). | client.log, enabled.json | ~10 min | code: GAMEANYTHING_TERRARIA_USER_DIR pins the user folder (adapter.user_dir; the image sets /sandbox/saves) (test); ready also on "Mod Load Completed" |
| 26 | `lab setup --image civ6` refused with 14.1 GB free although Civ VI shares base + steam with the Cities image already there: the pull was 0.4 GB (8 s with `docker pull` by digest). The 15 GB check (#16, #21) counts no shared layers. | the refusal | 0 | open: the check could subtract the layers already present (`docker manifest inspect` sizes minus local ones) |
| 27 | `sandbox.run_argv` mounts only a host folder (`-v <game_dir>:/game:ro`): a game Steam downloaded in the sandbox (ga-steam-games) needs `--mount type=volume,...,volume-subpath=common/<folder>,readonly`, which it cannot express. | writing the run lines | 0 | fixed 2026-10-30: `sandbox.sandbox_argv` writes the volume-subpath mount, and `gameanything lab sandbox up --project P` (labsandbox.py) starts a project's sandbox with every option on plain Docker without gamebench (tests/test_labsandbox.py; Valheim verified end to end) |
| 28 | Cities: Skylines (pulled 20261030b image): `ga-cities run` waited 420 s for "MainMenu" while the game was at its menu after 26 s (the smoke mod even started a city): the 2026 Linux build logs no such line. | screenshot, Player.log | ~10 min | code: ready on the `Saving ...userGameState.cgs` line (the menu; the `Loading` one comes at start-up) or the smoke mod's "menu True" / "city loaded" (test) |
| 29 | Cities, the next start hung at Mono init for 7 min, twice: a Cities.x64 from the previous run, in another process group, survived `ga-cities stop` (galab killed only the started group). SIGKILL of it (our own process) fixed the next start. | `ps` in the sandbox | ~15 min | code: galab `stop` also kills the processes whose executable lies in the sandbox's game layer (`stray_game_pids`, test) |
| 30 | **Civ VI segfaulted at once as `--user 1004` on the pulled image** (built for uid 1000): no /etc/passwd line for 1004, and Aspyr's build takes its user folder from the account's home. With a line added by hand (root, in that container) it ran. Every user whose uid is not 1000 hits this with Civ VI (and Wine looks the account up too). | `./Civ6` by hand: Segmentation fault; `getent passwd 1004` empty | ~10 min | code: the base layer leaves /etc/passwd and /etc/group writable (mode 666, inside the container only) and galab / ga-ea add the missing line (`ensure_account`, home = $HOME) (test). Needs a base rebuild |
| 31 | Civ VI's first start shows the **2K Games Online Policies, Agreements and Terms** in the game (after Steam's Take-Two EULA). On the 1280x720 screen the game window is 1024x576 (80 % of the screen) and the Agree button is cut off; with RenderWidth/Height 1280x720 the button showed but the mouse no longer matched (a click on "I Agree to All" hit the Privacy Policy button). With a 1600x900 screen (window 1024x768) Wenyi accepted it herself in the viewer. | screenshots | ~25 min | code: ga-civ6 defaults SCREEN to 1600x900x24 (test). The agreement is the user's (she said 「同意 帮我点」, our click missed; she clicked) |
| 32 | `lab login ea --install` said "还在下载模拟人生 4（已 N 分钟，正常）" every 2 min for 17+ min while nothing downloaded: `ga-ea status` game_bytes 0, no game folder; the download had not even been asked for (the user still had to click Library > Download > NEXT > the Terms of play). | `ga-ea status --json` | ~20 min of a wrong message | open: say "waiting for you to click DOWNLOAD" until gameStatus is installing / bytes grow |
| 33 | The EA App under Wine (Xorg + GPU, 20261030b sims4 image) repaints only on input: the window looked frozen (menu click "did nothing", "Calculating disk space..." for minutes) until the mouse moved; an `xdotool windowsize` made it draw at the old size until a restart. After `ga-ea stop` / `start` (saved sign-in, ~30 s) and a mouse move after each click it worked: Library > ... > Download > Download options (26.33 GB) > NEXT > Terms of play. | identical screenshots, then a mouse move | ~15 min | open: ga-ea / the watchdog could nudge the pointer before each snapshot; do not resize the EA window |
| 34 | The Sims 4 (pulled 20261030b, `--user 1004`): `ga-sims4 run` said "the game exited" after 2 s every time while the game came up: `wine TS4_x64.exe` exits with 170 and the EA App starts TS4_x64.exe again (another parent, so galab lost it). Then, following it, `run` waited 420 s: the window is "The Sims\u2122 4" and the tool looked for `^The Sims 4`. And on a cold start (EA App just started, not signed in yet) the hand-over was dropped: no game at all. | `ps`, `xdotool search`, the logs | ~30 min | code: galab `relaunch_name` follows the re-started process by name (`pids_by_comm`); ga-sims4 window `^The Sims`; `run` waits for `ga-ea status` signed_in first (tests). After: game up in 10-12 s, a cold start 22 s, `stop` ends it |
| 35 | The first start of The Sims 4 drew a black screen for 2+ min in every screenshot (the game loading under DXVK; the process at 300 % CPU, on the GPU); `native build --install` said "没有找到 The Sims 4" before that first start (Documents/Electronic Arts/The Sims 4 does not exist until the game made it). | screenshots, the install message | ~5 min | docs: start the game once before the mod install (as in the lab) |
| 36 | Civ VI on the 20261030c image still ran on a **1280x720** screen: the base image's `ENV SCREEN=1280x720x24` is always set, so `ga-civ6`'s `os.environ.setdefault("SCREEN", "1600x900x24")` (#31) never applied (my test checked only the script). The 2K agreement was already accepted on this volume, so the menu came up anyway; a first start would cut the Agree button off again. | `env` in the container, `xdpyinfo` | 0 | code: the civ6 Dockerfile sets `ENV SCREEN=1600x900x24` (test checks the Dockerfile); needs a civ6 image rebuild |
| 37 | Terraria with a **fresh sandbox volume** (20261030c image, `--user 1004`): `ga-terraria run` waited 420 s and said "not up": a save folder without config.json opens tModLoader on **Select language**, then its first-launch **Welcome** (OK). My earlier pass reused a volume that had been through both. | screenshot, client.log stuck before mod loading | ~20 min | code: `ga-terraria layer` writes `/sandbox/saves/config.json` with `Language: en-US` and `LastLaunchedTModLoaderVersion` (read from tModLoader.dll's ProductVersion) when there is none; fresh volume then up in 24 s with M2WSmoke loaded, no click (test). Needs a terraria image rebuild |
| 38 | The Sims 4 cold start on the 20261030c image (same ga-sims4 volume as #34, ~4 h later): the EA App came up on its **sign-in window** (fsm awaitingAuthentication) instead of signing in by itself; `ga-sims4 run` waited its 180 s, then the game exited. The Wine profile is unchanged (`drive_c/users/player`, USER=player), so not the new passwd line; most likely EA's saved session expired. | `ga-ea status --json` | until Wenyi signed in (~10 min) | code: `ga-sims4 run` stops after ~30 s on the sign-in window with "gameanything lab login ea, then run again" (a brief one at a cold start still passes; test). After her sign-in: game up in 11 s, Mods dialog lists M2WSmoke (sims4/menu-mods-20261030c.png, name masked) |
| 39 | The Sims 4 image was re-published (`:20261030e`, sha256:4c94475a...) but `sandbox.PUBLISHED` on main still named the `:20261030c` digest (ffdbf5bc...): `lab setup --image sims4` pulled the old image again (`grep -c wait_signed_in` = 0). | the check after the pull; `docker buildx imagetools inspect ...:latest` | ~2 min | pulled by digest and tagged by hand; the image server should push the new digest to `sandbox.PUBLISHED` with the image |
| 40 | E2E from a fresh clone (`uv tool install git+…`, new GAMEANYTHING_HOME, no gamebench): the installed package had no `lab/images/common/security`, so `lab sandbox up` of a Steam game failed on the missing seccomp file. | docker run error | ~10 min | fixed (ddbd4bf): the profiles are bundled like the skill, `sandbox.security_folder()`, wheel test |
| 41 | `setup guide` on the user's own headless server said "the hub's server" and gave the hub guide (seats, queue). | the guide's first lines | 0 | fixed (ddbd4bf): only the hub or a gamebench lab gets server-sandbox (now internal/, 87f306d) |
| 42 | The E2E builder used raw `docker exec` 5 times (reading files, `xrandr`): the role forbids it and there was no other way. | builder log | 0 | fixed (13de994): `lab sandbox look` (read-only), `fetch`; the xrandr need is #44 |
| 43 | The builder ran Valheim before Steam was up and looked at a black screen for minutes. | builder log | ~5 min | fixed (13de994): `lab sandbox tool -- run` of a Steam game refuses without Steam and names `lab login steam` |
| 44 | **Xorg on the GPU: the output's preferred mode was 1024x576 on a 1280x720 screen**: the game drew 1280x720 but the pointer stopped at 1024x576, so nothing in the lower part could be clicked (Valheim's 「新建角色」; likely also Civ VI's misplaced 2K agreement click, #31). | the builder's mouse tests, `xrandr` | ~15 min | code (13de994): `galab.fit_output` sets the output mode to the screen after Xorg starts (1600x900 added from gtf); in the `:20261030g` images (41de0a2) |
| 45 | No CJK font in the images: the Chinese banner drew as boxes (the builder switched to Valheim's own NotoSerifSC). | screenshot | ~10 min | fixed (41de0a2, `:20261030g` images): the base already had fonts-wqy-zenhei (a .ttc; `fc-list :lang=zh` listed it), so the game did not use it; base now adds fonts-noto-cjk (Noto Sans CJK, +61 MB download) and fonts-droid-fallback (a plain .ttf). Not yet seen in a game: please re-check the banner |
| 46 | **Steam Cloud**: the test character and world the builder made in the sandbox are "Cloud save" and sync to the user's real Steam account. | the builder's end note | - | fixed (41de0a2): the builder role: test characters / worlds / saves Local, never Steam Cloud, and a line on them in the end note; `ga-valheim run` says so, `stop` / `doctor` name every Cloud save (Steam userdata/<id>/892970/remote) written since the game started (test; LESSONS valheim-005) |
| 47 | The recording (`ga-valheim rec`) has no sound. | the builder's end note | - | fixed (41de0a2, `:20261030g` images): the game's sound did reach the `rec` sink, but `rec start` grabbed only the screen (no pulse input) in every tool. Now `galab.rec_argv` and ga-sdv also record `rec.monitor` (PCM track); the pulse socket takes anonymous clients; `ga-ea` gives the EA App (it re-starts TS4_x64.exe) the socket (it had /tmp/xdg-runtime: silent too). Checked in each unpacked image: a 440 Hz tone played into `rec` comes out at -21 dB (old recorder: no audio stream). Not yet heard from a real game |
| 48 | `lab sandbox tool -- run` refused Valheim with "Steam is not running" while Steam was signed in: `steam_running` read only the last line of `ga-steam status --json`, which is indented over many lines (the last line is `}`), so it was always "not running". The #43 test used a one-line fake. | the refusal right after `lab login steam` | ~5 min | fixed: the whole output is parsed (as loginflow.jsn does); the test uses ga-steam's indented output, Steam up and down |
| 49 | Valheim 1.0 has **no 「Cloud save」 tick** when you create a character or a world: both are Cloud saves (#46's "untick Cloud save" could not be followed). Manage saves > Move to local works, but the character's `_backup_auto` copy stays in the Cloud (`doctor` still named it) until it is removed there (expand the row, select it, Remove). | `doctor` `cloud_saves_since_start` | ~5 min | fixed: builder role, `ga-valheim` help / run / stop text (in the `:20261031a` Valheim image, 656e75a), LESSONS valheim-005: create, then Move to local at once, Remove the backup copy |
| 50 | **The shared Steam home volume at another HOME**: Civ VI (pulled image, `--user`: `/sandbox/home`) after Valheim had set up `ga-steam-home` at `/home/player`: Steam's links in the volume (`~/.steam/root` -> `/home/player/...`) led nowhere and the login stopped on "~/.steam belongs to root". A user hits it when one game's image is pulled and another's built here (`--build`), or after a rebuild. | login refusal | ~15 min | fixed: `up` reads `.steam/root` in the volume (`steam_volume_home`, as root read-only: the volume's HOME is 0750 for her uid) and mounts it at that HOME; HOME is set whenever the Steam home is given, also without `--user` (test) |
| 51 | After #50's re-created sandbox, the login still stopped at once: `/sandbox/logs/steam.log` (the project volume, kept across re-creation) had the old 「Permission denied」 and the watchdog matched it in phase "check", before this flow had started Steam. | login refusal | ~5 min | fixed: `steam_home_not_writable` only in start / updating / login (test) |
| 52 | **New store volumes not writable with `--user`** (a pulled uid-1000 image on a machine where she is not uid 1000): the own sandbox of The Sims 4 made a new `ga-ea`, root's (its mount point is not in the image), and `lab login ea` failed at once on `/sandbox/ea/dl` (PermissionError). Same for `ga-mc-*` and, on a new machine, the Steam volumes (they would get the image's uid 1000). Never seen before because every earlier run reused volumes made by gamebench (#40's E2E too). | traceback of `ga-ea fetch` | ~10 min | fixed: `up` checks each store volume of the source before the sandbox starts and `chown -R`s it to her uid when its top is not hers (`own_store_volumes`, test). Here the old `ga-sims4` volume held the EA App + The Sims 4 (29 GB, gamebench layout) and only 14 GB were free: `ga-ea` re-created as a bind volume to its `ea/` folder (test host only) |
| 53 | **No sound at all in EA / Microsoft / folder sandboxes run with `--user`**: HOME=/sandbox/home is the image's (uid 1000, mode 1777) and PulseAudio refuses a HOME that is not the user's ("Home directory not accessible: Permission denied", pulse.log), so the game had no sound device and `rec` wrote no audio track. Steam games were fine (HOME is the Steam volume, hers). #47's check ran as uid 1000. | `rec` .mkv with only `mjpeg,video`; `pactl`: connection refused | ~15 min | fixed: `own_store_volumes` also gives `/sandbox/home` of the project volume to her uid before the sandbox starts (mounted at /sandbox, so a new volume is still filled from the image; test). Checked here: pulse up, one sink-input from TS4_x64.exe (started again by the EA App with `PULSE_SERVER`), `rec` 15 s: `pcm_s16le` at -34 dB (menu music) |
| 54 | Right after she signed in to the EA App, `tool -- run` said "the game exited": the EA App had not loaded her library yet and The Sims 4's launcher (TS4_Launcher_x64.exe) stayed on its own 「Sign in with your EA Account to activate」 window ("DisplayName field missing from registry."). I took one screenshot of it (empty fields) before seeing what it was: ga-ea does not report it as a sign-in window. Killing the launcher (its pid) and `run` a minute later started TS4_x64.exe normally. | `ga-ea status` windows | ~10 min | fixed: `lab sandbox shot`, `tool -- shot` and `tool -- rec start` refuse (exit 4) while a store sign-in window is open, for EA also while any window is neither the EA App's nor the game's (test; builder role). Image side (in the `:20261031a` Sims 4 image, 656e75a): when only TS4_Launcher_x64.exe is left and TS4_x64.exe never came, `ga-sims4 run` closes the launcher (its pids), waits 60 s for the library and tries once more (test) |
| 55 | **`up` kept the old image after `git pull` brought new digests** (sims4 `:20261031a`): it only checked that `gameanything-lab-sims4` existed, so the sandbox kept running the 20261030g image. | `docker images --digests`, `docker inspect ga-sims4` | ~5 min | fixed: `image_state` compares the local image with `sandbox.PUBLISHED` (an image built here, without registry digests, is kept); an old pulled one is pulled again, the sandbox re-created on it (volumes kept) and the old image removed. Checked: `up` pulled 3031be7b, re-created ga-sims4, disk use unchanged (test) |
| 56 | **Every own-sandbox EA login ran into its timeout, and one stall screenshot was taken while the EA sign-in window was open**: `lab login ea` gave the watchdog `GA_EA_HOME` of the host (unset on her machine), so it looked for EADesktop.log under `~/.steam/debian-installation`: never "signed in" (the app was, 3 s after start: `ga-ea status` said so) and never "sign-in window open". The 01:43 screenshot (before she was asked to sign in, so empty fields) was deleted unopened. | the flow's "not a situation I know" while `ga-ea status` said signed in; DesktopFSM times in EADesktop.log | ~30 min | fixed: `loginflow.ea_home()` = GA_EA_HOME or `/sandbox/ea` (ga-ea's own default); the snapshot counts an unreadable private-state log as private (no screenshot). Checked: `lab login ea` "Signed in to EA" 14 s after the app started (test) |
| 57 | **A Content Patcher content pack could not be installed into her sandbox**: the builder role says Stardew content should be a content pack, but `lab sandbox build` (= `native build --install` in the sandbox, the builder's only way in) refused it: "no .cs files (a content pack needs no build: run gameanything native install)", a command the builder cannot run in the sandbox | Stardew's `build` stages a folder without .cs whose manifest.json has `ContentPackFor` as it is (no dotnet, no SMAPI needed), so `--install` installs it; warns when the framework is not in Mods/ or a Content Patcher pack has no content.json; the CLI prints "content pack for …: nothing to compile" (tests/test_native_mac.py). The sandbox runs the image's own gameanything, so the image side ships in **stardew `:20261102a`** (sha256:45bc1cd4cd51…, 31120bb; checked in a chroot of the image as uid 1000 / 1004). A folder named `[CP] Name` (Content Patcher's usual style) was still refused by the mod-name rule; her decision 2026-11-02: Stardew mod names may have `[ ]` (Stardew.name_re; native at once, in the sandbox from the next stardew image) | fixed; live in :20261102a on plain Docker (2026-11-02) |
| 58 | **The old image stayed on disk after `up` pulled a newer one**: the sandbox was down before `up` (the usual case after `git pull`), so no container ran the old image and #55's `docker image rm` never ran: stardew f6727fe3 stayed next to 45bc1cd4, 2.2 GB of 11 GB free | `up` remembers the image the tag named before the pull and removes it after the update (docker refuses while a container uses it) | fixed |

## Timings

| Step | Time |
|---|---|
| `gameanything setup guide --mode sandbox` (detection) | 0.37 s |
| `gameanything lab setup --yes` (ghcr pull of m2w-lab-base 1.54 GB, lab.env, pool.yaml) | 29 s |
| `gameanything lab setup --image stardew --steam` (local build, first time, nothing cached) | 6 min 21 s, image 3.31 GB, built for uid 1004 |
| the same after the install-steam.sh fix (COPY changed: no cache) | 6 min 12 s |
| `gameanything lab setup --image minecraft` (local build) | 4 min 47 s, image 2.29 GB |
| Steam first start -> sign-in window (`lab login steam`, local disk; Debian notice clicked by the watchdog; two update rounds) | 2 min 23 s |
| sign-in window -> signed in (Wenyi typed, Steam Guard) | about 7 min (her pace) |

## Stardew Valley (Steam inside the sandbox)

Namespace probe `docker run --rm --entrypoint "" <flags> gameanything-lab-stardew-steam unshare --user --map-root-user --mount true`:

| Flags | Result |
|---|---|
| Docker defaults | `unshare failed: Operation not permitted` |
| + seccomp=seccomp-steam.json | `cannot change root filesystem propagation: Permission denied` |
| + apparmor=unconfined (diagnostic only) | ok |
| + apparmor=gameanything-steam (the u2204 profile, loaded by Wenyi with sudo) | ok: the minimum on this host |

The exact `docker run` (no `--privileged`, no capability; `--memory 16g` added: a shared host):

```
docker volume create ga-steam-home; docker volume create ga-steam-games
docker run -d --name ga-stardew-steam -p 127.0.0.1:6080:6080 --shm-size 1g --memory 16g \
  --security-opt seccomp=$PWD/lab/images/common/security/seccomp-steam.json --security-opt apparmor=gameanything-steam \
  -v ga-steam-home:/home/player -v ga-steam-games:/home/player/.steam/debian-installation/steamapps \
  -v ga-stardew:/sandbox gameanything-lab-stardew-steam
```

Up in 5 s; inside: uid 1004 (= the host user), /dev/shm 1.0 GB, viewer HTTP 200 on 127.0.0.1:6080.

Full flow, 2026-10-29 (times on this host, local disk):

| Step | Result | Time |
|---|---|---|
| `lab login steam --container ga-stardew-steam --app 413150` | Debian notice clicked by the watchdog (known entry), two self-update rounds, sign-in window | 2 min 23 s |
| sign-in | Wenyi typed in the viewer, Steam Guard; nothing read or captured | ~7 min (her pace) |
| `lab login steam ... --install` | Install dialog (Wenyi clicked Install), depot download 508 MB | 3 min 47 s incl. her click |
| downloaded folder | 686 MB, `StardewValley` + `libcoreclr.so`, no .exe: the Linux build | - |
| `ga-sdv layer` (GA_GAME = the steamapps folder) | 226 entries, Content linked read-only, SMAPI 4.5.2 | 2.3 s |
| `gameanything native build --game stardew --install .../M2WSmoke` | built + installed, saves backed up first | 6 s |
| `ga-sdv run` | SMAPI "Loaded 3 mods", `[M2W-smoke] loaded`, window 1280x720 | 8 s |
| new farm (clicked for Wenyi at her request: 「你帮我做」) | M2W / M2WTest, Skip Intro; save created and loaded | ~5 s |
| HUD | "[M2W-smoke] hello from GameAnything", 8-11 s into the clip | - |
| proof | <test home>/ga-sandbox-test/stardew/: proof-hud-hello.png, clip-30s.mp4, title-menu.png, smapi-tail.log | - |
| `ga-sdv stop` | game stopped | 1 s |

Reuse: `docker rm` the sandbox, `docker run` again with the same three volumes, `lab login steam --app 413150 --install`: signed in by
itself with the saved login in 13 s (no password, no code), "Stardew Valley 已经装好了" (nothing downloaded); /sandbox still has the
layer, SMAPI, M2WSmoke and the save.

Read-only mount (the "I have the game installed" path): the downloaded folder copied to the host (685 MB, 4 s), started with the
argv of `sandbox.run_argv` (port changed to 127.0.0.1, #7): `touch /game/x` -> Read-only file system; `ga-sdv doctor` game_build linux;
layer + smoke mod + `ga-sdv run` + a new farm (save in the sandbox): 23 s to the game. sha256 of the host folder (metadata listing and
contents) identical before and after: 7f31e4ee... / 0018c243... (stardew/sha-before.txt, sha-after.txt).

Driving the game with xdotool: a plain `xdotool click 1` on the title menu only hovers (MonoGame misses a press+release in one
event batch); `mousedown`, 0.15 s, `mouseup` works. Stardew's SaveLoaded HUD message shows for ~4 s: start `ga-sdv rec` before OK.


## Minecraft: Java Edition (Microsoft download, offline play, GPU)

The exact `docker run` (as the docs, viewer on 127.0.0.1; `GA_GAME` = the downloaded copy, no .minecraft on this host):

```
docker run -d --name ga-mc -p 127.0.0.1:6080:6080 --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all \
  -e GA_GAME=/sandbox/minecraft -v ga-mc:/sandbox gameanything-lab-minecraft
```

| Step | Result | Time |
|---|---|---|
| sandbox up | uid 1004, 8 L40S visible, viewer 200 | 4 s |
| `lab login microsoft --container ga-mc` | code shown; Wenyi signed in on her own device; "Minecraft: Java Edition 在你的账号里" (game_minecraft, product_minecraft) | 63 s |
| token files | /sandbox/account/microsoft.json and minecraft.json: mode 600, owner player (contents not read) | - |
| `ga-mc download` | 26.3 + Fabric 0.19.5 + Fabric API 0.162.0, every hash checked, 710 MB (assets 5147 files 23 s) | 28 s |
| `ga-mc layer` / `native build --install M2WSmoke` | linked versions, libraries, runtime; mod built | 1 s / 2 s |
| `ga-mc run` | "Loading 50 mods" with m2wsmoke, `[M2W-smoke] loaded`; `nvidia-smi pmon`: java on GPU 0, type G | 17 s |
| first world | Singleplayer > Create New World (clicked; no login involved) | 12 s to "Player joined" |
| chat | "[M2W-smoke] hello from GameAnything" | - |
| proof | <test home>/ga-sandbox-test/minecraft/: proof-chat-hello.png, clip-40s.mp4, title-menu.png, latest-log-excerpt.txt | - |
| reuse (container removed, same volume) | `account status --recheck` from the saved token, no sign-in; `download` re-checked, fetched nothing (1 s); `run --world "New World"`: hello in chat | 36 s in all |
| read-only mount + 0600 world | the download (710 MB) and the world copied to the host, owner 1004, level.dat 0600; `-v game:/game:ro -v inst:/saves:ro`; writes to both refused; world loaded (the image's uid = the host uid); after #13, hello in chat. sha256 of both folders identical before and after (minecraft/sha-before.txt, sha-after.txt) | 95 s first run |

## Slay the Spire (2026-10-30, image built here from main 678f3ca, game from the in-sandbox Steam download)

```
docker run -d --name ga-sts -p 127.0.0.1:6080:6080 --memory 16g \
  --mount type=volume,src=ga-steam-games,dst=/game,volume-subpath=common/SlayTheSpire,readonly \
  --mount type=volume,src=ga-steam-games,dst=/workshop,volume-subpath=workshop/content/646570,readonly \
  -v ga-sts:/sandbox gameanything-lab-sts
```

| Step | Result | Time |
|---|---|---|
| build base, java, sts (`docker build`, PLAYER_UID 1004) | 3.11 GB image; `/opt/gameanything`, `/game`, `/usr/local/lib/gameanything` 755 (the umask fix, #17); `ga-steam status` works as the player | 353 s + 63 s + 191 s |
| ModTheSpire / BaseMod | Wenyi's account already subscribed to both (Workshop pages showed "Subscribed", nothing clicked); Steam had them in workshop/content/646570 | Steam auto-login 8 s |
| `ga-sts doctor` | linux build, game read-only, ModTheSpire + BaseMod from /workshop | 6 s up |
| `ga-sts layer` / `native build --install M2WSmoke` | layer (desktop-1.0.jar, jre linked); mod built and installed | 0 s / 2 s |
| `ga-sts run` | ModTheSpire 3.30.3, basemod 5.56.0 + m2wsmoke, `[M2W-smoke] loaded`, main menu; screenshot "[M2W-smoke] hello from GameAnything", "ModTheSpire 3.30.3 - 2 mods"; Mods list shows BaseMod + M2W smoke test | 12 s |
| reuse (container removed, same ga-sts volume) | `ga-sts run`, layer kept, hello again | 16 s in all |
| read-only | `touch /game/x`: Read-only file system; sha256 of the game folder (309 files, 548 MB) identical before and after (sts/sha-before.txt, sha-after.txt) | - |
| proof | <test home>/ga-sandbox-test/sts/: title-menu.png, mods-frame.png, clip-30s.mp4 | - |

The Steam library in ga-steam-games now also has (Install clicked for Wenyi, owned): Terraria 105600, tModLoader 1281930, Valheim 892970,
Overcooked! 2 728880, Kerbal Space Program 220200.

## Kerbal Space Program (2026-10-30, image built here, game from the in-sandbox Steam download)

```
docker run -d --name ga-ksp -p 127.0.0.1:6080:6080 --memory 16g --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all \
  --mount "type=volume,src=ga-steam-games,dst=/game,volume-subpath=common/Kerbal Space Program,readonly" \
  -v ga-ksp:/sandbox gameanything-lab-ksp
```

| Step | Result | Time |
|---|---|---|
| build steam, dotnet (shared with Terraria, Valheim, Overcooked 2), ksp | | 162 s + 86 s, ksp 43 s |
| download (Install clicked for Wenyi) | 4.64 GB to install; KSP 1.12.5 Linux | a few minutes, with Valheim, Terraria, Overcooked 2 in the queue (245 Mbit/s) |
| `ga-ksp doctor` | linux build, read-only, Xorg on the NVIDIA GPU | 6 s up |
| `ga-ksp layer` / `native build --install M2WSmoke` | KSP_Data linked, Squad copied; mod built | 2 s / 5 s |
| `ga-ksp run` | `[M2W-smoke] loaded`, MAINMENU; screen "M2W smoke: plugin loaded"; `nvidia-smi pmon`: KSP.x86_64 on GPU 0, type G | 46 s |
| reuse (container removed, same volume) | smoke loaded again | 51 s in all |
| read-only, sha256 | `touch /game/x` refused; 3380 files, 4.7 GB, identical before and after (ksp/sha-*.txt) | - |
| proof | <test home>/ga-sandbox-test/ksp/: title-menu.png, clip-20s.mp4 | - |

## Terraria (tModLoader), Valheim, Overcooked! 2 (2026-10-30, images built here, games from the in-sandbox Steam download)

The three need Steam running in the sandbox (SteamAPI); it logged in from the saved login (ga-steam-home) in under 10 s each time.
Base, steam (162 s), dotnet (86 s) built once; each game layer 43-44 s; one game image at a time on the 3-4 GB left on `/`.

```
docker run -d --name ga-<game> -p 127.0.0.1:6080:6080 --shm-size 1g --memory 16g --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all \
  --security-opt seccomp=$PWD/lab/images/common/security/seccomp-steam.json --security-opt apparmor=gameanything-steam \
  -v ga-steam-home:/home/player -v ga-steam-games:/home/player/.steam/debian-installation/steamapps \
  --mount "type=volume,src=ga-steam-games,dst=/game,volume-subpath=common/<Valheim | Overcooked! 2>,readonly" \
  -v ga-<game>:/sandbox gameanything-lab-<game>
# Terraria: no /game mount; -e GA_GAME=/home/player/.steam/debian-installation/steamapps/common/tModLoader (the in-sandbox Steam path)
```

| Game | Result | Times |
|---|---|---|
| Terraria 1.4.4.9 + tModLoader v2026.8.3.0 (EULA accepted for Wenyi, #23) | after #24 and #25 (image rebuilt): `[M2W-smoke] loaded`, "Mods using the most RAM: M2WSmoke", Mods List shows "M2W Smoke v0.1 Enabled" (terraria/mods.png, clip-menu-mods.mp4, cropped to the game window: Steam's friends window opened beside it) | first start 6 min (tModLoader downloads .NET 8 itself), then run 21 s; mod build 7 s |
| Valheim (BepInEx 5.4.23.5) | `[M2W-smoke] loaded`, Chainloader complete, banner "M2W smoke: plugin loaded" over the intro; valheim.x86_64 on GPU 0 (Xorg); `/game` read-only, sha256 of 986 files / 4.0 GB identical before and after; reuse 20 s | layer 0 s, plugin 4 s, run 4 s |
| Overcooked! 2 (BepInEx 5.4.23.5) | `[M2W-smoke] loaded`, banner on the title screen (overcooked2/menu.png, clip-30s.mp4); Overcooked2.x86 on GPU 0; read-only, sha256 of 610 files / 8.2 GB identical; reuse 23 s | layer + plugin 5 s, run 9 s |

## The re-published images (20261030b, 1406889): Cities: Skylines, Civ VI, The Sims 4 (2026-10-30)

Space on `/`: Wenyi removed another user's unused images (with their OK), 15 GB free; my local images removed first.

| Step | Result | Time |
|---|---|---|
| `lab setup --image cities_skylines` | pulled by digest e1dbc6ca..., tagged; uid 1000 and `--user 1004`: `ga-steam status` works, `find` of unreadable paths prints nothing, `ga-cities doctor` clean | 44 s, 3.39 GB |
| Steam first start, fresh volumes | uid 1000 (HOME /home/player) and `--user 1004 -e HOME=/sandbox/home`: installer Install clicked, sign-in window in both, no Permission denied, no workaround | 2 min 12 s |
| `docker stop` + `docker start` | Xvfb back, viewer 200, `ga-steam status` running False (not the old start's "signed in"), `ga-steam start` -> sign-in window | 8 s + 25 s |
| Cities download | Paradox User Agreement accepted for Wenyi (「帮我点」, `lab consent --click-for-me`); 6.2 GB | ~2 min |
| Cities run (`--user 1004 -e HOME=/home/player`, the existing ga-steam-home, game by volume subpath read-only, GPU) | after #28/#29: smoke mod started a new city, `[M2W-smoke] city loaded (NewGame), money 70000` (cities/city.png, clip-20s.mp4, cropped to the game window); Cities.x64 on GPU 0; reuse 35 s; `/game` read-only; sha256 of 1285 files / 16 GB identical | menu 26 s |
| Civ VI download | Take-Two EULA accepted for Wenyi (「同意 帮我点」); 10.75 GB | ~3 min |
| `docker pull` civ6 by digest | 0.4 GB new (base + steam shared with Cities); uid 1000 / 1004 permission check clean | 8 s |
| Civ VI run | #30 (passwd), #31 (2K agreement, screen); then main menu "Exit to Desktop [M2W-smoke]" (civ6/menu-smoke.png); reuse to the menu ~2.5 min, no agreement again; `/game` read-only, 44102 files / 24 GB (sha-after.txt) | first start 3-6 min |
| `lab setup --image sims4` | pulled, permission check clean as uid 1004, `ga-ea` / `ga-sims4` start | 41 s |
| EA App (`lab login ea --install`, `--user 1004`, no passwd line: Wine ran) | Wine and the app's parts installed by itself; EA User Agreement: Wenyi clicked LET'S GO; she signed in herself (no screenshot); ownership: "The Sims 4 在你的账号里" (managedBy EA, externalSource STEAM did not block) | Wine ~1-2 min |
| download | Library > ... > Download > Download options (26.33 GB) > NEXT > Terms of play: Wenyi clicked DOWNLOAD herself (#32, #33 on the way) | 26 GB in ~3 min |
| first start, mod | game 1.129.39.1030 DX11 on the GPU (all 8 L40S in pmon); after the first start `native build --install M2WSmoke` (Options.ini scriptmodsenabled, saves backed up); main menu with the Mods dialog listing **M2WSmoke** under Script Mods (sims4/menu-mods.png, EA user name masked) | menu ~1.5 min |
| reuse (container removed, same ga-sims4 volume) | EA App signed in by itself in 18 s, game still installed, menu + M2WSmoke again; after #34 `ga-sims4 run` up in 10-12 s (22 s cold) | - |

## The third rebuild (20261030c, 3b2ecb0): Civ VI, Cities, Terraria, The Sims 4 (2026-10-30)

One image at a time (old one removed first); `lab setup --image` itself pulled each (13-18 GB free, no refusal this time).

| Image | Pull | Checks (uid 1004 and 1000) | Run |
|---|---|---|---|
| civ6 | 38 s | passwd/group `-rw-rw-rw-`, `find` empty, `player1004` / `player`, `ensure_account` and `1600x900` in the files | `--user 1004:1004` with **no passwd workaround**: Steam signed in 16 s, game up in 4 s, main menu "Exit to Desktop [M2W-smoke]" (civ6/menu-20261030c-uid1004.png); the screen was 1280x720 (#36) |
| cities | 43 s | same, ready markers in ga-cities | run, stop, run: up in 17 s / 18 s, `[M2W-smoke] enabled`, 0 Cities.x64 left after each stop (#29 fixed) |
| terraria | 43 s | same, `GAMEANYTHING_TERRARIA_USER_DIR=/sandbox/saves`, ScriptCaller in ga-terraria | fresh volume: layer, mod built into /sandbox/saves/Mods (#25 fixed), ScriptCaller watched (#24 fixed); first-start screens (#37); after the fix up in 24 s, M2WSmoke loaded (terraria/menu-20261030c-fresh.png) |
| sims4 | 41 s | same; `--user 1004:1004` gives `player1004 player1004` (3b2ecb0's group fix) | EA App on its sign-in window (#38); after Wenyi signed in: `ga-sims4 run` up in 11 s, main menu, Mods dialog lists M2WSmoke |

## Civ VI and Terraria re-published alone (20261030d, add7bc8) (2026-10-30)

`lab setup --image civ6` refused first at 13.6 GB free (#26 again); the old sims4 image removed, then both pulled one at a time.

| Image | Pull | Checks | Run |
|---|---|---|---|
| civ6 | 39 s | `echo $SCREEN` = `1600x900x24` (#36 fixed); passwd/group `-rw-rw-rw-`, `find` empty, `player1004` / `player` | `--user 1004:1004`: Xorg 1600x900, game window 1024x768, up in 4 s, main menu now with Single Player / Multiplayer and "Exit to Desktop [M2W-smoke]" (civ6/menu-20261030d-1600x900.png). The 2K agreement did not come again (accepted before; a fresh `XDG_DATA_HOME` was not used by the game), so its first-start layout was not re-seen on this image; on 1600x900 it fit when Wenyi accepted it (#31) |
| terraria | 44 s | `grep -c seed_config` = 2; same permission checks | fresh volume: layer wrote config.json (en-US, 2026.8.3.0), mod installed, `run` up in 25 s, "Mod Load Completed", no language picker / Welcome, no click (#37 fixed; terraria/menu-20261030d-fresh.png) |

## The Sims 4 re-published alone (20261030e, c61d40f) (2026-10-30)

Pulled by digest (#39) in 35 s; `grep -c wait_signed_in` = 2; passwd/group `-rw-rw-rw-`, `find` empty, `player1004 player1004` /
`player player`. Cold start on the ga-sims4 volume: the EA App signed in by itself (Wenyi's sign-in of #38 still valid), `ga-sims4 run`
up in 11 s (29 s from `docker run`); two EA promotion screens closed with their X, then the main menu with the Mods dialog listing
M2WSmoke (sims4/menu-mods-20261030e.png, name masked). The sign-in-window stop of #38 is covered by its test; not seen live this time.

## The user's own sandbox without gamebench (`gameanything lab sandbox`, 2026-10-30)

Found while asking "does a Linux user who clones the repo get a working sandbox?": no. Without a gamebench checkout `buildmode` greyed the
sandbox choice ("needs a configured gamebench lab") for every game, and no GameAnything command started a sandbox for the ten images
(the seats, `lab env up` and the plain-Docker drivers are gamebench's, and those drivers exist for Stardew and Minecraft only).
Now: `gameanything lab sandbox up|status|tool|build|shot|input|down --project P` (labsandbox.py) on a local Docker engine with no gamebench
lab, no seats; `buildmode.own_sandbox()` turns the sandbox choice on for every game with an image; agentd starts the builder without a
seat (pooled False) and the builder starts the sandbox itself (roles/builder.md, linux-sandbox.md "Building in the user's own sandbox").
Verified here with `GAMEANYTHING_GAMEBENCH=/nonexistent` and a new project (Valheim, Steam): `up` pulled the image (49 s) and created
ga-valheim (GPU, `--user 1004`, Steam options, the game read-only by volume subpath, 8g); `lab login steam --project` signed in from the
saved login (13 s, owns Valheim); `tool -- layer`; `build <mod in the project>` compiled and installed the smoke plugin in the sandbox;
`tool -- run` up in 4 s; `shot` -> "M2W smoke: plugin loaded"; `input key Escape`; `status`; `down` (container removed, volume kept).

## End to end from a fresh clone (2026-10-30)

`uv tool install git+…` into its own tool dir, a new GAMEANYTHING_HOME, `GAMEANYTHING_GAMEBENCH=/nonexistent`; a feature project for
Valheim (`--mode lab`), `setup guide`, `lab sandbox up --source steam` (here with `--steam-home /home/player` to reuse the test host's Steam
volumes), `gameanything ui` (started agentd). Acting as the user through the page's own requests: the request, the resident's 4 questions,
the understanding card, 「确认需求」, the plan, 「就按这个做」, the go card (1 playtest round). agentd took the build with no seat; the
builder (Claude Code, Sonnet) followed the new role: `lab sandbox` up / tool layer / build / run / shot / input, `lab login steam` when Steam
was down, a new test character and local world, the banner in the world (screenshot: 「你好，GameAnything」 top centre), `tool -- rec`,
`fetch`, `build deliver`; `build check` OK (h264 1280x720, 15.9 s). 22:20 go -> 22:57 done. Hiccups #40-#47.

## All fifteen images rebuilt from base (20261030g, 41de0a2) (2026-10-31)

Valheim first (it shows #44-#47), digest sha256:8c141d97… = `sandbox.PUBLISHED`; the e2e install updated to 0ab3c29 (`uv tool install`).
- Image checks: `fit_output` in galab.py 2; `fc-list :lang=zh` non-empty, `Noto Sans CJK` 5 families, `fc-match sans-serif:lang=zh-cn` =
  Noto Sans CJK SC; `/etc/passwd`, `/etc/group` `-rw-rw-rw-`.
- #44 pass: `xrandr` on :99 = DVI-D-0 1280x720 (the screen), the pointer reaches (1275,718); Valheim's bottom buttons (New, Manage saves,
  Start at y=703) and the main menu's lower-left links click.
- #47 pass: 15 s of the intro with its music, `tool -- rec start/stop`, `fetch`: `mjpeg,video` + `pcm_s16le,audio`, mean -10.9 dB (max 0 dB).
- #46 / #49: a new character (GALocal) and world (galocalworld) were both Cloud saves (no tick); `doctor` named them (and the character's
  `_backup_auto`); Move to local + Remove the backup -> `cloud_saves_since_start []`; in the world, `tool -- stop` printed no warning.
- #45: the banner 「你好，GameAnything」 draws (Valheim's own NotoSerifSC, so the new system fonts were not needed by this mod); the save
  list's Chinese name 怡怡酱 draws too.
- #48 found on the way (`tool -- run` refused with Steam up), fixed.

Civ VI (sha256:5cdb7f38… = PUBLISHED), a new project `civ6-recheck` (`project new --game civ6 --mode lab`, `lab sandbox up --source steam`):
image checks as Valheim's; `xrandr` 1600x900 = the screen, pointer reaches (1595,895); after #50 / #51 the saved login signed in, `layer`,
`run` (4 s), the intro at 1600x900, `rec` 15 s: `pcm_s16le` audio at -21 dB; Escape -> the main menu with the smoke mod's
「Exit to Desktop [M2W-smoke]」; the 2K agreement was accepted before and did not come back (so #31 was not re-tried).

The Sims 4 (sha256:840f0d86… = PUBLISHED), a new project `sims4-recheck` (source ea): image checks as above; `xrandr` 1280x720 = the
screen. `lab login ea` first failed on the new root-owned `ga-ea` (#52); on this host the EA App + game sit in the old gamebench volume
`ga-sims4` (29 GB, 14 GB free), so `ga-ea` became a bind volume to its `ea/`. The saved EA session had run out: Wenyi signed in in the
viewer. The first `run` stopped on the launcher's activation window (#54), the second started the game (11 s, Halloween promo over the main
menu); no sound at all (#53), fixed, then `rec`: audio at -34 dB.

## A real Mac with Docker Desktop (Apple silicon M3, 8 GB, macOS 14.6) (2026-10-30)

Sandbox plan task 12, on Wenyi's Mac. Outcome: **a Mac has no sandbox** (her decision the same evening, 「Mac 只支持本机」); every game is
greyed in the sandbox wizard, native mode is recommended (sandbox.MAC_NO_SANDBOX, mac-sandbox.md).
- Docker Desktop with Rosetta, 6 GB memory, the disk image on an external drive: works (`docker info`: 5.8 GB; an amd64 alpine runs in 2.8 s).
- `gameanything setup guide --mode sandbox`: Mac arm64, Apple silicon, Docker missing / ok, 8 GB: right.
- M1 `lab setup --image X --github-user U --pat-stdin` pulled before the ghcr.io login: "unauthorized", then a local build. Fixed (ecf3cf9).
- M2 that local build ran for arm64 (ports.ubuntu.com, no i386 lists) and failed. Fixed: `--platform linux/amd64` on every pull / build / run.
- Pulls: sts 3.42 GB (71 s), stardew 3.69 GB, terraria 3.6 GB.
- M3 `lab sandbox up` (Slay the Spire, source steam, before the download) failed on the missing `workshop/content/646570` subpath. Fixed (760ec5b).
- M4 port 6080 held by Cursor's port forwarding: the message guessed "another sandbox", and the failed `docker run` left a "Created"
  container that the next `up --port 6081` only re-started with 6080. Fixed (760ec5b): the container is removed, the message says why.
- `up` on 6081: screen and viewer fine.
- M5 **the Steam client crashes**: the ~1 GB self-update finishes, then `qemu: uncaught target signal 11 (Segmentation fault)` ~10 s
  after each start (`logs/console-linux.txt`; started again by hand: the same). The client is 32-bit x86 (`ubuntu12_32/steam`); Rosetta
  for Linux translates 64-bit code only, so it runs under `qemu-i386`. Not fixable here. Watchdog entry `steam_crashes_under_qemu`
  (it was an unknown stall before). Mounting the Mac copy instead does not help (Stardew's Mac build has macOS libraries; Slay the
  Spire's bundled Java is a macOS program, the image's Java 25 is too new for the game).
- Not tested: an Intel Mac (no emulation).

## The Steam client under FEX-Emu on Apple silicon (her Mac, Docker Desktop, linux/arm64) (2026-10-31)

The way out of M5 above (Steam crashing under qemu-i386). A plain arm64 container (ubuntu:24.04, 4 KB pages, 8 cores):
- FEX-Emu 2610 from ppa:fex-emu/fex (package fex-emu-armv8.4) and FEX's Ubuntu 24.04 RootFS (502 MB squashfs, 1.9 GB extracted:
  `FEXRootFSFetcher -x`, no FUSE in a container). F1: the fetcher said "set as default" but wrote no Config.json; FEXBash then said
  "RootFS path doesn't exist": ~/.config/fex-emu/Config.json {"Config":{"RootFS": ...}} (or FEX_ROOTFS) fixes it.
- `FEXBash -c uname -m` = x86_64; the RootFS has /lib/i386-linux-gnu.
- F2: Steam's first start: zenity "Steam now requires user namespaces to be enabled". The seccomp-steam.json profile (the same as the
  x86 Steam images) fixes it (`unshare --user` works then).
- Steam bootstrap (repo.steampowered.com steam_latest.tar.gz) under FEXBash: the 32-bit client updated (~520 MB), restarted and showed
  the sign-in window, no crash (it crashed exactly here under qemu). She signed in in the noVNC viewer.
- F3: `steam.sh steam://install/646570` did not reach the running client; an appmanifest with StateFlags 1026 + a Steam restart did
  (first the Steam Linux Runtime 1391110, then Slay the Spire, 548 MB). F4: restart Steam only after the old client has exited: an
  overlapping start found "Steam is already running" and both ended.
- The Workshop items did not arrive within the test; ModTheSpire.jar / BaseMod.jar were copied from her Mac's Workshop folder (the same
  jars). The game's own x86 JRE under FEX: ModTheSpire patched the game, `[M2W-smoke] loaded`.
- F5: LWJGL 2 needs `xrandr` (it reads the screen modes with the command; without it: ArrayIndexOutOfBoundsException in
  LinuxDisplay.getAvailableDisplayModes) and a sound device (OpenAL: "Could not locate OpenAL library"): x11-xserver-utils and the
  PulseAudio null sink of the lab images; the arm64 xrandr is callable from inside FEX.
- Then the main menu of "Modded Slay the Spire" with "[M2W-smoke] hello from GameAnything" on screen.
- F6: the Steam client showed "Unexpected Transport Error (0x3002)" (its web helper) while the game ran; the game was not affected.
- Stardew Valley (same container, same login; 685 MB downloaded): SMAPI 4.5.2's own installer (`internal/linux/SMAPI.Installer
  --install --game-path ... --no-prompt`) ran under FEX; `./StardewModdingAPI --no-terminal`: "Loaded 3 mods", `[M2W-smoke] loaded`,
  the title screen (NEW / LOAD / Co-op / EXIT). Pass.
- tModLoader (170 MB + Terraria 843 MB): its start script downloads .NET 8 with Microsoft's dotnet-install (x64, under FEX: fine).
  F7: the .NET 8 game then spun at ~100 % CPU after 7 log lines for 40 min; with `DOTNET_EnableWriteXorExecute=0` (W^X off: the
  double-mapped JIT memory of .NET 7+) it went on to Steam, OpenGL (llvmpipe) and audio. Stardew's SMAPI (.NET 6) did not need it.
  F8: a fresh save folder opens on "Select language" (the lab images seed config.json with Language + LastLaunchedTModLoaderVersion);
  clicks are slow to show under FEX (the frame lags seconds). F9: the game then exited: Natives.log full of "IPC call to
  IClientNetworking::IsP2PPacketAvailable returned failure code 2", the Steam client's IPC failing (the same client showed
  "Unexpected Transport Error" before) while the Mac swapped ~8 GB (6 GB Docker VM on an 8 GB Mac).
  With a clean Steam and NO mods (enabled.json []), tModLoader reached its main menu under FEX ("Mod Load Completed", the menu on
  screen): tModLoader itself runs. With the smoke mod: once a native crash right after "Finding Mods..." ("Failed writing minidump",
  while Steam's IPC was failing), once tModLoader's own error box "Failed to load asset Fonts\Death_Text" (a vanilla Terraria font;
  its first start had been renaming wrong-cased assets and was stopped mid-way several times): verify Terraria's files and try again.
  Not settled: Terraria + the smoke mod under FEX.
  Settled the next day (2026-10-31, same container, after `docker start`): tModLoader (.NET 8) is UNSTABLE under FEX, mods or not.
  F10: the first Steam start after `docker start` sat idle 8 min, logged off, no window (CPU ~0, nothing in console-linux.txt after
  the launcher service); stopping the client by its exact pids and starting it again: logged on in 40 s.
  Then 4 more starts: with the smoke mod it found and sandboxed M2WSmoke and died after "JITModsAsync completed" (Natives.log: "Stack
  overflow.", "Failed writing minidump"); with DOTNET_DefaultStackSize=1000000 it died during "Finding Mods..."; without mods it died
  at once (Fatal error: System.AccessViolationException in Microsoft.Xna.Framework.Content.LzxDecoder.Decompress) and once with
  "Failed to load asset Fonts/Item_Stack". No OOM kill (/proc/vmstat oom_kill 0). Death_Text.xnb hashed the same three times in a
  row and had loaded fine in the 16:09 start: the files are intact, .NET 8 computes wrong under FEX (likely its SIMD code; not tried:
  DOTNET_EnableHWIntrinsic=0). Tally: without mods 1 of 3 starts reached the menu, with the smoke mod 0 of 4. Her call: offer it in the
  wizard anyway, with the warning (sandbox.FEX_NOTE). Not the external drive: Slay the Spire and Stardew ran from the same disk image.
- The prototype is lab/images/fex/ (Dockerfile, install-fex.sh, ga-fex-up).
- Wired in on 2026-10-31 (her go-ahead, 「把 FEX 镜像接进向导」), experimental, Apple silicon + the three 2D Steam games only:
  - the wizard (sandbox.sources) offers the Steam download after native mode for Stardew, Slay the Spire and Terraria on Apple
    silicon (sandbox.FEX_GAMES, MAC_FEX); 3D games, Minecraft and The Sims stay native only; an Intel Mac is greyed (not tested);
  - sandbox.PLATFORM = host_platform(): linux/arm64 on an ARM computer (GAMEANYTHING_PLATFORM overrides). `lab setup --image` never
    pulls there (no published arm64 images): it builds the usual chain for arm64 and refuses the games outside FEX_GAMES;
  - install-steam.sh hands over to install-steam-fex.sh on aarch64: FEX + RootFS + the Steam bootstrap, /usr/games/steam = steam.sh
    under FEXBash in Ubuntu's ~/.steam/debian-installation layout (what ga-steam reads), `ga-x86` = FEX with FEX_ROOTFS and
    DOTNET_EnableWriteXorExecute=0 (F1, F7); the dotnet / java layers stay native arm64 (the mod builds);
  - the game tools start the game through it (galab.x86 for ga-sts and ga-terraria; ga-sdv also runs SMAPI's installer through it);
  - ga-steam install under FEX writes the app's manifest (StateFlags 1026) and restarts Steam (F3, F4); tModLoader also queues Terraria;
  - a FEX sandbox gets --memory 5g (Steam + game took ~3 GB).
  - Checked on her Mac the same day: `labdocker.pull_images(["slay_the_spire"])` printed "no published arm64 images, building it here"
    and built base (cached) -> java -> sts for linux/arm64 (the sts layer ran `ga_need steam` -> install-steam-fex.sh), 5.5 GB. A
    container of it: layers base, fex, gameanything, java, steam; `ga-sts doctor` fine (Xvfb, viewer); `ga-steam start` -> the client
    came up under FEX through /usr/games/steam and showed the sign-in window in ~2 min; `ga-steam status`: login_window True,
    login_state WaitingForCredentials. Not yet run in that image: her sign-in, `ga-steam install` (the manifest path), the game.

## Valheim and The Sims 4 re-published alone (20261031a, 656e75a) (2026-10-31)

The Sims 4 (sha256:3031be7b… = PUBLISHED): `lab setup --image` refused at 12.9 GB free (#26); `lab sandbox up` kept the old image (#55),
fixed, then pulled it and re-created the sandbox; `ga-sims4` has the #54 retry (`only_launcher_left`); `/sandbox/home` hers, pulse up (#53);
the EA App signed in from its saved session (no window; the flow's timeout was #56, fixed); `run` started the game at once (the #54 retry
was not needed this time, so not seen live); `rec` 15 s: audio -35 dB. Valheim (sha256:b84ae659…): the help, `run` and `stop` texts of #49;
`lab login steam` from the saved login, `run` printed "new ones are Cloud saves; right after creating one, Manage saves > Move to local",
`stop` no Cloud-save warning.

## Stardew re-published with Content Patcher 2.9.1 (20261101a, bd340f4) (2026-11-01)

No stardew image here before: `lab sandbox up` on a new project pulled sha256:f6727fe3… (= PUBLISHED), started it with her uid and
the Steam volume's own HOME (#50). `ga-sdv doctor`: `content_patcher_vendor 2.9.1`, `content_patcher None`. `ga-sdv layer`: layer in
2.3 s, then "Content Patcher 2.9.1 built and installed (7.8 s)" offline; no dotnet / compiler process left, /sandbox/tmp empty,
`.ga-layer.json` has `content_patcher`. `layer` again: "already installed" (no build); with Mods/ContentPatcher removed (an older
layer): built again without --force (7.9 s). A content pack (EditData Data/Objects) could not go in through `lab sandbox build` (#57);
with the fixed code copied into the sandbox it installed, and SMAPI logged Content Patcher 2.9.1, "Loaded 1 content packs" and "Content
Patcher edited Data/Objects (for the 'GA Content Patcher Recheck' content pack)". The game was started with `ga-sdv run` directly
(Steam not signed in for this check; only the achievements message).

## Stardew re-published with the content-pack install (20261102a, 31120bb) (2026-11-02)

`lab sandbox up` (the sandbox was down): "a newer published stardew image: pulling it", sha256:45bc1cd4… (= PUBLISHED); the old
image stayed (#58, fixed). `ga-sdv layer` on the existing layer: "Content Patcher 2.9.1 already installed". `lab sandbox build` of the
content pack with the image's own code: "content pack for Pathoschild.ContentPatcher: nothing to compile", installed (#57 live). A
folder named "[CP] GA Recheck" is still refused by this image ("mod 名字不合适"; 7c18766 came after it, as its commit says); with the
repo code copied into the sandbox it installed and SMAPI loaded it ("(CP) GA Recheck", Content Patcher edited Data/Objects).

## Test suite on this host

`python -m pytest -q`: 1004 passed, 25 skipped, 2 failed before and after these changes (test_native_quiet
test_after_launch_runs_detached_and_records_its_result, test_native_valheim test_valheim_install_backs_up_worlds_and_characters):
native mode, unrelated to the sandbox, not touched.
