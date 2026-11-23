"""Agents under their own OS accounts (docs/agent-isolation.md). OFF unless GAMEANYTHING_AGENT_USERS=on (or settings.yaml `agent_users: on`).

While the page server, agentd and the agents all ran as one OS user, every software guard could be walked around (QA 2026-10-30: an agent
signed her decisions by calling the server's own code, faked a browser header to get the decision cookie, read hub_secret, appended card
answers to thread.jsonl, edited the config to drop strictness, rolled the ledger back). With isolation on the kernel draws the line:

    service account (root here)   the UI / hub server, agentd, the gate; owns conversation/, the ledger, the keys, users.yaml, hub_secret
    agent accounts                one per hub user (ga-<user>), or ga-agent on a single-user install; every agent CLI run (resident,
                                  builder, critic; claude-code, codex, gemini, opencode) runs as the project owner's account

    <project>/                    root:<account group> 3770 (setgid + sticky: the agent adds files, cannot rename / remove root's)
    <project>/conversation/       root:<account group> 2750, files 0640: the agent reads, never writes (writes go through the gate)
    <project>/<everything else>   <account>:<account group>, default ACL group rwx (what the server writes there stays the agent's to edit)
    <agent root>/homes/<account>  the account's HOME, TMPDIR, provider logins (0700, its own)
    <agent root>/public/          root 0755: the public half of the decision keys, the strict list, the ledger heads (agents verify)
    <agent root>/gate/agent.sock  root:ga-agents 0660: the only way an agent run writes conversation/ (gate.py)

The server never follows a link the agent planted: install_guard() makes every open / rename / unlink / mkdir under an agent tree walk the
path with O_NOFOLLOW from the project folder (a link that stays inside the project is followed, one that leaves it is refused).
"""
import errno
import io
import json
import os
import re
import stat
import struct
import threading
import time
from pathlib import Path

ENV = "GAMEANYTHING_AGENT_USERS"
PREFIX = "ga-"
SINGLE = "ga-agent"
GROUP = "ga-agents"
ROOT_ENV = "GAMEANYTHING_AGENT_ROOT"
DEFAULT_ROOT = "/var/lib/gameanything-agents"
GATE_ENV = "GAMEANYTHING_GATE"
FORWARDED_ENV = "GAMEANYTHING_GATE_FORWARDED"
PROTECTED = ("conversation",)               # project subfolders only the service account writes
SAFE = re.compile(r"[^a-z0-9_-]+")


class IsolationError(PermissionError):
    pass


