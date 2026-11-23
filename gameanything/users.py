"""Hub users, project roles and access requests (`gameanything hub`).

    <hub home>/users.yaml        {name: {display, password_hash, data_root, claude_config_dir, codex_home, agent, env_file, created, admin}}   (mode 0600)
    <hub home>/hub_secret        the key that signs session cookies (mode 0600)
    <hub home>/hub_revoked.json  sessions ended by logout, until they expire
    <user env file>              users.yaml env_file, else ~/workspace/<name>/.m2w-env (mode 0600): the user's own keys; 「我的 Claude」 writes
                                 CLAUDE_CODE_OAUTH_TOKEN (subscription, from `claude setup-token`) or ANTHROPIC_API_KEY there, and for Codex
                                 OPENAI_API_KEY (a ChatGPT login lives in the user's own CODEX_HOME, codex_home). Never sent back.
                                 OpenCode: the key of the chosen model's provider (OPENROUTER_API_KEY for openrouter/...); Gemini CLI:
                                 GEMINI_API_KEY (a Google login lives in the user's own Gemini home, gemini_home); DeepSeek Harness:
                                 the key of her dsh_model's provider, DEEPSEEK_API_KEY or OPENROUTER_API_KEY (her runs' dsh home is dsh_home).
    users.yaml `agent`           claude-code | codex | opencode | gemini | dsh: which agent CLI runs this user's projects (empty: the daemon's --provider)
    users.yaml `opencode_model` / `gemini_model` / `dsh_model`   the model those run with (provider/model for OpenCode, e.g.
                                 openrouter/moonshotai/kimi-k2.6; for dsh deepseek-v4-pro, or openrouter/deepseek/deepseek-v4-pro with an OpenRouter key)
    <project>/config/project.yaml   owner: <user>, members: {user: view|comment|edit}, visibility: hub (default) | private
    <project>/config/access_requests.yaml   [{id, user, role, prev, note, at, state: pending|approved|denied, card_id, decided_at, by}]

<hub home> = $GAMEANYTHING_HUB_HOME, else the project-list folder (projects.home(): ~/.config/gameanything or $GAMEANYTHING_HOME). The hub keeps the one
project list (projects.yaml) and puts the owner into each project's config/project.yaml, so `gameanything project list` works as before.

Isolation is app-level only: everyone on the server is root, so any of them can read every file. The hub keeps people from changing
each other's projects in the web UI; it is not OS-level security.

Roles: view (read only), comment (chat text and feedback notes; no card decisions, no settings), edit (everything but deleting the
project and changing members), owner. A logged-in user who is not a member sees a project read-only unless its visibility is private.
agentd runs a project's agent with the OWNER's agent (users.yaml `agent`) and login (claude_config_dir / codex_home) and env file: run_env().
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml

from . import clock
from . import envcompat, layout, projects

ROLES = ("view", "comment", "edit")
LEVEL = {None: 0, "view": 1, "comment": 2, "edit": 3, "owner": 4}
ROLE_ZH = {"view": "查看", "comment": "评论", "edit": "编辑", "owner": "所有者"}
ROLE_EN = {"view": "view", "comment": "comment", "edit": "edit", "owner": "owner"}
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
MIN_PASSWORD = 8
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
SESSION_SECS = 14 * 24 * 3600
# what never passes from the supervisor's own environment into another user's agent run (that user brings their own in env_file)
CRED_RE = re.compile(r"^(ANTHROPIC_.*|CLAUDE_CODE_OAUTH_TOKEN|CLAUDE_CONFIG_DIR|AWS_.*|GOOGLE_.*|GEMINI_.*|OPENAI_.*|OPENROUTER_.*|FAL_.*|MESHY_.*|HF_TOKEN|HUGGING.*"
                     r"|GH_TOKEN|GITHUB_TOKEN|.*_API_KEY|.*_TOKEN|.*_SECRET.*|.*_PASSWORD)$")


class HubError(ValueError):
    pass


def home() -> Path:
    return Path(os.environ.get("GAMEANYTHING_HUB_HOME") or projects.home())


def users_file() -> Path: return home() / "users.yaml"


def enabled() -> bool:
    """A hub is set up (users.yaml exists): agentd then picks each project's owner login."""
    return users_file().exists()


def now() -> str: return datetime.now().astimezone().isoformat(timespec="seconds")


def _write_private(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True); tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f: f.write(text)
    os.replace(tmp, p)


# ---------------------------------------------------------------- users
def local_owner():
    """Who owns a project made in a plain `gameanything ui` (no login): the hub user whose data_root is this data folder, else the only admin;
    None when there is no hub. Without an owner agentd would never answer the new project's chat."""
    us = load_users()
    if not us: return None
    from . import projects
    here = str(Path(projects.data_dir()).resolve())
    for n, v in us.items():
        if str(Path(str(v.get("data_root") or "")).expanduser().resolve()) == here: return n
    admins = [n for n, v in us.items() if v.get("admin")]
    return admins[0] if len(admins) == 1 else None


def load_users() -> dict:
    try: d = yaml.safe_load(users_file().read_text(encoding="utf-8")) or {}
    except FileNotFoundError: return {}
    return {k: v for k, v in d.items() if isinstance(v, dict)} if isinstance(d, dict) else {}


def save_users(us: dict):
    _write_private(users_file(), "# gameanything hub users (gameanything hub user ...). Passwords are stored as salted scrypt hashes only.\n"
                   + yaml.safe_dump(us, allow_unicode=True, sort_keys=False, width=160))


def get_user(name):
    u = load_users().get(str(name or ""))
    return {**u, "name": name} if u else None


def default_paths(name: str) -> dict:
    base = Path.home() / "workspace" / name
    return {"data_root": str(base / "m2w"), "claude_config_dir": str(base / ".claude-m2w"), "codex_home": str(base / ".codex-m2w"),
            "opencode_home": str(base / ".opencode-m2w"), "gemini_home": str(base / ".gemini-m2w"), "dsh_home": str(base / ".dsh-m2w")}


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode("utf-8"), salt=salt, dklen=32, **SCRYPT)
    return f"scrypt${SCRYPT['n']}${SCRYPT['r']}${SCRYPT['p']}${salt.hex()}${h.hex()}"


def check_password(pw: str, stored: str) -> bool:
    try:
        kind, *rest = str(stored or "").split("$")
        if kind == "scrypt":
            n, r, p, salt, h = rest
            got = hashlib.scrypt(pw.encode("utf-8"), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=len(h) // 2)
        elif kind == "pbkdf2_sha256":
            it, salt, h = rest
            got = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt), int(it))
        else: return False
        return hmac.compare_digest(got.hex(), h)
    except (ValueError, TypeError): return False


def _check_pw(pw):
    if not isinstance(pw, str) or len(pw) < MIN_PASSWORD: raise HubError(f"密码至少 {MIN_PASSWORD} 个字符")


def add_user(name, password, admin=False, display=None, data_root=None, claude_config_dir=None, env_file=None, codex_home=None, agent=None) -> dict:
    if not NAME_RE.match(str(name or "")): raise HubError("用户名只能用小写字母、数字、- 和 _，以字母开头，2 到 32 个字符")
    _check_pw(password)
    us = load_users()
    if name in us: raise HubError(f"用户 {name} 已经存在")
    d = default_paths(name)
    us[name] = {"display": display or name, "password_hash": hash_password(password),
                "data_root": str(Path(data_root or d["data_root"]).expanduser()),
                "claude_config_dir": str(Path(claude_config_dir or d["claude_config_dir"]).expanduser()),
                "codex_home": str(Path(codex_home or d["codex_home"]).expanduser()),
                "env_file": str(Path(env_file).expanduser()) if env_file else None, "created": now(), "admin": bool(admin)}
    if agent: us[name]["agent"] = _check_agent(agent)
    save_users(us); return {**us[name], "name": name}


