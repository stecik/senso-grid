#!/bin/bash
# Install only the reviewed local BlueZ package; preserve app data and InfluxDB.
set -Eeuo pipefail
base="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
new_version='5.82-1.1+sensogrid1'
old_version='5.82-1.1'
package="$base/artifacts/bluez_5.82-1.1+sensogrid1_amd64.deb"
original="$base/artifacts/original/bluez_5.82-1.1_amd64.deb"
app='sensogrid-app-1'

[[ "$(dpkg --print-architecture)" == amd64 ]]
[[ "$(dpkg-deb -f "$package" Package)" == bluez ]]
[[ "$(dpkg-deb -f "$package" Version)" == "$new_version" ]]
[[ "$(dpkg-deb -f "$original" Version)" == "$old_version" ]]
(cd "$base/artifacts" && sha256sum --check SHA256SUMS)
installed="$(dpkg-query -W -f='${Version}' bluez)"
if [[ "$installed" != "$old_version" && "$installed" != "$new_version" ]]; then
    printf 'Unexpected installed BlueZ version: %s; refusing to replace it.\n' "$installed" >&2
    exit 1
fi
apt-get --simulate --no-remove install "$package"
if [[ "${1:-}" == --check-only ]]; then
    printf 'PRECHECK_OK: %s -> %s\n' "$installed" "$new_version"
    exit 0
fi
if [[ "$EUID" -ne 0 ]]; then
    printf 'Run this script with sudo in your SSH terminal.\n' >&2
    exit 1
fi
app_was_running="$(docker inspect --format '{{.State.Running}}' "$app")"
changed=0
recover() {
    result="$1"
    trap - ERR INT TERM
    printf 'Deployment failed; restoring original package/service.\n' >&2
    if [[ "$changed" -eq 1 ]]; then dpkg -i "$original" || true; fi
    systemctl start bluetooth || true
    if [[ "$app_was_running" == true ]]; then docker start "$app" || true; fi
    exit "$result"
}
trap 'recover $?' ERR
trap 'recover 130' INT
trap 'recover 143' TERM
backup="$base/backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$backup"
if [[ "$app_was_running" == true ]]; then docker stop --timeout 20 "$app"; fi
systemctl stop bluetooth
cp -a /etc/bluetooth "$backup/"
if [[ -d /var/lib/bluetooth ]]; then cp -a /var/lib/bluetooth "$backup/state"; fi
systemctl cat bluetooth > "$backup/bluetooth.service.txt"
dpkg-query -W bluez libbluetooth3 > "$backup/versions.txt"
changed=1
dpkg -i "$package"
systemctl daemon-reload
systemctl start bluetooth
bluetoothctl power off
sleep 2
bluetoothctl power on
systemctl is-active --quiet bluetooth
[[ "$(dpkg-query -W -f='${Version}' bluez)" == "$new_version" ]]
if [[ "$app_was_running" == true ]]; then docker start "$app"; fi
{
    date -Is
    dpkg-query -W bluez libbluetooth3
    sha256sum /usr/libexec/bluetooth/bluetoothd
    readelf -n /usr/libexec/bluetooth/bluetoothd | grep 'Build ID'
    systemctl show bluetooth -p NRestarts -p ActiveEnterTimestamp
    printf 'Backup: %s\n' "$backup"
} | tee "$base/deployment.txt"
trap - ERR INT TERM
printf 'DEPLOYMENT_OK. Fresh sensor readings still need verification.\n'
