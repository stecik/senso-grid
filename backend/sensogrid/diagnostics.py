"""Bounded, authenticated support bundles; never export credentials or the database."""

import hashlib
import importlib.metadata
import io
import json
import logging
import platform
import re
import sys
import zipfile
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote, urlsplit, urlunsplit

from .config import Settings
from .db import Database

if TYPE_CHECKING:
    from .runtime import Runtime

LOG_BYTES = 512 * 1024
FILE_BYTES = 1024 * 1024
SENSITIVE = re.compile(r"password|token|secret|authorization|cookie|private.key|session", re.I)


def redact(value: str, secrets: Sequence[str] = ()) -> str:
    for secret in secrets:
        if isinstance(secret, str) and len(secret) >= 4:
            value = value.replace(secret, "[REDACTED]").replace(
                quote(secret, safe=""), "[REDACTED]"
            )

    def safe_url(match: re.Match[str]) -> str:
        try:
            parsed = urlsplit(match[0])
            host = parsed.hostname or ""
            if parsed.port:
                host += f":{parsed.port}"
            return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
        except ValueError:
            return "[REDACTED URL]"

    value = re.sub(r"https?://[^\s\"'<>]+", safe_url, value, flags=re.I)
    value = re.sub(
        r"(?im)(\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*[:=]\s*)[^\r\n]*",
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(r"(?i)\bBearer\s+[^\s,;\"']+", "Bearer [REDACTED]", value)
    return re.sub(
        r"(?i)([\"']?(?:password|token|secret|api[_-]?key|authorization|cookie|sensogrid_session)[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
        r"\1[REDACTED]",
        value,
    )


def secret_values(settings: Settings) -> list[str]:
    return [
        value
        for key, value in vars(settings).items()
        if SENSITIVE.search(key) and isinstance(value, str)
    ]


def scrub(value: Any, secrets: Sequence[str]) -> Any:
    if isinstance(value, str):
        return redact(value, secrets)
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SENSITIVE.search(key) else scrub(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [scrub(item, secrets) for item in value]
    return value


class DiagnosticFormatter(logging.Formatter):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings

    def format(self, record: logging.LogRecord) -> str:
        secrets = secret_values(self.settings)
        row = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage(), secrets)[:16000],
        }
        if record.exc_info:
            row["exception"] = redact(self.formatException(record.exc_info), secrets)[-16000:]
        return json.dumps(row, ensure_ascii=False)


@contextmanager
def capture_logs(settings: Settings) -> Generator[None]:
    directory = Path(settings.data_dir) / "diagnostics"
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        directory / "app.jsonl", maxBytes=LOG_BYTES, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(DiagnosticFormatter(settings))
    loggers = [
        (logging.getLogger(name), level)
        for name, level in (
            ("sensogrid", logging.INFO),
            ("bleak", logging.WARNING),
            ("dbus_fast", logging.WARNING),
            ("uvicorn.error", logging.INFO),
        )
    ]
    previous = [(logger, logger.level) for logger, _ in loggers]
    for logger, level in loggers:
        logger.setLevel(level)
        logger.addHandler(handler)
    try:
        logging.getLogger(__name__).info("Diagnostic logging started")
        yield
    finally:
        for logger, level in previous:
            logger.removeHandler(handler)
            logger.setLevel(level)
        handler.close()


