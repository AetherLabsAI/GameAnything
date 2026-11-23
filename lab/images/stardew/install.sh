#!/usr/bin/env bash
# The Stardew Valley game layer (run as root by lab/images/stardew/Dockerfile on gameanything-lab-dotnet; on a plain ubuntu:24.04, e.g. a
# docker-rt test sandbox, it installs the runtime layers base + steam + dotnet first). NO game files, no accounts, no keys: the user's
# game is mounted read-only at run time (or downloaded with Steam into the user's own volume).
#   SRC=<GameAnything checkout>   (default: the folder two levels up from this script)   PLAYER_UID=1000 (plain ubuntu only)
set -euo pipefail
umask 022   # readable for the player whatever the builder's umask (install-system.sh)
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${SRC:-$(cd "$HERE/../../.." && pwd)}
SMAPI_VERSION=${SMAPI_VERSION:-4.5.2}
SMAPI_SHA256=${SMAPI_SHA256:-dd01ddca7b566bfe0d3b3d2d03833496abc56c53da976241f2ab443f5484acc4}
CP_VERSION=${CP_VERSION:-2.9.1}
CP_SHA256=${CP_SHA256:-e54844cd296cf86b5b97f456b63cedaafcd2f0e362b630d8fb32215b95828bff}
. "$SRC/lab/images/common/layers.sh"
ga_need base steam dotnet
GAME_ID=stardew SRC="$SRC" bash "$SRC/lab/images/common/install-gameanything.sh"
# SMAPI (LGPL-3.0): the official installer zip, checksum-pinned. ga-sdv installs it into the sandbox's COPY of the game.
curl -fsSL --retry 3 -o "/opt/gameanything/vendor/SMAPI-${SMAPI_VERSION}-installer.zip" \
  "https://github.com/Pathoschild/SMAPI/releases/download/${SMAPI_VERSION}/SMAPI-${SMAPI_VERSION}-installer.zip"
echo "${SMAPI_SHA256}  /opt/gameanything/vendor/SMAPI-${SMAPI_VERSION}-installer.zip" | sha256sum -c -
printf 'SMAPI %s (LGPL-3.0) https://github.com/Pathoschild/SMAPI sha256 %s\n' "$SMAPI_VERSION" "$SMAPI_SHA256" >> /opt/gameanything/vendor/VERSIONS
# Content Patcher (MIT), for content packs (ContentPackFor: Pathoschild.ContentPatcher). Its built mod is only on Nexus (login needed),
# so the image carries the SOURCE of its release tag (checksum-pinned) and its NuGet packages; `ga-sdv layer` builds it offline against
# the sandbox's copy of the game + SMAPI (~15 s) and installs it into the layer's Mods/. 2.9.1 is C# 14 (`field`, nameof of an open
# generic): it needs the .NET 10 compiler, so this image adds Ubuntu's .NET SDK 10 next to the dotnet layer's SDK 8 (both net6.0 SMAPI
# mods build with either; the newest SDK is the default `dotnet`).
apt-get update
apt-get install -y --no-install-recommends dotnet-sdk-10.0
rm -rf /var/lib/apt/lists/*
CP=/opt/gameanything/vendor/ContentPatcher-${CP_VERSION}
curl -fsSL --retry 3 -o "$CP-src.tar.gz" "https://codeload.github.com/Pathoschild/StardewMods/tar.gz/refs/tags/content-patcher/${CP_VERSION}"
echo "${CP_SHA256}  $CP-src.tar.gz" | sha256sum -c -
# the restore needs no game files (ModBuildConfig looks for the game only when it builds): ModBuildConfig + the net6.0 reference packs
_t=$(mktemp -d); mkdir -p "$_t/src" "$_t/home"
tar xzf "$CP-src.tar.gz" -C "$_t/src" --strip-components=1 --wildcards '*/ContentPatcher/*' '*/Common/*' '*/Directory.Build.props' '*/Directory.Packages.props' '*/LICENSE'
echo '{"sdk": {"version": "10.0.100", "rollForward": "latestFeature"}}' > "$_t/src/global.json"
(cd "$_t/src" && HOME="$_t/home" NUGET_PACKAGES="$CP-nuget" DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 \
   dotnet restore ContentPatcher/ContentPatcher.csproj -nologo -v:q)
cp "$_t/src/LICENSE" "$CP-LICENSE"; rm -rf "$_t"
ls "$CP-nuget/pathoschild.stardew.modbuildconfig" >/dev/null
printf 'Content Patcher %s (MIT) https://github.com/Pathoschild/StardewMods tag content-patcher/%s source sha256 %s; built by ga-sdv layer\n' \
  "$CP_VERSION" "$CP_VERSION" "$CP_SHA256" >> /opt/gameanything/vendor/VERSIONS
printf '.NET SDK %s (MIT) Ubuntu dotnet-sdk-10.0, builds Content Patcher\n' "$(dotnet --list-sdks | awk '/^10\./{print $1}' | tail -1)" >> /opt/gameanything/vendor/VERSIONS
install -m 755 "$HERE/ga-sdv" /usr/local/bin/ga-sdv
dotnet --list-sdks
