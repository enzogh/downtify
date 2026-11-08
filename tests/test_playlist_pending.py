"""Songs added to a Library playlist before they are downloaded."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from downtify import api, manual_playlists
from downtify.library_catalog import LibraryContext
from downtify.manual_playlists import create_manual_playlist
from downtify.playlist_pending import PlaylistPendingSongs, pending_key

SONG = {
    'song_id': 'sp1',
    'name': 'Halo',
    'artists': ['Beyoncé'],
    'cover_url': 'https://i.example/halo.jpg',
    'duration': 261,
    'url': 'https://open.spotify.com/track/sp1',
    'lyrics': 'not kept',
}


@pytest.fixture
def store(tmp_path: Path) -> PlaylistPendingSongs:
    return PlaylistPendingSongs(tmp_path / 'library.db')


def test_add_keeps_the_song_fields_the_page_needs(store):
    added = store.add('Road trip', [SONG], user_id=3)

    assert [song['song_id'] for song in added] == ['sp1']
    [saved] = store.songs('road TRIP')
    assert saved['name'] == 'Halo'
    assert saved['artists'] == ['Beyoncé']
    assert 'lyrics' not in saved
    assert saved['added_at']


def test_a_song_waits_once_per_playlist(store):
    store.add('Road trip', [SONG])

    assert store.add('Road trip', [SONG, {'name': 'no id'}]) == []
    assert len(store.songs('Road trip')) == 1


def test_claim_returns_every_waiting_playlist_and_forgets_them(store):
    store.add('Road trip', [SONG])
    store.add('Gym', [SONG])

    assert store.claim('sp1') == ['Road trip', 'Gym']
    assert store.claim('sp1') == []
    assert store.songs('Road trip') == []


def test_remove_rename_and_drop(store):
    store.add('Road trip', [SONG, {**SONG, 'song_id': 'sp2'}])

    assert store.remove('Road trip', ['sp2']) == 1
    store.rename('Road trip', 'Summer')
    assert store.songs('Road trip') == []
    assert [song['song_id'] for song in store.songs('Summer')] == ['sp1']
    store.drop('Summer')
    assert store.songs('Summer') == []


def test_pending_key_matches_the_m3u_stem():
    assert pending_key(' Top 50: USA ') == pending_key('top 50 usa')
    assert not pending_key('  ')


@pytest.fixture
def library(tmp_path: Path, monkeypatch) -> LibraryContext:
    root = tmp_path / 'downloads'
    root.mkdir()
    (root / 'Halo.mp3').write_bytes(b'audio fixture')
    monkeypatch.setattr(
        manual_playlists, 'refresh_manual_playlist_cover', lambda *args: None
    )
    ctx = LibraryContext(download_dir=root)
    monkeypatch.setattr(api, 'library_context', lambda: ctx)
    return ctx


def _playlist_files(library: LibraryContext, name: str) -> list[str]:
    return manual_playlists._read_files(
        library, library.download_dir / 'Playlists' / f'{name}.m3u'
    )


def test_a_downloaded_song_moves_into_its_playlists(
    library, store, monkeypatch
):
    monkeypatch.setattr(api.state, 'playlist_pending', store)
    create_manual_playlist(library, 'Road trip')
    create_manual_playlist(library, 'Gym')
    store.add('Road trip', [SONG])
    store.add('Gym', [SONG])

    assert api.claim_pending_playlist_songs(SONG, 'Halo.mp3') is True

    assert _playlist_files(library, 'Road trip') == ['Halo.mp3']
    assert _playlist_files(library, 'Gym') == ['Halo.mp3']
    assert store.songs('Road trip') == []


def test_a_job_resolved_again_is_matched_by_its_url(
    library, store, monkeypatch
):
    monkeypatch.setattr(api.state, 'playlist_pending', store)
    create_manual_playlist(library, 'Road trip')
    store.add('Road trip', [{**SONG, 'song_id': ''}])

    job_song = {'song_id': 'other-id', 'url': SONG['url']}
    assert api.claim_pending_playlist_songs(job_song, 'Halo.mp3') is True
    assert _playlist_files(library, 'Road trip') == ['Halo.mp3']


def test_a_deleted_playlist_does_not_break_the_download(
    library, store, monkeypatch
):
    monkeypatch.setattr(api.state, 'playlist_pending', store)
    store.add('Gone', [SONG])

    assert api.claim_pending_playlist_songs(SONG, 'Halo.mp3') is False
    assert store.songs('Gone') == []


def test_the_claim_waits_for_the_library_registration(
    library, store, monkeypatch
):
    """The download thread's outcome hook no longer claims: the playlist
    listing would drop a file the library listing doesn't know yet."""

    monkeypatch.setattr(api.state, 'playlist_pending', store)
    monkeypatch.setattr(api.state, 'download_log', None)
    create_manual_playlist(library, 'Road trip')
    store.add('Road trip', [SONG])

    api.record_download_outcome(SONG, 'completed', 'Halo.mp3')

    assert len(store.songs('Road trip')) == 1


def test_the_async_claim_announces_the_change(library, store, monkeypatch):
    monkeypatch.setattr(api.state, 'playlist_pending', store)
    create_manual_playlist(library, 'Road trip')
    store.add('Road trip', [SONG])
    sent: list[str] = []

    async def announce() -> None:
        sent.append('playlists_changed')

    monkeypatch.setattr(api, 'announce_playlists_changed', announce)
    monkeypatch.setattr(
        api, 'invalidate_library_paths_cache', lambda **_: None
    )

    asyncio.run(api._claim_pending_playlist_songs(SONG, 'Halo.mp3'))

    assert sent == ['playlists_changed']
    assert _playlist_files(library, 'Road trip') == ['Halo.mp3']
