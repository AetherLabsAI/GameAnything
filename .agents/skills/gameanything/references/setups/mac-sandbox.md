# Setting: Mac, sandbox (Docker Desktop): Apple silicon + the 2D Steam games only, EXPERIMENTAL (FEX); else native mode

**On a Mac, native mode is the recommended mode for every game** (`mac-native.md`). Since 2026-10-31 (her go-ahead, 「把 FEX 镜像接进
向导」) the wizard also offers an **experimental** sandbox on **Apple silicon** for the three 2D Steam games: **Stardew Valley, Slay the
Spire, Terraria**. Everything else stays native only, greyed in the wizard with the reason:
- 3D games and Minecraft 26.x: Docker Desktop's VM has **no GPU** (decided 2026-10-29).
- The Sims 4: 3D, and its sandbox is the Windows build under Wine.
- An Intel Mac: not tested.

How the Apple silicon sandbox works (docs/sandbox-hiccups.md "The Steam client under FEX-Emu", F1-F9): the x86 images under Rosetta
fell to `qemu-i386` for the 32-bit Steam client, which crashed after every self-update (`qemu: uncaught target signal 11`). So on an
ARM computer the images are **built locally for linux/arm64** (there are no published arm64 images): the Steam layer installs FEX-Emu
and its x86 RootFS instead of i386 packages (`lab/images/common/install-steam-fex.sh`), and the game tools start the game under FEX
(`ga-x86`). The mods are still built natively (arm64 .NET SDK / OpenJDK). Tested on her Mac (M3, 8 GB, Docker Desktop with 6 GB):
Steam signs in, downloads and remembers the login; Slay the Spire (ModTheSpire + BaseMod + the smoke mod) and Stardew Valley (SMAPI +
the smoke mod) reached their menus; tModLoader reached its menu without mods (with the smoke mod: see the hiccups page). It is SLOW:
minutes to start a game, the screen lags seconds, and an 8 GB Mac swaps hard; 16 GB is recommended.
- Stardew Valley: `ga-sdv layer` also builds Content Patcher 2.9.1 from the image's pinned source (offline, natively on arm64; not yet tried under FEX on the Mac) into the sandbox's
  own `Mods/`, so content packs load; a failed build is reported and SMAPI C# mods still work (`ga-sdv doctor`: `content_patcher`).

## Checklist
- Game not Stardew / Slay the Spire / Terraria, or an Intel Mac: tell the user in one or two sentences why there is no sandbox (3D /
  Minecraft: no GPU; Intel: not tested), switch the project to native (`gameanything project set-mode <project id> native`), run
  `gameanything setup guide --project "$P"` again and follow mac-native.md. Stop here.
- One of the three on Apple silicon: say that native mode is faster and verified, and that the sandbox is experimental and slow;
  continue only if the user wants the sandbox.
- Docker Desktop running, at least 6 GB of memory for it (Settings > Resources); on an 8 GB Mac close other programs.
- The user (or the builder) runs `gameanything lab setup --image <game>`: it builds the arm64 chain on this Mac (~15 min the first
  time, 4-6 GB; a second game reuses the base and Steam layers). It never pulls on an ARM computer.
- `gameanything lab sandbox up --project "$P" --source steam`, then `gameanything lab login steam --project "$P" --app <APPID> --install`:
  the user signs in in the viewer (`http://localhost:6080/vnc.html`). Under FEX, Steam's `steam://install` does not reach the client:
  ga-steam writes the app's manifest and restarts Steam instead (it says so). Expect the first Steam start to take 5-20 min.
- Look at the sandbox screen after every step (`lab sandbox shot`), at most every ~10 s while waiting: under FEX a dialog can sit there
  for minutes unseen.

The rest of this page is the earlier setup notes, kept for the record.

## Prerequisites
- Docker Desktop for Mac (https://www.docker.com/products/docker-desktop/), the Apple silicon or Intel build for the chip
  (`gameanything setup guide` prints the chip). Start it once and accept its terms.
- macOS recent enough for the current Docker Desktop.
- A Steam account that owns the game (the sandbox downloads the Linux build); Minecraft: the user's own `.minecraft` can be mounted.

## Settings to change (Docker Desktop > Settings; names vary a little between versions)
- General: "Use Virtualization framework" on, and on Apple silicon "Use Rosetta for x86_64/amd64 emulation on Apple Silicon" on.
  Without Rosetta the images run under QEMU, which is much slower.
- Resources > Advanced: Memory 4-6 GB (the 2D games; on an 8 GB Mac not more than 6), CPUs 4 or more, a disk image large enough for the image
  plus the downloaded game.
- Resources > File sharing: the folders to mount (the Minecraft folder `~/Library/Application Support/minecraft`, the project) must be
  under a shared path; `/Users` is shared by default.
- Nothing about the uid: the Mac uid (501, ...) is passed to the build for the user; Docker Desktop's file sharing makes the files
  readable either way.

## How to check
- `gameanything setup guide --project "$P"`: Mac, chip, Docker state, the memory Docker Desktop has, this game's verdict and warnings
  (`emulated`, `mac_no_gpu`, `low_memory`).
- `gameanything lab setup --image <game>` (run by the user or the builder, not by you) pulls the published runtime image (private for now: `docker login ghcr.io` first) or, failing that, builds it locally; it works with Docker
  Desktop on a Mac.
- `gameanything game check <game>`.

## Resources
- Memory: what Docker Desktop is given counts, not the Mac's total (`gameanything setup guide` shows Docker's).
- Emulation on Apple silicon costs speed; 2D games (Stardew, Terraria, Slay the Spire) are the ones to run here.

