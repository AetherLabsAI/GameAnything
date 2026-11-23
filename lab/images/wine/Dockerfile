# GameAnything sandbox images, shared layer "wine" (on "base"): Wine 11.19 (Kron4ek staging WoW64 build, LGPL-2.1+), wine-mono 11.3.0,
# wine-gecko 2.47.4, DXVK 3.1.1, CPython 3.7.17 (for The Sims 4 script mods), all sha256-pinned. The Sims 4 builds on it.
# Never inside: the EA App (EA's terms; ga-ea downloads EA's installer into the user's volume), game files, accounts.
ARG BASE=gameanything-lab-base
FROM ${BASE}
COPY lab/images/common/install-wine.sh lab/images/common/ga-readable /tmp/ga-layer/
RUN umask 022 && bash /tmp/ga-layer/install-wine.sh && sh /tmp/ga-layer/ga-readable && rm -rf /tmp/ga-layer
ENV WINEDEBUG=-all GAMEANYTHING_PYTHON37=/opt/python3.7/bin/python3.7
LABEL org.gameanything.layer="wine" org.opencontainers.image.title="GameAnything sandbox base + Wine + DXVK (runtime only)" \
      org.opencontainers.image.licenses="LGPL-2.1-or-later AND Zlib AND MPL-2.0 AND PSF-2.0 AND others (docs/sandbox-images.md)"
