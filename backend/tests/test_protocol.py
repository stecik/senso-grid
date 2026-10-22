import pytest
from sensogrid.ble.protocol import FrameParser, decode_measurement, encode_frame


def test_real_sensor_frame():
    frames = FrameParser().feed(bytes.fromhex("aaaaa2000600e802080100ef55"))
    assert len(frames) == 1
    assert decode_measurement(frames[0]) == {
        "temperature": 23.2,
        "humidity": 52.0,
        "battery_raw": 1,
        "display_unit": "C",
    }


def test_fragmentation_coalescing_and_signed_temperature():
    parser = FrameParser()
    packet = encode_frame(0xA2, bytes.fromhex("ffcc01c80300"))
    assert parser.feed(b"noise" + packet[:1]) == []
    assert parser.feed(packet[1:7]) == []
    frames = parser.feed(packet[7:] + packet)
    assert len(frames) == 2
    assert decode_measurement(frames[0])["temperature"] == -5.2
    assert decode_measurement(frames[1])["humidity"] == 45.6


def test_invalid_checksum_tail_and_large_length_recover():
    good = encode_frame(0xA2, bytes.fromhex("00e802080100"))
    corrupt = bytearray(good)
    corrupt[-2] ^= 1
    bad_tail = bytearray(good)
    bad_tail[-1] = 0
    parser = FrameParser()
    frames = parser.feed(bytes.fromhex("aaaaa2ffff") + corrupt + bad_tail + good)
    assert len(frames) == 1
    assert decode_measurement(frames[0])["temperature"] == 23.2
    assert parser.invalid_frames >= 3


def test_query_and_invalid_payload():
    assert encode_frame(0xA2, bytes.fromhex("01")).hex() == "aaaaa2000101f855"
    with pytest.raises(ValueError):
        decode_measurement(FrameParser().feed(encode_frame(0xA2, bytes.fromhex("00")))[0])
    with pytest.raises(ValueError):
        decode_measurement(FrameParser().feed(encode_frame(0xA2, bytes.fromhex("00e827100100")))[0])