## Games in this setting
The table assumes Apple silicon with Docker running.
<!-- setup-games:begin (gameanything setup tables --write) -->
| Game | Verdict | Game source | Runtime image | Why |
|---|---|---|---|---|
| Stardew Valley (`stardew`) | available | Steam download in the sandbox | built on this Mac for arm64 (FEX); smoke mod reached the menu under FEX (2026-10-31, the lab/images/fex prototype) | Experimental: log in to your own Steam inside the sandbox and download the Linux build; Steam and the game run under FEX (x86 translated to ARM). |
| Minecraft (`minecraft`) | not available | - | - | Not supported on a Mac: newer Minecraft (26.x) needs a graphics card, and the sandbox on a Mac has none, so the game cannot open its window; use native mode |
| Cities: Skylines (`cities_skylines`) | not available | - | - | Not supported on a Mac: this 3D game needs a graphics card, and the sandbox on a Mac has none; use native mode |
| Slay the Spire (`slay_the_spire`) | available | Steam download in the sandbox | built on this Mac for arm64 (FEX); smoke mod reached the menu under FEX (2026-10-31, the lab/images/fex prototype) | Experimental: log in to your own Steam inside the sandbox and download the Linux build; Steam and the game run under FEX (x86 translated to ARM). |
| Overcooked! 2 (`overcooked2`) | not available | - | - | Not supported on a Mac: this 3D game needs a graphics card, and the sandbox on a Mac has none; use native mode |
| The Sims 4 (`sims4`) | not available | - | - | Not supported on a Mac: this 3D game needs a graphics card, and the sandbox on a Mac has none; use native mode |
| Valheim (`valheim`) | not available | - | - | Not supported on a Mac: this 3D game needs a graphics card, and the sandbox on a Mac has none; use native mode |
| Terraria (`terraria`) | available | Steam download in the sandbox | built on this Mac for arm64 (FEX); UNSTABLE: tModLoader (.NET 8) crashed under FEX in 6 of 7 starts, mods or not (2026-10-31) | Experimental: log in to your own Steam inside the sandbox and download the Linux build; Steam and the game run under FEX (x86 translated to ARM). |
| Sid Meier's Civilization VI (`civ6`) | not available | - | - | Not supported on a Mac: this 3D game needs a graphics card, and the sandbox on a Mac has none; use native mode |
| Kerbal Space Program (`ksp`) | not available | - | - | Not supported on a Mac: this 3D game needs a graphics card, and the sandbox on a Mac has none; use native mode |
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
- Found on a real Mac (Apple silicon, 8 GB, Docker Desktop, 2026-10-30):
  - The disk image (Settings > Resources > Advanced > Disk image location) can live on an external drive; the images are 3.4-3.7 GB
    each. Keep that drive plugged in, or Docker Desktop does not start. The Browse dialog may not list the drive: press Cmd+Shift+G
    and type the path (e.g. /Volumes/<drive>/docker).
  - The images are private on ghcr.io for now: `echo <PAT> | gameanything lab setup --github-user <user> --pat-stdin --image <game>`
    logs in first, then pulls (a pull took 71 s for Slay the Spire). That was the x86 test of 2026-10-30; since 2026-10-31 an Apple
    silicon Mac builds linux/arm64 images itself and never pulls (every build and run says `--platform linux/arm64` there).
  - Port 6080 may be taken by another program (Cursor's port forwarding on her Mac): `lab sandbox up --port 6081` (remembered).
- No GPU in the VM: Minecraft 26.x fails with "no GLX visual"; KSP, Valheim, Cities, Civ VI, Overcooked 2 and Sims 4 would run at
  very low frame rates. So they are not supported in a Mac sandbox (decided 2026-10-29): the wizard greys them with the reason and
  offers native mode.
- The Mac build of a game cannot run in the sandbox (it needs the Linux build); the user's Mac install is greyed out as a source.
- Minecraft: the mounted `.minecraft` lacks the Linux native libraries; the sandbox downloads them once (public, no login).
- Not yet verified: everything on a real Mac (Docker Desktop, Rosetta speed, file sharing of the game folders), and the Steam download
  inside the sandbox on a Mac (it ran in the maintainer's Linux Steam lab).

## Tell the user before launching
- On a Mac the sandbox has no graphics card and (Apple silicon) runs emulated: it is slower than the game on their Mac; for 3D games
  and Minecraft native mode is better.
- How much memory Docker Desktop must have and that Docker Desktop must be running.
- The first Steam start takes 5-20 min (longer emulated) before the sign-in window; they sign in themselves, tick Remember me,
  approve Steam Guard on the phone; the Steam account is busy while it runs (`../sandbox-logins.md`).
- They watch it at `http://localhost:6080/vnc.html`.
