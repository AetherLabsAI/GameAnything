#!/usr/bin/env bash
# Layer "java" (lab/images/java/Dockerfile, on top of "base"): OpenJDK 25 from the Ubuntu archive (GPL-2.0 with the Classpath
# Exception). javac for Fabric mods against Minecraft 26.x (Java 25 classes) and for ModTheSpire mods (javac --release 8); also runs
# Minecraft when the mounted .minecraft has no Java runtime of its own. What LWJGL 2 / 3 load is in "base". NO game files.
set -euo pipefail
umask 022   # readable for the player whatever the builder's umask (install-system.sh)
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends openjdk-25-jdk-headless libflite1
rm -rf /var/lib/apt/lists/*
java -version 2>&1 | head -1
mkdir -p /opt/gameanything/layers && echo "java $(date -u +%FT%TZ) $(java -version 2>&1 | head -1)" > /opt/gameanything/layers/java
