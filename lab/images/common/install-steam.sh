#!/usr/bin/env bash
# Layer "steam" (lab/images/steam/Dockerfile, on "base"; Slay the Spire runs it in its own layer): the Linux Steam client bootstrap, so
# the user can log in INSIDE the sandbox and download the Linux build of a game they own (wizard source "Steam download",
# docs/sandbox-images.md). Run as root.
# What it adds: i386 multiarch + Ubuntu's steam-installer (the bootstrap; the client itself is downloaded by Steam into the user's home
# on first start (~500 MB), under the Steam Subscriber Agreement that the user accepts by installing), the 32-bit libraries Steam needs, a D-Bus
# session, a small window manager (openbox) so the login window takes keyboard focus in the viewer, and ga-steam.
# NO account, no login data: the login cache and the downloaded games live in the user's sandbox volume (HOME=/home/player and
# ~/.steam/debian-installation/steamapps are volumes), so the second start needs no new login and no new download.
set -euo pipefail
umask 022   # readable for the player whatever the builder's umask (install-system.sh)
HERE=$(cd "$(dirname "$0")" && pwd)
# arm64 (Apple silicon): no i386 packages, and the 32-bit client crashes under qemu; Steam runs under FEX-Emu there instead
if [ "$(uname -m)" = aarch64 ]; then exec bash "$HERE/install-steam-fex.sh"; fi
export DEBIAN_FRONTEND=noninteractive
dpkg --add-architecture i386
# Ubuntu asks for the Steam license in debconf; the user who builds the image with STEAM=1 is the one installing Steam
echo 'steam steam/question select I AGREE' | debconf-set-selections
echo 'steam steam/license note ""' | debconf-set-selections
apt-get update
# packages by the names this release has: Ubuntu 24.04 renamed some libraries (*t64); older releases (22.04) use the old name, and
# a package the release does not have at all is left out with a note (tested on 22.04 for the 2026-10-29 Steam download test)
pkgs() { local p q a; for p in "$@"; do q=${p%%:*}; a=${p#"$q"}
  if apt-cache show "$p" >/dev/null 2>&1; then echo "$p"; elif apt-cache show "${q%t64}$a" >/dev/null 2>&1; then echo "${q%t64}$a"
  else echo "[install] $p: not in this release, left out" >&2; fi; done; }
apt-get install -y --no-install-recommends $(pkgs \
  steam-installer steam-libs-amd64 steam-libs-i386:i386 \
  libgl1:i386 libgl1-mesa-dri:i386 libglx-mesa0:i386 libegl1:i386 libvulkan1 libvulkan1:i386 mesa-vulkan-drivers mesa-vulkan-drivers:i386 \
  libnss3 libatk1.0-0t64 libatk-bridge2.0-0t64 libgtk-3-0t64 libgbm1 libxss1 libxtst6 libxcomposite1 libxdamage1 \
  dbus dbus-x11 xdg-utils zenity openbox python3 procps xz-utils libudev1)
rm -rf /var/lib/apt/lists/*
install -m 755 "$HERE/ga-steam" /usr/local/bin/ga-steam
# The steamapps volume mounts INSIDE the home volume: folders missing from the image are created by Docker as root, and Steam (the
# player) cannot write there (plain Docker on Linux, 2026-10-29: "ln: failed to create symbolic link '/home/player/.steam/steam':
# Permission denied"). Made here, a new volume takes the player's ownership from the image.
install -d -o player -g player /home/player/.steam /home/player/.steam/debian-installation /home/player/.steam/debian-installation/steamapps
# The same for a pulled image run for another uid (run_user_args: --user <uid>, HOME=/sandbox/home): writable for every uid, like /sandbox/home
if [ -d /sandbox/home ]; then
  install -d -o player -g player -m 1777 /sandbox/home/.steam /sandbox/home/.steam/debian-installation /sandbox/home/.steam/debian-installation/steamapps
fi
test -x /usr/games/steam
mkdir -p /opt/gameanything/layers && echo "steam $(date -u +%FT%TZ) $(dpkg-query -W -f='${Version}' steam-installer)" > /opt/gameanything/layers/steam
