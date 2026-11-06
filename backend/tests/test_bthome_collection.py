import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Self

import pytest
from sensogrid.config import Settings
from sensogrid.db import Database
from sensogrid.runtime import Runtime

from backend.tests.test_bthome import advertisement

ADDRESS = "02:00:00:5E:00:01"


def collection(tmp_path: Path) -> tuple[Runtime, Database, str]:
    settings = Settings(mode="ble", data_dir=tmp_path)
    db = Database(tmp_path / "meta.sqlite3", settings)
    sid = db.add_sensor({"name": "Desk", "address": ADDRESS, "protocol": "bthome_v2"})
    runtime = Runtime(settings, db)
    runtime._outbox.mkdir()
    return runtime, db, sid


def test_live_values_update_between_history_samples_without_duplicates(tmp_path: Path) -> None:
    runtime, db, sid = collection(tmp_path)
    advertisement(runtime.driver, "400021015a02630903dd10")
    runtime._collect_once()
    assert runtime.current()[0]["temperature"] == 24.03
    files = list(runtime._outbox.glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text())["source"] == "bthome_v2"
    advertisement(runtime.driver, "400022015902640903de10")
    runtime._collect_once()
    assert runtime.current()[0]["temperature"] == 24.04
    assert runtime.current()[0]["battery_percent"] == 89
    runtime._collect_once()
    assert len(list(runtime._outbox.glob("*.json"))) == 1
    runtime._last_poll[sid] = time.monotonic() - 301
    # No newly received climate frame: do not create a synthetic historical sample.
    runtime._collect_once()
    assert len(list(runtime._outbox.glob("*.json"))) == 1
    advertisement(runtime.driver, "400023015902650903df10")
    runtime._collect_once()
    assert len(list(runtime._outbox.glob("*.json"))) == 2
    assert db.all_sensors()[0]["last_seen"] == runtime.current()[0]["timestamp"]


def test_disabled_legacy_and_unregistered_sensors_do_not_collect(tmp_path: Path) -> None:
    runtime, db, sid = collection(tmp_path)
    db.patch_sensor(sid, {"enabled": False})
    db.add_sensor({"name": "Old", "address": "11:22", "protocol": "lt_thermometer"})
    advertisement(runtime.driver, "400021015a02630903dd10")
    advertisement(runtime.driver, "400021015a02630903dd10", "22:33")
    runtime._collect_once()
    assert not list(runtime._outbox.glob("*.json"))
    assert runtime.current() == []


def test_auxiliary_packets_do_not_restore_stale_climate(tmp_path: Path) -> None:
    runtime, db, sid = collection(tmp_path)
    advertisement(runtime.driver, "400021015a02630903dd10")
    runtime._collect_once()
    first = runtime.current()[0].copy()
    first["timestamp"] = (datetime.now(UTC) - timedelta(seconds=2000)).isoformat()
    runtime._latest[sid] = first
    observation = runtime.driver.devices[ADDRESS]
    observation.received["temperature"] -= 2000
    observation.received["humidity"] -= 2000
    advertisement(runtime.driver, "4000200c6d0b10001101")
    runtime._collect_once()
    assert sid in runtime.unavailable_sensors
    assert runtime.current()[0] == first
    advertisement(runtime.driver, "400022015a02630903dd10")
    runtime._collect_once()
    assert sid not in runtime.unavailable_sensors


