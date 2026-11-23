# Setting: Windows, sandbox (Docker Desktop + WSL 2)

The game runs in a Docker container in Docker Desktop's WSL 2 VM on the user's Windows PC. **Not yet verified on a real Windows PC**
(the images were tested on a Linux server only). The sandbox runs the Linux build of a game, so the user's Windows install can be
mounted only for Minecraft (the jar runs anywhere) and The Sims 4 (the Windows build under Wine).

## Checklist
- Docker Desktop with the WSL 2 engine is running: `gameanything setup guide --project "$P"` shows `Docker ok`.
- Run GameAnything inside the WSL 2 distro (e.g. Ubuntu), not from Windows itself, where possible: the user's uid is then passed for them.
- Give WSL 2 enough memory in `%UserProfile%\.wslconfig` (8 GB for a 3D game, 4 GB for 2D; 16 GB in the PC for 3D games).
- 3D games: an NVIDIA GPU with a current Windows driver (GPU in WSL 2); no GPU = slow 3D, Minecraft 26.x does not start.
- Games with a Linux build: download the Linux build with Steam inside the sandbox (verified 2026-10-29 in the maintainer's Steam lab with Stardew, Terraria + tModLoader, Valheim and Overcooked! 2, not yet on plain Docker; not on Windows yet).
- Store logins and downloads (Steam, Microsoft, EA): read `../sandbox-logins.md` first, then run `gameanything lab login steam|microsoft --project "$P"`; it watches every wait (the setup watchdog). Never wait blindly, never accept a publisher EULA for the user.
- Before the first launch, tell the user what is in "Tell the user before launching".
- Stardew Valley: `ga-sdv layer` also builds Content Patcher 2.9.1 from the image's pinned source (offline, ~15 s) into the sandbox's
  own `Mods/`, so content packs load; a failed build is reported and SMAPI C# mods still work (`ga-sdv doctor`: `content_patcher`).

## Prerequisites
- Windows 10 22H2 or Windows 11 with virtualization on in the firmware (Task Manager > Performance > CPU: "Virtualization: Enabled").
- WSL 2: `wsl --install` in an administrator terminal, reboot, create the Linux user.
- Docker Desktop (https://www.docker.com/products/docker-desktop/) with "Use the WSL 2 based engine" on and, under Resources > WSL
  integration, the distro switched on, so `docker` works inside it.
- 3D games: an NVIDIA GPU and the NVIDIA Windows driver (it provides the GPU inside WSL 2; do not install a Linux NVIDIA driver in the
  distro). AMD and Intel GPUs are not passed to containers.

## Settings to change
- `%UserProfile%\.wslconfig` (Docker Desktop's memory slider does not apply with the WSL 2 engine):
  ```ini
  [wsl2]
  memory=16GB
  processors=4
  ```
  then `wsl --shutdown` and start Docker Desktop again.
- Where GameAnything runs, and so which uid the image gets (`gameanything lab setup --image` does it for the user):
  - inside the WSL distro: the distro uid is passed; files in the distro keep their Linux owner, same as Linux;
  - from Windows itself: nothing is passed (the image keeps uid 1000); drives shared into the VM (`C:\...`) appear as root, mode 0777,
    readable by every uid.
- Keep the project and anything the sandbox writes inside the distro (`~/...`), not under `/mnt/c`: crossing the VM boundary is slow.
  Mounting a game folder from `/mnt/c/...` read-only is fine.
- Minecraft's folder seen from the distro: `/mnt/c/Users/<user>/AppData/Roaming/.minecraft`.

## How to check
- `gameanything setup guide --project "$P"`: Windows or Linux (WSL), Docker state, memory, this game's verdict.
- Inside the distro: `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi` (run by the user) shows the GPU.
- `gameanything lab setup --image <game>` (the user or the builder) pulls the published runtime image (private for now: `docker login ghcr.io` first) or builds it locally; it works with Docker Desktop.
- `gameanything game check <game>`.

## Resources
- WSL 2 takes the memory set in `.wslconfig` while Docker runs; close Docker Desktop to give it back.
- Disk: the WSL 2 virtual disk grows with the image and the downloaded game (and does not shrink by itself).

## Games in this setting
<!-- setup-games:begin (gameanything setup tables --write) -->
| Game | Verdict | Game source | Runtime image | Why |
|---|---|---|---|---|
| Stardew Valley (`stardew`) | recommended | Steam download in the sandbox | published, smoke mod tested on plain Docker (2026-10-30) | Log in to your own Steam inside the sandbox; the game is downloaded once, kept on your computer and reused |
| Minecraft (`minecraft`) | recommended | own folder, mounted read-only | published, smoke mod tested on plain Docker (2026-10-30) | Minecraft's game files (the jar) are the same on every system: your own copy is mounted read-only, your game and saves stay as they are; the first time, the sandbox downloads a few small Linux files (public, no login). |
| Cities: Skylines (`cities_skylines`) | recommended | Steam download in the sandbox | published, smoke mod tested on plain Docker (2026-10-30) | Log in to your own Steam inside the sandbox; the game is downloaded once, kept on your computer and reused |
| Slay the Spire (`slay_the_spire`) | recommended | Steam download in the sandbox | published, smoke mod tested on plain Docker (2026-10-30) | Log in to your own Steam inside the sandbox; the game is downloaded once, kept on your computer and reused |
| Overcooked! 2 (`overcooked2`) | recommended | Steam download in the sandbox | published, smoke mod tested on plain Docker (2026-10-30) | Log in to your own Steam inside the sandbox; the game is downloaded once, kept on your computer and reused |
| The Sims 4 (`sims4`) | recommended | own folder, mounted read-only | published, smoke mod tested on plain Docker (2026-10-30) | Uses the game already on your computer: mounted read-only, mods go into the sandbox's own layer, your game and saves stay as they are |
| Valheim (`valheim`) | recommended | Steam download in the sandbox | published, smoke mod tested on plain Docker (2026-10-30) | Log in to your own Steam inside the sandbox; the game is downloaded once, kept on your computer and reused |
| Terraria (`terraria`) | recommended | Steam download in the sandbox | published, smoke mod tested on plain Docker (2026-10-30) | Log in to your own Steam inside the sandbox; the game is downloaded once, kept on your computer and reused |
| Sid Meier's Civilization VI (`civ6`) | recommended | Steam download in the sandbox | published, smoke mod tested on plain Docker (2026-10-30) | Log in to your own Steam inside the sandbox; the game is downloaded once, kept on your computer and reused |
| Kerbal Space Program (`ksp`) | recommended | Steam download in the sandbox | published, smoke mod tested on plain Docker (2026-10-30) | Log in to your own Steam inside the sandbox; the game is downloaded once, kept on your computer and reused |
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
- The Windows build of a game cannot run in the sandbox (except The Sims 4 under Wine, whose image is not built yet); the user's install
  is greyed out as a source for the Linux-build games.
- Minecraft: the Windows `.minecraft` lacks the Linux native libraries; the sandbox downloads them once (public, no login). Played
  offline with a local player name.
- A uid mismatch (an image built from Windows, then used from the distro, or the reverse): `doctor` warns; rebuild with
  `gameanything lab setup --image <game>` from where GameAnything runs.
- Windows Defender can slow the first build and the game download; Controlled Folder Access can block writes to `Documents`.
- Not yet verified: everything on a real Windows PC (Docker Desktop, WSL 2 GPU in our images, the uid rules above), and the Steam
  download inside the sandbox on Windows (it ran in the maintainer's Linux Steam lab).

## Tell the user before launching
- The game runs in a sandbox on their PC; their own game folder and saves are only read.
- Docker Desktop must be running, and WSL 2 holds the memory set in `.wslconfig` while it runs.
- 3D games need an NVIDIA GPU here; without one they are slow and Minecraft does not start.
- The first Steam start takes 5-20 min before the sign-in window; they sign in themselves, tick Remember me, approve Steam Guard on
  the phone; the Steam account is busy while it runs (`../sandbox-logins.md`).
- They watch it at `http://localhost:6080/vnc.html`.
