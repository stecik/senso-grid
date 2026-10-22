"""LT thermometer framing, verified against LT_7506 hardware."""

import struct
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Frame:
    command: int
    payload: bytes


def encode_frame(command: int, payload: bytes) -> bytes:
    if not 0 <= command <= 255 or len(payload) > 4096:
        raise ValueError("Invalid command or payload size")
    head = b"\xaa\xaa" + bytes([command]) + len(payload).to_bytes(2, "big") + payload
    return head + bytes([sum(head) & 255, 0x55])


class FrameParser:
    def __init__(self, max_payload: int = 4096) -> None:
        self.buffer = bytearray()
        self.max_payload = max_payload
        self.invalid_frames = 0

    def feed(self, data: bytes) -> list[Frame]:
        self.buffer.extend(data)
        frames = []
        while len(self.buffer) >= 2:
            pos = self.buffer.find(b"\xaa\xaa")
            if pos < 0:
                self.buffer[:] = self.buffer[-1:] if self.buffer[-1] == 0xAA else b""
                break
            if pos:
                del self.buffer[:pos]
            if len(self.buffer) < 5:
                break
            length = int.from_bytes(self.buffer[3:5], "big")
            if length > self.max_payload:
                self.invalid_frames += 1
                del self.buffer[0]
                continue
            size = length + 7
            if len(self.buffer) < size:
                break
            packet = bytes(self.buffer[:size])
            if packet[-1] != 0x55 or (sum(packet[:-2]) & 255) != packet[-2]:
                self.invalid_frames += 1
                del self.buffer[0]
                continue
            frames.append(Frame(packet[2], packet[5:-2]))
            del self.buffer[:size]
        return frames


def decode_measurement(frame: Frame) -> dict:
    if frame.command != 0xA2 or len(frame.payload) != 6:
        raise ValueError("Expected six-byte A2 measurement")
    temperature, humidity, battery, unit = struct.unpack(">hHBB", frame.payload)
    if humidity > 1000 or unit not in (0, 1):
        raise ValueError("Invalid humidity or display unit")
    return {
        "temperature": temperature / 10,
        "humidity": humidity / 10,
        "battery_raw": battery,
        "display_unit": "C" if unit == 0 else "F",
    }
