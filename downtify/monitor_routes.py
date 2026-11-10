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
