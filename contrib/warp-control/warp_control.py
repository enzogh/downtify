"""Tiny control endpoint for a Cloudflare WARP proxy container.

Runs inside the WARP container (e.g. ``caomingjun/warp``) next to
``warp-svc`` and answers one call: ``POST /rotate`` reconnects WARP,
which gives a new exit IP in a few seconds. Downtify calls it
(``DOWNTIFY_IP_ROTATE_URL``) when YouTube flags the current IP with
"Sign in to confirm you're not a bot".

Standard library only. ``WARP_CONTROL_TOKEN`` is required: requests must
send ``Authorization: Bearer <token>``. Listens on
``WARP_CONTROL_PORT`` (default 8081); keep it off the host's ports.
"""

from __future__ import annotations

import hmac
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get('WARP_CONTROL_TOKEN', '').strip()
PORT = int(os.environ.get('WARP_CONTROL_PORT', '8081'))
CONNECT_TIMEOUT_SECONDS = 30

_lock = threading.Lock()


def _warp(*args: str) -> str:
    done = subprocess.run(
        ['warp-cli', '--accept-tos', *args],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    return (done.stdout + done.stderr).strip()


def rotate() -> tuple[bool, str]:
    """Reconnect WARP; ``(connected, last status line)``."""

    with _lock:
        _warp('disconnect')
        _warp('connect')
        deadline = time.monotonic() + CONNECT_TIMEOUT_SECONDS
        status = ''
        while time.monotonic() < deadline:
            lines = _warp('status').splitlines()
            status = lines[0] if lines else ''
            if 'Connected' in status:
                # Give the SOCKS side a moment to use the new tunnel.
                time.sleep(1)
                return True, status
            time.sleep(0.5)
        return False, status


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code: int, body: dict[str, object]) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == '/health':
            self._reply(200, {'ok': True})
        else:
            self._reply(404, {'ok': False})

    def do_POST(self) -> None:
        if self.path != '/rotate':
            self._reply(404, {'ok': False})
            return
        sent = self.headers.get('Authorization', '')
        if not hmac.compare_digest(sent, f'Bearer {TOKEN}'):
            self._reply(401, {'ok': False})
            return
        ok, status = rotate()
        self._reply(200 if ok else 503, {'ok': ok, 'status': status})

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(
            f'[warp-control] {self.address_string()} {fmt % args}\n'
        )


def main() -> None:
    if not TOKEN:
        sys.exit('[warp-control] WARP_CONTROL_TOKEN is required')
    server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    sys.stderr.write(f'[warp-control] listening on :{PORT}\n')
    server.serve_forever()


if __name__ == '__main__':
    main()
