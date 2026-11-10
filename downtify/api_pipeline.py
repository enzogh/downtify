"""The download pipeline shared by the ``/api`` routers.

Queue jobs and slots, ``_run_download``, playlist batches and their
M3U/cover, the playlist catalog after a download, settings load/save,
likes and library-changed announcements, usage snapshots.

Re-exported by :mod:`downtify.api`.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import (
    datetime,
    timezone,
)
from pathlib import (
    Path,
)
from typing import (
    Any,
    AsyncIterator,
    Collection,
    Hashable,
    Optional,
)

from fastapi import (
    HTTPException,
    Request,
)
from loguru import (
    logger,
)

from . import (
    library_only,
    m3u,
)
from .api_core import (
    _clamp_parallel_downloads,
    _effective_slskd_settings,
    _fetch_playlist_tracks,
    _organize_enabled,
    _playlists_for_successful_download,
    _record_download_traffic,
    _schedule_playlist_refresh_after_download,
    claim_pending_playlist_songs,
    forget_library_file,
    library_context,
    record_download_outcome,
    request_is_admin,
    request_user_id,
    spawn_task,
    state,
)
from .discover import (
    DiscoverStore,
)
from .download_history import (
    FINISHED,
)
from .download_log import (
    OUTCOME_SKIPPED,
)
from .download_queue import (
    PendingDownload,
    queue_pause,
)
from .downloader import (
    DOWNLOAD_EXECUTOR,
    NoAudioMatchError,
    TrackTooLongError,
    save_playlist_cover,
)
from .external_library import (
    extra_dirs_from_settings,
)
from .external_sync import (
    folders_removed,
    unmap_extra_folder,
)
from .ip_rotation import (
    is_youtube_hiccup,
)
from .library_catalog import (
    LibraryContext,
    drop_library_listing_files,
    entry_content_key,
    listing_for_request,
    merge_library_listing_file,
)
from .library_paths import (
    library_stored_path,
    locate_library_file,
    slskd_dir_from_downloader,
)
from .library_paths_cache import (
    add_invalidation_listener,
    invalidate_library_paths_cache,
)
from .library_reconcile import (
    playlist_refresh_enabled,
    refresh_playlists_after_moves,
)
from .library_usage import (
    library_snapshot,
)
from .likes import (
    LikedTracks,
    content_key_for,
    sync_liked_playlist,
)
from .monitor import (
    KIND_PLAYLIST,
    SOURCE_SPOTIFY,
    MonitoredPlaylist,
    download_playlist_cover,
    fetch_playlist,
    parse_playlist_url,
)
from .navidrome import (
    _effective_navidrome_settings,
    cache_navidrome_song_id,
)
from .playlist_hidden import (
    HiddenSongs,
)
from .search_ahead import (
    SEARCH_AHEAD_DEPTH,
)
from .track_index import (
    normalize_spotify_track_id,
    resolve_existing_download,
)
from .watch_stats import (
    norm_path,
)


async def after_library_delete(
    results: dict[str, dict[str, Any]],
    response: dict[str, Any],
    user_id: int = 0,
) -> dict[str, Any]:
    """Update the library stores after ``DELETE /delete`` or
    ``/delete/batch`` and report affected playlists on ``response``.

    Wiped files leave every store (and everybody's likes); released
    ones only drop *user_id*'s like — the file and everyone else's
    hearts stay.
    """

    deleted = [f for f, r in results.items() if r.get('deleted')]
    released = [f for f, r in results.items() if r.get('released')]
    affected: set[str] = set()
    if deleted or (released and user_id):

        def _forget() -> None:
            liked_before = state.likes.count() if state.likes else 0
            for name in deleted:
                affected.update(forget_library_file(name))
            if state.likes is not None and user_id:
                for name in released:
                    state.likes.unlike(name, user_id)
            if deleted:
                # The rows are gone from disk: the RAM snapshot must
                # stop claiming them, or the search "already
                # downloaded" badge keeps a deleted track downloaded.
                drop_library_listing_files(library_context(), deleted)
                invalidate_library_paths_cache()
            if state.likes is not None and state.likes.count() != liked_before:
                # A deleted song can't stay liked, or on the playlist.
                _sync_liked_playlist()
                _announce_likes()

        await asyncio.to_thread(_forget)
    response['playlists_affected'] = sorted(affected)
    # The deleted tracks' playlists get their M3U/Navidrome playlist
    # rewritten in the background (can take minutes).
    response['playlists_refresh_scheduled'] = bool(affected)
    if affected:
        await _schedule_playlist_refresh_after_delete(affected)
    return response


def _upsert_track_in_playlists(
    song: dict[str, Any],
    filename: str,
    playlist_names: set[str],
    *,
    primary_playlist: Optional[str] = None,
    primary_order: int = 0,
    spotify_playlist_id: Optional[str] = None,
    user_id: int = 0,
) -> None:
    """Register the file in the catalog for every affected playlist.

    Only the playlist the user actually downloaded (*primary_playlist*)
    is claimed for them; the other catalog playlists that happen to
    hold the track keep their owners.
    """

    if state.downloader is None or state.playlist_catalog is None:
        return
    if not playlist_names:
        return
    dl_dir = Path(state.downloader.download_dir)
    slskd = slskd_dir_from_downloader(state.downloader)
    full = locate_library_file(filename, dl_dir, slskd)
    if full is None:
        return
    catalog = state.playlist_catalog
    primary = str(primary_playlist or '').strip()
    for pl_name in sorted(playlist_names):
        sid = (
            spotify_playlist_id
            if pl_name == primary and spotify_playlist_id
            else catalog.spotify_id_for_playlist(pl_name)
        )
        catalog.ensure_playlist(
            pl_name,
            spotify_id=sid,
            user_id=user_id if pl_name == primary else None,
        )
        if hidden_from_playlist(pl_name, song, filename):
            continue
        order = primary_order if pl_name == primary else 0
        catalog.upsert_track(pl_name, song, filename, full, track_order=order)


def _register_download_playlists_on_disk(
    song: dict[str, Any],
    filename: str,
    *,
    playlist_name: Optional[str] = None,
    spotify_playlist_id: Optional[str] = None,
    track_order: int = 0,
    user_id: int = 0,
) -> set[str]:
    """Update indexes, catalog, monitor paths; return playlists to refresh."""

    if state.downloader is None or not filename:
        return set()
    tid = normalize_spotify_track_id(song)
    if state.monitor_db is not None and tid:
        state.monitor_db.update_filename_for_spotify(tid, filename)

    affected = _playlists_for_successful_download(
        song, primary_playlist=playlist_name
    )
    _upsert_track_in_playlists(
        song,
        filename,
        affected,
        primary_playlist=playlist_name,
        primary_order=track_order,
        spotify_playlist_id=spotify_playlist_id,
        user_id=user_id,
    )
    if state.track_index is not None:
        dl_dir = Path(state.downloader.download_dir)
        slskd = slskd_dir_from_downloader(state.downloader)
        full = locate_library_file(filename, dl_dir, slskd)
        if full is not None:
            state.track_index.register_song(song, filename, full_path=full)
    invalidate_library_paths_cache()
    return affected


async def _claim_pending_playlist_songs(
    song: dict[str, Any], filename: str
) -> None:
    """:func:`claim_pending_playlist_songs` off the event loop, then tell
    open pages the playlists changed, so they show the song in place."""

    if not filename or state.playlist_pending is None:
        return
    changed = await asyncio.to_thread(
        claim_pending_playlist_songs, song, filename
    )
    if changed:
        invalidate_library_paths_cache()
        await announce_playlists_changed()


#: One lock per song id, so two accounts asking for the same track at
#: once share one download instead of writing one file twice.
_download_locks: dict[str, asyncio.Lock] = {}


def _register_job(
    song: dict[str, Any], status: str = 'queued', user_id: int = 0
) -> str:
    """Register a queue job, joining the running one when there is one.

    Two accounts asking for the same track share one job row (keyed by
    the song id as before): the requester joins ``user_ids``, an active
    job is never reset by a newcomer, and a finished one restarts fresh
    - the retry/re-download behavior stays exactly as it was.
    """

    song_id = str(song.get('song_id') or song.get('url') or id(song))
    job = state.download_jobs.get(song_id)
    if job is None:
        job = {
            'song': song,
            'status': status,
            'progress': 0,
            'message': '',
            'provider': '',
            'filename': None,
            'user_ids': set(),
        }
        state.download_jobs[song_id] = job
    elif job.get('status') not in {'queued', 'downloading'}:
        job.update(
            status=status,
            progress=0,
            message='',
            provider='',
            filename=None,
            finished_at=None,
        )
    if user_id:
        users = job.setdefault('user_ids', set())
        if isinstance(users, set):
            users.add(user_id)
        else:
            job['user_ids'] = set(users) | {user_id}
    return song_id


def _job_users(job: dict[str, Any]) -> set[int]:
    """The accounts waiting on a job row (any shape it comes in)."""

    users = job.get('user_ids')
    if isinstance(users, set):
        return {int(uid) for uid in users if uid}
    if job.get('user_id'):
        return {int(job['user_id'])}
    return set()


def _note_download_owner(stored_path: str, user_id: int) -> None:
    """Record *user_id* as an owner of an on-disk download (best effort).

    Called for fresh downloads and for dedup hits alike, so two users
    asking for the same track share the one file with one row each.
    Never fails the download it runs next to.
    """

    if not user_id or state.track_owners is None or state.downloader is None:
        return
    try:
        full = locate_library_file(
            stored_path,
            Path(state.downloader.download_dir),
            slskd_dir_from_downloader(state.downloader),
        )
        if full is None:
            return
        key = content_key_for(full)
        if not key:
            return
        name = str(stored_path or '').strip().replace('\\', '/')
        added = state.track_owners.add(key, user_id, name)
        # New to this user: poke the mobile feed so their next
        # incremental sync picks the track up.
        if added and state.library_sync is not None:
            state.library_sync.touch(name)
    except Exception:
        logger.opt(exception=True).debug(
            'Could not record owner for {}', stored_path
        )


def _note_download_owners(stored_path: str, user_ids: Collection[int]) -> None:
    """Claim one finished file for every account waiting on its job."""

    for waiter in sorted(set(user_ids)):
        if waiter:
            _note_download_owner(stored_path, waiter)


def _pending_download(
    song: dict[str, Any],
    song_id: str,
    *,
    user_id: int = 0,
    subdir: Optional[str] = None,
    delay_seconds: float = 0,
    playlist_name: Optional[str] = None,
    spotify_playlist_id: Optional[str] = None,
    track_order: int = 0,
) -> PendingDownload:
    """The saved copy of a job, with what ``_run_download`` was given."""

    job = state.download_jobs.get(song_id) or {}
    users = _job_users(job) | ({user_id} if user_id else set())
    return PendingDownload(
        song_id=song_id,
        song=song,
        options={
            'subdir': subdir,
            'delay_seconds': delay_seconds,
            'playlist_name': playlist_name,
            'spotify_playlist_id': spotify_playlist_id,
            'track_order': track_order,
        },
        user_ids=sorted(users),
    )


async def _remember_finished(song_id: str, job: dict[str, Any]) -> None:
    """Keep an ended job for the queue's history (best effort): it is
    shown again after a restart, newest first by ``finished_at``."""

    if job.get('status') not in FINISHED:
        return
    if not job.get('finished_at'):
        job['finished_at'] = time.time()
    store = state.download_history
    if store is None or state.download_jobs.get(song_id) is not job:
        return
    try:
        await asyncio.to_thread(store.record, song_id, dict(job))
    except Exception:
        logger.exception('Could not save the download history')


def restore_finished_jobs() -> int:
    """Put the kept finished jobs back in the queue after a start; how
    many. Jobs already there (a restored unfinished one) win."""

    store = state.download_history
    if store is None:
        return 0
    try:
        jobs = store.jobs()
    except Exception:
        logger.exception('Could not read the download history')
        return 0
    restored = 0
    for song_id, job in jobs:
        if song_id not in state.download_jobs:
            state.download_jobs[song_id] = job
            restored += 1
    return restored


def _drop_pending(song_ids: Optional[Collection[str]] = None) -> None:
    """Forget saved jobs (every one when *song_ids* is ``None``)."""

    store = state.pending_downloads
    if store is None:
        return
    try:
        if song_ids is None:
            store.clear()
        else:
            store.forget(song_ids)
    except Exception:
        logger.exception('Could not update the saved download queue')


async def _remember_pending(rows: list[PendingDownload]) -> None:
    """Save unfinished jobs so a restart queues them again (best effort)."""

    store = state.pending_downloads
    if store is None or not rows:
        return
    try:
        await asyncio.to_thread(store.add, rows)
    except Exception:
        logger.exception('Could not save the download queue')


async def _forget_pending(song_ids: Collection[str]) -> None:
    if state.pending_downloads is not None:
        await asyncio.to_thread(_drop_pending, song_ids)


async def _broadcast_queue_state() -> None:
    await state.connections.broadcast({
        'type': 'queue_state',
        **_global_queue_status(),
    })


# Everyone learns the moment a paused queue's last download ends.
queue_pause.on_drained = _broadcast_queue_state


class _BatchProgress:
    """How many songs of a batch are done, for :func:`_search_ahead`."""

    def __init__(self) -> None:
        self.done = 0
        self._changed = asyncio.Event()

    def finished(self) -> None:
        self.done += 1
        self._changed.set()

    async def changed(self) -> None:
        self._changed.clear()
        await self._changed.wait()


async def _search_ahead(
    songs: list[dict[str, Any]],
    subdir: Optional[str],
    progress: _BatchProgress,
) -> None:
    """Have the next songs of a batch searched while earlier ones download.

    Keeps the search at most "Parallel downloads" + a couple of songs
    ahead of the finished ones, so a long playlist never turns into a
    burst of YouTube searches whose results go stale before they're used.
    """

    start = getattr(state.downloader, 'search_ahead_for', None)
    if start is None or len(songs) < 2:
        return
    for index, song in enumerate(songs):
        while index >= progress.done + _search_ahead_window():
            await progress.changed()
        start(song, subdir)


def _search_ahead_window() -> int:
    return (
        _clamp_parallel_downloads(state.settings.get('max_parallel_downloads'))
        + SEARCH_AHEAD_DEPTH
    )


@contextlib.asynccontextmanager
async def _searching_ahead(
    songs: list[dict[str, Any]], subdir: Optional[str]
) -> AsyncIterator[_BatchProgress]:
    """Run :func:`_search_ahead` for the duration of a batch."""

    progress = _BatchProgress()
    task = asyncio.ensure_future(_search_ahead(songs, subdir, progress))
    try:
        yield progress
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        prepared = getattr(state.downloader, 'search_ahead', None)
        if prepared is not None:
            prepared.discard(songs)


def _download_slot(
    owner: Hashable,
) -> contextlib.AbstractAsyncContextManager[Any]:
    """One "Parallel downloads" slot for *owner* (an account id).

    Free slots go to the account running the fewest downloads, so one
    account's long playlist doesn't hold up everyone else's songs.
    """

    slots = state.download_semaphore
    if slots is None:
        return contextlib.nullcontext()
    return slots.slot(owner)


async def _queue_turn(
    song_id: str, job: dict[str, Any], song: dict[str, Any]
) -> bool:
    """Wait while the queue is paused; whether the job should still run.

    The paused job keeps its concurrency slot and shows as waiting again
    (a single download registers as ``downloading``). A job taken off
    the queue meanwhile (``DELETE /api/queue...``) is dropped here
    instead of started.
    """

    if queue_pause.paused:
        if job.get('status') != 'queued':
            job['status'] = 'queued'
            await state.connections.broadcast_job(
                _job_users(job),
                {
                    'song': song,
                    'progress': 0,
                    'message': '',
                    'status': 'queued',
                },
            )
        await queue_pause.wait()
    if state.download_jobs.get(song_id) is job:
        return True
    logger.info('Skipping download (removed from the queue): {}', song_id)
    return False


async def _run_download(
    song: dict[str, Any],
    song_id: str,
    subdir: Optional[str] = None,
    delay_seconds: float = 0,
    *,
    playlist_name: Optional[str] = None,
    spotify_playlist_id: Optional[str] = None,
    track_order: int = 0,
    refresh_playlists: bool = True,
    user_id: int = 0,
    pending_saved: bool = False,
) -> Optional[str]:
    """Run a single download to completion, updating jobs state and broadcasting WS events.

    The concurrency slot is acquired before the existing-file check and
    before the ``downloading`` broadcast, so a batch that starts every
    row at once cannot announce or look up all of them together. When
    *delay_seconds* is positive, that same slot stays held for that long
    after a successful download, so the next row can't start until the
    delay has elapsed. This is only meant for multi-song orchestration
    (playlist/album batches); single manual downloads should pass
    ``delay_seconds=0`` so a one-off download never waits around for
    nothing.

    With *Overwrite existing files* off, a song already in the library is
    not downloaded again: by its Spotify id in the track index (wherever it
    was saved, slskd folder included) or by its filename at the
    destination.

    A finished file is registered in the track index, the playlist catalog
    (for ``playlist_name``, at ``track_order``) and the caches. Unless
    ``refresh_playlists`` is off (a batch refreshes once at the end), the
    M3U/Navidrome playlists that contain the track are refreshed in the
    background.

    The job is saved (:class:`PendingDownloads`) until it ends, unless
    the caller already did (*pending_saved*): a shutdown mid-queue keeps
    it for the next start. A paused queue holds it before it starts
    (:func:`_queue_turn`).
    """

    if library_only.enabled(state.settings):
        raise HTTPException(status_code=409, detail=library_only.DETAIL)
    if state.downloader is None:
        raise RuntimeError('Downloader not ready')

    loop = state.loop or asyncio.get_running_loop()
    job = state.download_jobs.get(song_id)
    if job is None:
        song_id = _register_job(song, status='downloading', user_id=user_id)
        job = state.download_jobs[song_id]
    elif user_id:
        users = job.setdefault('user_ids', set())
        if isinstance(users, set):
            users.add(user_id)
        else:
            job['user_ids'] = _job_users(job) | {user_id}

    if not pending_saved:
        await _remember_pending([
            _pending_download(
                song,
                song_id,
                user_id=user_id,
                subdir=subdir,
                delay_seconds=delay_seconds,
                playlist_name=playlist_name,
                spotify_playlist_id=spotify_playlist_id,
                track_order=track_order,
            )
        ])

    # One download per track no matter how many accounts asked for it:
    # a second caller waits here, then shares the finished file (and
    # its ownership) instead of fetching the same bytes twice.
    lock = _download_locks.setdefault(song_id, asyncio.Lock())
    keep_pending = False
    try:
        async with lock:
            if job.get('status') == 'done' and job.get('filename'):
                sharers = _job_users(job)
                if sharers:
                    await asyncio.to_thread(
                        _note_download_owners,
                        job['filename'],
                        sharers,
                    )
                return job['filename']
            # YouTube's passing blocks get the song queued again for a
            # later try instead of an error the user has to retry.
            later = list(DEFERRED_RETRY_DELAYS_SECONDS)
            while True:
                try:
                    return await _run_download_locked(
                        song,
                        song_id,
                        job,
                        loop,
                        subdir=subdir,
                        delay_seconds=delay_seconds,
                        playlist_name=playlist_name,
                        spotify_playlist_id=spotify_playlist_id,
                        track_order=track_order,
                        refresh_playlists=refresh_playlists,
                        user_id=user_id,
                        retry_later=bool(later),
                    )
                except _RetryLater as retry:
                    wait = later.pop(0)
                    logger.warning(
                        'YouTube blocked {} ({}); trying again in {} s',
                        song_id,
                        retry.reason,
                        wait,
                    )
                    job.update(status='queued', progress=0, message='')
                    await state.connections.broadcast_job(
                        _job_users(job),
                        {
                            'song': song,
                            'progress': 0,
                            'message': '',
                            'status': 'queued',
                        },
                    )
                    await _sleep_before_retry(wait)
    except asyncio.CancelledError:
        # Shutting down mid-queue: the saved job stays, so the next
        # start downloads it again.
        keep_pending = True
        raise
    finally:
        if not lock.locked():
            _download_locks.pop(song_id, None)
        if not keep_pending:
            await _forget_pending([song_id])
            await _remember_finished(song_id, job)


#: Waits before trying a song YouTube blocked again (one per retry).
DEFERRED_RETRY_DELAYS_SECONDS = (30, 120, 600)


class _RetryLater(Exception):
    """A download hit a passing YouTube block: queue it again later."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason.splitlines()[0][:160] if reason else ''


async def _sleep_before_retry(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def _finish_with_existing(
    song: dict[str, Any], job: dict[str, Any], subdir: Optional[str]
) -> Optional[str]:
    """With *Overwrite existing files* off, end *job* with the song's
    copy already in the library - its stored path, or ``None``."""

    if getattr(state.downloader, 'overwrite_existing_files', True):
        return None
    existing_hit = await asyncio.to_thread(
        resolve_existing_download,
        state.downloader,
        song,
        subdir=subdir,
        track_index=state.track_index,
    )
    if not existing_hit:
        return None
    existing, skip_message = existing_hit
    logger.info(
        'Skipping download ({}): {}',
        skip_message.lower(),
        existing,
    )
    await asyncio.to_thread(
        record_download_outcome, song, OUTCOME_SKIPPED, existing
    )
    job.update(
        status='done',
        filename=existing,
        progress=100,
        message=skip_message,
    )
    sharers = _job_users(job)
    if sharers:
        # The file is shared, the ownership isn't: everyone waiting on
        # this job asked for it too.
        await asyncio.to_thread(_note_download_owners, existing, sharers)
    await _claim_pending_playlist_songs(song, existing)
    await state.connections.broadcast_job(
        _job_users(job),
        {
            'song': song,
            'progress': 100,
            'message': skip_message,
            'status': 'done',
            'filename': existing,
        },
    )
    return existing


async def _send_progress(job: dict[str, Any], message: dict[str, Any]) -> None:
    """Send a download's progress frame - unless the job ended first.

    The downloader's thread queues these; one still waiting when the
    ``done`` frame went out would put the row back to "downloading" at
    100 % on every page that got it.
    """

    if job.get('status') != 'downloading':
        return
    await state.connections.broadcast_job(_job_users(job), message)


async def _run_download_locked(
    song: dict[str, Any],
    song_id: str,
    job: dict[str, Any],
    loop: asyncio.AbstractEventLoop,
    *,
    subdir: Optional[str] = None,
    delay_seconds: float = 0,
    playlist_name: Optional[str] = None,
    spotify_playlist_id: Optional[str] = None,
    track_order: int = 0,
    refresh_playlists: bool = True,
    user_id: int = 0,
    retry_later: bool = False,
) -> Optional[str]:
    """Single execution of a download job, for one owner of the lock.

    With *retry_later*, a passing YouTube failure raises
    :class:`_RetryLater` (nothing broadcast) so the caller can queue the
    song again instead of showing an error.

    Shares the exact semantics the old ``_run_download`` body had: the
    concurrency slot is held across the existing-file check and the
    ``downloading`` broadcast, the post-download delay, and the
    skip-if-present path - except every broadcast and every ownership
    claim now covers all accounts waiting on the shared job, not just
    the caller that won the race to start it.
    """

    try:
        async with _download_slot(user_id):
            if not await _queue_turn(song_id, job, song):
                return None
            async with queue_pause.running():
                existing = await _finish_with_existing(song, job, subdir)
                if existing:
                    return existing

                job['status'] = 'downloading'

                await state.connections.broadcast_job(
                    _job_users(job),
                    {
                        'song': song,
                        'progress': 0,
                        'message': '',
                        'status': 'downloading',
                    },
                )

                def progress(
                    pct: float, message: str, provider: Optional[str] = None
                ) -> None:
                    j = state.download_jobs.get(song_id)
                    if j:
                        j['progress'] = pct
                        j['message'] = message
                        if provider:
                            j['provider'] = provider
                    asyncio.run_coroutine_threadsafe(
                        _send_progress(
                            job,
                            {
                                'song': song,
                                'progress': pct,
                                'message': message,
                                'provider': provider
                                or (j or {}).get('provider', ''),
                                'status': 'downloading',
                            },
                        ),
                        loop,
                    )

                filename = await loop.run_in_executor(
                    DOWNLOAD_EXECUTOR,
                    lambda: state.downloader.download(
                        song, progress, subdir=subdir
                    ),
                )
                job['status'] = 'done'
                job['filename'] = filename
                job['progress'] = 100
                if filename:
                    await _record_finished_download(
                        song,
                        filename,
                        playlist_name=playlist_name,
                        spotify_playlist_id=spotify_playlist_id,
                        track_order=track_order,
                        refresh_playlists=refresh_playlists,
                        user_id=user_id,
                    )
                    others = _job_users(job) - (
                        {user_id} if user_id else set()
                    )
                    if others:
                        # The leader is recorded inside
                        # _record_finished_download; everyone else waiting
                        # on the shared job claims the same file too.
                        await asyncio.to_thread(
                            _note_download_owners, filename, others
                        )
                invalidate_library_paths_cache()
                await state.connections.broadcast_job(
                    _job_users(job),
                    {
                        'song': song,
                        'progress': 100,
                        'message': 'Done',
                        'status': 'done',
                        'filename': filename,
                    },
                )
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
    except Exception as exc:
        if (
            retry_later
            and not isinstance(exc, (NoAudioMatchError, TrackTooLongError))
            and is_youtube_hiccup(str(exc))
        ):
            raise _RetryLater(str(exc)) from exc
        if isinstance(exc, (NoAudioMatchError, TrackTooLongError)):
            # An expected outcome, not a crash: no traceback in the log.
            logger.warning('{} ({})', exc, song_id)
            message = str(exc)
        else:
            logger.exception('Download failed for {}', song_id)
            message = f'Error: {exc}'
        job['status'] = 'error'
        job['message'] = message
        await state.connections.broadcast_job(
            _job_users(job),
            {
                'song': song,
                'progress': 0,
                'message': message,
                'status': 'error',
            },
        )
        raise
    return filename


async def _record_finished_download(
    song: dict[str, Any],
    filename: str,
    *,
    playlist_name: Optional[str],
    spotify_playlist_id: Optional[str],
    track_order: int,
    refresh_playlists: bool,
    user_id: int = 0,
) -> None:
    """Register a downloaded file in the library stores (best effort)."""

    downloader = state.downloader
    if downloader is None:
        return

    def _record() -> set[str]:
        # Ownership first, and every step isolated: a hiccup in one
        # store (a locked sqlite under parallel downloads) must never
        # hide a finished download from the account that ordered it,
        # or from the library listing. Claiming is best-effort itself
        # and never raises.
        _note_download_owner(filename, user_id)
        try:
            affected = _register_download_playlists_on_disk(
                song,
                filename,
                playlist_name=playlist_name,
                spotify_playlist_id=spotify_playlist_id,
                track_order=track_order,
                user_id=user_id,
            )
        except Exception:
            logger.exception('Playlist bookkeeping failed for {}', filename)
            affected = set()
        _record_download_traffic(filename, user_id)
        download_dir = Path(downloader.download_dir)
        slskd_dir = slskd_dir_from_downloader(downloader)
        if state.navidrome_index is not None:
            cache_navidrome_song_id(
                state.settings,
                song,
                filename,
                state.navidrome_index,
                download_dir=download_dir,
                slskd_dir=slskd_dir,
            )
        if state.metadata_cache is not None:
            state.metadata_cache.refresh_stored_path(
                filename, download_dir=download_dir, slskd_dir=slskd_dir
            )
        merge_library_listing_file(library_context(), filename)
        if state.settings.get('cache_cover_art') and state.cover_cache:
            state.cover_cache.refresh_stored_path(
                filename, download_dir=download_dir, slskd_dir=slskd_dir
            )
        return affected

    try:
        affected = await asyncio.to_thread(_record)
    except Exception:
        logger.exception('Could not register {} in the library', filename)
        return
    await _claim_pending_playlist_songs(song, filename)
    if refresh_playlists and affected:
        await _schedule_playlist_refresh_after_download(affected)


def hidden_songs_for(name: str) -> HiddenSongs:
    """The songs the owner hid from playlist *name* (see
    :mod:`downtify.playlist_hidden`) - empty when none, or on error."""

    store = state.playlist_hidden
    if store is None or not name:
        return HiddenSongs()
    try:
        return store.songs(name)
    except Exception:
        logger.opt(exception=True).warning(
            'Could not read the hidden songs of {!r}', name
        )
        return HiddenSongs()


def hidden_from_playlist(
    playlist_name: str, song: dict[str, Any], filename: str
) -> bool:
    """Whether the owner hid *song* (downloaded as *filename*) from
    playlist *playlist_name* - then it is never linked to it again."""

    hidden = hidden_songs_for(playlist_name)
    return hidden.hides_song(song) or hidden.hides_file(filename)


def _m3u_entries_for(
    songs: list[dict[str, Any]],
    resolved: dict[int, Optional[str]],
    hidden: HiddenSongs = HiddenSongs(),
) -> list[dict[str, Any]]:
    """Build M3U entries for the songs downloaded so far.

    Iterates ``songs`` in playlist order (not completion order, which
    varies with concurrency) and keeps only those with a filename in
    ``resolved``, so a partially-finished batch still produces a
    correctly-ordered file. Songs *hidden* from the playlist stay out
    of it even when downloaded again from its link.
    """
    entries: list[dict[str, Any]] = []
    for index, song in enumerate(songs):
        filename = resolved.get(index)
        if not filename:
            continue
        if hidden.hides_song(song) or hidden.hides_file(filename):
            continue
        entries.append({
            'filename': filename,
            'title': song.get('name') or '',
            'artist': ', '.join(song.get('artists') or []),
            'duration': song.get('duration') or 0,
        })
    return entries


async def _write_batch_m3u(
    songs: list[dict[str, Any]],
    resolved: dict[int, Optional[str]],
    playlist_name: str,
    playlist_subdir: str,
) -> Optional[Path]:
    entries = _m3u_entries_for(
        songs, resolved, hidden_songs_for(playlist_name)
    )
    if not entries:
        return None
    # When organize-by-artist/album is on, songs land in those folders
    # instead of the playlist subfolder, so the M3U must go to the legacy
    # Playlists/ directory (playlist_subdir=None) where relative paths
    # still resolve.
    organize = _organize_enabled()
    try:
        m3u_path, _kept = await asyncio.to_thread(
            m3u.write_m3u,
            state.downloader.download_dir,
            playlist_name,
            entries,
            playlist_subdir=None if organize else playlist_subdir,
            slskd_dir=slskd_dir_from_downloader(state.downloader),
        )
    except Exception:
        logger.exception('Failed to write M3U for {!r}', playlist_name)
        return None
    return m3u_path


def _download_playlist_cover_for_batch(
    source: str,
    playlist_id: str,
    m3u_path: Path,
    settings: dict[str, Any],
) -> Optional[Path]:
    """Save a downloaded playlist's cover art beside its M3U, when enabled
    (any service :func:`parse_playlist_url` knows, Deezer included). A
    cover that can't be saved is logged: the download itself succeeded."""

    try:
        return download_playlist_cover(source, playlist_id, m3u_path, settings)
    except Exception:
        logger.exception('Failed to save cover art for {}', m3u_path)
        return None


def _save_explicit_playlist_cover(
    cover_url: str, m3u_path: Path, settings: dict[str, Any]
) -> None:
    """Save *cover_url* beside *m3u_path*, when enabled.

    Counterpart to :func:`download_playlist_cover` for a batch that isn't
    backed by a real Spotify/YouTube Music playlist id (e.g. an artist's
    top songs) - the caller already knows the cover to use, so there's no
    playlist to re-fetch it from. Gated by the same
    ``download_cover_art_playlists`` setting.
    """

    if not settings.get('download_cover_art_playlists'):
        return
    try:
        save_playlist_cover(cover_url, m3u_path)
    except Exception:
        logger.exception('Failed to save cover art for {}', m3u_path)


async def _fetch_playlist_cover(
    target: Optional[tuple[str, str]],
    playlist_name: Optional[str],
    playlist_subdir: Optional[str],
    cover_url: Optional[str] = None,
) -> None:
    """Save the playlist's own cover art beside where its M3U will go.

    Resolving the M3U path without writing it (see ``m3u.m3u_path_for``)
    means the cover can land before the first track does. No-ops when
    the setting is off, or when the download didn't come from a
    playlist link (unless the caller passed an explicit ``cover_url``).
    """

    if (
        (target is None and not cover_url)
        or not playlist_name
        or state.downloader is None
    ):
        return
    # With organize-by-artist/album on, tracks are spread across those
    # folders and the M3U goes to the legacy Playlists/ directory — the
    # cover follows it, so both stay together.
    subdir = None if _organize_enabled() else playlist_subdir
    m3u_path = m3u.m3u_path_for(
        Path(state.downloader.download_dir),
        playlist_name,
        playlist_subdir=subdir,
    )
    if target is not None:
        await asyncio.to_thread(
            _download_playlist_cover_for_batch,
            *target,
            m3u_path,
            state.settings,
        )
    else:
        await asyncio.to_thread(
            _save_explicit_playlist_cover,
            cover_url,
            m3u_path,
            state.settings,
        )


async def _process_batch(
    songs: list[dict[str, Any]],
    job_ids: list[str],
    playlist_url: str,
    generate_m3u: bool,
    playlist_name: Optional[str] = None,
    *,
    batch_id: Optional[int] = None,
    cover_url: Optional[str] = None,
    user_id: int = 0,
) -> None:
    # Resolve the playlist name up-front so all tracks land in a single,
    # per-playlist sub-folder. Loose batches (e.g. albums or unrelated
    # tracks) keep the legacy flat layout under download_dir. A caller
    # without a Spotify/YouTube Music/Deezer playlist_url (e.g. a CSV
    # library import) can instead pass playlist_name directly.
    playlist_subdir: Optional[str] = None
    spotify_playlist_id: Optional[str] = None
    spotify_track_count = 0
    target = parse_playlist_url(playlist_url) if playlist_url else None
    if target is not None:
        try:
            playlist_name, tracks = await asyncio.to_thread(
                fetch_playlist, *target
            )
            playlist_subdir = m3u.sanitize_playlist_name(playlist_name)
            if target[0] == SOURCE_SPOTIFY:
                spotify_playlist_id = target[1]
                spotify_track_count = len(tracks)
                # Fresh Spotify track list for the playlist batch reports.
                if state.playlist_spotify_cache is not None:
                    await asyncio.to_thread(
                        state.playlist_spotify_cache.store,
                        spotify_playlist_id,
                        playlist_name,
                        tracks,
                    )
        except Exception:
            logger.exception(
                'Failed to resolve playlist name for {}', playlist_url
            )
    elif playlist_name:
        playlist_subdir = m3u.sanitize_playlist_name(playlist_name)

    if batch_id is not None and playlist_name and state.playlist_batch_store:
        await asyncio.to_thread(
            state.playlist_batch_store.update_batch_name,
            batch_id,
            playlist_name,
        )

    # A per-song delay only makes sense when there's a "next" song to
    # wait for; skip it entirely for a lone track so a single download
    # never waits around for nothing.
    delay_seconds = (
        state.settings.get('download_delay_seconds', 0)
        if len(songs) > 1
        else 0
    )

    wants_m3u = bool(generate_m3u and playlist_subdir and playlist_name)
    if wants_m3u:
        # Before the first track, so the folder already looks like the
        # playlist while it fills up (and a media server scanning
        # mid-download finds the artwork).
        await _fetch_playlist_cover(
            target, playlist_name, playlist_subdir, cover_url
        )
    # Filename per song index, filled in as downloads land. The M3U is
    # rewritten from this after every completed download, so the playlist
    # grows as it downloads instead of appearing all at once at the end,
    # and one slow or hung track can't hold up what's already on disk.
    resolved: dict[int, Optional[str]] = {}
    m3u_lock = asyncio.Lock()

    def _order(index: int, song: dict[str, Any]) -> int:
        return int(song.get('downtify_track_order') or index)

    # One write for the whole batch, so a restart picks it back up.
    await _remember_pending([
        _pending_download(
            song,
            song_id,
            user_id=user_id,
            subdir=playlist_subdir,
            delay_seconds=delay_seconds,
            playlist_name=playlist_name,
            spotify_playlist_id=spotify_playlist_id,
            track_order=_order(index, song),
        )
        for index, (song, song_id) in enumerate(zip(songs, job_ids))
    ])

    async def _bounded(index: int, song: dict[str, Any], song_id: str) -> None:
        try:
            await _download_one(index, song, song_id)
        finally:
            progress.finished()

    async def _download_one(
        index: int, song: dict[str, Any], song_id: str
    ) -> None:
        try:
            filename = await _run_download(
                song,
                song_id,
                subdir=playlist_subdir,
                delay_seconds=delay_seconds,
                playlist_name=playlist_name,
                spotify_playlist_id=spotify_playlist_id,
                track_order=_order(index, song),
                refresh_playlists=False,
                user_id=user_id,
                pending_saved=True,
            )
        except Exception:
            filename = None
        resolved[index] = filename
        if not (filename and wants_m3u):
            return
        # Serialized so concurrent downloads can't interleave writes to
        # the same file.
        async with m3u_lock:
            await _write_batch_m3u(
                songs, resolved, playlist_name, playlist_subdir
            )

    async with _searching_ahead(songs, playlist_subdir) as progress:
        await asyncio.gather(
            *[
                _bounded(i, s, sid)
                for i, (s, sid) in enumerate(zip(songs, job_ids))
            ],
            return_exceptions=False,
        )

    if wants_m3u:
        await _write_batch_m3u(songs, resolved, playlist_name, playlist_subdir)

    await _finish_playlist_batch(
        songs,
        resolved,
        batch_id=batch_id,
        playlist_name=playlist_name,
        spotify_playlist_id=spotify_playlist_id,
        spotify_track_count=spotify_track_count,
        generate_m3u=generate_m3u,
    )


async def _finish_playlist_batch(
    songs: list[dict[str, Any]],
    resolved: dict[int, Optional[str]],
    *,
    batch_id: Optional[int],
    playlist_name: Optional[str],
    spotify_playlist_id: Optional[str],
    spotify_track_count: int,
    generate_m3u: bool,
) -> None:
    """Close a playlist batch: record its outcome, relink the playlist's
    on-disk tracks in the catalog and refresh its M3U/Navidrome playlist.

    A batch can cover only part of a Spotify playlist (e.g. downloading
    just the missing tracks), so the catalog is rebuilt from every track
    of the playlist already in the library before the refresh — otherwise
    the refreshed playlist would only contain this batch's tracks.
    """

    succeeded = sum(1 for filename in resolved.values() if filename)
    failed = len(songs) - succeeded
    if playlist_name:
        logger.info(
            'playlist batch: name={!r} downloaded={}/{} failed={}',
            playlist_name,
            succeeded,
            len(songs),
            failed,
        )
    if batch_id is not None and state.playlist_batch_store is not None:
        await asyncio.to_thread(
            state.playlist_batch_store.finish_batch,
            batch_id,
            succeeded,
            failed,
            status='complete' if failed == 0 else 'incomplete',
        )
    if not playlist_name or state.playlist_catalog is None:
        return
    if spotify_track_count and len(songs) < spotify_track_count:
        logger.info(
            'playlist batch: partial run {}/{} tracks for {!r}; rebuilding '
            'the catalog from the library before the playlist refresh',
            len(songs),
            spotify_track_count,
            playlist_name,
        )

    def _catalog_batch() -> None:
        catalog = state.playlist_catalog
        downloader = state.downloader
        if catalog is None or downloader is None:
            return
        download_dir = Path(downloader.download_dir)
        slskd_dir = slskd_dir_from_downloader(downloader)
        if spotify_playlist_id:
            catalog.ensure_playlist(
                playlist_name, spotify_id=spotify_playlist_id
            )
        for index, song in enumerate(songs):
            filename = resolved.get(index)
            full = (
                locate_library_file(filename, download_dir, slskd_dir)
                if filename
                else None
            )
            if full is None or hidden_from_playlist(
                playlist_name, song, filename
            ):
                continue
            catalog.upsert_track(
                playlist_name,
                song,
                filename,
                full,
                track_order=int(song.get('downtify_track_order') or index),
            )
        if spotify_playlist_id:
            linked = _rebuild_playlist_catalog_from_library(
                playlist_name, spotify_playlist_id
            )
            logger.info(
                'playlist batch: catalog has {} on-disk track(s) for {!r}',
                linked,
                playlist_name,
            )

    await asyncio.to_thread(_catalog_batch)

    do_m3u, do_navidrome = playlist_refresh_enabled(state.settings)
    if not generate_m3u:
        do_m3u = False
    if do_m3u or do_navidrome:
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
                _effective_navidrome_settings(state.settings).get(
                    'scan_after_download', True
                )
            ),
            playlist_spotify_cache=state.playlist_spotify_cache,
            cover_cache=state.cover_cache,
            metadata_cache=state.metadata_cache,
        )


