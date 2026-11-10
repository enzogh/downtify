"""Download routes: ``/api/download/*`` and ``/api/queue*``.

Registers on the shared ``api_core.router`` (under its library-only
guard) when :mod:`downtify.api` imports it; the endpoint list lives
in that module's docstring.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import (
    Any,
    Collection,
    Optional,
)

from fastapi import (
    Body,
    HTTPException,
    Query,
    Request,
)
from loguru import (
    logger,
)

from . import (
    deezer,
    library_import,
    m3u,
    providers,
    spotify,
)
from .api_core import (
    _fetch_playlist_tracks,
    _organize_enabled,
    _usernames,
    log_activity,
    request_is_admin,
    request_user_id,
    router,
    spawn_task,
    state,
)
from .api_pipeline import (
    _broadcast_queue_state,
    _drop_pending,
    _global_queue_status,
    _job_users,
    _process_batch,
    _register_job,
    _run_download,
    _searching_ahead,
    _submit_playlist_batch,
)
from .download_queue import (
    queue_pause,
)
from .downloader import (
    NoAudioMatchError,
    TrackTooLongError,
)
from .monitor import (
    SOURCE_SPOTIFY,
    parse_playlist_url,
)


def song_label(song: dict[str, Any]) -> str:
    """``Artist - Title`` for a song as the download endpoints get it."""

    artists = song.get('artists') or []
    artist = (
        ', '.join(str(a) for a in artists)
        if isinstance(artists, list)
        else str(artists)
    )
    title = str(song.get('name') or song.get('title') or '')
    return ' - '.join(part for part in (artist, title) if part)


def _playlist_context_from_hints(
    hints: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Resolve optional playlist batch/retry context from client hints."""

    if not isinstance(hints, dict):
        return {}
    name = str(
        hints.get('downtify_playlist_name') or hints.get('playlist_name') or ''
    ).strip()
    playlist_url = str(
        hints.get('downtify_playlist_url') or hints.get('playlist_url') or ''
    ).strip()
    spotify_playlist_id = (
        str(
            hints.get('downtify_spotify_playlist_id')
            or hints.get('spotify_playlist_id')
            or ''
        ).strip()
        or None
    )
    order_raw = hints.get('downtify_track_order', hints.get('track_order', 0))
    try:
        track_order = int(order_raw)
    except (TypeError, ValueError):
        track_order = 0
    track_order = max(track_order, 0)

    if not name and playlist_url:
        parsed = spotify.parse_spotify_url(playlist_url)
        if parsed is not None and parsed[0] == 'playlist':
            spotify_playlist_id = spotify_playlist_id or parsed[1]
            try:
                name, _ = _fetch_playlist_tracks(parsed[1])
            except Exception:
                logger.opt(exception=True).warning(
                    'download: failed to resolve playlist name from url'
                )
                name = ''

    subdir: Optional[str] = None
    if name and state.downloader is not None and not _organize_enabled():
        subdir = m3u.sanitize_playlist_name(name)

    return {
        'playlist_name': name or None,
        'spotify_playlist_id': spotify_playlist_id,
        'track_order': track_order,
        'subdir': subdir,
    }


def _merge_client_track_hints(
    base: dict[str, Any],
    hints: Optional[dict[str, Any]],
) -> None:
    """Copy tagging fields from the client-resolved Spotify row.

    ``POST /api/download/url`` re-fetches metadata from the URL only, which loses
    ``track_number`` for rows that came from an album/playlist browse.
    """

    if not isinstance(hints, dict) or not hints:
        return
    tn = hints.get('track_number')
    if tn is not None:
        try:
            iv = int(tn)
        except (TypeError, ValueError):
            pass
        else:
            if iv > 0:
                base['track_number'] = iv
    tt = hints.get('album_track_total')
    if tt is not None:
        try:
            tv = int(tt)
        except (TypeError, ValueError):
            pass
        else:
            if tv > 0:
                base['album_track_total'] = tv
    # The search row says whether *that* upload has explicit lyrics, which
    # the URL alone (a bare video id) can't. It only ever adds the mark.
    if hints.get('explicit') is True:
        base['explicit'] = True
    rd = hints.get('release_date')
    if isinstance(rd, str) and rd.strip():
        base['release_date'] = rd.strip()
    yr = hints.get('year')
    if isinstance(yr, str) and yr.strip():
        base['year'] = yr.strip()
    # The album artist of the album/playlist the row was listed in, so a
    # track downloaded on its own is filed and tagged like its album-mates
    # (see album_artist.py) - unless re-resolving the URL already found one.
    album_artist = hints.get('album_artist')
    if (
        isinstance(album_artist, str)
        and album_artist.strip()
        and not str(base.get('album_artist') or '').strip()
    ):
        base['album_artist'] = album_artist.strip()
        if hints.get('compilation') is True:
            base['compilation'] = True
    # A video id or SoundCloud track the user pasted to retry a failed
    # track: download exactly that audio instead of matching again. One
    # replaces the other, so a stale one can't win the provider order.
    soundcloud = providers.parse_soundcloud_url(
        str(hints.get('soundcloud_url') or '')
    )
    ytid = str(hints.get('youtube_id') or '').strip()
    if soundcloud is not None:
        base['soundcloud_url'] = soundcloud[1]
        base['soundcloud_url_override'] = True
        base.pop('youtube_id', None)
    elif ytid:
        base['youtube_id'] = ytid
        base['youtube_id_override'] = True
        base.pop('soundcloud_url', None)


