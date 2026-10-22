from typing import Literal
from unicodedata import category

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ble.address import canonical_address


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Credentials(StrictModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=1, max_length=256)


class SetupCredentials(Credentials):
    password: str = Field(min_length=8, max_length=256)

    @field_validator("password")
    @classmethod
    def password_complexity(cls, value: str) -> str:
        categories = {category(char) for char in value}
        if not (
            "Lu" in categories and "Ll" in categories and any(c[0] in "PS" for c in categories)
        ):
            raise ValueError(
                "Password requires an uppercase letter, a lowercase letter and a symbol"
            )
        return value


class SensorInput(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    address: str = Field(min_length=1, max_length=128)
    room_id: str | None = None
    protocol: Literal["lt_thermometer"] = "lt_thermometer"

    @field_validator("address", mode="before")
    @classmethod
    def normalize_address(cls, value):
        return canonical_address(value) if isinstance(value, str) else value


class SensorPreviewInput(StrictModel):
    address: str = Field(min_length=1, max_length=128)


class SensorPatch(StrictModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    room_id: str | None = None
    enabled: bool | None = None
    sample_interval_seconds: int | None = Field(None, ge=10, le=86400)


class Room(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    polygon: list[tuple[float, float]] = Field(min_length=3, max_length=500)


class Placement(StrictModel):
    sensor_id: str
    room_id: str | None = None
    x: float
    y: float


def cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def on_segment(a, b, p):
    return (
        abs(cross(a, b, p)) < 1e-9
        and min(a[0], b[0]) - 1e-9 <= p[0] <= max(a[0], b[0]) + 1e-9
        and min(a[1], b[1]) - 1e-9 <= p[1] <= max(a[1], b[1]) + 1e-9
    )


def intersects(a, b, c, d):
    ca, cb, cc, cd = cross(a, b, c), cross(a, b, d), cross(c, d, a), cross(c, d, b)
    return (ca * cb < 0 and cc * cd < 0) or any(
        (on_segment(a, b, c), on_segment(a, b, d), on_segment(c, d, a), on_segment(c, d, b))
    )


def contains(poly, p):
    inside = False
    for i, a in enumerate(poly):
        b = poly[(i + 1) % len(poly)]
        if on_segment(a, b, p):
            return True
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (
            b[1] - a[1]
        ) + a[0]:
            inside = not inside
    return inside


class ImportCanvas(StrictModel):
    width: float = Field(gt=0, le=10000)
    height: float = Field(gt=0, le=10000)


class CanvasFloorplan(StrictModel):
    schemaVersion: Literal[1]
    name: str = Field(min_length=1, max_length=100)
    units: Literal["meters"]
    canvas: ImportCanvas
    rooms: list[Room] = Field(default_factory=list, max_length=500)
    sensors: list[Placement] = Field(default_factory=list, max_length=2000)


class Floorplan(StrictModel):
    schema_version: Literal[1] = 1
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    units: Literal["m"] = "m"
    width: float = Field(gt=0, le=10000)
    height: float = Field(gt=0, le=10000)
    rooms: list[Room] = Field(default_factory=list, max_length=500)
    sensors: list[Placement] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="before")
    @classmethod
    def canvas_import(cls, value):
        if isinstance(value, dict) and "schemaVersion" in value:
            imported = CanvasFloorplan.model_validate(value)
            return {
                "schema_version": 1,
                "id": "home",
                "name": imported.name,
                "units": "m",
                "width": imported.canvas.width,
                "height": imported.canvas.height,
                "rooms": [room.model_dump() for room in imported.rooms],
                "sensors": [sensor.model_dump() for sensor in imported.sensors],
            }
        return value

    @model_validator(mode="after")
    def geometry(self):
        ids = [r.id for r in self.rooms]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate room IDs")
        placements = [s.sensor_id for s in self.sensors]
        if len(placements) != len(set(placements)):
            raise ValueError("Duplicate sensor placements")
        rooms = {r.id: r for r in self.rooms}
        for room in self.rooms:
            p = room.polygon
            n = len(p)
            if len(set(p)) != n:
                raise ValueError("Polygon vertices must be distinct")
            if any(not (0 <= x <= self.width and 0 <= y <= self.height) for x, y in p):
                raise ValueError("Polygon out of bounds")
            area = sum(p[i][0] * p[(i + 1) % n][1] - p[(i + 1) % n][0] * p[i][1] for i in range(n))
            if abs(area) < 1e-9:
                raise ValueError("Polygon has zero area")
            for i in range(n):
                for j in range(i + 1, n):
                    if j == i + 1 or (i == 0 and j == n - 1):
                        continue
                    if intersects(p[i], p[(i + 1) % n], p[j], p[(j + 1) % n]):
                        raise ValueError("Self-intersecting polygon")
        for s in self.sensors:
            if not (0 <= s.x <= self.width and 0 <= s.y <= self.height):
                raise ValueError("Sensor out of bounds")
            if s.room_id is not None:
                if s.room_id not in rooms:
                    raise ValueError("Unknown room")
                if not contains(rooms[s.room_id].polygon, (s.x, s.y)):
                    raise ValueError("Sensor outside assigned room")
        return self


class Heatmap(StrictModel):
    temperature: tuple[float, float] = (18, 25)
    humidity: tuple[float, float] = (30, 70)

    @field_validator("temperature", mode="before")
    @classmethod
    def legacy_temperature_limits(cls, value):
        # Older preferences stored a manually configured comfort midpoint.
        if isinstance(value, (list, tuple)) and len(value) == 3:
            return value[0], value[2]
        return value

    @model_validator(mode="after")
    def ordered(self):
        if not self.temperature[0] < self.temperature[1] or not self.humidity[0] < self.humidity[1]:
            raise ValueError("Heatmap limits must increase")
        return self


class Preferences(StrictModel):
    language: Literal["cs", "en"] = "cs"
    theme: Literal["light", "dark", "system"] = "system"
    temperature_unit: Literal["C", "F"] = "C"
    push_enabled: bool = False
    heatmap: Heatmap = Field(default_factory=Heatmap)


class SystemSettings(StrictModel):
    sample_interval_seconds: int = Field(900, ge=10, le=86400)
    stale_after_seconds: int = Field(1800, ge=30, le=604800)


class RuleInput(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    sensor_id: str | None = None
    room_id: str | None = None
    metric: Literal["temperature", "humidity", "offline"]
    operator: Literal["above", "below"] = "above"
    threshold: float
    duration_seconds: int = Field(0, ge=0, le=604800)
    reset_threshold: float
    enabled: bool = True

    @model_validator(mode="after")
    def validate_rule(self):
        if bool(self.sensor_id) == bool(self.room_id):
            raise ValueError("Exactly one target required")
        if self.metric == "offline":
            if (
                self.operator != "above"
                or self.threshold <= 0
                or self.reset_threshold < 0
                or self.reset_threshold > self.threshold
            ):
                raise ValueError("Invalid offline thresholds")
        elif (
            self.operator == "above"
            and self.reset_threshold > self.threshold
            or self.operator == "below"
            and self.reset_threshold < self.threshold
        ):
            raise ValueError("Reset threshold must provide hysteresis")
        return self


class PushKeys(StrictModel):
    p256dh: str = Field(min_length=80, max_length=128, pattern=r"^[A-Za-z0-9_-]+=*$")
    auth: str = Field(min_length=20, max_length=32, pattern=r"^[A-Za-z0-9_-]+=*$")


class Subscription(StrictModel):
    endpoint: str = Field(max_length=2048)
    keys: PushKeys
    label: str = Field("", max_length=100)


class Unsubscribe(StrictModel):
    endpoint: str = Field(max_length=2048)