def _rebuild_playlist_catalog_from_library(
    playlist_name: str,
    spotify_playlist_id: str,
) -> int:
    """Link every on-disk Spotify playlist track into the catalog (upsert)."""

    if (
        state.playlist_catalog is None
        or state.downloader is None
        or state.track_index is None
    ):
        return 0
    sid = str(spotify_playlist_id or '').strip()
    if not sid:
        return 0
    try:
        resolved_name, tracks = _fetch_playlist_tracks(sid)
    except Exception:
        logger.opt(exception=True).warning(
            'playlist batch: catalog rebuild failed for {!r}',
            playlist_name,
        )
        return 0
    pl_name = str(resolved_name or playlist_name or '').strip()
    if not pl_name:
        return 0

    subdir = _playlist_subdir_for_name(pl_name)
    catalog_filenames = _catalog_filenames_for_playlist(pl_name, sid)
    dl_dir = Path(state.downloader.download_dir)
    slskd = slskd_dir_from_downloader(state.downloader)
    state.playlist_catalog.ensure_playlist(pl_name, spotify_id=sid)

    linked = 0
    for index, track in enumerate(tracks):
        filename: Optional[str] = None
        full: Optional[Path] = None
        hit = resolve_existing_download(
            state.downloader,
            track,
            subdir=subdir,
            track_index=state.track_index,
        )
        if hit:
            filename = hit[0]
            full = locate_library_file(filename, dl_dir, slskd)
        else:
            tid = normalize_spotify_track_id(track)
            if tid and catalog_filenames:
                filename = str(catalog_filenames.get(tid) or '').strip()
                if filename:
                    full = locate_library_file(filename, dl_dir, slskd)
        if (
            filename
            and full is not None
            and not hidden_from_playlist(pl_name, track, filename)
        ):
            state.playlist_catalog.upsert_track(
                pl_name, track, filename, full, track_order=index
            )
            linked += 1
    return linked


