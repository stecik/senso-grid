import hashlib
import json
import sqlite3
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC
from pathlib import Path
from typing import Any

from .ble.address import address_key, canonical_address
from .config import Settings
from .schemas import Preferences

DEFAULT_PLAN = {
    "schema_version": 1,
    "id": "home",
    "name": "SensoGrid",
    "units": "m",
    "width": 12,
    "height": 8,
    "rooms": [],
    "sensors": [],
}


class Database:
    def __init__(self, path: Path, settings: Settings | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self.migrate()
        if settings is not None and settings.mode == "ble":
            self._apply_gentle_ble_profile()

    def _apply_gentle_ble_profile(self) -> None:
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute("SELECT 1 FROM config WHERE key='ble_gentle_profile_v1'").fetchone():
                return
            row = c.execute("SELECT value FROM config WHERE key='system'").fetchone()
            system = (
                json.loads(row[0])
                if row
                else {
                    "sample_interval_seconds": getattr(
                        self.settings, "sample_interval_seconds", 300
                    ),
                    "stale_after_seconds": getattr(self.settings, "stale_after_seconds", 1800),
                }
            )
            system["sample_interval_seconds"] = max(300, system["sample_interval_seconds"])
            c.execute(
                "INSERT INTO config VALUES('system',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(system),),
            )
            c.execute(
                "UPDATE sensors SET sample_interval_seconds=300 WHERE sample_interval_seconds<300"
            )
            c.execute("INSERT INTO config VALUES('ble_gentle_profile_v1','true')")

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def migrate(self) -> None:
        with self.connection() as c:
            version = c.execute("PRAGMA user_version").fetchone()[0]
            if version > 2:
                raise RuntimeError("Database version is newer than this application")
            c.execute("PRAGMA journal_mode=WAL")
            if version < 1:
                c.executescript("""BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY CHECK(id=1),username TEXT NOT NULL UNIQUE,password TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS config(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS rooms(id TEXT PRIMARY KEY,name TEXT NOT NULL,archived INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS sensors(id TEXT PRIMARY KEY,name TEXT NOT NULL,address TEXT UNIQUE,protocol TEXT NOT NULL,room_id TEXT REFERENCES rooms(id),enabled INTEGER NOT NULL,sample_interval_seconds INTEGER,last_seen TEXT,created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS rules(id TEXT PRIMARY KEY,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS alert_state(rule_id TEXT PRIMARY KEY REFERENCES rules(id) ON DELETE CASCADE,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,rule_id TEXT NOT NULL,rule_name TEXT NOT NULL,state TEXT NOT NULL,message TEXT NOT NULL,started_at TEXT NOT NULL,resolved_at TEXT);
                CREATE TABLE IF NOT EXISTS subscriptions(endpoint TEXT PRIMARY KEY,data TEXT NOT NULL);
                PRAGMA user_version=2;
                COMMIT;""")

            if version == 1:
                c.execute("BEGIN IMMEDIATE")
                c.execute("ALTER TABLE sensors RENAME TO sensors_v1")
                c.execute(
                    "CREATE TABLE sensors(id TEXT PRIMARY KEY,name TEXT NOT NULL,address TEXT UNIQUE,protocol TEXT NOT NULL,room_id TEXT REFERENCES rooms(id),enabled INTEGER NOT NULL,sample_interval_seconds INTEGER,last_seen TEXT,created_at REAL NOT NULL)"
                )
                row = c.execute("SELECT value FROM config WHERE key='system'").fetchone()
                default_interval = (
                    json.loads(row[0])["sample_interval_seconds"]
                    if row
                    else getattr(self.settings, "sample_interval_seconds", 900)
                )
                c.execute(
                    "INSERT INTO sensors SELECT id,name,address,protocol,room_id,enabled,CASE WHEN sample_interval_seconds=? THEN NULL ELSE sample_interval_seconds END,last_seen,created_at FROM sensors_v1",
                    (default_interval,),
                )
                c.execute("DROP TABLE sensors_v1")
                c.execute("PRAGMA user_version=2")

    def config[T](self, key: str, default: T) -> T:
        with self.connection() as c:
            row = c.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_config(self, key: str, value: Any) -> None:
        with self.connection() as c:
            c.execute(
                "INSERT INTO config VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )

    def preferences(self) -> dict[str, Any]:
        return Preferences.model_validate(
            self.config("preferences", Preferences().model_dump(mode="json"))
        ).model_dump(mode="json")

    def system_settings(self) -> dict[str, Any]:
        return self.config(
            "system",
            {
                "sample_interval_seconds": getattr(self.settings, "sample_interval_seconds", 300),
                "stale_after_seconds": getattr(self.settings, "stale_after_seconds", 1800),
            },
        )

    def has_user(self) -> bool:
        with self.connection() as c:
            return bool(c.execute("SELECT 1 FROM users LIMIT 1").fetchone())

    def user(self, username: str) -> dict[str, Any] | None:
        with self.connection() as c:
            r = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return dict(r) if r else None

    def create_user(self, username: str, password: str) -> dict[str, str | int]:
        with self.connection() as c:
            c.execute("INSERT INTO users VALUES(1,?,?)", (username, password))
        return {"id": 1, "username": username}

    def add_session(self, token: str, expires: float) -> None:
        with self.connection() as c:
            c.execute("DELETE FROM sessions WHERE expires<=?", (time.time(),))
            c.execute(
                "INSERT INTO sessions VALUES(?,1,?)",
                (hashlib.sha256(token.encode()).hexdigest(), expires),
            )

    def session_user(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        with self.connection() as c:
            r = c.execute(
                "SELECT users.id,users.username FROM sessions JOIN users ON users.id=sessions.user_id WHERE token=? AND expires>?",
                (hashlib.sha256(token.encode()).hexdigest(), time.time()),
            ).fetchone()
        return dict(r) if r else None

    def delete_session(self, token: str) -> None:
        with self.connection() as c:
            c.execute(
                "DELETE FROM sessions WHERE token=?", (hashlib.sha256(token.encode()).hexdigest(),)
            )

    def all_sensors(self) -> list[dict[str, Any]]:
        with self.connection() as c:
            rows = c.execute("SELECT * FROM sensors ORDER BY created_at,id").fetchall()
        default_interval = self.system_settings()["sample_interval_seconds"]
        return [
            {
                **dict(r),
                "enabled": bool(r["enabled"]),
                "interval_override_seconds": r["sample_interval_seconds"],
                "sample_interval_seconds": r["sample_interval_seconds"] or default_interval,
            }
            for r in rows
        ]

    def note_seen(self, sensor_id: str, iso_timestamp: str) -> None:
        with self.connection() as c:
            c.execute(
                "UPDATE sensors SET last_seen=? WHERE id=? AND (last_seen IS NULL OR last_seen<?)",
                (iso_timestamp, sensor_id, iso_timestamp),
            )

    def rooms(self, archived: bool = False) -> list[dict[str, Any]]:
        with self.connection() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM rooms"
                    + ("" if archived else " WHERE archived=0")
                    + " ORDER BY rowid"
                )
            ]

    def validate_room(self, c: sqlite3.Connection, room_id: str | None) -> None:
        if (
            room_id is not None
            and not c.execute(
                "SELECT 1 FROM rooms WHERE id=? AND archived=0", (room_id,)
            ).fetchone()
        ):
            raise ValueError("Unknown room")

    def add_sensor(self, data: dict[str, Any]) -> str:
        data = {**data, "address": canonical_address(data["address"])}
        sensor_id = str(uuid.uuid4())
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            if any(
                row["address"] and address_key(row["address"]) == address_key(data["address"])
                for row in c.execute("SELECT address FROM sensors")
            ):
                raise sqlite3.IntegrityError("Sensor address already registered")
            self.validate_room(c, data.get("room_id"))
            c.execute(
                "INSERT INTO sensors VALUES(?,?,?,?,?,1,?,NULL,?)",
                (
                    sensor_id,
                    data["name"],
                    data["address"],
                    data["protocol"],
                    data.get("room_id"),
                    None,
                    time.time(),
                ),
            )
        return sensor_id

    def patch_sensor(self, sensor_id: str, data: dict[str, Any]) -> None:
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            if not c.execute("SELECT 1 FROM sensors WHERE id=?", (sensor_id,)).fetchone():
                raise KeyError("Sensor not found")
            if "room_id" in data:
                self.validate_room(c, data["room_id"])
            if data:
                keys = list(data)
                c.execute(
                    "UPDATE sensors SET " + ",".join(k + "=?" for k in keys) + " WHERE id=?",
                    [*[data[k] for k in keys], sensor_id],
                )
            if "room_id" in data:
                row = c.execute("SELECT value FROM config WHERE key='floorplan'").fetchone()
                if row:
                    plan = json.loads(row[0])
                    from .schemas import contains

                    for placement in plan["sensors"]:
                        if placement["sensor_id"] == sensor_id:
                            placement["room_id"] = data["room_id"]
                            room = next(
                                (r for r in plan["rooms"] if r["id"] == data["room_id"]), None
                            )
                            if room and not contains(
                                room["polygon"], (placement["x"], placement["y"])
                            ):
                                placement["x"], placement["y"] = room["polygon"][0]
                    c.execute(
                        "UPDATE config SET value=? WHERE key='floorplan'", (json.dumps(plan),)
                    )

    def delete_sensor(self, sensor_id: str) -> None:
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            if not c.execute("DELETE FROM sensors WHERE id=?", (sensor_id,)).rowcount:
                raise KeyError("Sensor not found")
            row = c.execute("SELECT value FROM config WHERE key='floorplan'").fetchone()
            if row:
                plan = json.loads(row[0])
                plan["sensors"] = [s for s in plan["sensors"] if s["sensor_id"] != sensor_id]
                c.execute("UPDATE config SET value=? WHERE key='floorplan'", (json.dumps(plan),))
            for row in c.execute("SELECT id,data FROM rules").fetchall():
                rule = json.loads(row["data"])
                if rule.get("sensor_id") == sensor_id:
                    rule["enabled"] = False
                    c.execute("UPDATE rules SET data=? WHERE id=?", (json.dumps(rule), row["id"]))

    def floorplan(self) -> dict[str, Any]:
        return self.config("floorplan", DEFAULT_PLAN.copy())

    def validate_plan(self, c: sqlite3.Connection, plan: dict[str, Any]) -> None:
        sensors = {r["id"]: dict(r) for r in c.execute("SELECT * FROM sensors")}
        room_ids = {r["id"] for r in plan["rooms"]}
        for s in plan["sensors"]:
            if s["sensor_id"] not in sensors:
                raise ValueError("Unknown sensor")
            if s["room_id"] is not None and s["room_id"] not in room_ids:
                raise ValueError("Unknown room")

    def save_floorplan(self, plan: dict[str, Any], preview: bool = False) -> None:
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            self.validate_plan(c, plan)
            if preview:
                return
            c.execute("UPDATE rooms SET archived=1")
            for room in plan["rooms"]:
                c.execute(
                    "INSERT INTO rooms VALUES(?,?,0) ON CONFLICT(id) DO UPDATE SET name=excluded.name,archived=0",
                    (room["id"], room["name"]),
                )
            c.execute(
                "UPDATE sensors SET room_id=NULL WHERE room_id IN (SELECT id FROM rooms WHERE archived=1)"
            )
            for placement in plan["sensors"]:
                c.execute(
                    "UPDATE sensors SET room_id=? WHERE id=?",
                    (placement["room_id"], placement["sensor_id"]),
                )
            for row in c.execute("SELECT id,data FROM rules").fetchall():
                rule = json.loads(row["data"])
                if rule.get("room_id") and rule["room_id"] not in {r["id"] for r in plan["rooms"]}:
                    rule["enabled"] = False
                    c.execute("UPDATE rules SET data=? WHERE id=?", (json.dumps(rule), row["id"]))
            c.execute(
                "INSERT INTO config VALUES('floorplan',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(plan),),
            )

    def rules(self) -> list[dict[str, Any]]:
        with self.connection() as c:
            return [
                {"id": r["id"], **json.loads(r["data"])}
                for r in c.execute("SELECT * FROM rules ORDER BY rowid")
            ]

    def save_rule(self, rule: dict[str, Any], rule_id: str | None = None) -> dict[str, Any]:
        rule_id = rule_id or str(uuid.uuid4())
        with self.connection() as c:
            if rule.get("room_id"):
                self.validate_room(c, rule["room_id"])
            if (
                rule.get("sensor_id")
                and not c.execute(
                    "SELECT 1 FROM sensors WHERE id=?", (rule["sensor_id"],)
                ).fetchone()
            ):
                raise ValueError("Unknown sensor")
            c.execute(
                "INSERT INTO rules VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                (rule_id, json.dumps(rule)),
            )
            old = c.execute("SELECT data FROM alert_state WHERE rule_id=?", (rule_id,)).fetchone()
            if old:
                state = json.loads(old[0])
                event = state.get("event_id")
                if event:
                    from datetime import datetime

                    c.execute(
                        "UPDATE events SET state='resolved',resolved_at=? WHERE id=? AND state='active'",
                        (datetime.now(UTC).isoformat(), event),
                    )
            c.execute("DELETE FROM alert_state WHERE rule_id=?", (rule_id,))
        return {"id": rule_id, **rule}

    def delete_rule(self, rule_id: str) -> None:
        with self.connection() as c:
            if not c.execute("DELETE FROM rules WHERE id=?", (rule_id,)).rowcount:
                raise KeyError("Rule not found")
            from datetime import datetime

            c.execute(
                "UPDATE events SET state='resolved',resolved_at=? WHERE rule_id=? AND state='active'",
                (datetime.now(UTC).isoformat(), rule_id),
            )

    def events(self) -> list[dict[str, Any]]:
        with self.connection() as c:
            return [
                dict(r)
                for r in c.execute("SELECT * FROM events ORDER BY started_at DESC LIMIT 500")
            ]

    def subscriptions(self) -> list[dict[str, Any]]:
        with self.connection() as c:
            return [json.loads(r[0]) for r in c.execute("SELECT data FROM subscriptions")]

    def save_subscription(self, data: dict[str, Any]) -> None:
        with self.connection() as c:
            c.execute(
                "INSERT INTO subscriptions VALUES(?,?) ON CONFLICT(endpoint) DO UPDATE SET data=excluded.data",
                (data["endpoint"], json.dumps(data)),
            )

    def delete_subscription(self, endpoint: str) -> None:
        with self.connection() as c:
            c.execute("DELETE FROM subscriptions WHERE endpoint=?", (endpoint,))

    def seed_demo(self) -> None:
        if self.config("demo_seeded", False):
            return
        plan: dict[str, Any] = {
            "schema_version": 1,
            "id": "home",
            "name": "Domov",
            "units": "m",
            "width": 12,
            "height": 8,
            "rooms": [
                {
                    "id": "living",
                    "name": "Obývací pokoj",
                    "polygon": [[0, 0], [7, 0], [7, 5], [0, 5]],
                },
                {"id": "bedroom", "name": "Ložnice", "polygon": [[7, 0], [12, 0], [12, 5], [7, 5]]},
                {"id": "kitchen", "name": "Kuchyně", "polygon": [[0, 5], [7, 5], [7, 8], [0, 8]]},
                {
                    "id": "bathroom",
                    "name": "Koupelna",
                    "polygon": [[7, 5], [12, 5], [12, 8], [7, 8]],
                },
            ],
            "sensors": [],
        }
        with self.connection() as c:
            rooms: list[dict[str, Any]] = plan["rooms"]
            for r in rooms:
                c.execute("INSERT OR IGNORE INTO rooms VALUES(?,?,0)", (r["id"], r["name"]))
                sid = "demo-" + r["id"]
                c.execute(
                    "INSERT OR IGNORE INTO sensors VALUES(?,?,NULL,'lt_thermometer',?,1,NULL,NULL,?)",
                    (sid, r["name"], r["id"], time.time()),
                )
                p = r["polygon"]
                plan["sensors"].append(
                    {
                        "sensor_id": sid,
                        "room_id": r["id"],
                        "x": (p[0][0] + p[2][0]) / 2,
                        "y": (p[0][1] + p[2][1]) / 2,
                    }
                )
            c.execute("INSERT OR IGNORE INTO config VALUES('floorplan',?)", (json.dumps(plan),))
            c.execute("INSERT OR REPLACE INTO config VALUES('demo_seeded','true')")
