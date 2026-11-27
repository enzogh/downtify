"""Listening history: one row per play, per user (no network)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from downtify import api, discover_routes, listening_history
from downtify.auth import Principal
from downtify.discover import DiscoverStore
from downtify.listening_history import ListeningHistory, clean_play

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)


def _play(play_id: str, **extra: Any) -> dict[str, Any]:
    return {
        'play_id': play_id,
        'played_at': (NOW - timedelta(hours=1)).isoformat(),
        'artist': 'PLK',
        'title': 'Pas les mêmes',
        'played_s': 180,
        'duration_s': 200,
        **extra,
    }


@pytest.fixture
def store(tmp_path: Path) -> DiscoverStore:
    return DiscoverStore(tmp_path / 'library.db')


def test_clean_play_rejects_unusable_rows() -> None:
    assert clean_play({'play_id': 'a', 'artist': 'X'}, NOW) is None
    assert clean_play('nope', NOW) is None
    future = _play('a', played_at=(NOW + timedelta(days=1)).isoformat())
    assert clean_play(future, NOW) is None
    old = _play('a', played_at=(NOW - timedelta(days=400)).isoformat())
    assert clean_play(old, NOW) is None


def test_clean_play_normalises_fields() -> None:
    row = clean_play(
        _play(
            'a',
            played_at=int((NOW - timedelta(minutes=3)).timestamp() * 1000),
            source='weird',
            skipped=1,
            played_s='nan',
        ),
        NOW,
    )
    assert row is not None
    assert row['source'] == 'library'
    assert row['skipped'] == 1
    assert row['played_s'] == 0
    assert row['played_at'].startswith('2026-11-27T11:57')


def test_record_counts_a_play_id_once_per_user(store: DiscoverStore) -> None:
    history = store.history
    assert history.record([_play('p1'), _play('p2')], 1, NOW) == 2
    assert history.record([_play('p1')], 1, NOW) == 0
    # Another user may have the same id.
    assert history.record([_play('p1')], 2, NOW) == 1
    plays = history.plays(1, now=NOW)
    assert sorted(p['play_id'] for p in plays) == ['p1', 'p2']
    assert all(p['artist'] == 'PLK' for p in plays)
    assert history.plays(3, now=NOW) == []


def test_plays_newest_first_within_days(store: DiscoverStore) -> None:
    history = store.history
    history.record(
        [
            _play('old', played_at=(NOW - timedelta(days=40)).isoformat()),
            _play('new', played_at=(NOW - timedelta(days=1)).isoformat()),
            _play('mid', played_at=(NOW - timedelta(days=5)).isoformat()),
        ],
        1,
        NOW,
    )
    assert [p['play_id'] for p in history.plays(1, 30, now=NOW)] == [
        'new',
        'mid',
    ]
    assert len(history.plays(1, 90, now=NOW)) == 3
    assert history.plays(1, 90, limit=1, now=NOW)[0]['play_id'] == 'new'


def test_prune_keeps_the_newest(
    store: DiscoverStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(listening_history, 'MAX_ROWS', 3)
    plays = [
        _play(f'p{i}', played_at=(NOW - timedelta(hours=i)).isoformat())
        for i in range(1, 6)
    ]
    store.history.record(plays, 1, NOW)
    kept = [p['play_id'] for p in store.history.plays(1, now=NOW)]
    assert kept == ['p1', 'p2', 'p3']


def test_clear_and_remove_user(store: DiscoverStore) -> None:
    store.history.record([_play('a')], 1, NOW)
    store.history.record([_play('b')], 2, NOW)
    assert store.history.clear(1) == 1
    store.remove_user(2)
    assert store.history.plays(2, now=NOW) == []


def test_history_is_its_own_table(tmp_path: Path) -> None:
    store = DiscoverStore(tmp_path / 'library.db')
    again = ListeningHistory(store.db)
    again.record([_play('x')], 0, NOW)
    assert store.history.plays(0, now=NOW)[0]['play_id'] == 'x'


# Routes


def _request(user_id: int, payload: Any = None) -> Request:
    body = json.dumps(payload if payload is not None else {}).encode()

    async def receive() -> dict[str, Any]:
        return {'type': 'http.request', 'body': body, 'more_body': False}

    principal = Principal('device', 'client', '', user_id, 'user', 'user')
    return Request(
        {
            'type': 'http',
            'method': 'POST',
            'headers': [],
            'state': {'principal': principal},
        },
        receive,
    )


def test_routes_keep_plays_per_user(
    store: DiscoverStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api.state, 'discover', store)
    recent = datetime.now(timezone.utc) - timedelta(minutes=5)
    body = {'plays': [_play('r1', played_at=recent.isoformat())]}
    out = asyncio.run(discover_routes.record_plays_endpoint(_request(7, body)))
    assert out == {'recorded': 1}
    mine = asyncio.run(
        discover_routes.listening_history_endpoint(_request(7), 90, 100)
    )
    assert [p['play_id'] for p in mine['plays']] == ['r1']
    other = asyncio.run(
        discover_routes.listening_history_endpoint(_request(8), 90, 100)
    )
    assert other == {'plays': []}
    cleared = asyncio.run(discover_routes.clear_history_endpoint(_request(7)))
    assert cleared == {'cleared': 1}


def test_record_route_wants_a_list(
    store: DiscoverStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api.state, 'discover', store)
    with pytest.raises(HTTPException) as err:
        asyncio.run(
            discover_routes.record_plays_endpoint(_request(1, {'plays': 'x'}))
        )
    assert err.value.status_code == 400


# Admin panel


def test_summarize_adds_up_everyone() -> None:
    rows = [
        {**_play('a1', artist='PLK', title='A'), 'user_id': 1},
        {**_play('a2', artist='PLK', title='A'), 'user_id': 2},
        {
            **_play('a3', artist='Ninho', title='B', source='stream'),
            'user_id': 1,
        },
        {**_play('a4', artist='Ninho', title='C', skipped=1), 'user_id': 2},
    ]
    for row in rows:
        row['played_at'] = (NOW - timedelta(days=1)).isoformat()
    out = listening_history.summarize(rows, 7, {1: 'enzo', 2: 'sam'}, now=NOW)
    assert out['totals']['plays'] == 4
    assert out['totals']['listeners'] == 2
    assert out['totals']['skip_rate'] == 0.25
    assert out['totals']['stream_share'] == 0.25
    assert len(out['per_day']) == 7
    assert out['per_day'][-1]['plays'] == 0
    assert out['per_day'][-2]['plays'] == 4
    assert out['top_artists'][0] == {
        'artist': 'PLK',
        'plays': 2,
        'listeners': 2,
    }
    # A skip doesn't count towards the top songs.
    assert [s['title'] for s in out['top_songs']] == ['A', 'B']
    assert {u['username'] for u in out['users']} == {'enzo', 'sam'}
    assert out['recent'][0]['username'] == 'enzo'


def test_everyone_reads_all_users(store: DiscoverStore) -> None:
    store.history.record([_play('x')], 1, NOW)
    store.history.record([_play('y')], 2, NOW)
    rows = store.history.everyone(30, now=NOW)
    assert sorted(row['user_id'] for row in rows) == [1, 2]


def test_admin_listening_route(
    store: DiscoverStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api.state, 'discover', store)
    monkeypatch.setattr(api.state, 'auth', None)
    recent = datetime.now(timezone.utc) - timedelta(minutes=5)
    store.history.record([_play('r', played_at=recent.isoformat())], 3)
    out = asyncio.run(discover_routes.admin_listening_endpoint(7))
    assert out['totals']['plays'] == 1
    assert out['users'][0]['user_id'] == 3
