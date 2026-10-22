"""Opt-in test against a real disposable InfluxDB 3 Core instance."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sensogrid.timeseries import InfluxStore


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("SENSOGRID_TEST_INFLUX_URL"), reason="real InfluxDB not requested"
)
async def test_real_core_write_query_and_historical_room_attribution():
    store = InfluxStore(
        os.environ["SENSOGRID_TEST_INFLUX_URL"],
        os.environ["SENSOGRID_TEST_INFLUX_TOKEN"],
        "sensogrid_integration",
    )
    await store.ensure_database()
    sensor = "integration-" + uuid4().hex
    start = datetime(2026, 1, 1, tzinfo=UTC)
    assert await store.query(start, start + timedelta(days=1), [], [sensor], "raw") == []
    try:
        for hour, temp, room in [(0, 10, "before"), (1, 20, "before"), (50, 30, "after")]:
            await store.write(
                {
                    "timestamp": (start + timedelta(hours=hour)).isoformat(),
                    "sensor_id": sensor,
                    "room_id": room,
                    "temperature": temp,
                    "humidity": 50,
                    "source": "integration",
                }
            )
        points = await store.query(start, start + timedelta(days=7), [], [sensor], "month")
        assert len(points) == 2
        by_room = {p["room_id"]: p for p in points}
        assert by_room["before"]["temperature"] == 15
        assert by_room["before"]["count"] == 2
        assert by_room["after"]["temperature"] == 30
        raw = await store.query(start, start + timedelta(days=7), [], [sensor], "raw")
        assert len(raw) == 3
    finally:
        await store.close()
