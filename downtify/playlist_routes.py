"""Playlist routes: ``/api/library/playlist(s)*``, ``/api/playlists/*``
and ``/api/playlist/m3u``.

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
    Any,
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
    m3u,
    spotify,
)
from .api_core import (
    _fetch_playlist_tracks,
    _organize_enabled,
    _playlist_owner_maps,
    _usernames,
    filter_paths_for_request,
    library_context,
    playlist_display_identity,
    playlist_favorite_identity,
    playlists_for_request,
    request_is_admin,
    request_user_id,
    router,
    sharing_enabled,
    spawn_task,
    state,
    stored_content_key,
)
from .api_pipeline import (
    _catalog_filenames_for_playlist,
    _clear_likes,
    _download_playlist_cover_for_batch,
    _json_object,
    _known_spotify_playlist_sources,
    _playlist_subdir_for_name,
    _rebuild_playlist_catalog_from_library,
    _schedule_playlist_refresh_after_delete,
    _submit_playlist_batch,
    announce_library_changed,
    announce_playlists_changed,
    hidden_songs_for,
    likes_scope,
)
from .external_playlists import (
    discover_external_playlists,
)
from .file_providers import (
    providers_for,
)
from .library_catalog import (
    entry_content_key,
    listing_for_request,
    resolve_library_file,
)
from .library_delete import (
    delete_library_files,
    delete_playlist_from_library,
    remove_playlist_shell,
)
from .library_paths_cache import (
    invalidate_library_paths_cache,
    peek_cached_path_pairs,
)
from .library_reconcile import (
    playlist_refresh_enabled,
    refresh_playlists_after_moves,
)
from .likes import (
    is_liked_playlist,
)
from .manual_playlists import (
    ManualPlaylistError,
    copy_playlist,
    create_manual_playlist,
    detach_imported_playlist,
    edit_manual_playlist,
    existing_playlist_names,
    remove_manual_playlist_cover,
    rename_manual_playlist,
    reorder_imported_playlist,
    reorder_manual_playlist,
    save_manual_playlist_cover,
)
from .monitor import (
    KIND_PLAYLIST,
    download_playlist_cover,
    fetch_playlist,
    parse_playlist_url,
)
from .navidrome import (
    NavidromeClient,
    _effective_navidrome_settings,
    enrich_song_from_library_file,
    sync_playlist_to_navidrome,
)
from .playlist_batches import (
    LibrarySnapshot,
    active_queue_count_for_playlist,
    split_tracks_by_library,
)
from .playlist_diagnostics import (
    PlaylistDiagnosticsContext,
    build_playlist_diagnostics,
)
from .playlist_hidden import (
    HiddenSongsError,
    PlaylistHiddenSongs,
    catalog_names_for,
    hide_playlist_songs,
    show_playlist_songs,
    source_track_ids,
)
from .playlist_mosaic import (
    MAX_PLAYLIST_COVER_BYTES,
    keep_explicit_cover,
)
from .playlist_pending import (
    MAX_PENDING_PER_EDIT,
    PlaylistPendingSongs,
)
from .playlist_shares import (
    PRIVATE,
    SHARED,
    VISIBILITIES,
    share_key,
)


def playlist_entry_for_request(
    name: str, request: Optional[Request]
) -> Optional[dict[str, Any]]:
    """The listing entry for *name* when *request* may open it.

    Falls back to the playlist catalog when the M3U is gone (a delete
    still has tracks to take): admins see every catalog entry, anyone
    else only entries they own.
    """

    wanted = str(name or '').strip()
    if not wanted:
        return None
    for playlist in playlists_for_request(request):
        if str(playlist.get('name') or '') == wanted:
            return playlist
    catalog = state.playlist_catalog
    if catalog is None:
        return None
    try:
        rows = catalog.list_tracks(wanted)
    except Exception:
        return None
    if not rows:
        return None
    if not request_is_admin(request):
        user_id = request_user_id(request)
        try:
            owner = catalog.playlist_owner_map().get(wanted)
        except Exception:
            logger.opt(exception=True).debug(
                'Could not read owner for playlist {!r}', wanted
            )
            owner = None
        if not user_id or int(owner or 0) != user_id:
            return None
    return {
        'name': wanted,
        'files': [str(row.get('filename') or '') for row in rows],
        'count': len(rows),
        'added': 0,
        'cover': '',
        'liked': False,
        'manual': False,
    }


def require_playlist_visible(
    name: str, request: Optional[Request], *, manage: bool = False
) -> dict[str, Any]:
    """The playlist's entry; 404 unless *request* may open it (as if
    unknown). With *manage*, 403 unless it is also theirs to change - a
    playlist shared with them is view-only."""

    entry = playlist_entry_for_request(name, request)
    if entry is None:
        raise HTTPException(status_code=404, detail='Playlist not found')
    if manage and not entry.get('mine', True):
        raise HTTPException(
            status_code=403,
            detail='Only the owner can change this playlist',
        )
    return entry


def claim_manual_playlist(name: str, request: Optional[Request]) -> None:
    """Record a Library-created playlist's owner (best effort)."""

    user_id = request_user_id(request)
    if not user_id or state.manual_playlist_owners is None:
        return
    try:
        state.manual_playlist_owners.set_owner(name, user_id)
        if state.playlist_shares is not None:
            # A new playlist never inherits what an older one by that name
            # was shared with.
            state.playlist_shares.forget(name)
    except Exception:
        logger.opt(exception=True).debug(
            'Could not record owner for playlist {!r}', name
        )


def ownership_action(
    stored_path: str, request: Optional[Request]
) -> tuple[str, str]:
    """How a delete treats one file: ``(action, content_key)``.

    ``delete`` takes it off disk (an admin, or the last owner -
    today's behavior when nobody else has it). ``release`` drops
    one's own ownership row while the file stays for the rest.
    ``missing`` isn't on disk; ``foreign`` isn't theirs.
    """

    key = stored_content_key(stored_path)
    if not key:
        return 'missing', ''
    if state.track_owners is None:
        return 'delete', key
    if request_is_admin(request):
        return 'delete', key
    user_id = request_user_id(request)
    try:
        owners = state.track_owners.owners(key)
    except Exception:
        logger.opt(exception=True).debug(
            'Could not read owners for {}', stored_path
        )
        owners = []
    if user_id and user_id in owners:
        return ('delete' if len(owners) == 1 else 'release'), key
    return 'foreign', key


def release_file_ownership(
    stored_path: str, content_key: str, user_id: int
) -> dict[str, Any]:
    """Drop one owner's row after their delete; the file stays put."""

    if state.track_owners is not None and content_key and user_id:
        try:
            state.track_owners.remove(content_key, user_id)
        except Exception:
            logger.opt(exception=True).warning(
                'Could not release {} for user {}', stored_path, user_id
            )
    if state.library_sync is not None:
        try:
            name = str(stored_path or '').strip().replace('\\', '/')
            state.library_sync.touch(name)
        except Exception:
            logger.opt(exception=True).debug(
                'Could not poke the sync feed for {}', stored_path
            )
    announce_library_changed()
    return {'released': True}


def drop_file_owners(content_key: str) -> None:
    """Forget every owner and any hidden-song rule (the file was just
    deleted from disk)."""

    if not content_key:
        return
    if state.track_owners is not None:
        try:
            state.track_owners.drop_file(content_key)
        except Exception:
            logger.opt(exception=True).warning(
                'Could not drop owners for a deleted file'
            )
    if state.library_visibility is not None:
        try:
            state.library_visibility.drop_track(content_key)
        except Exception:
            logger.opt(exception=True).debug(
                'Could not drop a hidden item for a deleted file'
            )
    if state.file_providers is not None:
        try:
            state.file_providers.drop(content_key)
        except Exception:
            logger.opt(exception=True).debug(
                'Could not drop the provider of a deleted file'
            )
    if state.song_links is not None:
        try:
            state.song_links.drop(content_key)
        except Exception:
            logger.opt(exception=True).debug(
                'Could not drop the song links of a deleted file'
            )


def _song_row_hint(song: dict[str, Any]) -> dict[str, Any]:
    return {
        'song_id': song.get('song_id'),
        'name': song.get('name') or '',
        'artists': list(song.get('artists') or []),
        'album_name': song.get('album_name') or '',
        'cover_url': song.get('cover_url') or '',
        'url': song.get('url') or '',
        'duration': song.get('duration') or 0,
    }


def _batch_scope(request: Optional[Request]) -> Optional[int]:
    """Whose batches *request* sees: ``None`` (everyone's) for an admin."""

    return None if request_is_admin(request) else request_user_id(request)


