# GameAnything: instructions for any coding agent

GameAnything turns a person's own memories (photos, videos, documents such as a wedding) into playable content inside a game
they own (first target: Stardew Valley 1.6). You do the work for the user inside their own agent session; the user talks to
you in a local browser UI (cards, workspaces) and the terminal is only for starting. Everything stays on the user's machine.

## Start here
0. Each project names its game in `config/project.yaml` (`game: stardew | minecraft | cities_skylines`; missing = stardew). Read it first.
1. Read `skills/gameanything/SKILL.md`, then follow it (it points to the detailed references in `skills/gameanything/references/`).
   Installed as a plugin / extension or with `npx skills add`, it is your `gameanything` skill (same files). In a clone, `.agents/skills/` and
   `.claude/skills/` hold copies for the agents that look there: edit only `skills/gameanything/`, then `python tools/sync_skills.py`.
   The detailed guide is written in Chinese; talk to the user in the language they use. Its main parts (one copy only, in the skill):
   `references/rules-and-loop.md` (working rules, the conversation loop), `references/cards.md` (which card to use; yaml examples in
   `references/card-examples/`), `references/memory-project-flow.md` and `references/feature-flow.md` (the two project flows),
   `references/pitfalls.md` (common mistakes).
2. Use the `gameanything` CLI. Check with `gameanything --help`. If missing: `uv tool install git+https://github.com/AetherLabsAI/GameAnything`
   (or, from a clone: `uv tool install .`, or put the clone's `bin/` on PATH: `bin/gameanything`, `bin/gameanything.cmd` on Windows). Optional features `transcribe` (speech-to-text) and `detect` (person boxes): never install them yourself; `gameanything extras install <name> --project P` asks the user on a card first.
   Needs ffmpeg/ffprobe on PATH. Builds: docker on Linux (the lab), or native mode on macOS / Windows with the user's own game (`gameanything native doctor`, D19).

## Hard rules (never break these)
- **Privacy (D3)**: the user's files stay on their machine. Never upload or send anything anywhere unless the user agreed to that exact thing.
- **Ask before sending content to a model**: before any photo or text goes to a model (including you looking at images), send a
  `permission` card saying what is sent, what is not, and to whom; log each time in `privacy_ledger.yaml`.
- **The user's words are verbatim**: `gameanything chat read` records them in `feedback/answers.md`. Never edit them; write your own reading separately and ask the user to confirm.
- **Never invent personal facts** about real people (habits, history, personality, places, who said what). Draft lines use only confirmed facts, marked `source: draft`.
- **User choices (D8)**: anything that changes the save's look or long-term experience (people tiers, place tiers) is the user's choice. Offer options with costs and a recommendation; do not decide.
- **Copyright (D9)**: copyrighted music and films only from files the user provides; never download them, never put them in backups.
- Keep project directories outside any git repository. Kill processes only by exact PID. Check `df -h` before long jobs; temp files go on the data disk.

## The conversation loop
0. **agentd (default)**: when the supervisor `gameanything agentd` runs (`gameanything agentd status`), it answers every project chat itself: one headless
   Claude Code run per project with new words, with the role in `skills/gameanything/references/resident-prompt.md`. Then do not run the wait
   loop below. Runs ask for builds with `gameanything agentd request --kind build_start`: agentd itself starts a headless builder (role `skills/gameanything/roles/builder.md`,
   a lab seat from the broker first; `--builds coordinator` leaves builds to a coordinator session). Paid images, 3D, sound: `gameanything gen list | estimate | request --tool <adapter>:<cap> --inputs …` (gameanything/gen: fal, Meshy, Gemini, OpenAI, OpenRouter, local ComfyUI; agentd checks both cards and runs it with the owner's key).
1. **wait**: keep `gameanything chat wait --all --session S --timeout 3600` running in the background (loop while exit code is 2). It watches every
   registered project and claims one that gets a message while fewer than the user's maximum (default 3, set in the browser) are active (D20);
   one session owns a project's conversation (`gameanything chat claim --project P` takes one explicitly).
2. **read**: when it exits, for each project it prints, `gameanything chat read --project P --session S`.
3. **say**: answer first (`gameanything chat say`, with `--text-en`), then do the work; long jobs in the background with `gameanything chat progress`.
4. **card**: use cards for structured turns (`permission`, `questions`, `options`, `candidates`, `understanding`, `task`, `result`, `go`, `progress`); examples are in `skills/gameanything/references/card-examples/`.
Then go back to wait.

## Status
Conversation, ingest, perception and the UI work with any agent. agentd runs residents and builders with Claude Code or Codex (subscription or API key);
builds in the gamebench lab (and, on the user's own Linux machine with Docker, in their own sandbox: `gameanything lab sandbox`) have been run with Claude Code so far; Codex builds are wired (sandbox, lab network, lease) but not yet validated end to end.
