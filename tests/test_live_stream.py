"""Tests for live streaming (downtify.live_stream) and
``GET /api/stream/live``. YouTube is never reached: the resolver and
the upstream opener are fakes serving bytes from memory."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from downtify import api, live_stream
from downtify.live_stream import (
    LiveSource,
    LiveStreams,
    RangeNotSatisfiable,
    UpstreamExpired,
    parse_content_range,
    parse_range,
    url_expiry,
)

VID = 'dQw4w9WgXcQ'
AUDIO = bytes(range(256)) * 40  # 10240 bytes


class FakeUpstream:
    """Serves ``AUDIO`` by byte range, recording every request."""

    def __init__(self, data: bytes = AUDIO, *, expired: int = 0) -> None:
        self.data = data
        self.calls: list[tuple[str, int, int]] = []
        self.expired = expired
        self.closed = 0

    def __call__(self, source: LiveSource, start: int, end: int):
        self.calls.append((source.url, start, end))
        if self.expired:
            self.expired -= 1
            raise UpstreamExpired('YouTube answered 403')
        if start >= len(self.data):
            raise RangeNotSatisfiable(len(self.data))
        end = min(end, len(self.data) - 1)
        body = self.data[start : end + 1]
        pos = {'at': 0}

        def read(n: int) -> bytes:
            piece = body[pos['at'] : pos['at'] + n]
            pos['at'] += len(piece)
            return piece

        def close() -> None:
            self.closed += 1

        return f'bytes {start}-{end}/{len(self.data)}', read, close


def _resolver(filesize: int = 0, duration: float = 200.0):
    calls: list[str] = []

    def resolve(video_id: str, *, cookies_file: str = '') -> LiveSource:
        calls.append(video_id)
        return LiveSource(
            url=f'https://rr.googlevideo.com/{video_id}/{len(calls)}',
            ext='m4a',
            filesize=filesize,
            duration=duration,
            expires_at=10**12,
        )

    resolve.calls = calls
    return resolve


def _streams(upstream=None, resolver=None, **kwargs) -> LiveStreams:
    return LiveStreams(
        resolver=resolver or _resolver(),
        opener=upstream or FakeUpstream(),
        **kwargs,
    )


def _drain(streams: LiveStreams, header, **kwargs):
    relayed = asyncio.run(streams.open(VID, header, **kwargs))
    return relayed, b''.join(relayed.body)


# ── parsing ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('header', 'expected'),
    [
        (None, None),
        ('', None),
        ('bytes=0-', (0, None)),
        ('bytes=100-199', (100, 199)),
        ('bytes=-500', (-500, None)),
        ('bytes=9-3', None),
        ('items=0-1', None),
        ('bytes=0-1,5-9', None),
    ],
)
def test_parse_range(header, expected):
    assert parse_range(header) == expected


def test_parse_content_range():
    assert parse_content_range('bytes 0-99/1000') == (0, 99, 1000)
    assert parse_content_range('bytes 0-99/*') == (0, 99, -1)
    assert parse_content_range(None) is None


def test_url_expiry_follows_youtube_expire_with_a_margin():
    url = 'https://rr.googlevideo.com/videoplayback?expire=10000&x=1'
    assert (
        url_expiry(url, now=1000) == 10000 - live_stream.EXPIRY_MARGIN_SECONDS
    )


def test_url_expiry_defaults_without_expire():
    assert url_expiry('https://x/y', now=0) == live_stream.DEFAULT_TTL_SECONDS


def test_url_expiry_is_capped():
    url = 'https://x/y?expire=99999999999'
    assert url_expiry(url, now=0) == live_stream.MAX_TTL_SECONDS


# ── relay ───────────────────────────────────────────────────────────


def test_whole_track_without_range_is_a_200():
    relayed, body = _drain(_streams(), None)
    assert relayed.status == 200
    assert body == AUDIO
    assert relayed.headers['Content-Length'] == str(len(AUDIO))
    assert relayed.headers['Accept-Ranges'] == 'bytes'
    assert 'Content-Range' not in relayed.headers
    assert relayed.media_type == 'audio/mp4'


def test_open_range_is_a_206_with_content_range():
    relayed, body = _drain(_streams(), 'bytes=1000-')
    assert relayed.status == 206
    assert body == AUDIO[1000:]
    assert relayed.headers['Content-Range'] == (
        f'bytes 1000-{len(AUDIO) - 1}/{len(AUDIO)}'
    )


def test_bounded_range():
    relayed, body = _drain(_streams(), 'bytes=10-19')
    assert body == AUDIO[10:20]
    assert relayed.headers['Content-Length'] == '10'


def test_suffix_range_probes_the_size_first():
    relayed, body = _drain(_streams(), 'bytes=-100')
    assert body == AUDIO[-100:]
    assert relayed.headers['Content-Range'].startswith(
        f'bytes {len(AUDIO) - 100}-'
    )


def test_upstream_is_read_in_slices(monkeypatch):
    monkeypatch.setattr(live_stream, 'UPSTREAM_CHUNK_BYTES', 4096)
    monkeypatch.setattr(live_stream, 'RELAY_PIECE_BYTES', 1000)
    upstream = FakeUpstream()
    _relayed, body = _drain(_streams(upstream), 'bytes=0-')
    assert body == AUDIO
    assert [(s, e) for _u, s, e in upstream.calls] == [
        (0, 4095),
        (4096, 8191),
        (8192, 10239),
    ]
    assert upstream.closed == 3


def test_range_past_the_end_is_refused():
    streams = _streams(resolver=_resolver(filesize=len(AUDIO)))
    with pytest.raises(RangeNotSatisfiable):
        asyncio.run(streams.open(VID, f'bytes={len(AUDIO)}-'))


def test_expired_url_is_resolved_again_once():
    resolver = _resolver()
    upstream = FakeUpstream(expired=1)
    _relayed, body = _drain(_streams(upstream, resolver), None)
    assert body == AUDIO
    assert len(resolver.calls) == 2
    assert upstream.calls[0][0] != upstream.calls[1][0]


def test_expired_twice_gives_up():
    streams = _streams(FakeUpstream(expired=2))
    with pytest.raises(UpstreamExpired):
        asyncio.run(streams.open(VID, None))


def _fresh_resolver(now: dict):
    calls: list[str] = []

    def resolve(video_id: str, *, cookies_file: str = '') -> LiveSource:
        calls.append(video_id)
        return LiveSource(
            url=f'https://rr.googlevideo.com/{video_id}/{len(calls)}',
            ext='m4a',
            expires_at=10**12,
            resolved_at=now['t'],
        )

    resolve.calls = calls
    return resolve


def _recorded_sleeps():
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    return waits, sleep


def test_a_fresh_url_refused_is_retried_not_resolved_again():
    now = {'t': 1000.0}
    resolver = _fresh_resolver(now)
    waits, sleep = _recorded_sleeps()
    streams = _streams(
        FakeUpstream(expired=2),
        resolver,
        clock=lambda: now['t'],
        sleep=sleep,
    )
    _relayed, body = _drain(streams, None)
    assert body == AUDIO
    assert len(resolver.calls) == 1
    assert waits == [
        live_stream.FRESH_REFUSAL_DELAY_SECONDS,
        live_stream.FRESH_REFUSAL_DELAY_SECONDS * 2,
    ]


def test_a_fresh_url_refused_too_often_is_resolved_again():
    now = {'t': 1000.0}
    resolver = _fresh_resolver(now)
    _waits, sleep = _recorded_sleeps()
    streams = _streams(
        FakeUpstream(expired=live_stream.MAX_FRESH_REFUSALS + 1),
        resolver,
        clock=lambda: now['t'],
        sleep=sleep,
    )
    _relayed, body = _drain(streams, None)
    assert body == AUDIO
    assert len(resolver.calls) == 2


def test_an_old_url_refused_is_resolved_again_at_once():
    now = {'t': 1000.0}
    resolver = _fresh_resolver(now)
    waits, sleep = _recorded_sleeps()
    streams = _streams(
        FakeUpstream(),
        resolver,
        clock=lambda: now['t'],
        sleep=sleep,
    )
    asyncio.run(streams.source(VID))
    now['t'] += live_stream.FRESH_SOURCE_SECONDS + 1
    streams._opener = FakeUpstream(expired=1)
    _drain(streams, None)
    assert waits == []
    assert len(resolver.calls) == 2


def test_the_relay_waits_until_youtube_serves_the_url():
    now = {'t': 1000.0}

    def resolve(video_id: str, *, cookies_file: str = '') -> LiveSource:
        return LiveSource(
            url='https://rr.googlevideo.com/x',
            ext='m4a',
            expires_at=10**12,
            resolved_at=now['t'],
            available_at=now['t'] + 1.5,
        )

    waits, sleep = _recorded_sleeps()
    streams = _streams(
        FakeUpstream(), resolve, clock=lambda: now['t'], sleep=sleep
    )
    _relayed, body = _drain(streams, None)
    assert body == AUDIO
    assert waits == [1.5]


def test_available_at_is_read_from_the_chosen_format():
    info = {
        'format_id': '140',
        'formats': [
            {'format_id': '251', 'available_at': 5},
            {'format_id': '140', 'available_at': 1234},
        ],
    }
    assert live_stream._available_at(info) == 1234
    assert live_stream._available_at({'format_id': '140'}) == 0


def test_live_resolve_asks_the_quick_clients_first(monkeypatch):
    monkeypatch.delenv('DOWNTIFY_LIVE_PLAYER_CLIENTS', raising=False)
    seen: list[list[str]] = []
    info = {'url': 'https://rr.googlevideo.com/videoplayback', 'ext': 'm4a'}

    class FakeYdl:
        def __init__(self, opts):
            seen.append(opts['extractor_args']['youtube']['player_client'])

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        @staticmethod
        def extract_info(url, download):
            return info

    monkeypatch.setattr(live_stream.yt_dlp, 'YoutubeDL', FakeYdl)
    live_stream.resolve_live_source(VID)
    assert seen == [list(live_stream.DEFAULT_LIVE_PLAYER_CLIENTS)]


def test_live_resolve_falls_back_to_every_client(monkeypatch):
    monkeypatch.setenv('DOWNTIFY_LIVE_PLAYER_CLIENTS', 'web_embedded')
    seen: list[list[str]] = []
    info = {'url': 'https://rr.googlevideo.com/videoplayback', 'ext': 'm4a'}

    class FakeYdl:
        def __init__(self, opts):
            self.clients = opts['extractor_args']['youtube']['player_client']
            seen.append(self.clients)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download):
            if self.clients == ['web_embedded']:
                raise RuntimeError('Requested format is not available')
            return info

    monkeypatch.setattr(live_stream.yt_dlp, 'YoutubeDL', FakeYdl)
    source = live_stream.resolve_live_source(VID)
    assert source.url == info['url']
    assert seen[0] == ['web_embedded']
    assert len(seen[1]) > 1


def test_relayed_bytes_are_counted():
    counted: list[int] = []
    _drain(_streams(), 'bytes=0-99', on_bytes=counted.append)
    assert counted == [100]


def test_source_is_remembered_until_it_expires():
    now = {'t': 0.0}
    resolver = _resolver()
    streams = _streams(resolver=resolver, clock=lambda: now['t'])

    async def twice():
        await streams.source(VID)
        await streams.source(VID)

    asyncio.run(twice())
    assert len(resolver.calls) == 1
    now['t'] = 10.0**13
    asyncio.run(streams.source(VID))
    assert len(resolver.calls) == 2


def test_concurrent_requests_share_one_resolution():
    resolver = _resolver()
    streams = _streams(resolver=resolver)

    async def together():
        await asyncio.gather(*(streams.source(VID) for _ in range(5)))

    asyncio.run(together())
    assert len(resolver.calls) == 1


def test_malformed_video_id_is_refused():
    with pytest.raises(ValueError, match='video id'):
        asyncio.run(_streams().source('nope'))


def test_resolver_reads_the_direct_url_without_downloading():
    info = {
        'url': 'https://rr.googlevideo.com/videoplayback?expire=99',
        'ext': 'm4a',
        'filesize': 1234,
        'duration': 201,
        'http_headers': {'User-Agent': 'UA'},
    }
    client = MagicMock()
    client.__enter__.return_value.extract_info.return_value = info
    client.__exit__.return_value = False
    with patch('downtify.live_stream.yt_dlp.YoutubeDL', return_value=client):
        source = live_stream.resolve_live_source(VID, cookies_file='/c.txt')
    kwargs = client.__enter__.return_value.extract_info.call_args.kwargs
    assert kwargs == {'download': False}
    assert source.filesize == 1234
    assert source.duration == 201
    assert source.headers == {'User-Agent': 'UA'}


# ── endpoint ────────────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api.state, 'live_streams', _streams())
    monkeypatch.setattr(api.state, 'cookies_store', None)
    monkeypatch.setattr(api, '_max_track_duration_seconds', lambda: 600)
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_endpoint_streams_the_whole_track(client):
    response = client.get(f'/api/stream/live?video_id={VID}')
    assert response.status_code == 200
    assert response.content == AUDIO
    assert response.headers['content-type'] == 'audio/mp4'
    assert response.headers['accept-ranges'] == 'bytes'


def test_endpoint_honours_range(client):
    response = client.get(
        f'/api/stream/live?video_id={VID}', headers={'Range': 'bytes=5-9'}
    )
    assert response.status_code == 206
    assert response.content == AUDIO[5:10]
    assert response.headers['content-range'] == f'bytes 5-9/{len(AUDIO)}'


def test_endpoint_head_sends_no_body(client):
    response = client.head(f'/api/stream/live?video_id={VID}')
    assert response.status_code == 200
    assert response.content == b''
    assert response.headers['content-length'] == str(len(AUDIO))


def test_endpoint_refuses_malformed_ids(client):
    assert client.get('/api/stream/live?video_id=bad').status_code == 400


def test_endpoint_refuses_a_known_long_duration(client):
    url = f'/api/stream/live?video_id={VID}&duration=601'
    assert client.get(url).status_code == 400


def test_endpoint_refuses_a_resolved_long_track(client, monkeypatch):
    monkeypatch.setattr(
        api.state, 'live_streams', _streams(resolver=_resolver(duration=900))
    )
    assert client.get(f'/api/stream/live?video_id={VID}').status_code == 400


def test_endpoint_maps_range_past_end_to_416(client, monkeypatch):
    monkeypatch.setattr(
        api.state,
        'live_streams',
        _streams(resolver=_resolver(filesize=len(AUDIO))),
    )
    response = client.get(
        f'/api/stream/live?video_id={VID}', headers={'Range': 'bytes=99999-'}
    )
    assert response.status_code == 416
    assert response.headers['content-range'] == f'bytes */{len(AUDIO)}'


def test_endpoint_maps_youtube_failures_to_503(client, monkeypatch):
    def refuse(video_id, *, cookies_file=''):
        raise ValueError('YouTube did not answer: Boom')

    monkeypatch.setattr(api.state, 'live_streams', _streams(resolver=refuse))
    response = client.get(f'/api/stream/live?video_id={VID}')
    assert response.status_code == 503
    assert 'YouTube' in response.json()['detail']


def test_prefetch_resolves_in_the_background(client, monkeypatch):
    spawned: list[str] = []

    def spawn(coro, *, name=None):
        spawned.append(name)
        coro.close()

    monkeypatch.setattr(api, 'spawn_task', spawn)
    response = client.post('/api/stream/live/prefetch', json={'video_id': VID})
    assert response.json() == {'queued': True}
    assert spawned == [f'stream-live-prefetch-{VID}']


def test_prefetch_refuses_malformed_ids(client):
    response = client.post('/api/stream/live/prefetch', json={'video_id': 'x'})
    assert response.status_code == 400
