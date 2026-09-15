"""Default mode: serve continuously, render on a schedule."""

from __future__ import annotations

import datetime as dt
import threading

from . import pipeline, schedule, serve
from .config import Settings
from .log import log
from .proc import Terminated, shutdown


def run(settings: Settings) -> int:
    # Built before anything else so a bad RENDER_CRON fails at startup rather
    # than hours later.
    plan = schedule.build(settings)

    server = threading.Thread(
        target=serve.serve_forever, args=(settings,), name="serve", daemon=True
    )
    server.start()

    # A pass runs at startup whatever the schedule says: with a daily cron and
    # an empty /output, waiting until 4am would mean serving nothing all day.
    # An unchanged save makes it a cheap no-op anyway.
    log.info("render loop started, running %s", plan.description)
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

        if _wait(plan):
            break

    log.info("render loop stopped")
    return 0


def _wait(plan: schedule.Schedule) -> bool:
    """Sleep until the next run. True if we were told to shut down instead."""
    now = dt.datetime.now().astimezone()
    try:
        upcoming = plan.next_run(now)
    except Exception:
        log.exception("could not work out the next run time; stopping the loop")
        return True

    delay = max(0.0, (upcoming - now).total_seconds())
    log.info(
        "next check at %s (in %s)",
        upcoming.strftime("%Y-%m-%d %H:%M:%S %Z"),
        schedule.describe_delay(delay),
    )
    return shutdown.wait(delay)
