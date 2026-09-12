"""Logging setup. Everything goes to stderr so `docker logs` shows it in order."""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger("mapshot-cloud")


def setup() -> None:
    if log.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    log.addHandler(handler)
    log.setLevel(logging.DEBUG if os.environ.get("DEBUG") else logging.INFO)
    log.propagate = False


def banner(text: str) -> None:
    """A line that stands out in a wall of Factorio output."""
    log.info("=" * 8 + f" {text} " + "=" * 8)
