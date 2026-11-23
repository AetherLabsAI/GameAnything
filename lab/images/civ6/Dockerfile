# GameAnything sandbox image for Civilization VI: the RUNTIME ONLY (no game files inside).
#   the Steam bootstrap, Vulkan / OpenGL (Mesa; the GPU from the host), Xvfb / Xorg (GPU) + noVNC, ffmpeg, GameAnything + ga-civ6 (mods are XML / Lua / SQL: nothing to compile).
# The user brings the game: their Civilization VI folder (Aspyr's Linux build) mounted READ-ONLY, or downloaded with Steam in the sandbox (the Take-Two EULA is the user's to accept); the game needs Steam running. The sandbox writes only to /sandbox.
#
#   gameanything lab setup --image <game>     pulls ghcr.io/aetherlabsai/gameanything-lab-civ6 (private for now: docker login ghcr.io first);
#                                             --build builds base -> ... -> this image locally instead, for your own uid (PLAYER_UID)
#   (by hand, from the repository root, after the runtime layer: docker build -f lab/images/civ6/Dockerfile -t gameanything-lab-civ6 .)
#   docker run -d --name ga-civ6 -p 127.0.0.1:6080:6080 --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all \
#     -v "$HOME/.local/share/Steam/steamapps/common/Sid Meier's Civilization VI":/game:ro -v ga-civ6:/sandbox gameanything-lab-civ6
#   docker exec ga-civ6 ga-civ6 layer && docker exec ga-civ6 ga-civ6 run            # needs Steam running in the sandbox (ga-steam start)
#
# What is inside and under which license: docs/sandbox-images.md. Never inside: game files, Steam / EA / Microsoft accounts, user data, API keys.
# x86_64 only (Apple silicon: Docker Desktop runs it under Rosetta).
ARG RUNTIME=gameanything-lab-steam
FROM ${RUNTIME}
# PLAYER_UID: the published images keep 1000 (another uid runs with --user: gameanything/sandbox.py run_argv); a local build passes yours
ARG PLAYER_UID=1000
USER root
COPY . /opt/gameanything/src
RUN umask 022 && PLAYER_UID=${PLAYER_UID} SRC=/opt/gameanything/src bash /opt/gameanything/src/lab/images/civ6/install.sh \
 && sh /opt/gameanything/src/lab/images/common/ga-readable && rm -rf /opt/gameanything/src
# SCREEN: the base image sets 1280x720, where the 2K agreement's Agree button is off the window (ga-civ6's own default never applied)
ENV GAMEANYTHING_CIV6_DIR=/sandbox/game SCREEN=1600x900x24
LABEL org.gameanything.player-uid="${PLAYER_UID}" org.gameanything.game="civ6" \
      org.opencontainers.image.title="GameAnything Civilization VI sandbox (runtime only)" \
      org.opencontainers.image.description="the Steam bootstrap, Vulkan / OpenGL (Mesa; the GPU from the host), Xvfb / Xorg (GPU) + noVNC, ffmpeg, GameAnything + ga-civ6 (mods are XML / Lua / SQL: nothing to compile). No game files, no accounts." \
      org.opencontainers.image.licenses="Apache-2.0 AND MIT AND others (docs/sandbox-images.md)"
USER player
WORKDIR /home/player
VOLUME /sandbox
EXPOSE 6080
# up = the screen + viewer; then it waits (docker exec <container> ga-civ6 ... for the rest)
CMD ["/usr/bin/tini", "--", "bash", "-c", "ga-civ6 up && exec sleep infinity"]