def build_bundle(settings: Settings, db: Database, runtime: "Runtime") -> bytes:
    now = datetime.now(UTC)
    secrets = secret_values(settings)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "created_utc": now.isoformat(),
        "files": {},
        "host_logs": {"available": False},
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:

        def add_json(name: str, value: Any) -> None:
            archive.writestr(name, json.dumps(scrub(value, secrets), ensure_ascii=False, indent=2))

        versions = {}
        for package in ("sensogrid", "bleak", "dbus-fast", "fastapi", "uvicorn"):
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                versions[package] = "not installed"
        hashes = {}
        for name in ("runtime.py", "ble/bthome.py", "ble/address.py", "api.py", "diagnostics.py"):
            source = Path(__file__).parent / name
            hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
        latest = {row["sensor_id"]: row for row in runtime.current()}
        sensors = []
        for sensor in db.all_sensors():
            sensors.append(
                {
                    **{
                        key: sensor.get(key)
                        for key in (
                            "id",
                            "name",
                            "address",
                            "protocol",
                            "room_id",
                            "enabled",
                            "last_seen",
                            "sample_interval_seconds",
                        )
                    },
                    "read_state": runtime.read_states.get(sensor["id"], "waiting"),
                    "unavailable": sensor["id"] in runtime.unavailable_sensors,
                    "last_reading": {
                        key: latest.get(sensor["id"], {}).get(key)
                        for key in (
                            "timestamp",
                            "temperature",
                            "humidity",
                            "rssi",
                            "battery_raw",
                            "battery_percent",
                            "battery_timestamp",
                        )
                    },
                }
            )
        add_json(
            "snapshot.json",
            {
                "created_utc": now.isoformat(),
                "python": sys.version,
                "platform": platform.platform(),
                "versions": versions,
                "source_sha256": hashes,
                "configuration": {
                    "mode": settings.mode,
                    "ble_protocol": "bthome_v2",
                    "ble_connections": 0,
                    **db.system_settings(),
                },
                "scanner": {
                    "running": getattr(getattr(runtime, "driver", None), "running", False),
                    "statistics": getattr(getattr(runtime, "driver", None), "stats", {}),
                },
                "runtime": runtime.state,
                "tasks": [
                    {
                        "name": task.get_name(),
                        "done": task.done(),
                        "cancelled": task.cancelled(),
                        "stack": [
                            {
                                "file": Path(frame.f_code.co_filename).name,
                                "function": frame.f_code.co_name,
                                "line": frame.f_lineno,
                            }
                            for frame in task.get_stack(limit=3)
                        ],
                    }
                    for task in getattr(runtime, "_tasks", [])
                ],
                "sensors": sensors,
                "outbox_pending": sum(
                    1 for _ in (Path(settings.data_dir) / "outbox").glob("*.json")
                ),
            },
        )
        for name in ("app.jsonl.3", "app.jsonl.2", "app.jsonl.1", "app.jsonl"):
            path = Path(settings.data_dir) / "diagnostics" / name
            if not path.is_file() or path.is_symlink():
                continue
            try:
                with path.open("rb") as file:
                    size = file.seek(0, 2)
                    file.seek(max(0, size - FILE_BYTES))
                    text = file.read(FILE_BYTES).decode("utf-8", errors="replace")
                lines = []
                for line in text.splitlines():
                    try:
                        lines.append(
                            json.dumps(scrub(json.loads(line), secrets), ensure_ascii=False)
                        )
                    except ValueError:
                        lines.append(
                            json.dumps({"unparsed": redact(line, secrets)}, ensure_ascii=False)
                        )
                archive.writestr("application/" + name, "\n".join(lines))
                manifest["files"][name] = {"source_bytes": size, "truncated": size > FILE_BYTES}
            except OSError as exc:
                manifest["files"][name] = {"error": type(exc).__name__}
        host = Path(settings.host_diagnostics_dir) / "host.json"
        try:
            if host.is_symlink() or host.stat().st_size > FILE_BYTES:
                raise ValueError("Invalid or oversized host snapshot")
            payload = json.loads(host.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("commands", {}), dict):
                raise ValueError("Invalid host command results")
            generated = datetime.fromisoformat(payload["created_utc"].replace("Z", "+00:00"))
            age = (now - generated).total_seconds()
            add_json("host.json", payload)
            manifest["host_logs"] = {
                "available": True,
                "age_seconds": age,
                "stale": age > 180 or age < -60,
                "unavailable_sections": [
                    name
                    for name, result in payload.get("commands", {}).items()
                    if isinstance(result, dict)
                    and (result.get("error") or result.get("exit_code", 0) != 0)
                ],
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            cast(dict[str, Any], manifest["host_logs"])["reason"] = type(exc).__name__
        archive.writestr(
            "README.txt",
            "SensoGrid diagnostic bundle. Times use UTC. Sensor names, addresses and recent readings are included. No account database, passwords, tokens, floorplan or full measurement history are exported. Host logs require the optional host collector; see manifest.json for coverage and snapshot age. Application logs are bounded and rotated. Core dump memory is never included.\n",
        )
        add_json("manifest.json", manifest)
    return output.getvalue()
