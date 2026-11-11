"""Library routes: ``/api/library/*`` (minus playlists) and ``/api/likes``.

Registers on the shared ``api_core.router`` (under its library-only
guard) when :mod:`downtify.api` imports it; the endpoint list lives
in that module's docstring.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import threading
import time
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from pathlib import (
    Path,
)
from typing import (
    Any,
    Optional,
)
from urllib.parse import (
    quote,
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
    audio_replace,
    compilation,
    cover_sources,
    library_upgrade,
    library_visibility,
    lyrics,
    m3u,
    providers,
    track_metadata,
)
from .api_core import (
    _artist_image_kinds_to_save,
    _save_settings,
    _ui_language,
    admin_hidden_rules,
    allowed_entry_keys,
    bind_lrc_resolver,
    entries_for_request,
    filter_paths_for_request,
    library_context,
    log_activity,
    normalize_lyrics_location,
    request_is_admin,
    request_user_id,
    router,
    spawn_task,
    state,
)
from .api_pipeline import (
    _admin_like_scope,
    _announce_likes,
    _clear_likes,
    _download_slot,
    _json_object,
    _queue_turn,
    _register_job,
    _require_likes,
    _sync_liked_playlist,
    _unmap_extra_roots,
    _unmap_removed_extra_folders,
    _usage_library_inputs,
    announce_library_changed,
    likes_scope,
)
from .download_queue import (
    queue_pause,
)
from .downloader import (
    DOWNLOAD_EXECUTOR,
)
from .external_library import (
    effective_external_library,
)
from .external_sync import (
    ExternalSyncJob,
    run_external_sync,
)
from .library_catalog import (
    entry_content_key,
    library_album_index,
    library_artist_index,
    library_home_summary,
    list_library_paths,
    listing_for_request,
    lookup_library_songs,
    refresh_library_listing_files,
    resolve_library_file,
)
from .library_metadata import (
    read_audio_metadata,
)
from .library_paths_cache import (
    invalidate_library_paths_cache,
)
from .library_reconcile import (
    reconcile_and_refresh,
)
from .library_usage import (
    snapshot_of,
    usage_report,
)
from .library_visibility import (
    HiddenRules,
    LibraryVisibility,
)
from .likes import (
    LIKED_PLAYLIST_NAME,
    content_key_for,
    remap_moved,
)
from .storage_scan import (
    plan_folders,
    scan_folders,
)
from .watch_stats import (
    DEFAULT_DAYS,
    clamp_days,
)


def rekey_file_owners(
    old_key: str, new_key: str, stored_path: str = ''
) -> None:
    """Point ownership rows (and a hidden song's rule) at a rewritten
    file (best effort)."""

    if state.track_owners is not None:
        try:
            state.track_owners.rekey(old_key, new_key, stored_path)
        except Exception:
            logger.opt(exception=True).debug(
                'Could not rekey owners for {}', stored_path
            )
    # A hidden song stays hidden after its file is rewritten.
    if state.library_visibility is not None:
        try:
            state.library_visibility.rekey_track(old_key, new_key, stored_path)
        except Exception:
            logger.opt(exception=True).debug(
                'Could not rekey hidden item for {}', stored_path
            )
    # So does a song hidden from a playlist.
    if state.playlist_hidden is not None:
        try:
            state.playlist_hidden.rekey(old_key, new_key, stored_path)
        except Exception:
            logger.opt(exception=True).debug(
                'Could not rekey hidden playlist song {}', stored_path
            )
    # And what fetched it.
    if state.file_providers is not None:
        try:
            state.file_providers.rekey(old_key, new_key, stored_path)
        except Exception:
            logger.opt(exception=True).debug(
                'Could not rekey the provider of {}', stored_path
            )
    # And its public links.
    if state.song_links is not None:
        try:
            state.song_links.rekey(old_key, new_key, stored_path)
        except Exception:
            logger.opt(exception=True).debug(
                'Could not rekey the song links of {}', stored_path
            )


#: Slot owner of an admin's audio replacement (it has no account id).
_AUDIO_REPLACE_OWNER = 'audio-replace'


@router.post('/api/library/reconcile')
async def reconcile_library_endpoint() -> dict[str, Any]:
    """Detect moved files and refresh playlist M3U / Navidrome."""

    if state.downloader is None:
        raise HTTPException(status_code=500, detail='Downloader not ready')
    download_dir = Path(state.downloader.download_dir)

    def _run() -> dict[str, Any]:
        result = reconcile_and_refresh(
            download_dir,
            state.settings,
            state.downloader,
            track_index=state.track_index,
            playlist_catalog=state.playlist_catalog,
            monitor_db=state.monitor_db,
            navidrome_index=state.navidrome_index,
            refresh_playlists=True,
            playlist_spotify_cache=state.playlist_spotify_cache,
            cover_cache=state.cover_cache,
            metadata_cache=state.metadata_cache,
        )
        invalidate_library_paths_cache()
        if state.likes is not None:
            moved = remap_moved(state.likes, library_context())
            result['likes_updated'] = moved
            if moved:
                _sync_liked_playlist()
                _announce_likes()
        return result

    return await asyncio.to_thread(_run)


def _require_external_sync() -> ExternalSyncJob:
    if state.external_sync is None:
        raise HTTPException(
            status_code=503, detail='Extra-folder sync is not ready'
        )
    return state.external_sync


def broadcast_external_sync(status: dict[str, Any]) -> None:
    """Push extra-folder sync status from a worker thread."""

    loop = state.loop
    if loop is None:
        return
    asyncio.run_coroutine_threadsafe(
        state.connections.broadcast({
            'type': 'external_sync',
            'sync': status,
        }),
        loop,
    )


@router.post('/api/library/external/sync')
async def sync_external_library_endpoint(
    request: Request,
) -> dict[str, Any]:
    """Start a background scan of extra library folders.

    Optional JSON body ``{folders: ["/path", ...]}`` is saved into
    settings first (absolute paths only). The request returns the job
    status immediately; poll ``GET /api/library/external/sync`` or listen
    for ``external_sync`` WebSocket frames for the last-finished log.
    """

    payload = await _json_object(request)
    if 'folders' in payload:
        previous = dict(state.settings)
        state.settings['external_library'] = effective_external_library({
            'external_library': {
                **state.settings.get('external_library', {}),
                'folders': payload.get('folders'),
            }
        })
        if state.settings_path is not None:
            _save_settings(state.settings_path, state.settings)
        invalidate_library_paths_cache()
        _unmap_removed_extra_folders(previous, state.settings)

    job = _require_external_sync()
    if not job.try_begin():
        raise HTTPException(
            status_code=409,
            detail='A folder sync is already running',
        )
    download_dir = (
        Path(state.downloader.download_dir)
        if state.downloader is not None
        else Path('/downloads')
    )
    snapshot = job.snapshot()
    broadcast_external_sync(snapshot)

    async def _run() -> None:
        await asyncio.to_thread(
            run_external_sync,
            job,
            ctx=library_context(),
            download_dir=download_dir,
            settings=state.settings,
            lang=_ui_language(),
            image_kinds=_artist_image_kinds_to_save(state.settings),
            lyrics_cache=state.lyrics_cache,
            cover_cache=state.cover_cache,
            on_update=broadcast_external_sync,
        )

    spawn_task(_run(), name='external-library-sync')
    return snapshot


@router.get('/api/library/external/sync')
def get_external_sync_endpoint() -> dict[str, Any]:
    """Running extra-folder sync, or the last finished log."""

    return _require_external_sync().snapshot()


@router.post('/api/library/external/unmap')
async def unmap_external_folder_endpoint(
    request: Request,
) -> dict[str, Any]:
    """Stop mapping a folder: drop it from the library, keep the audio."""

    payload = await _json_object(request)
    raw = str(payload.get('folder') or '').strip()
    if not raw:
        raise HTTPException(status_code=400, detail='folder is required')
    root = Path(raw)
    previous = dict(state.settings)
    folders = [
        item
        for item in effective_external_library(state.settings)['folders']
        if Path(item) != root and str(item) != raw
    ]
    state.settings['external_library'] = effective_external_library({
        'external_library': {
            **state.settings.get('external_library', {}),
            'folders': folders,
        }
    })
    if state.settings_path is not None:
        _save_settings(state.settings_path, state.settings)
    result = _unmap_extra_roots([root], previous)
    normalize_lyrics_location(state.settings)
    bind_lrc_resolver()
    return {
        **result,
        'folders': list(effective_external_library(state.settings)['folders']),
    }


# ---------------------------------------------------------------------------
# Replacing a track's audio with a version picked by hand
# ---------------------------------------------------------------------------


_VIDEO_ID_RE = re.compile(r'^[A-Za-z0-9_-]{11}$')

# Files whose audio is being replaced right now.
_replacing: set[str] = set()


def _replaceable_track(file: str) -> tuple[Path, dict[str, Any]]:
    """A library file and its tags, or 404/400."""

    full = resolve_library_file(file, library_context())
    if full is None:
        raise HTTPException(status_code=404, detail='File not found')
    try:
        audio_replace.replacement_format(full)
    except audio_replace.ReplaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return full, read_audio_metadata(full)


def _track_summary(file: str, entry: dict[str, Any]) -> dict[str, Any]:
    return {
        'file': file,
        'title': str(entry.get('title') or ''),
        'artist': str(entry.get('artist') or '').replace(';', ', '),
        'album': str(entry.get('album') or ''),
        'duration': round(float(entry.get('duration') or 0), 1),
    }


@router.get('/api/library/replace/candidates')
async def replace_candidates(
    file: str = Query(...), query: str = Query('')
) -> dict[str, Any]:
    """Versions of a library track to replace its audio with:
    ``{track, query, candidates}``. ``query`` defaults to "Artist -
    Title"; a YouTube or YouTube Music link is that one video, a
    SoundCloud track link that track (its ``video_id`` is the track URL).
    Each candidate is ``{video_id, title, artist, album, duration,
    duration_diff, thumbnail, source, url}``."""

    full, entry = await asyncio.to_thread(_replaceable_track, file)
    text = query.strip() or audio_replace.search_query(entry)
    try:
        found = await asyncio.to_thread(audio_replace.candidates, text)
    except audio_replace.ReplaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    length = float(entry.get('duration') or 0)
    for row in found:
        row['duration_diff'] = (
            round(row['duration'] - length)
            if row['duration'] and length
            else None
        )
    return {
        'track': _track_summary(file, entry),
        'query': text,
        'candidates': found,
    }


@router.post('/api/library/replace')
async def replace_track_audio(request: Request) -> dict[str, Any]:
    """Replace a library track's audio with a YouTube video:
    ``{file, video_id}`` -> ``{job_id, file}`` (``video_id`` may be a
    SoundCloud track URL instead). Runs as a queue job (the
    usual progress messages, ``song.song_id`` = ``job_id``); the file keeps
    its path, format and tags."""

    payload = await _json_object(request)
    file = str(payload.get('file') or '').strip().replace('\\', '/')
    video_id = str(payload.get('video_id') or '').strip()
    if not file:
        raise HTTPException(status_code=400, detail='file is required')
    soundcloud = providers.parse_soundcloud_url(video_id)
    if soundcloud is not None:
        video_id = soundcloud[1]
    elif not _VIDEO_ID_RE.fullmatch(video_id):
        raise HTTPException(status_code=400, detail='Unknown video')
    if state.downloader is None:
        raise HTTPException(status_code=500, detail='Downloader not ready')
    full, entry = await asyncio.to_thread(_replaceable_track, file)
    if file in _replacing:
        raise HTTPException(
            status_code=409, detail='This track is already being replaced'
        )
    summary = _track_summary(file, entry)
    song = {
        'song_id': f'replace:{file}',
        'name': summary['title'] or full.stem,
        'artists': [
            a.strip() for a in summary['artist'].split(',') if a.strip()
        ],
        'album_name': summary['album'],
        'cover_url': f'/cover?file={quote(file)}',
        'duration': summary['duration'],
        'url': (
            video_id
            if soundcloud is not None
            else f'https://music.youtube.com/watch?v={video_id}'
        ),
        # Tells the queue this job replaces a file's audio: a retry
        # replaces again instead of downloading a new track.
        'replace': {'file': file, 'video_id': video_id},
    }
    job_id = _register_job(song, status='downloading')
    _replacing.add(file)
    await log_activity(
        request,
        'audio_replaced',
        f'{summary["artist"]} - {summary["title"]}'.strip(' -'),
        {'file': file, 'video_id': video_id},
    )
    spawn_task(
        _run_replacement(job_id, song, file, full, video_id),
        name=f'replace-{video_id}',
    )
    return {'job_id': job_id, 'file': file}


async def _run_replacement(
    job_id: str,
    song: dict[str, Any],
    file: str,
    full: Path,
    video_id: str,
) -> None:
    loop = state.loop or asyncio.get_running_loop()
    job = state.download_jobs[job_id]

    def progress(
        pct: float, message: str, provider: Optional[str] = None
    ) -> None:
        job.update(progress=pct, message=message, provider=provider or '')
        asyncio.run_coroutine_threadsafe(
            state.connections.broadcast({
                'song': song,
                'progress': pct,
                'message': message,
                'provider': provider or '',
                'status': 'downloading',
            }),
            loop,
        )

    try:
        old_key = content_key_for(full) or ''
    except Exception:
        old_key = ''
    try:
        await state.connections.broadcast({
            'song': song,
            'progress': 0,
            'message': 'Replacing audio',
            'status': 'downloading',
        })
        async with _download_slot(_AUDIO_REPLACE_OWNER):
            if not await _queue_turn(job_id, job, song):
                _replacing.discard(file)
                return
            async with queue_pause.running():
                await loop.run_in_executor(
                    DOWNLOAD_EXECUTOR,
                    lambda: audio_replace.replace_audio(
                        state.downloader,
                        full,
                        video_id,
                        song=song,
                        progress_cb=progress,
                    ),
                )
    except Exception as exc:
        _replacing.discard(file)
        logger.opt(
            exception=not isinstance(exc, audio_replace.ReplaceError)
        ).warning('Replacing the audio of {} failed: {}', file, exc)
        message = f'Error: {exc}'
        job.update(status='error', message=message)
        await state.connections.broadcast({
            'song': song,
            'progress': 0,
            'message': message,
            'status': 'error',
        })
        return
    _replacing.discard(file)
    await asyncio.to_thread(_after_replacement, file, full, old_key)
    job.update(status='done', progress=100, filename=file, message='Replaced')
    await state.connections.broadcast({
        'song': song,
        'progress': 100,
        'message': 'Replaced',
        'status': 'done',
        'filename': file,
    })
    announce_library_changed()


def _after_replacement(file: str, full: Path, old_key: str = '') -> None:
    """The caches that describe the file by its contents catch up."""

    if state.metadata_cache is not None:
        try:
            state.metadata_cache.refresh(file, full)
        except Exception:
            logger.debug('Metadata cache refresh failed for {}', file)
    # The listing the Library reads, right away (see the function).
    try:
        refresh_library_listing_files(library_context(), [file])
    except Exception:
        logger.opt(exception=True).debug(
            'Library listing refresh failed for {}', file
        )
    if state.track_index is not None:
        spotify_id = state.track_index.spotify_id_for_filename(file)
        if spotify_id:
            state.track_index.register(spotify_id, file, full_path=full)
    if old_key and state.track_owners is not None:
        try:
            new_key = content_key_for(full) or ''
            if new_key:
                state.track_owners.rekey(old_key, new_key, file)
        except Exception:
            logger.opt(exception=True).debug(
                'Could not rekey owners for {}', file
            )
    invalidate_library_paths_cache(notify=False)


def _require_admin(request: Request) -> None:
    if not request_is_admin(request):
        raise HTTPException(status_code=403, detail='Admins only')


def _editable_track(file: str) -> tuple[Path, dict[str, Any]]:
    """A library file and its tags, or 404."""

    full = resolve_library_file(file, library_context())
    if full is None:
        raise HTTPException(status_code=404, detail='File not found')
    return full, read_audio_metadata(full)


@router.get('/api/library/metadata')
async def track_metadata_endpoint(
    request: Request, file: str = Query(...), query: str = Query('')
) -> dict[str, Any]:
    """A track's tags and suggestions to edit them with (admins):
    ``{track, query, suggestions}``. ``query`` defaults to "Artist
    Title"; each suggestion is ``{source, name, artists, album_name,
    album_artist, year, release_date, track_number, genre, explicit,
    cover_url}`` (``source``: ``applemusic``, ``deezer`` or
    ``youtube``) - see ``downtify/track_metadata.py``."""

    _require_admin(request)
    file = file.strip().replace('\\', '/')
    _full, entry = await asyncio.to_thread(_editable_track, file)
    current = track_metadata.suggestion(
        {
            'name': entry.get('title'),
            'artists': entry.get('artists') or [entry.get('artist') or ''],
            'album_name': entry.get('album'),
            'album_artist': entry.get('album_artist'),
            'year': entry.get('year'),
            'release_date': entry.get('release_date'),
            'track_number': entry.get('track_number'),
            'genre': entry.get('genre'),
            'explicit': entry.get('explicit'),
        },
        'current',
    )
    text = (
        query.strip()
        or ' '.join([', '.join(current['artists']), current['name']]).strip()
    )
    found = await asyncio.to_thread(track_metadata.suggestions, text)
    return {
        'track': {**current, 'file': file},
        'query': text,
        'suggestions': found,
    }


@router.post('/api/library/metadata')
async def edit_track_metadata(request: Request) -> dict[str, Any]:
    """Write a track's tags (admins): ``{file, name, artists,
    album_name, album_artist, year, release_date, track_number, genre,
    explicit, cover_url}`` -> ``{file}``. Same path; a ``cover_url``
    replaces the cover, none keeps it."""

    _require_admin(request)
    payload = await _json_object(request)
    file = str(payload.get('file') or '').strip().replace('\\', '/')
    if not file:
        raise HTTPException(status_code=400, detail='file is required')
    try:
        edit = track_metadata.clean_edit(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    full, _entry = await asyncio.to_thread(_editable_track, file)
    try:
        old_key = content_key_for(full) or ''
    except Exception:
        old_key = ''
    try:
        await asyncio.to_thread(track_metadata.write_tags, full, edit)
    except Exception as exc:
        logger.opt(exception=True).warning('Editing tags of {} failed', file)
        raise HTTPException(
            status_code=500, detail='Could not write the tags'
        ) from exc
    await asyncio.to_thread(_after_replacement, file, full, old_key)
    if edit.get('cover_url') and state.cover_cache is not None:
        await asyncio.to_thread(state.cover_cache.refresh, file, full)
    await log_activity(
        request,
        'metadata_edited',
        f'{", ".join(edit["artists"])} - {edit["name"]}',
        {'file': file},
    )
    announce_library_changed()
    return {'file': file}


@router.post('/api/library/compilation')
async def set_album_compilation_endpoint(request: Request) -> dict[str, Any]:
    """Mark (``compilation: true``) or unmark an album as a various-artists
    compilation: ``{files, compilation}`` -> ``{album, album_artist,
    compilation, changed, failed}``. Rewrites only the album-artist tag and
    the compilation flag of every file, keeps them where they are, and
    remembers the album for its later downloads.

    Files already in the asked state are only re-read into the Library's
    listing (``changed`` is empty): the button is only offered from a
    listing that disagrees with the tags, so that listing is what's stale.
    """

    if state.compilation_marks is None:
        raise HTTPException(status_code=500, detail='Library not ready')
    payload = await _json_object(request)
    raw_files = payload.get('files')
    if not isinstance(raw_files, list) or not raw_files:
        raise HTTPException(status_code=400, detail='files is required')
    want = payload.get('compilation')
    if not isinstance(want, bool):
        raise HTTPException(
            status_code=400, detail='compilation must be true or false'
        )
    ctx = library_context()
    files: list[tuple[str, Path]] = []
    for raw in raw_files:
        file = str(raw or '').strip().replace('\\', '/')
        full = resolve_library_file(file, ctx) if file else None
        if full is None:
            raise HTTPException(
                status_code=404, detail=f'File not found: {file}'
            )
        files.append((file, full))
    # A rewrite can change a file's size, so its content key: whatever is
    # keyed by it (owners, hidden rules, provider) follows it below.
    old_keys = {file: content_key_for(full) or '' for file, full in files}

    try:
        result = await asyncio.to_thread(
            compilation.set_album_compilation,
            files,
            compilation=want,
            marks=state.compilation_marks,
        )
    except compilation.AlreadyInStateError as exc:
        for file, full in files:
            await asyncio.to_thread(_after_replacement, file, full)
        announce_library_changed()
        return {
            'album': exc.result.album,
            'album_artist': exc.result.album_artist,
            'compilation': exc.result.compilation,
            'changed': [],
            'failed': [],
        }
    except compilation.CompilationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    for file in result.changed:
        full = dict(files)[file]
        new_key = content_key_for(full) or ''
        if old_keys[file] and new_key and new_key != old_keys[file]:
            rekey_file_owners(old_keys[file], new_key, file)
        await asyncio.to_thread(_after_replacement, file, full)
    if result.changed:
        announce_library_changed()
    await log_activity(
        request,
        'album_compilation',
        f'{result.album_artist} - {result.album}'.strip(' -'),
        {
            'album': result.album,
            'compilation': result.compilation,
            'files': len(result.changed),
        },
    )
    return {
        'album': result.album,
        'album_artist': result.album_artist,
        'compilation': result.compilation,
        'changed': result.changed,
        'failed': result.failed,
    }


# ---------------------------------------------------------------------------
# Library upgrade (scan an existing library, then repair it)
# ---------------------------------------------------------------------------


def _require_upgrade_runner() -> library_upgrade.LibraryUpgradeRunner:
    if state.upgrade_runner is None:
        raise HTTPException(
            status_code=500, detail='Library upgrade not ready'
        )
    return state.upgrade_runner


def _upgrade_options(
    payload: dict[str, Any],
) -> library_upgrade.UpgradeOptions:
    """Request body over the saved defaults."""

    saved = state.settings.get('library_upgrade') or {}
    merged = {**saved, **(payload or {})}
    return library_upgrade.options_from(merged)


def _upgrade_payload(
    runner: library_upgrade.LibraryUpgradeRunner,
) -> dict[str, Any]:
    payload = runner.status()
    payload['categories'] = list(library_upgrade.CATEGORIES)
    payload['artwork_sources'] = list(cover_sources.ARTWORK_SOURCES)
    payload['deemix_available'] = bool(
        (state.settings.get('deemix') or {}).get('enabled')
    )
    return payload


@router.get('/api/library/upgrade')
def library_upgrade_status() -> dict[str, Any]:
    """The current (or last) upgrade run, its queue counts and scan totals."""

    return _upgrade_payload(_require_upgrade_runner())


@router.get('/api/library/upgrade/jobs')
def library_upgrade_jobs(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    """Tracks in the current run, newest activity first."""

    runner = _require_upgrade_runner()
    run = runner.db.latest_run()
    if run is None:
        return []
    return runner.db.jobs(int(run['id']), status=status, limit=limit)


@router.post('/api/library/upgrade/scan')
async def library_upgrade_scan(
    payload: dict[str, Any] = Body(default={}),
) -> dict[str, Any]:
    """Look at every library track and report what is behind.

    Nothing is written: the scan fills a queue the client then confirms
    with ``/api/library/upgrade/start``.
    """

    runner = _require_upgrade_runner()
    try:
        return runner.start_scan(_upgrade_options(payload))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/api/library/upgrade/start')
async def library_upgrade_start(
    payload: dict[str, Any] = Body(default={}),
) -> dict[str, Any]:
    """Begin upgrading the scanned tracks, for the chosen categories."""

    runner = _require_upgrade_runner()
    categories = library_upgrade.normalize_categories(
        (payload or {}).get('categories')
    )
    try:
        return runner.start(categories)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/api/library/upgrade/pause')
async def library_upgrade_pause() -> dict[str, Any]:
    """Stop after the track being worked on; the queue is kept."""

    return _require_upgrade_runner().pause()


@router.post('/api/library/upgrade/resume')
async def library_upgrade_resume() -> dict[str, Any]:
    runner = _require_upgrade_runner()
    try:
        return runner.resume()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/api/library/upgrade/cancel')
async def library_upgrade_cancel() -> dict[str, Any]:
    """Drop the rest of the queue. Finished tracks stay upgraded."""

    return _require_upgrade_runner().cancel()


@router.get('/api/library/summary')
def library_summary(request: Request) -> dict[str, Any]:
    """Home-page library stats and a short recent-album shelf.

    Avoids sending every ``GET /tracks`` row to the browser when the
    page only shows counts and a handful of albums. A user's counts leave
    out what an admin hid from users.
    """

    return library_home_summary(
        library_context(), allowed_keys=allowed_entry_keys(request)
    )


@router.get('/api/library/albums')
def library_albums(request: Request) -> list[dict[str, Any]]:
    """Album tiles for the Library page, without every track row."""

    return library_album_index(
        library_context(),
        allowed_keys=allowed_entry_keys(request),
        hidden=admin_hidden_rules(request),
    )


@router.get('/api/library/artists')
def library_artists(request: Request) -> list[dict[str, Any]]:
    """Artist tiles for the Library page and Discover's library payload."""

    liked: set[str] = set()
    if state.likes is not None:
        liked = {
            str(path or '').replace('\\', '/')
            for path in state.likes.paths(likes_scope(request))
        }
    return library_artist_index(
        library_context(),
        liked,
        allowed_keys=allowed_entry_keys(request),
        hidden=admin_hidden_rules(request),
    )