def _resolve_playlist_batch_status(
    *,
    missing_count: int,
    active_count: int,
    expected_count: int,
    batch: Optional[dict[str, Any]] = None,
) -> str:
    """Derive batch status from live counts (not stale DB status alone)."""

    if active_count > 0:
        return 'in_progress'
    if missing_count == 0 and expected_count > 0:
        if batch is not None and state.playlist_batch_store is not None:
            if batch.get('status') != 'complete':
                state.playlist_batch_store.mark_complete(batch['id'])
        return 'complete'
    if missing_count > 0:
        return 'incomplete'
    if batch is not None and batch.get('status') == 'complete':
        return 'complete'
    if batch is not None:
        return str(batch.get('status') or 'incomplete')
    return 'complete'


def _playlist_batch_summary(
    spotify_id: str,
    playlist_name: str,
    playlist_url: str,
    *,
    batch: Optional[dict[str, Any]] = None,
    expected_hint: int = 0,
    snapshot: Optional[LibrarySnapshot] = None,
) -> dict[str, Any]:
    """Counts from cached Spotify track list + library scan.

    *snapshot* (see :func:`_library_snapshot`) matches the tracks in
    memory instead of on disk.
    """

    active_count = active_queue_count_for_playlist(
        spotify_id, state.download_jobs
    )

    if state.playlist_catalog is not None:
        for row in state.playlist_catalog.list_playlists_with_spotify_id():
            if row['spotify_id'] != spotify_id:
                continue
            if not playlist_name or playlist_name == spotify_id:
                playlist_name = str(row['name'])
            break

    cached_name: Optional[str] = None
    cached_tracks: Optional[list[dict[str, Any]]] = None
    if state.playlist_spotify_cache is not None:
        hit = state.playlist_spotify_cache.get(spotify_id)
        if hit is not None:
            cached_name, cached_tracks = hit

    if cached_tracks is not None:
        if cached_name:
            playlist_name = cached_name
        cached_tracks = _without_hidden_songs(playlist_name, cached_tracks)
        expected_count = len(cached_tracks)
        downloaded_count = 0
        missing_count = expected_count
        if (
            cached_tracks
            and state.downloader is not None
            and state.track_index is not None
        ):
            subdir = _playlist_subdir_for_name(playlist_name)
            catalog_filenames = _catalog_filenames_for_playlist(
                playlist_name,
                spotify_id,
            )
            downloaded_count, missing_tracks = split_tracks_by_library(
                cached_tracks,
                downloader=state.downloader,
                track_index=state.track_index,
                subdir=subdir,
                catalog_filenames=catalog_filenames,
                snapshot=snapshot,
            )
            missing_count = len(missing_tracks)
        status = _resolve_playlist_batch_status(
            missing_count=missing_count,
            active_count=active_count,
            expected_count=expected_count,
            batch=batch,
        )
        if status == 'complete':
            missing_count = 0
        return {
            'batch_id': batch['id'] if batch else None,
            'spotify_playlist_id': spotify_id,
            'playlist_name': playlist_name,
            'playlist_url': playlist_url,
            'expected_count': expected_count,
            'downloaded_count': downloaded_count,
            'missing_count': missing_count,
            'missing_tracks': [],
            'active_in_queue': active_count,
            'status': status,
            'source': 'cache',
            'started_at': batch.get('started_at') if batch else None,
            'finished_at': batch.get('finished_at') if batch else None,
        }

    downloaded_count = 0
    if state.playlist_catalog is not None:
        for row in state.playlist_catalog.list_playlists_with_spotify_id():
            if row['spotify_id'] != spotify_id:
                continue
            downloaded_count = int(row.get('track_count') or 0)
            break
        if not downloaded_count and playlist_name:
            downloaded_count = len(
                state.playlist_catalog.list_tracks(playlist_name)
            )

    expected_count = max(int(expected_hint or 0), 0)
    if batch is not None:
        expected_count = max(
            expected_count, int(batch.get('expected_count') or 0)
        )

    status = 'in_progress' if active_count > 0 else 'pending'
    return {
        'batch_id': batch['id'] if batch else None,
        'spotify_playlist_id': spotify_id,
        'playlist_name': playlist_name,
        'playlist_url': playlist_url,
        'expected_count': expected_count,
        'downloaded_count': downloaded_count,
        'missing_count': 0,
        'missing_tracks': [],
        'active_in_queue': active_count,
        'status': status,
        'source': 'pending',
        'started_at': batch.get('started_at') if batch else None,
        'finished_at': batch.get('finished_at') if batch else None,
    }