def set_password(name, password):
    _check_pw(password); us = load_users()
    if name not in us: raise HubError(f"没有用户 {name}")
    us[name]["password_hash"] = hash_password(password); save_users(us)


def remove_user(name):
    """The user goes from users.yaml; their projects stay on disk with the owner unchanged (lists show 已移除用户; agentd does not run them)."""
    us = load_users()
    if name not in us: raise HubError(f"没有用户 {name}")
    if us[name].get("admin") and len(us) > 1 and sum(1 for v in us.values() if v.get("admin")) <= 1: raise HubError("不能移除最后一个管理员")
    del us[name]; save_users(us)


def set_admin(name, admin: bool):
    us = load_users()
    if name not in us: raise HubError(f"没有用户 {name}")
    if not admin and us[name].get("admin") and sum(1 for v in us.values() if v.get("admin")) <= 1: raise HubError("至少要留一个管理员")
    us[name]["admin"] = bool(admin); save_users(us)


def new_password() -> str:
    """A generated initial / reset password (shown once)."""
    return "-".join(secrets.token_urlsafe(6).replace("-", "x").replace("_", "y") for _ in range(2))


def display(name) -> str:
    u = load_users().get(name) if name else None
    return (u or {}).get("display") or name or ""


def user_dir(name) -> Path:
    """The user's own folder on the server (~/workspace/<name>): where their env file goes when users.yaml names none."""
    return Path.home() / "workspace" / str(name)


def env_path(u) -> Path:
    """The user's env file: users.yaml `env_file`, else <user dir>/.m2w-env (written by 「我的 Claude」)."""
    return Path(u["env_file"]).expanduser() if (u or {}).get("env_file") else user_dir((u or {}).get("name") or "_") / ".m2w-env"


def env_file_values(u) -> dict:
    """KEY=value lines of the user's env file (never printed)."""
    if not u: return {}
    out = {}
    try: lines = env_path(u).read_text(encoding="utf-8-sig").splitlines()
    except OSError: return {}
    for l in lines:
        k, sep, v = l.strip().removeprefix("export ").partition("=")
        if sep and k.strip() and not k.strip().startswith("#"): out[k.strip()] = v.strip().strip("'\"")
    return out


def claude_login(u) -> bool:
    """The user has logged in to Claude under their own config dir (or brings a token / key in their env file)."""
    return claude_status(u)["connected"]


# ---------------------------------------------------------------- which agent CLI runs the user's projects (users.yaml `agent`)
AGENTS = ("claude-code", "codex", "opencode", "gemini", "dsh")
AGENT_NAME = {"claude-code": "Claude Code", "codex": "Codex", "opencode": "OpenCode", "gemini": "Gemini CLI", "dsh": "DeepSeek Harness"}


def _check_agent(a) -> str:
    a = str(a or "").strip().lower().replace("_", "-")
    if a == "claude": a = "claude-code"
    if a == "opencode-ai": a = "opencode"
    if a in ("gemini-cli", "google-gemini"): a = "gemini"
    if a in ("deepseek", "deepseek-harness"): a = "dsh"
    if a not in AGENTS: raise HubError("agent 应该是 claude-code、codex、opencode、gemini 或 dsh")
    return a


def agent_of(u, default=None) -> str:
    """The user's chosen agent CLI, else the daemon's (default), else claude-code."""
    a = (u or {}).get("agent")
    return a if a in AGENTS else (default if default in AGENTS else "claude-code")


def set_agent(name, agent) -> dict:
    us = load_users()
    if name not in us: raise HubError(f"没有用户 {name}")
    us[name]["agent"] = _check_agent(agent); save_users(us); return agent_status({**us[name], "name": name})


def codex_home(u) -> Path:
    """The user's own CODEX_HOME (their `codex login` / ChatGPT login and sessions); users.yaml `codex_home`, else the default one."""
    v = (u or {}).get("codex_home") or default_paths((u or {}).get("name") or "_")["codex_home"]
    return Path(v).expanduser()


def is_default_codex_home(d) -> bool:
    """The supervisor's own Codex login (~/.codex, or $CODEX_HOME of the daemon): the env is then left as it is."""
    try:
        d = Path(d).expanduser().resolve()
        return d == (Path.home() / ".codex").resolve() or (bool(os.environ.get("CODEX_HOME")) and d == Path(os.environ["CODEX_HOME"]).expanduser().resolve())
    except (OSError, TypeError): return False


def codex_status(u) -> dict:
    """{connected, kind: api_key | login | None, last4, login}: an OpenAI API key in the env file wins over the CODEX_HOME login."""
    if not u: return {"connected": False, "kind": None, "last4": None, "login": False}
    login = (codex_home(u) / "auth.json").is_file()
    v = env_file_values(u).get(CODEX_KEY)
    if v: return {"connected": True, "kind": "api_key", "last4": v[-4:], "login": login}
    return {"connected": login, "kind": "login" if login else None, "last4": None, "login": login}


def _home(u, key) -> Path:
    v = (u or {}).get(key) or default_paths((u or {}).get("name") or "_")[key]
    return Path(v).expanduser()


def opencode_home(u) -> Path:
    """The user's own OpenCode home for GameAnything runs (config, sessions, an `opencode auth login`): users.yaml `opencode_home`, else the default."""
    return _home(u, "opencode_home")


def gemini_home(u) -> Path:
    """The user's own Gemini CLI home (GEMINI_CLI_HOME of their runs: settings, sessions, a Google login)."""
    return _home(u, "gemini_home")


def dsh_home(u) -> Path:
    """The user's own DeepSeek Harness home (DSH_HOME of their runs: profiles, sessions, the key file the run reads)."""
    return _home(u, "dsh_home")


MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]*(/[A-Za-z0-9][A-Za-z0-9._:@+-]*){1,3}$")
GEMINI_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")


def opencode_model(u) -> str:
    from . import agent_providers
    return (u or {}).get("opencode_model") or agent_providers.OPENCODE_DEFAULT_MODEL


def check_model(agent, model) -> str:
    m = str(model or "").strip()
    if agent == "opencode":
        if not MODEL_RE.match(m): raise HubError("模型要写成 provider/model，例如 openrouter/moonshotai/kimi-k2.6")
    elif agent == "gemini":
        if m and not GEMINI_MODEL_RE.match(m): raise HubError("Gemini 模型名不对，例如 gemini-3.1-pro-preview")
    elif agent == "dsh":
        if m and not (GEMINI_MODEL_RE.match(m) or MODEL_RE.match(m)):
            raise HubError("DeepSeek Harness 的模型名不对，例如 deepseek-v4-pro，或用 OpenRouter 时 openrouter/deepseek/deepseek-v4-pro")
    else: raise HubError("只有 OpenCode、Gemini CLI 和 DeepSeek Harness 可以在这里选模型")
    return m


