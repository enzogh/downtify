"""Playback routes: ``/api/stream*`` and ``/api/preview``.

Registers on the shared ``api_core.router`` (under its library-only
guard) when :mod:`downtify.api` imports it; the endpoint list lives
in that module's docstring.
"""

from __future__ import annotations

import asyncio
from pathlib import (
    Path,
)
from typing import (
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
    StreamingResponse,
)
from loguru import (
    logger,
)

from . import (
    deezer,
    stream,
)
from .api_core import (
    DEFAULT_SETTINGS,
    _clamp_track_duration,
    request_user_id,
    router,
    spawn_task,
    state,
)
from .api_pipeline import (
    _json_object,
)
from .downloader import (
    TrackTooLongError,
)
from .live_stream import (
    RangeNotSatisfiable,
)
from .stream import (
    StreamCache,
)
from .traffic import (
    DIRECTION_IN,
)


def _max_track_duration_seconds() -> int:
    """The live duration bound (downloads and streams share it)."""

    return _clamp_track_duration(
        state.settings.get(
            'max_track_duration_seconds',
            DEFAULT_SETTINGS['max_track_duration_seconds'],
        )
    )


def record_stream_fetch_traffic(video_path: Path, user_id: int) -> None:
    """Count a stream-cache fetch's bytes as upstream (it served no one
    yet - the serve itself is counted on the way out)."""

    if not user_id or state.traffic is None:
        return
    try:
        state.traffic.add(user_id, DIRECTION_IN, video_path.stat().st_size)
    except Exception:
        logger.opt(exception=True).debug(
            'Could not record stream traffic for {}', video_path
        )


