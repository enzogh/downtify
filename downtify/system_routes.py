"""Server routes: version, health, settings, cookies, connection tests,
``/api/fs/dirs``, ``/api/check_update`` and the ``/api/ws`` WebSocket.

Registers on the shared ``api_core.router`` (under its library-only
guard) when :mod:`downtify.api` imports it; the endpoint list lives
in that module's docstring.
"""

from __future__ import annotations

import asyncio
import json
from typing import (
    Any,
    Optional,
)

from fastapi import (
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from loguru import (
    logger,
)

from . import (
    integration_check,
    library_only,
    lyrics,
    providers,
)
from .api_core import (
    DEFAULT_SETTINGS,
    _clamp_cover_resolution,
    _clamp_download_delay,
    _clamp_parallel_downloads,
    _clamp_track_duration,
    _clean_ui_language,
    _effective_audio_providers,
    _effective_deemix_settings,
    _effective_slskd_settings,
    _save_settings,
    bind_lrc_resolver,
    client_label,
    log_activity,
    normalize_lyrics_location,
    router,
    state,
)
from .api_pipeline import (
    _json_object,
    _unmap_removed_extra_folders,
)
from .cookies import (
    MAX_COOKIES_BYTES,
    CookiesStore,
    InvalidCookiesFile,
)
from .deemix_provider import (
    DeemixError,
    check_deemix,
)
from .deemix_provider import (
    normalize_settings as normalize_deemix_settings,
)
from .deemix_provider import (
    validate_settings as validate_deemix_settings,
)
from .external_library import (
    effective_external_library,
)
from .fair_slots import (
    FairSlots,
)
from .fs_suggest import (
    suggest_directories,
)
from .library_paths_cache import (
    invalidate_library_paths_cache,
)
from .navidrome import (
    _effective_navidrome_settings,
)
from .slskd_provider import (
    reset_slskd_parallelism,
)


def _clamp_retry_budget(value: Any) -> int:
    try:
        return max(0, min(1440, int(value)))
    except (TypeError, ValueError, OverflowError):
        return 0


def _validate_integration_settings(
    slskd: dict[str, Any], navidrome: dict[str, Any]
) -> None:
    """Reject enabling slskd/Navidrome without the fields they need."""

    if slskd.get('enabled'):
        if not slskd.get('base_url'):
            raise HTTPException(
                status_code=400,
                detail='slskd base URL is required when enabled',
            )
        if not slskd.get('api_key'):
            raise HTTPException(
                status_code=400,
                detail='slskd API key is required when enabled',
            )
    if navidrome.get('enabled'):
        for key, label in (
            ('url', 'URL'),
            ('username', 'username'),
            ('password', 'password'),
        ):
            if not navidrome.get(key):
                raise HTTPException(
                    status_code=400,
                    detail=f'Navidrome {label} is required when enabled',
                )


def _effective_lyrics_providers(settings: dict[str, Any]) -> list[str]:
    """The lyrics providers to try, in order."""

    return lyrics.providers_from_settings(settings)


@router.get('/api/version')
def get_version() -> str:
    return state.version


@router.get('/api/health')
def get_health() -> dict[str, Any]:
    """Liveness probe: the process is up and FastAPI is serving requests.

    Deliberately doesn't check the downloader/monitor DB — those are
    only set up once ``main.py``'s startup hook finishes, so gating
    health on them would report unhealthy during the brief, normal
    window right after boot. Docker's ``HEALTHCHECK`` already has a
    ``--start-period`` for that; this endpoint just needs to answer.
    """
    return {'status': 'ok', 'version': state.version}


@router.get('/api/check_update')
def check_update() -> Optional[dict[str, Any]]:
    """Result of the last hourly GitHub Releases check (see
    ``downtify/update_check.py``), or ``None`` before the first one has
    run — briefly, right after startup.
    """
    if state.update_checker is None:
        return None
    return state.update_checker.status(state.version)


def _require_cookies_store() -> CookiesStore:
    if state.cookies_store is None:
        raise HTTPException(
            status_code=503, detail='Cookie storage is not ready yet'
        )
    return state.cookies_store


@router.get('/api/cookies')
def get_cookies_endpoint() -> dict[str, Any]:
    """Current cookie configuration, for the settings UI.

    ``locked`` means ``DOWNTIFY_COOKIES_FILE`` is set: that deployment
    manages its own cookie file, so uploads and deletions are refused.
    """
    return _require_cookies_store().status()


@router.post('/api/cookies')
async def upload_cookies_endpoint(request: Request) -> dict[str, Any]:
    """Store an uploaded Netscape ``cookies.txt``, replacing any previous one.

    The body is the raw file rather than a multipart form so Downtify
    doesn't need ``python-multipart`` just for this — a cookies.txt is
    plain text and never large.
    """
    store = _require_cookies_store()
    if store.is_locked():
        raise HTTPException(
            status_code=409,
            detail=(
                'Cookies are configured through the DOWNTIFY_COOKIES_FILE '
                'environment variable. Unset it to manage the file here.'
            ),
        )
    content = await request.body()
    if len(content) > MAX_COOKIES_BYTES:
        raise HTTPException(status_code=413, detail='File is too large')
    try:
        warnings = await asyncio.to_thread(store.save, content)
    except InvalidCookiesFile as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        logger.exception('Failed to store uploaded cookies file')
        raise HTTPException(
            status_code=500, detail=f'Could not save the file: {exc}'
        ) from exc
    return {**store.status(), 'warnings': warnings}


@router.delete('/api/cookies')
async def delete_cookies_endpoint() -> dict[str, Any]:
    store = _require_cookies_store()
    if store.is_locked():
        raise HTTPException(
            status_code=409,
            detail=(
                'Cookies are configured through the DOWNTIFY_COOKIES_FILE '
                'environment variable. Unset it to manage the file here.'
            ),
        )
    try:
        deleted = await asyncio.to_thread(store.delete)
    except OSError as exc:
        logger.exception('Failed to delete stored cookies file')
        raise HTTPException(
            status_code=500, detail=f'Could not delete the file: {exc}'
        ) from exc
    return {**store.status(), 'deleted': deleted}


@router.get('/api/settings')
def get_settings_endpoint(client_id: str = Query('')) -> dict[str, Any]:
    return state.settings


@router.get('/api/fs/dirs')
def suggest_fs_dirs_endpoint(path: str = Query('')) -> dict[str, Any]:
    """Directory names that complete ``path`` as typed in Settings."""

    return {'dirs': suggest_directories(path)}


def _set_library_only(value: Any) -> None:
    if value is True and not library_only.enabled(state.settings):
        if any(
            j.get('status') in {'queued', 'downloading'}
            for j in state.download_jobs.values()
        ) or (state.upgrade_runner and state.upgrade_runner.busy()):
            raise HTTPException(
                status_code=409,
                detail='Wait for external music operations to finish before enabling library-only mode.',
            )
    library_only.policy.set_enabled(state.settings, value)


@router.post('/api/settings/update')
async def update_settings_endpoint(
    request: Request, client_id: str = Query('')
) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    before = json.dumps(state.settings, sort_keys=True, default=str)
    previous = json.loads(before)
    if isinstance(payload, dict):
        # Validated up front so a rejected save changes nothing.
        pending = {**state.settings, **payload}
        slskd_cfg = _effective_slskd_settings(pending)
        navidrome_cfg = _effective_navidrome_settings(pending)
        deemix_cfg = _effective_deemix_settings(pending)
        if deemix_cfg['enabled']:
            try:
                validate_deemix_settings(deemix_cfg)
            except DeemixError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from None
            external = effective_external_library(pending)
            folder = deemix_cfg['source_dir']
            if folder not in external['folders']:
                if len(external['folders']) >= 20:
                    raise HTTPException(
                        status_code=400, detail='Too many library folders'
                    )
                external['folders'].append(folder)
            payload = {**payload, 'external_library': external}
        _validate_integration_settings(
            slskd_cfg if 'slskd' in payload else {},
            navidrome_cfg if 'navidrome' in payload else {},
        )
        if 'library_only' in payload:
            _set_library_only(payload['library_only'])
        for key, raw_value in payload.items():
            if key not in DEFAULT_SETTINGS:
                continue
            if key == 'max_parallel_downloads':
                state.settings[key] = _clamp_parallel_downloads(raw_value)
            elif key == 'download_retry_budget_minutes':
                state.settings[key] = _clamp_retry_budget(raw_value)
            elif key == 'download_delay_seconds':
                state.settings[key] = _clamp_download_delay(raw_value)
            elif key == 'max_track_duration_seconds':
                state.settings[key] = _clamp_track_duration(raw_value)
            elif key == 'external_sync_delay_seconds':
                state.settings[key] = _clamp_download_delay(raw_value)
            elif key == 'cover_resolution':
                state.settings[key] = _clamp_cover_resolution(raw_value)
            elif key == 'ui_language':
                # Not a language code: the saved one stays.
                state.settings[key] = _clean_ui_language(raw_value) or (
                    state.settings.get(key, '')
                )
            elif key == 'slskd':
                # The parallel limit is derived from max_parallel_downloads,
                # not stored with slskd's own options.
                state.settings[key] = {
                    k: v
                    for k, v in slskd_cfg.items()
                    if k != 'max_parallel_downloads'
                }
            elif key == 'navidrome':
                state.settings[key] = navidrome_cfg
            elif key == 'deemix':
                state.settings[key] = deemix_cfg
            elif key == 'external_library':
                state.settings[key] = effective_external_library({
                    'external_library': raw_value
                    if isinstance(raw_value, dict)
                    else {}
                })
            elif key == 'lyrics_lrc_beside':
                state.settings[key] = lyrics.coerce_bool(raw_value, True)
            elif key == 'lyrics_lrc_dir':
                state.settings[key] = str(raw_value or '').strip()
            else:
                state.settings[key] = raw_value
        if {'audio_providers', 'slskd', 'deemix'} & set(payload):
            state.settings['audio_providers'] = _effective_audio_providers(
                state.settings
            )
        if state.downloader is not None:
            state.downloader.deemix_settings = deemix_cfg
            if {
                'audio_providers',
                'slskd',
                'deemix',
                'max_parallel_downloads',
            } & set(payload):
                state.downloader.slskd_settings = (
                    state.downloader._normalize_slskd_settings(
                        _effective_slskd_settings(state.settings)
                    )
                )
                state.downloader.slskd_settings['output_dir'] = str(
                    state.downloader.download_dir
                )
                state.downloader.audio_providers = _effective_audio_providers(
                    state.settings
                )
            fmt = payload.get('format')
            if isinstance(fmt, str) and fmt:
                state.downloader.audio_format = fmt
            bitrate = payload.get('bitrate')
            if isinstance(bitrate, str) and bitrate:
                state.downloader.audio_bitrate = bitrate
            output = payload.get('output')
            if isinstance(output, str) and output:
                state.downloader.output_template = output.replace(
                    '.{output-ext}', ''
                )
            if 'lyrics_providers' in payload or 'download_lyrics' in payload:
                state.downloader.lyrics_providers = (
                    _effective_lyrics_providers(state.settings)
                )
            if 'organize_by_artist' in payload:
                state.downloader.organize_by_artist = bool(
                    payload['organize_by_artist']
                )
            if 'organize_by_album' in payload:
                state.downloader.organize_by_album = bool(
                    payload['organize_by_album']
                )
            if 'download_cover_art' in payload:
                state.downloader.download_cover_art = bool(
                    payload['download_cover_art']
                )
            if 'overwrite_existing_files' in payload:
                state.downloader.overwrite_existing_files = bool(
                    payload['overwrite_existing_files']
                )
            if 'max_track_duration_seconds' in payload:
                state.downloader.max_track_duration_seconds = state.settings[
                    'max_track_duration_seconds'
                ]
        if 'max_parallel_downloads' in payload:
            if state.download_semaphore is None:
                state.download_semaphore = FairSlots(
                    state.settings['max_parallel_downloads']
                )
            else:
                # In place: running downloads keep counting against it.
                state.download_semaphore.resize(
                    state.settings['max_parallel_downloads']
                )
            reset_slskd_parallelism(_effective_slskd_settings(state.settings))
        if 'cover_resolution' in payload:
            providers.set_cover_resolution(state.settings['cover_resolution'])
        if 'external_library' in payload:
            invalidate_library_paths_cache()
            _unmap_removed_extra_folders(previous, state.settings)
        normalize_lyrics_location(state.settings)
        bind_lrc_resolver()
    if state.settings_path is not None:
        _save_settings(state.settings_path, state.settings)
    after = json.loads(json.dumps(state.settings, sort_keys=True, default=str))
    # Names only: values may be passwords and API keys. The page telling
    # the server its language isn't somebody changing settings.
    changed = sorted(
        key
        for key in after
        if after.get(key) != previous.get(key) and key != 'ui_language'
    )
    if changed:
        await log_activity(
            request, 'settings_changed', ', '.join(changed), {'keys': changed}
        )
    if before != json.dumps(
        state.settings, sort_keys=True, default=str
    ) and previous.get('library_only', False) != state.settings.get(
        'library_only', False
    ):
        await state.connections.broadcast({
            'type': 'music_policy_changed',
            'library_only': library_only.enabled(state.settings),
        })
    return state.settings


@router.post('/api/deemix/test')
async def test_deemix_endpoint(request: Request) -> dict[str, Any]:
    """Test the unsaved Deemix form without adding any queue item."""
    payload = await _json_object(request)
    cfg = normalize_deemix_settings(payload or state.settings.get('deemix'))
    return await asyncio.to_thread(check_deemix, cfg)


@router.post('/api/slskd/test')
async def test_slskd_endpoint(request: Request) -> dict[str, Any]:
    """Try a slskd configuration without saving it.

    The body is the ``slskd`` settings object as it stands in the form; an
    empty body tests the saved one. A failed test is a normal answer, not
    an error: ``{ok, server, checks: [{id, status, code, detail}]}``.
    """

    payload = await _json_object(request)
    saved = state.settings.get('slskd')
    cfg = _effective_slskd_settings({
        **state.settings,
        'slskd': payload or (saved if isinstance(saved, dict) else {}),
    })
    return await asyncio.to_thread(integration_check.check_slskd, cfg)


@router.post('/api/navidrome/test')
async def test_navidrome_endpoint(request: Request) -> dict[str, Any]:
    """Try a Navidrome configuration without saving it.

    Same shape as ``POST /api/slskd/test``, with the ``navidrome`` settings
    object as the body.
    """

    payload = await _json_object(request)
    saved = state.settings.get('navidrome')
    cfg = _effective_navidrome_settings({
        **state.settings,
        'navidrome': payload or (saved if isinstance(saved, dict) else {}),
    })
    return await asyncio.to_thread(integration_check.check_navidrome, cfg)


@router.post('/api/proxy/test')
async def test_proxy_endpoint() -> dict[str, Any]:
    """Check the configured outbound proxy without exposing its egress IP."""

    return await asyncio.to_thread(integration_check.check_outbound_proxy)


@router.websocket('/api/ws')
async def websocket_endpoint(
    ws: WebSocket, client_id: str = Query(...)
) -> None:
    principal = (ws.scope.get('state') or {}).get('principal')
    user_id = getattr(principal, 'user_id', 0) or 0
    try:
        label = await asyncio.to_thread(client_label, ws, principal)
    except Exception:
        label = ''
    await state.connections.connect(
        client_id,
        ws,
        getattr(principal, 'device_id', '') or '',
        user_id,
        bool(getattr(principal, 'is_admin', False)),
        label,
    )
    # The account's other pages list this one as a device now.
    await announce_devices(user_id)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        state.connections.disconnect(client_id)
    except Exception:
        state.connections.disconnect(client_id)
    # A web page plays as its client_id: closed or reloaded, it's gone
    # from the device list at once (not 90 s later).
    if user_id and client_id not in state.connections.connected_ids():
        state.now_playing.forget_player(user_id, client_id)
    await announce_devices(user_id)


def devices_for_user(user_id: int) -> list[dict[str, Any]]:
    """*user_id*'s own players and open pages, Spotify Connect style.

    The players heard from lately come first (most recent first, see
    :meth:`NowPlaying.for_user`), then every other open page or app of
    the account as an ``idle`` row (no ``track``) - somewhere playback
    can be sent. ``app`` tells a paired app from a browser.
    """

    if not user_id:
        return []
    rows = [
        {**row, 'idle': False, 'app': bool(row.get('device_id'))}
        for row in state.now_playing.for_user(user_id)
    ]
    players = {row['player'] for row in rows}
    devices = {row['device_id'] for row in rows if row.get('device_id')}
    for sock in state.connections.user_sockets(user_id):
        if sock['player'] in players:
            continue
        if sock['device_id'] and sock['device_id'] in devices:
            continue
        rows.append({
            'player': sock['player'],
            'client': sock['client'],
            'device_id': sock['device_id'],
            'track': None,
            'paused': True,
            'position': 0,
            'started_at': None,
            'seconds_ago': 0,
            'idle': True,
            'app': bool(sock['device_id']),
        })
    for row in rows:
        row.pop('device_id', None)
    return rows


async def announce_devices(user_id: int) -> None:
    """Tell every open page and app of *user_id* their device list
    (``now_playing`` frame, same rows as ``GET /api/activity/devices``)."""

    if not user_id:
        return
    try:
        await state.connections.send_user(
            user_id,
            {'type': 'now_playing', 'players': devices_for_user(user_id)},
        )
    except Exception:
        logger.opt(exception=True).debug('Could not announce devices')
