"""Searching a batch's next songs while the current ones download."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from downtify import api
from downtify import downloader as downloader_mod
from downtify.downloader import Downloader
from downtify.search_ahead import PreparedSong, SearchAhead, search_key

_SONG = {
    'song_id': 'sp1',
    'source': 'spotify',
    'name': 'Song',
    'artists': ['Artist'],
    'album_name': 'Album',
    'cover_url': 'https://example.com/cover.jpg',
}


def _downloader(tmp_path: Path, monkeypatch, **kwargs) -> Downloader:
    monkeypatch.setattr(
        downloader_mod.spotify_mod,
        'enrich_track_from_spotify_if_sparse',
        lambda song, **_: {**song, 'year': '2024'},
    )
    monkeypatch.setattr(
        downloader_mod.deezer_mod,
        'enrich_track_from_deezer_if_sparse',
        lambda song: song,
    )
    monkeypatch.setattr(
        downloader_mod, 'enrich_from_match', lambda song, _match: song
    )
    d = Downloader(tmp_path, **kwargs)
    fetched: list[tuple[str, dict[str, Any]]] = []

    def _fetch_and_tag(song, video_id, *_args, **_kwargs):
        fetched.append((video_id, song))
        return 'Artist - Song.mp3'

    d._fetch_and_tag = _fetch_and_tag
    d.fetched = fetched
    return d


def _searched_ahead(d: Downloader, song: dict[str, Any]) -> bool:
    """Search *song* ahead and wait for the search to end."""

    with ThreadPoolExecutor(max_workers=1) as pool:
        d.search_ahead = SearchAhead(pool)
        return d.search_ahead_for(song)


def _count_searches(monkeypatch) -> list[str]:
    searches: list[str] = []

    def _find_match(song):
        searches.append(song['name'])
        return 'vid00000001', {'videoId': 'vid00000001', 'title': 'Song'}

    monkeypatch.setattr(downloader_mod, 'find_match', _find_match)
    return searches


def test_download_uses_the_song_searched_ahead(tmp_path, monkeypatch):
    searches = _count_searches(monkeypatch)
    d = _downloader(tmp_path, monkeypatch)

    assert _searched_ahead(d, _SONG)
    assert d.download(dict(_SONG)) == 'Artist - Song.mp3'

    assert searches == ['Song']
    video_id, song = d.fetched[0]
    assert video_id == 'vid00000001'
    # The enrichment done ahead is what gets tagged.
    assert song['year'] == '2024'
    assert len(d.search_ahead) == 0


def test_changed_audio_sources_search_again(tmp_path, monkeypatch):
    searches = _count_searches(monkeypatch)
    d = _downloader(tmp_path, monkeypatch)

    assert _searched_ahead(d, _SONG)
    d.audio_providers = ['youtube-music', 'soundcloud']
    d.download(dict(_SONG))

    assert searches == ['Song', 'Song']


def test_only_when_youtube_is_the_first_source(tmp_path, monkeypatch):
    _count_searches(monkeypatch)
    slskd_first = _downloader(
        tmp_path,
        monkeypatch,
        audio_providers=['slskd', 'youtube-music'],
        slskd_settings={'enabled': True},
    )
    assert not slskd_first.search_ahead_for(_SONG)

    slskd_off = _downloader(
        tmp_path,
        monkeypatch,
        audio_providers=['slskd', 'youtube-music'],
        slskd_settings={'enabled': False},
    )
    assert slskd_off.search_ahead_for(_SONG)

    soundcloud_first = _downloader(
        tmp_path, monkeypatch, audio_providers=['soundcloud', 'youtube']
    )
    assert not soundcloud_first.search_ahead_for(_SONG)


def test_a_song_with_its_video_is_not_searched(tmp_path, monkeypatch):
    _count_searches(monkeypatch)
    d = _downloader(tmp_path, monkeypatch)

    assert not d.search_ahead_for({**_SONG, 'youtube_id': 'abc123def45'})


def test_no_match_ahead_leaves_the_search_to_the_download(
    tmp_path, monkeypatch
):
    calls: list[str] = []

    def _find_match(song):
        calls.append(song['name'])
        return (None, None) if len(calls) == 1 else ('vid00000002', None)

    monkeypatch.setattr(downloader_mod, 'find_match', _find_match)
    d = _downloader(tmp_path, monkeypatch)

    assert _searched_ahead(d, _SONG)
    d.download(dict(_SONG))

    assert calls == ['Song', 'Song']
    assert d.fetched[0][0] == 'vid00000002'


def test_take_calls_off_a_search_still_waiting_its_turn():
    gate = threading.Event()
    ran: list[str] = []

    def _prepare(song):
        ran.append(song['name'])
        gate.wait(5)
        return PreparedSong(song, 'vid', None, 'youtube', ('youtube',))

    with ThreadPoolExecutor(max_workers=1) as pool:
        ahead = SearchAhead(pool)
        first = {'song_id': '1', 'name': 'First'}
        second = {'song_id': '2', 'name': 'Second'}
        assert ahead.start(first, _prepare)
        assert ahead.start(second, _prepare)
        assert not ahead.start(second, _prepare)

        assert ahead.take(second) is None
        gate.set()
        assert ahead.take(first).video_id == 'vid'

    assert ran == ['First']
    assert len(ahead) == 0


def test_search_key_needs_a_song_id():
    assert search_key({'name': 'x'}) is None
    assert search_key({'song_id': '1', 'name': 'x'}) is not None


def test_batch_searches_only_a_few_songs_ahead(monkeypatch):
    started: list[str] = []

    class _Downloader:
        search_ahead = SearchAhead()

        @staticmethod
        def search_ahead_for(song, subdir=None):
            started.append(song['song_id'])
            return True

    monkeypatch.setattr(api.state, 'downloader', _Downloader())
    monkeypatch.setitem(api.state.settings, 'max_parallel_downloads', 1)
    songs = [{'song_id': str(i), 'name': f'S{i}'} for i in range(10)]

    async def scenario() -> None:
        async with api._searching_ahead(songs, None) as progress:
            await asyncio.sleep(0.01)
            # 1 parallel download + 2 songs ahead.
            assert started == ['0', '1', '2']
            progress.finished()
            await asyncio.sleep(0.01)
            assert started == ['0', '1', '2', '3']
        # The batch ended: nothing more is searched.
        progress.finished()
        await asyncio.sleep(0.01)
        assert started == ['0', '1', '2', '3']

    asyncio.run(scenario())
