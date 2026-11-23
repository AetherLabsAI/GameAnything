#!/usr/bin/env bash
# The Minecraft: Java Edition game layer (run as root by lab/images/minecraft/Dockerfile on gameanything-lab-java; on a plain
# ubuntu:24.04 it installs base + java first). NO game files, no accounts, no keys: the user's .minecraft is mounted read-only at run
# time (or downloaded with their Microsoft account into their own volume: ga-mc download), and the game is started from it, offline.
#   SRC=<GameAnything checkout>   PLAYER_UID=1000 (plain ubuntu only)
set -euo pipefail
umask 022   # readable for the player whatever the builder's umask (install-system.sh)
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${SRC:-$(cd "$HERE/../../.." && pwd)}
. "$SRC/lab/images/common/layers.sh"
ga_need base java
GAME_ID=minecraft SRC="$SRC" bash "$SRC/lab/images/common/install-gameanything.sh"
install -m 755 "$HERE/ga-mc" /usr/local/bin/ga-mc
java -version
