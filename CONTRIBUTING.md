# Contributing

Thanks for helping. Run the tests before a pull request (`python -m pip install -e . pytest`, then `python -m pytest -q`; add `.[dev]` for
Playwright, used for headless screenshots of the web page); CI runs
them on Linux, Windows and macOS with fake game folders (docs/cross-platform.md). Keep pull requests focused, and never commit
personal materials, saves, keys or game files.

## Adding a game

Bring your favourite game into GameAnything as a **game package**. Full guide (for people and agents):
[skills/gameanything/references/add-a-game.md](skills/gameanything/references/add-a-game.md); worked example:
`gameanything/games/terraria/`; every game: [docs/games.md](docs/games.md).

1. **Recon and legality first.** The game needs a real mod loader route. Never ship game files, never bypass DRM / ownership checks,
   never touch anti-cheat or online play; tests use throwaway local saves only.
2. **Scaffold:** `gameanything game new <id> --title "<Game>" --loader <type> --engine <engine> --steam-appid <appid>` (in this checkout), or
   `--plugin <folder>` for a separate pip-installable plugin (entry point group `gameanything.games`; no fork needed).
3. **Fill** `game.yaml` (folders per system, saves, logs, process names, launch, toolchain, loader, the wizard's text in Chinese and
   English), `adapter.py` (build / checks / the loader's switch, only what game.yaml cannot say) and the smoke mod (logs
   `[M2W-smoke] loaded`, shows one thing on screen), and `LESSONS.md` (what builders / playtesters learned about the game, sections
   `## 开发` / `## 试玩`; format in skills/gameanything/references/lessons.md; `gameanything lessons add --game <id> …`).
4. **Validate:** `gameanything game check <id>` (and `--build` on a machine with the game), fake-folder tests in `tests/games/test_<id>.py`,
   `python -m pytest -q`.
5. **Verify on a real copy** (the native round trip in the guide): doctor -> build -> check -> backup -> install -> launch (with the
   user's yes) -> the smoke mod in the log + a screenshot -> close -> restore (byte-identical) -> uninstall.
6. **Docs:** `gameanything game list --write-docs`, a section in docs/games.md, the result row in docs/cross-platform.md and
   `verified:` in game.yaml.
7. Open the PR with the "Adding a game" checklist of the pull request template.

### Pull request checklist for a new game

- [ ] Recon written down: engine, loader (name, version, official URL), folders per system, cloud-save behaviour
- [ ] Legality: no game files / decompiled code in the PR, no DRM or ownership bypass, no anti-cheat or online play touched
- [ ] `gameanything game check <id>` prints `ok`; `python -m pytest -q` passes
- [ ] Fake-folder tests: folders on Linux, Windows and macOS, install / switch / uninstall, backup / restore, build with a stand-in toolchain
- [ ] Real round trip on: Windows / macOS / Linux (say which); evidence attached: `gameanything native doctor --game <id> --json`, the log lines
      with `[M2W-smoke] loaded`, one screenshot, restore byte-identical
- [ ] `docs/games.md` table regenerated + the game's section; result row in docs/cross-platform.md
- [ ] What is not automatable is said honestly (reload through a menu, launch options she sets once, ...)

## The skill and the plugin manifests
- Edit `skills/gameanything/` only. `.agents/skills/gameanything` and `.claude/skills/gameanything` are copies (not symlinks, so Windows
  clones work) for the agents that look there in a clone; refresh them with `python tools/sync_skills.py`. `tests/test_plugins.py`
  fails while they differ (`python tools/sync_skills.py --check` lists what differs). A lesson confirmed with `gameanything lessons review`
  changes `skills/gameanything/references/lessons/`, so sync before committing it.
- One manifest per agent, all named `gameanything` with the version from `pyproject.toml` (Claude Code's `.claude-plugin/plugin.json`
  has none on purpose, so every commit is an update): `plugin.json` (Agent Plugins: VS Code / Copilot, Codex, Cursor),
  `.claude-plugin/`, `.codex-plugin/` + `.agents/plugins/marketplace.json`, `.cursor-plugin/`, `gemini-extension.json`, `opencode.json`,
  `plugins/opencode/` (OpenCode 2). Codex caches an installed plugin by version: bump the version when a release should reach Codex users.
- A new top-level `gameanything` command also goes into `GROUPS` in `plugins/opencode/index.ts` (a test checks it).