_CLIENT_RESOLVED_SOURCES = {'text_search', 'deezer'}


def _song_from_download_request(
    url: str, client_hints: Optional[dict[str, Any]]
) -> dict[str, Any]:
    """The song to download for ``POST /api/download/url``.

    A slskd search stub (``source == 'text_search'``, see
    :func:`search_endpoint`), a YouTube Music search row marked for
    metadata matching, or a Deezer chart/Finder row (``source == 'deezer'``,
    see :func:`discover_chart_endpoint` and
    :func:`finder_search_endpoint`) has no URL this app
    can resolve on its own - these rows are taken from the request body as-is,
    already-resolved metadata that :func:`downtify.providers.find_match`
    can search YouTube/YouTube Music for directly.
    """

    if (
        isinstance(client_hints, dict)
        and client_hints.get('download_by_metadata') is True
    ):
        song = dict(client_hints)
        song.pop('download_by_metadata', None)
        song['_match_by_metadata'] = True
        return song
    if (
        isinstance(client_hints, dict)
        and client_hints.get('source') in _CLIENT_RESOLVED_SOURCES
    ):
        return dict(client_hints)
    song = _song_for_download(url)
    _merge_client_track_hints(song, client_hints)
    return song


def _song_for_download(url: str) -> dict[str, Any]:
    parsed = spotify.parse_spotify_url(url)
    if parsed is not None:
        kind, sid = parsed
        if kind == 'track':
            return spotify.track_from_id(sid, with_album=True)
        raise HTTPException(
            status_code=400,
            detail='Only Spotify track URLs are supported here',
        )
    youtube_parsed = providers.parse_youtube_url(url)
    if youtube_parsed is not None:
        kind, yid = youtube_parsed
        if kind == 'track':
            return providers.song_from_video_id(yid)
        raise HTTPException(
            status_code=400,
            detail='Only single YouTube video URLs are supported here',
        )
    deezer_parsed = deezer.parse_deezer_url(url)
    if deezer_parsed is not None:
        kind, did = deezer_parsed
        if kind == 'track':
            return deezer.track_from_id(did)
        raise HTTPException(
            status_code=400,
            detail='Only Deezer track URLs are supported here',
        )
    soundcloud_parsed = providers.parse_soundcloud_url(url)
    if soundcloud_parsed is not None:
        try:
            return providers.soundcloud_track_from_url(url)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception(
                'Failed to resolve SoundCloud download URL {}', url
            )
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail='Unsupported URL')


def _forget_history(song_ids: Optional[Collection[str]] = None) -> None:
    """Drop history rows taken off the queue (all when ``None``)."""

    store = state.download_history
    if store is None:
        return
    try:
        if song_ids is None:
            store.clear()
        else:
            store.forget(song_ids)
    except Exception:
        logger.exception('Could not update the download history')


@router.post('/api/download/url')
async def download_endpoint(
    request: Request,
    url: str = Query(...),
    client_id: str = Query(''),
    client_hints: Optional[dict[str, Any]] = Body(None),
):
    if state.downloader is None:
        raise HTTPException(status_code=500, detail='Downloader not ready')

    # Spotify/YouTube Music network calls: off the event loop, or every
    # other request and WebSocket stalls until they return.
    song = await asyncio.to_thread(
        _song_from_download_request, url, client_hints
    )
    # A retried track from a playlist carries its playlist in the hints,
    # so it lands in that playlist's folder and catalog.
    pl_ctx = await asyncio.to_thread(
        _playlist_context_from_hints, client_hints
    )
    logger.debug(
        'download/url: url={} body={} track_number={!r} year={!r} '
        'release_date={!r} playlist={!r}',
        url[:140],
        'json' if isinstance(client_hints, dict) else 'none',
        song.get('track_number'),
        song.get('year'),
        song.get('release_date'),
        pl_ctx.get('playlist_name'),
    )
    user_id = request_user_id(request)
    song_id = _register_job(song, status='downloading', user_id=user_id)
    await log_activity(
        request, 'download', song_label(song) or url[:200], {'url': url[:500]}
    )

    try:
        filename = await _run_download(
            song,
            song_id,
            subdir=pl_ctx.get('subdir'),
            playlist_name=pl_ctx.get('playlist_name'),
            spotify_playlist_id=pl_ctx.get('spotify_playlist_id'),
            track_order=int(pl_ctx.get('track_order') or 0),
            user_id=user_id,
        )
    except NoAudioMatchError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TrackTooLongError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return filename


