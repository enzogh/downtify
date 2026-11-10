"""Search and discovery routes: ``/api/discover*``, ``/api/finder/*``,
``/api/songs/search``, ``/api/albums/search``, ``/api/similar/tracks``,
``/api/buy``, ``/api/url*`` and ``/api/song/url``.

Registers on the shared ``api_core.router`` (under its library-only
guard) when :mod:`downtify.api` imports it; the endpoint list lives
in that module's docstring.
"""

from __future__ import annotations

import asyncio
from datetime import (
    datetime,
    timezone,
)
from typing import (
    Any,
    Optional,
)

from fastapi import (
    HTTPException,
    Query,
    Request,
)
from loguru import (
    logger,
)

from . import (
    artist_profile,
    deezer,
    library_only,
    providers,
    spotify,
)
from .api_core import (
    _artist_profile_download_dir,
    _effective_audio_providers,
    entries_for_request,
    local_catalog_for_request,
    request_is_admin,
    request_user_id,
    router,
    state,
    user_preferences,
)
from .api_pipeline import (
    _json_object,
    _require_discover,
)
from .buy_links import (
    buy_links,
)
from .discover import (
    collections,
    deezer_collections,
    recommendations,
    spotify_collections,
)
from .ttl_cache import (
    TTLCache,
)


def local_discovery_for_request(request: Request) -> dict[str, Any]:
    rows = local_catalog_for_request(request, collections=True)
    return {
        **rows,
        'seeds': [],
        'more_albums': [],
        'artist_urls': {},
        'partial': False,
    }


@router.get('/api/songs/search')
def search_endpoint(
    query: str = Query(''), request: Request = None
) -> list[dict[str, Any]]:
    if library_only.enabled(state.settings):
        return library_only.search(entries_for_request(request), query)
    results = providers.search_songs(query, limit=20)
    if results:
        return [{**song, 'download_by_metadata': True} for song in results]
    q = query.strip()
    if not q or 'slskd' not in _effective_audio_providers(state.settings):
        return []
    # With slskd enabled, a search YouTube Music has nothing for can still
    # be downloaded from Soulseek: offer the query itself as a track
    # ("Artist - Title" is split into artist and title).
    stub = providers.song_stub_from_text_query(q)
    if stub is None:
        return []
    logger.info(
        'Search fallback for slskd: q={!r} title={!r} artists={}',
        q,
        stub.get('name'),
        stub.get('artists'),
    )
    return [stub]


@router.get('/api/albums/search')
def search_albums_endpoint(
    request: Request,
    query: str = Query(''),
    limit: int = Query(25, ge=1, le=50),
) -> list[dict[str, Any]]:
    # A user's own choice (Settings > General) wins over the server's.
    wanted = user_preferences(request).get(
        'search_albums', state.settings.get('search_albums', True)
    )
    if not wanted:
        return []
    if library_only.enabled(state.settings):
        return local_catalog_for_request(request, query, limit)['albums']
    return providers.search_albums(query, limit=limit)


