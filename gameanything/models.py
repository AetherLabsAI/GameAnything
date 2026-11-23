"""Which agent CLI and which model a project's chat (the resident) and its builds use: config/project.yaml `chat_model` / `build_model`.

    chat_model:  {agent: claude-code, model: opus}        the resident runs (agentd.Daemon.provider_for(root, "chat"))
    build_model: {agent: codex, model: gpt-6.1-sol}       every builder of the project (builds.py; the go card only shows it)

Not set (the default): the owner's choice in the hub's 「我的 agent」 (users.agent_for / model_for), else the daemon's --provider / --model.
`model` empty = the CLI's own default (Claude Code: sonnet, the daemon's --model). Same agent, another model: the resident session is
resumed (every CLI takes --model on a resume). Another agent: agentd starts a new session and seeds it with the recent thread.

    gameanything project set-model <id> [chat|build] [agent[:model] | default] [--list]

The chat page's two chips (「对话：…」 「构建：…」, shell.js) read /api/models (state) and the owner changes them with POST /api/models (set).
Only the agents the owner can actually run are offered (a login / key for the owner in the hub; an installed CLI without a hub), with a
short curated model list per agent (catalog); OpenCode / Gemini / DeepSeek Harness also take a typed model (users.check_model).
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from . import projects, users

ROLES = ("chat", "build")
KEY = {"chat": "chat_model", "build": "build_model"}
AGENT_NAME = users.AGENT_NAME
DEFAULT_MODEL = {"claude-code": "sonnet", "gemini": "gemini-3.5-flash"}            # what the provider passes when no model is chosen (agent_providers.provider)

# the hints are the page's Chinese source strings (i18n.js has their English)
CLAUDE = [{"id": "sonnet", "label": "Sonnet", "hint": "日常默认：又快又稳，额度用得适中"},
          {"id": "opus", "label": "Opus", "hint": "更强，适合难的任务；更慢一些，用的额度更多"},
          {"id": "haiku", "label": "Haiku", "hint": "最快最省，适合简单的事；复杂的构建可能做不好"},
          {"id": "fable", "label": "Fable", "hint": "最强也最贵：额度用得最快，一期构建可能就用完",
           "warn": "Fable 非常贵：同样的活，它用掉的额度（或 API 的钱）比 Opus 多一倍左右，比 Sonnet 多好几倍。一期构建可能就用完你这几个小时的额度。只在别的模型做不好的时候选它。"}]
CLAUDE_FAMILIES = tuple(m["id"] for m in CLAUDE)    # the aliases the Claude Code CLI takes (`claude --model fable` = claude-fable-5-1)
# The Codex menu is a fixed list: Codex's models_cache.json is rewritten by every other Codex session on the machine (QA 2026-10-29: the
# menu changed under her). A model chosen before that is not in the list stays offered (state()).
CODEX_MODELS = ["gpt-6.1-sol", "gpt-6-astra", "gpt-6.1-terra", "gpt-6-luna"]
CODEX_FALLBACK = CODEX_MODELS                         # old name
# runs pass --ignore-user-config (agent_providers.Codex): the default is Codex's built-in one, never the model in her config.toml
HINT_DEFAULT = {"codex": "用 Codex 内置的默认模型（不是你自己 Codex 配置里写的那个）", "gemini": "gemini-3.5-flash：快，日常对话和整理够用",
                "opencode": "OpenCode 的默认模型", "dsh": "DeepSeek Harness 的默认模型"}
HINT_MINE = "你在「我的 agent」里配的模型"
# the Gemini menu (besides 默认 = GEMINI_DEFAULT_MODEL): models that answer on an AI Studio key (QA2 2026-10-30). gemini-3-flash
# (ModelNotFound) and the retired flash-lite models are refused by check().
GEMINI_MODELS = (("gemini-3.1-pro-preview", "更强，适合难的任务；更慢一些，用的额度更多"),)
GEMINI_GONE = {"gemini-3-flash": "gemini-3.5-flash", "gemini-2.5-flash-lite": "gemini-3.5-flash", "gemini-2.0-flash-lite": "gemini-3.5-flash"}
HINT_FREE = {"opencode": "也可以填别的 provider/model（要有那个 provider 的 key）", "gemini": "也可以填别的 Gemini 模型名",
             "dsh": "也可以填 DeepSeek 的模型名，或 openrouter/ 加 OpenRouter 上的模型名（要有对应的 key）"}
PLACEHOLDER = {"opencode": "openrouter/moonshotai/kimi-k2.6", "gemini": "gemini-3.1-pro-preview", "dsh": "openrouter/deepseek/deepseek-v4.1-flash"}
FULL_CLAUDE_RE = re.compile(r"^claude-[a-z0-9][a-z0-9.-]{1,60}$")
CODEX_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")


class ModelError(ValueError):
    pass


def _codex_hint(slug: str, desc: str = "") -> str:
    d = (desc or "").lower()
    if d.startswith(("older", "previous")): return "上一代模型，一般不用选它"
    s = slug.lower()
    if "astra" in s: return "最强，适合最难的任务；用的额度最多"
    if "sol" in s: return "主力模型：编程和日常都好用"
    if "terra" in s: return "均衡，适合直截了当的活"
    if "luna" in s: return "快又省，适合简单的事"
    return "Codex 提供的模型"


def _codex_home(u) -> Path:
    if u: return users.codex_home(u)
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()


def codex_models(u=None) -> list:
    """The Codex menu: the default (Codex's built-in one), then the fixed CODEX_MODELS (stable, whatever models_cache.json says now)."""
    return [{"id": "", "label": "默认", "hint": HINT_DEFAULT["codex"]}] + [{"id": m, "label": m, "hint": _codex_hint(m)} for m in CODEX_MODELS]


def catalog(agent, u=None) -> dict:
    """{models: [{id, label, hint}], free: bool, placeholder}: the menu of one agent for this owner."""
    if agent == "claude-code": return {"models": [dict(m) for m in CLAUDE], "free": False}
    if agent == "codex": return {"models": codex_models(u), "free": False}
    mine = (u or {}).get(f"{agent}_model") or (os.environ.get(f"GAMEANYTHING_{agent.upper()}_MODEL") if not u else None)
    if agent in ("opencode", "dsh"):
        from . import agent_providers
        mine = mine or (agent_providers.OPENCODE_DEFAULT_MODEL if agent == "opencode" else agent_providers.DSH_DEFAULT_MODEL)
        ms = [{"id": mine, "label": mine, "hint": HINT_MINE if (u or {}).get(f"{agent}_model") else HINT_DEFAULT[agent]}]
    else:
        ms = [{"id": "", "label": "默认", "hint": HINT_DEFAULT["gemini"]}] + [{"id": m, "label": m, "hint": h} for m, h in GEMINI_MODELS if m != mine] \
             + ([{"id": mine, "label": mine, "hint": HINT_MINE}] if mine else [])
    return {"models": ms, "free": True, "free_hint": HINT_FREE[agent], "placeholder": PLACEHOLDER[agent]}


def norm_agent(a) -> str:
    try: return users._check_agent(a)
    except users.HubError as x: raise ModelError(str(x))


def check(agent, model, u=None) -> str:
    """The model as the CLI takes it ('' = its default), or ModelError (the message is the page's Chinese, shown as is)."""
    m = str(model or "").strip()
    if agent == "claude-code":
        if not m: return ""
        if m.lower() in {x["id"] for x in CLAUDE}: return m.lower()
        if FULL_CLAUDE_RE.match(m): return m
        raise ModelError("Claude Code 的模型是 sonnet、opus、haiku、fable（或完整的 claude-… 名字）")
    if agent == "codex":
        if not m or CODEX_RE.match(m): return m
        raise ModelError("Codex 的模型名不对，例如 gpt-6.1-sol")
    if agent in ("opencode", "dsh") and not m: return ""
    if agent == "gemini" and m.lower() in GEMINI_GONE:
        raise ModelError(f"Gemini 没有 {m} 这个模型了（Google 返回 ModelNotFound），可以用 {GEMINI_GONE[m.lower()]}")
    try: m = users.check_model(agent, m)
    except users.HubError as x: raise ModelError(str(x))
    if agent == "opencode" and u is not None:           # the key of that model's provider must be there (her env file or an opencode login)
        from . import agent_providers
        names = agent_providers.opencode_key_names(m); pid = m.split("/", 1)[0]
        ev = users.env_file_values(u)
        try: login = pid in json.loads((users.opencode_home(u) / "data" / "opencode" / "auth.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError): login = False
        if not (login or any(ev.get(k) for k in names)):
            raise ModelError(f"「我的 agent」里还没有 {pid} 的 key（{names[0]}），这个模型跑不起来")
    if agent == "dsh" and u is not None:                # DeepSeek's own API or a pi-ai route: that route's key must be in her env file
        from . import agent_providers
        pid, _, key = agent_providers.dsh_route(m)
        if not users.env_file_values(u).get(key):
            raise ModelError(f"「我的 agent」里还没有 {'DeepSeek' if pid == agent_providers.DSH_PROVIDER else pid} 的 key（{key}），这个模型跑不起来")
    return m


# ---------------------------------------------------------------- what is chosen
def _cfg(root) -> dict:
    return projects.config_of(root)


def chosen(root, role) -> dict | None:
    """The project's own choice {agent, model} (config/project.yaml), or None."""
    v = _cfg(root).get(KEY[role])
    if not isinstance(v, dict) or v.get("agent") not in users.AGENTS: return None
    return {"agent": v["agent"], "model": str(v.get("model") or "")}


def daemon_default() -> tuple:
    """(provider, model) of the running agentd (its heartbeat), else of this environment (GAMEANYTHING_AGENT_PROVIDER, Claude Code + sonnet)."""
    try:
        from . import agentd
        hb = json.loads(agentd.heartbeat_path().read_text(encoding="utf-8"))
        if hb.get("provider") in users.AGENTS: return hb["provider"], hb.get("model") or None
    except (OSError, ValueError, AttributeError): pass
    p = (os.environ.get("GAMEANYTHING_AGENT_PROVIDER") or "claude-code").lower().replace("_", "-")
    if p == "claude": p = "claude-code"
    return (p if p in users.AGENTS else "claude-code"), None


def default(root, daemon=None) -> dict:
    """What runs without a project choice: the owner's agent (hub) with its model (OpenCode / Gemini), else the daemon's provider + --model."""
    dp, dm = daemon or daemon_default()
    a = users.agent_for(root, dp)
    om = users.model_for(root, a)
    m = om or (dm if a == dp else None) or ""
    o = users.get_user(users.owner_of(root)) if users.enabled() else None
    return {"agent": a, "model": m, "source": "owner" if (o and (o.get("agent") in users.AGENTS or om)) else "daemon"}


def effective(root, role, daemon=None) -> dict:
    """{agent, model, source: project | owner | daemon}: what the next chat run / build of this project uses."""
    c = chosen(root, role)
    if c: return {**c, "source": "project"}
    return default(root, daemon)


def run_model(agent, model):
    """The model handed to agent_providers.provider: None = its default (Claude Code: sonnet)."""
    return model or None


def shown_model(agent, model) -> str:
    """The model in words for a chip / card (and the menu's key of it): '' = the CLI default (Claude Code: sonnet; OpenCode: its default)."""
    if model: return model
    if agent == "opencode":
        from . import agent_providers
        return os.environ.get("GAMEANYTHING_OPENCODE_MODEL") or agent_providers.OPENCODE_DEFAULT_MODEL
    if agent == "dsh":
        from . import agent_providers
        return os.environ.get("GAMEANYTHING_DSH_MODEL") or agent_providers.DSH_DEFAULT_MODEL
    return DEFAULT_MODEL.get(agent, "")


def label(agent, model) -> str:
    m = shown_model(agent, model)
    return AGENT_NAME.get(agent, agent) + (f" · {m}" if m else "")


def set_choice(root, role, agent=None, model=None, by=None):
    """agent None / 'default': remove the project's choice (back to the default). Validated against what the owner can run (hub)."""
    if role not in ROLES: raise ModelError("应该是 chat 或 build")
    if agent in (None, "", "default"):
        users._write_cfg_key(root, KEY[role], None); return effective(root, role)
    a = norm_agent(agent); u = owner_user(root)
    if a not in usable(root, u): raise ModelError(f"项目所有者还不能用 {AGENT_NAME.get(a, a)}（先在「我的 agent」里登录或填 key）")
    nope = unavailable(a)
    if nope: raise ModelError(nope)
    m = check(a, model, u)
    users._write_cfg_key(root, KEY[role], {"agent": a, "model": m})
    return effective(root, role)


# ---------------------------------------------------------------- what the owner can use
def owner_user(root):
    if not users.enabled(): return None
    o = users.owner_of(root)
    u = users.get_user(o) if o else None
    return {**u, "name": o} if u else None


def _installed(agent) -> bool:
    from . import agent_providers
    exe, var = agent_providers.EXE[agent]
    v = os.environ.get(var)
    return bool((v and Path(v).exists()) or shutil.which(exe))


def usable(root, u=None, daemon=None) -> list:
    """The agents this project's runs can use: hub = the owner's logins / keys; no hub = the installed CLIs (the daemon's always)."""
    dp = (daemon or daemon_default())[0]
    if users.enabled():
        u = u if u is not None else owner_user(root)
        if not u: return []
        return [a for a in users.AGENTS if users.agent_connected(u, a)]
    return [a for a in users.AGENTS if a == dp or _installed(a)]


def state(root, can_edit=True, daemon=None) -> dict:
    """/api/models: both choices and, per usable agent, its menu."""
    d = daemon or daemon_default(); u = owner_user(root)
    out = {"can_edit": bool(can_edit), "hub": users.enabled(), "agents": [], "expensive": expensive()}
    for r in ROLES:
        e = effective(root, r, d)
        out[r] = {**e, "agent_name": AGENT_NAME.get(e["agent"], e["agent"]), "model_shown": shown_model(e["agent"], e["model"]),
                  "warn": warning(e["agent"], e["model"])}
    for a in usable(root, u, d):
        g = {"id": a, "name": AGENT_NAME.get(a, a), **catalog(a, u), "unavailable": unavailable(a)}
        ids = {m["id"] for m in g["models"]}
        for r in ROLES:                                     # a model chosen earlier that the fixed list does not have stays offered
            if out[r]["agent"] == a and out[r]["model"] and out[r]["model"] not in ids and not g.get("free"):
                g["models"].append({"id": out[r]["model"], "label": out[r]["model"], "hint": "现在用的模型"}); ids.add(out[r]["model"])
        out["agents"].append(g)
    return out


UNAVAILABLE = {"codex": "Codex 在这台机器上不能运行命令（它的沙盒需要这个容器没有的权限）：请选别的 agent，或者请管理员看一下"}


def unavailable(agent) -> str:
    """'' when the agent CLI can work on this machine, else why not (the page's Chinese): Codex whose sandbox cannot start here."""
    if agent != "codex": return ""
    from . import agent_providers
    try: why = agent_providers.provider("codex").unavailable()
    except Exception: return ""
    return UNAVAILABLE["codex"] if why else ""


def text(root) -> str:
    out = []
    for r in ROLES:
        e = effective(root, r)
        out.append(f"{r}_model={e['agent']}" + (f":{e['model']}" if e["model"] else "") + ("" if e["source"] == "project" else f" (not chosen: {e['source']} default)"))
    return "  ".join(out)


# ---------------------------------------------------------------- go card runners (builds)
HARNESS = {"claude code": "claude-code", "claude": "claude-code", "codex": "codex", "opencode": "opencode", "gemini": "gemini", "gemini cli": "gemini",
           "dsh": "dsh", "deepseek harness": "dsh"}


def cli_model(agent, model) -> str:
    """A runner's model (the price-table form: anthropic/claude-sonnet, openai/gpt-5) -> what the CLI takes (sonnet, gpt-5)."""
    m = str(model or "").strip()
    if agent in ("claude-code", "codex", "gemini"):
        for v in ("anthropic/", "openai/", "google/"):
            if m.lower().startswith(v): m = m[len(v):]
    if agent == "claude-code":
        x = m.lower()
        for fam in CLAUDE_FAMILIES:
            if x in (fam, f"claude-{fam}"): return fam
    return m


def runner_choice(runner: dict) -> dict | None:
    """A go card runner {id, harness, model} -> {agent, model} (the id is agent:model when `gameanything estimate --runners` wrote it)."""
    if not isinstance(runner, dict): return None
    rid = str(runner.get("id") or ""); a = rid.split(":", 1)[0] if ":" in rid else ""
    if a not in users.AGENTS: a = HARNESS.get(str(runner.get("harness") or "").strip().lower(), "")
    if a not in users.AGENTS: return None
    m = cli_model(a, runner.get("model"))
    return {"agent": a, "model": "" if m.lower() in ("default", "默认") else m}


def same(a: dict, b: dict) -> bool:
    if not a or not b or a.get("agent") != b.get("agent"): return False
    return shown_model(a["agent"], cli_model(a["agent"], a.get("model"))) == shown_model(b["agent"], cli_model(b["agent"], b.get("model")))


def warning(agent, model) -> str:
    """The warning of an expensive model (the page's Chinese; '' = none): Fable, chosen in Claude Code or by its name through another
    agent (OpenCode `anthropic/claude-fable-5-1`, `openrouter/anthropic/claude-fable…`)."""
    m = cli_model(agent, model).lower() if agent == "claude-code" else str(model or "").strip().lower()
    if agent != "claude-code": m = m.rsplit("/", 1)[-1]
    if not m: return ""
    return next((x.get("warn", "") for x in CLAUDE if x["id"] == m or (x["id"] == "fable" and m.startswith("claude-fable"))), "")


def expensive() -> list:
    """For the model menu's typed names: [{pattern, warn}] (a JS regex source), so a model typed for another agent warns like the list."""
    return [{"pattern": r"(^|/)(claude-)?fable([-.@:]|$)", "warn": x["warn"]} for x in CLAUDE if x["id"] == "fable" and x.get("warn")]


def stamp_build_model(root, card: dict) -> tuple:
    """A build go card as `gameanything chat card` posts it: builds use ONLY the project's build model, so the card names it
    (`build_model`, read only; she changes it with the 「构建」 chip) and carries its estimate. `runners` are taken off (an old habit / an
    older doc): the estimate of the runner that is the build model becomes the card's; otherwise the card's own estimate is kept when it
    is for the build model, else one of the same size is made for it. Returns (card, note): note = what the resident should fix ('')."""
    if not isinstance(card, dict) or card.get("kind") != "go": return card, ""
    b = effective(root, "build"); card = dict(card); note = ""
    rs = [r for r in card.pop("runners", None) or [] if isinstance(r, dict)]
    en = dict(card["en"]) if isinstance(card.get("en"), dict) else None
    ers = [r for r in (en.pop("runners", None) or []) if isinstance(r, dict)] if en is not None else []
    est_of = lambda e: {"agent": e.get("agent") or "claude-code", "model": e.get("model") or ""} if isinstance(e, dict) else None
    hit = next((r for r in rs if same(runner_choice(r) or {}, b) and r.get("estimate")), None)
    if hit:
        card["estimate"] = hit["estimate"]
        eh = next((r for r in ers if r.get("id") == hit.get("id") and r.get("estimate")), None)
        if en is not None and eh: en["estimate"] = eh["estimate"]
    elif card.get("estimate") is None or not same(est_of(card.get("estimate")) or {}, b):
        old = card.get("estimate") or next((r.get("estimate") for r in rs if r.get("estimate")), None)
        x = _estimate_like(old, b)
        if x:
            card["estimate"] = x[0]
            if en is not None or card.get("en") is None: en = {**(en or {}), "estimate": x[1]}
        elif old:
            card["estimate"] = old
            note = (f"这张开工卡的估算不是按项目的构建模型（{label(b['agent'], b['model'])}）算的："
                    f"gameanything estimate --project \"$P\" --size small|medium|large --yaml，并进卡片再发一次（同一个 key）")
    card["build_model"] = {"agent": b["agent"], "model": b["model"], "label": label(b["agent"], b["model"])}
    if en is not None: card["en"] = en
    return card, note


def _estimate_like(est, b):
    """(estimate, estimate_en) for the build model of the size `est` was made for (its wall_h); None when it cannot be told."""
    from . import estimate as E
    w = (est or {}).get("wall_h") if isinstance(est, dict) else None
    try:
        P = E.load(); size = next((s for s in E.SIZES if list(P["sizes"][s]["wall_h"]) == list(w or [])), None)
        if not size: return None
        acct = est.get("account") if est.get("account") in ("subscription", "api") and (est.get("agent") or "claude-code") == b["agent"] else None
        x = E.estimate(size, b["agent"], b["model"] or None, acct)
        return x["estimate"], x["estimate_en"]
    except Exception: return None
