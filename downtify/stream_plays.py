"""How often each not-downloaded song is played live, for auto-download.

``GET /api/stream/live`` relays a song that isn't in the library yet.
With *Download after N live plays* on (``auto_download_after_plays``),
the song is queued for download once it has been played live that
many times - by anyone, since the library is shared.

A play is a request that starts at the beginning of the audio (no
``Range`` or ``bytes=0-``); seeks and ``HEAD`` don't count, and plays
of the same video closer than :data:`MIN_SECONDS_BETWEEN_PLAYS` apart
count once (a browser may open the start of the stream twice). A
video queued once is never queued again by this counter.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from .sqlite_utils import connect_sqlite

#: Repeated starts of one video closer than this count as one play.
MIN_SECONDS_BETWEEN_PLAYS = 60

#: The highest threshold the setting takes (``0`` turns it off).
MAX_PLAYS_THRESHOLD = 100


def clamp_threshold(value: Any) -> int:
    """The setting as an int in ``[0, MAX_PLAYS_THRESHOLD]`` (0 = off)."""

    try:
        plays = int(value)
    except (TypeError, ValueError):
        return 0
    return min(MAX_PLAYS_THRESHOLD, max(0, plays))


def is_play_start(method: str, range_header: Optional[str]) -> bool:
    """Whether a live request starts a play (not a seek or a probe)."""

    if method.upper() != 'GET':
        return False
    if not range_header:
        return True
    return range_header.replace(' ', '').lower() in {'bytes=0-', 'bytes=0-1'}


class StreamPlays:
    """Live play counts per video id, in ``downtify_library.db``."""

    def __init__(self, db_path: str | Path) -> None:
        self._db = str(db_path)
        with self._connect() as conn:
            conn.execute(
                'CREATE TABLE IF NOT EXISTS stream_plays ('
                ' video_id TEXT PRIMARY KEY,'
                ' plays INTEGER NOT NULL DEFAULT 0,'
                ' last_play REAL NOT NULL DEFAULT 0,'
                ' queued INTEGER NOT NULL DEFAULT 0)'
            )

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self._db)

    def record(self, video_id: str, threshold: int) -> bool:
        """Count one play of *video_id*; ``True`` when it should be
        downloaded now (it just reached *threshold* and was never
        queued). The video is then marked as queued."""

        now = time.time()
        try:
            with self._connect() as conn:
                row = conn.execute(
                    'SELECT plays, last_play, queued FROM stream_plays'
                    ' WHERE video_id = ?',
                    (video_id,),
                ).fetchone()
                plays, last, queued = row or (0, 0.0, 0)
                if row and now - last < MIN_SECONDS_BETWEEN_PLAYS:
                    return False
                plays += 1
                due = bool(threshold) and not queued and plays >= threshold
                conn.execute(
                    'INSERT INTO stream_plays'
                    ' (video_id, plays, last_play, queued)'
                    ' VALUES (?, ?, ?, ?)'
                    ' ON CONFLICT(video_id) DO UPDATE SET'
                    ' plays = excluded.plays,'
                    ' last_play = excluded.last_play,'
                    ' queued = excluded.queued',
                    (video_id, plays, now, int(queued or due)),
                )
                return due
        except sqlite3.Error:
            logger.exception('Could not count a live play of {}', video_id)
            return False

    def plays(self, video_id: str) -> int:
        """How many live plays *video_id* has had."""

        with self._connect() as conn:
            row = conn.execute(
                'SELECT plays FROM stream_plays WHERE video_id = ?',
                (video_id,),
            ).fetchone()
        return int(row[0]) if row else 0
