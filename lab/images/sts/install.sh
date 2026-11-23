#!/usr/bin/env bash
# The Slay the Spire game layer (run as root by lab/images/sts/Dockerfile on gameanything-lab-java; on a plain ubuntu:24.04 it installs
# base + java first). Adds the Steam layer here (Slay the Spire comes from Steam; the shared Steam layer sits under .NET, not under Java).
# NO game files, no accounts, no keys: the user's game folder (and their Workshop copies of ModTheSpire + BaseMod) are mounted read-only
# at run time; the game runs on its own bundled Java 8, mods are built with javac --release 8.
#   SRC=<GameAnything checkout>   PLAYER_UID=1000 (plain ubuntu only)
set -euo pipefail
umask 022   # readable for the player whatever the builder's umask (install-system.sh)
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${SRC:-$(cd "$HERE/../../.." && pwd)}
. "$SRC/lab/images/common/layers.sh"
ga_need base java steam
GAME_ID=slay_the_spire SRC="$SRC" bash "$SRC/lab/images/common/install-gameanything.sh"
install -m 755 "$HERE/ga-sts" /usr/local/bin/ga-sts
mkdir -p /workshop
javac -version