# ---------------------------------------------------------------- the switch
def _settings() -> dict:
    try:
        import yaml
        from . import projects
        d = yaml.safe_load((projects.home() / "settings.yaml").read_text(encoding="utf-8")) or {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _on(v) -> bool: return str(v).strip().lower() in ("1", "on", "true", "yes")


def enabled() -> bool:
    """GAMEANYTHING_AGENT_USERS=on|off wins; else settings.yaml `agent_users`. Default off. Always off on Windows: no service account, no
    agent accounts (half of it on there would sign but trust the agent's own config, e.g. its `id:`; docs/agent-isolation.md)."""
    if os.name == "nt": return False
    v = os.environ.get(ENV)
    if v is not None and v.strip(): return _on(v)
    return _on(_settings().get("agent_users", "off"))


def service_uid() -> int:
    try: return int(os.environ.get("GAMEANYTHING_SERVICE_UID", "0"))
    except ValueError: return 0


def is_service() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == service_uid()


def client_mode() -> bool:
    """This process is an isolated agent's command: isolation on and not the service account."""
    return hasattr(os, "geteuid") and enabled() and not is_service()


def forwarded() -> bool:
    """This process is a command the gate runs for an agent (as the service account)."""
    return os.environ.get(FORWARDED_ENV) == "1"


# ---------------------------------------------------------------- where things are
def agent_root() -> Path:
    v = os.environ.get(ROOT_ENV) or _settings().get("agent_root")
    return Path(v or DEFAULT_ROOT)


def public_dir() -> Path: return agent_root() / "public"
def gate_path() -> Path: return Path(os.environ.get("GAMEANYTHING_GATE_SOCKET") or agent_root() / "gate" / "agent.sock")
def home_of(account) -> Path: return agent_root() / "homes" / account


def safe_name(owner) -> str:
    return SAFE.sub("-", str(owner).lower()).strip("-")[:24] or "x"


def account_name(owner=None) -> str:
    """The OS account of a hub user's agents (ga-<user>), or of every agent on a single-user install (ga-agent)."""
    return PREFIX + safe_name(owner) if owner else SINGLE


def account_for(root) -> str:
    from . import users
    if users.enabled():
        o = users.owner_of(root)
        return account_name(o) if o else None
    return SINGLE


def ids(account):
    """-> (uid, gid) of an account, or None when it does not exist on this computer."""
    from . import osdirs
    return osdirs.account(account) if account else None


def group_gid(name=None):
    from . import osdirs
    g = osdirs.group(name or GROUP); return g[0] if g else None


def agent_uids() -> set:
    """The uids of every agent account (members of ga-agents, and every ga-* user)."""
    from . import osdirs
    out = set(); g = osdirs.group(GROUP)
    for name, uid, gid in osdirs.accounts():
        if name.startswith(PREFIX) or (g and (name in g[1] or gid == g[0])): out.add(uid)
    out.discard(service_uid())
    return out


def account_of_uid(uid):
    from . import osdirs
    n = osdirs.account_name(uid)
    return n if n and n.startswith(PREFIX) else None


# ---------------------------------------------------------------- POSIX ACLs (as xattrs: no setfacl needed)
USER_OBJ, USER, GROUP_OBJ, GROUP_E, MASK, OTHER = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20
ACL_ACCESS, ACL_DEFAULT = "system.posix_acl_access", "system.posix_acl_default"
_NOID = 0xFFFFFFFF


def acl_read(path, kind=ACL_ACCESS, follow=False):
    """-> {(tag, id): perm} or None (no ACL)."""
    try: raw = os.getxattr(path, kind, follow_symlinks=follow)
    except OSError: return None
    out = {}
    for i in range(4, len(raw), 8):
        tag, perm, id_ = struct.unpack("<HHI", raw[i:i + 8]); out[(tag, id_)] = perm
    return out


def _acl_from_mode(mode) -> dict:
    return {(USER_OBJ, _NOID): (mode >> 6) & 7, (GROUP_OBJ, _NOID): (mode >> 3) & 7, (OTHER, _NOID): mode & 7}


def _acl_bytes(acl: dict) -> bytes:
    a = dict(acl)
    if any(t in (USER, GROUP_E) for t, _ in a):
        if (MASK, _NOID) not in a:
            m = 0
            for (t, _), p in a.items():
                if t in (USER, GROUP_E, GROUP_OBJ): m |= p
            a[(MASK, _NOID)] = m
    else: a.pop((MASK, _NOID), None)
    return struct.pack("<I", 2) + b"".join(struct.pack("<HHI", t, p, i) for (t, i), p in sorted(a.items()))


def acl_set(path, entries: dict, kind=ACL_ACCESS):
    """Add / replace named entries {(USER|GROUP_E, id): perm} on the path's ACL (from its mode when it has none); the mask is recomputed."""
    st = os.lstat(path)
    cur = acl_read(path, kind) or (_acl_from_mode(st.st_mode) if kind == ACL_ACCESS else
                                   {(USER_OBJ, _NOID): 7, (GROUP_OBJ, _NOID): (st.st_mode >> 3) & 7, (OTHER, _NOID): st.st_mode & 7})
    cur.pop((MASK, _NOID), None); cur.update(entries)
    os.setxattr(path, kind, _acl_bytes(cur), follow_symlinks=False)


def acl_raw(path, kind):
    try: return os.getxattr(path, kind, follow_symlinks=False)
    except OSError: return None


def acl_restore(path, kind, raw):
    if raw is None:
        try: os.removexattr(path, kind, follow_symlinks=False)
        except OSError: pass
    else: os.setxattr(path, kind, raw, follow_symlinks=False)


# ---------------------------------------------------------------- the project layout under isolation
def layout_problems(root, account=None) -> list:
    """Why the project is not (or no longer) in the isolated layout: [] when it is. Cheap (a few lstat calls): agentd checks before every run."""
    root = Path(root); account = account or account_for(root); out = []
    if not account: return ["no owner"]
    i = ids(account)
    if not i: return [f"the account {account} does not exist"]
    uid, gid = i; svc = service_uid()
    try: st = os.lstat(root)
    except OSError as e: return [f"{root}: {e.strerror}"]
    if stat.S_ISLNK(st.st_mode): return [f"{root} is a link"]
    if st.st_uid != svc or st.st_gid != gid or (st.st_mode & 0o7777) != 0o3770: out.append(f"{root.name}/ is not root:{account} 3770")
    for p in PROTECTED:
        try: s = os.lstat(root / p)
        except OSError: out.append(f"{p}/ is missing"); continue
        if not stat.S_ISDIR(s.st_mode) or s.st_uid != svc or s.st_mode & 0o022: out.append(f"{p}/ is not the service account's")
    for f in ("thread.jsonl", ".user_decisions.jsonl"):
        try: s = os.lstat(root / "conversation" / f)
        except FileNotFoundError: continue
        except OSError: out.append(f"conversation/{f} unreadable"); continue
        if not stat.S_ISREG(s.st_mode) or s.st_uid != svc or s.st_nlink != 1: out.append(f"conversation/{f} is not the service account's")
    return out


def trusted(path) -> bool:
    """With isolation on: the file is the service account's (a regular file, one link). Off: always True."""
    if not enabled(): return True
    try: s = os.lstat(path)
    except FileNotFoundError: return True
    except OSError: return False
    return stat.S_ISREG(s.st_mode) and s.st_uid == service_uid() and s.st_nlink == 1


def plan_project(root, account) -> list:
    """[(path, uid, gid, mode, default_acl_gid or None)] that make `root` the isolated layout (the migration's dry run lists them)."""
    root = Path(root); i = ids(account)
    if not i: raise IsolationError(f"the account {account} does not exist (run the migration first)")
    uid, gid = i; svc = service_uid(); out = [(root, svc, gid, 0o3770, None)]
    for dp, dns, fns in os.walk(root, followlinks=False):
        d = Path(dp)
        for n in list(dns) + fns:
            p = d / n
            try: st = os.lstat(p)
            except OSError: continue
            if stat.S_ISLNK(st.st_mode): continue
            prot = p.relative_to(root).parts[0] in PROTECTED
            isdir = stat.S_ISDIR(st.st_mode)
            if prot: out.append((p, svc, gid, (0o2750 if isdir else 0o640), None))
            else: out.append((p, uid, gid, ((st.st_mode & 0o770) | 0o2770) if isdir else ((st.st_mode & 0o770) | 0o660),
                              gid if isdir else None))
    return out


def prepare_project(root, account=None, journal=None) -> int:
    """(The service account) put the project in the isolated layout; -> how many paths changed. journal: a list that gets the old state of
    each changed path (the migration writes it, its rollback reads it)."""
    root = Path(root); account = account or account_for(root)
    if not account: raise IsolationError("the project has no owner")
    for p in PROTECTED: (root / p).mkdir(exist_ok=True)
    for f in ("thread.jsonl", ".user_decisions.jsonl"):     # the server's files exist from the start: an agent can never create them first
        q = root / "conversation" / f
        if not q.exists(): q.touch()
    n = 0
    for p, uid, gid, mode, dacl in plan_project(root, account):
        st = os.lstat(p); change = (st.st_uid, st.st_gid) != (uid, gid) or (st.st_mode & 0o7777) != mode
        old_dacl = acl_raw(p, ACL_DEFAULT) if dacl is not None else None
        want_dacl = None
        if dacl is not None:
            want_dacl = _acl_bytes({(USER_OBJ, _NOID): 7, (GROUP_OBJ, _NOID): 7, (OTHER, _NOID): 0, (GROUP_E, dacl): 7})
            change = change or old_dacl != want_dacl
        if not change: continue
        if journal is not None:
            journal.append({"path": str(p), "uid": st.st_uid, "gid": st.st_gid, "mode": st.st_mode & 0o7777,
                            "acl_default": old_dacl.hex() if old_dacl else None})
        os.chown(p, uid, gid, follow_symlinks=False); os.chmod(p, mode)
        if want_dacl is not None:
            try: os.setxattr(p, ACL_DEFAULT, want_dacl, follow_symlinks=False)
            except OSError: pass
        n += 1
    invalidate()
    return n


def ensure_project(root, account=None) -> list:
    """agentd before a run: [] when the layout is right (preparing it once when the folder is still the old one-user layout); else why not.
    A project another account already owns (the agent changed config/project.yaml `owner:`) is never handed over."""
    root = Path(root); account = account or account_for(root)
    if not account: return ["no owner"]
    if not ids(account): return [f"the account {account} does not exist (run the migration: tools/agent_isolation_migrate.py)"]
    probs = layout_problems(root, account)
    if not probs: return []
    try: st = os.lstat(root)
    except OSError as e: return [str(e)]
    from . import osdirs
    owner_acct = osdirs.group_name(st.st_gid)
    if st.st_uid == service_uid() and owner_acct and owner_acct.startswith(PREFIX) and owner_acct != account:
        return [f"the folder belongs to {owner_acct}, the config says {account}: an admin must move it (the migration's --owner)"]
    try: prepare_project(root, account)
    except OSError as e: return [f"could not prepare the folder ({e.strerror})"]
    return layout_problems(root, account)


# ---------------------------------------------------------------- a run as the account
def run_env(root, env: dict, run_id: str, account=None, tmp=None) -> tuple:
    """-> (env, run_as) for an agent run as the project's account: its own HOME / TMPDIR / provider homes, the gate's socket, the public keys,
    no service paths. tmp: the run's own temp folder (agent_providers.run_tmpdir), handed to the account. run_as = {"uid", "gid", "groups",
    "account", "home", "tmp"} for spawn(); raises IsolationError when the run must not start (the account or the layout is not there)."""
    account = account or account_for(root)
    probs = ensure_project(root, account)
    if probs: raise IsolationError("; ".join(probs))
    uid, gid = ids(account); ag = group_gid()
    h = home_of(account); home = h / "home"
    for d in (h, home):
        d.mkdir(parents=True, exist_ok=True); os.chown(d, uid, gid); os.chmod(d, 0o700)
    if tmp is None: tmp = home / "tmp" / f"run-{run_id}"; tmp.mkdir(parents=True, exist_ok=True)
    tmp = Path(tmp)
    try: os.chmod(tmp.parent, 0o711)                         # the runs' base: every account passes through, none lists it
    except OSError: pass
    os.chown(tmp, uid, gid); os.chmod(tmp, 0o700)
    try:
        from . import decisions
        decisions.write_server_id(root)
    except OSError: pass
    env = dict(env)
    for k in list(env):
        if k.startswith(("GAMEANYTHING_DECISION_KEYS", "GAMEANYTHING_HUB_HOME", "GAMEANYTHING_KEYS_FILE", "GAMEANYTHING_USER_ENV_FILE",
                         "XDG_", "SSH_", "DBUS_")): env.pop(k)
    env.update(HOME=str(home), USER=account, LOGNAME=account, TMPDIR=str(tmp), TMP=str(tmp), TEMP=str(tmp), GAMEANYTHING_RUN_TMP=str(tmp),
               GAMEANYTHING_HOME=str(home / ".config" / "gameanything"), GAMEANYTHING_DECISION_KEYS=str(public_dir()),
               GAMEANYTHING_GATE_SOCKET=str(gate_path()), GAMEANYTHING_AGENT_ACCOUNT=account, **{ENV: "on"},
               GAMEANYTHING_SERVICE_UID=str(service_uid()), GAMEANYTHING_AGENT_ROOT=str(agent_root()))
    env[GATE_ENV] = "1"
    # the provider logins: the hub user's own dirs (users.yaml, the migration hands them to the account) or the account's home
    for var, sub in (("CLAUDE_CONFIG_DIR", ".claude"), ("CODEX_HOME", ".codex"), ("GAMEANYTHING_GEMINI_HOME", "gemini-home"),
                     ("GAMEANYTHING_OPENCODE_HOME", "opencode-home"), ("GAMEANYTHING_DSH_HOME", "dsh-home")):
        v = env.get(var)
        if v and _owned_by(v, uid): continue
        env[var] = str(home / sub)
        (home / sub).mkdir(parents=True, exist_ok=True); os.chown(home / sub, uid, gid)
    groups = [gid] + ([ag] if ag is not None else [])
    return env, {"uid": uid, "gid": gid, "groups": groups, "account": account, "tmp": str(tmp), "home": str(home)}


def _owned_by(p, uid) -> bool:
    try: return os.stat(p).st_uid == uid
    except OSError: return False


def after_launch(env: dict, run_as: dict):
    """The provider wrote its per-run files (Gemini's settings and policy, OpenCode's config, DeepSeek Harness's patch and key file) as the
    service account: hand them over."""
    uid, gid = run_as["uid"], run_as["gid"]; home = Path(run_as["home"])
    for var in ("GEMINI_CLI_HOME", "GAMEANYTHING_GEMINI_HOME", "GAMEANYTHING_OPENCODE_HOME", "GAMEANYTHING_DSH_HOME", "OPENCODE_CONFIG_DIR", "XDG_CONFIG_HOME",
                "TMPDIR", "OPENCODE_CONFIG"):
        v = env.get(var)
        if not v: continue
        p = Path(v)
        try: p.relative_to(home)
        except ValueError: continue                     # only inside the account's own home
        for q in [p] + (list(p.rglob("*"))[:5000] if p.is_dir() else []):
            try:
                if os.lstat(q).st_uid != uid: os.chown(q, uid, gid, follow_symlinks=False)
            except OSError: pass


def spawn_kwargs(run_as) -> dict:
    """subprocess.Popen arguments that start the run as the account (never with the service account's groups)."""
    if not run_as: return {}
    return {"user": run_as["uid"], "group": run_as["gid"], "extra_groups": run_as["groups"], "umask": 0o007}


def run_as_for(root):
    """genrun: the account a project's own scripts run as (None with isolation off)."""
    if not enabled(): return None
    a = account_for(root); i = ids(a) if a else None
    if not i: raise IsolationError(f"no account for {root}")
    ag = group_gid()
    return {"uid": i[0], "gid": i[1], "groups": [i[1]] + ([ag] if ag is not None else []), "account": a, "home": str(home_of(a) / "home")}


# ---------------------------------------------------------------- who is on the other end of a local TCP connection (the page)
def _proc_net_uid(cip, cport, sport):
    def hexaddr(ip):
        import ipaddress
        a = ipaddress.ip_address(ip)
        if a.version == 4: return "%08X" % struct.unpack("<I", a.packed)[0]
        return "".join("%08X" % struct.unpack("<I", a.packed[i:i + 4])[0] for i in range(0, 16, 4))
    want = {f"{hexaddr(cip)}:{cport:04X}"}
    if ":" not in cip:
        import ipaddress
        want.add(f"{hexaddr('::ffff:' + cip)}:{cport:04X}")
    for f in ("/proc/net/tcp", "/proc/net/tcp6"):
        try: lines = open(f, encoding="ascii").read().splitlines()[1:]
        except OSError: continue
        for ln in lines:
            p = ln.split()
            if len(p) > 7 and p[1] in want and p[2].endswith(f":{sport:04X}"): return int(p[7])
    return None


def peer_is_agent(client_address, server_port) -> bool:
    """With isolation on: the page's TCP client is a process of an agent account (Linux /proc/net/tcp). Off, or unknown: False."""
    if not enabled(): return False
    try:
        uid = _proc_net_uid(client_address[0], int(client_address[1]), int(server_port))
    except Exception: return False
    return uid is not None and uid in agent_uids()


# ---------------------------------------------------------------- the server never follows a link an agent planted
_trees = ()
_trees_at = 0.0
_tl = threading.local()
_orig = {}


def invalidate():
    global _trees_at
    _trees_at = 0.0


def _load_trees():
    """The folders an agent account can write: the registered projects in the isolated layout and the agent homes."""
    out = set()
    try:
        from . import projects
        for e in projects.load():
            p = os.path.abspath(str(e.get("path") or ""))
            try: s = os.lstat(p)
            except OSError: continue
            if stat.S_ISDIR(s.st_mode) and s.st_mode & 0o1000: out.add(p)          # the sticky bit: prepared
    except Exception: pass
    out.add(os.path.abspath(str(agent_root() / "homes")))
    return tuple(sorted(out, key=len, reverse=True))


def _tree_of(path):
    global _trees, _trees_at
    if getattr(_tl, "busy", False): return None
    if time.time() - _trees_at > 5:
        _tl.busy = True
        try: _trees = _load_trees(); _trees_at = time.time()
        finally: _tl.busy = False
    try: p = os.path.abspath(os.fsdecode(path))
    except (TypeError, ValueError): return None
    for t in _trees:
        if p.startswith(t + os.sep): return t, p
    return None


_O_PATH = getattr(os, "O_PATH", 0)


def _walk(tree, path, hops=0):
    """-> (dir_fd, last name) of `path` under `tree`, every folder opened with O_NOFOLLOW; a link inside the tree is followed (lexically),
    one that leaves it raises IsolationError."""
    if hops > 8: raise IsolationError(f"too many links: {path}")
    rel = os.path.relpath(path, tree).split(os.sep)
    fd = _orig["os.open"](tree, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _O_PATH)
    try:
        for i, comp in enumerate(rel[:-1]):
            if comp in ("", "."): continue
            if comp == "..": raise IsolationError(f"'..' under a project: {path}")
            try: nfd = _orig["os.open"](comp, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _O_PATH, dir_fd=fd)
            except OSError as e:
                if e.errno not in (errno.ELOOP, errno.ENOTDIR): raise
                try: tgt = os.readlink(comp, dir_fd=fd)
                except OSError: raise e
                here = os.path.join(tree, *rel[:i])
                new = os.path.normpath(os.path.join(here, tgt) if not os.path.isabs(tgt) else tgt)
                if not new.startswith(tree + os.sep) and new != tree: raise IsolationError(f"a link that leaves the project: {os.path.join(here, comp)}")
                os.close(fd)
                return _walk(tree, os.path.join(new, *rel[i + 1:]), hops + 1)
            os.close(fd); fd = nfd
        return fd, rel[-1]
    except BaseException:
        os.close(fd); raise


def _final_link(tree, fd, name, path, hops):
    """The last part is a link: follow it only when it stays in the tree. -> new path or raises."""
    try: tgt = os.readlink(name, dir_fd=fd)
    except OSError: return None
    here = os.path.dirname(path)
    new = os.path.normpath(os.path.join(here, tgt) if not os.path.isabs(tgt) else tgt)
    if not new.startswith(tree + os.sep): raise IsolationError(f"a link that leaves the project: {path}")
    if hops > 8: raise IsolationError(f"too many links: {path}")
    return new


def safe_os_open(path, flags, mode=0o777, *, dir_fd=None, _hops=0):
    t = _tree_of(path) if dir_fd is None else None
    if not t: return _orig["os.open"](path, flags, mode, dir_fd=dir_fd)
    tree, p = t
    fd, name = _walk(tree, p)
    try:
        try: return _orig["os.open"](name, flags | os.O_NOFOLLOW, mode, dir_fd=fd)
        except OSError as e:
            if e.errno != errno.ELOOP: raise
            new = _final_link(tree, fd, name, p, _hops)
            if not new: raise
    finally: os.close(fd)
    return safe_os_open(new, flags, mode, _hops=_hops + 1)


def _guarded_open(file, mode="r", buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None):
    if opener is None and isinstance(file, (str, bytes, os.PathLike)) and _tree_of(file):
        opener = lambda p, f: safe_os_open(p, f, 0o666)
    return _orig["open"](file, mode, buffering, encoding, errors, newline, closefd, opener)


def _two(fn_name):
    orig = _orig[fn_name]

    def f(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        a = _tree_of(src) if src_dir_fd is None else None; b = _tree_of(dst) if dst_dir_fd is None else None
        if not a and not b: return orig(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        fa = fb = None
        try:
            if a: fa, sn = _walk(*a)
            else: sn = src
            if b: fb, dn = _walk(*b)
            else: dn = dst
            return orig(sn, dn, src_dir_fd=fa if a else src_dir_fd, dst_dir_fd=fb if b else dst_dir_fd)
        finally:
            for x in (fa, fb):
                if x is not None: os.close(x)
    return f


def _one(fn_name, **fixed):
    orig = _orig[fn_name]

    def f(path, *args, dir_fd=None, **kw):
        t = _tree_of(path) if dir_fd is None else None
        if not t: return orig(path, *args, dir_fd=dir_fd, **kw)
        fd, name = _walk(*t)
        try: return orig(name, *args, dir_fd=fd, **{**kw, **fixed})
        finally: os.close(fd)
    return f


def _chmod(path, mode, *, dir_fd=None, follow_symlinks=True):
    t = _tree_of(path) if dir_fd is None and not isinstance(path, int) else None
    if not t: return _orig["os.chmod"](path, mode, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
    fd = safe_os_open(path, os.O_RDONLY | _O_PATH if _O_PATH else os.O_RDONLY)
    try:
        st = os.fstat(fd)
        if stat.S_ISLNK(st.st_mode): raise IsolationError(f"chmod of a link: {path}")
        return _orig["os.chmod"](f"/proc/self/fd/{fd}", mode)
    finally: os.close(fd)


def install_guard():
    """(Service processes with isolation on) open / os.open / rename / replace / unlink / remove / rmdir / mkdir / symlink / chmod under
    an agent tree never follow a link out of it. Idempotent."""
    import builtins
    if _orig: return False
    _orig.update({"open": builtins.open, "os.open": os.open, "os.rename": os.rename, "os.replace": os.replace, "os.unlink": os.unlink,
                  "os.remove": os.remove, "os.rmdir": os.rmdir, "os.mkdir": os.mkdir, "os.chmod": os.chmod})
    builtins.open = io.open = _guarded_open
    os.open = safe_os_open
    os.rename = _two("os.rename"); os.replace = _two("os.replace")
    os.unlink = _one("os.unlink"); os.remove = _one("os.remove"); os.rmdir = _one("os.rmdir"); os.mkdir = _one("os.mkdir")
    os.chmod = _chmod
    return True


def uninstall_guard():
    import builtins
    if not _orig: return
    builtins.open = io.open = _orig["open"]
    for k, v in _orig.items():
        if k.startswith("os."): setattr(os, k[3:], v)
    _orig.clear()


def server_init():
    """Called by the service processes (cli.main as the service account with isolation on)."""
    if enabled() and is_service() and hasattr(os, "O_NOFOLLOW"): install_guard()


def status() -> dict:
    """`gameanything isolation status`: the switch, the accounts and the gate (no secrets)."""
    out = {"enabled": enabled(), "agent_root": str(agent_root()), "gate": str(gate_path()), "gate_exists": gate_path().exists(),
           "group": GROUP, "group_exists": group_gid() is not None, "accounts": {}}
    from . import osdirs
    for name, uid, _ in osdirs.accounts():
        if name.startswith(PREFIX): out["accounts"][name] = uid
    return out
