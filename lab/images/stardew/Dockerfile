# GameAnything sandbox image for Stardew Valley: the RUNTIME ONLY (no game files inside).
#   SMAPI 4.5.2 installer (pinned), the Content Patcher 2.9.1 source (pinned; ga-sdv layer builds it), .NET SDK 8 + 10, the Steam bootstrap, Xvfb + x11vnc + noVNC, PulseAudio, ffmpeg, GameAnything + ga-sdv.
# The user brings the game: their own Stardew Valley folder (the Linux build) mounted READ-ONLY, or the Linux build downloaded with Steam in the sandbox. The sandbox writes only to /sandbox.
#
#   gameanything lab setup --image <game>     pulls ghcr.io/aetherlabsai/gameanything-lab-stardew (private for now: docker login ghcr.io first);
#                                             --build builds base -> ... -> this image locally instead, for your own uid (PLAYER_UID)
#   (by hand, from the repository root, after the runtime layer: docker build -f lab/images/stardew/Dockerfile -t gameanything-lab-stardew .)
#   docker run -d --name ga-stardew -p 127.0.0.1:6080:6080 \
#     -v "$HOME/.local/share/Steam/steamapps/common/Stardew Valley":/game:ro \
#     -v "$HOME/.config/StardewValley":/saves:ro -v ga-stardew:/sandbox gameanything-lab-stardew
#   docker exec ga-stardew ga-sdv layer      # private copy + pinned SMAPI + Content Patcher, your folder untouched
#   docker exec ga-stardew gameanything native build --game stardew --install /opt/gameanything/smoke/M2WSmoke
#   docker exec ga-stardew ga-sdv run        # then open http://localhost:6080/vnc.html
#
# What is inside and under which license: docs/sandbox-images.md. Never inside: game files, Steam / EA / Microsoft accounts, user data, API keys.
# x86_64 only (Apple silicon: Docker Desktop runs it under Rosetta).
ARG RUNTIME=gameanything-lab-dotnet
FROM ${RUNTIME}
# PLAYER_UID: the published images keep 1000 (another uid runs with --user: gameanything/sandbox.py run_argv); a local build passes yours
ARG PLAYER_UID=1000
USER root
COPY . /opt/gameanything/src
RUN umask 022 && PLAYER_UID=${PLAYER_UID} SRC=/opt/gameanything/src bash /opt/gameanything/src/lab/images/stardew/install.sh \
 && sh /opt/gameanything/src/lab/images/common/ga-readable && rm -rf /opt/gameanything/src
ENV GAMEANYTHING_STARDEW_DIR=/sandbox/game
LABEL org.gameanything.player-uid="${PLAYER_UID}" org.gameanything.game="stardew" \
      org.opencontainers.image.title="GameAnything Stardew Valley sandbox (runtime only)" \
      org.opencontainers.image.description="SMAPI 4.5.2 installer (pinned), Content Patcher 2.9.1 source (pinned), .NET SDK 8 + 10, the Steam bootstrap, Xvfb + x11vnc + noVNC, PulseAudio, ffmpeg, GameAnything + ga-sdv. No game files, no accounts." \
      org.opencontainers.image.licenses="Apache-2.0 AND LGPL-3.0-only AND MIT AND others (docs/sandbox-images.md)"
USER player
WORKDIR /home/player
VOLUME /sandbox
EXPOSE 6080
# up = the screen + viewer; then it waits (docker exec <container> ga-sdv ... for the rest)
CMD ["/usr/bin/tini", "--", "bash", "-c", "ga-sdv up && exec sleep infinity"]
