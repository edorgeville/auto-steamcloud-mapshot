"""Serving the published map at the HTTP root.

mapshot's own `serve` command presents a listing of every render it can find,
which earns its place when you keep many. We publish exactly one map, so that
listing is a click in the way: it offers a list of one, and a "versions" menu
holding a single entry.

mapshot's generated output is fully static and self-contained - its README
says as much - so we serve the current map directly instead. `/output/current`
is a symlink that publishing repoints, and everything the viewer asks for is
relative to it.
"""

from __future__ import annotations

import io
import threading
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .config import MAPSHOT_PREFIX, OUTPUT_CURRENT, OUTPUT_DIR, Settings
from .log import log
from .proc import shutdown

PLACEHOLDER = b"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Factorio map</title>
<style>
  body { font: 16px/1.6 system-ui, sans-serif; margin: 0; display: grid;
         place-items: center; min-height: 100vh; background: #1b1b1b; color: #ddd; }
  div { max-width: 32rem; padding: 2rem; }
  h1 { font-size: 1.25rem; margin: 0 0 .5rem; }
  p { margin: .5rem 0; color: #aaa; }
</style>
<div>
  <h1>No map yet</h1>
  <p>The first render has not finished. It downloads the Factorio client and
     can take a while; the container log reports progress.</p>
  <p>This page refreshes every 30 seconds.</p>
</div>
<script>setTimeout(() => location.reload(), 30000)</script>
"""


def _root() -> Path | None:
    """The directory to serve, or None when there is no map yet."""
    if OUTPUT_CURRENT.is_dir():
        return OUTPUT_CURRENT

    # No symlink: either nothing has been published, or this is an /output
    # written by a version that predates it. Adopt the map if there is
    # exactly one, so an upgrade never serves a placeholder over a render
    # that is sitting right there.
    published = OUTPUT_DIR / MAPSHOT_PREFIX.strip("/")
    if published.is_dir():
        maps = [p for p in published.iterdir() if p.is_dir() and not p.name.startswith(".")]
        if len(maps) == 1:
            return maps[0]
    return None


class _Handler(SimpleHTTPRequestHandler):
    server_version = "factorio-mapshot-cloud"

    def __init__(self, *args: object, **kwargs: object) -> None:
        # Resolved per request, so a publish is picked up without a restart.
        root = _root()
        self._served_root = root
        super().__init__(*args, directory=str(root or OUTPUT_DIR), **kwargs)  # type: ignore[arg-type]

    def send_head(self):
        if self._served_root is None:
            return self._nothing_yet()
        return super().send_head()

    def _nothing_yet(self) -> io.BytesIO | None:
        path = urlsplit(self.path).path
        if path not in ("/", "/index.html"):
            self.send_error(404, "no render published yet")
            return None
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PLACEHOLDER)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        return io.BytesIO(PLACEHOLDER)

    def log_message(self, format: str, *args: object) -> None:
        log.debug("http %s", format % args)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve_forever(settings: Settings) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    httpd = _Server(("", settings.serve_port), _Handler)
    threading.Thread(target=httpd.serve_forever, name="http", daemon=True).start()
    log.info("serving %s on port %d", OUTPUT_CURRENT, settings.serve_port)
    try:
        shutdown.wait()
    finally:
        httpd.shutdown()
        httpd.server_close()
        log.info("http server stopped")


def healthy(port: int, timeout: int = 5) -> bool:
    url = f"http://127.0.0.1:{port}/"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 400
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
