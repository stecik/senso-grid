import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Never

import pytest
from sensogrid.config import Settings
from sensogrid.db import Database
from sensogrid.runtime import Runtime

ADDRESS = "AA:BB:CC:DD:EE:FF"


class Driver:
    protocol = "lt_thermometer"

    def __init__(self) -> None:
        self.visible = True
        self.failing = True
        self.reads = 0
        self.scans = 0

    async def discover(self, timeout: float = 15) -> list[dict[str, Any]]:
        self.scans += 1
        return [{"address": ADDRESS, "rssi": -60}] if self.visible else []

    async def read_current(self, address: str, timeout: float = 12) -> dict[str, Any]:
        assert address == ADDRESS
        self.reads += 1
        if self.failing:
            raise TimeoutError("No reply")
        return {
            "temperature": 22.4,
            "humidity": 47,
            "battery_raw": 1,
            "timestamp": datetime.now(UTC).isoformat(),
        }


class Clock:
    def __init__(self) -> None:
        self.value = 1000.0
        self.delays: list[float] = []
        self.stop_at = float("inf")

    def now(self) -> float:
        return self.value

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        self.value += delay
        if self.value >= self.stop_at:
            raise asyncio.CancelledError


def collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Runtime, Driver, Clock, str]:
    db = Database(tmp_path / "meta.sqlite3")
    sensor_id = db.add_sensor({"name": "Desk", "address": ADDRESS, "protocol": "lt_thermometer"})
    runtime = Runtime(Settings(mode="ble", data_dir=tmp_path), db)
    runtime._outbox.mkdir()
    driver, clock = Driver(), Clock()
    runtime.driver = driver
    monkeypatch.setattr("sensogrid.runtime.time", SimpleNamespace(monotonic=clock.now))
    monkeypatch.setattr("sensogrid.runtime.asyncio.sleep", clock.sleep)
    return runtime, driver, clock, sensor_id


@pytest.mark.asyncio
async def test_failed_read_has_only_two_attempts_then_escalating_cooldown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, driver, clock, sid = collection(tmp_path, monkeypatch)
    for expected in [300, 600, 1200, 1200]:
        before = driver.reads
        with pytest.raises(TimeoutError):
            await runtime.preview_sensor(ADDRESS)
        assert driver.reads - before == 2
        assert runtime._retry_after[sid] - clock.now() == expected
        assert sid in runtime.unavailable_sensors
        with pytest.raises(LookupError):
            await runtime.preview_sensor(ADDRESS)
        assert driver.reads - before == 2
        clock.value = runtime._retry_after[sid]
    driver.failing = False
    await runtime.preview_sensor(ADDRESS)
    assert sid not in runtime.unavailable_sensors
    driver.failing = True
    with pytest.raises(TimeoutError):
        await runtime.preview_sensor(ADDRESS)
    assert runtime._retry_after[sid] - clock.now() == 300


@pytest.mark.asyncio
async def test_new_scan_absence_prevents_connection_to_previously_visible_sensor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, driver, clock, sid = collection(tmp_path, monkeypatch)
    driver.failing = False
    await runtime.preview_sensor(ADDRESS)
    previous = dict(runtime._latest[sid])
    driver.visible = False
    clock.value += 300
    with pytest.raises(LookupError):
        await runtime.preview_sensor(ADDRESS)
    assert driver.reads == 1
    assert runtime._latest[sid] == previous
    assert runtime._retry_after[sid] - clock.now() == 300


@pytest.mark.asyncio
async def test_collector_does_not_retry_offline_sensor_every_thirty_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, driver, clock, sid = collection(tmp_path, monkeypatch)
    clock.stop_at = 1300
    with pytest.raises(asyncio.CancelledError):
        await runtime._collect_loop()
    assert driver.reads == 2
    assert sid in runtime.unavailable_sensors


@pytest.mark.asyncio
async def test_default_collector_waits_five_minutes_after_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, driver, clock, _ = collection(tmp_path, monkeypatch)
    driver.failing = False
    clock.stop_at = 1300
    with pytest.raises(asyncio.CancelledError):
        await runtime._collect_loop()
    assert driver.reads == 1
    clock.stop_at = 1306
    with pytest.raises(asyncio.CancelledError):
        await runtime._collect_loop()
    assert driver.reads == 2


def test_ble_upgrade_raises_saved_short_intervals_once_and_preserves_long_intervals(
    tmp_path: Path,
) -> None:
    path = tmp_path / "meta.sqlite3"
    db = Database(path)
    db.set_config("system", {"sample_interval_seconds": 60, "stale_after_seconds": 1000})
    for name, address, interval in [
        ("Fast", "AA", 60),
        ("Slow", "BB", 900),
        ("Inherited", "CC", None),
    ]:
        sid = db.add_sensor({"name": name, "address": address, "protocol": "lt_thermometer"})
        db.patch_sensor(sid, {"sample_interval_seconds": interval})
    ble_settings = Settings(mode="ble", data_dir=tmp_path)
    upgraded = Database(path, ble_settings)
    assert upgraded.system_settings() == {
        "sample_interval_seconds": 300,
        "stale_after_seconds": 1000,
    }
    intervals = {s["name"]: s["sample_interval_seconds"] for s in upgraded.all_sensors()}
    assert intervals == {"Fast": 300, "Slow": 900, "Inherited": 300}
    upgraded.set_config("system", {"sample_interval_seconds": 600, "stale_after_seconds": 1000})
    assert Database(path, ble_settings).system_settings()["sample_interval_seconds"] == 600


