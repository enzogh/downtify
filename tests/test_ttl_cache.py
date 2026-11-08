"""The in-memory cache behind repeated YouTube Music lookups."""

from __future__ import annotations

from downtify.ttl_cache import TTLCache


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_values_expire_after_their_ttl():
    clock = Clock()
    cache: TTLCache[str] = TTLCache(10, clock=clock)
    cache.set('a', 'mix')

    clock.now = 9.9
    assert cache.get('a') == 'mix'
    clock.now = 10
    assert cache.get('a') is None


def test_the_least_recently_used_goes_first():
    cache: TTLCache[int] = TTLCache(60, max_entries=2)
    cache.set('a', 1)
    cache.set('b', 2)
    assert cache.get('a') == 1
    cache.set('c', 3)

    assert cache.get('b') is None
    assert cache.get('a') == 1
    assert cache.get('c') == 3


def test_clear():
    cache: TTLCache[int] = TTLCache(60)
    cache.set('a', 1)
    cache.clear()
    assert cache.get('a') is None
