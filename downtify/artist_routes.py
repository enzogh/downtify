"""Artist routes: ``/api/artists/*``.

Registers on the shared ``api_core.router`` (under its library-only
guard) when :mod:`downtify.api` imports it; the endpoint list lives
in that module's docstring.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import mimetypes
import unicodedata
from pathlib import (
    Path,
)
from typing import (
    Any,
    Optional,
)

from fastapi import (
    HTTPException,
    Query,
    Request,
    Response,
)
from fastapi.responses import (
    FileResponse,
)
from loguru import (
    logger,
)

from . import (
    artist_photo_proxy,
    artist_profile,
    deezer,
    library_only,
    providers,
    spotify,
)
from .api_core import (
    _artist_image_kinds_to_save,
    _artist_profile_download_dir,
    library_context,
    local_catalog_for_request,
    router,
    state,
)
from .api_pipeline import (
    _json_object,
)
from .library_catalog import (
    resolve_library_file,
)


@router.get('/api/artists/search')
def search_artists_endpoint(
    query: str = Query(''), request: Request = None
) -> list[dict[str, Any]]:
    if library_only.enabled(state.settings):
        return local_catalog_for_request(request, query, 10)['artists']
    return providers.search_artists(query, limit=10)


@router.get('/api/artists/top_songs')
def artist_top_songs_endpoint(
    channel_id: str = Query(...),
) -> list[dict[str, Any]]:
    return providers.artist_top_songs_from_channel_id(channel_id)


@router.get('/api/artists/top_albums')
def artist_top_albums_endpoint(
    channel_id: str = Query(...),
) -> list[dict[str, Any]]:
    return providers.artist_top_albums_from_channel_id(channel_id)


@router.get('/api/artists/info')
def artist_info_endpoint(channel_id: str = Query(...)) -> dict[str, Any]:
    return providers.artist_info_from_channel_id(channel_id)


@router.get('/api/artists/similar')
def artist_similar_endpoint(
    channel_id: str = Query(...),
) -> list[dict[str, Any]]:
    return providers.artist_similar_from_channel_id(channel_id)


def _artist_art_entry(download_dir: Path, name: str) -> dict[str, Any]:
    """An artist's saved photo/banner URLs, each with the version
    (``*_version``, see ``artist_profile.image_version_for``) the client
    puts in the URL so a replaced image isn't shown from a browser cache."""

    entry: dict[str, Any] = {}
    for prefix, kind in (
        ('photo', artist_profile.KIND_PHOTO),
        ('banner', artist_profile.KIND_BANNER),
    ):
        entry[f'{prefix}_url'] = artist_profile.image_url_for(
            download_dir, name, kind
        )
        entry[f'{prefix}_version'] = artist_profile.image_version_for(
            download_dir, name, kind
        )
    return entry


@router.get('/api/artists/art')
def artist_art_endpoint(name: str = Query(...)) -> dict[str, Any]:
    return _artist_art_entry(_artist_profile_download_dir(), name)


def _decode_base64url(value: str) -> str:
    """*value* decoded from base64url (padding optional) to text, or
    :class:`ValueError` when it isn't valid base64url text."""

    try:
        padded = value + '=' * (-len(value) % 4)
        return base64.urlsafe_b64decode(padded.encode('ascii')).decode('utf-8')
    except ValueError as exc:
        # binascii.Error and the Unicode errors are all ValueErrors.
        raise ValueError('url is not base64url') from exc


