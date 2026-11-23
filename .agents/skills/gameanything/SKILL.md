---
name: gameanything
description: "Turn a person's memories (wedding, trip, family photos, videos, documents) into playable content inside a game they own (Stardew Valley, Minecraft, Cities: Skylines, Overcooked! 2, The Sims 4, Valheim; Slay the Spire for gameplay projects), using the GameAnything `gameanything` tool. Use when the user says things like \"turn my wedding / trip / memories into a game\", \"make a Stardew mod from my photos\", \"GameAnything\", or asks to continue an existing GameAnything project."
---

# GameAnything

You carry the user through a whole project: ingest their memories locally, look at the photos (with permission), confirm
people and the day with them, design the world, build it in their own game, replay, review, iterate. The user works in a
browser UI (`gameanything ui`); you talk to them there through the `gameanything chat` commands. Reply in the user's language.

## 1. Check the setup
- `gameanything --help` works? If not: `uv tool install git+https://github.com/AetherLabsAI/GameAnything` (optional features `transcribe` speech-to-text and `detect` person boxes: only via `gameanything extras install <name> --project "$P"`, which asks her on a card). Needs Linux, ffmpeg/ffprobe, docker, and the user's own Stardew Valley.
- Honest status to tell the user: the conversation part works with any agent; builds have been run with Claude Code (native mode, and the
  sandbox on the user's own Linux machine with Docker: `gameanything lab sandbox`, verified end to end with Valheim on 2026-10-30).
- Before any long job: `df -h`; temp files on the data disk.
- **The setting guide (hard rule, 2026-10-29):** at the start of every project, and again before its first build or game launch, run
  `gameanything setup guide --project "$P"`; it prints the WHOLE guide: read it, then `gameanything setup guide --project "$P" --read <mark1>-<mark2>-<mark3>` (the 3 read marks spread through it)
  with the token printed at its end (only that counts as read). The guide is `references/setups/<system>-<mode>.md`, or
  `server-sandbox.md` on the hub): prerequisites, settings to change, checks, resources, which games work there, pitfalls, and what to
  tell the user before launching. It detects the computer, picks the mode (the project's `build_mode`: lab = sandbox, else the
  recommended one) and records `setup:` in `config/project.yaml`. Re-run it whenever `build_mode` or the computer changes. The flow's
  go step (`setup_guide`) stays open until it is done. Detection failed (exit 3): ask the user which system and pass `--system`.
- **Store logins and downloads in a sandbox (2026-10-29):** read `references/sandbox-logins.md`, then use `gameanything lab login
  steam|microsoft|ea --project "$P"` (EA: verified in the lab 10-29). It prints progress in the user's language and runs the setup watchdog: never
  wait blindly with sleep loops, pass every line on, and on exit 4 ask the exact question it printed. Never accept a publisher EULA
  for the user (Cities: Paradox, Civ VI: Take-Two, tModLoader, EA) unless they say for that dialog 「同意，帮我点」 (then `lab consent
  --click-for-me --words`, valid 15 min); a surprising GUI result is first a suspected misclick; never read, log or screenshot what they type; tokens stay in the sandbox.

## 2. Start or resume a project
- New: `gameanything project new --title "<title>" --kind memory --game stardew --mode lab|native` (a feature project: `--kind feature`; an adaptation of a novel / series / anime: `--kind adaptation`, see adaptation-flow.md; an experience turned into a game system: `--kind gameplay`, default game `slay_the_spire`, see gameplay-flow.md; games: `stardew`, `minecraft`, `cities_skylines`, `slay_the_spire`, `overcooked2`, `sims4`, `valheim`, `terraria`, `civ6`); resume: `gameanything project list`, then `gameanything project open <id> --ui`.
- **Which game**: read `config/project.yaml` → `game` as soon as you open a project (missing = `stardew`; `gameanything project list` shows it too). The user picks it in
  the browser's new-project dialog (`gameanything game list`: every game, its engine and mod loader). Each game has a sandbox image
  (`gameanything lab sandbox`, setups/linux-sandbox.md) and a native adapter (`gameanything native … --game <g>`). Games with online play
  (Valheim, Terraria, Civ VI, Minecraft): test only in a local world / single player, never join a public server. KSP: test saves only.
  Offline single player only. Never design with Stardew-only things (villagers, the farmhouse, SMAPI) for another game.
