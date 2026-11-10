"""Shared state and helpers behind every ``/api`` router.

Settings defaults and clamps, :class:`ConnectionManager`, :class:`AppState`
(``state``), the library-only guard, who is asking (``request_user_id``,
``request_is_admin``), what they may see (``allowed_entry_keys``,
playlist visibility), ``library_context`` and file ownership.

Re-exported by :mod:`downtify.api`; see its docstring for the endpoints.
"""

from __future__ import annotations

import asyncio
import concurrent.futures.thread as cf_thread
import contextlib
import hashlib
import json
import re
import threading
from dataclasses import (
    dataclass,
)
from pathlib import (
    Path,
)
from typing import (
    Any,
    AsyncIterator,
    Collection,
    Optional,
)

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
)
from loguru import (
    logger,
)
from starlette.requests import (
    HTTPConnection,
)

from . import (
    artist_profile,
    catalog_worker,
    compilation,
    cover_sources,
    library_only,
    library_upgrade,
    lyrics,
    providers,
)
from .activity import (
    ActivityLog,
    NowPlaying,
    describe_user_agent,
)
from .auth import (
    AuthStore,
    PairingStore,
    Principal,
    RateLimiter,
    TicketStore,
    client_ip,
    trusted_proxies_from_env,
)
from .cookies import (
    CookiesStore,
)
from .cover_cache import (
    CoverArtCache,
)
from .cover_thumbs import (
    CoverThumbs,
)
from .deemix_provider import (
    DEFAULT_SETTINGS as DEEMIX_DEFAULTS,
)
from .deemix_provider import (
    normalize_settings as normalize_deemix_settings,
)
from .discover import (
    DiscoverStore,
)
from .download_history import (
    DownloadHistory,
)
from .download_log import (
    OUTCOME_COMPLETED,
    DownloadLog,
)
from .download_queue import (
    PendingDownloads,
)
from .downloader import (
    AUDIO_PROVIDERS,
    DOWNLOAD_EXECUTOR,
    MAX_PARALLEL_DOWNLOADS,
    MAX_TRACK_DURATION_SECONDS,
    Downloader,
)
from .external_library import (
    effective_external_library,
    extra_dirs_from_settings,
)
from .external_playlists import (
    ExternalPlaylistImports,
)
from .external_sync import (
    ExternalSyncJob,
)
from .fair_slots import (
    FairSlots,
)
from .file_providers import (
    FileProviders,
)
from .library_catalog import (
    LibraryContext,
    entry_content_key,
    library_context_from_state,
    list_library_paths,
    listing_for_request,
    resolve_library_file,
)
from .library_metadata_cache import (
    LibraryMetadataCache,
)
from .library_paths import (
    locate_library_file,
    slskd_dir_from_downloader,
)
from .library_reconcile import (
    refresh_playlists_after_moves,
)
from .library_sync import (
    LibrarySync,
)
from .library_usage import (
    UsageSnapshots,
)
from .library_visibility import (
    HiddenRules,
    LibraryVisibility,
)
from .likes import (
    LIKED_PLAYLIST_NAME,
    LikedTracks,
    content_key_for,
    is_liked_playlist,
)
from .live_stream import (
    LiveStreams,
)
from .loudness import (
    LoudnessAnalyzer,
)
from .lyrics_cache import (
    LyricsLookupCache,
)
from .manual_playlists import (
    ManualPlaylistError,
    edit_manual_playlist,
)
from .monitor import (
    PlaylistMonitorDB,
)
from .navidrome_index import (
    NavidromeIndex,
)
from .playlist_batches import (
    PlaylistBatchStore,
)
from .playlist_catalog import (
    ManualPlaylistOwners,
    PlaylistCatalog,
)
from .playlist_hidden import (
    PlaylistHiddenSongs,
    hidden_key,
)
from .playlist_listing import (
    list_library_playlists,
)
from .playlist_pending import (
    PlaylistPendingSongs,
)
from .playlist_shares import (
    PRIVATE,
    PlaylistShares,
    ShareView,
    share_key,
)
from .playlist_spotify_cache import (
    PlaylistSpotifyCache,
    fetch_playlist_tracks,
)
from .server_identity import (
    ServerIdentity,
)
from .stream import (
    StreamCache,
)
from .track_index import (
    TrackIndex,
    normalize_spotify_track_id,
)
from .track_owners import (
    TrackOwners,
)
from .traffic import (
    DIRECTION_IN,
    TrafficCounters,
)
from .transcode import (
    Transcoder,
)
from .update_check import (
    UpdateChecker,
)

MIN_PARALLEL_DOWNLOADS = 1

MIN_DOWNLOAD_DELAY_SECONDS = 0

MAX_DOWNLOAD_DELAY_SECONDS = 300

#: Longest track taken (seconds); ``0`` takes everything. The default
#: is :data:`downtify.downloader.MAX_TRACK_DURATION_SECONDS`.
MIN_TRACK_DURATION_SETTING_SECONDS = 0

MAX_TRACK_DURATION_SETTING_SECONDS = 6 * 3600

MIN_COVER_RESOLUTION = 300

MAX_COVER_RESOLUTION = 1200

DEFAULT_SETTINGS: dict[str, Any] = {
    'library_only': False,
    'audio_providers': ['youtube-music'],
    'deemix': dict(DEEMIX_DEFAULTS),
    'lyrics_providers': list(lyrics.PROVIDER_ORDER),
    'download_lyrics': True,
    'lyrics_lrc_beside': True,
    'lyrics_lrc_dir': lyrics.DEFAULT_LYRICS_LRC_DIR,
    'format': 'mp3',
    'bitrate': '320',
    'output': '{artists} - {title}.{output-ext}',
    'generate_m3u': True,
    'download_cover_art_playlists': True,
    # Whether Downtify may save an artist's photo/banner on its own: when
    # their Library page is first opened and when one of their tracks
    # finishes downloading (``enrich_artist_after_download``). The manual
    # picker on an artist's Library page never checks these.
    'download_cover_art_artist': True,
    'download_cover_art_artist_banner': False,
    'max_parallel_downloads': 3,
    'download_delay_seconds': 0,
    'download_retry_budget_minutes': 0,
    'max_track_duration_seconds': MAX_TRACK_DURATION_SECONDS,
    'external_sync_delay_seconds': 0,
    'cover_resolution': providers.DEFAULT_COVER_RESOLUTION,
    'download_cover_art': True,
    'overwrite_existing_files': True,
    'organize_by_artist': True,
    'organize_by_album': True,
    'search_albums': True,
    'mini_player_enabled': True,
    # The language the web UI is shown in (``en``, ``pt-BR``...). The choice
    # lives in the browser, so the page tells the server (see
    # ``model/settings.js``): work that runs without a browser, like an
    # artist's bio fetched after a download, needs it. ``''`` until a page
    # has said - then there is no language to fetch in.
    'ui_language': '',
    # Soulseek via slskd, used when 'slskd' is in audio_providers.
    'slskd': {
        'enabled': False,
        'base_url': '',
        'api_key': '',
        'download_dir': '/downloads',
        'source_dir': '/slskd',
        'leave_in_place': True,
        'timeout_seconds': 20,
        'search_retries': 5,
        'search_poll_seconds': 15,
        'download_attempts': 5,
        'poll_interval_seconds': 5,
        'poll_max_attempts': 60,
        'download_timeout_seconds': 600,
        'queued_timeout_seconds': 180,
        'duration_tolerance_seconds': 10,
        'duration_tolerance_percent': 15,
        'mix_duration_tolerance_percent': 50,
        'extensions': ['mp3', 'flac'],
        'strict_format_priority': False,
        'extensions_whitelist': False,
        'min_bitrate': 256,
    },
    # Navidrome (Subsonic API) playlist sync after playlist downloads.
    'sync_navidrome': True,
    # Whether users may share their playlists with other users (each user
    # also chooses whether to see public ones: ``show_public_playlists``).
    'allow_playlist_sharing': True,
    # Whether users may make public links to a song, which anyone can
    # open and play without signing in (see downtify/song_links.py).
    'allow_song_links': True,
    'navidrome': {
        'enabled': False,
        'url': '',
        'username': '',
        'password': '',
        'admin_username': '',
        'admin_password': '',
        'public_playlist': False,
        'scan_after_download': True,
        'scan_full': False,
        'scan_wait_seconds': 120,
        'scan_poll_seconds': 5,
        'scan_retry_seconds': 15,
        'client_name': 'Castify',
        'api_version': '1.16.1',
    },
    # Folders of already-tagged audio to include in the library (in
    # place). Synced from Settings → Library; see
    # ``downtify.external_library``.
    'external_library': {
        'folders': [],
    },
    # Keep extracted cover art under /data/cover_cache for faster Library
    # and Player loads.
    'cache_cover_art': False,
    # Defaults the Library upgrade scan starts from (see
    # downtify.library_upgrade); a scan request may override them.
    'library_upgrade': {
        'artwork_min_px': library_upgrade.DEFAULT_ARTWORK_MIN_PX,
        'artwork_source': cover_sources.PREFERENCE_HIGHEST,
        'recheck_days': library_upgrade.DEFAULT_RECHECK_DAYS,
    },
}

