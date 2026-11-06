"""Archived LT driver for historical benchmark scripts only; not used by Runtime."""

import asyncio
import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from .address import canonical_address
from .protocol import FrameParser, decode_measurement, encode_frame

logger = logging.getLogger(__name__)
SERVICE_UUID = "0000ffe5-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000ffe8-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000ffe9-0000-1000-8000-00805f9b34fb"
BATTERY_UUID = "00002a19-0000-1000-8000-00805f9b34fb"


class BatteryCharacteristic(Protocol):
    @property
    def properties(self) -> Sequence[str]: ...


class BatteryServices[Characteristic](Protocol):
    def get_characteristic(self, specifier: str, /) -> Characteristic | None: ...


class BatteryClient[Characteristic](Protocol):
    @property
    def services(self) -> BatteryServices[Characteristic]: ...

    async def read_gatt_char(self, characteristic: Characteristic, /) -> bytes | bytearray: ...


class LTDriver:
    protocol = "lt_thermometer"

    def __init__(self, diagnostics: bool = False) -> None:
        self.diagnostics = diagnostics
        self.devices: dict[str, BLEDevice] = {}
        self._battery: dict[str, dict[str, Any]] = {}
        self._battery_next: dict[str, float] = {}

    async def _read_battery[Characteristic: BatteryCharacteristic](
        self, client: BatteryClient[Characteristic], address: str
    ) -> dict[str, Any]:
        now = time.monotonic()
        if now < self._battery_next.get(address, 0):
            return dict(self._battery.get(address, {}))
        self._battery_next[address] = now + 300
        try:
            char = client.services.get_characteristic(BATTERY_UUID)
            if char is None or "read" not in char.properties:
                self._battery_next[address] = now + 3600
                return dict(self._battery.get(address, {}))
            async with asyncio.timeout(2):
                value = await client.read_gatt_char(char)
            if len(value) != 1 or not 0 <= value[0] <= 100:
                raise ValueError("Invalid standard Battery Level value")
            self._battery[address] = {
                "battery_percent": int(value[0]),
                "battery_timestamp": datetime.now(UTC).isoformat(),
            }
            self._battery_next[address] = now + 3600
        except Exception as exc:
            logger.info("Optional battery read address=%s failed: %s", address, type(exc).__name__)
        return dict(self._battery.get(address, {}))

    async def discover(self, timeout: float = 15) -> list[dict[str, Any]]:
        self.devices = {}
        devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
        found = []
        for device, adv in devices.values():
            name = adv.local_name or device.name or ""
            if "LT_" not in name and SERVICE_UUID not in adv.service_uuids:
                continue
            self.devices[device.address.upper()] = device
            row = {
                "name": name or device.address,
                "address": device.address,
                "rssi": adv.rssi,
                "protocol": self.protocol,
                "service_uuids": adv.service_uuids,
                "manufacturer_data": {str(k): v.hex() for k, v in adv.manufacturer_data.items()},
                "service_data": {k: v.hex() for k, v in adv.service_data.items()},
            }
            found.append(row)
            if self.diagnostics:
                logger.info("BLE advertisement %s", row)
        return found

    async def read_current(self, address: str, timeout: float = 12) -> dict[str, Any]:
        device = self.devices.get(canonical_address(address))
        if device is None:
            raise LookupError("Sensor not discovered in current scan")
        parser = FrameParser()
        result: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()

        def receive(_sender: BleakGATTCharacteristic, data: bytearray) -> None:
            if self.diagnostics:
                logger.info("BLE notification address=%s hex=%s", address, data.hex())
            for frame in parser.feed(bytes(data)):
                if frame.command != 0xA2:
                    continue
                try:
                    sample = decode_measurement(frame)
                except ValueError:
                    logger.warning("Invalid measurement address=%s", address)
                    continue
                if not result.done():
                    result.set_result({**sample, "timestamp": datetime.now(UTC).isoformat()})

        async with asyncio.timeout(timeout + 17):
            async with BleakClient(device, timeout=15) as client:
                notify = client.services.get_characteristic(NOTIFY_UUID)
                write = client.services.get_characteristic(WRITE_UUID)
                if notify is None or write is None:
                    raise ValueError("Sensor lacks expected LT characteristics")
                if self.diagnostics:
                    for service in client.services:
                        logger.info(
                            "GATT service=%s chars=%s",
                            service.uuid,
                            [(c.uuid, c.properties) for c in service.characteristics],
                        )
                await client.start_notify(notify, receive)
                try:
                    await client.write_gatt_char(
                        write, encode_frame(0xA2, b"\x01"), response="write" in write.properties
                    )
                    sample = await asyncio.wait_for(result, timeout)
                    sample.update(await self._read_battery(client, canonical_address(address)))
                    return sample
                finally:
                    if client.is_connected:
                        await client.stop_notify(notify)
