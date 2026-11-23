"""gameanything agentd: the supervisor that answers every project chat, independent of any interactive agent session.

    gameanything agentd run [--provider claude-code|codex|opencode|gemini|dsh] [--agent-bin PATH] [--model MODEL] [...]    (the daemon; one per data dir)
    gameanything agentd status                                           (is it alive, which runs go on, what waits)
    gameanything agentd request --project P --kind K --text "…" [--details JSON]   (a run asks the coordinator for something it may not do itself)
    gameanything agentd notify --project P --text "…"                     (the coordinator tells the project's agent something: starts a run)

Every SCAN_SECS it reads the registered projects (projects.load()). A project with new user words (or a coordinator note, or a brand-new
project nobody has greeted) and no live owner gets, at once, the status line 「收到，agent 正在过来…」 and one headless provider run
(Claude Code or Codex) in the project folder. The run's role and rules are layered (every kind, flow.OPT_IN): core.md + modes/<kind>.md
+ the one step doc `gameanything flow next` names + the flow state; references/resident-prompt.md is only the fallback (a custom template,
GAMEANYTHING_LAYERED=0, or a layered prompt that failed to build). After a run that skipped what its step requires, one corrective re-run. It claims the chat (session agentd:<project id>), reads, replies, works, and exits. The next message
starts the next run, resuming the same provider session (conversation/.agent_session) so the agent keeps its context.

- At most one run per project; at most settings `max_active_projects` projects with a live owner (the rest are queued, the page says why).
- The owner record carries the run's pid (`proc`): the chat is free the moment the run ends or dies, never 10 minutes later.
- A run that ends without answering is retried (RETRY_AFTER; greetings, corrections and notes too), then the page says it failed, and why,
  until the user writes again. Why a run failed (provider.failure, activity.scan_log): not logged in / a usage limit / the CLI cannot work on
  this machine (Codex's sandbox, a cached probe) / a crash / a loop (activity.Tail.looping: stopped early). A login, sandbox or usage-limit
  problem backs the project off (.agentd_backoff.json): no run per message, one line per message saying why and when it tries again.
- A run longer than RUN_MAX_SECS is stopped.
- <data>/agentd.json is the heartbeat (every scan): the page knows whether the supervisor runs (`daemon_state()`).
- Runs outlive a restart of the daemon (own process group); a new daemon adopts them through conversation/.agentd_run.json.
- With a hub (`gameanything hub`, users.py): each run uses the project OWNER's Claude config dir and env file (users.run_env); a project whose
  owner has no Claude login yet is not run (status says so), and a run never gets another user's credentials.
- Paid generation (genrun.py): a run queues it (`gameanything gen request`); every scan agentd checks the queued requests (both cards answered, go
  card unused, script inside 4_design/tools), runs one per project in a background thread with the owner's env, and sends the outcome (or
  the reason it was refused) to the project's agent as a note. No coordinator session is needed.
- Reference pictures (refs.py): a run queues `gameanything refs fetch` (conversation/.refs_queue/); every scan agentd checks it again (her yes on a
  websearch card, no private names in the query, a public http(s) image) and downloads it on the host into 2_perceive/landmark_refs/.
- Builds (builds.py, `--builds auto`, env GAMEANYTHING_BUILDS, the default): a build_start request starts ONE headless builder run per project
  (roles/builder.md; a lab seat from the broker first), build_change requests go to the running builder; the builder reports to the
  resident with notes. `--builds coordinator`: requests only wait for a coordinator session, as before. Request files stay where they are.
Files per project (conversation/): .agentd_run.json (the current / last run), .agent_session (provider + session id), .agentd_failed,
.agentd_inbox/ (coordinator notes). Requests to the coordinator: <requests dir>/<project>-<time>.json.
"""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import clock
from . import agent_providers, decisions, envcompat, osdirs, projects, shipped, users
from .conversation import Owned, Thread, now

SCAN_SECS = 2
HEARTBEAT_STALE_SECS = 15
RUN_MAX_SECS = 45 * 60
SESSION_MAX_AGE_SECS = 2 * 24 * 3600            # an older Claude session starts fresh (its context is old news; keeps resumes fast)
SESSION_MAX_RUNS = 60
RETRY_AFTER = (15, 60)                          # seconds before the 1st and 2nd retry of a run that did not answer; then: failed
CALLING_EVERY_SECS = 600                        # the 「收到，agent 正在过来」 line at most this often per project (the page's status line shows every call)
TOOLS = ("Bash", "Read", "Write", "Edit", "Glob", "Grep")
# shell commands a run may never start (agent_providers.DENY_*). Paid generation: a run may not RUN a gen_*.py script (nor the card-checked
# runner); it queues it with `gameanything gen request --tool <name>`, and agentd runs it after checking the user's cards (genrun.py). Claude Code
# matches each pattern against the whole command, `*` = anything. (A script written with Write is not executable, and chmod on it is denied.)
# Every run's env also loses the paid keys (agent_providers.agent_env: Claude and Codex alike), so a script a run starts finds no key.
DENY_GEN = agent_providers.DENY_GEN
DENY = agent_providers.DENY_RESIDENT                 # residents: nor change sandboxes, labs or games (`docker exec … cat` stays allowed)
DENY_BUILDER = agent_providers.DENY_BUILDER          # builders: the lab tools are allowed (they check GAMEANYTHING_LEASE); raw docker, kill, gen are not
REQUEST_KINDS = ("build_start", "build_change", "question", "gen_request_ready", "other")
CALLING = ("收到，agent 正在过来，大约半分钟内回复你", "Got it - an agent is on its way and will reply in about half a minute")
RETRYING = ("收到。agent 这次没接上，{s} 秒后自动再叫一次", "Got it. The agent did not start this time; it is called again in {s} s")
FAILED = ("agent 这次没能回复（试了 3 次）。你再说一句，后台会重新叫 agent；一直这样的话请告诉协调者看一下 agentd 日志",
          "The agent could not reply this time (tried 3 times). Write again and a new agent is called; if it keeps happening, ask the coordinator to check the agentd log")
# the session environment of the agent session that started the daemon must not leak into the runs (they would think they are its children)
ENV_DROP_PREFIX = ("CLAUDE_CODE_", "CLAUDECODE", "CLAUDE_PID", "CLAUDE_AGENT_SDK", "CLAUDE_EFFORT", "CLAUDE_SESSION_ID", *envcompat.names("INSTANCE", "SESSION"))
ENV_KEEP = ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_MAX_OUTPUT_TOKENS")
AUTH_FAILED = ("Claude 登录过期或这台电脑上的 claude 命令没有登录：后台调度（它用 claude 命令行跑）读不了你的话。"
               "在 Claude 桌面 App 里登录不算数，命令行要单独登录一次：让协调者（桌面 App 里的 Claude）替你运行 `claude auth login`，会弹出浏览器，你点「授权」就行，不用打开终端。",
               "Claude login expired, or the claude command on this computer is not logged in, so the background dispatcher (which runs the claude CLI) cannot read your words. "
               "Signing in to the Claude desktop app does not count: the CLI needs its own login once. Ask the coordinator (Claude in the desktop app) to run `claude auth login` for you; a browser opens and you click Authorize, no terminal needed.")
AUTH_FAILED_CODEX = ("Codex 登录过期或这台电脑上的 codex 命令没有登录：后台调度暂时读不了你的话。请让协调者运行 `codex login`，在浏览器里完成登录。",
                     "The Codex login expired, or the codex command on this computer is not logged in, so the background dispatcher cannot read your words. Ask the coordinator to run `codex login` and finish sign-in in the browser.")
