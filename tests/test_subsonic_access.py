"""Subsonic access through Navidrome (downtify/subsonic_access.py):
accounts made by users themselves, and each account's own playlists
kept in it. Offline: Navidrome is a fake in memory."""

from __future__ import annotations

from typing import Any, Optional

import pytest

from downtify.subsonic_access import (
    MARKER,
    SubsonicAccess,
    SubsonicAccessConfig,
    SubsonicAccessError,
    path_key,
    plan_sync,
    sync_all,
    track_ids,
)

CONFIG = SubsonicAccessConfig(
    public_url='https://subsonic.example.com',
    navidrome_url='http://navidrome:4533',
    admin_user='castify-admin',
    admin_password='secret',
)


class FakeNavidrome:
    """The admin API calls :class:`NavidromeAdmin` makes, in memory."""

    def __init__(self) -> None:
        self.user_rows: list[dict[str, Any]] = [
            {'id': 'u0', 'userName': 'castify-admin', 'isAdmin': True}
        ]
        self.passwords: dict[str, str] = {}
        self.songs = {
            path_key('A/x.flac'): 's1',
            path_key('B/y.mp3'): 's2',
            path_key('C/z.opus'): 's3',
        }
        self.playlists: dict[str, dict[str, Any]] = {}
        self._next = 0

    def _id(self, prefix: str) -> str:
        self._next += 1
        return f'{prefix}{self._next}'

    # Users

    def users(self) -> list[dict[str, Any]]:
        return list(self.user_rows)

    def find_user(self, username: str) -> Optional[dict[str, Any]]:
        for user in self.user_rows:
            if user['userName'].casefold() == username.casefold():
                return user
        return None

    def create_user(self, username: str, name: str, password: str) -> str:
        user_id = self._id('u')
        self.user_rows.append({
            'id': user_id,
            'userName': username,
            'isAdmin': False,
        })
        self.passwords[user_id] = password
        return user_id

    def set_password(self, user_id: str, password: str) -> None:
        self.passwords[user_id] = password

    def delete_user(self, user_id: str) -> None:
        self.user_rows = [u for u in self.user_rows if u['id'] != user_id]
        self.playlists = {
            k: v for k, v in self.playlists.items() if v['ownerId'] != user_id
        }

    # Playlists

    def song_ids(self) -> dict[str, str]:
        return dict(self.songs)

    def castify_playlists(self) -> list[dict[str, Any]]:
        return [
            {'id': pid, **row}
            for pid, row in self.playlists.items()
            if row['comment'] == MARKER
        ]

    def playlist_song_ids(self, playlist_id: str) -> list[str]:
        return list(self.playlists[playlist_id]['ids'])

    def create_playlist(self, name: str, ids: list[str], owner_id: str) -> str:
        pid = self._id('p')
        self.playlists[pid] = {
            'name': name,
            'ids': list(ids),
            'ownerId': owner_id,
            'comment': MARKER,
            'public': False,
        }
        return pid

    def replace_songs(
        self, playlist_id: str, ids: list[str], *, current: int
    ) -> None:
        assert current == len(self.playlists[playlist_id]['ids'])
        self.playlists[playlist_id]['ids'] = list(ids)

    def delete_playlist(self, playlist_id: str) -> None:
        del self.playlists[playlist_id]


@pytest.fixture
def nd() -> FakeNavidrome:
    return FakeNavidrome()


def _names(nd: FakeNavidrome, owner: str) -> dict[str, list[str]]:
    return {
        row['name']: row['ids']
        for row in nd.playlists.values()
        if row['ownerId'] == owner
    }


# ── Pure parts ──────────────────────────────────────────────────────────


def test_paths_match_whatever_the_case_slashes_and_unicode():
    assert path_key('/Café/Ünï.flac') == path_key('café\\Ünï.flac')
    assert path_key('Café/a.mp3') == path_key('Café/A.MP3')


def test_track_ids_keep_the_order_and_skip_unknown_files():
    ids = {path_key('a.mp3'): '1', path_key('b.mp3'): '2'}
    assert track_ids(['b.mp3', 'gone.mp3', 'a.mp3'], ids) == ['2', '1']


def test_plan_creates_updates_and_deletes_by_name():
    existing = [
        {'id': 'p1', 'name': 'Road', 'ids': ['1']},
        {'id': 'p2', 'name': 'Old', 'ids': ['2']},
        {'id': 'p3', 'name': 'road', 'ids': ['1']},
    ]
    plan = plan_sync(existing, {'ROAD': ['1', '3'], 'New': ['4'], 'Empty': []})
    assert plan.create == [('New', ['4'])]
    assert plan.update == [('p1', ['1', '3'])]
    assert sorted(plan.delete) == ['p2', 'p3']


