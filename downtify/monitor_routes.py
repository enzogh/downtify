"""Watched playlists/artists: ``/api/monitor/*``.

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
    Iterable,
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
    providers,
    spotify,
)
from .api_core import (
    _filter_entries_for,
    _usernames,
    admin_hidden_rules,
    allowed_entry_keys,
    hidden_rules,
    library_context,
    request_is_admin,
    request_user_id,
    router,
    spawn_task,
    state,
)
from .api_pipeline import (
    _require_discover,
)
from .artist_suggestions import (
    artist_candidates,
    artist_suggestions,
)
from .discover import (
    artist_key,
)
from .file_providers import (
    providers_for,
)
from .library_cache_keys import (
    file_content_key_from_name_and_size,
)
from .library_catalog import (
    entry_content_key,
    library_artist_index,
    list_entries_for_stored_paths,
    listing_for_request,
    resolve_library_file,
)
from .monitor import (
    ALL_RELEASE_TYPES,
    KIND_ARTIST,
    KIND_PLAYLIST,
    LibraryStores,
    MonitoredPlaylist,
    PlaylistMonitorDB,
    check_watch,
    fetch_playlist,
    normalize_release_types,
    parse_playlist_url,
    playlist_watch_key,
)
from .watch_history import (
    OUTCOME_UNKNOWN,
)
from .watch_stats import (
    DEFAULT_DAYS,
    clamp_days,
    first_events,
    holders_by_file,
    norm_path,
    provenance,
    providers_from_events,
    watch_stats,
)
from fastapi.responses import FileResponse
from fastapi.responses import RedirectResponse
from .api_pipeline import _json_object
from .api_pipeline import _library_songs
from . import artist_catalogue
from .monitor import check_running
from .monitor import saved_watch_cover as monitor_saved_watch_cover
from .monitor import watch_cover_url as monitor_watch_cover_url
from . import musicbrainz
import re
from .monitor import take_inventory


def visible_entries(
    entries: list[dict[str, Any]], request: Optional[Request]
) -> list[dict[str, Any]]:
    """*entries* as *request* may see them (hidden songs cut for a user,
    marked for an admin) - for a listing built from a subset, such as one
    playlist's tracks."""

    return _filter_entries_for(entries, request)


def library_stores() -> LibraryStores:
    """The library stores Playlist Monitor sweeps keep up to date."""

    return LibraryStores(
        track_index=state.track_index,
        playlist_catalog=state.playlist_catalog,
        navidrome_index=state.navidrome_index,
        metadata_cache=state.metadata_cache,
        cover_cache=state.cover_cache,
        playlist_spotify_cache=state.playlist_spotify_cache,
        track_owners=state.track_owners,
        playlist_hidden=state.playlist_hidden,
        listing=lambda: listing_for_request(library_context()),
    )


# ---------------------------------------------------------------------------
# Playlist monitoring endpoints
# ---------------------------------------------------------------------------


def _require_monitor_db() -> PlaylistMonitorDB:
    if state.monitor_db is None:
        raise HTTPException(
            status_code=500, detail='Monitor database not ready'
        )
    return state.monitor_db


def _youtube_artist_for_name(name: str) -> tuple[str, str]:
    """Find the YouTube Music artist channel that matches *name*.

    Spotify's artist embed exposes no discography (only a top-tracks
    preview), so a watched Spotify artist is followed through YouTube
    Music instead — which is also where the audio is fetched from, so
    every release we can see is one we can actually download. Returns
    ``(channel_id, resolved_name)``.

    Only an artist named exactly *name* (by :func:`artist_key`) is
    followed: the first one, YouTube Music's best match when namesakes
    share the name. The top result alone could be someone else entirely,
    so without an exact name ``409`` asks for the YouTube Music link.
    """

    results = providers.search_artists(name, limit=10)
    if not results:
        raise HTTPException(
            status_code=404,
            detail=f'No YouTube Music artist found for {name!r}',
        )
    wanted = artist_key(name)
    best = next(
        (
            r
            for r in results
            if r.get('artist_id') and artist_key(r.get('name')) == wanted
        ),
        None,
    )
    if best is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f'No YouTube Music artist is named exactly {name!r}: '
                "paste the artist's YouTube Music link instead"
            ),
        )
    channel_id = str(best['artist_id'])
    return channel_id, str(best.get('name') or name)


#: A Spotify user (listener) link: an account, never an artist's music.
_SPOTIFY_USER_LINK = re.compile(
    r'(?:spotify\.com/(?:intl-[a-z]{2}(?:-[a-z]{2})?/)?user/'
    r'|^\s*spotify:user:)',
    re.IGNORECASE,
)


