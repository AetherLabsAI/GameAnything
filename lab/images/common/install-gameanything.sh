#!/usr/bin/env bash
# The game layer's shared part (run as root by a game's install.sh, on top of its runtime layers): GameAnything in its own venv
# (builds and installs mods: gameanything native build --game <game> --install <mod>), the galab.py helper library, the game's smoke mod.
#   SRC=<GameAnything checkout>   GAME_ID=<gameanything game id, for the smoke mod>   PLAYER_UID (only to chown)
set -euo pipefail
umask 022   # readable for the player whatever the builder's umask (install-system.sh)
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${SRC:-$(cd "$HERE/../../.." && pwd)}
# built from a copy: pip writes build/ and *.egg-info next to the sources, and SRC may be read-only
B=$(mktemp -d); cp -r "$SRC/." "$B/"; rm -rf "$B/build" "$B"/*.egg-info "$B/.venv"
python3 -m venv /opt/gameanything/venv
/opt/gameanything/venv/bin/pip install --no-cache-dir --disable-pip-version-check -q "$B"
rm -rf "$B"
ln -sf /opt/gameanything/venv/bin/gameanything /usr/local/bin/gameanything
mkdir -p /usr/local/lib/gameanything /opt/gameanything/vendor /opt/gameanything/smoke
install -m 644 "$SRC/lab/images/common/galab.py" /usr/local/lib/gameanything/galab.py
install -m 644 "$SRC/docs/sandbox-images.md" /opt/gameanything/README.md 2>/dev/null || true
# the watchdog the store tools (ga-steam, ga-ea) import when present
# (outside /opt/gameanything/src, which the Dockerfile removes after the build)
mkdir -p /opt/gameanything/lib-src/gameanything
cp "$SRC/gameanything/watchdog.py" "$SRC/gameanything/hiccups.py" /opt/gameanything/lib-src/gameanything/
touch /opt/gameanything/lib-src/gameanything/__init__.py
if [ -n "${GAME_ID:-}" ]; then          # the game's smoke mod (game.yaml `smoke:`), as /opt/gameanything/smoke/M2WSmoke
  rel=$(python3 - "$SRC/gameanything/games/$GAME_ID/game.yaml" <<'PY'
import re, sys
m = re.search(r"^smoke:\s*(\S+)", open(sys.argv[1], encoding="utf-8").read(), re.M)
print(m.group(1) if m else "")
PY
)
  if [ -n "$rel" ] && [ -d "$SRC/gameanything/games/$GAME_ID/$rel" ]; then
    rm -rf /opt/gameanything/smoke/M2WSmoke; mkdir -p /opt/gameanything/smoke/M2WSmoke
    cp -r "$SRC/gameanything/games/$GAME_ID/$rel/." /opt/gameanything/smoke/M2WSmoke/
  fi
fi
# a local build for another uid (PLAYER_UID, passed by gameanything lab setup --image --build): the layers below were made for 1000
if [ -n "${PLAYER_UID:-}" ] && [ "$PLAYER_UID" != 0 ] && [ "$(id -u player)" != "$PLAYER_UID" ]; then
  other=$(getent passwd "$PLAYER_UID" | cut -d: -f1 || true)
  if [ -n "$other" ] && [ "$other" != player ]; then userdel "$other" 2>/dev/null || true; fi
  usermod -u "$PLAYER_UID" player && chown -R player:player /home/player
fi
chown -R player:player /opt/gameanything/smoke
gameanything --help >/dev/null
echo "gameanything $(date -u +%FT%TZ) game=${GAME_ID:-}" > /opt/gameanything/layers/gameanything
