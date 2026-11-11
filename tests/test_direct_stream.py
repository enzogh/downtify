"""Audio redirected to a hostname that skips the CDN
(downtify/direct_stream.py), signed for the session or device that asked."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from downtify.auth import SESSION_COOKIE, AuthMiddleware, AuthStore
from downtify.direct_stream import (
    DirectStreamConfig,
    DirectStreamMiddleware,
)

DIRECT = 'https://direct.example.com'
PUBLIC_HOST = 'https://music.example.com'


def _store(tmp_path: Path) -> AuthStore:
    store = AuthStore(tmp_path / 'auth.db', tmp_path / '.secret')
    return store


def _who(request: Request) -> JSONResponse:
    principal = request.scope['state']['principal']
    return JSONResponse({
        'kind': principal.kind,
        'user_id': principal.user_id,
        'device_id': principal.device_id,
        'path': request.url.path,
    })


def _app(store: AuthStore, config: Any) -> Starlette:
    return Starlette(
        routes=[
            Route('/downloads/{name:path}', _who),
            Route('/api/v1/tracks/{track}/stream', _who),
            Route('/tracks', _who),
        ],
        middleware=[
            Middleware(
                AuthMiddleware,
                get_store=lambda: store,
                get_tickets=lambda: None,
                trusted_proxies=[],
            ),
            Middleware(
                DirectStreamMiddleware,
                get_config=lambda: config,
                get_store=lambda: store,
            ),
        ],
    )


@pytest.fixture
def setup(tmp_path):
    store = _store(tmp_path)
    admin = store.users.first_admin()
    token = store.create_session(admin['id'])
    app = _app(store, DirectStreamConfig.parse(DIRECT))
    return store, admin, token, app


def _follow(app: Any, location: str, **kw: Any) -> Any:
    parts = urlsplit(location)
    client = TestClient(app, base_url=f'{parts.scheme}://{parts.netloc}')
    return client.get(f'{parts.path}?{parts.query}', **kw)


def test_a_browser_is_sent_to_the_direct_host_with_a_signed_url(setup):
    store, admin, token, app = setup
    client = TestClient(app, base_url=PUBLIC_HOST)
    client.cookies.set(SESSION_COOKIE, token)

    response = client.get(
        '/downloads/Some%20Artist/Song.mp3',
        headers={'range': 'bytes=0-'},
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers['cache-control'] == 'no-store'
    location = response.headers['location']
    assert location.startswith(f'{DIRECT}/downloads/Some%20Artist/Song.mp3?')
    assert 'sig=' in location
    assert token not in location
    # The direct host takes it without the cookie.
    served = _follow(app, location)
    assert served.status_code == 200
    assert served.json() == {
        'kind': 'signed',
        'user_id': admin['id'],
        'device_id': '',
        'path': '/downloads/Some Artist/Song.mp3',
    }


def test_signing_out_voids_the_session_s_urls(setup):
    store, _admin, token, app = setup
    client = TestClient(app, base_url=PUBLIC_HOST)
    client.cookies.set(SESSION_COOKIE, token)
    location = client.get('/downloads/a.mp3', follow_redirects=False).headers[
        'location'
    ]

    store.end_session(token)

    assert _follow(app, location).status_code == 401


def test_an_app_s_query_is_kept_and_signed_for_its_device(setup):
    store, admin, _token, app = setup
    device, device_token = store.create_device('Phone', user_id=admin['id'])
    client = TestClient(app, base_url=PUBLIC_HOST)

    response = client.get(
        '/api/v1/tracks/t1/stream?format=opus&bitrate=160',
        headers={'authorization': f'Bearer {device_token}'},
        follow_redirects=False,
    )

    location = response.headers['location']
    assert response.status_code == 307
    assert 'format=opus' in location
    assert 'bitrate=160' in location
    assert f'kid={device["id"]}' in location
    assert _follow(app, location).json()['device_id'] == device['id']
    # Tampering with the query breaks the signature.
    assert (
        _follow(
            app, location.replace('bitrate=160', 'bitrate=320')
        ).status_code
        == 401
    )


def test_an_already_signed_url_is_passed_on_as_it_is(setup):
    store, admin, _token, app = setup
    device, _device_token = store.create_device('Cast', user_id=admin['id'])
    signed = store.signer.sign_url('/downloads/a.mp3', device_id=device['id'])
    client = TestClient(app, base_url=PUBLIC_HOST)

    response = client.get(signed, follow_redirects=False)

    assert response.headers['location'] == DIRECT + signed


@pytest.mark.parametrize(
    ('base_url', 'path', 'headers'),
    [
        # Already there, or a LAN / local client.
        (DIRECT, '/downloads/a.mp3', {}),
        ('http://192.168.1.10:8095', '/downloads/a.mp3', {}),
        ('http://localhost:8000', '/downloads/a.mp3', {}),
        ('http://[::1]:8000', '/downloads/a.mp3', {}),
        # Not audio.
        (PUBLIC_HOST, '/tracks', {}),
        # A "Download" link opened as a page.
        (PUBLIC_HOST, '/downloads/a.mp3', {'sec-fetch-mode': 'navigate'}),
    ],
)
def test_requests_served_where_they_are(setup, base_url, path, headers):
    _store_, _admin, token, app = setup
    client = TestClient(app, base_url=base_url)
    client.cookies.set(SESSION_COOKIE, token)

    response = client.get(path, headers=headers, follow_redirects=False)

    assert response.status_code == 200
    assert response.json()['kind'] == 'session'


def test_nothing_changes_without_a_direct_host(tmp_path):
    store = _store(tmp_path)
    token = store.create_session(store.users.first_admin()['id'])
    client = TestClient(_app(store, None), base_url=PUBLIC_HOST)
    client.cookies.set(SESSION_COOKIE, token)

    response = client.get('/downloads/a.mp3', follow_redirects=False)

    assert response.status_code == 200


def test_signing_in_is_still_needed(setup):
    _store_, _admin, _token, app = setup
    client = TestClient(app, base_url=PUBLIC_HOST)

    response = client.get('/downloads/a.mp3', follow_redirects=False)

    assert response.status_code == 401


def test_a_url_is_stable_within_the_hour(setup):
    _store_, _admin, token, app = setup
    client = TestClient(app, base_url=PUBLIC_HOST)
    client.cookies.set(SESSION_COOKIE, token)

    first = client.get('/downloads/a.mp3', follow_redirects=False)
    second = client.get('/downloads/a.mp3', follow_redirects=False)

    assert first.headers['location'] == second.headers['location']


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        ('https://Direct.Example.com/', ('https://direct.example.com',)),
        ('http://10.0.0.2:8095', ('http://10.0.0.2:8095',)),
        ('', None),
        ('direct.example.com', None),
        ('https://direct.example.com/audio', None),
        ('ftp://direct.example.com', None),
    ],
)
def test_config_parsing(raw, expected):
    config = DirectStreamConfig.parse(raw)
    if expected is None:
        assert config is None
    else:
        assert config.base_url == expected[0]
