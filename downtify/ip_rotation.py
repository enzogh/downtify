"""Get a fresh exit IP when YouTube blocks the current one.

On datacenter and VPN IPs YouTube sometimes answers every request with
"Sign in to confirm you're not a bot", whatever the client or token.
The IP itself is flagged; a new one works again. When
``DOWNTIFY_IP_ROTATE_URL`` points at a control endpoint (e.g. the
``contrib/warp-control`` sidecar that reconnects Cloudflare WARP), a
blocked download or stream asks it for a new IP and retries, without
the user noticing.

Several downloads run in parallel and usually hit the block together:
a rotation *generation* makes sure they share one rotation instead of
each forcing its own.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Optional, TypeVar

import requests
from loguru import logger

T = TypeVar('T')

ENV_URL = 'DOWNTIFY_IP_ROTATE_URL'
ENV_TOKEN = 'DOWNTIFY_IP_ROTATE_TOKEN'

#: New IPs tried for one download or stream before giving up.
MAX_ROTATIONS_PER_ATTEMPT = 3
#: Rotations allowed per hour, so a YouTube-wide outage can't loop.
MAX_ROTATIONS_PER_HOUR = 30
#: The control endpoint waits for the tunnel; give it time.
ROTATE_TIMEOUT_SECONDS = 45
#: Extra tries after YouTube's passing 403 on the media.
MAX_REFUSAL_RETRIES = 2
#: Wait before a retry after a 403 (times the retry's number).
REFUSAL_RETRY_DELAY_SECONDS = 1.5

_BOT_CHECK_FRAGMENTS = (
    'confirm you’re not a bot',
    "confirm you're not a bot",
)

_lock = threading.Lock()
_generation = 0
_recent: deque[float] = deque()


def is_bot_check_error(message: str) -> bool:
    """Whether a yt-dlp error is YouTube's "not a bot" check."""

    lowered = message.lower()
    return any(fragment in lowered for fragment in _BOT_CHECK_FRAGMENTS)


def rotation_url() -> str:
    """The control endpoint, or ``''`` when rotation is off."""

    return os.getenv(ENV_URL, '').strip()


def current_generation() -> int:
    """Read before an attempt; pass to :func:`rotate_exit_ip` on failure."""

    return _generation


def _post_rotation(url: str) -> None:
    headers = {}
    token = os.getenv(ENV_TOKEN, '').strip()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    # The endpoint lives next to the proxy, never behind it.
    with requests.Session() as session:
        session.trust_env = False
        response = session.post(
            url, headers=headers, timeout=ROTATE_TIMEOUT_SECONDS
        )
    response.raise_for_status()


def rotate_exit_ip(seen_generation: int, now: Optional[float] = None) -> bool:
    """Make sure the exit IP changed since *seen_generation*.

    Returns ``True`` when a retry is worth it: another download already
    rotated since the caller's attempt began, or this call just did.
    ``False`` when rotation is off, over its hourly budget, or failed.
    """

    global _generation
    url = rotation_url()
    if not url:
        return False
    with _lock:
        if _generation != seen_generation:
            return True
        moment = time.time() if now is None else now
        while _recent and moment - _recent[0] > 3600:
            _recent.popleft()
        if len(_recent) >= MAX_ROTATIONS_PER_HOUR:
            logger.warning(
                'YouTube blocked this IP but {} new IPs were already '
                'tried this hour; not rotating again',
                len(_recent),
            )
            return False
        _recent.append(moment)
        try:
            _post_rotation(url)
        except Exception as exc:
            logger.warning('Could not get a new exit IP: {}', exc)
            return False
        _generation += 1
        logger.info('YouTube blocked the exit IP; switched to a new one')
        return True


def is_transient_refusal(message: str) -> bool:
    """Whether yt-dlp hit YouTube's passing ``403`` on the media itself.

    googlevideo sometimes refuses a fresh URL for a few seconds; the
    same song works on the next try."""

    return 'http error 403' in message.lower()


_HICCUP_FRAGMENTS = (
    'http error 403',
    'http error 429',
    'too many requests',
    'timed out',
    'connection reset',
    'connection aborted',
    'remote end closed',
    'temporary failure in name resolution',
    'unable to connect to proxy',
)


def is_youtube_hiccup(message: str) -> bool:
    """Whether a failed download is worth trying again later.

    YouTube's blocks and the network's hiccups pass; a missing video,
    an age wall or a too-long track never do."""

    lowered = message.lower()
    return is_bot_check_error(lowered) or any(
        fragment in lowered for fragment in _HICCUP_FRAGMENTS
    )


def run_with_ip_rotation(
    attempt: Callable[[], T],
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run *attempt*, riding out YouTube's blocks.

    A bot check gets a new IP and another run (up to
    :data:`MAX_ROTATIONS_PER_ATTEMPT`); a passing ``403`` gets up to
    :data:`MAX_REFUSAL_RETRIES` more runs, a little later each time.
    """

    rotations = 0
    refusals = 0
    while True:
        seen = current_generation()
        try:
            return attempt()
        except Exception as exc:
            message = str(exc)
            if is_transient_refusal(message):
                if refusals >= MAX_REFUSAL_RETRIES:
                    raise
                refusals += 1
                sleep(REFUSAL_RETRY_DELAY_SECONDS * refusals)
                continue
            if (
                rotations >= MAX_ROTATIONS_PER_ATTEMPT
                or not is_bot_check_error(message)
                or not rotate_exit_ip(seen)
            ):
                raise
            rotations += 1
