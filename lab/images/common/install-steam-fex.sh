#!/usr/bin/env bash
# Layer "steam" on arm64 (Apple silicon Macs, Docker Desktop linux/arm64; install-steam.sh hands over to this script there). EXPERIMENTAL
# (2026-10-31). The Steam client is a 32-bit x86 program: on Apple silicon the x86 images fell to qemu-i386 and Steam crashed (signal 11)
# after every self-update (docs/sandbox-hiccups.md M5). FEX-Emu runs 32- and 64-bit x86 programs on arm64 (F1-F9 there): with it Steam
# signs in and downloads, and Slay the Spire (ModTheSpire) and Stardew Valley (SMAPI) ran with the smoke mod on her Mac.
# What it adds: FEX-Emu (Launchpad ppa:fex-emu/fex, MIT), FEX's Ubuntu 24.04 x86 RootFS (extracted: a container has no FUSE), Valve's
# Steam bootstrap (the client itself downloads into the user's home on first start, under the Steam Subscriber Agreement), and
#   /usr/games/steam   the same command as Ubuntu's steam-installer: unpacks the bootstrap into ~/.steam/debian-installation (the layout
#                      ga-steam reads) and runs steam.sh under FEX
#   ga-x86             runs an x86 program under FEX (the game tools put it in front of the game: galab.x86, ga-sdv)
#   ga-steam           as on x86
# The mods are still built natively (the arm64 .NET SDK / OpenJDK of the dotnet / java layers): only the games and Steam are emulated.
# NO account, no login data, no game files.
set -euo pipefail
umask 022
HERE=$(cd "$(dirname "$0")" && pwd)
FEX_PACKAGE=${FEX_PACKAGE:-fex-emu-armv8.4}
ROOTFS_URL=${ROOTFS_URL:-https://rootfs.fex-emu.gg/Ubuntu_24_04/2026-08-11/Ubuntu_24_04.sqsh}
ROOTFS=/opt/fex-rootfs/Ubuntu_24_04
export DEBIAN_FRONTEND=noninteractive
[ "$(uname -m)" = aarch64 ] || { echo "[steam-fex] this layer is for arm64 (Apple silicon); x86_64 uses install-steam.sh" >&2; exit 1; }
apt-get update
# native: the D-Bus session, the window manager (the sign-in window takes keyboard focus), xrandr (LWJGL 2 games call it, F5)
apt-get install -y --no-install-recommends software-properties-common gpg-agent ca-certificates curl xz-utils squashfs-tools \
  dbus dbus-x11 xdg-utils openbox x11-xserver-utils python3 procps
add-apt-repository -y ppa:fex-emu/fex
apt-get update
apt-get install -y --no-install-recommends "$FEX_PACKAGE"
rm -rf /var/lib/apt/lists/*
mkdir -p /opt/fex-rootfs && curl -fsSL "$ROOTFS_URL" -o /tmp/rootfs.sqsh
unsquashfs -q -d "$ROOTFS" /tmp/rootfs.sqsh && rm -f /tmp/rootfs.sqsh
mkdir -p /opt/steam-bootstrap && curl -fsSL https://repo.steampowered.com/steam/archive/stable/steam_latest.tar.gz -o /tmp/steam.tar.gz
tar xzf /tmp/steam.tar.gz -C /opt/steam-bootstrap --strip-components=1 steam-launcher/bootstraplinux_ubuntu12_32.tar.xz && rm -f /tmp/steam.tar.gz

# FEX finds the RootFS by FEX_ROOTFS (F1: the fetcher's "set as default" wrote no Config.json); .NET 7+ under FEX needs W^X off (F7:
# tModLoader spun at 100 % CPU without it). Both set by the two commands, so any uid (docker run --user) works without a config file.
cat > /usr/local/bin/ga-x86 <<EOF
#!/bin/sh
# ga-x86 PROGRAM [ARGS]: run an x86 program under FEX-Emu (lab/images/common/install-steam-fex.sh)
export FEX_ROOTFS=\${FEX_ROOTFS:-$ROOTFS} DOTNET_EnableWriteXorExecute=0
exec FEX "\$@"
EOF
cat > /usr/games/steam <<EOF
#!/bin/sh
# Steam under FEX-Emu, in Ubuntu steam-installer's layout (~/.steam/debian-installation) so ga-steam finds everything where it looks
export FEX_ROOTFS=\${FEX_ROOTFS:-$ROOTFS} DOTNET_EnableWriteXorExecute=0
R=\${GA_STEAM_ROOT:-\$HOME/.steam/debian-installation}
if [ ! -x "\$R/steam.sh" ]; then mkdir -p "\$R" && tar xJf /opt/steam-bootstrap/bootstraplinux_ubuntu12_32.tar.xz -C "\$R"; fi
exec FEXBash -c 'cd "\$0" && exec ./steam.sh "\$@"' "\$R" "\$@"
EOF
chmod 755 /usr/local/bin/ga-x86 /usr/games/steam
install -m 755 "$HERE/ga-steam" /usr/local/bin/ga-steam
install -d -o player -g player /home/player/.steam /home/player/.steam/debian-installation /home/player/.steam/debian-installation/steamapps
if [ -d /sandbox/home ]; then
  install -d -o player -g player -m 1777 /sandbox/home/.steam /sandbox/home/.steam/debian-installation /sandbox/home/.steam/debian-installation/steamapps
fi
[ "$(FEX_ROOTFS=$ROOTFS FEXBash -c 'uname -m')" = x86_64 ] && test -d "$ROOTFS/lib/i386-linux-gnu"
mkdir -p /opt/gameanything/layers
echo "steam $(date -u +%FT%TZ) fex=$(dpkg-query -W -f='${Version}' "$FEX_PACKAGE")" > /opt/gameanything/layers/steam
echo "fex $(date -u +%FT%TZ) $(dpkg-query -W -f='${Version}' "$FEX_PACKAGE")" > /opt/gameanything/layers/fex
