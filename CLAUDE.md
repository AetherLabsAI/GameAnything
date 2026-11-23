@AGENTS.md

## Claude Code
- As a plugin the skill is `/gameanything:gameanything`, and `gameanything` is on PATH (the plugin's `bin/gameanything`, plus the SessionStart hook in
  `hooks/hooks.json` for older versions); it runs the plugin checkout's code through uv. A `uv tool install`ed gameanything works the same.
- In a clone, `.claude/settings.json` adds the same PATH hook and `.claude/skills/gameanything` is a copy of `skills/gameanything`
  (edit only `skills/`, then `python tools/sync_skills.py`).
- Run the `gameanything chat wait` loop with `run_in_background`; you are notified when it exits.
