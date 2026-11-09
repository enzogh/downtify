"""Public song links (see :mod:`downtify.song_links`).

Signed in (``/api/song-links``, a ``user`` scope):

* ``POST   /api/song-links`` - body ``{file}``: the caller's link to that
  library song, ``{token, path, file, created_at}`` (the same one when
  asked again). ``403`` while the admin's ``allow_song_links`` is off,
  ``404`` for a song the caller can't see.
* ``GET    /api/song-links`` - ``{enabled, links}``: the caller's links,
  newest first, each ``{token, path, file, title, artist, created_at,
  available}``.
* ``DELETE /api/song-links/{token}`` - revoke one (its maker, or an
  admin).

Public, no sign-in (outside the protected prefixes of
:mod:`downtify.auth`): ``GET /s/{token}`` (a page with the cover, title,
artist and a player, plus Open Graph tags for link previews), ``GET
/s/{token}/info`` (the same as JSON), ``GET|HEAD /s/{token}/audio`` (the
file, with Range) and ``GET /s/{token}/cover``. A link whose song is
gone, hidden from users by an admin, or switched off by
``allow_song_links`` answers ``404`` - the same as an unknown token, so a
link never tells more than the song it was made for.
"""

from __future__ import annotations

import asyncio
import html
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import api
from .cover_art import extract_cover_art
from .library_cache_keys import file_content_key
from .library_catalog import (
    entry_content_key,
    list_entries_for_stored_paths,
    resolve_library_file,
)
from .mobile_routes import audio_media_type
from .song_links import SongLink, SongLinks

router = APIRouter()

#: Shared pages are for whoever was sent the link, not search engines.
_PUBLIC_HEADERS = {
    'X-Robots-Tag': 'noindex, nofollow',
    'Referrer-Policy': 'no-referrer',
}


def links_enabled() -> bool:
    """Whether the admin lets users make public song links (Settings)."""

    return bool(api.state.settings.get('allow_song_links', True))


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


def _public_song(token: str) -> tuple[SongLink, dict[str, Any], Path]:
    """The link, its song's row and file - or ``404`` for anything that
    shouldn't play."""

    missing = HTTPException(status_code=404, detail='Link not found')
    if not links_enabled():
        raise missing
    link = _store().get(token)
    if link is None:
        raise missing
    full = _resolve(link.path)
    if full is None:
        raise missing
    entry = _entry(link.path)
    if entry is None or _hidden_from_users(entry):
        raise missing
    return link, entry, full


def _link_row(link: SongLink) -> dict[str, Any]:
    return {
        'token': link.token,
        'path': f'/s/{link.token}',
        'file': link.path,
        'created_at': link.created_at,
    }


# ── Signed in ───────────────────────────────────────────────────────────


@router.post('/api/song-links')
async def create_song_link(request: Request) -> dict[str, Any]:
    payload = await api._json_object(request)
    stored = str(payload.get('file') or '').strip().replace('\\', '/')
    if not stored:
        raise HTTPException(status_code=400, detail='No file given')
    if not links_enabled():
        raise HTTPException(
            status_code=403, detail='Public song links are turned off'
        )
    user_id = api.request_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail='Sign in first')

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

    def rows() -> list[dict[str, Any]]:
        found = []
        for link in _store().for_user(user_id):
            entry = _entry(link.path)
            found.append({
                **_link_row(link),
                'title': _title(entry) if entry else '',
                'artist': _artist(entry) if entry else '',
                'available': entry is not None
                and _resolve(link.path) is not None,
            })
        return found

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


def _info(link: SongLink, entry: dict[str, Any]) -> dict[str, Any]:
    duration = entry.get('duration')
    return {
        'title': _title(entry),
        'artist': _artist(entry),
        'album': str(entry.get('album') or ''),
        'duration': float(duration) if duration else 0,
        'explicit': bool(entry.get('explicit')),
        'has_cover': bool(entry.get('has_cover', True)),
        'audio_url': f'/s/{link.token}/audio',
        'cover_url': f'/s/{link.token}/cover',
    }


