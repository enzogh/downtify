"""Public links to one song, like Spotify's *Share → Copy link*.

A signed-in user makes a link for a song; anyone who has the link can
open ``/s/<token>`` and listen to it (with its cover, title and artist)
without signing in - and nothing else on the server. The song is a
library file (``kind`` ``file``) or one that isn't downloaded
(``stream``): a YouTube video relayed live, like the web player streams
a search result, with the title, artist and cover saved with the link. A link
belongs to the user who made it: they (or an admin) can revoke it, and
one user asking twice for the same song gets the same link back.

A link follows its song like the other per-file tables (see
``api.rekey_file_owners`` / ``api.drop_file_owners``): a rewritten file
keeps its link, a deleted one takes it with it. The admin's *Allow
public song links* setting (``allow_song_links``) turns every link off
at once, without forgetting them.
"""

from __future__ import annotations

import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .sqlite_utils import connect_sqlite

#: What a token looks like - also what ``/s/<token>`` accepts, so a
#: malformed one is a 404 without touching the database.
TOKEN_PATTERN = re.compile(r'^[A-Za-z0-9_-]{8,64}$')


def _norm_path(path: str) -> str:
    return str(path or '').replace('\\', '/').strip()


def valid_token(token: str) -> bool:
    return bool(TOKEN_PATTERN.match(str(token or '')))


FILE = 'file'
STREAM = 'stream'


@dataclass(frozen=True)
class StreamSong:
    """What a ``stream`` link plays and shows."""

    video_id: str
    title: str
    artist: str = ''
    album: str = ''
    duration: float = 0
    cover_url: str = ''
    explicit: bool = False


@dataclass(frozen=True)
class SongLink:
    token: str
    path: str
    content_key: str
    user_id: int
    created_at: int
    kind: str = FILE
    song: Optional[StreamSong] = None


#: Columns added after the first release (``song_links`` already existed).
_ADDED_COLUMNS = {
    'kind': "TEXT NOT NULL DEFAULT 'file'",
    'video_id': "TEXT NOT NULL DEFAULT ''",
    'title': "TEXT NOT NULL DEFAULT ''",
    'artist': "TEXT NOT NULL DEFAULT ''",
    'album': "TEXT NOT NULL DEFAULT ''",
    'duration': 'REAL NOT NULL DEFAULT 0',
    'cover_url': "TEXT NOT NULL DEFAULT ''",
    'explicit': 'INTEGER NOT NULL DEFAULT 0',
}


def _row(row: sqlite3.Row) -> SongLink:
    kind = str(row['kind'] or FILE)
    song = None
    if kind == STREAM:
        song = StreamSong(
            video_id=str(row['video_id'] or ''),
            title=str(row['title'] or ''),
            artist=str(row['artist'] or ''),
            album=str(row['album'] or ''),
            duration=float(row['duration'] or 0),
            cover_url=str(row['cover_url'] or ''),
            explicit=bool(row['explicit']),
        )
    return SongLink(
        token=str(row['token']),
        path=str(row['path']),
        content_key=str(row['content_key'] or ''),
        user_id=int(row['user_id'] or 0),
        created_at=int(row['created_at'] or 0),
        kind=kind,
        song=song,
    )


