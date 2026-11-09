"""Public song links (see :mod:`downtify.song_links`).

Signed in (``/api/song-links``, a ``user`` scope):

* ``POST   /api/song-links`` - body ``{file}`` (a library song) or
  ``{song: {video_id, title, artist, album, duration, cover_url,
  explicit}}`` (one that isn't downloaded): the caller's link to it,
  ``{token, path, kind, file, created_at}`` - the same one when asked
  again. ``403`` while the admin's ``allow_song_links`` is off (and, for
  a song that isn't downloaded, in library-only mode); ``404`` for a
  library song the caller can't see; ``400`` for a malformed song.
* ``GET    /api/song-links`` - ``{enabled, links}``: the caller's links,
  newest first, each ``{token, path, kind, file, title, artist,
  created_at, available}``.
* ``DELETE /api/song-links/{token}`` - revoke one (its maker, or an
  admin).

Public, no sign-in (outside the protected prefixes of
:mod:`downtify.auth`): ``GET /s/{token}`` (the web app's share page, with
Open Graph tags for link previews), ``GET /s/{token}/info`` (what that
page shows), ``GET|HEAD /s/{token}/audio`` (a library file with Range,
or the video relayed live like ``/api/stream/live``) and ``GET
/s/{token}/cover``. A link whose song is gone, hidden from users by an
admin, or switched off by ``allow_song_links`` answers ``404`` - the
same as an unknown token, so a link never tells more than the song it
was made for.
"""

from __future__ import annotations

import asyncio
import html
import re
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)

from . import api, library_only, stream
from .cover_art import extract_cover_art
from .library_cache_keys import file_content_key
from .library_catalog import (
    entry_content_key,
    list_entries_for_stored_paths,
    resolve_library_file,
)
from .mobile_routes import audio_media_type
from .song_links import STREAM, SongLink, SongLinks, StreamSong

router = APIRouter()

#: Shared pages are for whoever was sent the link, not search engines.
_PUBLIC_HEADERS = {
    'X-Robots-Tag': 'noindex, nofollow',
    'Referrer-Policy': 'no-referrer',
}

_TEXT_LIMIT = 300


class _Spa:
    """The web app's ``index.html`` (set by ``main.py``): the share page
    is one of its routes, served with the song's Open Graph tags."""

    index: Optional[Path] = None


def set_spa_index(path: Optional[Path]) -> None:
    _Spa.index = path


def links_enabled() -> bool:
    """Whether the admin lets users make public song links (Settings)."""

    return bool(api.state.settings.get('allow_song_links', True))


def _streams_allowed() -> bool:
    return not library_only.enabled(api.state.settings)


def _store() -> SongLinks:
    store = api.state.song_links
    if store is None:
        raise HTTPException(status_code=503, detail='Not ready')
    return store


def _resolve(stored: str) -> Optional[Path]:
    """The library file *stored* names - never one in the trash or in a
    folder hidden from the library."""

    ctx = api.library_context()
    full = resolve_library_file(stored, ctx)
    if full is None:
        return None
    resolved = full.resolve()
    if '.downtify-trash' in resolved.parts:
        return None
    if str(resolved) in ctx.hidden_resolved:
        return None
    return full


def _entry(stored: str) -> Optional[dict[str, Any]]:
    rows = list_entries_for_stored_paths(api.library_context(), [stored])
    return rows[0] if rows else None


def _hidden_from_users(entry: dict[str, Any]) -> bool:
    return api.hidden_rules().hides(entry)


def _artist(entry: dict[str, Any]) -> str:
    artists = entry.get('artists')
    if isinstance(artists, list) and artists:
        return ', '.join(str(a) for a in artists if a)
    return str(entry.get('artist') or '')


def _title(entry: dict[str, Any]) -> str:
    return str(entry.get('title') or Path(str(entry.get('file'))).stem)


def _text(value: Any) -> str:
    return str(value or '').strip()[:_TEXT_LIMIT]


def _web_url(value: Any) -> str:
    raw = str(value or '').strip()
    if len(raw) > 2048 or not re.match(r'^https?://', raw):
        return ''
    return raw


def _stream_song(payload: Any) -> StreamSong:
    """The song a ``{song}`` body describes, or ``400``."""

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail='No song given')
    try:
        video_id = stream.clean_video_id(payload.get('video_id'))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    title = _text(payload.get('title'))
    if not title:
        raise HTTPException(status_code=400, detail='The song has no title')
    try:
        duration = max(0.0, float(payload.get('duration') or 0))
    except (TypeError, ValueError):
        duration = 0.0
    return StreamSong(
        video_id=video_id,
        title=title,
        artist=_text(payload.get('artist')),
        album=_text(payload.get('album')),
        duration=duration,
        cover_url=_web_url(payload.get('cover_url')),
        explicit=payload.get('explicit') is True,
    )


