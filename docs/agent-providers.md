# Agent CLIs that run gameanything in the background (agentd)

`gameanything agentd` answers every project chat and runs builds with one headless coding-agent CLI per run
(`gameanything/agent_providers.py`). The user picks it in 「我的 agent」 (hub) or with `--provider` / `GAMEANYTHING_AGENT_PROVIDER`
(`claude-code | codex | opencode | gemini | dsh`).

```text
gameanything agentd run --provider claude-code|codex|opencode|gemini|dsh [--agent-bin /path/to/cli] [--model MODEL]
```

Which CLIs and models were run for real, and how to install them: [harness-check.md](harness-check.md).

agentd owns scheduling, chat ownership, retries, prompts and coordinator requests; `gameanything/agent_providers.py` owns only what
differs between the CLIs: finding the executable, building the command, session discovery / resume, authentication errors and cleaning
the parent session's environment. Defaults: `GAMEANYTHING_AGENT_PROVIDER`, and `GAMEANYTHING_CLAUDE` / `GAMEANYTHING_CODEX` /
`GAMEANYTHING_OPENCODE` / `GAMEANYTHING_GEMINI` / `GAMEANYTHING_DSH` for the executables (else PATH). `--claude PATH` is a deprecated alias for `--agent-bin`
with `--provider claude-code`. A stored session (`conversation/.agent_session`) records its provider: switching providers starts a new
session instead of passing one CLI's session id to another. The heartbeat and run records name `provider` and `model`
(`agent_provider` / `agent_session`; `claude_session` is kept for old readers).

