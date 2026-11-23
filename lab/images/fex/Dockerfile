# GameAnything sandbox layer for Apple silicon Macs (Docker Desktop, linux/arm64): the Linux Steam client under FEX-Emu.
# EXPERIMENTAL (2026-10-31). The standalone PROTOTYPE (Steam only, no game tools). The wizard's path is the normal chain built for
# linux/arm64: install-steam.sh hands over to lab/images/common/install-steam-fex.sh there (`gameanything lab setup --image <game>`).
# Why: on Apple silicon the x86_64 images run under Rosetta, which translates 64-bit code only; the Steam
# client is 32-bit (ubuntu12_32/steam), so it fell to qemu-i386 and crashed (signal 11) after its self-update, every start. FEX runs
# 32- and 64-bit x86 programs on arm64; verified on her Mac (M3, Docker Desktop): the client updated, restarted, showed the sign-in,
# she signed in, it downloaded Slay the Spire, and the game with ModTheSpire + BaseMod + the smoke mod reached the main menu.
#
#   docker build --platform linux/arm64 -f lab/images/fex/Dockerfile -t gameanything-lab-fex .      (from the repository root)
#   docker run -d --platform linux/arm64 --name ga-fex -p 127.0.0.1:6080:6080 --shm-size 1g \
#     --security-opt seccomp=lab/images/common/security/seccomp-steam.json -v ga-fex-home:/home/player gameanything-lab-fex
#   then open http://localhost:6080/vnc.html and sign in to Steam (the login and the games stay in the ga-fex-home volume)
#
# Inside: Ubuntu 24.04 arm64, FEX-Emu (Launchpad ppa:fex-emu/fex, MIT), FEX's Ubuntu 24.04 x86 RootFS (extracted: no FUSE in a
# container), Xvfb + openbox + x11vnc + noVNC, PulseAudio with a silent sink, xrandr (LWJGL 2 games read the screen modes with it),
# the Steam bootstrap from repo.steampowered.com (the client itself downloads into the user's home on first start, under the Steam
# Subscriber Agreement). Never inside: game files, accounts, user data.
FROM ubuntu:24.04
ARG PLAYER_UID=1000
ARG FEX_PACKAGE=fex-emu-armv8.4
ARG ROOTFS_URL=https://rootfs.fex-emu.gg/Ubuntu_24_04/2026-08-11/Ubuntu_24_04.sqsh
COPY lab/images/fex/install-fex.sh lab/images/fex/ga-fex-up lab/images/common/ga-readable /tmp/ga-layer/
RUN umask 022 && PLAYER_UID=${PLAYER_UID} FEX_PACKAGE=${FEX_PACKAGE} ROOTFS_URL=${ROOTFS_URL} bash /tmp/ga-layer/install-fex.sh \
 && sh /tmp/ga-layer/ga-readable && rm -rf /tmp/ga-layer
ENV FEX_ROOTFS=/opt/fex-rootfs/Ubuntu_24_04 DISPLAY=:99 XDG_RUNTIME_DIR=/tmp/ga-xdg PULSE_SINK=rec
LABEL org.gameanything.player-uid="${PLAYER_UID}" org.gameanything.layer="fex" \
      org.opencontainers.image.title="GameAnything Steam-under-FEX sandbox layer for Apple silicon (experimental)" \
      org.opencontainers.image.licenses="MIT (FEX-Emu) AND others (Ubuntu packages); Steam client: Steam Subscriber Agreement, downloaded by the user"
USER player
WORKDIR /home/player
EXPOSE 6080
CMD ["/usr/local/bin/ga-fex-up"]
