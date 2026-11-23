#!/usr/bin/env bash
# Layer "wine" (lab/images/wine/Dockerfile, on top of "base"): Windows games under Wine (The Sims 4 + the EA App). Every download is
# sha256-pinned. The EA App itself is NOT in the image (EA's terms): `ga-ea install-app` downloads EA's installer into the user's volume,
# and the user accepts EA's User Agreement in it.
#   /opt/gameanything/wine          Kron4ek wine-11.19-staging-amd64-wow64 (LGPL-2.1+; WoW64: no 32-bit libraries needed)
#                                   + wine-mono 11.3.0 and wine-gecko 2.47.4 in share/wine/{mono,gecko} (wineboot installs them itself)
#   /opt/gameanything/dxvk          DXVK 3.1.1 (zlib): Direct3D 9/10/11 on Vulkan
#   /opt/python3.7                  CPython 3.7.17 built from python.org's source (PSF-2.0): The Sims 4 script mods are .pyc of 3.7
# NO game files, no EA App, no accounts.
set -euo pipefail
umask 022   # readable for the player whatever the builder's umask (install-system.sh)
export DEBIAN_FRONTEND=noninteractive
WINE_URL=https://github.com/Kron4ek/Wine-Builds/releases/download/11.19/wine-11.19-staging-amd64-wow64.tar.xz
WINE_SHA=c89f69cf22f6664e3791210fa3b40c6e9e6d2e27a9aaa466f5a26d9c56664a09
MONO_URL=https://dl.winehq.org/wine/wine-mono/11.3.0/wine-mono-11.3.0-x86.msi
MONO_SHA=df2dfc1665c2511882e7cabd56eafd0c0a3d94e5a7e86f969277f6c189d418d3
GECKO64_URL=https://dl.winehq.org/wine/wine-gecko/2.47.4/wine-gecko-2.47.4-x86_64.msi
GECKO64_SHA=e590b7d988a32d6aa4cf1d8aa3aa3d33766fdd4cf4c89c2dcc2095ecb28d066f
GECKO32_URL=https://dl.winehq.org/wine/wine-gecko/2.47.4/wine-gecko-2.47.4-x86.msi
GECKO32_SHA=26cecc47706b091908f7f814bddb074c61beb8063318e9efc5a7f789857793d6
DXVK_URL=https://github.com/doitsujin/dxvk/releases/download/v3.1.1/dxvk-3.1.1.tar.gz
DXVK_SHA=40565b4a724aadc4433fa4e010b4b23916d9b1f1baeee64e17186db94f54e608
PY37_URL=https://www.python.org/ftp/python/3.7.17/Python-3.7.17.tar.xz
PY37_SHA=7911051ed0422fd54b8f59ffc030f7cf2ae30e0f61bda191800bb040dce4f9d2

# 1. what Wine (64-bit, WoW64) loads, Vulkan for DXVK, cabextract / winbind for installers
apt-get update
apt-get install -y --no-install-recommends \
  libfreetype6 libfontconfig1 libgnutls30t64 libxcomposite1 libxfixes3 libxdamage1 libdbus-1-3 libunwind8 libosmesa6 \
  libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  libvulkan1 mesa-vulkan-drivers vulkan-tools cabextract winbind libsdl2-2.0-0 libcups2t64 libkrb5-3 libgsm1 libpcap0.8t64 \
  build-essential zlib1g-dev libffi-dev libbz2-dev liblzma-dev libsqlite3-dev
fetch() { curl -fsSL --retry 3 -o "$2" "$1"; echo "$3  $2" | sha256sum -c -; }
T=$(mktemp -d)
fetch "$WINE_URL" "$T/wine.tar.xz" "$WINE_SHA"
fetch "$MONO_URL" "$T/wine-mono-11.3.0-x86.msi" "$MONO_SHA"
fetch "$GECKO64_URL" "$T/wine-gecko-2.47.4-x86_64.msi" "$GECKO64_SHA"
fetch "$GECKO32_URL" "$T/wine-gecko-2.47.4-x86.msi" "$GECKO32_SHA"
fetch "$DXVK_URL" "$T/dxvk.tar.gz" "$DXVK_SHA"
fetch "$PY37_URL" "$T/Python-3.7.17.tar.xz" "$PY37_SHA"
mkdir -p /opt/gameanything/wine /opt/gameanything/dxvk
tar -xJf "$T/wine.tar.xz" -C /opt/gameanything/wine --strip-components=1
mkdir -p /opt/gameanything/wine/share/wine/mono /opt/gameanything/wine/share/wine/gecko
cp "$T/wine-mono-11.3.0-x86.msi" /opt/gameanything/wine/share/wine/mono/
cp "$T/wine-gecko-2.47.4-x86_64.msi" "$T/wine-gecko-2.47.4-x86.msi" /opt/gameanything/wine/share/wine/gecko/
tar -xzf "$T/dxvk.tar.gz" -C /opt/gameanything/dxvk --strip-components=1
# 2. CPython 3.7 (the game's own version: its .pyc must match), only what py_compile needs; no ssl (OpenSSL 3 is too new for 3.7)
tar -xJf "$T/Python-3.7.17.tar.xz" -C "$T"
( cd "$T/Python-3.7.17" && ./configure --prefix=/opt/python3.7 --without-ensurepip --disable-test-modules >/dev/null \
  && make -j"$(nproc)" >/dev/null 2>&1 && make altinstall >/dev/null 2>&1 )
rm -rf /opt/python3.7/lib/python3.7/test /opt/python3.7/lib/python3.7/*/tests
/opt/python3.7/bin/python3.7 -c "import py_compile, zipfile, json; print('python3.7 ok')"
rm -rf "$T"
apt-get purge -y build-essential zlib1g-dev libffi-dev libbz2-dev liblzma-dev libsqlite3-dev >/dev/null
apt-get autoremove -y >/dev/null
rm -rf /var/lib/apt/lists/*
ln -sf /opt/gameanything/wine/bin/wine /usr/local/bin/wine; ln -sf /opt/gameanything/wine/bin/wineserver /usr/local/bin/wineserver
ln -sf /opt/gameanything/wine/bin/wineboot /usr/local/bin/wineboot
ln -sf /opt/python3.7/bin/python3.7 /usr/local/bin/python3.7
cat > /opt/gameanything/wine/VERSIONS <<V
wine 11.19-staging-amd64-wow64 (Kron4ek, LGPL-2.1+) sha256 $WINE_SHA
wine-mono 11.3.0 (MIT and others) sha256 $MONO_SHA
wine-gecko 2.47.4 x86_64 / x86 (MPL-2.0) sha256 $GECKO64_SHA / $GECKO32_SHA
dxvk 3.1.1 (zlib) sha256 $DXVK_SHA
cpython 3.7.17 (PSF-2.0, built from source) sha256 $PY37_SHA
V
/opt/gameanything/wine/bin/wine --version
mkdir -p /opt/gameanything/layers && echo "wine $(date -u +%FT%TZ) $(/opt/gameanything/wine/bin/wine --version) dxvk-3.1.1 python3.7.17" > /opt/gameanything/layers/wine
