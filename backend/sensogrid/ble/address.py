"""Stable BLE identity independent of MAC case and separators."""

import re


def address_key(address: str) -> str:
    return re.sub(r"[:\-\s]", "", address).upper()


def canonical_address(address: str) -> str:
    key = address_key(address)
    if re.fullmatch(r"[0-9A-F]{12}", key):
        return ":".join(key[index : index + 2] for index in range(0, 12, 2))
    return address.strip().upper()
