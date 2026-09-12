"""Default mode: serve continuously, render on an interval."""

from __future__ import annotations

import threading

from . import pipeline, serve
from .config import MIN_RENDER_INTERVAL, Settings
from .log import log
from .proc import Terminated, shutdown


def run(settings: Settings) -> int:
    interval, clamped = settings.effective_interval()
    if clamped:
        log.warning(
            "RENDER_INTERVAL=%ds is below the %ds floor and has been raised. "
            "Steam Cloud pulling is not sanctioned by Valve; polling harder "
            "than this risks the account.",
            settings.render_interval,
            MIN_RENDER_INTERVAL,
        )

    server = threading.Thread(
        target=serve.serve_forever, args=(settings,), name="serve", daemon=True
    )
    server.start()

    log.info("render loop started, checking every %ds", interval)
    while not shutdown.is_set():
        try:
            pipeline.run_once(settings)
        except Terminated:
            break
        except pipeline.PipelineError as exc:
            log.error("render failed: %s", exc)
            log.info("keeping the previous render online")
        except Exception:  # the loop must survive anything, or the site goes stale
            log.exception("render failed with an unexpected error")
            log.info("keeping the previous render online")

        if shutdown.wait(interval):
            break

    log.info("render loop stopped")
    return 0