# OpenCode / Gemini run on an API key. In the hub she pastes it in 「我的 agent」; the single-user UI has no such page (QA2 2026-10-30): there the
# key comes from the environment GameAnything (its background dispatcher) was started in. auth_notice() picks the right one.
_KEY_FIX = {
    "opencode": (("请在「我的 agent」里重新粘贴 key（例如 OpenRouter 的 sk-or-…），或检查服务器上的 OPENROUTER_API_KEY。",
                  "Paste the key again in “My agent” (for example an OpenRouter sk-or-… key), or check OPENROUTER_API_KEY on the server."),
                 ("请让协调者（桌面 App 里的 Claude）把有效的 key（例如 OpenRouter 的 OPENROUTER_API_KEY=sk-or-…）设到启动 GameAnything 的环境里，再重启后台调度；或者在输入框旁边的「对话」里换一个 agent。",
                  "Ask the coordinator (Claude in the desktop app) to put a valid key (for example OPENROUTER_API_KEY=sk-or-…) in the environment GameAnything is "
                  "started in and restart the background dispatcher, or pick another agent (the 「对话」 chip next to the message box).")),
    "gemini": (("请在「我的 agent」里粘贴 Gemini API key（在 aistudio.google.com 新建）。",
                "Paste a Gemini API key in “My agent” (create one at aistudio.google.com)."),
               ("请让协调者（桌面 App 里的 Claude）把 Gemini API key（在 aistudio.google.com 新建）设成启动 GameAnything 的环境里的 GEMINI_API_KEY，再重启后台调度；或者在输入框旁边的「对话」里换一个 agent。",
                "Ask the coordinator (Claude in the desktop app) to set GEMINI_API_KEY (create one at aistudio.google.com) in the environment GameAnything is "
                "started in and restart the background dispatcher, or pick another agent (the 「对话」 chip next to the message box).")),
    "dsh": (("请在「我的 agent」里重新粘贴 key：DeepSeek 的（在 platform.deepseek.com 新建，以 sk- 开头），或用 OpenRouter 模型时 OpenRouter 的 sk-or-…。",
             "Paste the key again in “My agent”: a DeepSeek key (create one at platform.deepseek.com; it starts with sk-), or for an OpenRouter model an OpenRouter sk-or-… key."),
            ("请让协调者（桌面 App 里的 Claude）把有效的 key 设到启动 GameAnything 的环境里（DEEPSEEK_API_KEY，或用 OpenRouter 模型时 OPENROUTER_API_KEY），再重启后台调度；或者在输入框旁边的「对话」里换一个 agent。",
             "Ask the coordinator (Claude in the desktop app) to put a valid key in the environment GameAnything is started in (DEEPSEEK_API_KEY, or "
             "OPENROUTER_API_KEY for an OpenRouter model) and restart the background dispatcher, or pick another agent (the 「对话」 chip next to the message box).")),
}
_KEY_WHY = {"opencode": ("OpenCode 用的 API key 不对、已失效或余额用完（模型服务返回 401 / 402）：后台调度暂时读不了你的话。",
                         "The API key OpenCode uses is wrong, no longer valid or out of credit (the model provider answered 401 / 402), so the background dispatcher cannot read your words. "),
            "gemini": ("Gemini 的 API key 不对或余额用完，或 Google 登录用不了（个人免费的 Google 登录已不再支持 Gemini CLI）：后台调度暂时读不了你的话。",
                       "The Gemini API key is not valid or out of credit, or the Google login cannot be used (Gemini CLI no longer accepts the free personal Google login), so the background dispatcher cannot read your words. "),
            "dsh": ("DeepSeek Harness 用的 API key 不对、已失效或余额不足（模型服务返回 401 / 402）：后台调度暂时读不了你的话。",
                    "The API key DeepSeek Harness uses is wrong, no longer valid or out of balance (the model provider answered 401 / 402), so the background dispatcher cannot read your words. ")}


def auth_notice(provider_name, hub=None) -> tuple:
    """(zh, en): the notice for a login / key problem of this agent CLI, with what to do in this mode (hub: 「我的 agent」; single-user: the
    environment GameAnything runs in)."""
    if provider_name not in _KEY_WHY: return AUTH_FAILED_BY.get(provider_name, AUTH_FAILED)
    if hub is None:
        from . import users
        try: hub = users.enabled()
        except Exception: hub = False
    fix = _KEY_FIX[provider_name][0 if hub else 1]; why = _KEY_WHY[provider_name]
    return why[0] + fix[0], why[1] + fix[1]


def model_notice(provider_name, model) -> tuple:
    """(zh, en): the chosen model was refused. Claude Code: also an old CLI (2.1.72 answers `--model fable` only with "issue with the selected
    model"), so the notice says to update it."""
    label = PROVIDER_LABEL.get(provider_name, provider_name); m = model or "默认模型"; m_en = model or "default model"
    t = MODEL_CLI_OLD if provider_name == "claude-code" else MODEL_FAILED
    return t[0].format(agent=label, model=m), t[1].format(agent=label, model=m_en)


AUTH_FAILED_OPENCODE = (_KEY_WHY["opencode"][0] + _KEY_FIX["opencode"][0][0], _KEY_WHY["opencode"][1] + _KEY_FIX["opencode"][0][1])
AUTH_FAILED_GEMINI = (_KEY_WHY["gemini"][0] + _KEY_FIX["gemini"][0][0], _KEY_WHY["gemini"][1] + _KEY_FIX["gemini"][0][1])
AUTH_FAILED_BY = {"codex": AUTH_FAILED_CODEX}
SANDBOX_FAILED = ("Codex 在这台机器上不能运行命令（它的沙盒需要这个容器没有的权限）：请在输入框旁边的「对话」里给这个项目换一个 agent，或者请管理员看一下。",
                  "Codex can't run commands on this machine (its sandbox needs permissions this container doesn't have); pick another agent for this "
                  "project (the 「对话」 chip next to the message box), or ask the admin.")
CRASHED = ("agent 这次没能回复：{agent} 的进程出错退出了（退出码 {rc}，试了 {n} 次）。你再说一句，后台会重新叫 agent；一直这样的话请换一个 agent，或者请协调者看一下 agentd 日志。",
           "The agent could not reply: the {agent} process exited with an error (exit code {rc}, tried {n} times). Write again and a new agent "
           "is called; if it keeps happening, pick another agent or ask the coordinator to check the agentd log.")
LOOPED = ("agent 在原地打转（一直在重复：{acts}），已经停下了，免得白白用掉额度。你再说一句，后台会重新叫 agent。",
          "The agent was going round in circles (repeating: {acts}), so it was stopped before it used up more quota. Write again and a new agent is called.")
# one short line per message she writes while backed off (the full reason was said once above; repeating it made a run-on sentence, QA2 2026-10-30)
WAITING = ("这句话先记下了。{why}，大约 {at} 会自动再试一次。", "Noted. {why_en}; it tries again by itself around {at}.")
# the chosen model was refused (agent_providers.MODEL_NEEDLES): her CLI is too old for it, or the account / key has no access to it
MODEL_FAILED = ("现在选的模型（{agent} 的 {model}）用不了：{agent} 拒绝了它（账号或 key 没有这个模型的权限）。请在输入框旁边的「对话」里换一个模型或 agent。",
                "The chosen model ({agent}: {model}) cannot be used: {agent} refused it (the account or key has no access to it). Pick another "
                "model or agent (the 「对话」 chip next to the message box).")
MODEL_CLI_OLD = ("现在选的模型（{agent} 的 {model}）用不了：多半是这台电脑上的 claude 命令行版本太旧。请让协调者（桌面 App 里的 Claude）运行 `claude update`，或者在输入框旁边的「对话」里换一个模型。",
                 "The chosen model ({agent}: {model}) cannot be used, most likely because the claude CLI on this computer is too old: ask the coordinator "
                 "(Claude in the desktop app) to run `claude update`, or pick another model (the 「对话」 chip next to the message box).")
WAITING_WHY = {"auth": ("agent 的登录或 key 有问题（上面说了怎么办）", "the agent's login or key has a problem (see above)"),
               "model": ("现在选的模型用不了（上面说了怎么办）", "the chosen model cannot be used (see above)"),
               "limit": ("agent 的用量到上限了", "the agent's usage limit is reached"),
               "sandbox": ("这个 agent 在这台机器上用不了（上面说了怎么办）", "this agent cannot work on this machine (see above)")}
# a provider that cannot work (login, quota, its sandbox): new words do not start a run before `until` (.agentd_backoff.json); the page says why
BACKOFF_SECS = {"auth": 15 * 60, "sandbox": 6 * 3600, "model": 6 * 3600}
SKILL = shipped.SKILL                           # the skill: the checkout's skills/gameanything, or the copy in an installed package (shipped.py)
PROMPT = SKILL / "references" / "resident-prompt.md"
CORE = SKILL / "core.md"                        # layered prompt (kinds that opted in, flow.OPT_IN): core + mode + the current step doc
MAX_CORRECTIONS = 1                             # corrective re-runs per flow step and message when a run skipped the step's required action
LIMIT_RETRY_SECS = 15 * 60                      # a run that stopped on a usage limit without a reset time: try again this much later
LIMIT_MAX_WAIT_SECS = 8 * 3600
PROVIDER_LABEL = {"claude-code": "Claude", "codex": "Codex", "opencode": "OpenCode", "gemini": "Gemini", "dsh": "DeepSeek Harness"}
MAX_CONTINUE = 4                                # continuation runs per message of hers when a run finished its step and the next one is the agent's
UNREAD_IN_PROMPT = 8
HOST = socket.gethostname()


def _read(p: Path):
    try: return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError): return None


def _write(p: Path, d):
    p.parent.mkdir(parents=True, exist_ok=True); tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8"); os.replace(tmp, p)


def _age(ts) -> float: return Thread._age(ts)


# ---------------------------------------------------------------- what the page and the other commands read
def heartbeat_path() -> Path: return projects.data_dir() / "agentd.json"


def daemon_state() -> dict:
    """{alive, at, pid}: alive while the heartbeat is fresh and (on this host) its process runs."""
    d = _read(heartbeat_path()) or {}
    alive = bool(d) and _age(d.get("at")) <= HEARTBEAT_STALE_SECS and (d.get("host") != HOST or osdirs.pid_alive(d.get("pid"), d.get("pid_start")))
    return {"alive": alive, "at": d.get("at"), "pid": d.get("pid")}


