#!/bin/sh
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
if [ "$(id -u)" -ne 0 ]; then
    printf 'Run with sudo to install the read-only host collector.\n' >&2
    exit 1
fi
install -d -m 0755 /usr/local/lib/sensogrid /var/lib/sensogrid-diagnostics
install -o root -g root -m 0644 "$base/scripts/collect_host_diagnostics.py" /usr/local/lib/sensogrid/collect_host_diagnostics.py
install -o root -g root -m 0644 "$base/diagnostics/host-logs/sensogrid-diagnostics.service" /etc/systemd/system/sensogrid-diagnostics.service
install -o root -g root -m 0644 "$base/diagnostics/host-logs/sensogrid-diagnostics.timer" /etc/systemd/system/sensogrid-diagnostics.timer
systemctl daemon-reload
systemctl enable --now sensogrid-diagnostics.timer
printf 'Read-only host diagnostic collector enabled; no services restarted.\n'