async def _resolve_watch_target(url: str) -> tuple[str, str, str]:
    """Resolve a pasted URL into ``(kind, watch_key, display_name)``.

    Accepts a Spotify, public Deezer or YouTube Music playlist URL
    (watched by its tracks), and a Spotify artist URL or a YouTube Music
    artist URL (``/channel/UC...`` or ``/@handle``, watched by their
    discography).
    """

    playlist_target = parse_playlist_url(url)
    if playlist_target is not None:
        source, playlist_id = playlist_target
        try:
            name, _tracks = await asyncio.to_thread(
                fetch_playlist, *playlist_target
            )
        except Exception as exc:
            logger.exception('Failed to resolve playlist {}', playlist_id)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return KIND_PLAYLIST, playlist_watch_key(source, playlist_id), name

    if _SPOTIFY_USER_LINK.search(url or ''):
        raise HTTPException(
            status_code=400,
            detail=(
                "That is a Spotify user link (a listener's account), not an "
                'artist link. Use the artist page, open.spotify.com/artist/…, '
                'or search the artist by name.'
            ),
        )

    spotify_parsed = spotify.parse_spotify_url(url)
    if spotify_parsed is not None and spotify_parsed[0] == 'artist':
        _, artist_id = spotify_parsed
        try:
            spotify_name = await asyncio.to_thread(
                spotify.artist_name_from_id, artist_id
            )
        except Exception as exc:
            logger.exception('Failed to resolve artist {}', artist_id)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        channel_id, name = await asyncio.to_thread(
            _youtube_artist_for_name, spotify_name
        )
        return KIND_ARTIST, channel_id, name

    youtube_parsed = providers.parse_youtube_url(url)
    if youtube_parsed is not None and youtube_parsed[0] == 'artist':
        _, channel_or_handle = youtube_parsed
        try:
            channel_id = await asyncio.to_thread(
                providers.resolve_artist_channel_id, channel_or_handle
            )
            info = await asyncio.to_thread(
                providers.artist_info_from_channel_id, channel_id
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception(
                'Failed to resolve artist channel {}', channel_or_handle
            )
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return KIND_ARTIST, channel_id, str(info.get('name') or channel_id)

    raise HTTPException(
        status_code=400,
        detail=(
            'A Spotify, Deezer or YouTube Music playlist URL, or a Spotify or '
            'YouTube Music artist URL, is required'
        ),
    )


def _monitor_watch_for_request(
    playlist_id: int, request: Optional[Request]
) -> Optional[MonitoredPlaylist]:
    """The watch when *request* may touch it (own or admin's)."""

    db = state.monitor_db
    if db is None:
        return None
    watch = db.get_playlist(playlist_id)
    if watch is None:
        return None
    if request_is_admin(request):
        return watch
    user_id = request_user_id(request)
    if user_id and watch.user_id == user_id:
        return watch
    return None


@router.get('/api/monitor/artist-suggestions')
def monitor_artist_suggestions(
    request: Request,
    listening_offset: int = Query(0, ge=0),
    library_offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Artists to follow, from the asking user's own listens and the
    library they can see (see :mod:`downtify.artist_suggestions`).

    Listens and watches are always the user's own, an admin's too; an
    artist hidden from users stays out of a user's listens as it does
    out of their library. Nothing is searched for here.
    """

    user_id = request_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail='Sign in required')
    artists = library_artist_index(
        library_context(),
        allowed_keys=allowed_entry_keys(request),
        hidden=admin_hidden_rules(request),
    )
    listens = _require_discover().listens(user_id)
    if not request_is_admin(request):
        rules = hidden_rules()
        listens = [
            row
            for row in listens
            if not rules.artist_hidden(row.get('name') or '')
        ]
    return artist_suggestions(
        artists,
        listens,
        _require_monitor_db().list_playlists(user_id),
        listening_offset=listening_offset,
        library_offset=library_offset,
        limit=limit,
    )


@router.get('/api/monitor/artist-suggestions/resolve')
def resolve_monitor_artist_suggestion(
    request: Request,
    name: str = Query(..., min_length=1, max_length=200),
) -> dict[str, Any]:
    """The YouTube Music artist to follow for a suggested *name*, or the
    ones to choose from (see :func:`artist_candidates`).

    Searched for only when the user clicks Follow. It never adds the
    watch: the page then posts the chosen link to
    ``POST /api/monitor/playlists``, as a pasted one.
    """

    if not request_user_id(request):
        raise HTTPException(status_code=401, detail='Sign in required')
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail='Artist name required')
    return artist_candidates(name, providers.search_artists(name, limit=10))


@router.get('/api/monitor/playlists')
async def list_monitor_playlists(request: Request) -> list[dict[str, Any]]:
    db = _require_monitor_db()
    scope = None if request_is_admin(request) else request_user_id(request)
    playlists = await asyncio.to_thread(db.list_playlists, scope)
    return [p.to_dict() for p in playlists]


@router.get('/api/monitor/playlists/{playlist_id}/cover')
async def monitor_playlist_cover(playlist_id: int, request: Request) -> Any:
    """A watched playlist's picture for the Monitor page: the cover saved
    beside its M3U when there is one, else a redirect to the cover its
    service (Spotify, YouTube Music, Deezer) shows, looked up once and
    remembered (:func:`downtify.monitor.watch_cover_url`). 404 for an
    artist, or when there is neither; the page then keeps the initials."""

    _require_monitor_db()
    watch = await asyncio.to_thread(
        _monitor_watch_for_request, playlist_id, request
    )
    if watch is None or watch.kind != KIND_PLAYLIST:
        raise HTTPException(status_code=404, detail='No cover')
    headers = {'Cache-Control': 'private, max-age=3600'}
    downloader = state.downloader
    if downloader is not None:
        saved = await asyncio.to_thread(
            monitor_saved_watch_cover, watch, downloader
        )
        if saved is not None:
            return FileResponse(
                saved, media_type='image/jpeg', headers=headers
            )
    url = await asyncio.to_thread(monitor_watch_cover_url, watch)
    if not url:
        raise HTTPException(status_code=404, detail='No cover')
    return RedirectResponse(url, status_code=302, headers=headers)


@router.post('/api/monitor/playlists')
async def add_monitor_playlist(request: Request) -> dict[str, Any]:
    db = _require_monitor_db()
    user_id = request_user_id(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    url = payload.get('url', '')
    interval_minutes = int(payload.get('interval_minutes', 60))
    release_types = _release_types_from(payload)

    kind, watch_key, name = await _resolve_watch_target(url)
    # Release filters only mean something for an artist's discography.
    new_only = kind == KIND_ARTIST and bool(payload.get('new_only'))
    if kind != KIND_ARTIST:
        release_types = ALL_RELEASE_TYPES

    existing = await asyncio.to_thread(
        db.get_by_spotify_id, watch_key, user_id
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                'This artist is already being watched'
                if kind == KIND_ARTIST
                else 'This playlist is already being monitored'
            ),
        )

    playlist = await asyncio.to_thread(
        db.add_playlist,
        watch_key,
        name,
        url,
        interval_minutes,
        kind,
        release_types,
        new_only,
        user_id,
    )
    _start_initial_check(playlist, db)
    return playlist.to_dict()


def _release_types_from(payload: dict[str, Any]) -> str:
    """``release_types`` from a request body, in its stored form; every
    type when it isn't given. ``400`` for a list that names none."""

    if 'release_types' not in payload:
        return ALL_RELEASE_TYPES
    types = normalize_release_types(payload.get('release_types'))
    if not types:
        raise HTTPException(
            status_code=400,
            detail='Choose at least one kind of release: album, single or ep',
        )
    return types


def _start_initial_check(
    playlist: MonitoredPlaylist, db: PlaylistMonitorDB
) -> None:
    """Run a watch's first download pass now, in the background.

    Saves waiting up to a full monitor sweep for the initial backfill.
    """
    if state.downloader is None:
        return
    loop = state.loop or asyncio.get_running_loop()

    async def _initial_check() -> None:
        try:
            await check_watch(
                playlist,
                db,
                state.downloader,  # type: ignore[arg-type]
                state.connections.broadcast,
                loop,
                state.settings,
                library_stores(),
            )
        except Exception:
            logger.exception('Initial check failed for watch {}', playlist.id)

    spawn_task(_initial_check(), name='monitor-initial-check')


async def _change_watch_url(
    db: PlaylistMonitorDB,
    current: MonitoredPlaylist,
    url: str,
    user_id: Optional[int] = None,
) -> Optional[MonitoredPlaylist]:
    """Apply a new URL to a watch; return the retargeted watch, if any.

    Another link to the same playlist or artist just replaces the stored
    URL. A link to a different one of the same kind retargets the watch
    (see :meth:`PlaylistMonitorDB.retarget_playlist`).
    """
    kind, watch_key, name = await _resolve_watch_target(url)
    if kind != current.kind:
        raise HTTPException(
            status_code=400,
            detail=(
                'This watch follows an artist; paste an artist URL'
                if current.kind == KIND_ARTIST
                else 'This watch follows a playlist; paste a playlist URL'
            ),
        )
    if watch_key == current.spotify_id:
        await asyncio.to_thread(db.update_playlist, current.id, url=url)
        return None
    other = await asyncio.to_thread(db.get_by_spotify_id, watch_key, user_id)
    if other is not None:
        raise HTTPException(
            status_code=409,
            detail=f'"{other.name}" is already being watched',
        )
    return await asyncio.to_thread(
        db.retarget_playlist, current.id, watch_key, name, url
    )


@router.patch('/api/monitor/playlists/{playlist_id}')
async def update_monitor_playlist(
    playlist_id: int, request: Request
) -> dict[str, Any]:
    db = _require_monitor_db()
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    current = await asyncio.to_thread(
        _monitor_watch_for_request, playlist_id, request
    )
    if current is None:
        raise HTTPException(
            status_code=404, detail='Monitored playlist not found'
        )

    retargeted = None
    url = str(payload.get('url') or '').strip()
    if url and url != current.url:
        retargeted = await _change_watch_url(
            db,
            current,
            url,
            None if request_is_admin(request) else request_user_id(request),
        )

    kwargs: dict[str, Any] = {}
    if 'interval_minutes' in payload:
        kwargs['interval_minutes'] = int(payload['interval_minutes'])
    if 'enabled' in payload:
        kwargs['enabled'] = bool(payload['enabled'])

    # An artist's release filters: a check right away downloads what they
    # now let through (a type just turned on, the back catalog after
    # "new releases only" is turned off) instead of waiting for the
    # next scheduled one.
    filters_changed = False
    if 'musicbrainz_kinds' in payload:
        if current.kind != KIND_ARTIST:
            raise HTTPException(
                status_code=400,
                detail='Release kinds only apply to artist watches',
            )
        kinds = _musicbrainz_kinds_from(payload['musicbrainz_kinds'])
        filters_changed = kinds != current.musicbrainz_kinds
        kwargs['musicbrainz_kinds'] = kinds
    if 'release_types' in payload or 'new_only' in payload:
        if current.kind != KIND_ARTIST:
            raise HTTPException(
                status_code=400,
                detail='Release filters only apply to artist watches',
            )
        if 'release_types' in payload:
            types = _release_types_from(payload)
            filters_changed = types != current.release_types
            kwargs['release_types'] = types
        if 'new_only' in payload:
            new_only = bool(payload['new_only'])
            filters_changed = filters_changed or new_only != current.new_only
            await asyncio.to_thread(db.set_new_only, playlist_id, new_only)

    updated = await asyncio.to_thread(
        db.update_playlist, playlist_id, **kwargs
    )
    if updated is None:
        raise HTTPException(
            status_code=404, detail='Monitored playlist not found'
        )
    if (retargeted is not None or filters_changed) and updated.enabled:
        _start_initial_check(updated, db)
    return updated.to_dict()


#: Most watches one bulk edit may name.
MONITOR_BULK_LIMIT = 5000


@router.patch('/api/monitor/playlists')
async def update_monitor_playlists(request: Request) -> dict[str, Any]:
    """Give several watches the same ``interval_minutes`` and/or
    ``enabled`` at once (the Monitor page's selection). Watches that
    don't exist or belong to another account are left out and listed
    under ``missing``."""

    db = _require_monitor_db()
    payload = await _json_object(request)

    raw_ids = payload.get('ids')
    if not isinstance(raw_ids, list) or not raw_ids:
        raise HTTPException(
            status_code=400, detail='ids is a non-empty list of watch ids'
        )
    if len(raw_ids) > MONITOR_BULK_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f'At most {MONITOR_BULK_LIMIT} watches at once',
        )
    try:
        ids = list(dict.fromkeys(int(i) for i in raw_ids))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400, detail='ids is a non-empty list of watch ids'
        )

    kwargs: dict[str, Any] = {}
    if 'interval_minutes' in payload:
        try:
            interval = int(payload['interval_minutes'])
        except (TypeError, ValueError):
            interval = 0
        if interval < 1:
            raise HTTPException(
                status_code=400,
                detail='interval_minutes is a positive number of minutes',
            )
        kwargs['interval_minutes'] = interval
    if 'enabled' in payload:
        kwargs['enabled'] = bool(payload['enabled'])
    if not kwargs:
        raise HTTPException(
            status_code=400,
            detail='Nothing to change: send interval_minutes or enabled',
        )

    def _apply() -> tuple[list[dict[str, Any]], list[int]]:
        updated: list[dict[str, Any]] = []
        missing: list[int] = []
        for watch_id in ids:
            if _monitor_watch_for_request(watch_id, request) is None:
                missing.append(watch_id)
                continue
            watch = db.update_playlist(watch_id, **kwargs)
            if watch is None:
                missing.append(watch_id)
            else:
                updated.append(watch.to_dict())
        return updated, missing

    updated, missing = await asyncio.to_thread(_apply)
    return {'updated': updated, 'missing': missing}