def opencode_status(u) -> dict:
    """{connected, kind: api_key | login | None, last4, login, model, key_name}: the key for the provider of her model (env file) wins over
    an `opencode auth login` in her OpenCode home that has that provider."""
    from . import agent_providers
    model = opencode_model(u); names = agent_providers.opencode_key_names(model); pid = model.split("/", 1)[0]
    if not u: return {"connected": False, "kind": None, "last4": None, "login": False, "model": model, "key_name": names[0]}
    try: login = pid in json.loads((opencode_home(u) / "data" / "opencode" / "auth.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError): login = False
    ev = env_file_values(u); v = next((ev[k] for k in names if ev.get(k)), None)
    if v: return {"connected": True, "kind": "api_key", "last4": v[-4:], "login": login, "model": model, "key_name": names[0]}
    return {"connected": login, "kind": "login" if login else None, "last4": None, "login": login, "model": model, "key_name": names[0]}


GEMINI_KEY = "GEMINI_API_KEY"


def gemini_status(u) -> dict:
    """{connected, kind: api_key | login | None, last4, login, model}: a Gemini API key in the env file wins over a Google login."""
    model = (u or {}).get("gemini_model") or ""
    if not u: return {"connected": False, "kind": None, "last4": None, "login": False, "model": model}
    login = (gemini_home(u) / ".gemini" / "oauth_creds.json").is_file()
    v = env_file_values(u).get(GEMINI_KEY)
    if v: return {"connected": True, "kind": "api_key", "last4": v[-4:], "login": login, "model": model}
    return {"connected": login, "kind": "login" if login else None, "last4": None, "login": login, "model": model}


def dsh_key_name(u) -> str:
    """The key variable her DeepSeek Harness model needs: DEEPSEEK_API_KEY (DeepSeek's own API), OPENROUTER_API_KEY (openrouter/...)."""
    from . import agent_providers
    return agent_providers.dsh_route((u or {}).get("dsh_model") or None)[2]


def dsh_status(u) -> dict:
    """{connected, kind: api_key | None, last4, login: False, model, key_name}: DeepSeek Harness runs only with an API key (headless dsh
    ignores the keys and sign-ins its GUI saves): the one of her model's provider."""
    model = (u or {}).get("dsh_model") or ""; name = dsh_key_name(u)
    v = env_file_values(u).get(name) if u else None
    if v: return {"connected": True, "kind": "api_key", "last4": v[-4:], "login": False, "model": model, "key_name": name}
    return {"connected": False, "kind": None, "last4": None, "login": False, "model": model, "key_name": name}


STATUS = {"codex": codex_status, "opencode": opencode_status, "gemini": gemini_status, "dsh": dsh_status}


def agent_connected(u, agent) -> bool:
    """This user has a login / key for exactly this agent CLI (agent_login: their chosen one, `agent` only the fallback)."""
    return STATUS.get(agent, claude_status)(u)["connected"]


def agent_login(u, agent=None) -> bool:
    return STATUS.get(agent_of(u, agent), claude_status)(u)["connected"]


def agent_status(u, default=None) -> dict:
    """What 「我的 agent」 shows: the chosen agent, whether it can run, and every login (never a secret)."""
    a = agent_of(u, default); st = {"claude": claude_status(u), **{k: f(u) for k, f in STATUS.items()}}
    cur = st["claude"] if a == "claude-code" else st[a]
    return {"agent": a, "chosen": bool((u or {}).get("agent")), "connected": cur["connected"], "kind": cur["kind"], "last4": cur["last4"], **st}


# ---------------------------------------------------------------- 「我的 Claude」: a subscription token or an API key in the user's env file
CLAUDE_KEYS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
CODEX_KEY = "OPENAI_API_KEY"                    # 「我的 agent」 Codex API key (runs get it as CODEX_API_KEY: user_env)
KIND_KEY = {"subscription": "CLAUDE_CODE_OAUTH_TOKEN", "api_key": "ANTHROPIC_API_KEY"}
SECRET_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{4,}|sk-(?:proj|svcacct|admin|or-v1)-[A-Za-z0-9_\-]{4,}|AIza[A-Za-z0-9_\-]{20,}")
TOKEN_CHARS = re.compile(r"^[A-Za-z0-9_\-]{24,512}$")


def claude_status(u) -> dict:
    """{connected, kind: api_key | subscription | login | None, last4, login}. `login`: a /login under the user's config dir.
    The kind is the one claude uses first (an API key wins over a subscription token, both over the config dir login). Never the secret."""
    if not u: return {"connected": False, "kind": None, "last4": None, "login": False}
    login = (Path(u.get("claude_config_dir") or "/nonexistent").expanduser() / ".credentials.json").is_file()
    ev = env_file_values(u)
    for kind in ("api_key", "subscription"):
        v = ev.get(KIND_KEY[kind])
        if v: return {"connected": True, "kind": kind, "last4": v[-4:], "login": login}
    return {"connected": login, "kind": "login" if login else None, "last4": None, "login": login}


def check_secret(kind, value) -> str:
    """-> the cleaned token / key (whitespace and line breaks of a terminal copy removed), or HubError. Loose prefix checks only."""
    if kind not in KIND_KEY: raise HubError("连接方式应该是 subscription 或 api_key")
    v = re.sub(r"\s+", "", str(value or ""))
    if not v: raise HubError("请先粘贴")
    if kind == "subscription":
        if v.startswith("sk-ant-api"): raise HubError("这是 API key，不是订阅 token：请用下面的「API key」方式")
        if not v.startswith("sk-ant-oat"): raise HubError("这看起来不是 claude setup-token 给的 token（应该以 sk-ant-oat 开头）")
    else:
        if v.startswith("sk-ant-oat"): raise HubError("这是订阅 token，不是 API key：请用上面的「订阅」方式")
        if not v.startswith("sk-ant-api"): raise HubError("这看起来不是 Anthropic API key（应该以 sk-ant-api 开头）")
    if not TOKEN_CHARS.match(v): raise HubError("格式不对：只应该有字母、数字、- 和 _，请完整复制")
    return v


def _edit_env_file(f: Path, values: dict):
    """Set (value) or remove (None) these keys in an env file; other lines stay as written. The file is (re)written with mode 0600."""
    try: lines = f.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError: lines = ["# gameanything hub: this user's own keys (「我的 Claude」 in the hub writes the Claude ones). Keep it private (0600)."]
    out, done = [], set()
    for l in lines:
        k = l.strip().removeprefix("export ").partition("=")[0].strip()
        if k in values:
            if values[k] is not None and k not in done: out.append(f"{k}={values[k]}"); done.add(k)
            continue
        out.append(l)
    out += [f"{k}={v}" for k, v in values.items() if v is not None and k not in done]
    _write_private(f, "\n".join(out) + "\n")
    os.chmod(f, 0o600)


def connect_claude(name, kind, value) -> dict:
    """Store the user's subscription token (CLAUDE_CODE_OAUTH_TOKEN) or API key (ANTHROPIC_API_KEY) in their env file (0600); the other
    of the two is removed, so the run uses what they chose. An env file is recorded in users.yaml if there was none. -> claude_status."""
    v = check_secret(kind, value)
    us = load_users()
    if name not in us: raise HubError(f"没有用户 {name}")
    u = {**us[name], "name": name}; f = env_path(u)
    _edit_env_file(f, {KIND_KEY[kind]: v, KIND_KEY["api_key" if kind == "subscription" else "subscription"]: None})
    if not us[name].get("env_file"): us[name]["env_file"] = str(f); save_users(us)
    try: Path(us[name].get("claude_config_dir") or "").expanduser().mkdir(parents=True, exist_ok=True)   # claude's own state for the runs
    except OSError: pass
    return claude_status({**us[name], "name": name})


def check_codex_key(value) -> str:
    v = re.sub(r"\s+", "", str(value or ""))
    if not v: raise HubError("请先粘贴")
    if v.startswith("sk-ant-"): raise HubError("这是 Anthropic（Claude）的 key：请在上面的 Claude 部分保存")
    if not v.startswith("sk-"): raise HubError("这看起来不是 OpenAI API key（应该以 sk- 开头）")
    if not TOKEN_CHARS.match(v): raise HubError("格式不对：只应该有字母、数字、- 和 _，请完整复制")
    return v


def connect_codex(name, value) -> dict:
    """Store the user's OpenAI API key for Codex (OPENAI_API_KEY in their env file, 0600); their CODEX_HOME is created. -> codex_status."""
    v = check_codex_key(value)
    us = load_users()
    if name not in us: raise HubError(f"没有用户 {name}")
    u = {**us[name], "name": name}; f = env_path(u)
    _edit_env_file(f, {CODEX_KEY: v})
    if not us[name].get("env_file"): us[name]["env_file"] = str(f)
    if not us[name].get("codex_home"): us[name]["codex_home"] = str(codex_home(u))
    save_users(us)
    try: codex_home(us[name]).mkdir(parents=True, exist_ok=True)
    except OSError: pass
    return codex_status({**us[name], "name": name})


KEY_CHARS = re.compile(r"^[A-Za-z0-9_\-.]{16,512}$")


def check_api_key(value, what="API key") -> str:
    v = re.sub(r"\s+", "", str(value or ""))
    if not v: raise HubError("请先粘贴")
    if v.startswith("sk-ant-oat"): raise HubError("这是 Claude 订阅 token，不是 API key：请在 Claude Code 部分保存")
    if not KEY_CHARS.match(v): raise HubError(f"这看起来不是 {what}：只应该有字母、数字、-、_ 和 .，请完整复制")
    return v


def connect_opencode(name, value, model=None) -> dict:
    """Store the user's key for OpenCode under the env name of her model's provider (OPENROUTER_API_KEY for openrouter/...) in her env
    file (0600); `model` (provider/model) is saved as opencode_model. Her OpenCode home is created. -> opencode_status."""
    us = load_users()
    if name not in us: raise HubError(f"没有用户 {name}")
    if model: us[name]["opencode_model"] = check_model("opencode", model)
    u = {**us[name], "name": name}; m = opencode_model(u)
    v = check_api_key(value, "API key")
    if m.startswith("openrouter/") and not v.startswith("sk-or-"): raise HubError("这看起来不是 OpenRouter 的 key（应该以 sk-or- 开头）")
    from . import agent_providers
    f = env_path(u); _edit_env_file(f, {agent_providers.opencode_key_names(m)[0]: v})
    if not us[name].get("env_file"): us[name]["env_file"] = str(f)
    if not us[name].get("opencode_home"): us[name]["opencode_home"] = str(opencode_home(u))
    save_users(us)
    try: opencode_home(us[name]).mkdir(parents=True, exist_ok=True)
    except OSError: pass
    return opencode_status({**us[name], "name": name})


def disconnect_opencode(name) -> dict:
    """Remove the key of her model's provider from her env file (an `opencode auth login` in her OpenCode home stays)."""
    from . import agent_providers
    u = get_user(name)
    if not u: raise HubError(f"没有用户 {name}")
    f = env_path(u)
    if f.exists(): _edit_env_file(f, {k: None for k in agent_providers.opencode_key_names(opencode_model(u))})
    return opencode_status(u)


def connect_gemini(name, value) -> dict:
    """Store the user's Gemini API key (GEMINI_API_KEY in her env file, 0600); her Gemini home is created. -> gemini_status."""
    v = check_api_key(value, "Gemini API key")
    if v.startswith("sk-"): raise HubError("这看起来不是 Gemini API key（Google AI Studio 的 key 通常以 AIza 开头）")
    us = load_users()
    if name not in us: raise HubError(f"没有用户 {name}")
    u = {**us[name], "name": name}; f = env_path(u)
    _edit_env_file(f, {GEMINI_KEY: v})
    if not us[name].get("env_file"): us[name]["env_file"] = str(f)
    if not us[name].get("gemini_home"): us[name]["gemini_home"] = str(gemini_home(u))
    save_users(us)
    try: gemini_home(us[name]).mkdir(parents=True, exist_ok=True)
    except OSError: pass
    return gemini_status({**us[name], "name": name})


def connect_dsh(name, value, model=None) -> dict:
    """Store the user's key for DeepSeek Harness under the variable her model needs (DEEPSEEK_API_KEY, or OPENROUTER_API_KEY for
    openrouter/...) in her env file (0600); `model` is saved as dsh_model first. Her dsh home is created. -> dsh_status."""
    us = load_users()
    if name not in us: raise HubError(f"没有用户 {name}")
    if model: us[name]["dsh_model"] = check_model("dsh", model)
    u = {**us[name], "name": name}; key = dsh_key_name(u)
    v = check_api_key(value, "API key")
    if key == "OPENROUTER_API_KEY":
        if not v.startswith("sk-or-"): raise HubError("这看起来不是 OpenRouter 的 key（应该以 sk-or- 开头）")
    elif key == "DEEPSEEK_API_KEY" and (v.startswith(("sk-ant-", "sk-or-", "sk-proj-")) or not v.startswith("sk-")):
        raise HubError("这看起来不是 DeepSeek API key（platform.deepseek.com 的 key 以 sk- 开头）")
    f = env_path(u)
    _edit_env_file(f, {key: v})
    if not us[name].get("env_file"): us[name]["env_file"] = str(f)
    if not us[name].get("dsh_home"): us[name]["dsh_home"] = str(dsh_home(u))
    save_users(us)
    try: dsh_home(us[name]).mkdir(parents=True, exist_ok=True)
    except OSError: pass
    return dsh_status({**us[name], "name": name})


def disconnect_dsh(name) -> dict:
    u = get_user(name)
    if not u: raise HubError(f"没有用户 {name}")
    f = env_path(u)
    if f.exists(): _edit_env_file(f, {dsh_key_name(u): None})
    return dsh_status(u)


def disconnect_gemini(name) -> dict:
    u = get_user(name)
    if not u: raise HubError(f"没有用户 {name}")
    f = env_path(u)
    if f.exists(): _edit_env_file(f, {GEMINI_KEY: None})
    return gemini_status(u)


def set_model(name, agent, model) -> dict:
    """users.yaml opencode_model / gemini_model / dsh_model (empty for Gemini: the CLI's own default; for dsh: deepseek-v4-pro). -> agent_status."""
    us = load_users()
    if name not in us: raise HubError(f"没有用户 {name}")
    m = check_model(agent, model); key = f"{agent}_model"
    if m: us[name][key] = m
    else: us[name].pop(key, None)
    save_users(us); return agent_status({**us[name], "name": name})


def disconnect_codex(name) -> dict:
    """Remove the OpenAI key from the user's env file (a `codex login` in their CODEX_HOME stays). -> codex_status."""
    u = get_user(name)
    if not u: raise HubError(f"没有用户 {name}")
    f = env_path(u)
    if f.exists(): _edit_env_file(f, {CODEX_KEY: None})
    return codex_status(u)


# ---------------------------------------------------------------- 「用 ChatGPT 登录 Codex」 in the web page: `codex login --device-auth` for her
# CODEX_HOME, started by the hub in the background (one per user). Codex prints a link and a one-time code; she opens the link in her own
# browser, signs in with her ChatGPT account and types the code; codex then writes <CODEX_HOME>/auth.json and exits 0. Only the link and
# the code are kept (and shown to her); the rest of codex's output is read and dropped, never stored or logged.
CODEX_LOGIN_SECS = 15 * 60                      # the code expires after 15 minutes; the process is killed then
CODEX_LOGINS = {}                               # name -> {proc, state, url, code, started, expires, exit}
CODEX_LOGIN_LOCK = threading.Lock()
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
DEVICE_URL_RE = re.compile(r"https://[^\s\x1b<>\"']+")
DEVICE_CODE_RE = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4,6})\b")
LOGIN_ACTIVE = ("starting", "waiting")