def _without_hidden_songs(
    playlist_name: str, tracks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """*tracks* (a playlist's source rows) minus the songs its owner hid
    from it: they neither count as expected nor as missing."""

    hidden = hidden_songs_for(playlist_name)
    if not hidden:
        return tracks
    return [track for track in tracks if not hidden.hides_song(track)]


def _playlist_completeness_report(
    spotify_id: str,
    playlist_name: str,
    playlist_url: str,
    *,
    batch: Optional[dict[str, Any]] = None,
    expected_hint: int = 0,
    include_missing_tracks: bool = True,
    refresh: bool = False,
    user_id: Optional[int] = None,
) -> dict[str, Any]:
    tracks: list[dict[str, Any]] = []
    try:
        fetched_name, tracks = _fetch_playlist_tracks(
            spotify_id, refresh=refresh
        )
        if fetched_name:
            playlist_name = fetched_name
    except Exception:
        logger.opt(exception=True).debug(
            'playlist batch: Spotify fetch failed for {}',
            spotify_id,
        )
    tracks = _without_hidden_songs(playlist_name, tracks)

    subdir = _playlist_subdir_for_name(playlist_name)
    catalog_filenames = _catalog_filenames_for_playlist(
        playlist_name,
        spotify_id,
    )
    owned: Optional[set[str]] = None
    if user_id is not None and state.track_owners is not None:
        owned = state.track_owners.owned_keys(user_id)
    downloaded_count, missing_tracks = split_tracks_by_library(
        tracks,
        downloader=state.downloader,
        track_index=state.track_index,
        subdir=subdir,
        catalog_filenames=catalog_filenames,
        owned_keys=owned,
    )
    expected_count = len(tracks) or int(expected_hint or 0)
    if batch is not None and not expected_count:
        expected_count = int(batch.get('expected_count') or 0)
    missing_count = len(missing_tracks)
    if not tracks and expected_count > downloaded_count:
        missing_count = expected_count - downloaded_count

    active_count = active_queue_count_for_playlist(
        spotify_id, state.download_jobs, user_id
    )

    status = _resolve_playlist_batch_status(
        missing_count=missing_count,
        active_count=active_count,
        expected_count=expected_count,
        batch=batch,
    )

    track_hints = (
        [_song_row_hint(t) for t in missing_tracks]
        if include_missing_tracks
        else []
    )

    return {
        'batch_id': batch['id'] if batch else None,
        'spotify_playlist_id': spotify_id,
        'playlist_name': playlist_name,
        'playlist_url': playlist_url,
        'expected_count': expected_count,
        'downloaded_count': downloaded_count,
        'missing_count': missing_count,
        'missing_tracks': track_hints,
        'active_in_queue': active_count,
        'status': status,
        'source': 'spotify',
        'started_at': batch.get('started_at') if batch else None,
        'finished_at': batch.get('finished_at') if batch else None,
    }


def _report_for_spotify_playlist(
    spotify_playlist_id: str,
    *,
    mode: str = 'estimate',
    include_missing_tracks: bool = True,
    refresh: bool = False,
    user_id: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    sid = str(spotify_playlist_id or '').strip()
    if not sid:
        return None
    meta = _known_spotify_playlist_sources(user_id).get(sid)
    if meta is None:
        return None
    batch = meta.get('batch')
    name = str(meta.get('playlist_name') or sid)
    url = str(
        meta.get('playlist_url') or f'https://open.spotify.com/playlist/{sid}'
    )
    hint = int(meta.get('expected_hint') or 0)
    if mode == 'spotify':
        return _playlist_completeness_report(
            sid,
            name,
            url,
            batch=batch if isinstance(batch, dict) else None,
            expected_hint=hint,
            include_missing_tracks=include_missing_tracks,
            refresh=refresh,
            user_id=user_id,
        )
    report = _playlist_batch_summary(
        sid,
        name,
        url,
        batch=batch if isinstance(batch, dict) else None,
        expected_hint=hint,
    )
    return report


def _library_snapshot() -> Optional[LibrarySnapshot]:
    """The track index and the listing's paths, read once, so a batch
    summary checks thousands of tracks without touching the disk.
    ``None`` until the listing snapshot exists (the summary then checks
    on disk, as before)."""

    if state.track_index is None:
        return None
    pairs = peek_cached_path_pairs(library_context())
    if pairs is None:
        return None
    try:
        track_files = state.track_index.filenames_by_spotify_id()
    except Exception:
        logger.opt(exception=True).debug('Could not read the track index')
        return None
    return LibrarySnapshot.build(track_files, [s for s, _r in pairs])


def _build_playlist_batch_reports(
    *,
    include_tracks: bool = False,
    user_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    if state.downloader is None or state.track_index is None:
        return []

    builder = (
        _playlist_completeness_report
        if include_tracks
        else _playlist_batch_summary
    )
    kwargs: dict[str, Any] = (
        {'user_id': user_id}
        if builder is _playlist_completeness_report
        else {'snapshot': _library_snapshot()}
    )
    reports: list[dict[str, Any]] = []
    for sid, meta in _known_spotify_playlist_sources(user_id).items():
        batch = meta.get('batch')
        reports.append(
            builder(
                sid,
                str(meta.get('playlist_name') or sid),
                str(
                    meta.get('playlist_url')
                    or f'https://open.spotify.com/playlist/{sid}'
                ),
                batch=batch if isinstance(batch, dict) else None,
                expected_hint=int(meta.get('expected_hint') or 0),
                **kwargs,
            )
        )
    reports.sort(
        key=lambda row: (
            row.get('status') != 'complete',
            row.get('playlist_name') or '',
        )
    )
    return reports


def _build_incomplete_playlist_reports(
    *,
    include_tracks: bool = False,
    user_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Playlists that still need work (missing tracks or active queue jobs)."""

    return [
        row
        for row in _build_playlist_batch_reports(
            include_tracks=include_tracks, user_id=user_id
        )
        if row['status'] != 'complete'
    ]


def _missing_tracks_for_playlist(
    spotify_playlist_id: str,
    *,
    user_id: Optional[int] = None,
) -> tuple[str, str, list[dict[str, Any]]]:
    if state.downloader is None or state.track_index is None:
        raise HTTPException(status_code=500, detail='Downloader not ready')

    sid = str(spotify_playlist_id or '').strip()
    if not sid:
        raise HTTPException(
            status_code=400, detail='spotify_playlist_id required'
        )

    try:
        playlist_name, tracks = _fetch_playlist_tracks(sid)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail='Failed to fetch playlist from Spotify'
        ) from exc
    # A song hidden from the playlist is never "missing" from it.
    tracks = _without_hidden_songs(playlist_name, tracks)

    subdir = _playlist_subdir_for_name(playlist_name)
    catalog_filenames = _catalog_filenames_for_playlist(
        playlist_name,
        sid,
    )
    owned: Optional[set[str]] = None
    if user_id is not None and state.track_owners is not None:
        owned = state.track_owners.owned_keys(user_id)
    _downloaded, missing = split_tracks_by_library(
        tracks,
        downloader=state.downloader,
        track_index=state.track_index,
        subdir=subdir,
        catalog_filenames=catalog_filenames,
        owned_keys=owned,
    )
    playlist_url = f'https://open.spotify.com/playlist/{sid}'
    return playlist_name, playlist_url, missing


@router.post('/api/library/playlists')
async def create_library_playlist_endpoint(request: Request) -> dict[str, Any]:
    """Create an empty playlist the user can edit in the Library."""

    payload = await _json_object(request)
    name = str(payload.get('name') or '').strip()
    ctx = library_context()
    try:
        result = await asyncio.to_thread(create_manual_playlist, ctx, name)
    except ManualPlaylistError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail=str(exc)
        ) from exc
    claim_manual_playlist(str(result.get('name') or name), request)
    invalidate_library_paths_cache()
    return result


@router.put('/api/library/playlists/cover')
async def upload_library_playlist_cover_endpoint(
    request: Request, name: str = Query(...)
) -> dict[str, Any]:
    """Set a manual playlist's own cover (owner or admin only)."""

    entry = require_playlist_visible(name, request, manage=True)
    if not entry.get('manual'):
        raise HTTPException(
            status_code=403,
            detail='Only a Library playlist can change its cover',
        )
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_PLAYLIST_COVER_BYTES:
            raise HTTPException(
                status_code=413, detail='Cover image is too large'
            )
    content_type = request.headers.get('content-type', '').split(';', 1)[0]
    try:
        await asyncio.to_thread(
            save_manual_playlist_cover,
            library_context(),
            str(entry.get('name') or name),
            bytes(data),
            content_type.lower(),
        )
    except ManualPlaylistError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    await announce_playlists_changed()
    return {'ok': True}


@router.delete('/api/library/playlists/cover')
async def remove_library_playlist_cover_endpoint(
    request: Request, name: str = Query(...)
) -> dict[str, Any]:
    """Remove a manual playlist's own cover (owner or admin only)."""

    entry = require_playlist_visible(name, request, manage=True)
    if not entry.get('manual'):
        raise HTTPException(
            status_code=403,
            detail='Only a Library playlist can change its cover',
        )
    try:
        await asyncio.to_thread(
            remove_manual_playlist_cover,
            library_context(),
            str(entry.get('name') or name),
        )
    except ManualPlaylistError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail=str(exc)
        ) from exc
    await announce_playlists_changed()
    return {'ok': True}


@router.get('/api/library/playlists/external')
async def external_playlist_candidates(request: Request) -> dict[str, Any]:
    user_id = request_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail='Sign in required')
    store = state.external_playlist_imports
    if store is None:
        raise HTTPException(status_code=503, detail='Starting up')
    candidates, warnings, truncated = await asyncio.to_thread(
        discover_external_playlists, library_context()
    )
    imported = await asyncio.to_thread(store.imported, user_id)
    rows = []
    for candidate in candidates:
        files = filter_paths_for_request(list(candidate.files), request)
        if not files and candidate.files and not request_is_admin(request):
            continue
        rows.append({
            'source_id': candidate.source_id,
            'revision': candidate.revision,
            'name': candidate.name,
            'folder': candidate.folder,
            'files': files,
            'count': len(files),
            'missing': candidate.missing + len(candidate.files) - len(files),
            'duplicates': candidate.duplicates,
            'imported_name': imported.get(candidate.source_id, ''),
        })
    return {'playlists': rows, 'warnings': warnings, 'truncated': truncated}


@router.post('/api/library/playlists/external')
async def import_external_playlists_endpoint(
    request: Request,
) -> dict[str, Any]:
    user_id = request_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail='Sign in required')
    payload = await _json_object(request)
    selected = payload.get('selected')
    if (
        not isinstance(selected, list)
        or not 1 <= len(selected) <= 50
        or not all(isinstance(item, dict) for item in selected)
    ):
        raise HTTPException(
            status_code=400, detail='Choose between 1 and 50 playlists'
        )
    store = state.external_playlist_imports
    if store is None:
        raise HTTPException(status_code=503, detail='Starting up')
    ctx = library_context()
    candidates, _, _ = await asyncio.to_thread(
        discover_external_playlists, ctx
    )
    by_id = {item.source_id: item for item in candidates}
    results = []
    for wanted in selected:
        candidate = by_id.get(str(wanted.get('source_id') or ''))
        if candidate is None or wanted.get('revision') != candidate.revision:
            results.append({
                'source_id': wanted.get('source_id'),
                'status': 'changed',
                'detail': 'Refresh the preview before importing',
            })
            continue
        files = filter_paths_for_request(list(candidate.files), request)
        if not files:
            results.append({
                'source_id': candidate.source_id,
                'status': 'unavailable',
                'detail': 'No accessible tracks found',
            })
            continue
        try:
            result = await asyncio.to_thread(
                store.import_snapshot, ctx, user_id, candidate, files
            )
            results.append(result)
        except (ManualPlaylistError, OSError):
            results.append({
                'source_id': candidate.source_id,
                'status': 'error',
                'detail': 'Playlist could not be imported',
            })
    invalidate_library_paths_cache()
    await announce_playlists_changed()
    return {'results': results}


@router.post('/api/library/playlists/tracks')
async def edit_library_playlist_tracks_endpoint(
    request: Request,
) -> dict[str, Any]:
    """Add or remove library files on a manual playlist: its owner's (or
    an admin's) to change, and its editors' - songs only: the source
    artwork (``source_playlist_url``) stays with the owner."""

    payload = await _json_object(request)
    name = str(payload.get('name') or '').strip()
    entry = require_playlist_visible(name, request)
    mine = bool(entry.get('mine', True))
    source_url = str(payload.get('source_playlist_url') or '').strip()
    if not mine and (not entry.get('can_edit_tracks') or source_url):
        raise HTTPException(
            status_code=403,
            detail='Only the owner can change this playlist',
        )
    cover_target = parse_playlist_url(source_url) if source_url else None
    if source_url and cover_target is None:
        raise HTTPException(
            status_code=400, detail='Invalid playlist source URL'
        )
    add = payload.get('add') if isinstance(payload.get('add'), list) else []
    remove = (
        payload.get('remove')
        if isinstance(payload.get('remove'), list)
        else []
    )
    remove_entries = _playlist_entry_refs(payload.get('remove_entries'))
    ctx = library_context()
    # Only songs they can see: one an admin hid is as good as missing.
    added = [path for path in (str(item).strip() for item in add) if path]
    if added:
        allowed = set(
            await asyncio.to_thread(filter_paths_for_request, added, request)
        )
        for path in added:
            if path not in allowed:
                raise HTTPException(
                    status_code=400, detail=f'Track not in the library: {path}'
                )
    try:
        result = await asyncio.to_thread(
            edit_manual_playlist,
            ctx,
            name,
            add=[str(item) for item in add],
            remove=[str(item) for item in remove],
            remove_entries=remove_entries,
            allow_duplicates=payload.get('allow_duplicates') is True,
        )
    except ManualPlaylistError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail=str(exc)
        ) from exc
    if cover_target is not None:
        path = m3u.find_m3u_for_name(ctx.download_dir, name)
        if path is not None:
            saved = await asyncio.to_thread(
                _download_playlist_cover_for_batch,
                *cover_target,
                path,
                state.settings,
            )
            if saved:
                await asyncio.to_thread(keep_explicit_cover, path)
    invalidate_library_paths_cache()
    await announce_playlist_edited(entry, request)
    return result


