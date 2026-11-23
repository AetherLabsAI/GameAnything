#!/usr/bin/env bash
# The Valheim (BepInEx) game layer (run as root by lab/images/valheim/Dockerfile on its runtime image; on a plain ubuntu:24.04, e.g. a docker-rt test
# sandbox, it installs the runtime layers base steam dotnet first). NO game files, no accounts, no keys: the user's game is mounted read-only at run
# time, or downloaded with the user's own account into the user's own volume.
#   SRC=<GameAnything checkout>   PLAYER_UID=1000 (plain ubuntu only)
set -euo pipefail
umask 022   # readable for the player whatever the builder's umask (install-system.sh)
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${SRC:-$(cd "$HERE/../../.." && pwd)}
. "$SRC/lab/images/common/layers.sh"
ga_need base steam dotnet
GAME_ID=valheim SRC="$SRC" bash "$SRC/lab/images/common/install-gameanything.sh"
install -m 755 "$HERE/ga-valheim" /usr/local/bin/ga-valheim
# BepInEx 5 (LGPL-2.1; bundles HarmonyX / MonoMod / Cecil: MIT): the official Linux zip, checksum-pinned. ga-* unpacks it into the
# sandbox's copy of the game; the user's own BepInEx and plugins are never copied.
BEPINEX_VERSION=5.4.23.5
BEPINEX_SHA256=e538560be65739f562519ab518a75f9c65b3f57f87457403ae7cde683c12dab7
curl -fsSL --retry 3 -o "/opt/gameanything/vendor/BepInEx_linux_x64_${BEPINEX_VERSION}.zip" \
  "https://github.com/BepInEx/BepInEx/releases/download/v${BEPINEX_VERSION}/BepInEx_linux_x64_${BEPINEX_VERSION}.zip"
echo "${BEPINEX_SHA256}  /opt/gameanything/vendor/BepInEx_linux_x64_${BEPINEX_VERSION}.zip" | sha256sum -c -
printf 'BepInEx %s (LGPL-2.1) https://github.com/BepInEx/BepInEx sha256 %s\n' "$BEPINEX_VERSION" "$BEPINEX_SHA256" >> /opt/gameanything/vendor/VERSIONS
dotnet --list-sdks