def ensure_running(env=None) -> str:
    """Start the supervisor detached unless it already runs (`gameanything ui` calls this: without agentd every chat message ends as
    「后台调度没有运行，暂时没有 agent 来读」). GAMEANYTHING_NO_AGENTD=1 turns it off. Returns what happened: running / started / off / no_claude / no_agent / failed."""
    env = os.environ if env is None else env
    if env.get("GAMEANYTHING_NO_AGENTD"): return "off"
    if daemon_state()["alive"]: return "running"
    provider_name = (env.get("GAMEANYTHING_AGENT_PROVIDER") or "claude-code").lower().replace("_", "-")
    exe_name, var = agent_providers.EXE.get(provider_name, agent_providers.EXE["claude-code"]); override = env.get(var)
    fallback = Path.home() / ".local" / "bin" / exe_name
    if not ((override and Path(override).is_file()) or shutil.which(exe_name, path=env.get("PATH")) or fallback.exists()):
        return "no_claude" if provider_name == "claude-code" else "no_agent"
    # the supervisor runs the SAME install as this page: the gameanything script beside this Python (its venv), else this Python itself.
    # Not a PATH lookup: on her Mac that found ~/.local/bin/m2w, an older install in another venv (2026-11-01). sys.argv[0] can be "-c".
    here = Path(sys.executable).parent
    exe = next((str(here / n) for n in ("gameanything", "gameanything.exe") if (here / n).is_file()), None)
    cmd = [exe] if exe else [sys.executable, "-c", "import sys; from gameanything.cli import main; sys.exit(main())"]
    log = projects.data_dir() / "agentd-ui.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(log, "ab") as fh:
            subprocess.Popen(cmd + ["agentd", "run"], stdin=subprocess.DEVNULL, stdout=fh, stderr=fh, start_new_session=True, env=dict(env))
    except OSError: return "failed"          # the page still opens; its banner says no agent is reading
    return "started"


def auth_failed(log) -> bool:
    """True when a run's stream-json log says the CLI could not authenticate (401 / not logged in): retrying cannot help."""
    try: txt = Path(log).read_text(encoding="utf-8", errors="replace")[-20000:]
    except (OSError, TypeError): return False
    return "authentication_failed" in txt or "Not logged in" in txt or "OAuth access token is invalid" in txt


def run_path(T: Thread) -> Path: return T.dir / ".agentd_run.json"


def active_run(T: Thread):
    """The project's current agentd run (its record) while its process runs, else None."""
    r = _read(run_path(T))
    if not r or r.get("ended") or r.get("host") != HOST: return None
    return r if osdirs.pid_alive(r.get("pid"), r.get("pid_start")) else None


def backoff(T: Thread, clock=None):
    """{kind, text, text_en, until_at}: the project's agent CLI is backed off right now (.agentd_backoff.json, until in the future), else None."""
    b = _read(T.dir / ".agentd_backoff.json")
    if not isinstance(b, dict): return None
    try: until = float(b.get("until") or 0)
    except (TypeError, ValueError): return None
    if until <= (clock or time.time)(): return None
    zh, en = (b.get("why") or ["", ""])[:2] if len(b.get("why") or []) >= 2 else ("", "")
    from . import activity
    return {"kind": b.get("kind"), "text": zh, "text_en": en, "until_at": datetime.fromtimestamp(until).isoformat(timespec="seconds"),
            "until_hm": activity.hhmm(until), "until_hm_en": activity.hhmm(until, "en")}


def failed(T: Thread):
    """{event, at, tries}: the last run(s) did not answer the user's message `event` (shown until the user writes again)."""
    return _read(T.dir / ".agentd_failed")


def requests_dir() -> Path:
    return Path(os.environ.get("GAMEANYTHING_PARENT_REQUESTS") or projects.data_dir() / "parent-requests")


def write_request(project: Path, kind: str, text: str, details=None, session=None) -> Path:
    """A request for the coordinator (the parent session): <requests dir>/<project id>-<time>.json. Never runs anything itself.
    gen_request_ready (old form of `gameanything gen request`) goes straight into the project's gen queue (genrun.py): agentd runs it, no coordinator."""
    if kind not in REQUEST_KINDS: raise ValueError(f"kind 应该是 {' / '.join(REQUEST_KINDS)}")
    if not (text or "").strip(): raise ValueError("text 不能是空的")
    if details is not None and not isinstance(details, dict): raise ValueError("details 应该是一个对象（JSON {…}）")
    project = Path(project).resolve()
    if kind == "gen_request_ready":
        from . import genrun
        _, tool, perm, go, args = genrun.from_old_request({"path": str(project), "details": details or {}})
        return genrun.request(project, tool, perm, go, args, session)
    try: e = projects.find(project); pid, title = e["id"], e.get("title")
    except KeyError: pid, title = project.name, project.name
    d = requests_dir(); d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S"); f = d / f"{pid}-{stamp}.json"; n = 2
    while f.exists(): f = d / f"{pid}-{stamp}-{n}.json"; n += 1
    _write(f, {"project": pid, "title": title, "path": str(project), "kind": kind, "text": text.strip(), "details": details or {},
               "session": session or os.environ.get("GAMEANYTHING_SESSION"), "at": now()})
    from . import isolation
    if isolation.enabled():                       # the agent account cannot read the requests folder: a copy in its project (read only)
        try: c = project / "conversation" / ".requests"; c.mkdir(exist_ok=True); shutil.copyfile(f, c / f.name)
        except OSError: pass
    return f


NOTE_FROM = {"coordinator": "Coordinator note", "builder": "Builder note (the background build of this project)",
             "agentd-build": "Background build note (agentd)", "gen": "Paid generation note (agentd)"}


def notify(project: Path, text: str, sender="coordinator") -> Path:
    """A note for the project's agent (e.g. 「图画好了」): agentd starts a run that gets it in its prompt."""
    if not (text or "").strip(): raise ValueError("text 不能是空的")
    T = Thread(Path(project)); d = T.dir / ".agentd_inbox"; d.mkdir(parents=True, exist_ok=True)
    f = d / f"{datetime.now():%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:4]}.json"
    _write(f, {"at": now(), "from": sender, "text": text.strip()}); return f


def inbox(T: Thread) -> list:
    d = T.dir / ".agentd_inbox"
    return sorted(d.glob("*.json")) if d.is_dir() else []


# ---------------------------------------------------------------- the claude command
def claude_bin(explicit=None) -> str:
    c = explicit or os.environ.get("GAMEANYTHING_CLAUDE") or shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")
    return c


def m2w_bin() -> str:
    """The GameAnything a run should use: $GAMEANYTHING_BIN, else the one next to this Python (the same install), else `gameanything` on PATH."""
    if os.environ.get("GAMEANYTHING_BIN"): return os.environ["GAMEANYTHING_BIN"]
    for name in ("gameanything", "m2w"):                              # m2w: the old name (an install from before the rename has only it)
        here = Path(sys.executable).parent / (name + ".exe" if os.name == "nt" else name)
        if here.exists(): return str(here)
    return shutil.which("gameanything") or shutil.which("m2w") or "gameanything"


def clean_env(base=None, extra=None) -> dict:
    env = {k: v for k, v in (base or os.environ).items() if k in ENV_KEEP or not k.startswith(ENV_DROP_PREFIX)}
    env.update(extra or {}); return env


def _mode_text(root: Path) -> str:
    from . import buildmode
    mode, src = buildmode.effective(root)
    return mode if src == "project" else f"{mode} (not chosen yet: the automatic rule)"


def _where_text(root: Path) -> str:
    """Where the build really runs, in the words to use with her (QA2 2026-10-30: agents told her a server sandbox ran 「在你电脑的沙箱里」)."""
    from . import buildmode
    mode, _src = buildmode.effective(root)
    if mode == "native": return "the build changes her own copy of the game on her computer (「我的电脑（本机）」)"
    where = ((projects.config_of(root).get("setup") or {}).get("where") if isinstance(projects.config_of(root).get("setup"), dict) else None)
    if not where:
        from . import users
        try: where = "server" if users.enabled() or buildmode.headless() else "this_computer"
        except Exception: where = None
    if where == "server":
        return "the sandbox runs on the server, not on her computer: say 「服务器上的沙箱」, never 「你电脑上的沙箱」 (go card, launch_notes too)"
    if where == "this_computer":
        return "the sandbox (Docker) runs on her own computer: 「你电脑上的沙箱」, her game files are not changed"
    return "unknown yet (run `gameanything setup guide`)"


def _fill(t: str, entry: dict, root: Path, session: str, requests: Path) -> str:
    cfg = projects.config_of(root)
    vals = {"project_id": entry.get("id") or root.name, "title": entry.get("title") or cfg.get("title") or root.name,
            "kind": cfg.get("kind") or entry.get("kind") or "memory", "game": projects.game_of(root), "path": str(root), "session": session,
            "build_mode": _mode_text(root), "build_where": _where_text(root),
            "skill_dir": str(SKILL), "repo": str(shipped.ROOT), "requests_dir": str(requests)}
    for k, v in vals.items(): t = t.replace("{{" + k + "}}", str(v))
    return t


def render_prompt(entry: dict, root: Path, session: str, requests: Path, template: Path = PROMPT) -> str:
    from . import internal_docs
    return _fill(template.read_text(encoding="utf-8") + internal_docs.addendum(root), entry, root, session, requests)


