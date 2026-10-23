"""Application collection runtime with explicit simulation and durable write retry."""

import asyncio
import json
import logging
import math
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .ble.address import address_key, canonical_address
from .ble.lt import LTDriver
from .ble.radio import BLERadio
from .timeseries import InfluxStore, aggregate_points, bucket_start, utc

logger = logging.getLogger(__name__)
READ_ATTEMPTS = 5


class Runtime:
    def __init__(self, settings: Any, db: Any) -> None:
        self.settings, self.db = settings, db
        self.driver = LTDriver(settings.diagnostics)
        self.store = InfluxStore(
            settings.influx_url, settings.influx_token, settings.influx_database
        )
        self.state = {
            "collector": "starting",
            "storage": "demo" if settings.mode == "demo" else "starting",
            "last_error": None,
        }
        self._latest: dict[str, dict] = db.config("latest_readings", {})
        self.read_states: dict[str, str] = {}
        self.unavailable_sensors: set[str] = set(db.config("unavailable_sensors", []))
        self._tasks: list[asyncio.Task] = []
        self._radio = BLERadio(settings.ble_concurrency)
        self._last_scan = 0.0
        self._last_poll: dict[str, float] = {}
        self._retry_after: dict[str, float] = {}
        self._outbox = Path(settings.data_dir) / "outbox"
        self._db_ready = False

    async def start(self) -> None:
        if self.settings.mode == "demo":
            self.state["collector"] = "demo"
            return
        self._outbox.mkdir(parents=True, exist_ok=True)
        self._tasks.append(asyncio.create_task(self._flush_loop(), name="influx-writer"))
        if self.settings.mode == "ble":
            self._tasks.append(asyncio.create_task(self._collect_loop(), name="ble-collector"))
        else:
            self.state["collector"] = "disabled"

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.store.close()

    def _sample_demo(self, sensor: dict, when: datetime) -> dict:
        phase = sum(map(ord, sensor["id"])) / 30
        hours = when.timestamp() / 3600
        temperature = round(
            21.2 + 1.6 * math.sin(hours / 6 + phase) + 0.4 * math.sin(hours * 1.3 + phase), 1
        )
        humidity = round(48 + 8 * math.sin(hours / 9 + phase), 1)
        return {
            "sensor_id": sensor["id"],
            "room_id": sensor.get("room_id"),
            "timestamp": when.isoformat(),
            "temperature": temperature,
            "humidity": humidity,
            "rssi": -58,
            "battery_raw": None,
            "source": "demo",
        }

    def current(self) -> list[dict]:
        sensors = self.db.all_sensors()
        if self.settings.mode == "demo":
            now = datetime.now(UTC).replace(second=0, microsecond=0)
            return [self._sample_demo(s, now) for s in sensors if s.get("enabled", True)]
        enabled = {s["id"]: s for s in sensors if s.get("enabled", True)}
        return [
            dict(row)
            for key, row in self._latest.items()
            if key in enabled
            and row.get("room_id") == enabled[key].get("room_id")
            and row.get("sensor_address", enabled[key].get("address"))
            == enabled[key].get("address")
        ]

    async def discover(self) -> list[dict]:
        if self.settings.mode == "demo":
            return [
                {
                    "name": "LT_7506 (demo)",
                    "address": "02:00:00:5E:00:03",
                    "rssi": -61,
                    "protocol": "lt_thermometer",
                    "service_uuids": [],
                    "manufacturer_data": {},
                    "service_data": {},
                }
            ]
        return await self._discover_devices()

    async def _discover_devices(
        self, timeout: float = 15, newer_than: float | None = None
    ) -> list[dict]:
        async with self._radio.scan():
            if newer_than is not None and self._last_scan > newer_than:
                return []
            devices = await self.driver.discover(timeout=timeout)
            self._last_scan = time.monotonic()
            return devices

    async def preview_sensor(self, address: str) -> dict:
        if self.settings.mode == "demo":
            return {
                "temperature": 21.2,
                "humidity": 48.0,
                "timestamp": datetime.now(UTC).isoformat(),
                "source": "demo",
            }
        if self.settings.mode != "ble":
            raise ValueError("Bluetooth collection is disabled")
        sensor = next(
            (
                s
                for s in self.db.all_sensors()
                if address_key(s.get("address") or "") == address_key(address)
                and s.get("enabled", True)
            ),
            None,
        )
        sensor_id = sensor["id"] if sensor else None
        row = await self._read_with_retry(address, sensor_id)
        self._publish_reading(address, row)
        return row

    async def _read_with_retry(self, address: str, sensor_id: str | None = None) -> dict:
        address = canonical_address(address)
        started = time.monotonic()
        for attempt in range(READ_ATTEMPTS):
            if sensor_id:
                self.read_states[sensor_id] = "reading" if attempt == 0 else "retrying"
            try:
                if attempt:
                    await self._discover_devices(timeout=5, newer_than=started)
                async with self._radio.read(address):
                    return await self.driver.read_current(address)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if attempt == READ_ATTEMPTS - 1:
                    logger.warning(
                        "BLE read exhausted address=%s attempts=%s reason=%s: %s",
                        address,
                        READ_ATTEMPTS,
                        type(exc).__name__,
                        str(exc),
                        exc_info=True,
                    )
                    if sensor_id:
                        self.read_states[sensor_id] = "unavailable"
                        self.unavailable_sensors.add(sensor_id)
                        self.db.set_config("unavailable_sensors", sorted(self.unavailable_sensors))
                        self._retry_after[sensor_id] = time.monotonic() + 30
                    raise
                if sensor_id:
                    self.read_states[sensor_id] = "retrying"
                delay = 2**attempt
                logger.info(
                    "BLE retry address=%s attempt=%s delay=%s reason=%s",
                    address,
                    attempt + 2,
                    delay,
                    type(exc).__name__,
                )
                await asyncio.sleep(delay)
        raise AssertionError("Retry loop exhausted")

    def _publish_reading(self, address: str, row: dict, rssi: int | None = None) -> None:
        sensors = self.db.all_sensors()
        sensor = next(
            (
                s
                for s in sensors
                if address_key(s.get("address") or "") == address_key(address)
                and s.get("enabled", True)
            ),
            None,
        )
        if sensor is None:
            return
        sample = {k: row[k] for k in ("timestamp", "temperature", "humidity", "battery_raw")}
        previous = self._latest.get(sensor["id"], {})
        if previous.get("sensor_address") != sensor["address"]:
            previous = {}
        battery = row if row.get("battery_percent") is not None else previous
        sample.update({key: battery.get(key) for key in ("battery_percent", "battery_timestamp")})
        sample.update(
            sensor_id=sensor["id"],
            room_id=sensor.get("room_id"),
            sensor_address=sensor["address"],
            rssi=rssi,
            source="ble",
        )
        self._queue_sample(sample)
        self._latest[sensor["id"]] = sample
        ids = {s["id"] for s in sensors}
        self._latest = {key: value for key, value in self._latest.items() if key in ids}
        self.db.set_config("latest_readings", self._latest)
        self.db.note_seen(sensor["id"], sample["timestamp"])
        self._last_poll[sensor["id"]] = time.monotonic()
        self._retry_after.pop(sensor["id"], None)
        self.read_states[sensor["id"]] = "ready"
        self.unavailable_sensors.discard(sensor["id"])
        self.unavailable_sensors.intersection_update(ids)
        self.db.set_config("unavailable_sensors", sorted(self.unavailable_sensors))

    async def history(
        self,
        start: datetime,
        end: datetime,
        room_ids: list[str],
        sensor_ids: list[str],
        bucket: str,
    ) -> list[dict]:
        start, end = utc(start), utc(end)
        if start >= end or end - start > timedelta(days=366):
            raise ValueError("Choose a valid time range of at most 366 days")
        if self.settings.mode != "demo":
            return await self.store.query(start, end, room_ids, sensor_ids, bucket)
        rows = []
        # One generated value per 15-minute slot; simulation is never persisted.
        cursor = start.replace(second=0, microsecond=0)
        cursor -= timedelta(minutes=cursor.minute % 15)
        if cursor < start:
            cursor += timedelta(minutes=15)
        sensors = [
            s
            for s in self.db.all_sensors()
            if (not sensor_ids or s["id"] in sensor_ids)
            and (not room_ids or s.get("room_id") in room_ids)
        ]
        if bucket == "raw" and ((end - start).total_seconds() / 900) * len(sensors) > 20000:
            raise ValueError("Too many points; choose a coarser aggregation")
        # Accumulate into calendar buckets without retaining a year of raw points.
        groups: dict[tuple, dict] = {}
        while cursor < end:
            for sensor in sensors:
                sample = self._sample_demo(sensor, cursor)
                key = (
                    bucket_start(cursor, bucket).isoformat(),
                    sensor["id"],
                    sensor.get("room_id"),
                )
                group = groups.setdefault(
                    key,
                    {
                        "timestamp": key[0],
                        "sensor_id": key[1],
                        "room_id": key[2],
                        "temperature": 0.0,
                        "humidity": 0.0,
                        "count": 0,
                        "temperature_min": math.inf,
                        "temperature_max": -math.inf,
                        "humidity_min": math.inf,
                        "humidity_max": -math.inf,
                    },
                )
                group["count"] += 1
                for metric in ("temperature", "humidity"):
                    group[metric] += sample[metric]
                    group[metric + "_min"] = min(group[metric + "_min"], sample[metric])
                    group[metric + "_max"] = max(group[metric + "_max"], sample[metric])
            cursor += timedelta(minutes=15)
        for group in groups.values():
            for metric in ("temperature", "humidity"):
                group[metric] /= group["count"]
            rows.append(group)
        return aggregate_points(rows, "raw")

    def _queue_sample(self, sample: dict) -> None:
        if sum(1 for _ in self._outbox.glob("*.json")) >= 10000:
            raise RuntimeError("Measurement outbox full; restore InfluxDB connectivity")
        name = f"{int(utc(sample['timestamp']).timestamp() * 1000000):020d}-{uuid.uuid4().hex}"
        target = self._outbox / (name + ".json")
        temp = target.with_suffix(".tmp")
        sample = {**sample, "ingested_at": datetime.now(UTC).isoformat()}
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(sample, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(target)

    async def _flush_loop(self) -> None:
        while True:
            try:
                if not self._db_ready:
                    await self.store.ensure_database()
                    self._db_ready = True
                for filename in sorted(self._outbox.glob("*.json")):
                    sample = json.loads(filename.read_text(encoding="utf-8"))
                    await self.store.write(sample)
                    filename.unlink()
                self.state["storage"] = "ready"
                if self.state["collector"] in ("ready", "disabled", "idle"):
                    self.state["last_error"] = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.state["storage"] = "unavailable"
                self.state["last_error"] = "InfluxDB unavailable; measurements queued locally"
                logger.warning("InfluxDB write retry: %s", type(exc).__name__)
                self._db_ready = False
            await asyncio.sleep(10)

    async def _collect_loop(self) -> None:
        while True:
            try:
                sensors = [
                    s for s in self.db.all_sensors() if s.get("enabled", True) and s.get("address")
                ]
                now = time.monotonic()
                default_interval = self.db.system_settings()["sample_interval_seconds"]
                due = []
                for sensor in sensors:
                    latest = self._latest.get(sensor["id"])
                    same_assignment = (
                        latest is not None
                        and latest.get("room_id") == sensor.get("room_id")
                        and latest.get("sensor_address", sensor["address"]) == sensor["address"]
                    )
                    next_poll = (
                        self._last_poll.get(sensor["id"], -float("inf"))
                        + max(10, sensor.get("sample_interval_seconds") or default_interval)
                        if same_assignment
                        else -float("inf")
                    )
                    if sensor["id"] in self.unavailable_sensors:
                        next_poll = -float("inf")
                    if now >= max(next_poll, self._retry_after.get(sensor["id"], 0)):
                        due.append(sensor)
                if not due:
                    self.state["collector"] = (
                        "idle"
                        if not sensors
                        else "degraded"
                        if any(self.read_states.get(s["id"]) == "unavailable" for s in sensors)
                        else "ready"
                    )
                    await asyncio.sleep(3)
                    continue
                self.state["collector"] = "scanning"
                for sensor in due:
                    self.read_states[sensor["id"]] = "reading"
                devices = await self._discover_devices()
                rssi = {d["address"].upper(): d["rssi"] for d in devices}

                async def poll(sensor, cycle_now, cycle_rssi):
                    # A preview may have acquired a fresh sample while discovery waited.
                    latest = self._latest.get(sensor["id"])
                    if (
                        latest
                        and latest.get("room_id") == sensor.get("room_id")
                        and self._last_poll.get(sensor["id"], 0) > cycle_now
                    ):
                        self.read_states[sensor["id"]] = "ready"
                        return
                    self.state["collector"] = "reading"
                    try:
                        if sensor["protocol"] != self.driver.protocol:
                            raise ValueError("Unsupported sensor protocol")
                        row = await self._read_with_retry(sensor["address"], sensor["id"])
                        self._publish_reading(
                            sensor["address"], row, cycle_rssi.get(sensor["address"].upper())
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        self._retry_after[sensor["id"]] = time.monotonic() + 30
                        self.read_states[sensor["id"]] = "unavailable"
                        self.state["last_error"] = (
                            f"Sensor read failed after {READ_ATTEMPTS} attempts; another cycle is scheduled in 30 seconds"
                        )
                        logger.warning(
                            "Sensor %s read failed after retries: %s",
                            sensor["id"],
                            type(exc).__name__,
                        )

                await asyncio.gather(*(poll(sensor, now, rssi) for sensor in due))
                failed = any(self.read_states.get(s["id"]) == "unavailable" for s in sensors)
                self.state["collector"] = "degraded" if failed else "ready"
                if not failed and self.state["storage"] == "ready":
                    self.state["last_error"] = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.state["collector"] = "unavailable"
                self.state["last_error"] = "Bluetooth unavailable; automatic retry scheduled"
                logger.warning(
                    "BLE scan failed: %s: %s", type(exc).__name__, str(exc), exc_info=True
                )
                await asyncio.sleep(15)
            await asyncio.sleep(3)