@router.post('/api/download/batch')
async def download_batch_endpoint(request: Request) -> dict[str, Any]:
    if state.downloader is None:
        raise HTTPException(status_code=500, detail='Downloader not ready')

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail='Invalid JSON') from exc

    songs = payload.get('songs') or []
    if not isinstance(songs, list) or not songs:
        raise HTTPException(
            status_code=400, detail='songs must be a non-empty list'
        )
    playlist_url = str(payload.get('playlist_url') or '')
    generate_m3u = bool(payload.get('generate_m3u', True))
    # No real Spotify/YouTube Music playlist id backs this batch (e.g. an
    # artist's top songs) - the caller names the playlist and its cover
    # directly instead of us deriving them from playlist_url.
    playlist_name = str(payload.get('playlist_name') or '') or None
    cover_url = str(payload.get('cover_url') or '') or None
    first_song = next((s for s in songs if isinstance(s, dict)), {})
    await log_activity(
        request,
        'download',
        playlist_name
        or str(first_song.get('album_name') or '')
        or song_label(first_song),
        {'songs': len(songs), 'url': playlist_url[:500]},
    )

    # A Spotify playlist download is tracked as a playlist batch, so an
    # incomplete one can be finished later (see /api/playlists/incomplete).
    batch_id: Optional[int] = None
    target = parse_playlist_url(playlist_url) if playlist_url else None
    if (
        target is not None
        and target[0] == SOURCE_SPOTIFY
        and state.playlist_batch_store is not None
    ):
        first = next((s for s in songs if isinstance(s, dict)), {})
        batch_user_id = request_user_id(request)
        batch_id = await asyncio.to_thread(
            state.playlist_batch_store.start_batch,
            target[1],
            str(first.get('album_name') or '').strip() or target[1],
            playlist_url,
            len(songs),
            user_id=batch_user_id,
        )

    return await _submit_playlist_batch(
        songs,
        playlist_url,
        generate_m3u=generate_m3u,
        batch_id=batch_id,
        playlist_name=playlist_name,
        cover_url=cover_url,
        user_id=request_user_id(request),
    )


def _scope_csv_song_ids(songs: list[dict[str, Any]]) -> None:
    """Replace per-file ``csv:N`` ids with ids unique to this import.

    ``parse_library_csv`` numbers from zero on every call. Two imports
    would otherwise share ``csv:0`` and overwrite one ``download_jobs``
    entry. The token is only a queue key; it is not a Spotify track id.
    """
    token = uuid.uuid4().hex[:12]
    for index, song in enumerate(songs):
        song['song_id'] = f'csv:{token}:{index}'


