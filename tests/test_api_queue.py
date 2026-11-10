"""Download queue maintenance endpoints."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from downtify import api
from downtify.activity import NowPlaying
from downtify.auth import Principal


def _request(user_id: int = 0) -> Request:
    scope: dict[str, Any] = {'type': 'http', 'headers': []}
    if user_id:
        scope['state'] = {
            'principal': Principal(
                'device', 'client', '', user_id, f'user{user_id}', 'user'
            )
        }
    return Request(scope)


def test_clear_completed_queue_removes_only_done_jobs():
    api.state.download_jobs.clear()
    try:
        done_id = api._register_job(
            {'song_id': 'done-1', 'name': 'A'},
            status='done',
            user_id=5,
        )
        err_id = api._register_job(
            {'song_id': 'err-1', 'name': 'B'},
            status='error',
            user_id=5,
        )
        q_id = api._register_job(
            {'song_id': 'q-1', 'name': 'C'},
            status='queued',
            user_id=5,
        )

        result = api.clear_completed_queue(_request(5))

        assert result['removed'] == 1
        assert done_id not in api.state.download_jobs
        assert err_id in api.state.download_jobs
        assert q_id in api.state.download_jobs
    finally:
        api.state.download_jobs.clear()


def test_queue_rows_carry_waiting_positions():
    api.state.download_jobs.clear()
    try:
        api._register_job(
            {'song_id': 'q-1', 'name': 'A'},
            status='downloading',
            user_id=5,
        )
        api._register_job(
            {'song_id': 'q-2', 'name': 'B'}, status='queued', user_id=5
        )
        api._register_job(
            {'song_id': 'd-1', 'name': 'C'}, status='done', user_id=5
        )

        rows = {j['song']['song_id']: j for j in api.get_queue(_request(5))}

        assert rows['q-1']['position'] == 1
        assert rows['q-2']['position'] == 2
        assert rows['d-1']['position'] is None
        assert rows['q-1']['user_ids'] == [5]
    finally:
        api.state.download_jobs.clear()


def _admin_request(user_id: int = 1) -> Request:
    scope: dict[str, Any] = {
        'type': 'http',
        'headers': [],
        'state': {
            'principal': Principal(
                'session', 'admin', '', user_id, 'boss', 'admin'
            )
        },
    }
    return Request(scope)


def test_admin_queue_rows_name_who_asked(monkeypatch):
    monkeypatch.setattr(api, '_usernames', lambda: {1: 'boss', 5: 'maria'})
    api.state.download_jobs.clear()
    try:
        api._register_job({'song_id': 'm-1'}, status='queued', user_id=5)
        api._register_job({'song_id': 'b-1'}, status='queued', user_id=1)
        api._register_job({'song_id': 'w-1'}, status='queued')

        rows = {
            j['song']['song_id']: j for j in api.get_queue(_admin_request())
        }
        assert rows['m-1']['users'] == ['maria']
        assert rows['m-1']['mine'] is False
        assert rows['b-1']['mine'] is True
        assert rows['w-1']['users'] == []
        assert rows['w-1']['mine'] is False

        # A user's own rows: no names of anyone else.
        own = api.get_queue(_request(5))
        assert [j['song']['song_id'] for j in own] == ['m-1']
        assert own[0]['mine'] is True
        assert 'users' not in own[0]
    finally:
        api.state.download_jobs.clear()


def test_clear_others_keeps_only_the_admins_jobs(monkeypatch):

    dropped: list = []
    monkeypatch.setattr(api, '_drop_pending', dropped.append)
    api.state.download_jobs.clear()
    try:
        api._register_job({'song_id': 'm-1'}, status='downloading', user_id=5)
        api._register_job({'song_id': 'b-1'}, status='queued', user_id=1)
        api._register_job({'song_id': 'w-1'}, status='done')

        with pytest.raises(HTTPException):
            api.clear_others_queue(_request(5))
        result = api.clear_others_queue(_admin_request())

        assert result == {'removed': 2}
        assert list(api.state.download_jobs) == ['b-1']
        assert sorted(dropped[0]) == ['m-1', 'w-1']
    finally:
        api.state.download_jobs.clear()


class _Socket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


def test_ownerless_job_frames_skip_signed_in_users():

    manager = api.ConnectionManager()
    user, admin, anon = _Socket(), _Socket(), _Socket()
    manager._clients = {'u': user, 'a': admin, 'x': anon}
    manager._users = {'u': 5, 'a': 1}
    manager._admins = {'a'}

    asyncio.run(manager.broadcast_job([], {'song': {'song_id': 's'}}))

    assert not user.sent
    assert len(admin.sent) == 1
    assert len(anon.sent) == 1

    asyncio.run(manager.broadcast_job([5], {'song': {'song_id': 's'}}))
    assert len(user.sent) == 1
    assert len(admin.sent) == 2
    assert len(anon.sent) == 1


def test_progress_after_the_end_is_not_sent(monkeypatch):

    sent: list = []

    async def fake_broadcast_job(users, message):
        sent.append((set(users), message))

    monkeypatch.setattr(
        api.state.connections, 'broadcast_job', fake_broadcast_job
    )
    job = {'status': 'downloading', 'user_ids': {5}}
    asyncio.run(api._send_progress(job, {'progress': 50}))
    job['status'] = 'done'
    asyncio.run(api._send_progress(job, {'progress': 100}))

    assert sent == [({5}, {'progress': 50})]


def test_private_playlist_edits_reach_the_owners_own_devices(monkeypatch):
    sent: list = []
    shared: list = []

    async def fake_send_user(user_id, message):
        sent.append((user_id, message))

    async def fake_announce():
        shared.append(True)

    monkeypatch.setattr(api.state.connections, 'send_user', fake_send_user)
    monkeypatch.setattr(api, 'announce_playlists_changed', fake_announce)

    asyncio.run(
        api.announce_playlist_edited(
            {'visibility': 'private', 'owner_id': 5}, _request(5)
        )
    )
    assert sent == [(5, {'type': 'playlists_changed'})]
    assert not shared

    sent.clear()
    asyncio.run(
        api.announce_playlist_edited(
            {'visibility': 'private', 'owner_id': 5}, _admin_request()
        )
    )
    assert [uid for uid, _ in sent] == [1, 5]

    sent.clear()
    asyncio.run(
        api.announce_playlist_edited(
            {'visibility': 'public', 'owner_id': 5}, _request(5)
        )
    )
    assert not sent
    assert shared == [True]


def test_open_pages_are_listed_as_idle_devices(monkeypatch):
    now = NowPlaying()
    now.report(
        user_id=5,
        username='maria',
        player=':tab-1',
        player_id='tab-1',
        client='Web',
        state='playing',
        track={'file': 'a.mp3'},
    )
    monkeypatch.setattr(api.state, 'now_playing', now)
    manager = api.ConnectionManager()
    manager._clients = {'tab-1': _Socket(), 'tab-2': _Socket(), 'x': _Socket()}
    manager._users = {'tab-1': 5, 'tab-2': 5, 'x': 6}
    manager._labels = {'tab-2': 'Web (Firefox on Linux)'}
    monkeypatch.setattr(api.state, 'connections', manager)

    rows = api.devices_for_user(5)

    assert [row['player'] for row in rows] == ['tab-1', 'tab-2']
    assert rows[0]['idle'] is False
    assert rows[1] == {
        'player': 'tab-2',
        'client': 'Web (Firefox on Linux)',
        'track': None,
        'paused': True,
        'position': 0,
        'started_at': None,
        'seconds_ago': 0,
        'idle': True,
        'app': False,
    }
    assert api.devices_for_user(0) == []
