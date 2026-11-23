# GameAnything sandbox image for The Sims 4 (Wine + DXVK + EA App): the RUNTIME ONLY (no game files inside).
#   Wine 11.19 (WoW64) + wine-mono + wine-gecko + DXVK 3.1.1 (all pinned), CPython 3.7 (script mods), Xvfb / Xorg (GPU) + noVNC, ffmpeg, GameAnything + ga-ea + ga-sims4.
# The user brings the game: the Windows build: downloaded with their own EA account by the EA App in the sandbox (ga-ea; the EA App installer is fetched from EA into the user's volume, never in the image), or their Windows install mounted READ-ONLY. The sandbox writes only to /sandbox.
#
#   gameanything lab setup --image <game>     pulls ghcr.io/aetherlabsai/gameanything-lab-sims4 (private for now: docker login ghcr.io first);
#                                             --build builds base -> ... -> this image locally instead, for your own uid (PLAYER_UID)
#   (by hand, from the repository root, after the runtime layer: docker build -f lab/images/sims4/Dockerfile -t gameanything-lab-sims4 .)
#   docker run -d --name ga-sims4 -p 127.0.0.1:6080:6080 --shm-size 1g --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all -v ga-sims4:/sandbox gameanything-lab-sims4
#   docker exec ga-sims4 ga-sims4 up && docker exec ga-sims4 ga-ea setup && docker exec ga-sims4 ga-ea install-app   # the user clicks EA's agreement
#   gameanything lab login ea --container ga-sims4     # sign in (the user types it in the viewer), then download The Sims 4 in the EA App
#
# What is inside and under which license: docs/sandbox-images.md. Never inside: game files, Steam / EA / Microsoft accounts, user data, API keys.
# x86_64 only (Apple silicon: Docker Desktop runs it under Rosetta).
ARG RUNTIME=gameanything-lab-wine
FROM ${RUNTIME}
# PLAYER_UID: the published images keep 1000 (another uid runs with --user: gameanything/sandbox.py run_argv); a local build passes yours
ARG PLAYER_UID=1000
USER root
COPY . /opt/gameanything/src
RUN umask 022 && PLAYER_UID=${PLAYER_UID} SRC=/opt/gameanything/src bash /opt/gameanything/src/lab/images/sims4/install.sh \
 && sh /opt/gameanything/src/lab/images/common/ga-readable && rm -rf /opt/gameanything/src
ENV GA_EA_HOME=/sandbox/ea WINEPREFIX=/sandbox/ea/pfx USER=player     GAMEANYTHING_SIMS4_DIR="/sandbox/ea/pfx/drive_c/users/player/Documents/Electronic Arts/The Sims 4"     GAMEANYTHING_SIMS4_GAME_DIR="/sandbox/ea/pfx/drive_c/Program Files/EA Games/The Sims 4"
LABEL org.gameanything.player-uid="${PLAYER_UID}" org.gameanything.game="sims4" \
      org.opencontainers.image.title="GameAnything The Sims 4 (Wine + DXVK + EA App) sandbox (runtime only)" \
      org.opencontainers.image.description="Wine 11.19 (WoW64) + wine-mono + wine-gecko + DXVK 3.1.1 (all pinned), CPython 3.7 (script mods), Xvfb / Xorg (GPU) + noVNC, ffmpeg, GameAnything + ga-ea + ga-sims4. No game files, no accounts." \
      org.opencontainers.image.licenses="Apache-2.0 AND LGPL-2.1-or-later AND Zlib AND MPL-2.0 AND PSF-2.0 AND others (docs/sandbox-images.md)"
USER player
WORKDIR /home/player
VOLUME /sandbox
EXPOSE 6080
# up = the screen + viewer; then it waits (docker exec <container> ga-sims4 ... for the rest)
CMD ["/usr/bin/tini", "--", "bash", "-c", "ga-sims4 up && exec sleep infinity"]
