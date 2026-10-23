# Temporary BlueZ 5.82 GATT discovery repair

## Installed versions and provenance

Deployed on HomeServer on **2026-10-23 at 10:23:49 CEST (UTC+02:00)**.

| Component | Before | After |
| --- | --- | --- |
| Debian bluez package | 5.82-1.1 | **5.82-1.1+sensogrid1** |
| libbluetooth3 | 5.82-1.1 | 5.82-1.1 (unchanged) |
| Kernel | 6.12.96+deb13-amd64 | unchanged |
| Bleak / dbus-fast | 3.0.2 / 5.2.0 | unchanged |
| Radio | Realtek USB 0bda:b85b | unchanged |

The package preserves Debian packaging, configure options and hardening. It backports exactly these upstream fixes, committed on 2026-10-19:

1. [6cdb936ebb6a3906062605883470d6b3a4e8c89e](https://github.com/bluez/bluez/commit/6cdb936ebb6a3906062605883470d6b3a4e8c89e) — shared/gatt-db: Always notify service removal. Notify removal of inactive services too, so in-flight discovery drops its reference before the service is freed.
2. [a338533f913bf42b267aeba30f1344d85459c13c](https://github.com/bluez/bluez/commit/a338533f913bf42b267aeba30f1344d85459c13c) — shared/gatt-client: Fix double-queued service. Avoid storing a duplicate inactive-service pointer in pending_svcs.

Both fixes postdate release 5.87. A higher upstream version number alone does not prove their inclusion. These fixes match the observed discovery cleanup crash path; the precise cause of the subsequent empty radio scan and long-term hardware stability still need observation.

## Verified build

- Debian source: bluez **5.82-1.1**, retained in artifacts/source.
- Build image: debian:13-slim, digest **sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad**.
- Build dependencies were installed inside an isolated Docker container, not on the host. Limits: 2 CPUs / 3 GiB.
- Both patches apply without adaptation. Official 5.82 source blobs checked separately: gatt-db.c b4414052393a5c879a9370e7b52de28b648d8247; gatt-client.c 41a5c6f9c399a32b14ccae4d333a1027c36dad34.
- dpkg-buildpackage -B -us -uc -j2 completed successfully.
- Explicit upstream tests (Debian packaging disables its automatic test target): **test-queue 8/8**, **test-gatt 193/193**.
- test-inactive-removal.c exercises the real GATT database API: baseline produced zero removal notifications and expected exit 1; patched library produced one notification and exit 0. This regression covers inactive-service removal, not a complete hardware reproduction of both faults.
- Package checksum verification and apt installation simulation passed. Simulation changes only bluez; no dependency replacement or removals.

Exact deployed artifact identities:

| Artifact | Identity |
| --- | --- |
| bluez_5.82-1.1+sensogrid1_amd64.deb SHA-256 | fc2aa3af6bd10ed46218103f64a45f5ae0a8f72dafb2c812aa8e0fd6c39162b0 |
| Original bluez_5.82-1.1_amd64.deb SHA-256 | 64a680d95abb11cf02f8170b2d57115dbdee4738a6163c2cf25021f546bce8ac |
| Installed bluetoothd SHA-256 | 855b151b4bfd0b3be14a6e946daa60c9e04574be651ddab1fc63f7c26a70a5d4 |
| Installed bluetoothd Build ID | 2ac9eba7f42650f9b5e888a2b314cde9e6878dce |
| Original bluetoothd Build ID | 76bad679a300bdbd6e3dcdd82580ad791aee79c9 |

## Files and installation

Host workspace: /home/marek/sensogrid-bluez-5.82-fix-20261023.

- input/: build scripts, two patches and regression source.
- artifacts/: Debian binaries, matching debug-symbol packages, buildinfo/changes, test logs, build.log, changelog and SHA256SUMS.
- artifacts/source/: original Debian source archives; apply the two repository patches using build-user.sh.
- artifacts/original/: original binary package for rollback.
- deploy.sh: reviewed installer; --check-only validates without changing services/packages.
- deployment.txt: installed version, binary identity, restart counter and backup location.
- backup-20261023T082340Z/: root-only backup of /etc/bluetooth and /var/lib/bluetooth, service definition and original version list. Contains pairing keys; keep private.

The installer briefly stopped sensogrid-app-1 and Bluetooth, saved the backup, installed only the bluez package, reinitialized the radio, and restarted the app. InfluxDB and app volumes were preserved. No restart watchdog, apt hold/pin or extra web-container privilege was added. Installer failure triggers an attempt to restore the original package and restart services.

For this prepared host workspace:

```sh
bash /home/marek/sensogrid-bluez-5.82-fix-20261023/deploy.sh --check-only
sudo bash /home/marek/sensogrid-bluez-5.82-fix-20261023/deploy.sh
```

Do not blindly reuse this host-specific installer on other machines: architecture, original version and container name are checked or fixed.

## Rebuild

Use a new empty output directory, retain the source archives and record new package checksums. The scripts request the exact Debian source version; if repositories no longer publish it, use the retained archives rather than silently substituting another version.

```sh
mkdir -p /home/marek/sensogrid-bluez-rebuild/artifacts
docker run --name sensogrid-bluez-rebuild --cpus=2 --memory=3g \
  --mount type=bind,src=/home/marek/sensogrid-bluez-5.82-fix-20261023/input,dst=/input,readonly \
  --mount type=bind,src=/home/marek/sensogrid-bluez-rebuild/artifacts,dst=/out \
  debian:13-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad \
  sh /input/build-container.sh
```

A successful build ends with BUILD_AND_TESTS_OK. Output ownership is UID 1000. Only install the bluez binary package; do not install every generated package.

## Runtime verification

**Later counterexample:** During the standalone BLE benchmark at **11:25:26 CEST on 2026-10-23**, BlueZ automatically restarted (NRestarts 0 → 1) while the production application was stopped. The backport is therefore not an established complete stability repair. Privileged logs confirm SIGSEGV. Offset 0xf6fbe resolves to gatt_db_attribute_write in the matching patched debug symbols, unlike the original discovery_op_complete fault. The exact new failure mechanism is unresolved; profile ordering alone does not prove causation.


At deployment, Bluetooth was active, NRestarts=0 and the installed binary matched the artifact. The app restarted at 08:23:49 UTC. Fresh readings from all five real sensors after that timestamp and an unchanged daemon restart counter must be checked. A successful HTTP health response or old cached values are insufficient.

At **10:25:40 CEST** all five sensors had fresh BLE readings after app restart, unavailable_sensors was empty, and Bluetooth remained active with **NRestarts=0**. This is a short post-deployment check; overnight stability is not yet established.

| Sensor | New reading (CEST) | Temperature | Humidity |
| --- | --- | --- | --- |
| Spíž | 10:24:12 | 19.9 °C | 46% |
| Obývák | 10:24:40 | 22.9 °C | 41% |
| Kuchyně | 10:24:10 | 22.4 °C | 44% |
| Ložnice | 10:25:04 | 22.1 °C | 45% |
| Koupelna | 10:24:10 | 22.7 °C | 44% |

Useful checks on HomeServer:

```sh
dpkg-query -W bluez libbluetooth3
systemctl show bluetooth -p ActiveState -p NRestarts -p ActiveEnterTimestamp
docker logs --timestamps --since 2026-10-23T08:23:49Z sensogrid-app-1
sudo journalctl -u bluetooth --since '2026-10-23 10:23:40' --no-pager
```

Compare fresh readings and crashes over a further overnight period. If it fails again, preserve logs and the matching debug-symbol package before recovery; do not treat individual sensor unavailability as a reason to restart host Bluetooth automatically.

## Rollback to the original package

This restores the known original build, including its known crash risk. It does not delete application data. Run one step at a time; do not continue past a failed installation.

```sh
docker stop --timeout 20 sensogrid-app-1
sudo systemctl stop bluetooth
sudo dpkg -i /home/marek/sensogrid-bluez-5.82-fix-20261023/artifacts/original/bluez_5.82-1.1_amd64.deb
sudo systemctl daemon-reload
sudo systemctl start bluetooth
sudo bluetoothctl power off
sleep 2
sudo bluetoothctl power on
docker start sensogrid-app-1
dpkg-query -W bluez libbluetooth3
```

Configuration and pairing state need no restoration for the normal package rollback. The private backup is retained for a separate, deliberate state recovery if needed.

## Remove the workaround later

1. Verify the candidate Debian package contains **both** fixes (or equivalent fixes) through source/changelog inspection. Review supported Debian release repositories; do not mix testing packages merely to obtain a larger version.
2. Keep the original and patched artifacts and their matching debug symbols until the replacement passes the same hardware checks.
3. Set distro_version to the exact verified package version. Refresh apt metadata and inspect the simulation first. No hold/pin was installed, but +sensogrid1 can sort above a same-base +deb13uN update; do not rely on unattended upgrades to remove this workaround.
4. Stop SensoGrid/Bluetooth, install the chosen distribution package, then restart the radio/app as in rollback. Stop and investigate if apt proposes unrelated changes.
5. Confirm all five sensors have fresh readings and no new daemon crashes, including an overnight run. Then remove the two patch files, build/test/deploy scripts and this temporary README section. Archive any useful incident evidence before deleting host artifacts.

```sh
# Replace with a version whose sources have actually been reviewed.
distro_version='REPLACE_WITH_VERIFIED_DEBIAN_VERSION'
sudo apt-get update
sudo apt-get --simulate --no-remove --allow-downgrades install "bluez=$distro_version"
# After reviewing the simulation:
docker stop --timeout 20 sensogrid-app-1
sudo systemctl stop bluetooth
sudo apt-get --no-remove --allow-downgrades install "bluez=$distro_version"
sudo systemctl start bluetooth
sudo bluetoothctl power off
sleep 2
sudo bluetoothctl power on
docker start sensogrid-app-1
dpkg-query -W bluez libbluetooth3
```