#: Most items one visibility request may carry.
MAX_VISIBILITY_ITEMS = 2000


def _visibility_store() -> LibraryVisibility:
    store = state.library_visibility
    if store is None:
        raise HTTPException(
            status_code=503, detail='Library visibility is not ready'
        )
    return store


def _hidden_paths(rules: HiddenRules) -> set[str]:
    """Paths of the library rows *rules* hide from users right now."""

    return {
        str(entry.get('file') or '').replace('\\', '/')
        for entry in listing_for_request(library_context())
        if rules.hides(entry)
    }


def _apply_visibility_item(
    store: LibraryVisibility,
    action: str,
    item: dict[str, Any],
    by_path: dict[str, dict[str, Any]],
) -> str:
    """Hide or show one item. Its label when the rules changed, else ``''``."""

    kind = str(item.get('kind') or '')
    hide = action == 'hide'
    if kind == library_visibility.KIND_TRACK:
        file = str(item.get('file') or '').strip().replace('\\', '/')
        entry = by_path.get(file)
        title = (
            str(entry.get('title') or entry.get('name') or file)
            if entry
            else file
        )
        artist = str(entry.get('artist') or '') if entry else ''
        label = f'{artist} - {title}' if artist else title
        if not hide:
            key = (
                entry_content_key(entry)
                if entry
                else str(item.get('key') or '')
            )
            changed = store.show(kind, key) if key else False
            return (
                label if store.show_track_by_path(file) > 0 or changed else ''
            )
        if entry is None:
            raise HTTPException(status_code=404, detail='No such track')
        added = store.hide(
            kind,
            entry_content_key(entry),
            label=label,
            detail=str(entry.get('album') or ''),
            path=file,
        )
        return label if added else ''
    if kind == library_visibility.KIND_ALBUM:
        artist = str(item.get('artist') or '').strip()
        title = str(item.get('title') or '').strip()
        if not title:
            raise HTTPException(status_code=400, detail='Album needs a title')
        key = library_visibility.album_key(artist, title)
        if hide:
            changed = store.hide(kind, key, label=title, detail=artist)
        else:
            changed = store.show(kind, key)
        return title if changed else ''
    if kind == library_visibility.KIND_ARTIST:
        name = str(item.get('name') or '').strip()
        if not name:
            raise HTTPException(status_code=400, detail='Artist needs a name')
        key = library_visibility.artist_key(name)
        if hide:
            changed = store.hide(kind, key, label=name)
        else:
            changed = store.show(kind, key)
        return name if changed else ''
    raise HTTPException(status_code=400, detail='Unknown item kind')