# ---------------------------------------------------------------- 「素材生成 API keys」: keys for `gameanything gen` (genrun runs with them; agent runs never see them)
GEN_KEYS = {"FAL_KEY": "fal", "MESHY_API_KEY": "Meshy", "OPENAI_API_KEY": "OpenAI", "OPENROUTER_API_KEY": "OpenRouter"}
GEN_KEY_CHARS = re.compile(r"^[A-Za-z0-9_\-:.]{16,512}$")          # fal keys are <id>:<secret>


def gen_keys_status(u) -> list:
    """[{name, title, set}] for the hub page: whether each key is in the user's env file; never any part of the value."""
    ev = env_file_values(u)
    from . import keys
    return [{"name": k, "title": t, "set": any(ev.get(n) for n in keys.names(k)), **({"codex": True} if k == CODEX_KEY else {})} for k, t in GEN_KEYS.items()]


def set_gen_key(name, key, value) -> list:
    """Store one generation key in the user's env file (0600; an env file is recorded in users.yaml if there was none)."""
    if key not in GEN_KEYS: raise HubError("不认识这个 key / unknown key")
    v = re.sub(r"\s+", "", str(value or ""))
    if not v: raise HubError("请先粘贴")
    if v.startswith("sk-ant-"): raise HubError("这是 Anthropic（Claude）的 key：请在上面的 Claude 部分保存")
    if not GEN_KEY_CHARS.match(v): raise HubError("格式不对：只应该有字母、数字、- _ : .，请完整复制")
    us = load_users()
    if name not in us: raise HubError(f"没有用户 {name}")
    u = {**us[name], "name": name}; f = env_path(u)
    from . import keys
    _edit_env_file(f, {key: v, **{a: None for a in keys.ALIASES.get(key, ())}})        # one value: an old FAL_API_KEY line goes
    if not us[name].get("env_file"): us[name]["env_file"] = str(f); save_users(us)
    return gen_keys_status({**us[name], "name": name})


