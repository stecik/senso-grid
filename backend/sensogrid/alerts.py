"""Persistent duration/hysteresis alert evaluation. No historical samples stored here."""

import json
import uuid
from datetime import UTC, datetime


def parse_time(value: str | None) -> datetime | None:
    try:
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    except (ValueError, TypeError, AttributeError):
        return None


class AlertEngine:
    def __init__(self, db, settings, push=None):
        self.db, self.settings, self.push = db, settings, push

    async def evaluate(self, measurements: list[dict], now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(UTC)
        stamp = now.timestamp()
        sensors = self.db.all_sensors()
        live = {m["sensor_id"]: m for m in measurements}
        stale = self.db.system_settings()["stale_after_seconds"]
        notifications = []
        for rule in self.db.rules():
            targets = [
                s
                for s in sensors
                if s["enabled"]
                and (
                    s["id"] == rule["sensor_id"]
                    if rule["sensor_id"]
                    else s["room_id"] == rule["room_id"]
                )
            ]
            values = []
            for sensor in targets:
                m = live.get(sensor["id"], {})
                if m.get("room_id") != sensor["room_id"]:
                    m = {}
                seen = parse_time(m.get("timestamp") or sensor.get("last_seen"))
                age = max(0, stamp - (seen.timestamp() if seen else sensor["created_at"]))
                if rule["metric"] == "offline":
                    values.append(age / 60)
                elif seen and age <= stale and m.get(rule["metric"]) is not None:
                    values.append(m[rule["metric"]])
            value = (
                (min(values) if rule["metric"] == "offline" else sum(values) / len(values))
                if values
                else None
            )
            trigger = value is not None and (
                value > rule["threshold"]
                if rule["operator"] == "above"
                else value < rule["threshold"]
            )
            reset = value is not None and (
                value <= rule["reset_threshold"]
                if rule["operator"] == "above"
                else value >= rule["reset_threshold"]
            )
            with self.db.connection() as c:
                c.execute("BEGIN IMMEDIATE")
                row = c.execute(
                    "SELECT data FROM alert_state WHERE rule_id=?", (rule["id"],)
                ).fetchone()
                state = json.loads(row[0]) if row else {"pending_since": None, "event_id": None}
                if not rule["enabled"]:
                    reset = True
                    trigger = False
                if state["event_id"]:
                    if reset:
                        event_id = state["event_id"]
                        c.execute(
                            "UPDATE events SET state='resolved',resolved_at=? WHERE id=?",
                            (now.isoformat(), event_id),
                        )
                        notifications.append(
                            dict(
                                c.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
                            )
                        )
                        state = {"pending_since": None, "event_id": None}
                elif trigger:
                    if state["pending_since"] is None:
                        state["pending_since"] = stamp
                    if stamp - state["pending_since"] >= rule["duration_seconds"]:
                        event_id = str(uuid.uuid4())
                        message = rule["name"] + ": " + rule["metric"] + " " + format(value, ".1f")
                        event = {
                            "id": event_id,
                            "rule_id": rule["id"],
                            "rule_name": rule["name"],
                            "state": "active",
                            "message": message,
                            "started_at": now.isoformat(),
                            "resolved_at": None,
                        }
                        c.execute(
                            "INSERT INTO events VALUES(:id,:rule_id,:rule_name,:state,:message,:started_at,:resolved_at)",
                            event,
                        )
                        state["event_id"] = event_id
                        notifications.append(event)
                else:
                    state["pending_since"] = None
                c.execute(
                    "INSERT INTO alert_state VALUES(?,?) ON CONFLICT(rule_id) DO UPDATE SET data=excluded.data",
                    (rule["id"], json.dumps(state)),
                )
        if self.push and self.db.preferences()["push_enabled"]:
            for event in notifications:
                await self.push.dispatch(
                    {
                        "title": "SensoGrid · " + event["rule_name"],
                        "body": event["message"],
                        "tag": event["rule_id"],
                        "state": event["state"],
                    }
                )
        return notifications
