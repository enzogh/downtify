"""Live streaming: a song plays while its audio is still arriving.

``GET /api/stream/file`` (see :mod:`downtify.stream`) downloads a whole
track into the stream cache before it sends the first byte, so a tap
on a song that isn't downloaded waits for the full download - it feels
like a download, not like a streaming service. ``GET
/api/stream/live`` is what the web player plays instead: the server
resolves the video's direct audio URL once (yt-dlp, same anti-bot
posture as a download, remembered until YouTube's URL expires) and
relays YouTube's bytes to the player as they arrive, forwarding the
player's ``Range`` requests so seeking works too. Nothing is written
to disk.

The relay stays server-side on purpose: the direct URL is bound to the
server's network (and YouTube may be unreachable from the browser), so
the browser only ever talks to this server.

YouTube throttles single large requests, so upstream is read in
``UPSTREAM_CHUNK_BYTES`` slices (what yt-dlp does too) while the
player sees one continuous response.

Failures surface as :class:`ValueError` (the endpoints map them to
``503``); a refused range is :class:`RangeNotSatisfiable` (``416``).
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import yt_dlp
from loguru import logger
from yt_dlp.networking import Request as YtRequest
from yt_dlp.networking.exceptions import HTTPError

from .downloader import is_age_restricted_error
from .ip_rotation import is_bot_check_error, run_with_ip_rotation
from .stream import _ydl_options, clean_video_id

#: Size of one upstream request (YouTube throttles bigger ones).
UPSTREAM_CHUNK_BYTES = 10 * 1024**2
#: Size of one piece relayed to the player.
RELAY_PIECE_BYTES = 64 * 1024
#: A resolved URL is forgotten this long before YouTube expires it.
EXPIRY_MARGIN_SECONDS = 120
#: Used when the URL carries no ``expire`` parameter.
DEFAULT_TTL_SECONDS = 60 * 60
#: Never trust a resolved URL longer than this.
MAX_TTL_SECONDS = 5 * 60 * 60
#: A URL resolved this recently is retried, not resolved again, on 403:
#: googlevideo sometimes refuses a brand-new URL for a moment.
FRESH_SOURCE_SECONDS = 30
#: Tries of a fresh URL after a 403, waiting a little longer each time.
MAX_FRESH_REFUSALS = 4
FRESH_REFUSAL_DELAY_SECONDS = 0.5
#: Player clients asked first when resolving a live stream. Each extra
#: client costs a round trip (and a PO Token for some), and these two
#: answer with playable audio; the full download list is the fallback.
DEFAULT_LIVE_PLAYER_CLIENTS = ('web_embedded', 'android')

_MEDIA_TYPES = {
    'm4a': 'audio/mp4',
    'mp4': 'audio/mp4',
    'webm': 'audio/webm',
    'opus': 'audio/ogg',
    'ogg': 'audio/ogg',
    'mp3': 'audio/mpeg',
}

_RANGE_RE = re.compile(r'^\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*$', re.I)
_CONTENT_RANGE_RE = re.compile(r'^\s*bytes\s+(\d+)-(\d+)/(\d+|\*)\s*$', re.I)


class RangeNotSatisfiable(ValueError):
    """The player asked for bytes past the end of the track."""

    def __init__(self, total: int) -> None:
        super().__init__(f'Range not satisfiable (size {total})')
        self.total = total


class UpstreamExpired(ValueError):
    """YouTube refused a resolved URL (expired or revoked)."""


@dataclass
class LiveSource:
    """One video's resolved direct audio URL and what we know of it."""

    url: str
    ext: str = ''
    headers: dict[str, str] = field(default_factory=dict)
    filesize: int = 0
    duration: float = 0.0
    expires_at: float = 0.0
    resolved_at: float = 0.0
    #: YouTube refuses the URL until then (epoch seconds; 0: unknown).
    available_at: float = 0.0

    @property
    def media_type(self) -> str:
        return _MEDIA_TYPES.get(self.ext.lower(), 'application/octet-stream')


def parse_range(header: Optional[str]) -> Optional[tuple[int, Optional[int]]]:
    """``(start, end)`` of a single ``bytes=`` range, ``None`` if absent.

    ``end`` is ``None`` for an open range (``bytes=100-``). Suffix
    ranges (``bytes=-500``) come back as ``(-500, None)`` and are
    resolved once the size is known. Anything unreadable is treated as
    no range at all (the whole track), which every player accepts.
    """

    match = _RANGE_RE.match(str(header or ''))
    if not match:
        return None
    first, last = match.group(1), match.group(2)
    if not first and not last:
        return None
    if not first:
        return (-int(last), None)
    start = int(first)
    end = int(last) if last else None
    if end is not None and end < start:
        return None
    return (start, end)