@router.get('/api/artists/photo-proxy')
def artist_photo_proxy_endpoint(
    name: str = Query(...), url: str = ''
) -> Response:
    """DISPLAY-ONLY artist photo for the UI, never persisted.

    A photo already saved for the artist wins and is served uncached;
    otherwise Deezer's is relayed and cached by the browser for
    three hours, and so is Deezer saying the artist has none (404). A
    failure - Deezer unreachable or over its request limit, a broken
    download - is a 503 the browser is told not to keep, so the next visit
    simply asks again. Not a way to obtain a photo to keep - see
    ``downtify.artist_photo_proxy``.

    *url*, optional: the artist's picture, when the page already has it -
    Deezer's (Discover's suggestions, the Finder), YouTube Music's (the
    search page) or any of the three for a pasted artist link -
    base64url-encoded (RFC 4648 section 5, padding
    optional) so the address travels as one plain query value - relayed
    as the photo without searching Deezer for the name. Only those image
    CDNs are accepted; anything else, or a value that isn't base64url, is
    a ``400``.
    """

    cache_control = (
        f'public, max-age={artist_photo_proxy.BROWSER_CACHE_SECONDS}'
    )
    local = artist_profile.image_path_for(
        _artist_profile_download_dir(), name, artist_profile.KIND_PHOTO
    )
    if local.is_file():
        return FileResponse(
            local,
            media_type=mimetypes.guess_type(str(local))[0] or 'image/jpeg',
            # Only remote photos are cached: a saved one may be replaced
            # at any moment, so the browser revalidates it every time.
            headers={'Cache-Control': 'no-cache'},
        )
    try:
        if url:
            photo = artist_photo_proxy.fetch_photo_at(_decode_base64url(url))
        else:
            photo = artist_photo_proxy.fetch_proxied_photo(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except artist_photo_proxy.PhotoUnavailable:
        # Not "no photo": never cached, so whatever went wrong (a rate
        # limit, say) is gone the next time the page asks.
        return Response(status_code=503, headers={'Cache-Control': 'no-store'})
    if photo is None:
        # Deezer's own answer that the artist has none: cacheable, or the
        # page would re-ask for every tile on every visit.
        return Response(
            status_code=404, headers={'Cache-Control': cache_control}
        )
    data, content_type = photo
    return Response(
        content=data,
        media_type=content_type,
        headers={
            'Cache-Control': cache_control,
            'ETag': f'"{hashlib.sha1(data).hexdigest()}"',
        },
    )


@router.post('/api/artists/art/bulk')
async def artist_art_bulk_endpoint(request: Request) -> dict[str, Any]:
    """Saved photo/banner URLs for many artists in one call - the Library
    page's artist grid needs this for every tile at once, rather than one
    request per artist."""

    payload = await _json_object(request)
    names = payload.get('names')
    if not isinstance(names, list):
        return {}
    download_dir = _artist_profile_download_dir()
    result: dict[str, Any] = {}
    for raw_name in names:
        name = str(raw_name or '').strip()
        if not name or name in result:
            continue
        result[name] = _artist_art_entry(download_dir, name)
    return result


@router.get('/api/artists/art/search')
def artist_art_search_endpoint(
    name: str = Query(...),
) -> list[dict[str, Any]]:
    query = name.strip()
    if not query:
        return []
    results: list[dict[str, Any]] = [
        {
            'source': 'youtube',
            'name': artist.get('name') or '',
            'image_url': artist['cover_url'],
        }
        for artist in providers.search_artists(query, limit=8)
        if artist.get('cover_url')
    ]
    results.extend(deezer.search_artist(query, limit=8))
    return relevant_art_results(query, results)


def relevant_art_results(
    query: str, results: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The photo candidates whose artist is the one searched for.

    Both searches pad their answer with related artists (Avicii and
    Zedd for "Martin Garrix"): a photo of someone else is never the
    right pick. A result counts when one name holds the other (ignoring
    case and accents, "Martin Garrix & Dua Lipa" included). When none
    does - a misspelt or partial search - everything found is kept.
    """

    wanted = _name_key(query)
    kept = [
        row
        for row in results
        if wanted
        and (
            wanted in _name_key(row.get('name'))
            or _name_key(row.get('name')) in wanted
        )
        and _name_key(row.get('name'))
    ]
    return kept or results


def _name_key(name: Any) -> str:
    text = unicodedata.normalize('NFKD', str(name or '').casefold())
    return ''.join(c for c in text if c.isalnum())


@router.get('/api/artists/art/spotify_candidate')
def artist_art_spotify_candidate_endpoint(
    file: str = Query(''),
    kind: str = Query(artist_profile.KIND_PHOTO),
    name: str = Query(''),
) -> dict[str, Any]:
    """A Spotify photo/banner candidate for an artist.

    The artist is resolved from *file* (a library track downloaded from
    Spotify - the most reliable route, no namesake risk) when that gives
    one, else from an exact-name search on *name*.
    """

    artist_id: Optional[str] = None
    try:
        artist_id = _spotify_artist_id_from_library_file(file, name)
        if not artist_id and name.strip():
            found = spotify.search_artist_by_name(name)
            artist_id = found['id'] if found else None
        if not artist_id:
            return {}
        image_url = (
            spotify.artist_banner_url_from_id(artist_id)
            if kind == artist_profile.KIND_BANNER
            else spotify.artist_image_url_from_id(artist_id)
        )
        if not image_url:
            return {}
        artist_name = spotify.artist_name_from_id(artist_id)
    except Exception:
        logger.opt(exception=True).debug(
            'Spotify artist art candidate lookup failed (file={!r}, '
            'name={!r})',
            file,
            name,
        )
        return {}
    return {'source': 'spotify', 'name': artist_name, 'image_url': image_url}


def _spotify_artist_id_from_library_file(
    file: str, name: str = ''
) -> Optional[str]:
    """Spotify id of *name* among the artists of a library file's Spotify
    track - its first artist when *name* is blank - or ``None`` when
    *file* is empty, unknown, wasn't from Spotify, or doesn't credit
    *name* (a guest's track must not give the track's first artist)."""

    if not file.strip() or state.track_index is None:
        return None
    if resolve_library_file(file, library_context()) is None:
        return None
    track_id = state.track_index.spotify_id_for_filename(
        file.strip().replace('\\', '/')
    )
    if not track_id:
        return None
    if isinstance(name, str) and name.strip():
        return spotify.credited_artist_id_from_track_id(track_id, name)
    return spotify.primary_artist_id_from_track_id(track_id)


@router.post('/api/artists/art/from_url')
async def artist_art_from_url_endpoint(request: Request) -> dict[str, Any]:
    payload = await _json_object(request)
    name = str(payload.get('name') or '').strip()
    kind = str(payload.get('kind') or '').strip()
    image_url = str(payload.get('image_url') or '').strip()
    source = str(payload.get('source') or '').strip()
    if not name or kind not in {
        artist_profile.KIND_PHOTO,
        artist_profile.KIND_BANNER,
    }:
        raise HTTPException(status_code=400, detail='Invalid request')
    try:
        url = await asyncio.to_thread(
            artist_profile.fetch_and_save_image,
            _artist_profile_download_dir(),
            name,
            kind,
            image_url,
            source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {'url': url}


@router.post('/api/artists/art/upload')
async def artist_art_upload_endpoint(
    request: Request,
    name: str = Query(...),
    kind: str = Query(...),
    source: str = '',
) -> dict[str, Any]:
    if kind not in {artist_profile.KIND_PHOTO, artist_profile.KIND_BANNER}:
        raise HTTPException(status_code=400, detail='Invalid kind')
    content = await request.body()
    if len(content) > artist_profile.MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail='File is too large')
    try:
        url = await asyncio.to_thread(
            artist_profile.save_image,
            _artist_profile_download_dir(),
            name,
            kind,
            content,
            source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {'url': url}


@router.delete('/api/artists/art')
def artist_art_delete_endpoint(
    name: str = Query(...), kind: str = Query(...)
) -> dict[str, Any]:
    if kind not in {artist_profile.KIND_PHOTO, artist_profile.KIND_BANNER}:
        raise HTTPException(status_code=400, detail='Invalid kind')
    removed = artist_profile.delete_image(
        _artist_profile_download_dir(), name, kind
    )
    return {'removed': removed}


@router.get('/api/artists/profile')
def artist_profile_endpoint(name: str = Query(...)) -> dict[str, Any]:
    return artist_profile.load_profile(_artist_profile_download_dir(), name)


@router.get('/api/artists/top_songs/spotify')
async def artist_top_songs_saved_endpoint(
    name: str = Query(...),
) -> dict[str, Any]:
    """An artist's saved Spotify top songs (see
    ``artist_profile.profile_top_songs_ensure``), for the artist page's Top
    songs tab.

    A fresh file is returned as is. A stale one is returned right away
    while a refresh runs in the background; with no file yet the songs are
    fetched now and saved. The Spotify artist id is the one in the artist's
    profile (``platforms_id.spotify``).
    """

    artist = name.strip()
    if not artist:
        raise HTTPException(status_code=400, detail='Invalid request')
    download_dir = _artist_profile_download_dir()
    profile = artist_profile.load_profile(download_dir, artist)
    spotify_id = str(profile['platforms_id'].get('spotify') or '')
    if not spotify_id:
        raise HTTPException(
            status_code=404, detail='No Spotify artist saved for this artist'
        )
    saved, fresh = artist_profile.profile_top_songs_cached(
        download_dir, artist, spotify_id
    )
    if saved is not None:
        if not fresh:
            artist_profile.profile_top_songs_refresh_in_background(
                download_dir, artist, spotify_id
            )
        return {**saved, 'stale': not fresh}
    try:
        data = await asyncio.to_thread(
            artist_profile.profile_top_songs_ensure,
            download_dir,
            artist,
            spotify_id,
        )
    except Exception as exc:
        logger.exception('Failed to fetch top songs for {}', artist)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {**data, 'stale': False}


@router.post('/api/artists/profile/ensure')
async def artist_profile_ensure_endpoint(request: Request) -> dict[str, Any]:
    payload = await _json_object(request)
    name = str(payload.get('name') or '').strip()
    lang = str(payload.get('lang') or 'en').strip()
    track_files = payload.get('track_files')
    if not name:
        raise HTTPException(status_code=400, detail='Invalid request')
    download_dir = _artist_profile_download_dir()
    profile = await asyncio.to_thread(
        artist_profile.ensure_profile,
        download_dir,
        name,
        track_files if isinstance(track_files, list) else [],
        lang,
        track_index=state.track_index,
        image_kinds=_artist_image_kinds_to_save(state.settings),
    )
    # The artist page's Top songs tab reads this file: get it made (or
    # refreshed once it's a week old) without holding up the profile.
    artist_profile.profile_top_songs_refresh_in_background(
        download_dir, name, str(profile['platforms_id'].get('spotify') or '')
    )
    return profile


@router.post('/api/artists/profile/bio')
async def artist_profile_bio_endpoint(request: Request) -> dict[str, Any]:
    payload = await _json_object(request)
    name = str(payload.get('name') or '').strip()
    lang = str(payload.get('lang') or 'en').strip()
    source = str(payload.get('source') or artist_profile.BIO_SOURCE_AUTO)
    if not name:
        raise HTTPException(status_code=400, detail='Invalid request')
    try:
        return await asyncio.to_thread(
            artist_profile.fetch_bio,
            _artist_profile_download_dir(),
            name,
            lang,
            source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/api/artists/profile/bio/preview')
async def artist_profile_bio_preview_endpoint(
    request: Request,
) -> dict[str, str]:
    """One service's bio text for the edit modal's text box - saves
    nothing; the user keeps it (or not) with ``PUT .../bio``."""

    payload = await _json_object(request)
    name = str(payload.get('name') or '').strip()
    lang = str(payload.get('lang') or 'en').strip()
    source = str(payload.get('source') or '').strip()
    if not name:
        raise HTTPException(status_code=400, detail='Invalid request')
    try:
        bio = await asyncio.to_thread(
            artist_profile.preview_bio,
            _artist_profile_download_dir(),
            name,
            lang,
            source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {'bio': bio}


@router.delete('/api/artists/profile/bio')
def artist_profile_bio_delete_endpoint(
    name: str = Query(...),
) -> dict[str, Any]:
    return artist_profile.remove_bio(_artist_profile_download_dir(), name)


@router.put('/api/artists/profile/bio')
async def artist_profile_bio_set_endpoint(request: Request) -> dict[str, Any]:
    payload = await _json_object(request)
    name = str(payload.get('name') or '').strip()
    if not name:
        raise HTTPException(status_code=400, detail='Invalid request')
    return artist_profile.save_bio(
        _artist_profile_download_dir(), name, str(payload.get('bio') or '')
    )


@router.put('/api/artists/profile/social')
async def artist_profile_social_set_endpoint(
    request: Request,
) -> dict[str, Any]:
    payload = await _json_object(request)
    name = str(payload.get('name') or '').strip()
    if not name:
        raise HTTPException(status_code=400, detail='Invalid request')
    social = payload.get('social')
    return artist_profile.save_social(
        _artist_profile_download_dir(),
        name,
        social if isinstance(social, dict) else {},
    )


# The YouTube Music "Top songs" playlist is the artist's whole catalogue
# ranked by popularity (well over a hundred rows, with alternate editions
# of the same song), so only its head is worth listing.
YOUTUBE_TOP_SONGS_LIMIT = 50


def _resolve_artist_top_songs(url: str) -> dict[str, Any]:
    """Artist name, cover and top songs for a pasted artist URL.

    Spotify is read from the artist's own "Popular" shelf (see
    :func:`spotify.artist_top_songs_from_id`). YouTube Music prefers the
    shelf's full auto-generated playlist (see
    :func:`providers.artist_full_top_songs_from_channel_id`), cut to
    ``YOUTUBE_TOP_SONGS_LIMIT``, and falls back to the ~5 item preview on
    the artist page.
    """

    spotify_parsed = spotify.parse_spotify_url(url)
    if spotify_parsed is not None and spotify_parsed[0] == 'artist':
        _, artist_id = spotify_parsed
        try:
            name, cover_url, songs = spotify.artist_top_songs_from_id(
                artist_id
            )
        except Exception as exc:
            logger.exception('Failed to resolve Spotify artist {}', url)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            'source': 'spotify',
            'artist_id': artist_id,
            'name': name,
            'cover_url': cover_url,
            'songs': songs,
        }

    youtube_parsed = providers.parse_youtube_url(url)
    if youtube_parsed is not None and youtube_parsed[0] == 'artist':
        _, channel_or_handle = youtube_parsed
        try:
            channel_id = providers.resolve_artist_channel_id(channel_or_handle)
            info = providers.artist_info_from_channel_id(channel_id)
            songs = providers.artist_full_top_songs_from_channel_id(
                channel_id
            ) or providers.artist_top_songs_from_channel_id(channel_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception('Failed to resolve YouTube artist {}', url)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            'source': 'youtube',
            'artist_id': channel_id,
            'name': info.get('name') or channel_id,
            'cover_url': info.get('cover_url') or '',
            'songs': songs[:YOUTUBE_TOP_SONGS_LIMIT],
        }

    deezer_parsed = deezer.parse_deezer_url(url)
    if deezer_parsed is not None and deezer_parsed[0] == 'artist':
        _, artist_id = deezer_parsed
        try:
            name, cover_url, songs = deezer.artist_top_songs_from_id(artist_id)
        except Exception as exc:
            logger.exception('Failed to resolve Deezer artist {}', url)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            'source': 'deezer',
            'artist_id': artist_id,
            'name': name,
            'cover_url': cover_url,
            'songs': songs,
        }

    raise HTTPException(
        status_code=400,
        detail='A Spotify, YouTube Music or Deezer artist URL is required',
    )


@router.get('/api/artists/top_songs/url')
async def artist_top_songs_from_url_endpoint(
    url: str = Query(...),
) -> dict[str, Any]:
    return await asyncio.to_thread(_resolve_artist_top_songs, url)