@router.delete('/api/monitor/playlists/{playlist_id}')
async def delete_monitor_playlist(
    playlist_id: int, request: Request
) -> dict[str, Any]:
    db = _require_monitor_db()
    visible = await asyncio.to_thread(
        _monitor_watch_for_request, playlist_id, request
    )
    if visible is None:
        raise HTTPException(
            status_code=404, detail='Monitored playlist not found'
        )
    deleted = await asyncio.to_thread(db.delete_playlist, playlist_id)
    if not deleted:
        raise HTTPException(
            status_code=404, detail='Monitored playlist not found'
        )
    return {'deleted': True, 'id': playlist_id}


def _musicbrainz_kinds_from(value: Any) -> Optional[str]:
    """A watch's ``musicbrainz_kinds`` from a request: ``None`` (follow
    the setting) or a list of ``musicbrainz.KINDS`` names, stored
    comma-separated. ``400`` for anything else."""

    if value is None:
        return None
    if not isinstance(value, list) or any(
        str(kind) not in musicbrainz.KINDS for kind in value
    ):
        raise HTTPException(
            status_code=400,
            detail='musicbrainz_kinds is a list of: '
            + ', '.join(musicbrainz.KINDS),
        )
    return ','.join(k for k in musicbrainz.KINDS if k in set(map(str, value)))


