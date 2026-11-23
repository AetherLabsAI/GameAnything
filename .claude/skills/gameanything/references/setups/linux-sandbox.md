# Setting: Linux, sandbox (Docker Engine)

The game runs in a Docker container on the user's own Linux computer. The image holds only the runtime (mod loader, build tools,
virtual screen, browser viewer, recorder, GameAnything); the game comes from the user's own folder, mounted read-only, or from a
download inside the sandbox. Nothing in the user's game folder or saves changes.

## Checklist
- Docker Engine answers: `gameanything setup guide --project "$P"` shows `Docker ok` (missing: see Prerequisites).
- The game has a runtime image (table below); `gameanything lab sandbox up` pulls it when missing (or `gameanything lab setup --image <game>`; `--build` builds it locally). You (the resident) never build images or start containers: the builder starts the sandbox with `gameanything lab sandbox` ("Building in the user's own sandbox").
- 3D games: an NVIDIA GPU with the NVIDIA Container Toolkit; Minecraft 26.x does not start without one.
- Memory: 4 GB for the container of a 2D game, 8 GB for a 3D game; 16 GB in the computer for 3D games.
- Mount the Linux install read-only (the recommended source); the Steam download inside the sandbox is verified 2026-10-29 in the maintainer's Steam lab with Stardew, Terraria + tModLoader, Valheim and Overcooked! 2, and on plain Docker Engine (Ubuntu 22.04, NVIDIA) with Stardew end to end (docs/sandbox-hiccups.md in the repository).
- Store logins and downloads (Steam, Microsoft, EA): read `../sandbox-logins.md` first, then run `gameanything lab login steam|microsoft --project "$P"`; it watches every wait (the setup watchdog). Never wait blindly, never accept a publisher EULA for the user.
- Before the first launch, tell the user what is in "Tell the user before launching".