def _pending_store() -> PlaylistPendingSongs:
    if state.playlist_pending is None:
        raise HTTPException(status_code=503, detail='Starting up')
    return state.playlist_pending


def _require_manual_editable(name: str, request: Request) -> dict[str, Any]:
    """A Library-created playlist *request* may add songs to: its own,
    or one shared with it as an editor."""

    entry = require_playlist_visible(name, request)
    if not entry.get('manual'):
        raise HTTPException(
            status_code=400,
            detail='Only Library playlists can hold songs to download',
        )
    if not entry.get('mine', True) and not entry.get('can_edit_tracks'):
        raise HTTPException(
            status_code=403,
            detail='Only the owner can change this playlist',
        )
    return entry


@router.get('/api/library/playlists/pending')
async def list_playlist_pending_endpoint(
    request: Request, name: str = ''
) -> dict[str, Any]:
    """The songs a Library playlist waits on: added from a search, the
    charts or a recommendation before they were downloaded."""

    entry = require_playlist_visible(name.strip(), request)
    if not entry.get('manual'):
        return {'name': entry.get('name') or name, 'songs': []}
    songs = await asyncio.to_thread(
        _pending_store().songs, str(entry.get('name') or name)
    )
    return {'name': entry.get('name') or name, 'songs': songs}


@router.post('/api/library/playlists/pending')
async def add_playlist_pending_endpoint(request: Request) -> dict[str, Any]:
    """Add songs that aren't downloaded yet to a Library playlist. Body:
    ``{name, songs: [song]}``. Each is written into the playlist once its
    download ends; the caller queues the downloads itself."""

    payload = await _json_object(request)
    name = str(payload.get('name') or '').strip()
    entry = _require_manual_editable(name, request)
    songs = payload.get('songs')
    if not isinstance(songs, list) or not songs:
        raise HTTPException(
            status_code=400, detail='songs must be a non-empty list'
        )
    if len(songs) > MAX_PENDING_PER_EDIT:
        raise HTTPException(
            status_code=400,
            detail=f'At most {MAX_PENDING_PER_EDIT} songs at a time',
        )
    added = await asyncio.to_thread(
        _pending_store().add,
        str(entry.get('name') or name),
        [song for song in songs if isinstance(song, dict)],
        user_id=request_user_id(request),
    )
    if entry.get('visibility', PRIVATE) != PRIVATE:
        await announce_playlists_changed()
    return {'name': entry.get('name') or name, 'added': added}


@router.delete('/api/library/playlists/pending')
async def remove_playlist_pending_endpoint(
    request: Request,
) -> dict[str, Any]:
    """Take waiting songs back out of a Library playlist. Body:
    ``{name, song_ids: [...]}``. Their downloads, if queued, carry on."""

    payload = await _json_object(request)
    name = str(payload.get('name') or '').strip()
    entry = _require_manual_editable(name, request)
    raw = payload.get('song_ids')
    ids = [str(item) for item in raw] if isinstance(raw, list) else []
    removed = await asyncio.to_thread(
        _pending_store().remove, str(entry.get('name') or name), ids
    )
    if entry.get('visibility', PRIVATE) != PRIVATE:
        await announce_playlists_changed()
    return {'name': entry.get('name') or name, 'removed': removed}


def _playlist_entry_refs(raw: object) -> list[tuple[str, int]]:
    """``[{file, occurrence}]`` from a request as ``(file, occurrence)``:
    one copy of a song a playlist may hold more than once."""

    if not isinstance(raw, list):
        return []
    refs: list[tuple[str, int]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        file = str(item.get('file') or '').strip()
        occurrence = item.get('occurrence', 0)
        if file and isinstance(occurrence, int) and occurrence >= 0:
            refs.append((file, occurrence))
    return refs


@router.put('/api/library/playlists/order')
async def reorder_library_playlist_endpoint(
    request: Request,
) -> dict[str, Any]:
    """Put a playlist's songs in a new order: ``{name, files}``, every
    song the caller sees (repeats included) in its new place.

    A Library playlist: its owner (or an admin) and its editors. An
    imported one (a link or a Playlist Monitor watch): its owner or an
    admin - the order is kept, and syncs from its source keep it too,
    new songs going at the end (see ``downtify/playlist_custom_order.py``).
    Liked songs can't be reordered (``403``). ``409`` when the playlist
    changed since the caller loaded it."""

    payload = await _json_object(request)
    name = str(payload.get('name') or '').strip()
    entry = require_playlist_visible(name, request)
    manual = bool(entry.get('manual'))
    allowed = (
        entry.get('mine', True) or entry.get('can_edit_tracks')
        if manual
        else entry.get('mine', True) and not entry.get('liked')
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail='Only the owner can change this playlist',
        )
    files = payload.get('files')
    if not isinstance(files, list):
        raise HTTPException(status_code=400, detail='Send the new order')
    order = [str(item) for item in files]
    # What the caller was shown: songs hidden from them keep their places.
    visible = set(entry.get('files') or [])
    try:
        if manual:
            result = await asyncio.to_thread(
                reorder_manual_playlist,
                library_context(),
                name,
                order,
                visible=visible,
            )
        else:
            result = await asyncio.to_thread(
                reorder_imported_playlist,
                library_context(),
                name,
                order,
                visible=visible,
            )
            if state.playlist_custom_order is not None:
                await asyncio.to_thread(
                    state.playlist_custom_order.set,
                    str(result['name']),
                    result['files'],
                )
    except ManualPlaylistError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail=str(exc)
        ) from exc
    invalidate_library_paths_cache()
    await announce_playlist_edited(entry, request)
    return result


