"""`gameanything isolation ...` (docs/agent-isolation.md): set a computer up for agents under their own OS accounts, or undo it.

    gameanything isolation status                       the switch, the accounts, the gate
    gameanything isolation migrate [--json]             DRY RUN (the default): every account, ACL, owner and mode it would change
    gameanything isolation migrate --apply --journal F  do it; F gets the old state of everything it changed (keep it for the rollback)
              [--enable]                                also write settings.yaml agent_users: on (otherwise isolation stays off)
              [--copy-logins]                           copy the operator's Claude login into the single-user account (else: log in)
    gameanything isolation rollback --journal F [--apply]   put everything back the way F says (dry run without --apply)

Nothing here moves a project. The service account keeps every file it had; the agent accounts get traverse-only ACL entries on the way to
the code, the venv, the agent CLIs and their own projects, and an explicit "nothing" entry on everything world-readable next to that way.
"""
import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import isolation as I, osdirs

UID_BASE = 39100
ACCOUNTS_FILE = "agent-accounts.json"
SECRETISH = ("hub_secret", "users.yaml", ".env", "credentials", "oauth", "auth.json", "token", "secret", "id_rsa", "id_ed25519", "Cookies",
             "Login Data")


# ---------------------------------------------------------------- what exists
def _users():
    from . import users
    if not users.enabled(): return {}
    try: return users.load_users()
    except Exception: return {}


def wanted_accounts() -> dict:
    """{account: {"owner", "uid"}}: one per hub user, else ga-agent. uids are stable (agent-accounts.json in the server folder)."""
    from . import decisions
    f = decisions.keys_dir() / ACCOUNTS_FILE
    try: known = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError): known = {}
    U = _users(); names = sorted(U) if U else [None]
    out = {}; used = set(known.values()) | {uid for _, uid, _ in osdirs.accounts()}
    for n in names:
        a = I.account_name(n)
        uid = known.get(a) or (I.ids(a) or (None,))[0]
        if uid is None:
            uid = UID_BASE
            while uid in used: uid += 1
        used.add(uid); out[a] = {"owner": n, "uid": uid}
    return out


CODE = None                                    # --code: the checkout the agents run (default: this code's folder)


def _cli_paths() -> list:
    """The real files of the agent CLIs, Python and GameAnything itself (what an agent account must be able to read and run)."""
    out = set()
    for name in ("claude", "codex", "gemini", "opencode", "dsh", "node", "gameanything", "bash", "git", "rg"):
        w = shutil.which(name)
        if w:
            r = os.path.realpath(w); out |= {r, os.path.abspath(w)}      # the link agentd starts (…/bin/claude) and what it points at
            if Path(r).parent.name == "bin" and name in ("codex", "opencode"): out.add(str(Path(r).parents[1]))   # its install (resources)
    for v in ("GAMEANYTHING_CLAUDE", "GAMEANYTHING_CODEX", "GAMEANYTHING_GEMINI", "GAMEANYTHING_OPENCODE", "GAMEANYTHING_DSH"):
        if os.environ.get(v): out.add(os.path.realpath(os.environ[v]))
    for d in (os.environ.get("GAMEANYTHING_DSH"), shutil.which("dsh")):      # DeepSeek Harness: its whole node_modules (…/node_modules/@deepseek-ai/dsh/lib/bin.js)
        r = Path(os.path.realpath(d)) if d else None
        if r and len(r.parents) > 3 and r.parents[3].name == "node_modules": out.add(str(r.parents[3]))
    out |= {os.path.realpath(sys.executable), os.path.realpath(sys.prefix), os.path.realpath(sys.base_prefix),
            os.path.realpath(str(CODE or Path(__file__).resolve().parents[1]))}
    g = shutil.which("gemini")
    if g: out.add(str(Path(os.path.realpath(g)).parents[2]))       # node_modules/@google/gemini-cli
    n = shutil.which("node")
    if n: out.add(str(Path(os.path.realpath(n)).parents[1]))       # the node install (lib/node_modules)
    c = shutil.which("claude")
    if c: out.add(os.path.realpath(c))
    return sorted(out)


