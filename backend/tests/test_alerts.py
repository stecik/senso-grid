from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sensogrid.alerts import AlertEngine
from sensogrid.config import Settings
from sensogrid.db import Database


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Settings, Database, str, dict[str, Any]]:
    settings = Settings(mode="off", data_dir=tmp_path)
    db = Database(tmp_path / "config.sqlite3", settings)
    sensor = db.add_sensor(
        {"name": "Desk", "address": "AA:BB", "protocol": "lt_thermometer", "room_id": None}
    )
    rule = db.save_rule(
        {
            "name": "Warm",
            "sensor_id": sensor,
            "room_id": None,
            "metric": "temperature",
            "operator": "above",
            "threshold": 25,
            "reset_threshold": 24,
            "duration_seconds": 60,
            "enabled": True,
        }
    )
    return settings, db, sensor, rule


def reading(sensor: str, now: datetime, temp: float = 26) -> list[dict[str, Any]]:
    return [
        {
            "sensor_id": sensor,
            "timestamp": now.isoformat(),
            "temperature": temp,
            "humidity": 50,
            "room_id": None,
        }
    ]


@pytest.mark.asyncio
async def test_duration_restart_hysteresis_single_event(
    setup: tuple[Settings, Database, str, dict[str, Any]],
) -> None:
    settings, db, sensor, rule = setup
    engine = AlertEngine(db, settings)
    now = datetime.now(UTC)
    assert await engine.evaluate(reading(sensor, now), now) == []
    # Reload engine and database: pending duration survives process restart.
    reloaded = Database(db.path, settings)
    engine = AlertEngine(reloaded, settings)
    assert (
        await engine.evaluate(
            reading(sensor, now + timedelta(seconds=59)), now + timedelta(seconds=59)
        )
        == []
    )
    events = await engine.evaluate(
        reading(sensor, now + timedelta(seconds=60)), now + timedelta(seconds=60)
    )
    assert len(events) == 1 and events[0]["state"] == "active"
    assert (
        await engine.evaluate(
            reading(sensor, now + timedelta(seconds=90), 24.5), now + timedelta(seconds=90)
        )
        == []
    )
    assert len(db.events()) == 1
    events = await engine.evaluate(
        reading(sensor, now + timedelta(seconds=120), 24), now + timedelta(seconds=120)
    )
    assert len(events) == 1 and events[0]["state"] == "resolved"
    assert db.events()[0]["resolved_at"] is not None


@pytest.mark.asyncio
async def test_stale_readings_cannot_trigger_or_resolve(
    setup: tuple[Settings, Database, str, dict[str, Any]],
) -> None:
    settings, db, sensor, rule = setup
    engine = AlertEngine(db, settings)
    now = datetime.now(UTC)
    old = now - timedelta(hours=2)
    await engine.evaluate(reading(sensor, old), now)
    assert db.events() == []
    await engine.evaluate(reading(sensor, now), now)
    await engine.evaluate(reading(sensor, now), now + timedelta(hours=2))
    # Stale break resets pending; no immediate fire when samples resume.
    assert (
        await engine.evaluate(reading(sensor, now + timedelta(hours=2)), now + timedelta(hours=2))
        == []
    )
    later = now + timedelta(hours=2, seconds=60)
    await engine.evaluate(reading(sensor, later), later)
    assert db.events()[0]["state"] == "active"
    await engine.evaluate(reading(sensor, old, 10), later)
    assert db.events()[0]["state"] == "active"


@pytest.mark.asyncio
async def test_offline_and_disabled_rules(
    setup: tuple[Settings, Database, str, dict[str, Any]],
) -> None:
    settings, db, sensor, rule = setup
    db.delete_rule(rule["id"])
    db.save_rule(
        {
            "name": "Lost",
            "sensor_id": sensor,
            "room_id": None,
            "metric": "offline",
            "operator": "above",
            "threshold": 10,
            "reset_threshold": 2,
            "duration_seconds": 0,
            "enabled": True,
        }
    )
    engine = AlertEngine(db, settings)
    now = datetime.now(UTC)
    db.note_seen(sensor, (now - timedelta(minutes=11)).isoformat())
    events = await engine.evaluate([], now)
    assert len(events) == 1 and events[0]["state"] == "active"
    events = await engine.evaluate(reading(sensor, now), now)
    assert len(events) == 1 and events[0]["state"] == "resolved"
    db.note_seen(sensor, now.isoformat())
    assert await engine.evaluate([], now) == []


@pytest.mark.asyncio
async def test_room_aggregation_waits_for_matching_sample_assignment(
    setup: tuple[Settings, Database, str, dict[str, Any]],
) -> None:
    settings, db, sensor, rule = setup
    db.delete_rule(rule["id"])
    db.save_floorplan(
        {
            "schema_version": 1,
            "id": "home",
            "name": "Home",
            "units": "m",
            "width": 5,
            "height": 5,
            "rooms": [{"id": "r", "name": "Room", "polygon": [[0, 0], [5, 0], [5, 5], [0, 5]]}],
            "sensors": [{"sensor_id": sensor, "room_id": "r", "x": 2, "y": 2}],
        }
    )
    db.save_rule(
        {
            "name": "Room hot",
            "sensor_id": None,
            "room_id": "r",
            "metric": "temperature",
            "operator": "above",
            "threshold": 25,
            "reset_threshold": 24,
            "duration_seconds": 0,
            "enabled": True,
        }
    )
    now = datetime.now(UTC)
    engine = AlertEngine(db, settings)
    assert await engine.evaluate(reading(sensor, now), now) == []
    sample = reading(sensor, now)
    sample[0]["room_id"] = "r"
    events = await engine.evaluate(sample, now)
    assert len(events) == 1