@router.get('/api/library/visibility')
def library_visibility_list() -> dict[str, list[dict[str, Any]]]:
    """What admins hid from users: ``{tracks, albums, artists}``."""

    return _visibility_store().items()


@router.post('/api/library/visibility')
async def library_visibility_update(request: Request) -> dict[str, Any]:
    """Hide songs, albums or artists from users (or show them again).

    Body: ``{"action": "hide"|"show", "items": [...]}`` where an item is
    ``{"kind": "track", "file": <library path>}``, ``{"kind": "album",
    "artist", "title"}`` or ``{"kind": "artist", "name"}``. Admins keep
    seeing everything either way.
    """

    payload = await _json_object(request)
    action = str(payload.get('action') or '')
    items = payload.get('items')
    if action not in {'hide', 'show'} or not isinstance(items, list):
        raise HTTPException(
            status_code=400, detail='Needs an action and a list of items'
        )
    if len(items) > MAX_VISIBILITY_ITEMS:
        raise HTTPException(status_code=413, detail='Too many items')
    store = _visibility_store()
    result = await asyncio.to_thread(_update_visibility, store, action, items)
    labels = result.pop('labels')
    if labels:
        shown = ', '.join(labels[:3]) + (' …' if len(labels) > 3 else '')
        await log_activity(
            request,
            'library_hidden' if action == 'hide' else 'library_shown',
            shown,
            {'count': len(labels)},
        )
    return result


