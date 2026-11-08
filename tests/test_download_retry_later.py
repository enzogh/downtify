"""A download YouTube blocks is queued again for later, not failed.

The downloader is a stub and ``asyncio.sleep`` is faked: nothing waits
and nothing reaches the network."""

from __future__ import annotations

import asyncio

import pytest

from downtify import api

BOT = 'ERROR: [youtube] x: Sign in to confirm you’re not a bot.'
REFUSED = 'ERROR: unable to download video data: HTTP Error 403: Forbidden'


class _StubDownloader:
    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = 0

    def download(self, song, progress_cb, subdir=None):
        self.calls += 1
        if self.errors:
            raise RuntimeError(self.errors.pop(0))
        return f'{song["song_id"]}.mp3'


@pytest.fixture
def run(monkeypatch):
    sent: list[dict] = []
    sleeps: list[float] = []

    async def fake_broadcast(_msg):
        return None

    async def fake_broadcast_job(_users, msg):
        sent.append(msg)

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    async def fake_remember(_rows):
        return None

    monkeypatch.setattr(api.state.connections, 'broadcast', fake_broadcast)
    monkeypatch.setattr(
        api.state.connections, 'broadcast_job', fake_broadcast_job
    )
    monkeypatch.setattr(api.state, 'download_semaphore', None)
    monkeypatch.setattr(api.asyncio, 'sleep', fake_sleep)
    monkeypatch.setattr(api, '_remember_pending', fake_remember)
    monkeypatch.setattr(api, '_forget_pending', fake_remember)

    def start(errors):
        stub = _StubDownloader(errors)
        monkeypatch.setattr(api.state, 'downloader', stub)
        monkeypatch.setitem(
            api.state.download_jobs, 'abc', {'status': 'queued'}
        )
        result = None
        error = None
        try:
            result = asyncio.run(api._run_download({'song_id': 'abc'}, 'abc'))
        except RuntimeError as exc:
            error = exc
        return result, error, stub, sent, sleeps

    return start


def test_a_blocked_download_is_queued_again_and_succeeds(run):
    result, error, stub, sent, sleeps = run([BOT, REFUSED])
    assert error is None
    assert result == 'abc.mp3'
    assert stub.calls == 3
    assert sleeps == list(api.DEFERRED_RETRY_DELAYS_SECONDS[:2])
    statuses = [m['status'] for m in sent]
    # The user never sees an error, only the song waiting again.
    assert 'error' not in statuses
    assert statuses.count('queued') == 2
    assert statuses[-1] == 'done'


def test_a_block_that_lasts_ends_in_an_error(run):
    tries = len(api.DEFERRED_RETRY_DELAYS_SECONDS) + 1
    result, error, stub, sent, sleeps = run([BOT] * tries)
    assert result is None
    assert error is not None
    assert stub.calls == tries
    assert sleeps == list(api.DEFERRED_RETRY_DELAYS_SECONDS)
    assert sent[-1]['status'] == 'error'


def test_other_failures_are_not_retried(run):
    result, error, stub, sent, sleeps = run(['Video unavailable'])
    assert error is not None
    assert stub.calls == 1
    assert sleeps == []
    assert sent[-1]['status'] == 'error'


def test_a_song_removed_while_waiting_is_not_tried_again(run, monkeypatch):
    async def drop_then_wait(seconds):
        api.state.download_jobs.pop('abc', None)

    monkeypatch.setattr(api, '_sleep_before_retry', drop_then_wait)
    result, error, stub, _sent, _sleeps = run([BOT])
    assert error is None
    assert result is None
    assert stub.calls == 1
