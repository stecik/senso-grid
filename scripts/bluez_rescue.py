"""Root-owned, opt-in host timer; restart BlueZ only after a complete BLE outage."""

import json
import os
import sqlite3
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

CONTAINER = "sensogrid-app-1"
OUTAGE_SECONDS = 600
COOLDOWN_SECONDS = 1800
STATE_FILE = Path("/var/lib/sensogrid-ble-rescue/last-attempt")


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def recovery_reason(snapshot: dict, now: datetime, last_attempt: datetime | None) -> str | None:
    sensors = snapshot.get("sensors", [])
    if not snapshot.get("running") or snapshot.get("mode") != "ble" or not sensors:
        return None
    threshold = max(OUTAGE_SECONDS, 3 * max(s["interval"] for s in sensors))
    if (now - timestamp(snapshot["started_at"])).total_seconds() < threshold:
        return None
    if last_attempt and (now - last_attempt).total_seconds() < COOLDOWN_SECONDS:
        return None
    for sensor in sensors:
        if sensor["last_seen"]:
            age = (now - timestamp(sensor["last_seen"])).total_seconds()
            if age < threshold:
                return None
    return f"All {len(sensors)} enabled sensors lack a fresh sample for at least {threshold:g}s"


def run_once(snapshot: dict, now: datetime, state_file: Path, restart: Callable[[], object]) -> int:
    try:
        last_attempt = (
            timestamp(state_file.read_text(encoding="utf-8").strip())
            if state_file.exists()
            else None
        )
        reason = recovery_reason(snapshot, now, last_attempt)
        if not reason:
            return 0
        # Persist before attempting recovery; failures must also respect cooldown.
        state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = state_file.with_suffix(".tmp")
        temporary.write_text(now.isoformat(), encoding="utf-8")
        temporary.replace(state_file)
        print(f"BlueZ rescue: {reason}; restarting bluetooth.service", flush=True)
        restart()
        return 0
    except Exception as exc:
        print(f"BlueZ rescue skipped/failed: {type(exc).__name__}: {exc}", flush=True)
        return 1


def container_snapshot() -> dict:
    """Executed as the existing unprivileged container user, with read-only SQLite."""
    data = Path(os.environ.get("SENSOGRID_DATA_DIR", "/app/data"))
    with sqlite3.connect(f"file:{data / 'sensogrid.sqlite3'}?mode=ro", uri=True, timeout=5) as db:
        row = db.execute("SELECT value FROM config WHERE key='system'").fetchone()
        system = json.loads(row[0]) if row else {}
        default = system.get(
            "sample_interval_seconds",
            int(os.environ.get("SENSOGRID_SAMPLE_INTERVAL_SECONDS", "900")),
        )
        sensors = [
            {"last_seen": seen, "interval": interval or default}
            for seen, interval in db.execute(
                "SELECT last_seen,sample_interval_seconds FROM sensors WHERE enabled=1 AND address IS NOT NULL AND address!='' AND protocol='bthome_v2'"
            )
        ]
    return {"mode": os.environ.get("SENSOGRID_MODE", "demo"), "sensors": sensors}


def probe() -> dict:
    def capture(args: list[str]) -> str:
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=20).stdout

    state = json.loads(capture(["docker", "inspect", "--format", "{{json .State}}", CONTAINER]))
    if not state["Running"]:
        return {"running": False}
    # Send only the fixed read-only probe; never give the application a restart API.
    import inspect

    code = "import os,json,sqlite3\nfrom pathlib import Path\n" + inspect.getsource(
        container_snapshot
    )
    code += "\nprint(json.dumps(container_snapshot()))\n"
    snapshot = json.loads(capture(["docker", "exec", CONTAINER, "python", "-c", code]))
    snapshot.update(running=True, started_at=state["StartedAt"])
    return snapshot


def main() -> int:
    try:
        snapshot = probe()
    except Exception as exc:
        # An unknown database/container state must never become a global restart.
        print(f"BlueZ rescue probe failed: {type(exc).__name__}", flush=True)
        return 1
    return run_once(
        snapshot,
        datetime.now(UTC),
        STATE_FILE,
        lambda: subprocess.run(
            ["systemctl", "restart", "bluetooth.service"], check=True, timeout=30
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
