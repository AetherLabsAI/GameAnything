# Store logins and downloads in the user's sandbox (Steam, Microsoft, EA)

Read this before any account login, game download or first launch inside a sandbox. Every sandbox setting guide
(`references/setups/*-sandbox.md`) points here. Based on the real runs of 2026-10-29 (Stardew, Terraria + tModLoader, Valheim,
Overcooked! 2 with Steam; Minecraft with a Microsoft account; Cities and Civ VI stopped at their publisher's agreement; the EA App
for The Sims 4 under Wine, verified in the lab the same evening).

## The one command
```
gameanything lab login steam     --project "$P" [--app APPID] [--install] [--json]
gameanything lab login microsoft --project "$P" [--json]
gameanything lab login ea        --project "$P" [--install] [--json]   # The Sims 4: Wine + EA App, sign-in, ownership (verified in the lab 10-29)
gameanything lab login steam     --project "$P" --status # read only: stopped / updating / login_window / signed_in
```
- It finds the sandbox (`--container C`, else `ga-<game>-steam` / `ga-<game>`, `ga-minecraft`), speaks the project's language (`--lang`),
  and runs the setup watchdog on every wait. `--json`: one JSON event per line (`zh` and `en`), the result last.
- Exit codes: 0 signed in (and owned when checked), 4 the user must act (the question is in the output: say it to the user word for
  word), 5 the sandbox is not running, 6 not verified / no Steam layer, 7 **not owned** (say so plainly), 8 timeout.
- Inside the sandbox the same pieces: `ga-steam install APPID --wait`, `ga-steam app APPID --watch`, `ga-steam wait`, `ga-steam owns`,
  `ga-steam shader-off`; `ga-mc account login|status --recheck`, `ga-mc download` (a progress line at least every ~2 min).
- Residents never start a login, Steam or a sandbox: only `--status`. The user's own agent (or a builder) runs the login.

## Use the watchdog, never wait blindly
- Never `sleep` in a loop waiting for Steam / a code / a download. The command (or `ga-steam ... --wait`) polls inside the sandbox,
  and when nothing changes for ~60 s it snapshots windows, processes, log tails and a screenshot and matches them against the known
  situations (`gameanything/hiccups.py`, 25 entries). It acts (a safe click, a Steam restart), tells the user, or stops and asks.
- An unknown stall: it tells the user what it sees, with the screenshot path. It is never silent more than ~2 minutes.
- Read state inside the sandbox only (docker exec): processes, windows, `logs/steamui_login.txt` (`WaitingForCredentials` = the
  sign-in window is up even when xdotool sees no window), `webhelper.txt` (`DesktopLoginWindow`), `connection_log.txt`
  (`[Logged On`), the account folder. Never trust host-side copies through a network disk (JuiceFS served stale files).
- Pass on every line it prints in the user's language; on exit 4 ask exactly the question it printed and wait for the answer.

## What to tell the user before each step, and the normal timings
| Step | Tell the user first | Normal time |
|---|---|---|
| Steam, first start | "Steam updates itself the first time (about 500 MB, usually 5-20 min); the sign-in window comes after that; nothing to click yet." | 5-20 min (about 20 on a network disk; two extract rounds) |
| Steam sign-in | "Sign in yourself in the viewer (URL); I cannot see what you type. Tick **Remember me**. Keep your phone ready for **Steam Guard**." | 1-6 min |
| Steam, later starts | "Signing in with the saved login, nothing to type." | 30-60 s |
| Steam download | "Steam may first reserve disk space (0 bytes for a while is normal)." Publisher agreement: see below. | Stardew 676 MB ~3 min, Valheim 4 GB ~6 min on a local disk; a network disk adds a long "installing files" |
| Microsoft (Minecraft) | "Open microsoft.com/link on your own phone or computer, enter the code, sign in with the account that bought Minecraft. Nothing is typed in the sandbox." A code expires after 15 min; a new one comes by itself. | ~1 min |
| Minecraft download | "About 700 MB, 5000+ small files, every file hash-checked." | ~2 min |
| Minecraft, first world | A fresh download has no world: "click Back to World List, then Create New World, once". | 10 s |
| EA App, first time | "Installing Wine and what the EA App needs (about 1-2 min, ~300 MB). The installer's first page is **EA's User Agreement**: your decision, you click LET'S GO yourself." | Wine 72 s; the app installs in ~20 s after LET'S GO |
| EA sign-in | "Sign in yourself in the viewer (URL) with the EA account that owns The Sims 4; you type e-mail, password and any e-mail / phone code; tick **Remember me**." | 1-5 min (3.5 min on 10-29) |
| EA App, later starts | "Signing in with the saved login, nothing to type." | ~30 s (32 s on 10-29) |
| EA ownership | Library > The Sims 4 tile > "..." > **Download** opens EA's own "Download options" (install folder, language, 26.33 GB). A linked Steam account (`gameStatus.externalSource: STEAM`) does NOT block it. `lab login ea` stops with **exit 9** (`other_store`, `external_source`, `external_store`, `next_command`) only on entitlement data saying another store MANAGES the game (`managedBy` != EA), never on a click outcome. | seconds |
| EA download | After NEXT: **"Terms of play"** (EA User Agreement + Microsoft VC++ 2015 and 2019 Runtime Agreements); DOWNLOAD = agreeing: see the agreement rule below. Progress: gameStatus installing -> installed (the folder size is useless: files are preallocated). | 26.3 GB in ~4.5 min (10-29, local disk) |
| The Sims 4, first start | "Close the promos (X, top right) and the info box; the Mods dialog lists the mods." The game shows the EA user name at the top right: mask it in any shared picture. | ~40 s to the menu |

