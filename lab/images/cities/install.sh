#!/usr/bin/env bash
# The Cities: Skylines game layer (run as root by lab/images/cities/Dockerfile on its runtime image; on a plain ubuntu:24.04, e.g. a docker-rt test
# sandbox, it installs the runtime layers base steam dotnet first). NO game files, no accounts, no keys: the user's game is mounted read-only at run
# time, or downloaded with the user's own account into the user's own volume.
#   SRC=<GameAnything checkout>   PLAYER_UID=1000 (plain ubuntu only)
set -euo pipefail
umask 022   # readable for the player whatever the builder's umask (install-system.sh)
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${SRC:-$(cd "$HERE/../../.." && pwd)}
. "$SRC/lab/images/common/layers.sh"
ga_need base steam dotnet
GAME_ID=cities_skylines SRC="$SRC" bash "$SRC/lab/images/common/install-gameanything.sh"
install -m 755 "$HERE/ga-cities" /usr/local/bin/ga-cities
dotnet --list-sdks
