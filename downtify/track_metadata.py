"""Edit a library track's tags by hand, with suggestions from the catalogs.

``GET /api/library/metadata`` returns a track's current tags and what
Apple Music (iTunes Search), Deezer and YouTube Music know about it;
``POST /api/library/metadata`` writes the fields the admin kept back
into the file - the same tags a download writes
(:func:`downtify.downloader.embed_metadata`), same path, so the track
stays in its playlists. The cover is replaced only when a new one is
picked; otherwise the embedded one is written back as it was. Lyrics
and every tag not listed in :data:`FIELDS` are left alone.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from . import deezer, itunes, providers
from .cover_art import extract_embedded_cover
from .downloader import _download_cover, embed_metadata

#: The fields a suggestion carries and an edit may set.
FIELDS = (
    'name',
    'artists',
    'album_name',
    'album_artist',
    'year',
    'release_date',
    'track_number',
    'genre',
    'explicit',
    'cover_url',
)

#: Suggestions kept per source.
PER_SOURCE = 5

_YEAR_RE = re.compile(r'^\d{4}')


def _text(value: Any) -> str:
    return str(value or '').strip()


def suggestion(song: dict[str, Any], source: str) -> dict[str, Any]:
    """*song* (a catalog row) cut down to :data:`FIELDS` plus ``source``."""

    artists = [_text(a) for a in song.get('artists') or [] if _text(a)]
    release = _text(song.get('release_date'))[:10]
    year = _text(song.get('year'))[:4] or release[:4]
    try:
        number = int(song.get('track_number') or 0)
    except (TypeError, ValueError):
        number = 0
    return {
        'source': source,
        'name': _text(song.get('name')),
        'artists': artists,
        'album_name': _text(song.get('album_name')),
        'album_artist': _text(song.get('album_artist')),
        'year': year if _YEAR_RE.match(year) else '',
        'release_date': release,
        'track_number': max(0, number),
        'genre': _text(song.get('genre')),
        'explicit': bool(song.get('explicit')),
        'cover_url': _text(song.get('cover_url')),
    }


def _itunes_song(row: dict[str, Any]) -> dict[str, Any]:
    artwork = _text(row.get('artworkUrl100'))
    return {
        'name': row.get('trackName'),
        'artists': [row.get('artistName')],
        'album_name': row.get('collectionName'),
        'album_artist': row.get('collectionArtistName')
        or row.get('artistName'),
        'release_date': row.get('releaseDate'),
        'track_number': row.get('trackNumber'),
        'genre': row.get('primaryGenreName'),
        'explicit': row.get('trackExplicitness') == 'explicit',
        'cover_url': artwork.replace('100x100bb', '600x600bb'),
    }


def _from_itunes(query: str) -> list[dict[str, Any]]:
    rows = itunes._search_itunes(query, limit=PER_SOURCE)
    return [_itunes_song(r) for r in rows if isinstance(r, dict)]


def _from_deezer(query: str) -> list[dict[str, Any]]:
    return deezer.finder_search(query, limit=PER_SOURCE)['songs']


def _from_youtube_music(query: str) -> list[dict[str, Any]]:
    return providers.search_songs(query, limit=PER_SOURCE)


_SOURCES: dict[str, Callable[[str], list[dict[str, Any]]]] = {
    'applemusic': _from_itunes,
    'deezer': _from_deezer,
    'youtube': _from_youtube_music,
}


def _one_source(source: str, query: str) -> list[dict[str, Any]]:
    try:
        rows = _SOURCES[source](query)
    except Exception:
        logger.opt(exception=True).debug(
            'Metadata suggestions from {} failed for {!r}', source, query
        )
        return []
    found = [suggestion(row, source) for row in rows[:PER_SOURCE]]
    return [row for row in found if row['name'] and row['artists']]


def suggestions(query: str) -> list[dict[str, Any]]:
    """Every source's matches for *query*, Apple Music first (it has the
    most complete tags), each source in its own order. A source that
    fails just has none."""

    text = query.strip()
    if not text:
        return []
    with ThreadPoolExecutor(max_workers=len(_SOURCES)) as pool:
        results = list(pool.map(lambda s: _one_source(s, text), _SOURCES))
    return [row for rows in results for row in rows]


def clean_edit(raw: dict[str, Any]) -> dict[str, Any]:
    """The posted fields as a song for :func:`embed_metadata`; raises
    :class:`ValueError` without a title or an artist."""

    edit = suggestion(raw, 'edit')
    if isinstance(raw.get('artists'), str):
        edit['artists'] = [
            a.strip() for a in raw['artists'].split(',') if a.strip()
        ]
    if not edit['name'] or not edit['artists']:
        raise ValueError('A title and an artist are required')
    edit.pop('source')
    return edit


def write_tags(path: Path, edit: dict[str, Any]) -> None:
    """Write *edit* (see :func:`clean_edit`) into *path*. A new
    ``cover_url`` replaces the cover; without one the embedded cover is
    written back unchanged."""

    cover = None
    if edit.get('cover_url'):
        cover = _download_cover(edit['cover_url'])
    if cover is None:
        cover, _mime = extract_embedded_cover(path)
    song = {**edit, 'cover_url': ''}
    embed_metadata(path, song, download_cover=True, cover_bytes=cover)