def remove_gen_key(name, key) -> list:
    if key not in GEN_KEYS: raise HubError("不认识这个 key / unknown key")
    u = get_user(name)
    if not u: raise HubError(f"没有用户 {name}")
    f = env_path(u)
    from . import keys
    if f.exists(): _edit_env_file(f, {n: None for n in keys.names(key)})
    return gen_keys_status(u)


def codex_login_cmd(binary=None) -> list:
    from . import agent_providers
    return [agent_providers.provider("codex", binary=binary).binary, "login", "--device-auth"]


def _login_view(name, s) -> dict:
    """What the page may see of a login: never more than the state, the link and the code."""
    u = get_user(name)
    out = {"state": (s or {}).get("state") or "idle", "codex": codex_status({**u, "name": name} if u else None)}
    if s and s.get("state") == "waiting": out.update(url=s.get("url"), code=s.get("code"), expires=s.get("expires"))
    return out


def _kill(proc):
    """End that exact login process and the group it leads (it was started in a new session / process group; osdirs.stop_group)."""
    from . import osdirs
    if proc.poll() is not None: return
    osdirs.stop_group(proc.pid)
    try: proc.wait(5)
    except subprocess.TimeoutExpired:
        try: proc.kill(); proc.wait(5)
        except (OSError, subprocess.TimeoutExpired): pass


def _watch_login(name, s):
    proc = s["proc"]
    timer = threading.Timer(max(1.0, s["expires"] - time.time()), lambda: _expire(name, s)); timer.daemon = True; timer.start()
    try:
        for line in proc.stdout:
            line = ANSI_RE.sub("", line)
            with CODEX_LOGIN_LOCK:
                if not s.get("url"):
                    m = DEVICE_URL_RE.search(line)
                    if m: s["url"] = m.group(0).rstrip(".,)")
                if not s.get("code") and s.get("url"):
                    m = DEVICE_CODE_RE.search(line)
                    if m: s["code"] = m.group(1)
                if s["state"] == "starting" and s.get("url") and s.get("code"): s["state"] = "waiting"
    except (OSError, ValueError): pass
    rc = proc.wait(); timer.cancel()
    u = get_user(name)
    with CODEX_LOGIN_LOCK:
        s["exit"] = rc
        if s["state"] in LOGIN_ACTIVE:
            s["state"] = "done" if rc == 0 and u and (codex_home(u) / "auth.json").is_file() else "failed"
        s["ended"] = time.time(); s.pop("url", None); s.pop("code", None)


def _expire(name, s):
    with CODEX_LOGIN_LOCK:
        if s["state"] not in LOGIN_ACTIVE: return
        s["state"] = "expired"
    _kill(s["proc"])


