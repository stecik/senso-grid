"""Accounting must expose missed/censored reads instead of hiding them."""

import argparse
import asyncio
import json

import pytest

from scripts import ble_benchmark as benchmark
from scripts.ble_benchmark import current_slot, summarize_profile


def test_slot_skips_overdue_ticks_without_building_a_queue():
    assert current_slot(125.0, 100.0, 10.0, 0) == 2
    assert current_slot(105.0, 100.0, 10.0, 1) == 1


def test_summary_distinguishes_retry_success_failed_and_unserved_slots():
    sensors = [{"address": "AA", "name": "Desk"}]
    events = [
        {"kind": "attempt", "address": "AA", "attempt": 1, "status": "error", "read_seconds": 2},
        {"kind": "attempt", "address": "AA", "attempt": 2, "status": "ok", "read_seconds": 1},
        {"kind": "attempt", "address": "AA", "attempt": 1, "status": "error", "read_seconds": 2},
        {"kind": "attempt", "address": "AA", "attempt": 2, "status": "error", "read_seconds": 2},
        {
            "kind": "cycle",
            "address": "AA",
            "slot": 0,
            "status": "ok",
            "elapsed_seconds": 5,
            "on_time": True,
        },
        {"kind": "cycle", "address": "AA", "slot": 1, "status": "failed", "elapsed_seconds": 6},
        {"kind": "cycle", "address": "AA", "slot": 2, "status": "missed"},
        {"kind": "cycle", "address": "AA", "slot": 3, "status": "censored"},
    ]
    row = summarize_profile(events, sensors, planned_slots=4)["sensors"][0]
    assert row["planned"] == 4
    assert row["successes"] == 1
    assert row["failed"] == 1
    assert row["missed"] == 1
    assert row["censored"] == 1
    assert row["first_attempt_success_pct"] == 0
    assert row["completed_cycle_success_pct"] == 50
    assert row["delivery_pct"] == 25
    assert row["on_time_pct"] == 25
    assert row["attempts"] == 4
    assert row["attempt_success_pct"] == 25


def test_summary_does_not_report_success_when_no_reads_were_possible():
    row = summarize_profile([], [{"address": "AA", "name": "Desk"}], planned_slots=10)["sensors"][0]
    assert row["first_attempt_success_pct"] is None
    assert row["completed_cycle_success_pct"] is None
    assert row["delivery_pct"] == 0
    assert row["unaccounted"] == 10


@pytest.mark.asyncio
async def test_deadline_records_censored_sensor_even_while_waiting_for_radio(tmp_path, monkeypatch):
    class Driver:
        async def discover(self, **kwargs):
            return []

        async def read_current(self, *args, **kwargs):
            await asyncio.Event().wait()

    monkeypatch.setattr(benchmark, "LTDriver", Driver)
    args = argparse.Namespace(
        duration=0.03, interval=60, attempts=3, scan=15, retry_scan=5, read_timeout=12, seed=1
    )
    result = await benchmark.run_profile(
        "A",
        [
            {"address": "AA", "name": "First"},
            {"address": "BB", "name": "Second"},
        ],
        tmp_path,
        args,
    )
    assert result["overall"]["planned"] == 2
    assert result["overall"]["censored"] == 2
    assert result["overall"]["delivery_pct"] == 0
    assert result["overall"]["unaccounted"] == 0
    events = [json.loads(line) for line in (tmp_path / "A.jsonl").read_text().splitlines()]
    assert len([e for e in events if e["kind"] == "cycle"]) == 2


