"""Read-only host snapshot for support downloads. No restarts or packet capture."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

OUTPUT = Path("/var/lib/sensogrid-diagnostics/host.json")
MAX_OUTPUT = 48000
COMMANDS = {
    "bluetooth_service": [
        "systemctl",
        "show",
        "bluetooth",
        "-p",
        "ActiveState",
        "-p",
        "SubState",
        "-p",
        "Result",
        "-p",
        "NRestarts",
        "-p",
        "ExecMainStatus",
        "-p",
        "ExecMainPID",
        "-p",
        "ActiveEnterTimestamp",
        "-p",
        "LimitCORE",
    ],
    "bluetooth_journal": [
        "journalctl",
        "-u",
        "bluetooth",
        "--since=-2h",
        "-n",
        "1000",
        "--no-pager",
        "-o",
        "short-iso",
    ],
    "kernel_journal": [
        "journalctl",
        "-k",
        "--since=-2h",
        "-n",
        "1000",
        "--grep=bluetooth|Bluetooth|btusb|segfault|firmware|USB disconnect",
        "--no-pager",
        "-o",
        "short-iso",
    ],
    "last_bluetooth_core": ["coredumpctl", "--no-pager", "-1", "info", "bluetoothd"],
    "adapter": ["bluetoothctl", "show"],
    "controller": ["btmgmt", "info"],
    "connections": ["hcitool", "con"],
    "usb": ["lsusb"],
    "usb_topology": ["lsusb", "-t"],
    "packages": [
        "dpkg-query",
        "-W",
        "-f=${Package} ${Version}\n",
        "bluez",
        "libbluetooth3",
        "firmware-realtek",
    ],
    "rescue": [
        "systemctl",
        "show",
        "sensogrid-ble-rescue.service",
        "-p",
        "Result",
        "-p",
        "ExecMainStatus",
    ],
    "rescue_journal": [
        "journalctl",
        "-u",
        "sensogrid-ble-rescue.service",
        "--since=-2h",
        "-n",
        "100",
        "--no-pager",
        "-o",
        "short-iso",
    ],
}


def collect(run=subprocess.run):
    commands = {}
    for name, args in COMMANDS.items():
        try:
            result = run(args, capture_output=True, text=True, timeout=8, check=False)
            text = result.stdout + result.stderr
            encoded = text.encode("utf-8", errors="replace")
            commands[name] = {
                "exit_code": result.returncode,
                "truncated": len(encoded) > MAX_OUTPUT,
                "output": encoded[-MAX_OUTPUT:].decode("utf-8", errors="replace"),
            }
        except (OSError, subprocess.TimeoutExpired) as exc:
            commands[name] = {"error": type(exc).__name__}
    result = {
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "commands": commands,
    }
    for name in ("core_pattern", "core_uses_pid"):
        try:
            result[name] = (Path("/proc/sys/kernel") / name).read_text().strip()[:1024]
        except OSError:
            result[name] = "unavailable"
    return result


def main():
    payload = json.dumps(collect(), ensure_ascii=False, indent=2)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.chmod(0o644)
    temporary.replace(OUTPUT)


if __name__ == "__main__":
    main()