def codex_login_start(name, binary=None, cmd=None) -> dict:
    """Start `codex login --device-auth` for this user's CODEX_HOME (one at a time per user; a running one is returned as it is).
    -> the page's view: {state: starting | waiting (url, code, expires) | ..., codex: codex_status}."""
    u = get_user(name)
    if not u: raise HubError(f"没有用户 {name}")
    with CODEX_LOGIN_LOCK:
        s = CODEX_LOGINS.get(name)
        if s and s["state"] in LOGIN_ACTIVE and s["proc"].poll() is None: return _login_view(name, s)
        d = codex_home(u)
        try: d.mkdir(parents=True, exist_ok=True)
        except OSError as x: raise HubError(f"没能建立 Codex 文件夹：{x}")
        env = {k: v for k, v in os.environ.items() if not CRED_RE.match(k)}
        env.update(CODEX_HOME=str(d), NO_COLOR="1", TERM="dumb")
        kw = {"creationflags": 0x00000200} if os.name == "nt" else {"start_new_session": True}       # CREATE_NEW_PROCESS_GROUP
        try:
            proc = subprocess.Popen(cmd or codex_login_cmd(binary), cwd=str(d), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", **kw)
        except OSError as x: raise HubError(f"没能启动 codex：{x}")
        t0 = time.time()
        s = CODEX_LOGINS[name] = {"proc": proc, "state": "starting", "started": t0, "expires": t0 + CODEX_LOGIN_SECS}
        if not u.get("codex_home"):
            us = load_users()
            if name in us and not us[name].get("codex_home"): us[name]["codex_home"] = str(d); save_users(us)
    threading.Thread(target=_watch_login, args=(name, s), daemon=True, name=f"codex-login-{name}").start()
    return _login_view(name, s)


def codex_login_status(name) -> dict:
    with CODEX_LOGIN_LOCK: return _login_view(name, CODEX_LOGINS.get(name))


def codex_login_cancel(name) -> dict:
    with CODEX_LOGIN_LOCK:
        s = CODEX_LOGINS.get(name)
        if not s or s["state"] not in LOGIN_ACTIVE: return _login_view(name, s)
        s["state"] = "cancelled"; proc = s["proc"]
    _kill(proc)
    return codex_login_status(name)


def disconnect_claude(name) -> dict:
    """Remove the token / key from the user's env file (a /login in their config dir stays). -> claude_status."""
    u = get_user(name)
    if not u: raise HubError(f"没有用户 {name}")
    f = env_path(u)
    if f.exists(): _edit_env_file(f, {k: None for k in CLAUDE_KEYS})
    return claude_status(u)


def redact(text, u=None) -> str:
    """Text with every Anthropic-looking secret and every value of the user's env file replaced by ***."""
    s = str(text or "")
    for v in sorted((v for v in env_file_values(u).values() if len(v) >= 8), key=len, reverse=True): s = s.replace(v, "***")
    return SECRET_RE.sub("sk-ant-***", s)


def try_claude(name, claude=None, run=None, timeout=60, agent=None) -> dict:
    """A tiny headless call with the user's own login, the env built the way agentd builds it (server credentials stripped).
    agent: claude-code | codex (default: the user's choice). -> {ok, text}: the reply or the error, secrets redacted."""
    import subprocess
    import tempfile
    from . import agent_providers, agentd
    u = get_user(name)
    if not u: raise HubError(f"没有用户 {name}")
    a = _check_agent(agent) if agent else agent_of(u)
    if not agent_login(u, a): return {"ok": False, "text": {"claude-code": "还没有连接：先粘贴订阅 token 或 API key", "codex": "还没有连接：先粘贴 OpenAI API key，或在服务器上 codex login",
                                                          "opencode": "还没有连接：先粘贴模型服务的 API key（例如 OpenRouter）", "gemini": "还没有连接：先粘贴 Gemini API key",
                                                          "dsh": "还没有连接：先粘贴 DeepSeek 或 OpenRouter 的 API key"}[a]}
    env = {k: v for k, v in agentd.clean_env().items() if not CRED_RE.match(k)}
    env = user_env(u, env, a)
    if a in ("opencode", "gemini", "dsh"):             # the same launch as a resident run (its config, permissions, isolation), in a scratch folder
        prov = agent_providers.provider(a, binary=claude, model=opencode_model(u) if a == "opencode" else (u.get(f"{a}_model") or None))
        env = agent_providers.agent_env(env, prov)
        run = run or subprocess.run
        with tempfile.TemporaryDirectory(prefix="m2w-agent-test-") as cwd:
            try:
                cmd, env = prov.launch("reply OK", "This is a connection test: reply with the single word OK and use no tools.", None, False, Path(cwd), env=env)
                r = run(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=max(timeout, 120))
            except subprocess.TimeoutExpired: return {"ok": False, "text": f"{max(timeout, 120)} 秒内没有回应"}
            except OSError as e: return {"ok": False, "text": redact(f"没能启动 {a}：{e}", u)}
        txt = agent_providers.reply_text(a, r.stdout or "")
        if r.returncode == 0 and txt: return {"ok": True, "text": redact(txt[-300:], u)}
        return {"ok": False, "text": redact((agent_providers.error_text(a, r.stdout or "") or (r.stderr or "").strip() or f"{a} 退出码 {r.returncode}")[-600:], u)}
    if a == "codex":
        exe = agent_providers.provider("codex", binary=claude).binary
        cmd = [exe, "exec", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules", "--sandbox", "read-only", "reply OK"]
    else: cmd = [agentd.claude_bin(claude), "-p", "reply OK", "--max-turns", "1", "--output-format", "text"]
    run = run or subprocess.run
    with tempfile.TemporaryDirectory(prefix="m2w-claude-test-") as cwd:
        try: r = run(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired: return {"ok": False, "text": f"{timeout} 秒内没有回应"}
        except OSError as e: return {"ok": False, "text": redact(f"没能启动 {'codex' if a == 'codex' else 'claude'}：{e}", u)}
    out = (r.stdout or "").strip(); errt = (r.stderr or "").strip()
    if r.returncode == 0 and out: return {"ok": True, "text": redact(out[-300:], u)}
    return {"ok": False, "text": redact((errt or out or f"{'codex' if a == 'codex' else 'claude'} 退出码 {r.returncode}")[-600:], u)}


def is_default_config(d) -> bool:
    """The Claude config dir is the default one (~/.claude): the supervisor's own login; CLAUDE_CONFIG_DIR is then left unset, as before."""
    try: return Path(d).expanduser().resolve() == (Path.home() / ".claude").resolve()
    except (OSError, TypeError): return False


# ---------------------------------------------------------------- sessions (signed cookie: name:expiry:nonce:hmac)
def _secret() -> bytes:
    f = home() / "hub_secret"
    try: return bytes.fromhex(f.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        s = secrets.token_bytes(32); _write_private(f, s.hex()); return s


def _sig(name, exp, nonce, pwh) -> str:
    fp = hashlib.sha256(str(pwh).encode()).hexdigest()[:16]          # a new password ends the old sessions
    return hmac.new(_secret(), f"{name}:{exp}:{nonce}:{fp}".encode(), hashlib.sha256).hexdigest()


def make_session(name) -> str:
    u = load_users()[name]; exp = int(time.time()) + SESSION_SECS; nonce = secrets.token_hex(8)
    return f"{name}:{exp}:{nonce}:{_sig(name, exp, nonce, u['password_hash'])}"


def _revoked() -> dict:
    try: d = json.loads((home() / "hub_revoked.json").read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}
    return d if isinstance(d, dict) else {}


def session_user(cookie):
    """-> the user dict of a valid session cookie value, else None."""
    try: name, exp, nonce, sig = str(cookie or "").split(":")
    except ValueError: return None
    if not exp.isdigit() or int(exp) < time.time(): return None
    u = get_user(name)
    if not u or not hmac.compare_digest(sig, _sig(name, exp, nonce, u.get("password_hash"))): return None
    if nonce in _revoked(): return None
    return u


def end_session(cookie):
    try: _, exp, nonce, _ = str(cookie or "").split(":")
    except ValueError: return
    d = {k: v for k, v in _revoked().items() if isinstance(v, int) and v > time.time()}
    d[nonce] = int(exp) if exp.isdigit() else int(time.time()) + SESSION_SECS
    _write_private(home() / "hub_revoked.json", json.dumps(d))


# ---------------------------------------------------------------- project owner, members, roles
def _cfg_file(root) -> Path: return Path(root) / layout.CONFIG / "project.yaml"


def owner_of(root):
    o = projects.config_of(root).get("owner"); return o if isinstance(o, str) and o else None


def members_of(root) -> dict:
    m = projects.config_of(root).get("members"); return {k: v for k, v in (m or {}).items() if v in ROLES} if isinstance(m, dict) else {}


def private(root) -> bool:
    return projects.config_of(root).get("visibility") == "private"


def role_of(user, root):
    """owner | edit | comment | view | None for this user (a dict or a name) on the project folder."""
    name = user.get("name") if isinstance(user, dict) else user
    if not name: return None
    o = owner_of(root)
    if o == name: return "owner"
    m = members_of(root).get(name)
    if m: return m
    return None if private(root) else "view"


def at_least(role, need) -> bool: return LEVEL.get(role, 0) >= LEVEL.get(need, 99)


def _set_top_key(text: str, key: str, block: str) -> str:
    """Replace the top-level `key:` entry (and its indented lines) of a yaml text with `block` (empty: remove it); other lines stay as written."""
    lines = text.splitlines(); out = []; i = 0; done = False
    while i < len(lines):
        if re.match(rf"^{re.escape(key)}\s*:", lines[i]):
            i += 1
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()): i += 1
            if block and not done: out.extend(block.rstrip("\n").splitlines()); done = True
            continue
        out.append(lines[i]); i += 1
    if block and not done: out.extend(block.rstrip("\n").splitlines())
    return "\n".join(out) + "\n"


def _write_cfg_key(root, key, value):
    f = _cfg_file(root); t = f.read_text(encoding="utf-8") if f.exists() else ""
    block = "" if value in (None, {}, "") else yaml.safe_dump({key: value}, allow_unicode=True, sort_keys=False)
    f.parent.mkdir(parents=True, exist_ok=True); tmp = f.with_name(f".project.yaml.{os.getpid()}.tmp")
    tmp.write_text(_set_top_key(t, key, block), encoding="utf-8"); os.replace(tmp, f)


def set_owner(root, name): _write_cfg_key(root, "owner", name)


def set_member(root, name, role):
    """role None removes the member. The owner is never a member."""
    if role is not None and role not in ROLES: raise HubError("角色应该是 view / comment / edit")
    if name == owner_of(root): raise HubError("所有者不需要加成员")
    m = members_of(root)
    if role is None: m.pop(name, None)
    else: m[name] = role
    _write_cfg_key(root, "members", m)


def migrate(owner: str, dry_run=False) -> list:
    """Give every registered project without an owner this owner (config/project.yaml `owner:`). -> [(id, path, what)]."""
    out = []
    for e in projects.load():
        root = Path(e["path"])
        if not _cfg_file(root).exists(): out.append((e["id"], str(root), "skipped (no config/project.yaml)")); continue
        o = owner_of(root)
        if o: out.append((e["id"], str(root), f"kept owner {o}")); continue
        if not dry_run: set_owner(root, owner)
        out.append((e["id"], str(root), f"owner -> {owner}" + (" (dry run)" if dry_run else "")))
    return out


def create_project(user: dict, title, kind="memory", lang="en", game="stardew", build_mode=None) -> dict:
    """A new project in the user's data_root/projects/, owned by them."""
    return projects.create(title, kind, lang=lang, game=game, owner=user["name"], data=Path(user.get("data_root") or projects.data_dir()), build_mode=build_mode)


# ---------------------------------------------------------------- access requests (a permission card in the owner's project thread)
def _req_file(root) -> Path: return Path(root) / layout.CONFIG / "access_requests.yaml"


def requests_of(root) -> list:
    try: d = yaml.safe_load(_req_file(root).read_text(encoding="utf-8")) or []
    except (OSError, yaml.YAMLError): return []
    return [r for r in d if isinstance(r, dict)] if isinstance(d, list) else []


def _save_requests(root, rs):
    f = _req_file(root); f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f".access_requests.yaml.{os.getpid()}.tmp")
    tmp.write_text("# 别人对这个项目的权限申请（gameanything hub）；所有者在对话里的卡片上同意或拒绝\n" + yaml.safe_dump(rs, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
    os.replace(tmp, f)


def latest_request(root, name):
    rs = [r for r in requests_of(root) if r.get("user") == name]
    return rs[-1] if rs else None


def _card(req, who, owner_name):
    role = req["role"]; rz, re_ = ROLE_ZH[role], ROLE_EN[role]
    can = {"view": ("只能看这个项目的对话和工作区，不能说话、不能改", "can only read this project's conversation and workspace; cannot write or change anything"),
           "comment": ("能看，也能在对话里说话、留意见；不能回答卡片、不能开工、不能改设置", "can read, write in the conversation and leave notes; cannot answer cards, start builds or change settings"),
           "edit": ("能看、能说话、能回答卡片、能开工和改设置；不能删项目、不能改成员", "can read, write, answer cards, start builds and change settings; cannot delete the project or change members")}[role]
    quota = ("TA 在对话里说的话由这个项目的 agent 回答，agent 用的是你的 Claude 登录和额度，不是 TA 的",
             "Their messages here are answered by this project's agent, which runs on YOUR Claude login and quota, not theirs")
    zh = {"kind": "permission", "key": f"access-{req['id']}", "title": f"{who} 申请这个项目的「{rz}」权限",
          "to": f"{who}（{req['user']}）",
          "will_send": [f"TA {can[0]}"] + ([quota[0]] if role in ("comment", "edit") else []),
          "will_not_send": ["你的密码和 Claude 登录凭据（TA 看不到）", "你的其他项目（各自单独申请）"],
          "access": {"request": req["id"], "user": req["user"], "role": role}}
    en = {"title": f"{who} asks for “{re_}” access to this project", "to": f"{who} ({req['user']})",
          "will_send": [f"They {can[1]}"] + ([quota[1]] if role in ("comment", "edit") else []),
          "will_not_send": ["Your password and Claude login (they never see them)", "Your other projects (each is asked for separately)"]}
    return zh, en


REQ_GAP, REQ_MAX, REQ_WINDOW = 60, 5, 86400      # access requests per (user, project): one a minute, five a day (each is a card in the owner's chat)


def _recent_requests(rs, name, t0):
    out = []
    for r in rs:
        if r.get("user") != name: continue
        try: at = clock.epoch(r.get("at"))
        except ValueError: continue
        if t0 - at < REQ_WINDOW: out.append(at)
    return sorted(out)


def request_access(root, user: dict, role: str, note: str = "") -> dict:
    """Ask the owner for a role; posts a permission card into the project's own thread. A pending request of the same user is replaced."""
    from .conversation import Thread, check_card
    if role not in ROLES: raise HubError("角色应该是 view / comment / edit")
    owner = owner_of(root); name = user["name"]
    if not owner: raise HubError("这个项目还没有所有者")
    if name == owner: raise HubError("这是你自己的项目")
    cur = members_of(root).get(name)                          # what a "no" restores
    if LEVEL[role] <= LEVEL.get(role_of(user, root), 0): raise HubError("你已经有这个权限了")
    note = str(note or "").strip()[:500]
    rs = requests_of(root); t0 = time.time(); recent = _recent_requests(rs, name, t0)
    if recent and t0 - recent[-1] < REQ_GAP: raise HubError("刚刚申请过了：请等一分钟再申请")
    if len(recent) >= REQ_MAX: raise HubError("今天申请太多次了：请明天再试，或直接联系所有者")
    for r in rs:
        if r.get("user") == name and r.get("state") == "pending": r["state"] = "replaced"
    req = {"id": secrets.token_hex(4), "user": name, "role": role, "prev": cur, "note": note, "at": now(), "state": "pending"}
    zh, en = _card(req, user.get("display") or name, display(owner))
    check_card(dict(zh))
    T = Thread(root)
    ev = T.append({"from": "system", "type": "card", "source": "hub", "card": zh, "card_en": en,
                   "text": f"附言：{note}" if note else "", **({"text_en": f"Note: {note}"} if note else {})})
    req["card_id"] = ev["id"]; rs.append(req); _save_requests(root, rs)
    return req


def access_card(root, card_id):
    """The access-request card with this id (its `access` field), or None for any other card."""
    from .conversation import Thread
    c = Thread(root).cards().get(card_id)
    return c if c and isinstance(c["card"].get("access"), dict) else None


def decide(root, card_id, answer: dict, by: dict) -> dict:
    """The owner's answer on an access card: yes -> members[user] = role; no -> the role they had before. -> the answer event."""
    from .conversation import CardError, Thread, check_answer
    c = access_card(root, card_id)
    if not c: raise CardError("找不到这张卡")
    if by["name"] != owner_of(root): raise HubError("只有项目的所有者能决定权限申请")
    check_answer("permission", answer)
    acc = c["card"]["access"]; rs = requests_of(root); req = next((r for r in rs if r.get("id") == acc.get("request")), None)
    if not req or req.get("state") != "pending": raise CardError("这个申请已经处理过了（或被新的申请替换了）")
    if answer["decision"] == "yes": set_member(root, acc["user"], acc["role"])
    else: set_member(root, acc["user"], req.get("prev"))
    req.update(state="approved" if answer["decision"] == "yes" else "denied", decided_at=now(), by=by["name"]); _save_requests(root, rs)
    # source hub: the owner's decision is not words for the agent (agentd does not start a run for it)
    return Thread(root).answer(card_id, answer, source="hub", author=by["name"], author_name=by.get("display") or by["name"])


# ---------------------------------------------------------------- agentd: the owner's login for a project's runs
def agent_for(root, default=None) -> str:
    """Which agent CLI runs this project: its owner's choice (hub), else the daemon's --provider (default)."""
    d = default if default in AGENTS else "claude-code"
    if not enabled(): return d
    return agent_of(get_user(owner_of(root)), d)


def run_env(root, env: dict, agent=None):
    """-> (env for the project's agent run, None) or (None, why it may not run). Without a hub (no users.yaml) the env is unchanged.
    The run gets the OWNER's login (Claude config dir / CODEX_HOME, agent = which CLI) and env file; credentials of the supervisor's own
    environment never reach another user's run."""
    if not enabled(): return env, None
    owner = owner_of(root)
    if not owner: return None, "no owner (run: gameanything hub migrate --owner <user>)"
    u = get_user(owner)
    if not u: return None, f"owner {owner} is not a hub user"
    a = agent or agent_of(u)
    if not agent_connected(u, a):
        if a == "codex": return None, f"owner {owner} has no Codex login yet (「我的 agent」 in the hub: an OpenAI API key, or gameanything hub user login {owner} --agent codex)"
        if a == "opencode": return None, f"owner {owner} has no OpenCode key yet (「我的 agent」 in the hub: the API key of {opencode_model(u).split('/')[0]}, e.g. OpenRouter)"
        if a == "gemini": return None, f"owner {owner} has no Gemini login yet (「我的 agent」 in the hub: a Gemini API key, or gameanything hub user login {owner} --agent gemini)"
        if a == "dsh": return None, f"owner {owner} has no {dsh_key_name(u)} yet (「我的 agent」 in the hub: DeepSeek Harness, a DeepSeek or OpenRouter key)"
        return None, f"owner {owner} has no Claude login yet (「我的 Claude」 in the hub, or gameanything hub user login {owner})"
    env = user_env(u, env, a); env["GAMEANYTHING_USER"] = owner
    return env, None


def model_for(root, agent):
    """The model the owner chose for this agent CLI (OpenCode / Gemini / dsh, users.yaml), else None (the daemon's --model or the default)."""
    if agent not in ("opencode", "gemini", "dsh") or not enabled(): return None
    return (get_user(owner_of(root)) or {}).get(f"{agent}_model") or None


def gen_env(root, env: dict):
    """-> (env for a paid generation script of this project, None) or (None, why not). The same env as the owner's agent runs (user_env:
    on a hub the owner's own key file, the supervisor's keys stripped), but a Claude login is not needed: the script calls no Claude."""
    if not enabled(): return env, None
    owner = owner_of(root)
    if not owner: return None, "no owner (run: gameanything hub migrate --owner <user>)"
    u = get_user(owner)
    if not u: return None, f"owner {owner} is not a hub user"
    env = user_env(u, env); env["GAMEANYTHING_USER"] = owner
    return env, None


def user_env(u, env: dict, agent="claude-code") -> dict:
    """The env of a run on this user's login: Claude = their config dir (unless it is the default one), Codex = their CODEX_HOME (unless it
    is the supervisor's) and an OpenAI key of theirs as CODEX_API_KEY; plus their env file. A token / key of their own replaces the
    supervisor's. Credentials of the supervisor's environment never reach another user's run. (Paid keys of the env file stay here for
    gen_env; resident / builder runs drop them: agent_providers.agent_env.)"""
    env = dict(env); extra = env_file_values(u)
    if agent in ("opencode", "gemini", "dsh"):               # always the user's own agent home: the operator's config never applies
        env = {k: v for k, v in env.items() if not CRED_RE.match(k)}
        var, h = {"opencode": ("GAMEANYTHING_OPENCODE_HOME", opencode_home), "gemini": ("GAMEANYTHING_GEMINI_HOME", gemini_home),
                  "dsh": ("GAMEANYTHING_DSH_HOME", dsh_home)}[agent]
        env[var] = str(h(u))
        env["GAMEANYTHING_KEYS_FILE"] = str(env_path(u)) if u.get("env_file") else ""
        env.update({k: v for k, v in extra.items() if k not in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", *envcompat.names("OPENCODE_HOME", "GEMINI_HOME", "DSH_HOME"),
                                                                 "GEMINI_CLI_HOME", "DSH_HOME")})
        return env
    if agent == "codex":
        h = codex_home(u)
        if not is_default_codex_home(h):                       # (the supervisor's own Codex login: its env stays, as for Claude)
            env = {k: v for k, v in env.items() if not CRED_RE.match(k)}
            env["CODEX_HOME"] = str(h)
            env["GAMEANYTHING_KEYS_FILE"] = str(env_path(u)) if u.get("env_file") else ""
        env.update({k: v for k, v in extra.items() if k not in ("CLAUDE_CONFIG_DIR", "CODEX_HOME")})
        if extra.get(CODEX_KEY): env["CODEX_API_KEY"] = extra[CODEX_KEY]      # codex exec reads its API key from CODEX_API_KEY
        return env
    if is_default_config(u.get("claude_config_dir")):
        env.pop("CLAUDE_CONFIG_DIR", None)                     # the supervisor's own (default) login, exactly as before the hub
    else:
        env = {k: v for k, v in env.items() if not CRED_RE.match(k)}
        env["CLAUDE_CONFIG_DIR"] = str(Path(u["claude_config_dir"]).expanduser())
        env["GAMEANYTHING_KEYS_FILE"] = str(env_path(u)) if u.get("env_file") else ""      # paid keys: the owner's file or none
    if any(extra.get(k) for k in CLAUDE_KEYS):
        for k in CLAUDE_KEYS: env.pop(k, None)               # the login they chose, not a mix with the supervisor's
    env.update({k: v for k, v in extra.items() if k != "CLAUDE_CONFIG_DIR"})
    return env


def blocked(root, agent=None):
    """Why agentd may not run this project now (None: it may). agent: the daemon's provider (the owner's choice wins)."""
    return run_env(root, {}, agent_for(root, agent) if agent else None)[1]


def default_login_may_run(root) -> bool:
    """An interactive / parent agent session (on the default Claude login) may answer this project: no hub, or its owner's login is the
    default one. Other users' projects are answered only by agentd, with their own login."""
    if not enabled(): return True
    u = get_user(owner_of(root))
    return bool(u) and is_default_config(u.get("claude_config_dir"))