def test_reassignment_waits_for_new_frame_and_retains_old_history(tmp_path: Path) -> None:
    runtime, db, sid = collection(tmp_path)
    advertisement(runtime.driver, "400021015a02630903dd10")
    runtime._collect_once()
    plan = db.floorplan()
    plan["rooms"] = [{"id": "r1", "name": "Room", "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]]}]
    db.save_floorplan(plan)
    db.patch_sensor(sid, {"room_id": "r1"})
    runtime._collect_once()
    assert runtime.current() == []
    advertisement(runtime.driver, "400022015a02630903dd10")
    runtime._collect_once()
    assert runtime.current()[0]["room_id"] == "r1"
    samples = [json.loads(path.read_text()) for path in runtime._outbox.glob("*.json")]
    assert {row["room_id"] for row in samples} == {None, "r1"}


@pytest.mark.asyncio
async def test_preview_waits_for_next_advertisement_without_creating_history(
    tmp_path: Path,
) -> None:
    runtime, db, sid = collection(tmp_path)
    advertisement(runtime.driver, "400021015a02630903dd10")
    runtime._collect_once()
    task = asyncio.create_task(runtime.preview_sensor(ADDRESS))
    await asyncio.sleep(0)
    assert not task.done()
    advertisement(runtime.driver, "4000200c6d0b10001101")
    await asyncio.sleep(0)
    assert not task.done()
    advertisement(runtime.driver, "400022015a02640903dd10")
    row = await asyncio.wait_for(task, 1)
    assert row["temperature"] == 24.04
    assert len(list(runtime._outbox.glob("*.json"))) == 1


@pytest.mark.asyncio
async def test_scanner_is_shared_and_stops_on_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    from sensogrid.ble.bthome import BTHomeDriver

    stopped = asyncio.Event()

    class Scanner:
        def __init__(self, **kwargs: Any) -> None:
            self.filtered = bool(kwargs.get("service_uuids"))

        async def __aenter__(self) -> Self:
            # WinRT filters advertised service UUIDs, which ATC may omit even
            # when it includes FCD2 Service Data. Model that real backend boundary.
            if not self.filtered:
                advertisement(driver, "400021015a02630903dd10")
            return self

        async def __aexit__(self, *args: object) -> None:
            stopped.set()

    monkeypatch.setattr("sensogrid.ble.bthome.BleakScanner", Scanner)
    driver = BTHomeDriver()
    task = asyncio.create_task(driver.run())
    await asyncio.sleep(0)
    first, second = await asyncio.gather(driver.discover(0), driver.discover(0))
    assert first == second and first[0]["available"]
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert stopped.is_set() and not driver.running


def test_new_ble_start_preserves_short_user_intervals(tmp_path: Path) -> None:
    db = Database(tmp_path / "meta.sqlite3")
    db.set_config("system", {"sample_interval_seconds": 60, "stale_after_seconds": 1800})
    db = Database(tmp_path / "meta.sqlite3", Settings(mode="ble"))
    assert db.system_settings()["sample_interval_seconds"] == 60


def test_last_live_reading_survives_restart(tmp_path: Path) -> None:
    runtime, db, sid = collection(tmp_path)
    advertisement(runtime.driver, "400021015a02630903dd10")
    runtime._collect_once()
    restarted = Runtime(runtime.settings, db)
    assert restarted.current() == runtime.current()
    assert datetime.fromisoformat(restarted.current()[0]["timestamp"]) <= datetime.now(UTC)
    restarted._collect_once()
    assert sid not in restarted.unavailable_sensors


def test_candidate_eviction_does_not_shorten_configured_staleness(tmp_path: Path) -> None:
    runtime, db, sid = collection(tmp_path)
    advertisement(runtime.driver, "400021015a02630903dd10")
    runtime._collect_once()
    runtime._latest[sid]["timestamp"] = (datetime.now(UTC) - timedelta(seconds=901)).isoformat()
    runtime.driver.devices.clear()
    runtime._collect_once()
    assert sid not in runtime.unavailable_sensors


def test_buffered_packet_cannot_move_into_reassigned_room(tmp_path: Path) -> None:
    runtime, db, sid = collection(tmp_path)
    advertisement(runtime.driver, "400021015a02630903dd10")
    runtime._collect_once()
    advertisement(runtime.driver, "400022015a02640903dd10")
    plan = db.floorplan()
    plan["rooms"] = [{"id": "r1", "name": "Room", "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]]}]
    db.save_floorplan(plan)
    db.patch_sensor(sid, {"room_id": "r1"})
    runtime._collect_once()
    assert runtime.current() == []
    advertisement(runtime.driver, "400023015a02650903dd10")
    runtime._collect_once()
    assert runtime.current()[0]["room_id"] == "r1"


@pytest.mark.asyncio
async def test_silent_post_start_abort_closes_scanner(monkeypatch: pytest.MonkeyPatch) -> None:
    from sensogrid.ble.bthome import BTHomeDriver

    stopped = asyncio.Event()

    class Scanner:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> None:
            stopped.set()

    monkeypatch.setattr("sensogrid.ble.bthome.BleakScanner", Scanner)
    monkeypatch.setattr("sensogrid.ble.bthome.SCANNER_SILENCE_SECONDS", 0.01, raising=False)
    monkeypatch.setattr("sensogrid.ble.bthome.WATCHDOG_INTERVAL", 0.01, raising=False)
    driver = BTHomeDriver()
    with pytest.raises(TimeoutError, match="No BTHome advertisements"):
        await asyncio.wait_for(driver.run(), 0.5)
    assert stopped.is_set() and not driver.running


@pytest.mark.asyncio
async def test_scanner_restarts_after_adapter_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sensogrid.ble.bthome import BTHomeDriver

    runtime, db, sid = collection(tmp_path)
    restarted = asyncio.Event()

    class RecoveringDriver(BTHomeDriver):
        attempts = 0

        async def run(self) -> None:
            self.attempts += 1
            if self.attempts == 1:
                raise OSError("Adapter reset")
            restarted.set()
            await asyncio.Event().wait()

    runtime.driver = RecoveringDriver()
    monkeypatch.setattr("sensogrid.runtime.SCAN_RETRY_SECONDS", 0)
    task = asyncio.create_task(runtime._scan_loop())
    try:
        await asyncio.wait_for(restarted.wait(), 1)
        advertisement(runtime.driver, "400021015a02630903dd10")
        runtime._collect_once()
        assert runtime.current()[0]["temperature"] == 24.03
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
