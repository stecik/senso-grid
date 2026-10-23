import asyncio
import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sensogrid.config import Settings
from sensogrid.db import Database
from sensogrid.main import create_app
from sensogrid.push import PushService, validate_endpoint


class FakeRuntime:
    def __init__(self, settings, db):
        self.settings, self.db = settings, db
        self.readings = []
        self.read_states = {}
        self.unavailable_sensors = set()
        self.state = {"collector": "idle", "storage": "ready", "last_error": None}

    async def start(self):
        pass

    async def stop(self):
        pass

    def current(self):
        return self.readings

    async def discover(self):
        return [
            {
                "name": "LT_test",
                "address": "AA:BB",
                "rssi": -50,
                "protocol": "lt_thermometer",
                "service_uuids": [],
                "manufacturer_data": {},
                "service_data": {},
            }
        ]

    async def history(self, *args):
        return []


@pytest.fixture
def client(tmp_path):
    app = create_app(
        Settings(mode="off", data_dir=tmp_path, static_dir=tmp_path / "static"),
        runtime_factory=FakeRuntime,
    )
    with TestClient(app) as client:
        yield client


@pytest.fixture
def logged(client):
    assert (
        client.post(
            "/api/auth/setup", json={"username": "admin", "password": "Safe-password-123"}
        ).status_code
        == 200
    )
    return client


def test_setup_session_csrf_logout(logged):
    assert logged.get("/api/auth/status").json()["authenticated"]
    assert logged.get("/api/auth/me").json() == {"id": 1, "username": "admin"}
    assert (
        logged.post(
            "/api/auth/setup", json={"username": "other", "password": "Safe-password-123"}
        ).status_code
        == 409
    )
    assert (
        logged.patch(
            "/api/settings", json={"theme": "dark"}, headers={"Origin": "https://evil.invalid"}
        ).status_code
        == 403
    )
    assert (
        logged.patch(
            "/api/settings", json={"theme": "dark"}, headers={"Sec-Fetch-Site": "cross-site"}
        ).status_code
        == 403
    )
    assert (
        logged.patch(
            "/api/settings", json={"theme": "dark"}, headers={"Origin": "http://testserver"}
        ).status_code
        == 200
    )
    cookie = logged.cookies.get("sensogrid_session")
    with logged.app.state.db.connection() as c:
        stored = c.execute("SELECT token FROM sessions").fetchone()[0]
        assert stored == hashlib.sha256(cookie.encode()).hexdigest()
        assert "Safe-password" not in c.execute("SELECT password FROM users").fetchone()[0]
    assert logged.post("/api/auth/logout").status_code == 200
    logged.cookies.set("sensogrid_session", cookie)
    assert logged.get("/api/dashboard").status_code == 401


def test_unauthenticated_and_expired_session(client):
    assert client.get("/api/settings").status_code == 401
    assert client.get("/api/auth/status").json()["setup_required"]
    response = client.post(
        "/api/auth/setup", json={"username": "admin", "password": "Safe-password-123"}
    )
    assert (
        "HttpOnly" in response.headers["set-cookie"]
        and "SameSite=strict" in response.headers["set-cookie"]
    )
    with client.app.state.db.connection() as c:
        c.execute("UPDATE sessions SET expires=0")
    assert client.get("/api/sensors").status_code == 401
    assert (
        client.post(
            "/api/auth/login", json={"username": "admin", "password": "Safe-password-123"}
        ).status_code
        == 200
    )


