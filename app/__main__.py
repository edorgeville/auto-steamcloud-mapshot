"""Command dispatch for the container entrypoint."""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

from . import daemon, pipeline, serve
from .config import CONFIG_DIR, DATA_DIR, OUTPUT_DIR, ConfigError, Settings
from .log import log, setup
from .proc import Terminated, install_signal_handlers
from .puller import PullError, get_puller
from .releases import DownloadError

MODE_FILE = Path("/tmp/mapshot-cloud-mode")  # noqa: S108 - container-local marker
SERVING_MODES = {"serve", "daemon"}

USAGE = """\
usage: <command>

  login-steam   one-time interactive Steam login; writes the session to /config
  render        pull, check, render once, exit
  serve         serve /output over HTTP, no rendering
  (no command)  serve and render on an interval
"""


def main(argv: list[str]) -> int:
    setup()
    install_signal_handlers()

    command = argv[0] if argv else "daemon"
    if command in ("-h", "--help", "help"):
        print(USAGE, end="")
        return 0

    if command == "healthcheck":
        return _healthcheck()

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        log.error("%s", exc)
        return 2

    _record_mode(command)

    try:
        if command == "login-steam":
            return _login(settings)
        if command == "render":
            return _render(settings)
        if command == "serve":
            serve.serve_forever(settings)
            return 0
        if command == "daemon":
            _prepare_dirs()
            return daemon.run(settings)
    except Terminated:
        return 0
    except (ConfigError, DownloadError, PullError, pipeline.PipelineError) as exc:
        log.error("%s", exc)
        return 1

    log.error("unknown command %r", command)
    print(USAGE, end="", file=sys.stderr)
    return 2


def _prepare_dirs() -> None:
    for path in (CONFIG_DIR, DATA_DIR, OUTPUT_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _login(settings: Settings) -> int:
    if not settings.steam_username:
        log.error("STEAM_USERNAME must be set for the login-steam command")
        return 2
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return get_puller().login(settings.steam_username)


def _render(settings: Settings) -> int:
    _prepare_dirs()
    pipeline.run_once(settings)
    return 0


def _record_mode(command: str) -> None:
    with contextlib.suppress(OSError):
        MODE_FILE.write_text(command)


def _healthcheck() -> int:
    """Only meaningful in the serving modes; a no-op elsewhere."""
    try:
        mode = MODE_FILE.read_text().strip()
    except OSError:
        mode = "daemon"
    if mode not in SERVING_MODES:
        return 0
    try:
        port = Settings.from_env().serve_port
    except ConfigError:
        return 1
    return 0 if serve.healthy(port) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
