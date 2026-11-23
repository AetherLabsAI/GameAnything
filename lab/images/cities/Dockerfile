# GameAnything sandbox image for Cities: Skylines: the RUNTIME ONLY (no game files inside).
#   .NET SDK 8 (mod DLLs, net35 against the game's own Managed/), Unity's libraries, the Steam bootstrap, Xvfb / Xorg (GPU) + noVNC, ffmpeg, GameAnything + ga-cities.
# The user brings the game: their Cities: Skylines folder (the Linux build) mounted READ-ONLY, or downloaded with Steam in the sandbox (the Paradox User Agreement is the user's to accept); the game needs Steam running. The sandbox writes only to /sandbox.
#
#   gameanything lab setup --image <game>     pulls ghcr.io/aetherlabsai/gameanything-lab-cities (private for now: docker login ghcr.io first);
#                                             --build builds base -> ... -> this image locally instead, for your own uid (PLAYER_UID)
#   (by hand, from the repository root, after the runtime layer: docker build -f lab/images/cities/Dockerfile -t gameanything-lab-cities .)
#   docker run -d --name ga-cities -p 127.0.0.1:6080:6080 --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all \
#     -v "$HOME/.local/share/Steam/steamapps/common/Cities_Skylines":/game:ro -v ga-cities:/sandbox gameanything-lab-cities
#   docker exec ga-cities ga-cities layer && docker exec ga-cities ga-cities run      # needs Steam running in the sandbox (ga-steam start)
#
# What is inside and under which license: docs/sandbox-images.md. Never inside: game files, Steam / EA / Microsoft accounts, user data, API keys.
# x86_64 only (Apple silicon: Docker Desktop runs it under Rosetta).
ARG RUNTIME=gameanything-lab-dotnet
FROM ${RUNTIME}
# PLAYER_UID: the published images keep 1000 (another uid runs with --user: gameanything/sandbox.py run_argv); a local build passes yours
ARG PLAYER_UID=1000
USER root
COPY . /opt/gameanything/src
RUN umask 022 && PLAYER_UID=${PLAYER_UID} SRC=/opt/gameanything/src bash /opt/gameanything/src/lab/images/cities/install.sh \
 && sh /opt/gameanything/src/lab/images/common/ga-readable && rm -rf /opt/gameanything/src
ENV GAMEANYTHING_CITIES_DIR=/sandbox/game
LABEL org.gameanything.player-uid="${PLAYER_UID}" org.gameanything.game="cities" \
      org.opencontainers.image.title="GameAnything Cities: Skylines sandbox (runtime only)" \
      org.opencontainers.image.description=".NET SDK 8 (mod DLLs, net35 against the game's own Managed/), Unity's libraries, the Steam bootstrap, Xvfb / Xorg (GPU) + noVNC, ffmpeg, GameAnything + ga-cities. No game files, no accounts." \
      org.opencontainers.image.licenses="Apache-2.0 AND MIT AND others (docs/sandbox-images.md)"
USER player
WORKDIR /home/player
VOLUME /sandbox
EXPOSE 6080
# up = the screen + viewer; then it waits (docker exec <container> ga-cities ... for the rest)
CMD ["/usr/bin/tini", "--", "bash", "-c", "ga-cities up && exec sleep infinity"]
