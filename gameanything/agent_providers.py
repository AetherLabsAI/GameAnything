"""Headless coding-agent providers used by :mod:`gameanything.agentd`.

Keep provider-specific command lines, session discovery, authentication errors and
environment isolation here.  The daemon owns scheduling and chat semantics; a
provider only describes how one agent process is started and resumed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

import yaml

ROLES = ("resident", "builder")


@dataclass(frozen=True)
class Provider:
    binary: str
    model: str | None = None
    name: str = "provider"

    def new_session_id(self) -> str | None:
        return None

    def command(self, prompt: str, system: str, session_id: str | None, resume: bool,
                root: Path, budget: float | None = None, *, role: str = "resident", add_dirs=(), network: bool = False,
                shell_set: dict | None = None, env: dict | None = None) -> list[str]:
        """role resident | builder (the builder's deny list lets the lab tools run, they check GAMEANYTHING_LEASE); add_dirs: writable outside the
        project; network: the builder needs it for the lab; shell_set: env values the agent's shell must keep (Codex drops *KEY* names);
        env: the run's env (Codex: its CODEX_HOME holds the config whose machine settings are kept)."""
        raise NotImplementedError

    # the agent's OWN login variables: they stay in the run env; every other credential is stripped (agent_env)
    own_creds: tuple = ()

    def session_id(self, log: Path) -> str | None:
        return None

    def auth_failed(self, log: Path) -> bool:
        return _log_has(log, ("authentication_failed", "Not logged in", "OAuth access token is invalid"))

    def sandbox_failed(self, log: Path) -> bool:
        """True when the CLI's own command sandbox could not start on this machine (Codex's bwrap in a container): no retry helps."""
        return False

    def unavailable(self, env=None) -> str:
        """'' when this CLI can work on this machine; else why not (Codex: its sandbox cannot start here, codex_sandbox_probe)."""
        return ""

    def out_of_credit(self, log: Path) -> bool:
        """An `auth` failure that is really the key's balance (402 / insufficient credit), not a login: agentd logs it as such."""
        return _log_has(log, CREDIT_NEEDLES)

    def model_refused(self, log: Path) -> bool:
        """The CLI or the model service refused the chosen MODEL (the CLI is too old for it, the account has no access, an OpenRouter key
        whose provider terms forbid it): no retry helps, another model or a CLI update does."""
        return _log_has(log, MODEL_NEEDLES)

    def failure(self, log: Path) -> str | None:
        """Why a run's log says it could not work: sandbox | auth | model | None (usage limits: activity.scan_log)."""
        if self.sandbox_failed(log): return "sandbox"
        if self.auth_failed(log): return "auth"
        if self.model_refused(log): return "model"
        return None

    def clean_env(self, env: dict[str, str]) -> dict[str, str]:
        return env

    def creds(self, env=None) -> tuple:
        """The env names of this agent's own login that stay in a run (agent_env); every other credential is stripped."""
        return tuple(self.own_creds)

    def launch(self, prompt, system, session_id, resume, root, budget=None, *, role="resident", add_dirs=(), network=False,
               shell_set=None, env=None):
        """-> (command, env) of one run. Providers that keep per-run files (OpenCode's config and instructions, Gemini's settings and
        policy) write them here and change the env; the others only build the command line."""
        return self.command(prompt, system, session_id, resume, root, budget, role=role, add_dirs=add_dirs, network=network,
                            shell_set=shell_set, env=env), env


# the provider answered that the key has no credit left (402): an `auth` failure for the backoff, logged as "out of credit" (QA2 2026-10-30)
CREDIT_NEEDLES = ('"statusCode":402', "Insufficient credits", "insufficient credits", "Insufficient balance", "insufficient balance",
                  "Insufficient Balance", "402 Payment Required", "prepayment credits are depleted")
# the chosen model cannot be used (harness check 2026-10-31, this Mac): Claude Code 2.1.72 refused `--model fable` ("issue with the selected
# model") and claude-opus-5-5 (claude_code_version_too_old); an OpenRouter key got 403 "violation of provider Terms Of Service" for every
# Anthropic / OpenAI / Google model. Each was counted as a crash and retried three times. Codex 0.166 and Gemini 0.66 on a model name they
# do not know: "model is not supported when using Codex with a ChatGPT account", "models/<x> is not found for API version v1beta".
MODEL_NEEDLES = ("claude_code_version_too_old", "There's an issue with the selected model", "does not support this model",
                 "violation of provider Terms Of Service", "model is not supported when using Codex", "is not found for API version")


# WebSearch / WebFetch: residents and builders may look up PUBLIC places (landmark-references.md: only after her yes on a websearch card, no
# personal names in a query); pictures are saved only through `gameanything refs fetch` (refs.py), which checks the card and the query.
CLAUDE_TOOLS = ("Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch")


@dataclass(frozen=True)
class ClaudeCode(Provider):
    name: str = "claude-code"

    def new_session_id(self) -> str:
        # Claude accepts a caller-assigned UUID, which makes the first run resumable
        # even if the daemon is restarted before it can inspect the output log.
        return str(uuid.uuid4())

    own_creds: tuple = ("ANTHROPIC_*", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR")

    def command(self, prompt, system, session_id, resume, root, budget=None, *, role="resident", add_dirs=(), network=False, shell_set=None, env=None):
        if role not in ROLES: raise ValueError(f"role 应该是 {' / '.join(ROLES)}")
        cmd = [self.binary, "-p", prompt]
        if self.model: cmd += ["--model", self.model]
        cmd += ["--output-format", "stream-json", "--verbose", "--permission-mode", "dontAsk",
                "--tools", ",".join(CLAUDE_TOOLS), "--allowedTools", " ".join(CLAUDE_TOOLS),
                "--disallowedTools", *(DENY_BUILDER if role == "builder" else DENY_RESIDENT), *decision_file_rules(), "--append-system-prompt", system,
                "--strict-mcp-config", "--disable-slash-commands"]
        for d in add_dirs: cmd += ["--add-dir", str(d)]           # Read / Edit outside the project (dontAsk would refuse them)
        cmd += ["--resume", session_id] if resume else ["--session-id", session_id]
        if budget: cmd += ["--max-budget-usd", str(budget)]
        return cmd

    def session_id(self, log):
        # The assigned id is already stored before launch; this parser is useful for
        # imported logs and deliberately accepts only documented stream-json shapes.
        return _jsonl_session(log, ("session_id",))


CODEX_WEB_SEARCH = "live"
CODEX_OFF = ("image_generation", "apps", "plugins", "browser_use", "computer_use", "goals")
# --ignore-user-config drops the whole config.toml, also the operator's machine settings: sqlite_home (2026-10-26, the first real Codex run:
# ~/.codex/thread_history_1.sqlite was corrupt on this server's disk, the operator had moved the state DBs to /tmp with sqlite_home, and
# every `exec resume` failed in 4 s with "database disk image is malformed"). These keys are copied over; nothing else of the file is.
CODEX_MACHINE_KEYS = ("sqlite_home", "log_dir")
# What a run's prompt says first: Codex always loads $CODEX_HOME/AGENTS.md (the operator's own instructions, e.g. «take notes in
# agent_notes/») and lists the operator's skills; neither is meant for a gameanything run (the skill listing is switched off below).
CODEX_PREAMBLE = ("Only the instructions in this prompt apply to this run. Ignore any AGENTS.md or skill instructions loaded from the Codex "
                  "home or elsewhere (for example note-taking rules): never create files the step does not ask for (no agent_notes/).")


def codex_machine_conf(env=None) -> list:
    """`-c key=value` for the CODEX_MACHINE_KEYS set in $CODEX_HOME/config.toml (top-level string values only)."""
    env = os.environ if env is None else env
    home = Path(env.get("CODEX_HOME") or Path.home() / ".codex")
    try: text = (home / "config.toml").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError): return []
    out = []
    for line in text.splitlines():
        if re.match(r"\s*\[", line): break                        # the first [table]: top-level keys end here
        m = re.match(r"\s*([A-Za-z_]+)\s*=\s*(\"[^\"\n]*\"|'[^'\n]*')\s*(#.*)?$", line)
        if m and m.group(1) in CODEX_MACHINE_KEYS: out += ["-c", f"{m.group(1)}={m.group(2)}"]     # the TOML string as written
    return out


# Codex runs every command of the agent in its own sandbox (Linux: bubblewrap). In a container without the rights bwrap needs (2026-10-29,
# this server: "bwrap: Failed to make / slave: Permission denied") every command fails, so the run cannot do anything. The sandbox is
# never switched off for that: a cached probe (`codex sandbox -- true`) tells agentd and the model menu that Codex cannot work here.
CODEX_SANDBOX_ERRORS = ("bwrap:", "Failed to make / slave", "landlock", "seccomp", "Sandbox(Denied", "sandbox could not", "Failed to apply sandbox")
CODEX_PROBE_TTL = 6 * 3600


def codex_sandbox_probe(binary, env=None, run=None, clock=None) -> dict:
    """{ok, why, at}: can Codex's command sandbox start on this machine? Linux only (elsewhere: ok). Cached per codex binary (its path and
    mtime) for CODEX_PROBE_TTL in <data>/agent-homes/codex-sandbox.json. A probe that cannot tell (no codex, an older codex without
    `codex sandbox`, a timeout) counts as ok: only the known sandbox errors make Codex unavailable. GAMEANYTHING_CODEX_SANDBOX=ok|fail
    forces the answer (tests, an operator who knows)."""
    import subprocess, sys, tempfile, time
    env = os.environ if env is None else env
    clock = clock or time.time
    force = (env.get("GAMEANYTHING_CODEX_SANDBOX") or os.environ.get("GAMEANYTHING_CODEX_SANDBOX") or "").lower()
    if force in ("ok", "fail"):
        return {"ok": force == "ok", "why": "" if force == "ok" else "bwrap: forced by GAMEANYTHING_CODEX_SANDBOX=fail", "at": None}
    if not sys.platform.startswith("linux"): return {"ok": True, "why": "", "at": None}
    exe = shutil.which(str(binary)) or str(binary)
    try: key = f"{Path(exe).resolve()}|{int(Path(exe).stat().st_mtime)}"
    except OSError: return {"ok": True, "why": "", "at": None}
    from . import projects
    cf = projects.data_dir() / "agent-homes" / "codex-sandbox.json"
    try: c = json.loads(cf.read_text(encoding="utf-8"))
    except (OSError, ValueError): c = {}
    if isinstance(c, dict) and c.get("key") == key and clock() - float(c.get("t") or 0) < CODEX_PROBE_TTL:
        return {"ok": bool(c.get("ok")), "why": c.get("why") or "", "at": c.get("at")}
    run = run or subprocess.run
    ok, why = True, ""
    try:
        with tempfile.TemporaryDirectory() as td:
            # in the temp folder (cwd): `-C` needs --permission-profile in codex 0.160
            r = run([exe, "sandbox", "--", "true"], cwd=td, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                    env={k: v for k, v in env.items() if not k.startswith("CODEX_") or k == "CODEX_HOME"})
        out = f"{r.stdout or ''}\n{r.stderr or ''}"
        if r.returncode != 0 and any(n.lower() in out.lower() for n in CODEX_SANDBOX_ERRORS):
            ok = False; why = next((ln.strip() for ln in out.splitlines() if any(n.lower() in ln.lower() for n in CODEX_SANDBOX_ERRORS)), out.strip())[:200]
    except (OSError, subprocess.SubprocessError, ValueError): pass
    from datetime import datetime
    at = datetime.now().isoformat(timespec="seconds")
    try: _write_if_changed(cf, json.dumps({"key": key, "t": clock(), "ok": ok, "why": why, "at": at}))
    except OSError: pass
    return {"ok": ok, "why": why, "at": at}


@dataclass(frozen=True)
class Codex(Provider):
    name: str = "codex"

    own_creds: tuple = ("CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "CODEX_HOME", "OPENAI_BASE_URL")

    def command(self, prompt, system, session_id, resume, root, budget=None, *, role="resident", add_dirs=(), network=False, shell_set=None, env=None):
        if budget is not None:
            raise ValueError("Codex CLI has no per-run USD budget flag; omit --budget-usd")
        if role not in ROLES: raise ValueError(f"role 应该是 {' / '.join(ROLES)}")
        combined = f"<{role}-system-prompt>\n{CODEX_PREAMBLE}\n\n{system}\n</{role}-system-prompt>\n\n{prompt}"
        # Sandbox (codex 0.160): workspace-write = the project (+ /tmp, $TMPDIR) and every --add-dir writable, the rest read only; no
        # network unless sandbox_workspace_write.network_access (the builder: the lab's docker socket and HTTP bridges). No approvals
        # (exec never asks). `exec resume` has no --sandbox / --cd / --add-dir: the same settings go as -c overrides, or a resumed run
        # would fall back to the read-only default. --ignore-rules: the operator's own execpolicy `allow` rules must not apply here.
        # Shell env: codex drops every variable whose name has KEY / SECRET / TOKEN from the agent's commands (default excludes, kept
        # on explicitly); exclude adds the other credential names; set puts back what GameAnything needs (GAMEANYTHING_KEYS_FILE).
        # Features off (CODEX_OFF): image_generation is paid generation on her account outside the go / permission cards; apps (connectors),
        # plugins, browser / computer use could send her things out or take the screen (native mode: the game window is never focused).
        dirs = [str(d) for d in add_dirs]
        conf = ["-c", "shell_environment_policy.ignore_default_excludes=false",
                "-c", 'shell_environment_policy.exclude=["*CREDENTIALS*", "*PASSWORD*", "AWS_*", "GOOGLE_*", "GEMINI_*", "OPENAI_*", "ANTHROPIC_*"]']
        if shell_set: conf += ["-c", "shell_environment_policy.set={" + ", ".join(f"{k}={json.dumps(str(v))}" for k, v in sorted(shell_set.items())) + "}"]
        # skills: the operator's own skills (imagegen, ...) are not listed to a run. Web search (web_search: disabled | cached | indexed |
        # live) runs on OpenAI's side, not in the sandbox: "live" for residents and builders, so they can look up PUBLIC places after her
        # yes on a websearch card (landmark-references.md). A resident's sandbox still has no network: pictures are downloaded by agentd
        # on the host through `gameanything refs fetch` (refs.py checks the card and the query first).
        conf += ["-c", "skills.include_instructions=false"] + codex_machine_conf(env) + ["-c", f"web_search={json.dumps(CODEX_WEB_SEARCH)}"]
        if network: conf += ["-c", "sandbox_workspace_write.network_access=true"]
        for f in CODEX_OFF: conf += ["--disable", f]
        if resume:
            cmd = [self.binary, "exec", "resume", "--json", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
                   "-c", 'sandbox_mode="workspace-write"', "-c", f"sandbox_workspace_write.writable_roots={json.dumps(dirs)}", *conf]
            if self.model: cmd += ["--model", self.model]
            return cmd + [str(session_id), combined]
        cmd = [self.binary, "exec", "--json", "--ignore-user-config", "--ignore-rules", "--sandbox", "workspace-write",
               "--skip-git-repo-check", "--cd", str(root)]
        for d in dirs: cmd += ["--add-dir", d]
        cmd += conf
        if self.model: cmd += ["--model", self.model]
        return cmd + [combined]

    def session_id(self, log):
        # codex exec emits {"type":"thread.started","thread_id":"..."} first.
        return _jsonl_session(log, ("thread_id", "session_id"))

    def auth_failed(self, log):
        if self.sandbox_failed(log): return False                 # the sandbox error is not a login problem (QA 2026-10-29)
        return _log_has(log, ("401 Unauthorized", "not logged in", "login required", "authentication failed"))

    def sandbox_failed(self, log):
        return _log_has(log, CODEX_SANDBOX_ERRORS)

    def unavailable(self, env=None):
        p = codex_sandbox_probe(self.binary, env)
        return "" if p.get("ok") else (p.get("why") or "sandbox")

    def clean_env(self, env):
        # A daemon launched from an interactive Codex session must not make child
        # runs look like nested turns.  Keep login/config and API-key variables.
        keep = {"CODEX_HOME", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "OPENAI_API_KEY"}
        return {k: v for k, v in env.items() if not k.startswith("CODEX_") or k in keep}


# ---------------------------------------------------------------- shared by the providers that keep an m2w-owned agent home
def agent_home(env, var: str, sub: str) -> Path:
    """The agent CLI's own home for GameAnything runs: $<var> (a hub user's, users.user_env), else <data dir>/agent-homes/<sub> (the operator's
    machine). Never the operator's own ~/.config/opencode or ~/.gemini: their config, skills, MCP servers and instructions stay out."""
    v = (env or {}).get(var)
    if v: return Path(v).expanduser()
    from . import projects
    return projects.data_dir() / "agent-homes" / sub


def _write_private(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh: fh.write(text)
    os.replace(tmp, p)
    try: os.chmod(p, 0o600)
    except OSError: pass


def _write_if_changed(p: Path, text: str, private=False):
    try:
        if p.read_text(encoding="utf-8") == text: return
    except (OSError, UnicodeDecodeError): pass
    if private: _write_private(p, text)
    else:
        p.parent.mkdir(parents=True, exist_ok=True); tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
        tmp.write_text(text, encoding="utf-8"); os.replace(tmp, p)


def _prune(d: Path, pattern: str, keep_secs=2 * 86400):
    import time
    for f in d.glob(pattern):
        try:
            if time.time() - f.stat().st_mtime > keep_secs: f.unlink()
        except OSError: pass


def decision_file_rules() -> list:
    """Claude Code file-tool rules: the ledger in any project and the server's key folder (decisions.keys_dir) are not read or written."""
    from . import decisions
    try: kd = Path(decisions.keys_dir()).expanduser().resolve().as_posix()
    except (OSError, RuntimeError): kd = None
    out = [f"{t}(**/{decisions.LEDGER})" for t in ("Edit", "Write")]
    if kd: out += [f"{t}(/{kd}/**)" for t in ("Read", "Edit", "Write")]
    return out


def _deny_globs(role) -> list:
    """The Claude deny list (Bash(<glob>)) as bare command globs."""
    return [d[5:-1] for d in (DENY_BUILDER if role == "builder" else DENY_RESIDENT)]


# ---------------------------------------------------------------- a private temp folder per run
# Every agent run (resident or builder, any provider) gets its own TMPDIR: runs inherited the daemon's shared one, and a card file written
# under a fixed name ($TMPDIR/go.yaml) by one project's run was posted by another project's run, in another chat (hotfix 2026-10-30).
RUN_TMP = "gameanything-runs"
RUN_TMP_KEEP_SECS = 2 * 86400             # longer than any build may run (wall_hours <= 12); an ended run's folder is removed at once


def run_tmp_base() -> Path:
    """<system temp>/gameanything-runs (GAMEANYTHING_RUN_TMP_BASE overrides: tests)."""
    import tempfile
    o = os.environ.get("GAMEANYTHING_RUN_TMP_BASE")
    if o: return Path(o)
    from . import isolation
    if isolation.enabled(): return isolation.agent_root() / "runs"           # agent accounts reach it (docs/agent-isolation.md)
    return Path(tempfile.gettempdir()) / RUN_TMP


def run_tmpdir(project_id, run_id) -> Path:
    """A new empty folder <system temp>/gameanything-runs/<project id>--<run id> (0700); old ones of runs that never ended are pruned."""
    import re, shutil, time
    base = run_tmp_base(); base.mkdir(parents=True, exist_ok=True)
    from . import isolation
    try: os.chmod(base, 0o711 if isolation.enabled() else 0o700)      # isolation: each account enters its own run folder (0700, its own)
    except OSError: pass
    for d in base.iterdir():
        try:
            if d.is_dir() and time.time() - d.stat().st_mtime > RUN_TMP_KEEP_SECS: shutil.rmtree(d, ignore_errors=True)
        except OSError: pass
    safe = lambda x: re.sub(r"[^A-Za-z0-9_.-]+", "_", str(x))[:80] or "x"
    d = base / f"{safe(project_id)}--{safe(run_id)}"
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    return d


def with_run_tmp(env: dict, tmp) -> dict:
    """The run's env with TMPDIR / TMP / TEMP (and GAMEANYTHING_RUN_TMP, which `chat card` and Gemini read) on its own folder."""
    env = dict(env or {}); t = str(tmp)
    env["TMPDIR"] = env["TMP"] = env["TEMP"] = env["GAMEANYTHING_RUN_TMP"] = t
    return env


def drop_run_tmp(tmp):
    """Remove an ended run's temp folder (only ever one under run_tmp_base())."""
    import shutil
    if not tmp: return
    try:
        d = Path(tmp).resolve(); base = run_tmp_base().resolve()
        if d.parent == base: shutil.rmtree(d, ignore_errors=True)
    except (OSError, RuntimeError): pass


def run_tmp_project(path):
    """The project id of the run temp folder a file lies in (<base>/<id>--<run>/...), else None."""
    try:
        p = Path(path).resolve(); base = run_tmp_base().resolve()
        rel = p.relative_to(base)
    except (OSError, RuntimeError, ValueError): return None
    return rel.parts[0].rsplit("--", 1)[0] if rel.parts and "--" in rel.parts[0] else None


def _system_files(add_dirs) -> list:
    """Folders outside the project a run may also touch with its file tools: the add_dirs, the skill and the GameAnything install (templates,
    references), the temp folder."""
    import tempfile
    from . import shipped
    out, seen = [], set()
    for d in [*add_dirs, shipped.SKILL, shipped.ROOT, shipped.PKG, Path(tempfile.gettempdir())]:
        try: d = Path(d).expanduser().resolve()
        except (OSError, RuntimeError): continue
        if str(d) not in seen: seen.add(str(d)); out.append(d)
    return out


# ---------------------------------------------------------------- OpenCode (`opencode run`): 75+ model providers, e.g. OpenRouter
# Model = provider/model as opencode takes it (openrouter/moonshotai/kimi-k2.6). The provider's key env var: models.dev names for the common
# ones, else <PROVIDER>_API_KEY. The key never stays in the run's env: it is written to a 0600 file in the GameAnything OpenCode home and the config
# points at it ({file:...}), so the agent's shell (and a gen script it starts) has no key in its environment.
OPENCODE_DEFAULT_MODEL = "openrouter/moonshotai/kimi-k2.6"
# A resident run answers one step and stops. The first real run (Kimi K2.6, 2026-10-26) did not: after the units card it went on for 241
# tool calls through every later step, drew fake preview pictures and sent a fake 「第一版完成」 card. opencode's own `steps` limit (tool
# rounds before it must answer in text) ends such a run; Codex / Claude runs of a step take far fewer. Builders have no such cap.
OPENCODE_RESIDENT_STEPS = 80
OPENCODE_KEY_ENV = {"openrouter": ("OPENROUTER_API_KEY",), "anthropic": ("ANTHROPIC_API_KEY",), "openai": ("OPENAI_API_KEY",),
                    "google": ("GOOGLE_GENERATIVE_AI_API_KEY", "GEMINI_API_KEY"), "deepseek": ("DEEPSEEK_API_KEY",), "groq": ("GROQ_API_KEY",),
                    "mistral": ("MISTRAL_API_KEY",), "xai": ("XAI_API_KEY",), "moonshotai": ("MOONSHOT_API_KEY",), "zai": ("ZHIPU_API_KEY",),
                    "togetherai": ("TOGETHER_AI_API_KEY",), "fireworks-ai": ("FIREWORKS_API_KEY",), "cerebras": ("CEREBRAS_API_KEY",)}
# env names a run of OpenCode drops before it starts: a daemon started from an OpenCode session must not make the run a nested one
OPENCODE_SHELL_PLUGIN = """// gameanything (written by gameanything agentd; rewritten before every run): the agent's own config folders and config are not the shell's.
// The shell gets the XDG folders the run had before GameAnything pointed OpenCode at its own home, and no credential-looking variable.
const CRED = /(^|_)(API_KEY|TOKEN|SECRET|PASSWORD)$|_SECRET_|CREDENTIALS/;
export const M2wShellEnv = async () => ({
  "shell.env": async (input, output) => {
    for (const k of ["XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"]) output.env[k] = process.env["GAMEANYTHING_SHELL_" + k] || "";
    output.env.OPENCODE_CONFIG_CONTENT = "";
    for (const k of Object.keys(process.env)) if (CRED.test(k)) output.env[k] = "";
  },
});
"""


def opencode_key_names(model) -> tuple:
    pid = str(model or OPENCODE_DEFAULT_MODEL).split("/", 1)[0].strip().lower()
    return OPENCODE_KEY_ENV.get(pid) or (re.sub(r"[^A-Z0-9]", "_", pid.upper()) + "_API_KEY",)


def opencode_permission(role, root, add_dirs) -> dict:
    """OpenCode permission rules (the last matching rule wins; nothing is left on "ask": `opencode run` has nobody to ask). Shell commands:
    the same deny list as Claude Code's. Files outside the project (external_directory: the file tools AND the paths opencode finds in
    cd / cp / mkdir / touch / rm ... commands): only the add_dirs, the skill / install and the temp folder."""
    ext = {"*": "deny"}
    for d in _system_files(add_dirs):
        for s in {str(d), d.as_posix()}: ext[s] = "allow"; ext[s.rstrip("/\\") + "/*"] = "allow"
    return {"*": "deny", "read": "allow", "glob": "allow", "grep": "allow", "list": "allow", "edit": "allow", "todowrite": "allow",
            "todoread": "allow", "webfetch": "allow", "websearch": "allow", "doom_loop": "allow",
            "bash": {"*": "allow", **{g: "deny" for g in _deny_globs(role)}},
            "task": "deny", "skill": "deny", "question": "deny", "lsp": "deny", "codesearch": "deny", "external_directory": ext}


@dataclass(frozen=True)
class OpenCode(Provider):
    name: str = "opencode"

    def creds(self, env=None):
        return (*opencode_key_names(self.model), "GAMEANYTHING_OPENCODE_HOME")

    def command(self, prompt, system, session_id, resume, root, budget=None, *, role="resident", add_dirs=(), network=False, shell_set=None, env=None):
        if budget is not None:
            raise ValueError("OpenCode has no per-run USD budget flag; omit --budget-usd")
        if role not in ROLES: raise ValueError(f"role 应该是 {' / '.join(ROLES)}")
        # --dir: opencode takes its project folder from $PWD (the daemon's folder, 2026-10-26: `gameanything chat say --project ""` wrote into
        # the daemon's folder), not from the process's working directory
        cmd = [self.binary, "run", "--format", "json", "--model", self.model or OPENCODE_DEFAULT_MODEL, "--dir", str(root)]
        if resume and session_id: cmd += ["--session", str(session_id)]
        return cmd + [prompt]

    def launch(self, prompt, system, session_id, resume, root, budget=None, *, role="resident", add_dirs=(), network=False, shell_set=None, env=None):
        """Point opencode at the GameAnything OpenCode home (XDG_CONFIG_HOME / XDG_DATA_HOME / XDG_STATE_HOME: config, sessions, auth): the
        operator's ~/.config/opencode (agents, plugins, MCP, AGENTS.md) never loads; OPENCODE_DISABLE_PROJECT_CONFIG / _CLAUDE_CODE /
        _EXTERNAL_SKILLS keep project and ~/.claude instructions and skills out. The system prompt is an instructions file (appended to
        opencode's own prompt), the config (permissions, model, the key file) is OPENCODE_CONFIG_CONTENT. No sandbox: like Claude Code, a
        run's shell can reach the network (residents and builders alike); see opencode_permission for what it may not do."""
        cmd = self.command(prompt, system, session_id, resume, root, budget, role=role, add_dirs=add_dirs, network=network, env=env)
        env = dict(env or {})
        home = agent_home(env, "GAMEANYTHING_OPENCODE_HOME", "opencode")
        m2w = home / "m2w"; m2w.mkdir(parents=True, exist_ok=True)
        model = self.model or OPENCODE_DEFAULT_MODEL; pid = model.split("/", 1)[0]
        provider_cfg = {}
        for k in opencode_key_names(model):
            v = env.pop(k, None)
            if v and not provider_cfg:
                kf = m2w / f"key-{pid}"; _write_if_changed(kf, v, private=True)
                provider_cfg = {pid: {"options": {"apiKey": "{file:" + kf.as_posix() + "}"}}}
        if not provider_cfg and "GAMEANYTHING_OPENCODE_HOME" not in env:
            _import_operator_file(Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "opencode" / "auth.json",
                                  home / "data" / "opencode" / "auth.json")
        sysf = m2w / f"system-{_digest(system)}.md"; _write_if_changed(sysf, system); _prune(m2w, "system-*.md")
        _write_if_changed(home / "config" / "opencode" / "plugins" / "m2w-shell-env.js", OPENCODE_SHELL_PLUGIN)
        cfg = {"$schema": "https://opencode.ai/config.json", "autoupdate": False, "share": "disabled", "snapshot": False,
               "model": model, "small_model": model, "instructions": [sysf.as_posix()], "mcp": {}, "provider": provider_cfg,
               "permission": opencode_permission(role, root, add_dirs)}
        if role == "resident": cfg["agent"] = {"build": {"steps": OPENCODE_RESIDENT_STEPS}}
        for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
            env["GAMEANYTHING_SHELL_" + k] = env.get("GAMEANYTHING_SHELL_" + k) or env.get(k) or ""
        env.update({"XDG_CONFIG_HOME": str(home / "config"), "XDG_DATA_HOME": str(home / "data"), "XDG_STATE_HOME": str(home / "state"),
                    "OPENCODE_CONFIG_CONTENT": json.dumps(cfg), "OPENCODE_DISABLE_PROJECT_CONFIG": "1", "OPENCODE_DISABLE_CLAUDE_CODE": "1",
                    "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1", "OPENCODE_DISABLE_AUTOUPDATE": "1", "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
                    "OPENCODE_DISABLE_LSP_DOWNLOAD": "1", "OPENCODE_ENABLE_EXA": "1"})
        for k in ("OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "OPENCODE_PERMISSION", "OPENCODE_AUTH_CONTENT"): env.pop(k, None)
        env["PWD"] = str(root)
        return cmd, env

    def session_id(self, log):
        # every opencode run --format json event carries "sessionID"
        return _jsonl_session(log, ("sessionID",))

    def auth_failed(self, log):
        return _log_has(log, ('"statusCode":401', "User not found", "No auth credentials found", "Invalid API key", "Incorrect API key",
                              "API key is missing", "invalid x-api-key", "ProviderAuthError",
                              *CREDIT_NEEDLES))                                     # no credit left on the key: retrying cannot help

    def clean_env(self, env):
        keep = {"OPENCODE_DISABLE_AUTOUPDATE"}
        return {k: v for k, v in env.items() if not (k.startswith("OPENCODE") and k not in keep)}


# ---------------------------------------------------------------- Gemini CLI (`gemini -p`): GEMINI_API_KEY or a Google login
# GEMINI_CLI_HOME = the GameAnything Gemini home (settings, sessions, login), never the operator's ~/.gemini. Shell commands: gemini's own environment
# redaction (security.environmentVariableRedaction) removes every *KEY* / *TOKEN* / *SECRET* / *PASSWORD* / *AUTH* / *CREDENTIAL* variable
# and GEMINI_API_KEY from the commands it runs; names with KEY cannot be allowed back, so GAMEANYTHING_KEYS_FILE reaches the shell as GAMEANYTHING_USER_ENV_FILE.
GEMINI_TOOLS = ("run_shell_command", "write_file", "replace", "read_file", "read_many_files", "glob", "grep_search", "search_file_content",
                "list_directory", "web_fetch", "google_web_search", "write_todos", "update_topic")
GEMINI_PREAMBLE = ("Only the instructions in this prompt apply to this run. Ignore any GEMINI.md, AGENTS.md or skill instructions from "
                   "elsewhere; never create files the step does not ask for.")
GEMINI_BLOCKED_ENV = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_GEMINI_BASE_URL", "GOOGLE_CLOUD_PROJECT",
                      "GOOGLE_CLOUD_LOCATION", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_GCA")


def gemini_read_only() -> list:
    """Folders a Gemini run must READ with its file tools but never write: the skill (core / mode / step docs, references, the setting
    guides) and the GameAnything install (templates). Without them in the workspace read_file says "Path not in workspace" (QA 2026-10-29)."""
    from . import shipped
    out = []
    for d in (shipped.SKILL, shipped.ROOT):
        try: d = Path(d).resolve()
        except (OSError, RuntimeError): continue
        if d.is_dir() and d not in out: out.append(d)
    return out


def gemini_dirs(add_dirs) -> list:
    """--include-directories of a run: the writable add_dirs, then the read-only skill / install folders (the policy denies writes there)."""
    out = [str(d) for d in add_dirs]
    for d in gemini_read_only():
        if str(d) not in out: out.append(str(d))
    return out


def gemini_policy(role) -> str:
    """Policy engine rules (TOML), user tier (--policy): the GameAnything tools allowed, the deny list of Claude Code as regexes on the whole shell
    command, everything else denied (MCP servers, skills, subagents, save_memory, ask_user: headless would treat "ask" as deny anyway)."""
    def rx(g): return ".*" + ".*".join(re.escape(x) for x in g.strip("*").split("*")) + ".*"
    out = ["# gameanything (written by gameanything agentd before every run)", "",
           "[[rule]]", f"toolName = {json.dumps(list(GEMINI_TOOLS))}", 'decision = "allow"', "priority = 100", "allowRedirection = true", "",
           "[[rule]]", 'toolName = "*"', 'decision = "deny"', "priority = 10", 'denyMessage = "gameanything: this tool is off in this run"', "",
           "[[rule]]", 'toolName = "*"', 'mcpName = "*"', 'decision = "deny"', "priority = 999", ""]
    for d in gemini_read_only():                                # the skill and the install: read only (write_file / replace refused)
        out += ["[[rule]]", 'toolName = ["write_file", "replace"]', f"argsPattern = {_toml_str('.*' + re.escape(json.dumps(d.as_posix())[1:-1]) + '.*')}",
                'decision = "deny"', "priority = 950", 'denyMessage = "gameanything: the skill and the GameAnything install are read only"', ""]
    from . import decisions
    for pat in (re.escape(decisions.LEDGER), re.escape(json.dumps(Path(decisions.keys_dir()).as_posix())[1:-1])):    # her decisions: the server's
        out += ["[[rule]]", 'toolName = ["write_file", "replace", "read_file", "read_many_files"]', f"argsPattern = {_toml_str('.*' + pat + '.*')}",
                'decision = "deny"', "priority = 960", 'denyMessage = "gameanything: her decisions are recorded by the page server only"', ""]
    for g in sorted(set(_deny_globs(role))):
        out += ["[[rule]]", 'toolName = "run_shell_command"', f"commandRegex = {_toml_str(rx(g))}", 'decision = "deny"', "priority = 900",
                'denyMessage = "gameanything: this command is not allowed in this run (paid generation: gameanything gen request; labs: the builder)"', ""]
    return "\n".join(out)


def _toml_str(s: str) -> str:
    return "'" + s + "'" if "'" not in s and "\n" not in s else json.dumps(s)


def gemini_settings(env, home: Path) -> dict:
    auth = ("gemini-api-key" if env.get("GEMINI_API_KEY") else "vertex-ai" if env.get("GOOGLE_GENAI_USE_VERTEXAI")
            else "oauth-personal" if (home / ".gemini" / "oauth_creds.json").is_file() else None)
    s = {"general": {"enableAutoUpdate": False, "enableAutoUpdateNotification": False, "checkpointing": {"enabled": False},
                     "plan": {"enabled": False}},
         "privacy": {"usageStatisticsEnabled": False}, "telemetry": {"enabled": False}, "ide": {"enabled": False},
         "context": {"fileName": ["M2W-NO-CONTEXT-FILE.md"], "loadMemoryFromIncludeDirectories": False},
         "tools": {"sandbox": False}, "mcpServers": {}, "skills": {"enabled": False}, "hooksConfig": {"enabled": False},
         "experimental": {"enableAgents": False},
         "security": {"folderTrust": {"enabled": False}, "environmentVariableRedaction": {"enabled": True, "blocked": list(GEMINI_BLOCKED_ENV)}}}
    if auth: s["security"]["auth"] = {"selectedType": auth}
    return s


# Gemini runs always name their model: with none, gemini 0.39 routes every turn through its "auto" classifier, which calls
# gemini-2.5-flash-lite (404 "no longer available to new users" on every run, a gemini-client-error-*.json each time; QA2 2026-10-30).
GEMINI_DEFAULT_MODEL = "gemini-3.5-flash"


@dataclass(frozen=True)
class Gemini(Provider):
    name: str = "gemini"

    def creds(self, env=None):
        env = env or {}
        keep = ["GEMINI_API_KEY", "GAMEANYTHING_GEMINI_HOME", "GOOGLE_GEMINI_BASE_URL"]
        if env.get("GOOGLE_GENAI_USE_VERTEXAI"): keep += ["GOOGLE_*"]
        return tuple(keep)

    def _paths(self, env, role):
        home = agent_home(env, "GAMEANYTHING_GEMINI_HOME", "gemini")
        return home, home / ".gemini" / "m2w" / f"policy-{role}.toml"

    def command(self, prompt, system, session_id, resume, root, budget=None, *, role="resident", add_dirs=(), network=False, shell_set=None, env=None):
        if budget is not None:
            raise ValueError("Gemini CLI has no per-run USD budget flag; omit --budget-usd")
        if role not in ROLES: raise ValueError(f"role 应该是 {' / '.join(ROLES)}")
        combined = f"<{role}-system-prompt>\n{GEMINI_PREAMBLE}\n\n{system}\n</{role}-system-prompt>\n\n{prompt}"
        _home, policy = self._paths(env, role)
        cmd = [self.binary, "--output-format", "stream-json", "--approval-mode", "default", "--policy", str(policy)]
        rt = (env or {}).get("GAMEANYTHING_RUN_TMP")             # its own temp folder: card files are written there (mktemp)
        for d in gemini_dirs([*add_dirs, *([rt] if rt else [])]): cmd += ["--include-directories", str(d)]
        if self.model: cmd += ["--model", self.model]
        if resume and session_id: cmd += ["--resume", str(session_id)]
        return cmd + ["--prompt", combined]

    def launch(self, prompt, system, session_id, resume, root, budget=None, *, role="resident", add_dirs=(), network=False, shell_set=None, env=None):
        """GEMINI_CLI_HOME = the GameAnything Gemini home, its .gemini/settings.json written by GameAnything (no MCP, skills, hooks, subagents, extensions,
        context files, telemetry, auto-update; secret redaction in the shell on), the policy file per role. File tools: the project and the
        add_dirs (--include-directories) only. No sandbox here (gemini's own needs docker / podman / bwrap): like Claude Code, a run's shell
        can write anywhere and reach the network."""
        env = dict(env or {})
        home, policy = self._paths(env, role)
        if "GAMEANYTHING_GEMINI_HOME" not in env and not env.get("GEMINI_API_KEY"):
            for f in ("oauth_creds.json", "google_accounts.json"):
                _import_operator_file(Path.home() / ".gemini" / f, home / ".gemini" / f)
        _write_if_changed(home / ".gemini" / "settings.json", json.dumps(gemini_settings(env, home), indent=1))
        _write_if_changed(policy, gemini_policy(role))
        env["GEMINI_CLI_HOME"] = str(home); env["PWD"] = str(root)
        tmp = home / "tmp"; tmp.mkdir(parents=True, exist_ok=True); _prune(tmp, "gemini-client-error-*.json")
        # its error reports (gemini-client-error-*.json) land in the run's own temp folder (agentd / builds), else here; never /tmp or her folders
        env["TMPDIR"] = env.get("GAMEANYTHING_RUN_TMP") or str(tmp)
        if env.get("GAMEANYTHING_KEYS_FILE") is not None: env["GAMEANYTHING_USER_ENV_FILE"] = env["GAMEANYTHING_KEYS_FILE"]
        for k in ("GEMINI_CLI_SYSTEM_SETTINGS_PATH", "GEMINI_SYSTEM_MD", "GEMINI_SANDBOX", "GEMINI_CLI_IDE_PID", "GEMINI_CLI_IDE_SERVER_PORT"):
            env.pop(k, None)
        return self.command(prompt, system, session_id, resume, root, budget, role=role, add_dirs=add_dirs, network=network, env=env), env

    def session_id(self, log):
        # gemini -o stream-json starts with {"type":"init","session_id":"<uuid>",...}; a resumed session keeps its id
        return _jsonl_session(log, ("session_id",))

    def auth_failed(self, log):
        return _log_has(log, ("API key not valid", "API_KEY_INVALID", "Please set an Auth method", "UNAUTHENTICATED", "API key expired",
                              "GEMINI_API_KEY environment variable not found", "Failed to login", "Error authenticating",
                              # a personal Google login (free Code Assist tier) is refused by gemini 0.39 since 2026: "This client is no
                              # longer supported for Gemini Code Assist for individuals" -> an API key is needed
                              "IneligibleTierError",
                              # a valid key on a Google account without credit (402): retrying cannot help either
                              *CREDIT_NEEDLES))
        # The free tier's daily quota ("You have exhausted your daily quota", TerminalQuotaError) is a usage limit, not a login problem
        # (QA 2026-10-29: it was reported as "not logged in (401)"): activity.LIMIT_RE, agentd waits for the reset.

    def clean_env(self, env):
        return {k: v for k, v in env.items() if not k.startswith("GEMINI_CLI") and k != "GEMINI_SYSTEM_MD"}


# ---------------------------------------------------------------- DeepSeek Harness (`dsh --profile headless`): a DeepSeek API key
# The headless profile runs one task, prints NDJSON events (--json) and resumes with --session-id. Its configuration is a stack of patch
# layers: DSH_HOME = GameAnything's dsh home (the operator's ~/.dsh, its settings, saved keys and AGENTS.md never load) plus one --patch file
# GameAnything writes before every run (model and its route: DeepSeek's own API, or another provider such as OpenRouter through dsh's pi-ai adapter; no
# instruction files, no skills / MCP / subagents). It has no command deny list, and its file sandbox is
# off (see Dsh.launch): the missing paid keys (agent_env, GAMEANYTHING_GEN_OFF) are the guard; see docs/agent-providers.md. DeepSeek Harness is a
# developer preview (breaking changes announced): tested with @deepseek-ai/dsh 0.2.1-rc.2 and 0.2.1-rc.5 (npm latest on 2026-10-31) against
# local stand-ins for DeepSeek's Messages endpoint and OpenRouter's chat completions.
DSH_PROVIDER = "deepseek-official"
DSH_DEFAULT_MODEL = "deepseek-v4-pro"            # the built-in catalog: deepseek-flash (dsh's own default), deepseek-v4-pro
DSH_KEY = "DEEPSEEK_API_KEY"
DSH_PREAMBLE = ("Only the instructions in this prompt apply to this run. Ignore any AGENTS.md, CLAUDE.md or skill instructions from "
                "elsewhere; never create files the step does not ask for.")
# rows of the composed headless tree a run does without: helper agents, skills from any folder, MCP, workflows, plugin installs (each id
# checked with `dsh --profile headless --patch <file> --dump-config`: a row the tree does not have is reported as "not found")
DSH_OFF = ("skill-filesystem", "tool-skill", "tool-subagent", "tool-subagent-fork", "tool-subagent-control", "tool-subagent-list-agents",
           "mcp-resources", "tool-workflow", "tool-plugin-manager")
# web_search without a DeepSeek key: dsh's own search backends all need one, so a run on another provider's key searches through GameAnything's
# plugins/dsh-web-search-openai-compatible (a search-capable model behind that provider's OpenAI-compatible endpoint, same key).
# provider route -> (endpoint, default search model); a provider not listed here gets no web_search.
DSH_SEARCH = {"openrouter": ("https://openrouter.ai/api/v1", "perplexity/sonar")}
DSH_SEARCH_PLUGIN = "plugins/dsh-web-search-openai-compatible/index.js"


def dsh_route(model) -> tuple:
    """(dsh provider route, model id, key env) of a GameAnything model name. A bare name (deepseek-v4-pro) or deepseek/<name> is DeepSeek's own
    API (dsh's deepseek-official route, DEEPSEEK_API_KEY); provider/model (openrouter/deepseek/deepseek-v4-pro, as OpenCode writes it)
    is that provider's route in dsh's pi-ai adapter, with the key variable OpenCode uses for it (OPENROUTER_API_KEY)."""
    m = str(model or DSH_DEFAULT_MODEL).strip()
    pid, _, rest = m.partition("/")
    if not rest: return DSH_PROVIDER, m, DSH_KEY
    if pid.lower() in ("deepseek", DSH_PROVIDER): return DSH_PROVIDER, rest, DSH_KEY
    return pid, rest, opencode_key_names(m)[0]


def dsh_search_rows(pid, key, search_model=None) -> list:
    """The rows that make web_search ask a search model on provider pid with its own key (plugins/dsh-web-search-openai-compatible, loaded
    from the GameAnything install by file URL), or [] when no search model is known there. OpenRouter: a perplexity/* model searches by itself;
    any other model gets OpenRouter's web search server tool (beta)."""
    from . import shipped
    if pid not in DSH_SEARCH: return []
    url, default = DSH_SEARCH[pid]
    model = search_model or default
    config = {"baseURL": url, "apiKeyEnv": key, "model": model}
    if pid == "openrouter" and not model.startswith("perplexity/"): config["body"] = {"tools": [{"type": "openrouter:web_search"}]}
    return [{"insert": [{"id": "web-search-openai-compatible", "name": (shipped.ROOT / DSH_SEARCH_PLUGIN).resolve().as_uri(), "config": config}]},
            {"id": "web", "config": {"searchProvider": "openai-compatible", "fetchProvider": "http"}}]


def dsh_patch(model, deepseek_key=True, search_model=None) -> list:
    """The --patch layer of a run (a Cordis patch list: rows by id, config replaced). web_search: DeepSeek's own search (dsh's default)
    with a DeepSeek key; without one, a search model on the run's provider (dsh_search_rows), else no web_search tool. web_fetch stays."""
    pid, mid, key = dsh_route(model)
    rows = [{"id": "agent-default-model", "config": {"provider": pid, "model": mid}}]
    # another provider: a pi-ai route (session titles and compaction summaries follow the main route, they have no route of their own)
    if pid != DSH_PROVIDER: rows.append({"id": "llm-pi-ai", "config": {"providers": {pid: {"apiKeyEnv": key}}}})
    if not deepseek_key: rows += dsh_search_rows(pid, key, search_model) or [{"id": "tool-web", "config": {"search": False}}]
    # no AGENTS.md / CLAUDE.md from the project folder or any parent (the shared server's own rules sit in a parent folder)
    rows.append({"id": "agent-instructions", "config": {"maxBytes": 65536, "instructionFileCandidates": ["M2W-NO-CONTEXT-FILE.md"],
                                                        "localInstructionFileCandidates": []}})
    return rows + [{"id": k, "disabled": True} for k in DSH_OFF]


@dataclass(frozen=True)
class Dsh(Provider):
    name: str = "dsh"

    def creds(self, env=None):
        # the model's key, and a DeepSeek key for web_search when the model goes through another provider
        return tuple(dict.fromkeys((dsh_route(self.model)[2], DSH_KEY, "DEEPSEEK_BASE_URL", "GAMEANYTHING_DSH_HOME")))

    def _home(self, env):
        return agent_home(env, "GAMEANYTHING_DSH_HOME", "dsh")

    def command(self, prompt, system, session_id, resume, root, budget=None, *, role="resident", add_dirs=(), network=False, shell_set=None, env=None):
        if budget is not None:
            raise ValueError("DeepSeek Harness has no per-run USD budget flag; omit --budget-usd")
        if role not in ROLES: raise ValueError(f"role 应该是 {' / '.join(ROLES)}")
        combined = f"<{role}-system-prompt>\n{DSH_PREAMBLE}\n\n{system}\n</{role}-system-prompt>\n\n{prompt}"
        # launcher flags (--profile, --patch) first: the first token the launcher does not know starts the headless app's own arguments.
        # Only --json and --session-id: 0.2.1-rc.x (npm latest / next) knows no other headless option and ends the run on one.
        cmd = [self.binary, "--profile", "headless", "--patch", str(self._home(env) / "gameanything" / f"patch-{role}.yml"), "--json"]
        if resume and session_id: cmd += ["--session-id", str(session_id)]
        return cmd + [combined]

    def launch(self, prompt, system, session_id, resume, root, budget=None, *, role="resident", add_dirs=(), network=False, shell_set=None, env=None):
        """DSH_HOME / DSH_AGENTS_HOME = GameAnything's dsh home (profiles, sessions, the user-global AGENTS.md: all its own), the patch file per
        role, telemetry and the file sandbox off. GAMEANYTHING_DSH_SEARCH_MODEL: the search model when web_search goes through the run's provider
        (dsh_search_rows; default perplexity/sonar on OpenRouter).
        The keys (the model's provider's, and DEEPSEEK_API_KEY for web_search) leave the run's env: the headless profile (and the search
        plugin) reads them from $DSH_HOME/.env (0600), so the agent's shell (and a gen script it starts) finds no key in its environment. The working directory is the workspace root: agentd starts the run in the project."""
        env = dict(env or {})
        home = self._home(env)
        keys = {k: env.pop(k) for k in dict.fromkeys((dsh_route(self.model)[2], DSH_KEY)) if env.get(k)}
        patch = dsh_patch(self.model, deepseek_key=DSH_KEY in keys, search_model=env.get("GAMEANYTHING_DSH_SEARCH_MODEL"))
        _write_if_changed(home / "gameanything" / f"patch-{role}.yml", "# GameAnything (written by agentd before every run)\n"
                          + yaml.safe_dump(patch, sort_keys=False, allow_unicode=True))
        kf = home / ".env"
        if keys: _write_if_changed(kf, "".join(f"{k}={v}\n" for k, v in keys.items()), private=True)
        elif kf.exists(): kf.unlink()                              # the run's env is the only source: a removed key stays removed
        (home / "agents").mkdir(parents=True, exist_ok=True)
        # telemetry off (D3): the base profile would upload whole session logs to DeepSeek's collector after a feedback event;
        # DSH_TELEMETRY_DISABLED is the launcher's hard switch, DSH_TELEMETRY_MODE the telemetry row's own.
        # danger-full-access (approval: never): dsh's workspace-write sandbox leaves only the project writable, and the CLI itself does not run
        # there (2026-10-27, 0.2.1-rc.2 with Landlock: `m2w` failed on its uv cache; `agentd request` writes the requests folder, a
        # builder the lab and build caches). 0.2.2-alpha.2 adds --add-dir; until a run with those grants is tested, like Claude Code,
        # OpenCode and Gemini CLI: no OS sandbox.
        env.update({"DSH_HOME": str(home), "DSH_AGENTS_HOME": str(home / "agents"), "DSH_TELEMETRY_DISABLED": "1",
                    "DSH_TELEMETRY_MODE": "DISABLED", "DSH_PERMISSION_MODE": "danger-full-access", "PWD": str(root)})
        return self.command(prompt, system, session_id, resume, root, budget, role=role, add_dirs=add_dirs, network=network, env=env), env

    def session_id(self, log):
        # dsh --json opens with {"type":"session","sessionId":"session-<uuid>","cwd":...}; a resumed run keeps its id
        return _jsonl_session(log, ("sessionId",))

    def model_refused(self, log):
        # a model name the service does not have: OpenRouter's 400 "<id> is not a valid model ID", DeepSeek's "Model Not Exist"
        return super().model_refused(log) or _log_has(log, ("is not a valid model ID", "Model Not Exist"))

    def auth_failed(self, log):
        return _log_has(log, ("MISSING_CREDENTIAL", "INVALID_CREDENTIAL", "Authentication Fails", "invalid api key",
                              "Insufficient Balance",     # DeepSeek's 402: no credit left on the key, retrying cannot help
                              "User not found", "No auth credentials found", "Insufficient credits"))   # OpenRouter's 401 / 402

    def clean_env(self, env):
        # a daemon started from a dsh session must not hand the run that session's home, profile or permission mode
        return {k: v for k, v in env.items() if not k.startswith("DSH_")}


def _digest(text: str) -> str:
    import hashlib
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:16]


def _import_operator_file(src: Path, dst: Path):
    """On the operator's own machine (no hub user home): their own login file for the agent CLI is copied once into the GameAnything agent home,
    the rest of their config is not."""
    try:
        if dst.exists() or not src.is_file(): return
        _write_private(dst, src.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError): pass


def _log_has(log: Path, needles: tuple[str, ...]) -> bool:
    try: text = Path(log).read_text(encoding="utf-8", errors="replace")[-20000:]
    except (OSError, TypeError): return False
    low = text.lower()
    return any(n.lower() in low for n in needles)


def _jsonl_session(log: Path, keys: tuple[str, ...]) -> str | None:
    try: lines = Path(log).read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, TypeError): return None
    for line in lines:
        try: event = json.loads(line)
        except (TypeError, ValueError): continue
        for key in keys:
            value = event.get(key) if isinstance(event, dict) else None
            if isinstance(value, str) and value: return value
    return None


def provider(name=None, binary=None, model=None) -> Provider:
    name = (name or os.environ.get("GAMEANYTHING_AGENT_PROVIDER") or "claude-code").lower().replace("_", "-")
    if name == "claude": name = "claude-code"
    if name in ("deepseek", "deepseek-harness"): name = "dsh"
    if name == "claude-code":
        exe = binary or os.environ.get("GAMEANYTHING_CLAUDE") or shutil.which("claude") or str(Path.home() / ".local/bin/claude")
        return ClaudeCode(binary=exe, model=model or "sonnet")
    if name == "codex":
        exe = binary or os.environ.get("GAMEANYTHING_CODEX") or shutil.which("codex") or str(Path.home() / ".local/bin/codex")
        return Codex(binary=exe, model=model)
    if name == "opencode":
        exe = binary or os.environ.get("GAMEANYTHING_OPENCODE") or shutil.which("opencode") or str(Path.home() / ".opencode/bin/opencode")
        return OpenCode(binary=exe, model=model or os.environ.get("GAMEANYTHING_OPENCODE_MODEL") or OPENCODE_DEFAULT_MODEL)
    if name == "gemini":
        exe = binary or os.environ.get("GAMEANYTHING_GEMINI") or shutil.which("gemini") or str(Path.home() / ".local/bin/gemini")
        return Gemini(binary=exe, model=model or os.environ.get("GAMEANYTHING_GEMINI_MODEL") or GEMINI_DEFAULT_MODEL)
    if name == "dsh":
        exe = binary or os.environ.get("GAMEANYTHING_DSH") or shutil.which("dsh") or str(Path.home() / ".local/bin/dsh")
        return Dsh(binary=exe, model=model or os.environ.get("GAMEANYTHING_DSH_MODEL") or DSH_DEFAULT_MODEL)
    raise ValueError(f"unknown agent provider: {name}")


PROVIDERS = ("claude-code", "codex", "opencode", "gemini", "dsh")
EXE = {"claude-code": ("claude", "GAMEANYTHING_CLAUDE"), "codex": ("codex", "GAMEANYTHING_CODEX"), "opencode": ("opencode", "GAMEANYTHING_OPENCODE"), "gemini": ("gemini", "GAMEANYTHING_GEMINI"),
       "dsh": ("dsh", "GAMEANYTHING_DSH")}


# ---------------------------------------------------------------- what a run may not do
# Claude Code: --disallowedTools patterns, each a glob on the whole Bash command. Paid generation: a run may not RUN a gen_*.py script (nor the
# card-checked runner); it queues it with `gameanything gen request` and agentd runs it after checking her cards (genrun.py).
DENY_GEN = ("Bash(*python* *gen_*.py*)", "Bash(py *gen_*.py*)", "Bash(*&& py *gen_*.py*)", "Bash(*; py *gen_*.py*)", "Bash(*| py *gen_*.py*)",
            "Bash(*uv run*gen_*.py*)", "Bash(*uvx *gen_*.py*)", "Bash(*runpy*gen_*)", "Bash(*chmod*gen_*)",
            "Bash(*run-gen-request*)", "Bash(*genrun*)",
            "Bash(*secret-tool*)", "Bash(*find-generic-password*)")          # the keyring that `gameanything gen key set` fills
DENY_DOCKER = ("Bash(*docker run*)", "Bash(*docker start*)", "Bash(*docker stop*)", "Bash(*docker restart*)", "Bash(*docker rm*)", "Bash(*docker kill*)")
DENY_LAB = ("Bash(*launch_rt/*)", "Bash(*mclab_rt*)", "Bash(*sdlab_rt*)", "Bash(*cslab_rt*)")
DENY_KILL = ("Bash(*pkill*)", "Bash(*killall*)")
# Steam in a sandbox: only through `gameanything lab env up` (labup.py: lease-checked, never a game, never a login typed for her)
DENY_STEAM = ("Bash(*steam-then-game*)", "Bash(*/usr/games/steam*)")
DENY_LAB_ENV = ("Bash(*gameanything lab env*)", "Bash(*m2w lab env*)", "Bash(*memory2world lab env*)")        # residents: the lab environment is the builder's (labup.py refuses too)
# Her decisions (decisions.py): the ledger, the server's public keys and strict list, the signing code and the page's decision POSTs are the
# server's; a run never touches them (QA 2026-10-30: an agent deleted the ledger, signed with the old key, POSTed a review without Origin).
DENY_DECISIONS = ("Bash(*user_decisions*)", "Bash(*decision-keys*)", "Bash(*strict-projects*)", "Bash(*decisions.key*)",
                  "Bash(*gameanything.decisions*)", "Bash(*gameanything import decisions*)", "Bash(*memory2world.decisions*)",
                  "Bash(*decisions.record*)", "Bash(*serve_signing*)", "Bash(*decisions.resign*)", "Bash(*decisions.migrate*)",
                  "Bash(*ed25519*)", "Bash(*ga_decide_*)", "Bash(*Sec-Fetch*)", "Bash(*api/*_review*)", "Bash(*api/thread/answer*)",
                  "Bash(*GAMEANYTHING_DECISION_KEYS*)")
DENY_RESIDENT = DENY_GEN + DENY_DOCKER + DENY_LAB + DENY_KILL + DENY_STEAM + DENY_LAB_ENV + DENY_DECISIONS
# the builder: the lab tools are allowed (each refuses a seat unless GAMEANYTHING_LEASE matches the lease agentd took for it), and `gameanything lab env up`
# for its own lease; raw docker, starting Steam by hand, paid generation and kill-by-pattern stay denied
DENY_BUILDER = DENY_GEN + DENY_DOCKER + DENY_KILL + DENY_STEAM + DENY_DECISIONS
_CLAUDE_DENY = DENY_RESIDENT          # old name


# ---------------------------------------------------------------- credentials in a run's env
def _cred(k: str) -> bool:
    from . import users
    return bool(users.CRED_RE.match(k))


def agent_env(env: dict, provider_name) -> dict:
    """The env of a resident / builder run without paid credentials: every variable users.CRED_RE calls a credential is dropped except the
    agent's own login (Claude: ANTHROPIC_*, CLAUDE_CODE_OAUTH_TOKEN, CLAUDE_CONFIG_DIR, plus AWS_* / GOOGLE_* for Bedrock / Vertex; Codex:
    CODEX_API_KEY, CODEX_HOME, ...; OpenCode: the key of its model's provider, e.g. OPENROUTER_API_KEY, which OpenCode.launch then moves
    into a key file; Gemini: GEMINI_API_KEY, hidden from its shell by gemini's redaction). provider_name: a name or a Provider (OpenCode's
    key depends on its model; DeepSeek Harness: DEEPSEEK_API_KEY, which Dsh.launch moves into $DSH_HOME/.env). OPENAI_API_KEY is an image-model key too, so it never stays for Codex (a hub user's Codex API key reaches
    codex as CODEX_API_KEY, users.user_env).
    GAMEANYTHING_GEN_OFF=1 makes keys.get() refuse, so a gen script started by a run gets no key from the keys file either. Paid generation runs
    only through agentd (genrun.py, users.gen_env keeps the keys)."""
    p = provider_name if isinstance(provider_name, Provider) else provider(provider_name, binary="-")
    keep = list(p.creds(env))
    if env.get("CLAUDE_CODE_USE_BEDROCK") and p.name == "claude-code": keep.append("AWS_*")
    if env.get("CLAUDE_CODE_USE_VERTEX") and p.name == "claude-code": keep += ["GOOGLE_*", "CLOUD_ML_*", "ANTHROPIC_VERTEX_*"]
    pat = re.compile("^(" + "|".join(re.escape(k).replace("\\*", ".*") for k in keep) + ")$")
    out = {k: v for k, v in env.items() if not _cred(k) or pat.match(k)}
    out["GAMEANYTHING_GEN_OFF"] = out["M2W_GEN_OFF"] = "1"            # M2W_GEN_OFF: an older install started from the run reads the old name
    return out


# ---------------------------------------------------------------- reading a run's JSON events (the hub's connection test, usage)
def _events(out: str):
    for line in str(out or "").splitlines():
        try: e = json.loads(line)
        except (TypeError, ValueError): continue
        if isinstance(e, dict): yield e


def reply_text(name, out: str) -> str:
    """The agent's reply text from `opencode run --format json` / `gemini -o stream-json` / `dsh --json` output ("" when it said nothing)."""
    if name == "dsh":
        ev = list(_events(out)); fin = [e for e in ev if e.get("type") == "final"]
        return str(fin[-1].get("text") or "").strip() if fin else "\n".join(e.get("text") or "" for e in ev if e.get("type") == "text").strip()
    if name == "opencode": return "".join((e.get("part") or {}).get("text") or "" for e in _events(out) if e.get("type") == "text").strip()
    if name == "gemini":
        return "".join(e.get("content") or "" for e in _events(out) if e.get("type") == "message" and e.get("role") == "assistant").strip()
    return str(out or "").strip()


def error_text(name, out: str) -> str:
    for e in _events(out):
        if name == "opencode" and e.get("type") == "error":
            d = (e.get("error") or {}).get("data") or {}
            return str(d.get("message") or e.get("error"))
        if name == "dsh" and e.get("type") == "error": return str(e.get("message") or e)
        # the turn's reason: on the turn_end status (0.2.1-rc.2), also on the final event (newer)
        if name == "dsh" and (e.get("type") == "final" or e.get("phase") == "turn_end") and (e.get("reason") or {}).get("kind") == "error":
            err = (e.get("reason") or {}).get("error") or {}
            return f"{err.get('code')}: {err.get('message')}" if err.get("code") else str(err.get("message") or err)
        if name == "gemini" and (e.get("type") == "error" or (e.get("type") == "result" and e.get("status") == "error")):
            return str((e.get("error") or {}).get("message") or e.get("message") or e)
    return ""


def usage(name, log) -> dict:
    """{cost_usd, input, output, cache_read, steps} of a run log, as far as the CLI reports it (OpenCode: cost per step; Gemini: tokens
    only; Codex and DeepSeek Harness: tokens; Claude Code: total_cost_usd)."""
    try: text = Path(log).read_text(encoding="utf-8", errors="replace")
    except (OSError, TypeError): return {}
    u = {"cost_usd": 0.0, "input": 0, "output": 0, "cache_read": 0, "steps": 0}
    for e in _events(text):
        t = e.get("type")
        if name == "opencode" and t == "step_finish":
            p = e.get("part") or {}; tk = p.get("tokens") or {}
            u["cost_usd"] += float(p.get("cost") or 0); u["input"] += int(tk.get("input") or 0); u["output"] += int(tk.get("output") or 0) + int(tk.get("reasoning") or 0)
            u["cache_read"] += int((tk.get("cache") or {}).get("read") or 0); u["steps"] += 1
        elif name == "dsh" and t == "status" and e.get("phase") == "step_end":
            s = e.get("usage") or {}; u["input"] += int(s.get("inputTokens") or 0); u["output"] += int(s.get("outputTokens") or 0)
            u["cache_read"] += int(s.get("cacheReadTokens") or 0); u["steps"] += 1; u["cost_usd"] = None
        elif name == "gemini" and t == "result":
            s = e.get("stats") or {}; u["input"] += int(s.get("input_tokens") or 0); u["output"] += int(s.get("output_tokens") or 0)
            u["cache_read"] += int(s.get("cached") or 0); u["steps"] += int(s.get("tool_calls") or 0); u["cost_usd"] = None
        elif name == "codex" and t == "turn.completed":
            s = e.get("usage") or {}; u["input"] += int(s.get("input_tokens") or 0); u["output"] += int(s.get("output_tokens") or 0)
            u["cache_read"] += int(s.get("cached_input_tokens") or 0); u["steps"] += 1; u["cost_usd"] = None
        elif name == "claude-code" and t == "result":
            u["cost_usd"] = float(e.get("total_cost_usd") or 0); s = e.get("usage") or {}
            u["input"] = int(s.get("input_tokens") or 0); u["output"] = int(s.get("output_tokens") or 0); u["cache_read"] = int(s.get("cache_read_input_tokens") or 0)
    return u
