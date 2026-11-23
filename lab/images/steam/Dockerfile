# GameAnything sandbox images, shared layer "steam" (on "base"): i386 multiarch, Ubuntu's steam-installer (the bootstrap only: Steam
# downloads the client itself into the user's own volume on first start, under the Steam Subscriber Agreement the user accepts),
# the 32-bit libraries, D-Bus, openbox, ga-steam. NO Steam client binaries, no account, no login data.
ARG BASE=gameanything-lab-base
FROM ${BASE}
COPY lab/images/common/install-steam.sh lab/images/common/install-steam-fex.sh lab/images/common/ga-steam lab/images/common/ga-readable /tmp/ga-layer/
RUN umask 022 && bash /tmp/ga-layer/install-steam.sh && sh /tmp/ga-layer/ga-readable && rm -rf /tmp/ga-layer
LABEL org.gameanything.layer="steam" org.opencontainers.image.title="GameAnything sandbox base + Steam bootstrap (runtime only)"