async def _artist_watch_for_request(
    playlist_id: int, request: Request
) -> MonitoredPlaylist:
    watch = await asyncio.to_thread(
        _monitor_watch_for_request, playlist_id, request
    )
    if watch is None:
        raise HTTPException(
            status_code=404, detail='Monitored playlist not found'
        )
    if watch.kind != KIND_ARTIST:
        raise HTTPException(
            status_code=400, detail='Only an artist watch has releases'
        )
    return watch


#: "Check what I have" per artist watch: ``{running, done, total,
#: checked, failed, started_at, finished_at}``, the last one kept.
_inventories: dict[int, dict[str, Any]] = {}


#: ``_artist_releases``'s "read the library yourself" (``None`` is a
#: library that couldn't be read).
_UNSET: Any = object()


def _artist_releases(
    db: PlaylistMonitorDB, watch: MonitoredPlaylist, songs: Any = _UNSET
) -> dict[str, Any]:
    if songs is _UNSET:
        songs = _library_songs()
    kinds = artist_catalogue.watch_kinds(watch, state.settings)
    have = artist_catalogue.library_have(
        db.catalogue.tracks(watch.id),
        songs,
        db.releases.counts(watch.id),
    )
    releases = artist_catalogue.catalogue_view(
        db.catalogue.rows(watch.id),
        have=have,
        seen=db.catalogue.seen(watch.id),
        types=set((watch.release_types or ALL_RELEASE_TYPES).split(',')),
        kinds=kinds,
    )
    names = {mb: name for name, mb in musicbrainz.KINDS.items()}
    return {
        'watch': watch.to_dict(),
        'kinds': [names[k] for k in musicbrainz.KINDS.values() if k in kinds],
        'kinds_default': watch.musicbrainz_kinds is None,
        'available_kinds': list(musicbrainz.KINDS),
        'musicbrainz': bool(state.settings.get('artist_watch_musicbrainz')),
        'releases': releases,
        'counts': artist_catalogue.counts(releases),
        'inventory': dict(_inventories.get(watch.id) or {}) or None,
        'missing': artist_catalogue.missing(releases),
        'checking': check_running(watch.id),
    }


