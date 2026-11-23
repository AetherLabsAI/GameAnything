# GameAnything sandbox image for Slay the Spire: the RUNTIME ONLY (no game files inside).
#   OpenJDK 25 (javac --release 8 for ModTheSpire mods), the Steam bootstrap, Xvfb + noVNC, ffmpeg, GameAnything + ga-sts.
# The user brings the game: their Slay the Spire folder (the Linux build) and the Workshop folder with ModTheSpire + BaseMod, both READ-ONLY. The sandbox writes only to /sandbox.
#
#   gameanything lab setup --image <game>     pulls ghcr.io/aetherlabsai/gameanything-lab-sts (private for now: docker login ghcr.io first);
#                                             --build builds base -> ... -> this image locally instead, for your own uid (PLAYER_UID)
#   (by hand, from the repository root, after the runtime layer: docker build -f lab/images/sts/Dockerfile -t gameanything-lab-sts .)
#   S="$HOME/.local/share/Steam/steamapps"
#   docker run -d --name ga-sts -p 127.0.0.1:6080:6080 -v "$S/common/SlayTheSpire":/game:ro -v "$S/workshop/content/646570":/workshop:ro \
#     -v ga-sts:/sandbox gameanything-lab-sts
#   docker exec ga-sts ga-sts layer && docker exec ga-sts gameanything native build --game slay_the_spire --install /opt/gameanything/smoke/M2WSmoke
#   docker exec ga-sts ga-sts run            # a 2D game: no GPU needed
#
# What is inside and under which license: docs/sandbox-images.md. Never inside: game files, Steam / EA / Microsoft accounts, user data, API keys.
# x86_64 only (Apple silicon: Docker Desktop runs it under Rosetta).
ARG RUNTIME=gameanything-lab-java
FROM ${RUNTIME}
# PLAYER_UID: the published images keep 1000 (another uid runs with --user: gameanything/sandbox.py run_argv); a local build passes yours
ARG PLAYER_UID=1000
USER root
COPY . /opt/gameanything/src
RUN umask 022 && PLAYER_UID=${PLAYER_UID} SRC=/opt/gameanything/src bash /opt/gameanything/src/lab/images/sts/install.sh \
 && sh /opt/gameanything/src/lab/images/common/ga-readable && rm -rf /opt/gameanything/src
ENV GAMEANYTHING_STS_DIR=/sandbox/game
LABEL org.gameanything.player-uid="${PLAYER_UID}" org.gameanything.game="sts" \
      org.opencontainers.image.title="GameAnything Slay the Spire sandbox (runtime only)" \
      org.opencontainers.image.description="OpenJDK 25 (javac --release 8 for ModTheSpire mods), the Steam bootstrap, Xvfb + noVNC, ffmpeg, GameAnything + ga-sts. No game files, no accounts." \
      org.opencontainers.image.licenses="Apache-2.0 AND GPL-2.0-only WITH Classpath-exception-2.0 AND others (docs/sandbox-images.md)"
USER player
WORKDIR /home/player
VOLUME /sandbox
EXPOSE 6080
# up = the screen + viewer; then it waits (docker exec <container> ga-sts ... for the rest)
CMD ["/usr/bin/tini", "--", "bash", "-c", "ga-sts up && exec sleep infinity"]
