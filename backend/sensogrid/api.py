import asyncio
import base64
import hashlib
import hmac
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

from .alerts import parse_time
from .config import Settings
from .db import Database
from .diagnostics import build_bundle
from .push import PushService, validate_endpoint
from .runtime import Runtime
from .schemas import (
    Credentials,
    Floorplan,
    Preferences,
    RuleInput,
    SensorInput,
    SensorPatch,
    SensorPreviewInput,
    SetupCredentials,
    Subscription,
    SystemSettings,
    Unsubscribe,
)

COOKIE = "sensogrid_session"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    result = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=64)
    return salt.hex() + ":" + result.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split(":")
        actual = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=64
        )
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


class Bucket(StrEnum):
    raw = "raw"
    hour = "hour"
    day = "day"
    week = "week"
    month = "month"


def model_merge(
    model: type[BaseModel], current: dict[str, Any], patch: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise HTTPException(422, "Expected an object")
    value = {**current, **patch}
    if "heatmap" in patch and isinstance(patch["heatmap"], dict):
        value["heatmap"] = {**current.get("heatmap", {}), **patch["heatmap"]}
    return model.model_validate(value).model_dump(mode="json")


class ApplicationState(Protocol):
    db: Database
    settings: Settings
    runtime: Runtime
    push: PushService


def install_api(app: FastAPI) -> None:
    state = cast(ApplicationState, app.state)
    auth = APIRouter(prefix="/api/auth")
    attempts: defaultdict[str, deque[float]] = defaultdict(deque)

    async def same_origin(request: Request) -> None:
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("sec-fetch-site") == "cross-site":
                raise HTTPException(403, "Cross-site request rejected")
            origin = request.headers.get("origin")
            if origin:
                parsed = urlsplit(origin)
                if (
                    parsed.scheme != request.url.scheme
                    or parsed.netloc.lower() != request.url.netloc.lower()
                    or parsed.path
                    or parsed.query
                    or parsed.fragment
                ):
                    raise HTTPException(403, "Origin mismatch")

    async def authenticated(request: Request) -> dict[str, Any]:
        await same_origin(request)
        user = state.db.session_user(request.cookies.get(COOKIE))
        if not user:
            raise HTTPException(401, "Authentication required")
        return user

    async def rate_limit(request: Request) -> None:
        await same_origin(request)
        key = request.client.host if request.client else "local"
        now = time.monotonic()
        queue = attempts[key]
        while queue and queue[0] < now - 60:
            queue.popleft()
        if len(queue) >= 10:
            raise HTTPException(
                429, "Too many authentication attempts", headers={"Retry-After": "60"}
            )
        queue.append(now)
        if len(attempts) > 10000:
            for old in list(attempts):
                if not attempts[old] or attempts[old][-1] < now - 60:
                    attempts.pop(old, None)

    def issue_session(response: Response) -> None:
        token = secrets.token_urlsafe(32)
        seconds = state.settings.session_hours * 3600
        state.db.add_session(token, time.time() + seconds)
        response.set_cookie(
            COOKIE,
            token,
            max_age=seconds,
            httponly=True,
            secure=state.settings.secure_cookies,
            samesite="strict",
            path="/",
        )
        response.headers["Cache-Control"] = "no-store"

    @auth.get("/status")
    def status(request: Request) -> dict[str, Any]:
        user = state.db.session_user(request.cookies.get(COOKIE))
        return {
            "setup_required": not state.db.has_user(),
            "authenticated": bool(user),
            "user": user,
        }

    @auth.post("/setup", dependencies=[Depends(rate_limit)])
    async def setup(data: SetupCredentials, response: Response) -> dict[str, Any]:
        if state.db.has_user():
            raise HTTPException(409, "Setup already complete")
        encoded = await asyncio.to_thread(hash_password, data.password)
        try:
            user = state.db.create_user(data.username, encoded)
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Setup already complete") from None
        issue_session(response)
        return user

    @auth.post("/login", dependencies=[Depends(rate_limit)])
    async def login(data: Credentials, response: Response) -> dict[str, Any]:
        user = state.db.user(data.username)
        valid = await asyncio.to_thread(
            verify_password,
            data.password,
            user["password"] if user else "00" * 16 + ":" + "00" * 64,
        )
        if not valid or not user:
            raise HTTPException(401, "Invalid credentials")
        issue_session(response)
        return {"id": user["id"], "username": user["username"]}

    @auth.get("/me")
    def me(user: dict[str, Any] = Depends(authenticated)) -> dict[str, Any]:
        return user

    @auth.post("/logout", dependencies=[Depends(authenticated)])
    def logout(request: Request, response: Response) -> dict[str, bool]:
        state.db.delete_session(request.cookies.get(COOKIE, ""))
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    app.include_router(auth)
    api = APIRouter(prefix="/api", dependencies=[Depends(authenticated)])
    diagnostic_downloads: deque[float] = deque()

    @api.get("/diagnostics")
    def diagnostics_download() -> Response:
        now = time.monotonic()
        while diagnostic_downloads and diagnostic_downloads[0] < now - 60:
            diagnostic_downloads.popleft()
        if len(diagnostic_downloads) >= 3:
            raise HTTPException(
                429, "Diagnostic download limit reached", headers={"Retry-After": "60"}
            )
        diagnostic_downloads.append(now)
        content = build_bundle(state.settings, state.db, state.runtime)
        filename = "sensogrid-diagnostics-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".zip"
        return Response(
            content,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    def sensor_views() -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        stale = state.db.system_settings()["stale_after_seconds"]
        live = {m["sensor_id"]: m for m in state.runtime.current()}
        result = []
        for sensor in state.db.all_sensors():
            m = live.get(sensor["id"], {})
            if not sensor["enabled"] or m.get("room_id") != sensor["room_id"]:
                m = {}
            seen = parse_time(m.get("timestamp"))
            read_state = state.runtime.read_states.get(sensor["id"], "waiting")
            available = bool(
                sensor["enabled"]
                and sensor["id"] not in state.runtime.unavailable_sensors
                and read_state != "unavailable"
                and seen
                and 0 <= (now - seen).total_seconds() <= stale
                and m.get("temperature") is not None
                and m.get("humidity") is not None
            )
            result.append(
                {
                    k: sensor[k]
                    for k in (
                        "id",
                        "name",
                        "address",
                        "protocol",
                        "room_id",
                        "enabled",
                        "sample_interval_seconds",
                        "interval_override_seconds",
                        "last_seen",
                    )
                }
                | {
                    "last_seen": m.get("timestamp") or sensor["last_seen"],
                    # Preserve the authoritative last sample even while offline.
                    # Live room/dashboard averages still filter by availability.
                    "temperature": m.get("temperature"),
                    "humidity": m.get("humidity"),
                    "rssi": m.get("rssi"),
                    "battery_raw": m.get("battery_raw"),
                    "battery_percent": m.get("battery_percent"),
                    "battery_timestamp": m.get("battery_timestamp"),
                    "available": available,
                    "read_state": read_state,
                }
            )
        return result

    def room_views(sensors: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for room in state.db.rooms():
            values = [s for s in sensors if s["room_id"] == room["id"] and s["available"]]
            result.append(
                {
                    "id": room["id"],
                    "name": room["name"],
                    "temperature": sum(s["temperature"] for s in values) / len(values)
                    if values
                    else None,
                    "humidity": sum(s["humidity"] for s in values) / len(values)
                    if values
                    else None,
                    "available": bool(values),
                }
            )
        return result

    @api.get("/dashboard")
    def dashboard() -> dict[str, Any]:
        sensors = sensor_views()
        available = [s for s in sensors if s["available"]]
        return {
            "mode": state.settings.mode,
            "now": datetime.now(UTC).isoformat(),
            "average_temperature": sum(s["temperature"] for s in available) / len(available)
            if available
            else None,
            "average_humidity": sum(s["humidity"] for s in available) / len(available)
            if available
            else None,
            "sensors": sensors,
            "rooms": room_views(sensors),
            "status": state.runtime.state,
        }

    @api.get("/sensors")
    def sensors() -> list[dict[str, Any]]:
        return sensor_views()

    @api.post("/sensors", status_code=201)
    def add_sensor(data: SensorInput) -> dict[str, Any]:
        sensor_id = state.db.add_sensor(data.model_dump())
        return next(s for s in sensor_views() if s["id"] == sensor_id)

    @api.post("/sensors/discover")
    async def discover() -> dict[str, list[dict[str, Any]]]:
        try:
            return {"devices": await asyncio.wait_for(state.runtime.discover(), timeout=60)}
        except TimeoutError:
            raise HTTPException(504, "Bluetooth scan timed out") from None
        except Exception:
            raise HTTPException(503, "Bluetooth discovery unavailable") from None

    @api.post("/sensors/preview")
    async def preview_sensor(data: SensorPreviewInput) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(state.runtime.preview_sensor(data.address), timeout=150)
        except TimeoutError:
            raise HTTPException(504, "Sensor measurement timed out") from None
        except Exception:
            raise HTTPException(
                503, "Sensor measurement unavailable; try again closer to the server"
            ) from None

    @api.patch("/sensors/{sensor_id}")
    def patch_sensor(sensor_id: str, data: SensorPatch) -> dict[str, Any]:
        patch = data.model_dump(exclude_unset=True)
        if any(
            value is None
            for key, value in patch.items()
            if key not in ("room_id", "sample_interval_seconds")
        ):
            raise HTTPException(422, "Only room_id and sample_interval_seconds can be null")
        state.db.patch_sensor(sensor_id, patch)
        return next(s for s in sensor_views() if s["id"] == sensor_id)

    @api.delete("/sensors/{sensor_id}")
    def delete_sensor(sensor_id: str) -> dict[str, bool]:
        state.db.delete_sensor(sensor_id)
        return {"ok": True}

    @api.get("/rooms")
    def rooms() -> list[dict[str, Any]]:
        return room_views(sensor_views())

    @api.get("/floorplan")
    def floorplan() -> dict[str, Any]:
        return state.db.floorplan()

    @api.get("/floorplan/export")
    def export(response: Response) -> dict[str, Any]:
        response.headers["Content-Disposition"] = 'attachment; filename="sensogrid-floorplan.json"'
        return state.db.floorplan()

    @api.post("/floorplan/preview")
    def preview(data: Floorplan) -> dict[str, Any]:
        state.db.save_floorplan(data.model_dump(mode="json"), preview=True)
        return {
            "valid": True,
            "rooms": len(data.rooms),
            "sensors": len(data.sensors),
            "warnings": [],
            "plan": data.model_dump(mode="json"),
        }

    @api.put("/floorplan")
    def save_floorplan(data: Floorplan) -> dict[str, Any]:
        plan = data.model_dump(mode="json")
        state.db.save_floorplan(plan)
        return plan

    @api.get("/history")
    async def history(
        start: datetime,
        end: datetime,
        bucket: Bucket = Bucket.hour,
        room_ids: str = "",
        sensor_ids: str = "",
    ) -> dict[str, Any]:
        if start.tzinfo is None or end.tzinfo is None:
            raise HTTPException(422, "Use timezone-aware ISO timestamps")
        start = start.astimezone(UTC)
        end = end.astimezone(UTC)
        if end <= start or end - start > timedelta(days=366):
            raise HTTPException(422, "Query window must be positive and at most 366 days")
        rooms = [x for x in room_ids.split(",") if x]
        sensors = [x for x in sensor_ids.split(",") if x]
        if len(rooms) > 100 or len(sensors) > 100:
            raise HTTPException(422, "Too many filters")
        try:
            points = await state.runtime.history(start, end, rooms, sensors, bucket.value)
        except HTTPException:
            raise
        except ValueError as exc:
            detail = str(exc)
            if detail.startswith(
                ("Too many points", "Unknown aggregation bucket", "Choose a time range")
            ):
                raise HTTPException(422, detail) from None
            raise HTTPException(503, "History storage unavailable") from None
        except Exception:
            raise HTTPException(503, "History storage unavailable") from None
        if len(points) > 50000:
            raise HTTPException(422, "Too many points; choose a wider aggregation bucket")
        return {
            "points": points,
            "source": "demo" if state.settings.mode == "demo" else "influxdb3",
        }

    @api.get("/settings")
    def settings() -> dict[str, Any]:
        return state.db.preferences()

    @api.patch("/settings")
    def patch_settings(data: dict[str, Any]) -> dict[str, Any]:
        value = model_merge(Preferences, state.db.preferences(), data)
        state.db.set_config("preferences", value)
        return value

    @api.get("/system/settings")
    def system_settings() -> dict[str, Any]:
        return state.db.system_settings()

    @api.patch("/system/settings")
    def patch_system(data: dict[str, Any]) -> dict[str, Any]:
        value = model_merge(SystemSettings, state.db.system_settings(), data)
        state.db.set_config("system", value)
        return value

    @api.get("/system/status")
    def system_status() -> dict[str, Any]:
        return {
            "mode": state.settings.mode,
            **state.runtime.state,
            "push_available": state.push.available,
        }

    @api.get("/alerts/rules")
    def rules() -> list[dict[str, Any]]:
        return state.db.rules()

    @api.post("/alerts/rules", status_code=201)
    def add_rule(data: RuleInput) -> dict[str, Any]:
        return state.db.save_rule(data.model_dump())

    @api.patch("/alerts/rules/{rule_id}")
    def patch_rule(rule_id: str, data: dict[str, Any]) -> dict[str, Any]:
        old = next((r for r in state.db.rules() if r["id"] == rule_id), None)
        if old is None:
            raise HTTPException(404, "Rule not found")
        old.pop("id")
        value = model_merge(RuleInput, old, data)
        return state.db.save_rule(value, rule_id)

    @api.delete("/alerts/rules/{rule_id}")
    def delete_rule(rule_id: str) -> dict[str, bool]:
        state.db.delete_rule(rule_id)
        return {"ok": True}

    @api.get("/alerts/events")
    def events() -> list[dict[str, Any]]:
        return state.db.events()

    @api.get("/push/key")
    def push_key() -> dict[str, bool | str | None]:
        return {
            "available": state.push.available,
            "public_key": state.settings.vapid_public_key or None,
        }

    @api.post("/push/subscriptions", status_code=201)
    async def subscribe(data: Subscription) -> dict[str, bool]:
        if not state.push.available:
            raise HTTPException(503, "Web Push is not configured")
        await asyncio.to_thread(validate_endpoint, data.endpoint)
        for key, length in ((data.keys.p256dh, 65), (data.keys.auth, 16)):
            try:
                valid = len(base64.urlsafe_b64decode(key + "=" * ((-len(key)) % 4))) == length
            except ValueError:
                valid = False
            if not valid:
                raise HTTPException(422, "Invalid subscription keys")
        state.db.save_subscription(data.model_dump())
        return {"ok": True}

    @api.delete("/push/subscriptions")
    def unsubscribe(data: Unsubscribe) -> dict[str, bool]:
        state.db.delete_subscription(data.endpoint)
        return {"ok": True}

    @api.post("/push/test")
    async def test_push() -> dict[str, int]:
        if not state.push.available:
            raise HTTPException(503, "Web Push is not configured")
        return await state.push.dispatch(
            {"title": "SensoGrid", "body": "Test notification", "tag": "test"}
        )

    @api.get("/openapi.json", include_in_schema=False)
    def openapi_schema() -> dict[str, Any]:
        return app.openapi()

    app.include_router(api)
