"""Public links to one song (``downtify/song_links.py`` and
``downtify/song_link_routes.py``). Offline.

A signed-in user makes a link to a library song; anyone with the link
plays it at ``/s/<token>`` without signing in, and nothing else. The
admin's ``allow_song_links`` switch, a deleted file or a song hidden from
users all make the link a plain 404.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from downtify import api, song_link_routes
from downtify.auth import CLIENT, PUBLIC, Principal, classify
from downtify.library_catalog import LibraryContext
from downtify.library_visibility import HiddenRules
from downtify.song_links import SongLinks, valid_token

ADMIN_ID = 1
ANA = 2
BO = 3


def _request(user_id: int, role: str = 'user', body: Any = None) -> Request:
    scope: dict[str, Any] = {
        'type': 'http',
        'headers': [],
        'query_string': b'',
        'state': {
            'principal': Principal(
                'device', 'client', '', user_id, f'u{user_id}', role
            )
        },
    }
    raw = json.dumps(body).encode() if body is not None else b''

    async def receive() -> dict[str, Any]:
        return {'type': 'http.request', 'body': raw, 'more_body': False}

    return Request(scope, receive)


class _Hides(HiddenRules):
    def __init__(self, files: set[str]) -> None:
        super().__init__()
        self._files = files

    def hides(self, entry: dict[str, Any]) -> bool:
        return entry.get('file') in self._files


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = tmp_path / 'downloads'
    root.mkdir()
    (root / 'Air - Sexy Boy.mp3').write_bytes(b'\xff\xfb' + b'\x00' * 400)
    (root / 'Orbital - Halcyon.mp3').write_bytes(b'\xff\xfb' + b'\x00' * 900)
    ctx = LibraryContext(download_dir=root)
    entries = {
        'Air - Sexy Boy.mp3': {
            'file': 'Air - Sexy Boy.mp3',
            'size': 402,
            'title': 'Sexy Boy',
            'artist': 'Air',
            'artists': ['Air'],
            'album': 'Moon Safari',
            'duration': 298.0,
            'has_cover': False,
        },
        'Orbital - Halcyon.mp3': {
            'file': 'Orbital - Halcyon.mp3',
            'size': 902,
            'title': 'Halcyon <On & On>',
            'artist': 'Orbital',
            'album': 'Orbital 2',
            'duration': 567.0,
            'has_cover': False,
        },
    }
    hidden: set[str] = set()
    store = SongLinks(tmp_path / 'lib.db')
    monkeypatch.setattr(api, 'library_context', lambda: ctx)
    monkeypatch.setattr(api.state, 'song_links', store)
    monkeypatch.setitem(api.state.settings, 'allow_song_links', True)
    monkeypatch.setattr(song_link_routes, '_entry', entries.get)
    monkeypatch.setattr(api, 'hidden_rules', lambda: _Hides(hidden))
    monkeypatch.setattr(
        api,
        'allowed_entry_keys',
        lambda request: (
            None
            if api.request_is_admin(request) or not hidden
            else {
                api.entry_content_key(e)
                for f, e in entries.items()
                if f not in hidden
            }
        ),
    )
    return type('World', (), {'root': root, 'store': store, 'hidden': hidden})


def _create(user_id: int, file: str, role: str = 'user') -> dict[str, Any]:
    return asyncio.run(
        song_link_routes.create_song_link(
            _request(user_id, role, {'file': file})
        )
    )


# ── The store ───────────────────────────────────────────────────────────


def test_store_gives_one_link_per_user_and_song(tmp_path):
    store = SongLinks(tmp_path / 'lib.db')
    first = store.create('a/b.mp3', 'key-1', ANA)
    assert store.create('a/b.mp3', 'key-1', ANA).token == first.token
    assert store.create('a/b.mp3', 'key-1', BO).token != first.token
    assert valid_token(first.token)
    assert store.get(first.token).path == 'a/b.mp3'
    assert [link.token for link in store.for_user(ANA)] == [first.token]


def test_store_follows_and_forgets_a_file(tmp_path):
    store = SongLinks(tmp_path / 'lib.db')
    link = store.create('old.mp3', 'key-1', ANA)
    assert store.rekey('key-1', 'key-2', 'new.mp3') == 1
    moved = store.get(link.token)
    assert (moved.path, moved.content_key) == ('new.mp3', 'key-2')
    assert store.drop('key-2') == 1
    assert store.get(link.token) is None


def test_store_revokes_and_rejects_malformed_tokens(tmp_path):
    store = SongLinks(tmp_path / 'lib.db')
    link = store.create('a.mp3', 'k', ANA)
    assert store.get('../etc') is None
    assert store.revoke('x') is False
    assert store.revoke(link.token) is True
    assert store.get(link.token) is None


# ── Signed in ───────────────────────────────────────────────────────────


def test_create_returns_the_same_link_twice(world):
    made = _create(ANA, 'Air - Sexy Boy.mp3')
    assert made['path'] == f'/s/{made["token"]}'
    assert made['file'] == 'Air - Sexy Boy.mp3'
    assert _create(ANA, 'Air - Sexy Boy.mp3')['token'] == made['token']


@pytest.mark.parametrize(
    'file', ['missing.mp3', '../outside.mp3', '/etc/passwd', '']
)
def test_create_refuses_what_is_not_a_library_song(world, file):
    with pytest.raises(HTTPException) as err:
        _create(ANA, file)
    assert err.value.status_code in {400, 404}


def test_create_refuses_while_switched_off(world, monkeypatch):
    monkeypatch.setitem(api.state.settings, 'allow_song_links', False)
    with pytest.raises(HTTPException) as err:
        _create(ANA, 'Air - Sexy Boy.mp3')
    assert err.value.status_code == 403


def test_a_user_cannot_share_a_song_hidden_from_them(world):
    world.hidden.add('Air - Sexy Boy.mp3')
    with pytest.raises(HTTPException) as err:
        _create(ANA, 'Air - Sexy Boy.mp3')
    assert err.value.status_code == 404
    assert _create(ADMIN_ID, 'Air - Sexy Boy.mp3', 'admin')['token']


def test_list_shows_only_my_links(world):
    mine = _create(ANA, 'Air - Sexy Boy.mp3')
    _create(BO, 'Orbital - Halcyon.mp3')
    found = asyncio.run(song_link_routes.list_song_links(_request(ANA)))
    assert found['enabled'] is True
    assert [row['token'] for row in found['links']] == [mine['token']]
    assert found['links'][0]['title'] == 'Sexy Boy'
    assert found['links'][0]['available'] is True


def test_only_the_maker_or_an_admin_revokes(world):
    token = _create(ANA, 'Air - Sexy Boy.mp3')['token']
    with pytest.raises(HTTPException) as err:
        asyncio.run(song_link_routes.revoke_song_link(token, _request(BO)))
    assert err.value.status_code == 403
    asyncio.run(
        song_link_routes.revoke_song_link(token, _request(ADMIN_ID, 'admin'))
    )
    assert world.store.get(token) is None


# ── Public ──────────────────────────────────────────────────────────────


def test_public_song_plays_without_signing_in(world):
    token = _create(ANA, 'Air - Sexy Boy.mp3')['token']
    _link, entry, full = song_link_routes._public_song(token)
    assert entry['title'] == 'Sexy Boy'
    assert full == world.root / 'Air - Sexy Boy.mp3'
    audio = asyncio.run(song_link_routes.song_link_audio(token))
    assert Path(audio.path) == full
    assert audio.headers['x-robots-tag'].startswith('noindex')


def test_public_info_says_only_what_the_page_shows(world):
    token = _create(ANA, 'Air - Sexy Boy.mp3')['token']
    info = json.loads(asyncio.run(song_link_routes.song_link_info(token)).body)
    assert info == {
        'title': 'Sexy Boy',
        'artist': 'Air',
        'album': 'Moon Safari',
        'duration': 298.0,
        'explicit': False,
        'has_cover': False,
        'audio_url': f'/s/{token}/audio',
        'cover_url': f'/s/{token}/cover',
    }


@pytest.mark.parametrize('why', ['off', 'hidden', 'deleted', 'unknown'])
def test_a_link_that_should_not_play_is_a_404(world, monkeypatch, why):
    token = _create(ANA, 'Air - Sexy Boy.mp3')['token']
    if why == 'off':
        monkeypatch.setitem(api.state.settings, 'allow_song_links', False)
    elif why == 'hidden':
        world.hidden.add('Air - Sexy Boy.mp3')
    elif why == 'deleted':
        (world.root / 'Air - Sexy Boy.mp3').unlink()
    else:
        token = 'NoSuchToken123'
    with pytest.raises(HTTPException) as err:
        song_link_routes._public_song(token)
    assert err.value.status_code == 404


def test_page_escapes_the_tags():
    page = song_link_routes.render_page(
        {
            'title': '<script>alert(1)</script>',
            'artist': 'A & B',
            'album': '"quoted"',
            'explicit': True,
            'has_cover': True,
            'audio_url': '/s/tok/audio',
            'cover_url': '/s/tok/cover',
        },
        'https://music.example',
    )
    assert '<script>alert' not in page
    assert '&lt;script&gt;' in page
    assert 'A &amp; B' in page
    assert 'content="https://music.example/s/tok/cover"' in page
    assert 'noindex' in page


def test_routes_are_classified():
    assert classify('GET', '/s/AbCdEf123456') == PUBLIC
    assert classify('GET', '/s/AbCdEf123456/audio') == PUBLIC
    assert classify('POST', '/api/song-links') == CLIENT
    assert classify('GET', '/api/song-links') == CLIENT
    assert classify('DELETE', '/api/song-links/AbCdEf123456') == CLIENT
