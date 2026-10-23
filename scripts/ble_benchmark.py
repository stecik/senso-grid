"""Compare BLE connection strategies without writing SensoGrid databases.

Uses the unmodified production LTDriver and BLERadio. Each scheduled slot
has one cycle per sensor; retry failures, missed slots and deadline
cancellations remain separate in the output.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import importlib.metadata
import json
import math
import platform
import random
import statistics
import sys
import time
import traceback
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sensogrid.ble.lt import LTDriver
from sensogrid.ble.radio import BLERadio

PROFILES = {
    "A": {"concurrency": 1, "stagger": 0.0},
    "B": {"concurrency": 2, "stagger": 0.0},
    "C": {"concurrency": 5, "stagger": 0.0},
    "D": {"concurrency": 5, "stagger": 0.5},
}


def current_slot(now: float, start: float, interval: float, next_slot: int) -> int:
    return max(next_slot, int(max(0, now - start) // interval))


def percentile(values: list[float], fraction: float) -> float | None:
    return (
        round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 3) if values else None
    )


def percent(numerator: int, denominator: int) -> float | None:
    return round(100 * numerator / denominator, 2) if denominator else None


def wilson(successes: int, count: int) -> list[float] | None:
    if not count:
        return None
    z = 1.96
    p = successes / count
    denominator = 1 + z * z / count
    middle = (p + z * z / (2 * count)) / denominator
    radius = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    return [round(100 * max(0, middle - radius), 2), round(100 * min(1, middle + radius), 2)]


def summarize_profile(events: list[dict], sensors: list[dict], planned_slots: int) -> dict:
    # Older journals can contain a fallback "missed" row after a started task
    # was cancelled. Preserve raw events, but distinguish it from never starting.
    started = {(e["address"], e["slot"]) for e in events if e["kind"] == "attempt" and "slot" in e}
    cycle_events = [
        {**e, "status": "censored"}
        if e["status"] == "missed" and (e["address"], e["slot"]) in started
        else e
        for e in events
        if e["kind"] == "cycle"
    ]
    rows = []
    groups = [(s["name"], s["address"], {s["address"]}, planned_slots) for s in sensors]
    groups.append(("ALL", "*", {s["address"] for s in sensors}, planned_slots * len(sensors)))
    for name, address, addresses, planned in groups:
        cycles = [e for e in cycle_events if e["address"] in addresses]
        attempts = [
            e
            for e in events
            if e["kind"] == "attempt"
            and e["address"] in addresses
            and e["status"] in ("ok", "error")
            and e.get("read_started", True)
        ]
        first = [e for e in attempts if e["attempt"] == 1]
        statuses = Counter(e["status"] for e in cycles)
        successes = statuses["ok"]
        failed = statuses["failed"] + statuses["scan_failed"]
        first_ok = sum(e["status"] == "ok" for e in first)
        on_time = sum(e["status"] == "ok" and e.get("on_time", False) for e in cycles)
        durations = [e["elapsed_seconds"] for e in cycles if e["status"] == "ok"]
        gaps = []
        for addr in addresses:
            arrivals = sorted(
                e["measurement_elapsed"]
                for e in cycles
                if e["address"] == addr and e["status"] == "ok" and "measurement_elapsed" in e
            )
            gaps.extend(b - a for a, b in zip(arrivals, arrivals[1:], strict=False))
        rssis = [e["rssi"] for e in cycles if e.get("rssi") is not None and -120 < e["rssi"] < 0]
        rows.append(
            {
                "name": name,
                "address": address,
                "planned": planned,
                "successes": successes,
                "failed": failed,
                "scan_failed": statuses["scan_failed"],
                "missed": statuses["missed"],
                "censored": statuses["censored"],
                "unaccounted": planned - len(cycles),
                "attempts": len(attempts),
                "first_attempts": len(first),
                "first_attempt_successes": first_ok,
                "first_attempt_success_pct": percent(first_ok, len(first)),
                "first_attempt_ci95": wilson(first_ok, len(first)),
                "completed_cycle_success_pct": percent(successes, successes + failed),
                "delivery_pct": percent(successes, planned),
                "on_time_pct": percent(on_time, planned),
                "attempt_success_pct": percent(
                    sum(e["status"] == "ok" for e in attempts), len(attempts)
                ),
                "cycle_seconds_p50": percentile(durations, 0.5),
                "cycle_seconds_p95": percentile(durations, 0.95),
                "gap_seconds_p50": percentile(gaps, 0.5),
                "gap_seconds_p95": percentile(gaps, 0.95),
                "gap_seconds_max": round(max(gaps), 3) if gaps else None,
                "read_seconds_p95": percentile([e["read_seconds"] for e in attempts], 0.95),
                "queue_seconds_p95": percentile(
                    [e.get("queue_seconds", 0) for e in attempts], 0.95
                ),
                "rssi_median": statistics.median(rssis) if rssis else None,
                "errors": dict(
                    Counter(
                        e.get("error_type", "unknown") for e in attempts if e["status"] == "error"
                    )
                ),
            }
        )
    return {"sensors": rows[:-1], "overall": rows[-1]}


class Journal:
    def __init__(self, path: Path, profile: str, start: float):
        self.file = path.open("x", encoding="utf-8")
        self.events: list[dict] = []
        self.profile, self.start = profile, start

    def emit(self, kind: str, **fields) -> None:
        row = {
            "kind": kind,
            "profile": self.profile,
            "utc": datetime.now(UTC).isoformat(),
            "elapsed": round(time.monotonic() - self.start, 6),
            **fields,
        }
        self.events.append(row)
        self.file.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.file.flush()

    def close(self):
        self.file.close()


async def run_profile(profile: str, sensors: list[dict], output: Path, args) -> dict:
    start = time.monotonic()
    planned = math.ceil(args.duration / args.interval)
    journal = Journal(output / f"{profile}.jsonl", profile, start)
    config = PROFILES[profile]
    radio = BLERadio(config["concurrency"])
    driver = LTDriver()
    last_scan = 0.0
    signals: dict[str, int] = {}

    async def scan(seconds: float, newer_than: float | None = None):
        nonlocal last_scan
        async with radio.scan():
            if newer_than is not None and last_scan > newer_than:
                return
            before = time.monotonic()
            found = await driver.discover(timeout=seconds)
            signals.update({r["address"].upper(): r["rssi"] for r in found})
            last_scan = time.monotonic()
            wanted = {s["address"] for s in sensors}
            journal.emit(
                "scan",
                seconds=round(last_scan - before, 6),
                found=[
                    {k: r[k] for k in ("address", "name", "rssi")}
                    for r in found
                    if r["address"].upper() in wanted
                ],
            )

    async def poll(sensor: dict, slot: int, position: int):
        address = sensor["address"]
        scheduled = start + slot * args.interval
        status = "censored"
        sample = None
        retry_started = time.monotonic()
        try:
            await asyncio.sleep(position * config["stagger"])
            for attempt in range(1, args.attempts + 1):
                phase = "rescan" if attempt > 1 else "queue"
                before = time.monotonic()
                acquired = None
                try:
                    if attempt > 1:
                        await scan(args.retry_scan, retry_started)
                    phase = "queue"
                    queue_start = time.monotonic()
                    async with radio.read(address):
                        acquired = time.monotonic()
                        phase = "read"
                        sample = await driver.read_current(address, timeout=args.read_timeout)
                    now = time.monotonic()
                    journal.emit(
                        "attempt",
                        address=address,
                        slot=slot,
                        attempt=attempt,
                        status="ok",
                        read_started=True,
                        read_seconds=round(now - acquired, 6),
                        queue_seconds=round(acquired - queue_start, 6),
                        total_seconds=round(now - before, 6),
                        sample=sample,
                    )
                    status = "ok"
                    return
                except asyncio.CancelledError:
                    journal.emit(
                        "attempt",
                        address=address,
                        slot=slot,
                        attempt=attempt,
                        status="censored",
                        phase=phase,
                        read_started=acquired is not None,
                        total_seconds=round(time.monotonic() - before, 6),
                    )
                    raise
                except Exception as exc:
                    now = time.monotonic()
                    journal.emit(
                        "attempt",
                        address=address,
                        slot=slot,
                        attempt=attempt,
                        status="error",
                        phase=phase,
                        read_started=acquired is not None,
                        read_seconds=round(now - acquired, 6) if acquired is not None else 0,
                        queue_seconds=round(acquired - queue_start, 6)
                        if acquired is not None
                        else 0,
                        total_seconds=round(now - before, 6),
                        error_type=type(exc).__name__,
                        error=str(exc),
                        traceback=traceback.format_exc(),
                    )
                    if attempt == args.attempts:
                        status = "failed"
                        return
                    await asyncio.sleep(2 ** (attempt - 1))
        finally:
            now = time.monotonic()
            journal.emit(
                "cycle",
                address=address,
                name=sensor["name"],
                slot=slot,
                status=status,
                elapsed_seconds=round(now - scheduled, 6),
                measurement_elapsed=round(now - start, 6) if sample is not None else None,
                on_time=status == "ok" and now <= scheduled + args.interval,
                rssi=signals.get(address),
            )

    journal.emit(
        "profile_start",
        config=config,
        duration=args.duration,
        interval=args.interval,
        attempts=args.attempts,
    )
    try:
        async with asyncio.timeout(args.duration):
            slot = 0
            while slot < planned:
                await asyncio.sleep(max(0, start + slot * args.interval - time.monotonic()))
                due = min(planned, current_slot(time.monotonic(), start, args.interval, slot))
                for skipped in range(slot, due):
                    for sensor in sensors:
                        journal.emit(
                            "cycle",
                            address=sensor["address"],
                            name=sensor["name"],
                            slot=skipped,
                            status="missed",
                        )
                slot = due
                if slot >= planned:
                    break
                try:
                    await scan(args.scan)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    journal.emit(
                        "scan_error",
                        error_type=type(exc).__name__,
                        error=str(exc),
                        traceback=traceback.format_exc(),
                    )
                    for sensor in sensors:
                        journal.emit(
                            "cycle",
                            address=sensor["address"],
                            name=sensor["name"],
                            slot=slot,
                            status="scan_failed",
                        )
                else:
                    ordered = list(sensors)
                    random.Random(args.seed + slot).shuffle(ordered)
                    tasks = [
                        asyncio.create_task(poll(sensor, slot, i))
                        for i, sensor in enumerate(ordered)
                    ]
                    try:
                        await asyncio.gather(*tasks)
                    finally:
                        # A child cancellation must not leave siblings using the
                        # radio after this profile closes its journal.
                        for task in tasks:
                            if not task.done() and not task.cancelling():
                                task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                slot += 1
            await asyncio.sleep(max(0, start + args.duration - time.monotonic()))
    except TimeoutError:
        journal.emit("profile_deadline")
    finally:
        seen = {(e["address"], e["slot"]) for e in journal.events if e["kind"] == "cycle"}
        for slot in range(planned):
            for sensor in sensors:
                if (sensor["address"], slot) not in seen:
                    journal.emit(
                        "cycle",
                        address=sensor["address"],
                        name=sensor["name"],
                        slot=slot,
                        status="missed",
                    )
        summary = summarize_profile(journal.events, sensors, planned)
        summary.update(
            profile=profile, config=config, duration_seconds=round(time.monotonic() - start, 3)
        )
        journal.emit("profile_end", overall=summary["overall"])
        journal.close()
        (output / f"{profile}-summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps({"profile": profile, "overall": summary["overall"]}, ensure_ascii=False),
            flush=True,
        )
    return summary


async def main(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    sensors = json.loads(Path(args.sensors).read_text(encoding="utf-8-sig"))
    if not sensors or len({s["address"].upper() for s in sensors}) != len(sensors):
        raise ValueError("Expected a nonempty, unique sensor list")
    for sensor in sensors:
        sensor["address"] = sensor["address"].upper()
    import sensogrid.ble.lt as driver_module

    metadata = {
        "started_utc": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python": sys.version,
        "bleak": importlib.metadata.version("bleak"),
        "args": vars(args),
        "sensors": sensors,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "driver_sha256": hashlib.sha256(Path(driver_module.__file__).read_bytes()).hexdigest(),
    }
    (output / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summaries = []
    for index, profile in enumerate(args.profiles):
        if index:
            await asyncio.sleep(args.cooldown)
        summaries.append(await run_profile(profile, sensors, output, args))
        (output / "summary.json").write_text(
            json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with (output / "summary.csv").open("w", newline="", encoding="utf-8-sig") as file:
            rows = [
                {**row, "profile": s["profile"]}
                for s in summaries
                for row in [*s["sensors"], s["overall"]]
            ]
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    (output / "complete.json").write_text(
        json.dumps({"utc": datetime.now(UTC).isoformat(), "profiles": args.profiles}),
        encoding="utf-8",
    )


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sensors", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--profiles", nargs="+", choices=list(PROFILES), default=list(PROFILES))
    parser.add_argument("--duration", type=float, default=600)
    parser.add_argument("--interval", type=float, default=60)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--scan", type=float, default=15)
    parser.add_argument("--retry-scan", type=float, default=5)
    parser.add_argument("--read-timeout", type=float, default=12)
    parser.add_argument("--cooldown", type=float, default=20)
    parser.add_argument("--seed", type=int, default=20261023)
    args = parser.parse_args()
    if (
        min(args.duration, args.interval, args.scan, args.retry_scan, args.read_timeout) <= 0
        or not 1 <= args.attempts <= 5
        or args.cooldown < 0
    ):
        parser.error("Positive durations/timeouts and 1..5 attempts required")
    return args


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
