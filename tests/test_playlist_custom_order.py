"""An imported playlist keeps the order its owner chose through the
syncs that rewrite it from its source (``downtify/playlist_custom_order``
and ``m3u.write_m3u``). Offline."""

from __future__ import annotations

from pathlib import Path

import pytest

from downtify import m3u
from downtify.playlist_custom_order import PlaylistCustomOrder


@pytest.fixture
def root(tmp_path: Path) -> Path:
    folder = tmp_path / 'downloads'
    folder.mkdir()
    for name in ('a', 'b', 'c', 'd'):
        (folder / f'{name}.mp3').write_bytes(b'audio')
    return folder


@pytest.fixture
def kept(tmp_path: Path):
    store = PlaylistCustomOrder(tmp_path / 'lib.db')
    m3u.set_custom_order_source(store.get)
    yield store
    m3u.set_custom_order_source(None)


def _sync(root: Path, *names: str) -> list[str]:
    path, _kept = m3u.write_m3u(
        root,
        'Road Trip',
        [{'filename': f'{n}.mp3', 'title': n, 'artist': 'X'} for n in names],
    )
    assert path is not None
    return m3u.read_m3u_tracks(path, root)


def test_a_sync_keeps_the_chosen_order_and_adds_new_songs_last(root, kept):
    assert _sync(root, 'a', 'b', 'c') == ['a.mp3', 'b.mp3', 'c.mp3']
    kept.set('Road Trip', ['c.mp3', 'a.mp3', 'b.mp3'])

    assert _sync(root, 'a', 'b', 'd', 'c') == [
        'c.mp3',
        'a.mp3',
        'b.mp3',
        'd.mp3',
    ]
    # A song the source dropped is simply gone.
    assert _sync(root, 'b', 'c') == ['c.mp3', 'b.mp3']


def test_without_a_chosen_order_the_source_order_stays(root, kept):
    assert _sync(root, 'b', 'a') == ['b.mp3', 'a.mp3']


def test_a_library_playlist_is_never_reordered_by_it(root, kept):
    kept.set('Mine', ['b.mp3', 'a.mp3'])
    path, _ = m3u.write_m3u(
        root,
        'Mine',
        [{'filename': 'a.mp3'}, {'filename': 'b.mp3'}],
        manual=True,
    )
    assert m3u.read_m3u_tracks(path, root) == ['a.mp3', 'b.mp3']


def test_reordering_keeps_each_song_with_its_lines(root):
    path = root / 'Playlists' / 'P.m3u'
    path.parent.mkdir()
    path.write_text(
        '#EXTM3U\n#PLAYLIST:P\n'
        '#EXTINF:10,X - a\n../a.mp3\n'
        '#EXTINF:20,X - b\n../b.mp3\n'
        '../elsewhere.mp3\n'
        '../c.mp3\n'
    )
    order = m3u.reorder_m3u_file(
        path, root, None, None, ['c.mp3', 'b.mp3', 'a.mp3']
    )
    # A missing file is still one of its songs: it goes after the others.
    assert order == ['c.mp3', 'b.mp3', 'a.mp3', 'elsewhere.mp3']
    assert path.read_text().splitlines() == [
        '#EXTM3U',
        '#PLAYLIST:P',
        '../c.mp3',
        '#EXTINF:20,X - b',
        '../b.mp3',
        '#EXTINF:10,X - a',
        '../a.mp3',
        '../elsewhere.mp3',
    ]


def test_the_store_is_by_name_whatever_the_case(tmp_path):
    store = PlaylistCustomOrder(tmp_path / 'lib.db')
    store.set('Road', ['b.mp3', 'a\\c.mp3', ''])
    assert store.get('ROAD') == ['b.mp3', 'a/c.mp3']
    store.set('road', ['a.mp3'])
    assert store.get('Road') == ['a.mp3']
    store.drop('Road')
    assert store.get('Road') == []