def parse_content_range(
    value: Optional[str],
) -> Optional[tuple[int, int, int]]:
    """``(start, end, total)`` of ``bytes a-b/total`` (``total`` -1: ``*``)."""

    match = _CONTENT_RANGE_RE.match(str(value or ''))
    if not match:
        return None
    total = match.group(3)
    return (
        int(match.group(1)),
        int(match.group(2)),
        -1 if total == '*' else int(total),
    )


def url_expiry(url: str, now: float) -> float:
    """When a resolved URL should be forgotten (epoch seconds)."""

    ttl = DEFAULT_TTL_SECONDS
    try:
        expire = int(parse_qs(urlparse(url).query).get('expire', [''])[0])
        ttl = expire - now - EXPIRY_MARGIN_SECONDS
    except (TypeError, ValueError):
        pass
    return now + max(0, min(ttl, MAX_TTL_SECONDS))


def _cookie_options(cookies_file: str) -> dict[str, Any]:
    opts: dict[str, Any] = {}
    resolved = str(cookies_file or '').strip()
    if resolved:
        opts['cookiefile'] = resolved
    cookies_browser = os.getenv('DOWNTIFY_COOKIES_FROM_BROWSER', '').strip()
    if cookies_browser:
        parts = cookies_browser.split(':', 1)
        opts['cookiesfrombrowser'] = tuple(parts)
    return opts


#: Never wait longer than this for a URL to become usable.
MAX_AVAILABILITY_WAIT_SECONDS = 8.0


def _available_at(info: dict[str, Any]) -> float:
    """When YouTube starts serving the chosen format (``0``: now).

    yt-dlp reports YouTube's ``available_at`` per format; before it,
    googlevideo answers ``403``."""

    wanted = info.get('format_id')
    for fmt in info.get('formats') or []:
        if isinstance(fmt, dict) and fmt.get('format_id') == wanted:
            try:
                return float(fmt.get('available_at') or 0)
            except (TypeError, ValueError):
                return 0.0
    try:
        return float(info.get('available_at') or 0)
    except (TypeError, ValueError):
        return 0.0


def live_player_clients() -> list[str]:
    """``DOWNTIFY_LIVE_PLAYER_CLIENTS``, else the quick default pair."""

    raw = os.getenv('DOWNTIFY_LIVE_PLAYER_CLIENTS', '').strip()
    clients = [c.strip() for c in raw.split(',') if c.strip()]
    return clients or list(DEFAULT_LIVE_PLAYER_CLIENTS)


def resolve_live_source(
    video_id: str, *, cookies_file: str = ''
) -> LiveSource:
    """Resolve *video_id* to its direct audio URL (blocking, no download).

    Raises :class:`ValueError` when YouTube refuses or can't be reached.
    The URL itself is never logged: it carries a signature.
    """

    vid = clean_video_id(video_id)

    def extract(clients: Optional[list[str]]) -> Any:
        opts = {**_ydl_options(), **_cookie_options(cookies_file)}
        if clients:
            opts['extractor_args']['youtube']['player_client'] = clients
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(
                f'https://www.youtube.com/watch?v={vid}', download=False
            )

    def attempt() -> Any:
        try:
            return extract(live_player_clients())
        except Exception as exc:
            message = str(exc)
            if is_bot_check_error(message) or is_age_restricted_error(message):
                raise
            # The quick clients had nothing: ask every client.
            logger.debug('Live stream quick resolve failed: {}', message)
            return extract(None)

    try:
        info = run_with_ip_rotation(attempt)
    except Exception as exc:
        if is_age_restricted_error(str(exc)):
            raise ValueError(
                'This track is age-restricted on YouTube: upload a '
                'YouTube cookies.txt in Settings > YouTube cookies '
                'to stream it.'
            ) from exc
        raise ValueError(
            f'YouTube did not answer: {type(exc).__name__}'
        ) from exc
    if not isinstance(info, dict) or not info.get('url'):
        raise ValueError('YouTube answered with an unreadable reply')
    url = str(info['url'])
    headers = {
        str(k): str(v)
        for k, v in dict(info.get('http_headers') or {}).items()
        if v is not None
    }
    source = LiveSource(
        url=url,
        ext=str(info.get('ext') or ''),
        headers=headers,
        # Only an exact size helps byte ranges (no ``filesize_approx``).
        filesize=int(info.get('filesize') or 0),
        duration=float(info.get('duration') or 0),
        expires_at=url_expiry(url, time.time()),
        resolved_at=time.time(),
        available_at=_available_at(info),
    )
    logger.info(
        'Live stream resolved for videoId={} ext={!r}', vid, source.ext
    )
    return source