@router.post('/api/library/playlists/rename')
async def rename_library_playlist_endpoint(request: Request) -> dict[str, Any]:
    """Rename a playlist the user created in the Library."""

    payload = await _json_object(request)
    name = str(payload.get('name') or '').strip()
    new_name = str(payload.get('new_name') or '').strip()
    entry = require_playlist_visible(name, request, manage=True)
    if not entry.get('manual'):
        if entry.get('liked'):
            raise HTTPException(
                status_code=403, detail='Liked songs cannot be renamed'
            )
        reset = payload.get('reset_display_name') is True
        if not reset and (not new_name or len(new_name) > 120):
            raise HTTPException(
                status_code=400,
                detail='Enter a name of at most 120 characters',
            )
        if not reset and is_liked_playlist(new_name):
            raise HTTPException(
                status_code=409, detail='That playlist name is reserved'
            )
        for other in playlists_for_request(request):
            if other['name'] != entry['name'] and share_key(
                other.get('display_name', other['name'])
            ) == share_key(new_name):
                raise HTTPException(
                    status_code=409,
                    detail='A playlist with that name already exists',
                )
        if state.playlist_shares is None:
            raise HTTPException(status_code=503, detail='Starting up')
        await asyncio.to_thread(
            state.playlist_shares.set_display_name,
            playlist_display_identity(entry),
            '' if reset else new_name,
        )
        await announce_playlists_changed()
        return {**entry, 'display_name': entry['name'] if reset else new_name}
    ctx = library_context()
    try:
        result = await asyncio.to_thread(
            rename_manual_playlist, ctx, name, new_name
        )
    except ManualPlaylistError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail=str(exc)
        ) from exc
    if state.manual_playlist_owners is not None:
        try:
            await asyncio.to_thread(
                state.manual_playlist_owners.rename_owner,
                name,
                str(result.get('name') or new_name),
            )
        except Exception:
            logger.opt(exception=True).debug(
                'Could not move owner for playlist {!r}', name
            )
    if state.external_playlist_imports is not None:
        await asyncio.to_thread(
            state.external_playlist_imports.rename,
            name,
            str(result.get('name') or new_name),
        )
    if state.playlist_pending is not None:
        await asyncio.to_thread(
            state.playlist_pending.rename,
            name,
            str(result.get('name') or new_name),
        )
    if state.playlist_shares is not None:
        try:
            await asyncio.to_thread(
                state.playlist_shares.rename,
                name,
                str(result.get('name') or new_name),
            )
        except Exception:
            logger.opt(exception=True).debug(
                'Could not move sharing for playlist {!r}', name
            )
    invalidate_library_paths_cache()
    await announce_playlists_changed()
    return result


async def announce_playlist_edited(
    entry: dict[str, Any], request: Request
) -> None:
    """A playlist's songs were added, removed or put in another order.

    A shared one is announced to everyone (its editors and followers
    have it open); a private one to its owner's and the editor's own
    pages and apps only - the same account on another device sees the
    change at once instead of at the next library refresh.
    """

    if entry.get('visibility', PRIVATE) != PRIVATE:
        await announce_playlists_changed()
        return
    message = {'type': 'playlists_changed'}
    for user_id in sorted({
        int(entry.get('owner_id') or 0),
        request_user_id(request),
    }):
        if user_id:
            await state.connections.send_user(user_id, message)


@router.put('/api/library/playlists/favorite')
async def set_playlist_favorite_endpoint(request: Request) -> dict[str, Any]:
    """Pin an accessible playlist for the signed-in account only."""
    user_id = request_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail='Sign in required')
    payload = await _json_object(request)
    name = str(payload.get('name') or '').strip()
    favorite = payload.get('favorite')
    if not isinstance(favorite, bool):
        raise HTTPException(
            status_code=400, detail='favorite must be a boolean'
        )
    if state.playlist_shares is None:
        raise HTTPException(status_code=503, detail='Starting up')
    if favorite:
        entry = require_playlist_visible(name, request)
        name = str(entry['name'])
    elif not name:
        raise HTTPException(status_code=400, detail='name is required')
    await asyncio.to_thread(
        state.playlist_shares.set_favorite,
        user_id,
        playlist_favorite_identity({'name': name}),
        favorite,
    )
    await announce_playlists_changed()
    return {'name': name, 'favorite': favorite}


def _owner_of(entry: dict[str, Any]) -> int:
    """The user id that owns the playlist *entry* (``0``: nobody)."""

    if entry.get('owner_id') is not None:
        return int(entry['owner_id'] or 0)
    catalog_names, manual_owners = _playlist_owner_maps()
    owners = manual_owners if entry.get('manual') else catalog_names
    return int(owners.get(share_key(str(entry.get('name') or '')), 0))


@router.put('/api/library/playlists/visibility')
async def set_playlist_visibility_endpoint(
    request: Request,
) -> dict[str, Any]:
    """Share a playlist you own: ``{name, visibility, shared_with,
    editors?}`` with ``visibility`` ``private`` (the default), ``shared``
    (with the usernames in ``shared_with``) or ``public`` (everyone on
    the server). Viewers only play it; ``editors`` - some of
    ``shared_with``, on a Library playlist - may also add and remove its
    songs (left out: the current editors still on the list stay).
    Liked songs are never shareable."""

    payload = await _json_object(request)
    name = str(payload.get('name') or '').strip()
    visibility = str(payload.get('visibility') or '').strip().lower()
    if visibility not in VISIBILITIES:
        raise HTTPException(status_code=400, detail='Unknown visibility')
    if is_liked_playlist(name):
        raise HTTPException(
            status_code=400, detail='Liked songs cannot be shared'
        )
    entry = require_playlist_visible(name, request, manage=True)
    shares = state.playlist_shares
    if shares is None:
        raise HTTPException(status_code=503, detail='Starting up')
    if visibility != PRIVATE and not sharing_enabled():
        raise HTTPException(
            status_code=403, detail='Sharing playlists is turned off'
        )
    owner_id = _owner_of(entry)
    if not owner_id:
        raise HTTPException(
            status_code=400, detail='This playlist has no owner to share it'
        )
    wanted = payload.get('shared_with')
    by_name = {
        username.casefold(): uid for uid, username in _usernames().items()
    }
    user_ids: list[int] = []
    for raw in wanted if isinstance(wanted, list) else []:
        uid = by_name.get(str(raw or '').strip().casefold())
        if uid is None:
            raise HTTPException(status_code=400, detail=f'Unknown user {raw}')
        if uid != owner_id and uid not in user_ids:
            user_ids.append(uid)
    if visibility == SHARED and not user_ids:
        raise HTTPException(
            status_code=400, detail='Choose who to share the playlist with'
        )
    editor_ids = _playlist_editor_ids(
        payload, entry, visibility, user_ids, by_name
    )
    stored = str(entry.get('name') or name)
    await asyncio.to_thread(
        shares.set_visibility, stored, visibility, user_ids, editor_ids
    )
    await announce_playlists_changed()
    usernames = _usernames()
    editors = (await asyncio.to_thread(shares.editors)).get(
        share_key(stored), []
    )
    return {
        'name': stored,
        'visibility': visibility,
        'shared_with': [
            usernames[uid] for uid in user_ids if uid in usernames
        ],
        'editors': [usernames[uid] for uid in editors if uid in usernames],
    }


def _playlist_editor_ids(
    payload: dict[str, Any],
    entry: dict[str, Any],
    visibility: str,
    user_ids: list[int],
    by_name: dict[str, int],
) -> Optional[list[int]]:
    """The ``editors`` of a visibility change as user ids (``None`` when
    left out: the current ones stay); 400 unless each is on the share
    list of a Library playlist."""

    if 'editors' not in payload:
        return None
    raw = payload['editors']
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail='editors must be a list')
    editor_ids: list[int] = []
    for value in raw:
        uid = by_name.get(str(value or '').strip().casefold())
        if uid is None:
            raise HTTPException(
                status_code=400, detail=f'Unknown user {value}'
            )
        if uid not in editor_ids:
            editor_ids.append(uid)
    if not editor_ids:
        return editor_ids
    if not entry.get('manual'):
        raise HTTPException(
            status_code=400,
            detail='Only playlists made in the Library can have editors',
        )
    if visibility != SHARED or not set(editor_ids) <= set(user_ids):
        raise HTTPException(
            status_code=400,
            detail='Editors must be among the people it is shared with',
        )
    return editor_ids


@router.post('/api/library/playlists/copy')
async def copy_library_playlist_endpoint(request: Request) -> dict[str, Any]:
    """Save a copy of a playlist you can open (your own, one shared with
    you or a public one) as a new playlist of yours, which you can edit.
    ``{name, new_name?}``; songs an admin hid from users are left out."""

    payload = await _json_object(request)
    name = str(payload.get('name') or '').strip()
    entry = require_playlist_visible(name, request)
    ctx = library_context()
    files = await asyncio.to_thread(
        filter_paths_for_request, list(entry.get('files') or []), request
    )
    taken = existing_playlist_names(ctx.download_dir)
    new_name = str(payload.get('new_name') or '').strip()
    if not new_name:
        base = f'{entry.get("name") or name} (copy)'
        new_name = base
        number = 2
        while new_name.casefold() in taken:
            new_name = f'{base} {number}'
            number += 1
    try:
        result = await asyncio.to_thread(copy_playlist, ctx, files, new_name)
    except ManualPlaylistError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail=str(exc)
        ) from exc
    claim_manual_playlist(str(result.get('name') or new_name), request)
    invalidate_library_paths_cache()
    await announce_playlists_changed()
    return result


