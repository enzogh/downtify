from __future__ import annotations

from downtify import track_metadata
from downtify.artist_routes import relevant_art_results
from downtify.cover_art import extract_embedded_cover
from downtify.downloader import embed_metadata
from downtify.library_metadata import read_audio_metadata


def test_suggestions_merge_sources_and_skip_failures(monkeypatch):
    def boom(_query):
        raise ValueError('down')

    itunes_row = {
        'trackName': 'Animals',
        'artistName': 'Martin Garrix',
        'collectionName': 'Animals - Single',
        'releaseDate': '2013-06-17T07:00:00Z',
        'trackNumber': 1,
        'primaryGenreName': 'Dance',
        'trackExplicitness': 'notExplicit',
        'artworkUrl100': 'https://x/100x100bb.jpg',
    }
    monkeypatch.setattr(
        track_metadata.itunes, '_search_itunes', lambda q, limit: [itunes_row]
    )
    monkeypatch.setattr(
        track_metadata,
        '_SOURCES',
        {
            'applemusic': track_metadata._from_itunes,
            'deezer': boom,
            'youtube': lambda q: [
                {'name': 'Animals', 'artists': ['Martin Garrix']}
            ],
        },
    )
    rows = track_metadata.suggestions('Martin Garrix Animals')
    assert [r['source'] for r in rows] == ['applemusic', 'youtube']
    first = rows[0]
    assert first['year'] == '2013'
    assert first['release_date'] == '2013-06-17'
    assert first['track_number'] == 1
    assert first['cover_url'] == 'https://x/600x600bb.jpg'
    edit = track_metadata.clean_edit({'name': 'A', 'artists': 'X, Y'})
    assert edit['artists'] == ['X', 'Y']


def test_artist_photo_search_drops_other_artists():
    rows = [
        {'name': 'Martin Garrix'},
        {'name': 'Avicii'},
        {'name': 'Martin Garrix & Dua Lipa'},
    ]
    assert [
        r['name'] for r in relevant_art_results('martin garrix', rows)
    ] == [
        'Martin Garrix',
        'Martin Garrix & Dua Lipa',
    ]
    assert relevant_art_results('garix', rows) == rows


def test_write_tags_keeps_the_cover(tmp_path):
    path = tmp_path / 't.mp3'
    path.write_bytes((b'\xff\xfb\x90\x64' + b'\x00' * 413) * 40)
    cover = b'\xff\xd8\xff\xe0JFIF' + b'\x00' * 200 + b'\xff\xd9'
    embed_metadata(path, {'name': 'old', 'artists': ['A']}, cover_bytes=cover)
    track_metadata.write_tags(
        path,
        track_metadata.clean_edit({
            'name': 'New',
            'artists': 'X, Y',
            'album_name': 'Alb',
            'year': '2013',
            'track_number': 3,
        }),
    )
    tags = read_audio_metadata(path)
    assert (tags['title'], tags['artists'], tags['album']) == (
        'New',
        ['X', 'Y'],
        'Alb',
    )
    assert extract_embedded_cover(path)[0] == cover
