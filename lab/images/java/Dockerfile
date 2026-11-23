# GameAnything sandbox images, shared layer "java" (on "base"): OpenJDK 25 (GPL-2.0 with the Classpath Exception). Minecraft and Slay the
# Spire build on it (Slay the Spire adds the Steam layer in its own image).
ARG BASE=gameanything-lab-base
FROM ${BASE}
COPY lab/images/common/install-java.sh lab/images/common/ga-readable /tmp/ga-layer/
RUN umask 022 && bash /tmp/ga-layer/install-java.sh && sh /tmp/ga-layer/ga-readable && rm -rf /tmp/ga-layer
LABEL org.gameanything.layer="java" org.opencontainers.image.title="GameAnything sandbox base + OpenJDK 25 (runtime only)"
