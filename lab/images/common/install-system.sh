#!/usr/bin/env bash
# Layer "base" of every GameAnything sandbox image (lab/images/base/Dockerfile; also run by install-base.sh on a plain ubuntu:24.04):
#   the virtual screen (Xvfb, or Xorg on an NVIDIA GPU when the sandbox has one), x11vnc + the noVNC viewer, a silent PulseAudio sink,
#   ffmpeg, OpenGL / Vulkan (Mesa), SDL2 / OpenAL, fonts, Python 3, and the user `player`. No GameAnything yet: that is the game layer.
# NO game files, no accounts, no keys.
#   PLAYER_UID=1000                 the uid the game runs as (gameanything lab setup --image passes yours)
#   APT_SNAPSHOT=20261029T000000Z   pin every apt package to that day of snapshot.ubuntu.com ("" = the live archive)
#   EXTRA_APT="<more packages>"
set -euo pipefail
# every folder and file made here is for the player (uid 1000, or another uid with --user) to read: never inherit the builder's
# umask (an image server built with umask 077 on 2026-10-30: /opt/gameanything, /game, galab.py's folder root-only, ga-steam crashed)
umask 022
PLAYER_UID=${PLAYER_UID:-1000}
APT_SNAPSHOT=${APT_SNAPSHOT-}
export DEBIAN_FRONTEND=noninteractive

# 0. pin the archive: every later `apt-get update` (Steam, .NET, Java, Wine layers) reads the same snapshot, so a rebuild gets the same
#    package versions. The first fetch over https needs ca-certificates, which the bare image lacks: apt still checks every index
#    against Ubuntu's signing key, so only the transport is unverified for that one bootstrap install.
if [ -n "$APT_SNAPSHOT" ] && [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then
  sed -i -E "s#https?://(archive|security)\.ubuntu\.com/ubuntu/?#https://snapshot.ubuntu.com/ubuntu/${APT_SNAPSHOT}/#g" /etc/apt/sources.list.d/ubuntu.sources
  if [ ! -s /etc/ssl/certs/ca-certificates.crt ]; then
    apt-get -o Acquire::https::Verify-Peer=false update
    apt-get -o Acquire::https::Verify-Peer=false install -y --no-install-recommends ca-certificates
  fi
  mkdir -p /opt/gameanything && echo "$APT_SNAPSHOT" > /opt/gameanything/APT_SNAPSHOT
fi

# 1. screen, viewer, recorder, OpenGL + Vulkan (Mesa llvmpipe / lavapipe; the NVIDIA libraries come from the host with --gpus), sound, Python 3
apt-get update
# packages by the names this release has: Ubuntu 24.04 renamed some libraries (*t64); older releases (22.04) use the old name, and
# a package the release does not have at all is left out with a note (tested on 22.04 in the 2026-10-29 Steam download test)
pkgs() { local p q a; for p in "$@"; do q=${p%%:*}; a=${p#"$q"}
  if apt-cache show "$p" >/dev/null 2>&1; then echo "$p"; elif apt-cache show "${q%t64}$a" >/dev/null 2>&1; then echo "${q%t64}$a"
  else echo "[install] $p: not in this release, left out" >&2; fi; done; }
# shellcheck disable=SC2086
apt-get install -y --no-install-recommends $(pkgs \
  ca-certificates curl unzip zip xz-utils procps tini less file jq git \
  xvfb xserver-xorg-core x11vnc novnc websockify x11-utils x11-xserver-utils xdotool \
  libgl1 libgl1-mesa-dri libglu1-mesa libegl1 libglx-mesa0 libvulkan1 mesa-vulkan-drivers \
  libx11-6 libxext6 libxrandr2 libxi6 libxcursor1 libxinerama1 libxss1 libxxf86vm1 libxrender1 libxtst6 libxkbcommon-x11-0 \
  libsdl2-2.0-0 libasound2t64 libpulse0 libopenal1 \
  fonts-dejavu-core fonts-wqy-zenhei fonts-noto-cjk fonts-droid-fallback \
  pulseaudio pulseaudio-utils ffmpeg \
  python3 python3-venv python3-pip \
  ${EXTRA_APT:-})
rm -rf /var/lib/apt/lists/*
# Chinese text (our users write Chinese): Noto Sans CJK (+61 MB download) is the CJK font most programs and engines look for by name,
# Droid Sans Fallback a plain .ttf for engines that skip .ttc collections; wqy-zenhei alone (a .ttc) left a mod's banner as boxes (#45)
fc-cache -f >/dev/null 2>&1 || true

# 2. the user the game runs as; /sandbox is the writable volume, /game (and /saves) the read-only mount points
if ! id player >/dev/null 2>&1 || [ "$(id -u player)" != "$PLAYER_UID" ]; then
  if getent passwd "$PLAYER_UID" >/dev/null; then userdel -r "$(getent passwd "$PLAYER_UID" | cut -d: -f1)" 2>/dev/null || true; fi
  id player >/dev/null 2>&1 && userdel -r player 2>/dev/null || true
  useradd -m -u "$PLAYER_UID" -s /bin/bash player
fi
mkdir -p /game /saves /sandbox/home /opt/gameanything/vendor /opt/gameanything/smoke /opt/gameanything/layers && chown player:player /sandbox /sandbox/home
chmod 1777 /sandbox /sandbox/home     # an image run for another uid (docker run --user, gameanything/sandbox.py run_user_args) can write too
chmod 666 /etc/passwd /etc/group      # and gets its own account line from galab (ensure_account): Civ VI segfaults without one
echo "base $(date -u +%FT%TZ) uid=$PLAYER_UID snapshot=${APT_SNAPSHOT:-live}" > /opt/gameanything/layers/base
