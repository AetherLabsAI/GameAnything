"""Her decisions, as the server saw them: a confirmation counts only when she made it through the page (or the API behind it).

    <project>/conversation/.user_decisions.jsonl   one line per decision {what, state, at, via, by?, kid, sig}, appended by the UI server
    <home>/server/decision-keys.txt                 the public keys of the UI / hub servers (one per server start), written by the server
    <home>/server/strict-projects.txt               the ids of the projects under the ledger rule (also config/project.yaml `decisions: strict`)

QA 2026-10-29: an agent (OpenCode) wrote feedback/gameplay_review.yaml `mapping.state: confirmed` itself after she said she would click it
herself, and the flow went on. The review files (board_review.yaml, plan_review.yaml, adaptation_review.yaml, feature_review.yaml,
gameplay_review.yaml, the people tags) stay what they were, the agent reads them; but the flow treats one of them as HER decision only when
the ledger has a matching line the UI server signed when she clicked (`record`).

QA 2026-10-30 (three bypasses, all closed here):
  * deleting the ledger made a project "legacy" (files alone count): strictness is now kept in three places (the ledger, the project
    config, the server's strict list). A strict project without a ledger has NO confirmations and `flow check` calls it tampering.
  * `python -c "decisions.record(...)"` signed with a key in the data folder the agent could read: signing is Ed25519 (ed25519.py) with a
    private key that exists only in the memory of the running UI / hub server (`serve_signing()` at its start; a new key per start). Its
    public key goes to <home>/server/decision-keys.txt; verifying (`flow check`, agentd, the pages) needs only the public keys. `record`
    in any other process raises NotTheServer.
  * the signature covered Path(root).name: it covers the project id now (config/project.yaml `id`), so a copied / moved / restored
    project keeps her confirmations.
Residual risk (one OS user for her, the server and the agents): a process of hers can still append its own public key to
decision-keys.txt, or add a line to the ledger with a key it made. The agents' tools are denied those files and this module
(agent_providers.DENY_DECISIONS; Codex's sandbox cannot write outside the project at all), and every server start re-checks; full isolation
needs the agents to run as another OS user than the server (docs/agent-providers.md, "Her confirmations").

Projects from before the ledger (no .user_decisions.jsonl, not in the strict list, no `decisions: strict`) keep the old rule: the files
alone count. A project with a ledger is strict from the first time this code sees it (it joins the strict list).
What a decision is called (`what`):
    board                    「确认这一天」 (board_review.yaml state / board.yaml status)
    plan:<milestone>         「就按这个做」 on the 方案 page, or her approval on a plan card (flow.record_answer)
    scenes / characters      the 场景 page's two confirmations (adaptation_review.yaml state / state_characters)
    spec                     「确认需求」 (feature_review.yaml)
    gameplay:mapping / gameplay:content   「确认机制映射」 / 「确认内容」 (gameplay_review.yaml)
    people                   she saved the people page (tags.yaml / confirmed_by: user in people.yaml)
"""
import hashlib
import hmac
import json
import os
import threading
from datetime import datetime
from pathlib import Path

import yaml

from . import ed25519, layout

LEDGER = ".user_decisions.jsonl"
KEYRING = "decision-keys.txt"
STRICT_LIST = "strict-projects.txt"
LEGACY_PIN = "legacy-key.sha256"         # the old HMAC key the new code first saw (an agent's own decisions.key is not it)
HEADS = "ledger-heads.json"              # {project id: {n, h, answers_from}}: the last ledger line the server wrote, where signed answers start
SERVER_ID = ".server.json"
LEGACY_CLOSED = "legacy-closed"          # a new server started and signed the old lines again: old-style lines never count after it


class NotTheServer(PermissionError):
    """record() outside the UI / hub server: only the server that saw her click may sign her decision."""


def ledger(root) -> Path: return Path(root) / "conversation" / LEDGER


def keys_dir() -> Path:
    """The server's own folder (public keys, the strict list): $GAMEANYTHING_DECISION_KEYS, else <home>/server. Never in a project, the
    data folder (agent homes live there) or the temp folder."""
    v = os.environ.get("GAMEANYTHING_DECISION_KEYS")
    if v: return Path(v).expanduser()
    from . import projects
    return projects.home() / "server"


