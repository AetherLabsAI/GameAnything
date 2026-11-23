/**
 * gameanything: OpenCode 2 plugin.
 *
 * One passthrough tool, `gameanything_run`, that runs the `gameanything` CLI the way a person would type it. The plugin never
 * reimplements gameanything: the CLI stays the single source of truth, and its skill tells the agent which commands to run.
 * Skills come from a clone (`.agents/skills`, `.claude/skills`) or `npx skills add`, not from this plugin.
 */
import { spawn } from "node:child_process"
import { accessSync, constants } from "node:fs"
import { homedir } from "node:os"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

import { Plugin } from "@opencode/plugin"

/** plugins/opencode/index.ts -> repository root */
const PLUGIN_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..")

/**
 * The top-level `gameanything` commands (the subparsers in gameanything/cli.py). Named in the tool description and used to
 * answer a typo without spawning the CLI. tests/test_plugins.py checks this list against `gameanything --help`.
 */
const GROUPS = [
  { name: "lab", blurb: "seats in the shared lab sandboxes" },
  { name: "extras", blurb: "optional features (speech to text, person boxes), installed after the user's yes on a card" },
  { name: "ingest", blurb: "inventory a folder of memories into the project (local, no model)" },
  { name: "perceive", blurb: "one model call per item, only after a permission card" },
  { name: "ui", blurb: "the local browser UI the user works in" },
  { name: "art", blurb: "Stardew walk sprites and portraits" },
  { name: "video", blurb: "contact sheet of a video" },
  { name: "status", blurb: "project README and development status" },
  { name: "lessons", blurb: "what builders and playtesters learned" },
  { name: "feedback", blurb: "her feedback as records: reading, confirmation, before / after, repeat rate" },
  { name: "profile", blurb: "her private preference profile" },
  { name: "chat", blurb: "read what the user said, answer with text / cards / progress" },
  { name: "estimate", blurb: "what a build round may cost" },
  { name: "build", blurb: "watch and report builds" },
  { name: "agentd", blurb: "the background supervisor that answers project chats" },
  { name: "gen", blurb: "queue paid generation (agentd checks the cards and runs it)" },
  { name: "hub", blurb: "several users on one server" },
  { name: "i18n", blurb: "English for the project's content" },
  { name: "text", blurb: "text tools for adaptation projects" },
  { name: "demo", blurb: "a read-only, clickable copy of the UI on one project, as static files" },
  { name: "project", blurb: "new / list / open / settings / export / import" },
  { name: "backup", blurb: "optional automatic backup" },
  { name: "game", blurb: "the game packages: list, scaffold, check" },
  { name: "native", blurb: "the user's own copy of the game: doctor, saves, mods, launch (only with her yes)" },
  { name: "flow", blurb: "the step to work on next and its exit criteria" },
  { name: "setup", blurb: "the setting guide to read for this computer and mode (records it in the project)" },
  { name: "refs", blurb: "reference pictures of public places, only after a websearch card" },
  { name: "visuals", blurb: "keyframes and people crops from an adaptation's videos" },
  { name: "adaptation", blurb: "adaptation data tools" },
]

const GROUP_NAMES = new Set(GROUPS.map((group) => group.name))

/** `~` and `~/...` as the user's home; relative paths against `base`. */
function expandPath(path: string, base: string): string {
  if (path === "~") return homedir()
  if (path.startsWith("~/") || path.startsWith("~\\")) return join(homedir(), path.slice(2))
  return resolve(base, path)
}

function resolveCli(root: string, override?: string): string {
  if (override) return override
  // bin/gameanything is a bash script, which Windows cannot spawn directly; there `gameanything` (uv tool install: gameanything.exe) must be on PATH.
  if (process.platform === "win32") return "gameanything"
  const local = join(root, "bin", "gameanything")
  try {
    accessSync(local, constants.X_OK)
    return local
  } catch {
    return "gameanything"
  }
}

function run(
  command: string,
  args: string[],
  cwd: string,
  signal: AbortSignal,
): Promise<{ code: number; out: string; err: string }> {
  return new Promise((done) => {
    // PYTHONUTF8: gameanything prints Chinese; on Windows the default pipe encoding would garble it.
    const child = spawn(command, args, { cwd, signal, env: { ...process.env, PYTHONUTF8: "1" } })
    let out = ""
    let err = ""
    child.stdout?.setEncoding("utf8")
    child.stderr?.setEncoding("utf8")
    child.stdout?.on("data", (chunk) => (out += chunk))
    child.stderr?.on("data", (chunk) => (err += chunk))
    child.on("error", (error) => done({ code: -1, out, err: `${err}${String(error)}` }))
    child.on("close", (code) => done({ code: code ?? -1, out, err }))
  })
}

export default Plugin.define({
  id: "gameanything",
  async setup(ctx) {
    const project = ctx.location.directory
    const root = typeof ctx.options.root === "string" ? expandPath(ctx.options.root, project) : PLUGIN_ROOT
    const cli = resolveCli(root, typeof ctx.options.command === "string" ? ctx.options.command : undefined)

    await ctx.tool.transform((editor) => {
      editor.namespace({
        name: "gameanything",
        description: `GameAnything CLI (${cli}): turn the user's memories into playable content in a game they own. ` +
          "Follow the gameanything skill; it says which gameanything commands to run and which need the user's yes first.",
      })

      editor.add({
        name: "run",
        description:
          "Run the GameAnything `gameanything` CLI. `args` is the command line after `gameanything`, e.g. " +
          `["project", "list"], ["flow", "next", "--project", "<id>"], ["chat", "read", "--project", "<id>", "--session", "<s>"], ` +
          `["native", "doctor"], ["<group>", "--help"]. Long waits (\`chat wait\`, builds) belong in the background, not here. ` +
          "Groups: " + GROUPS.map((group) => group.name).join(", ") + ".",
        input: {
          type: "object",
          properties: {
            args: {
              type: "array",
              items: { type: "string" },
              description: "Arguments for `gameanything`, e.g. [\"project\", \"list\"] or [\"chat\", \"--help\"].",
            },
            cwd: { type: "string", description: "Working directory. Defaults to the project directory." },
          },
          required: ["args"],
          additionalProperties: false,
        },
        options: { namespace: "gameanything", codemode: true },
        execute: async (input, context) => {
          const parsed = (input ?? {}) as { args?: string[]; cwd?: string }
          const args = parsed.args ?? []
          const cwd = parsed.cwd ? expandPath(parsed.cwd, project) : project
          const head = args[0]

          if (head && !head.startsWith("-") && !GROUP_NAMES.has(head)) {
            return {
              content:
                `unknown gameanything command "${head}". Commands: ${GROUPS.map((group) => group.name).join(", ")}. ` +
                "Run [\"--help\"] or [\"<command>\", \"--help\"] for details.",
            }
          }

          const result = await run(cli, args, cwd, context.signal)
          const body = [result.out.trimEnd(), result.err.trimEnd()].filter(Boolean).join("\n")
          return {
            content: `gameanything ${args.join(" ")}` +
              `${result.code === 0 ? "" : ` (exit ${result.code})`}\n\n${body || "(no output)"}`,
          }
        },
      })
    })
  },
})
