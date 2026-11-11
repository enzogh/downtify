"""Audio served from a second hostname that skips the CDN.

A server behind a CDN or tunnel (Cloudflare, say) pays for, or is
limited on, every byte that goes through it, and audio is most of them.
``DOWNTIFY_DIRECT_STREAM_URL`` names another address of this same server
that reaches it directly (a DNS-only record): a signed-in request for a
song's audio that arrives on any other hostname is answered with a
redirect there, to the same path with a signed URL (``exp``, ``kid``,
``sig`` - see :class:`downtify.auth.UrlSigner`), since the browser's
cookie and the app's token header don't follow it to another host.

The page, the API and covers keep going through the CDN; only the bytes
of the audio don't. The signed URL works for the session or device that
asked: signing out or revoking the device stops it. Each redirect is a
few hundred bytes through the CDN.

Left alone:

* requests already on the direct hostname, or on an IP address or
  ``localhost`` (a LAN or local client gains nothing);
* page navigations (a "Download" link opened in the tab), which would
  show the other hostname in the address bar;
* anything but ``GET``/``HEAD``.
"""

from __future__ import annotations

import math
import os
import re
import time
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any, Optional
from urllib.parse import parse_qsl, quote, urlsplit

from loguru import logger

from .auth import AuthStore, Principal, session_cookie

#: Paths whose response is a song's audio.
STREAM_PATH = re.compile(
    r'^/(downloads|media)/'
    r'|^/api/v1/tracks/[^/]+/stream$'
    r'|^/api/stream/(file|live)$'
)
#: How long a redirect's signed URL works. A player keeps using the URL
#: it was sent to for the whole song, a paused one included.
SIGNED_TTL_SECONDS = 12 * 3600
#: Expiries are rounded up to this, so a song asked for twice within it
#: gets the same URL (and the browser's cached copy).
_EXPIRY_STEP_SECONDS = 3600

ASGIApp = Callable[..., Awaitable[None]]


@dataclass(frozen=True)
class DirectStreamConfig:
    """Where audio is sent: ``base_url`` (scheme and host, no path)."""

    base_url: str
    host: str

    @classmethod
    def parse(cls, raw: str) -> Optional[DirectStreamConfig]:
        text = (raw or '').strip().rstrip('/')
        if not text:
            return None
        parts = urlsplit(text)
        if (
            parts.scheme not in {'http', 'https'}
            or not parts.netloc
            or parts.path
            or parts.query
            or '@' in parts.netloc
        ):
            logger.warning(
                'DOWNTIFY_DIRECT_STREAM_URL: ignoring {!r} (expected '
                'https://host)',
                raw,
            )
            return None
        host = parts.netloc.lower()
        return cls(base_url=f'{parts.scheme}://{host}', host=host)

    @classmethod
    def from_env(cls) -> Optional[DirectStreamConfig]:
        """``DOWNTIFY_DIRECT_STREAM_URL``, or ``None`` when unset."""

        return cls.parse(os.getenv('DOWNTIFY_DIRECT_STREAM_URL', ''))


def _header(scope: MutableMapping[str, Any], name: str) -> str:
    wanted = name.encode()
    for key, value in scope.get('headers') or []:
        if key.lower() == wanted:
            return value.decode('latin-1')
    return ''


def _bare_host(host: str) -> str:
    """*host* without its port (and IPv6 brackets)."""

    if host.startswith('['):
        return host[1 : host.find(']')] if ']' in host else host
    return host.rsplit(':', 1)[0] if host.count(':') == 1 else host


def _is_local_host(host: str) -> bool:
    bare = _bare_host(host)
    if bare == 'localhost' or bare.endswith('.localhost'):
        return True
    try:
        ip_address(bare)
    except ValueError:
        return False
    return True


def _expiry(now: float) -> int:
    step = _EXPIRY_STEP_SECONDS
    return int(math.ceil((now + SIGNED_TTL_SECONDS) / step) * step)


def _signing_key(
    scope: MutableMapping[str, Any], principal: Principal, store: AuthStore
) -> str:
    """The ``kid`` to sign for: the app's device, or the browser's
    session. ``''`` when there is nothing to sign for."""

    if principal.kind == 'device' and principal.device_id:
        return principal.device_id
    if principal.kind == 'session':
        token = session_cookie(scope)
        return store.session_kid(token) if token else ''
    return ''


def redirect_location(
    scope: MutableMapping[str, Any],
    config: DirectStreamConfig,
    store: AuthStore,
    *,
    now: Optional[float] = None,
) -> Optional[str]:
    """Where to send this request instead, or ``None`` to serve it."""

    if scope.get('type') != 'http':
        return None
    if scope.get('method') not in {'GET', 'HEAD'}:
        return None
    path = scope.get('path', '')
    if not STREAM_PATH.search(path):
        return None
    host = _header(scope, 'host').lower()
    if not host or host == config.host or _is_local_host(host):
        return None
    if _header(scope, 'sec-fetch-mode') == 'navigate':
        return None
    principal = (scope.get('state') or {}).get('principal')
    if principal is None:
        return None
    raw_path = scope.get('raw_path')
    target = (
        raw_path.decode('latin-1')
        if isinstance(raw_path, bytes) and raw_path
        else quote(path)
    )
    query = (scope.get('query_string') or b'').decode('latin-1')
    if principal.kind in {'signed', 'open'}:
        # Already carries its signature (a Cast receiver), or nobody
        # signs in at all: the same URL works on the other host.
        suffix = f'?{query}' if query else ''
        return f'{config.base_url}{target}{suffix}'
    kid = _signing_key(scope, principal, store)
    if not kid:
        return None
    params = parse_qsl(query, keep_blank_values=True)
    signed = store.signer.sign_url(
        path,
        params,
        device_id=kid,
        expires_at=_expiry(time.time() if now is None else now),
    )
    # sign_url returns the decoded path; keep the client's own encoding.
    return f'{config.base_url}{target}{signed[len(path) :]}'


class DirectStreamMiddleware:
    """Redirects audio requests to :class:`DirectStreamConfig`'s host.

    Runs inside :class:`downtify.auth.AuthMiddleware`, which has already
    checked the request and put its principal in the scope.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        get_config: Callable[[], Optional[DirectStreamConfig]],
        get_store: Callable[[], Optional[AuthStore]],
    ) -> None:
        self.app = app
        self._get_config = get_config
        self._get_store = get_store

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: Callable[..., Awaitable[Any]],
        send: Callable[..., Awaitable[None]],
    ) -> None:
        config = self._get_config()
        store = self._get_store()
        location = (
            redirect_location(scope, config, store)
            if config is not None and store is not None
            else None
        )
        if location is None:
            await self.app(scope, receive, send)
            return
        await send({
            'type': 'http.response.start',
            'status': 307,
            'headers': [
                (b'location', location.encode('latin-1')),
                (b'cache-control', b'no-store'),
                (b'content-length', b'0'),
            ],
        })
        await send({'type': 'http.response.body', 'body': b''})