def _update_visibility(
    store: LibraryVisibility, action: str, items: list[Any]
) -> dict[str, Any]:
    entries = listing_for_request(library_context())
    by_path = {
        str(entry.get('file') or '').replace('\\', '/'): entry
        for entry in entries
    }
    before = _hidden_paths(store.rules())
    labels: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        label = _apply_visibility_item(store, action, item, by_path)
        if label:
            labels.append(label)
    changed = len(labels)
    if changed:
        # Users' apps learn from the sync feed: poke every row whose
        # visibility flipped so the next sync drops or restores it.
        after = _hidden_paths(store.rules())
        if state.library_sync is not None:
            for path in before ^ after:
                try:
                    state.library_sync.touch(path)
                except Exception:
                    logger.opt(exception=True).debug(
                        'Could not poke the sync feed for {}', path
                    )
        announce_library_changed()
    return {'changed': changed, 'labels': labels, **store.items()}


@router.post('/api/library/lookup')
async def library_lookup(request: Request) -> list[dict[str, Any]]:
    """Library rows for search/link songs that are already downloaded."""

    payload = await _json_object(request)
    songs = payload.get('songs')
    if not isinstance(songs, list):
        songs = []
    return lookup_library_songs(
        library_context(), songs, allowed_keys=allowed_entry_keys(request)
    )