@pytest.mark.asyncio
async def test_transient_read_failure_is_counted_before_success_on_retry(tmp_path, monkeypatch):
    class Driver:
        def __init__(self):
            self.calls = 0

        async def discover(self, **kwargs):
            return []

        async def read_current(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("transient notification loss")
            return {"temperature": 22.5, "humidity": 44, "timestamp": "2026-10-23T08:00:00Z"}

    original_sleep = asyncio.sleep

    async def sleep(delay):
        if delay == 1:
            return
        await original_sleep(delay)

    monkeypatch.setattr(benchmark, "LTDriver", Driver)
    monkeypatch.setattr(benchmark.asyncio, "sleep", sleep)
    args = argparse.Namespace(
        duration=0.05, interval=60, attempts=3, scan=15, retry_scan=5, read_timeout=12, seed=1
    )
    result = await benchmark.run_profile("B", [{"address": "AA", "name": "Desk"}], tmp_path, args)
    row = result["sensors"][0]
    assert row["successes"] == 1
    assert row["attempts"] == 2
    assert row["first_attempt_success_pct"] == 0
    assert row["attempt_success_pct"] == 50
    assert row["delivery_pct"] == 100
    assert row["errors"] == {"TimeoutError": 1}


def test_started_slot_without_final_result_is_censored_not_never_started():
    events = [
        {
            "kind": "attempt",
            "address": "AA",
            "slot": 0,
            "attempt": 1,
            "status": "error",
            "read_seconds": 1,
        },
        {"kind": "cycle", "address": "AA", "slot": 0, "status": "missed"},
    ]
    row = summarize_profile(events, [{"address": "AA", "name": "Desk"}], 1)["sensors"][0]
    assert row["missed"] == 0
    assert row["censored"] == 1
    assert row["delivery_pct"] == 0


@pytest.mark.asyncio
async def test_profile_drains_slow_cancellation_before_closing_journal(tmp_path, monkeypatch):
    original_sleep = asyncio.sleep

    class Driver:
        def __init__(self):
            self.scans = 0

        async def discover(self, **kwargs):
            self.scans += 1
            if self.scans == 1:
                return []
            try:
                await asyncio.Event().wait()
            finally:
                await original_sleep(0.06)

        async def read_current(self, address, **kwargs):
            if address == "AA":
                raise LookupError("device missing")
            await asyncio.Event().wait()

    async def sleep(delay):
        if delay != 1:
            await original_sleep(delay)

    monkeypatch.setattr(benchmark, "LTDriver", Driver)
    monkeypatch.setattr(benchmark.asyncio, "sleep", sleep)
    args = argparse.Namespace(
        duration=0.04, interval=60, attempts=3, scan=15, retry_scan=5, read_timeout=12, seed=1
    )
    try:
        await benchmark.run_profile(
            "C",
            [
                {"address": "AA", "name": "Rescanning"},
                {"address": "BB", "name": "Reading"},
            ],
            tmp_path,
            args,
        )
        pending = [
            t
            for t in asyncio.all_tasks()
            if t is not asyncio.current_task()
            and "run_profile.<locals>.poll" in t.get_coro().__qualname__
        ]
        assert not pending, "A profile returned while its radio tasks were still cleaning up"
    finally:
        await original_sleep(0.1)


@pytest.mark.asyncio
async def test_child_cancellation_does_not_leave_another_sensor_running(tmp_path, monkeypatch):
    original_sleep = asyncio.sleep

    class Driver:
        def __init__(self):
            self.scans = 0

        async def discover(self, **kwargs):
            self.scans += 1
            if self.scans == 1:
                return []
            try:
                await asyncio.Event().wait()
            finally:
                await original_sleep(0.03)

        async def read_current(self, address, **kwargs):
            if address == "AA":
                raise LookupError("device missing")
            await original_sleep(0.01)
            raise asyncio.CancelledError()

    async def sleep(delay):
        if delay != 1:
            await original_sleep(delay)

    monkeypatch.setattr(benchmark, "LTDriver", Driver)
    monkeypatch.setattr(benchmark.asyncio, "sleep", sleep)
    args = argparse.Namespace(
        duration=0.2, interval=60, attempts=3, scan=15, retry_scan=5, read_timeout=12, seed=1
    )
    pending = []
    try:
        with pytest.raises(asyncio.CancelledError):
            await benchmark.run_profile(
                "C",
                [
                    {"address": "AA", "name": "Rescanning"},
                    {"address": "BB", "name": "Cancelled"},
                ],
                tmp_path,
                args,
            )
        pending = [
            t
            for t in asyncio.all_tasks()
            if t is not asyncio.current_task()
            and "run_profile.<locals>.poll" in t.get_coro().__qualname__
        ]
        assert not pending, "One sensor cancelled; another sensor kept using the radio"
    finally:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