## Prerequisites
- Docker Engine: `sudo apt install docker.io` (or Docker's own packages), then `sudo usermod -aG docker $USER` and log in again.
  Not running: `sudo systemctl start docker`.
- 3D games: the NVIDIA driver and the NVIDIA Container Toolkit, so that `docker run --gpus all` works. Without a GPU the sandbox uses
  Xvfb with software OpenGL: 2D games work, 3D games are slow, Minecraft 26.x opens no window ("no GLX visual").
- The game itself, Linux build. Steam's default folder: `~/.local/share/Steam/steamapps/common/<Game>`.
- Steam inside the sandbox, on a host with AppArmor: load the Steam profile once with sudo. Ubuntu 24.04+ (AppArmor 4):
  `lab/images/common/security/gameanything-steam.apparmor`; Ubuntu 22.04 (AppArmor 3, "Could not open 'abi/4.0'"):
  `gameanything-steam-u2204.apparmor` (same profile name). `sudo install -m 644 <file> /etc/apparmor.d/gameanything-steam &&
  sudo apparmor_parser -r -W /etc/apparmor.d/gameanything-steam`. Without it Steam's sandbox check fails (`cannot change root
  filesystem propagation: Permission denied`), also with the seccomp profile.
- Disk where Docker keeps IMAGES: Docker Engine 29 with the containerd image store uses `/var/lib/containerd`, often on the root disk
  even when `/var/lib/docker` is a big separate disk. `df -h /var/lib/containerd`; `lab setup --image` stops below 15 GB free there.
  `docker builder prune` frees little there (cache records the images still use); move /var/lib/containerd to the big disk.

## Settings to change
- Nothing in the game. The user's uid is passed to every image build for them (`--build-arg PLAYER_UID=$(id -u)`, done by
  `gameanything lab setup --image`); never ask the user to type it.
- Only on a gamebench lab (not the user's own sandbox): `gameanything lab setup` without `--image` (ghcr.io login, images,
  `~/.config/m2w/lab.env`, game folders, the local seat pool). The user's own sandbox needs none of that: `gameanything lab sandbox up`.
- Before the first build, the user's own agent (not the builder: it cannot sudo) does the one-time sudo steps above (AppArmor for Steam
  games, the docker group, the NVIDIA toolkit), runs `gameanything lab sandbox up --project "$P" --source …` and the store login with
  `--install`, so the builder later only needs `up --project`. `gameanything ui` starts agentd (the builds) by itself.

## How to check
- `gameanything setup guide --project "$P"`: system, Docker state, memory, this game's verdict.
- `gameanything lab sandbox status --project "$P"` (the sandbox, its project, whether the game is mounted, the game tool's doctor).
  `gameanything lab ready` / `lab doctor` are for gamebench labs only.
- Disk: images go where Docker keeps them (`df -h /var/lib/containerd`, about 15 GB free), Steam / EA downloads into volumes
  (`df -h /var/lib/docker`: Valheim ~2 GB, Civ VI ~25 GB, The Sims 4 ~26 GB).
- `gameanything game check <game>`: the game package is valid.
- Inside a running sandbox (builder only): `ga-sdv doctor` / `ga-ksp doctor` / `ga-mc doctor` / `ga-sts doctor` say which build is
  mounted and whether the uid matches.

## Resources
- Tested on 2026-10-29 (a server, `ubuntu:24.04` with the same install script): Slay the Spire 2 CPU / 4 GB, no GPU; KSP and
  Minecraft 4 CPU / 8 GB with one GPU.
- Verified on plain Docker Engine 2026-10-29 (Ubuntu 22.04.5, Docker 27.5 client / 29.5 engine, NVIDIA L40S, Container Toolkit in CDI
  mode): Stardew Valley (Steam download, mounted folder, reuse, read-only mount unchanged by sha256, out of memory) and Minecraft
  (Microsoft download, GPU, reuse, a 0600 world mounted read-only). Measured memory peak: Stardew 1.3-1.5 GB. Below the need
  (`--memory 700m`) the game is stopped by the kernel inside the sandbox only; `ga-sdv` and the watchdog say so.
  2026-10-30, images built on that host from main: Slay the Spire (ModTheSpire + BaseMod from her Workshop subscriptions), KSP (GPU),
  Terraria + tModLoader (EULA accepted by the user), Valheim and Overcooked! 2 (BepInEx, GPU, Steam running): smoke mod on screen,
  reuse, read-only `/game` unchanged by sha256.
- A game downloaded by Steam IN the sandbox lives in the library volume, not a host folder: mount it read-only with a volume subpath
  (Docker Engine 26+), e.g. `--mount "type=volume,src=ga-steam-games,dst=/game,volume-subpath=common/Valheim,readonly"`.
- 3D games and less than 16 GB of memory: the wizard warns (not a block).
- Disk: the image plus the sandbox's own layer of the game (Stardew copies about 150 MB and links `Content/`; KSP copies `GameData`).
- Stardew Valley: `ga-sdv layer` also builds Content Patcher 2.9.1 from the image's pinned source (offline, ~15 s) into the sandbox's
  own `Mods/`, so content packs load; a failed build is reported and SMAPI C# mods still work (`ga-sdv doctor`: `content_patcher`).
- The viewer is `http://localhost:6080/vnc.html`. It is published on 127.0.0.1 only (`-p 127.0.0.1:6080:6080`); on a server the
  user opens an SSH tunnel first (`ssh -L 6080:127.0.0.1:6080 <server>`). Never publish it on all interfaces: the Steam sign-in window is in it.

## Building in the user's own sandbox (`gameanything lab sandbox`, no gamebench)
On the user's own Linux machine there is no lab server, no seat and no broker: the builder starts the sandbox with
`gameanything lab sandbox` (labsandbox.py), which writes the whole `docker run` itself (the pulled image as the user's uid, the GPU for a
3D game, Steam's seccomp / AppArmor / shm, the game read-only, a memory limit, the viewer on 127.0.0.1). Never type `docker run` by hand.
```bash
gameanything lab sandbox up --project "$P" --source steam        # or: --source folder --folder "<her game folder>" [--saves DIR];
                                                                 # sims4: --source ea; minecraft: --source microsoft. Kept in project.yaml.
gameanything lab login steam --project "$P" [--install]          # her sign-in in the viewer (exit 4: she must act); --install downloads
gameanything lab sandbox up --project "$P"                       # again after a first Steam download: the game is then mounted read-only
gameanything lab sandbox tool  --project "$P" -- layer           # the game's own tool: doctor | layer | run | shot | rec | log | stop
gameanything lab sandbox build --project "$P" "$P/5_build/m1/mod" # gameanything native build --install inside (the project is at /project)
gameanything lab sandbox tool  --project "$P" -- run
gameanything lab sandbox shot  --project "$P" "$P/5_build/m1/play/r1.png"
gameanything lab sandbox input --project "$P" key Escape | click 640 360 | type "hello"
gameanything lab sandbox look  --project "$P" /sandbox/game/BepInEx/LogOutput.log -n 80   # read-only, under /sandbox /game /project /workshop
gameanything lab sandbox fetch --project "$P" /sandbox/rec/<file>.mkv "$P/5_build/m1/play/r1.mkv"   # a recording out of the sandbox
gameanything lab sandbox down  --project "$P"                    # stops it, removes the container; volumes stay
```
- One container per game (`ga-<image>`, the name `lab login` finds), labelled with the project; another project's sandbox of the same game
  must be `down` first (`up --replace` does that). Volumes: the project's own `ga-<image>-<project id>` (/sandbox: layer, mods, logs) and the
  store volumes every project shares (`ga-steam-home`, `ga-steam-games`, `ga-ea`, `ga-mc-account`, `ga-mc-game`): a sign-in and a download once.
- Exit codes: 0 ok, 1 failed, 2 usage, 4 needs the user (the AppArmor sudo step, a download, another project's sandbox), 5 not running.
- Verified 2026-10-30 on the test host with no gamebench: Valheim from Steam, image pulled by `up` (49 s), Steam signed in from its saved
  login (13 s), layer, the smoke plugin built and installed in the sandbox, run, "M2W smoke: plugin loaded" in the screenshot.

## The exact `docker run` (verified on plain Docker, 2026-10-29; `lab sandbox up` writes it for you)
```bash
# Stardew with Steam inside (no --privileged, no capability). Tested as gameanything-lab-stardew-steam (the image name before
# the layered images) with --memory 16g; measured peak 1.5 GB, so 4g is the recommendation, not the tested value.
docker volume create ga-steam-home; docker volume create ga-steam-games
docker run -d --name ga-stardew-steam -p 127.0.0.1:6080:6080 --shm-size 1g --memory 4g \
  --security-opt seccomp=$PWD/lab/images/common/security/seccomp-steam.json --security-opt apparmor=gameanything-steam \
  -v ga-steam-home:/home/player -v ga-steam-games:/home/player/.steam/debian-installation/steamapps \
  -v ga-stardew:/sandbox gameanything-lab-stardew
# Minecraft, downloaded with a Microsoft account, GPU
docker run -d --name ga-mc -p 127.0.0.1:6080:6080 --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all \
  -e GA_GAME=/sandbox/minecraft -v ga-mc:/sandbox gameanything-lab-minecraft
# Own folder, read-only (any game): -v "<game folder>":/game:ro [-v "<instance or saves folder>":/saves:ro]
```
On a computer reachable from a network (a server), publish the viewer on `127.0.0.1` only and open it through
`ssh -L 6080:127.0.0.1:6080 <server>`: `-p 6080:6080` puts the sandbox's screen, sign-in windows included, on every interface.

## Games in this setting
<!-- setup-games:begin (gameanything setup tables --write) -->
| Game | Verdict | Game source | Runtime image | Why |
|---|---|---|---|---|
| Stardew Valley (`stardew`) | recommended | own folder, mounted read-only | published, smoke mod tested on plain Docker (2026-10-30) | Uses the game already on your computer: mounted read-only, mods go into the sandbox's own layer, your game and saves stay as they are |
| Minecraft (`minecraft`) | recommended | own folder, mounted read-only | published, smoke mod tested on plain Docker (2026-10-30) | Minecraft's game files (the jar) are the same on every system: your own copy is mounted read-only, your game and saves stay as they are. |
| Cities: Skylines (`cities_skylines`) | recommended | own folder, mounted read-only | published, smoke mod tested on plain Docker (2026-10-30) | Uses the game already on your computer: mounted read-only, mods go into the sandbox's own layer, your game and saves stay as they are |
| Slay the Spire (`slay_the_spire`) | recommended | own folder, mounted read-only | published, smoke mod tested on plain Docker (2026-10-30) | Uses the game already on your computer: mounted read-only, mods go into the sandbox's own layer, your game and saves stay as they are |
| Overcooked! 2 (`overcooked2`) | recommended | own folder, mounted read-only | published, smoke mod tested on plain Docker (2026-10-30) | Uses the game already on your computer: mounted read-only, mods go into the sandbox's own layer, your game and saves stay as they are |
| The Sims 4 (`sims4`) | recommended | EA App download in the sandbox | published, smoke mod tested on plain Docker (2026-10-30) | Log in to your own the EA App inside the sandbox; the game is downloaded once, kept on your computer and reused |
| Valheim (`valheim`) | recommended | own folder, mounted read-only | published, smoke mod tested on plain Docker (2026-10-30) | Uses the game already on your computer: mounted read-only, mods go into the sandbox's own layer, your game and saves stay as they are |
| Terraria (`terraria`) | recommended | own folder, mounted read-only | published, smoke mod tested on plain Docker (2026-10-30) | Uses the game already on your computer: mounted read-only, mods go into the sandbox's own layer, your game and saves stay as they are |
| Sid Meier's Civilization VI (`civ6`) | recommended | own folder, mounted read-only | published, smoke mod tested on plain Docker (2026-10-30) | Uses the game already on your computer: mounted read-only, mods go into the sandbox's own layer, your game and saves stay as they are |
| Kerbal Space Program (`ksp`) | recommended | own folder, mounted read-only | published, smoke mod tested on plain Docker (2026-10-30) | Uses the game already on your computer: mounted read-only, mods go into the sandbox's own layer, your game and saves stay as they are |
| No Man's Sky (`nms`) | not available | - | - | This game is not in the sandbox wizard (use native mode) |
<!-- setup-games:end -->

## Account logins and downloads
Read `../sandbox-logins.md` (the whole file) before the first login. In short:
- `gameanything lab login steam --project "$P" [--app APPID --install]` / `lab login microsoft --project "$P"`; `--json` for you,
  progress lines in the user's language for them; exit 4 = ask the question it printed, 7 = the game is not in that account.
  EA App (The Sims 4): `lab login ea` installs Wine and the EA App, waits for the user's sign-in and checks the game (verified in the lab 10-29; a game **linked from Steam** cannot be downloaded by the EA App: say so). See sandbox-logins.md.
- Normal times: Steam's first start 5-20 min (a ~500 MB self-update), the sign-in 1-6 min with Steam Guard, later starts 30-60 s;
  Microsoft code ~1 min; Minecraft download ~2 min. The watchdog prints a line at least every ~2 min and reports unknown stalls with a
  screenshot path.
- Publisher agreements are the user's decision: Cities: Skylines shows Paradox's User Agreement, Civ VI Take-Two's EULA, tModLoader
  its EULA, the EA App installer EA's User Agreement, The Sims 4's download "Terms of play" (EA + Microsoft VC++ 2015/2019). Tell them
  before; by default they click Accept themselves. Only if they say, for THAT dialog, "agree, click it for me" (ask: 「要我替你点吗？请回复『同意，帮我点』」)
  record `lab consent --app X --yes --click-for-me --words "<their words>"`; the watchdog then clicks it once within 15 min, logged.
- Verify before concluding: a surprising result after a GUI click is first suspected to be a misclick (normalise the window, fresh
  screenshot, check the target, verify the effect); check earlier runs' logs before telling the user something is impossible.
- The user types passwords and codes themselves; nothing they type is read, logged or captured; tokens stay in the sandbox volume.

## Known pitfalls
- A save private to its owner (Minecraft's `level.dat` is 0600) is unreadable when the image's player uid differs. `doctor` warns;
  rebuild with `gameanything lab setup --image <game>` (it passes the uid). A pulled image built for uid 1000 is run with `--user`.
- `ga-* layer` copies the game into the sandbox's volume (an overlay filesystem would need privileges): the first layer takes 20 s
  (Stardew) to a minute (KSP).
- A Windows or Mac `.minecraft` has no Linux native libraries: the sandbox downloads them once from the public Mojang servers (sha1
  checked, no login). Minecraft is played offline with a local player name; no Microsoft login is needed to test mods.
- Processes detached from `docker exec` become zombies when they end; `kill -0` still counts them as alive (KSP lesson). Check the
  process state, not only the pid.
- Steam games keep the user's Steam account busy while the sandbox runs them (one game at a time per account).
- `docker run --gpus all` fails with `failed to fulfil mount request: open /usr/lib/x86_64-linux-gnu/libEGL_nvidia.so.<old version>`:
  the NVIDIA Container Toolkit's CDI spec is from a driver that is no longer installed. `sudo nvidia-ctk cdi generate
  --output=/etc/cdi/nvidia.yaml` (after every driver update).
- Steam in the sandbox on an AppArmor host needs the profile `gameanything-steam`, loaded once with sudo: Ubuntu 24.04 and later
  `lab/images/common/security/gameanything-steam.apparmor`, Ubuntu 22.04 `gameanything-steam-u2204.apparmor` (the 24.04 file fails
  there with "Could not open 'abi/4.0'"). `sandbox.apparmor_load_commands()` prints the right two commands for this host.
- Images built or pulled before 2026-10-30 have no `~/.steam` folders: Steam's first start stops with `ln: failed to create symbolic link
  '/home/player/.steam/steam': Permission denied` (the watchdog knows it): pull again (`gameanything lab setup --image <game>`) or
  rebuild, remove the two new Steam volumes, re-create the sandbox.
- Images built before 2026-10-29 do not survive `docker stop` + `docker start` ("no X display :99"): rebuild, or recreate the
  container with the same volumes (nothing is lost; the logins and games are in the volumes). The published images since 2026-10-30
  (`:20261030c` and later) survive it (tested).
- Verified on plain Docker 2026-10-30 with the re-published images: Cities: Skylines, Civ VI, The Sims 4 (docs/sandbox-hiccups.md #26-#35).
- A pulled image run for another uid (`--user`): Civ VI needs an /etc/passwd line for that uid (images built after 124c14f add it).
  (their images were not built on the test host: its image disk was full; see docs/sandbox-hiccups.md #16).

## Tell the user before launching
- The game runs in a sandbox on their computer; their own game folder and saves are only read, never changed.
- How much memory it takes (above) and that 3D games need the GPU.
- They watch it at `http://localhost:6080/vnc.html`.
- A Steam login inside the sandbox: they sign in themselves in the viewer, tick Remember me, approve Steam Guard on the phone; the
  first start takes 5-20 min before the sign-in window; a Steam game keeps their account busy while it runs (`../sandbox-logins.md`).
