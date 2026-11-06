"""Receive pvvx ATC BTHome v2 advertisements. No connections or GATT operations."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from .address import canonical_address

logger = logging.getLogger(__name__)
BTHOME_UUID = "0000fcd2-0000-1000-8000-00805f9b34fb"
SCANNER_SILENCE_SECONDS = 120
WATCHDOG_INTERVAL = 30
# Objects emitted by ATC v5.9, including auxiliary GPIO objects we skip.
OBJECTS = {
    0x00: ("packet_id", 1, False, 1),
    0x01: ("battery_percent", 1, False, 1),
    0x02: ("temperature", 2, True, 0.01),
    0x03: ("humidity", 2, False, 0.01),
    0x0C: ("battery_voltage", 2, False, 0.001),
    0x10: (None, 1, False, 1),
    0x11: (None, 1, False, 1),
    0x2E: ("humidity", 1, False, 1),
}


def decode_payload(payload: bytes) -> dict[str, Any]:
    """Decode service data (without UUID); reject encryption and malformed objects."""
    if not payload or payload[0] >> 5 != 2 or payload[0] & 1:
        raise ValueError("Expected unencrypted BTHome v2")
    result: dict[str, Any] = {}
    offset = 1
    while offset < len(payload):
        spec = OBJECTS.get(payload[offset])
        if spec is None:
            break  # Length of an unknown object is unknown; never guess.
        name, size, signed, factor = spec
        offset += 1
        if offset + size > len(payload):
            raise ValueError("Truncated BTHome object")
        value = int.from_bytes(payload[offset : offset + size], "little", signed=signed)
        offset += size
        if name is not None:
            if name in result:
                raise ValueError("Ambiguous repeated BTHome measurement")
            result[name] = round(value * factor, 3) if factor != 1 else value
    if any(not 0 <= result[key] <= 100 for key in ("battery_percent", "humidity") if key in result):
        raise ValueError("Invalid BTHome percentage")
    return result


@dataclass
class Observation:
    name: str
    seen: float
    rssi: int
    fields: dict[str, Any] = field(default_factory=dict)
    received: dict[str, float] = field(default_factory=dict)
    timestamps: dict[str, str] = field(default_factory=dict)
    climate_signatures: dict[str, tuple[Any, ...]] = field(default_factory=dict)


class BTHomeDriver:
    protocol = "bthome_v2"

    def __init__(self, diagnostics: bool = False) -> None:
        self.diagnostics = diagnostics
        self.devices: dict[str, Observation] = {}
        self.running = False
        self.last_packet = time.monotonic()
        self.changed = asyncio.Event()
        self.stats = {"packets": 0, "invalid": 0, "duplicates": 0, "climate_frames": 0}

    def receive(self, device: BLEDevice, adv: AdvertisementData) -> None:
        payload = adv.service_data.get(BTHOME_UUID)
        if payload is None:
            return
        self.stats["packets"] += 1
        self.last_packet = time.monotonic()
        try:
            values = decode_payload(payload)
        except ValueError:
            self.stats["invalid"] += 1
            return
        if not values:
            return
        now, stamp = time.monotonic(), datetime.now(UTC).isoformat()
        address = canonical_address(device.address)
        # Bound memory even in a busy environment; expired candidates are expendable.
        self.devices = {key: row for key, row in self.devices.items() if now - row.seen < 900}
        if address not in self.devices and len(self.devices) >= 256:
            del self.devices[min(self.devices, key=lambda key: self.devices[key].seen)]
        row = self.devices.setdefault(address, Observation(device.name or address, now, adv.rssi))
        row.name = adv.local_name or row.name
        row.seen, row.rssi = now, adv.rssi
        climate = {key: values[key] for key in ("temperature", "humidity") if key in values}
        had_climate = bool(climate)
        for key, value in list(climate.items()):
            signature = (values.get("packet_id"), value)
            if values.get("packet_id") is not None and signature == row.climate_signatures.get(key):
                del climate[key]
                del values[key]
            else:
                row.climate_signatures[key] = signature
        if had_climate and not climate:
            self.stats["duplicates"] += 1
            return
        if climate:
            self.stats["climate_frames"] += 1
        for key, value in values.items():
            if key == "packet_id":
                continue
            row.fields[key], row.received[key], row.timestamps[key] = value, now, stamp
        if self.diagnostics:
            logger.info(
                "BTHome advertisement address=%s rssi=%s data=%s", address, adv.rssi, values
            )
        self.changed.set()

    def latest(self, address: str, max_age: float = 30) -> dict[str, Any] | None:
        row = self.devices.get(canonical_address(address))
        if row is None or not {"temperature", "humidity"} <= row.fields.keys():
            return None
        received = [row.received[key] for key in ("temperature", "humidity")]
        if time.monotonic() - min(received) > max_age or max(received) - min(received) > 30:
            return None
        return {
            **row.fields,
            "timestamp": min(row.timestamps[key] for key in ("temperature", "humidity")),
            "battery_timestamp": row.timestamps.get("battery_percent"),
            "battery_raw": None,
            "rssi": row.rssi,
            "source": self.protocol,
        }

    async def run(self) -> None:
        # Active scanning is portable on both supported backends. It sends scan requests,
        # never connection requests; BlueZ passive scanning requires experimental monitors.
        try:
            # Service Data UUID is not necessarily in the advertised service list.
            # In particular WinRT's UUID filter drops valid ATC advertisements.
            self.last_packet = time.monotonic()
            async with BleakScanner(detection_callback=self.receive):
                self.running = True
                logger.info("BTHome scanner started (advertisements only)")
                while True:
                    await asyncio.sleep(WATCHDOG_INTERVAL)
                    # Some backends silently abort after start (e.g. adapter power loss).
                    # Restart only our scanner; do not manipulate the Bluetooth service.
                    if time.monotonic() - self.last_packet >= SCANNER_SILENCE_SECONDS:
                        raise TimeoutError("No BTHome advertisements; restarting scanner")
        finally:
            self.running = False
            logger.info("BTHome scanner stopped stats=%s", self.stats)

    async def discover(self, timeout: float = 15) -> list[dict[str, Any]]:
        await asyncio.sleep(timeout)
        if not self.running:
            raise RuntimeError("Bluetooth scanner is not running")
        now = time.monotonic()
        return [
            {
                "name": row.name,
                "address": address,
                "rssi": row.rssi,
                "protocol": self.protocol,
                "service_uuids": [BTHOME_UUID],
                "service_data": {},
                "manufacturer_data": {},
                **(self.latest(address) or {}),
                "available": self.latest(address) is not None,
            }
            for address, row in self.devices.items()
            if now - row.seen <= 30
        ]

    async def read_current(self, address: str, timeout: float = 30) -> dict[str, Any]:
        """Wait for a fresh climate advertisement; never poll the thermometer."""
        started = datetime.now(UTC).isoformat()
        async with asyncio.timeout(timeout):
            while True:
                self.changed.clear()
                row = self.latest(address)
                if row and row["timestamp"] > started:
                    return row
                await self.changed.wait()