@router.get('/api/discover/chart')
def discover_chart_endpoint(
    limit: int = Query(25, ge=1, le=50),
    request: Request = None,
) -> dict[str, Any]:
    try:
        if library_only.enabled(state.settings):
            return local_catalog_for_request(
                request, limit=limit, collections=True
            )
        return deezer.fetch_chart(limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


_DEEZER_ID = r'^\d+$'


@router.get('/api/finder/search')
def finder_search_endpoint(
    query: str = Query(''),
    limit: int = Query(25, ge=1, le=50),
    request: Request = None,
) -> dict[str, Any]:
    try:
        if library_only.enabled(state.settings):
            rows = local_catalog_for_request(request, query, limit)
            return {
                'songs': rows['tracks'],
                'albums': rows['albums'],
                'artists': rows['artists'],
            }
        return deezer.finder_search(query, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get('/api/finder/artist')
def finder_artist_endpoint(
    artist_id: str = Query(..., pattern=_DEEZER_ID),
    lang: str = Query('en', max_length=16),
) -> dict[str, Any]:
    try:
        artist = deezer.finder_artist(artist_id, lang)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # Plain text, paragraphs split by a blank line - the same cleanup a
    # saved artist bio gets, so the page never renders Deezer's HTML.
    artist['bio'] = artist_profile._format_bio_text(artist.pop('bio_html'))
    return artist


@router.get('/api/finder/artist/songs')
def finder_artist_songs_endpoint(
    artist_id: str = Query(..., pattern=_DEEZER_ID),
    name: str = Query(..., min_length=1),
) -> dict[str, Any]:
    """A Deezer artist's songs, shaped like a Finder search's
    ``{songs, albums, artists}`` (albums and artists always empty) - see
    ``downtify.deezer.finder_artist_songs``."""

    try:
        songs = deezer.finder_artist_songs(artist_id, name)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {'songs': songs, 'albums': [], 'artists': []}


@router.get('/api/finder/artist/albums')
def finder_artist_albums_endpoint(
    artist_id: str = Query(..., pattern=_DEEZER_ID),
) -> list[dict[str, Any]]:
    try:
        return deezer.finder_artist_albums(artist_id)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get('/api/finder/albums/track_counts')
def finder_album_track_counts_endpoint(
    ids: str = Query(''),
) -> dict[str, int]:
    return deezer.album_track_counts(ids.split(','))


@router.get('/api/finder/album')
def finder_album_endpoint(
    album_id: str = Query(..., pattern=_DEEZER_ID),
) -> dict[str, Any]:
    try:
        return deezer.finder_album(album_id)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get('/api/song/url')
def song_url_endpoint(url: str = Query(...)):
    return _resolve_url(url)


@router.get('/api/url')
def url_endpoint(url: str = Query(...)):
    return _resolve_url(url)


def _resolve_url(url: str):
    spotify_parsed = spotify.parse_spotify_url(url)
    if spotify_parsed is not None:
        kind, sid = spotify_parsed
        try:
            if kind == 'track':
                return spotify.track_from_id(sid, with_album=True)
            if kind == 'album':
                return spotify.album_tracks_from_id(sid)
            if kind == 'playlist':
                return spotify.playlist_tracks_from_id(sid)
        except Exception as exc:
            logger.exception('Failed to resolve Spotify URL {}', url)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        raise HTTPException(
            status_code=400, detail=f'Unsupported entity type: {kind}'
        )

    youtube_parsed = providers.parse_youtube_url(url)
    if youtube_parsed is not None:
        kind, yid = youtube_parsed
        try:
            if kind == 'track':
                return providers.song_from_video_id(yid)
            if kind == 'album':
                return providers.album_tracks_from_browse_id(yid)
            if kind == 'playlist':
                return providers.playlist_tracks_from_id(yid)
            if kind == 'artist':
                return providers.artist_albums_from_channel_id(
                    providers.resolve_artist_channel_id(yid)
                )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception('Failed to resolve YouTube URL {}', url)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        raise HTTPException(
            status_code=400, detail=f'Unsupported entity type: {kind}'
        )

    deezer_parsed = deezer.parse_deezer_url(url)
    if deezer_parsed is not None:
        kind, did = deezer_parsed
        try:
            if kind == 'track':
                return deezer.track_from_id(did)
            if kind == 'album':
                return deezer.album_from_id(did)
            if kind == 'playlist':
                _, tracks = deezer.playlist_info_and_tracks(did)
                return tracks
            if kind == 'artist':
                _, _cover, releases = deezer.artist_page_from_id(did)
                return releases
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception('Failed to resolve Deezer URL {}', url)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        raise HTTPException(
            status_code=400, detail=f'Unsupported entity type: {kind}'
        )

    soundcloud_parsed = providers.parse_soundcloud_url(url)
    if soundcloud_parsed is not None:
        try:
            return providers.soundcloud_track_from_url(url)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception('Failed to resolve SoundCloud URL {}', url)
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    raise HTTPException(status_code=400, detail='Invalid URL')


def _artists_label(song: dict[str, Any]) -> str:
    artists = song.get('artists') or []
    if isinstance(artists, list) and artists:
        return ', '.join(str(a) for a in artists if a)
    return str(song.get('artist') or '')


def _collection_details(
    kind: str, tracks: list[dict[str, Any]], name: str = ''
) -> dict[str, Any]:
    first = tracks[0] if tracks else {}
    is_album = kind == 'album'
    return {
        'kind': kind,
        'name': name or str(first.get('album_name') or ''),
        'subtitle': _artists_label(first) if is_album else '',
        # A playlist has no single cover in the track rows; the client
        # builds a mosaic from the tracks' own covers instead.
        'cover_url': str(first.get('cover_url') or '') if is_album else '',
        'year': str(first.get('year') or '') if is_album else '',
        'tracks': tracks,
        'albums': [],
    }


def _track_details(song: dict[str, Any]) -> dict[str, Any]:
    return {
        'kind': 'track',
        'name': str(song.get('name') or ''),
        'subtitle': _artists_label(song),
        'cover_url': str(song.get('cover_url') or ''),
        'year': str(song.get('year') or ''),
        'tracks': [song],
        'albums': [],
    }


def _spotify_details(kind: str, sid: str) -> dict[str, Any]:
    if kind == 'track':
        return _track_details(spotify.track_from_id(sid, with_album=True))
    if kind == 'album':
        return _collection_details('album', spotify.album_tracks_from_id(sid))
    if kind == 'playlist':
        name, tracks = spotify.playlist_info_and_tracks(sid)
        return _collection_details('playlist', tracks, name)
    if kind == 'artist':
        # The embed has no discography (see spotify.artist_name_from_id);
        # the releases come from the player's artist overview. The client
        # offers the top songs from /api/artists/top_songs/url.
        name, cover_url, releases = spotify.artist_page_from_id(sid)
        return {
            'kind': 'artist',
            'name': name,
            'subtitle': '',
            'cover_url': cover_url,
            'year': '',
            'tracks': [],
            'albums': releases,
        }
    raise HTTPException(
        status_code=400, detail=f'Unsupported entity type: {kind}'
    )


def _youtube_details(kind: str, yid: str) -> dict[str, Any]:
    if kind == 'track':
        return _track_details(providers.song_from_video_id(yid))
    if kind == 'album':
        return _collection_details(
            'album', providers.album_tracks_from_browse_id(yid)
        )
    if kind == 'playlist':
        name, tracks = providers.playlist_info_and_tracks_from_id(yid)
        return _collection_details('playlist', tracks, name)
    if kind == 'artist':
        channel_id = providers.resolve_artist_channel_id(yid)
        info = providers.artist_info_from_channel_id(channel_id)
        return {
            'kind': 'artist',
            'name': str(info.get('name') or ''),
            'subtitle': str(info.get('description') or ''),
            'cover_url': str(info.get('cover_url') or ''),
            'year': '',
            'tracks': [],
            'albums': providers.artist_albums_from_channel_id(channel_id),
        }
    raise HTTPException(
        status_code=400, detail=f'Unsupported entity type: {kind}'
    )


def _deezer_details(kind: str, did: str) -> dict[str, Any]:
    if kind == 'track':
        return _track_details(deezer.track_from_id(did))
    if kind == 'album':
        return _collection_details('album', deezer.album_from_id(did))
    if kind == 'playlist':
        name, cover, tracks = deezer.playlist_page_from_id(did)
        details = _collection_details('playlist', tracks, name)
        details['cover_url'] = cover
        return details
    if kind == 'artist':
        # Deezer has a real discography endpoint (unlike Spotify's embed),
        # so - like YouTube Music - the releases come straight from it,
        # no overview-shelf fallback needed. The client offers top songs
        # from /api/artists/top_songs/url, same as the other two sources.
        name, cover_url, releases = deezer.artist_page_from_id(did)
        return {
            'kind': 'artist',
            'name': name,
            'subtitle': '',
            'cover_url': cover_url,
            'year': '',
            'tracks': [],
            'albums': releases,
        }
    raise HTTPException(
        status_code=400, detail=f'Unsupported entity type: {kind}'
    )


def _soundcloud_details(url: str) -> dict[str, Any]:
    return _track_details(providers.soundcloud_track_from_url(url))


@router.get('/api/url/resolve')
def url_resolve_endpoint(url: str = Query(...)) -> dict[str, Any]:
    """What a pasted link points at, with its tracks (or releases).

    Same inputs as ``/api/song/url``, but always an object:
    ``{kind, name, subtitle, cover_url, year, tracks, albums}`` -
    ``kind`` is ``track``, ``album``, ``playlist`` or ``artist``; an
    artist fills ``albums`` (release summaries) instead of ``tracks``.
    """

    spotify_parsed = spotify.parse_spotify_url(url)
    youtube_parsed = (
        None if spotify_parsed else providers.parse_youtube_url(url)
    )
    deezer_parsed = (
        None
        if spotify_parsed or youtube_parsed
        else deezer.parse_deezer_url(url)
    )
    soundcloud_parsed = (
        None
        if spotify_parsed or youtube_parsed or deezer_parsed
        else providers.parse_soundcloud_url(url)
    )
    if (
        spotify_parsed is None
        and youtube_parsed is None
        and not deezer_parsed
        and not soundcloud_parsed
    ):
        raise HTTPException(status_code=400, detail='Invalid URL')
    try:
        if spotify_parsed is not None:
            return _spotify_details(*spotify_parsed)
        if youtube_parsed is not None:
            return _youtube_details(*youtube_parsed)
        if deezer_parsed is not None:
            return _deezer_details(*deezer_parsed)
        return _soundcloud_details(url)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception('Failed to resolve URL {}', url)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post('/api/discover')
async def discover_endpoint(request: Request) -> dict[str, Any]:
    """Artists the library doesn't have yet, suggested from the ones it
    does (see ``downtify.discover``).

    Body ``{library: [{name, tracks, liked}]}``: every library artist with
    its track and liked-track counts, as the Library page groups them. The
    server adds how often each was listened to, and leaves out the library
    and the block list. A Deezer failure for some seeds isn't an error -
    the rest still count, and ``partial`` says so.
    """

    if library_only.enabled(state.settings):
        return local_discovery_for_request(request)
    store = _require_discover()
    payload = await _json_object(request)
    library = payload.get('library')
    if not isinstance(library, list):
        raise HTTPException(status_code=400, detail='library is required')
    return await asyncio.to_thread(
        recommendations, store, library, user_id=request_user_id(request)
    )


@router.post('/api/discover/collections')
async def discover_collections_endpoint(request: Request) -> dict[str, Any]:
    """Albums and playlists for the library (see
    ``downtify.discover.collections``).

    Body: the same ``library`` as ``POST /api/discover``, plus ``albums``
    (``{artist, title}`` per library album) and ``playlist_ids`` (Spotify
    ids of downloaded playlists), both left out of the answer.
    """

    if library_only.enabled(state.settings):
        return local_discovery_for_request(request)
    store = _require_discover()
    payload = await _json_object(request)
    library = payload.get('library')
    if not isinstance(library, list):
        raise HTTPException(status_code=400, detail='library is required')
    albums = payload.get('albums')
    playlist_ids = payload.get('playlist_ids')
    return await asyncio.to_thread(
        collections,
        store,
        library,
        albums if isinstance(albums, list) else [],
        playlist_ids if isinstance(playlist_ids, list) else [],
    )


def _list_field(payload: dict[str, Any], name: str) -> list[Any]:
    value = payload.get(name)
    return value if isinstance(value, list) else []


@router.post('/api/discover/collections/deezer')
async def discover_deezer_collections_endpoint(
    request: Request,
) -> dict[str, Any]:
    """Albums and playlists for the library from Deezer alone - the web
    page's first answer (see ``downtify.discover.deezer_collections``).

    Body: what ``POST /api/discover/collections`` takes, plus
    ``playlist_names`` (the library's playlist names, so a Deezer playlist
    already downloaded isn't suggested).
    """

    if library_only.enabled(state.settings):
        return local_discovery_for_request(request)
    store = _require_discover()
    payload = await _json_object(request)
    library = payload.get('library')
    if not isinstance(library, list):
        raise HTTPException(status_code=400, detail='library is required')
    return await asyncio.to_thread(
        deezer_collections,
        store,
        library,
        _list_field(payload, 'albums'),
        _list_field(payload, 'playlist_names'),
    )


@router.post('/api/discover/collections/spotify')
async def discover_spotify_collections_endpoint(
    request: Request,
) -> dict[str, Any]:
    """What Spotify adds to the Deezer answer, its albums matched to Deezer
    - the web page's second answer (see
    ``downtify.discover.spotify_collections``).

    Body: what ``POST /api/discover/collections`` takes, plus ``shown``
    (the album ``key``\\ s the page already shows, left out unmatched).
    """

    if library_only.enabled(state.settings):
        return {
            'source': 'library',
            'albums': [],
            'more_albums': [],
            'playlists': [],
            'partial': False,
        }
    store = _require_discover()
    payload = await _json_object(request)
    library = payload.get('library')
    if not isinstance(library, list):
        raise HTTPException(status_code=400, detail='library is required')
    return await asyncio.to_thread(
        spotify_collections,
        store,
        library,
        _list_field(payload, 'albums'),
        _list_field(payload, 'playlist_ids'),
        _list_field(payload, 'shown'),
    )


@router.get('/api/buy')
async def buy_links_endpoint(
    artist: str = Query('', max_length=200),
    title: str = Query('', max_length=300),
    album: str = Query('', max_length=300),
    country: str = Query('', max_length=8),
) -> dict[str, Any]:
    """Where to buy a song (``title``), an album (``album``, no title) or
    an artist's music (``artist`` alone), to support the artist - see
    :mod:`downtify.buy_links`. ``country`` (two letters, ``US`` by
    default) picks the iTunes store. ``{kind, query, links}``."""

    artist = artist.strip()
    if not artist:
        raise HTTPException(status_code=400, detail='artist is required')
    website = await asyncio.to_thread(_artist_website, artist)
    return await asyncio.to_thread(
        buy_links,
        artist,
        title,
        album,
        country=country,
        website=website,
    )


def _artist_website(name: str) -> str:
    """The website in *name*'s saved profile (``''`` without one; a
    profile is never fetched for this)."""

    try:
        profile = artist_profile.load_profile(
            _artist_profile_download_dir(), name
        )
    except Exception:
        logger.opt(exception=True).debug('Could not read profile of {}', name)
        return ''
    return str((profile.get('social') or {}).get('website') or '')


#: Radio mixes already fetched: playlist recommendations ask for the same
#: seeds every time a playlist opens (see downtify/ttl_cache.py).
_SIMILAR_CACHE: TTLCache[dict[str, Any]] = TTLCache(6 * 60 * 60, 512)


@router.get('/api/similar/tracks')
async def similar_tracks_endpoint(
    artist: str = Query('', max_length=200),
    track: str = Query('', max_length=200),
    limit: int = Query(20, ge=1, le=50),
    request: Request = None,
) -> dict[str, Any]:
    """Tracks similar to *track* by *artist*, from YouTube Music's own
    radio mix for the track (see
    ``downtify.providers.youtube_similar_tracks``). Either *artist*
    or *track* alone is enough for a seed.

    Response ``{artist, track, source, tracks}`` - downloadable song
    rows plus ``match``. ``502`` when YouTube Music can't be used.
    """

    if library_only.enabled(state.settings):
        return library_only.similar(
            entries_for_request(request), artist, track, limit
        )
    key = (artist.strip().casefold(), track.strip().casefold(), limit)
    cached = _SIMILAR_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        found = await asyncio.to_thread(
            providers.youtube_similar_tracks,
            artist,
            track,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if found.get('tracks'):
        _SIMILAR_CACHE.set(key, found)
    return found


@router.post('/api/discover/listens')
async def record_listen_endpoint(request: Request) -> dict[str, Any]:
    """Count one listen to ``{artist}`` - sent by the player once a track
    has played long enough to count.

    An app may also send ``track_id`` instead of ``artist`` (the track's
    album artist is used), ``played_at`` (ISO 8601, for plays it reports
    after being offline; a future time counts as now) and ``play_id``
    (the same play reported twice counts once).
    """

    store = _require_discover()
    payload = await _json_object(request)
    artist = str(payload.get('artist') or '')
    track_id = str(payload.get('track_id') or '')
    if not artist and track_id and state.library_sync is not None:
        row = await asyncio.to_thread(state.library_sync.row_for, track_id)
        artist = str((row or {}).get('album_artist') or '')
    when = _played_at(payload.get('played_at'))
    row = await asyncio.to_thread(
        store.record_listen,
        artist,
        when,
        str(payload.get('play_id') or '').strip(),
        request_user_id(request),
    )
    if row is None:
        raise HTTPException(status_code=400, detail='artist is required')
    return row


def _played_at(value: Any) -> Optional[datetime]:
    """``played_at`` from a listen report: ``None`` (now) when missing,
    unreadable or in the future."""

    if not value:
        return None
    try:
        when = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return None if when > datetime.now(timezone.utc) else when


@router.delete('/api/discover/listens')
async def clear_listens_endpoint(request: Request) -> dict[str, Any]:
    """Forget every counted listen of one's own. The library and likes
    are untouched."""

    store = _require_discover()
    scope = None if request_is_admin(request) else request_user_id(request)
    cleared = await asyncio.to_thread(store.clear_listens, scope)
    return {'cleared': cleared}


@router.get('/api/discover/blocked')
async def blocked_artists_endpoint(request: Request) -> list[dict[str, Any]]:
    store = _require_discover()
    scope = None if request_is_admin(request) else request_user_id(request)
    return await asyncio.to_thread(store.blocked, scope)


@router.post('/api/discover/blocked')
async def block_artist_endpoint(request: Request) -> dict[str, Any]:
    """Never suggest ``{name}`` again. Blocking twice is a no-op."""

    store = _require_discover()
    payload = await _json_object(request)
    row = await asyncio.to_thread(
        store.block, str(payload.get('name') or ''), request_user_id(request)
    )
    if row is None:
        raise HTTPException(status_code=400, detail='name is required')
    return row


@router.delete('/api/discover/blocked')
async def unblock_artist_endpoint(
    request: Request, name: str = Query(...)
) -> dict[str, Any]:
    store = _require_discover()
    scope = None if request_is_admin(request) else request_user_id(request)
    removed = await asyncio.to_thread(store.unblock, name, scope)
    return {'name': name, 'removed': removed}
