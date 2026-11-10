"""The queue's recent finished downloads, kept across restarts.

The queue (``state.download_jobs``) lives in memory: a restart or an
update used to empty its **Done** and **Failed** tabs, and a page opened
afterwards had nothing to show of what was downloaded a minute before.
:class:`DownloadHistory` keeps a copy of every job that ended (``done``
or ``error``) in ``downtify_library.db`` - the same row ``GET
/api/queue`` shows, plus when it ended - and the server puts them back
in the queue when it starts.

It is a short history, not a log (the usage page has
:mod:`downtify.download_log` for that): each account keeps its
:data:`KEEP_PER_ACCOUNT` most recent rows, and so do the jobs nobody
asked for (watches, retries). Clearing or removing rows from the queue
removes them here too.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection
from pathlib import Path
from typing import Any

from loguru import logger

from .sqlite_utils import connect_sqlite

#: How many finished downloads each account keeps.
KEEP_PER_ACCOUNT = 50

#: The statuses of a finished job.
FINISHED = frozenset({'done', 'error'})

#: Keeps every ``IN (...)`` under SQLite's bound-parameter limit.
_CHUNK = 500


def _user_ids(raw: Any) -> list[int]:
    try:
        values = json.loads(raw or '[]')
    except (TypeError, ValueError):
        return []
    if not isinstance(values, list):
        return []
    found: set[int] = set()
    for value in values:
        try:
            uid = int(value)
        except (TypeError, ValueError):
            continue
        if uid:
            found.add(uid)
    return sorted(found)


def keep_ids(
    rows: list[tuple[str, list[int]]], keep: int = KEEP_PER_ACCOUNT
) -> set[str]:
    """Which of *rows* (``(song_id, user_ids)``, newest first) to keep:
    a row stays while one of its accounts - or "nobody", for a row
    without any - has fewer than *keep* newer rows."""

    counts: dict[int, int] = {}
    kept: set[str] = set()
    for song_id, users in rows:
        owners = users or [0]
        if any(counts.get(uid, 0) < keep for uid in owners):
            kept.add(song_id)
        for uid in owners:
            counts[uid] = counts.get(uid, 0) + 1
    return kept


class DownloadHistory:
    """SQLite copy of the recently finished download jobs."""

    def __init__(self, db_path: Path, keep: int = KEEP_PER_ACCOUNT) -> None:
        self._path = str(db_path)
        self._keep = keep
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self._path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS download_history (
                    song_id TEXT PRIMARY KEY,
                    song TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    filename TEXT,
                    provider TEXT NOT NULL DEFAULT '',
                    user_ids TEXT NOT NULL DEFAULT '[]',
                    finished_at REAL NOT NULL
                )
            """)
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_download_history_at '
                'ON download_history (finished_at)'
            )

    def record(self, song_id: str, job: dict[str, Any]) -> None:
        """Save finished *job* (replacing an older end of the same song)
        and drop what falls past each account's limit."""

        status = str(job.get('status') or '')
        if not song_id or status not in FINISHED:
            return
        users = sorted({int(uid) for uid in job.get('user_ids') or () if uid})
        with self._connect() as conn:
            conn.execute(
                'INSERT INTO download_history (song_id, song, status, '
                'message, filename, provider, user_ids, finished_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?) '
                'ON CONFLICT(song_id) DO UPDATE SET song = excluded.song, '
                'status = excluded.status, message = excluded.message, '
                'filename = excluded.filename, '
                'provider = excluded.provider, '
                'user_ids = excluded.user_ids, '
                'finished_at = excluded.finished_at',
                (
                    song_id,
                    json.dumps(job.get('song') or {}, default=str),
                    status,
                    str(job.get('message') or ''),
                    job.get('filename') or None,
                    str(job.get('provider') or ''),
                    json.dumps(users),
                    float(job.get('finished_at') or 0),
                ),
            )
        self.prune()

    def prune(self) -> int:
        """Drop rows past each account's limit; how many went."""

        with self._connect() as conn:
            found = conn.execute(
                'SELECT song_id, user_ids FROM download_history '
                'ORDER BY finished_at DESC'
            ).fetchall()
        rows = [(str(sid), _user_ids(users)) for sid, users in found]
        kept = keep_ids(rows, self._keep)
        doomed = [sid for sid, _ in rows if sid not in kept]
        self.forget(doomed)
        return len(doomed)

    def forget(self, song_ids: Collection[str]) -> None:
        ids = list(dict.fromkeys(str(sid) for sid in song_ids if sid))
        if not ids:
            return
        with self._connect() as conn:
            for start in range(0, len(ids), _CHUNK):
                chunk = ids[start : start + _CHUNK]
                marks = ','.join('?' * len(chunk))
                conn.execute(
                    f'DELETE FROM download_history WHERE song_id IN ({marks})',
                    chunk,
                )

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute('DELETE FROM download_history')

    def jobs(self) -> list[tuple[str, dict[str, Any]]]:
        """Every kept row as a queue job ``(song_id, job)``, oldest
        first (unreadable rows skipped)."""

        with self._connect() as conn:
            found = conn.execute(
                'SELECT song_id, song, status, message, filename, provider, '
                'user_ids, finished_at FROM download_history '
                'ORDER BY finished_at'
            ).fetchall()
        jobs: list[tuple[str, dict[str, Any]]] = []
        for row in found:
            song_id, song, status, message, filename, provider = row[:6]
            try:
                song_dict = json.loads(song)
            except ValueError:
                logger.warning('Skipping unreadable finished download')
                continue
            if not isinstance(song_dict, dict):
                continue
            jobs.append((
                str(song_id),
                {
                    'song': song_dict,
                    'status': status,
                    'progress': 100 if status == 'done' else 0,
                    'message': message or '',
                    'provider': provider or '',
                    'filename': filename,
                    'user_ids': set(_user_ids(row[6])),
                    'finished_at': float(row[7] or 0),
                },
            ))
        return jobs