@router.get('/s/{token}/info')
async def song_link_info(token: str) -> JSONResponse:
    link, entry, _full = await asyncio.to_thread(_public_song, token)
    return JSONResponse(_info(link, entry), headers=_PUBLIC_HEADERS)


@router.api_route('/s/{token}/audio', methods=['GET', 'HEAD'])
async def song_link_audio(token: str) -> FileResponse:
    _link, _entry_row, full = await asyncio.to_thread(_public_song, token)
    return FileResponse(
        full,
        media_type=audio_media_type(full),
        headers={**_PUBLIC_HEADERS, 'Cache-Control': 'private, max-age=600'},
    )


@router.get('/s/{token}/cover')
async def song_link_cover(token: str) -> Response:
    _link, _entry_row, full = await asyncio.to_thread(_public_song, token)
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
    link, entry, _full = await asyncio.to_thread(_public_song, token)
    info = _info(link, entry)
    base = str(request.base_url).rstrip('/')
    page = render_page(info, base)
    return HTMLResponse(
        page,
        headers={**_PUBLIC_HEADERS, 'Cache-Control': 'no-store'},
    )


def render_page(info: dict[str, Any], base_url: str) -> str:
    """The shared song's page: its cover, title, artist and a player.

    Every value is escaped; ``base_url`` only makes the Open Graph image
    and audio absolute, as link previews need."""

    esc = html.escape
    title = info['title']
    artist = info['artist']
    album = info['album']
    heading = f'{title} · {artist}' if artist else title
    byline = ' · '.join(part for part in (artist, album) if part)
    cover = info['cover_url'] if info['has_cover'] else ''
    og_image = (
        f'<meta property="og:image" content="{esc(base_url + cover)}">'
        if cover
        else ''
    )
    art = (
        f'<img class="cover" src="{esc(cover)}" alt="">'
        if cover
        else '<div class="cover blank" aria-hidden="true">♪</div>'
    )
    explicit = (
        '<span class="explicit" title="Explicit">E</span>'
        if info['explicit']
        else ''
    )
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{esc(heading)}</title>
<meta property="og:type" content="music.song">
<meta property="og:site_name" content="Castify">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(byline)}">
{og_image}
<meta property="og:audio" content="{esc(base_url + info['audio_url'])}">
<meta name="twitter:card" content="summary">
<style>
:root {{ color-scheme: dark; }}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; min-height: 100dvh; display: flex; align-items: center;
  justify-content: center; padding: 24px 16px;
  font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
  background: radial-gradient(120% 80% at 50% 0%, #1f2a22 0%, #0b0c0e 60%);
  color: #f2f3f5;
}}
main {{ width: 100%; max-width: 380px; text-align: center; }}
.cover {{
  width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 16px;
  box-shadow: 0 24px 60px rgba(0,0,0,.5); background: #1b1d21;
}}
.blank {{
  display: flex; align-items: center; justify-content: center;
  font-size: 96px; color: #5c6066;
}}
h1 {{
  margin: 24px 0 4px; font-size: 24px; line-height: 1.2;
  overflow-wrap: anywhere;
}}
p {{ margin: 0; color: #a3a7ad; font-size: 15px; overflow-wrap: anywhere; }}
.explicit {{
  display: inline-block; margin-left: 8px; padding: 0 5px;
  border-radius: 4px; background: #a3a7ad; color: #0b0c0e;
  font-size: 11px; font-weight: 700; vertical-align: middle;
}}
audio {{ width: 100%; margin-top: 24px; }}
footer {{
  margin-top: 32px; font-size: 13px; color: #6d7177;
  display: flex; align-items: center; justify-content: center; gap: 8px;
}}
footer b {{ color: #57d16c; }}
</style>
</head>
<body>
<main>
{art}
<h1>{esc(title)}{explicit}</h1>
<p>{esc(byline)}</p>
<audio controls preload="metadata" src="{esc(info['audio_url'])}"></audio>
<footer><b>●</b> Castify</footer>
</main>
</body>
</html>
"""