**Per project** (`gameanything/models.py`): config/project.yaml `chat_model` / `build_model` = `{agent, model}` override that default for the resident
and for builds (the chat page's 「对话 / 构建」 chips, owner only; `gameanything project set-model <id> chat|build agent[:model]|default`, `--list`).
Only agents the owner can run are offered, each with a short model list (Claude Code: sonnet / opus / haiku / fable, the aliases `claude --model`
takes; `fable` = claude-fable-5-1, very expensive: the menu marks it and asks her to confirm, `set-model` prints the warning; Codex: its `models_cache.json`;
OpenCode / Gemini / DeepSeek Harness: her configured model or a typed one). Same agent, other model: the session is resumed with `--model`. Another agent: a new
session whose first prompt quotes the recent thread (`agentd.seed_text`). **Builds run only on `build_model`** (since 2026-10-28): `gameanything chat card`
stamps the go card with `build_model` (shown read only, with a pointer to the 「构建」 chip) and drops `runners`; `gameanything estimate --project P`
estimates that model. builds.py starts every builder with the build model at the time it starts; when the owner cannot run it (no login / key), the
build stays `blocked` and the resident gets a note to tell her (no fallback to another model). An older go card that carries a runner still starts:
the runner is logged (`card_runner` in `.build_run.json`) and ignored. The run file
(`.agentd_run.json` `agent_model`, `.build_run.json` `model`), the agentd log, the live build card and the result card name the model.

| | Claude Code | Codex | OpenCode | Gemini CLI | DeepSeek Harness |
|---|---|---|---|---|---|
| headless run | `claude -p … --output-format stream-json` | `codex exec --json` | `opencode run --format json` | `gemini --prompt … --output-format stream-json` | `dsh --profile headless --patch <file> --json` |
| system prompt | `--append-system-prompt` | first block of the prompt | instructions file in the gameanything OpenCode home (appended to opencode's own prompt) | first block of the prompt (`GEMINI_SYSTEM_MD` would replace gemini's tool guidance) | first block of the prompt (a `personaSuffix` would be a template: `{{…}}` in it are variables) |
| session resume | `--session-id` / `--resume` | `exec resume <thread>` | `--session <sessionID>` | `--resume <session uuid>` (per project folder) | `--session-id <id>` from the opening `session` event (same working directory only) |
| config of the operator ignored | `--strict-mcp-config`, `--disable-slash-commands`, own tool list | `--ignore-user-config`, `--ignore-rules`, skills / apps / plugins off, AGENTS.md preamble | own home: XDG_CONFIG_HOME / XDG_DATA_HOME / XDG_STATE_HOME → `<home>`; `OPENCODE_DISABLE_PROJECT_CONFIG`, `_CLAUDE_CODE`, `_EXTERNAL_SKILLS`, `_DEFAULT_PLUGINS`; `mcp: {}`, no task / skill tools | own home: `GEMINI_CLI_HOME`; settings written by gameanything: no MCP, skills, hooks, subagents, extensions, context files, telemetry, auto-update | own home: `DSH_HOME` / `DSH_AGENTS_HOME`; a `--patch` layer written by gameanything: model and route (DeepSeek's own API, or a pi-ai route such as `openrouter`; without a DeepSeek key `web_search` goes to gameanything's OpenAI-compatible search plugin on that provider, or is off), no `AGENTS.md` / `CLAUDE.md` candidates, skills / MCP resources / subagents / workflows / plugin manager off; telemetry off (`DSH_TELEMETRY_DISABLED`) |
| shell deny list (gen scripts, raw docker, pkill; residents: lab tools) | `--disallowedTools` | (sandbox + `--ignore-rules`) | `permission.bash` deny globs | policy engine rules (`--policy`, user tier), regex on the whole command | **none** (dsh has no command rules) |
| file tools outside the project | `--add-dir` only | sandbox writable roots (`--add-dir`) | `permission.external_directory`: add_dirs, skill / install, temp folder; also checked for paths in `cd` / `cp` / `mkdir` / `touch` / `rm` commands | `--include-directories` only | no limit (sandbox off) |
| OS sandbox | no | yes (`workspace-write`) | no | no (gemini's needs docker / podman / bwrap; not used) | off (`DSH_PERMISSION_MODE=danger-full-access`: in its workspace-write sandbox the CLI itself fails on its uv cache) |
| network: resident / builder | yes / yes | no / yes | yes / yes | yes / yes | yes / yes |
| paid keys in the shell | stripped (`agent_env`), `GAMEANYTHING_GEN_OFF` | stripped, `shell_environment_policy` excludes | stripped; the model key is moved into a 0600 file the config points at (`{file:…}`), a `shell.env` plugin blanks credential-looking names and gives the shell its XDG folders back | stripped; gemini's own redaction hides `GEMINI_API_KEY` and every *KEY* / *TOKEN* / *SECRET* name from shell commands | stripped; the model's key (`DEEPSEEK_API_KEY` / `OPENROUTER_API_KEY`) and a DeepSeek key for search are moved into `$DSH_HOME/.env` (0600), which headless dsh reads; dsh rebuilds only `DSH_*` for its shell |
| per-run USD cap | `--max-budget-usd` | none | none | none | none |
| auth failure → one chat message, no retries | yes | yes | yes (401 / "User not found" / missing key) | yes ("API key not valid", "Please set an Auth method", …) | yes (`MISSING_CREDENTIAL`, `INVALID_CREDENTIAL`, "Authentication Fails", "Insufficient Balance") |
| model refused (old CLI, no access, unknown name) → one chat message, backoff until the model changes | yes (`claude_code_version_too_old`, "issue with the selected model") | yes ("model is not supported when using Codex") | yes (OpenRouter 403 terms of service) | yes ("is not found for API version") | yes ("is not a valid model ID" from OpenRouter, "Model Not Exist" from DeepSeek) |
| per-user login on a hub | config dir / token / key | CODEX_HOME / key | `opencode_home` + the key of her model's provider (`opencode_model`) | `gemini_home` + `GEMINI_API_KEY` (or a Google login in that home) | `dsh_home` + the key of `dsh_model`'s provider: `DEEPSEEK_API_KEY`, or `OPENROUTER_API_KEY` for `openrouter/...` |

What cannot be matched, and how it is covered:
- **DeepSeek Harness has no command deny list and runs without its sandbox**: the weakest guard of the five. Its only guard is the
  missing paid keys (`agent_env`, `GAMEANYTHING_GEN_OFF`; paid calls only via `gameanything gen request` after her cards). 0.2.2-alpha.2 adds `--add-dir`
  grants to its workspace-write sandbox; a sandboxed run needs at least the uv cache, the requests folder and, for a builder, the lab and
  build caches writable, and has not been tried. Tested with 0.2.1-rc.2, and again with 0.2.1-rc.5 (npm latest on 2026-10-31), against a local stand-in for DeepSeek's Messages
  endpoint: launch, session and resume, the patch rows, telemetry off, no key in the shell, the CLI working in the run's shell; and with an
  OpenRouter model (`openrouter/deepseek/deepseek-v4-pro`) against a local stand-in for OpenRouter's chat completions: every model call
  of the run (the agent's steps and the session title) went to OpenRouter. `web_search`: DeepSeek's own search with a DeepSeek key;
  with only the OpenRouter key, gameanything's plugin `plugins/dsh-web-search-openai-compatible` (loaded by dsh from the install by file URL,
  `perplexity/sonar` on OpenRouter, the same key from `$DSH_HOME/.env`), checked with the real dsh against a local stand-in for each
  source shape it reads, an HTTP 401 and a missing key. One run with a real key (2026-11-01, 0.2.1-rc.5, `openrouter/deepseek/deepseek-v4.1-flash`, launched by `Dsh.launch` as agentd does): the agent ran `gameanything native ready` in its shell and replied with the output, the key was not in the event log. No build yet. With agent isolation on, the run's dsh
  home is the account's (`isolation.run_env` / `after_launch`, like OpenCode's) and `isolation_setup` grants dsh's node_modules: not tried
  with real agent accounts yet. On a shared server without isolation a dsh run can touch whatever the service account can.
- **No OS sandbox for OpenCode and Gemini CLI** (as for Claude Code): their shell can reach the network and write outside the project.
  Covered by the same deny list, by the missing paid keys (`agent_env`, `GAMEANYTHING_GEN_OFF`: `keys.get()` refuses in a run, paid calls only via
  `gameanything gen request` after her cards) and by the file tools being limited to the project and the run's folders.
- **The agent's own login file is readable by the run** (Claude's `.credentials.json`, Codex's `auth.json`, OpenCode's key file,
  Gemini's `oauth_creds.json`, DeepSeek Harness's `$DSH_HOME/.env`): every CLI needs it; none of them is a paid generation key, and nothing in gameanything reads it for generation.
