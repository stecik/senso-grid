from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pytest
from sensogrid.config import Settings
from sensogrid.runtime import Runtime


class DB:
    saved_config: dict[str, Any]

    def note_seen(self, sensor_id: str, iso_timestamp: str) -> None:
        pass

    def config(self, key: str, default: Any) -> Any:
        return getattr(self, "saved_config", {}).get(key, default)

    def set_config(self, key: str, value: Any) -> None:
        if not hasattr(self, "saved_config"):
            self.saved_config = {}
        self.saved_config[key] = value

    def all_sensors(self) -> list[dict[str, Any]]:
        return [{"id": "s1", "name": "Bedroom", "room_id": "r1", "enabled": True}]

    def system_settings(self) -> dict[str, int]:
        return {"sample_interval_seconds": 900}


def settings(tmp_path: Path, mode: Literal["demo", "ble", "off"] = "demo") -> Settings:
    return Settings(
        mode=mode,
        data_dir=tmp_path,
        diagnostics=False,
        influx_url="http://localhost:8181",
        influx_token="",
        influx_database="sensogrid",
    )


@pytest.mark.asyncio
async def test_explicit_demo_and_filtered_history(tmp_path: Path) -> None:
    runtime = Runtime(settings(tmp_path), DB())
    await runtime.start()
    assert runtime.current()[0]["source"] == "demo"
    rows = await runtime.history(
        datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC), ["r1"], [], "day"
    )
    assert len(rows) == 1 and rows[0]["count"] == 96
    assert (
        await runtime.history(
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
            ["different"],
            [],
            "day",
        )
        == []
    )
    await runtime.stop()


def test_durable_outbox_and_no_fake_live_samples(tmp_path: Path) -> None:
    runtime = Runtime(settings(tmp_path, "ble"), DB())
    runtime._outbox.mkdir()
    assert runtime.current() == []
    runtime._queue_sample(
        {
            "sensor_id": "s1",
            "room_id": "r1",
            "timestamp": "2026-01-01T00:00:00Z",
            "temperature": 20,
            "humidity": 40,
        }
    )
    assert len(list(runtime._outbox.glob("*.json"))) == 1
    assert not list(runtime._outbox.glob("*.tmp"))


def test_reassignment_hides_old_live_reading(tmp_path: Path) -> None:
    runtime = Runtime(settings(tmp_path, "ble"), DB())
    runtime._latest["s1"] = {
        "sensor_id": "s1",
        "room_id": "old-room",
        "timestamp": "2026-01-01T00:00:00Z",
        "temperature": 25,
        "humidity": 50,
    }
    assert runtime.current() == []
    runtime._latest["s1"]["room_id"] = "r1"
    assert runtime.current()[0]["temperature"] == 25
