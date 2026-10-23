#!/bin/sh
set -eu
cd /work
export DEBFULLNAME='SensoGrid local maintenance' DEBEMAIL='local@localhost'
apt-get source bluez=5.82-1.1
cd bluez-5.82
cp src/shared/gatt-db.c /work/gatt-db-baseline.c
cp /input/01-6cdb936ebb6a.patch debian/patches/sensogrid-inactive-service-removal.patch
cp /input/02-a338533f913b.patch debian/patches/sensogrid-pending-service-dedup.patch
printf '%s\n' sensogrid-inactive-service-removal.patch sensogrid-pending-service-dedup.patch >> debian/patches/series
dpkg-source --before-build .
dch --newversion 5.82-1.1+sensogrid1 --distribution trixie --force-distribution 'Backport upstream GATT lifetime fixes 6cdb936ebb6a and a338533f913b for SensoGrid; temporary local package.'
dpkg-buildpackage -B -us -uc -j2
make check -j2 TESTS='unit/test-queue unit/test-gatt'
# Reproduce the inactive-service notification defect against the baseline object,
# then exercise the same public API against the patched library.
cc -D_GNU_SOURCE -DHAVE_CONFIG_H -I. $(pkg-config --cflags glib-2.0) -c /work/gatt-db-baseline.c -o /work/gatt-db-baseline.o
cc -D_GNU_SOURCE -DHAVE_CONFIG_H -I. $(pkg-config --cflags glib-2.0) /input/test-inactive-removal.c /work/gatt-db-baseline.o src/.libs/libshared-glib.a lib/.libs/libbluetooth-internal.a $(pkg-config --libs glib-2.0) -o /work/probe-baseline
cc -D_GNU_SOURCE -DHAVE_CONFIG_H -I. $(pkg-config --cflags glib-2.0) /input/test-inactive-removal.c src/.libs/libshared-glib.a lib/.libs/libbluetooth-internal.a $(pkg-config --libs glib-2.0) -o /work/probe-patched
set +e
/work/probe-baseline
baseline_status=$?
set -e
test "$baseline_status" -eq 1
/work/probe-patched
mkdir -p /out/original /out/source
cp /work/*.deb /work/*.buildinfo /work/*.changes /out/
cp /work/bluez_5.82-1.1.dsc /work/bluez_5.82.orig.tar.gz /work/bluez_5.82-1.1.debian.tar.xz /out/source/
cp unit/test-queue.log unit/test-gatt.log test-suite.log /out/
cp /work/bluez-5.82/debian/changelog /out/changelog
cd /out/original
apt-get download bluez=5.82-1.1
cd /out
sha256sum *.deb original/*.deb source/* > SHA256SUMS
printf 'BUILD_AND_TESTS_OK\n'