def render_layered(entry: dict, root: Path, session: str, requests: Path):
    """The system prompt of a run for a kind that opted in (flow.OPT_IN): the core rules, the mode, the ONE step doc the flow says to work
    on, and that step's actions / criteria — not the whole skill. -> (prompt, step id, flow next)."""
    from . import flow
    n = flow.next_step(root); kind = n["kind"]
    parts = [CORE.read_text(encoding="utf-8"), (SKILL / flow.KIND_DOCS[kind]).read_text(encoding="utf-8")]
    if n.get("step"):
        d = Path(n["step"]["doc"])
        parts.append("## The step to work on now (from `gameanything flow next`)\n\n" + (d.read_text(encoding="utf-8") if d.is_file() else ""))
    parts.append("## Flow state now\n\n" + flow.next_text(n) + f"\n\nOther docs (cards.md, pitfalls.md, the long {Path(flow.LONG_DOCS[kind]).name}) are in "
                 "{{skill_dir}}/references/: read one only when this step needs it.")
    from . import internal_docs                 # a gamebench lab or the hub only (internal/, never the user's flow)
    return _fill("\n\n".join(parts) + internal_docs.addendum(root), entry, root, session, requests), n.get("todo"), n


def command(claude: str, model: str, prompt: str, system: str, sid: str, resume: bool, budget=None) -> list:
    """Compatibility wrapper for callers that build the historical Claude command."""
    return agent_providers.provider("claude-code", claude, model).command(
        prompt, system, sid, resume, Path.cwd(), budget)


def run_prompt(T: Thread, why: str, notes: list, layered=False, correct=None) -> str:
    """The user turn of one run: the role is in the system prompt; this says why it was started. layered (flow kinds): her unread words
    are quoted here too; correct: a corrective re-run (the last run skipped what its flow step required)."""
    if why == "correct" and (correct or {}).get("mode") == "continue":
        c = correct
        miss = "\n".join(f"- {m.get('id')}: {m.get('why')}" for m in c.get("missing") or [])
        return (f"Continuation run. The last run finished flow step `{c.get('after')}`; the next step `{c.get('step')}` is yours and is due now:\n{miss}\n\n"
                "Claim, read the chat, then do this step (the step doc is in your rules; a card goes with `gameanything chat card`, not as plain text). "
                "End with one line to her: where we are and what she should do next.")
    if why == "correct":
        c = correct or {}
        miss = "\n".join(f"- {m.get('id')}: {m.get('why')}" for m in c.get("missing") or [])
        return (f"Corrective run. The last run ended, but flow step `{c.get('step')}` still misses what it requires:\n{miss}\n\n"
                "Claim, read the chat, then do exactly these now (a card goes with `gameanything chat card`, not as plain text). Then "
                f"`gameanything flow check --project \"$P\" --step {c.get('step')}` must pass for your part. End with one line to her: where we are "
                "and what she should do next. Do not apologise at length or mention this correction.")
    head = {"words": "The user wrote in the project chat. Do the steps of EVERY RUN now: claim, read, reply.",
            "new": ("This project was just created and nobody has written yet. Claim, then greet the user in one short Chinese line at once. Then, in this "
                    "same run, read SKILL.md and the flow for this kind and send her the first step (the first question or card the flow starts with)."),
            "note": ("The coordinator, the background build or the paid-generation runner sent you a note (below). Claim, read the chat, then act on "
                     "the note and tell the user in Chinese what changed (short; a build's progress: one line). If it says a build is done: run "
                     "`gameanything build check --project \"$P\" --m <milestone>` first and post no result card while it fails (see Result cards in your rules).")}[why]
    if why == "new" and layered:
        head = ("This project was just created and nobody has written yet. Claim, then greet the user in one short Chinese line at once. "
                "Then do the first step of the flow (below) in this same run.")
    out = [head]
    if layered:
        new = T.unread()[-UNREAD_IN_PROMPT:]
        if new: out.append("Her unread words (read them with `gameanything chat read` too):\n" + "\n".join(f"- {str(e.get('text') or '')[:400]}" for e in new))
    for n in notes:
        d = _read(n) or {}
        out.append(f"{NOTE_FROM.get(d.get('from'), 'Coordinator note')} ({d.get('at', '')}): {d.get('text', '')}")
    return "\n\n".join(out)


SEED_EVENTS = 16


def seed_text(T: Thread, old: str, new: str) -> str:
    """The run that takes the chat over from another agent CLI (the owner switched the chat model to another agent): its session is new and
    knows nothing, so the prompt quotes the recent thread (her words, the agent's replies, the cards and her answers; oldest first)."""
    rows = []
    for e in T.events()[-200:]:
        f, ty = e.get("from"), e.get("type")
        if f == "user" and ty in ("text", "answer"):
            try: rows.append("她: " + T.render(e))
            except Exception: rows.append("她: " + str(e.get("text") or ""))
        elif f == "agent" and ty == "text": rows.append("agent: " + str(e.get("text") or ""))
        elif f == "agent" and ty == "card": rows.append(f"agent (card {(e.get('card') or {}).get('kind')}): " + str((e.get("card") or {}).get("title") or e.get("text") or ""))
    rows = [r.replace("\n", " ")[:400] for r in rows[-SEED_EVENTS:]]
    if not rows: return ""
    return (f"\n\nThe owner switched this project's chat from {PROVIDER_LABEL.get(old, old)} to {PROVIDER_LABEL.get(new, new)}: this is a NEW session and you "
            "have none of the earlier one's context. The recent conversation (oldest first; `gameanything chat read` and `gameanything flow next` "
            "have the rest). Carry on from where it stands; do not greet her again or restart the flow:\n" + "\n".join(f"- {r}" for r in rows))


# ---------------------------------------------------------------- the daemon
def resident_dirs(requests) -> list:
    """Where a resident run writes outside its project (Codex --add-dir): the requests folder (`gameanything agentd request`)."""
    d = Path(requests)
    try: d.mkdir(parents=True, exist_ok=True)
    except OSError: pass
    return [d] if d.is_dir() else []


def popen(cmd, cwd, env, log, run_as=None):
    """Start a run in its own process group (it survives the daemon; the daemon can stop the whole group). run_as: the agent account
    (isolation.run_env; docs/agent-isolation.md)."""
    kw = {"creationflags": 0x00000200} if os.name == "nt" else {"start_new_session": True}       # CREATE_NEW_PROCESS_GROUP
    if run_as:
        from . import isolation
        kw.update(isolation.spawn_kwargs(run_as))
    env = {**env, "PWD": str(cwd)}          # some CLIs (opencode) take their folder from $PWD, which would still be the daemon's
    return subprocess.Popen(cmd, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **kw)


def _stop(pid):
    osdirs.stop_group(pid)