@router.get('/api/library/loudness')
async def track_loudness(
    request: Request, file: str = Query(..., min_length=1)
) -> dict[str, Any]:
    if not request_user_id(request) and not request_is_admin(request):
        raise HTTPException(status_code=401, detail='Sign in required')
    if not filter_paths_for_request([file], request):
        raise HTTPException(status_code=404, detail='Track not found')
    full = resolve_library_file(file, library_context())
    if full is None:
        raise HTTPException(status_code=404, detail='Track not found')
    runner = state.loudness_analyzer
    if runner is None:
        return {'state': 'unavailable', 'gain_db': 0.0}
    profile = await asyncio.to_thread(runner.info, file, full)
    return profile or {'state': 'unanalysed', 'gain_db': 0.0}


@router.get('/api/library/loudness/status')
async def loudness_status(request: Request) -> dict[str, Any]:
    if not request_is_admin(request):
        raise HTTPException(status_code=403, detail='This needs an admin')
    if state.loudness_analyzer is None:
        raise HTTPException(status_code=503, detail='Starting up')
    return await asyncio.to_thread(state.loudness_analyzer.status)


@router.post('/api/library/loudness/{action}')
async def control_loudness(request: Request, action: str) -> dict[str, Any]:
    if not request_is_admin(request):
        raise HTTPException(status_code=403, detail='This needs an admin')
    runner = state.loudness_analyzer
    if runner is None:
        raise HTTPException(status_code=503, detail='Starting up')
    try:
        if action == 'start':
            entries = await asyncio.to_thread(entries_for_request, request)
            await asyncio.to_thread(
                runner.start, [entry['file'] for entry in entries]
            )
        elif action == 'pause':
            runner.pause()
        elif action == 'resume':
            runner.resume()
        else:
            raise HTTPException(status_code=404, detail='Unknown action')
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await asyncio.to_thread(runner.status)