def _projects():
    from . import projects
    return [e for e in projects.load() if e.get("path")]


def _world(st) -> bool:
    """Others could reach it (a directory others may enter, a file others may read)."""
    return bool(st.st_mode & (0o001 if stat.S_ISDIR(st.st_mode) else 0o004))


def _traversable(st) -> bool: return bool(st.st_mode & 0o001)


# ---------------------------------------------------------------- the plan
def plan(accounts=None) -> dict:
    """Everything `migrate --apply` would do, as data (read only)."""
    from . import decisions
    accounts = accounts or wanted_accounts()
    ag_gid = I.group_gid()
    P = {"accounts": [], "dirs": [], "acl": [], "projects": [], "logins": [], "warnings": [], "settings": {}}
    for a, v in accounts.items():
        P["accounts"].append({"account": a, "owner": v["owner"], "uid": v["uid"], "exists": I.ids(a) is not None})
    root = I.agent_root()
    P["dirs"] = [(str(root), "root", 0o755), (str(I.public_dir()), "root", 0o755), (str(I.gate_path().parent), f"root:{I.GROUP}", 0o750),
                 (str(root / "homes"), "root", 0o711)] + [(str(I.home_of(a)), a, 0o700) for a in accounts]
    # who needs which path: shared (every agent account) and per account
    allow = {}                                    # path -> set of principals ("*" = ga-agents, else an account)
    for p in _cli_paths(): allow.setdefault(p, set()).add("*")
    allow.setdefault(str(I.agent_root()), set()).add("*")
    U = _users()
    for e in _projects():
        owner = (e.get("owner") or _owner_of(e["path"])) if U else None
        a = I.account_name(owner) if (owner or not U) else None
        if not a: P["warnings"].append(f"project {e['id']}: no owner, no account (it will not run)"); continue
        allow.setdefault(os.path.realpath(e["path"]), set()).add(a)
        pr = _project_plan(e, a, accounts)
        P["projects"].append(pr)
    for n, u in U.items():
        a = I.account_name(n)
        for k in ("claude_config_dir", "codex_home", "gemini_home", "opencode_home"):
            d = u.get(k)
            if not d: continue
            d = os.path.realpath(os.path.expanduser(d))
            from . import users
            if k == "claude_config_dir" and users.is_default_config(d):
                P["logins"].append({"account": a, "what": k, "action": "log in once as the account (the default ~/.claude stays the operator's)"})
                continue
            P["logins"].append({"account": a, "what": k, "path": d, "action": f"chown -R {a}"})
            allow.setdefault(d, set()).add(a)
    if not U:
        P["logins"].append({"account": I.SINGLE, "what": "claude login", "action": "copy with --copy-logins, or log in once as the account"})
    P["acl"] = _acl_plan(allow)
    code = os.path.realpath(str(CODE or Path(__file__).resolve().parents[1]))
    if os.path.isdir(os.path.join(code, ".git")):                 # the agents run the code, they never need its git folder
        P["acl"].append({"path": os.path.join(code, ".git"), "who": "*", "perm": 0, "why": "the checkout's git folder"})
    P["parents"] = sorted({pr["path"].rsplit("/", 1)[0] for pr in P["projects"] if "the folder that holds it is not root-only writable" in pr["problems"]})
    # things that stay readable for the agents (secrets that would be reachable) and other checks
    from .buildmode import pool_path
    pp = pool_path()
    for f in ((pp.parent / "leases.json", pp) if pp else ()):
        try:
            if os.stat(f).st_mode & 0o002: P["warnings"].append(f"{f} is world-writable: an agent could edit the lab leases (chmod 644; lab via the gate)")
        except OSError: pass
    for s in ("/tmp/docker-rt.sock",):
        try:
            st = os.stat(s)
            if st.st_mode & 0o006: P["warnings"].append(f"{s} is world-accessible (an agent could drive every sandbox)")
        except OSError: pass
    if not _acl_ok(): P["warnings"].append("this file system does not keep POSIX ACLs: isolation cannot be set up here")
    code = Path(CODE or Path(__file__).resolve().parents[1])
    for q in list(code.glob("*")) + list(code.glob("*/*")):
        try: st = os.lstat(q)
        except OSError: continue
        if stat.S_ISREG(st.st_mode) and st.st_mode & 0o004 and any(k in q.name for k in SECRETISH):
            P["warnings"].append(f"{q} is world-readable and looks like a secret: the agents can read the code folder (chmod 600 or move it)")
    P["settings"] = {"agent_users": "on (only with --enable)", "agent_root": str(root)}
    P["seal"] = [e["id"] for e in _projects() if decisions.ledger(e["path"]).exists()]
    return P


