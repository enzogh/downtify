"""FairSlots: "Parallel downloads" slots shared fairly between accounts."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from downtify import api
from downtify.fair_slots import FairSlots


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def _start(
    slots: FairSlots,
    owner: Any,
    name: str,
    started: list[str],
    gate: asyncio.Event,
) -> asyncio.Task[None]:
    async def job() -> None:
        async with slots.slot(owner):
            started.append(name)
            await gate.wait()

    return asyncio.ensure_future(job())


def test_lone_song_jumps_a_long_playlist():
    async def scenario() -> list[str]:
        slots = FairSlots(2)
        started: list[str] = []
        gates = {f'a{i}': asyncio.Event() for i in range(10)}
        gates['b0'] = asyncio.Event()
        tasks = [
            _start(slots, 'alice', f'a{i}', started, gates[f'a{i}'])
            for i in range(10)
        ]
        await _settle()
        tasks.append(_start(slots, 'bob', 'b0', started, gates['b0']))
        await _settle()
        assert started == ['a0', 'a1']
        gates['a0'].set()
        await _settle()
        for gate in gates.values():
            gate.set()
        await asyncio.gather(*tasks)
        return started

    started = asyncio.run(scenario())
    # Bob's song takes the first slot Alice frees.
    assert started[:3] == ['a0', 'a1', 'b0']
    # Alice's own songs keep their order.
    assert [s for s in started if s.startswith('a')] == [
        f'a{i}' for i in range(10)
    ]


def test_owners_alternate_when_both_have_a_backlog():
    async def scenario() -> list[str]:
        slots = FairSlots(1)
        started: list[str] = []
        release = asyncio.Event()
        tasks = [
            _start(slots, owner, f'{owner}{i}', started, release)
            for owner in ('a', 'b')
            for i in range(3)
        ]
        await _settle()
        release.set()
        await asyncio.gather(*tasks)
        return started

    assert asyncio.run(scenario()) == ['a0', 'b0', 'a1', 'b1', 'a2', 'b2']


def test_never_more_than_the_limit():
    async def scenario() -> int:
        slots = FairSlots(3)
        peak = 0

        async def job(owner: int) -> None:
            nonlocal peak
            async with slots.slot(owner):
                peak = max(peak, slots.running)
                await asyncio.sleep(0)

        await asyncio.gather(*(job(i % 4) for i in range(40)))
        assert slots.running == 0
        assert slots.waiting == 0
        return peak

    assert asyncio.run(scenario()) == 3


def test_resize_up_starts_waiters_and_down_holds_new_ones():
    async def scenario() -> None:
        slots = FairSlots(1)
        started: list[str] = []
        gate = asyncio.Event()
        tasks = [_start(slots, 'a', f'a{i}', started, gate) for i in range(4)]
        await _settle()
        assert started == ['a0']
        slots.resize(3)
        await _settle()
        assert started == ['a0', 'a1', 'a2']
        slots.resize(1)
        gate.set()
        await asyncio.gather(*tasks)
        assert started == ['a0', 'a1', 'a2', 'a3']
        assert slots.running == 0

    asyncio.run(scenario())


def test_cancelled_waiter_gives_its_place_back():
    async def scenario() -> None:
        slots = FairSlots(1)
        started: list[str] = []
        gate = asyncio.Event()
        first = _start(slots, 'a', 'a0', started, gate)
        await _settle()
        cancelled = _start(slots, 'b', 'b0', started, gate)
        last = _start(slots, 'c', 'c0', started, gate)
        await _settle()
        cancelled.cancel()
        await _settle()
        assert slots.waiting == 1
        gate.set()
        await asyncio.gather(first, last)
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        assert started == ['a0', 'c0']
        assert slots.running == 0

    asyncio.run(scenario())


def test_cancelled_right_after_its_grant_releases_the_slot():
    async def scenario() -> None:
        slots = FairSlots(1)
        started: list[str] = []
        gate = asyncio.Event()
        gate.set()
        release = asyncio.Event()
        tasks: dict[str, asyncio.Task[None]] = {}

        async def holder() -> None:
            async with slots.slot('a'):
                await release.wait()
            # The slot just went to b0: cancel it before it can run.
            tasks['b0'].cancel()

        held = asyncio.ensure_future(holder())
        await _settle()
        tasks['b0'] = _start(slots, 'b', 'b0', started, gate)
        tasks['c0'] = _start(slots, 'c', 'c0', started, gate)
        await _settle()
        release.set()
        await held
        await tasks['c0']
        with pytest.raises(asyncio.CancelledError):
            await tasks['b0']
        assert started == ['c0']
        assert slots.running == 0

    asyncio.run(scenario())


def test_run_download_takes_the_slot_of_its_account(monkeypatch):
    slots = FairSlots(2)
    monkeypatch.setattr(api.state, 'download_semaphore', slots)

    async def scenario() -> None:
        async with api._download_slot(7), api._download_slot(8):
            assert slots.running == 2
        assert slots.running == 0

    asyncio.run(scenario())


def test_no_slots_configured_runs_unbounded(monkeypatch):
    monkeypatch.setattr(api.state, 'download_semaphore', None)

    async def scenario() -> None:
        async with api._download_slot(1):
            pass

    asyncio.run(scenario())
