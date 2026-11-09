"""Public links to one song, like Spotify's *Share → Copy link*.

A signed-in user makes a link for a library song; anyone who has the
link can open ``/s/<token>`` and listen to it (with its cover, title and
artist) without signing in - and nothing else on the server. A link
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


@dataclass(frozen=True)
class SongLink:
    token: str
    path: str
    content_key: str
    user_id: int
    created_at: int


def _row(row: sqlite3.Row) -> SongLink:
    return SongLink(
        token=str(row['token']),
        path=str(row['path']),
        content_key=str(row['content_key'] or ''),
        user_id=int(row['user_id'] or 0),
        created_at=int(row['created_at'] or 0),
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

    def create(self, path: str, content_key: str, user_id: int) -> SongLink:
        """The user's link to *path*: the one they already have, else a
        new one."""

        path = _norm_path(path)
        with self._connect() as conn:
            found = conn.execute(
                'SELECT * FROM song_links WHERE user_id = ? AND path = ?',
                (int(user_id), path),
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
