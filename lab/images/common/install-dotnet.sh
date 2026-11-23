#!/usr/bin/env bash
# Layer "dotnet" (lab/images/dotnet/Dockerfile, on top of "steam"): .NET SDK 8 from the Ubuntu archive (Ubuntu's source build, MIT) and
# what Unity / FNA / MonoGame games load: ICU, libgdiplus, GTK 3, NSS, udev. Builds SMAPI mods (net6.0), tModLoader mods (net8.0),
# BepInEx plugins (net35 / net462 / netstandard2.0 against the game's own Managed/ assemblies), KSP plugins (net472) and Cities: Skylines
# mods (net35). NO game files.
set -euo pipefail
umask 022   # readable for the player whatever the builder's umask (install-system.sh)
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  dotnet-sdk-8.0 libicu74 libgdiplus \
  libgtk-3-0t64 libudev1 libxcomposite1 libxdamage1 libnss3 libglib2.0-0t64
rm -rf /var/lib/apt/lists/*
dotnet --list-sdks
mkdir -p /opt/gameanything/layers && echo "dotnet $(date -u +%FT%TZ) $(dotnet --list-sdks | tr '\n' ' ')" > /opt/gameanything/layers/dotnet