def _playlist_subdir_for_name(playlist_name: str) -> str:
    return m3u.sanitize_playlist_name(playlist_name)


def _catalog_filenames_for_playlist(
    playlist_name: str,
    spotify_playlist_id: str,
) -> dict[str, str]:
    """Map Spotify track id to on-disk filename from the playlist catalog."""

    if state.playlist_catalog is None:
        return {}
    sid = str(spotify_playlist_id or '').strip()
    names: list[str] = []
    if str(playlist_name or '').strip():
        names.append(str(playlist_name).strip())
    for row in state.playlist_catalog.list_playlists_with_spotify_id():
        if sid and row['spotify_id'] != sid:
            continue
        name = str(row['name'] or '').strip()
        if name and name not in names:
            names.append(name)
    by_tid: dict[str, str] = {}
    for name in names:
        for row in state.playlist_catalog.list_tracks(name):
            tid = str(row.get('track_spotify_id') or '').strip()
            filename = str(row.get('filename') or '').strip()
            if tid and filename:
                by_tid[tid] = filename
    return by_tid


def _is_spotify_playlist_watch(watch: MonitoredPlaylist) -> bool:
    """Whether *watch* follows a Spotify playlist.

    A watch's ``spotify_id`` column holds whatever it follows: a YouTube
    Music playlist id, an artist's channel id or a podcast's id. Only a
    Spotify playlist's id may be looked up on Spotify (the playlist cache
    does that in the background); anything else only fills the log with
    "Spotify entity not found" errors.
    """

    return (
        watch.kind == KIND_PLAYLIST
        and watch.source == SOURCE_SPOTIFY
        and bool(str(watch.spotify_id or '').strip())
    )