- **Gemini hides `GAMEANYTHING_KEYS_FILE`** from shell commands (its name has KEY): runs get the same value as `GAMEANYTHING_USER_ENV_FILE` (keys.py reads both).
- **OpenCode sets XDG_* for its own process**: the `shell.env` plugin hands the shell the folders it had before, so `gameanything` and other tools in
  the shell use the user's real folders.
- **No per-run dollar cap** for Codex, OpenCode, Gemini and DeepSeek Harness: the go card shows the estimate (`gameanything estimate`), OpenCode reports the cost of
  every step in its event stream (`agent_providers.usage`).

**Her confirmations** (`gameanything/decisions.py`, since 2026-10-30). A confirmation on a page (「确认这一天」, 「就按这个做」, the 场景 / 角色 / 需求 /
机制映射 confirmations, a plan card approval, the people page) counts only when the page server signed it into
`conversation/.user_decisions.jsonl`:
- **Signing**: Ed25519 (`ed25519.py`). The private key is made when `gameanything ui` / `gameanything hub` starts and lives only in that process's
  memory; its public key is appended to `<config>/gameanything/server/decision-keys.txt`. `flow check`, agentd and the pages verify with public keys
  only, so nothing on disk lets a run sign. `decisions.record` in any other process raises `NotTheServer`. The signature covers the project id
  (`config/project.yaml id`), so moving or copying a project keeps her confirmations; an import through the page signs them again.
- **Strict projects**: a project is under this rule when it has a ledger, when `config/project.yaml` says `decisions: strict`, or when the
  server's `strict-projects.txt` has its id. A strict project whose ledger is gone has no confirmations, and `flow check` reports it as
  tampering. Projects that never had a ledger keep the old rule, where the review files alone count.
- **The decision POSTs** (`ui/__init__.py DECISION_POST`) need the page's Origin and a decision cookie. That cookie is HttpOnly and
  SameSite=Strict, the server keeps it only in memory and makes a new one at every start, and it is set only on a page a browser loads
  (`Sec-Fetch-Dest: document | iframe`). In the hub they need the Origin as well as her login cookie.
- **Runs**: every provider gets `agent_providers.DENY_DECISIONS`, which covers the ledger, the server folder, the signing code and curl to
  the decision endpoints. Claude Code also has file-tool rules for the ledger and the server folder; Gemini has policy rules for both. Codex's
  sandbox cannot write outside the project at all.