class Agentd:
    def __init__(self, claude=None, model=None, log_root=None, requests=None, spawn=popen, clock=time.time, budget=None,
                 max_run_secs=RUN_MAX_SECS, template=PROMPT, quiet=False, gen_spawn=None, provider="claude-code", agent=None,
                 builds=None, lab=None):
        self.provider = agent_providers.provider(provider, agent or claude, model)
        self.claude, self.model = self.provider.binary, self.provider.model
        self.budget, self.spawn, self.clock = budget, spawn, clock
        self.log_root = Path(log_root) if log_root else projects.data_dir() / "agentd-logs"
        self.requests = Path(requests) if requests else requests_dir()
        self.max_run_secs, self.template, self.quiet = max_run_secs, Path(template), quiet
        self.procs = {}                    # project path -> Popen (runs this daemon started; reaped here)
        self.tries = {}                    # project path -> {key, n, next}: retries of a run that did not answer
        self.started = now(); self.queued = []; self.blocked = {}     # project id -> why it may not run (its owner has no Claude login, ...)
        self.gens = {}                     # project path -> the background thread of its paid generation run (genrun.py; one per project)
        self.gen_spawn = gen_spawn
        self.refs = {}                     # project path -> the background thread downloading its queued reference pictures (refs.py)
        self.refs_opener = None            # tests: a fake urllib opener / resolver
        self.refs_resolve = None
        from . import live as _live
        self.live = _live.Live(log=self.log)          # agentd's own words in her chat about background work (live.py)
        from . import builds as _b
        self.builds_mode = _b.mode({"GAMEANYTHING_BUILDS": builds} if builds else None)     # auto: agentd runs build requests (builds.py)
        self.builds = _b.Builds(self, lab) if self.builds_mode == "auto" else None

    # ---- log
    def log_dir(self) -> Path:
        d = self.log_root / datetime.now().strftime("%Y-%m-%d"); d.mkdir(parents=True, exist_ok=True); return d

    def log(self, msg):
        line = f"{now()} {msg}"
        try:
            with open(self.log_dir() / "agentd.log", "a", encoding="utf-8") as f: f.write(line + "\n")
        except OSError: pass
        if not self.quiet: print(line, flush=True)

    # ---- one scan
    def tick(self):
        cap = projects.settings()["max_active_projects"]; rows = []
        self._old_gen_requests()
        for e in projects.load():
            root = Path(e["path"])
            if not (root / "conversation").is_dir() or not (root / "config" / "project.yaml").exists(): continue
            T = Thread(root)
            try:
                self._gen(e, T)
                self._refs(T)
                if self.builds:
                    try: self.builds.scan(e, T)
                    except Exception as x: self.log(f"{e['id']}: build scan failed ({type(x).__name__}: {x})")
                self._reap(e, T)
                run = active_run(T)
                if not run:
                    try: decisions.note_forged(root, T)        # an agent's own 「已确认」: her chat says it does not count (decisions.py)
                    except Exception as x: self.log(f"{e['id']}: forged-confirmation check failed ({type(x).__name__}: {x})")
                if run and self.clock() - _ts(run.get("started")) > self.max_run_secs:
                    self.log(f"{e['id']}: run {run['run_id']} over {self.max_run_secs // 60} min, stopping it"); _stop(run["pid"])
                if run:
                    try: tl = self.live.resident(e, T, run)
                    except Exception as x: tl = None; self.log(f"{e['id']}: live resident check failed ({type(x).__name__}: {x})")
                    if tl is not None: self._loop_check(e, T, run, tl)
                if str(root) in self.gens:
                    try: self.live.gen(e, T)
                    except Exception as x: self.log(f"{e['id']}: live gen check failed ({type(x).__name__}: {x})")
                live = bool(run) or T.owner_live()
                why, key, at = self._wants(e, T) if not live else (None, None, None)
                if why and self._backoff(e, T, why, key): why = key = at = None
                blk = users.run_env(root, {}, self.provider_for(root).name)[1] if why else None
                if blk:
                    if self.blocked.get(e["id"]) != blk: self.log(f"{e['id']}: not run: {blk}")
                    self.blocked[e["id"]] = blk; why = key = at = None
                else: self.blocked.pop(e["id"], None)
                rows.append((e, T, live, why, key, at))
            except (OSError, ValueError) as x:
                self.log(f"{e.get('id')}: skipped this scan ({type(x).__name__}: {x})")
        ids = {r[0]["id"] for r in rows}; self.blocked = {k: v for k, v in self.blocked.items() if k in ids}   # removed projects drop out
        holding = [r[0].get("title") or r[0]["id"] for r in rows if r[2]]; self.queued = []      # the projects that hold a slot
        for e, T, live, why, key, at in sorted((r for r in rows if not r[2] and r[3]), key=lambda r: str(r[5] or "")):
            if self._held(T, key): continue
            if len(holding) < cap:
                try:
                    if self.start(e, T, why, key): holding.append(e.get("title") or e["id"])
                except (OSError, ValueError) as x: self.log(f"{e['id']}: could not start a run ({type(x).__name__}: {x})")
                (T.dir / ".agent_queued").unlink(missing_ok=True)
            else:
                _write(T.dir / ".agent_queued", {"at": now(), "active": len(holding), "cap": cap, "projects": holding}); self.queued.append(e["id"])
        self.beat(rows)
        return rows

    def _wants(self, e, T):
        """(why, key, at) when the project needs a run: new user words, a coordinator note, or a brand-new project; else Nones."""
        new = T.unread()
        if new: return "words", new[-1]["id"], new[0]["at"]
        notes = inbox(T)
        if notes: return "note", notes[-1].name, (_read(notes[0]) or {}).get("at") or now()
        c = _read(T.dir / ".agentd_correct.json")
        if c: return "correct", c.get("key") or "correct", c.get("at") or now()
        # a brand-new project nobody has greeted: no word of hers or of an agent yet (status lines do not count). Its greeting run is retried
        # like any other (QA 2026-10-29: the first greeting that failed was never retried, the check wanted no run file at all)
        if (not any(x.get("from") in ("user", "agent") for x in T.events())
                and (failed(T) or {}).get("event") != "new-project"):
            return "new", "new-project", e.get("created") or now()
        return None, None, None

    # ---- a provider that cannot work right now (login, usage limit, its sandbox): wait, say so once per message, no run per message
    def _backoff(self, e, T, why, key) -> bool:
        """True while the project's agent CLI is backed off (.agentd_backoff.json): no run starts; new words of hers get one status line saying
        why and when the next try is. The backoff ends at `until` (one fresh try, also for the words that waited) or when she picks another agent."""
        bf = T.dir / ".agentd_backoff.json"; b = _read(bf)
        if not b: return False
        p_ = self.provider_for(T.root); prov = p_.name
        if b.get("kind") == "model" and b.get("model") != (p_.model or None): prov = f"{prov} ({p_.model or 'default model'})"   # she picked another model
        if b.get("provider") != prov or self.clock() >= float(b.get("until") or 0):
            # over: one fresh try for the words that waited (a usage limit: they are answered by themselves). The same words are tried
            # once after a backoff, not every BACKOFF_SECS: when it fails again, her NEXT words start the next run
            bf.unlink(missing_ok=True); k = str(T.root); t = self.tries.get(k) or {}
            if b.get("kind") == "limit" or b.get("provider") != prov: self.tries.pop(k, None)
            elif key and key in (b.get("keys") or [])[1:] and t.get("bo_retried") != key:     # words she wrote while it waited
                self.tries[k] = {"key": key, "n": len(RETRY_AFTER), "next": 0, "bo_retried": key}
            self.log(f"{e['id']}: {b.get('provider')} backoff ({b.get('kind')}) over" + (f": {prov} is used now" if b.get("provider") != prov else ""))
            return False
        if why == "words" and key and key not in (b.get("keys") or []):
            from . import activity
            zh, en = b.get("why") or ["", ""]; wz, we = WAITING_WHY.get(b.get("kind"), WAITING_WHY["auth"])
            T.append({"from": "system", "type": "status", "text": WAITING[0].format(why=wz, at=activity.hhmm(b.get("until"))),
                      "text_en": WAITING[1].format(why_en=we, at=activity.hhmm(b.get("until"), "en")), "live": "resident_pause"})
            b["keys"] = (b.get("keys") or [])[-20:] + [key]; _write(bf, b)
            if b.get("kind") != "limit": _write(T.dir / ".agentd_failed", {"event": key, "at": now(), "tries": 0, "reason": b.get("kind"), "text": zh, "text_en": en,
                                              "until": b.get("until")})
        return True

    def _set_backoff(self, T, kind, provider_name, secs, why, key, model=None):
        _write(T.dir / ".agentd_backoff.json", {"kind": kind, "provider": provider_name, "at": now(), "until": self.clock() + secs,
                                                "why": list(why), "keys": [key] if key else [], **({"model": model} if kind == "model" else {})})

    def _notice(self, T, kind, provider_name, msg, key, said_key):
        """One status line per (reason, message): the same failure of the same message is not said twice."""
        said = _read(T.dir / ".agentd_said.json") or {}
        if said.get(kind) == said_key: return
        T.append({"from": "system", "type": "status", "text": msg[0], "text_en": msg[1], "live": "resident_pause"})
        said[kind] = said_key; _write(T.dir / ".agentd_said.json", said)

    # ---- a run that goes round in circles (activity.Tail.looping): stopped early, she is told, no retry
    def _loop_check(self, e, T, run, tail):
        acts = tail.looping()
        if not acts or run.get("stopped"): return
        run["stopped"] = "loop"; run["loop"] = acts; _write(run_path(T), run)
        self.log(f"{e['id']}: run {run['run_id']} is looping ({' / '.join(acts)}): stopping it"); _stop(run["pid"])

    def _held(self, T, key) -> bool:
        """A run for this same message did not answer: wait before retrying; after the last retry, wait for new words."""
        t = self.tries.get(str(T.root))
        if not t or t["key"] != key: return False
        return t["n"] > len(RETRY_AFTER) or self.clock() < t["next"]

    # ---- paid generation (genrun.py): checked and run here, in the background, one per project; the outcome is a note for the agent
    def _gen(self, e, T):
        from . import genrun
        k = str(T.root); t = self.gens.get(k)
        if t is not None:
            if t.is_alive(): return
            self.gens.pop(k, None)
        if genrun.busy_elsewhere(T.root): return              # a run of an earlier agentd still goes
        for qf in genrun.pending(T.root):
            if ((_read(qf) or {}).get("state")) == "running": continue
            kw = {"spawn": self.gen_spawn} if self.gen_spawn else {}
            t = genrun.start(T.root, qf, self.log_dir(), log=self.log, **kw)
            if t is not None: self.gens[k] = t; return

    # ---- reference pictures (refs.py): a run queues `gameanything refs fetch`; checked again (her websearch card, the query) and downloaded here,
    # on the host (a Codex resident's sandbox has no network), one project at a time in the background
    def _refs(self, T):
        from . import refs
        k = str(T.root); t = self.refs.get(k)
        if t is not None and t.is_alive(): return
        self.refs.pop(k, None)
        qs = refs.pending(T.root)
        if not qs: return

        def work():
            for qf in qs:
                st, res = refs.process(T.root, qf, self.refs_opener, self.refs_resolve, notify=lambda r, text: notify(r, text, sender="refs"))
                self.log(f"{T.root.name}: refs {qf.name} {st}" + (f" ({res.get('why')})" if res.get("why") else ""))
        t = threading.Thread(target=work, name=f"refs-{T.root.name}", daemon=True); t.start(); self.refs[k] = t

    def _old_gen_requests(self):
        """Old-style coordinator requests kind gen_request_ready in the requests dir -> the project's gen queue (the file moves to converted/)."""
        from . import genrun
        if not self.requests.is_dir(): return
        for f in sorted(self.requests.glob("*.json")):
            d = _read(f)
            if not isinstance(d, dict) or d.get("kind") != "gen_request_ready": continue
            dest = self.requests / "converted"; dest.mkdir(exist_ok=True)
            try:
                root, tool, perm, go, args = genrun.from_old_request(d)
                q = genrun.request(root, tool, perm, go, args, d.get("session")); out = f"queued {q}"
            except (ValueError, OSError) as x:
                out = f"refused: {x}"
                if d.get("path") and (Path(d["path"]) / "conversation").is_dir():
                    notify(d["path"], f"付费生成的请求没有执行：{x}。请用简单的中文告诉用户还缺什么。", sender="gen")
            _write(dest / f.name, {**d, "converted": out, "converted_at": now()}); f.unlink(missing_ok=True)
            self.log(f"old gen request {f.name}: {out}")

    def wait_gens(self, timeout=30):
        for t in list(self.gens.values()): t.join(timeout)

    # ---- start / finish a run
    def provider_for(self, root, role="chat", choice=None):
        """The agent CLI + model of this project's chat (role chat) or builds (role build): the project's choice (models.py, config/project.yaml
        chat_model / build_model; choice: a go card runner {agent, model}), else the owner's (hub), else the daemon's --provider / --model."""
        from . import models
        c = choice or models.effective(root, role, (self.provider.name, self.provider.model))
        name, model = c["agent"], models.run_model(c["agent"], c.get("model"))
        same = name == self.provider.name
        if same and (model or None) == (self.provider.model or None): return self.provider
        return agent_providers.provider(name, binary=self.provider.binary if same else None, model=model)

    def start(self, e, T, why, key) -> bool:
        pid_ = e["id"]; session = f"agentd:{pid_}"; run_id = uuid.uuid4().hex[:12]
        prov = self.provider_for(T.root)                     # the owner's choice of agent CLI (hub), else the daemon's
        nope = prov.unavailable()                            # Codex whose sandbox cannot start here (cached probe): no run would work
        if nope:
            self.log(f"{pid_}: {prov.name} cannot work on this machine ({nope}): no run; she is told to pick another agent")
            self._set_backoff(T, "sandbox", prov.name, BACKOFF_SECS["sandbox"], SANDBOX_FAILED, key)
            self._notice(T, "sandbox", prov.name, SANDBOX_FAILED, key, f"sandbox|{prov.name}|{key}")
            _write(T.dir / ".agentd_failed", {"event": key, "at": now(), "tries": 0, "reason": "sandbox", "text": SANDBOX_FAILED[0], "text_en": SANDBOX_FAILED[1]})
            return False
        if why == "words":
            T.set_calling(key)
            f = T.dir / ".agent_calling_line"
            if not (f.exists() and time.time() - f.stat().st_mtime < CALLING_EVERY_SECS):
                f.write_text(now(), encoding="utf-8")
                T.append({"from": "system", "type": "status", "text": CALLING[0], "text_en": CALLING[1], "session": session})
        sess = _read(T.dir / ".agent_session") or {}
        session_provider = sess.get("provider") or "claude-code"
        resume = (session_provider == prov.name and bool(sess.get("id")) and
                  _age(sess.get("created")) <= SESSION_MAX_AGE_SECS and
                  int(sess.get("runs") or 0) < SESSION_MAX_RUNS and not sess.get("broken"))
        sid = sess["id"] if resume else prov.new_session_id()
        switched = sess.get("provider") if sess.get("id") and session_provider != prov.name else None    # another agent CLI: a new session, seeded
        notes = inbox(T) if why == "note" else []
        correct = _read(T.dir / ".agentd_correct.json") if why == "correct" else None
        from . import flow
        layered = (self.template == PROMPT and os.environ.get("GAMEANYTHING_LAYERED", "1") != "0"
                   and flow.opted_in(projects.config_of(T.root).get("kind")))
        fstep, fmiss = None, []
        if layered:
            try:
                system, fstep, _n = render_layered(e, T.root, session, self.requests)
                fmiss = [c["id"] for c in flow.agent_missing(T.root, fstep)] if fstep else []
            except Exception as x:                          # the long resident prompt is the fallback (never a run without rules)
                self.log(f"{pid_}: layered prompt failed ({type(x).__name__}: {x}); using resident-prompt.md"); layered = False
        if not layered: system = render_prompt(e, T.root, session, self.requests, self.template)
        env = clean_env(extra={"GAMEANYTHING_SESSION": session, "GAMEANYTHING_INSTANCE": run_id, "GAMEANYTHING_PARENT_REQUESTS": str(self.requests), "GAMEANYTHING_BIN": m2w_bin()})
        env = prov.clean_env(env)
        env, blk = users.run_env(T.root, env, prov.name)    # the owner's login (hub); unchanged without a hub
        if blk: self.log(f"{pid_}: not run: {blk}"); self.blocked[pid_] = blk; return False
        env = agent_providers.agent_env(env, prov)          # no paid keys in a run (genrun.py gets them)
        env["PATH"] = str(Path(m2w_bin()).parent) + os.pathsep + env.get("PATH", "")
        prompt = run_prompt(T, why, notes, layered, correct) + (seed_text(T, switched, prov.name) if switched else "")
        run_tmp = agent_providers.run_tmpdir(pid_, run_id); env = agent_providers.with_run_tmp(env, run_tmp)   # its own TMPDIR (hotfix 2026-10-30)
        run_as = self._isolate(e, T, env, run_id, run_tmp)
        if run_as is False: return False
        if run_as: env = run_as.pop("env")
        cmd, env = prov.launch(prompt, system, sid, resume, T.root, self.budget if prov.name == "claude-code" else None,
                               add_dirs=[] if run_as else resident_dirs(self.requests),
                               shell_set={k: env[k] for k in ("GAMEANYTHING_KEYS_FILE",) if env.get(k)}, env=env)
        if run_as:
            from . import isolation
            isolation.after_launch(env, run_as)
        logf = self.log_dir() / "agentd-runs" / f"{pid_}-{datetime.now():%H%M%S}-{run_id}.jsonl"; logf.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(logf, "ab") as lf: p = self.spawn(cmd, T.root, env, lf, **({"run_as": run_as} if run_as else {}))
        except BaseException: agent_providers.drop_run_tmp(run_tmp); raise
        try: T.claim(session, proc=p.pid, inst=run_id)
        except Owned:                                       # someone claimed it in the last second: let them have it
            _stop(p.pid); agent_providers.drop_run_tmp(run_tmp); self.log(f"{pid_}: another session claimed the chat first, run {run_id} stopped"); return False
        self.procs[str(T.root)] = p
        _write(run_path(T), {"run_id": run_id, "pid": p.pid, "pid_start": osdirs.pid_start(p.pid), "host": HOST, "session": session,
                             "agent_provider": prov.name, "agent_model": prov.model, "switched_from": switched, "agent_session": sid, "claude_session": sid if prov.name == "claude-code" else None,
                             "resume": resume, "why": why, "key": key, "started": now(), "log": str(logf),
                             "events_before": len(T.events()), "notes": [n.name for n in notes],
                             "prompt_chars": len(system), "flow_step": fstep, "flow_missing": fmiss, "correct": correct, "tmpdir": str(run_tmp),
                             **({"account": run_as["account"]} if run_as else {})})
        # .agentd_correct.json and the notes stay until the run ended (_reap): a run that fails is retried with them (QA 2026-10-29: the
        # correction file was deleted at start, so a failed corrective run was never retried)
        if sid:
            _write(T.dir / ".agent_session", {"id": sid, "provider": prov.name, "model": prov.model,
                                              "created": sess.get("created") if resume else now(), "last_used": now(),
                                              "runs": (int(sess.get("runs") or 0) if resume else 0) + 1})
        sid_text = sid[:8] if sid else "pending"
        self.log(f"{pid_}: {prov.name} ({prov.model or 'default model'}) run {run_id} started for {why} {key} (pid {p.pid}, {'resume' if resume else 'new'} session {sid_text}"
                 + (f", switched from {switched}: seeded with the recent thread" if switched else "") + f", log {logf.name})")
        return True

    def _isolate(self, e, T, env, run_id, run_tmp):
        """Isolation on (docs/agent-isolation.md): the run's env and account; False when it must not start (said in the log and the status). Off: None."""
        from . import isolation
        if not isolation.enabled(): return None
        try: env2, run_as = isolation.run_env(T.root, env, run_id, tmp=run_tmp)
        except (isolation.IsolationError, OSError) as x:
            why = f"agent account: {x}"
            self.log(f"{e['id']}: not run: {why}"); self.blocked[e["id"]] = why; agent_providers.drop_run_tmp(run_tmp); return False
        self.ensure_gate()
        return {**run_as, "env": env2}

    def ensure_gate(self):
        """Isolation on: the gate (gate.py) listens while this daemon runs: the only way the runs write the conversation."""
        from . import isolation
        if getattr(self, "gate", None) is not None or not isolation.enabled(): return getattr(self, "gate", None)
        from .gate import Gate
        try: self.gate = Gate(self.run_for, log=self.log).start()
        except OSError as x: self.log(f"gate could not start: {x}"); self.gate = None
        return self.gate

    def run_for(self, pids):
        """The gate: the live run (resident or builder) whose process is one of `pids` (the caller and its parents)."""
        from . import builds as _b, isolation
        pids = set(int(p) for p in pids)
        for e in projects.load():
            root = Path(e.get("path") or "")
            if not (root / "conversation").is_dir(): continue
            T = Thread(root); r = active_run(T)
            if r and int(r.get("pid") or 0) in pids:
                return {"root": str(root), "project": e["id"], "session": r.get("session"), "run_id": r.get("run_id"), "role": "resident",
                        "account": r.get("account") or isolation.account_for(root), "tmp": r.get("tmpdir")}
            for m, b in _b.records(root):
                if b.get("state") == "running" and int(b.get("pid") or 0) in pids and osdirs.pid_alive(b.get("pid"), b.get("pid_start")):
                    return {"root": str(root), "project": e["id"], "session": f"builder:{e['id']}", "run_id": b.get("run_id"), "role": "builder",
                            "account": b.get("account") or isolation.account_for(root), "lease": b.get("lease"), "tmp": b.get("tmpdir"), "milestone": m}
        return None

    def _reap(self, e, T):
        """A run that ended (ours, or adopted from an earlier daemon): release the chat, judge whether it answered and why it failed, plan a
        retry or a backoff, and tell her the reason (not logged in / usage limit / the agent cannot work here / it crashed / it looped)."""
        r = _read(run_path(T))
        if not r or r.get("ended") or r.get("host") != HOST: return
        p = self.procs.get(str(T.root)); rc = None
        if p is not None and p.pid == r.get("pid"):
            rc = p.poll()
            if rc is None: return
            self.procs.pop(str(T.root), None)
        elif osdirs.pid_alive(r.get("pid"), r.get("pid_start")): return
        provider_name = r.get("agent_provider") or "claude-code"
        run_provider = self.provider if self.provider.name == provider_name else agent_providers.provider(provider_name)
        sid = r.get("agent_session") or r.get("claude_session") or run_provider.session_id(r.get("log"))
        if sid and not r.get("agent_session"):
            r["agent_session"] = sid
            old = _read(T.dir / ".agent_session") or {}
            if not r.get("resume") or old.get("id") != sid: old = {}     # a new session (Codex learns its id only now): its own age and count
            _write(T.dir / ".agent_session", {"id": sid, "provider": provider_name, "created": old.get("created") or r.get("started") or now(),
                                              "last_used": now(), "runs": int(old.get("runs") or 0) + 1})
        evs = T.events(); after = evs[int(r.get("events_before") or 0):]
        answered = any(x.get("from") == "agent" for x in after)
        if r.get("why") == "words": answered = answered and not any(x["id"] == r.get("key") for x in T.unread())
        try: ast = self.live.resident_end(T.root, r) or {}
        except Exception: ast = {}
        from . import activity
        pause = ast.get("pause") or activity.scan_log(r.get("log"), provider_name)
        fail = run_provider.failure(r.get("log"))                          # sandbox | auth | model | None
        if not fail and pause and pause.get("kind") == "limit": fail = "limit"
        if not fail and r.get("stopped") == "loop": fail = "loop"
        if not fail and isinstance(rc, int) and rc > 0: fail = "crash"           # an error exit (a signal: stopped, by us or the system)
        r.update(ended=now(), rc=rc, answered=answered, failure=fail); _write(run_path(T), r)
        agent_providers.drop_run_tmp(r.get("tmpdir"))
        T.release(r["session"], r["run_id"])
        secs = _ts(r["ended"]) - _ts(r["started"])
        self.log(f"{e['id']}: run {r['run_id']} ended rc={rc} after {secs:.0f} s, {'answered' if answered else 'NO ANSWER'}" + (f" ({fail})" if fail else ""))
        k = str(T.root); key = r.get("key"); label = PROVIDER_LABEL.get(provider_name, provider_name)
        if answered:
            self.tries.pop(k, None); (T.dir / ".agentd_failed").unlink(missing_ok=True); self._handed_over(T, r)
            if fail in ("auth", "sandbox", "limit", "model"):               # it answered, then stopped: what it did not finish waits, and she knows why
                self._stopped_by(e, T, r, fail, provider_name, pause, (ast.get("live") or {}).get("said_pause"))
                return
            if fail: self.log(f"{e['id']}: run {r['run_id']} answered but exited with {fail} (rc={rc})")
            try: self._flow_after(e, T, r, secs)
            except Exception as x: self.log(f"{e['id']}: flow check after the run failed ({type(x).__name__}: {x})")
            return
        if fail in ("auth", "sandbox", "limit", "model"):
            self._stopped_by(e, T, r, fail, provider_name, pause, (ast.get("live") or {}).get("said_pause")); return
        if r.get("resume") and secs < 60:                  # a resumed session that fails fast is likely broken: start the next one fresh
            s = _read(T.dir / ".agent_session") or {}
            if s.get("id") == sid: s["broken"] = True; _write(T.dir / ".agent_session", s)
        t = self.tries.get(k) if (self.tries.get(k) or {}).get("key") == key else {"key": key, "n": 0}
        t["n"] += 1
        if fail == "loop":
            acts = "、".join((r.get("loop") or [])[:3])
            msg = (LOOPED[0].format(acts=acts), LOOPED[1].format(acts=", ".join((r.get("loop") or [])[:3])))
            self._give_up(e, T, r, t, "loop", msg)
        elif t["n"] <= len(RETRY_AFTER):
            t["next"] = self.clock() + RETRY_AFTER[t["n"] - 1]; self.log(f"{e['id']}: will retry in {RETRY_AFTER[t['n'] - 1]} s")
            if t["n"] == 1 and r.get("why") == "words" and key:          # she hears at once (the 「收到」 line is posted at most every 10 min)
                T.set_calling(key)
                T.append({"from": "system", "type": "status", "text": RETRYING[0].format(s=RETRY_AFTER[0]), "text_en": RETRYING[1].format(s=RETRY_AFTER[0]),
                          "session": r.get("session")})
        else:
            msg = ((CRASHED[0].format(agent=label, rc=rc, n=t["n"]), CRASHED[1].format(agent=label, rc=rc, n=t["n"])) if fail == "crash" else FAILED)
            self._give_up(e, T, r, t, fail or "no_answer", msg)
        self.tries[k] = t

    def _handed_over(self, T, r):
        """The run's own inputs are used up: its notes move to .agentd_inbox/done, its correction file goes (a newer one may follow)."""
        for name in r.get("notes") or []:
            n = T.dir / ".agentd_inbox" / name
            if n.exists():
                d = T.dir / ".agentd_inbox" / "done"; d.mkdir(exist_ok=True); os.replace(n, d / n.name)
        c = T.dir / ".agentd_correct.json"
        if r.get("why") == "correct" or (r.get("answered") and c.exists()): c.unlink(missing_ok=True)

    def _give_up(self, e, T, r, t, reason, msg):
        """The last try did not answer: the page says why until she writes again; the run's inputs are dropped (no endless retries)."""
        runs = t["n"]; t["n"] = max(t["n"], len(RETRY_AFTER) + 1)       # the log says how many runs there really were (a loop: 1)
        _write(T.dir / ".agentd_failed", {"event": r.get("key"), "at": now(), "tries": runs, "log": r.get("log"), "reason": reason,
                                          "text": msg[0], "text_en": msg[1]})
        self._notice(T, reason, r.get("agent_provider"), msg, r.get("key"), f"{reason}|{r.get('key')}")
        self._handed_over(T, r)
        self.log(f"{e['id']}: gave up on {r.get('key')} after {runs} run(s) ({reason})")

    def _stopped_by(self, e, T, r, fail, provider_name, pause, said_pause=False):
        """A run stopped by something no retry fixes now: the login (auth), the CLI's sandbox, a usage limit. The project backs off (no run per
        message: _backoff), she is told once why and what to do; after a usage limit the same words are answered by themselves at the reset."""
        from . import activity
        k = str(T.root); key = r.get("key"); label = PROVIDER_LABEL.get(provider_name, provider_name)
        if fail == "limit":
            rs = (pause or {}).get("resets"); wait = (float(rs) - self.clock() + 30) if rs else LIMIT_RETRY_SECS
            wait = min(max(wait, 60), LIMIT_MAX_WAIT_SECS)
            zh = f"agent 现在回复不了：{label} 的用量到上限了" + (f"，大约 {activity.hhmm(rs)} 恢复" if rs else "")
            en = f"The agent cannot answer right now: the {label} usage limit is reached" + (f" (resets around {activity.hhmm(rs, 'en')})" if rs else "")
            msg = (zh + "。到时候会自动接着回复你，不用再说一遍。", en + ". It answers by itself after that; no need to write again.")
            self.tries[k] = {"key": key, "n": 1, "next": self.clock() + wait, "limit": True}
            self._set_backoff(T, "limit", provider_name, wait, (zh, en), key)
            if (_read(T.dir / ".agentd_limit.json") or {}).get("key") != key and not said_pause:
                self._notice(T, "limit", provider_name, msg, key, f"limit|{key}")
            _write(T.dir / ".agentd_limit.json", {"key": key, "at": now(), "resets": rs})
            self.log(f"{e['id']}: run {r['run_id']} hit the {provider_name} usage limit; next try in {wait / 60:.0f} min")
            return
        model = r.get("agent_model")
        msg = SANDBOX_FAILED if fail == "sandbox" else model_notice(provider_name, model) if fail == "model" else auth_notice(provider_name)
        self.tries[k] = {"key": key, "n": len(RETRY_AFTER) + 1, "auth": key, "bo_retried": (self.tries.get(k) or {}).get("bo_retried")}
        self._set_backoff(T, fail, provider_name, BACKOFF_SECS[fail], msg, key, model=model)
        _write(T.dir / ".agentd_failed", {"event": key, "at": now(), "tries": 1, "log": r.get("log"), "reason": fail, "text": msg[0], "text_en": msg[1]})
        self._notice(T, fail, provider_name, msg, key, f"{fail}|{provider_name}|{key}")
        if fail == "sandbox":
            try: (projects.data_dir() / "agent-homes" / "codex-sandbox.json").unlink(missing_ok=True)   # probe again (the run proved it fails)
            except OSError: pass
            self.log(f"{e['id']}: the {provider_name} sandbox cannot start on this machine: backed off, she is told to pick another agent")
        elif fail == "model":
            self.log(f"{e['id']}: {provider_name} refused the model {model or '(default)'}: backed off until she picks another model, no more runs for {key}")
        else:
            prov_ = agent_providers.provider(provider_name, binary="-")
            what = "key is out of credit (402)" if prov_.out_of_credit(r.get("log")) else "CLI is not logged in"
            self.log(f"{e['id']}: the {provider_name} {what}: backed off {BACKOFF_SECS[fail] // 60} min, no more runs for {key}")

    def _flow_after(self, e, T, r, secs):
        """A run of a flow kind that ended without doing what its step required now (e.g. the step needs a choice card and none was
        sent): ONE corrective re-run with an explicit instruction (MAX_CORRECTIONS per step and message; logged).
        A run that finished its step while the next step is again the agent's (ingest -> copyright -> the units card): a continuation run
        for that step (one step per run; MAX_CONTINUE per message of hers), so she is not left waiting for a step nobody starts."""
        from . import flow
        step = r.get("flow_step")
        if not step or secs >= self.max_run_secs * 0.9: return
        c = r.get("correct") or {}; origin = c.get("origin") or r.get("key")
        todo = flow.state(T.root)["todo"]
        hf = T.dir / ".agentd_flow.json"; h = _read(hf) or {}
        if todo and todo != step:
            due = flow.agent_missing(T.root, todo)
            if not due: return
            k = f"continue|{origin}"
            if h.get(k, 0) >= MAX_CONTINUE:
                self.log(f"{e['id']}: flow step {todo} is due but {h[k]} continuation run(s) for {origin} already ran: left for the next message"); return
            h[k] = h.get(k, 0) + 1; _write(hf, h)
            _write(T.dir / ".agentd_correct.json", {"at": now(), "key": f"continue-{r['run_id']}", "mode": "continue", "step": todo, "after": step,
                                                    "origin": origin, "missing": [{"id": x["id"], "why": x["why"]} for x in due]})
            self.log(f"{e['id']}: run {r['run_id']} finished flow step {step}; the next step {todo} is the agent's: one continuation run")
            return
        if r.get("why") == "correct" and c.get("mode") != "continue": return          # a corrective run is not corrected again
        missing = flow.agent_missing(T.root, step)
        if not missing or todo != step: return
        k = f"{step}|{origin}"
        ids = [c["id"] for c in missing]
        if h.get(k, 0) >= MAX_CORRECTIONS:
            self.log(f"{e['id']}: flow step {step} still misses {ids} after {h[k]} corrective run(s): left for the next message"); return
        h[k] = h.get(k, 0) + 1; _write(hf, h)
        _write(T.dir / ".agentd_correct.json", {"at": now(), "key": f"correct-{r['run_id']}", "step": step, "after": r["run_id"], "origin": origin,
                                                "missing": [{"id": x["id"], "why": x["why"]} for x in missing]})
        self.log(f"{e['id']}: run {r['run_id']} left flow step {step} without {ids}: one corrective run")

    # ---- heartbeat
    def beat(self, rows):
        runs = [{"project": e["id"], "pid": r["pid"], "started": r["started"]} for e, T, live, *_ in rows for r in [active_run(T)] if r]
        _write(heartbeat_path(), {"pid": os.getpid(), "pid_start": osdirs.pid_start(os.getpid()), "host": HOST, "started": self.started, "at": now(),
                                  "runs": runs, "queued": self.queued, "blocked": self.blocked, "paused": self.live.paused,
                                  "provider": self.provider.name, "model": self.model, "builds_mode": self.builds_mode,
                                  "builds": [{"project": e["id"], "milestone": m, "state": r.get("state"), "pid": r.get("pid"), "started": r.get("started")}
                                             for e, *_ in rows for m, r in [_builds_current(e)] if r]})

    def serve(self, pid_file=None, once=False):
        lockf = projects.data_dir() / "agentd.lock"; lockf.parent.mkdir(parents=True, exist_ok=True)
        lk = open(lockf, "a+", encoding="utf-8")
        try: osdirs.lock(lk, block=False)
        except OSError:
            d = daemon_state(); print(f"[agentd] already running (pid {d.get('pid')})", file=sys.stderr); return 1
        if pid_file: Path(pid_file).parent.mkdir(parents=True, exist_ok=True); Path(pid_file).write_text(str(os.getpid()), encoding="utf-8")
        stop = []
        for s in (signal.SIGTERM, signal.SIGINT): signal.signal(s, lambda *_: stop.append(1))
        self.log(f"agentd started (pid {os.getpid()}, data {projects.data_dir()}, projects {projects.home() / 'projects.yaml'}, {self.provider.name} {self.claude}, "
                 f"model {self.model}, builds {self.builds_mode}" + (f" since {self.builds.since}" if self.builds else "") + ")")
        self.ensure_gate()
        try:
            while not stop:
                try: self.tick()
                except Exception as x: self.log(f"scan failed: {type(x).__name__}: {x}")      # never die on one bad project file
                if once: break
                for _ in range(int(SCAN_SECS * 10)):
                    if stop: break
                    time.sleep(0.1)
        finally:
            if getattr(self, "gate", None): self.gate.close()
            heartbeat_path().unlink(missing_ok=True)
            if pid_file:
                try: Path(pid_file).unlink()
                except OSError: pass
            self.log("agentd stopped (runs that are still going keep going; the next agentd adopts them)")
        return 0


