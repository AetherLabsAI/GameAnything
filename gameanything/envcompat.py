"""Environment variable names: GAMEANYTHING_<NAME> is the name; M2W_<NAME> (memory2world, before the rename on 2026-10-27) still works.

The one place that knows about the old prefix. Code reads and writes only GAMEANYTHING_* names; `adopt(os.environ)` runs once when the
package is imported (gameanything/__init__.py) and copies every M2W_<NAME> whose GAMEANYTHING_<NAME> is not set, so an old shell
profile, service unit or env file keeps working and the new name wins when both are set. The old names stay in the environment (other
tools read them: the lab tools in gamebench read M2W_LEASE and the M2W_LAB_* settings), so a child env that must NOT inherit a
variable drops both spellings (`drop`, `names`).

    PREFIX / LEGACY            "GAMEANYTHING_" / "M2W_"
    adopt(env)                 env with every legacy name copied to the new one where that is missing (in place; -> env)
    get(name, default, env)    env[GAMEANYTHING_<name>], else env[M2W_<name>], else default (for an env dict built by hand)
    names(*names)              ("GAMEANYTHING_X", "M2W_X", ...): both spellings, for drop lists and filters
    drop(env, *names)          remove both spellings from env (in place; -> env)
    legacy_pin(var)            a pin variable as a game package declares it -> (new, old) spellings
"""
import os

PREFIX = "GAMEANYTHING_"
LEGACY = "M2W_"

# Not adopted: the lab's own settings (gamebench's names; lab.env files and the lab tools use M2W_LAB_*, M2W_LEASES, M2W_LEASE_MIRROR).
# They keep their names everywhere, so copying them would only add a second spelling nobody reads.
_LAB_ONLY = ("M2W_LAB_", "M2W_LEASES", "M2W_LEASE_MIRROR")


def _new(old: str) -> str:
    return PREFIX + old[len(LEGACY):]


def adopt(env=None):
    env = os.environ if env is None else env
    for k in [k for k in env if k.startswith(LEGACY) and not k.startswith(_LAB_ONLY)]:
        n = _new(k)
        if n not in env: env[n] = env[k]
    return env


def get(name: str, default=None, env=None):
    env = os.environ if env is None else env
    if PREFIX + name in env: return env[PREFIX + name]
    return env.get(LEGACY + name, default)


def names(*names) -> tuple:
    return tuple(p + n for n in names for p in (PREFIX, LEGACY))


def drop(env, *names_):
    for k in names(*names_): env.pop(k, None)
    return env


def legacy_pin(var: str) -> tuple:
    """A game package's pin_var in either spelling -> (GAMEANYTHING_..., M2W_...); any other name -> (var, var)."""
    if var.startswith(LEGACY): return _new(var), var
    if var.startswith(PREFIX): return var, LEGACY + var[len(PREFIX):]
    return var, var