def test_auth_rate_limit_and_error_no_password(client):
    for _ in range(10):
        assert (
            client.post(
                "/api/auth/login", json={"username": "missing", "password": "Safe-password-123"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/auth/login", json={"username": "missing", "password": "Safe-password-123"}
        ).status_code
        == 429
    )
    response = client.post("/api/auth/setup", json={"username": "admin", "password": "short"})
    assert "short" not in response.text


def test_setup_database_race(tmp_path):
    db = Database(tmp_path / "config.sqlite3")

    def insert(name):
        try:
            db.create_user(name, "hash")
            return True
        except sqlite3.IntegrityError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sum(executor.map(insert, ["one", "two"])) == 1


def test_preferences_and_system_validation(logged):
    response = logged.patch("/api/settings", json={"heatmap": {"temperature": [10, 30]}})
    assert response.json()["heatmap"] == {"temperature": [10, 30], "humidity": [30, 70]}
    assert (
        logged.patch("/api/settings", json={"heatmap": {"temperature": [30, 20, 10]}}).status_code
        == 422
    )
    assert logged.patch("/api/settings", json={"unknown": True}).status_code == 422
    assert (
        logged.patch("/api/system/settings", json={"sample_interval_seconds": 0}).status_code == 422
    )
    assert (
        logged.patch("/api/system/settings", json={"sample_interval_seconds": 60}).json()[
            "sample_interval_seconds"
        ]
        == 60
    )


def test_current_stale_disabled_and_history(logged):
    sensor = logged.post("/api/sensors", json={"name": "Desk", "address": "AA:BB"}).json()
    now = datetime.now(UTC)
    logged.app.state.runtime.readings = [
        {
            "sensor_id": sensor["id"],
            "timestamp": now.isoformat(),
            "temperature": 23.4,
            "humidity": 52.0,
        }
    ]
    assert logged.get("/api/dashboard").json()["average_temperature"] == 23.4
    logged.app.state.runtime.readings[0]["timestamp"] = (now - timedelta(hours=2)).isoformat()
    assert logged.get("/api/dashboard").json()["average_temperature"] is None
    assert not logged.get("/api/sensors").json()[0]["available"]
    logged.app.state.runtime.readings[0]["timestamp"] = now.isoformat()
    assert logged.patch("/api/sensors/" + sensor["id"], json={"enabled": False}).status_code == 200
    assert not logged.get("/api/sensors").json()[0]["available"]
    query = {"start": (now - timedelta(days=1)).isoformat(), "end": now.isoformat()}
    assert logged.get("/api/history", params=query).json() == {"points": [], "source": "influxdb3"}
    assert (
        logged.get(
            "/api/history", params={**query, "start": (now - timedelta(days=367)).isoformat()}
        ).status_code
        == 422
    )
    assert logged.get("/api/history", params={**query, "bucket": "invalid"}).status_code == 422
    assert logged.post("/api/sensors/discover").json()["devices"][0]["name"] == "LT_test"


def test_rules_and_unconfigured_push(logged):
    sensor = logged.post("/api/sensors", json={"name": "Desk", "address": "AA:BB"}).json()
    rule = {
        "name": "Warm",
        "sensor_id": sensor["id"],
        "metric": "temperature",
        "operator": "above",
        "threshold": 25,
        "reset_threshold": 24,
        "duration_seconds": 60,
    }
    response = logged.post("/api/alerts/rules", json=rule)
    assert response.status_code == 201
    rid = response.json()["id"]
    assert logged.patch("/api/alerts/rules/" + rid, json={"threshold": 23}).status_code == 422
    assert logged.patch("/api/alerts/rules/" + rid, json={"name": "Hot"}).json()["name"] == "Hot"
    assert logged.get("/api/push/key").json() == {"available": False, "public_key": None}
    assert logged.post("/api/push/test").status_code == 503
    assert logged.delete("/api/alerts/rules/" + rid).status_code == 200
    assert logged.delete("/api/alerts/rules/" + rid).status_code == 404


def test_push_endpoint_ssrf_and_cleanup(tmp_path, monkeypatch):
    for url in [
        "http://fcm.googleapis.com/x",
        "https://127.0.0.1/x",
        "https://fcm.googleapis.com.evil.test/x",
        "https://user@fcm.googleapis.com/x",
        "https://fcm.googleapis.com:8443/x",
    ]:
        with pytest.raises(ValueError):
            validate_endpoint(url, resolve=False)
    import sensogrid.push as module

    monkeypatch.setattr(
        module.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 443))]
    )
    with pytest.raises(ValueError):
        validate_endpoint("https://fcm.googleapis.com/push/x")
    monkeypatch.setattr(module, "validate_endpoint", lambda x: x)
    db = Database(tmp_path / "config.sqlite3")
    db.save_subscription({"endpoint": "https://fcm.googleapis.com/x", "keys": {}})
    import pywebpush

    class Gone:
        status_code = 410
        text = "expired"

    def expired(**kwargs):
        raise pywebpush.WebPushException("gone", response=Gone())

    monkeypatch.setattr(pywebpush, "webpush", expired)
    push = PushService(Settings(vapid_private_key="fake", vapid_public_key="fake"), db)
    assert asyncio.run(push.dispatch({"title": "test"})) == {"sent": 0, "failed": 1}
    assert db.subscriptions() == []