## Publisher agreements (EULA): always the user's decision
- **By default the user clicks a licence, EULA or user agreement themselves**, even when they agreed earlier. The watchdog stops
  (exit 4) and asks, quoting the publisher and the URL; the user reads it and clicks Accept (or Cancel) in the viewer.
- **Exception (Wenyi, 2026-10-29): "agree, click it for me".** When the user says, in the moment and for THAT dialog, that they agree
  and want you to click, ask exactly: 「要我替你点吗？请回复『同意，帮我点』」 / "Shall I click it for you? Reply 'agree, click it for me'".
  On that reply record `gameanything lab consent --app <APPID|ea|ea_ts4_terms> --project "$P" --yes --click-for-me --words "<their
  exact words>"`. The watchdog then clicks that agreement's button ONCE, only if the consent is for the same agreement and at most 15
  min old, and logs a screenshot of the dialog plus the consent record (`accept-*.png/json` in the evidence folder). A plain or older
  yes never authorises a click; an agreement entry is never `kind: auto`. Steam's agreement dialogs have no click script yet: the user
  clicks those.
- When the user says yes in their own words, record it: `gameanything lab consent --app APPID --project "$P" --yes --note "<where she
  said it>"`. A recorded yes only changes the words ("you agreed on DATE, please click Accept yourself"); it never clicks.
- Tell the user BEFORE the install which agreement will show (`lab login steam --app` does it):

| Game | Agreement Steam shows in the Install flow | URL |
|---|---|---|
| Cities: Skylines (255710) | Paradox Interactive User Agreement + Privacy Policy | legal.paradoxplaza.com/eula |
| Sid Meier's Civilization VI (289070) | Take-Two LIMITED SOFTWARE WARRANTY AND LICENSE AGREEMENT (2019-07-13) | take2games.com/eula |
| tModLoader (1281930, for Terraria) | tModLoader EULA | in Steam's dialog |
| EA App itself (The Sims 4) | **EA User Agreement**, the installer's first page: "LET'S GO" accepts it (`lab consent --app ea`) | tos.ea.com/legalapp/WEBTERMS/US/en/PC/ |
| The Sims 4 download in the EA App | **Terms of play**: EA User Agreement + Microsoft Visual C++ 2015 and 2019 Runtime Agreements; DOWNLOAD accepts (`--app ea_ts4_terms`) | links in the dialog |
| Stardew, Terraria, Valheim, Overcooked! 2 | none seen (2026-10-29) | - |

- The Debian "Steam installer" box on the first start is the packager's notice, not a licence: the watchdog clicks Install (Return
  would be Cancel).

## Security rules
- The user types passwords and Steam Guard / Microsoft codes on their own; never read, log, screenshot or ask for them. No screenshot
  is taken while a sign-in window (or Steam's Friends window, which shows friends' names) is open.