@router.get('/api/monitor/playlists/{playlist_id}/releases')
async def artist_watch_releases(
    playlist_id: int, request: Request
) -> dict[str, Any]:
    """An artist watch's whole catalogue, from its last check: one row
    per release with what the library has of it (``state``: complete,
    partly, missing, skipped, not_watched, off, not_own), plus the
    watch's MusicBrainz release kinds. See ``downtify/artist_catalogue.py``."""

    db = _require_monitor_db()
    watch = await _artist_watch_for_request(playlist_id, request)
    return await asyncio.to_thread(_artist_releases, db, watch)


@router.get('/api/monitor/playlists/{playlist_id}/releases/tracks')
async def artist_watch_release_tracks(
    playlist_id: int, request: Request, album_id: list[str] = Query(...)
) -> dict[str, Any]:
    """One release's tracklist (of the first of *album_id* - a release's
    ``album_ids`` - with one kept) and the library file holding each
    track: ``{album_id, tracks: [{position, name, artists, duration,
    file}]}``, ``file`` ``null`` when the library doesn't have it.
    ``tracks`` is empty until a check read the tracklist."""

    db = _require_monitor_db()
    watch = await _artist_watch_for_request(playlist_id, request)

    def build() -> dict[str, Any]:
        kept = db.catalogue.tracks(watch.id)
        chosen = next((a for a in album_id if a in kept), '')
        if not chosen:
            return {'album_id': album_id[0], 'tracks': []}
        recorded = {
            position: filename
            for (position, _track), filename in db.releases.tracks(
                watch.id, chosen
            ).items()
        }
        return {
            'album_id': chosen,
            'tracks': artist_catalogue.track_list(
                kept[chosen], _library_songs(), recorded
            ),
        }

    return await asyncio.to_thread(build)


