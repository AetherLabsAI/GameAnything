# GameAnything: OpenCode plugin

Exposes the `gameanything` CLI as one OpenCode tool, `gameanything_run` (it was `gameanything_run` before the rename). It uses the OpenCode 2 plugin API (`@opencode/plugin`,
`Plugin.define`), so it needs OpenCode 2; OpenCode 1.x does not load it. Written after the plugin in
rehan-remade/universal-modder; not yet run in a real OpenCode 2 session (no OpenCode on the test machine).

## Install

A clone does not need it: run `opencode` inside the clone; it reads `AGENTS.md` (`opencode.json`) and finds the skill in
`.agents/skills` / `.claude/skills`, and `bin/gameanything` is there (`export PATH="$PWD/bin:$PATH"`).

Without a clone, point OpenCode 2 at this folder in your global `opencode.json`, and install the CLI and the skill:

```jsonc
{
  "plugins": [
    { "package": "/path/to/gameanything/plugins/opencode", "options": { "command": "gameanything" } }
  ]
}
```
```sh
uv tool install git+https://github.com/AetherLabsAI/GameAnything      # the gameanything CLI the tool runs
npx skills add https://github.com/AetherLabsAI/GameAnything -a opencode # the skill
```

Options: `root` = a checkout whose `bin/gameanything` to run (default: the checkout this plugin sits in); `command` = the
launcher itself (e.g. `"gameanything"` for a `uv tool install`ed CLI). On Windows it always runs `gameanything` from PATH (or `command`),
because `bin/gameanything` is a bash script.

## What it adds

- **One tool, `gameanything_run`.** `args` is the command line after `gameanything`: `["project", "list"]`, `["flow", "next", "--project", "<id>"]`,
  `["chat", "--help"]`. An optional `cwd` sets the working directory (default: the project directory). An unknown command
  is answered with the command list instead of spawning the CLI.
- Nothing else: no MCP server, no skills, no background jobs. Long waits (`gameanything chat wait`, builds) are for the agent's own
  background shell or for `gameanything agentd`.

`tests/test_plugins.py` checks the command list in `index.ts` against `gameanything --help`.