def _owner_of(path):
    from . import users
    try: return users.owner_of(path)
    except Exception: return None


def _project_plan(e, account, accounts):
    root = Path(e["path"]); out = {"id": e["id"], "path": str(root), "account": account, "changes": 0, "protected": 0, "agent": 0,
                                   "parent": None, "problems": []}
    try: pst = os.stat(root.parent)
    except OSError as x: out["problems"].append(f"parent: {x.strerror}"); return out
    out["parent"] = f"{osdirs.account_name(pst.st_uid)}:{oct(pst.st_mode & 0o7777)}"
    if pst.st_uid != I.service_uid() or pst.st_mode & 0o022: out["problems"].append("the folder that holds it is not root-only writable")
    uid = accounts.get(account, {}).get("uid")
    svc = I.service_uid()
    for dp, dns, fns in os.walk(root, followlinks=False):
        for n in dns + fns:
            p = Path(dp) / n
            try: st = os.lstat(p)
            except OSError: continue
            if stat.S_ISLNK(st.st_mode):
                t = os.path.realpath(p)
                if not (t + os.sep).startswith(str(root.resolve()) + os.sep): out["problems"].append(f"link out of the project: {p.relative_to(root)} -> {t}")
                continue
            prot = p.relative_to(root).parts[0] in I.PROTECTED
            if prot: out["protected"] += 1; out["changes"] += st.st_uid != svc or bool(st.st_mode & 0o027)
            else: out["agent"] += 1; out["changes"] += st.st_uid != uid
    return out


def _acl_ok() -> bool:
    import tempfile
    try:
        base = I.agent_root().parent
        d = tempfile.mkdtemp(prefix=".ga-acl-probe-", dir=str(base) if base.is_dir() and os.access(base, os.W_OK) else None)
    except OSError: return False
    try:
        I.acl_set(d, {(I.GROUP_E, 0): 1}); return I.acl_read(d) is not None
    except OSError: return False
    finally: shutil.rmtree(d, ignore_errors=True)


def _acl_plan(allow: dict) -> list:
    """[{path, entry, perm, why}]: traverse entries on the way to every allowed path, and "nothing" for ga-agents on world-reachable
    neighbours of that way (inside a folder that was closed before: opening it must not open its other children)."""
    out = {}
    def add(p, who, perm, why):
        k = (p, who)
        if k in out and out[k]["perm"] >= perm: return
        out[k] = {"path": p, "who": who, "perm": perm, "why": why}
    on_way = {}                                   # dir -> {child name: set(principals)}
    opened = set()
    for target, whos in allow.items():
        parts = Path(target).parts
        closed_above = False
        for i in range(1, len(parts)):
            d = str(Path(*parts[:i])); child = parts[i]
            try: st = os.stat(d)
            except OSError: break
            if not _traversable(st) or closed_above:
                for w in whos:
                    if not _traversable(st): add(d, w, 1, f"traverse to {target}")
                closed_above = True; opened.add(d)
            on_way.setdefault(d, {}).setdefault(child, set()).update(whos)
        if not os.access(target, os.R_OK): continue
    def inside_shared(d):                         # a folder inside an allowed tree: its children are allowed too (no "nothing" there)
        return any(w == "*" and (d + os.sep).startswith(t.rstrip(os.sep) + os.sep) and os.path.isdir(t) for t, ws in allow.items() for w in ws)
    for d in sorted(opened):
        if inside_shared(d): continue
        try: names = os.listdir(d)
        except OSError: continue
        way = on_way.get(d, {})
        for n in names:
            p = os.path.join(d, n)
            try: st = os.lstat(p)
            except OSError: continue
            if stat.S_ISLNK(st.st_mode): continue
            whos = way.get(n)
            if p in allow and "*" not in allow[p]:      # an account's own folder (a project, its login): its owner / mode decide, no entry
                if _world(st): add(p, "*", 0, "another account's folder: nothing for the other agents")
                continue
            if whos is None:
                if _world(st): add(p, "*", 0, "next to the way: nothing for the agents")
            elif "*" not in whos:
                deny = _world(st)
                if deny: add(p, "*", 0, "another account's way: nothing for the other agents")
                for w in whos:                    # a named user entry comes before the group's "nothing"
                    if stat.S_ISDIR(st.st_mode) and (deny or not _traversable(st)): add(p, w, 1, "its own way")
    return sorted(out.values(), key=lambda x: (x["path"], x["who"]))


