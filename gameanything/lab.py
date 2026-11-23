"""`gameanything lab`: the sandboxes. On the user's OWN Linux machine (no gamebench): `lab setup --image`, `lab sandbox`, `lab login`,
`lab consent` are all there is (no seats). On a gamebench lab (the maintainer's servers): also seats in the shared lab sandboxes (who may
run which game where), a thin wrapper: the broker itself is gamebench hosting/broker.py (pool and leases on the lab server: $GAMEANYTHING_LAB_POOL, leases.json next to it; on a single machine
with plain Docker: <M2W_LAB_HOME>/labs/{pool.yaml,leases.json}).

    gameanything lab acquire --user U --project P --game G     prints the seat and `export GAMEANYTHING_LEASE=...` / M2W_LEASE (or the queue position, 排队等位置)
    gameanything lab release --project P | heartbeat --project P | status | queue | stale | register-existing
    gameanything lab setup [--yes] [--github-user U --pat-stdin] [--stardew DIR] [--minecraft DIR]
                                                      the lab on THIS Linux machine with plain Docker (labdocker.py): ghcr.io login,
                                                      images, ~/.config/m2w/lab.env, game folders, the local seat pool
    gameanything lab setup --image GAME [--build]              GAME's runtime-only sandbox image: pull the published one, else (or --build) build it locally for your own uid
                                                      (PLAYER_UID is passed for you; also with Docker Desktop on Windows / Mac)
    gameanything lab ready [--json]                            which games the plain-Docker lab can run here, and why not
    gameanything lab doctor [--json] [--game G]                gamebench's hosting/lab/lab-doctor (Docker, GPU, disk, images, game folders)
    gameanything lab login steam|microsoft|ea [--project P | --container C] [--app A] [--install] [--lang zh|en] [--json] [--status]
                                                      the user signs in to THEIR OWN store account in their sandbox: live progress in
                                                      their language, the setup watchdog on every wait, ownership checked after
                                                      (loginflow.py; EA: not yet verified, starts nothing)
    gameanything lab consent --app APPID [--project P] --yes   record that the user agreed to a publisher EULA (they still click Accept)
    gameanything lab sandbox up|status|tool|build|shot|input|down --project P
                                                      the user's own sandbox on their own Linux machine with plain Docker: no gamebench,
                                                      no seats (labsandbox.py)
    gameanything lab env up|status [--lease L] [--json]        the lease's base environment: pod, X display + viewer, Steam logged on (labup.py;
                                                      never starts a game, never types a Steam login: exit 4 = she must log in)
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from . import osdirs


NO_GAMEBENCH = "no gamebench checkout configured: set GAMEANYTHING_GAMEBENCH (or `gamebench:` in settings.yaml); maintainers only, internal/README.md"


def gamebench():
    """The configured gamebench checkout (it may not exist), or None when none is configured (buildmode.gamebench_path)."""
    from .buildmode import gamebench_path
    return gamebench_path()


def main(argv):
    argv = list(argv)
    if not argv or argv[0] in ("-h", "--help", "help"):          # without gamebench the broker fallback below would only say it is missing
        print(__doc__); return 0
    if argv[:1] == ["setup"]:
        from .labdocker import setup
        return setup(argv[1:])
    if argv[:1] == ["ready"]:
        from .labdocker import WHY_TEXT, status
        st = status()
        if "--json" in argv: print(osdirs.json_text(st, indent=1)); return 0
        print(f"[lab] config {st['config'] or 'none (gameanything lab setup)'}, gamebench {st['gamebench'] or 'not found'}, ghcr.io login {'yes' if st['docker_login'] else 'no'}, "
              f"pool {st['pool'] or 'none'}")
        for g, s in st["games"].items():
            print(f"[lab] {g}: " + ("ready" if s["ready"] else f"not ready ({WHY_TEXT.get(s['why'], s['why'])})") + f"  folder {s['folder'] or '-'}  image {s['image'] or '-'}")
        return 0
    if argv[:1] == ["sandbox"]:
        from .labsandbox import main as sandbox_main
        return sandbox_main(argv[1:])
    if argv[:1] == ["login"]:
        from .loginflow import main as login_main
        return login_main(argv[1:])
    if argv[:1] == ["consent"]:
        from .loginflow import consent_main
        return consent_main(argv[1:])
    if argv[:1] == ["env"]:
        from .labup import main as env_main
        return env_main(argv[1:])
    if gamebench() is None: sys.exit(f"[lab] {NO_GAMEBENCH}")          # doctor and the broker below need the maintainers' gamebench
    if argv[:1] == ["doctor"]:
        d = gamebench() / "hosting" / "lab" / "lab-doctor"
        if not d.is_file(): sys.exit(f"[lab] no lab-doctor at {d} (set GAMEANYTHING_GAMEBENCH to the gamebench checkout)")
        return subprocess.run([sys.executable, str(d), *argv[1:]]).returncode
    hosting = gamebench() / "hosting"
    if not (hosting / "broker.py").is_file():
        sys.exit(f"[lab] no lab broker at {hosting}/broker.py (set GAMEANYTHING_GAMEBENCH to the gamebench checkout)")
    if str(hosting) not in sys.path: sys.path.insert(0, str(hosting))
    import broker
    return broker.main(argv)
