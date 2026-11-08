"""Request pacing of YouTube downloads (downtify.downloader).

Downloads run unpaced until YouTube answers ``429`` or its bot check;
then the song is retried once, paced, and every download stays paced
for a while.
yt-dlp never runs: its client is faked."""

from __future__ import annotations

from pathlib import Path

import pytest

from downtify import downloader as downloader_mod
from downtify import ip_rotation
from downtify.downloader import (
    RATE_LIMIT_PACING_SECONDS,
    RATE_LIMIT_PACING_WINDOW_SECONDS,
    Downloader,
    is_rate_limited_error,
    note_rate_limited,
    request_pacing_seconds,
    yt_extractor_args,
)
from downtify.ip_rotation import MAX_ROTATIONS_PER_ATTEMPT

_SONG = {'name': 'Urus', 'artists': ['Favé']}
_429 = 'ERROR: [youtube] x: HTTP Error 429: Too Many Requests'
_BOT = (
    'ERROR: [youtube] x: Sign in to confirm you\u2019re not a bot. '
    'Use --cookies-from-browser or --cookies for the authentication.'
)


class _FakeYoutubeDL:
    """Records each run's options; raises the queued errors in order."""

    runs: list[dict] = []
    errors: list[Exception] = []

    def __init__(self, opts):
        self.opts = dict(opts)
        # The audio-extraction postprocessor reads its options here.
        self.params = self.opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def add_post_processor(self, pp, when=None):
        self.opts.setdefault('post_processors', []).append((pp, when))

    def download(self, urls):
        _FakeYoutubeDL.runs.append(self.opts)
        if _FakeYoutubeDL.errors:
            raise _FakeYoutubeDL.errors.pop(0)
        target = Path(self.opts['outtmpl'].replace('%(ext)s', 'flac'))
        target.write_bytes(b'fLaC')


@pytest.fixture
def fake_ydl(monkeypatch):
    _FakeYoutubeDL.runs = []
    _FakeYoutubeDL.errors = []
    monkeypatch.setattr(downloader_mod.yt_dlp, 'YoutubeDL', _FakeYoutubeDL)
    monkeypatch.setattr(downloader_mod, '_paced_until', 0.0)
    monkeypatch.delenv('DOWNTIFY_YT_SLEEP_REQUESTS', raising=False)
    monkeypatch.delenv('DOWNTIFY_IP_ROTATE_URL', raising=False)
    return _FakeYoutubeDL


def _fetch(tmp_path: Path) -> Path:
    d = Downloader(tmp_path, audio_format='flac')
    return d.fetch_audio('cmQohyB8YjE', tmp_path, 'Urus', song=_SONG)


def test_downloads_are_not_paced_by_default(tmp_path, fake_ydl):
    assert _fetch(tmp_path).name == 'Urus.flac'
    [opts] = fake_ydl.runs
    assert 'sleep_interval_requests' not in opts


def test_a_rate_limit_retries_once_paced_and_keeps_pacing(tmp_path, fake_ydl):
    fake_ydl.errors = [RuntimeError(_429)]
    assert _fetch(tmp_path).name == 'Urus.flac'
    first, second = fake_ydl.runs
    assert 'sleep_interval_requests' not in first
    assert second['sleep_interval_requests'] == RATE_LIMIT_PACING_SECONDS
    # The next song is paced from the start.
    fake_ydl.runs = []
    _fetch(tmp_path)
    [opts] = fake_ydl.runs
    assert opts['sleep_interval_requests'] == RATE_LIMIT_PACING_SECONDS


def test_a_paced_rate_limit_is_not_retried_again(tmp_path, fake_ydl):
    note_rate_limited()
    fake_ydl.errors = [RuntimeError(_429)]
    with pytest.raises(RuntimeError):
        _fetch(tmp_path)
    assert len(fake_ydl.runs) == 1


def test_other_errors_are_not_retried(tmp_path, fake_ydl):
    fake_ydl.errors = [RuntimeError('ERROR: Video unavailable')]
    with pytest.raises(RuntimeError):
        _fetch(tmp_path)
    assert len(fake_ydl.runs) == 1


def test_pacing_ends_after_its_window(monkeypatch):
    monkeypatch.setattr(downloader_mod, '_paced_until', 0.0)
    monkeypatch.delenv('DOWNTIFY_YT_SLEEP_REQUESTS', raising=False)
    note_rate_limited(now=1000.0)
    assert request_pacing_seconds(now=1001.0) == RATE_LIMIT_PACING_SECONDS
    end = 1000.0 + RATE_LIMIT_PACING_WINDOW_SECONDS
    assert request_pacing_seconds(now=end) == 0.0


