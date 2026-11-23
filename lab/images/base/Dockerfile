# GameAnything sandbox images, shared layer "base" (every game image starts here): Ubuntu 24.04 pinned by digest, every apt package
# pinned to one day of snapshot.ubuntu.com, the virtual screen (Xvfb / Xorg on a GPU), x11vnc + noVNC, PulseAudio, ffmpeg, Mesa
# OpenGL + Vulkan, SDL2, fonts, Python 3, the user `player` (uid PLAYER_UID). NO game files, no accounts, no keys.
#   chain: base -> steam -> dotnet -> stardew | terraria | valheim | overcooked2 | ksp | cities ;  base -> steam -> civ6 ;
#          base -> java -> minecraft | sts (+ Steam) ;  base -> wine -> sims4                         (docs/sandbox-images.md)
#   gameanything lab setup --image <game>     pulls the published image; --build builds this chain locally for your own uid
#   (by hand, from the repository root: docker build -f lab/images/base/Dockerfile --build-arg PLAYER_UID=$(id -u) -t gameanything-lab-base .)
ARG UBUNTU=ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852
FROM ${UBUNTU}
ARG PLAYER_UID=1000
ARG APT_SNAPSHOT=20261029T000000Z
ENV LANG=C.UTF-8 TZ=UTC DEBIAN_FRONTEND=noninteractive
COPY lab/images/common/install-system.sh lab/images/common/ga-readable /tmp/ga-layer/
RUN umask 022 && PLAYER_UID=${PLAYER_UID} APT_SNAPSHOT=${APT_SNAPSHOT} bash /tmp/ga-layer/install-system.sh && sh /tmp/ga-layer/ga-readable && rm -rf /tmp/ga-layer
ENV HOME=/home/player DISPLAY=:99 SCREEN=1280x720x24 NOVNC_PORT=6080 GAMEANYTHING_IN_SANDBOX=1
LABEL org.gameanything.player-uid="${PLAYER_UID}" org.gameanything.apt-snapshot="${APT_SNAPSHOT}" org.gameanything.layer="base" \
      org.opencontainers.image.source="https://github.com/AetherLabsAI/GameAnything" \
      org.opencontainers.image.title="GameAnything sandbox base (runtime only)" \
      org.opencontainers.image.licenses="GPL-2.0-or-later AND LGPL-2.1-or-later AND MIT AND others (docs/sandbox-images.md)"
