import asyncio

import pytest
from sensogrid.ble.radio import BLERadio


@pytest.mark.asyncio
async def test_same_mac_never_connects_twice_at_once() -> None:
    radio = BLERadio(10)
    entered = False

    async def second() -> None:
        nonlocal entered
        async with radio.read("aa-bb-cc-dd-ee-ff"):
            entered = True

    async with radio.read("AA:BB:CC:DD:EE:FF"):
        task = asyncio.create_task(second())
        await asyncio.sleep(0)
        assert not entered
    await asyncio.wait_for(task, 1)
    assert entered


@pytest.mark.asyncio
async def test_scan_waits_for_connections_and_blocks_new_connections() -> None:
    radio = BLERadio(2)
    scanning = asyncio.Event()
    finish = asyncio.Event()

    async def scanner() -> None:
        async with radio.scan():
            scanning.set()
            await finish.wait()

    async def reader() -> None:
        async with radio.read("BB"):
            assert not scanning.is_set() or finish.is_set()

    async with radio.read("AA"):
        scan = asyncio.create_task(scanner())
        await asyncio.sleep(0)
        assert not scanning.is_set()
    await asyncio.wait_for(scanning.wait(), 1)
    read = asyncio.create_task(reader())
    await asyncio.sleep(0)
    assert not read.done()
    finish.set()
    await asyncio.gather(scan, read)


@pytest.mark.asyncio
async def test_cancelling_waiting_scan_restores_all_connection_slots() -> None:
    radio = BLERadio(2)
    async with radio.read("AA"):
        scan = asyncio.create_task(radio.scan().__aenter__())
        await asyncio.sleep(0)
        scan.cancel()
        await asyncio.gather(scan, return_exceptions=True)

    async def both() -> None:
        async with radio.read("AA"), radio.read("BB"):
            pass

    await asyncio.wait_for(both(), 1)
