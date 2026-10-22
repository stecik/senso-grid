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
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .alerts import parse_time
from .push import validate_endpoint
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


def hash_password(password):
    salt = secrets.token_bytes(16)
    result = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=64)
    return salt.hex() + ":" + result.hex()


def verify_password(password, stored):
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


def model_merge(model, current, patch):
    if not isinstance(patch, dict):
        raise HTTPException(422, "Expected an object")
    value = {**current, **patch}
    if "heatmap" in patch and isinstance(patch["heatmap"], dict):
        value["heatmap"] = {**current.get("heatmap", {}), **patch["heatmap"]}
    return model.model_validate(value).model_dump(mode="json")


def install_api(app):
    auth = APIRouter(prefix="/api/auth")
    attempts = defaultdict(deque)

    async def same_origin(request: Request):
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

    async def authenticated(request: Request):
        await same_origin(request)
        user = app.state.db.session_user(request.cookies.get(COOKIE))
        if not user:
            raise HTTPException(401, "Authentication required")
        return user

    async def rate_limit(request: Request):
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

    def issue_session(response):
        token = secrets.token_urlsafe(32)
        seconds = app.state.settings.session_hours * 3600
        app.state.db.add_session(token, time.time() + seconds)
        response.set_cookie(
            COOKIE,
            token,
            max_age=seconds,
            httponly=True,
            secure=app.state.settings.secure_cookies,
            samesite="strict",
            path="/",
        )
        response.headers["Cache-Control"] = "no-store"

    @auth.get("/status")
    def status(request: Request):
        user = app.state.db.session_user(request.cookies.get(COOKIE))
        return {
            "setup_required": not app.state.db.has_user(),
            "authenticated": bool(user),
            "user": user,
        }

    @auth.post("/setup", dependencies=[Depends(rate_limit)])
    async def setup(data: SetupCredentials, response: Response):
        if app.state.db.has_user():
            raise HTTPException(409, "Setup already complete")
        encoded = await asyncio.to_thread(hash_password, data.password)
        try:
            user = app.state.db.create_user(data.username, encoded)
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Setup already complete") from None
        issue_session(response)
        return user

    @auth.post("/login", dependencies=[Depends(rate_limit)])
    async def login(data: Credentials, response: Response):
        user = app.state.db.user(data.username)
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
    def me(user=Depends(authenticated)):
        return user

    @auth.post("/logout", dependencies=[Depends(authenticated)])
    def logout(request: Request, response: Response):
        app.state.db.delete_session(request.cookies.get(COOKIE, ""))
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    app.include_router(auth)
    api = APIRouter(prefix="/api", dependencies=[Depends(authenticated)])

    def sensor_views():
        now = datetime.now(UTC)
        stale = app.state.db.system_settings()["stale_after_seconds"]
        live = {m["sensor_id"]: m for m in app.state.runtime.current()}
        result = []
        for sensor in app.state.db.all_sensors():
            m = live.get(sensor["id"], {})
            if not sensor["enabled"] or m.get("room_id") != sensor["room_id"]:
                m = {}
            seen = parse_time(m.get("timestamp"))
            read_state = app.state.runtime.read_states.get(sensor["id"], "waiting")
            available = bool(
                sensor["enabled"]
                and sensor["id"] not in app.state.runtime.unavailable_sensors
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
                    "temperature": m.get("temperature") if available else None,
                    "humidity": m.get("humidity") if available else None,
                    "rssi": m.get("rssi"),
                    "battery_raw": m.get("battery_raw"),
                    "available": available,
                    "read_state": read_state,
                }
            )
        return result

    def room_views(sensors):
        result = []
        for room in app.state.db.rooms():
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
    def dashboard():
        sensors = sensor_views()
        available = [s for s in sensors if s["available"]]
        return {
            "mode": app.state.settings.mode,
            "now": datetime.now(UTC).isoformat(),
            "average_temperature": sum(s["temperature"] for s in available) / len(available)
            if available
            else None,
            "average_humidity": sum(s["humidity"] for s in available) / len(available)
            if available
            else None,
            "sensors": sensors,
            "rooms": room_views(sensors),
            "status": app.state.runtime.state,
        }

    @api.get("/sensors")
    def sensors():
        return sensor_views()

    @api.post("/sensors", status_code=201)
    def add_sensor(data: SensorInput):
        sensor_id = app.state.db.add_sensor(data.model_dump())
        return next(s for s in sensor_views() if s["id"] == sensor_id)

    @api.post("/sensors/discover")
    async def discover():
        try:
            return {"devices": await asyncio.wait_for(app.state.runtime.discover(), timeout=60)}
        except TimeoutError:
            raise HTTPException(504, "Bluetooth scan timed out") from None
        except Exception:
            raise HTTPException(503, "Bluetooth discovery unavailable") from None

    @api.post("/sensors/preview")
    async def preview_sensor(data: SensorPreviewInput):
        try:
            return await asyncio.wait_for(
                app.state.runtime.preview_sensor(data.address), timeout=150
            )
        except TimeoutError:
            raise HTTPException(504, "Sensor measurement timed out") from None
        except Exception:
            raise HTTPException(
                503, "Sensor measurement unavailable; try again closer to the server"
            ) from None

    @api.patch("/sensors/{sensor_id}")
    def patch_sensor(sensor_id: str, data: SensorPatch):
        patch = data.model_dump(exclude_unset=True)
        if any(
            value is None
            for key, value in patch.items()
            if key not in ("room_id", "sample_interval_seconds")
        ):
            raise HTTPException(422, "Only room_id and sample_interval_seconds can be null")
        app.state.db.patch_sensor(sensor_id, patch)
        return next(s for s in sensor_views() if s["id"] == sensor_id)

    @api.delete("/sensors/{sensor_id}")
    def delete_sensor(sensor_id: str):
        app.state.db.delete_sensor(sensor_id)
        return {"ok": True}

    @api.get("/rooms")
    def rooms():
        return room_views(sensor_views())

    @api.get("/floorplan")
    def floorplan():
        return app.state.db.floorplan()

    @api.get("/floorplan/export")
    def export(response: Response):
        response.headers["Content-Disposition"] = 'attachment; filename="sensogrid-floorplan.json"'
        return app.state.db.floorplan()

    @api.post("/floorplan/preview")
    def preview(data: Floorplan):
        app.state.db.save_floorplan(data.model_dump(mode="json"), preview=True)
        return {
            "valid": True,
            "rooms": len(data.rooms),
            "sensors": len(data.sensors),
            "warnings": [],
            "plan": data.model_dump(mode="json"),
        }

    @api.put("/floorplan")
    def save_floorplan(data: Floorplan):
        plan = data.model_dump(mode="json")
        app.state.db.save_floorplan(plan)
        return plan

    @api.get("/history")
    async def history(
        start: datetime,
        end: datetime,
        bucket: Bucket = Bucket.hour,
        room_ids: str = "",
        sensor_ids: str = "",
    ):
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
            points = await app.state.runtime.history(start, end, rooms, sensors, bucket.value)
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
            "source": "demo" if app.state.settings.mode == "demo" else "influxdb3",
        }

    @api.get("/settings")
    def settings():
        return app.state.db.preferences()

    @api.patch("/settings")
    def patch_settings(data: dict):
        value = model_merge(Preferences, app.state.db.preferences(), data)
        app.state.db.set_config("preferences", value)
        return value

    @api.get("/system/settings")
    def system_settings():
        return app.state.db.system_settings()

    @api.patch("/system/settings")
    def patch_system(data: dict):
        value = model_merge(SystemSettings, app.state.db.system_settings(), data)
        app.state.db.set_config("system", value)
        return value

    @api.get("/system/status")
    def system_status():
        return {
            "mode": app.state.settings.mode,
            **app.state.runtime.state,
            "push_available": app.state.push.available,
        }

    @api.get("/alerts/rules")
    def rules():
        return app.state.db.rules()

    @api.post("/alerts/rules", status_code=201)
    def add_rule(data: RuleInput):
        return app.state.db.save_rule(data.model_dump())

    @api.patch("/alerts/rules/{rule_id}")
    def patch_rule(rule_id: str, data: dict):
        old = next((r for r in app.state.db.rules() if r["id"] == rule_id), None)
        if old is None:
            raise HTTPException(404, "Rule not found")
        old.pop("id")
        value = model_merge(RuleInput, old, data)
        return app.state.db.save_rule(value, rule_id)

    @api.delete("/alerts/rules/{rule_id}")
    def delete_rule(rule_id: str):
        app.state.db.delete_rule(rule_id)
        return {"ok": True}

    @api.get("/alerts/events")
    def events():
        return app.state.db.events()

    @api.get("/push/key")
    def push_key():
        return {
            "available": app.state.push.available,
            "public_key": app.state.settings.vapid_public_key or None,
        }

    @api.post("/push/subscriptions", status_code=201)
    async def subscribe(data: Subscription):
        if not app.state.push.available:
            raise HTTPException(503, "Web Push is not configured")
        await asyncio.to_thread(validate_endpoint, data.endpoint)
        for key, length in ((data.keys.p256dh, 65), (data.keys.auth, 16)):
            try:
                valid = len(base64.urlsafe_b64decode(key + "=" * ((-len(key)) % 4))) == length
            except ValueError:
                valid = False
            if not valid:
                raise HTTPException(422, "Invalid subscription keys")
        app.state.db.save_subscription(data.model_dump())
        return {"ok": True}

    @api.delete("/push/subscriptions")
    def unsubscribe(data: Unsubscribe):
        app.state.db.delete_subscription(data.endpoint)
        return {"ok": True}

    @api.post("/push/test")
    async def test_push():
        if not app.state.push.available:
            raise HTTPException(503, "Web Push is not configured")
        return await app.state.push.dispatch(
            {"title": "SensoGrid", "body": "Test notification", "tag": "test"}
        )

    @api.get("/openapi.json", include_in_schema=False)
    def openapi_schema():
        return app.openapi()

    app.include_router(api)
