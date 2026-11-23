# Harness check: every agent CLI and model on a real Mac (2026-10-31)

Machine: Apple silicon Mac, 8 GB RAM, macOS 14 (Darwin 23.6). The new CLIs went on the external disk
(`/Volumes/USB-500G/m2w_dev/agent-clis`: Node 22.23.4, then `npm i -g` with that prefix), because the internal disk had ~12 GB free.
While the check ran, a Docker VM of another session used 6 GB and the Mac had 6.8 GB of swap in use: every Node / Codex / Gemini
start took 10–60 s, so the times below are slow for reasons outside GameAnything.

How each line was tested:

- **Minimal run** = `agent_providers.provider(name, model).launch(...)` with the env built the way agentd builds it (`agentd.clean_env` +
  `agent_env`, its own run TMPDIR), in a scratch project with `hello.txt`. The prompt asks the agent to read the file with its tool and
  answer with the word inside it. "OK" means it used its file tool and answered correctly.
- **Resume** = the same session resumed (`--resume` / `exec resume` / `--session`), asked for the word without tools.
- **Builder** = the same run with `role="builder"` (the builder's deny list and policy).
- **agentd end to end** = a separate agentd (its own `GAMEANYTHING_HOME` / `GAMEANYTHING_DATA` on the external disk, `--builds coordinator`) with one
  new project per CLI (`project set-model <id> chat <agent>[:model]`): the resident's real prompt, its greeting written into the chat with
  `gameanything chat say`.

## Results

| CLI (version) | Login used | Model | Minimal run | Resume | Builder | agentd end to end |
|---|---|---|---|---|---|---|
| Claude Code 2.1.72 (`~/.local/bin/claude`) | subscription login | sonnet / opus / haiku | OK (but `sonnet` = claude-sonnet-4-6, `opus` = claude-opus-4-6, `haiku` = claude-haiku-4-5: the old CLI maps the aliases to old models) | OK | OK | – |
| | | fable | **refused**: "There's an issue with the selected model (fable)"; `claude-opus-5-5` / `claude-fable-5-1`: 400 `claude_code_version_too_old` (needs ≥ 2.1.251 / 2.1.280) | | | |
| Claude Code 2.1.309 (the desktop app's copy) | same login | sonnet / opus / haiku / fable | OK (claude-sonnet-5-5, claude-opus-5-5, claude-haiku-5-5, claude-fable-5-1; fable cost $0.22 for this tiny run) | | | OK, 14 s (sonnet) |
| Codex 0.166.0 | ChatGPT login (`codex login`, done in the browser) | default | OK | OK | OK | OK, 496 s |
| | | gpt-6.1-sol / gpt-6-astra / gpt-6.1-terra / gpt-6-luna | OK (90–275 s each, mostly start-up under swap) | | | |
| Gemini CLI 0.66.0 | `GEMINI_API_KEY` (env_file) | gemini-3.5-flash (default) | first try: 402 "prepayment credits are depleted" (classified `auth`, out of credit, correct); after the top-up: OK | OK | OK | OK, 512 s |
| | | gemini-3.1-pro-preview | OK | | | |
| OpenCode 1.19.5 | OpenRouter key (env_file) | openrouter/moonshotai/kimi-k2.6 (default) | OK | OK | OK | OK, 352 s |
| | | openrouter/moonshotai/kimi-k3, openrouter/deepseek/deepseek-v4.1-flash, openrouter/z-ai/glm-5.3 | OK | | | |
| | | openrouter/anthropic/claude-sonnet-5.5, openrouter/openai/gpt-6.1-terra, openrouter/google/gemini-3.8-flash | **refused**: 403 "violation of provider Terms Of Service". A plain `curl` to OpenRouter with the same key and "reply OK" gets the same 403, while Kimi answers, so this is the key / account, not GameAnything | | | |
| | `GEMINI_API_KEY` | google/gemini-3.5-flash | OK | | | |

A model name the CLI does not know: Codex "model is not supported when using Codex with a ChatGPT account", Gemini "models/… is not found
for API version v1beta" (now both detected, see below); OpenCode `openrouter/no-such/model-x` only says "Unexpected server error".

## Installing the skill / plugin (each into an empty home on the external disk)

| Agent | Command (README) | Result |
|---|---|---|
| Claude Code | `claude plugin marketplace add AetherLabsAI/GameAnything`, `claude plugin install gameanything@gameanything` | OK, skill at `plugins/cache/gameanything/gameanything/<sha>/skills/gameanything/SKILL.md` |
| Codex | `codex plugin marketplace add …`, `codex plugin add gameanything@gameanything` | OK, skill in `plugins/cache/gameanything/gameanything/0.0.1/` |
| Gemini CLI | `gemini extensions install https://github.com/AetherLabsAI/GameAnything` | **failed**: "could not read Username for 'https://github.com'". From the local clone (`gemini extensions install <clone> --consent`): OK, `AGENTS.md` as context file and the `gameanything` skill listed |
| `npx skills add` | `npx -y skills add https://github.com/AetherLabsAI/GameAnything --yes` | OK, `.agents/skills/gameanything/SKILL.md` |
| OpenCode | run `opencode` inside a clone | OK: `opencode debug skill` finds `.claude/skills/gameanything/SKILL.md`, `debug config` has `instructions: ["AGENTS.md"]`. The `plugins/opencode` tool plugin needs OpenCode 2; npm's latest is 1.19.5, so it still cannot be tried |
| VS Code / Copilot, Cursor | GUI install | not run (both apps are installed, but the install is clicks in the app) |

**When this check ran, the GitHub repository was still private** (anonymous `https://github.com/AetherLabsAI/GameAnything` answered 404). The
installs above that clone it worked because this Mac's git had the owner's GitHub login in the keychain; Gemini's clone does not use it,
hence its failure. With the repository public, the README install lines (`uv tool install git+https://…`, the plugin marketplaces,
`gemini extensions install`, `npx skills add`) need no login.

## Fixed in this round

- **A refused model is its own failure, `model`** (`agent_providers.MODEL_NEEDLES`, `Provider.model_refused`): Claude Code's old-CLI
  refusals, OpenRouter's 403 terms refusal, Codex's and Gemini's unknown-model errors. Before, agentd counted each as a crash, retried
  the same model three times and then said only "the process exited with an error". Now agentd backs off (`BACKOFF_SECS["model"]`, 6 h),
  tells her once which model was refused and what to do (Claude Code: `claude update` or pick another model; the others: pick another
  model or agent), and the backoff ends as soon as the project's chat model changes (`.agentd_backoff.json` keeps the model).
  Tests: `tests/test_agentd_failures.py::test_a_refused_model_is_said_once_and_waits_for_another_model`, `…::test_model_refusals_of_each_cli_are_model_failures_not_logins`.

## Still to do (by a person)

- `claude update` on this Mac: `~/.local/bin/claude` is 2.1.72, so agentd's Claude runs get the old 4.x models for sonnet / opus / haiku
  and cannot use fable at all. (Or set `GAMEANYTHING_CLAUDE` to a newer claude.)
- The env file's OpenRouter line is spelled `PENROUTER_API_KEY`; GameAnything and OpenCode look for `OPENROUTER_API_KEY`.
- The OpenRouter key cannot reach Anthropic / OpenAI / Google models (403 terms of service): check the OpenRouter account's settings,
  or use Kimi / DeepSeek / GLM through it, Claude through Claude Code, GPT through Codex and Gemini through Gemini CLI.
- Make the repository public before telling others to install it (see above).
- To use Codex, Gemini CLI and OpenCode with agentd later, put `/Volumes/USB-500G/m2w_dev/agent-clis/npm-global/bin` on PATH (or set
  `GAMEANYTHING_CODEX` / `GAMEANYTHING_GEMINI` / `GAMEANYTHING_OPENCODE`), and the external disk must be mounted.

**DeepSeek Harness used by hand (2026-11-02, dsh 0.2.1-rc.5, `openrouter/deepseek/deepseek-v4.1-flash`, a fresh clone).** `dsh --profile
headless` started inside the clone loaded `AGENTS.md` (first line `# GameAnything: instructions for any coding agent`), `CLAUDE.md` and the
`gameanything` skill from `.agents/skills`. `dsh web` started in the same folder did not: its "Default workspace" is
`~/Documents/deepseek-harness/default-workspace` (it creates that folder), so it had no instructions and no skill. Add the clone with
**Add workspace**, which opens the system's folder picker (not tried here: the picker cannot be driven from a browser tab).

