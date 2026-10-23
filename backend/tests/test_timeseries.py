from datetime import UTC, datetime, timedelta
from typing import Any, Never

import pytest
from sensogrid.timeseries import InfluxStore, aggregate_points, query_windows


def test_history_is_split_with_no_overlap() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=30)
    windows = list(query_windows(start, end))
    assert windows[0][0] == start and windows[-1][1] == end
    assert all(b - a <= timedelta(hours=48) for a, b in windows)
    assert all(windows[i][1] == windows[i + 1][0] for i in range(len(windows) - 1))


def test_weighted_aggregation_across_query_boundaries() -> None:
    rows = [
        {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "sensor_id": "s",
            "room_id": "r",
            "temperature": 10,
            "humidity": 40,
            "temperature_min": 9,
            "temperature_max": 11,
            "humidity_min": 35,
            "humidity_max": 45,
            "count": 3,
        },
        {
            "timestamp": "2026-01-02T00:00:00+00:00",
            "sensor_id": "s",
            "room_id": "r",
            "temperature": 30,
            "humidity": 80,
            "temperature_min": 29,
            "temperature_max": 31,
            "humidity_min": 75,
            "humidity_max": 85,
            "count": 1,
        },
    ]
    result = aggregate_points(rows, "month")
    assert len(result) == 1
    assert result[0]["temperature"] == 15
    assert result[0]["humidity"] == 50
    assert result[0]["temperature_min"] == 9
    assert result[0]["temperature_max"] == 31
    assert result[0]["count"] == 4


def test_room_at_measurement_is_preserved_and_gaps_not_filled() -> None:
    rows = [
        {
            "timestamp": "2026-01-01T00:00:00Z",
            "sensor_id": "s",
            "room_id": r,
            "temperature": 20,
            "humidity": 40,
            "count": 1,
        }
        for r in ["old", "new"]
    ]
    assert len(aggregate_points(rows, "day")) == 2
    assert aggregate_points([], "day") == []


@pytest.mark.asyncio
async def test_sql_window_bounds_and_identifier_escaping(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []
    store = InfluxStore("http://localhost:8181", "token", "sensogrid")

    async def fake(sql: str) -> list[dict[str, Any]]:
        seen.append(sql)
        return []

    monkeypatch.setattr(store, "_query_sql", fake)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    assert await store.query(start, start + timedelta(days=7), ["room'1"], [], "day") == []
    assert len(seen) == 4
    assert all("room''1" in s and "time >=" in s and "time < " in s for s in seen)


@pytest.mark.asyncio
async def test_storage_failure_is_not_a_demo_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    store = InfluxStore("http://localhost:8181", "token", "sensogrid")

    async def fail(sql: str) -> Never:
        raise ConnectionError("unavailable")

    monkeypatch.setattr(store, "_query_sql", fail)
    with pytest.raises(ConnectionError):
        await store.query(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC), [], [], "hour"
        )


@pytest.mark.asyncio
async def test_write_cancellation_drains_before_close(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import threading

    from sensogrid.timeseries import InfluxStore

    started, release = threading.Event(), threading.Event()
    calls = []

    class Writer:
        def close(self) -> None:
            calls.append("closed")

    store = InfluxStore("http://localhost:8181", "token", "sensogrid")
    monkeypatch.setattr(store, "_writer", Writer())

    def write(_sample: dict[str, Any]) -> None:
        calls.append("write_started")
        started.set()
        release.wait(2)
        calls.append("write_done")

    monkeypatch.setattr(store, "_write_sync", write)
    task = asyncio.create_task(store.write({}))
    await asyncio.to_thread(started.wait, 1)
    task.cancel()
    close = asyncio.create_task(store.close())
    await asyncio.sleep(0.03)
    assert "closed" not in calls
    release.set()
    await asyncio.gather(task, close, return_exceptions=True)
    assert calls == ["write_started", "write_done", "closed"]


@pytest.mark.asyncio
async def test_cancelled_failed_write_preserves_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import threading

    started, release = threading.Event(), threading.Event()
    store = InfluxStore("http://localhost:8181", "token", "sensogrid")

    def write(_sample: dict[str, Any]) -> None:
        started.set()
        release.wait(1)
        raise OSError("network failed during shutdown")

    monkeypatch.setattr(store, "_write_sync", write)
    task = asyncio.create_task(store.write({}))
    await asyncio.to_thread(started.wait, 1)
    task.cancel()
    release.set()
    result = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)
    await store.close()
