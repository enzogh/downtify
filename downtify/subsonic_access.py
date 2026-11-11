"""Subsonic access for every account, through a Navidrome next to Castify.

Castify has no Subsonic API of its own; a Navidrome reading the same
music folder serves Subsonic clients (Symfonium, Amperfy, Feishin...).
With ``DOWNTIFY_SUBSONIC_*`` set, each user turns their access on in
Settings > Apps, without an admin:

* ``POST /api/me/subsonic`` creates their Navidrome account (named like
  their Castify account, never an admin) or gives it a new password,
  shown once. ``DELETE`` removes it.
* Castify keeps each account's **own** playlists, and their liked songs,
  in their Navidrome account as private playlists (:func:`sync_all`,
  every few minutes and right after an account is made). Nobody gets
  anyone else's playlists, like in Castify. Only playlists Castify made
  (their comment is :data:`MARKER`) are ever changed or removed.

Navidrome is driven through its own admin API with the admin account in
``DOWNTIFY_SUBSONIC_ADMIN_USER`` / ``_PASSWORD``. Navidrome makes every
playlist its caller's, so a playlist is created by that admin, filled,
then handed to its user (an admin may still edit it afterwards).
"""

from __future__ import annotations

import os
import secrets
import threading
import time
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Optional

import requests
from loguru import logger

#: The comment on every playlist Castify keeps in Navidrome: only those
#: are ever changed or removed.
MARKER = 'Castify'
#: Seconds between two full syncs.
SYNC_INTERVAL_SECONDS = 600
_TIMEOUT = 30
_SONG_PAGE = 5000
_DELETE_CHUNK = 200


class SubsonicAccessError(RuntimeError):
    """Navidrome can't be reached or refused; the message says why."""


@dataclass(frozen=True)
class SubsonicAccessConfig:
    #: What users put in their Subsonic client.
    public_url: str
    #: Where Castify reaches Navidrome (e.g. ``http://navidrome:4533``).
    navidrome_url: str
    admin_user: str
    admin_password: str

    @classmethod
    def from_env(cls) -> Optional[SubsonicAccessConfig]:
        """``DOWNTIFY_SUBSONIC_URL``, ``_NAVIDROME_URL`` (defaults to the
        public one), ``_ADMIN_USER`` and ``_ADMIN_PASSWORD``; ``None``
        unless the public URL and the admin login are all set."""

        public = os.getenv('DOWNTIFY_SUBSONIC_URL', '').strip().rstrip('/')
        user = os.getenv('DOWNTIFY_SUBSONIC_ADMIN_USER', '').strip()
        password = os.getenv('DOWNTIFY_SUBSONIC_ADMIN_PASSWORD', '')
        if not (public and user and password):
            return None
        internal = (
            os
            .getenv('DOWNTIFY_SUBSONIC_NAVIDROME_URL', '')
            .strip()
            .rstrip('/')
            or public
        )
        return cls(public, internal, user, password)


def path_key(path: str) -> str:
    """A library path as both sides spell it: ``/`` separators, NFC,
    casefolded, no leading slash."""

    text = unicodedata.normalize('NFC', str(path or '').replace('\\', '/'))
    return text.lstrip('/').casefold()


def new_password() -> str:
    return secrets.token_urlsafe(15)


def track_ids(files: Iterable[str], song_ids: dict[str, str]) -> list[str]:
    """Navidrome song ids for *files* (library paths), in order; files
    Navidrome doesn't have (not scanned yet, outside its folder) are
    left out."""

    ids = []
    for file in files:
        found = song_ids.get(path_key(file))
        if found:
            ids.append(found)
    return ids


@dataclass(frozen=True)
class SyncPlan:
    #: ``[(name, ids)]`` to create.
    create: list[tuple[str, list[str]]]
    #: ``[(playlist id, ids)]`` whose songs change.
    update: list[tuple[str, list[str]]]
    #: Playlist ids to delete.
    delete: list[str]


def plan_sync(
    existing: list[dict[str, Any]], wanted: dict[str, list[str]]
) -> SyncPlan:
    """What to do to one account's Castify playlists in Navidrome.

    *existing*: that account's playlists made by Castify, as ``{id,
    name, ids}``; *wanted*: ``{name: song ids}``. Names match ignoring
    case; a duplicate of a name is deleted. Empty playlists are not
    created."""

    by_name: dict[str, dict[str, Any]] = {}
    delete = []
    for row in existing:
        key = str(row.get('name') or '').casefold()
        if key in by_name:
            delete.append(str(row['id']))
        else:
            by_name[key] = row
    create = []
    update = []
    for name, ids in wanted.items():
        row = by_name.pop(name.casefold(), None)
        if row is None:
            if ids:
                create.append((name, ids))
        elif list(row.get('ids') or []) != ids:
            update.append((str(row['id']), ids))
    delete.extend(str(row['id']) for row in by_name.values())
    return SyncPlan(create=create, update=update, delete=delete)