@router.post('/api/monitor/playlists/{playlist_id}/releases/inventory')
async def check_artist_watch_inventory(
    playlist_id: int, request: Request
) -> dict[str, Any]:
    """ "Check what I have": read, in the background, the tracklist of every
    release of the watch's catalogue that has none kept, so ``GET
    .../releases`` counts what the library has of each. Downloads
    nothing. ``{inventory: {running, done, total, ...}}``; a second call
    while it runs returns the running one."""

    db = _require_monitor_db()
    watch = await _artist_watch_for_request(playlist_id, request)
    job = _inventories.get(watch.id)
    if job and job.get('running'):
        return {'inventory': dict(job)}
    job = {
        'running': True,
        'done': 0,
        'total': 0,
        'checked': 0,
        'failed': 0,
        'started_at': datetime.now(timezone.utc).isoformat(),
        'finished_at': '',
    }
    _inventories[watch.id] = job

    def progress(done: int, total: int) -> None:
        job.update(done=done, total=total)

    async def run() -> None:
        try:
            job.update(
                await asyncio.to_thread(
                    take_inventory, watch, db, progress=progress
                )
            )
        except Exception:
            logger.exception(
                'Checking what the library has of "{}" failed', watch.name
            )
            job['error'] = True
        finally:
            job.update(
                running=False,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )

    spawn_task(run(), name=f'artist-inventory-{watch.id}')
    return {'inventory': dict(job)}


@router.post('/api/monitor/playlists/{playlist_id}/releases/download-missing')
async def download_missing_artist_releases(
    playlist_id: int, request: Request
) -> dict[str, Any]:
    """ "Download missing": a check of the watch that goes through every
    release it downloads again, known or not, and downloads the songs
    missing from them (linking those the library has under another name)
    - as the queue shows. Releases the watch doesn't download are left
    alone; switch one on first. ``{started, missing}``; ``409`` while the
    watch is being checked."""

    db = _require_monitor_db()
    watch = await _artist_watch_for_request(playlist_id, request)
    if state.downloader is None:
        raise HTTPException(status_code=500, detail='Downloader not ready')
    if check_running(watch.id):
        raise HTTPException(
            status_code=409, detail='This artist is being checked right now'
        )
    missing = (await asyncio.to_thread(_artist_releases, db, watch))['missing']
    loop = state.loop or asyncio.get_running_loop()

    async def run() -> None:
        try:
            await check_watch(
                watch,
                db,
                state.downloader,  # type: ignore[arg-type]
                state.connections.broadcast,
                loop,
                state.settings,
                library_stores(),
                fill_missing=True,
            )
        except Exception:
            logger.exception('Downloading what "{}" misses failed', watch.name)

    spawn_task(run(), name=f'artist-missing-{watch.id}')
    return {'started': True, 'missing': missing}


@router.patch('/api/monitor/playlists/{playlist_id}/releases')
async def switch_artist_watch_releases(
    playlist_id: int, request: Request
) -> dict[str, Any]:
    """Switch releases of an artist watch: ``{album_ids, choice}``, the
    choice ``on`` (download it even when its type isn't watched or it
    came out before a "new releases only" watch), ``off`` (never) or
    ``''`` (follow the watch). Switching on starts a check, so it
    downloads now. Returns the releases as ``GET`` does."""

    db = _require_monitor_db()
    watch = await _artist_watch_for_request(playlist_id, request)
    payload = await _json_object(request)
    album_ids = payload.get('album_ids')
    choice = payload.get('choice')
    if (
        not isinstance(album_ids, list)
        or not album_ids
        or not all(isinstance(a, str) and a for a in album_ids)
        or choice not in artist_catalogue.CHOICES
    ):
        raise HTTPException(
            status_code=400,
            detail="Send album_ids and a choice: 'on', 'off' or ''",
        )
    changed = await asyncio.to_thread(
        db.catalogue.set_choice, watch.id, album_ids, choice
    )
    if not changed:
        raise HTTPException(
            status_code=404, detail='The watch lists no such release'
        )
    if choice == 'on':
        await asyncio.to_thread(
            db.catalogue.forget_skipped, watch.id, album_ids
        )
        if watch.enabled:
            _start_initial_check(watch, db)
    return await asyncio.to_thread(_artist_releases, db, watch)


