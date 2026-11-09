"""Download slots shared fairly between accounts.

The "Parallel downloads" setting bounds how many downloads run at once
for the whole server. A plain :class:`asyncio.Semaphore` hands its free
slots out first come, first served, so one account queueing a
300-track playlist made every other account wait for all 300 tracks
before its single song could start.

:class:`FairSlots` keeps one FIFO line per owner (the account id) and
gives each free slot to the waiting owner running the fewest downloads,
ties going to the one served longest ago. An account's own songs keep
their order; a lone song from another account starts at the next free
slot. With a single owner it behaves like a FIFO semaphore.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
from collections import deque
from collections.abc import AsyncIterator, Hashable


class FairSlots:
    """At most *limit* holders at once, shared round-robin by owner."""

    def __init__(self, limit: int) -> None:
        self._limit = max(1, int(limit))
        self._active: dict[Hashable, int] = {}
        self._waiting: dict[Hashable, deque[asyncio.Future[None]]] = {}
        self._served: dict[Hashable, int] = {}
        self._turns = itertools.count()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def running(self) -> int:
        """Slots currently held."""
        return sum(self._active.values())

    @property
    def waiting(self) -> int:
        """Callers waiting for a slot."""
        return sum(len(line) for line in self._waiting.values())

    def resize(self, limit: int) -> None:
        """Change the limit in place; holders keep their slots.

        A lower limit lets the extra holders finish and starts nothing
        until the count drops under it; a higher one starts waiters
        right away.
        """
        self._limit = max(1, int(limit))
        self._wake()

    @contextlib.asynccontextmanager
    async def slot(self, owner: Hashable = 0) -> AsyncIterator[None]:
        """Hold one slot for *owner* for the duration of the block."""
        await self._acquire(owner)
        try:
            yield
        finally:
            self._release(owner)

    async def _acquire(self, owner: Hashable) -> None:
        if self.running < self._limit and not self._waiting:
            self._grant(owner)
            return
        waiter: asyncio.Future[None] = (
            asyncio.get_running_loop().create_future()
        )
        self._waiting.setdefault(owner, deque()).append(waiter)
        try:
            await waiter
        except asyncio.CancelledError:
            if waiter.done() and not waiter.cancelled():
                # Granted, then cancelled before running: hand it on.
                self._release(owner)
            else:
                self._forget(owner, waiter)
            raise

    def _grant(self, owner: Hashable) -> None:
        self._active[owner] = self._active.get(owner, 0) + 1
        self._served[owner] = next(self._turns)

    def _release(self, owner: Hashable) -> None:
        count = self._active.get(owner, 0) - 1
        if count > 0:
            self._active[owner] = count
        else:
            self._active.pop(owner, None)
        self._wake()

    def _forget(self, owner: Hashable, waiter: asyncio.Future[None]) -> None:
        line = self._waiting.get(owner)
        if line is None:
            return
        with contextlib.suppress(ValueError):
            line.remove(waiter)
        if not line:
            del self._waiting[owner]
        # Our place may have been the one blocking an idle slot.
        self._wake()

    def _next_owner(self) -> Hashable:
        return min(
            self._waiting,
            key=lambda o: (self._active.get(o, 0), self._served.get(o, -1)),
        )

    def _wake(self) -> None:
        while self._waiting and self.running < self._limit:
            owner = self._next_owner()
            line = self._waiting[owner]
            waiter = line.popleft()
            if not line:
                del self._waiting[owner]
            if waiter.done():
                continue
            self._grant(owner)
            waiter.set_result(None)