# Settings stored as nested objects: saved values are merged over the
# defaults key by key, so a settings.json from an older version still gets
# every newer option.
_NESTED_SETTINGS = (
    'deemix',
    'slskd',
    'navidrome',
    'library_upgrade',
    'external_library',
)


def _clamp_parallel_downloads(value: Any) -> int:
    """Coerce and clamp a requested parallel-download count.

    Keeps the setting inside ``[MIN_PARALLEL_DOWNLOADS,
    MAX_PARALLEL_DOWNLOADS]`` regardless of what the client sends, so a
    malformed or malicious payload can't spin up an unbounded number of
    concurrent yt-dlp/ffmpeg processes.
    """
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = DEFAULT_SETTINGS['max_parallel_downloads']
    return min(MAX_PARALLEL_DOWNLOADS, max(MIN_PARALLEL_DOWNLOADS, count))


def _clamp_download_delay(value: Any) -> float:
    """Coerce and clamp the requested inter-download delay, in seconds.

    Keeps the setting inside ``[MIN_DOWNLOAD_DELAY_SECONDS,
    MAX_DOWNLOAD_DELAY_SECONDS]`` regardless of what the client sends,
    so a malformed or malicious payload can't freeze batch/monitor
    downloads for an unbounded amount of time.
    """
    try:
        delay = float(value)
    except (TypeError, ValueError):
        delay = DEFAULT_SETTINGS['download_delay_seconds']
    return min(
        MAX_DOWNLOAD_DELAY_SECONDS, max(MIN_DOWNLOAD_DELAY_SECONDS, delay)
    )


def _clamp_track_duration(value: Any) -> int:
    """Coerce and clamp the longest track taken, in seconds.

    ``0`` takes everything (mixes included); anything else lands inside
    ``[60, MAX_TRACK_DURATION_SETTING_SECONDS]``. Applies to downloads
    and streams alike (see :mod:`downtify.stream`).
    """

    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return int(DEFAULT_SETTINGS['max_track_duration_seconds'])
    if seconds <= 0:
        return MIN_TRACK_DURATION_SETTING_SECONDS
    return min(MAX_TRACK_DURATION_SETTING_SECONDS, max(60, seconds))


_UI_LANGUAGE_RE = re.compile(r'[a-z]{2}(-[A-Z]{2})?')


def _clean_ui_language(value: Any) -> str:
    """*value* when it is a language code of the shape the web UI uses
    (``en``, ``pt-BR``), else ``''``. It ends up in ``settings.json`` and in
    other services' requests, so nothing else is kept."""

    code = value.strip() if isinstance(value, str) else ''
    return code if _UI_LANGUAGE_RE.fullmatch(code) else ''


def _clamp_cover_resolution(value: Any) -> int:
    """Coerce and clamp the requested cover art target size, in pixels.

    Keeps the setting inside ``[MIN_COVER_RESOLUTION,
    MAX_COVER_RESOLUTION]``. Affects YouTube Music-sourced cover art
    (see ``providers.set_cover_resolution``, which resizes a thumbnail
    URL directly) and Deezer-sourced cover art (see
    ``deezer._cover_from_images``, which instead picks the smallest of
    Deezer's four fixed image sizes that still meets it, reading this
    same value via ``providers.cover_resolution``). Spotify-sourced
    covers are unaffected: Downtify already uses the largest size
    Spotify's embed API offers, with no equivalent to resize or pick
    from.
    """
    try:
        px = int(value)
    except (TypeError, ValueError):
        px = DEFAULT_SETTINGS['cover_resolution']
    return min(MAX_COVER_RESOLUTION, max(MIN_COVER_RESOLUTION, px))


