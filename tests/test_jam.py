"""Jam: the shared queue and playback clock, and its HTTP routes."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from downtify import api, jam_routes
from downtify.auth import Principal
from downtify.jam import (
    CODE_LENGTH,
    IDLE_SECONDS,
    JamError,
    JamStore,
    normalize_code,
)

HOST, GUEST, OTHER = 1, 2, 3


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _song(name: str, duration: float = 200) -> dict[str, Any]:
    return {'file': f'{name}.mp3', 'title': name, 'duration': duration}


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(clock: Clock) -> JamStore:
    return JamStore(clock=clock)


def _started(store: JamStore) -> str:
    snapshot, _ = store.start(HOST, 'host')
    store.join(GUEST, 'guest', snapshot['code'])
    return snapshot['code']


# ── membership ─────────────────────────────────────────────────────────


def test_start_gives_a_short_code_and_the_host_as_member(store):
    snapshot, gone = store.start(HOST, 'host')

    assert len(snapshot['code']) == CODE_LENGTH
    assert snapshot['members'] == [{'id': HOST, 'name': 'host', 'host': True}]
    assert gone == []
    assert store.get(HOST)['id'] == snapshot['id']


def test_join_accepts_a_sloppy_code_or_a_link(store):
    snapshot, _ = store.start(HOST, 'host')
    code = snapshot['code']
    link = f'https://castify.local/jam?code={code.lower()}&x=1'

    joined, _ = store.join(GUEST, 'guest', link)

    assert [m['id'] for m in joined['members']] == [HOST, GUEST]
    assert normalize_code(f' {code[:3].lower()}-{code[3:]} ') == code


def test_join_with_an_unknown_code_is_refused(store):
    with pytest.raises(JamError) as err:
        store.join(GUEST, 'guest', 'ZZZZZZ')

    assert err.value.status == 404


def test_joining_another_jam_leaves_the_first(store):
    first, _ = store.start(HOST, 'host')
    store.join(GUEST, 'guest', first['code'])
    second, _ = store.start(OTHER, 'other')

    store.join(GUEST, 'guest', second['code'])

    assert [m['id'] for m in store.get(HOST)['members']] == [HOST]
    assert store.get(GUEST)['id'] == second['id']


def test_the_host_leaving_ends_the_jam_for_everyone(store):
    _started(store)

    gone, remaining = store.leave(HOST)

    assert sorted(gone) == [HOST, GUEST]
    assert remaining == []
    assert store.get(GUEST) is None


def test_a_guest_leaving_keeps_the_jam(store):
    _started(store)

    gone, remaining = store.leave(GUEST)

    assert gone == [GUEST]
    assert remaining == [HOST]


def test_an_idle_jam_expires(store, clock):
    _started(store)
    clock.now += IDLE_SECONDS + 1

    assert store.get(HOST) is None


# ── queue ──────────────────────────────────────────────────────────────


def test_the_first_song_added_is_cued_not_played(store):
    _started(store)

    snapshot = store.add(GUEST, [_song('a'), _song('b')])

    assert snapshot['index'] == 0
    assert snapshot['playing'] is False
    assert snapshot['queue'][0]['added_by_name'] == 'guest'


def test_play_next_goes_right_after_the_current_song(store):
    _started(store)
    store.add(HOST, [_song('a'), _song('b')])
    store.control(HOST, 'jump', index=0)

    snapshot = store.add(GUEST, [_song('c')], position='next')

    assert [i['title'] for i in snapshot['queue']] == ['a', 'c', 'b']
    assert snapshot['index'] == 0


def test_adding_before_the_current_song_keeps_it_current(store):
    _started(store)
    store.add(HOST, [_song('a'), _song('b')])
    store.control(HOST, 'jump', index=1)

    snapshot = store.add(HOST, [_song('z')], position=0)

    assert snapshot['queue'][snapshot['index']]['title'] == 'b'


def test_add_and_play_jumps_to_the_new_song(store):
    _started(store)
    store.add(HOST, [_song('a')])

    snapshot = store.add(GUEST, [_song('b')], position='next', play=True)

    assert snapshot['queue'][snapshot['index']]['title'] == 'b'
    assert snapshot['playing'] is True


def test_a_guest_removes_only_their_own_songs_without_control(store):
    _started(store)
    store.configure(HOST, guests_can_control=False)
    hosts = store.add(HOST, [_song('a')])['queue'][0]['id']
    guests = store.add(GUEST, [_song('b')])['queue'][1]['id']

    with pytest.raises(JamError) as err:
        store.remove(GUEST, hosts)
    snapshot = store.remove(GUEST, guests)

    assert err.value.status == 403
    assert [i['title'] for i in snapshot['queue']] == ['a']


def test_removing_the_last_song_empties_the_jam(store):
    _started(store)
    item = store.add(HOST, [_song('a')])['queue'][0]['id']
    store.control(HOST, 'play')

    snapshot = store.remove(HOST, item)

    assert snapshot['index'] == -1
    assert snapshot['playing'] is False


def test_move_keeps_the_current_song_current(store):
    _started(store)
    queue = store.add(HOST, [_song('a'), _song('b'), _song('c')])['queue']
    store.control(HOST, 'jump', index=1)

    snapshot = store.move(HOST, queue[2]['id'], 0)

    assert [i['title'] for i in snapshot['queue']] == ['c', 'a', 'b']
    assert snapshot['queue'][snapshot['index']]['title'] == 'b'


def test_clear_drops_only_the_upcoming_songs(store):
    _started(store)
    store.add(HOST, [_song('a'), _song('b'), _song('c')])
    store.control(HOST, 'jump', index=1)

    snapshot = store.clear_upcoming(GUEST)

    assert [i['title'] for i in snapshot['queue']] == ['a', 'b']


# ── playback clock ─────────────────────────────────────────────────────


def test_the_position_follows_the_clock_while_playing(store, clock):
    _started(store)
    store.add(HOST, [_song('a', 100)])
    store.control(HOST, 'play')

    clock.now += 30
    assert store.get(GUEST)['position'] == pytest.approx(30)

    store.control(GUEST, 'pause')
    clock.now += 30
    assert store.get(GUEST)['position'] == pytest.approx(30)

    clock.now += 500
    store.control(HOST, 'play')
    clock.now += 500
    # Never past the end of the song.
    assert store.get(HOST)['position'] == pytest.approx(100)


def test_seek_is_clamped_to_the_song(store):
    _started(store)
    store.add(HOST, [_song('a', 100)])

    snapshot = store.control(HOST, 'seek', position=250)

    assert snapshot['position'] == pytest.approx(100)


def test_prev_restarts_the_song_after_a_few_seconds(store, clock):
    _started(store)
    store.add(HOST, [_song('a'), _song('b')])
    store.control(HOST, 'jump', index=1)

    clock.now += 10
    restarted = store.control(HOST, 'prev')
    back = store.control(HOST, 'prev')

    assert restarted['index'] == 1
    assert restarted['position'] == 0
    assert back['index'] == 0


def test_ended_moves_on_once_however_many_devices_report_it(store):
    _started(store)
    store.add(HOST, [_song('a'), _song('b')])
    store.control(HOST, 'play')

    first = store.control(GUEST, 'ended', from_index=0)
    second = store.control(HOST, 'ended', from_index=0)

    assert first['index'] == 1
    assert second is None
    assert store.get(HOST)['index'] == 1


def test_the_end_of_the_queue_stops_and_cues_the_next_song_added(store):
    _started(store)
    store.add(HOST, [_song('a')])
    store.control(HOST, 'play')

    done = store.control(HOST, 'ended', from_index=0)
    added = store.add(GUEST, [_song('b')])

    assert done['playing'] is False
    assert added['queue'][added['index']]['title'] == 'b'


def test_guests_need_permission_to_control(store):
    _started(store)
    store.add(HOST, [_song('a')])
    store.configure(HOST, guests_can_control=False)

    with pytest.raises(JamError) as err:
        store.control(GUEST, 'play')
    with pytest.raises(JamError) as setting:
        store.configure(GUEST, guests_can_control=True)

    assert err.value.status == 403
    assert setting.value.status == 403
    # Adding songs stays open to everyone.
    assert len(store.add(GUEST, [_song('b')])['queue']) == 2


def test_an_unknown_action_is_refused(store):
    _started(store)

    with pytest.raises(JamError) as err:
        store.control(HOST, 'rewind')

    assert err.value.status == 400


# ── routes ─────────────────────────────────────────────────────────────


class Sent:
    def __init__(self) -> None:
        self.frames: list[tuple[int, Any]] = []

    async def send_user(self, user_id: int, message: dict) -> None:
        self.frames.append((user_id, message['jam']))


@pytest.fixture
def client(monkeypatch, clock):
    sent = Sent()
    monkeypatch.setattr(jam_routes, 'store', JamStore(clock=clock))
    monkeypatch.setattr(api.state, 'connections', sent)
    monkeypatch.setattr(api, 'library_context', lambda: None)
    monkeypatch.setattr(
        jam_routes,
        'resolve_library_file',
        lambda file, ctx: None if file.startswith('missing') else file,
    )
    app = FastAPI()

    @app.middleware('http')
    async def sign_in(request: Request, call_next):
        uid = int(request.headers.get('x-user', '0'))
        if uid:
            request.scope.setdefault('state', {})['principal'] = Principal(
                'session', 'user', '', uid, f'user{uid}', 'user'
            )
        return await call_next(request)

    app.include_router(jam_routes.router)
    test = TestClient(app)
    test.sent = sent
    return test


def _as(uid: int) -> dict[str, str]:
    return {'x-user': str(uid)}


def test_routes_need_a_signed_in_user(client):
    assert client.get('/api/jam').status_code == 401


def test_routes_start_join_add_and_play_together(client):
    started = client.post('/api/jam', headers=_as(HOST)).json()['jam']
    joined = client.post(
        '/api/jam/join', json={'code': started['code']}, headers=_as(GUEST)
    )
    added = client.post(
        '/api/jam/queue',
        json={'tracks': [_song('a'), _song('missing')]},
        headers=_as(GUEST),
    )
    played = client.post(
        '/api/jam/control', json={'action': 'play'}, headers=_as(GUEST)
    )

    assert joined.status_code == 200
    assert [i['title'] for i in added.json()['jam']['queue']] == ['a']
    assert played.json()['jam']['playing'] is True
    # Every change reached both members.
    last = client.sent.frames[-2:]
    assert sorted(uid for uid, _ in last) == [HOST, GUEST]
    assert client.get('/api/jam', headers=_as(GUEST)).json()['jam']['playing']


def test_routes_refuse_songs_outside_the_library(client):
    client.post('/api/jam', headers=_as(HOST))

    res = client.post(
        '/api/jam/queue',
        json={'tracks': [_song('missing')]},
        headers=_as(HOST),
    )

    assert res.status_code == 400


def test_routes_tell_guests_the_jam_ended(client):
    started = client.post('/api/jam', headers=_as(HOST)).json()['jam']
    client.post(
        '/api/jam/join', json={'code': started['code']}, headers=_as(GUEST)
    )
    client.sent.frames.clear()

    client.post('/api/jam/leave', headers=_as(HOST))

    assert sorted(client.sent.frames) == [(HOST, None), (GUEST, None)]
    assert client.get('/api/jam', headers=_as(GUEST)).json() == {'jam': None}


def test_routes_report_a_guest_without_control(client):
    started = client.post('/api/jam', headers=_as(HOST)).json()['jam']
    client.post(
        '/api/jam/join', json={'code': started['code']}, headers=_as(GUEST)
    )
    client.patch(
        '/api/jam', json={'guests_can_control': False}, headers=_as(HOST)
    )

    res = client.post(
        '/api/jam/control', json={'action': 'next'}, headers=_as(GUEST)
    )

    assert res.status_code == 403
