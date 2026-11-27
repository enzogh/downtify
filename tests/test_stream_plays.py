from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from downtify import api, stream_plays
from downtify.stream_plays import StreamPlays

VID = 'dQw4w9WgXcQ'


def test_queues_once_at_threshold(tmp_path, monkeypatch):
    store = StreamPlays(tmp_path / 'lib.db')
    clock = iter([0, 10, 100, 200, 300])
    monkeypatch.setattr(stream_plays.time, 'time', lambda: next(clock))

    # 10 s after the first start: the same play, not counted.
    assert [store.record('vid', 3) for _ in range(5)] == [
        False,
        False,
        False,
        True,
        False,
    ]
    assert store.plays('vid') == 4
    assert stream_plays.is_play_start('GET', 'bytes=0-')
    assert not stream_plays.is_play_start('GET', 'bytes=5000-')
    assert not stream_plays.is_play_start('HEAD', None)
    assert stream_plays.clamp_threshold('500') == 100
    assert stream_plays.clamp_threshold('x') == 0


def test_status_reports_plays_and_queueing(tmp_path, monkeypatch):
    store = StreamPlays(tmp_path / 'lib.db')
    clock = iter([0, 100])
    monkeypatch.setattr(stream_plays.time, 'time', lambda: next(clock))

    assert store.status(VID) == (0, False)
    store.record(VID, 2)
    assert store.status(VID) == (1, False)
    store.record(VID, 2)
    assert store.status(VID) == (2, True)


@pytest.fixture
def plays_client(tmp_path, monkeypatch):
    store = StreamPlays(tmp_path / 'lib.db')
    monkeypatch.setattr(api.state, 'stream_plays', store)
    monkeypatch.setattr(api.state, 'downloader', object())
    monkeypatch.setattr(
        api.state,
        'settings',
        {**api.state.settings, 'auto_download_after_plays': 3},
    )
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app), store


def test_plays_endpoint_tells_how_close_a_song_is(plays_client):
    client, store = plays_client
    store.record(VID, 3)

    response = client.get(f'/api/stream/live/plays?video_id={VID}')

    assert response.status_code == 200
    assert response.json() == {'plays': 1, 'threshold': 3, 'queued': False}


def test_plays_endpoint_says_off_without_a_downloader(
    plays_client, monkeypatch
):
    client, _ = plays_client
    monkeypatch.setattr(api.state, 'downloader', None)

    body = client.get(f'/api/stream/live/plays?video_id={VID}').json()

    assert body['threshold'] == 0


def test_plays_endpoint_refuses_a_malformed_id(plays_client):
    client, _ = plays_client
    assert client.get('/api/stream/live/plays?video_id=bad').status_code == 400