# ---------------------------------------------------------------- doing it
def _sbin(name):
    return shutil.which(name, path=os.environ.get("PATH", "") + ":/usr/sbin:/sbin:/usr/bin:/bin") or name


def _run(cmd, apply, log):
    cmd = [_sbin(cmd[0]), *cmd[1:]]
    log(("  run " if apply else "  would run ") + " ".join(cmd))
    if apply: subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)


def apply(P, journal_path, enable=False, copy_logins=False, log=print) -> dict:
    """Do what plan() says. Every change goes into the journal first (its old state), so rollback() can undo it."""
    from . import decisions, projects
    J = {"at": datetime.now().isoformat(timespec="seconds"), "created_users": [], "created_groups": [], "created_dirs": [], "paths": [],
         "acl": [], "projects": [], "settings": None}
    def save(): Path(journal_path).write_text(json.dumps(J, indent=1), encoding="utf-8"); os.chmod(journal_path, 0o600)
    save()
    if I.group_gid() is None:
        _run(["groupadd", "-g", str(UID_BASE - 1), I.GROUP], True, log); J["created_groups"].append(I.GROUP); save()
    for a in P["accounts"]:
        if a["exists"]: continue
        _run(["groupadd", "-g", str(a["uid"]), a["account"]], True, log); J["created_groups"].append(a["account"])
        _run(["useradd", "-M", "-u", str(a["uid"]), "-g", a["account"], "-G", I.GROUP, "-d", str(I.home_of(a["account"]) / "home"),
              "-s", "/usr/sbin/nologin", a["account"]], True, log)
        J["created_users"].append(a["account"]); save()
    known = {a["account"]: a["uid"] for a in P["accounts"]}
    kd = decisions.keys_dir(); kd.mkdir(parents=True, exist_ok=True)
    (kd / ACCOUNTS_FILE).write_text(json.dumps(known), encoding="utf-8")
    for d, owner, mode in P["dirs"]:
        p = Path(d)
        if not p.exists(): p.mkdir(parents=True); J["created_dirs"].append(d)
        else: J["paths"].append(_state(p))
        u, _, g = owner.partition(":")
        uid = I.ids(u)[0] if u != "root" else 0; gid = I.group_gid(g) if g else (I.ids(u)[1] if u != "root" else 0)
        os.chown(p, uid, gid); os.chmod(p, mode)
        if u != "root": (p / "home").mkdir(exist_ok=True); os.chown(p / "home", uid, gid); os.chmod(p / "home", 0o700)
    save()
    for d in P.get("parents") or []:              # the folder that holds projects: only the service account adds / renames them
        J["paths"].append(_state(Path(d))); os.chown(d, I.service_uid(), os.lstat(d).st_gid); os.chmod(d, os.lstat(d).st_mode & 0o7755)
        log(f"  {d}: no longer writable by others")
    for x in P["acl"]:
        who = x["who"]
        try:
            e = (I.GROUP_E, I.group_gid()) if who == "*" else (I.USER, I.ids(who)[0])
            J["acl"].append({"path": x["path"], "access": (I.acl_raw(x["path"], I.ACL_ACCESS) or b"").hex() or None})
            I.acl_set(x["path"], {e: x["perm"]})
        except (OSError, TypeError) as err: log(f"  ACL {x['path']}: {err}")
    save()
    for pr in P["projects"]:
        jr = []
        try: n = I.prepare_project(pr["path"], pr["account"], journal=jr)
        except OSError as err: log(f"  project {pr['id']}: {err}"); continue
        J["projects"].append({"id": pr["id"], "path": pr["path"], "changed": jr}); save()
        log(f"  project {pr['id']}: {n} paths -> {pr['account']} (conversation/ stays root)")
        try: decisions.write_server_id(pr["path"])
        except OSError: pass
    for lg in P["logins"]:
        if lg.get("path") and lg["action"].startswith("chown"):
            uid, gid = I.ids(lg["account"])
            for dp, dns, fns in os.walk(lg["path"]):
                for n in [dp] + [os.path.join(dp, f) for f in dns + fns]:
                    try:
                        st = os.lstat(n); J["paths"].append({"path": n, "uid": st.st_uid, "gid": st.st_gid, "mode": st.st_mode & 0o7777})
                        os.chown(n, uid, gid, follow_symlinks=False)
                    except OSError: pass
            save()
    if copy_logins and not _users():
        src = Path.home() / ".claude" / ".credentials.json"; dst = I.home_of(I.SINGLE) / "home" / ".claude" / ".credentials.json"
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, dst); uid, gid = I.ids(I.SINGLE)
            for p in (dst.parent, dst): os.chown(p, uid, gid)
            os.chmod(dst, 0o600); log("  copied the Claude login into ga-agent's config (not printed)")
    for e in projects.load():
        if decisions.ledger(e["path"]).exists():
            try: decisions.seal(e["path"])
            except OSError: pass
    if enable:
        f = projects.home() / "settings.yaml"
        J["settings"] = f.read_text(encoding="utf-8") if f.exists() else ""
        import yaml
        d = yaml.safe_load(J["settings"] or "") or {}
        d.update(agent_users="on", agent_root=str(I.agent_root()))
        f.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
    save()
    return J