def _urls(link: SongLink) -> dict[str, str]:
    return {
        'audio_url': f'/s/{link.token}/audio',
        'cover_url': f'/s/{link.token}/cover',
    }


def _file_info(link: SongLink, entry: dict[str, Any]) -> dict[str, Any]:
    duration = entry.get('duration')
    return {
        'title': _title(entry),
        'artist': _artist(entry),
        'album': str(entry.get('album') or ''),
        'duration': float(duration) if duration else 0,
        'explicit': bool(entry.get('explicit')),
        'has_cover': bool(entry.get('has_cover', True)),
        **_urls(link),
    }


def _stream_info(link: SongLink, song: StreamSong) -> dict[str, Any]:
    return {
        'title': song.title,
        'artist': song.artist,
        'album': song.album,
        'duration': song.duration,
        'explicit': song.explicit,
        'has_cover': bool(song.cover_url),
        **_urls(link),
    }


def _public_song(
    token: str,
) -> tuple[SongLink, dict[str, Any], Optional[Path]]:
    """The link, what its page shows and - for a library song - its
    file; ``404`` for anything that shouldn't play."""

    missing = HTTPException(status_code=404, detail='Link not found')
    if not links_enabled():
        raise missing
    link = _store().get(token)
    if link is None:
        raise missing
    if link.kind == STREAM:
        if link.song is None or not _streams_allowed():
            raise missing
        return link, _stream_info(link, link.song), None
    full = _resolve(link.path)
    if full is None:
        raise missing
    entry = _entry(link.path)
    if entry is None or _hidden_from_users(entry):
        raise missing
    return link, _file_info(link, entry), full


def _link_row(link: SongLink) -> dict[str, Any]:
    return {
        'token': link.token,
        'path': f'/s/{link.token}',
        'kind': link.kind,
        'file': link.path,
        'created_at': link.created_at,
    }


# ── Signed in ───────────────────────────────────────────────────────────


@router.post('/api/song-links')
async def create_song_link(request: Request) -> dict[str, Any]:
    payload = await api._json_object(request)
    stored = str(payload.get('file') or '').strip().replace('\\', '/')
    song = payload.get('song')
    if not stored and song is None:
        raise HTTPException(status_code=400, detail='No song given')
    if not links_enabled():
        raise HTTPException(
            status_code=403, detail='Public song links are turned off'
        )
    user_id = api.request_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail='Sign in first')

    if not stored:
        if not _streams_allowed():
            raise HTTPException(
                status_code=403,
                detail='Only library songs can be shared in library-only mode',
            )
        wanted = _stream_song(song)
        made = await asyncio.to_thread(_store().create_stream, wanted, user_id)
        return _link_row(made)

    def make() -> SongLink:
        full = _resolve(stored)
        entry = _entry(stored) if full is not None else None
        if full is None or entry is None:
            raise HTTPException(status_code=404, detail='Song not found')
        allowed = api.allowed_entry_keys(request)
        if allowed is not None and entry_content_key(entry) not in allowed:
            raise HTTPException(status_code=404, detail='Song not found')
        return _store().create(stored, file_content_key(full) or '', user_id)

    link = await asyncio.to_thread(make)
    return _link_row(link)


@router.get('/api/song-links')
async def list_song_links(request: Request) -> dict[str, Any]:
    user_id = api.request_user_id(request)

    def row(link: SongLink) -> dict[str, Any]:
        if link.song is not None:
            return {
                **_link_row(link),
                'title': link.song.title,
                'artist': link.song.artist,
                'available': _streams_allowed(),
            }
        entry = _entry(link.path)
        return {
            **_link_row(link),
            'title': _title(entry) if entry else '',
            'artist': _artist(entry) if entry else '',
            'available': entry is not None and _resolve(link.path) is not None,
        }

    def rows() -> list[dict[str, Any]]:
        return [row(link) for link in _store().for_user(user_id)]

    return {
        'enabled': links_enabled(),
        'links': await asyncio.to_thread(rows) if user_id else [],
    }


@router.delete('/api/song-links/{token}')
async def revoke_song_link(token: str, request: Request) -> dict[str, Any]:
    store = _store()
    link = await asyncio.to_thread(store.get, token)
    if link is None:
        raise HTTPException(status_code=404, detail='Link not found')
    if link.user_id != api.request_user_id(
        request
    ) and not api.request_is_admin(request):
        raise HTTPException(status_code=403, detail='Not your link')
    await asyncio.to_thread(store.revoke, token)
    return {'revoked': True}