- **Where builds run (D19; per project since 2026-10-24)**: the project's `config/project.yaml` → `build_mode` decides, chosen by the user in the
  new-project wizard step 「在哪里做」 (`lab` = the sandbox: a Docker container on her own Linux machine, `gameanything lab sandbox`;
  `native` = 我的电脑（本机）, her own copy of the game) and changeable in the project menu or with `gameanything project set-mode <id> lab|native`
  (`--show` lists what works for its game here, with the reason when one does not). Read it before planning or starting any build and build only
  that way; **native builds never use docker** (no sandboxes, no containers). Missing `build_mode` (projects made before 2026-10-24): the old
  automatic rule, `gameanything native doctor --project <id>` says which. A Steam game in the sandbox keeps her Steam account busy while it runs.
  New projects from the command line: `gameanything project new … --mode lab|native`. Native mode in the user's own copy of the game: `gameanything native backup / build / install / log --game <g>` (saves backed up first, only the Mods folder changes, nothing
  deleted, no mouse or keyboard control).
  **Native mode disturbs her as little as possible (本机模式少打扰, docs/cross-platform.md):** her game is opened ONLY by
  `gameanything native launch --project P` (it posts the card 「要开游戏测一下，现在可以吗？」 and opens the game only after her 「现在可以」 on it,
  or in her time window / when she chose 「随时可以」 in the project menu 「什么时候开游戏」: `native_launch: ask | window | always`); exit 2 = pending
  (do other work, never ask again in chat), 3 = refused (the game is open: maybe she is playing; never close it). Close only with
  `gameanything native close --project P` (only what gameanything opened). Batch each round: compile + `gameanything native check --project P --src <built mod>` first
  (references against the game's assemblies / jars; Minecraft `--server` runs it headless), then ONE launch per round with `--round <label>`,
  `gameanything native reload` where the game can (Overcooked 2 / Valheim with ScriptEngine, Cities: Skylines on Windows / macOS) instead of a restart, and say in the progress card
  how many launches the round used (`gameanything native launches --project P`). `native_launch: idle` (「我没在用电脑时」) opens it only after she has
  not touched mouse / keyboard for N minutes (`gameanything native idle`; unknown = it asks with the card). **Never focus or bring her game to the
  front while she is at the computer** (no `osascript activate`, `open -a`, `xdotool windowactivate`, `SetForegroundWindow`): look with
  `gameanything native shot --project P` (only the game window gameanything opened) and press keys with `gameanything native drive --project P "key escape" "click x y"`
  (only to that window, no focus change; exit 2 = she is at the computer or, on Windows, the game is not in front: stop and try later;
  3 = not gameanything's game). **Before the first launch, and again after the project's agent / model changed: `gameanything native ready
  --project P --if-needed --card-file $TMPDIR/ready.yaml`** (能不能操作屏幕: run it yourself, it checks YOUR sandbox + app; exit 0 full, 1 look
  only, 3 none). `next: card` → post that file ONCE with `gameanything chat card`; `self` (she chose 「不给，我自己点」, native_hands: self) →
  never drive: each round's progress card lists her clicks, wait for her 「好了」 (no shot either: ask for a screenshot). Never weaken an agent's
  sandbox for it (docs/cross-platform.md §8a). Windows: drive brings the game to the front only with 「测试时允许把游戏切到前面」
  (native_front: away) while she is away. macOS needs Accessibility + Screen Recording for the app running gameanything: `gameanything native permissions` says how. gameanything's
  Unity smoke plugins set `Application.runInBackground = true`; add it to project BepInEx / Cities mods too (docs/cross-platform.md §9). Cities: Skylines on Windows / Linux compiles `Source/*.cs`
  itself; the macOS game has no compiler, so run `gameanything native build --game cities_skylines <mod> --install` (needs the .NET SDK; template:
  `gameanything/worlds/cities_skylines/template`). `install` switches the mod on; the game must be closed for that. Check that the chain works
  with the smoke mod (`worlds/cities_skylines/smoke`: logs `[M2W-smoke] city loaded`, starts a city by itself through the New Game panel).
  The Sims 4 (`--game sims4`) is native mode only: her own Windows / Mac (the game must be closed for `install`; scripts need Python 3.7, a package-only mod does not; template
  `worlds/sims4/template`, smoke mod `worlds/sims4/smoke`: console `m2w.hello`). In the docker sandbox it needs the EA app under Proton, which was unreliable (2026-10-23): do not plan Sims 4 builds in the lab.
- Keep the project folder outside any git repo. Tell the user the browser address from `gameanything ui` and that they can talk to you there.
- Who answers the chats: by default the supervisor `gameanything agentd` (one long-running process on the machine). For each project with new user
  words it starts one headless Claude Code run with the role in [references/resident-prompt.md](references/resident-prompt.md), while fewer
  than the user's maximum (default 3, browser Settings) are active. A run claims, reads, replies, works and exits. Without agentd, keep
  `gameanything chat wait --all` running yourself (see the loop below): it claims any project that gets a message, so new projects never wait for the
  user to remind you.

## 3. Read before acting (progressive; read what the step needs)
0. **Flow state machine first (2026-10-26):** `gameanything flow next --project P` says the ONE step to work on, its required actions (cards,
   files), what blocks it and what to tell her; `gameanything flow check --project P` checks its exit criteria. Every kind (memory, feature,
   adaptation, gameplay) runs on layered docs: [core.md](core.md) (rules + per-run loop), `modes/<kind>.md` (the steps), and one doc per
   step in `steps/<kind>/`; agentd builds their runs from exactly these (resident-prompt.md is only the fallback; the long files below
   stay for reference). After a version is built the flow loops: 「下一步」 card → next milestone → that version's plan → go → build.
1. [references/rules-and-loop.md](references/rules-and-loop.md): hard rules and the claim / wait / read / say loop. Read first, every time.
2. [references/cards.md](references/cards.md): which card for which situation (yaml examples in `references/card-examples/`).
3. [references/memory-project-flow.md](references/memory-project-flow.md): the ten steps of a memory project (materials, perceive, people, board, design, portraits, each build, feedback, take home, backup).
4. [references/feature-flow.md](references/feature-flow.md): when the user asks to add a feature.
5. [references/pitfalls.md](references/pitfalls.md): mistakes that already happened.
5b. [references/adaptation-flow.md](references/adaptation-flow.md): `kind: adaptation` projects (a novel / TV series / anime made into a game world): copyright first, everything in simplified Chinese (traditional input is converted automatically), extraction with grounding levels, place registry, plan, preview images.
5c. [references/gameplay-flow.md](references/gameplay-flow.md): `kind: gameplay` projects (an abstract life experience, e.g. a CS PhD, made into a game system in a game's native mechanics, e.g. a Slay the Spire character mod): the experience → mechanic mapping agreed first (机制映射 page), then a small v1 content list (内容 page), art as in-game assets via a permission card, lab build with agent playtests and balance runs (平衡 page); obstacles not people.
6. [references/landmark-references.md](references/landmark-references.md): rebuilding real places: search public landmark references, draw target pictures first, have the reviewer compare.
7. [references/resident-prompt.md](references/resident-prompt.md): when `gameanything agentd` started you for one project: the run's steps, what never to do, and `gameanything agentd request` for anything the coordinator must do (builds, paid images).
7b. [references/dev-status.md](references/dev-status.md): the project's development status `5_build/STATUS.yaml` (`gameanything status show|init|set-item|add-issue|add-regression|recheck|feedback|decide|card`): her requirements and their state, known issues, regressions, the every-round recheck list, her unhandled words; the 开发状态 page shows it; answer "where are we" from it.
7c. [references/lessons.md](references/lessons.md): agent experience memory (`gameanything lessons show|add|review`): per game (`<game package>/LESSONS.md`), per role (`references/lessons/builder.md`, `playtester.md`) and local-only (`<project list folder>/lessons/`); read at round start, add candidates at round end, the coordinator reviews.
7d. [references/feedback-records.md](references/feedback-records.md): her feedback as records (`gameanything feedback …`): one record per point she makes, your reading (confirmed with her when unsure, before any change), linked to a STATUS item, re-shot at the same anchor (before / after) and closed only on her ok; the repeat-feedback rate on the 开发状态 page. Design and evaluation: `docs/feedback-loop.md`.
8. [references/add-a-game.md](references/add-a-game.md): bringing a new game into GameAnything (or contributing one as a PR): recon and legality, `gameanything game new / check`, game.yaml + adapter + smoke mod, fake-folder tests, the native round trip, docs and the PR checklist.
9. [references/lessons.md](references/lessons.md): experience left by earlier agents (per game `gameanything/games/<id>/LESSONS.md`, per role `references/lessons/builder.md` / `playtester.md`); read before every round with `gameanything lessons show`.
10. [references/dev-status.md](references/dev-status.md): a project's `5_build/STATUS.yaml` (her requirements and their state, known issues, regressions, recheck list, open feedback); read with `gameanything status show` before every round.

## 4. The loop in one screen
```
while true; do gameanything chat wait --all --session S --timeout 3600; rc=$?; [ $rc -ne 2 ] && break; done   # background: every project, auto-claim (D20)
gameanything chat read --project P --session S      # records the user's words verbatim in feedback/answers.md
gameanything chat say  --project P --text "..." --text-en "..."
F=$(mktemp "$TMPDIR/card-XXXXXX.yaml")            # a new file per card, never a fixed name like $TMPDIR/go.yaml
gameanything chat card --project P --file "$F"     # the card stamped `project: <id>`; go / permission cards need a `key:`
```
Answer first, then work; re-attach the wait when done.

## 4b. Delivering a build (hard rule, 2026-10-24)
Two builds were delivered as folders only (no world_plan milestone and / or no `play.yaml`) and the 试玩 page did not list them.
- **Builder, last step before reporting "done":** `gameanything build deliver --project P --m <m> --name "第 N 版 …" [--what "…"] [--chapters final.chapters.yaml]`.
  It checks the video plays (ffprobe), writes a missing `play.yaml` (one full chapter, or the `--chapters` file), validates it (chapters
  `{moment, title, t}`, referenced stills / scenes / sounds exist) and registers the milestone in `4_design/world_plan.yaml` (status `built`,
  `at`, name / what; comments and other fields kept). Exit 1 = not delivered: fix what it lists and run it again. Running it twice is safe.
- **Resident / whoever posts the `result` card:** `gameanything build check --project P --m <m>` first (read only; without `--m` it lists every
  5_build folder and what it lacks). Never post a `result` card while it fails.
- `gameanything build status … --done` warns when the milestone is not delivered yet.

## 4c. Every round: lessons and the development status (hard rule, 2026-10-25)
- **Round start (builder and playtester):** `gameanything lessons show --game <g> --role builder|playtester` and `gameanything status show --project P`
  (`gameanything status init` first when there is no `5_build/STATUS.yaml`). Builder / critic briefs must say this, they do not read the skill.
- **Builder:** after each requirement, `gameanything status set-item --project P --id rN --state done|partial --build <m> --by builder --evidence "…"`.
- **Playtester:** verifies every item independently (`--by playtester`), runs the recheck list (`gameanything status recheck --build <m> --pass … --fail …`),
  marks regressions (`--state regressed`, `gameanything status add-regression … --cause …`).
- **Both, at round end:** new pitfalls / fixes as candidate lessons: `gameanything lessons add --game <g> --role … --symptom … --cause … --fix … --evidence …`
  (`--local` for machine / account specifics; never her photos, names or save details in shared lessons). The coordinator runs `gameanything lessons review`.
- `gameanything build deliver` warns from STATUS; result cards come from `gameanything status card`; the resident answers "where are we" from `gameanything status show`.

## 4d. Native mode: look at the game at every step (hard rule, Wenyi 2026-10-30)
When gameanything opens or drives a game on her computer, **you look at the game window after every step**, not only at the logs:
- After every `native launch`, `native drive`, `native close` and every click or key: `gameanything native shot --project P` (or the
  screen) within a few seconds, read the picture, then decide the next step. While a game starts, loads or changes screens, never go more
  than ~10 s without a fresh picture.
- Logs are not enough: they miss start-up promos and ads (The Sims 4: Esc closes each one), launchers (Civ VI's Aspyr launcher, the
  Minecraft Launcher), "are you sure?" boxes, crash reports, notices (KSP's Unity Analytics) and agreements. When the picture shows one,
  deal with it at once (or ask her if it is an agreement / her decision); do not wait for a log line that cannot come.
- Never block on one long wait (a foreground `sleep` / `until` loop, a long blocking command): the session can end in it and nobody looks.
  Put the wait in the background and keep taking pictures meanwhile; tell her what the picture shows if it takes long.
- A click or key that did nothing (the picture is the same) is a result: look again, find out why (focus, a window in front, the wrong
  spot), do not repeat it blindly.

## 5. Never
Send content to a model without a `permission` card; edit the user's words; invent facts about real people; decide save-affecting choices for the user; download copyrighted media; kill processes by pattern (exact PID only).
