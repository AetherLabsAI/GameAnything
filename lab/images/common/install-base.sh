#!/usr/bin/env bash
# Base + GameAnything in one go, for a plain ubuntu:24.04 (the docker-rt test sandboxes, docs/sandbox-images.md). The images split it:
# install-system.sh is the shared layer "base" (lab/images/base), install-gameanything.sh is part of each game layer.
#   SRC=<GameAnything checkout>    PLAYER_UID=1000    EXTRA_APT="<the game's packages>"    APT_SNAPSHOT (install-system.sh)
set -euo pipefail
umask 022   # readable for the player whatever the builder's umask (install-system.sh)
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${SRC:-$(cd "$HERE/../../.." && pwd)}
bash "$HERE/install-system.sh"
SRC="$SRC" bash "$HERE/install-gameanything.sh"