def _setting_int(
    data: dict[str, Any],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(data.get(key) or default)
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


def _slskd_extensions(raw: dict[str, Any]) -> list[str]:
    value = raw.get('extensions')
    if isinstance(value, str):
        value = value.split(',')
    if not isinstance(value, list):
        value = []
    extensions = [
        str(e).strip().lower().lstrip('.') for e in value if str(e).strip()
    ]
    return extensions or ['mp3', 'flac']


def _effective_slskd_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Normalized slskd settings (URLs trimmed, numbers clamped).

    ``source_dir`` defaults to ``/slskd`` when files are left in place and
    to the download folder otherwise. The parallel-download limit is taken
    from the global setting, capped at 8 for slskd.
    """

    raw = settings.get('slskd')
    if not isinstance(raw, dict):
        raw = {}
    download_dir = str(raw.get('download_dir') or '/downloads').strip()
    leave_in_place = raw.get('leave_in_place')
    leave_in_place = True if leave_in_place is None else bool(leave_in_place)
    source_dir = str(raw.get('source_dir') or '').strip() or (
        '/slskd' if leave_in_place else download_dir
    )

    def bounded(key: str, default: int, low: int, high: int) -> int:
        return _setting_int(raw, key, default, minimum=low, maximum=high)

    try:
        min_bitrate = int(raw.get('min_bitrate'))
    except (TypeError, ValueError):
        min_bitrate = 256
    min_bitrate = min(10000, max(0, min_bitrate))

    return {
        'enabled': bool(raw.get('enabled', False)),
        'base_url': str(raw.get('base_url') or '').strip().rstrip('/'),
        'api_key': str(raw.get('api_key') or '').strip(),
        'download_dir': download_dir,
        'source_dir': source_dir,
        'leave_in_place': leave_in_place,
        'extensions': _slskd_extensions(raw),
        'timeout_seconds': bounded('timeout_seconds', 20, 5, 120),
        'search_retries': bounded('search_retries', 5, 1, 20),
        'search_poll_seconds': bounded('search_poll_seconds', 15, 3, 60),
        'download_attempts': bounded('download_attempts', 5, 1, 10),
        'poll_interval_seconds': bounded('poll_interval_seconds', 5, 1, 30),
        'poll_max_attempts': bounded('poll_max_attempts', 60, 1, 300),
        'download_timeout_seconds': bounded(
            'download_timeout_seconds', 600, 30, 3600
        ),
        'queued_timeout_seconds': bounded(
            'queued_timeout_seconds', 180, 15, 3600
        ),
        'duration_tolerance_seconds': bounded(
            'duration_tolerance_seconds', 10, 1, 120
        ),
        'duration_tolerance_percent': bounded(
            'duration_tolerance_percent', 15, 1, 100
        ),
        'mix_duration_tolerance_percent': bounded(
            'mix_duration_tolerance_percent', 50, 1, 200
        ),
        'strict_format_priority': bool(
            raw.get('strict_format_priority', False)
        ),
        'extensions_whitelist': bool(raw.get('extensions_whitelist', False)),
        'min_bitrate': min_bitrate,
        'max_parallel_downloads': _setting_int(
            settings, 'max_parallel_downloads', 3, minimum=1, maximum=8
        ),
    }


def _effective_deemix_settings(settings: dict[str, Any]) -> dict[str, Any]:
    return normalize_deemix_settings(settings.get('deemix'))


def _effective_audio_providers(settings: dict[str, Any]) -> list[str]:
    """Enabled audio providers in the configured order.

    slskd is dropped while it's disabled. When slskd is the only provider
    left, YouTube Music and YouTube are appended as fallbacks so a track
    slskd can't find still downloads.
    """

    slskd_enabled = bool(_effective_slskd_settings(settings).get('enabled'))
    out: list[str] = []
    for raw in settings.get('audio_providers') or []:
        name = str(raw or '').strip()
        if name == 'slskd' and not slskd_enabled:
            continue
        if (
            name == 'deemix'
            and not _effective_deemix_settings(settings)['enabled']
        ):
            continue
        if name in AUDIO_PROVIDERS and name not in out:
            out.append(name)
    if not out:
        return ['youtube-music']
    if out == ['slskd']:
        out += ['youtube-music', 'youtube']
    return out


def _organize_enabled() -> bool:
    """True when tracks are routed into per-artist/per-album folders.

    In that case per-playlist folders are bypassed, so the M3U must be
    written to the legacy ``Playlists/`` directory where its relative
    track paths still resolve.
    """

    d = state.downloader
    return bool(d and (d.organize_by_artist or d.organize_by_album))


class ConnectionManager:
    """Tracks the active WebSocket clients keyed by ``client_id``."""

    def __init__(self) -> None:
        self._clients: dict[str, WebSocket] = {}
        # client_id -> the paired device it belongs to, if any, so a
        # revoked device's socket can be closed at once.
        self._devices: dict[str, str] = {}
        # client_id -> the signed-in user, so a user signed out
        # everywhere (or deleted) is disconnected too.
        self._users: dict[str, int] = {}
        # Sockets that see every download job event (admins).
        self._admins: set[str] = set()
        # client_id -> what it is ("Web (Chrome on macOS)", an app's
        # name), for the account's device list.
        self._labels: dict[str, str] = {}

    async def connect(
        self,
        client_id: str,
        ws: WebSocket,
        device_id: str = '',
        user_id: int = 0,
        is_admin: bool = False,
        label: str = '',
    ) -> None:
        await ws.accept()
        self._clients[client_id] = ws
        self._labels[client_id] = label
        if device_id:
            self._devices[client_id] = device_id
        else:
            self._devices.pop(client_id, None)
        if user_id:
            self._users[client_id] = user_id
        else:
            self._users.pop(client_id, None)
        if is_admin:
            self._admins.add(client_id)
        else:
            self._admins.discard(client_id)

    def disconnect(self, client_id: str) -> None:
        self._clients.pop(client_id, None)
        self._devices.pop(client_id, None)
        self._users.pop(client_id, None)
        self._admins.discard(client_id)
        self._labels.pop(client_id, None)

    def connected_ids(self) -> set[str]:
        """Every open socket's ``client_id``."""

        return set(self._clients)

    def user_sockets(self, user_id: int) -> list[dict[str, str]]:
        """*user_id*'s open sockets: ``{player, client, device_id}`` -
        a web page's ``player`` is its ``client_id`` (the id it reports
        playback with)."""

        return [
            {
                'player': cid,
                'client': self._labels.get(cid, ''),
                'device_id': self._devices.get(cid, ''),
            }
            for cid, uid in self._users.items()
            if uid == user_id and cid in self._clients
        ]

    async def send_user(self, user_id: int, message: dict[str, Any]) -> None:
        """Send *message* to every socket of *user_id*."""

        for cid in [c for c, uid in self._users.items() if uid == user_id]:
            await self.send(cid, message)

    async def close_user(self, user_id: int) -> None:
        """Close every socket of *user_id*, browsers and apps (``4401``)."""

        doomed = [cid for cid, uid in self._users.items() if uid == user_id]
        sockets = [self._clients.pop(cid, None) for cid in doomed]
        for cid in doomed:
            self._users.pop(cid, None)
            self._devices.pop(cid, None)
        await asyncio.gather(
            *(ws.close(code=4401) for ws in sockets if ws is not None),
            return_exceptions=True,
        )

    async def close_device(self, device_id: str = '') -> None:
        """Close the sockets of *device_id* - every paired device's when
        it's empty (``4401``: signed out)."""

        doomed = [
            cid
            for cid, dev in self._devices.items()
            if dev and (not device_id or dev == device_id)
        ]
        sockets = [self._clients.pop(cid, None) for cid in doomed]
        for cid in doomed:
            self._devices.pop(cid, None)
        await asyncio.gather(
            *(ws.close(code=4401) for ws in sockets if ws is not None),
            return_exceptions=True,
        )

    async def send(self, client_id: str, message: dict[str, Any]) -> None:
        ws = self._clients.get(client_id)
        if ws is None:
            return
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            self._clients.pop(client_id, None)

    async def broadcast_job(
        self, user_ids: Collection[int], message: dict[str, Any]
    ) -> None:
        """A download job event: its waiters and the admins, nobody else.

        The titles in job events would otherwise tell every connected
        client what someone else is downloading (``GET /api/queue`` is
        filtered the same way). An ownerless job (a watch's, a retry's)
        goes to the admins and to sockets of no account (sign-in off) -
        never to a signed-in user, whose queue could not list it and so
        would show it downloading forever.
        """

        targets_set = {int(uid) for uid in user_ids if uid}
        targets = [
            cid for cid, uid in self._users.items() if uid in targets_set
        ]
        targets += [cid for cid in self._admins if cid not in targets]
        if not targets_set:
            targets += [
                cid
                for cid in self._clients
                if cid not in self._users and cid not in targets
            ]
        for client_id in targets:
            await self.send(client_id, message)

    async def broadcast(self, message: dict[str, Any]) -> None:
        # Serialized once, sent to every client concurrently: one slow
        # client (a phone on a weak connection) no longer delays the rest.
        clients = list(self._clients.items())
        if not clients:
            return
        text = json.dumps(message)
        results = await asyncio.gather(
            *(ws.send_text(text) for _, ws in clients),
            return_exceptions=True,
        )
        for (client_id, ws), result in zip(clients, results):
            # Only drop that exact socket: the client may have reconnected
            # under the same id while the sends were in flight.
            if isinstance(result, Exception) and (
                self._clients.get(client_id) is ws
            ):
                self._clients.pop(client_id, None)

    async def close_all(self, code: int = 1012) -> None:
        """Close every tracked socket (``1012`` = service restart).

        Cleared before awaiting so a concurrent reconnect cannot land in
        the map we are tearing down. Safe if uvicorn already closed the
        transport.
        """
        clients = list(self._clients.items())
        self._clients.clear()
        self._devices.clear()
        self._admins.clear()
        if not clients:
            return
        await asyncio.gather(
            *(ws.close(code=code) for _, ws in clients),
            return_exceptions=True,
        )


class AppState:
    version: str = '0.0.0'
    downloader: Optional[Downloader] = None
    connections: ConnectionManager = ConnectionManager()
    settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
    settings_path: Optional[Path] = None
    cookies_store: Optional[CookiesStore] = None
    update_checker: Optional[UpdateChecker] = None
    loop: Optional[asyncio.AbstractEventLoop] = None
    monitor_db: Optional[PlaylistMonitorDB] = None
    download_jobs: dict[str, dict[str, Any]] = {}
    # The "Parallel downloads" slots, shared fairly between accounts
    # (downtify/fair_slots.py).
    download_semaphore: Optional[FairSlots] = None
    # The unfinished jobs and the pause switch, for the next start
    # (downtify/download_queue.py).
    pending_downloads: Optional[PendingDownloads] = None
    # The recently finished jobs, for the queue's Done/Failed tabs after
    # a restart (downtify/download_history.py).
    download_history: Optional[DownloadHistory] = None
    # Fire-and-forget work owned by the process (import batches, monitor
    # loops, playlist refresh). Cancelled in :func:`shutdown_resources`.
    background_tasks: set[asyncio.Task[Any]] = set()
    # Library stores in /data/downtify_library.db (opened at startup).
    track_index: Optional[TrackIndex] = None
    navidrome_index: Optional[NavidromeIndex] = None
    metadata_cache: Optional[LibraryMetadataCache] = None
    cover_cache: Optional[CoverArtCache] = None
    playlist_catalog: Optional[PlaylistCatalog] = None
    playlist_batch_store: Optional[PlaylistBatchStore] = None
    playlist_spotify_cache: Optional[PlaylistSpotifyCache] = None
    lyrics_cache: Optional[LyricsLookupCache] = None
    upgrade_runner: Optional[library_upgrade.LibraryUpgradeRunner] = None
    audio_replacements: Any = None
    external_sync: Optional[ExternalSyncJob] = None
    likes: Optional[LikedTracks] = None
    track_owners: Optional[TrackOwners] = None
    library_visibility: Optional[LibraryVisibility] = None
    manual_playlist_owners: Optional[ManualPlaylistOwners] = None
    playlist_shares: Optional[PlaylistShares] = None
    # Public links to one song (see downtify/song_links.py).
    song_links: Any = None
    # Orders owners gave their imported playlists
    # (see downtify/playlist_custom_order.py).
    playlist_custom_order: Any = None
    playlist_hidden: Optional[PlaylistHiddenSongs] = None
    # Songs added to a Library playlist before their download ends
    # (downtify/playlist_pending.py).
    playlist_pending: Optional[PlaylistPendingSongs] = None
    # Which audio provider fetched each file (downtify/file_providers.py).
    file_providers: Optional[FileProviders] = None
    # How each download ended and the library's size day by day, for the
    # library usage page (downtify/download_log.py, library_usage.py).
    download_log: Optional[DownloadLog] = None
    usage_snapshots: Optional[UsageSnapshots] = None
    external_playlist_imports: Optional[ExternalPlaylistImports] = None
    loudness_analyzer: Optional[LoudnessAnalyzer] = None
    traffic: Optional[TrafficCounters] = None
    compilation_marks: Optional[compilation.CompilationMarks] = None
    discover: Optional[DiscoverStore] = None
    # Sign-in and paired apps (see downtify/auth.py and auth_routes.py).
    auth: Optional[AuthStore] = None
    pairing: PairingStore = PairingStore()
    ws_tickets: TicketStore = TicketStore()
    login_limiter: RateLimiter = RateLimiter()
    pair_limiter: RateLimiter = RateLimiter()
    identity: Optional[ServerIdentity] = None
    # {host, port, source}: where the server listens and what chose the
    # port (downtify/server_port.py).
    listen: dict[str, Any] = {}
    # What users do (downtify/activity.py), for admins.
    activity: Optional[ActivityLog] = None
    now_playing: NowPlaying = NowPlaying()
    # The mobile API (downtify/mobile_routes.py).
    library_sync: Optional[LibrarySync] = None
    library_trash: Any = None
    transcoder: Optional[Transcoder] = None
    stream_cache: Optional[StreamCache] = None
    live_streams: LiveStreams = LiveStreams()
    cover_thumbs: Optional[CoverThumbs] = None
    discovery: Any = None


state = AppState()


async def library_only_guard(
    connection: HTTPConnection,
) -> AsyncIterator[None]:
    """Apply the same policy to browsers and paired devices."""
    if connection.scope.get('type') != 'http':
        yield
        return
    path = connection.url.path
    if not library_only.remote_route(
        path, connection.scope.get('method', 'GET')
    ):
        yield
    elif (
        library_only.enabled(state.settings)
        and path in library_only.LOCAL_ROUTES
    ):
        yield
    else:
        with library_only.policy.external(state.settings):
            yield


router = APIRouter(dependencies=[Depends(library_only_guard)])

_shutdown_done = False


def spawn_task(coro: Any, *, name: Optional[str] = None) -> asyncio.Task[Any]:
    """Create a task and track it for :func:`shutdown_resources`."""
    if name and name.startswith((
        'playlist-batch',
        'csv-batch',
        'stream-prefetch-',
        'stream-live-prefetch-',
        'replace-',
        'monitor-initial-check',
        'monitor-manual-check',
        'queue-restore',
    )):
        lease = contextlib.ExitStack()
        try:
            lease.enter_context(library_only.policy.external(state.settings))
        except HTTPException:
            coro.close()
            raise

        async def guarded() -> Any:
            try:
                return await coro
            finally:
                lease.close()

        task = asyncio.create_task(guarded(), name=name)

        def release(finished: asyncio.Task[Any]) -> None:
            lease.close()
            if finished.cancelled():
                coro.close()

        task.add_done_callback(release)
    else:
        task = asyncio.create_task(coro, name=name)
    state.background_tasks.add(task)
    task.add_done_callback(state.background_tasks.discard)
    return task


# ---------------------------------------------------------------------------
# Who is asking (see downtify/auth.py) and the activity log
# ---------------------------------------------------------------------------


_TRUSTED_PROXIES = trusted_proxies_from_env()


def principal_of(request: Request) -> Optional[Principal]:
    """Who made *request* (set by the auth middleware), if anyone."""

    return (request.scope.get('state') or {}).get('principal')


def request_user_id(request: Optional[Request]) -> int:
    """The signed-in user behind *request* (``0`` when there is none)."""

    if request is None:
        return 0
    principal = principal_of(request)
    return int(getattr(principal, 'user_id', 0) or 0)


def request_is_admin(request: Optional[Request]) -> bool:
    """Whether *request* was made by an admin (sees every track)."""

    if request is None:
        return False
    principal = principal_of(request)
    return bool(principal is not None and principal.is_admin)


def hidden_rules() -> HiddenRules:
    """What admins hid from users (nothing, until they hide something)."""

    if state.library_visibility is None:
        return HiddenRules()
    try:
        return state.library_visibility.rules()
    except Exception:
        logger.opt(exception=True).warning('Could not read hidden items')
        return HiddenRules()


def admin_hidden_rules(request: Optional[Request]) -> Optional[HiddenRules]:
    """The rules to mark rows with for an admin's view, else ``None``
    (users get the rows themselves cut instead)."""

    if not request_is_admin(request):
        return None
    rules = hidden_rules()
    return rules if rules else None


def allowed_entry_keys(request: Optional[Request]) -> Optional[set[str]]:
    """Content keys *request* may browse (``None``: everything).

    The library is shared: an admin sees all of it, and so does everyone
    else - except what an admin hid from users, which is cut here (one
    pass over the listing, and only while something is hidden).
    """

    if request_is_admin(request):
        return None
    if not request_user_id(request):
        return set()
    rules = hidden_rules()
    if not rules:
        return None
    return {
        entry_content_key(entry)
        for entry in listing_for_request(library_context())
        if not rules.hides(entry)
    }


def _playlist_owner_maps() -> tuple[dict[str, int], dict[str, int]]:
    """``({casefolded catalog name: user_id}, {manual name: user_id})``."""

    catalog_names: dict[str, int] = {}
    manual: dict[str, int] = {}
    try:
        catalog = state.playlist_catalog
        if catalog is not None:
            catalog_names = {
                str(name or '').strip().casefold(): int(uid or 0)
                for name, uid in catalog.playlist_owner_map().items()
            }
        owned = state.manual_playlist_owners
        if owned is not None:
            manual = dict(owned.owner_map())
    except Exception:
        logger.opt(exception=True).debug('Could not read playlist owners')
    return catalog_names, manual


def sharing_enabled() -> bool:
    """Whether the admin lets users share playlists (Settings)."""

    return bool(state.settings.get('allow_playlist_sharing', True))


def _share_view(user_id: int) -> ShareView:
    """What *user_id* is shown of other people's playlists (nothing while
    sharing is off)."""

    shares = state.playlist_shares
    if shares is None or not user_id or not sharing_enabled():
        return ShareView()
    try:
        return shares.view_for(user_id)
    except Exception:
        logger.opt(exception=True).debug('Could not read playlist shares')
        return ShareView()


def _usernames() -> dict[int, str]:
    """``{user id: username}`` for labelling whose playlist it is."""

    if state.auth is None:
        return {}
    try:
        return {
            int(user['id']): str(user['username'])
            for user in state.auth.users.list()
        }
    except Exception:
        logger.opt(exception=True).debug('Could not list usernames')
        return {}


def _playlist_visible(
    name: str, *, liked: bool, manual: bool, user_id: int
) -> bool:
    """Whether *user_id* may open a playlist (admins bypass this): their
    own, one shared with them, or a public one."""

    if liked or not user_id:
        return False
    catalog_names, manual_owners = _playlist_owner_maps()
    key = share_key(name)
    owner = (manual_owners if manual else catalog_names).get(key, 0)
    if owner == user_id:
        return True
    if not owner:
        return False
    view = _share_view(user_id)
    return key in view.public or key in view.to_me


@dataclass
class _PlaylistLens:
    """Who is looking, and what every playlist's owner and sharing are -
    read once per listing."""

    admin: bool
    user_id: int
    owners: tuple[dict[str, int], dict[str, int]]
    visibility: dict[str, str]
    shared_users: dict[str, list[int]]
    editors: dict[str, list[int]]
    view: ShareView
    show_public: bool
    names: dict[int, str]

    def row(self, playlist: dict[str, Any]) -> Optional[dict[str, Any]]:
        """*playlist* as the viewer sees it, or ``None`` when hidden."""

        key = share_key(str(playlist.get('name') or ''))
        owner_id = self.owners[1 if playlist.get('manual') else 0].get(key, 0)
        mine = self.admin or bool(self.user_id and owner_id == self.user_id)
        followed = key in self.view.followed
        invited = key in self.view.to_me
        if not mine and not (
            owner_id
            and (
                invited
                or (key in self.view.public and (followed or self.show_public))
            )
        ):
            return None
        editors = self.editors.get(key, [])
        row = {
            **playlist,
            'owner_id': owner_id,
            'owner': self.names.get(owner_id, ''),
            'visibility': self.visibility.get(key, PRIVATE),
            'mine': mine,
            'followed': followed,
            'shared_with_me': invited,
            'new': invited and not self.view.to_me[key],
            # Songs of a Library playlist: the owner's (or an admin's) to
            # change, and its editors' while it is shared with them.
            'can_edit_tracks': bool(
                playlist.get('manual')
                and (mine or (invited and self.user_id in editors))
            ),
        }
        if mine:
            row['shared_with'] = [
                self.names[uid]
                for uid in self.shared_users.get(key, [])
                if uid in self.names
            ]
            row['editors'] = [
                self.names[uid] for uid in editors if uid in self.names
            ]
        return row


def _playlist_lens(request: Optional[Request]) -> _PlaylistLens:
    admin = request_is_admin(request)
    user_id = request_user_id(request)
    visibility: dict[str, str] = {}
    shared_users: dict[str, list[int]] = {}
    editors: dict[str, list[int]] = {}
    shares = state.playlist_shares
    if shares is not None and sharing_enabled():
        try:
            visibility = shares.visibility_map()
            shared_users = shares.shared_users()
            editors = shares.editors()
        except Exception:
            logger.opt(exception=True).debug('Could not read playlist shares')
    return _PlaylistLens(
        admin=admin,
        user_id=user_id,
        owners=_playlist_owner_maps(),
        visibility=visibility,
        shared_users=shared_users,
        editors=editors,
        view=ShareView() if admin else _share_view(user_id),
        show_public=admin
        or bool(user_preferences(request).get('show_public_playlists', True)),
        names=_usernames(),
    )


def _filter_playlists_for(
    playlists: list[dict[str, Any]], request: Optional[Request]
) -> list[dict[str, Any]]:
    """Playlists *request* may open, each labelled with its owner.

    Admins see everything. Anyone else sees playlists they own
    (downloaded or Library-created), those shared with them by name,
    the public ones they follow and - unless they switched
    *Show public playlists* off - the rest of the public ones. The
    shared liked-songs file is swapped for their own hearts (which live
    in the database only).

    Rows are copies carrying ``owner_id``, ``owner``, ``visibility``,
    ``mine`` (theirs to change: their own, or anything for an admin),
    ``followed``, ``shared_with_me``, ``new`` (shared with them, not
    opened yet) and ``can_edit_tracks`` (they may add and remove songs:
    a Library playlist that is theirs, or shared with them as an
    editor); the owner's also list ``shared_with`` and ``editors``
    (usernames) and, on an imported playlist they hid songs from,
    ``hidden_count``.
    """

    lens = _playlist_lens(request)
    kept: list[dict[str, Any]] = []
    for playlist in playlists:
        if playlist.get('liked'):
            if lens.admin:
                kept.append(playlist)
            continue
        row = lens.row(playlist)
        if row is not None:
            kept.append(row)
    if lens.user_id and not lens.admin and state.likes is not None:
        try:
            liked_files = state.likes.paths(lens.user_id)
        except Exception:
            logger.opt(exception=True).debug(
                'Could not read likes for playlist listing'
            )
            liked_files = []
        if liked_files:
            kept.append({
                'name': LIKED_PLAYLIST_NAME,
                'files': liked_files,
                'count': len(liked_files),
                'added': 0,
                'cover': '',
                'liked': True,
                'manual': False,
                'mine': True,
                'visibility': PRIVATE,
            })
    labels = (
        state.playlist_shares.display_names()
        if state.playlist_shares is not None
        else {}
    )
    favorites = (
        state.playlist_shares.favorites(lens.user_id)
        if state.playlist_shares is not None and lens.user_id
        else frozenset()
    )
    kept = [
        {
            **row,
            'display_name': labels.get(
                playlist_display_identity(row), row['name']
            ),
            'favorite': playlist_favorite_identity(row) in favorites,
        }
        for row in kept
    ]
    hidden_counts = _hidden_song_counts()
    for row in kept:
        # The owner's imported playlists say how many songs they hide.
        count = hidden_counts.get(hidden_key(row['name']), 0)
        if count and row.get('mine') and not row.get('manual'):
            row['hidden_count'] = count
    kept.sort(
        key=lambda item: (
            not item.get('favorite'),
            not item.get('liked'),
            str(item.get('display_name') or item.get('name') or '').casefold(),
        )
    )
    return kept


def _hidden_song_counts() -> dict[str, int]:
    """``{playlist key: hidden songs}`` (empty when nothing is hidden)."""

    if state.playlist_hidden is None:
        return {}
    try:
        return state.playlist_hidden.counts()
    except Exception:
        logger.opt(exception=True).debug('Could not count hidden songs')
        return {}


def playlist_display_identity(entry: dict[str, Any]) -> str:
    """Keep a source-backed playlist's label through source-name updates."""
    name = str(entry['name'])
    catalog = state.playlist_catalog
    source = (
        catalog.spotify_id_for_playlist(name) if catalog is not None else None
    )
    return f'source:{source}' if source else f'name:{share_key(name)}'


def playlist_favorite_identity(entry: dict[str, Any]) -> str:
    name = str(entry['name'])
    catalog = state.playlist_catalog
    source = catalog.spotify_id_for_playlist(name) if catalog else None
    if source:
        return '@source:' + hashlib.sha256(source.encode()).hexdigest()
    return share_key(name)


def _filter_entries_for(
    entries: list[dict[str, Any]], request: Optional[Request]
) -> list[dict[str, Any]]:
    """Library rows *request* may browse.

    An admin gets every row; those hidden from users carry ``hidden_by``
    (``track``, ``album`` or ``artist``). Anyone else gets every row an
    admin hasn't hidden, with foreign playlists cut: a track can sit in
    playlists nobody else may open (someone else's download shares the
    file), and those names are scrubbed from its row so it never reveals
    them. Rows are copied, never mutated - the snapshot they come from
    is shared.
    """

    if request_is_admin(request):
        rules = admin_hidden_rules(request)
        if rules is None:
            return entries
        marked = []
        for entry in entries:
            reason = rules.reason(entry)
            marked.append({**entry, 'hidden_by': reason} if reason else entry)
        return marked

    user_id = request_user_id(request)
    if not user_id:
        return []
    rules = hidden_rules()
    catalog_names, manual_owners = _playlist_owner_maps()
    owned = {name for name, uid in catalog_names.items() if uid == user_id} | {
        key for key, uid in manual_owners.items() if uid == user_id
    }

    def _scrubbed(row: dict[str, Any], names: Any) -> dict[str, Any]:
        kept = [
            str(raw)
            for raw in names
            if is_liked_playlist(raw)
            or str(raw or '').strip().casefold() in owned
        ]
        return {**row, 'playlists': kept}

    filtered = []
    for entry in entries:
        if rules and rules.hides(entry):
            continue
        names = entry.get('playlists')
        filtered.append(_scrubbed(entry, names) if names else entry)
    return filtered


def entries_for_request(request: Optional[Request]) -> list[dict[str, Any]]:
    """``GET /tracks`` rows *request* may browse."""

    return _filter_entries_for(listing_for_request(library_context()), request)


def filter_paths_for_request(
    paths: list[str], request: Optional[Request]
) -> list[str]:
    """Library paths *request* may browse (``GET /list``), order kept."""

    allowed = allowed_entry_keys(request)
    if allowed is None:
        return list(paths)
    by_file = {}
    for entry in listing_for_request(library_context()):
        by_file[str(entry.get('file') or '').replace('\\', '/')] = (
            entry_content_key(entry)
        )
    return [
        path
        for path in paths
        if by_file.get(str(path or '').replace('\\', '/')) in allowed
    ]


def playlists_for_request(request: Optional[Request]) -> list[dict[str, Any]]:
    """Playlist listing entries *request* may open.

    Served from memory while recently checked (see
    ``library_paths_cache.PLAYLIST_RECHECK_SECONDS``): walking the
    downloads folder for M3U files on every page took ~300 ms on a NAS.
    """

    ctx = library_context()
    found = list_library_playlists(
        ctx.download_dir, ctx.slskd_dir, ctx.extra_dirs, stale_ok=True
    )
    return _filter_playlists_for(found, request)


def request_ip(request: Request) -> str:
    return client_ip(request.scope, _TRUSTED_PROXIES)


def client_label(
    request: HTTPConnection, principal: Optional[Principal]
) -> str:
    """What a request came from, for the activity log: a paired app's
    name, or ``Web (Firefox on Linux)``."""

    if principal is not None and principal.device_id and state.auth:
        device = state.auth.get_device(principal.device_id) or {}
        return str(device.get('name') or 'App')
    browser = describe_user_agent(request.headers.get('user-agent', ''))
    return f'Web ({browser})' if browser else 'Web'


def user_preferences(request: Request) -> dict[str, Any]:
    """The signed-in user's own preferences (Settings > General)."""

    if state.auth is None:
        return {}
    principal = principal_of(request)
    if principal is None or not principal.user_id:
        return {}
    return state.auth.users.preferences(principal.user_id)


async def log_activity(
    request: Request,
    kind: str,
    summary: str = '',
    detail: Optional[dict[str, Any]] = None,
) -> None:
    """Add what *request*'s user did to the activity log. Never fails the
    request it's called from."""

    log = state.activity
    if log is None:
        return
    principal = principal_of(request)
    try:
        label = await asyncio.to_thread(client_label, request, principal)
        await asyncio.to_thread(
            log.record,
            kind,
            user_id=principal.user_id if principal else 0,
            username=principal.username if principal else '',
            summary=summary,
            detail=detail,
            client=label,
            ip=request_ip(request),
        )
    except Exception:
        logger.exception('Activity log: could not record {}', kind)


_SHUTDOWN_TASK_TIMEOUT_SECONDS = 1.0


def _skip_threadpool_join() -> None:
    """Stop CPython from joining every ThreadPoolExecutor on exit.

    Python 3.9+ registers ``concurrent.futures.thread._python_exit`` with
    ``threading._register_atexit``, not ``atexit``. That hook ``join()``s
    every worker still in ``_threads_queues`` — download, metadata, and
    ``asyncio.to_thread`` pools. Setting ``daemon=True`` does not skip it.
    A second Ctrl+C during shutdown was interrupting that join.
    """
    try:
        threading._threading_atexits.clear()
    except Exception:
        pass
    try:
        for thread in list(getattr(cf_thread, '_threads_queues', {})):
            try:
                thread.daemon = True
            except Exception:
                pass
    except Exception:
        pass
    for thread in threading.enumerate():
        if thread is threading.main_thread():
            continue
        try:
            thread.daemon = True
        except Exception:
            pass


def release_thread_pools() -> None:
    """Stop accepting pool work and do not join in-flight workers."""
    DOWNLOAD_EXECUTOR.shutdown(wait=False, cancel_futures=True)
    _skip_threadpool_join()


async def shutdown_resources() -> None:
    """Close WebSockets, cancel background work, release the download pool.

    Idempotent: lifespan and ``main``'s ``finally`` may both call this.
    """
    global _shutdown_done
    if _shutdown_done:
        return
    _shutdown_done = True

    logger.info('Castify shutdown: closing WebSockets and background tasks')
    if state.loudness_analyzer is not None:
        await asyncio.to_thread(state.loudness_analyzer.close)
    await state.connections.close_all()

    tasks = list(state.background_tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=_SHUTDOWN_TASK_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            still = sum(1 for task in tasks if not task.done())
            logger.warning(
                'Shutdown: {} background task(s) still running, continuing',
                still,
            )

    if state.upgrade_runner is not None:
        try:
            state.upgrade_runner.pause()
        except Exception:
            logger.exception('Library upgrade: could not pause on shutdown')

    await asyncio.to_thread(catalog_worker.stop_catalog_worker)

    if state.traffic is not None:
        try:
            await asyncio.to_thread(state.traffic.flush)
        except Exception:
            logger.exception('Traffic counters: could not save on shutdown')

    try:
        loop = asyncio.get_running_loop()
        await asyncio.wait_for(
            loop.shutdown_default_executor(),
            timeout=_SHUTDOWN_TASK_TIMEOUT_SECONDS,
        )
    except Exception:
        pass

    release_thread_pools()
    logger.info('Castify shutdown: complete')


def library_context() -> LibraryContext:
    """Where library files live (downloads + slskd folder) and the
    stores that describe them."""

    download_dir = (
        Path(state.downloader.download_dir)
        if state.downloader is not None
        else Path('/downloads')
    )
    # Songs in the music trash (or waiting to go there) are no longer
    # part of the library, for anyone.
    hidden_files, hidden_resolved = (
        state.library_trash.hidden()
        if state.library_trash is not None
        else (frozenset(), frozenset())
    )
    return library_context_from_state(
        download_dir,
        state.settings,
        state.track_index,
        metadata_cache=state.metadata_cache,
        playlist_catalog=state.playlist_catalog,
        hidden_files=hidden_files,
        hidden_resolved=hidden_resolved,
    )


def stored_content_key(stored_path: str) -> str:
    """The ownership key of a library path (``''`` when not on disk)."""

    try:
        full = resolve_library_file(stored_path, library_context())
    except Exception:
        return ''
    if full is None:
        return ''
    try:
        return content_key_for(full) or ''
    except Exception:
        return ''


#: What a delete answers for a file that isn't the caller's to delete.
NOT_YOURS_ERROR = 'Only an admin or whoever downloaded it can delete this song'


def _record_download_traffic(filename: str, user_id: int) -> None:
    """Count a finished download's bytes as the downloader's upstream."""

    if not user_id or state.traffic is None or state.downloader is None:
        return
    try:
        full = locate_library_file(
            filename,
            Path(state.downloader.download_dir),
            slskd_dir_from_downloader(state.downloader),
        )
        if full is None:
            return
        state.traffic.add(user_id, DIRECTION_IN, full.stat().st_size)
    except Exception:
        logger.opt(exception=True).debug(
            'Could not record download traffic for {}', filename
        )


#: Who pre-feature files belong to on the first start with ownership.
MIGRATION_USERNAME = 'brillik'


def resolve_migration_user_id() -> int:
    """Who files without owners belong to: ``brillik`` when that account
    exists, else the oldest admin, else ``0`` (nobody - try again next
    start)."""

    users = state.auth.users if state.auth is not None else None
    if users is None:
        return 0
    try:
        found = users.by_username(MIGRATION_USERNAME)
        if found is not None:
            return int(found['id'])
        first = users.first_admin()
        return int(first['id']) if first is not None else 0
    except Exception:
        logger.opt(exception=True).debug(
            'Could not resolve the migration user'
        )
        return 0


def migrate_first_run_ownership() -> dict[str, int]:
    """Attribute every ownerless thing, once.

    Runs on start while the ownership table is still empty (a fresh
    install has no files yet, so this is a no-op there): every library
    file becomes the migration user's, and pre-feature likes,
    playlists, batches, monitor watches and
    discover history take the same owner. Later arrivals record their
    real downloader instead. Returns what was attributed.
    """

    done = {
        'files': 0,
        'likes': 0,
        'playlists': 0,
        'batches': 0,
        'watches': 0,
        'listens': 0,
    }
    owners = state.track_owners
    if owners is None or not owners.is_empty():
        return done
    user_id = resolve_migration_user_id()
    if not user_id:
        logger.warning(
            'Ownership backfill: no users yet, will retry on next start'
        )
        return done
    try:
        paths = list_library_paths(library_context())
    except Exception:
        logger.opt(exception=True).warning(
            'Ownership backfill: could not list the library'
        )
        return done
    claimed = 0
    for stored in paths:
        try:
            key = stored_content_key(stored)
        except Exception:
            continue
        name = str(stored or '').strip().replace('\\', '/')
        if key and owners.add(key, user_id, name):
            claimed += 1
    done['files'] = claimed

    def _migrate(label: str, store: Any, method: str) -> None:
        if store is None:
            return
        try:
            done[label] = getattr(store, method)(user_id)
        except Exception:
            logger.opt(exception=True).warning(
                'Ownership backfill: could not migrate {}', label
            )

    _migrate('likes', state.likes, 'reassign_legacy')
    _migrate('playlists', state.playlist_catalog, 'reassign_legacy')
    _migrate('batches', state.playlist_batch_store, 'reassign_legacy')
    _migrate('watches', state.monitor_db, 'reassign_legacy')
    _migrate('listens', state.discover, 'reassign_legacy')
    if any(done.values()):
        logger.info(
            'Ownership backfill: {} file(s), {} like(s), {} playlist(s), '
            '{} batch(es), {} watch(es), {} listen row(s)'
            ' now belong to user {}',
            done['files'],
            done['likes'],
            done['playlists'],
            done['batches'],
            done['watches'],
            done['listens'],
            user_id,
        )
        if state.library_sync is not None:
            try:
                state.library_sync.touch_all()
            except Exception:
                logger.opt(exception=True).debug(
                    'Ownership backfill: could not poke the sync feed'
                )
    return done


def forget_library_file(stored_path: str) -> list[str]:
    """Drop a deleted file from the library stores.

    Removes it from the track index, playlist catalog, Navidrome song-id
    index and the metadata/cover caches, all keyed by its library path
    (the file itself is already gone). Returns the playlists it belonged
    to.
    """

    name = str(stored_path or '').strip().replace('\\', '/')
    if not name:
        return []
    affected: list[str] = []
    if state.playlist_catalog is not None:
        affected = state.playlist_catalog.remove_tracks_for_filename(name)
    if state.track_index is not None:
        state.track_index.remove_by_filename(name)
    if state.navidrome_index is not None:
        state.navidrome_index.forget_filename(name)
    if state.metadata_cache is not None:
        state.metadata_cache.forget(name)
    if state.cover_cache is not None:
        state.cover_cache.forget_by_stored_path(name)
    if state.likes is not None:
        state.likes.unlike(name)
    return affected


def _fetch_playlist_tracks(
    spotify_playlist_id: str,
    *,
    refresh: bool = False,
) -> tuple[str, list[dict[str, Any]]]:
    return fetch_playlist_tracks(
        spotify_playlist_id,
        cache=state.playlist_spotify_cache,
        refresh=refresh,
    )


def _playlists_for_successful_download(
    song: dict[str, Any],
    *,
    primary_playlist: Optional[str] = None,
) -> set[str]:
    """Playlist names that should be refreshed after this track succeeds."""

    names: set[str] = set()
    primary = str(primary_playlist or '').strip()
    if primary:
        names.add(primary)
    tid = normalize_spotify_track_id(song)
    if not tid:
        return names
    if state.playlist_catalog is not None:
        names.update(state.playlist_catalog.playlists_for_track(tid))
    if state.monitor_db is not None:
        names.update(state.monitor_db.playlists_for_track(tid))
    return names


async def _schedule_playlist_refresh_after_download(
    playlist_names: set[str],
) -> None:
    if not playlist_names or state.downloader is None:
        return
    if state.playlist_catalog is None:
        return

    async def _run() -> None:
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
                navidrome_scan=bool(
                    state.settings.get('navidrome', {}).get(
                        'scan_after_download', True
                    )
                ),
                playlist_spotify_cache=state.playlist_spotify_cache,
                cover_cache=state.cover_cache,
                metadata_cache=state.metadata_cache,
            )
        except Exception:
            logger.exception(
                'download: playlist refresh failed for {}',
                ', '.join(sorted(playlist_names)[:5]),
            )

    spawn_task(_run(), name='playlist-refresh-after-download')


# Defaults that changed for new installs. A settings file saved before,
# without the key, keeps the old default: turning organizing on by itself
# would scatter an existing library's new downloads into other folders.
_PREVIOUS_DEFAULTS: dict[str, Any] = {
    'organize_by_artist': False,
    'organize_by_album': False,
    'download_cover_art_playlists': False,
    'download_cover_art_artist': False,
}


def _load_settings(path: Path) -> dict[str, Any]:
    """Load saved settings from *path*, merging with DEFAULT_SETTINGS as base."""
    try:
        saved = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(saved, dict):
            merged = {**DEFAULT_SETTINGS, **_PREVIOUS_DEFAULTS}
            for k, v in saved.items():
                if k not in DEFAULT_SETTINGS:
                    continue
                if k in _NESTED_SETTINGS and isinstance(v, dict):
                    merged[k] = {**DEFAULT_SETTINGS[k], **v}
                else:
                    merged[k] = v
            merged['max_parallel_downloads'] = _clamp_parallel_downloads(
                merged['max_parallel_downloads']
            )
            merged['download_delay_seconds'] = _clamp_download_delay(
                merged['download_delay_seconds']
            )
            merged['max_track_duration_seconds'] = _clamp_track_duration(
                merged.get(
                    'max_track_duration_seconds',
                    DEFAULT_SETTINGS['max_track_duration_seconds'],
                )
            )
            merged['external_sync_delay_seconds'] = _clamp_download_delay(
                merged.get(
                    'external_sync_delay_seconds',
                    DEFAULT_SETTINGS['external_sync_delay_seconds'],
                )
            )
            merged['cover_resolution'] = _clamp_cover_resolution(
                merged['cover_resolution']
            )
            merged['library_only'] = merged.get('library_only') is True
            merged['ui_language'] = _clean_ui_language(merged['ui_language'])
            merged['external_library'] = effective_external_library(merged)
            normalize_lyrics_location(merged)
            return merged
    except Exception:
        pass
    return dict(DEFAULT_SETTINGS)


def _save_settings(path: Path, settings: dict[str, Any]) -> None:
    try:
        path.write_text(json.dumps(settings, indent=2), encoding='utf-8')
    except Exception as exc:
        logger.warning('Could not persist settings: {}', exc)


def _library_dirs() -> tuple[Path, Optional[Path]]:
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
    return download_dir, slskd_dir


def normalize_lyrics_location(settings: dict[str, Any]) -> None:
    """Keep ``lyrics_lrc_*`` keys valid against the current music trees."""

    download_dir, slskd_dir = _library_dirs()
    extra = extra_dirs_from_settings(settings, download_dir, slskd_dir)
    settings['lyrics_lrc_beside'] = lyrics.coerce_bool(
        settings.get('lyrics_lrc_beside'), True
    )
    settings['lyrics_lrc_dir'] = lyrics.sanitize_lyrics_lrc_dir(
        settings.get('lyrics_lrc_dir'),
        download_dir=download_dir,
        slskd_dir=slskd_dir,
        extra_dirs=extra,
    )


def bind_lrc_resolver() -> None:
    """Point sidecar writes at the live settings (folder vs beside)."""

    def _resolve(audio: Path) -> Path:
        ctx = library_context()
        deemix = _effective_deemix_settings(state.settings)
        if deemix['enabled']:
            try:
                audio.resolve().relative_to(
                    Path(deemix['source_dir']).resolve()
                )
                beside = audio.with_suffix('.lrc')
                if beside.is_file():
                    return beside
            except (OSError, ValueError):
                pass
        return lyrics.lrc_sidecar_path(
            audio,
            settings=state.settings,
            download_dir=ctx.download_dir,
            slskd_dir=ctx.slskd_dir,
            extra_dirs=ctx.extra_dirs,
        )

    def _root() -> Optional[Path]:
        return Path(
            str(
                state.settings.get('lyrics_lrc_dir')
                or lyrics.DEFAULT_LYRICS_LRC_DIR
            )
        )

    def _search(audio: Path) -> list[Path]:
        ctx = library_context()
        dedicated = lyrics.lrc_sidecar_path(
            audio,
            settings={**state.settings, 'lyrics_lrc_beside': False},
            download_dir=ctx.download_dir,
            slskd_dir=ctx.slskd_dir,
            extra_dirs=ctx.extra_dirs,
        )
        return [dedicated]

    lyrics.set_lrc_resolver(_resolve, tree_root=_root, search=_search)


def local_catalog_for_request(
    request: Optional[Request],
    query: str = '',
    limit: int = 25,
    *,
    collections: bool = False,
) -> dict[str, Any]:
    rows = library_only.catalog(entries_for_request(request), query, limit)
    if collections:
        rows['playlists'] = library_only.playlist_rows(
            playlists_for_request(request), limit
        )
        blocked = (
            state.discover.blocked_keys(request_user_id(request))
            if state.discover
            else set()
        )
        blocked = {library_only.text(name) for name in blocked}
        rows['artists'] = [
            row
            for row in rows['artists']
            if library_only.text(row['name']) not in blocked
        ]
        rows['albums'] = [
            row
            for row in rows['albums']
            if library_only.text(row['artist']) not in blocked
        ]
    return rows


def _artist_profile_download_dir() -> Path:
    return (
        Path(state.downloader.download_dir)
        if state.downloader is not None
        else Path('/downloads')
    )


def _artist_image_kinds_to_save(settings: dict[str, Any]) -> tuple[str, ...]:
    """Which of an artist's photo/banner Downtify may save on its own,
    per the user's ``download_cover_art_artist``/``..._banner`` settings.
    Only automatic saving is gated by them - the artist-art picker is
    always available and saves whatever the user picks."""

    return tuple(
        kind
        for kind, key in (
            (artist_profile.KIND_PHOTO, 'download_cover_art_artist'),
            (artist_profile.KIND_BANNER, 'download_cover_art_artist_banner'),
        )
        if settings.get(key)
    )


def _ui_language() -> str:
    """The language the web UI is shown in (see ``ui_language`` in
    ``DEFAULT_SETTINGS``), or ``fr`` - the web UI's default - while no
    page has said."""

    return str(state.settings.get('ui_language') or '') or 'fr'


def after_download(song: dict[str, Any], filename: str) -> None:
    """``Downloader.on_downloaded`` (set in ``main.py``): remember which
    provider fetched the new file, then seed its artist's profile. Runs on
    the download's own thread; never raises."""

    record_download_provider(song, filename)
    enrich_artist_after_download(song, filename)


def record_download_provider(song: dict[str, Any], filename: str) -> None:
    """Store ``song['download_provider']`` for *filename*, and the slskd
    transfer it was copied from (``song['download_source']``), see
    :mod:`downtify.file_providers` - best effort."""

    provider = str(song.get('download_provider') or '').strip()
    if not provider or state.file_providers is None:
        return
    try:
        state.file_providers.record(
            stored_content_key(filename),
            filename,
            provider,
            str(song.get('download_source') or ''),
        )
    except Exception:
        logger.opt(exception=True).debug(
            'Could not record the provider of {}', filename
        )


def enrich_artist_after_download(song: dict[str, Any], filename: str) -> None:
    """``Downloader.on_downloaded``: a track just finished, so its artist's
    profile (bio, genre, origin, social links, platform ids) is seeded in the
    background if they have none yet - the same seeding as opening their
    Library page, see ``artist_profile.profile_seed_enqueue``.

    Photo and banner are saved only if the user's settings allow it, read
    now rather than at startup so a change applies to the very next track.
    The artist's top songs are deliberately left alone: they are made when
    their page is opened. Returns at once and never raises - this runs on
    the download's own thread.
    """

    try:
        artist_profile.profile_seed_enqueue(
            _artist_profile_download_dir(),
            song,
            _ui_language(),
            _artist_image_kinds_to_save(state.settings),
        )
    except Exception:
        logger.opt(exception=True).debug(
            'Could not queue the artist profile of {}', filename
        )


def claim_pending_playlist_songs(song: dict[str, Any], filename: str) -> bool:
    """A song some Library playlists were waiting on is now *filename*:
    write it at the end of each (see :mod:`downtify.playlist_pending`).
    True when a playlist changed. Never raises.

    Called once the file is registered in the library listing
    (:func:`_record_finished_download`, :func:`_finish_with_existing`):
    the playlist listing only keeps files the listing knows, so a claim
    any earlier would publish the playlist without its new song."""

    store = state.playlist_pending
    if store is None:
        return False
    changed = False
    try:
        keys = [str(song.get('song_id') or ''), str(song.get('url') or '')]
        names = store.claim(*keys)
        if not names:
            return False
        ctx = library_context()
        for name in names:
            try:
                edit_manual_playlist(ctx, name, add=[filename])
                changed = True
            except ManualPlaylistError as exc:
                logger.debug(
                    'Pending song {} not added to {!r}: {}',
                    filename,
                    name,
                    exc,
                )
    except Exception:
        logger.opt(exception=True).debug(
            'Could not add {} to the playlists waiting on it', filename
        )
    return changed


def record_download_outcome(
    song: dict[str, Any], outcome: str, filename: str = ''
) -> None:
    """``Downloader.on_outcome`` (set in ``main.py``), and the queue's own
    "already in library" check: log how a download ended, with the new
    file's size and provider (see :mod:`downtify.download_log`). Runs on
    the download's own thread; never raises."""

    log = state.download_log
    if log is None:
        return
    completed = outcome == OUTCOME_COMPLETED
    size = 0
    try:
        if completed and filename:
            full = resolve_library_file(filename, library_context())
            size = full.stat().st_size if full is not None else 0
        log.record(
            outcome,
            provider=str(song.get('download_provider') or '')
            if completed
            else '',
            size=size,
            filename=filename,
        )
    except Exception:
        logger.opt(exception=True).debug(
            'Could not log the download of {}', song.get('name')
        )