def _known_spotify_playlist_sources(
    user_id: Optional[int] = None,
) -> dict[str, dict[str, Any]]:
    """Merge Spotify playlist ids from batch store, catalog, and monitor.

    With *user_id*: only their batches and playlists (monitor watches
    are the admin's). Without it: everything.
    """

    sources: dict[str, dict[str, Any]] = {}
    if state.playlist_batch_store is not None:
        for batch in state.playlist_batch_store.list_latest_batches(user_id):
            sid = str(batch['spotify_playlist_id'] or '').strip()
            if not sid:
                continue
            sources[sid] = {
                'playlist_name': batch['playlist_name'],
                'playlist_url': batch['playlist_url'],
                'expected_hint': int(batch.get('expected_count') or 0),
                'batch': batch,
            }
    if state.playlist_catalog is not None:
        owners: dict[str, int] = {}
        if user_id is not None and state.playlist_catalog is not None:
            try:
                owners = {
                    str(name or '').strip().casefold(): int(uid or 0)
                    for name, uid in state.playlist_catalog.playlist_owner_map().items()
                }
            except Exception:
                logger.opt(exception=True).debug(
                    'Could not read playlist owners'
                )
        for row in state.playlist_catalog.list_playlists_with_spotify_id():
            sid = str(row['spotify_id'] or '').strip()
            if not sid:
                continue
            if (
                user_id is not None
                and owners.get(str(row['name'] or '').strip().casefold(), 0)
                != user_id
            ):
                continue
            if sid not in sources:
                sources[sid] = {
                    'playlist_name': row['name'],
                    'playlist_url': f'https://open.spotify.com/playlist/{sid}',
                    'expected_hint': int(row.get('track_count') or 0),
                    'batch': None,
                }
            else:
                entry = sources[sid]
                if not entry.get('playlist_name'):
                    entry['playlist_name'] = row['name']
                if int(row.get('track_count') or 0) > int(
                    entry.get('expected_hint') or 0
                ):
                    entry['expected_hint'] = int(row['track_count'])
        monitor_by_name: dict[str, Any] = {}
        if state.monitor_db is not None and user_id is None:
            for pl in state.monitor_db.list_playlists():
                name = str(pl.name or '').strip()
                if name:
                    monitor_by_name[name] = pl
        batch_by_name: dict[str, dict[str, Any]] = {}
        if state.playlist_batch_store is not None:
            for batch in state.playlist_batch_store.list_latest_batches(
                user_id
            ):
                name = str(batch.get('playlist_name') or '').strip()
                if name:
                    batch_by_name[name] = batch
        for name in state.playlist_catalog.list_playlist_names():
            if (
                user_id is not None
                and owners.get(name.strip().casefold(), 0) != user_id
            ):
                continue
            sid = state.playlist_catalog.spotify_id_for_playlist(name) or ''
            if not sid:
                mon = monitor_by_name.get(name)
                if mon and _is_spotify_playlist_watch(mon):
                    sid = str(mon.spotify_id).strip()
                else:
                    batch = batch_by_name.get(name)
                    if batch:
                        sid = str(batch['spotify_playlist_id']).strip()
            if not sid or sid in sources:
                continue
            track_count = len(state.playlist_catalog.list_tracks(name))
            sources[sid] = {
                'playlist_name': name,
                'playlist_url': f'https://open.spotify.com/playlist/{sid}',
                'expected_hint': track_count,
                'batch': batch_by_name.get(name),
            }
    if state.monitor_db is not None and user_id is None:
        for pl in state.monitor_db.list_playlists():
            if not _is_spotify_playlist_watch(pl):
                continue
            sid = str(pl.spotify_id or '').strip()
            if not sid:
                continue
            if sid not in sources:
                sources[sid] = {
                    'playlist_name': pl.name,
                    'playlist_url': pl.url,
                    'expected_hint': int(pl.last_track_count or 0),
                    'batch': None,
                }
            else:
                entry = sources[sid]
                if pl.name and (
                    not entry.get('playlist_name')
                    or entry['playlist_name'] == sid
                ):
                    entry['playlist_name'] = pl.name
                if pl.url:
                    entry['playlist_url'] = pl.url
    return sources


