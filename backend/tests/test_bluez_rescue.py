"""Host rescue must ignore isolated losses and rate-limit recovery attempts."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Never

import pytest

from scripts import bluez_rescue as rescue

NOW = datetime(2026, 10, 23, 14, tzinfo=UTC)


def snapshot(
    *ages: float | None,
    uptime: float = 3600,
    interval: float = 60,
    mode: str = "ble",
    running: bool = True,
) -> dict[str, Any]:
    return {
        "running": running,
        "mode": mode,
        "started_at": (NOW - timedelta(seconds=uptime)).isoformat(),
        "sensors": [
            {
                "last_seen": (NOW - timedelta(seconds=age)).isoformat()
                if age is not None
                else None,
                "interval": interval,
            }
            for age in ages
        ],
    }


def test_only_complete_prolonged_outage_requests_restart() -> None:
    assert rescue.recovery_reason(snapshot(700, 900), NOW, None)
    assert rescue.recovery_reason(snapshot(None, None), NOW, None)
    assert rescue.recovery_reason(snapshot(700, 20), NOW, None) is None


def test_startup_disabled_empty_and_slow_collectors_do_not_restart() -> None:
    for state in [
        snapshot(900, uptime=300),
        snapshot(900, mode="off"),
        snapshot(900, running=False),
        snapshot(),
        snapshot(900, interval=900),
    ]:
        assert rescue.recovery_reason(state, NOW, None) is None


def test_cooldown_and_future_timestamps_fail_closed() -> None:
    state = snapshot(900)
    assert rescue.recovery_reason(state, NOW, NOW - timedelta(seconds=1799)) is None
    assert rescue.recovery_reason(state, NOW, NOW - timedelta(seconds=1800))
    assert rescue.recovery_reason(snapshot(-30), NOW, None) is None


def test_failed_restart_is_also_rate_limited(tmp_path: Path) -> None:
    calls = []

    def restart() -> Never:
        calls.append(True)
        raise RuntimeError("restart failed")

    state_file = tmp_path / "last-attempt"
    assert rescue.run_once(snapshot(900), NOW, state_file, restart) == 1
    assert state_file.exists()
    assert rescue.run_once(snapshot(901), NOW + timedelta(seconds=60), state_file, restart) == 0
    assert len(calls) == 1


def test_corrupt_cooldown_state_never_triggers_restart(tmp_path: Path) -> None:
    state_file = tmp_path / "last-attempt"
    state_file.write_text("broken", encoding="utf-8")
    calls = []
    assert rescue.run_once(snapshot(900), NOW, state_file, lambda: calls.append(True)) == 1
    assert not calls


def test_probe_uses_saved_intervals_and_ignores_disabled_sensors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SENSOGRID_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SENSOGRID_MODE", "ble")
    with sqlite3.connect(tmp_path / "sensogrid.sqlite3") as db:
        db.executescript(
            "CREATE TABLE config(key TEXT,value TEXT); CREATE TABLE sensors(last_seen TEXT,sample_interval_seconds INTEGER,enabled INTEGER,address TEXT,protocol TEXT);"
        )
        db.execute(
            "INSERT INTO config VALUES('system',?)", (json.dumps({"sample_interval_seconds": 60}),)
        )
        db.executemany(
            "INSERT INTO sensors VALUES(NULL,?,?,?,?)",
            [
                (None, 1, "AA", "bthome_v2"),
                (120, 1, "BB", "bthome_v2"),
                (10, 0, "CC", "bthome_v2"),
                (10, 1, None, "bthome_v2"),
                (10, 1, "OLD", "lt_thermometer"),
            ],
        )
    result = rescue.container_snapshot()
    assert result == {
        "mode": "ble",
        "sensors": [{"last_seen": None, "interval": 60}, {"last_seen": None, "interval": 120}],
    }
