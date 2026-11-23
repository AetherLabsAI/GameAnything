# GameAnything sandbox image for Overcooked! 2 (BepInEx): the RUNTIME ONLY (no game files inside).
#   BepInEx 5.4.23.5 (pinned, LGPL-2.1), .NET SDK 8, Unity's libraries, the Steam bootstrap, Xvfb / Xorg (GPU) + noVNC, ffmpeg, GameAnything + ga-oc2.
# The user brings the game: their Overcooked! 2 folder (the Linux build) mounted READ-ONLY, or downloaded with Steam in the sandbox. The sandbox writes only to /sandbox.
#
#   gameanything lab setup --image <game>     pulls ghcr.io/aetherlabsai/gameanything-lab-overcooked2 (private for now: docker login ghcr.io first);
#                                             --build builds base -> ... -> this image locally instead, for your own uid (PLAYER_UID)
#   (by hand, from the repository root, after the runtime layer: docker build -f lab/images/overcooked2/Dockerfile -t gameanything-lab-overcooked2 .)
#   docker run -d --name ga-oc2 -p 127.0.0.1:6080:6080 --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all \
#     -v "$HOME/.local/share/Steam/steamapps/common/Overcooked! 2":/game:ro -v ga-oc2:/sandbox gameanything-lab-overcooked2
#   docker exec ga-oc2 ga-oc2 layer && docker exec ga-oc2 gameanything native build --game overcooked2 --install /opt/gameanything/smoke/M2WSmoke
#   docker exec ga-oc2 ga-oc2 run            # needs Steam running in the sandbox (ga-steam start)
#
# What is inside and under which license: docs/sandbox-images.md. Never inside: game files, Steam / EA / Microsoft accounts, user data, API keys.
# x86_64 only (Apple silicon: Docker Desktop runs it under Rosetta).
ARG RUNTIME=gameanything-lab-dotnet
FROM ${RUNTIME}
# PLAYER_UID: the published images keep 1000 (another uid runs with --user: gameanything/sandbox.py run_argv); a local build passes yours
ARG PLAYER_UID=1000
USER root
COPY . /opt/gameanything/src
RUN umask 022 && PLAYER_UID=${PLAYER_UID} SRC=/opt/gameanything/src bash /opt/gameanything/src/lab/images/overcooked2/install.sh \
 && sh /opt/gameanything/src/lab/images/common/ga-readable && rm -rf /opt/gameanything/src
ENV GAMEANYTHING_OC2_DIR=/sandbox/game
LABEL org.gameanything.player-uid="${PLAYER_UID}" org.gameanything.game="overcooked2" \
      org.opencontainers.image.title="GameAnything Overcooked! 2 (BepInEx) sandbox (runtime only)" \
      org.opencontainers.image.description="BepInEx 5.4.23.5 (pinned, LGPL-2.1), .NET SDK 8, Unity's libraries, the Steam bootstrap, Xvfb / Xorg (GPU) + noVNC, ffmpeg, GameAnything + ga-oc2. No game files, no accounts." \
      org.opencontainers.image.licenses="Apache-2.0 AND LGPL-2.1-only AND MIT AND others (docs/sandbox-images.md)"
USER player
WORKDIR /home/player
VOLUME /sandbox
EXPOSE 6080
# up = the screen + viewer; then it waits (docker exec <container> ga-oc2 ... for the rest)
CMD ["/usr/bin/tini", "--", "bash", "-c", "ga-oc2 up && exec sleep infinity"]
