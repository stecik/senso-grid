"""Host-specific benchmark supervisor. Restores only the SensoGrid app."""

import json
import signal
import subprocess
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
APP = "sensogrid-app-1"
BENCH = "sensogrid-ble-benchmark-20261023"
DEADLINE_SECONDS = 6600


def state(event, **fields):
    row = {"utc": datetime.now(UTC).isoformat(), "event": event, **fields}
    with (BASE / "supervisor.jsonl").open("a") as file:
        file.write(json.dumps(row) + "\n")
    print(json.dumps(row), flush=True)


def docker(*args, **kwargs):
    return subprocess.run(["docker", *args], check=True, **kwargs)


def restore():
    docker("start", APP, timeout=60)
    state("app_restored")


def terminate(signum, frame):
    raise SystemExit(f"signal {signum}")


def main():
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    details = json.loads(subprocess.check_output(["docker", "inspect", APP]))[0]
    if (
        not details["State"]["Running"]
        or details["Config"]["Labels"].get("com.docker.compose.service") != "app"
    ):
        raise RuntimeError("Expected the running SensoGrid app container")
    deadline = time.monotonic() + DEADLINE_SECONDS
    state("preflight", app=APP, image=details["Image"])
    (BASE / "containers-before.json").write_text(
        subprocess.check_output(["docker", "ps", "-a", "--format", "{{json .}}"], text=True)
    )
    (BASE / "bluez-before.txt").write_text(
        subprocess.check_output(
            [
                "systemctl",
                "show",
                "bluetooth",
                "-p",
                "NRestarts",
                "-p",
                "ActiveState",
                "-p",
                "ActiveEnterTimestamp",
            ],
            text=True,
        )
    )
    process = None
    try:
        docker("stop", "--timeout", "20", APP, timeout=40)
        state("app_stopped")
        args = [
            "run",
            "--name",
            BENCH,
            "--network",
            "none",
            "--user",
            "10001:10001",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=32m",
            "--mount",
            f"type=bind,src={BASE}/input,dst=/benchmark,readonly",
            "--mount",
            f"type=bind,src={BASE}/artifacts,dst=/results",
            "--mount",
            "type=bind,src=/run/dbus,dst=/run/dbus,readonly",
            details["Image"],
            "python",
            "/benchmark/ble_benchmark.py",
            "--sensors",
            "/benchmark/sensors.json",
            "--output",
            "/results/debian",
            "--duration",
            "600",
            "--interval",
            "60",
            "--attempts",
            "3",
        ]
        with (BASE / "benchmark.log").open("w") as log:
            process = subprocess.Popen(["docker", *args], stdout=log, stderr=subprocess.STDOUT)
            try:
                code = process.wait(timeout=2900)
            except subprocess.TimeoutExpired:
                docker("stop", "--timeout", "20", BENCH, timeout=40)
                process.wait(timeout=30)
                raise RuntimeError("Benchmark exceeded the safety timeout") from None
        if code != 0 or not (BASE / "artifacts/debian/complete.json").exists():
            raise RuntimeError(f"Linux benchmark did not complete: {code}")
        (BASE / "bluez-after-linux.txt").write_text(
            subprocess.check_output(
                [
                    "systemctl",
                    "show",
                    "bluetooth",
                    "-p",
                    "NRestarts",
                    "-p",
                    "ActiveState",
                    "-p",
                    "ActiveEnterTimestamp",
                ],
                text=True,
            )
        )
        state(
            "linux_complete_waiting_for_windows",
            deadline_seconds=round(deadline - time.monotonic()),
        )
        while not (BASE / "release").exists() and time.monotonic() < deadline:
            time.sleep(5)
        state("release" if (BASE / "release").exists() else "safety_deadline")
    except BaseException:
        state("error", traceback=traceback.format_exc())
        raise
    finally:
        if process is not None and process.poll() is None:
            subprocess.run(["docker", "stop", "--timeout", "20", BENCH], timeout=40)
        restore()
        (BASE / "containers-after.json").write_text(
            subprocess.check_output(["docker", "ps", "-a", "--format", "{{json .}}"], text=True)
        )


if __name__ == "__main__":
    main()
