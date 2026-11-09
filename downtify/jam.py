"""Jam: several accounts listening together to one shared queue.

One account starts a Jam and gets a short code; other signed-in accounts
join with it. Everyone can add songs from the library to the shared
queue, and every device in the Jam plays the same song at the same
moment: the server keeps the playback clock (``index``, ``position`` at
``updated``, ``playing``) and each client follows it.

The host can always control playback; guests too unless the host turns
``guests_can_control`` off. Anyone may remove a song they added; the
host (and controlling guests) may remove any.

Jams live in memory only: a server restart ends them, and one nobody
touched for :data:`IDLE_SECONDS` is dropped. An account is in at most
one Jam at a time - starting or joining another leaves the first.
"""

from __future__ import annotations

import math
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

#: No 0/O or 1/I, so a code read aloud is typed right the first time.
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
CODE_LENGTH = 6
#: A Jam nobody touched for this long is dropped.
IDLE_SECONDS = 12 * 3600
MAX_QUEUE = 500
MAX_TEXT = 300
#: Within this many seconds of its start, "previous" goes back a song
#: instead of restarting the current one (the player does the same).
RESTART_THRESHOLD = 3.0

CONTROL_ACTIONS = frozenset({
    'play',
    'pause',
    'seek',
    'next',
    'prev',
    'jump',
    'ended',
})