@router.post('/api/monitor/playlists/{playlist_id}/check')
async def manual_check_playlist(
    playlist_id: int, request: Request
) -> dict[str, Any]:
    db = _require_monitor_db()
    playlist = await asyncio.to_thread(
        _monitor_watch_for_request, playlist_id, request
    )
    if playlist is None:
        raise HTTPException(
            status_code=404, detail='Monitored playlist not found'
        )
    if state.downloader is None:
        raise HTTPException(status_code=500, detail='Downloader not ready')

    loop = state.loop or asyncio.get_running_loop()

    async def _run() -> None:
        try:
            count = await check_watch(
                playlist,
                db,
                state.downloader,
                state.connections.broadcast,
                loop,
                # Was omitted before, which silently ignored the
                # delay-between-downloads setting on a manual check.
                state.settings,
                library_stores(),
            )
            logger.info(
                'Manual check: downloaded {} new track(s) from "{}"',
                count,
                playlist.name,
            )  # type: ignore[union-attr]
        except Exception:
            logger.exception('Manual check failed for watch {}', playlist_id)

    spawn_task(_run(), name='monitor-manual-check')
    return {'status': 'check_started', 'id': playlist_id}


# ---------------------------------------------------------------------------
# Playlist Monitor provenance and statistics (downtify/watch_stats.py)
# ---------------------------------------------------------------------------


def _watch_file_facts(
    paths: Iterable[str],
) -> tuple[dict[str, int], dict[str, str]]:
    """``({path: size}, {path: provider})`` for the library files among
    *paths* still on disk.

    Read off the library listing snapshot, so a file it has costs no disk
    access; one it lacks (a download not merged into it yet) is looked up
    on disk.
    """

    wanted = {norm_path(path) for path in paths}
    wanted.discard('')
    if not wanted:
        return {}, {}
    ctx = library_context()
    try:
        listing = listing_for_request(ctx)
    except Exception:
        logger.opt(exception=True).warning(
            'Library listing unavailable for the watch statistics'
        )
        listing = []
    by_file = {}
    for entry in listing:
        name = norm_path(entry.get('file'))
        if name in wanted:
            by_file[name] = entry
    sizes: dict[str, int] = {}
    keys: dict[str, str] = {}
    for name in wanted:
        entry = by_file.get(name)
        if entry is not None:
            sizes[name] = int(entry.get('size') or 0)
            keys[name] = entry_content_key(entry)
            continue
        full = resolve_library_file(name, ctx)
        try:
            size = full.stat().st_size if full is not None else -1
        except OSError:
            size = -1
        if size >= 0:
            sizes[name] = size
            keys[name] = file_content_key_from_name_and_size(name, size) or ''
    return sizes, providers_for(state.file_providers, keys)


def _watch_summary(
    watch: MonitoredPlaylist, usernames: dict[int, str]
) -> dict[str, Any]:
    """What the provenance panel shows of a watch - enough to tell two
    watches of the same link apart (id, owner, when it was added)."""

    return {
        'id': watch.id,
        'name': watch.name,
        'url': watch.url,
        'kind': watch.kind,
        'source': watch.source,
        'enabled': watch.enabled,
        'created_at': watch.created_at,
        'owner': usernames.get(watch.user_id, ''),
    }


def _sees_watch(request: Request, owner_id: int) -> bool:
    """Whether *request* may see a watch of *owner_id* by name."""

    if request_is_admin(request):
        return True
    user_id = request_user_id(request)
    return bool(user_id) and owner_id == user_id


@router.get('/api/monitor/stats')
async def monitor_stats(
    request: Request, days: int = DEFAULT_DAYS
) -> dict[str, Any]:
    """Each watch's storage, download status and activity over the last
    *days* - see :func:`downtify.watch_stats.watch_stats`."""

    db = _require_monitor_db()
    scope = None if request_is_admin(request) else request_user_id(request)
    return await asyncio.to_thread(_monitor_stats, db, scope, days)


def _monitor_stats(
    db: PlaylistMonitorDB, scope: Optional[int], days: int
) -> dict[str, Any]:
    associations = db.list_all_downloaded_tracks()
    sizes, file_providers = _watch_file_facts(
        row['filename'] for row in associations
    )
    return watch_stats(
        db.list_playlists(scope),
        associations,
        db.history.events(),
        sizes,
        now=datetime.now(timezone.utc),
        days=clamp_days(days),
        providers=file_providers,
        failures=db.history.failure_counts(),
    )


@router.get('/api/monitor/provenance')
async def monitor_provenance(
    request: Request, file: str = ''
) -> dict[str, Any]:
    """Which watch first downloaded a library file, and which hold it."""

    db = _require_monitor_db()
    name = norm_path(file)
    if not name:
        raise HTTPException(status_code=400, detail='A file is required')
    return await asyncio.to_thread(_monitor_provenance, db, name, request)


