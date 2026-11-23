# GameAnything sandbox image for Terraria (tModLoader): the RUNTIME ONLY (no game files inside).
#   .NET SDK 8 (tModLoader builds mods with it), FNA's native libraries, the Steam bootstrap, Xvfb + noVNC, ffmpeg, GameAnything + ga-terraria.
# The user brings the game: their tModLoader folder (the free Steam app 1281930, Linux build) mounted READ-ONLY, or both apps downloaded with Steam in the sandbox; Terraria itself must be owned on Steam. The sandbox writes only to /sandbox.
#
#   gameanything lab setup --image <game>     pulls ghcr.io/aetherlabsai/gameanything-lab-terraria (private for now: docker login ghcr.io first);
#                                             --build builds base -> ... -> this image locally instead, for your own uid (PLAYER_UID)
#   (by hand, from the repository root, after the runtime layer: docker build -f lab/images/terraria/Dockerfile -t gameanything-lab-terraria .)
#   S="$HOME/.local/share/Steam/steamapps/common"
#   docker run -d --name ga-terraria -p 127.0.0.1:6080:6080 -v "$S/tModLoader":/game:ro -v ga-terraria:/sandbox gameanything-lab-terraria
#   docker exec ga-terraria ga-terraria layer && docker exec ga-terraria ga-terraria run     # needs Steam running in the sandbox (ga-steam start)
#
# What is inside and under which license: docs/sandbox-images.md. Never inside: game files, Steam / EA / Microsoft accounts, user data, API keys.
# x86_64 only (Apple silicon: Docker Desktop runs it under Rosetta).
ARG RUNTIME=gameanything-lab-dotnet
FROM ${RUNTIME}
# PLAYER_UID: the published images keep 1000 (another uid runs with --user: gameanything/sandbox.py run_argv); a local build passes yours
ARG PLAYER_UID=1000
USER root
COPY . /opt/gameanything/src
RUN umask 022 && PLAYER_UID=${PLAYER_UID} SRC=/opt/gameanything/src bash /opt/gameanything/src/lab/images/terraria/install.sh \
 && sh /opt/gameanything/src/lab/images/common/ga-readable && rm -rf /opt/gameanything/src
ENV GAMEANYTHING_TERRARIA_DIR=/sandbox/game GAMEANYTHING_TERRARIA_USER_DIR=/sandbox/saves
LABEL org.gameanything.player-uid="${PLAYER_UID}" org.gameanything.game="terraria" \
      org.opencontainers.image.title="GameAnything Terraria (tModLoader) sandbox (runtime only)" \
      org.opencontainers.image.description=".NET SDK 8 (tModLoader builds mods with it), FNA's native libraries, the Steam bootstrap, Xvfb + noVNC, ffmpeg, GameAnything + ga-terraria. No game files, no accounts." \
      org.opencontainers.image.licenses="Apache-2.0 AND MIT AND others (docs/sandbox-images.md)"
USER player
WORKDIR /home/player
VOLUME /sandbox
EXPOSE 6080
# up = the screen + viewer; then it waits (docker exec <container> ga-terraria ... for the rest)
CMD ["/usr/bin/tini", "--", "bash", "-c", "ga-terraria up && exec sleep infinity"]