def test_spa_does_not_capture_api_or_traversal(tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>SensoGrid</html>")
    (tmp_path / "private.txt").write_text("secret")
    with TestClient(
        create_app(
            Settings(mode="off", data_dir=tmp_path, static_dir=static), runtime_factory=FakeRuntime
        )
    ) as client:
        assert client.get("/history").status_code == 200
        assert client.get("/api/missing").status_code == 404
        assert client.get("/%2e%2e/private.txt").status_code == 404
        assert client.get("/missing.js").status_code == 404
        assert client.get("/health").headers["cache-control"] == "no-store"


def test_global_interval_inheritance_and_overrides(logged):
    sensor = logged.post("/api/sensors", json={"name": "Desk", "address": "AA:BB"}).json()
    sensor_id = sensor["id"]
    assert sensor["sample_interval_seconds"] == 900 and sensor["interval_override_seconds"] is None
    assert (
        logged.patch("/api/system/settings", json={"sample_interval_seconds": 300}).status_code
        == 200
    )
    assert logged.get("/api/sensors").json()[0]["sample_interval_seconds"] == 300
    assert (
        logged.patch("/api/sensors/" + sensor_id, json={"sample_interval_seconds": 60}).json()[
            "interval_override_seconds"
        ]
        == 60
    )
    assert (
        logged.patch("/api/system/settings", json={"sample_interval_seconds": 120}).status_code
        == 200
    )
    assert logged.get("/api/sensors").json()[0]["sample_interval_seconds"] == 60
    response = logged.patch("/api/sensors/" + sensor_id, json={"sample_interval_seconds": None})
    assert response.status_code == 200
    assert response.json()["interval_override_seconds"] is None
    assert response.json()["sample_interval_seconds"] == 120


def test_schema_v1_migration_preserves_metadata_and_custom_intervals(tmp_path):
    db = Database(tmp_path / "old.sqlite3")
    with db.connection() as c:
        c.execute("DROP TABLE sensors")
        c.execute(
            "CREATE TABLE sensors(id TEXT PRIMARY KEY,name TEXT NOT NULL,address TEXT UNIQUE,protocol TEXT NOT NULL,room_id TEXT REFERENCES rooms(id),enabled INTEGER NOT NULL,sample_interval_seconds INTEGER NOT NULL,last_seen TEXT,created_at REAL NOT NULL)"
        )
        c.executemany(
            "INSERT INTO sensors VALUES(?,? ,?,'lt_thermometer',NULL,1,?,NULL,0)",
            [("default", "Default", "AA", 900), ("custom", "Custom", "BB", 120)],
        )
        c.execute("PRAGMA user_version=1")
    migrated = Database(db.path)
    sensors = {s["id"]: s for s in migrated.all_sensors()}
    assert sensors["default"]["interval_override_seconds"] is None
    assert sensors["custom"]["interval_override_seconds"] == 120
    assert sensors["custom"]["name"] == "Custom"
    with migrated.connection() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 2


def test_reassignment_waits_for_sample_from_new_room(logged):
    sensor = logged.post("/api/sensors", json={"name": "Desk", "address": "AA:BB"}).json()
    now = datetime.now(UTC).isoformat()
    sample = {
        "sensor_id": sensor["id"],
        "room_id": None,
        "timestamp": now,
        "temperature": 28,
        "humidity": 50,
    }
    logged.app.state.runtime.readings = [sample]
    assert logged.get("/api/dashboard").json()["average_temperature"] == 28
    plan = {
        "schema_version": 1,
        "id": "home",
        "name": "Home",
        "units": "m",
        "width": 5,
        "height": 5,
        "rooms": [{"id": "r", "name": "Room", "polygon": [[0, 0], [5, 0], [5, 5], [0, 5]]}],
        "sensors": [{"sensor_id": sensor["id"], "room_id": "r", "x": 2, "y": 2}],
    }
    assert logged.put("/api/floorplan", json=plan).status_code == 200
    result = logged.get("/api/dashboard").json()
    assert result["average_temperature"] is None
    assert not result["sensors"][0]["available"] and not result["rooms"][0]["available"]
    sample["room_id"] = "r"
    assert logged.get("/api/dashboard").json()["rooms"][0]["temperature"] == 28


def test_history_point_limit_is_actionable_client_error(logged):
    async def limit(*args):
        raise ValueError("Too many points; choose a coarser aggregation")

    logged.app.state.runtime.history = limit
    now = datetime.now(UTC)
    params = {
        "start": (now - timedelta(days=1)).isoformat(),
        "end": now.isoformat(),
        "bucket": "raw",
    }
    response = logged.get("/api/history", params=params)
    assert response.status_code == 422 and "coarser aggregation" in response.json()["detail"]

    async def failure(*args):
        raise ValueError("Unexpected InfluxDB query response")

    logged.app.state.runtime.history = failure
    assert logged.get("/api/history", params=params).status_code == 503


@pytest.mark.parametrize("password", ["Abcdefg!", "Červená!"])
def test_setup_accepts_eight_characters_without_digits(client, password):
    assert (
        client.post("/api/auth/setup", json={"username": "admin", "password": password}).status_code
        == 200
    )
    assert client.post("/api/auth/logout").status_code == 200
    assert (
        client.post("/api/auth/login", json={"username": "admin", "password": password}).status_code
        == 200
    )


@pytest.mark.parametrize(
    "password",
    ["Abcdef!", "abcdefghijk!", "ABCDEFGHIJK!", "Abcdefghijkl", "Abcdefghijk1", "Abcdefghijk "],
)
def test_setup_rejects_missing_password_requirements(client, password):
    response = client.post("/api/auth/setup", json={"username": "admin", "password": password})
    assert response.status_code == 422
    assert password not in response.text
    assert client.get("/api/auth/status").json()["setup_required"]


def test_login_preserves_existing_password_without_new_complexity(client):
    from sensogrid.api import hash_password

    password = "previous-password"
    client.app.state.db.create_user("admin", hash_password(password))
    assert (
        client.post("/api/auth/login", json={"username": "admin", "password": password}).status_code
        == 200
    )


def test_discovered_sensor_preview_does_not_register_sensor(logged):
    from sensogrid.runtime import Runtime

    class Driver:
        async def read_current(self, address):
            if address != "AA:BB":
                raise LookupError("Not discovered")
            return {"temperature": 22.8, "humidity": 51.0, "timestamp": "2026-10-22T18:19:00Z"}

    runtime = Runtime(
        logged.app.state.settings.model_copy(update={"mode": "ble"}), logged.app.state.db
    )
    runtime.driver = Driver()
    logged.app.state.runtime = runtime
    response = logged.post("/api/sensors/preview", json={"address": "AA:BB"})
    assert response.status_code == 200
    assert response.json()["temperature"] == 22.8
    assert response.json()["humidity"] == 51.0
    assert logged.get("/api/sensors").json() == []
    assert logged.post("/api/sensors/preview", json={"address": ""}).status_code == 422
    assert logged.post("/api/sensors/preview", json={"address": "UNKNOWN"}).status_code == 503
    assert runtime.current() == []
    assert not list(runtime._outbox.glob("*.json"))


def test_fresh_measurement_stays_available_until_retries_exhausted(logged):
    sensor = logged.post("/api/sensors", json={"name": "Desk", "address": "AA:BB"}).json()
    runtime = logged.app.state.runtime
    runtime.readings = [
        {
            "sensor_id": sensor["id"],
            "room_id": None,
            "temperature": 22.4,
            "humidity": 47,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    ]
    runtime.read_states = {sensor["id"]: "retrying"}
    assert logged.get("/api/dashboard").json()["sensors"][0]["available"]
    runtime.read_states[sensor["id"]] = "unavailable"
    assert not logged.get("/api/dashboard").json()["sensors"][0]["available"]
    runtime.unavailable_sensors = {sensor["id"]}
    runtime.read_states[sensor["id"]] = "retrying"
    assert not logged.get("/api/dashboard").json()["sensors"][0]["available"]
    runtime.unavailable_sensors.clear()
    runtime.read_states[sensor["id"]] = "ready"
    assert logged.get("/api/dashboard").json()["sensors"][0]["available"]


def test_offline_sensor_retains_server_sample_without_entering_live_averages(logged):
    sensor = logged.post("/api/sensors", json={"name": "Desk", "address": "AA:BB"}).json()
    runtime = logged.app.state.runtime
    timestamp = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    runtime.readings = [
        {
            "sensor_id": sensor["id"],
            "room_id": None,
            "timestamp": timestamp,
            "temperature": 22.4,
            "humidity": 47,
            "battery_percent": 0,
            "battery_timestamp": timestamp,
        }
    ]
    runtime.read_states = {sensor["id"]: "unavailable"}
    runtime.unavailable_sensors = {sensor["id"]}
    view = logged.get("/api/sensors").json()[0]
    assert view["temperature"] == 22.4
    assert view["humidity"] == 47
    assert view["last_seen"] == timestamp
    assert view["available"] is False
    assert view["battery_percent"] == 0
    assert view["battery_timestamp"] == timestamp
    dashboard = logged.get("/api/dashboard").json()
    assert dashboard["average_temperature"] is None
    assert dashboard["average_humidity"] is None


def test_diagnostics_download_requires_login(client):
    assert client.get("/api/diagnostics").status_code == 401


def test_diagnostics_download_is_redacted_zip_and_reports_missing_host_logs(logged):
    import io
    import json
    import zipfile

    response = logged.get("/api/diagnostics")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert {"manifest.json", "snapshot.json"} <= set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["host_logs"]["available"] is False
        snapshot = json.loads(archive.read("snapshot.json"))
        assert snapshot["configuration"]["mode"] == "off"
        assert not any(name.endswith((".sqlite3", ".env")) for name in archive.namelist())
        contents = b"\n".join(archive.read(name) for name in archive.namelist())
        assert b"Safe-password-123" not in contents
        assert b"sensogrid_session" not in contents


def test_diagnostics_includes_host_snapshot_and_redacts_settings_secrets(logged, tmp_path):
    import io
    import json
    import zipfile

    settings = logged.app.state.settings
    settings.host_diagnostics_dir = tmp_path / "host"
    settings.host_diagnostics_dir.mkdir()
    settings.influx_token = "a-private-token-value"
    payload = {
        "created_utc": datetime.now(UTC).isoformat(),
        "commands": {"bluetooth": {"output": "error a-private-token-value"}},
    }
    (settings.host_diagnostics_dir / "host.json").write_text(json.dumps(payload))
    with zipfile.ZipFile(io.BytesIO(logged.get("/api/diagnostics").content)) as archive:
        assert json.loads(archive.read("manifest.json"))["host_logs"]["available"]
        assert b"a-private-token-value" not in archive.read("host.json")
        for name in archive.namelist():
            if name.startswith("application/"):
                for line in archive.read(name).decode().splitlines():
                    assert isinstance(json.loads(line), dict)


def test_diagnostics_limits_repeated_downloads(logged):
    assert [logged.get("/api/diagnostics").status_code for _ in range(4)] == [200, 200, 200, 429]


def test_invalid_host_snapshot_does_not_break_application_download(logged, tmp_path):
    import io
    import json
    import zipfile

    settings = logged.app.state.settings
    settings.host_diagnostics_dir = tmp_path / "host-invalid"
    settings.host_diagnostics_dir.mkdir()
    (settings.host_diagnostics_dir / "host.json").write_text("[]")
    response = logged.get("/api/diagnostics")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert not json.loads(archive.read("manifest.json"))["host_logs"]["available"]


def test_same_mac_with_different_format_does_not_create_another_sensor(logged):
    first = logged.post(
        "/api/sensors", json={"name": "Ložnice", "address": "AA:BB:CC:DD:EE:FF"}
    ).json()
    assert (
        logged.post(
            "/api/sensors", json={"name": "LT_factory", "address": " aa-bb-cc-dd-ee-ff "}
        ).status_code
        == 409
    )
    sensors = logged.get("/api/sensors").json()
    assert len(sensors) == 1
    assert sensors[0]["id"] == first["id"]
    assert sensors[0]["name"] == "Ložnice"


def test_legacy_heatmap_settings_keep_outer_limits_and_preferences(logged):
    stored = {
        "language": "en",
        "theme": "dark",
        "temperature_unit": "F",
        "push_enabled": False,
        "heatmap": {"temperature": [18, 22, 25], "humidity": [35, 65]},
    }
    logged.app.state.db.set_config("preferences", stored)
    expected = {**stored, "heatmap": {"temperature": [18, 25], "humidity": [35, 65]}}
    assert logged.get("/api/settings").json() == expected
    response = logged.patch("/api/settings", json={"language": "cs"})
    assert response.status_code == 200
    assert response.json() == {**expected, "language": "cs"}
    assert logged.app.state.db.config("preferences", {})["heatmap"]["temperature"] == [18, 25]


@pytest.mark.parametrize("limits", [[25, 18], [22, 22], [18], [18, 20, 22, 25]])
def test_reject_invalid_temperature_heatmap_limits(logged, limits):
    original = logged.get("/api/settings").json()
    assert (
        logged.patch("/api/settings", json={"heatmap": {"temperature": limits}}).status_code == 422
    )
    assert logged.get("/api/settings").json() == original
