# GameAnything sandbox images, shared layer "dotnet" (on "steam"): .NET SDK 8 (Ubuntu's build, MIT) + ICU, libgdiplus, GTK 3, NSS, udev
# for Unity / FNA games. Stardew Valley, Terraria (tModLoader), Valheim, Overcooked! 2, KSP and Cities: Skylines build on it.
ARG BASE=gameanything-lab-steam
FROM ${BASE}
COPY lab/images/common/install-dotnet.sh lab/images/common/ga-readable /tmp/ga-layer/
RUN umask 022 && bash /tmp/ga-layer/install-dotnet.sh && sh /tmp/ga-layer/ga-readable && rm -rf /tmp/ga-layer
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1
LABEL org.gameanything.layer="dotnet" org.opencontainers.image.title="GameAnything sandbox base + Steam + .NET SDK 8 (runtime only)"
