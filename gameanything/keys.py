"""The user's own API keys for model calls the user approved on a permission card (image generation etc.).
Read at call time from the environment, else from the user's keys file (settings `keys_file`: a KEY=value file such as a .env; on a hub
the owner's env file, GAMEANYTHING_KEYS_FILE), else (single-user installs only) from the system keyring (`gameanything gen key set NAME`).
The value is never printed, logged or copied, so an agent session can run an approved generation without ever seeing the key.

    lookup(name, env)   -> the value or None, from that env dict (genrun passes the project owner's env: users.gen_env)
    source(name, env)   -> where it comes from ("env" | "keys file" | "keyring" | None), never the value
    get(name)           -> the value from this process's env, or MissingKey / GenOff (GAMEANYTHING_GEN_OFF: inside a resident / builder run)
"""
import os
from pathlib import Path

KEYRING_SERVICE = "m2w-gen"
# other names a key goes by (fal's own docs say FAL_KEY; many .env files say FAL_API_KEY): looked up after the main name, in each source
ALIASES = {"FAL_KEY": ("FAL_API_KEY",)}


def names(name: str) -> tuple: return (name, *ALIASES.get(name, ()))


class MissingKey(RuntimeError):
    pass


class GenOff(MissingKey):
    pass


def _from_file(path: Path, name: str):
    try: lines = path.read_text(encoding="utf-8-sig").splitlines()          # -sig: a .env saved by Windows Notepad may start with a BOM
    except OSError: return None
    for l in lines:
        k, sep, v = l.strip().removeprefix("export ").partition("=")
        if sep and k.strip() == name: return v.strip().strip("'\"") or None
    return None


def _keys_file(env):
    # GAMEANYTHING_KEYS_FILE: set by `gameanything agentd` for a hub user's run (that user's own file; empty = none); else the settings' keys file
    if "GAMEANYTHING_KEYS_FILE" in env: return env["GAMEANYTHING_KEYS_FILE"] or None
    # GAMEANYTHING_USER_ENV_FILE: the same, in a Gemini run's shell (gemini hides every variable with KEY in its name from the commands it runs)
    if "GAMEANYTHING_USER_ENV_FILE" in env: return env["GAMEANYTHING_USER_ENV_FILE"] or None
    from . import projects
    return projects.settings().get("keys_file")


def _keyring(name, env):
    """The keyring belongs to the OS user that runs GameAnything: only when no hub user's key file is in play (GAMEANYTHING_KEYS_FILE not set)."""
    if "GAMEANYTHING_KEYS_FILE" in env or "GAMEANYTHING_USER_ENV_FILE" in env or env.get("GAMEANYTHING_NO_KEYRING"): return None
    from . import osdirs
    return osdirs.secret_get(KEYRING_SERVICE, name) or None


def _first(read, name):
    for n in names(name):
        v = read(n)
        if v: return v
    return None


def _sources(name, env):
    yield "env", lambda: _first(lambda n: env.get(n) or None, name)
    f = _keys_file(env)
    if f: yield "keys file", lambda: _first(lambda n: _from_file(Path(f).expanduser(), n), name)
    yield "keyring", lambda: _first(lambda n: _keyring(n, env), name)


def lookup(name: str, env=None):
    env = os.environ if env is None else env
    for _, read in _sources(name, env):
        v = read()
        if v: return v
    return None


def source(name: str, env=None):
    env = os.environ if env is None else env
    for label, read in _sources(name, env):
        if read(): return label
    return None


def _lookup(name: str): return lookup(name)


def get(name: str) -> str:
    # GAMEANYTHING_GEN_OFF: set by agentd in every resident / builder run (agent_providers.agent_env): a script a model run starts gets no paid key;
    # paid calls run only through `gameanything gen request` (agentd checks her two cards, genrun.py, and runs it with the keys)
    if os.environ.get("GAMEANYTHING_GEN_OFF"):
        raise GenOff(f"{name}：付费调用只能通过 gameanything gen request 排队（后台核对两张卡后运行），agent 自己不能用 key / "
                     "paid calls run only through `gameanything gen request` (agentd checks both cards, then runs it)")
    v = _lookup(name)
    if v: return v
    raise MissingKey(f"没有找到 {name}：请在设置里指定 key 文件（gameanything project settings --keys-file <路径>，文件里一行 {name}=...），"
                     f"或者 gameanything gen key set {name}，或者在环境变量里提供 / {name} not found: set a keys file (gameanything project settings --keys-file <path>), "
                     f"`gameanything gen key set {name}`, or the env var")


def available(name: str, env=None) -> bool:
    """The key is there (env, keys file or keyring); true in a run too (GAMEANYTHING_GEN_OFF only stops handing it out)."""
    return bool(lookup(name, env))


def keyring_set(name: str, value: str) -> bool:
    from . import osdirs
    return osdirs.secret_set(KEYRING_SERVICE, name, value.strip(), f"gameanything {name}")


def keyring_clear(name: str) -> bool:
    from . import osdirs
    return osdirs.secret_clear(KEYRING_SERVICE, name)


def keyring_has(name: str) -> bool:
    from . import osdirs
    return bool(osdirs.secret_get(KEYRING_SERVICE, name))
