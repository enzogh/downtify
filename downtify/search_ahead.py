"""Search the next songs of a batch while the current ones download.

Before its audio download starts, every song spends a few seconds on
metadata enrichment (the per-track Spotify / Deezer lookup) and on the
YouTube Music search. In a playlist or an album those seconds used to
come one after another, each inside a download slot. :class:`SearchAhead`
runs that preparation for the next few songs of a batch on a small pool
of its own, so a song that gets a slot can start downloading at once.

It is only a head start: a song that finds no prepared result (not
searched yet, the search failed, the settings changed meanwhile) simply
searches by itself, exactly as before.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Hashable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Optional

#: Searches running at once for the whole server. Kept low: these are
#: extra YouTube Music requests, and a burst of them is what gets a
#: server rate-limited.
SEARCH_AHEAD_WORKERS = 2

#: Songs of a batch searched beyond the ones already downloading.
SEARCH_AHEAD_DEPTH = 2

SEARCH_AHEAD_EXECUTOR = ThreadPoolExecutor(
    max_workers=SEARCH_AHEAD_WORKERS,
    thread_name_prefix='downtify-search-ahead',
)


@dataclass(frozen=True)
class PreparedSong:
    """What a download would have looked up for a song before fetching."""

    #: The song after enrichment (``enrich_from_match`` included), the
    #: one the download tags.
    song: dict[str, Any]
    video_id: str
    #: The YouTube Music result (``None`` for a plain YouTube match).
    match: Optional[dict[str, Any]]
    provider: str
    #: The audio provider order it was searched under.
    providers: tuple[str, ...]


def search_key(song: dict[str, Any]) -> Optional[Hashable]:
    """The key a song's prepared result is filed under (``None``: none)."""

    song_id = str(song.get('song_id') or '')
    if not song_id:
        return None
    return (
        str(song.get('source') or ''),
        song_id,
        str(song.get('name') or ''),
    )


class SearchAhead:
    """Prepared songs, by :func:`search_key`."""

    def __init__(self, executor: Optional[ThreadPoolExecutor] = None) -> None:
        self._executor = executor or SEARCH_AHEAD_EXECUTOR
        self._entries: dict[Hashable, Future[Optional[PreparedSong]]] = {}
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def start(
        self,
        song: dict[str, Any],
        prepare: Callable[[dict[str, Any]], Optional[PreparedSong]],
    ) -> bool:
        """Queue ``prepare(song)``; whether it was queued (once per song)."""

        key = search_key(song)
        if key is None:
            return False
        with self._lock:
            if key in self._entries:
                return False
            self._entries[key] = self._executor.submit(prepare, song)
        return True

    def take(self, song: dict[str, Any]) -> Optional[PreparedSong]:
        """The prepared result for *song*, used up; ``None`` when none.

        A search already running is waited for (it would be repeated
        otherwise); one still queued is called off, and the song searches
        by itself right away instead of waiting its turn.
        """

        key = search_key(song)
        if key is None:
            return None
        with self._lock:
            future = self._entries.pop(key, None)
        if future is None or future.cancel():
            return None
        try:
            return future.result()
        except Exception:
            return None

    def discard(self, songs: list[dict[str, Any]]) -> None:
        """Forget what was prepared for *songs* and was never used."""

        with self._lock:
            for song in songs:
                key = search_key(song)
                future = self._entries.pop(key, None) if key else None
                if future is not None:
                    future.cancel()
