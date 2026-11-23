"""What differs between Linux, macOS and Windows for the core tool (D19): where gameanything keeps its own files, file locks, the
system keyring, and opening a URL. Game-specific paths live in `native/`.

    system()                     "linux" | "mac" | "windows"
    config_home() / data_home()  Linux and macOS: ~/.config/gameanything and ~/.local/share/gameanything (XDG, the CLI
                                 convention, kept for existing projects); Windows: %APPDATA% and %LOCALAPPDATA%. A folder left
                                 from before the rename (.../memory2world) is moved there on first use and a link with the old
                                 name points at the new one (migrate_home); nothing is deleted
    lock(f, block=True)          exclusive lock on an open file (fcntl, or msvcrt on Windows); raises OSError when not blocking and held
    secret_get / secret_set / secret_clear      the system keyring (macOS Keychain via `security`, Linux Secret Service via `secret-tool`); None when there is none
    open_url(url)                open a URL with the system handler (also steam:// links)
    pid_alive(pid, start=None)   is that process running on this machine (and, when `start` is given, the same one: pids are reused)
    pid_start(pid)               a token for when the process started (Linux: /proc/<pid>/stat field 22), None when unknown
    stop_group(pid)              ask a process group started with its own session / group (a supervised run) to stop
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path


def system() -> str:
    return "mac" if sys.platform == "darwin" else "windows" if os.name == "nt" else "linux"


def json_text(obj, **kw) -> str:
    """JSON for stdout (--json, read by an agent). Windows: ASCII only (\\uXXXX): Windows PowerShell 5.1 decodes a native command's
    output with the console code page, so `gameanything ... --json > f` or `| ...` inside OpenCode turned UTF-8 Chinese into
    "σÅæµîë" (a real Windows 11 PC, 2026-11-02). Elsewhere readable UTF-8 as before. Files are written as UTF-8 and do not need it."""
    import json
    return json.dumps(obj, ensure_ascii=system() == "windows", **kw)


def windows_package():
    """Windows: the packaged (MSIX) app whose file redirection this process is under (e.g. the Claude desktop app), else None.
    There, a NEW folder under AppData is written to Packages/<app>/LocalCache instead: a game started from Steam never sees it (a
    real Windows 11 PC 2026-11-01: Cities' Addons/Mods and a downloaded .minecraft). Its child processes have no package identity
    (GetCurrentPackageFullName says none), so this looks: a probe folder, then where it really is."""
    if os.name != "nt" or not os.environ.get("LOCALAPPDATA"): return None
    local = Path(os.environ["LOCALAPPDATA"]); probe = local / f"gameanything-probe-{os.getpid()}"
    try:
        probe.mkdir(exist_ok=True)
        hit = next((p for p in (local / "Packages").glob(f"*/LocalCache/Local/{probe.name}")), None)
        return hit.parents[2].name if hit else None
    except OSError: return None
    finally:
        try: probe.rmdir()
        except OSError: pass


NAME = "gameanything"
OLD_NAME = "memory2world"           # the folder name before the rename (2026-10-27)


def config_home() -> Path:
    if system() == "windows": return migrate_home(Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"))
    return migrate_home(Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"))


def data_home() -> Path:
    if system() == "windows": return migrate_home(Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"))
    return migrate_home(Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"))


def migrate_home(base: Path) -> Path:
    """base/gameanything. When only base/memory2world is there (an install from before the rename): move it to base/gameanything and
    leave base/memory2world as a link to it, so an older GameAnything still running finds its files (projects.yaml, users, settings) where it
    left them. Deletes nothing. When the link cannot be made (Windows without the right to make one), the move is undone and the old
    folder stays in use; so does an old folder that is itself a link, and one that cannot be moved."""
    new, old = base / NAME, base / OLD_NAME
    if new.exists(): return new
    if not old.is_dir(): return new                                     # a new install
    if old.is_symlink() or new.is_symlink(): return old                 # someone's own link: leave both as they are
    try: os.rename(old, new)
    except OSError: return new if new.exists() else old              # another process moved it first, or it cannot be moved
    try: os.symlink(new, old, target_is_directory=True)
    except OSError:
        try: os.rename(new, old); return old
        except OSError: return new
    return new


def lock(f, block=True):
    """Exclusive lock on the open file `f`, released when it is closed."""
    if system() == "windows":
        import msvcrt
        f.seek(0)
        while True:
            try: msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1); return
            except OSError:
                if not block: raise
                import time; time.sleep(0.05)
    import fcntl
    fcntl.flock(f, fcntl.LOCK_EX | (0 if block else fcntl.LOCK_NB))


# ---------------------------------------------------------------- keyring
# The macOS Keychain service keeps its name from before the rename ("memory2world-<service>"): the secrets already stored there stay readable.
def _run(args, **kw):
    if not shutil.which(args[0]): return None
    try: return subprocess.run(args, capture_output=True, text=True, encoding="locale", errors="replace", timeout=15, **kw)
    except (OSError, subprocess.SubprocessError): return None


def secret_get(service: str, key: str):
    """The stored secret, '' when the keyring has none, None when there is no keyring."""
    if system() == "mac": r = _run(["security", "find-generic-password", "-s", f"memory2world-{service}", "-a", key, "-w"])
    elif system() == "linux": r = _run(["secret-tool", "lookup", "service", service, "key", key])
    else: return None
    if r is None: return None
    return r.stdout.strip() if r.returncode == 0 else ""


def secret_set(service: str, key: str, value: str, label: str) -> bool:
    """Store in the keyring -> True; False when there is no keyring or it refused. The value never goes on a command line."""
    if system() == "mac":
        if any(c in value for c in "\"\\\n"): return False                 # `security -i` quoting; tokens never contain these
        r = _run(["security", "-i"], input=f'add-generic-password -U -s "memory2world-{service}" -a "{key}" -l "{label}" -w "{value}"\n')
    elif system() == "linux": r = _run(["secret-tool", "store", f"--label={label}", "service", service, "key", key], input=value)
    else: return False
    return r is not None and r.returncode == 0


def secret_clear(service: str, key: str) -> bool:
    """Remove the secret from the keyring -> True when the keyring took the request."""
    if system() == "mac": r = _run(["security", "delete-generic-password", "-s", f"memory2world-{service}", "-a", key])
    elif system() == "linux": r = _run(["secret-tool", "clear", "service", service, "key", key])
    else: return False
    return r is not None and r.returncode == 0


def open_url(url: str) -> bool:
    if system() == "windows":
        try: os.startfile(url); return True                                 # noqa: the Windows shell handler
        except OSError: return False
    r = _run(["open" if system() == "mac" else "xdg-open", url])
    return r is not None and r.returncode == 0


# ---------------------------------------------------------------- processes
def pid_start(pid):
    """When the process started, as an opaque string (Linux only; None elsewhere or when it is gone). Tells a reused pid apart."""
    try: return Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()[19]
    except (OSError, ValueError, IndexError, TypeError): return None


def pid_alive(pid, start=None) -> bool:
    """True while process `pid` runs on this machine (a zombie counts as gone); with `start` (from pid_start) also the same process."""
    try: pid = int(pid)
    except (TypeError, ValueError): return False
    if pid <= 0: return False
    if system() == "windows":
        import ctypes
        k = ctypes.windll.kernel32; h = k.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h: return False
        code = ctypes.c_ulong(); ok = k.GetExitCodeProcess(h, ctypes.byref(code)); k.CloseHandle(h)
        return bool(ok) and code.value == 259                                      # STILL_ACTIVE
    try: os.getpgid(pid)                                                           # POSIX: raises when there is no such process
    except ProcessLookupError: return False
    except OSError: return False
    try:
        st = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()
        if st[0] == "Z": return False
        if start is not None and st[19] != str(start): return False
    except (OSError, IndexError): pass
    return True


def stop_group(pid) -> bool:
    """SIGTERM to the process group `pid` leads (started with start_new_session / CREATE_NEW_PROCESS_GROUP); Windows: the process tree."""
    args = ["taskkill", "/PID", str(int(pid)), "/T", "/F"] if system() == "windows" else ["kill", "-TERM", "--", f"-{int(pid)}"]
    try: return subprocess.run(args, capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError): return False


# ---------------------------------------------------------------- OS accounts (POSIX; agent isolation, docs/agent-isolation.md)
def accounts() -> list:
    """[(name, uid, gid)] of every OS account; [] where there are none to list (Windows)."""
    try: import pwd
    except ImportError: return []
    return [(p.pw_name, p.pw_uid, p.pw_gid) for p in pwd.getpwall()]


def account(name):
    """(uid, gid) of an OS account, or None."""
    try:
        import pwd
        p = pwd.getpwnam(name); return p.pw_uid, p.pw_gid
    except (ImportError, KeyError, TypeError): return None


def account_name(uid):
    try:
        import pwd
        return pwd.getpwuid(uid).pw_name
    except (ImportError, KeyError, TypeError): return None


def group(name):
    """(gid, [member names]) of an OS group, or None."""
    try:
        import grp
        g = grp.getgrnam(name); return g.gr_gid, list(g.gr_mem)
    except (ImportError, KeyError, TypeError): return None


def group_name(gid):
    try:
        import grp
        return grp.getgrgid(gid).gr_name
    except (ImportError, KeyError, TypeError): return None