def _private_dir() -> Path:
    d = keys_dir(); d.mkdir(parents=True, exist_ok=True)
    try: os.chmod(d, 0o700)
    except OSError: pass
    return d


def _append_line(f: Path, line: str):
    _private_dir()
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh: fh.write(line.rstrip("\n") + "\n")


def _mirror(name):
    """(The service account, isolation on) the public half of the key folder, for the agents' own checks: <agent root>/public/<name>."""
    from . import isolation
    if not (isolation.enabled() and isolation.is_service()): return
    try:
        src = keys_dir() / name; dst = isolation.public_dir() / name
        if src.resolve() == dst.resolve(): return
        dst.parent.mkdir(parents=True, exist_ok=True)
        try: os.chmod(dst.parent, 0o755)
        except OSError: pass
        tmp = dst.with_name(dst.name + f".{os.getpid()}.tmp"); tmp.write_bytes(src.read_bytes()); os.chmod(tmp, 0o644); os.replace(tmp, dst)
    except OSError: pass


def _h(line: str) -> str: return hashlib.sha256(line.encode("utf-8")).hexdigest()[:32]


_heads_cache = {}
_heads_lock = threading.Lock()


def heads() -> dict:
    f = keys_dir() / HEADS
    try: st = f.stat(); k = (str(f), st.st_mtime_ns, st.st_size, st.st_ino)
    except OSError: return {}
    if k not in _heads_cache:
        try: d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError): d = {}
        _heads_cache.clear(); _heads_cache[k] = d if isinstance(d, dict) else {}
    return _heads_cache[k]


