#!/usr/bin/env bash
# The fex layer (lab/images/fex/Dockerfile): FEX-Emu + its x86 RootFS + the screen, sound and viewer + the Steam bootstrap, on arm64.
set -euo pipefail
umask 022
export DEBIAN_FRONTEND=noninteractive
[ "$(uname -m)" = aarch64 ] || { echo "[fex] this layer is for arm64 (Apple silicon); x86_64 hosts use the normal images" >&2; exit 1; }
apt-get update
apt-get install -y --no-install-recommends software-properties-common gpg-agent ca-certificates curl xz-utils squashfs-tools \
  xvfb x11-utils x11-xserver-utils openbox x11vnc novnc websockify dbus dbus-x11 pulseaudio pulseaudio-utils imagemagick python3 procps
add-apt-repository -y ppa:fex-emu/fex
apt-get update
apt-get install -y --no-install-recommends "$FEX_PACKAGE"
# the x86 RootFS (Ubuntu 24.04 with the 32-bit libraries Steam needs), extracted: a container has no FUSE to mount the image
mkdir -p /opt/fex-rootfs && curl -fsSL "$ROOTFS_URL" -o /tmp/rootfs.sqsh
unsquashfs -q -d /opt/fex-rootfs/Ubuntu_24_04 /tmp/rootfs.sqsh && rm -f /tmp/rootfs.sqsh
# the player (the same uid rule as the other images: PLAYER_UID)
if id -u ubuntu >/dev/null 2>&1 && [ "$(id -u ubuntu)" = "$PLAYER_UID" ]; then userdel -r ubuntu; fi
useradd -m -u "$PLAYER_UID" -s /bin/bash player
install -d -o player -g player /home/player/.config/fex-emu
printf '{"Config":{"RootFS":"/opt/fex-rootfs/Ubuntu_24_04"}}\n' > /home/player/.config/fex-emu/Config.json
chown player:player /home/player/.config/fex-emu/Config.json
# the Steam bootstrap (Valve's launcher package); ga-fex-up unpacks it into the home on the first start
mkdir -p /opt/steam-bootstrap && curl -fsSL https://repo.steampowered.com/steam/archive/stable/steam_latest.tar.gz -o /tmp/steam.tar.gz
tar xzf /tmp/steam.tar.gz -C /opt/steam-bootstrap --strip-components=1 steam-launcher/bootstraplinux_ubuntu12_32.tar.xz && rm -f /tmp/steam.tar.gz
install -m 755 /tmp/ga-layer/ga-fex-up /usr/local/bin/ga-fex-up
rm -rf /var/lib/apt/lists/*
test -x /usr/bin/FEXBash && test -d /opt/fex-rootfs/Ubuntu_24_04/lib/i386-linux-gnu && test -f /opt/steam-bootstrap/bootstraplinux_ubuntu12_32.tar.xz
mkdir -p /opt/gameanything/layers && echo "fex $(date -u +%FT%TZ) $(dpkg-query -W -f='${Version}' "$FEX_PACKAGE")" > /opt/gameanything/layers/fex
