"""Fake game folders for a game package's tests (no game, no Steam, no network): what tests/games/test_<id>.py and a plugin's tests use.

    env = fake_steam_app(tmp, appid, "Install Dir", files=["tModLoader.dll"])     # a Steam library with that app installed
    g = make(spec_or_id, tmp, env=env, sys_="linux")                            # the adapter on that fake system
The adapter only ever sees `home` and `env` (plus GAMEANYTHING_DATA), so pointing them into tmp keeps a test away from the real user's files.
"""
from pathlib import Path


def fake_steam_app(root, appid: int, installdir: str, files=(), env=None) -> dict:
    """<root>/steam/steamapps/{appmanifest_<appid>.acf, common/<installdir>/<files>}; -> env with GAMEANYTHING_STEAM_DIR set (merged into env)."""
    st = Path(root) / "steam"; sa = st / "steamapps"; d = sa / "common" / installdir
    d.mkdir(parents=True, exist_ok=True)
    (sa / f"appmanifest_{appid}.acf").write_text(f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"installdir"\t\t"{installdir}"\n}}\n', encoding="utf-8")
    for f in files:
        p = d / f
        if str(f).endswith("/"): p.mkdir(parents=True, exist_ok=True)
        else: p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"fake")
    return {**(env or {}), "GAMEANYTHING_STEAM_DIR": str(st)}


def make(spec, root, env=None, sys_="linux", home=None):
    """The game's adapter instance with home = <root>/home and GAMEANYTHING_DATA = <root>/data (env entries win)."""
    from .. import games as registry
    s = registry.get(spec) if isinstance(spec, str) else spec
    cls = registry.adapter_class(s)
    home = Path(home) if home else Path(root) / "home"; home.mkdir(parents=True, exist_ok=True)
    e = {"GAMEANYTHING_DATA": str(Path(root) / "data"), "USERPROFILE": str(home), **(env or {})}
    return cls(sys_=sys_, home=home, env=e)