def known_spotify_playlist_ids() -> list[str]:
    """Spotify playlist ids tracked by batches, catalog, and monitor."""

    return list(_known_spotify_playlist_sources().keys())


def collect_playlist_batch_sync_rows() -> list[dict[str, Any]]:
    """Playlist rows for startup batch registration."""

    rows: list[dict[str, Any]] = []
    for sid, meta in _known_spotify_playlist_sources().items():
        rows.append({
            'spotify_id': sid,
            'name': str(meta.get('playlist_name') or sid),
            'url': str(
                meta.get('playlist_url')
                or f'https://open.spotify.com/playlist/{sid}'
            ),
            'track_count': int(meta.get('expected_hint') or 0),
        })
    return rows


async def _submit_playlist_batch(
    songs: list[dict[str, Any]],
    playlist_url: str,
    *,
    generate_m3u: bool,
    batch_id: Optional[int] = None,
    playlist_name: Optional[str] = None,
    cover_url: Optional[str] = None,
    user_id: int = 0,
) -> dict[str, Any]:
    valid_songs: list[dict[str, Any]] = []
    job_ids: list[str] = []
    for song in songs:
        if not isinstance(song, dict):
            continue
        song_id = _register_job(song, status='queued', user_id=user_id)
        valid_songs.append(song)
        job_ids.append(song_id)

    if not valid_songs:
        raise HTTPException(status_code=400, detail='No valid songs in batch')

    # One frame for the whole batch. Per-row ``queued`` events made a
    # large playlist or CSV rebuild the queue once per track.
    await state.connections.broadcast({'type': 'queue_reload'})

    task = spawn_task(
        _process_batch(
            valid_songs,
            job_ids,
            playlist_url,
            generate_m3u,
            playlist_name,
            batch_id=batch_id,
            cover_url=cover_url,
            user_id=user_id,
        ),
        name='playlist-batch',
    )

    def _log_batch_failure(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.opt(exception=exc).error('Batch processing crashed')

    task.add_done_callback(_log_batch_failure)
    return {'job_ids': job_ids, 'count': len(job_ids)}


def _unmap_extra_roots(
    roots: list[Path], settings_for_dirs: dict[str, Any]
) -> dict[str, Any]:
    download_dir = (
        Path(state.downloader.download_dir)
        if state.downloader is not None
        else Path('/downloads')
    )
    slskd_dir = (
        slskd_dir_from_downloader(state.downloader)
        if state.downloader is not None
        else None
    )
    extra = extra_dirs_from_settings(
        settings_for_dirs, download_dir, slskd_dir
    )
    unmapped = 0
    folder_ids: list[str] = []
    for root in roots:
        info = unmap_extra_folder(
            root,
            download_dir=download_dir,
            slskd_dir=slskd_dir,
            extra_dirs=extra,
            cover_cache=state.cover_cache,
            metadata_cache=state.metadata_cache,
            playlist_catalog=state.playlist_catalog,
            track_index=state.track_index,
            likes=state.likes,
            navidrome_index=state.navidrome_index,
        )
        unmapped += int(info.get('unmapped') or 0)
        folder_ids.append(str(info.get('folder_id') or ''))
    return {'unmapped': unmapped, 'folder_ids': folder_ids}


def _unmap_removed_extra_folders(
    before: dict[str, Any], after: dict[str, Any]
) -> None:
    roots = folders_removed(before, after)
    if roots:
        _unmap_extra_roots(roots, before)


# ---------------------------------------------------------------------------
# Marking an album as a various-artists compilation by hand
# ---------------------------------------------------------------------------


def album_override_for(song: dict[str, Any]) -> dict[str, Any]:
    """What an admin set by hand for *song*'s album (see
    ``compilation.CompilationMarks``) - the downloader's
    ``album_override``."""

    marks = state.compilation_marks
    return marks.override_for(song) if marks is not None else {}


def broadcast_upgrade_progress(status: dict[str, Any]) -> None:
    """Push upgrade progress to connected clients from the worker thread."""

    loop = state.loop
    if loop is None:
        return
    asyncio.run_coroutine_threadsafe(
        state.connections.broadcast({
            'type': 'library_upgrade',
            'upgrade': status,
        }),
        loop,
    )


async def _schedule_playlist_refresh_after_delete(
    playlist_names: set[str],
) -> None:
    if not playlist_names or state.downloader is None:
        return
    if state.playlist_catalog is None:
        return

    async def _run() -> None:
        logger.info(
            'Library delete: scheduling M3U/Navidrome refresh for {}',
            ', '.join(sorted(playlist_names)[:8])
            + ('; ...' if len(playlist_names) > 8 else ''),
        )
        try:
            await asyncio.to_thread(
                refresh_playlists_after_moves,
                playlist_names,
                settings=state.settings,
                downloader=state.downloader,
                playlist_catalog=state.playlist_catalog,
                track_index=state.track_index,
                monitor_db=state.monitor_db,
                navidrome_index=state.navidrome_index,
                playlist_spotify_cache=state.playlist_spotify_cache,
                cover_cache=state.cover_cache,
                metadata_cache=state.metadata_cache,
            )
        except Exception:
            logger.exception(
                'library delete: background playlist refresh failed for {}',
                ', '.join(sorted(playlist_names)[:5]),
            )

    spawn_task(_run(), name='playlist-refresh-after-delete')


async def announce_playlists_changed() -> None:
    """Tell connected clients playlists were shared, followed, copied,
    detached, renamed or deleted, so they list them again."""

    await state.connections.broadcast({'type': 'playlists_changed'})


def _global_queue_status() -> dict[str, Any]:
    status = queue_pause.status()
    runner = state.upgrade_runner
    if status['paused'] and runner is not None and runner.busy():
        status['active'] += 1
        status['state'] = 'pausing'
    return status


async def restore_download_queue() -> int:
    """Pick the saved queue back up after a restart; how many jobs.

    The pause switch comes back first, so a queue paused before an
    update stays paused. Jobs run with today's settings and provider
    order. Each playlist's M3U/Navidrome playlist is refreshed once its
    rows are done (as a batch does), loose songs one by one. Nothing is
    started in library-only mode: the rows wait for a later start.
    """

    store = state.pending_downloads
    if store is None:
        return 0
    if await asyncio.to_thread(store.paused):
        queue_pause.pause()
    rows = await asyncio.to_thread(store.rows)
    if not rows or state.downloader is None:
        return 0
    if library_only.enabled(state.settings):
        logger.info(
            'Library-only mode: {} saved download(s) left for later',
            len(rows),
        )
        return 0
    for row in rows:
        song = row.song
        if not (song.get('song_id') or song.get('url')):
            song['song_id'] = row.song_id
        for uid in row.user_ids or [0]:
            _register_job(song, status='queued', user_id=uid)
    logger.info(
        'Download queue: {} unfinished job(s) restored{}',
        len(rows),
        ' (paused)' if queue_pause.paused else '',
    )
    spawn_task(_run_restored_queue(rows), name='queue-restore')
    return len(rows)


async def _run_restored_queue(rows: list[PendingDownload]) -> None:
    groups: dict[str, list[PendingDownload]] = {}
    for row in rows:
        name = str(row.options.get('playlist_name') or '')
        groups.setdefault(name, []).append(row)
    await asyncio.gather(
        *(_run_restored_group(name, group) for name, group in groups.items())
    )


async def _run_restored_group(
    playlist_name: str, rows: list[PendingDownload]
) -> None:
    async def _one(row: PendingDownload) -> Optional[str]:
        options = row.options
        try:
            return await _run_download(
                row.song,
                row.song_id,
                subdir=options.get('subdir') or None,
                delay_seconds=float(options.get('delay_seconds') or 0),
                playlist_name=playlist_name or None,
                spotify_playlist_id=options.get('spotify_playlist_id') or None,
                track_order=int(options.get('track_order') or 0),
                refresh_playlists=not playlist_name,
                user_id=row.user_ids[0] if row.user_ids else 0,
                pending_saved=True,
            )
        except Exception:
            # Already marked failed on the queue (and logged).
            return None

    results = await asyncio.gather(*(_one(row) for row in rows))
    if playlist_name and any(results):
        await _schedule_playlist_refresh_after_download({playlist_name})


async def _json_object(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


# ---------------------------------------------------------------------------
# Liked songs
# ---------------------------------------------------------------------------


def _require_likes() -> LikedTracks:
    if state.likes is None:
        raise HTTPException(status_code=500, detail='Likes not ready')
    return state.likes


def _admin_like_scope() -> set[int]:
    """Whose likes the shared playlist file holds: every admin's, plus
    pre-feature rows (``user_id`` ``0``, made when likes belonged to
    whoever ran the single-user server)."""

    ids = {0}
    try:
        users = state.auth.users if state.auth is not None else None
        for user in users.list() if users is not None else []:
            if user.get('role') == 'admin':
                ids.add(int(user['id']))
    except Exception:
        logger.opt(exception=True).debug('Could not resolve the admin set')
    return ids


def _sync_liked_playlist() -> None:
    """Rewrite (or remove) the liked songs playlist to match the likes."""

    if state.likes is None or state.downloader is None:
        return
    ctx = library_context()
    try:
        sync_liked_playlist(
            state.likes,
            ctx.download_dir,
            ctx.slskd_dir,
            ctx.extra_dirs,
            user_ids=_admin_like_scope(),
        )
    except Exception:
        logger.exception('Liked songs playlist sync failed')


_LIBRARY_ANNOUNCE_DELAY = 2.0

# The pending "library changed" broadcast, if one is scheduled.
_library_announce: dict[str, Optional[asyncio.TimerHandle]] = {'timer': None}


def _broadcast_library_changed() -> None:
    _library_announce['timer'] = None
    spawn_task(
        state.connections.broadcast({'type': 'library_changed'}),
        name='library-changed',
    )


def _schedule_library_changed() -> None:
    loop = state.loop
    if loop is None or _library_announce['timer'] is not None:
        return
    _library_announce['timer'] = loop.call_later(
        _LIBRARY_ANNOUNCE_DELAY, _broadcast_library_changed
    )


def announce_library_changed() -> None:
    """Tell connected clients (the apps) the library changed, so they
    sync - at most once every couple of seconds, however many files a
    batch download adds. Safe from any thread."""

    loop = state.loop
    if loop is None:
        return
    loop.call_soon_threadsafe(_schedule_library_changed)


add_invalidation_listener(announce_library_changed)


def _announce_likes() -> None:
    """Tell open pages the likes changed, from any thread."""

    loop = state.loop
    if loop is None or state.likes is None:
        return
    asyncio.run_coroutine_threadsafe(
        state.connections.broadcast({
            'type': 'likes',
            'count': state.likes.count(),
        }),
        loop,
    )


def _clear_likes(user_id: Optional[int] = None) -> int:
    likes = _require_likes()
    cleared = likes.clear(user_id)
    _sync_liked_playlist()
    _announce_likes()
    return cleared


def likes_scope(request: Request) -> Optional[int]:
    """Whose likes *request* sees: ``None`` (everyone's) for an admin."""

    return None if request_is_admin(request) else request_user_id(request)


# ── Discover ─────────────────────────────────────────────────────────
def _require_discover() -> DiscoverStore:
    if state.discover is None:
        raise HTTPException(status_code=500, detail='Discover store not ready')
    return state.discover


#: How often the library's size is noted (the day's last reading stays).
USAGE_SNAPSHOT_INTERVAL = 3600

#: The first reading waits for the library listing to be warm.
USAGE_SNAPSHOT_FIRST_DELAY = 300


def _usage_library_inputs(ctx: LibraryContext) -> dict[str, Any]:
    """The listing and what is known of its files, for
    :func:`downtify.library_usage.usage_report` /
    :func:`~downtify.library_usage.library_snapshot`."""

    entries = listing_for_request(ctx)
    keys = {norm_path(e.get('file')): entry_content_key(e) for e in entries}
    keys.pop('', None)
    store = state.file_providers
    recorded = store.recorded(keys) if store is not None else {}
    referenced = set(recorded)
    if state.track_index is not None:
        referenced.update(state.track_index.list_filenames())
    return {
        'entries': entries,
        'providers': {path: row['provider'] for path, row in recorded.items()},
        'recorded': {
            path: row['recorded_at'] for path, row in recorded.items()
        },
        'sources': _working_sources(ctx),
        'slskd_in_place': bool(
            _effective_slskd_settings(state.settings)['leave_in_place']
        ),
        'referenced': referenced,
    }


def _working_sources(ctx: LibraryContext) -> dict[str, int]:
    """``{library path: size}`` of the slskd transfers copied into the
    library and still on disk."""

    store = state.file_providers
    found: dict[str, int] = {}
    for raw in store.sources() if store is not None else []:
        path = Path(raw)
        try:
            if not path.is_file():
                continue
            size = path.stat().st_size
        except OSError:
            continue
        stored = library_stored_path(
            path, ctx.download_dir, ctx.slskd_dir, ctx.extra_dirs
        )
        found[stored] = size
    return found


def take_usage_snapshot() -> None:
    """Note the library's size for today, and drop download log rows
    older than :data:`downtify.download_log.RETENTION_DAYS`."""

    if state.usage_snapshots is not None:
        inputs = _usage_library_inputs(library_context())
        inputs.pop('recorded')
        state.usage_snapshots.record(
            library_snapshot(**inputs), datetime.now(timezone.utc)
        )
    if state.download_log is not None:
        state.download_log.prune()


async def usage_snapshot_loop(
    interval_seconds: float = USAGE_SNAPSHOT_INTERVAL,
    first_delay: float = USAGE_SNAPSHOT_FIRST_DELAY,
) -> None:
    """Background task: every hour, note the library's size, so the
    usage page has a day-by-day growth even when nobody opens it."""

    await asyncio.sleep(first_delay)
    while True:
        try:
            await asyncio.to_thread(take_usage_snapshot)
        except Exception:
            logger.exception('Could not note the library size')
        await asyncio.sleep(interval_seconds)