@pytest.mark.parametrize(('raw', 'expected'), [('2', 2.0), ('0', 0.0)])
def test_env_forces_pacing_either_way(monkeypatch, raw, expected):
    monkeypatch.setattr(downloader_mod, '_paced_until', 10.0**12)
    monkeypatch.setenv('DOWNTIFY_YT_SLEEP_REQUESTS', raw)
    assert request_pacing_seconds(now=0.0) == expected


def test_unreadable_env_falls_back_to_adaptive(monkeypatch):
    monkeypatch.setattr(downloader_mod, '_paced_until', 0.0)
    monkeypatch.setenv('DOWNTIFY_YT_SLEEP_REQUESTS', 'fast')
    assert request_pacing_seconds(now=0.0) == 0.0


def test_rate_limit_detection():
    assert is_rate_limited_error(_429)
    assert is_rate_limited_error('Too many requests, slow down')
    assert not is_rate_limited_error('ERROR: Video unavailable')


@pytest.mark.parametrize(
    'message',
    [_BOT, "Sign in to confirm you're not a bot", _429],
)
def test_the_bot_check_counts_as_a_rate_limit(message):
    assert is_rate_limited_error(message)


def test_a_bot_check_retries_once_paced(tmp_path, fake_ydl):
    fake_ydl.errors = [RuntimeError(_BOT)]
    assert _fetch(tmp_path).name == 'Urus.flac'
    first, second = fake_ydl.runs
    assert 'sleep_interval_requests' not in first
    assert second['sleep_interval_requests'] == RATE_LIMIT_PACING_SECONDS


def test_extractor_args_use_the_po_token_server_when_set(monkeypatch):
    monkeypatch.setenv('DOWNTIFY_POT_PROVIDER_URL', 'http://bgutil:4416')
    monkeypatch.setenv('DOWNTIFY_YT_PO_TOKEN', 'mweb.gvs+ABC')
    args = yt_extractor_args()
    assert args['youtubepot-bgutilhttp'] == {
        'base_url': ['http://bgutil:4416']
    }
    assert args['youtube']['po_token'] == ['mweb.gvs+ABC']
    assert args['youtube']['player_client']


def test_extractor_args_skip_the_po_token_server_by_default(monkeypatch):
    monkeypatch.delenv('DOWNTIFY_POT_PROVIDER_URL', raising=False)
    monkeypatch.delenv('DOWNTIFY_YT_PO_TOKEN', raising=False)
    args = yt_extractor_args()
    assert set(args) == {'youtube'}
    assert 'po_token' not in args['youtube']


def test_downloads_pass_the_shared_extractor_args(
    tmp_path, fake_ydl, monkeypatch
):
    monkeypatch.setenv('DOWNTIFY_POT_PROVIDER_URL', 'http://bgutil:4416')
    _fetch(tmp_path)
    [opts] = fake_ydl.runs
    assert 'youtubepot-bgutilhttp' in opts['extractor_args']


@pytest.fixture
def rotations(monkeypatch):
    calls: list[str] = []
    monkeypatch.setenv('DOWNTIFY_IP_ROTATE_URL', 'http://warp:8081/rotate')
    monkeypatch.setattr(ip_rotation, '_generation', 0)
    monkeypatch.setattr(ip_rotation, '_recent', ip_rotation.deque())
    monkeypatch.setattr(ip_rotation, '_post_rotation', calls.append)
    return calls


def test_a_bot_check_gets_a_new_ip_and_retries(tmp_path, fake_ydl, rotations):
    fake_ydl.errors = [RuntimeError(_BOT), RuntimeError(_BOT)]
    assert _fetch(tmp_path).name == 'Urus.flac'
    assert len(rotations) == 2
    assert len(fake_ydl.runs) == 3


def test_a_429_does_not_rotate_the_ip(tmp_path, fake_ydl, rotations):
    fake_ydl.errors = [RuntimeError(_429)]
    assert _fetch(tmp_path).name == 'Urus.flac'
    assert rotations == []


def test_downloads_give_up_when_no_new_ip_helps(tmp_path, fake_ydl, rotations):
    fake_ydl.errors = [RuntimeError(_BOT)] * 10
    with pytest.raises(RuntimeError):
        _fetch(tmp_path)
    assert len(rotations) == MAX_ROTATIONS_PER_ATTEMPT
