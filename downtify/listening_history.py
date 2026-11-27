"""Each user's listening history: one row per song played, with how long
it played and whether it was skipped.

It is what the recommendations learn from (``frontend/src/lib/
recommender.js``): every device of an account reports its plays here, so
the suggestions follow the person rather than the browser. Library songs
and streamed songs alike are kept - a streamed song played to the end is
as telling as a downloaded one, and a skip says what not to suggest.

Rows are kept for :data:`KEEP_DAYS` and at most :data:`MAX_ROWS` per user;
a ``play_id`` is counted once per user, so a device that retries a lost
upload doesn't count a play twice. Lives in the library database next to
the Discover tables (:class:`downtify.discover.DiscoverStore` owns it).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .db.config import Dialect
from .db.core import Database

#: How long a play is remembered.
KEEP_DAYS = 365
#: The most plays kept per user (the oldest go first).
MAX_ROWS = 20000
#: The most plays one upload may carry.
MAX_BATCH = 500

_SOURCES = {'library', 'stream'}
_COLUMNS = (
    'play_id',
    'played_at',
    'artist',
    'title',
    'album',
    'file',
    'video_id',
    'source',
    'played_s',
    'duration_s',
    'skipped',
    'context',
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: Any, limit: int) -> str:
    return str(value or '').strip()[:limit]


def _seconds(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(number) or number < 0:
        return 0.0
    return round(min(number, 24 * 3600), 1)


def _played_at(value: Any, now: datetime) -> Optional[str]:
    """ISO 8601 UTC time of a play: ``None`` when it can't be read, is in
    the future or older than :data:`KEEP_DAYS`."""

    if isinstance(value, (int, float)):
        # Milliseconds since the epoch, as a browser's Date.now().
        try:
            when = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        try:
            when = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError:
            return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    if when > now + timedelta(minutes=5):
        return None
    if when < now - timedelta(days=KEEP_DAYS):
        return None
    return when.astimezone(timezone.utc).isoformat()


def clean_play(raw: Any, now: Optional[datetime] = None) -> Optional[dict]:
    """One reported play as a row, or ``None`` when it isn't usable (no
    id, no artist or title, an unreadable time)."""

    if not isinstance(raw, dict):
        return None
    now = now or _now()
    play_id = _text(raw.get('play_id'), 64)
    artist = _text(raw.get('artist'), 300)
    title = _text(raw.get('title'), 300)
    played_at = _played_at(raw.get('played_at'), now)
    if not play_id or not artist or not title or not played_at:
        return None
    source = _text(raw.get('source'), 16)
    return {
        'play_id': play_id,
        'played_at': played_at,
        'artist': artist,
        'title': title,
        'album': _text(raw.get('album'), 300),
        'file': _text(raw.get('file'), 1024),
        'video_id': _text(raw.get('video_id'), 64),
        'source': source if source in _SOURCES else 'library',
        'played_s': _seconds(raw.get('played_s')),
        'duration_s': _seconds(raw.get('duration_s')),
        'skipped': 1 if raw.get('skipped') else 0,
        'context': _text(raw.get('context'), 32),
    }


class ListeningHistory:
    """The plays table, on the library database."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._init_db()

    def _init_db(self) -> None:
        # PostgreSQL gets its schema from the migrations (0005).
        if self.db.dialect is not Dialect.SQLITE:
            return
        with self.db.connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS listening_history (
                    user_id INTEGER NOT NULL DEFAULT 0,
                    play_id TEXT NOT NULL,
                    played_at TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    title TEXT NOT NULL,
                    album TEXT NOT NULL DEFAULT '',
                    file TEXT NOT NULL DEFAULT '',
                    video_id TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'library',
                    played_s REAL NOT NULL DEFAULT 0,
                    duration_s REAL NOT NULL DEFAULT 0,
                    skipped INTEGER NOT NULL DEFAULT 0,
                    context TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (user_id, play_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_listening_history_user_at
                    ON listening_history (user_id, played_at)
            """)

    def record(
        self,
        plays: Iterable[Any],
        user_id: int = 0,
        now: Optional[datetime] = None,
    ) -> int:
        """Keep the usable *plays* of *user_id*; returns how many were
        new (a play already recorded is ignored)."""

        now = now or _now()
        rows = [
            row
            for row in (
                clean_play(raw, now) for raw in list(plays)[:MAX_BATCH]
            )
            if row is not None
        ]
        if not rows:
            return 0
        uid = int(user_id or 0)
        columns = ', '.join(('user_id', *_COLUMNS))
        marks = ', '.join('?' for _ in range(len(_COLUMNS) + 1))
        added = 0
        with self.db.connect() as conn:
            for row in rows:
                cur = conn.execute(
                    f'INSERT INTO listening_history ({columns}) '
                    f'VALUES ({marks}) '
                    'ON CONFLICT(user_id, play_id) DO NOTHING',
                    (uid, *(row[name] for name in _COLUMNS)),
                )
                added += max(cur.rowcount, 0)
            self._prune(conn, uid, now)
        return added

    @staticmethod
    def _prune(conn: Any, uid: int, now: datetime) -> None:
        since = (now - timedelta(days=KEEP_DAYS)).isoformat()
        conn.execute(
            'DELETE FROM listening_history WHERE user_id = ? '
            'AND played_at < ?',
            (uid, since),
        )
        row = conn.execute(
            'SELECT played_at FROM listening_history WHERE user_id = ? '
            'ORDER BY played_at DESC LIMIT 1 OFFSET ?',
            (uid, MAX_ROWS),
        ).fetchone()
        if row is not None:
            conn.execute(
                'DELETE FROM listening_history WHERE user_id = ? '
                'AND played_at <= ?',
                (uid, row['played_at']),
            )

    def plays(
        self,
        user_id: int = 0,
        days: int = 90,
        limit: int = 5000,
        now: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        """*user_id*'s plays of the last *days*, newest first."""

        now = now or _now()
        since = (now - timedelta(days=max(1, int(days)))).isoformat()
        with self.db.connect() as conn:
            rows = conn.execute(
                f'SELECT {", ".join(_COLUMNS)} FROM listening_history '
                'WHERE user_id = ? AND played_at >= ? '
                'ORDER BY played_at DESC LIMIT ?',
                (int(user_id or 0), since, max(1, int(limit))),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item['skipped'] = bool(item['skipped'])
            out.append(item)
        return out

    def clear(self, user_id: Optional[int] = None) -> int:
        """Forget *user_id*'s plays (everyone's when ``None``)."""

        with self.db.connect() as conn:
            if user_id is None:
                return conn.execute('DELETE FROM listening_history').rowcount
            return conn.execute(
                'DELETE FROM listening_history WHERE user_id = ?',
                (int(user_id),),
            ).rowcount
