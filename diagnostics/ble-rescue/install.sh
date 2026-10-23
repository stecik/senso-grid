#!/bin/sh
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
if [ "$(id -u)" -ne 0 ]; then
    printf 'Run this installer with sudo.\n' >&2
    exit 1
fi
install -d -m 0755 /usr/local/lib/sensogrid
install -o root -g root -m 0644 "$base/scripts/bluez_rescue.py" /usr/local/lib/sensogrid/bluez_rescue.py
install -o root -g root -m 0644 "$base/diagnostics/ble-rescue/sensogrid-ble-rescue.service" /etc/systemd/system/sensogrid-ble-rescue.service
install -o root -g root -m 0644 "$base/diagnostics/ble-rescue/sensogrid-ble-rescue.timer" /etc/systemd/system/sensogrid-ble-rescue.timer
systemctl daemon-reload
systemctl enable --now sensogrid-ble-rescue.timer
printf 'SensoGrid BLE rescue timer enabled. No unconditional Bluetooth restart performed.\n'