def _builds_current(e):
    from . import builds
    return builds.current(e["path"])


def _ts(s) -> float:
    try: return clock.epoch(s)
    except (TypeError, ValueError): return 0.0


def _flow_status(T) -> str:
    """The last run's prompt size and flow step, and the corrective / continuation runs so far (.agentd_flow.json)."""
    r = _read(run_path(T)) or {}; h = _read(T.dir / ".agentd_flow.json") or {}
    cont = sum(int(v or 0) for k, v in h.items() if str(k).startswith("continue|"))
    corr = sum(int(v or 0) for k, v in h.items() if not str(k).startswith("continue|"))
    out = ""
    if r.get("prompt_chars"): out += f"  prompt_chars {r['prompt_chars']}" + (f" (step {r['flow_step']})" if r.get("flow_step") else "")
    if r.get("why") == "correct": out += "  last run: " + ("continuation" if (r.get("correct") or {}).get("mode") == "continue" else "correction")
    return out + (f"  corrections {corr}" if corr or cont or r.get("flow_step") else "") + (f"  continuations {cont}" if cont else "")


def status_lines() -> list:
    from . import builds
    d = daemon_state(); hb = _read(heartbeat_path()) or {}
    out = [f"agentd: {'running' if d['alive'] else 'NOT running'} (pid {d.get('pid')}, last beat {d.get('at')}, builds {hb.get('builds_mode') or '?'})"]
    for e in projects.load():
        root = Path(e["path"])
        if not (root / "conversation").is_dir(): continue
        T = Thread(root); r = active_run(T); o = T.owner(); new = T.unread()
        st = (f"run {r['run_id']} since {r['started']}" if r else f"owner {o.get('session')}" if T.owner_live(o) else "free")
        from . import models
        blk = users.run_env(root, {}, models.effective(root, "chat")["agent"])[1]
        out.append(f"{e['id']:<24} {st:<44} unread {len(new)}" + ("  QUEUED" if (T.dir / '.agent_queued').exists() and not T.owner_live(o) else "")
                   + (f"  FAILED {failed(T).get('event')}" if failed(T) else "") + (f"  NOT RUN: {blk}" if blk else "") + _flow_status(T))
        out += [f"{'':<24} {b}" for b in builds.status(root)]
    return out
