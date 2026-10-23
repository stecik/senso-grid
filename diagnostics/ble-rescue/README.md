# Debian BLE rescue

Optional host-level fallback for container `sensogrid-app-1`. Install with:

```sh
sudo sh diagnostics/ble-rescue/install.sh
```

The root-owned systemd timer checks once a minute. The application remains
unprivileged and receives no Docker socket, sudo rule or restart endpoint.
The probe runs as the existing container user and reads SQLite in read-only mode.

Recovery requires all of the following:

- The SensoGrid container is running in BLE mode and has enabled sensors.
- No enabled sensor has a recent successful measurement.
- The outage and container uptime both exceed 10 minutes, or three times the
  longest configured sensor interval when that is greater.
- No recovery attempt occurred during the last 30 minutes. This cooldown
  survives timer/application restarts and also applies to failed attempts.

Then only `bluetooth.service` is restarted. This briefly affects other Bluetooth
clients on the same host. A single missing sensor never triggers recovery.
Probe failures or corrupt cooldown state do not trigger a restart. systemd
already restarts a crashing BlueZ daemon; this fallback covers a daemon that
remains running while the entire collector stops making progress. It does not
repair a sensor that needs a battery reset or establish the BlueZ crash cause.

Inspect and disable:

```sh
systemctl status sensogrid-ble-rescue.timer
sudo journalctl -u sensogrid-ble-rescue.service
sudo systemctl disable --now sensogrid-ble-rescue.timer
```

Installed script: `/usr/local/lib/sensogrid/bluez_rescue.py`.
Cooldown state: `/var/lib/sensogrid-ble-rescue/last-attempt`.
Keep the cooldown file when updating. Do not enable another independent
Bluetooth watchdog with a different cooldown.