def _monitor_provenance(
    db: PlaylistMonitorDB, name: str, request: Request
) -> dict[str, Any]:
    history = db.history
    holdings = history.holdings(name)
    events = history.events(filename=name)
    if not holdings and not events and state.track_index is not None:
        # The watches may still name the song's old path.
        tid = state.track_index.spotify_id_for_filename(name)
        if tid:
            holdings = history.holdings(name, {tid})
            events = history.events(filename=name, track_ids={tid})
    found = provenance(
        holdings, events, {w.id: w for w in db.list_playlists()}
    )
    usernames = _usernames() if request_is_admin(request) else {}
    watches = [
        {
            **_watch_summary(holder['watch'], usernames),
            'added_at': holder['added_at'],
            'outcome': holder['outcome'],
            'initial': holder['initial'],
        }
        for holder in found['holders']
        if _sees_watch(request, holder['watch'].user_id)
    ]
    origin = found['origin']
    if origin is not None:
        watch = origin.pop('watch')
        if not _sees_watch(request, origin.pop('user_id')):
            # Another account's watch: when, not whose.
            origin = {
                'hidden': True,
                'at': origin['at'],
                'initial': origin['initial'],
                'estimated': origin['estimated'],
            }
        else:
            origin['watch'] = (
                _watch_summary(watch, usernames) if watch else None
            )
    return {
        'file': name,
        'origin': origin,
        'watches': watches,
        'others': len(found['holders']) - len(watches),
    }


@router.delete('/api/monitor/playlists/{playlist_id}/failures')
async def monitor_playlist_clear_failures(
    playlist_id: int, request: Request
) -> dict[str, Any]:
    """Forget a watch's failing songs, so its next checks show only what
    still fails (after a settings change, say). They are tried again on
    the next check either way."""

    db = _require_monitor_db()
    watch = await asyncio.to_thread(
        _monitor_watch_for_request, playlist_id, request
    )
    if watch is None:
        raise HTTPException(
            status_code=404, detail='Monitored playlist not found'
        )
    removed = await asyncio.to_thread(db.history.forget_failures, watch.id)
    return {'removed': removed}


@router.get('/api/monitor/playlists/{playlist_id}/tracks')
async def monitor_playlist_tracks(
    playlist_id: int, request: Request
) -> dict[str, Any]:
    """The songs a watch holds, newest first, as ``GET /tracks`` rows -
    with how and when each got there - plus the ones failing."""

    db = _require_monitor_db()
    watch = await asyncio.to_thread(
        _monitor_watch_for_request, playlist_id, request
    )
    if watch is None:
        raise HTTPException(
            status_code=404, detail='Monitored playlist not found'
        )
    return await asyncio.to_thread(_monitor_watch_tracks, db, watch, request)


def _monitor_watch_tracks(
    db: PlaylistMonitorDB, watch: MonitoredPlaylist, request: Request
) -> dict[str, Any]:
    events = db.history.events()
    firsts = first_events(
        event
        for event in events
        if event['playlist_id'] == watch.id
        and event['watch_key'] == watch.spotify_id
    )
    added: dict[str, dict[str, Any]] = {}
    for track_id, filename in db.get_track_filenames(watch.id).items():
        name = norm_path(filename)
        if not name:
            continue
        first = firsts.get((watch.id, watch.spotify_id, track_id)) or {}
        info = {
            'track_id': track_id,
            'added_at': first.get('happened_at') or '',
            'outcome': first.get('outcome') or OUTCOME_UNKNOWN,
            'initial': bool(first.get('initial')),
            'provider': first.get('provider') or '',
        }
        known = added.get(name)
        if known is None or info['added_at'] < known['added_at']:
            added[name] = info
    order = sorted(added, key=lambda n: added[n]['added_at'], reverse=True)
    on_disk = list_entries_for_stored_paths(library_context(), order)
    holders = holders_by_file(db.list_all_downloaded_tracks())
    fetched_by = {
        **providers_from_events(events),
        **providers_for(
            state.file_providers,
            {entry['file']: entry_content_key(entry) for entry in on_disk},
        ),
    }
    tracks = []
    for entry in visible_entries(on_disk, request):
        name = norm_path(entry['file'])
        info = added.get(name, {})
        tracks.append({
            **entry,
            'watch': {
                **info,
                'provider': fetched_by.get(name) or info.get('provider', ''),
                'shared_with': max(0, len(holders.get(name, ())) - 1),
            },
        })
    return {
        'watch': watch.to_dict(),
        'tracks': tracks,
        'missing': len(order) - len(on_disk),
        'failures': db.history.failures(watch.id),
    }