@router.post('/api/download/csv')
async def download_csv_endpoint(request: Request) -> dict[str, Any]:
    """Import a library-export CSV (Soundiiz, TuneMyMusic, Exportify, ...).

    Body: ``{"csv": "<raw file text>", "playlist_name": "...",
    "generate_m3u": true}``. The CSV is read client-side and sent as
    plain text in the JSON body rather than as a multipart upload, to
    match every other endpoint here and avoid an extra dependency.

    Each row is resolved the same way a free-text search would be, via
    :func:`providers.find_match` inside :meth:`Downloader.download` -
    there is no Spotify/YouTube URL per row, only a title, artist, and
    album when the CSV has it.
    """
    if state.downloader is None:
        raise HTTPException(status_code=500, detail='Downloader not ready')

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail='Invalid JSON') from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail='Invalid payload')

    csv_text = payload.get('csv')
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise HTTPException(
            status_code=400, detail='csv must be a non-empty string'
        )

    try:
        songs = await asyncio.to_thread(
            library_import.parse_library_csv, csv_text
        )
    except library_import.LibraryCsvError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    playlist_name = (
        str(payload.get('playlist_name') or '').strip() or 'Imported Library'
    )
    generate_m3u = bool(payload.get('generate_m3u', True))
    # Parser ids restart at csv:0 on every file. The queue is keyed by
    # song_id, so a second import would replace the first import's jobs
    # and the badge /queue tabs would count the longer file only.
    _scope_csv_song_ids(songs)

    user_id = request_user_id(request)
    job_ids: list[str] = []
    for song in songs:
        song_id = _register_job(song, status='queued', user_id=user_id)
        job_ids.append(song_id)

    # Same single reload as _submit_playlist_batch. The rows are already
    # in download_jobs; clients fetch them with GET /api/queue.
    await state.connections.broadcast({'type': 'queue_reload'})

    task = spawn_task(
        _process_batch(
            songs,
            job_ids,
            '',
            generate_m3u,
            playlist_name=playlist_name,
            user_id=user_id,
        ),
        name='csv-batch',
    )

    def _log_batch_failure(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.opt(exception=exc).error('CSV batch processing crashed')

    task.add_done_callback(_log_batch_failure)
    return {
        'job_ids': job_ids,
        'count': len(job_ids),
        'playlist_name': playlist_name,
    }


def _songs_for_album_download(url: str) -> list[dict[str, Any]]:
    youtube_parsed = providers.parse_youtube_url(url)
    if youtube_parsed is None or youtube_parsed[0] != 'album':
        raise HTTPException(
            status_code=400,
            detail='Only YouTube Music album/browse URLs are supported here',
        )
    _, browse_id = youtube_parsed
    songs = providers.album_tracks_from_browse_id(browse_id)
    if not songs:
        raise HTTPException(
            status_code=404, detail='Album not found or has no tracks'
        )
    return songs


@router.post('/api/download/album')
async def download_album_endpoint(
    request: Request, url: str = Query(...)
) -> dict[str, str]:
    """Download every track of a YouTube Music album/browse URL.

    Unlike ``POST /api/download/url`` (which only accepts a single video URL
    and therefore re-resolves catalog metadata independently, per track),
    this resolves the album's full tracklist once via
    :func:`providers.album_tracks_from_browse_id` and downloads each track
    using that shared, already-consistent metadata (track number, album
    name/artist, cover, year). This matters for compilations/"best of"
    albums, whose tracks would otherwise be re-matched one video at a time
    and can drift to their original, differently-tagged source album.

    Returns a mapping of ``song_id -> downloaded filename`` for every track
    that downloaded successfully (failed tracks are omitted, not raised).
    """
    if state.downloader is None:
        raise HTTPException(status_code=500, detail='Downloader not ready')

    songs = await asyncio.to_thread(_songs_for_album_download, url)
    first_song = songs[0] if songs else {}
    await log_activity(
        request,
        'download',
        str(first_song.get('album_name') or '') or url[:200],
        {'songs': len(songs), 'url': url[:500]},
    )
    # See _process_batch: only meaningful when there's a "next" track to
    # wait for, so a single-track album never waits around for nothing.
    delay_seconds = (
        state.settings.get('download_delay_seconds', 0)
        if len(songs) > 1
        else 0
    )

    user_id = request_user_id(request)

    async def _one(song: dict[str, Any]) -> tuple[str, Optional[str]]:
        song_id = str(song.get('song_id') or '')
        if not song_id:
            return '', None
        job_id = _register_job(song, status='downloading', user_id=user_id)
        try:
            filename = await _run_download(
                song, job_id, delay_seconds=delay_seconds, user_id=user_id
            )
        except Exception:
            logger.exception('Album track download failed for {}', song_id)
            return song_id, None
        finally:
            progress.finished()
        return song_id, filename

    async with _searching_ahead(songs, None) as progress:
        results = await asyncio.gather(*(_one(song) for song in songs))
    return {
        song_id: filename
        for song_id, filename in results
        if song_id and filename
    }


def _queue_job_visible(job: dict[str, Any], request: Request) -> bool:
    """Whether the queue *job* is *request*'s own (admins see every job).

    A shared job is visible to every account waiting on it; an ownerless
    job (a system retry with no waiter yet) is admin-only.
    """

    if request_is_admin(request):
        return True
    return request_user_id(request) in _job_users(job)


@router.get('/api/queue')
def get_queue(request: Request) -> list[dict[str, Any]]:
    """The download queue: everyone's for an admin, one's own otherwise.

    Every row carries ``position``: the 1-based place among the still
    waiting jobs (``queued`` + ``downloading``) in the order shown, or
    ``None`` once finished. An admin's positions are global, a user's
    count their own slice. ``user_ids`` is the sorted waiter list; a
    shared job shows the same row (and the same position) to everyone
    waiting on it. A finished row carries ``finished_at`` (epoch
    seconds); the last :data:`downtify.download_history.KEEP_PER_ACCOUNT`
    of each account's survive a restart. ``mine`` says whether the
    caller is one of them, and
    an admin's rows name them too (``users``: usernames, empty for a
    job nobody asked for - a watch's or a retry's).
    """

    admin = request_is_admin(request)
    me = request_user_id(request)
    names = _usernames() if admin else {}
    rows: list[dict[str, Any]] = []
    position = 0
    for job in state.download_jobs.values():
        if not _queue_job_visible(job, request):
            continue
        row = dict(job)
        if job.get('status') in {'queued', 'downloading'}:
            position += 1
            row['position'] = position
        else:
            row['position'] = None
        waiters = sorted(_job_users(job))
        row['user_ids'] = waiters
        row['mine'] = bool(me and me in waiters)
        if admin:
            row['users'] = [names[uid] for uid in waiters if uid in names]
        rows.append(row)
    return rows


@router.delete('/api/queue')
def clear_queue(request: Request) -> dict:
    """Clear the queue. A job that hasn't started yet never starts;
    downloads already running finish."""

    if request_is_admin(request):
        state.download_jobs.clear()
        _drop_pending()
        _forget_history()
        return {'cleared': True}
    removed = [
        key
        for key, job in list(state.download_jobs.items())
        if _queue_job_visible(job, request)
    ]
    for song_id in removed:
        del state.download_jobs[song_id]
    _drop_pending(removed)
    _forget_history(removed)
    return {'cleared': True}


@router.delete('/api/queue/completed')
def clear_completed_queue(request: Request) -> dict:
    """Remove finished jobs so a new playlist queue is easier to read."""
    removed = [
        song_id
        for song_id, job in list(state.download_jobs.items())
        if job.get('status') == 'done' and _queue_job_visible(job, request)
    ]
    for song_id in removed:
        del state.download_jobs[song_id]
    _forget_history(removed)
    return {'removed': len(removed)}


@router.delete('/api/queue/others')
def clear_others_queue(request: Request) -> dict:
    """An admin takes the jobs they aren't waiting on off their queue:
    other accounts' downloads and the ones nobody asked for. One that
    hasn't started never starts; one already running finishes for the
    accounts waiting on it. ``403`` for anyone else (they only ever see
    their own)."""

    if not request_is_admin(request):
        raise HTTPException(status_code=403, detail='Admins only')
    me = request_user_id(request)
    removed = [
        song_id
        for song_id, job in list(state.download_jobs.items())
        if not (me and me in _job_users(job))
    ]
    for song_id in removed:
        del state.download_jobs[song_id]
    _drop_pending(removed)
    _forget_history(removed)
    return {'removed': len(removed)}


@router.delete('/api/queue/item')
def remove_queue_item(request: Request, song_id: str = Query(...)) -> dict:
    job = state.download_jobs.get(song_id)
    if job is not None and _queue_job_visible(job, request):
        del state.download_jobs[song_id]
        _drop_pending([song_id])
        _forget_history([song_id])
        return {'removed': True}
    return {'removed': False}


@router.get('/api/queue/state')
def get_queue_state(request: Request) -> dict[str, Any]:
    """Whether the queue is paused: ``{paused, state, active}``.

    ``state`` is ``running``, ``pausing`` (paused, ``active`` downloads
    still finishing) or ``paused``; ``active`` counts the downloads
    running right now, everyone's. Each change is also a ``queue_state``
    WebSocket frame.
    """

    return {
        **_global_queue_status(),
        'monitors_paused': queue_pause.paused,
        'global_pause_supported': True,
        'can_control': request_is_admin(request)
        and getattr(getattr(request.state, 'principal', None), 'kind', '')
        != 'device',
    }


async def _set_queue_paused(paused: bool) -> dict[str, Any]:
    if paused:
        queue_pause.pause()
        if state.upgrade_runner is not None and state.upgrade_runner.busy():
            state.upgrade_runner.pause()
    else:
        queue_pause.resume()
    store = state.pending_downloads
    if store is not None:
        try:
            await asyncio.to_thread(store.set_paused, paused)
        except Exception:
            logger.exception('Could not save the queue pause')
    logger.info('Download queue {}', 'paused' if paused else 'resumed')
    await _broadcast_queue_state()
    return _global_queue_status()


@router.post('/api/queue/pause')
async def pause_queue() -> dict[str, Any]:
    """Start no new download until resumed; running ones finish."""

    return await _set_queue_paused(True)


@router.post('/api/queue/resume')
async def resume_queue() -> dict[str, Any]:
    """Carry on with the waiting jobs, with the current settings."""

    return await _set_queue_paused(False)
