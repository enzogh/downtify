"""Each user's listening history: one row per song played.

Mirrors :class:`downtify.listening_history.ListeningHistory`.
"""

from __future__ import annotations

from downtify.db.core import Connection

DDL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS listening_history (
        user_id BIGINT NOT NULL DEFAULT 0,
        play_id TEXT NOT NULL,
        played_at TEXT NOT NULL,
        artist TEXT NOT NULL,
        title TEXT NOT NULL,
        album TEXT NOT NULL DEFAULT '',
        file TEXT NOT NULL DEFAULT '',
        video_id TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'library',
        played_s DOUBLE PRECISION NOT NULL DEFAULT 0,
        duration_s DOUBLE PRECISION NOT NULL DEFAULT 0,
        skipped BIGINT NOT NULL DEFAULT 0,
        context TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (user_id, play_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_listening_history_user_at
        ON listening_history (user_id, played_at)
    """,
]


def up(conn: Connection) -> None:
    for stmt in DDL:
        conn.execute(stmt)