#: ``opener(source, start, end) -> (content_range, reader, close)``:
#: one upstream request for bytes ``start..end`` (inclusive).
Opener = Callable[
    [LiveSource, int, int],
    tuple[Optional[str], Callable[[int], bytes], Callable[[], None]],
]


def ytdlp_opener(
    source: LiveSource, start: int, end: int
) -> tuple[Optional[str], Callable[[int], bytes], Callable[[], None]]:
    """Fetch bytes ``start..end`` of *source* through yt-dlp's networking.

    yt-dlp's stack keeps the same IPv4 / proxy behaviour as downloads.
    Raises :class:`UpstreamExpired` on ``403``/``404``/``410`` (the URL
    needs resolving again) and :class:`ValueError` otherwise.
    """

    opts: dict[str, Any] = {
        'quiet': True,
        'nocheckcertificate': True,
        'socket_timeout': 30,
    }
    if os.getenv('DOWNTIFY_FORCE_IPV4', '').strip() in {'1', 'true', 'yes'}:
        opts['source_address'] = '0.0.0.0'
    headers = {**source.headers, 'Range': f'bytes={start}-{end}'}
    ydl = yt_dlp.YoutubeDL(opts)
    try:
        response = ydl.urlopen(YtRequest(source.url, headers=headers))
    except HTTPError as exc:
        ydl.close()
        if exc.status == 416:
            raise RangeNotSatisfiable(source.filesize) from exc
        if exc.status in {403, 404, 410}:
            raise UpstreamExpired(f'YouTube answered {exc.status}') from exc
        raise ValueError(f'YouTube answered {exc.status}') from exc
    except Exception as exc:
        ydl.close()
        raise ValueError(
            f'YouTube did not answer: {type(exc).__name__}'
        ) from exc

    def close() -> None:
        try:
            response.close()
        finally:
            ydl.close()

    content_range = response.headers.get('Content-Range')
    if content_range is None and response.status == 200:
        # The whole body came back: describe it as a range anyway.
        length = int(response.headers.get('Content-Length') or 0)
        if length:
            content_range = f'bytes 0-{length - 1}/{length}'
    return content_range, response.read, close


@dataclass
class LiveResponse:
    """What to answer the player: status, headers, and the body."""

    status: int
    headers: dict[str, str]
    body: Iterator[bytes]
    media_type: str