def _set_head(pid, **kv):
    """(The service account) update one project's head; written atomically, mirrored for the agents."""
    with _heads_lock:
        _private_dir(); f = keys_dir() / HEADS
        try: d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError): d = {}
        if not isinstance(d, dict): d = {}
        d[pid] = {**(d.get(pid) or {}), **kv}
        tmp = f.with_name(f".{HEADS}.{os.getpid()}.{threading.get_ident()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh: fh.write(json.dumps(d, ensure_ascii=False))
        os.replace(tmp, f)
    _mirror(HEADS)


def _raw(root) -> list:
    try: return [ln for ln in ledger(root).read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError: return []


def enforced() -> bool:
    """The kernel-backed rules (isolation on): ledger heads and chain, signed card answers, files owned by the service account."""
    from . import isolation
    return isolation.enabled()


# ---------------------------------------------------------------- the project's id (what a signature covers)
def _config(root) -> dict:
    try: d = yaml.safe_load((Path(root) / layout.CONFIG / "project.yaml").read_text(encoding="utf-8")) or {}
    except Exception: return {}
    return d if isinstance(d, dict) else {}


def _list_id(root):
    """The id the SERVER gave this folder: its project list (the service account), or conversation/.server.json it wrote (an agent run)."""
    from . import isolation
    if not isolation.is_service():
        f = Path(root) / "conversation" / SERVER_ID
        if isolation.trusted(f) and f.exists():
            try: return str(json.loads(f.read_text(encoding="utf-8")).get("id") or "") or None
            except (OSError, ValueError, AttributeError): return None
        return None
    try:
        from . import projects
        rp = Path(root).resolve()
        for e in projects.load():
            try:
                if Path(e["path"]).resolve() == rp and e.get("id"): return str(e["id"])
            except (OSError, KeyError): continue
    except Exception: pass
    return None


def write_server_id(root):
    """(agentd, isolation on) conversation/.server.json = the list's id: what an agent run's own checks use (it cannot read the list)."""
    pid = _list_id(root)
    if not pid: return None
    f = Path(root) / "conversation" / SERVER_ID
    try:
        if json.loads(f.read_text(encoding="utf-8")).get("id") == pid: return pid
    except (OSError, ValueError, AttributeError): pass
    f.write_text(json.dumps({"id": pid}), encoding="utf-8"); return pid


def project_id(root) -> str:
    """config/project.yaml `id` (written at creation and when the server first signs), else the project list's id for this folder, else
    the folder name (projects from before the id was written). With isolation on the server's own id comes first: the config is the
    agent's file, so changing its `id:` never moves a project out of the strict list (QA 2026-10-30, H4)."""
    from . import isolation
    if isolation.enabled():
        lid = _list_id(root)
        if lid: return lid
    v = _config(root).get("id")
    if isinstance(v, str) and v.strip(): return v.strip()
    try:
        from . import projects
        rp = Path(root).resolve()
        for e in projects.load():
            try:
                if Path(e["path"]).resolve() == rp and e.get("id"): return str(e["id"])
            except (OSError, KeyError): continue
    except Exception: pass
    return Path(root).name


def _set_config(root, **kv):
    """Add top-level keys to config/project.yaml without rewriting the rest of it (only keys it does not have yet)."""
    f = Path(root) / layout.CONFIG / "project.yaml"
    try: t = f.read_text(encoding="utf-8")
    except OSError: t = ""
    cur = _config(root); add = [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in kv.items() if k not in cur]
    if not add: return
    try: f.parent.mkdir(parents=True, exist_ok=True); f.write_text((t.rstrip("\n") + "\n" if t.strip() else "") + "\n".join(add) + "\n", encoding="utf-8")
    except OSError: pass


# ---------------------------------------------------------------- strictness: three places, any one is enough
def _strict_ids() -> set:
    try: return {ln.strip() for ln in (keys_dir() / STRICT_LIST).read_text(encoding="utf-8").splitlines() if ln.strip()}
    except OSError: return set()


def _mark_strict(root):
    pid = project_id(root)
    if pid not in _strict_ids():
        try: _append_line(keys_dir() / STRICT_LIST, pid); _mirror(STRICT_LIST)
        except OSError: pass


def strict(root) -> bool:
    """Under the ledger rule: the ledger exists, or config/project.yaml says `decisions: strict`, or the server's strict list has the
    project's id. A ledger seen once puts the project on the strict list, so deleting the ledger later does not make it legacy again."""
    if ledger(root).exists():
        _mark_strict(root); return True
    return _config(root).get("decisions") == "strict" or project_id(root) in _strict_ids()


def tampered(root) -> str:
    """Why the ledger of a strict project cannot be trusted ("" when it can): it was deleted; with isolation on also: it is not the server's
    file, or it was cut / changed after the last line the server wrote (its head)."""
    if strict(root) and not ledger(root).exists(): return f"conversation/{LEDGER} 不见了（这个项目要她在页面上确认，记录被删了）"
    if enforced() and strict(root):
        from . import isolation
        if not isolation.trusted(ledger(root)): return f"conversation/{LEDGER} 不是服务器写的文件（被替换了）"
        if _rolled_back(root): return f"conversation/{LEDGER} 被改回去了（少了服务器写过的记录）"
    return ""


def _rolled_back(root) -> bool:
    h = heads().get(project_id(root)) or {}
    n = h.get("n")
    if not isinstance(n, int) or n <= 0: return False
    raw = _raw(root)
    return len(raw) < n or _h(raw[n - 1]) != h.get("h")


def start(root, pid=None):
    """A new project: her confirmations count only through the ledger from now on (in all three places). pid: its id in the list."""
    f = ledger(root); f.parent.mkdir(parents=True, exist_ok=True); f.touch(exist_ok=True)
    _set_config(root, id=pid or project_id(root), decisions="strict"); _mark_strict(root)
    from . import isolation
    if isolation.is_service():                          # a new project: every answer of hers is signed from the start
        try:
            p_ = pid or project_id(root)
            if "answers_from" not in (heads().get(p_) or {}): _set_head(p_, answers_from=0)
        except OSError: pass


# ---------------------------------------------------------------- the server's signing key (memory only) and the public keys
_signer = None                      # (secret, public, kid) of THIS server process; None in every other process
_signer_lock = threading.Lock()
_published = set()                  # keyring files this process's public key is already in


def _kid(pub: bytes) -> str: return hashlib.sha256(pub).hexdigest()[:16]


def serve_signing():
    """Called once by the UI / hub server when it starts: a new key pair in memory (never written), its public key added to the keyring;
    then the projects signed the old way (an HMAC key in the data folder) are signed again and that key is removed."""
    global _signer
    with _signer_lock:
        if _signer is None:
            s, p = ed25519.keypair(); _signer = (s, p, _kid(p))
    _publish()
    try: migrate_all()
    except Exception as x:
        import sys; sys.stderr.write(f"[decisions] migrate: {type(x).__name__}: {x}\n")
    return _signer[2]


def _publish():
    f = keys_dir() / KEYRING
    if str(f) in _published and f.exists(): return
    if _signer[2] not in _keyring(): _append_line(f, f"{_signer[2]} {_signer[1].hex()} {datetime.now().isoformat(timespec='seconds')} pid={os.getpid()}")
    _mirror(KEYRING)
    _published.add(str(f))


_kr_cache = {}


def _keyring() -> dict:
    f = keys_dir() / KEYRING
    try: st = f.stat(); key = (str(f), st.st_mtime_ns, st.st_size)
    except OSError: return {}
    if key in _kr_cache: return _kr_cache[key]
    out = {}
    for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = ln.split()
        if len(parts) >= 2:
            try:
                pub = bytes.fromhex(parts[1])
                if len(pub) == 32 and _kid(pub) == parts[0]: out[parts[0]] = pub
            except ValueError: continue
    _kr_cache.clear(); _kr_cache[key] = out
    return out


def _msg(pid, d) -> bytes:
    m = [pid, d.get("what"), d.get("state"), d.get("at"), d.get("via"), d.get("by")]
    if "prev" in d: m += [d.get("prev"), d.get("n")]            # chained lines (2026-10-30): the line before it and its place
    return json.dumps(m, ensure_ascii=False).encode("utf-8")


def _signed(pid, d) -> dict:
    d = {k: v for k, v in d.items() if k not in ("sig", "kid")}
    d["kid"] = _signer[2]; d["sig"] = ed25519.sign(_signer[0], _msg(pid, d)).hex()
    return d


_ok_cache = {}


def _valid(pid, d) -> bool:
    pub = _keyring().get(str(d.get("kid") or ""))
    if pub is None: return False
    try: sig = bytes.fromhex(str(d.get("sig") or ""))
    except ValueError: return False
    m = _msg(pid, d); k = (pub, m, sig)
    if k not in _ok_cache:
        if len(_ok_cache) > 4096: _ok_cache.clear()
        _ok_cache[k] = ed25519.verify(pub, m, sig)
    return _ok_cache[k]


def record(root, what, state="confirmed", via="ui", by=None) -> dict:
    """The UI server saw her decide (state confirmed | draft). Raises NotTheServer anywhere else (an agent's command, the CLI)."""
    if _signer is None: raise NotTheServer("只有 GameAnything 的页面服务器能记下她的确认（她要自己在页面上点）")
    _publish()
    d = {"what": str(what), "state": "confirmed" if state == "confirmed" else "draft", "at": datetime.now().isoformat(timespec="seconds"),
         "via": str(via)}
    if by: d["by"] = str(by)
    pid = project_id(root); _set_config(root, id=pid, decisions="strict"); _mark_strict(root)
    f = ledger(root); f.parent.mkdir(parents=True, exist_ok=True)
    with _record_lock:
        raw = _raw(root)
        d["prev"] = _h(raw[-1]) if raw else ""; d["n"] = len(raw)      # each line names the one before it: a removed line breaks the chain
        d = _signed(pid, d); line = json.dumps(d, ensure_ascii=False)
        with open(f, "a", encoding="utf-8") as fh: fh.write(line + "\n")
        _set_head(pid, n=len(raw) + 1, h=_h(line))
    return d


_record_lock = threading.Lock()


def _rewrite(root, rows):
    """(The server) the ledger written again from `rows` (each signed again, chained), and its head."""
    pid = project_id(root); out = []; prev = ""
    for i, d in enumerate(rows):
        d = {k: v for k, v in d.items() if k not in ("sig", "kid", "prev", "n")}; d["prev"] = prev; d["n"] = i
        line = json.dumps(_signed(pid, d), ensure_ascii=False); out.append(line); prev = _h(line)
    ledger(root).write_text("".join(r + "\n" for r in out), encoding="utf-8")
    _set_head(pid, n=len(out), h=prev)


def seal(root):
    """(The server, at its start) a strict project's ledger without a head gets one (the lines there now), and the point in its thread
    from which her card answers must be signed (the answers before it are from before signing existed)."""
    pid = project_id(root); h = heads().get(pid) or {}; kv = {}
    if "n" not in h:
        raw = _raw(root); kv.update(n=len(raw), h=_h(raw[-1]) if raw else "")
    if "answers_from" not in h:
        try: kv["answers_from"] = sum(1 for ln in (Path(root) / "conversation" / "thread.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip())
        except OSError: kv["answers_from"] = 0
    if kv: _set_head(pid, **kv)


# ---------------------------------------------------------------- her card answers, signed by the page server (QA 2026-10-30, H3)
def _ev_msg(pid, ev) -> bytes:
    return json.dumps([pid, "answer", ev.get("id"), ev.get("at"), ev.get("card_id"), ev.get("answer"), ev.get("source"), ev.get("author")],
                      ensure_ascii=False, sort_keys=True).encode("utf-8")


def sign_event(root, ev) -> dict:
    """(The page server) her answer event gets kid / sig over the project id, its id, time, card and answer. Elsewhere: unchanged."""
    if _signer is None: return ev
    _publish()
    ev["kid"] = _signer[2]; ev["sig"] = ed25519.sign(_signer[0], _ev_msg(project_id(root), ev)).hex()
    return ev


def answer_ok(root, ev, index, pid=None, floor=None) -> bool:
    """Does this answer event count (isolation on, a strict project)? Before the project's `answers_from` line: yes (from before signing);
    from there on only with the page server's signature. Isolation off: always (the old rule)."""
    if not enforced(): return True
    if ev.get("from") != "user" or ev.get("type") != "answer": return True
    if floor is None:
        if not strict(root): return True
        floor = (heads().get(pid or project_id(root)) or {}).get("answers_from", 0)
    if isinstance(floor, int) and index < floor: return True
    pub = _keyring().get(str(ev.get("kid") or ""))
    if pub is None: return False
    try: sig = bytes.fromhex(str(ev.get("sig") or ""))
    except ValueError: return False
    m = _ev_msg(pid or project_id(root), ev); k = (pub, m, sig)
    if k not in _ok_cache:
        if len(_ok_cache) > 4096: _ok_cache.clear()
        _ok_cache[k] = ed25519.verify(pub, m, sig)
    return _ok_cache[k]


def answer_floor(root):
    """(pid, floor) for Thread.events: floor None = every answer counts (isolation off or a legacy project)."""
    if not enforced() or not strict(root): return None, None
    pid = project_id(root)
    return pid, (heads().get(pid) or {}).get("answers_from", 0)


# ---------------------------------------------------------------- the old HMAC lines (before 2026-10-30): read while the old key is there
def _legacy_keys(root) -> list:
    """The old key, while it may still count: no new server has started yet (LEGACY_CLOSED), and it is the key first seen (LEGACY_PIN)."""
    from . import projects
    kd = keys_dir()
    if (kd / LEGACY_CLOSED).exists(): return []
    try: pins = set((kd / LEGACY_PIN).read_text(encoding="utf-8").split())
    except OSError: pins = None
    out = []
    for dd in {str(projects.data_dir()), str(projects.data_dir(root))}:
        try: k = bytes.fromhex((Path(dd) / "decisions.key").read_text(encoding="utf-8").strip())
        except (OSError, ValueError): continue
        h = hashlib.sha256(k).hexdigest()
        if pins is None:
            try: _append_line(kd / LEGACY_PIN, h); pins = {h}
            except OSError: pins = set()
        if h in pins: out.append(k)
    return out


def _legacy_ok(root, d, keys) -> bool:
    if d.get("kid") or not keys: return False
    m = json.dumps([Path(root).name, d.get("what"), d.get("state"), d.get("at"), d.get("via")], ensure_ascii=False).encode("utf-8")
    return any(hmac.compare_digest(str(d.get("sig") or ""), hmac.new(k, m, hashlib.sha256).hexdigest()[:32]) for k in keys)


def _rows(root) -> list:
    try: lines = ledger(root).read_text(encoding="utf-8").splitlines()
    except OSError: return []
    out = []
    for ln in lines:
        try: d = json.loads(ln)
        except ValueError: continue
        if isinstance(d, dict): out.append(d)
    return out


def entries(root) -> list:
    pid = project_id(root)
    if enforced(): return _entries_enforced(root, pid)
    rows = _rows(root)
    lk = _legacy_keys(root) if any(not d.get("kid") for d in rows) else []
    return [d for d in rows if _valid(pid, d) or _legacy_ok(root, d, lk)]


def _entries_enforced(root, pid) -> list:
    """Isolation on: only the server's file, only up to its head, and a chained line only while the chain holds."""
    from . import isolation
    if not isolation.trusted(ledger(root)) or _rolled_back(root): return []
    raw = _raw(root); h = heads().get(pid) or {}
    if isinstance(h.get("n"), int): raw = raw[:h["n"]]                  # lines after the last one the server wrote never count
    rows, out = [], []
    for i, ln in enumerate(raw):
        try: d = json.loads(ln)
        except ValueError: d = None
        if not isinstance(d, dict): continue
        if "prev" in d and (d.get("prev") != (_h(raw[i - 1]) if i else "") or d.get("n") != i): break
        rows.append(d)
    lk = _legacy_keys(root) if any(not d.get("kid") for d in rows) else []
    return [d for d in rows if _valid(pid, d) or _legacy_ok(root, d, lk)]


def migrate(root) -> int:
    """(The server) the old HMAC lines that are valid, signed again with this server's key; -> how many."""
    if _signer is None or not ledger(root).exists(): return 0
    _publish(); rows = _rows(root); lk = _legacy_keys(root); pid = project_id(root); n = 0; out = []
    for d in rows:
        if _legacy_ok(root, d, lk): d = _signed(pid, d); n += 1
        out.append(json.dumps(d, ensure_ascii=False))
    if n:
        _set_config(root, id=pid, decisions="strict")
        _rewrite(root, [json.loads(r) for r in out if _valid(pid, json.loads(r))])
    _mark_strict(root)
    return n


def migrate_all():
    """(The server, at its start) every listed project with a ledger: old lines signed again; then the old key files are removed."""
    from . import projects
    if _signer is None: return
    keys = set()
    for e in projects.load():
        root = Path(e.get("path") or "")
        if not ledger(root).exists(): continue
        migrate(root)
        try: seal(root)
        except OSError: pass
        keys |= {str(Path(dd) / "decisions.key") for dd in {str(projects.data_dir()), str(projects.data_dir(root))}}
    keys.add(str(projects.data_dir() / "decisions.key"))
    for k in keys:
        try: Path(k).unlink()
        except OSError: pass
    try: _private_dir(); (keys_dir() / LEGACY_CLOSED).write_text(datetime.now().isoformat(timespec="seconds") + "\n", encoding="utf-8")
    except OSError: pass


def last(root, what):
    """Her latest valid decision about `what` ({what, state, at, via}), or None."""
    E = [(str(d.get("at") or ""), i, d) for i, d in enumerate(entries(root)) if d.get("what") == what]
    return max(E, key=lambda x: x[:2])[2] if E else None          # by its signed time: moving an old line down changes nothing


def confirmed(root, what, claimed=True) -> bool:
    """Does a file's confirmation (`claimed`) count as hers? Legacy projects: the file alone; else her latest decision says confirmed
    (a strict project without its ledger: none counts)."""
    if not claimed: return False
    if not strict(root): return True
    d = last(root, what); return bool(d and d.get("state") == "confirmed")


def resign(root) -> bool:
    """After an import into this GameAnything: her decisions in the backup, signed again with this server's key (the import is her own
    act on the page). Outside the server (the CLI's import) the lines stay as they are and do not count here: -> False."""
    if _signer is None: return False
    _publish(); pid = project_id(root)
    _set_config(root, id=pid, decisions="strict"); _mark_strict(root)
    _rewrite(root, [d for d in _rows(root) if d.get("what")])
    return True


# ---------------------------------------------------------------- what the review files claim, and whether she did it
def _y(p):
    try: return yaml.safe_load(Path(p).read_text(encoding="utf-8")) or {}
    except Exception: return {}


def claims(root) -> list:
    """[(what, file)] for every confirmation the project's files claim (the review files the UI writes, the agent's board / plan status)."""
    root = Path(root); F, R, D = root / layout.FEEDBACK, root / layout.REMEMBER, root / layout.DESIGN
    out = []
    def d(x): return x if isinstance(x, dict) else {}
    b = d(_y(F / "board_review.yaml"))
    if b.get("state") == "confirmed": out.append(("board", "feedback/board_review.yaml"))
    p = d(_y(F / "plan_review.yaml"))
    if p.get("state") == "confirmed": out.append((f"plan:{p.get('milestone')}", "feedback/plan_review.yaml"))
    a = d(_y(F / "adaptation_review.yaml"))
    if a.get("state") == "confirmed": out.append(("scenes", "feedback/adaptation_review.yaml"))
    if a.get("state_characters") == "confirmed": out.append(("characters", "feedback/adaptation_review.yaml (state_characters)"))
    if d(_y(F / "feature_review.yaml")).get("state") == "confirmed": out.append(("spec", "feedback/feature_review.yaml"))
    g = d(_y(F / "gameplay_review.yaml"))
    for st in ("mapping", "content"):
        if d(g.get(st)).get("state") == "confirmed": out.append((f"gameplay:{st}", f"feedback/gameplay_review.yaml ({st}.state)"))
    ppl = d(_y(R / "people.yaml")).get("people")
    if isinstance(ppl, list) and any(isinstance(x, dict) and x.get("confirmed_by") == "user" for x in ppl):
        out.append(("people", "3_remember/people.yaml (confirmed_by: user)"))
    return out


def forged(root) -> list:
    """The files that claim a confirmation of hers the ledger does not have (an agent wrote it): [(what, file)]. Legacy projects: none.
    A plan confirmed on an older milestone, or her approval on a plan card (flow.record_answer records it too), are not listed."""
    if not strict(root): return []
    return [(w, f) for w, f in claims(root) if not confirmed(root, w)]


FORGED_NOTE = ("agent 写的确认不算数，请你自己在页面上确认（{what}）",
               "A confirmation the agent wrote does not count: please confirm it yourself on the page ({what})")
WHAT_NAMES = {"board": ("这一天", "the day"), "scenes": ("场景和地点", "the scenes and places"), "characters": ("人物", "the characters"),
              "spec": ("需求单", "the requirements"), "gameplay:mapping": ("机制映射", "the mechanics mapping"),
              "gameplay:content": ("内容表", "the content list"), "people": ("人物标注", "the people tags")}


def _what_name(w, en=False):
    if w.startswith("plan:"): return f"the plan ({w[5:]})" if en else f"方案（{w[5:]}）"
    return WHAT_NAMES.get(w, (w, w))[1 if en else 0]


def note_forged(root, thread=None) -> list:
    """(agentd, after a run) A confirmation an agent wrote and the ledger does not have: one system line in her chat, so the agent's
    「我已经帮你确认了」 does not stand there alone (QA 2026-10-30). Once per claim (conversation/.forged_noted.json); -> the whats noted now."""
    root = Path(root); f = root / "conversation" / ".forged_noted.json"
    try: done = set(json.loads(f.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError): done = set()
    now = {w for w, _ in forged(root)}
    new = sorted(now - done)
    if new:
        from .conversation import Thread
        T = thread or Thread(root)
        zh = "、".join(_what_name(w) for w in new); en = ", ".join(_what_name(w, True) for w in new)
        T.append({"from": "system", "type": "status", "text": FORGED_NOTE[0].format(what=zh), "text_en": FORGED_NOTE[1].format(what=en),
                  "notice": "forged_confirmation"})
    if now != done:
        try: f.write_text(json.dumps(sorted(now)), encoding="utf-8")       # a claim undone and made again is noted again
        except OSError: pass
    return new
