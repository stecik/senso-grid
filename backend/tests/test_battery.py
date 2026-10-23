import asyncio
import struct
from types import SimpleNamespace

import pytest
from sensogrid.ble import lt
from sensogrid.ble.protocol import encode_frame


class Client:
    def __init__(self, value=b"\x49", error=False, missing=False):
        self.value, self.error, self.missing = value, error, missing
        self.reads = 0
        self.is_connected = True
        self.services = SimpleNamespace(get_characteristic=self.characteristic)

    def characteristic(self, uuid):
        if uuid == lt.BATTERY_UUID and self.missing:
            return None
        return SimpleNamespace(uuid=uuid, properties=["read", "write"])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def start_notify(self, char, callback):
        self.receive = callback

    async def stop_notify(self, char):
        pass

    async def write_gatt_char(self, *args, **kwargs):
        self.receive(None, bytearray(encode_frame(0xA2, struct.pack(">hHBB", 224, 470, 1, 0))))

    async def read_gatt_char(self, char):
        self.reads += 1
        if self.error:
            raise TimeoutError("battery read failed")
        return self.value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value,expected",
    [(b"\x00", 0), (b"\x64", 100), (b"\xff", None), (b"", None), (b"\x01\x02", None)],
)
async def test_standard_battery_percentage_is_not_the_raw_lt_status(value, expected):
    result = await lt.LTDriver()._read_battery(Client(value), "AA:BB")
    assert result.get("battery_percent") == expected
    if expected is not None:
        assert result["battery_timestamp"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"error": True}, {"missing": True}, {}])
async def test_optional_battery_failure_never_discards_climate_sample(monkeypatch, kwargs):
    client = Client(**kwargs)
    monkeypatch.setattr(lt, "BleakClient", lambda *a, **k: client)
    driver = lt.LTDriver()
    driver.devices["AA:BB"] = object()
    result = await driver.read_current("AA:BB")
    assert result["temperature"] == 22.4
    assert result["humidity"] == 47
    assert result["battery_raw"] == 1
    assert result.get("battery_percent") == (73 if not kwargs else None)


@pytest.mark.asyncio
async def test_battery_is_cached_and_rechecked_after_one_hour(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(lt.time, "monotonic", lambda: now[0])
    driver, client = lt.LTDriver(), Client()
    first = await driver._read_battery(client, "AA:BB")
    assert (await driver._read_battery(client, "AA:BB")) == first
    assert client.reads == 1
    now[0] += 3601
    client.value = b"\x32"
    assert (await driver._read_battery(client, "AA:BB"))["battery_percent"] == 50
    assert client.reads == 2


@pytest.mark.asyncio
async def test_stalled_battery_read_does_not_block_or_discard_climate(monkeypatch):
    class Stalled(Client):
        async def read_gatt_char(self, char):
            await asyncio.Event().wait()

    client = Stalled()
    monkeypatch.setattr(lt, "BleakClient", lambda *a, **k: client)
    driver = lt.LTDriver()
    driver.devices["AA:BB"] = object()
    result = await asyncio.wait_for(driver.read_current("AA:BB"), timeout=4)
    assert result["temperature"] == 22.4
    assert result.get("battery_percent") is None