@pytest.mark.asyncio
async def test_default_profile_never_connects_to_two_sensors_at_once(tmp_path: Path) -> None:
    class ParallelDriver(Driver):
        active = 0
        peak = 0

        async def discover(self, timeout: float = 15) -> list[dict[str, Any]]:
            return [{"address": address, "rssi": -60} for address in [ADDRESS, "BB"]]

        async def read_current(self, address: str, timeout: float = 12) -> dict[str, Any]:
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0)
                return {
                    "temperature": 22,
                    "humidity": 45,
                    "battery_raw": 1,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            finally:
                self.active -= 1

    runtime = Runtime(Settings(mode="ble", data_dir=tmp_path), Database(tmp_path / "meta.sqlite3"))
    driver = ParallelDriver()
    runtime.driver = driver
    await asyncio.gather(runtime.preview_sensor(ADDRESS), runtime.preview_sensor("BB"))
    assert driver.peak == 1


@pytest.mark.asyncio
async def test_scan_failure_also_waits_five_minutes_before_next_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, _, clock, sid = collection(tmp_path, monkeypatch)

    class BrokenScanner(Driver):
        async def discover(self, timeout: float = 15) -> list[dict[str, Any]]:
            self.scans += 1
            raise RuntimeError("Adapter unavailable")

    driver = BrokenScanner()
    runtime.driver = driver
    clock.stop_at = 1300
    with pytest.raises(asyncio.CancelledError):
        await runtime._collect_loop()
    assert driver.scans == 1
    assert driver.reads == 0
    assert sid in runtime.unavailable_sensors


@pytest.mark.asyncio
async def test_offline_sensor_does_not_prevent_healthy_sensor_measurement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, _, clock, sid = collection(tmp_path, monkeypatch)
    db = Database(tmp_path / "meta.sqlite3")
    healthy_id = db.add_sensor({"name": "Other", "address": "BB", "protocol": "lt_thermometer"})

    class MixedDriver(Driver):
        async def discover(self, timeout: float = 15) -> list[dict[str, Any]]:
            return [{"address": a, "rssi": -60} for a in [ADDRESS, "BB"]]

        async def read_current(self, address: str, timeout: float = 12) -> dict[str, Any]:
            if address == ADDRESS:
                raise TimeoutError("No reply")
            return {
                "temperature": 21,
                "humidity": 45,
                "battery_raw": 1,
                "timestamp": datetime.now(UTC).isoformat(),
            }

    runtime.driver = MixedDriver()
    clock.stop_at = 1300
    with pytest.raises(asyncio.CancelledError):
        await runtime._collect_loop()
    assert sid in runtime.unavailable_sensors
    assert runtime._latest[healthy_id]["temperature"] == 21
    assert runtime.read_states[healthy_id] == "ready"


def test_gentle_upgrade_does_not_change_off_mode_or_repeat_user_configuration(
    tmp_path: Path,
) -> None:
    path = tmp_path / "meta.sqlite3"
    db = Database(path)
    db.set_config("system", {"sample_interval_seconds": 60, "stale_after_seconds": 1000})
    off = Database(path, Settings(mode="off", data_dir=tmp_path))
    assert off.system_settings()["sample_interval_seconds"] == 60
    ble_settings = Settings(mode="ble", data_dir=tmp_path)
    upgraded = Database(path, ble_settings)
    upgraded.set_config("system", {"sample_interval_seconds": 120, "stale_after_seconds": 1000})
    assert Database(path, ble_settings).system_settings()["sample_interval_seconds"] == 120


@pytest.mark.asyncio
@pytest.mark.parametrize("scan_fails", [False, True])
async def test_lt_driver_removes_devices_missing_from_a_later_scan(
    monkeypatch: pytest.MonkeyPatch,
    scan_fails: bool,
) -> None:
    from bleak.backends.device import BLEDevice
    from sensogrid.ble import lt

    device = BLEDevice(ADDRESS, "LT_Test", None)
    adv = SimpleNamespace(
        local_name="LT_Test", service_uuids=[], rssi=-60, manufacturer_data={}, service_data={}
    )
    present = True

    async def scan(**kwargs: Any) -> dict[str, Any]:
        if not present and scan_fails:
            raise OSError("Adapter unavailable")
        return {ADDRESS: (device, adv)} if present else {}

    def unexpected_connection(*args: Any, **kwargs: Any) -> Never:
        pytest.fail("A device absent from the latest scan must not be connected")

    monkeypatch.setattr(lt.BleakScanner, "discover", scan)
    monkeypatch.setattr(lt, "BleakClient", unexpected_connection)
    driver = lt.LTDriver()
    assert len(await driver.discover()) == 1
    present = False
    if scan_fails:
        with pytest.raises(OSError):
            await driver.discover()
    else:
        assert await driver.discover() == []
    with pytest.raises(LookupError):
        await driver.read_current(ADDRESS)


@pytest.mark.asyncio
async def test_concurrent_manual_reads_cannot_bypass_failure_cooldown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    yield_control = asyncio.sleep
    runtime, _, _, _ = collection(tmp_path, monkeypatch)

    class ConcurrentDriver(Driver):
        async def discover(self, timeout: float = 15) -> list[dict[str, Any]]:
            await yield_control(0)
            return await super().discover(timeout)

        async def read_current(self, address: str, timeout: float = 12) -> dict[str, Any]:
            await yield_control(0)
            return await super().read_current(address, timeout)

    driver = ConcurrentDriver()
    runtime.driver = driver
    results = await asyncio.gather(
        runtime.preview_sensor(ADDRESS), runtime.preview_sensor(ADDRESS), return_exceptions=True
    )
    assert driver.reads == 2
    assert isinstance(results[0], TimeoutError)
    assert isinstance(results[1], LookupError)
