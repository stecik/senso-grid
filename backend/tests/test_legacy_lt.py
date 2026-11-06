"""Archived LT driver coverage for historical benchmark tooling."""

from types import SimpleNamespace
from typing import Any, Never

import pytest

ADDRESS = "AA:BB:CC:DD:EE:FF"


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
