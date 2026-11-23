# Installing GameAnything

The short version is in the [README](../README.md#install). This page has the details: requirements, optional extras, every agent's
install route, the two ways the agent works, which account you need, using an API key only, and running the command line by hand.

## Requirements
- Linux, macOS or Windows; `ffmpeg` / `ffprobe` on PATH, Python 3.10 to 3.14 (`uv tool install` fetches one by itself), [uv](https://docs.astral.sh/uv/).
- Builds: you choose per project where they run (new-project wizard step 「在哪里做」, later in the project menu, or `gameanything project set-mode`):
  **native** in your own copy of the game on macOS / Windows / Linux (`gameanything native doctor` checks the game, the mod loader and the build toolchain;
  your saves are backed up before anything changes and only the Mods folder changes), or **lab**, a Docker sandbox: on your own Linux
  computer or server with Docker Engine (`gameanything lab sandbox`; the game runs read-only in a container, see "Sandbox on your own Linux
  machine" below), or the gamebench lab on the maintainer's servers. The wizard recommends one and greys out what cannot work for that game on your computer, with the reason.
- Your own copy of Stardew Valley (the tool never ships or downloads the game).
- Supported games: [docs/games.md](games.md) (`gameanything game list`). Your favourite game is not there? Add it: [CONTRIBUTING.md](../CONTRIBUTING.md#adding-a-game).
- Optional: an image-model key (OpenRouter / Seedream) for pixel portraits.

## Pick your setting

Where GameAnything works on a game is a *setting*: your system and a mode, either a **sandbox** (Docker on your computer; recommended)
or **native** (your own copy of the game). Each setting has one guide with its prerequisites, the settings to change, how to check,
memory and GPU needs, which games work and the known pitfalls. Your agent picks and reads the right one by itself
(`gameanything setup guide --project <id>` detects the computer and names it); you can read the same files:

| | Sandbox | Native |
|---|---|---|
| Linux | [linux-sandbox](../skills/gameanything/references/setups/linux-sandbox.md) | [linux-native](../skills/gameanything/references/setups/linux-native.md) |
| Mac | [mac-sandbox](../skills/gameanything/references/setups/mac-sandbox.md) | [mac-native](../skills/gameanything/references/setups/mac-native.md) |
| Windows | [windows-sandbox](../skills/gameanything/references/setups/windows-sandbox.md) (Docker Desktop + WSL 2) | [windows-native](../skills/gameanything/references/setups/windows-native.md) |

## Install

Every route needs the `gameanything` CLI; the plugin/skill routes add the agent instructions on top.

```bash
uv tool install git+https://github.com/AetherLabsAI/GameAnything        # the gameanything CLI (works for every agent)
uv tool install "gameanything[transcribe] @ git+https://github.com/AetherLabsAI/GameAnything"   # + local speech-to-text, up front
```
Optional features, not installed by default: `transcribe` (faster-whisper: speech in videos -> text) and `detect` (torch + torchvision: person
boxes on the people page). Without them ingest still adds everything and notes what it skipped; the agent then runs
`gameanything extras install <name> --project P`, which asks the user on a card and installs into the Python GameAnything runs in (uv pip, else
pip) only after her yes; the next ingest fills in what was skipped. `gameanything extras status` shows what is missing and the command to run
yourself. A package added this way is not in uv's record of the tool, so `uv tool upgrade gameanything` drops it: install again, or put the
extra in the install line as above. `perceive` (jsonschema) is a basic dependency since 2026-11-01; `dev` (Playwright) is for contributors
(CONTRIBUTING.md).
The installed CLI carries the skill (`skills/gameanything/`) and `AGENTS.md` inside the package (`gameanything/_bundle/`, see `gameanything/shipped.py`), so `gameanything agentd` and `gameanything flow` work without a clone; lessons it learns go to your data folder.

Then add the agent side: the `gameanything` skill (Agent Skills format, one source in `skills/gameanything/`) and `AGENTS.md`.

| Agent | Install the agent side | What it brings |
|---|---|---|
| Claude Code | `/plugin marketplace add AetherLabsAI/GameAnything` then `/plugin install gameanything@gameanything` | skill `/gameanything:gameanything`; `bin/gameanything` on PATH (plugin `bin/` + a SessionStart hook, `hooks/`) |
| Codex | `codex plugin marketplace add AetherLabsAI/GameAnything` then `codex plugin add gameanything@gameanything` (or `/plugins` in a session) | the skill (`.codex-plugin/plugin.json`, marketplace `.agents/plugins/marketplace.json`) |
| Gemini CLI | `gemini extensions install https://github.com/AetherLabsAI/GameAnything` | the skill (extension `skills/`) and `AGENTS.md` as context (`gemini-extension.json`) |
| VS Code / Copilot | enable `chat.plugins.enabled`, run **Chat: Install Plugin From Source**, enter this repo's URL | the skill (`plugin.json`, Agent Plugins format) |
| Cursor | Cursor Marketplace / Import from Repo, or open a clone | the skill (`.cursor-plugin/`); a clone also gives `AGENTS.md` and `.agents/skills` |
| OpenCode | clone the repo and run `opencode` inside it; OpenCode 2 also has a plugin with an `gameanything_run` tool: [plugins/opencode](../plugins/opencode/README.md) | `AGENTS.md` (`opencode.json`) and the skill from `.agents/skills` |
| DeepSeek Harness (`dsh`) | clone the repo, start `dsh web` (a page in the browser; dsh has no terminal UI by default) and add the clone with **Add workspace**: its own default workspace is a separate folder (`~/Documents/deepseek-harness/default-workspace`), not the folder you start it in. `dsh --profile headless "…"` run inside the clone uses the clone directly. As GameAnything's background agent it needs no clone: [setup](agent-providers.md#deepseek-harness-setup) | `AGENTS.md` (dsh-agent-instructions) and the skill from `.agents/skills` (dsh-skill-filesystem, project scope = the git root) |
| Skills only (any agent) | `npx skills add https://github.com/AetherLabsAI/GameAnything` (`-a <agent>` to pick one) | the skill folder, copied into the agent's skills folder |
| Anything else | `git clone https://github.com/AetherLabsAI/GameAnything` and start your agent inside it | `AGENTS.md`, `.agents/skills`, `.claude/skills`, `bin/gameanything` |

From a clone, every route also takes the local path, e.g. `uv tool install ./GameAnything`, `/plugin marketplace add ./GameAnything`,
`codex plugin marketplace add ./GameAnything`, `gemini extensions install ./GameAnything`.

**The `gameanything` CLI.** Only the Claude Code plugin (and a clone opened in Claude Code: `.claude/settings.json`) puts it on PATH by itself; it
then runs this checkout's code (`bin/gameanything`: the clone's `.venv`, else uv, else python). Every other route needs the `uv tool install`
line above once, or, in a clone, `export PATH="$PWD/bin:$PATH"` (Windows: add the `bin` folder to PATH, `bin/gameanything.cmd`).

**Inside a clone** each agent finds the skill where it looks: `.agents/skills/` (Codex, Gemini CLI, Cursor, Copilot, OpenCode) and
`.claude/skills/` (Claude Code) are copies of `skills/gameanything/` (copies, not symlinks, so Windows clones work; refresh them with
`python tools/sync_skills.py`, a test fails while they differ). `CLAUDE.md` and `GEMINI.md` point to `AGENTS.md`.

**Two ways the agent works.**
- *Interactive* (every agent in the table): your own agent session runs the skill and the `gameanything` CLI; you start it in a terminal, and it
  talks to you in the browser UI through `gameanything chat`. It can do everything the skill describes; paid generation still goes through
  `gameanything gen request` and a card.
- *Background web chat* (`gameanything agentd`, started by `gameanything ui`): the supervisor answers every project chat and runs the builds with a
  headless agent CLI of its own. It supports only the providers in `gameanything/agent_providers.py` (Claude Code, Codex, OpenCode, Gemini CLI and DeepSeek Harness; see
  "Which account do I need"); an agent that is not there (Cursor, Copilot, ...) works interactively only.

Then tell your agent, in a terminal: "Turn my wedding photos into a Stardew Valley mod with GameAnything."

## Which account do I need
| You have | Use | Works today |
|---|---|---|
| Claude subscription | Claude Code (plugin above) | Conversation and builds |
| Codex subscription (ChatGPT) | Codex (plugin above) | Conversation; builds wired, not yet validated end to end |
| API key only | Claude Code with an Anthropic key, Codex with an OpenAI key, OpenCode with an OpenRouter (or any of its 75+ providers') key, or Gemini CLI with a Gemini key (see below) | Conversation and builds (billed per token) |
| DeepSeek or OpenRouter API key | DeepSeek Harness (`dsh`) in the background (see below) | Conversation (billed per token); builds wired, not yet tested |

Honest status (D18): the conversation part (ingest, looking at photos, people, memory board, design) works with any agent. The background
supervisor `gameanything agentd` answers every project chat and, since 2026-10-26, also runs the builds itself (`--builds auto`, the default): when you
press 开工 it starts a headless builder (Claude Code or Codex), takes a sandbox seat for lab builds and reports back in the chat. Lab builds
have been run with Claude Code so far; Codex builds are wired but not yet validated end to end. A build costs real money or quota (about
$40-56 per milestone with Sonnet so far); you will see the estimate before it starts.

## 只有 API key 怎么用 / API key only
You need no subscription and no coordinator session: the gameanything install plus ONE agent CLI with an API key is enough.
1. Install the CLI: `npm install -g @anthropic-ai/claude-code` (Claude Code), `npm install -g @openai/codex` (Codex),
   `npm install -g opencode-ai` (OpenCode), `npm install -g @google/gemini-cli` (Gemini CLI) or `npm install -g @deepseek-ai/dsh`
   (DeepSeek Harness, tested 0.2.1-rc.2 and rc.5).
2. Give it the key:
   `export ANTHROPIC_API_KEY=…` before `gameanything ui` (Claude Code), or `printenv OPENAI_API_KEY | codex login --with-api-key`
     once (Codex), and start with `GAMEANYTHING_AGENT_PROVIDER=codex gameanything ui` for Codex; OpenCode: `export OPENROUTER_API_KEY=…` and
     `GAMEANYTHING_AGENT_PROVIDER=opencode GAMEANYTHING_OPENCODE_MODEL=openrouter/<vendor>/<model> gameanything ui` (another provider: its own key variable, e.g.
     `DEEPSEEK_API_KEY` with `deepseek/deepseek-chat`); Gemini CLI: `export GEMINI_API_KEY=…` and `GAMEANYTHING_AGENT_PROVIDER=gemini gameanything ui`;
     DeepSeek Harness: `export DEEPSEEK_API_KEY=…` and `GAMEANYTHING_AGENT_PROVIDER=dsh gameanything ui` (model: `GAMEANYTHING_DSH_MODEL=deepseek-flash`),
     or with OpenRouter `export OPENROUTER_API_KEY=…` and `GAMEANYTHING_DSH_MODEL=openrouter/deepseek/deepseek-v4.1-flash` (web search then uses
     `perplexity/sonar` on OpenRouter, `GAMEANYTHING_DSH_SEARCH_MODEL`). On a hub, 「我的 agent」 takes a DeepSeek `sk-…` or an OpenRouter `sk-or-…` key
     with the model.
3. Then talk in the browser as usual. Everything runs in the background: replies, paid pictures (only after your two cards), and builds
   (after you press 开工 on the go card).
4. An API key is **billed per token**: every reply and every build is charged to your account. The go card shows the estimated cost and
   time (`gameanything estimate --agent claude-code|codex --account api`, `gameanything estimate --agent opencode --model openrouter/<vendor>/<model>`) before
   anything is spent; nothing starts until you press 开工. OpenRouter prices for a few common models are in the table (taken from
   OpenRouter's model list on 2026-10-26); for a model that is not there the card says it cannot give a dollar figure.

中文简述：装好 gameanything 和一个 agent 命令行（claude、codex、opencode、gemini 或 dsh），在「我的 agent」里贴上 API key（或在自己电脑上用环境变量 / `codex login --with-api-key`），
之后回复、画图、构建都在后台自动跑，不需要另开协调会话。API key 按 token 计费，开工卡上会先写出大约花多少钱、多久，你点了开工才开始。

What each agent CLI guarantees in a background run (docs/agent-providers.md has the details):
- all five: the project's chat rules as the system prompt, session resume, no paid key in the run's shell (paid pictures only through
  `gameanything gen request`), the operator's own config / skills / MCP servers / AGENTS.md not loaded, a clear chat message when the login
  or key is wrong;
- all but DeepSeek Harness: the same deny list (no `gen_*.py`, no raw `docker run`, no `pkill`; residents also no lab tools). DeepSeek
  Harness has no command rules and runs with its sandbox off (the CLI cannot run inside it), so its shell can do anything the OS user can;
- only Codex runs in an OS sandbox (residents without network). Claude Code, OpenCode and Gemini CLI limit their FILE tools to the project
  plus the folders a run needs, but their shell can reach the network and write elsewhere (the deny list and the missing keys are the guard).

Not supported: no agent CLI at all (a bare API key without one of these CLIs installed); gameanything does not call model APIs for the agent itself.
Builds also need either a sandbox (Linux with Docker Engine, below) or your own copy of the game (native mode).

## Sandbox on your own Linux machine (Docker)

Use a clone or an editable install (`git clone …; cd GameAnything; uv tool install -e .`, or the clone's `bin/` on PATH): `lab setup --image
--build` builds images from the clone's `lab/images/`. Once per machine, with sudo (your agent shows you each command; `gameanything setup
guide --project P` prints the guide, skills/gameanything/references/setups/linux-sandbox.md):

1. Docker Engine 26 or newer, your user in the `docker` group (`sudo usermod -aG docker $USER`, then log in again).
2. 3D games: the NVIDIA driver and the NVIDIA Container Toolkit (`sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml`).
3. Steam games: the AppArmor profile, `sudo install -m 644 lab/images/common/security/gameanything-steam.apparmor /etc/apparmor.d/gameanything-steam
   && sudo apparmor_parser -r -W /etc/apparmor.d/gameanything-steam` (Ubuntu 22.04 / Debian 12: the `gameanything-steam-u2204.apparmor` file).
4. Disk: about 15 GB free where Docker keeps images (`df -h /var/lib/containerd`) plus the games' size where it keeps volumes (`df -h /var/lib/docker`).

Then, per project: `gameanything project new --title T --game valheim --mode lab`, `gameanything lab sandbox up --project P --source steam`
(it pulls the image), `gameanything lab login steam --project P --install` (you sign in and accept in the viewer, http://localhost:6080/vnc.html;
on a server first `ssh -L 6080:127.0.0.1:6080 <server>`), `gameanything lab sandbox up --project P` again. `gameanything ui` also starts agentd,
which runs the builds (each builder uses `gameanything lab sandbox`).

## The command line without an agent: ingest (local, no LLM)

```bash
pip install -e ".[transcribe]"      # needs ffmpeg / ffprobe on PATH
gameanything ingest ~/my-memories --project ~/m2w/our-day --vocab "Alice,Bob"
```

The user's files are only read. Everything is written under `<project>/1_ingest/` (the project layout is in `gameanything/layout.py`; `gameanything status` writes `<project>/README.md`):
- `pack.yaml`: one entry per file, with a hash, a kind, normalized derivatives, raw metadata and an assessed capture time
  (with a trust level and reasons: metadata is a hint, never a fact);
- `derived/`: normalized images (HEIC -> JPEG, orientation fixed), thumbnails, contact sheets, video keyframes, audio,
  local speech-to-text (faster-whisper, offline), document pages (text + images).

Re-running is incremental. Put names and special terms in `<project>/config/vocab.txt` (one per line) to improve transcription.

Keep project directories outside any git repository: they hold personal data.
