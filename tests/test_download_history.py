"""The queue's finished downloads, kept across restarts."""

from __future__ import annotations

import asyncio

from downtify import api
from downtify.download_history import DownloadHistory, keep_ids


def _job(status: str = 'done', users=(5,), at: float = 1.0) -> dict:
    return {
        'song': {'song_id': 'x', 'name': 'Roads'},
        'status': status,
        'message': 'Done',
        'provider': 'youtube',
        'filename': 'Roads.mp3',
        'user_ids': set(users),
        'finished_at': at,
    }


def test_keep_ids_keeps_each_accounts_newest():
    rows = [('a', [1]), ('b', [1]), ('c', [2]), ('d', [1, 2]), ('e', [])]
    assert keep_ids(rows, keep=2) == {'a', 'b', 'c', 'd', 'e'}
    assert keep_ids(rows, keep=1) == {'a', 'c', 'e'}


def test_history_round_trips_and_prunes(tmp_path):
    store = DownloadHistory(tmp_path / 'lib.db', keep=2)
    for i in range(3):
        store.record(f's{i}', _job(at=float(i + 1)))
    store.record('err', _job('error', users=(7,), at=9.0))
    store.record('running', _job('downloading'))

    jobs = dict(store.jobs())
    # Account 5 keeps its two newest; account 7's failure stays.
    assert set(jobs) == {'s1', 's2', 'err'}
    assert jobs['s2']['status'] == 'done'
    assert jobs['s2']['user_ids'] == {5}
    assert jobs['s2']['filename'] == 'Roads.mp3'
    assert jobs['s2']['progress'] == 100
    assert jobs['err']['progress'] == 0
    assert [sid for sid, _ in store.jobs()][-1] == 'err'

    store.forget(['s1'])
    assert 's1' not in dict(store.jobs())
    store.clear()
    assert store.jobs() == []


def test_finished_jobs_come_back_after_a_restart(tmp_path, monkeypatch):
    store = DownloadHistory(tmp_path / 'lib.db')
    monkeypatch.setattr(api.state, 'download_history', store)
    monkeypatch.setattr(api.state, 'download_jobs', {})
    job = {**_job(), 'finished_at': None}
    api.state.download_jobs['song-1'] = job

    asyncio.run(api._remember_finished('song-1', job))
    assert job['finished_at']

    # A restart: memory is empty, the saved rows come back.
    api.state.download_jobs.clear()
    api.state.download_jobs['queued'] = {'status': 'queued'}
    assert api.restore_finished_jobs() == 1
    assert api.state.download_jobs['song-1']['status'] == 'done'
    assert 'queued' in api.state.download_jobs

    # Removing it from the queue removes it from the history.
    api._forget_history(['song-1'])
    assert store.jobs() == []


def test_a_job_taken_off_the_queue_is_not_kept(tmp_path, monkeypatch):
    store = DownloadHistory(tmp_path / 'lib.db')
    monkeypatch.setattr(api.state, 'download_history', store)
    monkeypatch.setattr(api.state, 'download_jobs', {})

    asyncio.run(api._remember_finished('gone', _job()))

    assert store.jobs() == []
