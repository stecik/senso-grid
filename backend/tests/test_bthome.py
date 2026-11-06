import pytest
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData


def test_real_atc_climate_and_auxiliary_frames() -> None:
    from sensogrid.ble.bthome import decode_payload

    assert decode_payload(bytes.fromhex("400021015a02630903dd10")) == {
        "packet_id": 33,
        "battery_percent": 90,
        "temperature": 24.03,
        "humidity": 43.17,
    }
    assert decode_payload(bytes.fromhex("4000200c6d0b10001101")) == {
        "packet_id": 32,
        "battery_voltage": 2.925,
    }
    assert decode_payload(bytes.fromhex("4002c7fe03a00f")) == {
        "temperature": -3.13,
        "humidity": 40.0,
    }


@pytest.mark.parametrize(
    "payload", ["", "41", "20", "4002", "400263", "400165", "400327", "4003ffff"]
)
def test_invalid_or_encrypted_data_is_rejected(payload: str) -> None:
    from sensogrid.ble.bthome import decode_payload

    with pytest.raises(ValueError):
        decode_payload(bytes.fromhex(payload))


def test_unknown_object_stops_parsing_without_guessing_its_length() -> None:
    from sensogrid.ble.bthome import decode_payload

    assert decode_payload(bytes.fromhex("40015aff026309")) == {"battery_percent": 90}


def advertisement(driver: object, payload: str, address: str = "02:00:00:5E:00:01") -> None:
    from sensogrid.ble.bthome import BTHOME_UUID, BTHomeDriver

    assert isinstance(driver, BTHomeDriver)
    driver.receive(
        BLEDevice(address, "ATC_5E0001", None),
        AdvertisementData(
            local_name=None,
            rssi=-57,
            service_data={BTHOME_UUID: bytes.fromhex(payload)},
            manufacturer_data={},
            service_uuids=[],
            tx_power=None,
            platform_data=(),
        ),
    )


def test_auxiliary_and_duplicate_packets_do_not_refresh_climate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sensogrid.ble.bthome import BTHomeDriver

    clock = [100.0]
    monkeypatch.setattr("sensogrid.ble.bthome.time.monotonic", lambda: clock[0])
    driver = BTHomeDriver()
    advertisement(driver, "400021015a02630903dd10")
    first = driver.latest("02-00-00-5e-00-01", max_age=30)
    assert first and first["temperature"] == 24.03
    clock[0] += 10
    advertisement(driver, "4000200c6d0b10001101")
    advertisement(driver, "400021015a02630903dd10")
    second = driver.latest("02:00:00:5E:00:01", max_age=30)
    assert second and second["timestamp"] == first["timestamp"]
    assert second["battery_percent"] == 90
    assert second["battery_voltage"] == 2.925
    clock[0] += 21
    assert driver.latest("02:00:00:5E:00:01", max_age=30) is None
    advertisement(driver, "400000015a02630903dd10")
    assert driver.latest("02:00:00:5E:00:01", max_age=30) is not None


def test_auxiliary_only_or_malformed_devices_have_no_climate() -> None:
    from sensogrid.ble.bthome import BTHomeDriver

    driver = BTHomeDriver()
    advertisement(driver, "4000200c6d0b10001101")
    advertisement(driver, "4002")
    assert driver.latest("02:00:00:5E:00:01", max_age=30) is None


def test_replayed_alternating_partial_frames_do_not_refresh_climate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sensogrid.ble.bthome import BTHomeDriver

    clock = [100.0]
    monkeypatch.setattr("sensogrid.ble.bthome.time.monotonic", lambda: clock[0])
    driver = BTHomeDriver()
    advertisement(driver, "400021026309")
    advertisement(driver, "40002103dd10")
    assert driver.latest("02:00:00:5E:00:01")
    clock[0] += 100
    advertisement(driver, "400021026309")
    advertisement(driver, "40002103dd10")
    assert driver.latest("02:00:00:5E:00:01", max_age=30) is None
