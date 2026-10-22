from copy import deepcopy

import test_api

client = test_api.client
logged = test_api.logged

PLAN = {
    "schema_version": 1,
    "id": "home",
    "name": "Home",
    "units": "m",
    "width": 10,
    "height": 8,
    "rooms": [{"id": "room-1", "name": "Living", "polygon": [[0, 0], [5, 0], [5, 8], [0, 8]]}],
    "sensors": [],
}


def test_atomic_import_assignments_stable_rooms(logged):
    sensor = logged.post("/api/sensors", json={"name": "Desk", "address": "AA:BB"}).json()
    plan = deepcopy(PLAN)
    plan["sensors"] = [{"sensor_id": sensor["id"], "room_id": "room-1", "x": 2, "y": 2}]
    assert logged.post("/api/floorplan/preview", json=plan).status_code == 200
    assert logged.get("/api/rooms").json() == []
    assert logged.get("/api/sensors").json()[0]["room_id"] is None
    assert logged.put("/api/floorplan", json=plan).status_code == 200
    assert logged.get("/api/sensors").json()[0]["room_id"] == "room-1"
    plan["rooms"][0]["name"] = "Renamed"
    assert logged.put("/api/floorplan", json=plan).status_code == 200
    assert logged.get("/api/rooms").json()[0]["id"] == "room-1"
    bad = deepcopy(plan)
    bad["sensors"][0]["sensor_id"] = "unknown"
    assert logged.put("/api/floorplan", json=bad).status_code == 422
    assert logged.get("/api/floorplan").json() == plan
    plan["rooms"] = []
    plan["sensors"][0]["room_id"] = None
    assert logged.put("/api/floorplan", json=plan).status_code == 200
    assert logged.get("/api/sensors").json()[0]["room_id"] is None
    assert logged.app.state.db.rooms(archived=True)[0] == {
        "id": "room-1",
        "name": "Renamed",
        "archived": 1,
    }


def test_reject_invalid_geometry_and_duplicates(logged):
    for polygon in (
        [[0, 0], [5, 5], [0, 5], [5, 0]],
        [[0, 0], [5, 0], [10, 0]],
        [[0, 0], [5, 0], [5, 0]],
        [[0, 0], [11, 0], [5, 5]],
        [[0, 0], [5, 0], [3, 0], [5, 5], [0, 5]],
    ):
        plan = deepcopy(PLAN)
        plan["rooms"][0]["polygon"] = polygon
        assert logged.post("/api/floorplan/preview", json=plan).status_code == 422
    plan = deepcopy(PLAN)
    plan["rooms"].append(deepcopy(plan["rooms"][0]))
    assert logged.put("/api/floorplan", json=plan).status_code == 422
    plan = deepcopy(PLAN)
    plan["sensors"] = [{"sensor_id": "unknown", "room_id": "room-1", "x": 8, "y": 2}]
    assert logged.put("/api/floorplan", json=plan).status_code == 422


def test_delete_sensor_clears_placement_and_preserves_rules(logged):
    sensor = logged.post("/api/sensors", json={"name": "Desk", "address": "AA:BB"}).json()
    plan = deepcopy(PLAN)
    plan["sensors"] = [{"sensor_id": sensor["id"], "room_id": "room-1", "x": 2, "y": 2}]
    assert logged.put("/api/floorplan", json=plan).status_code == 200
    rule = logged.post(
        "/api/alerts/rules",
        json={
            "name": "Warm",
            "sensor_id": sensor["id"],
            "metric": "temperature",
            "threshold": 25,
            "reset_threshold": 24,
        },
    ).json()
    assert logged.delete("/api/sensors/" + sensor["id"]).status_code == 200
    assert logged.get("/api/floorplan").json()["sensors"] == []
    assert not logged.get("/api/alerts/rules").json()[0]["enabled"]
    assert logged.get("/api/alerts/rules").json()[0]["id"] == rule["id"]


def test_patch_assignment_updates_existing_plan(logged):
    sensor = logged.post("/api/sensors", json={"name": "Desk", "address": "AA:BB"}).json()
    plan = deepcopy(PLAN)
    plan["sensors"] = [{"sensor_id": sensor["id"], "room_id": None, "x": 8, "y": 2}]
    assert logged.put("/api/floorplan", json=plan).status_code == 200
    assert (
        logged.patch("/api/sensors/" + sensor["id"], json={"room_id": "room-1"}).status_code == 200
    )
    placement = logged.get("/api/floorplan").json()["sensors"][0]
    assert placement["room_id"] == "room-1" and placement["x"] <= 5


def test_canvas_import_preview_and_apply_preserve_ids(logged):
    imported = {
        "schemaVersion": 1,
        "name": "My apartment",
        "units": "meters",
        "canvas": {"width": 5, "height": 8.7},
        "rooms": [
            {"id": "top-left", "name": "Room", "polygon": [[0, 0], [3.3, 0], [3.3, 2.4], [0, 2.4]]}
        ],
    }
    before = logged.get("/api/floorplan").json()
    response = logged.post("/api/floorplan/preview", json=imported)
    assert response.status_code == 200
    normalized = response.json()["plan"]
    assert normalized == {
        "schema_version": 1,
        "id": "home",
        "name": "My apartment",
        "units": "m",
        "width": 5,
        "height": 8.7,
        "rooms": imported["rooms"],
        "sensors": [],
    }
    assert logged.get("/api/floorplan").json() == before
    assert logged.put("/api/floorplan", json=normalized).status_code == 200
    assert logged.get("/api/floorplan/export").json() == normalized
    imported["rooms"][0]["polygon"][1][0] = 6
    assert logged.post("/api/floorplan/preview", json=imported).status_code == 422
    assert logged.get("/api/floorplan").json() == normalized