def _unlink_imported_playlist(entry: dict[str, Any], name: str) -> None:
    """Forget where an imported playlist came from: its catalog row (and
    cached Spotify tracks and batches), its watch, and move its owner to
    the Library playlists'."""

    owner_id = _owner_of(entry)
    key = share_key(name)
    sid = ''
    catalog = state.playlist_catalog
    if catalog is not None:
        exact = next(
            (n for n in catalog.list_playlist_names() if share_key(n) == key),
            None,
        )
        if exact is not None:
            sid = catalog.spotify_id_for_playlist(exact) or ''
            catalog.delete_playlist(exact)
    if state.manual_playlist_owners is not None and owner_id:
        state.manual_playlist_owners.set_owner(name, owner_id)
    # Nothing rewrites it from a source any more: hidden songs simply
    # aren't in it, and can be added back like any other song.
    if state.playlist_hidden is not None:
        state.playlist_hidden.forget(name)
    if state.monitor_db is not None:
        for watch in state.monitor_db.list_playlists(owner_id or None):
            if watch.kind == KIND_PLAYLIST and (
                share_key(watch.name) == key
                or (sid and watch.spotify_id == sid)
            ):
                state.monitor_db.delete_playlist(watch.id)
    if not sid:
        return
    if state.playlist_batch_store is not None:
        state.playlist_batch_store.delete_for_spotify_playlist(
            sid, user_id=owner_id
        )
    still_used = catalog is not None and any(
        row['spotify_id'] == sid
        for row in catalog.list_playlists_with_spotify_id()
    )
    if state.playlist_spotify_cache is not None and not still_used:
        state.playlist_spotify_cache.delete_playlist(sid)


@router.post('/api/library/playlists/detach')
async def detach_library_playlist_endpoint(
    request: Request,
) -> dict[str, Any]:
    """Make an imported (Spotify / YouTube Music) playlist a Library one
    so it can be edited: tracks and owner stay, the link to its source
    and its watch go. ``{name}``."""

    payload = await _json_object(request)
    name = str(payload.get('name') or '').strip()
    entry = require_playlist_visible(name, request, manage=True)
    if entry.get('liked') or entry.get('manual'):
        raise HTTPException(
            status_code=409, detail='This playlist can already be edited'
        )
    ctx = library_context()
    try:
        result = await asyncio.to_thread(
            detach_imported_playlist, ctx, str(entry.get('name') or name)
        )
    except ManualPlaylistError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail=str(exc)
        ) from exc
    # Its file holds the order now; nothing rewrites it from a source.
    if state.playlist_custom_order is not None:
        await asyncio.to_thread(
            state.playlist_custom_order.drop, str(result['name'])
        )
    try:
        await asyncio.to_thread(
            _unlink_imported_playlist, entry, str(result['name'])
        )
    except Exception:
        logger.opt(exception=True).warning(
            'Could not unlink {!r} from its source', result['name']
        )
    invalidate_library_paths_cache()
    await announce_playlists_changed()
    return result


def _require_playlist_hidden() -> PlaylistHiddenSongs:
    if state.playlist_hidden is None:
        raise HTTPException(status_code=503, detail='Starting up')
    return state.playlist_hidden


def _imported_playlist_to_change(
    name: str, request: Optional[Request]
) -> dict[str, Any]:
    """Imported playlist *name*'s entry, when *request* may change it -
    the owner's or, for an admin, anyone's. 409 for a Library playlist
    (it is edited instead) and for liked songs."""

    entry = require_playlist_visible(name, request, manage=True)
    if entry.get('liked') or entry.get('manual'):
        raise HTTPException(
            status_code=409,
            detail='Songs are removed from a Library playlist, not hidden',
        )
    return entry


def hidden_playlist_songs(
    name: str, request: Optional[Request]
) -> dict[str, Any]:
    """``{name, songs}``: the songs hidden from imported playlist *name*,
    most recently hidden first, each ``{key, label, file, present,
    hidden_at}`` - ``present`` while its file is still in the library."""

    entry = _imported_playlist_to_change(name, request)
    rows = _require_playlist_hidden().items(entry['name'])
    ctx = library_context()
    return {
        'name': entry['name'],
        'songs': [
            {
                'key': row['key'],
                'label': row['label'],
                'file': row['file'],
                'present': bool(row['file'])
                and resolve_library_file(row['file'], ctx) is not None,
                'hidden_at': row['hidden_at'],
            }
            for row in rows
        ],
    }


async def change_hidden_playlist_songs(
    request: Request, name: str, hide: list[str], show: list[str]
) -> dict[str, Any]:
    """Hide the library files *hide* from imported playlist *name* and
    show the hidden songs *show* (their ``key``) again - for the web page
    and the apps alike. ``{name, hidden, keys, shown, restored, files,
    count}``: ``keys`` are the hidden songs' (what *show* takes to undo
    it); ``restored`` of the ``shown`` songs went back into the playlist
    (the others' files are gone; the source brings them back)."""

    if not hide and not show:
        raise HTTPException(status_code=400, detail='Nothing to hide or show')
    entry = _imported_playlist_to_change(name, request)
    store = _require_playlist_hidden()
    ctx = library_context()
    stored = str(entry['name'])
    result: dict[str, Any] = {
        'name': stored,
        'hidden': 0,
        'keys': [],
        'shown': 0,
        'restored': 0,
    }
    try:
        if show:
            result.update(
                await asyncio.to_thread(
                    show_playlist_songs,
                    ctx,
                    store,
                    stored,
                    show,
                    catalog=state.playlist_catalog,
                )
            )
        if hide:
            ids = await asyncio.to_thread(
                source_track_ids,
                stored,
                hide,
                catalog=state.playlist_catalog,
                monitor_db=state.monitor_db,
            )
            result.update(
                await asyncio.to_thread(
                    hide_playlist_songs,
                    ctx,
                    store,
                    stored,
                    hide,
                    track_ids=ids,
                    catalog=state.playlist_catalog,
                )
            )
    except HiddenSongsError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail=str(exc)
        ) from exc
    invalidate_library_paths_cache()
    if _navidrome_playlist_sync_on():
        spawn_task(
            asyncio.to_thread(_sync_navidrome_playlist, stored),
            name='navidrome-sync-hidden-songs',
        )
    await announce_playlists_changed()
    return result


def _navidrome_playlist_sync_on() -> bool:
    settings = state.settings
    return settings.get('sync_navidrome', True) is not False and bool(
        _effective_navidrome_settings(settings).get('enabled')
    )


def _sync_navidrome_playlist(name: str) -> None:
    """Mirror playlist *name*'s M3U into its Navidrome playlist (best
    effort)."""

    settings = state.settings
    ctx = library_context()
    path = m3u.find_m3u_for_name(ctx.download_dir, name)
    if path is None:
        return
    files = m3u.read_m3u_tracks(
        path, ctx.download_dir, ctx.slskd_dir, tuple(ctx.extra_dirs or ())
    )
    songs = [
        enrich_song_from_library_file(
            {'filename': stored}, ctx.download_dir, ctx.slskd_dir
        )
        for stored in files
    ]
    # A watch named its Navidrome playlist with the source's own name.
    synced = next(iter(catalog_names_for(state.playlist_catalog, name)), name)
    try:
        sync_playlist_to_navidrome(
            synced,
            songs,
            settings,
            navidrome_index=state.navidrome_index,
            download_dir=ctx.download_dir,
            trigger_scan=False,
        )
    except Exception:
        logger.opt(exception=True).warning(
            'Navidrome sync failed for {!r}', synced
        )


@router.get('/api/library/playlists/details')
async def playlist_details_endpoint(
    request: Request, name: str = Query(..., min_length=1)
) -> dict[str, Any]:
    """What the playlist page filters its songs by, for a playlist the
    caller can open: ``{name, providers, navidrome}`` - ``providers`` is
    ``{file: provider}`` for the songs whose provider is known, and
    ``navidrome`` is ``{enabled, unmatched}``: while Navidrome sync is on,
    the songs that have no Navidrome song id yet."""

    entry = require_playlist_visible(name, request)
    files = await asyncio.to_thread(
        filter_paths_for_request, list(entry.get('files') or []), request
    )
    return await asyncio.to_thread(
        _playlist_details, str(entry['name']), files
    )


@router.get('/api/library/playlists/diagnostics')
async def playlist_diagnostics_endpoint(
    request: Request, name: str = Query(..., min_length=1)
) -> dict[str, Any]:
    """Compare a Spotify playlist with its local and Navidrome records."""

    entry = require_playlist_visible(name, request)
    files = await asyncio.to_thread(
        filter_paths_for_request, list(entry.get('files') or []), request
    )
    return await asyncio.to_thread(
        _playlist_diagnostics, str(entry['name']), files, request
    )


