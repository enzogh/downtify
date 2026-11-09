"""The order an owner gave an imported playlist.

An imported playlist (a Spotify / YouTube Music link, or a Playlist
Monitor watch) is rewritten from its source on every sync, in the
source's order. When its owner (or an admin) drags its songs into another
order, that order is kept here - by casefolded M3U name, as stored
library paths - and ``m3u.write_m3u`` applies it whenever it rewrites the
playlist (see ``m3u.set_custom_order_source``): the songs keep their
places and new ones from the source go at the end. A Library playlist
needs none of this: its M3U is only written by Castify.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Sequence

from .sqlite_utils import connect_sqlite


def order_key(name: str) -> str:
    return str(name or '').strip().casefold()


class PlaylistCustomOrder:
    """Chosen orders, in the library database."""

    def __init__(self, db_path: Path) -> None:
        self._path = str(db_path)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS playlist_custom_order (
                    name_key TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    PRIMARY KEY (name_key, position)
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self._path)

    def get(self, name: str) -> list[str]:
        """Stored paths in the chosen order (``[]``: the source's)."""

        with self._connect() as conn:
            rows = conn.execute(
                'SELECT path FROM playlist_custom_order WHERE name_key = ? '
                'ORDER BY position',
                (order_key(name),),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def set(self, name: str, paths: Sequence[str]) -> None:
        key = order_key(name)
        rows = [
            (key, position, str(path).replace('\\', '/'))
            for position, path in enumerate(paths)
            if str(path or '').strip()
        ]
        with self._connect() as conn:
            conn.execute(
                'DELETE FROM playlist_custom_order WHERE name_key = ?', (key,)
            )
            conn.executemany(
                'INSERT INTO playlist_custom_order (name_key, position, path) '
                'VALUES (?, ?, ?)',
                rows,
            )

    def drop(self, name: str) -> None:
        """Forget it (the playlist was deleted or detached)."""

        with self._connect() as conn:
            conn.execute(
                'DELETE FROM playlist_custom_order WHERE name_key = ?',
                (order_key(name),),
            )
