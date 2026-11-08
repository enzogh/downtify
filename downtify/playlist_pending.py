"""Songs added to a Library playlist before they are downloaded.

A Library playlist is an M3U of library files, so a song found on
Spotify / YouTube Music can't be one of its lines until its file exists.
Adding such a song puts it here instead, and queues its download: the
playlist page lists it right away (it plays streamed meanwhile), and the
moment its download ends - or the queue finds it already in the library
- :func:`downtify.api.claim_pending_playlist_songs` writes its file at
the end of the playlist and drops the row.

Rows are keyed like :mod:`downtify.playlist_hidden`'s: by the playlist's
sanitized, casefolded M3U stem, and by the song's ``song_id`` (the id the
download queue keys its jobs by).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import m3u
from .sqlite_utils import connect_sqlite

#: Most songs one request may add to a playlist this way.
MAX_PENDING_PER_EDIT = 500
#: The song fields kept: what the page shows and the queue needs again.
_SONG_FIELDS = (
    'song_id',
    'name',
    'artist',
    'artists',
    'album_name',
    'album_artist',
    'cover_url',
    'duration',
    'url',
    'explicit',
    'youtube_id',
    'isrc',
)


def pending_key(name: Any) -> str:
    """The stored key of a playlist: its M3U stem, case-insensitively."""

    text = str(name or '').strip()
    return m3u.sanitize_playlist_name(text).casefold() if text else ''


def song_key(song: dict[str, Any]) -> str:
    """The id a pending song is known by (the download job's key)."""

    return str(song.get('song_id') or song.get('url') or '').strip()


def _present(value: Any) -> bool:
    # Lists (``artists``) are kept as they are: only missing and blank
    # values are left out.
    return value is not None and not (isinstance(value, str) and not value)


def _slim(song: dict[str, Any]) -> dict[str, Any]:
    return {
        field: song[field]
        for field in _SONG_FIELDS
        if _present(song.get(field))
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PlaylistPendingSongs:
    """Every playlist's not-yet-downloaded songs, in
    ``downtify_library.db``."""

    def __init__(self, db_path: Path) -> None:
        self._path = str(db_path)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self._path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS playlist_pending_songs (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    playlist TEXT NOT NULL,
                    playlist_name TEXT NOT NULL,
                    song_id TEXT NOT NULL,
                    song TEXT NOT NULL,
                    user_id INTEGER NOT NULL DEFAULT 0,
                    added_at TEXT NOT NULL,
                    UNIQUE (playlist, song_id)
                )
            """)
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_playlist_pending_song '
                'ON playlist_pending_songs (song_id)'
            )

    def add(
        self,
        name: str,
        songs: Iterable[dict[str, Any]],
        *,
        user_id: int = 0,
    ) -> list[dict[str, Any]]:
        """Remember *songs* for playlist *name*; returns the ones that
        were new to it (a song already waiting there keeps its place)."""

        key = pending_key(name)
        if not key:
            return []
        added: list[dict[str, Any]] = []
        with self._lock, self._connect() as conn:
            for song in songs:
                if not isinstance(song, dict):
                    continue
                sid = song_key(song)
                if not sid:
                    continue
                slim = {**_slim(song), 'song_id': sid}
                cursor = conn.execute(
                    'INSERT OR IGNORE INTO playlist_pending_songs '
                    '(playlist, playlist_name, song_id, song, user_id, '
                    'added_at) VALUES (?, ?, ?, ?, ?, ?)',
                    (
                        key,
                        str(name).strip(),
                        sid,
                        json.dumps(slim, default=str),
                        int(user_id or 0),
                        _now_iso(),
                    ),
                )
                if cursor.rowcount:
                    added.append(slim)
        return added

    def songs(self, name: str) -> list[dict[str, Any]]:
        """Playlist *name*'s waiting songs, first added first, each with
        ``added_at``."""

        key = pending_key(name)
        if not key:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT song, added_at FROM playlist_pending_songs '
                'WHERE playlist = ? ORDER BY seq',
                (key,),
            ).fetchall()
        found: list[dict[str, Any]] = []
        for raw, added_at in rows:
            try:
                song = json.loads(raw)
            except ValueError:
                continue
            if isinstance(song, dict):
                found.append({**song, 'added_at': added_at})
        return found

    def remove(self, name: str, song_ids: Iterable[str]) -> int:
        """Take songs out of playlist *name*'s waiting list."""

        key = pending_key(name)
        ids = [str(sid).strip() for sid in song_ids if str(sid).strip()]
        if not key or not ids:
            return 0
        removed = 0
        with self._lock, self._connect() as conn:
            for sid in ids:
                removed += conn.execute(
                    'DELETE FROM playlist_pending_songs '
                    'WHERE playlist = ? AND song_id = ?',
                    (key, sid),
                ).rowcount
        return removed

    def claim(self, *song_ids: str) -> list[str]:
        """The playlists waiting on any of *song_ids* (a job's
        ``song_id`` and its ``url``; their names as added), which stop
        waiting: the caller now writes the file into them."""

        ids = list(dict.fromkeys(str(sid or '').strip() for sid in song_ids))
        ids = [sid for sid in ids if sid]
        if not ids:
            return []
        marks = ','.join('?' * len(ids))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                'SELECT playlist_name FROM playlist_pending_songs '
                f'WHERE song_id IN ({marks}) ORDER BY seq',
                ids,
            ).fetchall()
            conn.execute(
                f'DELETE FROM playlist_pending_songs WHERE song_id IN ({marks})',
                ids,
            )
        return list(dict.fromkeys(str(row[0]) for row in rows))

    def rename(self, old: str, new: str) -> None:
        """Follow a renamed playlist."""

        old_key, new_key = pending_key(old), pending_key(new)
        if not old_key or not new_key or old_key == new_key:
            return
        with self._lock, self._connect() as conn:
            conn.execute(
                'UPDATE OR IGNORE playlist_pending_songs '
                'SET playlist = ?, playlist_name = ? WHERE playlist = ?',
                (new_key, str(new).strip(), old_key),
            )
            conn.execute(
                'DELETE FROM playlist_pending_songs WHERE playlist = ?',
                (old_key,),
            )

    def drop(self, name: str) -> None:
        """Forget a deleted playlist's waiting songs."""

        key = pending_key(name)
        if not key:
            return
        with self._lock, self._connect() as conn:
            conn.execute(
                'DELETE FROM playlist_pending_songs WHERE playlist = ?',
                (key,),
            )