def test_an_unchanged_playlist_is_left_alone():
    plan = plan_sync(
        [{'id': 'p1', 'name': 'Road', 'ids': ['1']}], {'Road': ['1']}
    )
    assert (plan.create, plan.update, plan.delete) == ([], [], [])


# ── Accounts ────────────────────────────────────────────────────────────


def test_a_user_makes_their_account_then_gets_a_new_password(nd):
    access = SubsonicAccess(CONFIG, admin=nd)
    assert access.status('ana')['exists'] is False

    made = access.issue_password('ana', 'ana')
    assert made['created'] is True
    assert made['url'] == 'https://subsonic.example.com'
    user = nd.find_user('ana')
    assert user is not None
    assert user['isAdmin'] is False
    assert nd.passwords[user['id']] == made['password']

    again = access.issue_password('ana', 'ana')
    assert again['created'] is False
    assert again['password'] != made['password']
    assert nd.passwords[user['id']] == again['password']
    assert access.status('ana')['exists'] is True


def test_an_admin_account_s_password_is_never_handed_out(nd):
    access = SubsonicAccess(CONFIG, admin=nd)
    with pytest.raises(SubsonicAccessError):
        access.issue_password('castify-admin', 'x')
    with pytest.raises(SubsonicAccessError):
        access.remove('castify-admin')


def test_removing_the_access_deletes_the_account(nd):
    access = SubsonicAccess(CONFIG, admin=nd)
    access.issue_password('ana', 'ana')
    assert access.remove('ana') is True
    assert nd.find_user('ana') is None
    assert access.remove('ana') is False


# ── Playlists ───────────────────────────────────────────────────────────


def test_each_account_gets_only_its_own_playlists(nd):
    ana = nd.create_user('ana', 'ana', 'pw')
    bo = nd.create_user('bo', 'bo', 'pw')
    accounts = {
        'ana': {'Road': ['A/x.flac', 'B/y.mp3'], 'Titres likés': ['C/z.opus']},
        'bo': {'Chill': ['B/y.mp3']},
        'cy': {'Nobody': ['A/x.flac']},
    }

    changed = sync_all(nd, accounts)

    assert changed == 3
    assert _names(nd, ana) == {'Road': ['s1', 's2'], 'Titres likés': ['s3']}
    assert _names(nd, bo) == {'Chill': ['s2']}
    assert all(not row['public'] for row in nd.playlists.values())


def test_a_second_sync_follows_changes_and_changes_nothing_else(nd):
    ana = nd.create_user('ana', 'ana', 'pw')
    nd.playlists['own'] = {
        'name': 'Made in Navidrome',
        'ids': ['s1'],
        'ownerId': ana,
        'comment': '',
        'public': False,
    }
    sync_all(nd, {'ana': {'Road': ['A/x.flac'], 'Gone': ['B/y.mp3']}})

    changed = sync_all(nd, {'ana': {'Road': ['A/x.flac', 'C/z.opus']}})

    assert changed == 2
    assert _names(nd, ana) == {
        'Made in Navidrome': ['s1'],
        'Road': ['s1', 's3'],
    }
    assert sync_all(nd, {'ana': {'Road': ['A/x.flac', 'C/z.opus']}}) == 0


def test_only_syncs_one_account_when_asked(nd):
    ana = nd.create_user('ana', 'ana', 'pw')
    bo = nd.create_user('bo', 'bo', 'pw')
    accounts = {'ana': {'Road': ['A/x.flac']}, 'bo': {'Chill': ['B/y.mp3']}}

    sync_all(nd, accounts, only='ANA')

    assert _names(nd, ana) == {'Road': ['s1']}
    assert _names(nd, bo) == {}


def test_config_needs_the_url_and_the_admin_login(monkeypatch):
    for name in ('URL', 'NAVIDROME_URL', 'ADMIN_USER', 'ADMIN_PASSWORD'):
        monkeypatch.delenv(f'DOWNTIFY_SUBSONIC_{name}', raising=False)
    assert SubsonicAccessConfig.from_env() is None

    monkeypatch.setenv('DOWNTIFY_SUBSONIC_URL', 'https://s.example.com/')
    monkeypatch.setenv('DOWNTIFY_SUBSONIC_ADMIN_USER', 'admin')
    assert SubsonicAccessConfig.from_env() is None
    monkeypatch.setenv('DOWNTIFY_SUBSONIC_ADMIN_PASSWORD', 'pw')
    config = SubsonicAccessConfig.from_env()
    assert config is not None
    assert config.public_url == 'https://s.example.com'
    assert config.navidrome_url == 'https://s.example.com'
