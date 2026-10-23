from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sensogrid.runtime import Runtime


class DB:
    def config(self, key, default):
        return getattr(self, "saved_config", {}).get(key, default)

    def set_config(self, key, value):
        if not hasattr(self, "saved_config"):
            self.saved_config = {}
        self.saved_config[key] = value

    def all_sensors(self):
        return [{"id": "s1", "name": "Bedroom", "room_id": "r1", "enabled": True}]

    def system_settings(self):
        return {"sample_interval_seconds": 900}


def settings(tmp_path, mode="demo"):
    return SimpleNamespace(
        mode=mode,
        data_dir=tmp_path,
        diagnostics=False,
        ble_concurrency=10,
        influx_url="http://localhost:8181",
        influx_token="",
        influx_database="sensogrid",
    )


@pytest.mark.asyncio
async def test_explicit_demo_and_filtered_history(tmp_path):
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


def test_durable_outbox_and_no_fake_live_samples(tmp_path):
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


@pytest.mark.asyncio
async def test_inflight_read_uses_current_room_and_ignores_disabled(tmp_path):
    import asyncio

    class MutableDB(DB):
        room = "old"
        enabled = True

        def all_sensors(self):
            return [
                {
                    "id": "s1",
                    "address": "02:00:00:5E:00:03",
                    "protocol": "lt_thermometer",
                    "room_id": self.room,
                    "enabled": self.enabled,
                    "sample_interval_seconds": 10,
                }
            ]

        def note_seen(self, *args):
            pass

    db = MutableDB()
    runtime = Runtime(settings(tmp_path, "ble"), db)
    captured = []
    done = asyncio.Event()

    class Driver:
        protocol = "lt_thermometer"

        async def discover(self, **kwargs):
            return [{"address": "02:00:00:5E:00:03", "rssi": -50}]

        async def read_current(self, address):
            db.room = "new"
            return {
                "timestamp": "2026-01-01T00:00:00Z",
                "temperature": 20,
                "humidity": 40,
                "battery_raw": 1,
            }

    runtime.driver = Driver()

    def capture(sample):
        captured.append(sample)
        done.set()

    runtime._queue_sample = capture
    task = asyncio.create_task(runtime._collect_loop())
    await asyncio.wait_for(done.wait(), 1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert captured[0]["room_id"] == "new"


def test_reassignment_hides_old_live_reading(tmp_path):
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


@pytest.mark.asyncio
async def test_preview_retries_four_times_with_backoff_then_succeeds(tmp_path, monkeypatch):
    delays = []

    async def pause(delay):
        delays.append(delay)

    monkeypatch.setattr("sensogrid.runtime.asyncio.sleep", pause)

    class Driver:
        calls = 0

        async def discover(self, **kwargs):
            return []

        async def read_current(self, address):
            self.calls += 1
            if self.calls < 5:
                raise TimeoutError("Temporary radio loss")
            return {
                "temperature": 22.4,
                "humidity": 47,
                "timestamp": datetime.now(UTC).isoformat(),
                "battery_raw": 1,
            }

    runtime = Runtime(settings(tmp_path, "ble"), DB())
    runtime.driver = Driver()
    result = await runtime.preview_sensor("AA:BB")
    assert result["temperature"] == 22.4
    assert runtime.driver.calls == 5
    assert delays == [1, 2, 4, 8]


def test_last_known_battery_zero_survives_a_later_optional_read_failure(tmp_path):
    from sensogrid.db import Database

    db = Database(tmp_path / "metadata.sqlite3")
    sensor_id = db.add_sensor(
        {"name": "Desk", "address": "AA:BB", "room_id": None, "protocol": "lt_thermometer"}
    )
    runtime = Runtime(settings(tmp_path, "ble"), db)
    runtime._outbox.mkdir()
    timestamp = datetime.now(UTC).isoformat()
    row = {"timestamp": timestamp, "temperature": 22.4, "humidity": 47, "battery_raw": 0}
    runtime._publish_reading("AA:BB", {**row, "battery_percent": 0, "battery_timestamp": timestamp})
    runtime._publish_reading("AA:BB", row)
    assert runtime._latest[sensor_id]["battery_percent"] == 0
    assert runtime._latest[sensor_id]["battery_timestamp"] == timestamp


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff"])
async def test_registered_preview_survives_restart_without_new_radio_read(tmp_path, address):
    from sensogrid.db import Database

    db = Database(tmp_path / "metadata.sqlite3")
    sensor_id = db.add_sensor(
        {
            "name": "Desk",
            "address": "AA:BB:CC:DD:EE:FF",
            "room_id": None,
            "protocol": "lt_thermometer",
        }
    )
    sample = {
        "temperature": 22.4,
        "humidity": 47,
        "timestamp": datetime.now(UTC).isoformat(),
        "battery_raw": 1,
    }

    class Driver:
        async def read_current(self, address):
            return sample

    runtime = Runtime(settings(tmp_path, "ble"), db)
    runtime._outbox.mkdir()
    runtime.driver = Driver()
    await runtime.preview_sensor(address)
    restarted = Runtime(settings(tmp_path, "ble"), db)
    assert len(restarted.current()) == 1
    assert restarted.current()[0]["sensor_id"] == sensor_id
    assert restarted.current()[0]["temperature"] == 22.4


@pytest.mark.asyncio
@pytest.mark.parametrize("room_changed,failed", [(True, False), (False, True)])
async def test_room_change_or_failure_does_not_wait_for_sampling_interval(
    tmp_path, room_changed, failed
):
    import asyncio
    import time

    class ChangedDB(DB):
        def all_sensors(self):
            return [
                {
                    "id": "s1",
                    "address": "AA:BB",
                    "protocol": "lt_thermometer",
                    "room_id": "new-room",
                    "enabled": True,
                    "sample_interval_seconds": 900,
                }
            ]

        def note_seen(self, *args):
            pass

    class Driver:
        protocol = "lt_thermometer"

        async def discover(self, **kwargs):
            return [{"address": "AA:BB", "rssi": -60}]

        async def read_current(self, address):
            return {
                "temperature": 22.4,
                "humidity": 47,
                "timestamp": datetime.now(UTC).isoformat(),
                "battery_raw": 1,
            }

    runtime = Runtime(settings(tmp_path, "ble"), ChangedDB())
    runtime.driver = Driver()
    runtime._last_poll["s1"] = time.monotonic()
    runtime._latest["s1"] = {
        "sensor_id": "s1",
        "room_id": "old-room" if room_changed else "new-room",
        "temperature": 20,
        "humidity": 40,
    }
    if failed:
        runtime.unavailable_sensors.add("s1")
        runtime._retry_after["s1"] = time.monotonic() - 1
    captured = []
    runtime._queue_sample = captured.append
    task = asyncio.create_task(runtime._collect_loop())
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert captured and captured[0]["room_id"] == "new-room"


@pytest.mark.asyncio
async def test_five_failed_reads_preserve_last_sample_and_stop_retrying(tmp_path, monkeypatch):
    from sensogrid.db import Database

    db = Database(tmp_path / "metadata.sqlite3")
    sensor_id = db.add_sensor(
        {"name": "Desk", "address": "AA:BB", "room_id": None, "protocol": "lt_thermometer"}
    )
    runtime = Runtime(settings(tmp_path, "ble"), db)
    sample = {
        "sensor_id": sensor_id,
        "room_id": None,
        "temperature": 22.4,
        "humidity": 47,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    runtime._latest[sensor_id] = sample
    delays = []

    async def pause(delay):
        delays.append(delay)

    monkeypatch.setattr("sensogrid.runtime.asyncio.sleep", pause)

    class Driver:
        calls = 0

        async def discover(self, **kwargs):
            return []

        async def read_current(self, address):
            self.calls += 1
            raise TimeoutError("Radio unavailable")

    runtime.driver = Driver()
    with pytest.raises(TimeoutError):
        await runtime.preview_sensor("AA:BB")
    assert runtime.driver.calls == 5
    assert delays == [1, 2, 4, 8]
    assert runtime._latest[sensor_id] == sample
    assert runtime.read_states[sensor_id] == "unavailable"
    assert sensor_id in Runtime(settings(tmp_path, "ble"), db).unavailable_sensors


@pytest.mark.asyncio
async def test_preview_reads_distinct_devices_concurrently_with_limit_ten(tmp_path):
    import asyncio

    active = 0
    peak = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    class Driver:
        async def read_current(self, address):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if active == 10:
                entered.set()
            try:
                await release.wait()
                return {
                    "temperature": 22.4,
                    "humidity": 47,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "battery_raw": 1,
                }
            finally:
                active -= 1

    runtime = Runtime(settings(tmp_path, "ble"), DB())
    runtime.driver = Driver()
    tasks = [asyncio.create_task(runtime.preview_sensor(f"AA:{index:02X}")) for index in range(12)]
    try:
        try:
            await asyncio.wait_for(entered.wait(), 0.3)
        except TimeoutError:
            pass
        assert peak == 10
        release.set()
        assert len(await asyncio.gather(*tasks)) == 12
        assert peak == 10
    finally:
        release.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