def _playlist_diagnostics(
    name: str, files: list[str], request: Request
) -> dict[str, Any]:
    ctx = library_context()
    return build_playlist_diagnostics(
        name,
        files,
        PlaylistDiagnosticsContext(
            catalog=state.playlist_catalog,
            spotify_cache=state.playlist_spotify_cache,
            track_index=state.track_index,
            navidrome_index=state.navidrome_index,
            monitor_db=state.monitor_db,
            hidden=state.playlist_hidden,
            settings=state.settings,
            download_dir=ctx.download_dir,
            slskd_dir=ctx.slskd_dir,
            is_admin=request_is_admin(request),
            user_id=request_user_id(request),
            navidrome_client=NavidromeClient,
        ),
    )


def _playlist_details(name: str, files: list[str]) -> dict[str, Any]:
    by_file = {
        str(row.get('file') or '').replace('\\', '/'): row
        for row in listing_for_request(library_context())
    }
    keys = {
        path: entry_content_key(by_file[path]) if path in by_file else ''
        for path in dict.fromkeys(files)
    }
    enabled = (
        _navidrome_playlist_sync_on() and state.navidrome_index is not None
    )
    unmatched: list[str] = []
    if enabled:
        try:
            matched = state.navidrome_index.matched_files(keys)
        except Exception:
            logger.opt(exception=True).warning(
                'Could not read the Navidrome matches of {!r}', name
            )
            matched = set(keys)
        unmatched = [path for path in keys if path not in matched]
    return {
        'name': name,
        'providers': providers_for(state.file_providers, keys),
        'navidrome': {'enabled': enabled, 'unmatched': unmatched},
    }


@router.get('/api/library/playlists/hidden')
async def hidden_playlist_songs_endpoint(
    request: Request, name: str = Query(..., min_length=1)
) -> dict[str, Any]:
    """The songs hidden from an imported playlist you can change."""

    return await asyncio.to_thread(hidden_playlist_songs, name, request)


@router.post('/api/library/playlists/hidden')
async def change_hidden_playlist_songs_endpoint(
    request: Request,
) -> dict[str, Any]:
    """Hide songs from an imported playlist - and keep them out of it
    when its watch or its link brings them back - or show them again:
    ``{name, hide: [library paths], show: [hidden song keys]}``. The
    audio files stay in the library; the source playlist is untouched."""

    payload = await _json_object(request)
    return await change_hidden_playlist_songs(
        request,
        str(payload.get('name') or '').strip(),
        _string_list(payload.get('hide')),
        _string_list(payload.get('show')),
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or '').strip()]


@router.delete('/api/library/playlist')
async def delete_library_playlist_endpoint(
    request: Request,
    playlist_name: str = Query(..., min_length=1),
) -> dict[str, Any]:
    """Delete all tracks in a playlist, its M3U, and catalog entry.

    A user deletes their own playlist only: files others still own
    stay on disk (losing just this owner's row), files nobody else
    owns go like a single delete.
    """

    if state.downloader is None:
        raise HTTPException(status_code=500, detail='Downloader not ready')

    if is_liked_playlist(playlist_name):
        # Deleting a playlist deletes its tracks from disk. Here that must
        # only ever mean "unlike everything": the songs are the user's
        # library, the playlist merely lists the ones they hearted.
        await asyncio.to_thread(_clear_likes, likes_scope(request))
        return {
            'ok': True,
            'playlist': playlist_name,
            'files': [],
            'deleted_count': 0,
            'failed_count': 0,
            'failed': [],
            'playlists_affected': [],
            'playlists_refresh_scheduled': False,
        }

    return await _delete_playlist_by_name(request, playlist_name)


async def _delete_playlist_by_name(
    request: Request, playlist_name: str
) -> dict[str, Any]:
    """Shared core of both playlist delete endpoints."""

    if request_is_admin(request):

        def _run() -> dict[str, Any]:
            assert state.downloader is not None
            return delete_playlist_from_library(
                playlist_name,
                Path(state.downloader.download_dir),
                state.settings,
                state,
            )

        result = await asyncio.to_thread(_run)
    else:
        match = require_playlist_visible(playlist_name, request, manage=True)
        result = await _delete_owned_playlist(request, match)
    if not result.get('ok'):
        raise HTTPException(
            status_code=400,
            detail=str(result.get('error') or 'Playlist delete failed'),
        )
    affected = set(result.get('playlists_affected') or [])
    if affected:
        await _schedule_playlist_refresh_after_delete(affected)
    result['playlists_refresh_scheduled'] = bool(affected)
    if state.playlist_shares is not None:
        await asyncio.to_thread(state.playlist_shares.forget, playlist_name)
    if state.playlist_hidden is not None:
        await asyncio.to_thread(state.playlist_hidden.forget, playlist_name)
    if state.playlist_custom_order is not None:
        await asyncio.to_thread(
            state.playlist_custom_order.drop, playlist_name
        )
    if state.playlist_pending is not None:
        await asyncio.to_thread(state.playlist_pending.drop, playlist_name)
    if state.external_playlist_imports is not None:
        await asyncio.to_thread(
            state.external_playlist_imports.forget, playlist_name
        )
    await announce_playlists_changed()
    return result


async def _delete_owned_playlist(
    request: Request, match: dict[str, Any]
) -> dict[str, Any]:
    """One user's playlist delete (see
    :func:`delete_library_playlist_endpoint`)."""

    name = str(match.get('name') or '')
    user_id = request_user_id(request)

    def _run() -> dict[str, Any]:
        assert state.downloader is not None
        download_dir = Path(state.downloader.download_dir)
        if state.library_trash is not None:
            result = delete_playlist_from_library(
                name, download_dir, state.settings, state
            )
            if state.manual_playlist_owners is not None:
                state.manual_playlist_owners.forget_owner(name)
            return result
        if match.get('manual'):
            result = delete_playlist_from_library(
                name, download_dir, state.settings, state
            )
            if state.manual_playlist_owners is not None:
                state.manual_playlist_owners.forget_owner(name)
            return result
        files = [
            str(item or '').strip().replace('\\', '/')
            for item in (match.get('files') or [])
            if str(item or '').strip()
        ]
        to_delete: list[str] = []
        released = 0
        for stored in files:
            action, key = ownership_action(stored, request)
            if action == 'delete' and key:
                to_delete.append(stored)
            elif action == 'release' and key:
                release_file_ownership(stored, key, user_id)
                released += 1
        keys = {stored: stored_content_key(stored) for stored in to_delete}
        batch = delete_library_files(
            to_delete, library_context(), state, log_failures=False
        )
        for gone in batch.get('deleted') or []:
            if keys.get(gone):
                drop_file_owners(keys[gone])
        if state.playlist_catalog is not None:
            state.playlist_catalog.delete_playlist(name)
        organize = bool(
            state.settings.get('organize_by_artist', False)
            or state.settings.get('organize_by_album', False)
        )
        shell = remove_playlist_shell(
            name, download_dir, organize_by_artist=organize
        )
        affected = set(batch.get('playlists_affected') or [])
        affected.add(name)
        failed = list(batch.get('failed') or [])
        logger.info(
            'Playlist delete finished for {!r}: {} audio file(s) '
            'removed, {} released, {} failed, {} M3U file(s)',
            name,
            len(batch.get('deleted') or []),
            released,
            len(failed),
            shell['m3u_removed'],
        )
        return {
            'ok': True,
            'playlist': name,
            'files': list(batch.get('deleted') or []),
            'deleted_count': len(batch.get('deleted') or []),
            'released_count': released,
            'failed_count': len(failed),
            'failed': failed,
            'playlists_affected': sorted(affected),
        }

    result = await asyncio.to_thread(_run)
    return result


@router.get('/api/playlists/batches')
async def list_playlist_batches_endpoint(request: Request) -> dict[str, Any]:
    """Tracked Spotify playlist batches (summary from Spotify cache)."""

    scope = _batch_scope(request)
    reports = await asyncio.to_thread(
        _build_playlist_batch_reports, user_id=scope
    )
    return {'playlists': reports, 'count': len(reports)}


@router.get('/api/playlists/batches/{spotify_playlist_id}')
async def get_playlist_batch_detail_endpoint(
    request: Request,
    spotify_playlist_id: str,
    tracks: bool = Query(default=True),
    refresh: bool = Query(default=False),
) -> dict[str, Any]:
    """Completeness for one playlist using cached Spotify track list."""

    scope = _batch_scope(request)
    report = await asyncio.to_thread(
        _report_for_spotify_playlist,
        spotify_playlist_id,
        mode='spotify',
        include_missing_tracks=tracks,
        refresh=refresh,
        user_id=scope,
    )
    if report is None:
        raise HTTPException(status_code=404, detail='Playlist not found')
    return report


