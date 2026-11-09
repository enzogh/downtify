"""Global Spotify track deduplication index."""

from __future__ import annotations

import sqlite3

from downtify.downloader import Downloader
from downtify.library_paths import library_stored_path
from downtify.track_index import (
    TrackIndex,
    normalize_spotify_track_id,
    resolve_existing_download,
)

SPOTIFY_ID = '4uLU6hMCjMI75M1A2tKUQC'


def test_normalize_spotify_track_id_from_song_id():
    assert normalize_spotify_track_id({'song_id': SPOTIFY_ID}) == SPOTIFY_ID


def test_normalize_spotify_track_id_from_uri():
    assert (
        normalize_spotify_track_id({'song_id': f'spotify:track:{SPOTIFY_ID}'})
        == SPOTIFY_ID
    )


def test_normalize_ignores_youtube_ids():
    assert normalize_spotify_track_id({'song_id': 'dQw4w9WgXcQ'}) is None


def test_resolve_existing_prefers_global_library(tmp_path):
    download_dir = tmp_path / 'music'
    download_dir.mkdir()
    slskd_dir = tmp_path / 'slskd'
    target = slskd_dir / 'Artist - Track.mp3'
    slskd_dir.mkdir(parents=True)
    target.write_bytes(b'x' * 100)

    stored = library_stored_path(target, download_dir, slskd_dir)
    index = TrackIndex(tmp_path / 'library.db')
    index.register(SPOTIFY_ID, stored)

    d = Downloader(
        download_dir,
        audio_format='mp3',
        audio_providers=['youtube'],
        slskd_settings={'source_dir': str(slskd_dir)},
    )
    song = {
        'song_id': SPOTIFY_ID,
        'name': 'Track',
        'artists': ['Artist'],
    }
    hit = resolve_existing_download(
        d,
        song,
        subdir='Playlist B',
        track_index=index,
    )
    assert hit is not None
    assert hit[1] == 'Already in library'
    assert hit[0] == stored


def test_register_updates_path_for_same_track(tmp_path):
    index = TrackIndex(tmp_path / 'library.db')
    first = tmp_path / 'first' / 'Artist - Song.mp3'
    second = tmp_path / 'second' / 'Artist - Song.mp3'
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b'same')
    second.write_bytes(b'same')
    index.register(SPOTIFY_ID, 'first/path.mp3', full_path=first)
    index.register(SPOTIFY_ID, 'second/path.mp3', full_path=second)
    assert index.lookup(SPOTIFY_ID) == 'second/path.mp3'


def test_filenames_by_spotify_id_reads_the_whole_index(tmp_path):
    index = TrackIndex(tmp_path / 'lib.db')
    index.register('4uLU6hMCjMI75M1A2tKUQC', r'A\One.mp3')
    index.register('1x00000000000000000000', 'Two.flac')

    assert index.filenames_by_spotify_id() == {
        '4uLU6hMCjMI75M1A2tKUQC': 'A/One.mp3',
        '1x00000000000000000000': 'Two.flac',
    }


def test_backfill_from_monitor_db_writes_only_changes(tmp_path):
    other = '0VjIjW4GlUZAMYd2vXMi3b'
    monitor_db = tmp_path / 'monitor.db'
    with sqlite3.connect(monitor_db) as conn:
        conn.executescript(f"""
            CREATE TABLE downloaded_tracks (
                id INTEGER PRIMARY KEY, track_spotify_id TEXT, filename TEXT
            );
            INSERT INTO downloaded_tracks VALUES
                (1, '{SPOTIFY_ID}', 'a/old.mp3'),
                (2, '{SPOTIFY_ID}', 'a/song.mp3'),
                (3, '{other}', 'b\\other.mp3'),
                (4, 'not-a-spotify-id', 'c.mp3');
        """)
    index = TrackIndex(tmp_path / 'library.db')
    song_file = tmp_path / 'song.mp3'
    song_file.write_bytes(b'audio')
    index.register(SPOTIFY_ID, 'a/song.mp3', full_path=song_file)

    # The later row wins; the known track keeps its content key.
    assert index.backfill_from_monitor_db(monitor_db) == 1
    assert index.lookup(SPOTIFY_ID) == 'a/song.mp3'
    assert index.lookup(other) == 'b/other.mp3'
    assert index.backfill_from_monitor_db(monitor_db) == 0
    with sqlite3.connect(tmp_path / 'library.db') as conn:
        (ck,) = conn.execute(
            'SELECT content_key FROM library_tracks WHERE spotify_track_id = ?',
            (SPOTIFY_ID,),
        ).fetchone()
    assert ck