@router.get('/api/likes')
def get_likes(request: Request) -> dict[str, Any]:
    """The liked files, newest like first, and the playlist's name.

    ``files`` are library paths, the same ones ``GET /tracks`` uses.
    A user sees their own hearts; an admin sees everyone's.
    """

    likes = _require_likes()
    files = likes.paths(likes_scope(request))
    return {
        'files': files,
        'count': len(files),
        'playlist': m3u.sanitize_playlist_name(LIKED_PLAYLIST_NAME),
    }


@router.put('/api/likes')
async def set_like(request: Request) -> dict[str, Any]:
    """Like or unlike one library file: ``{file, liked}``.

    Idempotent — sending the state you want twice changes nothing — so a
    client can retry a tap that may not have arrived. Liking needs a file
    that is in the library; unliking accepts any path, so a heart on a
    file that has since vanished can still be cleared. The heart belongs
    to whoever tapped it.
    """

    payload = await _json_object(request)
    file = str(payload.get('file') or '').strip().replace('\\', '/')
    if not file:
        raise HTTPException(status_code=400, detail='file is required')
    liked = bool(payload.get('liked', True))
    result = await apply_like(file, liked, user_id=request_user_id(request))
    await log_activity(request, 'like' if liked else 'unlike', file)
    return result


async def apply_like(
    file: str, liked: bool, user_id: int = 0
) -> dict[str, Any]:
    """Like or unlike a library path (``PUT /api/likes`` and, by track
    id, ``PUT /api/v1/likes``)."""

    likes = _require_likes()

    if liked:
        full = resolve_library_file(file, library_context())
        if full is None:
            raise HTTPException(status_code=404, detail='File not found')
        meta = await asyncio.to_thread(read_audio_metadata, full)
        changed = await asyncio.to_thread(
            lambda: likes.like(
                file,
                content_key=content_key_for(full),
                title=str(meta.get('title') or full.stem),
                artist=str(meta.get('artist') or ''),
                duration=float(meta.get('duration') or 0.0),
                user_id=user_id,
            )
        )
    else:
        changed = await asyncio.to_thread(likes.unlike, file, user_id)

    if changed:
        await asyncio.to_thread(_sync_liked_playlist)
        _announce_likes()
    scope = None if user_id in _admin_like_scope() else user_id
    return {'file': file, 'liked': liked, 'count': likes.count(scope)}