class SongLinks:
    """The links, in the library database."""

    def __init__(self, db_path: Path) -> None:
        self._path = str(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self._path, row_factory=True)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS song_links (
                    token TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    content_key TEXT NOT NULL DEFAULT '',
                    user_id INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute(
                'CREATE INDEX IF NOT EXISTS song_links_owner '
                'ON song_links (user_id, path)'
            )
            conn.execute(
                'CREATE INDEX IF NOT EXISTS song_links_key '
                'ON song_links (content_key)'
            )
            have = {
                str(row['name'])
                for row in conn.execute('PRAGMA table_info(song_links)')
            }
            for name, spec in _ADDED_COLUMNS.items():
                if name not in have:
                    conn.execute(
                        f'ALTER TABLE song_links ADD COLUMN {name} {spec}'
                    )

    def create(self, path: str, content_key: str, user_id: int) -> SongLink:
        """The user's link to *path*: the one they already have, else a
        new one."""

        path = _norm_path(path)
        with self._connect() as conn:
            found = conn.execute(
                'SELECT * FROM song_links WHERE user_id = ? AND path = ? '
                'AND kind = ?',
                (int(user_id), path, FILE),
            ).fetchone()
            if found is not None:
                return _row(found)
            link = SongLink(
                token=secrets.token_urlsafe(12),
                path=path,
                content_key=str(content_key or ''),
                user_id=int(user_id),
                created_at=int(time.time()),
            )
            conn.execute(
                'INSERT INTO song_links '
                '(token, path, content_key, user_id, created_at) '
                'VALUES (?, ?, ?, ?, ?)',
                (
                    link.token,
                    link.path,
                    link.content_key,
                    link.user_id,
                    link.created_at,
                ),
            )
            return link

    def create_stream(self, song: StreamSong, user_id: int) -> SongLink:
        """The user's link to a song that isn't downloaded, by its video:
        the one they already have (its details refreshed), else a new
        one."""

        values = (
            song.title,
            song.artist,
            song.album,
            float(song.duration or 0),
            song.cover_url,
            int(bool(song.explicit)),
        )
        with self._connect() as conn:
            found = conn.execute(
                'SELECT token FROM song_links WHERE user_id = ? '
                'AND kind = ? AND video_id = ?',
                (int(user_id), STREAM, song.video_id),
            ).fetchone()
            if found is not None:
                token = str(found['token'])
                conn.execute(
                    'UPDATE song_links SET title = ?, artist = ?, '
                    'album = ?, duration = ?, cover_url = ?, explicit = ? '
                    'WHERE token = ?',
                    (*values, token),
                )
            else:
                token = secrets.token_urlsafe(12)
                conn.execute(
                    'INSERT INTO song_links (token, path, content_key, '
                    'user_id, created_at, kind, video_id, title, artist, '
                    'album, duration, cover_url, explicit) '
                    "VALUES (?, '', '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        token,
                        int(user_id),
                        int(time.time()),
                        STREAM,
                        song.video_id,
                        *values,
                    ),
                )
        link = self.get(token)
        if link is None:  # pragma: no cover - written just above
            raise RuntimeError('Song link vanished after writing it')
        return link

    def get(self, token: str) -> Optional[SongLink]:
        if not valid_token(token):
            return None
        with self._connect() as conn:
            row = conn.execute(
                'SELECT * FROM song_links WHERE token = ?', (token,)
            ).fetchone()
        return _row(row) if row is not None else None

    def for_user(self, user_id: int) -> list[SongLink]:
        """The user's links, newest first."""

        with self._connect() as conn:
            rows = conn.execute(
                'SELECT * FROM song_links WHERE user_id = ? '
                'ORDER BY created_at DESC, token',
                (int(user_id),),
            ).fetchall()
        return [_row(row) for row in rows]

    def revoke(self, token: str) -> bool:
        if not valid_token(token):
            return False
        with self._connect() as conn:
            cur = conn.execute(
                'DELETE FROM song_links WHERE token = ?', (token,)
            )
            return cur.rowcount > 0

    def rekey(self, old_key: str, new_key: str, stored_path: str = '') -> int:
        """Follow a file rewritten in place (upgrade, replaced audio)."""

        old = str(old_key or '').strip()
        new = str(new_key or '').strip()
        if not old or not new or old == new:
            return 0
        with self._connect() as conn:
            cur = conn.execute(
                'UPDATE song_links SET content_key = ?, '
                "path = COALESCE(NULLIF(?, ''), path) WHERE content_key = ?",
                (new, _norm_path(stored_path), old),
            )
            return cur.rowcount

    def drop(self, content_key: str) -> int:
        """Forget the links to a deleted file."""

        key = str(content_key or '').strip()
        if not key:
            return 0
        with self._connect() as conn:
            cur = conn.execute(
                'DELETE FROM song_links WHERE content_key = ?', (key,)
            )
            return cur.rowcount