# ── Public ──────────────────────────────────────────────────────────────


@router.get('/s/{token}/info')
async def song_link_info(token: str) -> JSONResponse:
    _link, info, _full = await asyncio.to_thread(_public_song, token)
    return JSONResponse(info, headers=_PUBLIC_HEADERS)


@router.api_route('/s/{token}/audio', methods=['GET', 'HEAD'])
async def song_link_audio(token: str, request: Request) -> Response:
    link, info, full = await asyncio.to_thread(_public_song, token)
    if full is None and link.song is not None:
        # Not downloaded: relayed from YouTube, counted to the maker.
        response = await api.relay_live_audio(
            request,
            link.song.video_id,
            float(info['duration'] or 0),
            user_id=link.user_id,
        )
        response.headers.update(_PUBLIC_HEADERS)
        return response
    if full is None:
        raise HTTPException(status_code=404, detail='Link not found')
    return FileResponse(
        full,
        media_type=audio_media_type(full),
        headers={**_PUBLIC_HEADERS, 'Cache-Control': 'private, max-age=600'},
    )


@router.get('/s/{token}/cover')
async def song_link_cover(token: str) -> Response:
    link, _info, full = await asyncio.to_thread(_public_song, token)
    if full is None:
        cover = link.song.cover_url if link.song else ''
        if not cover:
            raise HTTPException(status_code=404, detail='No cover')
        return RedirectResponse(
            cover, status_code=302, headers=_PUBLIC_HEADERS
        )
    data, mime = await asyncio.to_thread(extract_cover_art, full)
    if data is None:
        raise HTTPException(status_code=404, detail='No cover')
    return Response(
        content=data,
        media_type=mime or 'image/jpeg',
        headers={**_PUBLIC_HEADERS, 'Cache-Control': 'public, max-age=3600'},
    )


@router.get('/s/{token}', response_class=HTMLResponse)
async def song_link_page(token: str, request: Request) -> HTMLResponse:
    index = _Spa.index
    shell = ''
    if index is not None and index.is_file():
        shell = await asyncio.to_thread(index.read_text, encoding='utf-8')
    headers = {**_PUBLIC_HEADERS, 'Cache-Control': 'no-store'}
    try:
        _link, info, _full = await asyncio.to_thread(_public_song, token)
    except HTTPException as exc:
        if exc.status_code != 404 or not shell:
            raise
        # The app says the link doesn't work - and nothing else.
        return HTMLResponse(missing_page(shell), 404, headers=headers)
    base = str(request.base_url).rstrip('/')
    return HTMLResponse(render_page(info, base, shell), headers=headers)


def missing_page(shell: str) -> str:
    """The app's ``index.html`` for a link that doesn't play."""

    tags = '<meta name="robots" content="noindex, nofollow">'
    return shell.replace('</head>', f'{tags}\n</head>', 1)


def meta_tags(info: dict[str, Any], base_url: str) -> str:
    """The share page's ``<head>`` additions: title, Open Graph tags for
    link previews, and no indexing. Every value is escaped."""

    esc = html.escape
    title = info['title']
    artist = info['artist']
    heading = f'{title} · {artist}' if artist else title
    byline = ' · '.join(p for p in (artist, info['album']) if p)
    audio = esc(base_url + info['audio_url'])
    tags = [
        '<meta name="robots" content="noindex, nofollow">',
        f'<title>{esc(heading)}</title>',
        '<meta property="og:type" content="music.song">',
        '<meta property="og:site_name" content="Castify">',
        f'<meta property="og:title" content="{esc(title)}">',
        f'<meta property="og:description" content="{esc(byline)}">',
        f'<meta property="og:audio" content="{audio}">',
        '<meta name="twitter:card" content="summary">',
    ]
    if info['has_cover']:
        cover = esc(base_url + info['cover_url'])
        tags.append(f'<meta property="og:image" content="{cover}">')
    return '\n'.join(tags)


def render_page(info: dict[str, Any], base_url: str, shell: str = '') -> str:
    """The web app's ``index.html`` (*shell*) with the song's tags in its
    ``<head>`` - the app then draws the share page itself. Without a
    built app (a development server), a bare page with a plain player."""

    tags = meta_tags(info, base_url)
    if shell and '</head>' in shell:
        shell = re.sub(r'<title>.*?</title>', '', shell, count=1, flags=re.S)
        return shell.replace('</head>', f'{tags}\n</head>', 1)
    esc = html.escape
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, '
        f'initial-scale=1">{tags}</head><body>'
        f'<h1>{esc(info["title"])}</h1><p>{esc(info["artist"])}</p>'
        f'<audio controls src="{esc(info["audio_url"])}"></audio>'
        '</body></html>'
    )