class LiveStreams:
    """Resolved-URL memory plus the ranged relay (see module docstring).

    Concurrent requests for one video share one resolution; a URL is
    remembered until shortly before YouTube expires it, and forgotten
    (then resolved again, once) as soon as YouTube refuses it.
    """

    def __init__(
        self,
        *,
        resolver: Callable[..., LiveSource] = resolve_live_source,
        opener: Opener = ytdlp_opener,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_entries: int = 256,
    ) -> None:
        self._resolver = resolver
        self._opener = opener
        self._clock = clock
        self._sleep = sleep
        self._max_entries = max(1, int(max_entries))
        self._sources: dict[str, LiveSource] = {}
        self._pending: dict[str, asyncio.Future[LiveSource]] = {}

    def known(self, video_id: str) -> Optional[LiveSource]:
        """The remembered, still-valid source of *video_id*, if any."""

        source = self._sources.get(video_id)
        if source is None:
            return None
        if source.expires_at <= self._clock():
            self._sources.pop(video_id, None)
            return None
        return source

    def forget(self, video_id: str) -> None:
        self._sources.pop(video_id, None)

    async def source(
        self, video_id: str, *, cookies_file: str = ''
    ) -> LiveSource:
        """The direct audio source of *video_id*, resolving it if needed."""

        vid = clean_video_id(video_id)
        known = self.known(vid)
        if known is not None:
            return known
        pending = self._pending.get(vid)
        if pending is None:
            pending = asyncio.ensure_future(
                asyncio.to_thread(
                    self._resolver, vid, cookies_file=cookies_file
                )
            )
            self._pending[vid] = pending
            pending.add_done_callback(lambda _f: self._pending.pop(vid, None))
        source = await asyncio.shield(pending)
        self._remember(vid, source)
        return source

    def _remember(self, video_id: str, source: LiveSource) -> None:
        self._sources[video_id] = source
        while len(self._sources) > self._max_entries:
            self._sources.pop(next(iter(self._sources)))

    async def open(
        self,
        video_id: str,
        range_header: Optional[str],
        *,
        cookies_file: str = '',
        on_bytes: Optional[Callable[[int], None]] = None,
    ) -> LiveResponse:
        """The relayed response for one player request.

        ``on_bytes(n)`` runs once the body is finished (or abandoned)
        with the number of bytes relayed, so traffic can be counted.
        """

        vid = clean_video_id(video_id)
        wanted = parse_range(range_header)
        resolved_again = False
        refusals = 0
        while True:
            source = await self.source(vid, cookies_file=cookies_file)
            wait = min(
                source.available_at - self._clock(),
                MAX_AVAILABILITY_WAIT_SECONDS,
            )
            if wait > 0:
                # Asking earlier only earns a 403.
                await self._sleep(wait)
            try:
                return await asyncio.to_thread(
                    self._relay, source, wanted, on_bytes
                )
            except UpstreamExpired:
                fresh = (
                    self._clock() - source.resolved_at < FRESH_SOURCE_SECONDS
                )
                if fresh and refusals < MAX_FRESH_REFUSALS:
                    # A brand-new URL refused: it works a moment later,
                    # while resolving again would restart from zero.
                    refusals += 1
                    await self._sleep(FRESH_REFUSAL_DELAY_SECONDS * refusals)
                    continue
                self.forget(vid)
                if resolved_again:
                    raise
                resolved_again = True
                refusals = 0
                logger.debug('Live stream URL expired for videoId={}', vid)

    def _relay(
        self,
        source: LiveSource,
        wanted: Optional[tuple[int, Optional[int]]],
        on_bytes: Optional[Callable[[int], None]],
    ) -> LiveResponse:
        start, end = wanted if wanted else (0, None)
        if start < 0:
            # A suffix range needs the size first.
            total = source.filesize or self._probe_size(source)
            start, end = max(0, total + start), total - 1
        first_end = start + UPSTREAM_CHUNK_BYTES - 1
        if end is not None:
            first_end = min(first_end, end)
        if source.filesize:
            if start >= source.filesize:
                raise RangeNotSatisfiable(source.filesize)
            first_end = min(first_end, source.filesize - 1)
        content_range, read, close = self._opener(source, start, first_end)
        parsed = parse_content_range(content_range)
        total = source.filesize
        if parsed is not None and parsed[2] > 0:
            total = parsed[2]
            source.filesize = total
        if not total:
            close()
            raise ValueError('YouTube did not say how long the track is')
        last = total - 1 if end is None else min(end, total - 1)
        if start > last:
            close()
            raise RangeNotSatisfiable(total)
        length = last - start + 1
        headers = {
            'Accept-Ranges': 'bytes',
            'Content-Length': str(length),
            'Cache-Control': 'no-store',
        }
        status = 200
        if wanted is not None:
            status = 206
            headers['Content-Range'] = f'bytes {start}-{last}/{total}'
        body = self._body(
            source, start, last, (read, close), on_bytes=on_bytes
        )
        return LiveResponse(status, headers, body, source.media_type)

    def _probe_size(self, source: LiveSource) -> int:
        content_range, _read, close = self._opener(source, 0, 0)
        close()
        parsed = parse_content_range(content_range)
        if parsed is None or parsed[2] <= 0:
            raise ValueError('YouTube did not say how long the track is')
        source.filesize = parsed[2]
        return parsed[2]

    def _body(
        self,
        source: LiveSource,
        start: int,
        last: int,
        first: tuple[Callable[[int], bytes], Callable[[], None]],
        *,
        on_bytes: Optional[Callable[[int], None]],
    ) -> Iterator[bytes]:
        read, close = first
        position = start
        sent = 0
        fresh = True
        try:
            while position <= last:
                piece = read(min(RELAY_PIECE_BYTES, last - position + 1))
                if piece:
                    position += len(piece)
                    sent += len(piece)
                    fresh = False
                    yield piece
                    continue
                close()
                close = _noop
                if fresh:
                    # A new slice gave nothing: YouTube stopped short.
                    logger.debug('Live stream ended early at {}', position)
                    break
                # This upstream slice is done: open the next one.
                fresh = True
                slice_end = min(last, position + UPSTREAM_CHUNK_BYTES - 1)
                _range, read, close = self._opener(source, position, slice_end)
        except UpstreamExpired:
            logger.debug('Live stream URL expired mid-track')
        finally:
            close()
            if on_bytes is not None and sent:
                try:
                    on_bytes(sent)
                except Exception:
                    logger.opt(exception=True).debug(
                        'Could not count live stream bytes'
                    )


def _noop() -> None:
    return None