class JamError(Exception):
    """A refused Jam request: *status* is the HTTP status to answer."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class JamItem:
    id: str
    file: str
    title: str
    artist: str
    album: str
    duration: float
    added_by: int

    def to_dict(self, names: dict[int, str]) -> dict[str, Any]:
        return {
            'id': self.id,
            'file': self.file,
            'title': self.title,
            'artist': self.artist,
            'album': self.album,
            'duration': self.duration,
            'added_by': self.added_by,
            'added_by_name': names.get(self.added_by, ''),
        }


@dataclass
class Jam:
    id: str
    code: str
    host_id: int
    #: user_id -> username, in joining order (the host first).
    members: dict[int, str]
    queue: list[JamItem] = field(default_factory=list)
    index: int = -1
    #: Seconds into the current song at ``updated``.
    position: float = 0.0
    playing: bool = False
    updated: float = 0.0
    guests_can_control: bool = True
    version: int = 0
    touched: float = 0.0

    def current_position(self, now: float) -> float:
        """Where the current song is at *now*, by the shared clock."""

        if not self.playing:
            return self.position
        elapsed = max(0.0, now - self.updated)
        position = self.position + elapsed
        item = self.current_item()
        if item is not None and item.duration > 0:
            position = min(position, item.duration)
        return position

    def current_item(self) -> Optional[JamItem]:
        if 0 <= self.index < len(self.queue):
            return self.queue[self.index]
        return None

    def can_control(self, user_id: int) -> bool:
        return user_id == self.host_id or (
            self.guests_can_control and user_id in self.members
        )

    def snapshot(self, now: float) -> dict[str, Any]:
        return {
            'id': self.id,
            'code': self.code,
            'host_id': self.host_id,
            'members': [
                {'id': uid, 'name': name, 'host': uid == self.host_id}
                for uid, name in self.members.items()
            ],
            'queue': [item.to_dict(self.members) for item in self.queue],
            'index': self.index,
            'position': round(self.current_position(now), 3),
            'playing': self.playing,
            # The clock the position was read at, so a client can work
            # out where the song is when the message reaches it.
            'updated': round(now, 3),
            'now': round(now, 3),
            'guests_can_control': self.guests_can_control,
            'version': self.version,
        }


def _clean_text(value: Any) -> str:
    return ' '.join(str(value or '').split())[:MAX_TEXT]


def _clean_duration(value: Any) -> float:
    try:
        duration = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(duration) or duration < 0:
        return 0.0
    return min(duration, 24 * 3600.0)


def new_code(taken: set[str]) -> str:
    """A fresh join code not in *taken*."""

    while True:
        code = ''.join(
            secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH)
        )
        if code not in taken:
            return code


def normalize_code(value: Any) -> str:
    """A typed or pasted code (spaces, dashes, lowercase, a join link)."""

    text = str(value or '').strip()
    if 'code=' in text:
        text = text.split('code=', 1)[1].split('&', 1)[0]
    return ''.join(ch for ch in text.upper() if ch in CODE_ALPHABET)


def _changed(jam: Jam, now: float) -> None:
    jam.version += 1
    jam.touched = now


def _go(jam: Jam, index: int, now: float) -> None:
    jam.index = index
    jam.position = 0.0
    jam.updated = now
    jam.playing = 0 <= index < len(jam.queue)


def _advance(jam: Jam, now: float) -> None:
    if jam.index + 1 < len(jam.queue):
        _go(jam, jam.index + 1, now)
        return
    # The end of the queue: past the last song, stopped. The next
    # song added is cued from there.
    jam.index = len(jam.queue)
    jam.position = 0.0
    jam.updated = now
    jam.playing = False


class JamStore:
    """Every live Jam, by id, with who is in which."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._jams: dict[str, Jam] = {}
        self._by_code: dict[str, str] = {}
        self._by_user: dict[int, str] = {}

    # -- lookup ---------------------------------------------------------

    def _expire(self, now: float) -> list[Jam]:
        stale = [
            jam
            for jam in self._jams.values()
            if now - jam.touched > IDLE_SECONDS
        ]
        for jam in stale:
            self._drop(jam)
        return stale

    def _drop(self, jam: Jam) -> None:
        self._jams.pop(jam.id, None)
        self._by_code.pop(jam.code, None)
        for uid in jam.members:
            if self._by_user.get(uid) == jam.id:
                self._by_user.pop(uid, None)

    def _jam_of(self, user_id: int) -> Jam:
        jam_id = self._by_user.get(user_id)
        jam = self._jams.get(jam_id) if jam_id else None
        if jam is None:
            raise JamError(404, 'You are not in a Jam')
        return jam

    def get(self, user_id: int) -> Optional[dict[str, Any]]:
        """The Jam *user_id* is in, or ``None``."""

        with self._lock:
            now = self._clock()
            self._expire(now)
            jam_id = self._by_user.get(user_id)
            jam = self._jams.get(jam_id) if jam_id else None
            return jam.snapshot(now) if jam else None

    def members_of(self, user_id: int) -> list[int]:
        """Everyone in *user_id*'s Jam (empty when there is none)."""

        with self._lock:
            jam_id = self._by_user.get(user_id)
            jam = self._jams.get(jam_id) if jam_id else None
            return list(jam.members) if jam else []

    # -- membership -----------------------------------------------------

    def _leave(self, user_id: int) -> tuple[list[int], list[int]]:
        """Take *user_id* out of their Jam: ``(gone, remaining)`` users.

        The host leaving ends the Jam for everyone.
        """

        jam_id = self._by_user.get(user_id)
        jam = self._jams.get(jam_id) if jam_id else None
        if jam is None:
            self._by_user.pop(user_id, None)
            return [], []
        if user_id == jam.host_id:
            gone = list(jam.members)
            self._drop(jam)
            return gone, []
        jam.members.pop(user_id, None)
        self._by_user.pop(user_id, None)
        _changed(jam, self._clock())
        return [user_id], list(jam.members)

    def start(self, user_id: int, name: str) -> tuple[dict, list[int]]:
        """Start a Jam hosted by *user_id*: ``(snapshot, users_who_left)``.

        Whoever was in a Jam *user_id* hosted is told it ended.
        """

        if not user_id:
            raise JamError(401, 'Sign in to start a Jam')
        with self._lock:
            now = self._clock()
            self._expire(now)
            gone, _ = self._leave(user_id)
            jam = Jam(
                id=secrets.token_hex(8),
                code=new_code(set(self._by_code)),
                host_id=user_id,
                members={user_id: _clean_text(name) or f'#{user_id}'},
                updated=now,
                touched=now,
            )
            self._jams[jam.id] = jam
            self._by_code[jam.code] = jam.id
            self._by_user[user_id] = jam.id
            return jam.snapshot(now), [uid for uid in gone if uid != user_id]

    def join(
        self, user_id: int, name: str, code: str
    ) -> tuple[dict, list[int]]:
        """Join the Jam with *code*: ``(snapshot, users_who_left)``."""

        if not user_id:
            raise JamError(401, 'Sign in to join a Jam')
        wanted = normalize_code(code)
        with self._lock:
            now = self._clock()
            self._expire(now)
            jam_id = self._by_code.get(wanted)
            jam = self._jams.get(jam_id) if jam_id else None
            if jam is None:
                raise JamError(404, 'No Jam has this code')
            gone: list[int] = []
            if self._by_user.get(user_id) != jam.id:
                gone, _ = self._leave(user_id)
                jam.members[user_id] = _clean_text(name) or f'#{user_id}'
                self._by_user[user_id] = jam.id
                _changed(jam, now)
            return jam.snapshot(now), [uid for uid in gone if uid != user_id]

    def leave(self, user_id: int) -> tuple[list[int], list[int]]:
        """Leave (or, for the host, end) the Jam: ``(gone, remaining)``."""

        with self._lock:
            return self._leave(user_id)

    def configure(self, user_id: int, guests_can_control: bool) -> dict:
        with self._lock:
            now = self._clock()
            jam = self._jam_of(user_id)
            if user_id != jam.host_id:
                raise JamError(403, 'Only the host can change this')
            jam.guests_can_control = bool(guests_can_control)
            _changed(jam, now)
            return jam.snapshot(now)

    # -- queue ----------------------------------------------------------

    def add(
        self,
        user_id: int,
        tracks: list[dict[str, Any]],
        position: Any = 'end',
        play: bool = False,
    ) -> dict:
        """Add library *tracks*: at the ``'end'``, ``'next'`` (after the
        current song) or an index. ``play`` jumps to the first of them."""

        with self._lock:
            now = self._clock()
            jam = self._jam_of(user_id)
            if play and not jam.can_control(user_id):
                raise JamError(403, 'Only the host can control playback')
            items = [
                JamItem(
                    id=secrets.token_hex(6),
                    file=str(track.get('file') or ''),
                    title=_clean_text(track.get('title')),
                    artist=_clean_text(track.get('artist')),
                    album=_clean_text(track.get('album')),
                    duration=_clean_duration(track.get('duration')),
                    added_by=user_id,
                )
                for track in tracks
                if track.get('file')
            ]
            room = MAX_QUEUE - len(jam.queue)
            if room <= 0 or not items:
                if not items:
                    raise JamError(400, 'No songs to add')
                raise JamError(409, 'The Jam queue is full')
            items = items[:room]
            if position == 'next':
                at = jam.index + 1 if jam.index >= 0 else len(jam.queue)
            elif position == 'end' or position is None:
                at = len(jam.queue)
            else:
                try:
                    at = int(position)
                except (TypeError, ValueError):
                    at = len(jam.queue)
            at = max(0, min(at, len(jam.queue)))
            finished = jam.index >= len(jam.queue)
            jam.queue[at:at] = items
            if jam.index < 0 or finished:
                # An empty or played-out Jam cues the first new song.
                jam.index = at
                jam.position = 0.0
                jam.updated = now
            elif jam.index >= at:
                jam.index += len(items)
            if play:
                _go(jam, at, now)
            _changed(jam, now)
            return jam.snapshot(now)

    def remove(self, user_id: int, item_id: str) -> dict:
        with self._lock:
            now = self._clock()
            jam = self._jam_of(user_id)
            at = next(
                (i for i, it in enumerate(jam.queue) if it.id == item_id), -1
            )
            if at < 0:
                raise JamError(404, 'This song is no longer in the Jam')
            item = jam.queue[at]
            if item.added_by != user_id and not jam.can_control(user_id):
                raise JamError(403, 'You can only remove songs you added')
            jam.queue.pop(at)
            if at < jam.index:
                jam.index -= 1
            elif at == jam.index:
                # The playing song went: the next one takes its place
                # (past the end, the Jam stops).
                if jam.index >= len(jam.queue):
                    jam.playing = False
                jam.position = 0.0
                jam.updated = now
            if not jam.queue:
                jam.index = -1
                jam.playing = False
            _changed(jam, now)
            return jam.snapshot(now)

    def move(self, user_id: int, item_id: str, to: int) -> dict:
        with self._lock:
            now = self._clock()
            jam = self._jam_of(user_id)
            if not jam.can_control(user_id):
                raise JamError(403, 'Only the host can reorder the Jam')
            at = next(
                (i for i, it in enumerate(jam.queue) if it.id == item_id), -1
            )
            if at < 0:
                raise JamError(404, 'This song is no longer in the Jam')
            to = max(0, min(int(to), len(jam.queue) - 1))
            current = jam.current_item()
            item = jam.queue.pop(at)
            jam.queue.insert(to, item)
            if current is not None:
                jam.index = jam.queue.index(current)
            _changed(jam, now)
            return jam.snapshot(now)

    def clear_upcoming(self, user_id: int) -> dict:
        with self._lock:
            now = self._clock()
            jam = self._jam_of(user_id)
            if not jam.can_control(user_id):
                raise JamError(403, 'Only the host can clear the Jam')
            del jam.queue[max(jam.index, -1) + 1 :]
            _changed(jam, now)
            return jam.snapshot(now)

    # -- playback -------------------------------------------------------

    def control(
        self,
        user_id: int,
        action: str,
        position: Optional[float] = None,
        index: Optional[int] = None,
        from_index: Optional[int] = None,
    ) -> Optional[dict]:
        """Apply a transport *action*; ``None`` when it changed nothing
        (an ``ended`` another device already reported)."""

        if action not in CONTROL_ACTIONS:
            raise JamError(400, f'Unknown action {action!r}')
        with self._lock:
            now = self._clock()
            jam = self._jam_of(user_id)
            # A song ending is no one's decision: every listening device
            # reports it, and only the first report (for the song still
            # current) moves the Jam on.
            if action == 'ended':
                if from_index != jam.index or jam.current_item() is None:
                    return None
                _advance(jam, now)
                _changed(jam, now)
                return jam.snapshot(now)
            if not jam.can_control(user_id):
                raise JamError(403, 'Only the host can control playback')
            if action == 'play':
                if jam.current_item() is None:
                    if not jam.queue:
                        raise JamError(409, 'The Jam queue is empty')
                    # Played out: start the last song again.
                    _go(jam, min(max(jam.index, 0), len(jam.queue) - 1), now)
                else:
                    jam.position = jam.current_position(now)
                    jam.updated = now
                    jam.playing = True
            elif action == 'pause':
                jam.position = jam.current_position(now)
                jam.updated = now
                jam.playing = False
            elif action == 'seek':
                item = jam.current_item()
                target = max(0.0, float(position or 0))
                if item is not None and item.duration > 0:
                    target = min(target, item.duration)
                jam.position = target
                jam.updated = now
            elif action == 'next':
                _advance(jam, now)
            elif action == 'prev':
                if (
                    jam.current_position(now) > RESTART_THRESHOLD
                    or jam.index <= 0
                ):
                    jam.position = 0.0
                    jam.updated = now
                else:
                    _go(jam, jam.index - 1, now)
            elif action == 'jump':
                if index is None or not 0 <= int(index) < len(jam.queue):
                    raise JamError(400, 'No song at this position')
                _go(jam, int(index), now)
            _changed(jam, now)
            return jam.snapshot(now)