- Tokens and login caches stay in the sandbox's data volume only (`/home/player` for Steam, `/sandbox/account/microsoft.json`, 0600).
  Never print, copy or commit them; never `cat` config.vdf, loginusers.vdf, registry.vdf or microsoft.json.
- Screenshots shared outside the sandbox: close the Friends window first; never post one with friends' names.
- Kill only processes you started, by exact pid; never `pkill -f` (a pattern matches your own shell).

## Known situations (the watchdog's table, `gameanything/hiccups.py`)
Steam: mount namespace denied (re-create the sandbox with the seccomp / AppArmor / `--shm-size 1g` options), Debian installer box,
installer cancelled, client downloading / extracting (twice on the first start), the updater window also titled "Steam" (not the
login), the sign-in window, harmless "logon failure" polling noise, the Friends window, network-disk library, publisher EULA,
Steam's Install dialog after `steam://install`, "No licenses" (not owned), reserving space, 0 bps for 5 min (pause/resume, then a
client restart), the slow file commit, a stale manifest (restart), Steam thinking a killed game still runs (restart), shader
pre-caching on before the first launch (turned off while Steam is stopped), shader processing running. Microsoft: code waiting,
code expired, two sign-ins at once, account does not own Java Edition. Minecraft: "Could not find a world". EA App: Wine's Mono
installer box (clicked), EA's User Agreement on the installer's first page (asks), the sign-in form (no screenshot), the sign-in page
failing to load (restart), the game's Terms of play (asks), a browser opening after a click (suspected misclick: the window is
normalised), a game managed by another store (asks, exit 9).

## Verify before concluding (GUI clicks)
- A surprising result after a click in a Wine / Electron / CEF app is first suspected to be a MISCLICK. On 10-29 a maximised EA App
  window (no window manager) drew full screen while its X window stayed 1024x576; clicks landed on a banner link, Wine opened it with
  winebrowser, and the builder wrongly told the user "the EA App hands the download to Steam". It was false: the 10-24 run had
  downloaded the game through the EA App, and at the default size "..." > Download works.
- Before a click: normalise the window (default size and place: `ga-ea normalize`; never maximise without a window manager), take a
  fresh screenshot, check the target (the text near the point). After the click: check the expected effect (a dialog, a log line).
- An unexpected browser / winebrowser after a click is a misclick, never evidence. Check logs (earlier runs too) before telling the
  user something is impossible.
A new hiccup is one entry there (see docs/sandbox-images.md "Adding a known situation").

## EA App (The Sims 4) — verified in the lab 2026-10-29
Verified in a lab sandbox (Xvfb, a fresh test prefix): `ga-ea setup` (Kron4ek wine-11.19-staging-amd64-wow64, wine-mono 11.3.0
+ gecko 2.47.4, DXVK 3.1.1; 72 s), the EA App installer 13.813.1.6327 (EA User Agreement clicked by the user; install 20 s), the
sign-in (the user, about 4 min), a restart with the saved login (29-32 s, nothing typed), ownership, "Download options" and the
Terms of play (the user clicked DOWNLOAD), the download (26.3 GB in ~4.5 min on a local disk), the game 1.129.39.1030 under DXVK on
Xvfb, the smoke package listed in the Mods dialog and visible in the main menu, and after a restart: still signed in, still installed.
Not verified on a plain Docker host.
- Inside the sandbox: `ga-ea setup | install-app | start | stop | status --json | owns --json | game`; everything lives in
  `GA_EA_HOME` (default /sandbox/ea: Wine, the prefix with the login, the library), so a new sandbox with the same volume starts signed in.
- State is read from the app's own log (`ProgramData/EA Desktop/Logs/EADesktop.log`: `DesktopFSM[awaitingAuthentication]` = the
  sign-in form, `[authenticated]` = signed in; EADesktopVerbose.log `gameStatus` = installed / installing / `externalSource`). The log is
  appended per start: only lines after the start count. Never read the app's cookies, its .ini files or the QtWebEngine profile.
- Window titles use a no-break space ("EA\u00a0app installer"); the sign-in form is the "EA" window at 520x648, the app 1024x576.
- Without a window manager "maximise" breaks the app's drawing: resize with `xdotool windowsize` instead.
- On docker-rt (the lab) the host-side snapshot exec is refused; run the flow inside: `gameanything lab login ea --local`.
- Exit codes as for Steam, plus **9 = another store manages the game** (entitlement data only; not seen in a real account yet).

