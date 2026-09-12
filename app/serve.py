"""Serving /output over HTTP with mapshot's built-in server.

`mapshot serve` only needs the script-output directory, not a Factorio install,
so serving keeps working even when no render has ever succeeded.
"""

from __future__ import annotations

import urllib.error
import urllib.request

from .config import MAPSHOT_BIN, OUTPUT_DIR, Settings
from .log import log
from .proc import Terminated, run, shutdown

RESTART_DELAY = 5


def serve_forever(settings: Settings) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        MAPSHOT_BIN,
        "serve",
        "--factorio_scriptoutput",
        OUTPUT_DIR,
        "--port",
        str(settings.serve_port),
        "--logtostderr",
    ]
    log.info("serving %s on port %d", OUTPUT_DIR, settings.serve_port)
    while not shutdown.is_set():
        try:
            result = run(cmd)
        except Terminated:
            return
        if shutdown.is_set():
            return
        log.error(
            "mapshot serve exited with %d; restarting in %ds",
            result.returncode,
            RESTART_DELAY,
        )
        shutdown.wait(RESTART_DELAY)


def healthy(port: int, timeout: int = 5) -> bool:
    url = f"http://127.0.0.1:{port}/"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 400
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
