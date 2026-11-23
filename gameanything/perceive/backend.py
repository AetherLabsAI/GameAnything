"""Model backends for perceive. Default: the user's own Claude Code CLI in headless mode (no API key to configure).

    GAMEANYTHING_CLAUDE   the command to run (default "claude"); any wrapper that behaves like `claude` works
"""
import json
import os
import shutil
import subprocess
import time


class ClaudeCode:
    name = "claude-code"

    def __init__(self, model, cmd=None, max_turns=8, timeout=600):
        self.model, self.cmd = model, cmd or os.environ.get("GAMEANYTHING_CLAUDE", "claude")
        self.max_turns, self.timeout = max_turns, timeout

    def call(self, prompt: str, schema: dict, cwd) -> tuple:
        """-> (structured output dict, {cost_usd, turns, seconds}). The prompt goes in on stdin; only Read is allowed."""
        args = [shutil.which(self.cmd) or self.cmd, "-p",                  # which: finds claude.exe / claude.cmd on Windows (PATHEXT)
                "--model", self.model, "--output-format", "json", "--allowedTools", "Read",
                "--max-turns", str(self.max_turns), "--json-schema", json.dumps(schema)]
        t0 = time.time()
        r = subprocess.run(args, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(cwd), timeout=self.timeout)
        if r.returncode != 0 and not r.stdout.strip():
            raise RuntimeError(f"{self.cmd} exited {r.returncode}: {r.stderr.strip()[-500:]}")
        j = json.loads(r.stdout)
        out = j.get("structured_output")
        if out is None:                                   # older CLIs: the JSON is in the text result
            txt = (j.get("result") or "").strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            out = json.loads(txt)
        if j.get("is_error"): raise RuntimeError(f"model error: {str(j.get('result'))[:500]}")
        return out, {"cost_usd": j.get("total_cost_usd"), "turns": j.get("num_turns"), "seconds": round(time.time() - t0, 1)}


BACKENDS = {"claude-code": ClaudeCode}