- **What is left** when she, the server and the agents all run as one OS user: a run that gets past the deny patterns, for example by writing a
  script file and running it, can still append its own public key to `decision-keys.txt`, or fetch the page the way a browser does to get the
  cookie. Each of these takes a deliberate effort against explicit rules, and none happens by accident. Full isolation needs the agent CLIs to
  run as a different OS user from the server, so that they cannot write the server folder. GameAnything does not do that yet.
- **Upgrade**: ledgers signed the old way (an HMAC key in the data folder) keep counting until the new server first starts. That start
  signs them again with the new key, deletes the old key file and writes `legacy-closed`. Until then, only the old key the new code saw
  first is accepted (`legacy-key.sha256`).

## DeepSeek Harness setup

[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (`dsh`) can answer your project chats in the background with a
DeepSeek or OpenRouter API key. When you press Start, it runs the build too: wired, but not yet tested end to end.

```bash
npm install -g @deepseek-ai/dsh                  # tested: 0.2.1-rc.2 and rc.5 (npm latest)

# with a DeepSeek key (make one on platform.deepseek.com)
export DEEPSEEK_API_KEY=sk-...
GAMEANYTHING_AGENT_PROVIDER=dsh gameanything ui           # or: gameanything agentd run --provider dsh

# or with an OpenRouter key: the model is openrouter/<the model's name on OpenRouter>
export OPENROUTER_API_KEY=sk-or-...
GAMEANYTHING_AGENT_PROVIDER=dsh GAMEANYTHING_DSH_MODEL=openrouter/deepseek/deepseek-v4.1-flash gameanything ui
```

To use it by hand instead (not as the background agent): clone the repo, start `dsh web` and add the clone with **Add workspace**
(it reads `AGENTS.md` and `.agents/skills`).

- **Weaker guard than the other agents:** no command deny list, and its file sandbox is off (the CLI itself cannot run inside it); see the
  table above. On a shared server, turn on agent isolation (`agent_users`) before you offer it.
- **Developer preview:** its authors announce breaking changes.

- **Model:** `deepseek-v4-pro` by default; `GAMEANYTHING_DSH_MODEL=deepseek-flash` (or `--model deepseek-flash`) for a cheaper one. A model
  written as `openrouter/...` goes through OpenRouter, with every model call of the run (replies, session titles, summaries of long
  conversations).
- **Web search:** with a DeepSeek key, dsh's own search (DeepSeek's API). With an OpenRouter key alone, each search goes to `perplexity/sonar`
  on OpenRouter with the same key, through the plugin [plugins/dsh-web-search-openai-compatible](../plugins/dsh-web-search-openai-compatible/README.md)
  (about half a cent per search). `GAMEANYTHING_DSH_SEARCH_MODEL` picks another OpenRouter model, which then searches with OpenRouter's web
  search tool (beta). The plugin works with any OpenAI-compatible endpoint, so it also works in your own dsh.
- **Shared server (`gameanything hub`):** in "My agent" choose DeepSeek Harness, enter the model if you want another one (for OpenRouter:
  `openrouter/deepseek/deepseek-v4-pro`), then paste the matching key. An admin can also run `gameanything hub user agent <name> dsh` and
  `gameanything hub user model <name> dsh <model>`.
- **Per project:** once the owner can run it, DeepSeek Harness is offered in the chat page's *Chat* / *Build* chips, with a typed model
  (a DeepSeek model, or `openrouter/...` when that key is there).
- **What each run gets:** its own dsh home (your own `~/.dsh`, its saved keys and `AGENTS.md` are not used), no skills, MCP servers or helper
  agents, dsh telemetry off, the key kept out of the agent's shell, and no paid-generation keys (paid pictures only through your cards).
  On a shared server without agent isolation (`agent_users`), a dsh run can read and write whatever the service account can.
- **Cost:** billed per token to your DeepSeek or OpenRouter balance. `gameanything estimate` has no prices for DeepSeek's own API yet, so the
  go card shows the time but no dollar figure; `openrouter/deepseek/deepseek-v4-pro`, `-v4-flash` and `-v4.1-flash` use OpenRouter's price
  (checked 2026-10-31), other `openrouter/deepseek/...` models an unverified one. Web searches are not in the estimate.