def _state(p):
    st = os.lstat(p)
    return {"path": str(p), "uid": st.st_uid, "gid": st.st_gid, "mode": st.st_mode & 0o7777}


def rollback(journal_path, do=False, log=print) -> int:
    J = json.loads(Path(journal_path).read_text(encoding="utf-8")); n = 0
    def act(msg, fn):
        nonlocal n
        n += 1; log(("  " if do else "  would ") + msg)
        if do:
            try: fn()
            except OSError as e: log(f"    failed: {e}")
    if J.get("settings") is not None:
        from . import projects
        f = projects.home() / "settings.yaml"
        act(f"restore {f}", lambda: f.write_text(J["settings"], encoding="utf-8"))
    for pr in reversed(J.get("projects") or []):
        for c in reversed(pr["changed"]):
            def fix(c=c):
                os.chown(c["path"], c["uid"], c["gid"], follow_symlinks=False); os.chmod(c["path"], c["mode"])
                I.acl_restore(c["path"], I.ACL_DEFAULT, bytes.fromhex(c["acl_default"]) if c.get("acl_default") else None)
            act(f"owner/mode back: {c['path']}", fix)
    for c in reversed(J.get("acl") or []):
        act(f"ACL back: {c['path']}", lambda c=c: I.acl_restore(c["path"], I.ACL_ACCESS, bytes.fromhex(c["access"]) if c.get("access") else None))
    for c in reversed(J.get("paths") or []):
        act(f"owner/mode back: {c['path']}", lambda c=c: (os.chown(c["path"], c["uid"], c["gid"], follow_symlinks=False), os.chmod(c["path"], c["mode"])))
    for u in reversed(J.get("created_users") or []):
        act(f"userdel {u}", lambda u=u: subprocess.run([_sbin("userdel"), u], check=False))
    for g in reversed(J.get("created_groups") or []):
        act(f"groupdel {g}", lambda g=g: subprocess.run([_sbin("groupdel"), g], check=False, stderr=subprocess.DEVNULL))
    for d in reversed(J.get("created_dirs") or []):
        act(f"remove {d} (agent homes with logins are kept unless empty)", lambda d=d: _rmdir_if_empty(d))
    return n


