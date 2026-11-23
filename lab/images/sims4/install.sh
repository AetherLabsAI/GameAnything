#!/usr/bin/env bash
# The The Sims 4 game layer (run as root by lab/images/sims4/Dockerfile on its runtime image; on a plain ubuntu:24.04, e.g. a docker-rt test
# sandbox, it installs the runtime layers base wine first). NO game files, no accounts, no keys: the user's game is mounted read-only at run
# time, or downloaded with the user's own account into the user's own volume.
#   SRC=<GameAnything checkout>   PLAYER_UID=1000 (plain ubuntu only)
set -euo pipefail
umask 022   # readable for the player whatever the builder's umask (install-system.sh)
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${SRC:-$(cd "$HERE/../../.." && pwd)}
. "$SRC/lab/images/common/layers.sh"
ga_need base wine
GAME_ID=sims4 SRC="$SRC" bash "$SRC/lab/images/common/install-gameanything.sh"
install -m 755 "$HERE/ga-sims4" /usr/local/bin/ga-sims4
install -m 755 "$SRC/lab/images/common/ga-ea" /usr/local/bin/ga-ea
wine --version && /opt/python3.7/bin/python3.7 --version
