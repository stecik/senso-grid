"""InfluxDB 3 storage; finite SQL windows with weighted calendar aggregation."""

import asyncio
import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)
MAX_POINTS = 20000


def utc(value: datetime | str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def query_windows(start: datetime, end: datetime):
    start, end = utc(start), utc(end)
    if start >= end or end - start > timedelta(days=366):
        raise ValueError("Choose a time range between zero and 366 days")
    while start < end:
        stop = min(end, start + timedelta(hours=48))
        yield start, stop
        start = stop


def bucket_start(timestamp: datetime | str, bucket: str) -> datetime:
    dt = utc(timestamp)
    if bucket == "raw":
        return dt
    if bucket == "hour":
        return dt.replace(minute=0, second=0, microsecond=0)
    dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if bucket == "week":
        dt -= timedelta(days=dt.weekday())
    elif bucket == "month":
        dt = dt.replace(day=1)
    elif bucket != "day":
        raise ValueError("Unknown aggregation bucket")
    return dt


def aggregate_points(rows: list[dict], bucket: str) -> list[dict]:
    groups: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        timestamp = bucket_start(row["timestamp"], bucket).isoformat()
        key = (timestamp, row["sensor_id"], row.get("room_id"))
        count = int(row.get("count", 1))
        if count <= 0:
            continue
        values = [float(row[x]) for x in ("temperature", "humidity")]
        if not all(math.isfinite(v) for v in values):
            continue
        group = groups.setdefault(
            key,
            {
                "timestamp": timestamp,
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
        for metric in ("temperature", "humidity"):
            group[metric] += float(row[metric]) * count
            group[metric + "_min"] = min(
                group[metric + "_min"], float(row.get(metric + "_min", row[metric]))
            )
            group[metric + "_max"] = max(
                group[metric + "_max"], float(row.get(metric + "_max", row[metric]))
            )
        group["count"] += count
    for group in groups.values():
        for metric in ("temperature", "humidity"):
            group[metric] /= group["count"]
    return sorted(
        groups.values(), key=lambda r: (r["timestamp"], r["sensor_id"], r["room_id"] or "")
    )


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class InfluxStore:
    def __init__(self, url: str, token: str, database: str) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.database = database
        self._writer = None
        self._inflight: set[asyncio.Task] = set()

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def ensure_database(self) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                self.url + "/api/v3/configure/database",
                headers=self.headers,
                json={"db": self.database},
            )
            if response.status_code not in (200, 201, 204, 409):
                # Some Core releases return 400 for an already-existing database.
                if response.status_code == 400 and "already exists" in response.text.lower():
                    return
                response.raise_for_status()

    async def write(self, sample: dict) -> None:
        operation = asyncio.create_task(asyncio.to_thread(self._write_sync, sample))
        self._inflight.add(operation)
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError:
            await asyncio.gather(operation, return_exceptions=True)
            raise
        finally:
            self._inflight.discard(operation)

    def _write_sync(self, sample: dict) -> None:
        from influxdb_client_3 import InfluxDBClient3, Point

        if self._writer is None:
            self._writer = InfluxDBClient3(
                host=self.url, token=self.token or None, database=self.database
            )
        point = (
            Point("measurements")
            .tag("sensor_id", sample["sensor_id"])
            .tag("room_id", sample.get("room_id") or "_unassigned")
            .tag("source", sample.get("source", "ble"))
            .field("temperature", float(sample["temperature"]))
            .field("humidity", float(sample["humidity"]))
            .field("ingested_at", sample.get("ingested_at", datetime.now(UTC).isoformat()))
            .time(utc(sample["timestamp"]))
        )
        if sample.get("rssi") is not None:
            point.field("rssi", int(sample["rssi"]))
        self._writer.write(record=point)

    async def _query_sql(self, sql: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                self.url + "/api/v3/query_sql",
                headers=self.headers,
                params={"db": self.database, "q": sql, "format": "json"},
            )
            if response.status_code == 404:
                # A database/table that has never received a sample has no series.
                text = response.text.lower()
                if "not found" in text and (
                    "measurements" in text or self.database.lower() in text
                ):
                    return []
            if response.status_code == 400:
                text = response.text.lower()
                if "measurements" in text and "not found" in text and "table" in text:
                    return []
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list):
                raise ValueError("Unexpected InfluxDB query response")
            return rows

    async def query(
        self,
        start: datetime,
        end: datetime,
        room_ids: list[str],
        sensor_ids: list[str],
        bucket: str,
    ) -> list[dict]:
        if bucket not in ("raw", "hour", "day", "week", "month"):
            raise ValueError("Unknown aggregation bucket")
        result = []
        for left, right in query_windows(start, end):
            conditions = [
                f"time >= {quote(left.isoformat())}",
                f"time < {quote(right.isoformat())}",
            ]
            for column, ids in (("room_id", room_ids), ("sensor_id", sensor_ids)):
                if ids:
                    conditions.append(column + " IN (" + ",".join(quote(i) for i in ids) + ")")
            where = " AND ".join(conditions)
            if bucket == "raw":
                sql = f"SELECT time AS timestamp, sensor_id, room_id, temperature, humidity FROM measurements WHERE {where} ORDER BY time LIMIT {MAX_POINTS + 1}"
            else:
                interval = "1 hour" if bucket == "hour" else "1 day"
                sql = (
                    f"SELECT date_bin(INTERVAL '{interval}', time) AS timestamp, sensor_id, room_id, "
                    "avg(temperature) AS temperature, avg(humidity) AS humidity, "
                    "min(temperature) AS temperature_min, max(temperature) AS temperature_max, "
                    "min(humidity) AS humidity_min, max(humidity) AS humidity_max, count(*) AS count "
                    f"FROM measurements WHERE {where} GROUP BY 1, sensor_id, room_id ORDER BY 1 LIMIT {MAX_POINTS + 1}"
                )
            rows = await self._query_sql(sql)
            for row in rows:
                if row.get("room_id") == "_unassigned":
                    row["room_id"] = None
            result.extend(rows)
            if len(result) > MAX_POINTS:
                raise ValueError("Too many points; choose a coarser aggregation")
        return aggregate_points(result, bucket)

    async def close(self) -> None:
        if self._inflight:
            await asyncio.gather(*tuple(self._inflight), return_exceptions=True)
        if self._writer is not None:
            await asyncio.to_thread(self._writer.close)
            self._writer = None
