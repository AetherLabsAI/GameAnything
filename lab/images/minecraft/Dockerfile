# GameAnything sandbox image for Minecraft: Java Edition: the RUNTIME ONLY (no game files inside).
#   OpenJDK 25, Xvfb / Xorg (GPU) + noVNC, ffmpeg, GameAnything + ga-mc (starts the user's own Fabric profile offline).
# The user brings the game: their .minecraft (with a Fabric profile) mounted READ-ONLY, or the files downloaded with their Microsoft account (ga-mc download). The sandbox writes only to /sandbox.
#
#   gameanything lab setup --image <game>     pulls ghcr.io/aetherlabsai/gameanything-lab-minecraft (private for now: docker login ghcr.io first);
#                                             --build builds base -> ... -> this image locally instead, for your own uid (PLAYER_UID)
#   (by hand, from the repository root, after the runtime layer: docker build -f lab/images/minecraft/Dockerfile -t gameanything-lab-minecraft .)
#   docker run -d --name ga-mc -p 127.0.0.1:6080:6080 --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all \
#     -v "$HOME/.minecraft":/game:ro -v ga-mc:/sandbox gameanything-lab-minecraft
#   docker exec ga-mc ga-mc layer && docker exec ga-mc gameanything native build --game minecraft --install /opt/gameanything/smoke/M2WSmoke
#   docker exec ga-mc ga-mc run --world "<a world>"     # Minecraft 26.x needs a GPU
#
# What is inside and under which license: docs/sandbox-images.md. Never inside: game files, Steam / EA / Microsoft accounts, user data, API keys.
# x86_64 only (Apple silicon: Docker Desktop runs it under Rosetta).
ARG RUNTIME=gameanything-lab-java
FROM ${RUNTIME}
# PLAYER_UID: the published images keep 1000 (another uid runs with --user: gameanything/sandbox.py run_argv); a local build passes yours
ARG PLAYER_UID=1000
USER root
COPY . /opt/gameanything/src
RUN umask 022 && PLAYER_UID=${PLAYER_UID} SRC=/opt/gameanything/src bash /opt/gameanything/src/lab/images/minecraft/install.sh \
 && sh /opt/gameanything/src/lab/images/common/ga-readable && rm -rf /opt/gameanything/src
ENV GAMEANYTHING_MINECRAFT_DIR=/sandbox/game
LABEL org.gameanything.player-uid="${PLAYER_UID}" org.gameanything.game="minecraft" \
      org.opencontainers.image.title="GameAnything Minecraft: Java Edition sandbox (runtime only)" \
      org.opencontainers.image.description="OpenJDK 25, Xvfb / Xorg (GPU) + noVNC, ffmpeg, GameAnything + ga-mc (starts the user's own Fabric profile offline). No game files, no accounts." \
      org.opencontainers.image.licenses="Apache-2.0 AND GPL-2.0-only WITH Classpath-exception-2.0 AND others (docs/sandbox-images.md)"
USER player
WORKDIR /home/player
VOLUME /sandbox
EXPOSE 6080
# up = the screen + viewer; then it waits (docker exec <container> ga-mc ... for the rest)
CMD ["/usr/bin/tini", "--", "bash", "-c", "ga-mc up && exec sleep infinity"]
