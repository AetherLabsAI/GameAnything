#!/usr/bin/env bash
# SessionStart hook (Claude Code): put gameanything's bin/ on PATH for every later Bash call in the session, so the skill can just
# say `gameanything ...` in a clone or a plugin install. Arg 1: the root (the plugin root or the cloned repo). Does nothing when `gameanything` is
# already on PATH (`uv tool install`), so an installed CLI is never shadowed. Recent Claude Code also adds a plugin's bin/ by itself.
root="${1:-${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-}}}"
# Windows (Git Bash): the root arrives as C:/..., whose colon would split PATH into "C" and "/Users/...".
[ -n "$root" ] && command -v cygpath >/dev/null 2>&1 && root="$(cygpath -u "$root")"
[ -n "$root" ] && [ -n "${CLAUDE_ENV_FILE:-}" ] && [ -x "$root/bin/gameanything" ] || exit 0
command -v gameanything >/dev/null 2>&1 && exit 0
grep -qsE "(gameanything|memory2world)-path" "$CLAUDE_ENV_FILE" && exit 0     # memory2world-path: written before the rename
printf 'export PATH="%s/bin:$PATH"  # gameanything-path\n' "$root" >> "$CLAUDE_ENV_FILE"
exit 0
