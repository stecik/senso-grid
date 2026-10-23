# Debian BLE outage, 23 October 2026

The initial investigation below was read-only. The later authorized recovery and targeted package deployment are recorded in the follow-up sections. Times below are Europe/Prague (CEST, UTC+02:00).

## Confirmed evidence

- HomeServer runs Debian kernel 6.12.96+deb13-amd64, BlueZ 5.82-1.1 and Realtek USB radio 0bda:b85b. App uses Bleak 3.0.2 and dbus-fast 5.2.0.
- The kernel reports bluetoothd segmentation faults at 06:32:30, 06:51:10 and 07:04:25, plus a general protection fault at 07:03:35. Systemd confirms status=11/SEGV and automatic restarts. Restart counter reached 36; that counter is not a claim that all 36 occurred in this captured time window.
- Matching Debian debug symbols (binary Build ID 76bad679a300bdbd6e3dcdd82580ad791aee79c9) map repeated fault offsets 0xf2463/0xf246e to discovery_op_complete. DWARF line tables place the fault in inlined GATT database access at gatt-db.c:660 during GATT service discovery completion. This locates the fault, but does not establish which upstream patch fixes it.
- Repeated input-hog profile errors precede crashes. These are context, not proof that HID is the crash cause.
- The service restarted at 07:04:25. Actual successful sensor reads continued until 07:09:43–07:11:30. Therefore the last daemon restart alone does not explain the exact transition to persistent failure.
- SensoGrid is still retrying: captured application logs contain 626 exhausted-retry BleakError entries since 06:00. Container health remains green because its health endpoint does not verify successful BLE acquisition. InfluxDB reports ready.
- Current BlueZ object manager contains only service/adapter objects and no device objects. A separate, fresh driver process performed a six-second discovery and found no supported sensors. This rules out an application-process cache as the only cause of the currently empty supported scan.
- A diagnostic read using the old sensor object path reproduces BleakError: device 'dev_F9_E3_94_8B_4A_F3' not found. The running application logs only exception class names, so the exact text of its historical exceptions cannot be recovered from these logs.
- Adapter is powered on, reported discovery active, RFKill unblocked, USB runtime active. USB autosuspend is enabled, but no captured USB reset/disconnect or firmware error proves it caused this outage.
- The inspected dpkg log contains no package installation/update records for 06:00–07:59. The configured apt metadata offers the currently installed BlueZ version.

## Interpretation and remaining uncertainty

There is a confirmed host Bluetooth daemon crash problem during GATT discovery/cleanup and a subsequent persistent failure to discover/read sensors. The collector is not frozen; retries cannot restore devices while the lower Bluetooth layer does not rediscover them. The first suspected single hung-read explanation is not supported by the observed continuing retry cycles.

Exact memory lifetime bug, reason the radio/discovery remains empty after 07:11, and a durable repair remain unverified. No full core dump is available (core_pattern=core; systemd coredump directory empty). A known newer GATT teardown lifetime fix exists upstream, but it is not established as the fix for this fault location:
https://github.com/bluez/bluez/commit/d01616f0c276a441dad8afe4e8f7bb261b26ba0a

## Proposed recovery and verification

1. In a controlled recovery, reinitialize the host Bluetooth service/adapter and restart the app collector; verify actual fresh readings from all five devices, not only HTTP health. A restart restores service at most temporarily and is not proof of a permanent repair.
2. Trial reduced BLE concurrency (one connection) to reduce stress while testing stability. This is a mitigation hypothesis, not a demonstrated fix.
3. Improve application diagnostics to retain exception message/phase and distinguish radio-wide discovery failure from individual sensor failures; discard stale device objects when appropriate and verify recovery after a BlueZ restart.
4. Evaluate a supported BlueZ update or targeted backport against the identified fault and perform an overnight soak test. Do not assume an arbitrary newer release fixes this exact crash.

## Local evidence

Raw evidence is in ignored .logs/debian-*.log files: privileged Bluetooth/kernel logs, application failures, device-object snapshot, fresh scan, cached-path probe, matching debug symbol lookup and decoded line table. Debug symbols were downloaded from Debian debuginfod to a named file in /tmp on HomeServer solely for address decoding; no package was installed.

## Follow-up: specific upstream fixes found

On 23 October, targeted GitHub commit search found two fixes committed on 19 October 2026: 6cdb936ebb6a3906062605883470d6b3a4e8c89e (notify inactive service removal) and a338533f913bf42b267aeba30f1344d85459c13c (avoid double-queuing an inactive service). Both describe stale/freed service pointers later dereferenced by discovery_op_complete, making them closer candidates to the observed offsets than the previously listed generic teardown fix. Both apply cleanly to the official 5.82 source without changes. Patched source and git apply --check are verified; compilation and sensor soak testing are not yet performed. They postdate release 5.87. Reviewable patch files and provenance are in diagnostics/bluez-5.82-fixes/. No BlueZ package or daemon configuration was changed on the host.

## Authorized deployment and immediate verification

On 23 October 2026 at **10:23:49 CEST**, the host installed **bluez 5.82-1.1+sensogrid1**, built from Debian 5.82-1.1 with exactly the two upstream patches above. libbluetooth3 remains 5.82-1.1. The isolated Debian package build, 8 queue tests, 193 GATT tests and a baseline-versus-patched inactive-service removal regression all passed. Only the BlueZ package and Bluetooth/app runtime were changed; no application/InfluxDB data was removed.

Installed bluetoothd Build ID: **2ac9eba7f42650f9b5e888a2b314cde9e6878dce**, SHA-256 **855b151b4bfd0b3be14a6e946daa60c9e04574be651ddab1fc63f7c26a70a5d4**. The installer saved a private Bluetooth configuration/state backup at /home/marek/sensogrid-bluez-5.82-fix-20261023/backup-20261023T082340Z and retained the original package for rollback.

At **10:25:40 CEST**, all five sensors had new real BLE readings after the app restart at 10:23:49. unavailable_sensors was empty, Bluetooth was active and NRestarts remained 0. This establishes successful installation and immediate acquisition, not an overnight fix or proof of the exact original failure mechanism. Full package identities, build scripts, rollback and eventual removal procedure are in [diagnostics/bluez-5.82-fixes/README.md](../diagnostics/bluez-5.82-fixes/README.md). Raw build and post-deployment evidence is in ignored .logs/debian-bluez-patched-build.log and .logs/debian-bluez-postdeployment.log.

## Follow-up during the independent BLE experiment

During profile D (five connections, 500 ms stagger) on 23 October, systemd NRestarts changed from 0 to 1 and ActiveEnterTimestamp became **11:25:26 CEST**. The production SensoGrid app had been stopped since 10:49:59; only the standalone diagnostic process was reading sensors. This confirms a further automatic daemon restart despite bluez 5.82-1.1+sensogrid1. It does not establish that profile D caused it or that it is the same original fault. Unprivileged journal access is unavailable; targeted privileged Bluetooth/kernel logs have been requested. The D result must be marked as affected by a service incident, rather than interpreted solely as a concurrency performance result.

Privileged logs subsequently confirmed **code=killed, status=11/SEGV** at 11:25:26. Kernel fault offset is **0xf6fbe** in the patched binary (Build ID 2ac9eba7f42650f9b5e888a2b314cde9e6878dce). addr2line against its matching generated bluez-dbgsym package resolves **gatt_db_attribute_write**, with no usable source-line result. This differs from the old discovery_op_complete offsets; no full core/backtrace is available to establish the memory-lifetime mechanism. Evidence is retained in .logs/ble-benchmark-20261023/debian-host/.