def _rmdir_if_empty(d):
    p = Path(d)
    for q in sorted(p.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        if q.is_dir() and not any(q.iterdir()): q.rmdir()
    if p.is_dir() and not any(p.iterdir()): p.rmdir()


# ---------------------------------------------------------------- the report
def text(P) -> list:
    L = ["Agent accounts:"]
    for a in P["accounts"]: L.append(f"  {a['account']:<14} uid {a['uid']:<6} owner {a['owner'] or '(single user)'}  {'exists' if a['exists'] else 'NEW'}")
    L.append(f"Group {I.GROUP} ({'exists' if I.group_gid() is not None else 'NEW'}); folders:")
    for d, o, m in P["dirs"]: L.append(f"  {d}  {o} {oct(m)}")
    L.append(f"ACL entries ({len(P['acl'])}; every one with --json): traverse-only on the way, nothing for the agents next to it")
    by = {}
    for x in P["acl"]:
        if x["perm"] == 1: L.append(f"  {x['path']}  {'g:' + I.GROUP if x['who'] == '*' else 'u:' + x['who']}:--x   ({x['why']})")
        else: by.setdefault(os.path.dirname(x["path"]), []).append(os.path.basename(x["path"]))
    for d, ns in sorted(by.items()):
        L.append(f"  in {d}: g:{I.GROUP}:--- on {len(ns)}: {', '.join(repr(n) if not n.isprintable() or not n else n for n in sorted(ns)[:12])}"
                 + (" …" if len(ns) > 12 else ""))
    L.append("Projects (never moved):")
    for pr in P["projects"]:
        L.append(f"  {pr['id']:<22} -> {pr['account']:<12} {pr['agent']} files to the account, {pr['protected']} in conversation/ stay root; "
                 f"{pr['changes']} change; parent {pr['parent']}" + ("".join(f"\n      ! {x}" for x in pr["problems"][:5])))
    for d in P.get("parents") or []: L.append(f"  chmod go-w {d} (the folder that holds the projects)")
    L.append("Provider logins:")
    for lg in P["logins"]: L.append(f"  {lg['account']}: {lg['what']} {lg.get('path', '')}  -> {lg['action']}")
    L.append(f"Ledgers sealed (head + where signed answers start): {', '.join(P['seal']) or 'none'}")
    for w in P["warnings"]: L.append(f"WARNING: {w}")
    L.append(f"Settings: {P['settings']}")
    return L


def main(argv) -> int:
    ap = argparse.ArgumentParser(prog="gameanything isolation")
    ap.add_argument("what", choices=["status", "migrate", "rollback"])
    ap.add_argument("--apply", action="store_true"); ap.add_argument("--journal", type=Path, default=None)
    ap.add_argument("--enable", action="store_true"); ap.add_argument("--copy-logins", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--code", type=Path, default=None, help="the GameAnything checkout the agents run (default: this one)")
    a = ap.parse_args(argv)
    global CODE
    CODE = a.code
    if a.what == "status": print(json.dumps(I.status(), indent=1)); return 0
    if os.name == "nt": sys.exit("[isolation] Linux / macOS only")
    if a.what == "rollback":
        if not a.journal: sys.exit("[isolation] rollback needs --journal")
        n = rollback(a.journal, a.apply); print(f"[isolation] {'undid' if a.apply else 'would undo'} {n} changes"); return 0
    P = plan()
    if a.json: print(json.dumps(P, indent=1, default=str))
    else: print("\n".join(text(P)))
    if not a.apply: print("[isolation] dry run: nothing was changed (add --apply --journal FILE)"); return 0
    if os.geteuid() != 0: sys.exit("[isolation] --apply needs the service account (root)")
    if not a.journal: sys.exit("[isolation] --apply needs --journal FILE (the rollback reads it)")
    apply(P, a.journal, a.enable, a.copy_logins)
    print(f"[isolation] done; journal {a.journal}" + ("" if a.enable else " (isolation is still OFF: --enable, or agent_users: on)"))
    return 0