@router.post('/api/likes/clear')
async def clear_likes_endpoint(request: Request) -> dict[str, Any]:
    """Unlike everything of one's own (everything for an admin), which
    also takes the playlist away.

    Only the hearts and the playlist file go; no song is deleted.
    """

    cleared = await asyncio.to_thread(_clear_likes, likes_scope(request))
    return {'cleared': cleared, 'count': 0}


# ---------------------------------------------------------------------------
# Library storage and download usage (downtify/library_usage.py,
# downtify/storage_scan.py)
# ---------------------------------------------------------------------------

#: How long a walk of the folders is reused, in seconds.
USAGE_SCAN_TTL = 600.0

_usage_scan_lock = threading.Lock()

_usage_scan: dict[str, Any] = {}


def _disk_usage(path: Path) -> Optional[dict[str, int]]:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return {'total': usage.total, 'used': usage.used, 'free': usage.free}


@router.get('/api/library/usage')
async def library_usage(days: int = DEFAULT_DAYS) -> dict[str, Any]:
    """The library's size, growth, download outcomes, duplicates and
    working copies (admins) - see
    :func:`downtify.library_usage.usage_report`."""

    return await asyncio.to_thread(_library_usage, clamp_days(days))


def _library_usage(days: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    ctx = library_context()
    snapshots = state.usage_snapshots
    log = state.download_log
    report = usage_report(
        **_usage_library_inputs(ctx),
        snapshots=snapshots.since(start.date().isoformat())
        if snapshots is not None
        else [],
        downloads=log.since(start) if log is not None else [],
        downloads_since=log.first_at() if log is not None else None,
        disk=_disk_usage(ctx.download_dir),
        now=now,
        days=days,
    )
    if snapshots is not None:
        try:
            snapshots.record(snapshot_of(report), now)
        except Exception:
            logger.opt(exception=True).debug('Could not note the library size')
    return report


@router.get('/api/library/usage/scan')
async def library_usage_scan(refresh: bool = False) -> dict[str, Any]:
    """What Downtify's folders hold besides library songs, and what could
    be cleaned up (admins) - see :func:`downtify.storage_scan.scan_folders`.
    Kept for :data:`USAGE_SCAN_TTL` unless *refresh*."""

    return await asyncio.to_thread(_library_usage_scan, refresh)


def _library_usage_scan(refresh: bool) -> dict[str, Any]:
    with _usage_scan_lock:
        cached = _usage_scan.get('result')
        fresh = time.monotonic() - _usage_scan.get('at', 0.0) < USAGE_SCAN_TTL
        if cached is not None and fresh and not refresh:
            return cached
        ctx = library_context()
        folders, lyrics_folder = plan_folders(
            ctx.download_dir,
            ctx.slskd_dir,
            Path(
                str(
                    state.settings.get('lyrics_lrc_dir')
                    or lyrics.DEFAULT_LYRICS_LRC_DIR
                )
            ),
        )
        stems = {
            Path(stored).with_suffix('').as_posix()
            for stored in list_library_paths(ctx)
        }
        result = {
            **scan_folders(folders, lyrics=lyrics_folder, library_stems=stems),
            'scanned_at': datetime.now(timezone.utc).isoformat(),
        }
        _usage_scan.update(result=result, at=time.monotonic())
        return result