class NavidromeAdmin:
    """Navidrome's admin API (``/auth/login``, ``/api/...``)."""

    def __init__(
        self,
        config: SubsonicAccessConfig,
        session: Optional[requests.Session] = None,
    ) -> None:
        self._config = config
        self._session = session or requests.Session()
        # Navidrome sits on the local network: never through the
        # outbound proxy that YouTube traffic uses.
        self._session.trust_env = False
        self._token = ''
        self._lock = threading.Lock()

    def _login(self) -> str:
        try:
            response = self._session.post(
                f'{self._config.navidrome_url}/auth/login',
                json={
                    'username': self._config.admin_user,
                    'password': self._config.admin_password,
                },
                timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise SubsonicAccessError('Navidrome cannot be reached') from exc
        if response.status_code != 200:
            raise SubsonicAccessError('Navidrome refused the admin login')
        token = str((response.json() or {}).get('token') or '')
        if not token:
            raise SubsonicAccessError('Navidrome refused the admin login')
        return token

    def _call(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Any = None,
    ) -> Any:
        with self._lock:
            if not self._token:
                self._token = self._login()
            token = self._token
        for attempt in range(2):
            try:
                response = self._session.request(
                    method,
                    f'{self._config.navidrome_url}{path}',
                    json=json,
                    params=params,
                    headers={'x-nd-authorization': f'Bearer {token}'},
                    timeout=_TIMEOUT,
                )
            except requests.RequestException as exc:
                raise SubsonicAccessError(
                    'Navidrome cannot be reached'
                ) from exc
            if response.status_code == 401 and attempt == 0:
                with self._lock:
                    self._token = self._login()
                    token = self._token
                continue
            if response.status_code >= 400:
                raise SubsonicAccessError(
                    f'Navidrome answered {response.status_code} to {path}'
                )
            return response.json() if response.content else {}
        raise SubsonicAccessError('Navidrome refused the admin login')

    # Users

    def users(self) -> list[dict[str, Any]]:
        return list(self._call('GET', '/api/user') or [])

    def find_user(self, username: str) -> Optional[dict[str, Any]]:
        wanted = username.casefold()
        for user in self.users():
            if str(user.get('userName') or '').casefold() == wanted:
                return user
        return None

    def create_user(self, username: str, name: str, password: str) -> str:
        made = self._call(
            'POST',
            '/api/user',
            json={
                'userName': username,
                'name': name or username,
                'password': password,
                'isAdmin': False,
            },
        )
        return str((made or {}).get('id') or '')

    def set_password(self, user_id: str, password: str) -> None:
        user = self._call('GET', f'/api/user/{user_id}')
        self._call(
            'PUT',
            f'/api/user/{user_id}',
            json={**user, 'password': password},
        )

    def delete_user(self, user_id: str) -> None:
        self._call('DELETE', f'/api/user/{user_id}')

    # Songs and playlists

    def song_ids(self) -> dict[str, str]:
        """``{path_key: song id}`` for the whole library."""

        found: dict[str, str] = {}
        start = 0
        while True:
            page = self._call(
                'GET',
                '/api/song',
                params={
                    '_start': start,
                    '_end': start + _SONG_PAGE,
                    '_sort': 'id',
                },
            )
            rows = list(page or [])
            for row in rows:
                if row.get('path') and row.get('id'):
                    found[path_key(row['path'])] = str(row['id'])
            if len(rows) < _SONG_PAGE:
                return found
            start += _SONG_PAGE

    def castify_playlists(self) -> list[dict[str, Any]]:
        """Every playlist Castify made, with its owner."""

        rows = self._call('GET', '/api/playlist', params={'_end': 100000})
        return [row for row in rows or [] if str(row.get('comment')) == MARKER]

    def playlist_song_ids(self, playlist_id: str) -> list[str]:
        rows = self._call(
            'GET',
            f'/api/playlist/{playlist_id}/tracks',
            params={'_end': 100000},
        )
        return [str(row.get('mediaFileId') or '') for row in rows or []]

    def create_playlist(self, name: str, ids: list[str], owner_id: str) -> str:
        made = self._call(
            'POST',
            '/api/playlist',
            json={'name': name, 'comment': MARKER, 'public': False},
        )
        playlist_id = str((made or {}).get('id') or '')
        if not playlist_id:
            raise SubsonicAccessError('Navidrome made no playlist')
        self.replace_songs(playlist_id, ids, current=0)
        # Navidrome makes it the admin's: hand it to its user.
        playlist = self._call('GET', f'/api/playlist/{playlist_id}')
        self._call(
            'PUT',
            f'/api/playlist/{playlist_id}',
            json={**playlist, 'ownerId': owner_id, 'public': False},
        )
        return playlist_id

    def replace_songs(
        self, playlist_id: str, ids: list[str], *, current: int
    ) -> None:
        """Make *ids* the playlist's songs; *current* is how many it has
        (tracks are removed by position, 1-based)."""

        # From the end, so the positions still to remove never shift.
        for end in range(current, 0, -_DELETE_CHUNK):
            start = max(1, end - _DELETE_CHUNK + 1)
            self._call(
                'DELETE',
                f'/api/playlist/{playlist_id}/tracks',
                params=[('id', str(n)) for n in range(start, end + 1)],
            )
        if ids:
            self._call(
                'POST',
                f'/api/playlist/{playlist_id}/tracks',
                json={'ids': ids},
            )

    def delete_playlist(self, playlist_id: str) -> None:
        self._call('DELETE', f'/api/playlist/{playlist_id}')


def apply_plan(
    admin: NavidromeAdmin,
    plan: SyncPlan,
    owner_id: str,
    sizes: dict[str, int],
) -> None:
    for name, ids in plan.create:
        admin.create_playlist(name, ids, owner_id)
    for playlist_id, ids in plan.update:
        admin.replace_songs(
            playlist_id, ids, current=sizes.get(playlist_id, 0)
        )
    for playlist_id in plan.delete:
        admin.delete_playlist(playlist_id)


def sync_all(
    admin: NavidromeAdmin,
    accounts: dict[str, dict[str, list[str]]],
    *,
    only: Optional[str] = None,
) -> int:
    """Bring every account's Castify playlists in Navidrome in line.

    *accounts*: ``{castify username: {playlist name: library paths}}``.
    Accounts without a Navidrome account are skipped. *only*: just that
    username. How many playlists changed."""

    users = {
        str(user.get('userName') or '').casefold(): str(user['id'])
        for user in admin.users()
    }
    wanted_users = {
        name: playlists
        for name, playlists in accounts.items()
        if name.casefold() in users
        and (only is None or name.casefold() == only.casefold())
    }
    if not wanted_users:
        return 0
    song_ids = admin.song_ids()
    made = admin.castify_playlists()
    changed = 0
    for username, playlists in wanted_users.items():
        owner_id = users[username.casefold()]
        mine = [row for row in made if str(row.get('ownerId')) == owner_id]
        existing = [
            {
                'id': row['id'],
                'name': row.get('name'),
                'ids': admin.playlist_song_ids(str(row['id'])),
            }
            for row in mine
        ]
        wanted = {
            name: track_ids(files, song_ids)
            for name, files in playlists.items()
        }
        plan = plan_sync(existing, wanted)
        sizes = {str(row['id']): len(row['ids']) for row in existing}
        apply_plan(admin, plan, owner_id, sizes)
        changed += len(plan.create) + len(plan.update) + len(plan.delete)
    return changed


class SubsonicAccess:
    """What the routes and the sync loop use."""

    def __init__(
        self,
        config: SubsonicAccessConfig,
        admin: Optional[NavidromeAdmin] = None,
    ) -> None:
        self.config = config
        self.admin = admin or NavidromeAdmin(config)
        self._sync_lock = threading.Lock()

    def status(self, username: str) -> dict[str, Any]:
        user = self.admin.find_user(username)
        return {
            'available': True,
            'url': self.config.public_url,
            'username': username,
            'exists': user is not None,
        }

    def issue_password(self, username: str, name: str) -> dict[str, Any]:
        """Create *username*'s account, or give it a new password."""

        password = new_password()
        user = self.admin.find_user(username)
        if user is None:
            self.admin.create_user(username, name, password)
            created = True
        else:
            if user.get('isAdmin'):
                # Never hand out an admin's password from here.
                raise SubsonicAccessError(
                    'This Navidrome account is an admin: change its '
                    'password in Navidrome'
                )
            self.admin.set_password(str(user['id']), password)
            created = False
        return {
            'url': self.config.public_url,
            'username': username,
            'password': password,
            'created': created,
        }

    def remove(self, username: str) -> bool:
        user = self.admin.find_user(username)
        if user is None:
            return False
        if user.get('isAdmin'):
            raise SubsonicAccessError(
                'This Navidrome account is an admin: remove it in Navidrome'
            )
        self.admin.delete_user(str(user['id']))
        return True

    def sync(
        self,
        accounts: dict[str, dict[str, list[str]]],
        *,
        only: Optional[str] = None,
    ) -> int:
        with self._sync_lock:
            started = time.monotonic()
            changed = sync_all(self.admin, accounts, only=only)
            if changed:
                logger.info(
                    'Subsonic: {} playlist(s) updated in Navidrome ({:.1f} s)',
                    changed,
                    time.monotonic() - started,
                )
            return changed
