#!/bin/sh
set -eu
export DEBIAN_FRONTEND=noninteractive
rm -f /etc/apt/sources.list.d/sensogrid-source.list
sed -i 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/debian.sources
apt-get update
apt-get install -y --no-install-recommends ca-certificates build-essential devscripts dpkg-dev quilt
apt-get build-dep -y --no-install-recommends bluez=5.82-1.1
id -u builder >/dev/null 2>&1 || useradd --uid 1000 --create-home builder
mkdir -p /work
chown 1000:1000 /work /out
exec runuser -u builder -- sh /input/build-user.sh