@router.get('/api/preview')
async def song_preview_endpoint(
    artist: str = Query(...),
    title: str = Query(...),
    duration: Optional[float] = Query(None),
) -> dict[str, str]:
    """A song's 30 s preview clip from Deezer, for a song without one of
    its own (a YouTube Music result, a long Spotify playlist's later
    tracks). ``""`` when Deezer has no song by that artist with that
    title; ``503`` when Deezer couldn't be asked."""

    try:
        url = await asyncio.to_thread(
            deezer.find_track_preview, artist, title, duration
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {'preview_url': url}


@router.get('/api/stream')
async def stream_endpoint(
    video_id: str = Query(..., min_length=1, max_length=64),
) -> dict[str, str]:
    """A track's full audio as a fresh direct URL (``?video_id=``).

    What plays in the built-in player when the song behind a row isn't
    downloaded yet: no download, no tags, nothing stored. The URL is
    short-lived and bound to this server's network, so it is fetched
    on demand and never cached or persisted - ask again rather than
    storing it. ``400`` for a malformed id, ``503`` when YouTube can't
    be reached or refuses (including age-gated tracks without usable
    cookies - see Settings > YouTube cookies).
    """

    try:
        vid = stream.clean_video_id(video_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        cookies = await asyncio.to_thread(
            stream.resolve_cookies_file, state.cookies_store
        )
        resolved = await asyncio.to_thread(
            stream.stream_url_for_video, vid, cookies_file=cookies
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {'url': resolved['url']}


@router.get('/api/stream/file')
async def stream_file_endpoint(
    request: Request,
    video_id: str = Query(..., min_length=1, max_length=64),
    duration: float = Query(0, ge=0),
) -> FileResponse:
    """A track's full audio, downloaded once and served from this server.

    ``GET /api/stream/file?video_id=`` is what the web player behind a
    song that isn't downloaded yet plays: the first request downloads
    the audio into ``/data/stream_cache`` (concurrent requests for the
    same video share one download), later ones are served from disk.
    Served with seeking support, pruned least-recently-used past
    ``DOWNTIFY_STREAM_CACHE_MB`` (see ``downtify.stream``). ``duration``
    (seconds, when the caller knows it) refuses long tracks before any
    download; the served file is probed either way. ``400`` for a
    malformed id or a track past the duration limit (Settings →
    Downloads), ``503`` when YouTube can't provide the audio.
    """

    try:
        vid = stream.clean_video_id(video_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    limit = _max_track_duration_seconds()
    if limit and duration > limit:
        raise HTTPException(
            status_code=400, detail=stream.too_long_detail(limit)
        )
    cache = state.stream_cache
    if cache is None:
        raise HTTPException(
            status_code=503, detail='Streaming is not ready yet'
        )
    cookies = stream.resolve_cookies_file(state.cookies_store)
    was_cached = await asyncio.to_thread(cache.cached_path, vid) is not None
    try:
        path = await cache.get(vid, cookies_file=cookies, max_seconds=limit)
    except TrackTooLongError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not was_cached:
        record_stream_fetch_traffic(path, request_user_id(request))
    return FileResponse(
        str(path),
        media_type=stream.media_type_for(path),
        filename=f'{vid}{path.suffix}',
    )


async def _prefetch_stream_video(
    cache: StreamCache,
    video_id: str,
    cookies_file: str,
    max_seconds: Optional[int] = None,
) -> None:
    """Cache one video's audio in the background (never raises)."""

    try:
        await cache.get(
            video_id, cookies_file=cookies_file, max_seconds=max_seconds
        )
    except Exception:
        logger.debug('Stream prefetch failed for videoId={}', video_id)


@router.post('/api/stream/prefetch')
async def stream_prefetch_endpoint(request: Request) -> dict[str, bool]:
    """Start caching a video's audio without waiting for it.

    Body ``{video_id}``; answers ``{queued: true}`` at once while the
    download continues detached, so the player can warm the next track
    up while the current one is still loading. ``400`` for a malformed
    id, ``503`` when streaming isn't ready.
    """

    payload = await _json_object(request)
    try:
        vid = stream.clean_video_id(payload.get('video_id'))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cache = state.stream_cache
    if cache is None:
        raise HTTPException(
            status_code=503, detail='Streaming is not ready yet'
        )
    cookies = stream.resolve_cookies_file(state.cookies_store)
    spawn_task(
        _prefetch_stream_video(
            cache, vid, cookies, _max_track_duration_seconds()
        ),
        name=f'stream-prefetch-{vid}',
    )
    return {'queued': True}


@router.api_route(
    '/api/stream/live', methods=['GET', 'HEAD'], response_model=None
)
async def stream_live_endpoint(
    request: Request,
    video_id: str = Query(..., min_length=1, max_length=64),
    duration: float = Query(0, ge=0),
) -> Response:
    """A track's full audio relayed live from YouTube (``?video_id=``).

    What the web player plays for a song that isn't downloaded yet:
    playback starts as soon as YouTube's first bytes arrive instead of
    after a whole download (``/api/stream/file``). ``Range`` requests
    are forwarded, so seeking works; nothing is written to disk (see
    ``downtify.live_stream``). ``duration`` (seconds, when the caller
    knows it) refuses long tracks before anything is resolved, and the
    resolved length is checked either way. ``400`` for a malformed id
    or a track past the duration limit, ``416`` for a range past the
    end, ``503`` when YouTube can't provide the audio.
    """

    try:
        vid = stream.clean_video_id(video_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await relay_live_audio(
        request, vid, duration, user_id=request_user_id(request)
    )


async def relay_live_audio(
    request: Request, vid: str, duration: float, *, user_id: int
) -> Response:
    """Relay video *vid*'s audio live from YouTube (see
    ``GET /api/stream/live``), the bytes counted to *user_id* - also what
    a public song link plays for a song that isn't downloaded."""

    limit = _max_track_duration_seconds()
    if limit and duration > limit:
        raise HTTPException(
            status_code=400, detail=stream.too_long_detail(limit)
        )
    live = state.live_streams
    cookies = stream.resolve_cookies_file(state.cookies_store)
    try:
        source = await live.source(vid, cookies_file=cookies)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if limit and source.duration > limit:
        raise HTTPException(
            status_code=400, detail=stream.too_long_detail(limit)
        )

    def count(sent: int) -> None:
        if user_id and state.traffic is not None:
            state.traffic.add(user_id, DIRECTION_IN, sent)

    try:
        relayed = await live.open(
            vid,
            request.headers.get('range'),
            cookies_file=cookies,
            on_bytes=count,
        )
    except RangeNotSatisfiable as exc:
        return Response(
            status_code=416,
            headers={'Content-Range': f'bytes */{exc.total}'},
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if request.method == 'HEAD':
        relayed.body.close()
        return Response(
            status_code=relayed.status,
            headers=relayed.headers,
            media_type=relayed.media_type,
        )
    return StreamingResponse(
        relayed.body,
        status_code=relayed.status,
        headers=relayed.headers,
        media_type=relayed.media_type,
    )


async def _prefetch_live_stream(video_id: str, cookies_file: str) -> None:
    """Resolve one video's live source in the background (never raises)."""

    try:
        await state.live_streams.source(video_id, cookies_file=cookies_file)
    except Exception:
        logger.debug('Live stream prefetch failed for videoId={}', video_id)


@router.post('/api/stream/live/prefetch')
async def stream_live_prefetch_endpoint(request: Request) -> dict[str, bool]:
    """Resolve a video's live audio URL without waiting for it.

    Body ``{video_id}``; answers ``{queued: true}`` at once, so the
    player's next track starts as fast as a cached one. ``400`` for a
    malformed id.
    """

    payload = await _json_object(request)
    try:
        vid = stream.clean_video_id(payload.get('video_id'))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cookies = stream.resolve_cookies_file(state.cookies_store)
    spawn_task(
        _prefetch_live_stream(vid, cookies),
        name=f'stream-live-prefetch-{vid}',
    )
    return {'queued': True}
