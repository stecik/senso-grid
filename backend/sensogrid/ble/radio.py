"""Bounded parallel connections, one connection per address, exclusive scanning."""

import asyncio
from contextlib import asynccontextmanager

from .address import address_key


class BLERadio:
    def __init__(self, concurrency: int = 10):
        self.limit = concurrency
        self._slots = asyncio.Semaphore(concurrency)
        self._scan_lock = asyncio.Lock()
        self._addresses: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def read(self, address: str):
        key = address_key(address)
        lock = self._addresses.setdefault(key, asyncio.Lock())
        async with lock, self._slots:
            yield

    @asynccontextmanager
    async def scan(self):
        async with self._scan_lock:
            acquired = 0
            try:
                for _ in range(self.limit):
                    await self._slots.acquire()
                    acquired += 1
                yield
            finally:
                for _ in range(acquired):
                    self._slots.release()
