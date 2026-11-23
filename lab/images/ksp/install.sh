#!/usr/bin/env bash
# The Kerbal Space Program game layer (run as root by lab/images/ksp/Dockerfile on gameanything-lab-dotnet; on a plain ubuntu:24.04 it
# installs base + steam + dotnet first). NO game files, no accounts, no keys: the user's KSP folder is mounted read-only at run time.
# Plugins are built with the .NET SDK 8 (net472 against the game's own KSP_Data/Managed, offline); Unity's libraries are in "dotnet".
#   SRC=<GameAnything checkout>   PLAYER_UID=1000 (plain ubuntu only)
set -euo pipefail
umask 022   # readable for the player whatever the builder's umask (install-system.sh)
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${SRC:-$(cd "$HERE/../../.." && pwd)}
. "$SRC/lab/images/common/layers.sh"
ga_need base steam dotnet
GAME_ID=ksp SRC="$SRC" bash "$SRC/lab/images/common/install-gameanything.sh"
install -m 755 "$HERE/ga-ksp" /usr/local/bin/ga-ksp
dotnet --list-sdks
