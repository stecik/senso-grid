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
from typing import Any, Protocol

from .ble.address import address_key, canonical_address
from .ble.bthome import BTHomeDriver
from .config import Settings
from .timeseries import InfluxStore, aggregate_points, bucket_start, utc

logger = logging.getLogger(__name__)
SCAN_RETRY_SECONDS = 15


class RuntimeDatabase(Protocol):
    """Configuration and sensor metadata required by collection."""

    def config[T](self, key: str, default: T) -> T: ...

    def set_config(self, key: str, value: Any) -> None: ...

    def all_sensors(self) -> list[dict[str, Any]]: ...

    def system_settings(self) -> dict[str, Any]: ...

    def note_seen(self, sensor_id: str, iso_timestamp: str) -> None: ...


class MeasurementStore(Protocol):
    """Persistence operations used by the collector and history API."""

    async def ensure_database(self) -> None: ...

    async def write(self, sample: dict[str, Any]) -> None: ...

    async def query(
        self,
        start: datetime,
        end: datetime,
        room_ids: list[str],
        sensor_ids: list[str],
        bucket: str,
    ) -> list[dict[str, Any]]: ...

    async def close(self) -> None: ...


class Runtime:
    def __init__(self, settings: Settings, db: RuntimeDatabase) -> None:
        self.settings, self.db = settings, db
        self.driver = BTHomeDriver(settings.diagnostics)
        self.store: MeasurementStore = InfluxStore(
            settings.influx_url, settings.influx_token, settings.influx_database
        )
        self.state: dict[str, str | None] = {
            "collector": "starting",
            "storage": "demo" if settings.mode == "demo" else "starting",
            "last_error": None,
        }
        self._latest: dict[str, dict[str, Any]] = db.config("latest_readings", {})
        self.read_states: dict[str, str] = {}
        self.unavailable_sensors: set[str] = set(db.config("unavailable_sensors", []))
        self._tasks: list[asyncio.Task[None]] = []
        self._last_poll: dict[str, float] = {}
        self._assignments = {s["id"]: self._assignment(s) for s in db.all_sensors()}
        self._assignment_since: dict[str, str] = {}
        self._outbox = Path(settings.data_dir) / "outbox"
        self._db_ready = False

    async def start(self) -> None:
        if self.settings.mode == "demo":
            self.state["collector"] = "demo"
            return
        self._outbox.mkdir(parents=True, exist_ok=True)
        self._tasks.append(asyncio.create_task(self._flush_loop(), name="influx-writer"))
        if self.settings.mode == "ble":
            self._tasks.append(asyncio.create_task(self._scan_loop(), name="bthome-scanner"))
            self._tasks.append(asyncio.create_task(self._collect_loop(), name="ble-collector"))
        else:
            self.state["collector"] = "disabled"

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.store.close()

    def _sample_demo(self, sensor: dict[str, Any], when: datetime) -> dict[str, Any]:
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

    def current(self) -> list[dict[str, Any]]:
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

    async def discover(self) -> list[dict[str, Any]]:
        if self.settings.mode == "demo":
            return [
                {
                    "name": "ATC_5E0001 (demo)",
                    "address": "02:00:00:5E:00:01",
                    "rssi": -61,
                    "protocol": self.driver.protocol,
                    "service_uuids": [],
                    "manufacturer_data": {},
                    "service_data": {},
                }
            ]
        if self.settings.mode != "ble":
            raise ValueError("Bluetooth collection is disabled")
        return await self.driver.discover()

    async def preview_sensor(self, address: str) -> dict[str, Any]:
        if self.settings.mode == "demo":
            return {
                "temperature": 21.2,
                "humidity": 48.0,
                "timestamp": datetime.now(UTC).isoformat(),
                "source": "demo",
            }
        if self.settings.mode != "ble":
            raise ValueError("Bluetooth collection is disabled")
        row = await self.driver.read_current(canonical_address(address))
        self._publish_reading(address, row)
        return row

    def _publish_reading(self, address: str, row: dict[str, Any]) -> None:
        sensor = next(
            (
                s
                for s in self.db.all_sensors()
                if address_key(s.get("address") or "") == address_key(address)
                and s.get("enabled", True)
                and s["protocol"] == self.driver.protocol
            ),
            None,
        )
        if sensor is None:
            return
        sid = sensor["id"]
        self._track_assignment(sensor)
        if row["timestamp"] <= self._assignment_since.get(sid, ""):
            return
        previous = self._latest.get(sid, {})
        # A cached frame must never move to another room or create a repeated sample.
        if row["timestamp"] <= previous.get("timestamp", ""):
            return
        sample: dict[str, Any] = {
            **row,
            "sensor_id": sid,
            "room_id": sensor.get("room_id"),
            "sensor_address": sensor["address"],
            "source": self.driver.protocol,
        }
        same_assignment = (
            previous.get("room_id") == sample["room_id"]
            and previous.get("sensor_address") == sample["sensor_address"]
        )
        interval = (
            sensor.get("sample_interval_seconds")
            or self.db.system_settings()["sample_interval_seconds"]
        )
        if (
            not same_assignment
            or time.monotonic() - self._last_poll.get(sid, -float("inf")) >= interval
        ):
            self._queue_sample(sample)
            self._last_poll[sid] = time.monotonic()
        self._latest[sid] = sample
        self.db.set_config("latest_readings", self._latest)
        self.db.note_seen(sid, sample["timestamp"])
        self.read_states[sid] = "ready"
        if sid in self.unavailable_sensors:
            self.unavailable_sensors.discard(sid)
            self.db.set_config("unavailable_sensors", sorted(self.unavailable_sensors))

    @staticmethod
    def _assignment(sensor: dict[str, Any]) -> tuple[Any, ...]:
        return (sensor.get("room_id"), sensor.get("address"), sensor.get("enabled", True))

    def _track_assignment(self, sensor: dict[str, Any]) -> None:
        sid, assignment = sensor["id"], self._assignment(sensor)
        if self._assignments.get(sid) != assignment:
            self._assignments[sid] = assignment
            # Conservatively discard buffered data on room/address/enabled changes.
            # Next newly received frame belongs to the new assignment.
            self._assignment_since[sid] = datetime.now(UTC).isoformat()

    async def history(
        self,
        start: datetime,
        end: datetime,
        room_ids: list[str],
        sensor_ids: list[str],
        bucket: str,
    ) -> list[dict[str, Any]]:
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
        groups: dict[tuple[str, str, str | None], dict[str, Any]] = {}
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

    def _queue_sample(self, sample: dict[str, Any]) -> None:
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

    async def _scan_loop(self) -> None:
        while True:
            try:
                await self.driver.run()
                raise RuntimeError("Bluetooth scanner exited unexpectedly")
            except asyncio.CancelledError:
                raise
            except Exception:
                self.state["collector"] = "unavailable"
                self.state["last_error"] = (
                    "Bluetooth scanner unavailable; automatic retry scheduled"
                )
                logger.exception("BTHome scanner failed; retry in %ss", SCAN_RETRY_SECONDS)
                await asyncio.sleep(SCAN_RETRY_SECONDS)

    def _collect_once(self) -> None:
        stale = self.db.system_settings()["stale_after_seconds"]
        all_sensors = self.db.all_sensors()
        for sensor in all_sensors:
            self._track_assignment(sensor)
        sensors = [s for s in all_sensors if s.get("enabled", True) and s.get("address")]
        for sensor in sensors:
            sid = sensor["id"]
            self._track_assignment(sensor)
            if sensor["protocol"] != self.driver.protocol:
                self.read_states[sid] = "unavailable"
                self.unavailable_sensors.add(sid)
                continue
            row = self.driver.latest(sensor["address"], max_age=stale)
            if row is not None:
                self._publish_reading(sensor["address"], row)
            # Cache retention and scanner restarts must not shorten the configured
            # freshness of a persisted climate sample.
            latest = self._latest.get(sid, {})
            age = (
                (datetime.now(UTC) - utc(latest["timestamp"])).total_seconds()
                if latest
                else float("inf")
            )
            same_assignment = (
                latest.get("room_id") == sensor.get("room_id")
                and latest.get("sensor_address") == sensor["address"]
            )
            if not same_assignment or not 0 <= age <= stale:
                self.read_states[sid] = "unavailable" if sid in self._latest else "waiting"
                self.unavailable_sensors.add(sid)
            else:
                self.read_states[sid] = "ready"
                self.unavailable_sensors.discard(sid)
        ids = {s["id"] for s in self.db.all_sensors()}
        self._latest = {sid: row for sid, row in self._latest.items() if sid in ids}
        self.unavailable_sensors.intersection_update(ids)
        saved = self.db.config("unavailable_sensors", [])
        if saved != sorted(self.unavailable_sensors):
            self.db.set_config("unavailable_sensors", sorted(self.unavailable_sensors))

    async def _collect_loop(self) -> None:
        while True:
            try:
                self._collect_once()
                if self.driver.running:
                    supported = [
                        s
                        for s in self.db.all_sensors()
                        if s.get("enabled", True) and s["protocol"] == self.driver.protocol
                    ]
                    failed = any(s["id"] in self.unavailable_sensors for s in supported)
                    self.state["collector"] = (
                        "idle" if not supported else "degraded" if failed else "ready"
                    )
                    if self.state["storage"] == "ready":
                        self.state["last_error"] = None
            except asyncio.CancelledError:
                raise
            except Exception:
                self.state["collector"] = "degraded"
                self.state["last_error"] = "Cannot store received Bluetooth measurements"
                logger.exception("BTHome collection failed")
            await asyncio.sleep(1)