def _purge_playlist_tracking(spotify_playlist_id: str) -> None:
    sid = str(spotify_playlist_id or '').strip()
    if not sid:
        return
    batches_removed = 0
    if state.playlist_batch_store is not None:
        batches_removed = (
            state.playlist_batch_store.delete_for_spotify_playlist(sid)
        )
    if state.playlist_spotify_cache is not None:
        state.playlist_spotify_cache.delete_playlist(sid)
    monitor_removed = False
    if state.monitor_db is not None:
        monitored = state.monitor_db.get_by_spotify_id(sid)
        if monitored is not None:
            state.monitor_db.delete_playlist(monitored.id)
            monitor_removed = True
    logger.info(
        'Playlist delete: cleared tracking for {} '
        '(batch_rows={}, spotify_cache=yes, monitor={})',
        sid,
        batches_removed,
        'removed' if monitor_removed else 'none',
    )


@router.delete('/api/playlists/batches/{spotify_playlist_id}')
async def delete_playlist_batch_endpoint(
    request: Request,
    spotify_playlist_id: str,
) -> dict[str, Any]:
    """Delete playlist audio, catalog, M3U, and batch/monitor/cache tracking."""

    sid = str(spotify_playlist_id or '').strip()
    if not sid:
        raise HTTPException(
            status_code=400, detail='spotify_playlist_id required'
        )
    if state.downloader is None:
        raise HTTPException(status_code=500, detail='Downloader not ready')

    scope = _batch_scope(request)
    meta = _known_spotify_playlist_sources(scope).get(sid)
    if meta is None:
        raise HTTPException(status_code=404, detail='Playlist not found')

    playlist_name = str(meta.get('playlist_name') or sid).strip() or sid
    logger.info(
        'Playlist batch delete requested for {!r} (spotify_id={})',
        playlist_name,
        sid,
    )

    if request_is_admin(request):

        def _run() -> dict[str, Any]:
            assert state.downloader is not None
            result = delete_playlist_from_library(
                playlist_name,
                Path(state.downloader.download_dir),
                state.settings,
                state,
            )
            _purge_playlist_tracking(sid)
            return result

        result = await asyncio.to_thread(_run)
    else:
        batch = meta.get('batch')
        if not isinstance(batch, dict) or not batch.get('id'):
            raise HTTPException(status_code=404, detail='Playlist not found')
        result = await _delete_playlist_by_name(request, playlist_name)
        if state.playlist_batch_store is not None:
            await asyncio.to_thread(
                state.playlist_batch_store.delete_for_spotify_playlist,
                sid,
                request_user_id(request),
            )
    if not result.get('ok'):
        raise HTTPException(
            status_code=400,
            detail=str(result.get('error') or 'Playlist delete failed'),
        )
    affected = set(result.get('playlists_affected') or [])
    if affected:
        await _schedule_playlist_refresh_after_delete(affected)
    result['spotify_playlist_id'] = sid
    result['playlists_refresh_scheduled'] = bool(affected)
    return result


@router.get('/api/playlists/incomplete')
async def list_incomplete_playlists_endpoint(
    request: Request,
) -> dict[str, Any]:
    """Playlist batches that are still missing tracks vs Spotify."""

    scope = _batch_scope(request)
    reports = await asyncio.to_thread(
        _build_incomplete_playlist_reports, user_id=scope
    )
    return {'playlists': reports, 'count': len(reports)}


@router.post('/api/playlists/incomplete/download-missing')
async def download_missing_playlist_tracks_endpoint(
    request: Request,
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Queue only tracks from a Spotify playlist that are not in the library."""

    if state.downloader is None:
        raise HTTPException(status_code=500, detail='Downloader not ready')

    spotify_playlist_id = str(body.get('spotify_playlist_id') or '').strip()
    playlist_url = str(body.get('playlist_url') or '').strip()
    if not spotify_playlist_id and playlist_url:
        parsed = spotify.parse_spotify_url(playlist_url)
        if parsed is not None and parsed[0] == 'playlist':
            spotify_playlist_id = parsed[1]
    if not spotify_playlist_id:
        raise HTTPException(
            status_code=400,
            detail='spotify_playlist_id or playlist_url required',
        )

    playlist_name, resolved_url, missing = await asyncio.to_thread(
        _missing_tracks_for_playlist,
        spotify_playlist_id,
        user_id=_batch_scope(request),
    )
    if not missing:
        if state.playlist_batch_store is not None:
            for batch in state.playlist_batch_store.list_open_batches():
                if batch['spotify_playlist_id'] == spotify_playlist_id:
                    state.playlist_batch_store.mark_complete(batch['id'])
        linked = await asyncio.to_thread(
            _rebuild_playlist_catalog_from_library,
            playlist_name,
            spotify_playlist_id,
        )
        do_m3u, do_navidrome = playlist_refresh_enabled(state.settings)
        if linked and (do_m3u or do_navidrome):
            await asyncio.to_thread(
                refresh_playlists_after_moves,
                {playlist_name},
                settings=state.settings,
                downloader=state.downloader,
                playlist_catalog=state.playlist_catalog,
                track_index=state.track_index,
                monitor_db=state.monitor_db,
                navidrome_index=state.navidrome_index,
                navidrome_scan=bool(
                    state.settings.get('navidrome', {}).get(
                        'scan_after_download', True
                    )
                ),
                playlist_spotify_cache=state.playlist_spotify_cache,
                cover_cache=state.cover_cache,
                metadata_cache=state.metadata_cache,
            )
        return {
            'count': 0,
            'message': 'Playlist already complete',
            'catalog_linked': linked,
            'playlist_refresh': bool(linked and (do_m3u or do_navidrome)),
        }

    generate_m3u = bool(body.get('generate_m3u', True))
    batch_id: Optional[int] = None
    if state.playlist_batch_store is not None:
        batch_id = await asyncio.to_thread(
            state.playlist_batch_store.start_batch,
            spotify_playlist_id,
            playlist_name,
            resolved_url,
            len(missing),
            user_id=request_user_id(request),
        )

    songs: list[dict[str, Any]] = []
    for index, track in enumerate(missing):
        song = dict(track)
        song['downtify_playlist_url'] = resolved_url
        song['downtify_track_order'] = index
        songs.append(song)

    result = await _submit_playlist_batch(
        songs,
        resolved_url,
        generate_m3u=generate_m3u,
        batch_id=batch_id,
        user_id=request_user_id(request),
    )
    result['missing_count'] = len(missing)
    result['playlist_name'] = playlist_name
    return result


@router.post('/api/playlist/m3u')
async def write_playlist_m3u_endpoint(request: Request) -> dict[str, Any]:
    """Write an M3U for the playlist after the per-track downloads.

    The frontend POSTs ``{playlist_url, tracks: [{filename, title,
    artist, duration}, ...]}``, where ``playlist_url`` is a Spotify,
    Deezer or YouTube Music playlist. The playlist name is resolved server-side
    via :func:`monitor.fetch_playlist` so the existing ``/api/song/url``
    shape stays untouched.
    """

    if state.downloader is None:
        raise HTTPException(status_code=500, detail='Downloader not ready')
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail='Invalid JSON') from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail='Invalid payload')

    playlist_url = str(payload.get('playlist_url') or '').strip()
    if not playlist_url:
        raise HTTPException(status_code=400, detail='Missing playlist_url')
    source_and_id = parse_playlist_url(playlist_url)
    if source_and_id is None:
        raise HTTPException(
            status_code=400,
            detail='Not a Spotify, Deezer or YouTube Music playlist URL',
        )

    tracks = payload.get('tracks') or []
    if not isinstance(tracks, list):
        raise HTTPException(status_code=400, detail='tracks must be a list')

    try:
        playlist_name, _ = await asyncio.to_thread(
            fetch_playlist, *source_and_id
        )
    except Exception as exc:
        logger.exception('Failed to resolve playlist {}', playlist_url)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    hidden = hidden_songs_for(playlist_name)
    entries = [
        t
        for t in tracks
        if isinstance(t, dict) and not hidden.hides_file(t.get('filename'))
    ]
    playlist_subdir = m3u.sanitize_playlist_name(playlist_name)
    organize = _organize_enabled()
    target, kept = m3u.write_m3u(
        state.downloader.download_dir,
        playlist_name,
        entries,
        playlist_subdir=None if organize else playlist_subdir,
    )
    if target is None:
        raise HTTPException(
            status_code=400, detail='No tracks resolved to a file on disk'
        )
    await asyncio.to_thread(
        download_playlist_cover,
        *source_and_id,
        target,
        state.settings,
    )
    return {'path': str(target), 'count': kept}
