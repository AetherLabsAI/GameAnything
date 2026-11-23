# GameAnything sandbox image for Kerbal Space Program: the RUNTIME ONLY (no game files inside).
#   .NET SDK 8 (plugins against the game's own assemblies), Unity's libraries, the Steam bootstrap, Xvfb / Xorg (GPU) + noVNC, ffmpeg, GameAnything + ga-ksp.
# The user brings the game: their own KSP 1 folder (the Linux build) mounted READ-ONLY, or downloaded with Steam in the sandbox. The sandbox writes only to /sandbox.
#
#   gameanything lab setup --image <game>     pulls ghcr.io/aetherlabsai/gameanything-lab-ksp (private for now: docker login ghcr.io first);
#                                             --build builds base -> ... -> this image locally instead, for your own uid (PLAYER_UID)
#   (by hand, from the repository root, after the runtime layer: docker build -f lab/images/ksp/Dockerfile -t gameanything-lab-ksp .)
#   docker run -d --name ga-ksp -p 127.0.0.1:6080:6080 --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all \
#     -v "$HOME/.local/share/Steam/steamapps/common/Kerbal Space Program":/game:ro -v ga-ksp:/sandbox gameanything-lab-ksp
#   docker exec ga-ksp ga-ksp layer && docker exec ga-ksp gameanything native build --game ksp --install /opt/gameanything/smoke/M2WSmoke
#   docker exec ga-ksp ga-ksp run            # then open http://localhost:6080/vnc.html
#
# What is inside and under which license: docs/sandbox-images.md. Never inside: game files, Steam / EA / Microsoft accounts, user data, API keys.
# x86_64 only (Apple silicon: Docker Desktop runs it under Rosetta).
ARG RUNTIME=gameanything-lab-dotnet
FROM ${RUNTIME}
# PLAYER_UID: the published images keep 1000 (another uid runs with --user: gameanything/sandbox.py run_argv); a local build passes yours
ARG PLAYER_UID=1000
USER root
COPY . /opt/gameanything/src
RUN umask 022 && PLAYER_UID=${PLAYER_UID} SRC=/opt/gameanything/src bash /opt/gameanything/src/lab/images/ksp/install.sh \
 && sh /opt/gameanything/src/lab/images/common/ga-readable && rm -rf /opt/gameanything/src
ENV GAMEANYTHING_KSP_DIR=/sandbox/game
LABEL org.gameanything.player-uid="${PLAYER_UID}" org.gameanything.game="ksp" \
      org.opencontainers.image.title="GameAnything Kerbal Space Program sandbox (runtime only)" \
      org.opencontainers.image.description=".NET SDK 8 (plugins against the game's own assemblies), Unity's libraries, the Steam bootstrap, Xvfb / Xorg (GPU) + noVNC, ffmpeg, GameAnything + ga-ksp. No game files, no accounts." \
      org.opencontainers.image.licenses="Apache-2.0 AND MIT AND others (docs/sandbox-images.md)"
USER player
WORKDIR /home/player
VOLUME /sandbox
EXPOSE 6080
# up = the screen + viewer; then it waits (docker exec <container> ga-ksp ... for the rest)
CMD ["/usr/bin/tini", "--", "bash", "-c", "ga-ksp up && exec sleep infinity"]
